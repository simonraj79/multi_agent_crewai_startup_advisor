"""Observability and lifecycle gaps closed in this pass - F20, F21, F30, F31.

Everything here is no-cost. No CrewAI crew, no OpenRouter call, no network:
usage arrives as hand-built ``token`` frames through the same capture path a
real ``LLMCallCompletedEvent`` takes, storage is in-memory SQLite, and the
periodic jobs are either driven explicitly or given a tiny interval.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import threading
import time
from typing import Any
import unittest

from crewai.events import MethodExecutionStartedEvent

from brief_crew.config import (
    CHEAP_MODEL,
    VALIDATOR_FRAME_FLUSH_INTERVAL_SECONDS,
    VALIDATOR_RUN_RETENTION_SECONDS,
    compute_cost_usd,
)
from brief_crew.events import (
    FrameBuffer,
    FrameData,
    FrameDraft,
    FrameKind,
    FrameLevel,
    QUARANTINE_NODE_ID,
    UIEventType,
)
from brief_crew.service.graph import (
    BRIEF_GRAPH,
    BRIEF_NODE_REGISTRY,
    VALIDATOR_GRAPH,
    VALIDATOR_NODE_REGISTRY,
)
from brief_crew.service.models import RunStatus, RunStatusResponse
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import (
    RunRegistry,
    WorkflowRuntime,
    _PersistenceWriter,
)
from brief_crew.service.runner import RunExecution, SyntheticValidatorRunner


WRITER_THREAD_NAME = "validator-frame-writer"
SWEEPER_THREAD_NAME = "validator-gate-sweeper"
PROMPT_TOKENS = 100
COMPLETION_TOKENS = 50


def _frame(seq: int = 1, run_id: str = "run") -> FrameData:
    return FrameData(
        seq=seq,
        run_id=run_id,
        ts=datetime.now(timezone.utc),
        kind=FrameKind.NODE_STATE,
        event_type=UIEventType.NODE_START,
        level=FrameLevel.INFO,
        node_id="scope_idea",
        message="frame",
    )


def _metrics_frames(record: Any) -> list[dict[str, Any]]:
    return [
        dict(frame.details)
        for frame in record.buffer.replay(limit=500)
        if frame.kind is FrameKind.METRICS
    ]


class _UsageRunner:
    """Emit N model calls as llm/token frame pairs, then optionally park.

    This is the shape ``FieldBoundedSerializer`` produces for a real
    ``LLMCallCompletedEvent``, so the accumulation path under test is the
    production one.
    """

    def __init__(self, *, calls: int = 1, park: threading.Event | None = None) -> None:
        self.calls = calls
        self.park = park
        self.emitted = threading.Event()

    def __call__(self, execution: RunExecution) -> dict[str, Any]:
        for index in range(self.calls):
            call_id = f"call-{index}"
            execution.capture.emit(
                kind=FrameKind.LLM,
                event_type=UIEventType.MODEL_CALL,
                node_id="scope_idea",
                message="model call started",
                details={
                    "stage": "before",
                    "call_id": call_id,
                    "model": CHEAP_MODEL,
                },
            )
            execution.capture.emit(
                kind=FrameKind.LLM,
                event_type=UIEventType.MODEL_CALL,
                node_id="scope_idea",
                message="model call completed",
                details={
                    "stage": "after",
                    "call_id": call_id,
                    "model": CHEAP_MODEL,
                },
            )
            execution.capture.emit(
                kind=FrameKind.TOKEN,
                event_type=UIEventType.MODEL_CALL,
                node_id="scope_idea",
                message="Token usage recorded",
                details={
                    "call_id": call_id,
                    "model": CHEAP_MODEL,
                    "usage": {
                        "successful_requests": 1,
                        "prompt_tokens": PROMPT_TOKENS,
                        "completion_tokens": COMPLETION_TOKENS,
                        "total_tokens": PROMPT_TOKENS + COMPLETION_TOKENS,
                        "call_count": 1,
                    },
                },
            )
        self.emitted.set()
        if self.park is not None:
            assert self.park.wait(timeout=10), "the parked runner was never released"
        return {"calls": self.calls}


class _RecordingStore:
    """Records who wrote frames, and when.

    Everything except ``append_frames`` is delegated to a real store when one
    is supplied, so this can stand in for persistence inside a live registry
    without reimplementing the interface.
    """

    def __init__(
        self,
        *,
        block: threading.Event | None = None,
        delegate: Any = None,
    ) -> None:
        self.block = block
        self.delegate = delegate
        self.writes: list[tuple[float, str, int, str]] = []
        self.wrote = threading.Event()
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        delegate = self.__dict__.get("delegate")
        if delegate is None:
            raise AttributeError(name)
        return getattr(delegate, name)

    def append_frames(self, run_id: str, frames: Any) -> None:
        if self.block is not None:
            self.block.wait(timeout=10)
        with self._lock:
            self.writes.append(
                (
                    time.monotonic(),
                    run_id,
                    len(tuple(frames)),
                    threading.current_thread().name,
                )
            )
        self.wrote.set()

    def frame_count(self) -> int:
        with self._lock:
            return sum(count for _, _, count, _ in self.writes)

    def writer_threads(self) -> set[str]:
        with self._lock:
            return {name for _, _, _, name in self.writes}


class RegistryTestCase(unittest.TestCase):
    """A registry over in-memory SQLite with the periodic jobs off by default."""

    def _registry(
        self,
        *,
        runner: Any,
        graph: Any = BRIEF_GRAPH,
        node_registry: Any = BRIEF_NODE_REGISTRY,
        sweep_interval: float = 0.0,
        persistence: Any = "sqlite",
    ) -> RunRegistry:
        store: Any = None
        if persistence == "sqlite":
            store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
            self.addCleanup(store.close)
        elif persistence is not None:
            store = persistence
        registry = RunRegistry(
            graph_version=graph.version,
            node_registry=node_registry,
            runner=runner,
            workflows={
                graph.id: WorkflowRuntime(
                    graph_version=graph.version,
                    node_registry=node_registry,
                    runner=runner,
                )
            },
            persistence=store,
            gate_sweep_interval=sweep_interval,
        )
        self.addCleanup(registry.close)
        return registry

    def _completed_run(
        self,
        registry: RunRegistry,
        *,
        graph: Any = BRIEF_GRAPH,
        inputs: dict[str, Any] | None = None,
        session_id: str = "observability",
    ) -> Any:
        record = registry.create_run(
            session_id=session_id,
            workflow_id=graph.id,
            inputs=inputs or {"topic": "observability"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=10)
        return record


class MetricsFrameTests(RegistryTestCase):
    """PRD F20: FrameKind.METRICS is emitted, and on a defensible cadence."""

    def test_terminal_metrics_frame_carries_run_and_node_usage(self) -> None:
        """Acceptance 1: the snapshot exists and its numbers are right."""
        runner = _UsageRunner(calls=3)
        registry = self._registry(runner=runner)
        record = self._completed_run(registry)

        snapshots = _metrics_frames(record)
        self.assertEqual(len(snapshots), 1, "one authoritative end-of-run snapshot")
        details = snapshots[0]
        self.assertEqual(details["reason"], "run_completed")

        expected_cost = round(
            3 * compute_cost_usd(CHEAP_MODEL, PROMPT_TOKENS, COMPLETION_TOKENS),
            12,
        )
        usage = details["usage"]
        self.assertEqual(usage["prompt_tokens"], 3 * PROMPT_TOKENS)
        self.assertEqual(usage["completion_tokens"], 3 * COMPLETION_TOKENS)
        self.assertEqual(
            usage["total_tokens"], 3 * (PROMPT_TOKENS + COMPLETION_TOKENS)
        )
        self.assertEqual(usage["call_count"], 3)
        self.assertAlmostEqual(usage["cost_usd"], expected_cost, places=12)

        # Per-node/per-model breakdown, which is what the Studio node badges show.
        self.assertEqual(len(details["nodes"]), 1)
        node = details["nodes"][0]
        self.assertEqual(node["node_id"], "scope_idea")
        self.assertEqual(node["model"], CHEAP_MODEL)
        self.assertEqual(node["total_tokens"], usage["total_tokens"])
        self.assertAlmostEqual(node["cost_usd"], expected_cost, places=12)

        # It agrees with the run status the HTTP API serves.
        status = registry.status_payload(record.run_id)
        self.assertEqual(dict(status["usage"]), dict(usage))
        self.assertEqual(details["frames"]["dropped"], 0)

    def test_metrics_are_coalesced_and_cannot_flood_the_ring(self) -> None:
        """Acceptance 1: cadence is per changed tick, never per model call."""
        park = threading.Event()
        self.addCleanup(park.set)
        runner = _UsageRunner(calls=40, park=park)
        registry = self._registry(runner=runner)

        record = registry.create_run(
            session_id="cadence",
            workflow_id=BRIEF_GRAPH.id,
            inputs={"topic": "cadence"},
        )
        registry.start_run(record.run_id)
        self.assertTrue(runner.emitted.wait(timeout=10))

        # 40 model calls have landed and produced no metrics frame at all.
        self.assertEqual(_metrics_frames(record), [])

        # One tick, one frame - and a second tick with nothing new adds none.
        self.assertEqual(registry.sweep_metrics(), 1)
        self.assertEqual(registry.sweep_metrics(), 0)
        self.assertEqual(registry.sweep_metrics(), 0)
        self.assertEqual(len(_metrics_frames(record)), 1)

        park.set()
        registry.wait(record.run_id, timeout=10)

        # Completing added no duplicate: nothing changed after the snapshot
        # above, so the terminal transition had nothing new to report.
        snapshots = _metrics_frames(record)
        self.assertEqual([entry["reason"] for entry in snapshots], ["interval"])
        self.assertEqual(registry.maintenance_status()["metrics_frames"], 1)
        # 40 model calls produced 120 llm/token frames and one metrics frame.
        self.assertGreaterEqual(record.buffer.stats().captured, 120)
        self.assertLess(len(snapshots), record.buffer.stats().captured / 50)

    def test_a_run_with_no_model_calls_emits_no_metrics_frame(self) -> None:
        """Silence is the correct cadence when there is nothing to report."""
        runner = _UsageRunner(calls=0)
        registry = self._registry(runner=runner)
        record = self._completed_run(registry)

        self.assertEqual(_metrics_frames(record), [])
        self.assertEqual(registry.sweep_metrics(), 0)

    def test_the_maintenance_thread_emits_the_interval_snapshot(self) -> None:
        """The cadence is wired to the real background tick, not only to tests."""
        park = threading.Event()
        self.addCleanup(park.set)
        runner = _UsageRunner(calls=2, park=park)
        registry = self._registry(runner=runner, sweep_interval=0.05)

        record = registry.create_run(
            session_id="tick",
            workflow_id=BRIEF_GRAPH.id,
            inputs={"topic": "tick"},
        )
        registry.start_run(record.run_id)
        self.assertTrue(runner.emitted.wait(timeout=10))

        deadline = time.monotonic() + 10
        while not _metrics_frames(record) and time.monotonic() < deadline:
            time.sleep(0.02)
        snapshots = _metrics_frames(record)
        self.assertTrue(snapshots, "the maintenance tick never emitted a snapshot")
        self.assertEqual(snapshots[0]["reason"], "interval")

        park.set()
        registry.wait(record.run_id, timeout=10)

    def test_a_gate_pause_snapshots_before_the_run_goes_idle(self) -> None:
        """A run parked on a human gate reports its totals immediately."""
        registry = self._registry(
            runner=SyntheticValidatorRunner(),
            graph=VALIDATOR_GRAPH,
            node_registry=VALIDATOR_NODE_REGISTRY,
        )
        record = registry.create_run(
            session_id="gate-metrics",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A no-cost synthetic idea"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=10)
        self.assertEqual(record.status, RunStatus.WAITING)

        # The synthetic validator DOES spend tokens now, so the pause has
        # something to report and reports it. This assertion used to read
        # `self.assertEqual(_metrics_frames(record), [])` on the stated grounds
        # that "the synthetic validator spends no tokens" - which was true, and
        # was the defect: the runner emitted no TOKEN frame, so the console's
        # entire spend surface read `CALLS 0 · TOKENS 0 · $0.0000` on a
        # completed run and no free path could exercise it (critic round
        # product-1, P-08). The test was asserting the bug.
        parked = _metrics_frames(record)
        self.assertEqual([entry["reason"] for entry in parked], ["gate_open"])
        self.assertGreater(parked[0]["usage"]["total_tokens"], 0)
        already = int(parked[0]["usage"]["total_tokens"])
        # A second call on top of it still reports, and reports the SUM - which
        # is the property this test was always about.
        record.capture.emit(
            kind=FrameKind.TOKEN,
            event_type=UIEventType.MODEL_CALL,
            node_id="scope_idea",
            message="Token usage recorded",
            details={
                "call_id": "gate-call",
                "model": CHEAP_MODEL,
                "usage": {
                    "prompt_tokens": PROMPT_TOKENS,
                    "completion_tokens": COMPLETION_TOKENS,
                    "total_tokens": PROMPT_TOKENS + COMPLETION_TOKENS,
                },
            },
        )
        gate_id = str(record.pending_gate["gate_id"])
        registry.answer_gate(record.run_id, gate_id, outcome="approve")
        registry.wait(record.run_id, timeout=10)

        snapshots = _metrics_frames(record)
        self.assertEqual(snapshots[0]["reason"], "gate_open")
        # `assertGreaterEqual`, not `assertEqual`: approving the gate lets the
        # rest of the pipeline run, and every node past it now bills too. The
        # property under test is that the injected call is INCLUDED in the
        # total, not that it is the whole of it.
        self.assertGreaterEqual(
            snapshots[-1]["usage"]["total_tokens"],
            already + PROMPT_TOKENS + COMPLETION_TOKENS,
        )


class UnattributedFrameTests(RegistryTestCase):
    """PRD F21: the quarantine node's loss has to be countable, not silent."""

    def test_buffer_counts_only_quarantined_frames(self) -> None:
        buffer = FrameBuffer(capacity=8)
        for node_id in (QUARANTINE_NODE_ID, "scope_idea", QUARANTINE_NODE_ID):
            buffer.push(
                "run-q",
                FrameDraft(
                    ts=datetime.now(timezone.utc),
                    kind=FrameKind.NODE_STATE,
                    event_type=UIEventType.NODE_START,
                    level=FrameLevel.INFO,
                    node_id=node_id,
                    message="frame",
                ),
            )
        stats = buffer.stats()
        self.assertEqual(stats.captured, 3)
        self.assertEqual(stats.unattributed, 2)

    def test_run_status_reports_the_unattributed_count(self) -> None:
        """Acceptance 2: an unresolvable event shows up in run status."""
        runner = _UsageRunner(calls=1)
        registry = self._registry(runner=runner)
        record = self._completed_run(registry)

        self.assertEqual(
            registry.status_payload(record.run_id)["frames"]["unattributed"], 0
        )

        # An event for a method no declared node owns: the exact case PRD 9.3
        # says must be visible rather than dropped on the floor.
        record.capture(
            None,
            MethodExecutionStartedEvent(
                flow_name="BriefFlow",
                method_name="a_method_no_node_declares",
                state={},
                params=None,
            ),
        )

        payload = registry.status_payload(record.run_id)
        self.assertEqual(payload["frames"]["unattributed"], 1)
        quarantined = [
            frame
            for frame in record.buffer.replay(limit=500)
            if frame.node_id == QUARANTINE_NODE_ID
        ]
        self.assertEqual(len(quarantined), 1)
        # And it survives the HTTP response model the Studio consumes.
        self.assertEqual(
            RunStatusResponse.model_validate(payload).frames.unattributed, 1
        )

    def test_the_count_survives_recovery_from_storage(self) -> None:
        """It is derived from the durable frames, so a rehydrated run agrees."""
        runner = _UsageRunner(calls=1)
        registry = self._registry(runner=runner)
        record = self._completed_run(registry)
        record.capture(
            None,
            MethodExecutionStartedEvent(
                flow_name="BriefFlow",
                method_name="a_method_no_node_declares",
                state={},
                params=None,
            ),
        )
        registry._writer.flush()

        evicted = registry.evict_stale_runs(
            now=datetime.now(timezone.utc)
            + timedelta(seconds=VALIDATOR_RUN_RETENTION_SECONDS + 1)
        )
        self.assertEqual(evicted, [record.run_id])
        self.assertEqual(
            registry.status_payload(record.run_id)["frames"]["unattributed"], 1
        )


class FrameWriterCadenceTests(unittest.TestCase):
    """PRD F31: the batch closes on size or on the interval, whichever first."""

    def _writer(self, store: Any, **kwargs: Any) -> _PersistenceWriter:
        writer = _PersistenceWriter(store, lambda run_id: None, **kwargs)
        self.addCleanup(writer.close)
        return writer

    def test_a_partial_batch_is_written_on_the_interval(self) -> None:
        """Acceptance 3: one frame, no flush() call, written on wall time."""
        store = _RecordingStore()
        writer = self._writer(
            store,
            batch_size=100,
            flush_interval=VALIDATOR_FRAME_FLUSH_INTERVAL_SECONDS,
        )

        started = time.monotonic()
        writer.enqueue("run-interval", (_frame(),))
        # Nobody calls flush(); only the interval can close a 1-frame batch.
        self.assertTrue(store.wrote.wait(timeout=5), "the partial batch never landed")
        elapsed = store.writes[0][0] - started

        self.assertEqual(store.frame_count(), 1)
        self.assertGreaterEqual(
            elapsed,
            VALIDATOR_FRAME_FLUSH_INTERVAL_SECONDS * 0.5,
            "the write did not wait for the coalescing window",
        )
        self.assertLess(
            elapsed,
            VALIDATOR_FRAME_FLUSH_INTERVAL_SECONDS * 12,
            "the write was far later than the configured interval",
        )

    def test_reaching_the_batch_size_does_not_wait_for_the_interval(self) -> None:
        """The size trigger still fires first when frames arrive fast."""
        store = _RecordingStore()
        writer = self._writer(store, batch_size=4, flush_interval=30.0)

        started = time.monotonic()
        for seq in range(1, 5):
            writer.enqueue("run-size", (_frame(seq=seq),))

        self.assertTrue(store.wrote.wait(timeout=5), "the full batch never landed")
        self.assertLess(store.writes[0][0] - started, 5.0)
        self.assertEqual(store.frame_count(), 4)

    def test_flush_does_not_wait_out_the_interval(self) -> None:
        """flush() overtakes a long window, so wait()/close() stay prompt."""
        store = _RecordingStore()
        writer = self._writer(store, batch_size=100, flush_interval=30.0)
        writer.enqueue("run-flush", (_frame(),))

        started = time.monotonic()
        writer.flush()
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(store.frame_count(), 1)

    def test_the_writer_thread_stops_cleanly(self) -> None:
        """Acceptance 7: close() drains and joins; nothing is left running."""
        store = _RecordingStore()
        writer = _PersistenceWriter(store, lambda run_id: None)
        writer.enqueue("run-close", (_frame(),))
        writer.close()

        self.assertFalse(writer.thread.is_alive())
        self.assertEqual(store.frame_count(), 1)
        self.assertNotIn(writer.thread, threading.enumerate())


class EventHandlerLatencyTests(RegistryTestCase):
    """The batching thread exists so the capture path never touches the DB."""

    def test_capture_never_blocks_on_or_performs_database_writes(self) -> None:
        """Acceptance 6: emits stay fast while every write is parked."""
        block = threading.Event()
        self.addCleanup(block.set)
        delegate = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(delegate.close)
        store = _RecordingStore(block=block, delegate=delegate)
        registry = self._registry(runner=_UsageRunner(calls=0), persistence=store)

        record = registry.create_run(
            session_id="latency",
            workflow_id=BRIEF_GRAPH.id,
            inputs={"topic": "latency"},
        )

        started = time.monotonic()
        for index in range(200):
            record.capture.emit(
                kind=FrameKind.NODE_STATE,
                event_type=UIEventType.NODE_START,
                node_id="scope_idea",
                message=f"frame {index}",
            )
        elapsed = time.monotonic() - started

        # Every write is still parked inside append_frames.
        self.assertFalse(store.wrote.is_set())
        self.assertLess(elapsed, 2.0, "capture waited on the database")
        self.assertEqual(record.buffer.stats().captured, 200)

        block.set()
        registry._writer.flush()
        self.assertEqual(store.frame_count(), 200)
        # And no frame was ever written from a run worker or the caller.
        self.assertEqual(store.writer_threads(), {WRITER_THREAD_NAME})


class RunEvictionTests(RegistryTestCase):
    """PRD F30: terminal runs leave memory; live ones never do."""

    def _future(self, seconds: int = VALIDATOR_RUN_RETENTION_SECONDS + 60) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=seconds)

    def test_terminal_runs_are_kept_until_the_retention_window_passes(self) -> None:
        registry = self._registry(runner=_UsageRunner(calls=1))
        record = self._completed_run(registry)

        self.assertEqual(registry.evict_stale_runs(), [])
        self.assertEqual(
            registry.evict_stale_runs(
                now=datetime.now(timezone.utc)
                + timedelta(seconds=VALIDATOR_RUN_RETENTION_SECONDS - 60)
            ),
            [],
        )
        self.assertEqual(registry.maintenance_status()["tracked_runs"], 1)

    def test_an_evicted_run_is_rehydrated_from_storage_on_the_next_read(self) -> None:
        """Acceptance 4: memory is freed, the run is not."""
        registry = self._registry(runner=_UsageRunner(calls=2))
        record = self._completed_run(registry)
        before = registry.status_payload(record.run_id)
        frame_count = len(registry.all_frames(record.run_id))

        self.assertEqual(registry.evict_stale_runs(now=self._future()), [record.run_id])
        self.assertEqual(registry.maintenance_status()["tracked_runs"], 0)
        self.assertEqual(registry.maintenance_status()["evicted_runs"], 1)

        after = registry.status_payload(record.run_id)
        self.assertEqual(registry.maintenance_status()["tracked_runs"], 1)
        self.assertEqual(after["status"], RunStatus.COMPLETED)
        self.assertEqual(after["usage"], before["usage"])
        self.assertEqual(after["node_usage"], before["node_usage"])
        self.assertEqual(after["frames"]["captured"], before["frames"]["captured"])
        self.assertEqual(len(registry.all_frames(record.run_id)), frame_count)

    def test_a_waiting_run_is_never_evicted_and_its_gate_still_answers(self) -> None:
        """Acceptance 5: PRD Scenario C survives an arbitrarily late reply."""
        registry = self._registry(
            runner=SyntheticValidatorRunner(),
            graph=VALIDATOR_GRAPH,
            node_registry=VALIDATOR_NODE_REGISTRY,
        )
        record = registry.create_run(
            session_id="late-gate",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A no-cost synthetic idea"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=10)
        self.assertEqual(record.status, RunStatus.WAITING)

        # A year past the retention window, and still not a candidate.
        for offset in (
            VALIDATOR_RUN_RETENTION_SECONDS + 1,
            VALIDATOR_RUN_RETENTION_SECONDS * 100,
            365 * 24 * 60 * 60,
        ):
            self.assertEqual(
                registry.evict_stale_runs(
                    now=datetime.now(timezone.utc) + timedelta(seconds=offset)
                ),
                [],
                f"a WAITING run was evicted {offset}s past its start",
            )
        self.assertEqual(registry.maintenance_status()["tracked_runs"], 1)

        gate_id = str(record.pending_gate["gate_id"])
        registry.answer_gate(record.run_id, gate_id, outcome="approve")
        registry.wait(record.run_id, timeout=10)

        self.assertEqual(record.status, RunStatus.WAITING)
        self.assertEqual(record.pending_gate["node_id"], "review_verdict")

    def test_a_connected_subscriber_pins_a_terminal_run_in_memory(self) -> None:
        registry = self._registry(runner=_UsageRunner(calls=1))
        record = self._completed_run(registry)

        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        subscription_id, _ = record.subscribe(loop)

        self.assertEqual(registry.evict_stale_runs(now=self._future()), [])

        record.unsubscribe(subscription_id)
        self.assertEqual(registry.evict_stale_runs(now=self._future()), [record.run_id])

    def test_eviction_is_refused_without_durable_storage(self) -> None:
        """Without persistence, memory is the only copy of the run."""
        registry = self._registry(runner=_UsageRunner(calls=0), persistence=None)
        record = self._completed_run(registry)

        self.assertEqual(registry.evict_stale_runs(now=self._future()), [])
        self.assertEqual(registry.status_payload(record.run_id)["status"], RunStatus.COMPLETED)


class MaintenanceShutdownTests(RegistryTestCase):
    """Acceptance 7: the shared tick starts once and stops cleanly."""

    def test_close_stops_the_maintenance_and_writer_threads(self) -> None:
        # Compared by identity, not by name: thread names are not unique and
        # another test's registry may still be shutting one down.
        before = set(threading.enumerate())
        registry = self._registry(runner=_UsageRunner(calls=1), sweep_interval=0.05)
        self._completed_run(registry)

        started = [
            thread
            for thread in threading.enumerate()
            if thread.name in {SWEEPER_THREAD_NAME, WRITER_THREAD_NAME}
            and thread not in before
        ]
        self.assertEqual(
            {thread.name for thread in started},
            {SWEEPER_THREAD_NAME, WRITER_THREAD_NAME},
        )
        # One periodic thread carries all three jobs.
        self.assertEqual(
            len([t for t in started if t.name == SWEEPER_THREAD_NAME]), 1
        )

        registry.close()
        for thread in started:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive(), f"{thread.name} outlived close()")


if __name__ == "__main__":
    unittest.main()
