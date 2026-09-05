"""E4 on ONE port: the sanctioned measurement, arms in blocks instead of interleaved runs.

Why this file exists at all
---------------------------
`scripts/observability/measure_overhead.py` is the sanctioned E4 harness and it
starts BOTH arms at once, on `--port-on` and `--port-off`. This verification was
constrained to **port 8098 only** - 8000 and 8099 were carrying another worker's
paid proof runs and no other port was assigned - so two simultaneous backends
were not available. The brief allows the fallback ("restarting the backend per
arm otherwise").

Everything that MEASURES is the sanctioned script's own code, imported, not
copied: `start_backend`, `wait_for_health`, `launch_and_wait`,
`parse_exporter_lines`. What this file adds is the scheduling: one backend at a
time on one port, arms in an **ABBA block order** so a machine that warms up or
throttles across the measurement contributes to both arms equally - the control
the script's run-level alternation buys, taken at block granularity.

The third arm (`bh`) is EXTRA and is not required by E4: the exporter ON with
`LANGFUSE_BASE_URL` at a dead local port, to price a run whose Langfuse is
unreachable. It needs its own launcher, and the reason is a trap:
`brief_crew/__init__.py` calls `load_dotenv(override=True)`, so a
`LANGFUSE_BASE_URL` placed in the child's environment - which is exactly what
`measure_overhead.py --env` does, and what its README recommends for this
purpose - is OVERWRITTEN by `.env` at import. The bootstrap here imports
`brief_crew` first, sets the variable second and imports the app third, so the
value config reads is the one asked for. `/readyz` is read before any run so the
arm's actual state is recorded rather than assumed.

No credential is read, printed or written by this file.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts" / "observability"))

import measure_overhead as mo  # noqa: E402
from _common import Http, ensure_dir, load_env, now_iso, write_json  # noqa: E402


def readyz(base_url: str) -> dict[str, Any]:
    with Http(base_url, timeout=10.0, retries=2) as http:
        _, body = http.get("/readyz", allow_status=tuple(range(400, 600)))
    return dict(body) if isinstance(body, dict) else {"raw": body}


def start_blackhole(name: str, port: int, args: Any, out_dir: Path, url: str) -> mo.Backend:
    """The `bh` arm's backend. Identical to `mo.start_backend` but for the bootstrap."""

    python = ROOT / ".venv" / "Scripts" / "python.exe"
    env = dict(os.environ)
    env["SYNTHETIC"] = "1"
    env["SYNTHETIC_BRANCH_DELAY_SECONDS"] = str(args.branch_delay)
    env["PORT"] = str(port)
    env["HOST"] = "127.0.0.1"
    env.setdefault("CREDENTIALS_MASTER_KEY", "Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE=")
    env["VALIDATOR_ALLOW_AUTO_GATES"] = "1"
    env["LANGFUSE_EXPORT_ENABLED"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    bootstrap = (
        "import logging;"
        "logging.basicConfig(level=logging.INFO,"
        " format='%(asctime)s %(levelname)s %(name)s %(message)s');"
        "import brief_crew, os;"
        "os.environ['LANGFUSE_BASE_URL']=" + repr(url) + ";"
        "from brief_crew.service.app import serve;"
        "serve()"
    )
    log_path = out_dir / ("server-" + name + ".log")
    handle = log_path.open("wb")
    process = subprocess.Popen(
        [str(python), "-c", bootstrap],
        cwd=str(ROOT),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    command = (
        "SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=" + str(args.branch_delay)
        + " PORT=" + str(port)
        + " LANGFUSE_EXPORT_ENABLED=1 VALIDATOR_ALLOW_AUTO_GATES=1"
        + " CREDENTIALS_MASTER_KEY=<placeholder> "
        + str(python)
        + ' -c "basicConfig(INFO); import brief_crew; os.environ[LANGFUSE_BASE_URL]='
        + url
        + '; from brief_crew.service.app import serve; serve()"'
    )
    backend = mo.Backend(name, "http://127.0.0.1:" + str(port), process, log_path, command)
    mo.wait_for_health(backend, args.start_timeout)
    return backend


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E4 on one port, arms in blocks.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--port", type=int, default=8098)
    parser.add_argument("--branch-delay", default="2")
    parser.add_argument("--runs-per-block", type=int, default=5)
    parser.add_argument(
        "--blocks",
        default="on,off,off,on",
        help="block order, comma separated. Arms: on | off | bh",
    )
    parser.add_argument("--bh-url", default="http://127.0.0.1:9")
    parser.add_argument("--workflow-id", default="idea-validator")
    parser.add_argument("--idea", default=mo.DEFAULT_IDEA)
    parser.add_argument("--start-timeout", type=float, default=180.0)
    parser.add_argument("--run-timeout", type=float, default=600.0)
    parser.add_argument("--poll", type=float, default=0.25)
    parser.add_argument("--settle", type=float, default=3.0)
    args = parser.parse_args(argv)

    load_env()
    out_dir = ensure_dir(args.out)
    blocks = [b.strip() for b in str(args.blocks).split(",") if b.strip()]

    inner = SimpleNamespace(
        branch_delay=args.branch_delay,
        force_on=True,
        env=[],
        use_serve_exe=False,
        start_timeout=args.start_timeout,
        run_timeout=args.run_timeout,
        poll=args.poll,
        workflow_id=args.workflow_id,
        idea=args.idea,
    )

    records: list[dict[str, Any]] = []
    commands: list[str] = []
    block_reports: list[dict[str, Any]] = []

    for number, arm in enumerate(blocks, start=1):
        name = arm + "-b" + str(number)
        backend: mo.Backend | None = None
        try:
            t0 = time.perf_counter()
            if arm == "bh":
                backend = start_blackhole(name, args.port, inner, out_dir, args.bh_url)
            else:
                backend = mo.start_backend(name, args.port, inner, out_dir, arm == "on")
            boot = time.perf_counter() - t0
            commands.append("# block " + str(number) + " (" + arm + ")\n" + backend.command)
            ready = readyz(backend.base_url)
            obs = ready.get("observability")
            print(
                "[block %d %s] booted in %.1fs; observability=%s" % (number, arm, boot, obs),
                file=sys.stderr,
            )
            block_reports.append(
                {
                    "block": number,
                    "arm": arm,
                    "boot_seconds": boot,
                    "observability": obs,
                    "command": backend.command,
                    "log": str(backend.log_path),
                }
            )
            for index in range(1, args.runs_per_block + 1):
                run = mo.launch_and_wait(backend, inner, index)
                run["arm"] = arm
                run["block"] = number
                run["index_in_block"] = index
                records.append(run)
                print(
                    "[block %d %s] run %d: %s in %.2fs (%s)"
                    % (number, arm, index, run["status"], run["wall_clock_seconds"], run["run_id"]),
                    file=sys.stderr,
                )
        finally:
            if backend is not None:
                # The per-run summary line is written when the trace closes,
                # which the terminal frame triggers on the export thread; give
                # it a moment before the process is killed.
                time.sleep(args.settle)
                backend.stop()
        log_text = backend.read_log() if backend else ""
        lines = mo.parse_exporter_lines(log_text)
        block_reports[-1]["exporter_lines"] = lines
        by_run = {str(line.get("run")): line for line in lines if line.get("run")}
        for run in records:
            if run["block"] == number:
                run["exporter"] = by_run.get(str(run["run_id"]))

    report = {
        "generated_at": now_iso(),
        "port": args.port,
        "branch_delay": args.branch_delay,
        "workflow_id": args.workflow_id,
        "runs_per_block": args.runs_per_block,
        "blocks": blocks,
        "block_reports": block_reports,
        "runs": records,
        "commands": commands,
    }
    write_json(out_dir, "e4-raw.json", report)
    print(json.dumps({"runs": len(records), "blocks": blocks}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
