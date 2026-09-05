"""Pull one run's own figures out of the application.

Serves the APP column of DoD rows **E5** and **E1** (call counts, tokens, cost),
the app half of **B4** (durations from frame timestamps), and it produces the
`response_ids` list that `pull_openrouter.py` consumes.

It reads two surfaces and derives from both, because neither alone is enough:

* `GET /api/runs/{run_id}` - the snapshot: status, `usage`, `node_usage`,
  frame counters, timestamps. This is the app's OWN aggregate, and it is kept
  verbatim so a verifier can see the app disagreeing with itself if it does.
* `GET /api/runs/{run_id}/logs?format=ndjson` - every frame. The snapshot has
  no per-agent or per-task breakdown and no generation ids at all
  (`audit/app-surface.md` §3.5: *"a frame carries `response_id` but no surface
  aggregates it"*), so per-agent, per-task and the id list can only come from
  the frames.

Where the two disagree, `app-figures.json` reports both: `totals` is derived
from the TOKEN frames, `snapshot_usage` is what the app says, and
`totals_vs_snapshot` names every differing field. A reconciliation that hid an
app-versus-app difference could not be trusted about an app-versus-Langfuse one.

Usage:

    .venv/Scripts/python.exe scripts/observability/pull_app_run.py \
        --base http://127.0.0.1:8099 --run-id <run id> --out DIR
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    Http,
    HttpError,
    add_call,
    bucket_for,
    bucket_table,
    duration_seconds,
    ensure_dir,
    load_env,
    md_table,
    new_bucket,
    now_iso,
    parse_ts,
    read_json,
    secs,
    sum_buckets,
    usd,
    write_json,
    write_text,
)

# The frame `details` keys this script reads, all confirmed against
# `src/brief_crew/events/serializer.py` at 2026-09-05:
#   kind "llm",   details.stage == "after"  -> call_id, model, finish_reason,
#                                              response_id (None on the
#                                              synthetic double, runner.py:856)
#   kind "token", details                   -> call_id, model, cost_usd,
#                                              usage{prompt_tokens,
#                                              completion_tokens, total_tokens,
#                                              cost_usd, call_count}
#   every non-workflow frame                -> agent_role, task_name, agent_id,
#                                              task_id, run_attempts, stamped by
#                                              FieldBoundedSerializer.drafts
#   kind "tool",  details.stage in before/after/error -> tool, query,
#                                              tool_status, result_count
LLM_KIND = "llm"
TOKEN_KIND = "token"
TOOL_KIND = "tool"
AGENT_KIND = "agent"
NODE_KIND = "node_state"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Save an app run's snapshot and frames, and derive its figures.",
    )
    parser.add_argument(
        "--base",
        default="http://127.0.0.1:8099",
        help="base URL of the running backend (default the free synthetic port)",
    )
    parser.add_argument("--run-id", required=True, help="the app run id")
    parser.add_argument("--out", required=True, help="directory to write into")
    parser.add_argument(
        "--token",
        default=None,
        help=(
            "bearer token, when the backend has AUTH_BASE_URL set. Prefer "
            "OBS_APP_TOKEN in the environment; this flag lands in shell history."
        ),
    )
    parser.add_argument(
        "--synthetic-user",
        default=None,
        help=(
            "value for the X-Synthetic-User header - how a cookieless client "
            "authenticates against a SYNTHETIC=1 backend (the E2E harness "
            "sends e2e-user). Only honoured by a synthetic backend."
        ),
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="HTTP timeout in seconds"
    )
    parser.add_argument(
        "--from-files",
        default=None,
        help=(
            "a directory holding an already-saved app-run.json and "
            "app-frames.ndjson (frames.ndjson is accepted too). Derives the "
            "figures from those with NO network, which is the only way to "
            "reconcile a run whose backend is gone."
        ),
    )
    parser.add_argument(
        "--snapshot-file",
        default=None,
        help="an app-run.json to read instead of GET /api/runs/{id}",
    )
    parser.add_argument(
        "--frames-file",
        default=None,
        help="an NDJSON frame log to read instead of GET /api/runs/{id}/logs",
    )
    return parser.parse_args(argv)


def offline_sources(args: argparse.Namespace) -> tuple[Path | None, Path | None]:
    """The snapshot and frame files to read instead of the backend, if any.

    `--from-files DIR` is the common case and names both; the two explicit
    flags exist because a directory written by hand does not always use the
    names this script writes (`evidence/smoke-live/` holds BOTH `frames.ndjson`
    and `app-frames.ndjson`, and they are the same bytes).
    """

    snapshot = Path(args.snapshot_file) if args.snapshot_file else None
    frames = Path(args.frames_file) if args.frames_file else None
    if args.from_files:
        directory = Path(args.from_files)
        if snapshot is None:
            snapshot = directory / "app-run.json"
        if frames is None:
            for name in ("app-frames.ndjson", "frames.ndjson"):
                candidate = directory / name
                if candidate.is_file():
                    frames = candidate
                    break
    return snapshot, frames


def build_headers(args: argparse.Namespace) -> dict[str, str]:
    import os

    headers: dict[str, str] = {}
    token = args.token or os.environ.get("OBS_APP_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    user = args.synthetic_user or os.environ.get("OBS_SYNTHETIC_USER", "").strip()
    if user:
        headers["X-Synthetic-User"] = user
    return headers


# --- frame reading ----------------------------------------------------------


def iter_frames(ndjson: str) -> Iterable[dict[str, Any]]:
    """Yield the `data` object of each NDJSON line.

    The log endpoint writes `{"type":"frame","data":{...}}` per line
    (`service/app.py::download_logs`); a line that is not that shape is skipped
    rather than fatal, so a truncated download still yields what it has.
    """

    for line in ndjson.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            continue
        data = envelope.get("data") if isinstance(envelope, dict) else None
        if isinstance(data, dict):
            yield data


def details_of(frame: Mapping[str, Any]) -> dict[str, Any]:
    details = frame.get("details")
    return dict(details) if isinstance(details, Mapping) else {}


def usage_of(details: Mapping[str, Any]) -> dict[str, Any]:
    usage = details.get("usage")
    return dict(usage) if isinstance(usage, Mapping) else {}


def cost_of(details: Mapping[str, Any]) -> float | None:
    """The call's cost, or None for "no price on file".

    `None` is NOT zero, and the app says so in `config.compute_cost_usd`. The
    serializer writes the figure in two places - `details.cost_usd` and
    `details.usage.cost_usd` - deliberately (CLAUDE.md section 8); either is
    authoritative and the top level is read first.
    """

    for candidate in (details.get("cost_usd"), usage_of(details).get("cost_usd")):
        if candidate is None:
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    return None


# --- span extraction --------------------------------------------------------


def span_key(frame: Mapping[str, Any]) -> tuple[str, ...] | None:
    """The pairing key for a before/after frame pair, or None if unpairable.

    The discriminator that is not obvious: `FrameKind.AGENT` carries THREE
    different spans - an agent execution, a task, and a crew kickoff - and they
    are told apart by the `details` keys the serializer writes, not by the
    message. `AgentExecutionStartedEvent` is the only one of the three that puts
    a `task` key on the frame, so that key separates the agent span from the
    other two.

    Task and crew deliberately share one key. `CrewKickoffCompletedEvent` is the
    only frame of the three carrying `total_tokens`, and keying on it would
    make a crew's `before` and `after` frames hash differently - the pair would
    never close and every crew would be reported as an unclosed span, which is
    the D3 signal and would be a lie. They are grouped on the task name when
    there is one and on the message's subject when there is not, which is the
    crew name; both frames of a pair produce the same string either way.
    """

    kind = str(frame.get("kind") or "")
    details = details_of(frame)
    node = str(frame.get("node_id") or "")
    if kind == NODE_KIND:
        return ("node", node)
    if kind == AGENT_KIND:
        if "task" in details:
            return ("agent", node, str(details.get("agent_role") or _subject(frame)))
        return ("task", node, str(details.get("task_name") or _subject(frame)))
    if kind == TOOL_KIND:
        return ("tool", node, str(details.get("tool") or _subject(frame)))
    if kind == LLM_KIND:
        return ("llm", node, str(details.get("call_id") or _subject(frame)))
    return None


def _subject(frame: Mapping[str, Any]) -> str:
    """The leading noun of a frame message - "Market analyst started" -> role.

    A fallback only: every frame this is used on carries the identity in
    `details` on the paid path. The synthetic double carries it too since
    2026-09-05. It exists so a frame from a future producer that forgets the
    stamp still lands in a named row rather than in "(none)".
    """

    message = str(frame.get("message") or "").strip()
    # Longest first: "x call started" also ends with " started", and stripping
    # the short one would leave "x call" while its partner became "x".
    for tail in (
        " call started",
        " call completed",
        " call failed",
        " started",
        " completed",
        " failed",
    ):
        if message.endswith(tail):
            return message[: -len(tail)].strip()
    return message


def extract_spans(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair before/after frames into spans, in sequence order.

    A stack per key, so a node that runs twice (a revise loop) yields two spans
    rather than one long one - the lap count is the thing the console had to
    reconstruct from `nodeVisits` and it must not be flattened here either.
    An unclosed span is emitted with `end_ts: null` and `open: true`; that is
    the app-side counterpart of D3's open-observation check.
    """

    open_spans: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    spans: list[dict[str, Any]] = []
    for frame in frames:
        key = span_key(frame)
        if key is None:
            continue
        details = details_of(frame)
        stage = str(details.get("stage") or "")
        if stage == "before":
            open_spans.setdefault(key, []).append(
                {
                    "kind": key[0],
                    "label": key[-1],
                    "node_id": frame.get("node_id"),
                    "agent_role": details.get("agent_role"),
                    "task_name": details.get("task_name"),
                    "tool": details.get("tool"),
                    "start_seq": frame.get("seq"),
                    "start_ts": frame.get("ts"),
                    "end_seq": None,
                    "end_ts": None,
                    "duration_seconds": None,
                    "duration_ms_reported": None,
                    "level": frame.get("level"),
                    "open": True,
                }
            )
            continue
        if stage not in {"after", "error"}:
            continue
        stack = open_spans.get(key) or []
        if not stack:
            continue
        span = stack.pop()
        span["end_seq"] = frame.get("seq")
        span["end_ts"] = frame.get("ts")
        span["duration_seconds"] = duration_seconds(span["start_ts"], frame.get("ts"))
        span["duration_ms_reported"] = frame.get("duration_ms")
        span["level"] = frame.get("level")
        span["open"] = False
        if stage == "error":
            span["errored"] = True
        spans.append(span)
    for stack in open_spans.values():
        spans.extend(stack)
    spans.sort(key=lambda s: (s.get("start_seq") or 0))
    return spans


def duration_rows(spans: list[dict[str, Any]], kind: str, label_key: str) -> list[dict[str, Any]]:
    """Total, count and max seconds per label, slowest first - B4's ranking."""

    rolled: dict[str, dict[str, Any]] = {}
    for span in spans:
        if span.get("kind") != kind:
            continue
        label = str(span.get(label_key) or span.get("label") or "(none)")
        row = rolled.setdefault(
            label,
            {"label": label, "spans": 0, "total_seconds": 0.0, "max_seconds": 0.0, "open": 0},
        )
        row["spans"] += 1
        if span.get("open"):
            row["open"] += 1
        seconds = span.get("duration_seconds")
        if seconds is None:
            continue
        row["total_seconds"] += float(seconds)
        row["max_seconds"] = max(row["max_seconds"], float(seconds))
    return sorted(rolled.values(), key=lambda r: r["total_seconds"], reverse=True)


# --- figures ----------------------------------------------------------------


def derive_figures(
    snapshot: Mapping[str, Any], frames: list[dict[str, Any]], base: str, run_id: str
) -> dict[str, Any]:
    by_node: dict[str, dict[str, Any]] = {}
    by_agent: dict[str, dict[str, Any]] = {}
    by_task: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    calls: list[dict[str, Any]] = []

    # `after` LLM frames carry the response id; TOKEN frames carry the usage.
    # They are joined on `call_id`, which both carry, rather than assumed to be
    # adjacent - the adapter coalesces stream chunks and a retry re-emits.
    after_by_call: dict[str, dict[str, Any]] = {}
    failed_calls: list[dict[str, Any]] = []
    for frame in frames:
        kind = str(frame.get("kind") or "")
        details = details_of(frame)
        if kind != LLM_KIND:
            continue
        stage = str(details.get("stage") or "")
        call_id = str(details.get("call_id") or "")
        if stage == "after" and call_id:
            after_by_call[call_id] = {"frame": frame, "details": details}
        elif stage == "error":
            failed_calls.append(
                {
                    "call_id": call_id or None,
                    "model": details.get("model"),
                    "node_id": frame.get("node_id"),
                    "agent_role": details.get("agent_role"),
                    "task_name": details.get("task_name"),
                    "ts": frame.get("ts"),
                    "error": details.get("error"),
                }
            )

    for frame in frames:
        if str(frame.get("kind") or "") != TOKEN_KIND:
            continue
        details = details_of(frame)
        usage = usage_of(details)
        call_id = str(details.get("call_id") or "")
        after = after_by_call.get(call_id, {})
        after_details = after.get("details", {}) if isinstance(after, dict) else {}
        node_id = str(frame.get("node_id") or "")
        agent_role = str(
            details.get("agent_role") or after_details.get("agent_role") or ""
        )
        task_name = str(details.get("task_name") or after_details.get("task_name") or "")
        model = str(details.get("model") or after_details.get("model") or "")
        cost = cost_of(details)
        record = {
            "call_id": call_id or None,
            "response_id": after_details.get("response_id"),
            "model": model,
            "node_id": node_id,
            "agent_role": agent_role or None,
            "task_name": task_name or None,
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(
                usage.get("total_tokens")
                or (int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0))
            ),
            "cost_usd": cost,
            "ts": frame.get("ts"),
            "seq": frame.get("seq"),
        }
        calls.append(record)
        for mapping, key in (
            (by_node, node_id),
            (by_agent, agent_role),
            (by_task, task_name),
            (by_model, model),
        ):
            add_call(
                bucket_for(mapping, key),
                input_tokens=record["input_tokens"],
                output_tokens=record["output_tokens"],
                total_tokens=record["total_tokens"],
                cost_usd=record["cost_usd"],
            )

    totals = sum_buckets(by_node)
    spans = extract_spans(frames)
    snapshot_usage = dict(snapshot.get("usage") or {})

    # The app's own aggregate versus the frames it was built from. `_record_usage`
    # drives both, so a difference here is a real defect and not a rounding
    # artefact - which is why it is reported field by field rather than as a
    # boolean.
    comparison = []
    for derived_key, snapshot_key in (
        ("calls", "call_count"),
        ("input_tokens", "prompt_tokens"),
        ("output_tokens", "completion_tokens"),
        ("total_tokens", "total_tokens"),
        ("cost_usd", "cost_usd"),
    ):
        derived_value = totals.get(derived_key)
        snapshot_value = snapshot_usage.get(snapshot_key)
        try:
            equal = abs(float(derived_value or 0) - float(snapshot_value or 0)) < 1e-9
        except (TypeError, ValueError):
            equal = derived_value == snapshot_value
        comparison.append(
            {
                "metric": derived_key,
                "from_frames": derived_value,
                "from_snapshot": snapshot_value,
                "agree": equal,
            }
        )

    tool_calls = [
        {
            "tool": details_of(f).get("tool"),
            "node_id": f.get("node_id"),
            "agent_role": details_of(f).get("agent_role"),
            "stage": details_of(f).get("stage"),
            "tool_status": details_of(f).get("tool_status"),
            "result_count": details_of(f).get("result_count"),
            "duration_ms": f.get("duration_ms"),
            "level": f.get("level"),
            "ts": f.get("ts"),
        }
        for f in frames
        if str(f.get("kind") or "") == TOOL_KIND
    ]

    response_ids = [c["response_id"] for c in calls if c.get("response_id")]
    return {
        "source": "app",
        "generated_at": now_iso(),
        "base_url": base,
        "run_id": run_id,
        "session_id": snapshot.get("session_id"),
        "workflow_id": snapshot.get("workflow_id"),
        "graph_version": snapshot.get("graph_version"),
        "status": snapshot.get("status"),
        "stop_reason": snapshot.get("stop_reason"),
        "mode": snapshot.get("mode"),
        "error": snapshot.get("error"),
        "created_at": snapshot.get("created_at"),
        "started_at": snapshot.get("started_at"),
        "completed_at": snapshot.get("completed_at"),
        "wall_clock_seconds": duration_seconds(
            snapshot.get("started_at") or snapshot.get("created_at"),
            snapshot.get("completed_at"),
        ),
        "frame_counters": dict(snapshot.get("frames") or {}),
        "frames_downloaded": len(frames),
        "totals": totals,
        "snapshot_usage": snapshot_usage,
        "totals_vs_snapshot": comparison,
        "by_node": by_node,
        "by_agent_role": by_agent,
        "by_task_name": by_task,
        "by_model": by_model,
        "node_usage": list(snapshot.get("node_usage") or []),
        "calls": calls,
        "failed_calls": failed_calls,
        "response_ids": response_ids,
        "calls_without_response_id": sum(
            1 for c in calls if not c.get("response_id")
        ),
        "tool_calls": tool_calls,
        "tool_call_count": sum(
            1 for t in tool_calls if str(t.get("stage") or "") in {"after", "error"}
        ),
        "spans": spans,
        "open_spans": [s for s in spans if s.get("open")],
        "durations": {
            "by_node": duration_rows(spans, "node", "node_id"),
            "by_agent_role": duration_rows(spans, "agent", "agent_role"),
            "by_task_name": duration_rows(spans, "task", "task_name"),
            "by_tool": duration_rows(spans, "tool", "tool"),
            "by_llm_call": duration_rows(spans, "llm", "label"),
        },
    }


def render_markdown(figures: Mapping[str, Any]) -> str:
    totals = figures["totals"]
    lines = [
        f"# App figures - run `{figures['run_id']}`",
        "",
        f"Generated {figures['generated_at']} from `{figures['base_url']}`.",
        "Serves the app column of DoD E1/E5 and the app half of B4.",
        "",
        "## Run",
        "",
        md_table(
            ["field", "value"],
            [
                ["workflow_id", figures.get("workflow_id")],
                ["graph_version", figures.get("graph_version")],
                ["status", figures.get("status")],
                ["stop_reason", figures.get("stop_reason") or "(none)"],
                ["mode", figures.get("mode")],
                ["started_at", figures.get("started_at")],
                ["completed_at", figures.get("completed_at")],
                ["wall clock (s)", secs(figures.get("wall_clock_seconds"))],
                ["frames downloaded", figures.get("frames_downloaded")],
                ["error", figures.get("error") or "(none)"],
            ],
        ),
        "",
        "## Totals, from the TOKEN frames",
        "",
        md_table(
            ["metric", "value"],
            [
                ["LLM calls", totals["calls"]],
                ["input tokens", totals["input_tokens"]],
                ["output tokens", totals["output_tokens"]],
                ["total tokens", totals["total_tokens"]],
                ["cost (app estimate)", usd(totals["cost_usd"])],
                ["calls with no price on file", totals["calls_without_cost"]],
                ["failed LLM calls (no tokens)", len(figures.get("failed_calls") or [])],
                ["tool calls (finished or errored)", figures.get("tool_call_count")],
                ["generation ids captured", len(figures.get("response_ids") or [])],
                ["calls with no generation id", figures.get("calls_without_response_id")],
            ],
        ),
        "",
        "## Frames versus the app's own snapshot",
        "",
        md_table(
            ["metric", "from frames", "from GET /api/runs/{id}", "agree"],
            [
                [
                    row["metric"],
                    row["from_frames"],
                    row["from_snapshot"],
                    "yes" if row["agree"] else "**NO**",
                ]
                for row in figures["totals_vs_snapshot"]
            ],
        ),
        "",
        "## Per agent role",
        "",
        bucket_table(figures["by_agent_role"], label="agent_role"),
        "",
        "## Per task name",
        "",
        bucket_table(figures["by_task_name"], label="task_name"),
        "",
        "## Per node",
        "",
        bucket_table(figures["by_node"], label="node_id"),
        "",
        "## Per model",
        "",
        bucket_table(figures["by_model"], label="model"),
        "",
        "## Durations, from frame timestamps",
        "",
    ]
    for title, key, label in (
        ("Agents", "by_agent_role", "agent_role"),
        ("Tasks", "by_task_name", "task_name"),
        ("Tools", "by_tool", "tool"),
        ("Nodes", "by_node", "node_id"),
    ):
        rows = figures["durations"][key]
        lines += [
            f"### {title} (slowest first)",
            "",
            md_table(
                [label, "spans", "total s", "slowest s", "unclosed"],
                [
                    [r["label"], r["spans"], secs(r["total_seconds"]), secs(r["max_seconds"]), r["open"] or ""]
                    for r in rows
                ],
            ),
            "",
        ]
    open_spans = figures.get("open_spans") or []
    lines += [
        f"Unclosed app-side spans: **{len(open_spans)}**"
        + (" (a run that is still going, or a frame pair the log does not close)" if open_spans else ""),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env()
    out_dir = ensure_dir(args.out)
    headers = build_headers(args)
    snapshot_file, frames_file = offline_sources(args)
    offline = bool(snapshot_file or frames_file)

    if offline:
        # A run whose backend has been killed cannot be re-pulled, and every
        # figure here comes from two files that were already saved. Deriving
        # from them is not a lesser measurement: it is the same function over
        # the same bytes.
        if snapshot_file is None or not snapshot_file.is_file():
            print(f"no app-run.json to read at {snapshot_file}", file=sys.stderr)
            return 2
        if frames_file is None or not frames_file.is_file():
            print(f"no frame NDJSON to read at {frames_file}", file=sys.stderr)
            return 2
        snapshot = read_json(snapshot_file)
        ndjson = frames_file.read_text(encoding="utf-8")
        print(
            f"offline: {snapshot_file} + {frames_file}; no request was made",
            file=sys.stderr,
        )
    else:
        with Http(args.base, headers=headers, timeout=args.timeout) as http:
            try:
                _, snapshot = http.get(f"/api/runs/{args.run_id}")
            except HttpError as exc:
                print(f"could not read the run snapshot: {exc}", file=sys.stderr)
                if exc.status in (401, 403):
                    print(
                        "the backend wants an identity: pass --token, or "
                        "--synthetic-user e2e-user against a SYNTHETIC=1 backend.",
                        file=sys.stderr,
                    )
                return 2
            ndjson = http.get_text(
                f"/api/runs/{args.run_id}/logs", {"format": "ndjson"}
            )

    if not isinstance(snapshot, Mapping):
        print("the snapshot was not a JSON object", file=sys.stderr)
        return 2

    snapshot_path = write_json(out_dir, "app-run.json", snapshot)
    frames_path = Path(out_dir) / "app-frames.ndjson"
    frames_path.write_text(ndjson, encoding="utf-8")

    frames = list(iter_frames(ndjson))
    figures = derive_figures(
        snapshot,
        frames,
        f"{snapshot_file} (offline)" if offline else args.base,
        args.run_id,
    )
    figures_path = write_json(out_dir, "app-figures.json", figures)
    md_path = write_text(out_dir, "app-figures.md", render_markdown(figures))

    print(render_markdown(figures))
    print(f"wrote {snapshot_path}")
    print(f"wrote {frames_path} ({len(frames)} frames)")
    print(f"wrote {figures_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
