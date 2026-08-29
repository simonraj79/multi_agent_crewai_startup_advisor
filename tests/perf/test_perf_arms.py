"""The harness must drive the real Flow and must never touch real outputs.

These tests run ValidatorFlow for real (with no-cost doubles), so they are
slower than the rest of the suite. They stay no-cost: no crew, no model, no
network.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import bench_fanout
from scripts.perf_arms import (
    BranchConcurrency,
    FirstTouch,
    InstrumentedRunner,
    SleepingRunner,
    build_fixtures,
    frame_report,
    measure_gate_resume,
    run_arm_once,
    synthetic_factories,
)
from scripts.perf_metrics import select_memory_probe

BRANCH_SECONDS = (0.5, 0.5, 0.5)
RESERVED = ("brief.md", "last_run.json", "validation.md")


def _reserved_state() -> dict[str, tuple[bool, float]]:
    state = {}
    for name in RESERVED:
        path = Path("output") / name
        state[name] = (path.exists(), path.stat().st_mtime if path.exists() else 0.0)
    return state


class InstrumentationTests(unittest.TestCase):
    def test_first_touch_records_only_the_earliest_mark(self) -> None:
        touch = FirstTouch()
        self.assertIsNone(touch.value)

        touch.mark()
        first = touch.value
        touch.mark()

        self.assertEqual(touch.value, first)
        touch.reset()
        self.assertIsNone(touch.value)

    def test_instrumented_runner_serializes_and_tracks(self) -> None:
        import threading

        concurrency = BranchConcurrency()
        lock = threading.Lock()
        runners = [
            InstrumentedRunner(
                SleepingRunner("x", 0.05), lock=lock, concurrency=concurrency
            )
            for _ in range(3)
        ]
        threads = [threading.Thread(target=runner.kickoff, args=({},)) for runner in runners]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(concurrency.maximum, 1)

    def test_uninstrumented_runners_overlap(self) -> None:
        import threading

        concurrency = BranchConcurrency()
        runners = [
            InstrumentedRunner(SleepingRunner("x", 0.1), concurrency=concurrency)
            for _ in range(3)
        ]
        threads = [threading.Thread(target=runner.kickoff, args=({},)) for runner in runners]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(concurrency.maximum, 3)


class ArmExecutionTests(unittest.TestCase):
    """The two arms must do the same work with different concurrency."""

    def test_arms_differ_only_in_concurrency_and_leave_real_outputs_alone(self) -> None:
        before = _reserved_state()
        fixtures = build_fixtures()
        factories = synthetic_factories(
            fixtures, branch_seconds=BRANCH_SECONDS, stage_seconds=0.0
        )
        probe = select_memory_probe()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                parallel = run_arm_once(
                    arm="parallel",
                    index=0,
                    base_factories=factories,
                    serialize=False,
                    idea="A scheduling assistant for clinics",
                    output_path=root / "parallel.md",
                    memory_probe=probe,
                    sample_interval_s=0.02,
                    isolate_cache=True,
                )
                sequential = run_arm_once(
                    arm="sequential",
                    index=0,
                    base_factories=factories,
                    serialize=True,
                    idea="A scheduling assistant for clinics",
                    output_path=root / "sequential.md",
                    memory_probe=probe,
                    sample_interval_s=0.02,
                    isolate_cache=True,
                )

            self.assertTrue(parallel.ok, parallel.error)
            self.assertTrue(sequential.ok, sequential.error)
            self.assertTrue((root / "parallel.md").exists())
            self.assertTrue((root / "sequential.md").exists())

        # The Flow really does fan out, and the lock really does serialize it.
        self.assertEqual(parallel.max_concurrent_branches, 3)
        self.assertEqual(sequential.max_concurrent_branches, 1)
        # A serialized arm cannot finish before the sum of its branch sleeps.
        self.assertGreaterEqual(sequential.wall_seconds, sum(BRANCH_SECONDS))
        # ...and the parallel arm must be faster, or the baseline is not a baseline.
        self.assertGreater(sequential.wall_seconds, parallel.wall_seconds)

        # Every real deliverable is untouched.
        self.assertEqual(_reserved_state(), before)

    def test_frames_are_gapless_and_node_paired_on_a_real_run(self) -> None:
        for run in self._single_parallel_run():
            frames = run.frames
            self.assertGreater(frames["captured"], 0)
            self.assertEqual(frames["dropped"], 0)
            self.assertEqual(frames["gaps"], 0)
            self.assertEqual(frames["emit_errors"], 0)
            self.assertEqual(frames["unpaired_nodes"], 0)
            self.assertTrue(frames["seq_contiguous"])
            self.assertEqual(frames["first_seq"], 1)

    def test_synthetic_mode_opens_no_socket(self) -> None:
        """Acceptance criterion: synthetic mode must be free and offline."""
        import socket
        import threading
        from unittest.mock import patch

        # asyncio's Windows proactor loop builds its wake-up pipe from a
        # loopback socketpair, so loopback is allowed and anything else is not.
        loopback = {"127.0.0.1", "::1", "localhost", "", None}
        real_connect = socket.socket.connect
        real_getaddrinfo = socket.getaddrinfo
        real_connect_ex = socket.socket.connect_ex
        real_create_connection = socket.create_connection

        # patch.object patches the socket CLASS, which is process-wide. Threads
        # belonging to other tests - the frame writer, the gate sweeper, CrewAI
        # telemetry - are alive in the same interpreter, and raising inside one
        # of them fails an unrelated test instead of this one. So enforce only
        # on this thread and on threads the harness itself starts during the
        # window; every thread that already existed passes straight through.
        own_ident = threading.get_ident()
        foreign = {t.ident for t in threading.enumerate()} - {own_ident}

        def enforced() -> bool:
            return threading.get_ident() not in foreign

        def host_of(address: object) -> object:
            return address[0] if isinstance(address, tuple) and address else address

        def guarded_connect(self: socket.socket, address: object) -> object:
            if enforced() and host_of(address) not in loopback:
                raise AssertionError(f"synthetic mode dialled {address!r}")
            return real_connect(self, address)

        def guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
            if enforced() and host not in loopback:
                raise AssertionError(f"synthetic mode resolved {host!r}")
            return real_getaddrinfo(host, *args, **kwargs)

        def guarded_connect_ex(self: socket.socket, address: object) -> object:
            if enforced() and host_of(address) not in loopback:
                raise AssertionError(f"synthetic mode dialled {address!r}")
            return real_connect_ex(self, address)

        def guarded_create_connection(address: object, *args: object, **kwargs: object) -> object:
            if enforced() and host_of(address) not in loopback:
                raise AssertionError(f"synthetic mode dialled {address!r}")
            return real_create_connection(address, *args, **kwargs)

        fixtures = build_fixtures()
        factories = synthetic_factories(
            fixtures, branch_seconds=(0.0, 0.0, 0.0), stage_seconds=0.0
        )

        with tempfile.TemporaryDirectory() as directory:
            with contextlib.redirect_stdout(io.StringIO()):
                with (
                    patch.object(socket.socket, "connect", guarded_connect),
                    patch.object(socket.socket, "connect_ex", guarded_connect_ex),
                    patch.object(socket, "create_connection", guarded_create_connection),
                    patch.object(socket, "getaddrinfo", guarded_getaddrinfo),
                ):
                    outcome = run_arm_once(
                        arm="parallel",
                        index=0,
                        base_factories=factories,
                        serialize=False,
                        idea="idea",
                        output_path=Path(directory) / "out.md",
                        memory_probe=select_memory_probe(),
                        sample_interval_s=0.05,
                        isolate_cache=True,
                    )

        self.assertTrue(outcome.ok, outcome.error)

    def test_a_crashing_crew_is_reported_not_raised(self) -> None:
        from dataclasses import replace

        class Exploding:
            def kickoff(self, inputs: dict[str, object]) -> object:
                raise RuntimeError("crew exploded")

        fixtures = build_fixtures()
        factories = replace(
            synthetic_factories(fixtures, branch_seconds=(0.0, 0.0, 0.0), stage_seconds=0.0),
            scope=Exploding,
        )

        with tempfile.TemporaryDirectory() as directory:
            with contextlib.redirect_stdout(io.StringIO()):
                outcome = run_arm_once(
                    arm="parallel",
                    index=0,
                    base_factories=factories,
                    serialize=False,
                    idea="idea",
                    output_path=Path(directory) / "out.md",
                    memory_probe=select_memory_probe(),
                    sample_interval_s=0.05,
                    isolate_cache=True,
                )

        self.assertFalse(outcome.ok)
        self.assertIn("crew exploded", outcome.error)

    def _single_parallel_run(self):
        fixtures = build_fixtures()
        factories = synthetic_factories(
            fixtures, branch_seconds=(0.0, 0.0, 0.0), stage_seconds=0.0
        )
        with tempfile.TemporaryDirectory() as directory:
            with contextlib.redirect_stdout(io.StringIO()):
                yield run_arm_once(
                    arm="parallel",
                    index=0,
                    base_factories=factories,
                    serialize=False,
                    idea="idea",
                    output_path=Path(directory) / "out.md",
                    memory_probe=select_memory_probe(),
                    sample_interval_s=0.05,
                    isolate_cache=True,
                )


class FrameReportTests(unittest.TestCase):
    def test_a_ring_overflow_is_reported_as_loss_not_hidden(self) -> None:
        from brief_crew.events import FrameBuffer, FrameKind, StreamSinkAdapter, UIEventType
        from brief_crew.service.graph import VALIDATOR_NODE_REGISTRY

        buffer = FrameBuffer(capacity=4)
        adapter = StreamSinkAdapter(
            run_id="overflow", buffer=buffer, registry=VALIDATOR_NODE_REGISTRY
        )
        for index in range(10):
            adapter.emit(
                kind=FrameKind.NODE_STATE,
                event_type=UIEventType.NODE_START,
                node_id="scope_idea",
                message=f"frame {index}",
            )

        report = frame_report(buffer)

        self.assertEqual(report["captured"], 10)
        self.assertEqual(report["dropped"], 6)
        self.assertEqual(report["gaps"], 6)
        self.assertFalse(report["seq_contiguous"])
        self.assertEqual(report["unpaired_nodes"], 4)


class GateProbeTests(unittest.TestCase):
    def test_both_native_gates_are_timed_through_persist_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                result = measure_gate_resume(
                    rounds=1,
                    idea="A scheduling assistant for clinics",
                    database_url=f"sqlite:///{(root / 'gates.db').as_posix()}",
                    output_path=root / "gate.md",
                )

        # Retries are allowed but every attempt is recorded, so a persistently
        # broken resume path still shows up as zero samples.
        self.assertEqual(
            [sample.gate for sample in result.samples], ["scope", "verdict"], result.errors
        )
        for sample in result.samples:
            self.assertGreater(sample.total_ms, 0.0)
            self.assertGreaterEqual(sample.total_ms, sample.load_ms)

    def test_a_permanently_broken_resume_yields_no_samples(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                with patch(
                    "scripts.perf_arms._gate_round", side_effect=RuntimeError("resume broke")
                ):
                    result = measure_gate_resume(
                        rounds=1,
                        idea="idea",
                        database_url=f"sqlite:///{(root / 'broken.db').as_posix()}",
                        output_path=root / "gate.md",
                    )

        self.assertEqual(result.samples, [])
        self.assertEqual(len(result.errors), 2)
        self.assertIn("resume broke", result.errors[0])


class LiveWiringTests(unittest.TestCase):
    """--live must reach the real crews. Nothing here executes one."""

    def test_live_factories_are_the_real_validator_crew_factories(self) -> None:
        from brief_crew import validator_flow
        from scripts.perf_arms import live_factories

        factories = live_factories()

        self.assertIs(factories.scope, validator_flow._scope_runner)
        self.assertIs(factories.market, validator_flow._market_runner)
        self.assertIs(factories.sentiment, validator_flow._sentiment_runner)
        self.assertIs(factories.feasibility, validator_flow._feasibility_runner)
        self.assertIs(factories.synthesis, validator_flow._synthesis_runner)
        self.assertIs(factories.report, validator_flow._report_runner)

    def test_instrumentation_preserves_the_real_factory_underneath(self) -> None:
        from brief_crew import validator_flow
        from scripts.perf_arms import instrument_factories, live_factories

        wrapped = instrument_factories(live_factories())

        # Scope and synthesis are untouched; only the branches and reporter wrap.
        self.assertIs(wrapped.scope, validator_flow._scope_runner)
        self.assertIs(wrapped.synthesis, validator_flow._synthesis_runner)
        self.assertIsNot(wrapped.market, validator_flow._market_runner)

    def test_live_makes_the_speedup_binding_and_keeps_the_cache_live(self) -> None:
        args = bench_fanout.build_parser().parse_args(["--live"])

        self.assertTrue(args.live)
        targets = bench_fanout._targets(
            args,
            {"parallel": [], "sequential": []},
            [],
            select_memory_probe(),
        )
        speedup = next(target for target in targets if target.key == "fanout_speedup")

        self.assertFalse(speedup.advisory, "the live speedup must pass or fail the target")
        self.assertFalse(
            any(target.key == "serial_overhead" for target in targets),
            "the synthetic-only overhead projection must not appear in a live report",
        )

    def test_synthetic_makes_the_speedup_advisory(self) -> None:
        args = bench_fanout.build_parser().parse_args([])

        targets = bench_fanout._targets(
            args, {"parallel": [], "sequential": []}, [], select_memory_probe()
        )
        speedup = next(target for target in targets if target.key == "fanout_speedup")

        self.assertTrue(speedup.advisory)


class CliTests(unittest.TestCase):
    def test_branch_seconds_accepts_one_or_three_values(self) -> None:
        self.assertEqual(bench_fanout._branch_seconds("0.4"), (0.4, 0.4, 0.4))
        self.assertEqual(bench_fanout._branch_seconds("1,2,3"), (1.0, 2.0, 3.0))
        with self.assertRaises(Exception):
            bench_fanout._branch_seconds("1,2")

    def test_live_refuses_to_spend_money_without_explicit_consent(self) -> None:
        args = bench_fanout.build_parser().parse_args(["--live"])
        args.warmup = 0

        with self.assertRaises(SystemExit) as raised:
            bench_fanout._confirm_live(args)

        self.assertIn("--yes", str(raised.exception))

    def test_out_may_not_be_the_output_root(self) -> None:
        with self.assertRaises(SystemExit):
            bench_fanout.main(["--out", "output", "--runs", "1", "--gate-rounds", "0"])

    def test_synthetic_smoke_reports_every_target_and_writes_json(self) -> None:
        before = _reserved_state()
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "perf"
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = bench_fanout.main(
                    [
                        "--runs", "1",
                        "--warmup", "0",
                        "--branch-seconds", "0.05",
                        "--stage-seconds", "0",
                        "--gate-rounds", "1",
                        "--out", str(out),
                    ]
                )

            payload = json.loads((out / "fanout-synthetic-latest.json").read_text("utf-8"))

        self.assertIn(code, (0, 1, 2))
        self.assertEqual(payload["mode"], "synthetic")
        self.assertTrue(payload["config"]["cache_isolated"])
        keys = {target["key"] for target in payload["targets"]}
        self.assertLessEqual(
            {"fanout_speedup", "peak_rss", "gate_resume", "frame_loss"}, keys
        )
        self.assertEqual(len(payload["arms"]["parallel"]), 1)
        self.assertEqual(len(payload["arms"]["sequential"]), 1)
        self.assertTrue(payload["gate_probe"]["samples"])
        self.assertTrue(any("SYNTHETIC MODE" in caveat for caveat in payload["caveats"]))
        self.assertEqual(_reserved_state(), before)


if __name__ == "__main__":
    unittest.main()
