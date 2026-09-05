"""Put the app, Langfuse and OpenRouter side by side for one run.

Serves DoD rows **E5** (*"the app's figures and Langfuse's agree, or the
difference is diagnosed"*) and **E1** (*"nothing reaches Langfuse twice"*).

It writes the `RECONCILIATION-<run>.md` fragment a verifier fills in, and it
deliberately does NOT decide whether a difference is acceptable. Every
differing cell gets an empty **Diagnosis** column, because E5's own wording is
that *"every difference has a named cause; 'close enough' is not a status"* -
a script that graded its own output would be exactly the "close enough" this
row refuses.

Four checks, in the order a reader wants them:

1. **Totals** - calls, input/output/total tokens, cost, per source.
2. **E1, in three parts, because "nothing reaches Langfuse twice" has three
   ways of being false and one of them is invisible from inside the session:**

   a. the count of GENERATION observations in the session against the app's
      own LLM after-frame count - a second copy inside the session;
   b. the per-call join on `metadata.response_id` against OpenRouter's own
      generation records - the only check that can find a call present in two
      sources and absent from the third;
   c. a scan of the same time window for a SECOND trace carrying
      `metadata["openrouter.api_key_name"]` - the shape OpenRouter's own
      broadcast integration writes. That trace is not in this run's session and
      no amount of looking inside the session would ever find it, which is
      exactly why the double-report E1 forbids needs its own check. The count
      must be **0** after the OpenRouter-side exclusion. `--window-minutes`
      widens the window either side of the run.

3. **Durations (B4)** - the app's frame-derived spans against Langfuse's,
   **per observation**, never per group. The contract's tree nests
   node -> task -> agent -> tool over one tool call, so a grouped sum counts a
   2 s call three times and reports 6.014 s against the app's 2.006 s: a
   failing exporter that is really a failing reconciler. Each row pairs one
   app span with one Langfuse observation of the same role and label, in start
   order, and the tables are ranked slowest first - which is the other half of
   what B4 asks.

Usage:

    .venv/Scripts/python.exe scripts/observability/reconcile.py \
        --app DIR --langfuse DIR --openrouter DIR \
        --out docs/observability/RECONCILIATION-<run>.md

Every source is a directory of files somebody already pulled, so this runs
against a saved run with the backend long gone. The ONE thing it does over the
network is E1(c), and `--no-network` turns that off (it then reads
**NOT CHECKED**, never PASS).
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from itertools import zip_longest
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    Http,
    HttpError,
    env_optional,
    load_env,
    md_table,
    now_iso,
    parse_ts,
    read_json,
    secs,
    usd,
    write_text_redacted,
)
from pull_langfuse_run import fetch_all, observation_durations, unwrap  # noqa: E402

TOKEN_TOLERANCE = 0
COST_TOLERANCE = 1e-9
DURATION_TOLERANCE_SECONDS = 1.0

# The metadata key OpenRouter's own Langfuse broadcast stamps on a trace. It is
# a key NAME, never a key value - `api_key_name` is what the destination was
# called in the OpenRouter dashboard - so looking for it leaks nothing.
OPENROUTER_BROADCAST_KEY = "openrouter.api_key_name"

# App span kind -> Langfuse observation role. The pairing is 1:1 within a
# (kind, label): one app agent-execution span against one AGENT observation,
# one tool before/after pair against one TOOL observation. A GENERATION is
# deliberately absent - the app's `llm` spans are inside their agent's span,
# and pairing them here would invite exactly the double count this section
# exists to remove.
DURATION_ROLES = (
    ("agent", "agent", "agent_role", "Agents"),
    ("task", "task", "task_name", "Tasks"),
    ("tool", "tool", "tool", "Tools"),
    ("node", "node", "node_id", "Nodes"),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile app, Langfuse and OpenRouter figures for one run.",
    )
    parser.add_argument("--app", required=True, help="directory holding app-figures.json")
    parser.add_argument(
        "--langfuse", default=None, help="directory holding langfuse-figures.json"
    )
    parser.add_argument(
        "--openrouter", default=None, help="directory holding openrouter-figures.json"
    )
    parser.add_argument("--out", required=True, help="the RECONCILIATION markdown file")
    parser.add_argument(
        "--durations-out",
        default=None,
        help=(
            "also write the app-versus-Langfuse duration comparison here "
            "(B4's side-by-side half; pull_langfuse_run.py's durations.md is "
            "the Langfuse side alone)"
        ),
    )
    parser.add_argument(
        "--window-minutes",
        type=float,
        default=10.0,
        help=(
            "how far either side of the run to look for a SECOND trace carrying "
            "openrouter.api_key_name - E1(c) (default 10)"
        ),
    )
    parser.add_argument(
        "--no-network",
        action="store_true",
        help=(
            "skip E1(c)'s Langfuse query; that check then reads NOT CHECKED, "
            "which is not a pass"
        ),
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args(argv)


def load(directory: str | None, name: str) -> dict[str, Any] | None:
    if not directory:
        return None
    path = Path(directory)
    if path.is_dir():
        path = path / name
    if not path.is_file():
        return None
    payload = read_json(path)
    return dict(payload) if isinstance(payload, Mapping) else None


def totals_of(figures: Mapping[str, Any] | None) -> dict[str, Any]:
    """A source's totals, or `{}` when the source has nothing to say.

    "Nothing to say" is not "zero", and conflating them is the single most
    misleading thing this script could do: an OpenRouter directory holding no
    generation ids would otherwise report `calls 0` and make every metric read
    **DIFFER** against an app that made six calls, sending a verifier off to
    diagnose a difference that is an absent measurement.
    """

    if not figures:
        return {}
    if figures.get("source") == "openrouter" and not figures.get("requested"):
        return {}
    if figures.get("source") == "langfuse" and not figures.get("observation_count"):
        return {}
    return dict(figures.get("totals") or {})


def numbers_agree(values: list[Any], tolerance: float) -> bool:
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return True
    try:
        floats = [float(v) for v in present]
    except (TypeError, ValueError):
        return len({str(v) for v in present}) == 1
    return max(floats) - min(floats) <= tolerance


def totals_table(
    app: Mapping[str, Any] | None,
    langfuse: Mapping[str, Any] | None,
    openrouter: Mapping[str, Any] | None,
) -> tuple[str, list[str]]:
    app_totals = totals_of(app)
    lf_totals = totals_of(langfuse)
    or_totals = totals_of(openrouter)
    rows: list[list[Any]] = []
    differing: list[str] = []
    specs = [
        ("calls", "calls", "calls", "calls", TOKEN_TOLERANCE, str),
        ("input tokens", "input_tokens", "input_tokens", "input_tokens", TOKEN_TOLERANCE, str),
        ("output tokens", "output_tokens", "output_tokens", "output_tokens", TOKEN_TOLERANCE, str),
        ("total tokens", "total_tokens", "total_tokens", "total_tokens", TOKEN_TOLERANCE, str),
        ("cost (USD)", "cost_usd", "cost_usd", "cost_usd", COST_TOLERANCE, usd),
    ]
    for label, app_key, lf_key, or_key, tolerance, fmt in specs:
        app_value = app_totals.get(app_key) if app_totals else None
        lf_value = lf_totals.get(lf_key) if lf_totals else None
        or_value = or_totals.get(or_key) if or_totals else None
        present = [v for v in (app_value, lf_value, or_value) if v is not None]
        agree = numbers_agree([app_value, lf_value, or_value], tolerance)
        if not agree:
            differing.append(label)
        if len(present) < 2:
            verdict = "1 source only"
        else:
            verdict = "agree" if agree else "**DIFFER**"
        rows.append(
            [
                label,
                fmt(app_value) if app_value is not None else "n/a",
                fmt(lf_value) if lf_value is not None else "n/a",
                fmt(or_value) if or_value is not None else "n/a",
                verdict,
                "" if not agree else "-",
            ]
        )
    table = md_table(
        ["metric", "app", "Langfuse", "OpenRouter", "verdict", "Diagnosis"], rows
    )
    return table, differing


def join_table(
    app: Mapping[str, Any] | None,
    langfuse: Mapping[str, Any] | None,
    openrouter: Mapping[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    app_calls = {
        str(call.get("response_id")): call
        for call in (app or {}).get("calls", [])
        if call.get("response_id")
    }
    lf_calls: dict[str, list[dict[str, Any]]] = {}
    for call in (langfuse or {}).get("calls", []):
        if call.get("response_id"):
            lf_calls.setdefault(str(call["response_id"]), []).append(dict(call))
    or_calls = {
        str(call.get("response_id")): call
        for call in (openrouter or {}).get("calls", [])
        if call.get("response_id")
    }

    ids = sorted(set(app_calls) | set(lf_calls) | set(or_calls))
    rows: list[list[Any]] = []
    missing: dict[str, list[str]] = {"app": [], "langfuse": [], "openrouter": []}
    for generation_id in ids:
        app_call = app_calls.get(generation_id)
        lf_list = lf_calls.get(generation_id) or []
        lf_call = lf_list[0] if lf_list else None
        or_call = or_calls.get(generation_id)
        if app_call is None:
            missing["app"].append(generation_id)
        if lf_call is None:
            missing["langfuse"].append(generation_id)
        if or_call is None:
            missing["openrouter"].append(generation_id)
        rows.append(
            [
                generation_id,
                (app_call or lf_call or or_call or {}).get("model") or "",
                (app_call or lf_call or {}).get("agent_role") or "",
                _tokens(app_call),
                _tokens(lf_call),
                _tokens(or_call),
                usd((app_call or {}).get("cost_usd")) if app_call else "MISSING",
                usd((lf_call or {}).get("cost_usd")) if lf_call else "MISSING",
                usd((or_call or {}).get("cost_usd")) if or_call else "MISSING",
                "",
            ]
        )
    table = md_table(
        [
            "generation id",
            "model",
            "agent_role",
            "app in/out",
            "LF in/out",
            "OR in/out",
            "app cost",
            "LF cost",
            "OR cost",
            "Diagnosis",
        ],
        rows,
    )
    summary = {
        "joined_ids": len(ids),
        "missing": missing,
        "app_calls_without_id": (app or {}).get("calls_without_response_id"),
        "langfuse_calls_without_id": (langfuse or {}).get("calls_without_response_id"),
    }
    return table, summary


def _tokens(call: Mapping[str, Any] | None) -> str:
    if not call:
        return "MISSING"
    return f"{call.get('input_tokens', 0)}/{call.get('output_tokens', 0)}"


def _or_na(value: Any) -> Any:
    return "n/a" if value is None else value


def duplicates_section(langfuse: Mapping[str, Any] | None) -> tuple[str, int]:
    if not langfuse or not langfuse.get("observation_count"):
        return (
            "**NOT CHECKED** - no Langfuse observations were pulled for this run, "
            "so nothing was examined for a second copy. This is not a pass.",
            0,
        )
    duplicates = dict(langfuse.get("duplicate_response_ids") or {})
    if not duplicates:
        return (
            "No generation id appears on more than one Langfuse observation. "
            "**E1 duplicate check: PASS** for this run.",
            0,
        )
    rows = [
        [generation_id, len(observation_ids), ", ".join(observation_ids)]
        for generation_id, observation_ids in sorted(duplicates.items())
    ]
    return (
        "**E1 VIOLATION** - these generation ids are carried by more than one "
        "Langfuse observation, which means one model call reached Langfuse "
        "twice:\n\n"
        + md_table(["generation id", "copies", "observation ids"], rows),
        len(duplicates),
    )


def langfuse_observation_rows(
    langfuse: Mapping[str, Any] | None, directory: str | None
) -> list[dict[str, Any]]:
    """Per-observation durations, from the figures file or from the raw export.

    `pull_langfuse_run.py` writes them under `durations.observations`. A
    directory pulled before that existed still reconciles, because the raw
    `langfuse-observations.json` beside it is re-derived here with the same
    function - the two cannot disagree, which is the only reason a fallback is
    tolerable at all.
    """

    rows = ((langfuse or {}).get("durations") or {}).get("observations")
    if isinstance(rows, list) and rows:
        return [dict(row) for row in rows if isinstance(row, Mapping)]
    if not directory:
        return []
    path = Path(directory)
    if path.is_dir():
        path = path / "langfuse-observations.json"
    if not path.is_file():
        return []
    return observation_durations(unwrap(read_json(path)))


def _app_span_label(span: Mapping[str, Any], label_key: str) -> str:
    return str(span.get(label_key) or span.get("label") or "(none)")


def _by_label(
    items: Sequence[Mapping[str, Any]], label_of, start_of
) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        grouped.setdefault(label_of(item), []).append(item)
    for entries in grouped.values():
        entries.sort(key=lambda e: (parse_ts(start_of(e)) or parse_ts("1970-01-01T00:00:00Z")))
    return grouped


def duration_pairs(
    app: Mapping[str, Any] | None,
    lf_rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Pair each app span with ONE Langfuse observation of the same role.

    Within a (role, label) the two lists are matched in start-time order, so a
    node that ran twice gives two rows rather than one summed row. Anything
    unmatched is kept and named - "one side only" is a finding, and dropping it
    would let a missing observation look like agreement.
    """

    app_spans = list((app or {}).get("spans") or [])
    out: dict[str, list[dict[str, Any]]] = {}
    for app_kind, lf_role, label_key, _title in DURATION_ROLES:
        app_group = _by_label(
            [s for s in app_spans if s.get("kind") == app_kind],
            lambda s, k=label_key: _app_span_label(s, k),
            lambda s: s.get("start_ts"),
        )
        lf_group = _by_label(
            [r for r in lf_rows if r.get("role") == lf_role],
            lambda r: str(r.get("label") or "(none)"),
            lambda r: r.get("start_time"),
        )
        rows: list[dict[str, Any]] = []
        for label in sorted(set(app_group) | set(lf_group)):
            pairs = zip_longest(app_group.get(label, []), lf_group.get(label, []))
            for index, (app_span, lf_row) in enumerate(pairs, start=1):
                app_seconds = (app_span or {}).get("duration_seconds")
                lf_seconds = (lf_row or {}).get("seconds")
                if app_seconds is None or lf_seconds is None:
                    delta: float | None = None
                    if app_span is None:
                        verdict = "Langfuse only"
                    elif lf_row is None:
                        verdict = "app only"
                    else:
                        verdict = "one side has no duration"
                else:
                    delta = abs(float(app_seconds) - float(lf_seconds))
                    verdict = (
                        "within 1 s"
                        if delta <= DURATION_TOLERANCE_SECONDS
                        else "**OVER 1 s**"
                    )
                rows.append(
                    {
                        "role": lf_role,
                        "label": label,
                        "occurrence": index,
                        "app_seconds": app_seconds,
                        "langfuse_seconds": lf_seconds,
                        "delta": delta,
                        "verdict": verdict,
                        "observation_id": (lf_row or {}).get("id"),
                        "rank_seconds": max(
                            float(lf_seconds or 0.0), float(app_seconds or 0.0)
                        ),
                    }
                )
        rows.sort(key=lambda r: -r["rank_seconds"])
        out[lf_role] = rows
    return out


def generation_count_section(
    app: Mapping[str, Any] | None, langfuse: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any]]:
    """E1(a): GENERATION observations in the session vs the app's LLM calls.

    **The app figure is ATTEMPTS, not completions**, and that correction is
    RECONCILIATION.md discrepancy 3. It used the after-frame count -
    `pull_app_run.py`'s `calls` list, one entry per call that produced tokens -
    which is 0 on a run whose every call was refused. `builder-agentfail` made
    six calls, all rejected 400 by the provider: six LLM **error** frames, six
    ERROR generations in Langfuse, and this check printed **FAIL: 0 app calls
    vs 6 generations** over a pair that agrees perfectly. One generation is
    written per call ATTEMPT, successful or failed, so attempts is the
    comparator, and the split is printed on both sides so a reader sees the
    0 + 6 = 6 rather than having to reconstruct it.

    A Langfuse count above the app's attempts is a second copy and reads FAIL;
    below is a SHORTFALL, which is a loss rather than an E1 failure and is
    labelled as one instead of being quietly accepted.
    """

    if not langfuse or not langfuse.get("observation_count"):
        return (
            "**NOT CHECKED** - no Langfuse observations were pulled for this run.",
            {"langfuse": None, "app": None, "verdict": "NOT CHECKED"},
        )

    lf_calls = list(langfuse.get("calls") or [])
    lf_generations = int(
        (langfuse.get("observation_types") or {}).get("GENERATION")
        or (langfuse.get("totals") or {}).get("calls")
        or 0
    )
    # A refused call is a GENERATION at level ERROR; everything else succeeded
    # as far as Langfuse is concerned.
    lf_failed = sum(1 for call in lf_calls if str(call.get("level") or "") == "ERROR")
    lf_ok = (len(lf_calls) - lf_failed) if lf_calls else None
    if lf_calls and len(lf_calls) != lf_generations:
        # The GENERATION type count is the authority; the calls list is what
        # the split is derived from, and a disagreement is worth showing.
        lf_ok = lf_generations - lf_failed

    app_ok: int | None = None
    app_failed: int | None = None
    if app:
        calls = app.get("calls")
        if isinstance(calls, list):
            app_ok = len(calls)
        elif (app.get("totals") or {}).get("calls") is not None:
            app_ok = int((app.get("totals") or {}).get("calls"))
        failed = app.get("failed_calls")
        if isinstance(failed, (list, tuple)):
            app_failed = len(failed)
        elif isinstance(failed, int):
            app_failed = failed
    app_attempts = (
        None if app_ok is None else app_ok + int(app_failed or 0)
    )

    if app_attempts is None:
        verdict = "NOT CHECKED"
        note = "no app figures, so there is nothing to compare the count against."
    elif lf_generations == app_attempts:
        verdict = "PASS"
        note = (
            "one GENERATION observation per LLM call ATTEMPT: no second copy "
            "inside the session."
        )
    elif lf_generations > app_attempts:
        verdict = "**FAIL**"
        note = (
            f"{lf_generations - app_attempts} MORE generation(s) in Langfuse than "
            "the app attempted calls - that is a duplicate report, which is what "
            "E1 forbids."
        )
    else:
        verdict = "**SHORTFALL**"
        note = (
            f"{app_attempts - lf_generations} call attempt(s) the app made are "
            "missing from Langfuse. Not a duplicate, so not an E1 failure - a "
            "loss, which D3/E5 own. Read it with the drop counter in the "
            "exporter's summary line."
        )
    if (
        verdict == "PASS"
        and app_failed is not None
        and lf_ok is not None
        and (app_ok, app_failed) != (lf_ok, lf_failed)
    ):
        note += (
            f" The totals agree; the ok/failed SPLIT does not "
            f"({app_ok}/{app_failed} app against {lf_ok}/{lf_failed} Langfuse), "
            "which is a level-mapping question rather than a count one."
        )

    table = md_table(
        ["measurement", "app", "Langfuse"],
        [
            [
                "calls that COMPLETED (app: LLM after-frames; LF: level != ERROR)",
                _or_na(app_ok),
                _or_na(lf_ok),
            ],
            [
                "calls that FAILED (app: LLM error frames; LF: level == ERROR)",
                _or_na(app_failed),
                _or_na(lf_failed),
            ],
            [
                "**call ATTEMPTS / GENERATION observations** - the comparator",
                _or_na(app_attempts),
                lf_generations,
            ],
            ["verdict", verdict, ""],
        ],
    )
    return f"{table}\n\n{note}", {
        "langfuse": lf_generations,
        "langfuse_ok": lf_ok,
        "langfuse_failed": lf_failed,
        "app": app_attempts,
        "app_ok": app_ok,
        "app_failed": app_failed,
        "verdict": verdict,
    }



def _count_of(value: Any) -> Any:
    """A count, whatever shape the figure arrived in - never a rendered list."""

    if value is None:
        return "n/a"
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return value


def _has_key(payload: Any, key: str) -> bool:
    """Is `key` present anywhere in this structure, at any depth?"""

    if isinstance(payload, Mapping):
        if key in payload:
            return True
        return any(_has_key(value, key) for value in payload.values())
    if isinstance(payload, (list, tuple)):
        return any(_has_key(item, key) for item in payload)
    return False


def second_trace_section(
    run_id: str,
    app: Mapping[str, Any] | None,
    langfuse: Mapping[str, Any] | None,
    *,
    window_minutes: float,
    timeout: float,
    enabled: bool,
) -> tuple[str, dict[str, Any]]:
    """E1(c): is there a SECOND trace for this run, from OpenRouter's broadcast?

    Nothing inside the session can answer this. OpenRouter's own Langfuse
    destination writes a trace with **no** `sessionId` (the audit measured
    `sessionId` null on all 40 of them), so a call reported twice - once by the
    app's exporter and once by OpenRouter - produces two traces that never meet.
    The tell is `metadata["openrouter.api_key_name"]`, a key NAME and not a key
    value, on a trace inside the run's own time window.

    The answer must be 0 after the OpenRouter-side exclusion. A window with no
    such trace is evidence; a window that could not be queried is NOT.
    """

    result: dict[str, Any] = {
        "checked": False,
        "window_minutes": window_minutes,
        "from": None,
        "to": None,
        "traces_in_window": 0,
        "openrouter_broadcast_traces": 0,
        "matches": [],
    }
    started = parse_ts((langfuse or {}).get("started_at")) or parse_ts(
        (app or {}).get("started_at")
    )
    ended = parse_ts((langfuse or {}).get("ended_at")) or parse_ts(
        (app or {}).get("completed_at")
    )
    if started is None or ended is None:
        return (
            "**NOT CHECKED** - neither source carries a start and an end time, so "
            "there is no window to scan. Not a pass.",
            result,
        )
    window = timedelta(minutes=max(0.0, window_minutes))
    from_ts = (started - window).isoformat().replace("+00:00", "Z")
    to_ts = (ended + window).isoformat().replace("+00:00", "Z")
    result["from"], result["to"] = from_ts, to_ts

    if not enabled:
        return (
            f"**NOT CHECKED** - `--no-network` was given. The window that would "
            f"have been scanned is {from_ts} to {to_ts}. Not a pass.",
            result,
        )
    base = env_optional("LANGFUSE_BASE_URL")
    public = env_optional("LANGFUSE_PUBLIC_KEY")
    secret = env_optional("LANGFUSE_SECRET_KEY")
    if not (base and public and secret):
        return (
            "**NOT CHECKED** - no Langfuse credentials in the environment, so the "
            f"window {from_ts} to {to_ts} was never queried. Not a pass.",
            result,
        )

    own_trace_ids = {str(i) for i in ((langfuse or {}).get("trace_ids") or [])}
    try:
        with Http(
            base,
            auth=(public, secret),
            timeout=timeout,
            retries=6,
            backoff=2.0,
        ) as http:
            traces = fetch_all(
                http,
                "/api/public/traces",
                {"fromTimestamp": from_ts, "toTimestamp": to_ts},
            )
    except HttpError as error:
        return (
            f"**NOT CHECKED** - the Langfuse query failed (HTTP {error.status}). "
            "Not a pass.",
            result,
        )

    result["checked"] = True
    result["traces_in_window"] = len(traces)
    matches = []
    for trace in traces:
        if str(trace.get("id")) in own_trace_ids:
            continue
        if str(trace.get("sessionId") or "") == run_id:
            continue
        if _has_key(trace.get("metadata"), OPENROUTER_BROADCAST_KEY):
            matches.append(
                {
                    "id": trace.get("id"),
                    "name": trace.get("name"),
                    "timestamp": trace.get("timestamp"),
                    "sessionId": trace.get("sessionId"),
                }
            )
    result["openrouter_broadcast_traces"] = len(matches)
    result["matches"] = matches

    header = md_table(
        ["measurement", "value"],
        [
            ["window scanned", f"{from_ts} .. {to_ts} (+/-{window_minutes:g} min)"],
            ["traces in the window", len(traces)],
            ["this run's own traces, excluded", len(own_trace_ids)],
            [
                f"OTHER traces carrying `{OPENROUTER_BROADCAST_KEY}`",
                f"**{len(matches)}**" if matches else "0",
            ],
            ["verdict", "**FAIL - a second report**" if matches else "PASS"],
        ],
    )
    if not matches:
        return (
            header
            + "\n\nNo second trace carries the OpenRouter broadcast's own metadata "
            "key in this window, so this run was reported once.",
            result,
        )
    return (
        header
        + "\n\n**E1 VIOLATION** - these traces are not in this run's session and "
        "carry the OpenRouter broadcast's metadata key, so the same calls were "
        "reported twice:\n\n"
        + md_table(
            ["trace id", "name", "timestamp", "sessionId"],
            [
                [m["id"], m["name"], m["timestamp"], m["sessionId"] or "(none)"]
                for m in matches
            ],
        ),
        result,
    )


def durations_section(
    app: Mapping[str, Any] | None,
    langfuse: Mapping[str, Any] | None,
    lf_rows: Sequence[Mapping[str, Any]],
) -> tuple[str, dict[str, Any]]:
    if not app or not langfuse:
        return (
            "Not computed: both an app and a Langfuse directory are needed.",
            {"over_tolerance": None, "slowest": {}},
        )
    if not lf_rows:
        return (
            "**NOT CHECKED** - the Langfuse directory carries no per-observation "
            "durations (`durations.observations` in `langfuse-figures.json`, or a "
            "`langfuse-observations.json` beside it). Not a pass.",
            {"over_tolerance": None, "slowest": {}},
        )

    pairs = duration_pairs(app, lf_rows)
    blocks: list[str] = [
        "Every row is ONE observation against ONE app span, matched on role, "
        "label and start order. A child's duration is never added to its "
        "parent's: the contract nests node -> task -> agent -> tool over one "
        "call, and summing that tree turns a 2.006 s agent into 6.014 s.",
        "",
        "Slowest first, which is the ranking B4 asks for.",
    ]
    slowest: dict[str, Any] = {}
    over = 0
    for _app_kind, lf_role, _label_key, title in DURATION_ROLES:
        rows = pairs.get(lf_role, [])
        over += sum(1 for row in rows if row["verdict"] == "**OVER 1 s**")
        ranked = [r for r in rows if r.get("langfuse_seconds") is not None]
        if ranked:
            slowest[lf_role] = {
                "label": ranked[0]["label"],
                "seconds": ranked[0]["langfuse_seconds"],
                "app_seconds": ranked[0]["app_seconds"],
            }
        blocks.append(
            f"### {title} - one row per observation\n\n"
            + md_table(
                [
                    "rank",
                    "label",
                    "#",
                    "app s",
                    "Langfuse s",
                    "delta s",
                    "verdict",
                    "observation id",
                    "Diagnosis",
                ],
                [
                    [
                        position,
                        row["label"],
                        row["occurrence"],
                        secs(row["app_seconds"]),
                        secs(row["langfuse_seconds"]),
                        secs(row["delta"]),
                        row["verdict"],
                        row["observation_id"] or "-",
                        "",
                    ]
                    for position, row in enumerate(rows, start=1)
                ],
            )
        )
    headline = md_table(
        ["the slowest", "label", "Langfuse s", "app s"],
        [
            [
                role,
                (slowest.get(role) or {}).get("label", "(none observed)"),
                secs((slowest.get(role) or {}).get("seconds")),
                secs((slowest.get(role) or {}).get("app_seconds")),
            ]
            for role in ("agent", "task", "tool")
        ],
    )
    body = "\n\n".join(
        [
            "\n".join(blocks[:3]),
            "#### The B4 answer",
            headline,
            f"Rows outside the {DURATION_TOLERANCE_SECONDS:.0f} s tolerance: "
            f"**{over}**.",
            *blocks[3:],
        ]
    )
    return body, {"over_tolerance": over, "slowest": slowest}


def render(
    app: Mapping[str, Any] | None,
    langfuse: Mapping[str, Any] | None,
    openrouter: Mapping[str, Any] | None,
    *,
    langfuse_dir: str | None = None,
    window_minutes: float = 10.0,
    network: bool = True,
    timeout: float = 60.0,
) -> tuple[str, str]:
    run_id = (
        (app or {}).get("run_id")
        or (langfuse or {}).get("run_id")
        or "unknown-run"
    )
    totals, differing = totals_table(app, langfuse, openrouter)
    join, join_summary = join_table(app, langfuse, openrouter)
    duplicates, duplicate_count = duplicates_section(langfuse)
    counts, _counts_summary = generation_count_section(app, langfuse)
    second_trace, _second_summary = second_trace_section(
        str(run_id),
        app,
        langfuse,
        window_minutes=window_minutes,
        timeout=timeout,
        enabled=network,
    )
    lf_rows = langfuse_observation_rows(langfuse, langfuse_dir)
    durations, _durations_summary = durations_section(app, langfuse, lf_rows)

    missing_note = []
    for side, ids in join_summary["missing"].items():
        if ids:
            missing_note.append(
                f"- **{len(ids)}** generation id(s) absent from **{side}**: "
                + ", ".join(f"`{i}`" for i in ids[:20])
                + (" ..." if len(ids) > 20 else "")
            )
    if not join_summary["joined_ids"]:
        missing_note = [
            "- **no generation ids to join.** Not a pass: the join is the only check "
            "that can find a call present in two sources and absent from the third, "
            "and it did not run.",
        ]
    elif not missing_note:
        missing_note = ["- every joined generation id is present in all three sources."]

    lines = [
        f"# Reconciliation - run `{run_id}`",
        "",
        f"Generated {now_iso()} by `scripts/observability/reconcile.py`.",
        "DoD rows **E1** and **E5**. Every **Diagnosis** cell is empty on purpose:",
        "the script measures, a verifier names the cause.",
        "",
        "| source | what it is | file |",
        "| --- | --- | --- |",
        f"| app | the run's own frames and snapshot | `{(app or {}).get('base_url', 'n/a')}` |",
        f"| Langfuse | session `{(langfuse or {}).get('session_id') or 'not found'}`, "
        f"{(langfuse or {}).get('observation_count', 0)} observations | public API |",
        f"| OpenRouter | {(openrouter or {}).get('found', 0)} of "
        f"{(openrouter or {}).get('requested', 0)} generation records | "
        "`GET /api/v1/generation?id=` |",
        "",
        "## 1. Totals",
        "",
        totals,
        "",
    ]
    if differing:
        lines += [
            "Differing metrics needing a diagnosis: "
            + ", ".join(f"**{name}**" for name in differing),
            "",
            "Causes worth ruling out before writing one, each measured elsewhere in",
            "this repository:",
            "",
            "- OpenRouter's **native** token counts are not the app's provider-reported",
            "  counts; its normalised `tokens_prompt` differ again "
            "(`openrouter.md` reports both).",
            "- The app's cost is `compute_cost_usd`, a local price table; OpenRouter's is",
            "  billed. `:nitro` routes on speed and the spread across endpoints for one",
            "  model was measured at 3.6x (CLAUDE.md, OpenRouter MCP section).",
            "- Embeddings, rerank and Firecrawl raise no LLM event: absent from all three",
            "  columns, not just one.",
            "- A failed call bills nothing and emits no TOKEN frame, but may still appear",
            "  as an ERROR generation in Langfuse.",
            "",
        ]
    lines += [
        "## 2. E1 - nothing reaches Langfuse twice",
        "",
        "### 2a. GENERATION observations against the app's LLM calls",
        "",
        counts,
        "",
        "### 2b. A generation id carried by two Langfuse observations",
        "",
        duplicates,
        "",
        "### 2c. A SECOND trace in the same window, from OpenRouter's broadcast",
        "",
        second_trace,
        "",
        "## 3. Per-call join on `response_id`",
        "",
        *missing_note,
        "",
        f"- app calls carrying no generation id: "
        f"{_or_na(join_summary['app_calls_without_id'])} "
        "(expected to be every call on a SYNTHETIC run - the double writes "
        "`response_id: None`)",
        f"- Langfuse generations carrying no `metadata.response_id`: "
        f"{_or_na(join_summary['langfuse_calls_without_id'])}",
        "",
        join,
        "",
        "## 4. Durations, app frames versus Langfuse spans (B4)",
        "",
        durations,
        "",
        f"Langfuse observations paired: {len(lf_rows)} available.",
        "",
        "## 5. Diagnosis notes",
        "",
        "_Verifier: one line per differing cell above. E5 accepts no cell left blank._",
        "",
    ]
    body = "\n".join(lines)
    durations_doc = "\n".join(
        [
            f"# Durations - run `{run_id}`",
            "",
            "DoD B4: Langfuse spans against the app's own frame timestamps.",
            f"Generated {now_iso()}. Tolerance in the verdict column: "
            f"{DURATION_TOLERANCE_SECONDS:.0f} s.",
            "",
            durations,
            "",
        ]
    )
    return body, durations_doc


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env()
    app = load(args.app, "app-figures.json")
    langfuse = load(args.langfuse, "langfuse-figures.json")
    openrouter = load(args.openrouter, "openrouter-figures.json")
    if app is None:
        print(f"no app-figures.json under {args.app}", file=sys.stderr)
        return 2
    if langfuse is None:
        print(
            f"no langfuse-figures.json under {args.langfuse!r}; the Langfuse "
            "column will read n/a",
            file=sys.stderr,
        )
    body, durations_doc = render(
        app,
        langfuse,
        openrouter,
        langfuse_dir=args.langfuse,
        window_minutes=args.window_minutes,
        network=not args.no_network,
        timeout=args.timeout,
    )

    # Both files are written through the redactor for the same reason
    # `pull_langfuse_run.py` is: every figure here was copied out of a Langfuse
    # response, and F3 is checked over the whole tree, not per script.
    out_path = Path(args.out)
    _, redacted_body = write_text_redacted(out_path.parent, out_path.name, body)
    print(body)
    print(f"wrote {out_path}", file=sys.stderr)
    redacted_durations = 0
    if args.durations_out:
        durations_path = Path(args.durations_out)
        _, redacted_durations = write_text_redacted(
            durations_path.parent, durations_path.name, durations_doc
        )
        print(f"wrote {durations_path}", file=sys.stderr)
    print(
        f"redaction: {redacted_body + redacted_durations} credential-shaped value(s) "
        "replaced before writing (F3)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
