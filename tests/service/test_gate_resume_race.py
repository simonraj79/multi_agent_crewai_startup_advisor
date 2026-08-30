"""The gate-reply / settling-future race, and the wedged run it used to leave.

Reproduced live before this file existed: 3 wedged runs out of ~16 gate
replies. ``_mark_pending`` publishes the gate - durable row, WAITING status,
GATE_OPEN frame - and only *then* does ``_execute`` return and its future
complete. A reply that arrived inside that window was refused by ``_submit``
as "already executing", but the durable compare-and-set in ``answer_gate`` had
already accepted it, so the run sat at RUNNING forever with ``pending_gate``
null and 409 on every retry. Polling for ``status == "waiting"`` first did not
help: ``mark_waiting`` happens *inside* the same window.

Every test here is no-cost. The runner is a subclass of the synthetic
validator runner - no LLM, no tool, no network - and the database is in-memory
SQLite. Nothing waits on a wall clock for correctness: the worker thread is
parked on a ``threading.Event`` inside the exact window under test, and each
test asserts, from the registry's own bookkeeping, that the reply really did
reach ``_submit`` while the previous future was still live.
"""

from __future__ import annotations

from concurrent.futures import Future
import threading
from typing import Any
import unittest

from brief_crew.events import FrameKind, FrameLevel
from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY
from brief_crew.service.models import RunStatus
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import (
    RunBusyError,
    RunRecord,
    RunRegistry,
    WorkflowRuntime,
)
from brief_crew.service.runner import RunExecution, SyntheticValidatorRunner


# How long the parked worker holds its future open when the test releases it
# on a bound rather than on an explicit signal. Long enough that the reply on
# the main thread provably lands inside the window (each test asserts that it
# did), short enough that a failing test finishes rather than hangs.
WORKER_HOLD_SECONDS = 0.75
# The bound a *genuinely* busy run must be refused within. Well under the
# production default so a refusal cannot be mistaken for a hang.
SHORT_SETTLE_TIMEOUT = 0.1
JOIN_TIMEOUT = 15.0


class ParkingRegistry(RunRegistry):
    """A registry whose worker thread can be held inside ``_mark_pending``.

    Two seams, both read-only with respect to the behaviour under test:

    ``_mark_pending`` parks *after* the real one has run, which is the precise
    window the bug lives in - the gate is durable, the record says WAITING, the
    GATE_OPEN frame is out, and the future has not completed.

    ``_submit`` records whether the previous future was still live when a
    resume reached it. Without that, a test that accidentally lost the race
    would still pass while exercising nothing.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.gate_published = threading.Event()
        self.release_worker = threading.Event()
        self.park_hold_seconds: float | None = WORKER_HOLD_SECONDS
        # Release the parked worker the moment a resume provably reaches
        # ``_submit`` with the future still live. Without this the success
        # path depends on wall clock - the worker unparks on a 0.75s bound
        # while the settle wait allows 5s - and a loaded machine (two suites
        # at once, say) can invert them and refuse a reply the test expects to
        # succeed. The refusal tests turn this off, because a refusal is
        # exactly what they are asserting.
        self.release_on_resume = True
        self.note_error_after_park = False
        self.parked_gates = 0
        self.resume_saw_live_future: bool | None = None
        super().__init__(*args, **kwargs)

    def _mark_pending(self, record: RunRecord, pending: Any) -> None:
        super()._mark_pending(record, pending)
        # Only the first gate parks; the second must resume normally so the
        # run can be watched all the way out of RUNNING.
        if self.parked_gates:
            return
        self.parked_gates += 1
        self.gate_published.set()
        self.release_worker.wait(timeout=self.park_hold_seconds)
        if self.note_error_after_park:
            # The real hazard, reproduced exactly: a frame emitted from
            # _execute's tail while the persistence queue is full reaches
            # _note_persistence_error, which takes the registry lock on this
            # worker thread. If _submit waited while holding that lock, this
            # call would block forever and the future would never settle.
            self._note_persistence_error(record.run_id)

    def _submit(
        self,
        record: RunRecord,
        *,
        context: Any = None,
        feedback: str = "",
    ) -> Future[Any]:
        if context is not None:
            with self._lock:
                current = self._futures.get(record.run_id)
            self.resume_saw_live_future = (
                current is not None and not current.done()
            )
            if self.resume_saw_live_future and self.release_on_resume:
                # The window has been entered and recorded; hold it no longer.
                # super()._submit is about to wait for this future, so letting
                # the worker go now makes the settle deterministic instead of
                # a race between two timeouts.
                self.release_worker.set()
        return super()._submit(record, context=context, feedback=feedback)


class BlockingRunner:
    """A run that never reaches a gate and stays busy until released."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, execution: RunExecution) -> dict[str, Any]:
        self.started.set()
        self.release.wait(timeout=JOIN_TIMEOUT)
        return {"blocked": True, "run_id": execution.run_id}


class GateResumeRaceTestCase(unittest.TestCase):
    def _registry(
        self,
        *,
        runner: Any = None,
        settle_timeout: float | None = None,
        registry_class: type[RunRegistry] = ParkingRegistry,
    ) -> tuple[RunRegistry, PostgresFlowPersistence]:
        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        flow_runner = runner if runner is not None else SyntheticValidatorRunner()
        registry = registry_class(
            graph_version=VALIDATOR_GRAPH.version,
            node_registry=VALIDATOR_NODE_REGISTRY,
            runner=flow_runner,
            workflows={
                VALIDATOR_GRAPH.id: WorkflowRuntime(
                    graph_version=VALIDATOR_GRAPH.version,
                    node_registry=VALIDATOR_NODE_REGISTRY,
                    runner=flow_runner,
                )
            },
            persistence=store,
            gate_sweep_interval=0.0,
            submit_settle_timeout=settle_timeout,
        )
        self.addCleanup(store.close)
        self.addCleanup(registry.close)
        return registry, store

    def _parked_at_first_gate(
        self,
        registry: ParkingRegistry,
    ) -> tuple[RunRecord, str]:
        """Start a run and return once its scope gate is published but unsettled."""
        record = registry.create_run(
            session_id="gate-resume-race",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A no-cost synthetic idea"},
        )
        future = registry.start_run(record.run_id)
        self.assertTrue(
            registry.gate_published.wait(timeout=JOIN_TIMEOUT),
            "the synthetic runner never reached its first gate",
        )
        # This is the whole bug in three assertions: the client has everything
        # it needs to reply, and the run's future has not completed.
        self.assertEqual(record.status, RunStatus.WAITING)
        self.assertIsNotNone(record.pending_gate)
        self.assertFalse(future.done())
        prompt = record.pending_gate
        assert prompt is not None
        return record, str(prompt["gate_id"])


class GateReplyDuringSettlingFutureTests(GateResumeRaceTestCase):
    def test_reply_inside_the_settling_window_is_accepted_and_resumes(self) -> None:
        """The reproduction: a reply on a live future now resumes the run."""
        registry, _ = self._registry()
        assert isinstance(registry, ParkingRegistry)
        record, gate_id = self._parked_at_first_gate(registry)

        registry.answer_gate(record.run_id, gate_id, outcome="approve")

        self.assertIs(
            registry.resume_saw_live_future,
            True,
            "the reply did not reach _submit while the first future was live, "
            "so this test exercised nothing",
        )
        registry.wait(record.run_id, timeout=JOIN_TIMEOUT)
        # The resume ran: the synthetic validator's second gate is open.
        self.assertEqual(record.status, RunStatus.WAITING)
        self.assertIsNotNone(record.pending_gate)
        prompt = record.pending_gate
        assert prompt is not None
        self.assertNotEqual(str(prompt["gate_id"]), gate_id)
        self.assertEqual(prompt["node_id"], "review_verdict")

    def test_the_run_never_wedges_in_running_without_a_gate(self) -> None:
        """Acceptance 2: status leaves RUNNING and pending_gate stays truthful."""
        registry, store = self._registry()
        assert isinstance(registry, ParkingRegistry)
        record, gate_id = self._parked_at_first_gate(registry)

        registry.answer_gate(record.run_id, gate_id, outcome="approve")
        registry.wait(record.run_id, timeout=JOIN_TIMEOUT)

        payload = registry.status_payload(record.run_id)
        self.assertNotEqual(payload["status"], RunStatus.RUNNING)
        self.assertEqual(payload["status"], RunStatus.WAITING)
        self.assertIsNotNone(payload["pending_gate"])
        # The wedged run's signature was a durably answered gate with nothing
        # left to answer. Both durable facts now agree with the record.
        first = store.get_gate(record.run_id, gate_id)
        assert first is not None
        self.assertIsNotNone(first["answered_at"])
        pending = store.get_pending_gate(record.run_id)
        assert pending is not None
        self.assertNotEqual(pending["gate_id"], gate_id)

        # And the second gate answers normally, so the run reaches a terminal
        # state rather than parking forever.
        second = record.pending_gate
        assert second is not None
        registry.answer_gate(
            record.run_id,
            str(second["gate_id"]),
            outcome="approve",
        )
        registry.wait(record.run_id, timeout=JOIN_TIMEOUT)
        self.assertEqual(record.status, RunStatus.COMPLETED)

    def test_the_settling_wait_does_not_hold_the_registry_lock(self) -> None:
        """The deadlock this fix could have introduced, reproduced not argued.

        ``_execute``'s tail emits frames, and a frame emitted while the
        persistence queue is full reaches ``_note_persistence_error``, which
        takes ``self._lock`` *on the worker thread*. If ``_submit`` waited for
        that thread while holding the same lock, the worker would block
        forever, the future would never settle, the wait would time out and
        the reply would be refused. The parked worker makes that call here, so
        a lock-holding wait fails this test as a RunBusyError rather than
        hanging the suite.
        """
        registry, _ = self._registry()
        assert isinstance(registry, ParkingRegistry)
        registry.note_error_after_park = True
        record, gate_id = self._parked_at_first_gate(registry)

        registry.answer_gate(record.run_id, gate_id, outcome="approve")

        self.assertIs(registry.resume_saw_live_future, True)
        self.assertGreaterEqual(record.buffer.stats().emit_errors, 1)
        registry.wait(record.run_id, timeout=JOIN_TIMEOUT)
        self.assertEqual(record.status, RunStatus.WAITING)


class BusyRunRefusalTests(GateResumeRaceTestCase):
    def test_a_genuinely_executing_run_is_refused_within_the_timeout(self) -> None:
        """Acceptance 3: the wait is bounded, and a busy run still raises."""
        runner = BlockingRunner()
        registry, _ = self._registry(
            runner=runner,
            settle_timeout=SHORT_SETTLE_TIMEOUT,
            registry_class=RunRegistry,
        )
        record = registry.create_run(
            session_id="busy-run",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A run that never reaches a gate"},
        )
        registry.start_run(record.run_id)
        self.assertTrue(runner.started.wait(timeout=JOIN_TIMEOUT))

        try:
            with self.assertRaises(RunBusyError) as caught:
                registry.start_run(record.run_id)
        finally:
            runner.release.set()
        self.assertIn(record.run_id, str(caught.exception))
        self.assertEqual(caught.exception.run_id, record.run_id)
        registry.wait(record.run_id, timeout=JOIN_TIMEOUT)
        self.assertEqual(record.status, RunStatus.COMPLETED)

    def test_the_settle_timeout_is_validated(self) -> None:
        """A non-positive bound would make the wait meaningless or infinite."""
        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(store.close)
        with self.assertRaises(ValueError):
            RunRegistry(
                graph_version=VALIDATOR_GRAPH.version,
                node_registry=VALIDATOR_NODE_REGISTRY,
                runner=SyntheticValidatorRunner(),
                persistence=store,
                gate_sweep_interval=0.0,
                submit_settle_timeout=0.0,
            )


class BusyResumeRollbackTests(GateResumeRaceTestCase):
    """The secondary fix: a refused resume must not leave a wedged run."""

    def _refused_reply(
        self,
    ) -> tuple[ParkingRegistry, PostgresFlowPersistence, RunRecord, str]:
        registry, store = self._registry(settle_timeout=SHORT_SETTLE_TIMEOUT)
        assert isinstance(registry, ParkingRegistry)
        # Hold the worker until the test says otherwise, so the settle wait is
        # guaranteed to time out.
        registry.park_hold_seconds = JOIN_TIMEOUT
        registry.release_on_resume = False
        self.addCleanup(registry.release_worker.set)
        record, gate_id = self._parked_at_first_gate(registry)
        with self.assertRaises(RunBusyError):
            registry.answer_gate(record.run_id, gate_id, outcome="approve")
        return registry, store, record, gate_id

    def test_a_refused_resume_reopens_the_gate_durably(self) -> None:
        _registry, store, record, gate_id = self._refused_reply()
        gate = store.get_gate(record.run_id, gate_id)
        assert gate is not None
        self.assertIsNone(gate["answered_at"])
        self.assertEqual(gate["status"], "open")
        run = store.get_run(record.run_id)
        assert run is not None
        self.assertEqual(run["status"], "waiting")

    def test_a_refused_resume_leaves_the_record_answerable(self) -> None:
        registry, _store, record, gate_id = self._refused_reply()
        self.assertEqual(record.status, RunStatus.WAITING)
        self.assertNotIn(gate_id, record.answered_gates)
        prompt = record.pending_gate
        assert prompt is not None
        self.assertEqual(str(prompt["gate_id"]), gate_id)
        payload = registry.status_payload(record.run_id)
        self.assertEqual(payload["status"], RunStatus.WAITING)
        assert payload["pending_gate"] is not None
        self.assertEqual(str(payload["pending_gate"]["gate_id"]), gate_id)

    def test_a_refused_resume_says_so_in_the_frame_stream(self) -> None:
        _registry, _store, record, gate_id = self._refused_reply()
        frames = list(record.buffer.replay())
        alerts = [frame for frame in frames if frame.kind is FrameKind.GATE_ALERT]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, FrameLevel.WARNING)
        self.assertEqual(alerts[0].details["reason"], "run_busy")
        self.assertEqual(alerts[0].details["gate_id"], gate_id)
        # The client applied GATE_CLOSED, so the gate has to be re-offered
        # after it, not before.
        kinds = [
            frame.kind
            for frame in frames
            if frame.kind in {FrameKind.GATE_OPEN, FrameKind.GATE_CLOSED}
        ]
        self.assertEqual(
            kinds,
            [FrameKind.GATE_OPEN, FrameKind.GATE_CLOSED, FrameKind.GATE_OPEN],
        )

    def test_the_same_reply_succeeds_once_the_run_settles(self) -> None:
        """The point of rolling back: retrying is not 409, it works."""
        registry, store, record, gate_id = self._refused_reply()
        registry.release_worker.set()
        registry.wait(record.run_id, timeout=JOIN_TIMEOUT)

        registry.answer_gate(record.run_id, gate_id, outcome="approve")
        registry.wait(record.run_id, timeout=JOIN_TIMEOUT)

        gate = store.get_gate(record.run_id, gate_id)
        assert gate is not None
        self.assertIsNotNone(gate["answered_at"])
        self.assertEqual(record.status, RunStatus.WAITING)
        prompt = record.pending_gate
        assert prompt is not None
        self.assertEqual(prompt["node_id"], "review_verdict")

    def test_reopen_gate_leaves_an_unanswered_gate_alone(self) -> None:
        """The compensating write is a compare-and-set in its own right."""
        registry, store = self._registry()
        assert isinstance(registry, ParkingRegistry)
        registry.release_worker.set()
        record = registry.create_run(
            session_id="reopen-cas",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A no-cost synthetic idea"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=JOIN_TIMEOUT)
        prompt = record.pending_gate
        assert prompt is not None
        gate_id = str(prompt["gate_id"])

        gate = store.reopen_gate(record.run_id, gate_id)
        self.assertIsNone(gate["answered_at"])
        self.assertEqual(gate["status"], "open")
        with self.assertRaises(KeyError):
            store.reopen_gate(record.run_id, "no-such-gate")


class BusyResumeTransportTests(GateResumeRaceTestCase):
    """A refused reply must read as retryable, not as a server fault."""

    def test_the_http_gate_route_answers_503(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:  # pragma: no cover - service extra absent
            self.skipTest("fastapi is not installed")
        from brief_crew.service.app import create_app

        registry, _store = self._registry(settle_timeout=SHORT_SETTLE_TIMEOUT)
        assert isinstance(registry, ParkingRegistry)
        registry.park_hold_seconds = JOIN_TIMEOUT
        registry.release_on_resume = False
        self.addCleanup(registry.release_worker.set)
        record, gate_id = self._parked_at_first_gate(registry)

        app = create_app(registry=registry)
        with TestClient(app) as client:
            response = client.post(
                f"/api/runs/{record.run_id}/gates/{gate_id}",
                json={"outcome": "approve", "fields": {}},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("retry", response.json()["detail"])
        # 503 is only honest if the gate really is answerable again.
        self.assertEqual(record.status, RunStatus.WAITING)
        prompt = record.pending_gate
        assert prompt is not None
        self.assertEqual(str(prompt["gate_id"]), gate_id)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
