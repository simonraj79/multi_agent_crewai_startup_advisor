"""Measure what the exporter costs a run, exporter on versus off.

Serves DoD row **E4**: *"on a full synthetic run with a fixed branch delay,
what is the wall-clock delta and the per-frame handler latency (p50/p95) with
the exporter on versus off, n >= 3 each?"* Output: `overhead.md`, plus the raw
per-run JSON and both servers' captured stdout/stderr.

Two arms, each a separate backend process on its own port:

* **on**  - the environment as it stands (`LANGFUSE_EXPORT_ENABLED` unset, so
  the exporter's own default decides; pass `--force-on` to set it to 1).
* **off** - the same, with `LANGFUSE_EXPORT_ENABLED=0`.

Everything else is held constant: `SYNTHETIC=1` (so the runs are free and
deterministic), a fixed `SYNTHETIC_BRANCH_DELAY_SECONDS`, the same idea text,
the same `gates: "auto"`, the same number of runs. The arms are run
**alternately** (on, off, on, off, ...) rather than in two blocks, because a
machine that warms up or throttles during the measurement would otherwise put
all of that into one arm - the same control discipline the run-shell
performance work used.

The exporter's per-run summary line (`TRACE-CONTRACT.md` §10) is parsed out of
the captured server log:

    langfuse-exporter run=<id> enqueued=<n> dropped=<n> sent=<n> http_errors=<n>
      lookup_ok=<n> lookup_failed=<n> enqueue_p50_us=<n> enqueue_p95_us=<n>

**If that line is absent the script says "not found" and still reports the wall
clock.** The exporter is built by another worker; a harness that only worked
once the thing it measures existed could never have been tested.

Processes are started with `subprocess.Popen` and killed with
`taskkill /PID <pid> /T /F` on Windows - never `pkill`, which reports success
on Windows while the old process keeps serving (gotcha 25) and would leave a
stale backend answering `/healthz` from the other arm's code.

Usage:

    .venv/Scripts/python.exe scripts/observability/measure_overhead.py \\
        --runs 3 --out docs/observability/evidence/perf

    # against two backends somebody else already started:
    .venv/Scripts/python.exe scripts/observability/measure_overhead.py \\
        --runs 3 --base-on http://127.0.0.1:8110 \\
        --base-off http://127.0.0.1:8111 --out DIR
"""

from __future__ import annotations

import argparse
import os
import re
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    Http,
    HttpError,
    ensure_dir,
    load_env,
    md_table,
    now_iso,
    repo_root,
    secs,
    write_json,
    write_text,
)

TERMINAL = {"completed", "failed", "cancelled"}
SUMMARY_LINE = re.compile(r"langfuse-exporter\s+(?P<body>[^\r\n]*)")
KEY_VALUE = re.compile(r"(?P<key>[a-z_0-9]+)=(?P<value>[^\s]+)")
DEFAULT_IDEA = (
    "A scheduling assistant for small veterinary clinics that books, reminds "
    "and reschedules appointments"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wall clock and exporter latency, exporter on versus off.",
    )
    parser.add_argument("--runs", type=int, default=3, help="runs per arm (E4 wants >= 3)")
    parser.add_argument("--out", required=True, help="directory to write into")
    parser.add_argument("--base-on", default=None, help="an already-running exporter-ON backend")
    parser.add_argument("--base-off", default=None, help="an already-running exporter-OFF backend")
    parser.add_argument("--port-on", type=int, default=8110)
    parser.add_argument("--port-off", type=int, default=8111)
    parser.add_argument(
        "--branch-delay",
        default="2",
        help="SYNTHETIC_BRANCH_DELAY_SECONDS, held equal across arms (default 2)",
    )
    parser.add_argument("--idea", default=DEFAULT_IDEA)
    parser.add_argument("--workflow-id", default="idea-validator")
    parser.add_argument(
        "--force-on",
        action="store_true",
        help="set LANGFUSE_EXPORT_ENABLED=1 on the on arm instead of leaving it to the default",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "an extra environment variable for BOTH server arms (repeatable). "
            "Held equal across arms by construction, so it cannot bias the "
            "delta. Use it to point LANGFUSE_BASE_URL at a black-hole port "
            "when the measurement must not reach the real project."
        ),
    )
    parser.add_argument(
        "--use-serve-exe",
        action="store_true",
        help=(
            "launch `.venv/Scripts/serve.exe` instead of the logging-configured "
            "launcher. NOTE: nothing in the app calls logging.basicConfig, so "
            "under serve.exe the exporter's INFO summary line is dropped by "
            "logging.lastResort and the p50/p95 half of E4 cannot be measured."
        ),
    )
    parser.add_argument("--start-timeout", type=float, default=90.0)
    parser.add_argument("--run-timeout", type=float, default=600.0)
    parser.add_argument("--poll", type=float, default=0.25)
    return parser.parse_args(argv)


# --- the backend ------------------------------------------------------------


class Backend:
    """One arm's server process, or a note that somebody else is running it."""

    def __init__(
        self,
        name: str,
        base_url: str,
        process: subprocess.Popen[bytes] | None,
        log_path: Path | None,
        command: str,
    ) -> None:
        self.name = name
        self.base_url = base_url
        self.process = process
        self.log_path = log_path
        self.command = command

    def stop(self) -> None:
        if self.process is None:
            return
        pid = self.process.pid
        if os.name == "nt":
            # /T kills the tree - uvicorn's reloader-free run is one process,
            # but a future --reload would not be, and a survivor keeps serving.
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:  # pragma: no cover - this programme runs on Windows
            self.process.terminate()
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover
            self.process.kill()

    def read_log(self) -> str:
        if self.log_path and self.log_path.is_file():
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        return ""


def start_backend(
    name: str, port: int, args: argparse.Namespace, out_dir: Path, exporter_on: bool
) -> Backend:
    root = repo_root()
    serve = root / ".venv" / "Scripts" / ("serve.exe" if os.name == "nt" else "serve")
    python = root / ".venv" / "Scripts" / ("python.exe" if os.name == "nt" else "python")
    if not serve.is_file() or not python.is_file():
        raise SystemExit(f"{serve} or {python} is missing; is the venv installed?")

    env = dict(os.environ)
    env["SYNTHETIC"] = "1"
    env["SYNTHETIC_BRANCH_DELAY_SECONDS"] = str(args.branch_delay)
    env["PORT"] = str(port)
    env["HOST"] = "127.0.0.1"
    # Any base64 of 32 bytes; the placeholder tests/__init__.py uses, which
    # authenticates against nothing. Without it the credential routes answer
    # 503 and, with AUTH_BASE_URL set, create_app refuses to boot at all.
    env.setdefault(
        "CREDENTIALS_MASTER_KEY", "Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="
    )
    # `gates: "auto"` is refused with 403 for an anonymous caller unless this is
    # set (service/app.py::create_run). A synthetic backend spends nothing.
    env["VALIDATOR_ALLOW_AUTO_GATES"] = "1"
    if exporter_on:
        if args.force_on:
            env["LANGFUSE_EXPORT_ENABLED"] = "1"
        else:
            env.pop("LANGFUSE_EXPORT_ENABLED", None)
    else:
        env["LANGFUSE_EXPORT_ENABLED"] = "0"
    # Applied AFTER the arm's own switch, so an operator can override anything
    # except the one variable that distinguishes the arms.
    extra: list[str] = []
    for item in args.env:
        key, _, value = str(item).partition("=")
        key = key.strip()
        if not key or key == "LANGFUSE_EXPORT_ENABLED":
            continue
        env[key] = value
        extra.append(f"{key}={value}")

    # MEASURED 2026-09-05: nothing in `src/brief_crew/` calls
    # `logging.basicConfig` or `dictConfig`, and uvicorn's own config attaches
    # handlers to the three `uvicorn*` loggers only. A `brief_crew.*` record
    # therefore propagates to a root logger with no handler and is served by
    # `logging.lastResort`, which emits WARNING and above. The exporter's
    # summary line is INFO, so under bare `serve.exe` it is DROPPED - the
    # p50/p95 half of E4 would be unmeasurable and would look like an exporter
    # that never ran. The default launcher configures the root logger first and
    # then calls the same `serve()` the console script does; `--use-serve-exe`
    # restores the old behaviour for anyone who wants to see it.
    env.setdefault("PYTHONUNBUFFERED", "1")
    if args.use_serve_exe:
        command_argv = [str(serve)]
        launcher = str(serve)
    else:
        bootstrap = (
            "import logging;"
            "logging.basicConfig(level=logging.INFO,"
            " format='%(asctime)s %(levelname)s %(name)s %(message)s');"
            "from brief_crew.service.app import serve;"
            "serve()"
        )
        command_argv = [str(python), "-c", bootstrap]
        launcher = f'{python} -c "logging.basicConfig(level=INFO); serve()"'

    log_path = out_dir / f"server-{name}.log"
    handle = log_path.open("wb")
    process = subprocess.Popen(
        command_argv,
        cwd=str(root),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    knobs = " ".join(
        f"{key}={env.get(key, '(unset)')}"
        for key in (
            "SYNTHETIC",
            "SYNTHETIC_BRANCH_DELAY_SECONDS",
            "PORT",
            "LANGFUSE_EXPORT_ENABLED",
            "VALIDATOR_ALLOW_AUTO_GATES",
        )
    )
    command = " ".join([knobs, *extra, "CREDENTIALS_MASTER_KEY=<placeholder>", launcher])
    backend = Backend(name, f"http://127.0.0.1:{port}", process, log_path, command)
    wait_for_health(backend, args.start_timeout)
    return backend


def wait_for_health(backend: Backend, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    with Http(backend.base_url, timeout=5.0, retries=1) as http:
        while time.monotonic() < deadline:
            if backend.process is not None and backend.process.poll() is not None:
                raise SystemExit(
                    f"the {backend.name} backend exited during startup; read "
                    f"{backend.log_path}"
                )
            try:
                status, _ = http.get("/healthz", allow_status=tuple(range(400, 600)))
                if status == 200:
                    return
            except Exception:
                pass
            time.sleep(0.4)
    raise SystemExit(f"the {backend.name} backend never answered /healthz")


# --- runs -------------------------------------------------------------------


def launch_and_wait(
    backend: Backend, args: argparse.Namespace, index: int
) -> dict[str, Any]:
    session_id = f"perf-{backend.name}-{index}-{uuid.uuid4().hex[:8]}"
    with Http(backend.base_url, timeout=60.0, retries=2) as http:
        started = time.perf_counter()
        status, body = http.post(
            f"/api/sessions/{session_id}/runs",
            {
                "workflow_id": args.workflow_id,
                "inputs": {"idea": args.idea},
                "gates": "auto",
            },
        )
        if not isinstance(body, Mapping) or not body.get("run_id"):
            raise SystemExit(f"launch failed on {backend.name}: HTTP {status} {body}")
        run_id = str(body["run_id"])
        deadline = time.monotonic() + args.run_timeout
        snapshot: Mapping[str, Any] = {}
        while time.monotonic() < deadline:
            try:
                _, snapshot = http.get(f"/api/runs/{run_id}")
            except HttpError:
                time.sleep(args.poll)
                continue
            if isinstance(snapshot, Mapping) and str(snapshot.get("status")) in TERMINAL:
                break
            time.sleep(args.poll)
        elapsed = time.perf_counter() - started

    usage = dict((snapshot or {}).get("usage") or {})
    frames = dict((snapshot or {}).get("frames") or {})
    return {
        "arm": backend.name,
        "index": index,
        "run_id": run_id,
        "session_id": session_id,
        "status": (snapshot or {}).get("status"),
        "wall_clock_seconds": elapsed,
        "started_at": (snapshot or {}).get("started_at"),
        "completed_at": (snapshot or {}).get("completed_at"),
        "frames": frames.get("count"),
        "frames_dropped": frames.get("dropped"),
        "calls": usage.get("call_count"),
        "total_tokens": usage.get("total_tokens"),
    }


# --- the exporter's own line ------------------------------------------------


def parse_exporter_lines(log_text: str) -> list[dict[str, Any]]:
    """Every `langfuse-exporter ...` summary line, as key/value dicts.

    Values that look numeric become numbers so they can be averaged; anything
    else stays a string, so a future field cannot crash the parse.
    """

    parsed: list[dict[str, Any]] = []
    for match in SUMMARY_LINE.finditer(log_text):
        fields: dict[str, Any] = {}
        for pair in KEY_VALUE.finditer(match.group("body")):
            key, value = pair.group("key"), pair.group("value")
            try:
                fields[key] = int(value)
            except ValueError:
                try:
                    fields[key] = float(value)
                except ValueError:
                    fields[key] = value
        if fields:
            parsed.append(fields)
    return parsed


def summarise(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "min": None, "max": None, "median": None, "stdev": None}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "min": min(values),
        "max": max(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def render(report: Mapping[str, Any]) -> str:
    arms = report["arms"]
    rows = []
    for name in ("on", "off"):
        arm = arms.get(name) or {}
        wall = arm.get("wall_clock") or {}
        rows.append(
            [
                name,
                wall.get("n", 0),
                secs(wall.get("mean")),
                secs(wall.get("median")),
                secs(wall.get("min")),
                secs(wall.get("max")),
                secs(wall.get("stdev")),
            ]
        )
    delta = report.get("wall_clock_delta_seconds")
    exporter_rows = []
    for name in ("on", "off"):
        arm = arms.get(name) or {}
        exporter = arm.get("exporter") or {}
        if not exporter.get("lines"):
            exporter_rows.append([name, "not found", "-", "-", "-", "-", "-"])
            continue
        exporter_rows.append(
            [
                name,
                exporter["lines"],
                exporter.get("enqueued_total"),
                exporter.get("sent_total"),
                exporter.get("dropped_total"),
                exporter.get("enqueue_p50_us_mean"),
                exporter.get("enqueue_p95_us_mean"),
            ]
        )

    lines = [
        "# Exporter overhead - DoD E4",
        "",
        f"Measured {report['generated_at']} on this machine.",
        f"Runs per arm: {report['runs_per_arm']}. Arms alternated on/off, "
        "not run in two blocks.",
        f"Workflow `{report['workflow_id']}`, `gates: \"auto\"`, `SYNTHETIC=1`, "
        f"`SYNTHETIC_BRANCH_DELAY_SECONDS={report['branch_delay']}`.",
        "",
        "## Wall clock per run (launch to terminal status, client side)",
        "",
        md_table(
            ["arm", "n", "mean s", "median s", "min s", "max s", "stdev s"], rows
        ),
        "",
        (
            f"**Delta (on - off), on the means: {secs(delta)} s"
            + (
                f" ({report['wall_clock_delta_percent']:.1f}%)"
                if report.get("wall_clock_delta_percent") is not None
                else ""
            )
            + ".**"
            if delta is not None
            else "**Delta: not computable - one arm produced no runs.**"
        ),
        "",
        "A synthetic run's duration is dominated by "
        "`SYNTHETIC_BRANCH_DELAY_SECONDS`, which is held equal, so the delta is",
        "the exporter's contribution plus this machine's noise. Read it against",
        "the `stdev` column: a delta inside one standard deviation is not a",
        "measurement of the exporter.",
        "",
        "## The exporter's own counters",
        "",
        "Parsed from the captured server log, one summary line per run "
        "(`TRACE-CONTRACT.md` section 10).",
        "",
        md_table(
            [
                "arm",
                "summary lines",
                "enqueued",
                "sent",
                "dropped",
                "enqueue p50 us (mean)",
                "enqueue p95 us (mean)",
            ],
            exporter_rows,
        ),
        "",
    ]
    if not (arms.get("on") or {}).get("exporter", {}).get("lines"):
        lines += [
            "**No `langfuse-exporter` summary line was found in the ON arm's log.**",
            "Either the exporter is not wired yet, or it did not run. The wall-clock",
            "half of this row is still measured; the p50/p95 half is NOT, and must",
            "not be reported as zero.",
            "",
        ]
    lines += [
        "## Per run",
        "",
        md_table(
            ["arm", "#", "run_id", "status", "wall s", "frames", "dropped", "calls", "tokens"],
            [
                [
                    run["arm"],
                    run["index"],
                    run["run_id"],
                    run["status"],
                    secs(run["wall_clock_seconds"]),
                    run["frames"],
                    run["frames_dropped"],
                    run["calls"],
                    run["total_tokens"],
                ]
                for run in report["runs"]
            ],
        ),
        "",
        "## The exact commands",
        "",
        "```text",
        *report["commands"],
        "```",
        "",
        "Servers were killed with `taskkill /PID <pid> /T /F`, never `pkill`:",
        "on Windows `pkill` reports success while the old process keeps serving",
        "(`docs/gotchas-and-insights.md` 25).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env()
    out_dir = ensure_dir(args.out)

    backends: dict[str, Backend] = {}
    started: list[Backend] = []
    commands: list[str] = []
    try:
        for name, base, port, exporter_on in (
            ("on", args.base_on, args.port_on, True),
            ("off", args.base_off, args.port_off, False),
        ):
            if base:
                backends[name] = Backend(name, base.rstrip("/"), None, None, f"(already running at {base})")
                commands.append(f"# {name}: reused a backend already running at {base}")
                continue
            backend = start_backend(name, port, args, out_dir, exporter_on)
            backends[name] = backend
            started.append(backend)
            commands.append(f"# {name} arm\n{backend.command}")

        runs: list[dict[str, Any]] = []
        for index in range(1, max(1, args.runs) + 1):
            for name in ("on", "off"):
                run = launch_and_wait(backends[name], args, index)
                runs.append(run)
                print(
                    f"{name} run {index}: {run['status']} in "
                    f"{run['wall_clock_seconds']:.2f}s ({run['run_id']})",
                    file=sys.stderr,
                )
    finally:
        for backend in started:
            backend.stop()

    arms: dict[str, Any] = {}
    for name in ("on", "off"):
        arm_runs = [r for r in runs if r["arm"] == name]
        wall = summarise([float(r["wall_clock_seconds"]) for r in arm_runs])
        log_text = backends[name].read_log()
        exporter_lines = parse_exporter_lines(log_text)
        exporter: dict[str, Any] = {"lines": len(exporter_lines), "raw": exporter_lines}
        if exporter_lines:
            for key in ("enqueued", "sent", "dropped", "http_errors", "lookup_ok", "lookup_failed"):
                exporter[f"{key}_total"] = sum(
                    int(line.get(key, 0) or 0) for line in exporter_lines
                )
            for key in ("enqueue_p50_us", "enqueue_p95_us"):
                values = [
                    float(line[key]) for line in exporter_lines if isinstance(line.get(key), (int, float))
                ]
                exporter[f"{key}_mean"] = (
                    round(statistics.fmean(values), 1) if values else None
                )
        arms[name] = {"runs": len(arm_runs), "wall_clock": wall, "exporter": exporter}

    on_mean = (arms["on"]["wall_clock"] or {}).get("mean")
    off_mean = (arms["off"]["wall_clock"] or {}).get("mean")
    delta = None if on_mean is None or off_mean is None else on_mean - off_mean
    percent = (
        None if delta is None or not off_mean else (delta / off_mean) * 100.0
    )

    report = {
        "generated_at": now_iso(),
        "runs_per_arm": args.runs,
        "workflow_id": args.workflow_id,
        "branch_delay": args.branch_delay,
        "arms": arms,
        "runs": runs,
        "wall_clock_delta_seconds": delta,
        "wall_clock_delta_percent": percent,
        "commands": commands,
        "logs": {
            name: str(backends[name].log_path) if backends[name].log_path else None
            for name in backends
        },
    }
    write_json(out_dir, "overhead.json", report)
    text = render(report)
    write_text(out_dir, "overhead.md", text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
