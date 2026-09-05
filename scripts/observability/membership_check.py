"""Check that no observation sits in the wrong run's trace.

Serves DoD rows **A2** and **D5**: two runs launched concurrently must produce
two sessions with zero cross-membership - every observation's `metadata.run_id`
equal to the `sessionId` of the trace it sits in.

Two distinct failures are counted separately, because they have different
causes and a single "mismatches" number would hide the interesting one:

* **MISMATCH** - the observation's `metadata.run_id` is not this trace's
  session id. Cause: the exporter's per-run scope leaked, or an observation was
  attached to a trace id it does not belong to.
* **CROSS-MEMBERSHIP** - a mismatch whose `run_id` is one of the OTHER run ids
  under test. That is the concurrency bug A2 is actually about: run A's frames
  landing inside run B's trace. A mismatch naming an unrelated id is a
  different (still real) defect.

A third is reported and is not a failure by itself: **MISSING** - an
observation carrying no `run_id` metadata at all. `TRACE-CONTRACT.md` §3 says
every observation carries it, so a non-zero count here is a contract gap for
the reviewer rather than a leak.

Exits 1 if any mismatch (of either kind) is found, 0 otherwise.

Usage:

    .venv/Scripts/python.exe scripts/observability/membership_check.py \
        --run-id RUN_A --run-id RUN_B --out DIR

    # or over directories already pulled by pull_langfuse_run.py:
    .venv/Scripts/python.exe scripts/observability/membership_check.py \
        --from-dir evidence/proof/run-a --from-dir evidence/proof/run-b --out DIR
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    Http,
    ensure_dir,
    env_required,
    load_env,
    md_table,
    now_iso,
    read_json,
    write_json_redacted,
    write_text_redacted,
)
from pull_langfuse_run import fetch_all, metadata_of, unwrap  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk every observation of each session and check its run_id.",
    )
    parser.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="an app run id (= Langfuse sessionId). Repeat for each run.",
    )
    parser.add_argument(
        "--from-dir",
        action="append",
        default=[],
        help="a directory written by pull_langfuse_run.py, used instead of fetching",
    )
    parser.add_argument("--out", required=True, help="directory to write into")
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args(argv)


def load_from_dir(directory: str) -> dict[str, Any]:
    path = Path(directory)
    traces = unwrap(read_json(path / "langfuse-traces.json"))
    observations = unwrap(read_json(path / "langfuse-observations.json"))
    figures_path = path / "langfuse-figures.json"
    run_id = ""
    if figures_path.is_file():
        run_id = str(read_json(figures_path).get("run_id") or "")
    if not run_id:
        run_id = str((traces[0].get("sessionId") if traces else "") or path.name)
    return {"run_id": run_id, "traces": traces, "observations": observations, "source": str(path)}


def fetch_run(http: Http, run_id: str) -> dict[str, Any]:
    traces: list[dict[str, Any]] = []
    status, body = http.get(f"/api/public/sessions/{run_id}", allow_status=(404,))
    session_found = status == 200
    if session_found and isinstance(body, Mapping):
        traces = [t for t in unwrap({"data": body.get("traces")}) if t]
    known = {str(t.get("id")) for t in traces}
    for trace in fetch_all(http, "/api/public/traces", {"sessionId": run_id}):
        if str(trace.get("id")) not in known:
            traces.append(trace)
    observations: list[dict[str, Any]] = []
    for trace in traces:
        observations.extend(
            fetch_all(http, "/api/public/observations", {"traceId": str(trace.get("id"))})
        )
    return {
        "run_id": run_id,
        "session_found": session_found,
        "traces": traces,
        "observations": observations,
        "source": "langfuse API",
    }


def check(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    all_run_ids = {str(run["run_id"]) for run in runs}
    report: dict[str, Any] = {
        "generated_at": now_iso(),
        "run_ids": sorted(all_run_ids),
        "runs": [],
        "mismatches": [],
        "cross_membership": [],
        "missing_run_id": [],
    }
    for run in runs:
        run_id = str(run["run_id"])
        traces = run.get("traces") or []
        observations = run.get("observations") or []
        session_by_trace = {
            str(trace.get("id")): str(trace.get("sessionId") or "") for trace in traces
        }
        traces_without_session = [
            str(trace.get("id"))
            for trace in traces
            if not trace.get("sessionId")
        ]
        traces_wrong_session = [
            {"trace_id": tid, "sessionId": sid}
            for tid, sid in session_by_trace.items()
            if sid and sid != run_id
        ]
        mismatched = 0
        missing = 0
        for observation in observations:
            trace_id = str(observation.get("traceId") or "")
            # The trace's OWN sessionId is the authority, so an observation is
            # judged against where it actually sits rather than against the run
            # id the caller typed.
            expected = session_by_trace.get(trace_id, run_id) or run_id
            actual = metadata_of(observation).get("run_id")
            entry = {
                "observation_id": observation.get("id"),
                "type": observation.get("type"),
                "name": observation.get("name"),
                "trace_id": trace_id,
                "trace_session_id": expected,
                "metadata_run_id": actual,
                "checked_under": run_id,
            }
            if actual in (None, ""):
                missing += 1
                report["missing_run_id"].append(entry)
                continue
            if str(actual) != str(expected):
                mismatched += 1
                report["mismatches"].append(entry)
                if str(actual) in all_run_ids:
                    report["cross_membership"].append(entry)
        report["runs"].append(
            {
                "run_id": run_id,
                "source": run.get("source"),
                "session_found": run.get("session_found"),
                "traces": len(traces),
                "trace_ids": sorted(session_by_trace),
                "observations": len(observations),
                "mismatched": mismatched,
                "missing_run_id": missing,
                "traces_without_session_id": traces_without_session,
                "traces_with_a_different_session_id": traces_wrong_session,
            }
        )
    report["mismatch_count"] = len(report["mismatches"])
    report["cross_membership_count"] = len(report["cross_membership"])
    report["missing_run_id_count"] = len(report["missing_run_id"])
    report["verdict"] = "PASS" if report["mismatch_count"] == 0 else "FAIL"
    # The A2 artifact is read by somebody looking for one number. Totals over
    # ALL the sessions given, so "every observation was walked" is a figure on
    # the page rather than a claim about the code.
    report["totals"] = {
        "sessions": len(report["runs"]),
        "traces": sum(int(run["traces"]) for run in report["runs"]),
        "observations": sum(int(run["observations"]) for run in report["runs"]),
        "mismatches": report["mismatch_count"],
        "cross_membership": report["cross_membership_count"],
        "missing_run_id": report["missing_run_id_count"],
        "verdict": report["verdict"],
    }
    return report


def render(report: Mapping[str, Any]) -> str:
    totals = report.get("totals") or {}
    lines = [
        "Membership check - DoD A2 / D5",
        "=" * 60,
        f"checked at: {report['generated_at']}",
        f"run ids:    {', '.join(report['run_ids'])}",
        "",
        # One line a reader can quote, over EVERY observation of EVERY session
        # given: A2 asks for a script that walks them all, so the walk's size
        # belongs on the page beside its verdict.
        "TOTALS: "
        f"sessions={totals.get('sessions')} "
        f"traces={totals.get('traces')} "
        f"observations={totals.get('observations')} "
        f"mismatches={totals.get('mismatches')} "
        f"cross-membership={totals.get('cross_membership')} "
        f"no-run_id={totals.get('missing_run_id')} "
        f"VERDICT={totals.get('verdict')}",
        "",
        f"MISMATCHES (must be 0):        {report['mismatch_count']}",
        f"CROSS-MEMBERSHIP (must be 0):  {report['cross_membership_count']}",
        f"observations with no run_id:   {report['missing_run_id_count']}",
        f"observations walked:           {totals.get('observations')}",
        f"VERDICT: {report['verdict']}",
        "",
        md_table(
            ["run_id", "session", "traces", "observations", "mismatched", "no run_id"],
            [
                [
                    run["run_id"],
                    "found" if run.get("session_found") else ("dir" if run.get("source") != "langfuse API" else "**MISSING**"),
                    run["traces"],
                    run["observations"],
                    run["mismatched"],
                    run["missing_run_id"],
                ]
                for run in report["runs"]
            ],
        ),
        "",
    ]
    for run in report["runs"]:
        if run["traces_without_session_id"]:
            lines.append(
                f"NOTE {run['run_id']}: traces with NO sessionId: "
                + ", ".join(run["traces_without_session_id"])
            )
        if run["traces_with_a_different_session_id"]:
            lines.append(
                f"NOTE {run['run_id']}: traces whose sessionId is something else: "
                + ", ".join(
                    f"{t['trace_id']}->{t['sessionId']}"
                    for t in run["traces_with_a_different_session_id"]
                )
            )
    if report["mismatches"]:
        lines += ["", "MISMATCHES", "-" * 60]
        for entry in report["mismatches"]:
            lines.append(
                f"  {entry['type']} {entry['name']} id={entry['observation_id']}"
            )
            lines.append(
                f"    trace {entry['trace_id']} sessionId={entry['trace_session_id']} "
                f"but metadata.run_id={entry['metadata_run_id']}"
            )
    if report["cross_membership"]:
        lines += ["", "CROSS-MEMBERSHIP (one run's observation inside another's trace)", "-" * 60]
        for entry in report["cross_membership"]:
            lines.append(
                f"  {entry['observation_id']} carries run_id={entry['metadata_run_id']} "
                f"inside the trace of {entry['trace_session_id']}"
            )
    if report["missing_run_id"]:
        lines += [
            "",
            "OBSERVATIONS WITH NO run_id METADATA",
            "(TRACE-CONTRACT section 3 requires it on every observation; this is a",
            " contract gap for the reviewer, not a leak, and does not fail this check)",
            "-" * 60,
        ]
        for entry in report["missing_run_id"][:100]:
            lines.append(
                f"  {entry['type']} {entry['name']} id={entry['observation_id']} "
                f"trace={entry['trace_id']}"
            )
        if len(report["missing_run_id"]) > 100:
            lines.append(f"  ... and {len(report['missing_run_id']) - 100} more")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env()
    if not args.run_id and not args.from_dir:
        print("give at least one --run-id or --from-dir", file=sys.stderr)
        return 2
    out_dir = ensure_dir(args.out)

    runs: list[dict[str, Any]] = [load_from_dir(d) for d in args.from_dir]
    if args.run_id:
        base = env_required("LANGFUSE_BASE_URL")
        public = env_required("LANGFUSE_PUBLIC_KEY")
        secret = env_required("LANGFUSE_SECRET_KEY")
        with Http(base, auth=(public, secret), timeout=args.timeout) as http:
            for run_id in args.run_id:
                runs.append(fetch_run(http, run_id))

    report = check(runs)
    text = render(report)
    # Redacted on the way out for the same reason `pull_langfuse_run.py` is:
    # this report is built out of Langfuse API objects, and F3 is checked over
    # the whole evidence tree rather than per script.
    _, text_redactions = write_text_redacted(out_dir, "membership-check.txt", text)
    _, json_redactions = write_json_redacted(out_dir, "membership-check.json", report)
    print(text)
    print(
        f"redaction: {text_redactions + json_redactions} credential-shaped value(s) "
        "replaced before writing (F3)",
        file=sys.stderr,
    )
    return 1 if report["mismatch_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
