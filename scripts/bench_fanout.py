#!/usr/bin/env python
"""F42 performance harness: fan-out speedup, peak RSS, gate latency, frame loss.

Two modes, one harness:

  synthetic (default)  Real ValidatorFlow orchestration driven by injected crew
                       doubles that sleep instead of calling paid models. Zero
                       network calls, zero cost, CI-safe. Measures the fan-out
                       machinery's own overhead, NOT real branch latency.

  --live               Same harness, real crew factories: OpenRouter, Firecrawl,
                       Hacker News and GitHub. THIS COSTS MONEY. It is the run
                       that produces the numbers for PRD section 13.

Synthetic:
    .\\.venv\\Scripts\\python.exe scripts\\bench_fanout.py

Live (paid; requires explicit consent):
    .\\.venv\\Scripts\\python.exe scripts\\bench_fanout.py --live --yes --runs 5

Exit status: 0 all targets met, 1 a target missed, 2 a target unmeasured.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

if __package__ in (None, ""):  # allow `python scripts/bench_fanout.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.perf_metrics import (  # noqa: E402 - imports no CrewAI code
    DEFAULT_RUNS_PER_ARM,
    DEFAULT_SAMPLE_INTERVAL_S,
    INCOMPLETE,
    MET,
    MISSED,
    TargetResult,
    advisory_concurrency,
    advisory_overhead,
    disable_crewai_telemetry,
    evaluate_frame_integrity,
    evaluate_gate_latency,
    evaluate_peak_rss,
    evaluate_speedup,
    overall_status,
    render_table,
    render_verdict_block,
    select_memory_probe,
    summarize,
    telemetry_state,
)

# Synthetic mode must make zero network calls, and CrewAI's telemetry exporter
# posts over HTTP. The decision is taken from raw argv before any CrewAI import
# so nothing has been constructed yet. A --live run is left exactly as the
# operator's environment configured it: suppressing a serial cost that a real
# deployment pays would flatter the live speedup ratio.
if "--live" not in sys.argv[1:]:
    disable_crewai_telemetry()

from scripts.perf_arms import (  # noqa: E402 - must follow the telemetry decision
    DEFAULT_BRANCH_SECONDS,
    DEFAULT_IDEA,
    DEFAULT_STAGE_SECONDS,
    SEQUENTIAL_ARM_CAVEAT,
    RunOutcome,
    build_fixtures,
    live_factories,
    measure_gate_resume,
    run_arm_once,
    synthetic_factories,
)

SCHEMA = "brief-crew.perf.fanout/1"
RESERVED_OUTPUTS = {"brief.md", "last_run.json", "validation.md"}
SYNTHETIC_CAVEAT = (
    "SYNTHETIC MODE measures orchestration overhead only. Branch durations are "
    "fixed sleeps chosen by --branch-seconds, so the speedup ratio is a property of "
    "that flag and not of the system under test. It is reported as ADVISORY here and "
    "does not pass or fail the PRD target. It says nothing about whether real "
    "Firecrawl / HN / GitHub branches will hit 1.8x. Only --live answers PRD Q1."
)
SYNTHETIC_SPEEDUP_REASON = (
    "Advisory in synthetic mode: the ratio scales with --branch-seconds. See the "
    "serial overhead row for the number that does transfer to a live run."
)
SYNTHETIC_RSS_CAVEAT = (
    "Synthetic peak RSS is a FLOOR. Real crews add LLM clients, HTTP connection "
    "pools, Firecrawl/HN/GitHub payloads and Pinecone/Cohere buffers on top of it."
)


def _branch_seconds(raw: str) -> tuple[float, float, float]:
    parts = [float(piece) for piece in str(raw).split(",") if piece.strip()]
    if len(parts) == 1:
        return (parts[0], parts[0], parts[0])
    if len(parts) == 3:
        return (parts[0], parts[1], parts[2])
    raise argparse.ArgumentTypeError(
        "--branch-seconds takes one value or three comma-separated values "
        "(market,sentiment,feasibility)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure ValidatorFlow fan-out speedup, peak RSS, gate latency and frame loss.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the real paid crew factories instead of no-cost doubles.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm a paid --live run without an interactive prompt.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS_PER_ARM,
        help=f"Measured runs per arm (PRD asks for {DEFAULT_RUNS_PER_ARM}).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=None,
        help="Discarded warm-up runs per arm. Default 1 synthetic, 0 live.",
    )
    parser.add_argument("--idea", default=DEFAULT_IDEA, help="Startup idea to validate.")
    parser.add_argument(
        "--branch-seconds",
        type=_branch_seconds,
        default=DEFAULT_BRANCH_SECONDS,
        help="Synthetic only: seconds each research branch sleeps (one value, or "
        "market,sentiment,feasibility).",
    )
    parser.add_argument(
        "--stage-seconds",
        type=float,
        default=DEFAULT_STAGE_SECONDS,
        help="Synthetic only: seconds for each serial stage (scope, synthesis, report).",
    )
    parser.add_argument(
        "--gate-rounds",
        type=int,
        default=3,
        help="Gated pause/resume round trips to time. 0 skips the gate probe.",
    )
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=DEFAULT_SAMPLE_INTERVAL_S,
        help="Seconds between resident-memory samples.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output") / "perf",
        help="Directory for JSON and text results. Never output/ itself.",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always exit 0, even when a target is missed.",
    )
    return parser


def _confirm_live(args: argparse.Namespace) -> None:
    if args.yes:
        return
    banner = (
        "\n--live runs the real six-agent validator against OpenRouter, Firecrawl, "
        f"Hacker News and GitHub.\nThis will spend money: {args.runs * 2} full runs "
        f"plus {args.warmup * 2} warm-up runs.\n"
    )
    if not sys.stdin.isatty():
        raise SystemExit(banner + "Refusing to start non-interactively without --yes.")
    print(banner)
    try:
        answer = input("Type LIVE to continue: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(
            "No answer on stdin; refusing to start a paid run without --yes."
        ) from None
    if answer != "LIVE":
        raise SystemExit("Aborted; nothing was spent.")


def _environment(memory_probe_name: str) -> dict[str, Any]:
    try:
        from crewai import __version__ as crewai_version
    except Exception:  # noqa: BLE001 - version reporting must never break a run
        crewai_version = "unknown"
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "crewai": crewai_version,
        "memory_probe": memory_probe_name,
        "crewai_telemetry_env": telemetry_state(),
        "cwd": str(Path.cwd()),
    }


def _run_arms(args: argparse.Namespace, base_factories: Any, memory_probe: Any) -> dict[str, list[RunOutcome]]:
    """Interleave the arms so machine drift cannot favour one of them."""
    runs_dir = args.out / "runs"
    results: dict[str, list[RunOutcome]] = {"parallel": [], "sequential": []}

    def execute(arm: str, index: int, measured: bool) -> None:
        outcome = run_arm_once(
            arm=arm,
            index=index,
            base_factories=base_factories,
            serialize=arm == "sequential",
            idea=args.idea,
            output_path=runs_dir / f"{arm}-{index:02d}-validation.md",
            memory_probe=memory_probe,
            sample_interval_s=args.sample_interval,
            isolate_cache=not args.live,
        )
        tag = "warmup " if not measured else ""
        status = "ok" if outcome.ok else f"FAILED {outcome.error}"
        print(
            f"  {tag}{arm:<10} #{index:<2} {outcome.wall_seconds:7.3f}s  "
            f"concurrency={outcome.max_concurrent_branches}  {status}"
        )
        if measured:
            # Failures are kept so a broken arm is visible in the JSON rather
            # than silently shrinking the sample count.
            results[arm].append(outcome)

    if args.warmup:
        print(f"Warm-up ({args.warmup} per arm, discarded):")
        for index in range(args.warmup):
            execute("parallel", -1 - index, measured=False)
            execute("sequential", -1 - index, measured=False)

    print(f"Measured runs ({args.runs} per arm, interleaved):")
    for index in range(args.runs):
        order = ("parallel", "sequential") if index % 2 == 0 else ("sequential", "parallel")
        for arm in order:
            execute(arm, index, measured=True)
    return results


def _targets(
    args: argparse.Namespace,
    arms: dict[str, list[RunOutcome]],
    gate_latencies: Sequence[float],
    memory_probe: Any,
) -> list[TargetResult]:
    parallel_ok = [run for run in arms["parallel"] if run.ok]
    sequential_ok = [run for run in arms["sequential"] if run.ok]

    peaks = [run.peak_bytes for run in parallel_ok if run.peak_bytes is not None]
    peak = max(peaks) if peaks else None

    frame_stats = [dict(run.frames) for run in parallel_ok + sequential_ok]

    sequential_times = [run.wall_seconds for run in sequential_ok]
    parallel_times = [run.wall_seconds for run in parallel_ok]

    results = [
        evaluate_speedup(
            sequential_times,
            parallel_times,
            advisory=not args.live,
            advisory_reason=SYNTHETIC_SPEEDUP_REASON,
        ),
        evaluate_peak_rss(
            peak,
            probe_name=memory_probe.name,
            reason=memory_probe.reason,
        ),
        evaluate_gate_latency(gate_latencies),
        evaluate_frame_integrity(frame_stats),
        advisory_concurrency([run.max_concurrent_branches for run in parallel_ok]),
    ]
    if not args.live:
        results.append(
            advisory_overhead(sequential_times, parallel_times, args.branch_seconds)
        )
    return results


def _write_results(out_dir: Path, mode: str, payload: dict[str, Any], text: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"fanout-{mode}-{stamp}.json"
    text_path = out_dir / f"fanout-{mode}-{stamp}.txt"
    for path in (json_path, text_path, out_dir / f"fanout-{mode}-latest.json"):
        if path.name in RESERVED_OUTPUTS:
            raise SystemExit(f"refusing to write reserved output file {path}")
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    text_path.write_text(text, encoding="utf-8")
    (out_dir / f"fanout-{mode}-latest.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return json_path, text_path


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")
    if args.warmup is None:
        args.warmup = 0 if args.live else 1
    if args.warmup < 0:
        raise SystemExit("--warmup cannot be negative")
    if args.out.resolve() == (Path("output").resolve()):
        raise SystemExit("--out must be a subdirectory, not output/ itself")

    mode = "live" if args.live else "synthetic"
    if args.live:
        _confirm_live(args)

    memory_probe = select_memory_probe()
    fixtures = build_fixtures(args.idea)
    base_factories = (
        live_factories()
        if args.live
        else synthetic_factories(
            fixtures,
            branch_seconds=args.branch_seconds,
            stage_seconds=args.stage_seconds,
        )
    )

    print(f"Mode: {mode}")
    print(f"Memory probe: {memory_probe.name}" + ("" if memory_probe.available else " (UNAVAILABLE)"))
    print(f"Sample interval: {args.sample_interval * 1000:.0f} ms")
    print(f"CrewAI telemetry env: {telemetry_state()}")
    if not args.live:
        print(f"Synthetic branch sleeps (m,s,f): {args.branch_seconds}")
    print()

    arms = _run_arms(args, base_factories, memory_probe)

    gate_probe = None
    if args.gate_rounds > 0:
        print(f"\nGate probe ({args.gate_rounds} rounds, both gates each):")
        gate_probe = measure_gate_resume(
            rounds=args.gate_rounds,
            idea=args.idea,
            database_url=f"sqlite:///{(args.out / 'gate-probe.db').as_posix()}",
            output_path=args.out / "runs" / "gate-probe-validation.md",
        )
        for sample in gate_probe.samples:
            print(
                f"  round {sample.index} {sample.gate:<8} {sample.total_ms:7.1f} ms "
                f"(load {sample.load_ms:.1f} ms, dispatch {sample.dispatch_ms:.1f} ms)"
            )
        for error in gate_probe.errors:
            print(f"  ERROR {error}")

    gate_latencies = gate_probe.latencies_ms() if gate_probe else []
    targets = _targets(args, arms, gate_latencies, memory_probe)
    status = overall_status(targets)

    caveats = [SEQUENTIAL_ARM_CAVEAT]
    if not args.live:
        caveats.insert(0, SYNTHETIC_CAVEAT)
        caveats.append(SYNTHETIC_RSS_CAVEAT)
        caveats.append(
            "CrewAI telemetry is disabled in synthetic mode so the run makes no HTTP "
            "call. That removes a serial cost a live run may still pay."
        )

    text_lines = [
        f"ValidatorFlow fan-out benchmark ({mode})",
        f"generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        render_table(targets),
        "",
        render_verdict_block(targets),
        "",
        "Caveats:",
    ]
    text_lines.extend(f"  - {caveat}" for caveat in caveats)
    if gate_probe is not None:
        text_lines.append(f"  - {gate_probe.as_dict()['note']}")
    text = "\n".join(text_lines)

    sequential_summary = summarize([run.wall_seconds for run in arms["sequential"] if run.ok])
    parallel_summary = summarize([run.wall_seconds for run in arms["parallel"] if run.ok])

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "overall": status,
        "environment": _environment(memory_probe.name),
        "config": {
            "runs_per_arm": args.runs,
            "warmup_per_arm": args.warmup,
            "idea": args.idea,
            "branch_seconds": list(args.branch_seconds) if not args.live else None,
            "stage_seconds": args.stage_seconds if not args.live else None,
            "gate_rounds": args.gate_rounds,
            "sample_interval_s": args.sample_interval,
            "cache_isolated": not args.live,
        },
        "caveats": caveats,
        "wall_clock": {
            "sequential": sequential_summary.as_dict() if sequential_summary else None,
            "parallel": parallel_summary.as_dict() if parallel_summary else None,
        },
        "arms": {arm: [run.as_dict() for run in runs] for arm, runs in arms.items()},
        "gate_probe": gate_probe.as_dict() if gate_probe else None,
        "targets": [target.as_dict() for target in targets],
    }

    json_path, text_path = _write_results(args.out, mode, payload, text)

    print()
    print(text)
    print()
    print(f"JSON: {json_path}")
    print(f"Text: {text_path}")

    if args.exit_zero:
        return 0
    if status == MISSED:
        return 1
    if status == INCOMPLETE:
        return 2
    return 0 if status == MET else 1


if __name__ == "__main__":
    raise SystemExit(main())
