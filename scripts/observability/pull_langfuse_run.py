"""Pull one run's Langfuse session, traces, observations and scores.

Serves DoD rows **B1** (`per-agent.md`), **B2** (`per-task.md`), **B4**
(`durations.md`), **D3** (`open-spans.txt`) and the Langfuse column of **E1**
and **E5** (`langfuse-figures.json`, shaped identically to `pull_app_run.py`'s
so the two can be compared cell for cell).

It addresses the session by the app's own run id, because
`TRACE-CONTRACT.md` §1 fixes `sessionId = run_id` verbatim. Three lookups,
in this order, because each covers a way the first can be legitimately empty:

1. `GET /api/public/sessions/{run_id}` - the session and its traces.
2. `GET /api/public/traces?sessionId=<run_id>` - the same set from the other
   side; on Langfuse Cloud the sessions endpoint is deprecated (sunset
   2026-11-16) and this is its replacement's nearest v3 equivalent.
3. `GET /api/public/traces/{run_id-derived-trace-id}` is NOT attempted: the
   contract derives the trace id with Langfuse's seeded derivation, which this
   script does not reimplement. Traces are found through the session instead.

**When there is no session it says so and exits 3, rather than crashing.** That
is the expected answer against the traces already in this project: they arrived
through OpenRouter's broadcast, which sends no `sessionId`
(`audit/langfuse-inventory.md` §2 - `sessionId` null on all 40).

Observations are paginated to exhaustion; a script that reads page 1 and stops
would under-report every long run, which is exactly the failure mode B1 exists
to catch.

**It waits for Langfuse to ingest before it reads.** Measured on the smoke-live
run (`evidence/smoke-live/README.md` §5): observations became visible **14.1 s**
after the run's terminal frame, all at once, and the public API rate-limits at
roughly one request a second. A fixed sleep is therefore either too short (an
empty pull reported as an empty run) or a guess; this polls the observation
count until it is **stable across two samples at least `--poll-stable-seconds`
apart**, backs off on 429, and records how long visibility took in
`langfuse-figures.json` under `ingestion_visibility`.

**Nothing it writes carries a credential.** Langfuse returns
`metadata.scope.attributes.public_key` - the value of `LANGFUSE_PUBLIC_KEY` -
on every trace, observation and session, so every file is written through
`_common.redact_for_disk` and the number of redactions goes to stderr. See F3.

Usage:

    .venv/Scripts/python.exe scripts/observability/pull_langfuse_run.py \
        --run-id <run id> --out DIR

    # parse-only, no network - used to test this script against the saved
    # audit exports before any exporter existed:
    .venv/Scripts/python.exe scripts/observability/pull_langfuse_run.py \
        --run-id any --out DIR \
        --offline-traces  docs/observability/evidence/audit/langfuse/api-traces-all.json \
        --offline-observations docs/observability/evidence/audit/langfuse/api-observations-all.json
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    Http,
    HttpError,
    add_call,
    bucket_for,
    bucket_table,
    duration_seconds,
    ensure_dir,
    env_required,
    eprint,
    load_env,
    md_table,
    now_iso,
    parse_ts,
    read_json,
    secs,
    sum_buckets,
    usd,
    write_json_redacted,
    write_text_redacted,
)

PAGE_LIMIT = 100
GENERATION = "GENERATION"
TOOL = "TOOL"
AGENT = "AGENT"
EVENT = "EVENT"

# The types that CAN end. D3 asks whether anything was left without an end
# time; a Langfuse EVENT is a point in time and carries no `endTime` by
# construction, so counting one as an unfinished span is a category error.
# MEASURED on the paid proof runs: the headline read 38 / 10 / 19 / 22 while
# the number of unfinished SPANS was 0 on every one of the six
# (`evidence/proof/cancelled/open-spans-by-type.txt`). The rule is by
# exclusion, not by allow-list: a type this script has never seen is assumed
# to close, because the failure that matters is missing a real open span.

# The five roles TRACE-CONTRACT.md §2 gives the hierarchy. Langfuse's native
# AGENT and TOOL types ARE the contract's agent and tool - §2's "a SPAN with
# metadata.observation_role" is the fallback for an ingestion that has no such
# type, and an older export is exactly that case, so both are accepted.
ROLE_RUN = "run"
ROLE_NODE = "node"
ROLE_TASK = "task"
ROLE_AGENT = "agent"
ROLE_TOOL = "tool"
ROLE_GENERATION = "generation"
ROLE_EVENT = "event"

# How long a single poll waits before the next count sample while the trace is
# still invisible. Deliberately shorter than the stability window: the first
# figure a reader wants is when the trace APPEARED, and a coarse interval would
# quantise it. It backs off from here on a 429.
POLL_FIRST_INTERVAL_SECONDS = 2.0
POLL_MAX_INTERVAL_SECONDS = 20.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Save a Langfuse session, its traces, observations and scores.",
    )
    parser.add_argument("--run-id", required=True, help="the app run id = sessionId")
    parser.add_argument("--out", required=True, help="directory to write into")
    parser.add_argument(
        "--trace-id",
        action="append",
        default=[],
        help="an extra trace id to include (repeatable); for a run whose session is missing",
    )
    parser.add_argument(
        "--offline-traces",
        default=None,
        help="a saved traces JSON (list, or a {data:[...]} envelope) - no network",
    )
    parser.add_argument(
        "--offline-observations",
        default=None,
        help="a saved observations JSON (list, or {data:[...]}) - no network",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--retries",
        type=int,
        default=5,
        help=(
            "attempts per request. A 429 waits for the server's own "
            "retryAfterSeconds (Langfuse asks for 42 on the observations "
            "endpoint), so five attempts outlast two windows"
        ),
    )
    parser.add_argument(
        "--app-figures",
        default=None,
        help=(
            "app-figures.json (or the directory holding it), so per-agent.md and "
            "per-task.md can state whether their SUM row equals the APP total as "
            "well as the trace total (B1, B2)"
        ),
    )
    parser.add_argument(
        "--no-poll",
        action="store_true",
        help=(
            "read once instead of waiting for ingestion. Only safe for a run "
            "whose trace is known to be complete already"
        ),
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=120.0,
        help="give up waiting for a stable observation count after N seconds (default 120)",
    )
    parser.add_argument(
        "--poll-stable-seconds",
        type=float,
        default=5.0,
        help=(
            "two count samples this far apart must agree before the pull starts "
            "(default 5; the smoke-live measurement is 14.1 s to first visibility)"
        ),
    )
    parser.add_argument(
        "--since",
        default=None,
        help=(
            "ISO timestamp of the run's terminal frame; visibility is then also "
            "reported relative to it, which is the figure a paid run wants"
        ),
    )
    return parser.parse_args(argv)


# --- fetching ---------------------------------------------------------------


def unwrap(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def fetch_all(http: Http, path: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every page of a Langfuse list endpoint.

    Stops on `meta.totalPages`, and additionally on an empty page, because a
    filtered endpoint has been seen to report a total for the unfiltered set.
    Bounded at 500 pages so a paging bug is a loud stop, not an infinite loop.
    """

    items: list[dict[str, Any]] = []
    page = 1
    while page <= 500:
        _, body = http.get(path, {**params, "page": page, "limit": PAGE_LIMIT})
        batch = unwrap(body)
        items.extend(batch)
        meta = body.get("meta") if isinstance(body, Mapping) else None
        total_pages = int((meta or {}).get("totalPages") or 0)
        if not batch or page >= max(total_pages, 1):
            break
        page += 1
    return items


# --- ingestion latency ------------------------------------------------------


def count_observations(http: Http, trace_ids: Sequence[str]) -> int:
    """How many observations Langfuse currently holds for these traces.

    Asks for one item and reads `meta.totalItems`, so a stability poll costs one
    request per trace rather than a full pagination each time - which matters
    against an API that rate-limits at about one request a second.
    """

    total = 0
    for trace_id in trace_ids:
        _, body = http.get(
            "/api/public/observations", {"traceId": trace_id, "limit": 1, "page": 1}
        )
        meta = body.get("meta") if isinstance(body, Mapping) else None
        if isinstance(meta, Mapping) and meta.get("totalItems") is not None:
            total += int(meta.get("totalItems") or 0)
        else:
            total += len(unwrap(body))
    return total


def wait_for_ingestion(
    http: Http,
    run_id: str,
    *,
    timeout: float,
    stable_seconds: float,
    since: str | None,
) -> dict[str, Any]:
    """Poll until the observation count stops moving, and say how long it took.

    The rule is *two samples at least `stable_seconds` apart agreeing on a
    non-zero count*, never a fixed sleep: the measured shape of this ingestion
    is a step (nothing for 14 s, then all 33 at once), and any fixed wait is
    either a guess that is too short or a guess that is too long. A 429 - which
    the smoke test hit five times in a row - lengthens the interval rather than
    counting as an answer.

    Returns a record even when it gives up: `stable: false` with the last count
    is an honest measurement, and a caller that pulled anyway can say so.
    """

    started = time.monotonic()
    since_ts = parse_ts(since)
    report: dict[str, Any] = {
        "polled": True,
        "started_at": now_iso(),
        "timeout_seconds": timeout,
        "stability_window_seconds": stable_seconds,
        "polls": 0,
        "rate_limited_polls": 0,
        "errors": 0,
        "first_visible_after_seconds": None,
        "stable_after_seconds": None,
        "stable": False,
        "observation_count": 0,
        "trace_count": 0,
        "since": since,
        "first_visible_after_terminal_seconds": None,
        "stable_after_terminal_seconds": None,
    }
    interval = POLL_FIRST_INTERVAL_SECONDS
    last_count: int | None = None
    last_count_at: float | None = None

    while True:
        elapsed = time.monotonic() - started
        report["polls"] += 1
        try:
            traces = fetch_all(http, "/api/public/traces", {"sessionId": run_id})
            trace_ids = [str(t.get("id")) for t in traces if t.get("id")]
            count = count_observations(http, trace_ids) if trace_ids else 0
        except HttpError as error:
            if error.status == 429:
                report["rate_limited_polls"] += 1
            else:
                report["errors"] += 1
            interval = min(interval * 2, POLL_MAX_INTERVAL_SECONDS)
            if time.monotonic() - started >= timeout:
                break
            time.sleep(min(interval, max(0.0, timeout - (time.monotonic() - started))))
            continue

        now = time.monotonic()
        elapsed = now - started
        report["trace_count"] = len(trace_ids)
        report["observation_count"] = count
        if count and report["first_visible_after_seconds"] is None:
            report["first_visible_after_seconds"] = round(elapsed, 3)
            if since_ts is not None:
                report["first_visible_after_terminal_seconds"] = round(
                    (parse_ts(now_iso()) - since_ts).total_seconds(), 3
                )
        if (
            count
            and last_count == count
            and last_count_at is not None
            and (now - last_count_at) >= stable_seconds
        ):
            report["stable"] = True
            report["stable_after_seconds"] = round(elapsed, 3)
            if since_ts is not None:
                report["stable_after_terminal_seconds"] = round(
                    (parse_ts(now_iso()) - since_ts).total_seconds(), 3
                )
            break
        if last_count != count:
            last_count = count
            last_count_at = now
            # A count that is still moving is worth re-sampling promptly; only
            # a settled one has to wait out the stability window.
            interval = POLL_FIRST_INTERVAL_SECONDS
        else:
            interval = max(POLL_FIRST_INTERVAL_SECONDS, stable_seconds / 2.0)
        if elapsed >= timeout:
            break
        wait = min(interval, max(0.1, timeout - elapsed))
        time.sleep(wait)

    report["finished_at"] = now_iso()
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report


# --- identity ---------------------------------------------------------------


def observation_role(observation: Mapping[str, Any]) -> str:
    """The contract's role for one observation, from its TYPE first.

    Langfuse's native `AGENT` and `TOOL` types are the contract's agent and
    tool (`TRACE-CONTRACT.md` §2), so the type answers first and
    `metadata.observation_role` is the fallback that keeps an older export -
    one written before those native types existed - readable by the same code.
    A bare `SPAN` with no role metadata is placed by what it names: the run
    span, a span named after its task, else a node.
    """

    kind = str(observation.get("type") or "").upper()
    if kind == GENERATION:
        return ROLE_GENERATION
    if kind == AGENT:
        return ROLE_AGENT
    if kind == TOOL:
        return ROLE_TOOL
    if kind == EVENT:
        return ROLE_EVENT
    meta = metadata_of(observation)
    role = str(meta.get("observation_role") or "").strip().lower()
    if role in {
        ROLE_RUN,
        ROLE_NODE,
        ROLE_TASK,
        ROLE_AGENT,
        ROLE_TOOL,
        ROLE_GENERATION,
        ROLE_EVENT,
    }:
        return role
    name = str(observation.get("name") or "")
    if name == "run" and not observation.get("parentObservationId"):
        return ROLE_RUN
    if meta.get("task_name") and name == str(meta.get("task_name")):
        return ROLE_TASK
    if meta.get("agent_role") and name == str(meta.get("agent_role")):
        return ROLE_AGENT
    return ROLE_NODE


def can_end(observation: Mapping[str, Any]) -> bool:
    """Could this observation have an `endTime` at all?

    Everything except an EVENT. `TRACE-CONTRACT.md` §2 makes an EVENT the
    catch-all for a frame that is a moment rather than an interval - a gate
    opening, an unknown frame kind - and Langfuse gives it no end time to have.
    D3 ("nothing is left without an end time once a terminal frame has been
    seen") is a question about spans, and an instrument that answers it by
    counting events reports a broken exporter on a healthy run.
    """

    return observation_role(observation) != ROLE_EVENT


def role_label(observation: Mapping[str, Any], role: str) -> str:
    """The name a role's row is filed under, matching the app's span labels."""

    meta = metadata_of(observation)
    name = str(observation.get("name") or "")
    if role == ROLE_AGENT:
        return str(meta.get("agent_role") or name or "(none)")
    if role == ROLE_TASK:
        return str(meta.get("task_name") or name or "(none)")
    if role == ROLE_TOOL:
        return name or "(none)"
    if role == ROLE_NODE:
        return str(meta.get("node_id") or name or "(none)")
    return name or role


def metadata_of(observation: Mapping[str, Any]) -> dict[str, Any]:
    meta = observation.get("metadata")
    return dict(meta) if isinstance(meta, Mapping) else {}


def resolve_identity(
    observation: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]], key: str
) -> str | None:
    """`metadata[key]`, else the nearest ancestor that has it.

    TRACE-CONTRACT §3 puts `agent_role` and `task_name` on EVERY observation,
    so the walk should never be needed. It is here because §2 also allows an
    observation to hang directly off the node span when a frame carries no
    agent - and because a per-agent table that silently files a generation
    under "(none)" is exactly the B1 answer the audit says is missing today.
    Which path answered is recorded per call in `identity_source`.
    """

    seen: set[str] = set()
    current: Mapping[str, Any] | None = observation
    while current is not None:
        value = metadata_of(current).get(key)
        if value not in (None, ""):
            return str(value)
        parent_id = current.get("parentObservationId")
        if not parent_id or parent_id in seen:
            return None
        seen.add(str(parent_id))
        current = by_id.get(str(parent_id))
    return None


def is_tool(observation: Mapping[str, Any]) -> bool:
    """TOOL, or the SPAN fallback the contract §2 allows for an ingestion
    that has no TOOL type."""

    if str(observation.get("type") or "") == TOOL:
        return True
    return str(metadata_of(observation).get("observation_role") or "") == "tool"


def tokens_of(observation: Mapping[str, Any]) -> tuple[int, int, int]:
    usage = observation.get("usageDetails")
    if isinstance(usage, Mapping) and usage:
        inp = int(usage.get("input") or 0)
        out = int(usage.get("output") or 0)
        total = int(usage.get("total") or (inp + out))
        return inp, out, total
    inp = int(observation.get("promptTokens") or 0)
    out = int(observation.get("completionTokens") or 0)
    total = int(observation.get("totalTokens") or (inp + out))
    return inp, out, total


def cost_of(observation: Mapping[str, Any]) -> float | None:
    """`costDetails.total`, else `calculatedTotalCost`, else None.

    None means Langfuse holds no cost for this generation - which is a real
    state (an unpriced model) and must not become 0.0.
    """

    details = observation.get("costDetails")
    if isinstance(details, Mapping) and details.get("total") is not None:
        try:
            return float(details["total"])
        except (TypeError, ValueError):
            pass
    value = observation.get("calculatedTotalCost")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --- derivation -------------------------------------------------------------


def derive_figures(
    run_id: str,
    session: Mapping[str, Any] | None,
    traces: Sequence[Mapping[str, Any]],
    observations: Sequence[Mapping[str, Any]],
    scores: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    by_id = {str(o.get("id")): o for o in observations if o.get("id")}
    by_node: dict[str, dict[str, Any]] = {}
    by_agent: dict[str, dict[str, Any]] = {}
    by_task: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    calls: list[dict[str, Any]] = []
    response_id_seen: dict[str, list[str]] = {}

    for observation in observations:
        if str(observation.get("type") or "") != GENERATION:
            continue
        meta = metadata_of(observation)
        inp, out, total = tokens_of(observation)
        agent_role = resolve_identity(observation, by_id, "agent_role")
        task_name = resolve_identity(observation, by_id, "task_name")
        node_id = resolve_identity(observation, by_id, "node_id")
        model = str(observation.get("model") or meta.get("model") or "")
        cost = cost_of(observation)
        response_id = meta.get("response_id")
        if response_id:
            response_id_seen.setdefault(str(response_id), []).append(
                str(observation.get("id"))
            )
        record = {
            "observation_id": observation.get("id"),
            "trace_id": observation.get("traceId"),
            "parent_observation_id": observation.get("parentObservationId"),
            "name": observation.get("name"),
            "response_id": response_id,
            "model": model,
            "node_id": node_id,
            "agent_role": agent_role,
            "task_name": task_name,
            "identity_source": "metadata"
            if meta.get("agent_role")
            else ("ancestor" if agent_role else "none"),
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": total,
            "cost_usd": cost,
            "cost_source": meta.get("cost_source"),
            "openrouter_cost_usd": meta.get("openrouter_cost_usd"),
            "attempt": meta.get("attempt"),
            "prompt_fingerprint": meta.get("prompt_fingerprint"),
            "level": observation.get("level"),
            "status_message": observation.get("statusMessage"),
            "start_time": observation.get("startTime"),
            "end_time": observation.get("endTime"),
            "duration_seconds": duration_seconds(
                observation.get("startTime"), observation.get("endTime")
            ),
        }
        calls.append(record)
        for mapping, key in (
            (by_node, node_id or ""),
            (by_agent, agent_role or ""),
            (by_task, task_name or ""),
            (by_model, model),
        ):
            add_call(
                bucket_for(mapping, key),
                input_tokens=inp,
                output_tokens=out,
                total_tokens=total,
                cost_usd=cost,
            )

    totals = sum_buckets(by_node)

    def _open_entry(o: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": o.get("id"),
            "traceId": o.get("traceId"),
            "type": o.get("type"),
            "role": observation_role(o),
            "name": o.get("name"),
            "startTime": o.get("startTime"),
            "level": o.get("level"),
            "run_id": metadata_of(o).get("run_id"),
            "can_end": can_end(o),
        }

    # Kept whole - every observation with a null endTime, EVENTs included - so
    # nothing is hidden. The D3 number is the non-EVENT subset below it.
    open_all = [_open_entry(o) for o in observations if not o.get("endTime")]
    open_observations = [entry for entry in open_all if entry["can_end"]]
    open_counts = {
        "total": len(open_all),
        "non_event": len(open_observations),
        "event": len(open_all) - len(open_observations),
        "by_type": _count(str(entry["type"] or "") for entry in open_all),
        "by_role": _count(str(entry["role"]) for entry in open_all),
    }

    tool_observations = [
        {
            "id": o.get("id"),
            "name": o.get("name"),
            "node_id": resolve_identity(o, by_id, "node_id"),
            "agent_role": resolve_identity(o, by_id, "agent_role"),
            "level": o.get("level"),
            "status_message": o.get("statusMessage"),
            "tool_status": metadata_of(o).get("tool_status"),
            "duration_seconds": duration_seconds(o.get("startTime"), o.get("endTime")),
        }
        for o in observations
        if is_tool(o)
    ]

    trace_status = None
    trace_output = (traces[0].get("output") if traces else None) or {}
    if isinstance(trace_output, Mapping):
        trace_status = trace_output.get("status")

    starts = [parse_ts(o.get("startTime")) for o in observations]
    ends = [parse_ts(o.get("endTime")) for o in observations]
    starts = [s for s in starts if s]
    ends = [e for e in ends if e]
    duration_rows = observation_durations(observations)

    return {
        "source": "langfuse",
        "generated_at": now_iso(),
        "run_id": run_id,
        "session_found": session is not None,
        "session_id": (session or {}).get("id"),
        "trace_ids": [t.get("id") for t in traces],
        "trace_names": sorted({str(t.get("name") or "") for t in traces}),
        "environment": sorted({str(t.get("environment") or "") for t in traces}),
        "user_ids": sorted({str(t.get("userId") or "") for t in traces}),
        "tags": sorted({tag for t in traces for tag in (t.get("tags") or [])}),
        "trace_metadata": [t.get("metadata") for t in traces],
        "status": trace_status,
        "started_at": min(starts).isoformat().replace("+00:00", "Z") if starts else None,
        "ended_at": max(ends).isoformat().replace("+00:00", "Z") if ends else None,
        "wall_clock_seconds": (max(ends) - min(starts)).total_seconds()
        if starts and ends
        else None,
        "observation_count": len(observations),
        "observation_types": _count(str(o.get("type") or "") for o in observations),
        "totals": totals,
        "by_node": by_node,
        "by_agent_role": by_agent,
        "by_task_name": by_task,
        "by_model": by_model,
        "calls": calls,
        "response_ids": [c["response_id"] for c in calls if c.get("response_id")],
        "calls_without_response_id": sum(1 for c in calls if not c.get("response_id")),
        "duplicate_response_ids": {
            rid: ids for rid, ids in response_id_seen.items() if len(ids) > 1
        },
        "tool_calls": tool_observations,
        "tool_call_count": len(tool_observations),
        # `open_observations` is the D3 list: observations that COULD have
        # ended and did not. `open_observations_all` keeps the EVENTs too, so
        # a reader can see both halves without re-deriving either.
        "open_observations": open_observations,
        "open_observations_all": open_all,
        "open_counts": open_counts,
        "scores": [
            {
                "name": s.get("name"),
                "value": s.get("value"),
                "stringValue": s.get("stringValue"),
                "dataType": s.get("dataType"),
                "traceId": s.get("traceId"),
                "observationId": s.get("observationId"),
            }
            for s in scores
        ],
        "observation_roles": _count(observation_role(o) for o in observations),
        "durations": {
            "by_agent_role": _durations_for_role(duration_rows, ROLE_AGENT),
            "by_task_name": _durations_for_role(duration_rows, ROLE_TASK),
            "by_node": _durations_for_role(duration_rows, ROLE_NODE),
            "by_tool": _durations_for_role(duration_rows, ROLE_TOOL),
            "by_run": _durations_for_role(duration_rows, ROLE_RUN),
            # Every observation, with its OWN duration and nothing summed into
            # it. `reconcile.py` pairs these 1:1 with the app's frame spans.
            "observations": duration_rows,
            "by_observation": sorted(
                (dict(row) for row in duration_rows),
                key=lambda r: (r["seconds"] is None, -(r["seconds"] or 0.0)),
            )[:50],
        },
    }


def _count(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def observation_durations(
    observations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """One row per observation: its OWN duration, its role and its label.

    This is the input B4 needs and the thing that was previously missing. The
    contract's tree nests four observations per agent execution (node -> task ->
    agent -> tool/generation), each covering nearly the same wall clock, so any
    figure that adds a child's duration to its parent's counts one 2 s tool call
    three times and reports 6 s. Nothing here ever sums across the tree: a row
    is one observation, and a group is a set of observations *of the same role*,
    which are siblings in time rather than nested.
    """

    rows: list[dict[str, Any]] = []
    for observation in observations:
        role = observation_role(observation)
        meta = metadata_of(observation)
        rows.append(
            {
                "id": observation.get("id"),
                "trace_id": observation.get("traceId"),
                "parent_observation_id": observation.get("parentObservationId"),
                "type": observation.get("type"),
                "role": role,
                "name": observation.get("name"),
                "label": role_label(observation, role),
                "node_id": meta.get("node_id"),
                "agent_role": meta.get("agent_role"),
                "task_name": meta.get("task_name"),
                "start_time": observation.get("startTime"),
                "end_time": observation.get("endTime"),
                "seconds": duration_seconds(
                    observation.get("startTime"), observation.get("endTime")
                ),
                "open": not observation.get("endTime"),
                "level": observation.get("level"),
            }
        )
    rows.sort(key=lambda r: (parse_ts(r["start_time"]) or parse_ts("1970-01-01T00:00:00Z")))
    return rows


def _durations_for_role(
    rows: Sequence[Mapping[str, Any]], role: str
) -> list[dict[str, Any]]:
    """Group observations OF ONE ROLE by their label, slowest first.

    Same-role observations are never each other's ancestors in this contract's
    tree, so the total here is a sum over separate executions - a node that ran
    twice - and not the nesting artefact above.
    """

    rolled: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("role") != role:
            continue
        label = str(row.get("label") or "(none)")
        entry = rolled.setdefault(
            label,
            {
                "label": label,
                "role": role,
                "spans": 0,
                "total_seconds": 0.0,
                "max_seconds": 0.0,
                "open": 0,
            },
        )
        entry["spans"] += 1
        if row.get("open"):
            entry["open"] += 1
        seconds = row.get("seconds")
        if seconds is None:
            continue
        entry["total_seconds"] += float(seconds)
        entry["max_seconds"] = max(entry["max_seconds"], float(seconds))
    return sorted(rolled.values(), key=lambda r: r["total_seconds"], reverse=True)


# --- rendering --------------------------------------------------------------


def hierarchy_text(
    observations: Sequence[Mapping[str, Any]], traces: Sequence[Mapping[str, Any]]
) -> str:
    """An indented tree of role/type/name per trace - the human's map of the run.

    Two things it must survive, because both have been measured here:

    * **the parentless root.** `TRACE-CONTRACT.md` §1 makes the `run` span the
      root with `parentObservationId` null, so the tree is drawn from whatever
      is parentless. Nothing assumes there is exactly one.
    * **a missing parent.** The smoke-live export's `run` span named a parent
      the API never returns, and drawing only from parentless roots printed an
      ORPHANED line and no tree at all - an empty artifact for the row that
      cites it. An orphan is now a subtree ROOT, drawn in full under an
      ORPHANED heading that says which parent id is absent, so the rest of the
      tree is legible while the defect stays visible.

    Roles come from `observation_role`, so Langfuse's native AGENT and TOOL
    types read as the contract's agent and tool and an older export's
    `metadata.observation_role` still does too.
    """

    children: dict[str, list[Mapping[str, Any]]] = {}
    known = {str(o.get("id")) for o in observations}
    roots: dict[str, list[Mapping[str, Any]]] = {}
    orphans: list[Mapping[str, Any]] = []
    for observation in observations:
        parent = observation.get("parentObservationId")
        if parent and str(parent) in known:
            children.setdefault(str(parent), []).append(observation)
        elif parent:
            orphans.append(observation)
        else:
            roots.setdefault(str(observation.get("traceId")), []).append(observation)

    def sort_key(observation: Mapping[str, Any]) -> tuple[Any, ...]:
        started = parse_ts(observation.get("startTime"))
        return (started.timestamp() if started else 0.0, str(observation.get("name") or ""))

    lines: list[str] = []
    drawn: set[str] = set()

    def walk(observation: Mapping[str, Any], depth: int) -> None:
        identifier = str(observation.get("id"))
        if identifier in drawn:  # a cycle, or a parent id repeated
            lines.append(f"{'  ' * depth}- (already drawn: {identifier})")
            return
        drawn.add(identifier)
        meta = metadata_of(observation)
        role = observation_role(observation)
        agent = meta.get("agent_role") or ""
        task = meta.get("task_name") or ""
        marker = "" if observation.get("endTime") else "  [OPEN]"
        level = str(observation.get("level") or "")
        level_marker = f"  [{level}]" if level and level != "DEFAULT" else ""
        suffix = " ".join(
            part
            for part in (
                f"agent={agent}" if agent else "",
                f"task={task}" if task else "",
            )
            if part
        )
        lines.append(
            f"{'  ' * depth}- {observation.get('type')}/{role} {observation.get('name')}"
            + (f"  ({suffix})" if suffix else "")
            + level_marker
            + marker
        )
        for child in sorted(children.get(identifier, []), key=sort_key):
            walk(child, depth + 1)

    for trace in traces:
        trace_id = str(trace.get("id"))
        trace_roots = sorted(roots.get(trace_id, []), key=sort_key)
        lines.append(
            f"TRACE {trace_id}  name={trace.get('name')}  session={trace.get('sessionId')}"
        )
        lines.append(
            f"  roots (parentObservationId null): {len(trace_roots)}"
            + ("  <- NONE; see ORPHANED below" if not trace_roots else "")
        )
        for root in trace_roots:
            walk(root, 1)
        lines.append("")
    unplaced = [
        trace_id for trace_id in roots if trace_id not in {str(t.get("id")) for t in traces}
    ]
    for trace_id in unplaced:
        lines.append(f"TRACE {trace_id}  (not in the fetched trace list)")
        for root in sorted(roots[trace_id], key=sort_key):
            walk(root, 1)
        lines.append("")
    if orphans:
        lines.append(
            "ORPHANED - the parent observation named below was not returned by the API."
        )
        lines.append(
            "The subtree under each is drawn in full: a missing parent is a finding"
        )
        lines.append("about the exporter, not a reason to lose the tree.")
        for observation in sorted(orphans, key=sort_key):
            lines.append(
                f"  MISSING PARENT {observation.get('parentObservationId')} of "
                f"{observation.get('type')} {observation.get('name')}:"
            )
            walk(observation, 2)
        lines.append("")
    undrawn = [o for o in observations if str(o.get("id")) not in drawn]
    if undrawn:
        lines.append(
            f"NOT DRAWN ({len(undrawn)}) - reachable from no root and from no orphan:"
        )
        for observation in sorted(undrawn, key=sort_key):
            lines.append(
                f"  - {observation.get('type')} {observation.get('name')} "
                f"id={observation.get('id')} parent={observation.get('parentObservationId')}"
            )
    return "\n".join(lines)


def render_durations(figures: Mapping[str, Any]) -> str:
    lines = [
        f"# Durations from Langfuse spans - run `{figures['run_id']}`",
        "",
        "DoD B4. Slowest first. The app-side column is in `app-figures.md`;",
        "`reconcile.py` is what puts the two within-1-s comparison side by side.",
        "",
        f"Run span: {figures.get('started_at')} -> {figures.get('ended_at')} "
        f"({secs(figures.get('wall_clock_seconds'))} s)",
        "",
        "Every figure below is an observation's OWN duration. A child's duration",
        "is never added to its parent's: the contract nests node -> task -> agent",
        "-> tool over one 2 s tool call, and summing that tree reports 6 s.",
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
            f"## {title}",
            "",
            md_table(
                [label, "spans", "total s", "slowest s", "unclosed"],
                [
                    [
                        row["label"],
                        row["spans"],
                        secs(row["total_seconds"]),
                        secs(row["max_seconds"]),
                        row["open"] or "",
                    ]
                    for row in rows
                ],
            ),
            "",
        ]
    slowest = []
    for role, title in ((ROLE_AGENT, "agent"), (ROLE_TASK, "task"), (ROLE_TOOL, "tool")):
        ranked = [
            row
            for row in figures["durations"]["observations"]
            if row.get("role") == role and row.get("seconds") is not None
        ]
        ranked.sort(key=lambda r: -(r["seconds"] or 0.0))
        slowest.append(
            [
                title,
                ranked[0]["label"] if ranked else "(none observed)",
                secs(ranked[0]["seconds"]) if ranked else "n/a",
                ranked[0]["id"] if ranked else "",
            ]
        )
    lines += [
        "## The B4 answer: the slowest agent, task and tool",
        "",
        md_table(["role", "label", "seconds", "observation id"], slowest),
        "",
        "## Slowest individual observations",
        "",
        md_table(
            ["role", "type", "name", "seconds", "id"],
            [
                [row["role"], row["type"], row["name"], secs(row["seconds"]), row["id"]]
                for row in figures["durations"]["by_observation"][:20]
            ],
        ),
        "",
    ]
    return "\n".join(lines)


def _run_metrics_usage(figures: Mapping[str, Any]) -> dict[str, Any] | None:
    """The run total the TRACE itself reports, if it carries one.

    `trace.metadata.run_metrics.usage` is the app's own last metrics snapshot.
    It is a different measurement from summing the generations, and on the
    smoke-live runs the two disagree (the interval snapshot was kept, not the
    final one), which is exactly why B1/B2 must state the comparison rather
    than print one number and leave a reader to assume.
    """

    for metadata in figures.get("trace_metadata") or []:
        if not isinstance(metadata, Mapping):
            continue
        metrics = metadata.get("run_metrics")
        if isinstance(metrics, Mapping) and isinstance(metrics.get("usage"), Mapping):
            usage = dict(metrics["usage"])
            usage["reason"] = metrics.get("reason")
            return usage
    return None


def _equal(left: Any, right: Any, tolerance: float = 0.0) -> str:
    if left is None or right is None:
        return "n/a"
    try:
        return "**YES**" if abs(float(left) - float(right)) <= tolerance else "**NO**"
    except (TypeError, ValueError):
        return "n/a"


def render_group(
    figures: Mapping[str, Any],
    key: str,
    label: str,
    row_id: str,
    app: Mapping[str, Any] | None = None,
) -> str:
    totals = figures["totals"]
    grouped = sum_buckets(figures[key])
    run_metrics = _run_metrics_usage(figures)
    app_totals = dict((app or {}).get("totals") or {}) if app else {}

    rows: list[list[Any]] = [
        [
            "this table's SUM row",
            grouped["calls"],
            grouped["input_tokens"],
            grouped["output_tokens"],
            grouped["total_tokens"],
            usd(grouped["cost_usd"]),
            "-",
        ],
        [
            "every GENERATION in the trace",
            totals["calls"],
            totals["input_tokens"],
            totals["output_tokens"],
            totals["total_tokens"],
            usd(totals["cost_usd"]),
            _equal(grouped["total_tokens"], totals["total_tokens"]),
        ],
    ]
    if run_metrics is not None:
        rows.append(
            [
                f"trace metadata `run_metrics` (reason: {run_metrics.get('reason')})",
                run_metrics.get("call_count"),
                "",
                "",
                run_metrics.get("total_tokens"),
                usd(run_metrics.get("cost_usd")),
                _equal(grouped["total_tokens"], run_metrics.get("total_tokens")),
            ]
        )
    if app_totals:
        rows.append(
            [
                "the APP's own frame-derived total",
                app_totals.get("calls"),
                app_totals.get("input_tokens"),
                app_totals.get("output_tokens"),
                app_totals.get("total_tokens"),
                usd(app_totals.get("cost_usd")),
                _equal(grouped["total_tokens"], app_totals.get("total_tokens")),
            ]
        )

    lines = [
        f"# Per {label} - run `{figures['run_id']}`",
        "",
        f"DoD {row_id}, computed from the Langfuse API by grouping GENERATION",
        f"observations on their `metadata.{key.replace('by_', '')}` attribute.",
        "",
        bucket_table(figures[key], label=label),
        "",
        "## Does the SUM row equal the run total?",
        "",
        md_table(
            [
                "total",
                "calls",
                "input",
                "output",
                "total tokens",
                "cost",
                "equals the SUM row?",
            ],
            rows,
        ),
        "",
    ]
    if not app_totals:
        lines += [
            "The APP row is absent: no `--app-figures` was given, so this file "
            "compares the table only against Langfuse's own figures.",
            "",
        ]
    lines += [
        f"Generations whose identity came from an ANCESTOR rather than their own "
        f"metadata: {sum(1 for c in figures['calls'] if c.get('identity_source') == 'ancestor')}"
        f"; with no identity at all: "
        f"{sum(1 for c in figures['calls'] if c.get('identity_source') == 'none')}.",
        "",
    ]
    return "\n".join(lines)


def render_visibility(visibility: Mapping[str, Any] | None) -> list[str]:
    """How long Langfuse took to make this run readable - measured, not assumed."""

    if not visibility:
        return []
    if not visibility.get("polled"):
        return [
            "## Ingestion visibility",
            "",
            "**NOT MEASURED** - `--no-poll` was given, so this pull read whatever was "
            "there at the moment it ran. An empty or short read is not evidence of an "
            "empty run.",
            "",
        ]
    return [
        "## Ingestion visibility (measured by polling, not assumed)",
        "",
        md_table(
            ["field", "value"],
            [
                ["polls", visibility.get("polls")],
                ["rate-limited polls (429)", visibility.get("rate_limited_polls")],
                ["other poll errors", visibility.get("errors")],
                [
                    "first observation visible after (s, from poll start)",
                    secs(visibility.get("first_visible_after_seconds")),
                ],
                [
                    "count stable after (s, from poll start)",
                    secs(visibility.get("stable_after_seconds")),
                ],
                [
                    "first visible after the run's terminal frame (s)",
                    secs(visibility.get("first_visible_after_terminal_seconds")),
                ],
                [
                    "stable after the run's terminal frame (s)",
                    secs(visibility.get("stable_after_terminal_seconds")),
                ],
                [
                    "stable within the timeout",
                    "yes" if visibility.get("stable") else "**NO - timed out**",
                ],
                ["observation count at that point", visibility.get("observation_count")],
                ["stability window (s)", secs(visibility.get("stability_window_seconds"))],
                ["timeout (s)", secs(visibility.get("timeout_seconds"))],
            ],
        ),
        "",
    ]


def render_summary(figures: Mapping[str, Any]) -> str:
    totals = figures["totals"]
    duplicates = figures.get("duplicate_response_ids") or {}
    return "\n".join(
        [
            f"# Langfuse figures - run `{figures['run_id']}`",
            "",
            md_table(
                ["field", "value"],
                [
                    ["session found", "yes" if figures["session_found"] else "**NO**"],
                    ["traces", len(figures["trace_ids"])],
                    ["trace names", ", ".join(figures["trace_names"]) or "(none)"],
                    ["environment", ", ".join(figures["environment"]) or "(none)"],
                    ["userId", ", ".join(figures["user_ids"]) or "(none)"],
                    ["tags", ", ".join(figures["tags"]) or "(none)"],
                    ["trace output.status", figures.get("status") or "(none)"],
                    ["observations", figures["observation_count"]],
                    [
                        "observation types",
                        ", ".join(f"{k}:{v}" for k, v in figures["observation_types"].items())
                        or "(none)",
                    ],
                    [
                        "observation roles",
                        ", ".join(
                            f"{k}:{v}"
                            for k, v in (figures.get("observation_roles") or {}).items()
                        )
                        or "(none)",
                    ],
                    # Three different numbers, and the previous table
                    # printed only the middle one under the D3 label.
                    [
                        "unfinished spans (D3: non-EVENT, endTime null)",
                        (figures.get("open_counts") or {}).get("non_event"),
                    ],
                    [
                        "observations with endTime null, all types",
                        (figures.get("open_counts") or {}).get("total"),
                    ],
                    [
                        "of those, EVENT (no endTime by construction)",
                        (figures.get("open_counts") or {}).get("event"),
                    ],
                    ["scores", len(figures["scores"])],
                    ["wall clock (s)", secs(figures.get("wall_clock_seconds"))],
                ],
            ),
            "",
            "## Totals",
            "",
            md_table(
                ["metric", "value"],
                [
                    ["generations", totals["calls"]],
                    ["input tokens", totals["input_tokens"]],
                    ["output tokens", totals["output_tokens"]],
                    ["total tokens", totals["total_tokens"]],
                    ["cost", usd(totals["cost_usd"])],
                    ["generations with no cost", totals["calls_without_cost"]],
                    ["tool observations", figures["tool_call_count"]],
                    ["generation ids present", len(figures["response_ids"])],
                    ["generations with no id", figures["calls_without_response_id"]],
                    [
                        "DUPLICATE generation ids (E1)",
                        f"**{len(duplicates)}**" if duplicates else "0",
                    ],
                ],
            ),
            "",
            *render_visibility(figures.get("ingestion_visibility")),
        ]
    )


# --- main -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env()
    out_dir = ensure_dir(args.out)

    session: Mapping[str, Any] | None = None
    traces: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    scores: list[dict[str, Any]] = []
    visibility: dict[str, Any] | None = None
    offline = bool(args.offline_traces or args.offline_observations)

    if offline:
        if args.offline_traces:
            traces = unwrap(read_json(args.offline_traces))
        if args.offline_observations:
            observations = unwrap(read_json(args.offline_observations))
        matching = [t for t in traces if str(t.get("sessionId") or "") == args.run_id]
        if matching:
            traces = matching
            trace_ids = {str(t.get("id")) for t in traces}
            observations = [o for o in observations if str(o.get("traceId")) in trace_ids]
        else:
            print(
                f"offline mode: no saved trace carries sessionId == {args.run_id!r}; "
                f"deriving over ALL {len(traces)} saved traces so the parsing is "
                "exercised. The figures below are about the file, not about a run.",
                file=sys.stderr,
            )
    else:
        base = env_required("LANGFUSE_BASE_URL", "e.g. https://us.cloud.langfuse.com")
        public = env_required("LANGFUSE_PUBLIC_KEY")
        secret = env_required("LANGFUSE_SECRET_KEY")
        # Five attempts, not three, and `Http` now waits as long as the
        # server's own `retryAfterSeconds` asks. Measured: Langfuse limits
        # `/api/public/observations` to 15 requests per window and answers 429
        # with `retryAfterSeconds: 42`, which three attempts at 1.5/3/6 s
        # cannot outlast - pulling three runs back to back raised.
        with Http(
            base,
            auth=(public, secret),
            timeout=args.timeout,
            retries=args.retries,
        ) as http:
            if args.no_poll:
                visibility = {"polled": False, "reason": "--no-poll"}
            else:
                visibility = wait_for_ingestion(
                    http,
                    args.run_id,
                    timeout=args.poll_timeout,
                    stable_seconds=args.poll_stable_seconds,
                    since=args.since,
                )
                eprint(
                    f"ingestion: {visibility['polls']} polls, "
                    f"{visibility['observation_count']} observations, "
                    f"first visible after "
                    f"{secs(visibility.get('first_visible_after_seconds'))} s, "
                    f"stable={visibility['stable']} "
                    f"({visibility['rate_limited_polls']} rate-limited)"
                )
            status, body = http.get(
                f"/api/public/sessions/{args.run_id}", allow_status=(404,)
            )
            if status == 200 and isinstance(body, Mapping):
                session = body
                traces = [t for t in unwrap({"data": body.get("traces")}) if t]
            by_filter = fetch_all(http, "/api/public/traces", {"sessionId": args.run_id})
            known = {str(t.get("id")) for t in traces}
            traces.extend(t for t in by_filter if str(t.get("id")) not in known)
            for trace_id in args.trace_id:
                if trace_id in {str(t.get("id")) for t in traces}:
                    continue
                trace_status, trace_body = http.get(
                    f"/api/public/traces/{trace_id}", allow_status=(404,)
                )
                if trace_status == 200 and isinstance(trace_body, Mapping):
                    traces.append(dict(trace_body))

            if not traces:
                write_text_redacted(
                    out_dir,
                    "langfuse-session-missing.txt",
                    "\n".join(
                        [
                            f"run_id / sessionId: {args.run_id}",
                            f"checked at:         {now_iso()}",
                            "GET /api/public/sessions/{run_id}      -> 404",
                            "GET /api/public/traces?sessionId={run_id} -> 0 traces",
                            "",
                            "NOT a crash and not necessarily a defect: traces that reach",
                            "this project through OpenRouter's broadcast carry no",
                            "sessionId at all (audit/langfuse-inventory.md section 2), so",
                            "they can never be found this way. A run whose exporter ran",
                            "should be found here; one whose exporter was disabled, or a",
                            "run whose id was mistyped, will not be.",
                            "",
                            f"ingestion poll: {visibility}",
                        ]
                    ),
                )
                print(
                    f"no Langfuse session and no trace for run {args.run_id}. "
                    f"Wrote {out_dir / 'langfuse-session-missing.txt'} explaining what "
                    "that does and does not mean.",
                    file=sys.stderr,
                )
                return 3

            for trace in traces:
                observations.extend(
                    fetch_all(
                        http, "/api/public/observations", {"traceId": str(trace.get("id"))}
                    )
                )
                trace_scores = fetch_all(
                    http, "/api/public/v2/scores", {"traceId": str(trace.get("id"))}
                )
                scores.extend(trace_scores)

    # Every write goes through the redactor. Langfuse returns the project's own
    # public key on every object it serves (`metadata.scope.attributes.
    # public_key`), so a verbatim save writes a credential to disk 36 times per
    # run and DoD F3's own scanner fails over the directory. See _common.py.
    redactions = 0
    written: list[Path] = []

    def save_json(name: str, data: Any) -> None:
        nonlocal redactions
        path, count = write_json_redacted(out_dir, name, data)
        redactions += count
        written.append(path)

    def save_text(name: str, text: str) -> None:
        nonlocal redactions
        path, count = write_text_redacted(out_dir, name, text)
        redactions += count
        written.append(path)

    save_json("langfuse-session.json", session or {"note": "no session object"})
    save_json("langfuse-traces.json", traces)
    save_json("langfuse-observations.json", observations)
    save_json("langfuse-scores.json", scores)

    app_figures: Mapping[str, Any] | None = None
    if args.app_figures:
        app_path = Path(args.app_figures)
        if app_path.is_dir():
            app_path = app_path / "app-figures.json"
        if app_path.is_file():
            loaded = read_json(app_path)
            app_figures = loaded if isinstance(loaded, Mapping) else None
        else:
            eprint(f"--app-figures: {app_path} does not exist; the APP row is omitted")

    figures = derive_figures(args.run_id, session, traces, observations, scores)
    figures["ingestion_visibility"] = visibility
    save_json("langfuse-figures.json", figures)
    save_text("langfuse-figures.md", render_summary(figures))
    save_text(
        "per-agent.md",
        render_group(figures, "by_agent_role", "agent_role", "B1", app_figures),
    )
    save_text(
        "per-task.md",
        render_group(figures, "by_task_name", "task_name", "B2", app_figures),
    )
    save_text("durations.md", render_durations(figures))
    save_text("hierarchy.txt", hierarchy_text(observations, traces))

    open_observations = figures["open_observations"]
    open_all = figures["open_observations_all"]
    counts = figures["open_counts"]
    # The HEADLINE is the D3 number and nothing else: observations that could
    # have ended and did not. The total and the per-type split sit beside it so
    # a reader sees both figures rather than having to trust one - the previous
    # headline counted EVENTs and read 38 on a paid run whose unfinished-span
    # count was 0.
    open_lines = [
        "unfinished spans (non-EVENT observations with endTime null): "
        f"{counts['non_event']}",
        "",
        f"run_id: {args.run_id}   checked: {now_iso()}",
        f"observations examined: {figures['observation_count']}",
        "",
        "The split, because these are three different numbers:",
        f"  observations with endTime null, ALL types  : {counts['total']}",
        f"  of those, EVENT (no endTime by construction): {counts['event']}",
        f"  of those, able to end and still open (D3)   : {counts['non_event']}",
        "",
        "  by type: "
        + (
            ", ".join(f"{k or '(none)'}={v}" for k, v in counts["by_type"].items())
            or "(nothing open)"
        ),
        "  by role: "
        + (
            ", ".join(f"{k}={v}" for k, v in counts["by_role"].items())
            or "(nothing open)"
        ),
        "",
        "A Langfuse EVENT is a point in time and carries no endTime:",
        "TRACE-CONTRACT.md section 2 makes it the catch-all for a gate opening or",
        "an unknown frame kind. Counting one as an unfinished span is a category",
        "error, and it is the one this file made until 2026-09-06 - it read 38 on",
        "a paid run whose unfinished-span count was 0. See",
        "evidence/proof/cancelled/open-spans-by-type.txt.",
        "",
    ]
    for observation in open_observations:
        open_lines.append(
            f"  {observation['type']} {observation['name']} id={observation['id']} "
            f"start={observation['startTime']} run_id={observation['run_id']}"
        )
    if not open_observations:
        open_lines.append("  (no unfinished span - DoD D3 is satisfied for this run)")
    if counts["event"]:
        open_lines += [
            "",
            f"The {counts['event']} EVENT observation(s) with no endTime, listed for",
            "completeness. None of these is a D3 finding:",
        ]
        for observation in open_all:
            if observation["can_end"]:
                continue
            open_lines.append(
                f"  {observation['type']} {observation['name']} "
                f"id={observation['id']} start={observation['startTime']}"
            )
    save_text("open-spans.txt", "\n".join(open_lines))

    print(render_summary(figures))
    print(f"wrote {out_dir}")
    # The COUNT, never a value: F3's whole point is that a credential does not
    # travel, and a script that printed what it had redacted would leak it into
    # a terminal log instead of a file.
    eprint(
        f"redaction: {redactions} credential-named field(s) and credential-shaped "
        f"value(s) replaced with '<redacted>' across {len(written)} file(s) "
        "BEFORE writing (F3)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
