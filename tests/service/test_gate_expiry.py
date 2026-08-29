"""Server-side human-gate expiry - PRD F03 and risk R-2.

F03 makes expiry *advisory*: an unanswered gate past its deadline is marked
expired and a frame is pushed, but the run is neither failed nor auto-answered,
and a late reply still resumes it (PRD Scenario C, guarantee G5).

Every test here is no-cost: the synthetic validator runner produces the two
durable gates with no LLM, no tool and no network call, and the sweeper is
driven with an explicit ``now`` so nothing waits on a wall clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from brief_crew.config import VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS
from brief_crew.events import FrameKind
from brief_crew.service import registry as registry_module
from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY
from brief_crew.service.models import RunStatus
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import RunRecord, RunRegistry, WorkflowRuntime
from brief_crew.service.runner import SyntheticValidatorRunner


SWEEPER_THREAD_NAME = "validator-gate-sweeper"


def _kinds(record: RunRecord, kind: FrameKind) -> list[dict[str, object]]:
    return [
        dict(frame.details)
        for frame in record.buffer.replay()
        if frame.kind is kind
    ]


def _deadline(record: RunRecord) -> datetime:
    prompt = record.pending_gate
    assert prompt is not None
    return datetime.fromisoformat(str(prompt["expires_at"]))


class GateExpiryTestCase(unittest.TestCase):
    """A validator registry parked on its first gate, with the sweeper off."""

    def setUp(self) -> None:
        # The R-2 alert logs at ERROR by design. Quiet it here so the suite's
        # output stays readable; the test that asserts the alert re-enables it
        # through assertLogs.
        logger = logging.getLogger("brief_crew.service.registry")
        previous = logger.level
        logger.setLevel(logging.CRITICAL)
        self.addCleanup(logger.setLevel, previous)

    def _registry(
        self,
        *,
        database_url: str = "sqlite+pysqlite:///:memory:",
        sweep_interval: float = 0.0,
    ) -> tuple[RunRegistry, PostgresFlowPersistence]:
        store = PostgresFlowPersistence(database_url)
        runner = SyntheticValidatorRunner()
        registry = RunRegistry(
            graph_version=VALIDATOR_GRAPH.version,
            node_registry=VALIDATOR_NODE_REGISTRY,
            runner=runner,
            workflows={
                VALIDATOR_GRAPH.id: WorkflowRuntime(
                    graph_version=VALIDATOR_GRAPH.version,
                    node_registry=VALIDATOR_NODE_REGISTRY,
                    runner=runner,
                )
            },
            persistence=store,
            gate_sweep_interval=sweep_interval,
        )
        self.addCleanup(store.close)
        self.addCleanup(registry.close)
        return registry, store

    def _waiting_run(
        self,
        registry: RunRegistry,
        *,
        timeout_seconds: int = 0,
        session_id: str = "gate-expiry",
    ) -> RunRecord:
        """Park a run on its scope gate with a chosen gate timeout.

        Patching the constant the registry reads is how a deterministic deadline
        is produced without a fake clock; ``0`` means the gate opens already due.
        """
        with patch.object(
            registry_module,
            "VALIDATOR_GATE_TIMEOUT_SECONDS",
            timeout_seconds,
        ):
            record = registry.create_run(
                session_id=session_id,
                workflow_id=VALIDATOR_GRAPH.id,
                inputs={"idea": "A no-cost synthetic idea"},
            )
            registry.start_run(record.run_id)
            registry.wait(record.run_id, timeout=5)
        self.assertEqual(record.status, RunStatus.WAITING)
        self.assertIsNotNone(record.pending_gate)
        return record


class GateExpiryReportingTests(GateExpiryTestCase):
    def test_expired_gate_is_reported_by_the_run_status_payload(self) -> None:
        """Acceptance 1: an unanswered gate past expires_at reads as expired."""
        registry, _ = self._registry()
        expired_run = self._waiting_run(registry, timeout_seconds=0)
        live_run = self._waiting_run(
            registry,
            timeout_seconds=1800,
            session_id="gate-live",
        )

        expired_gate = registry.status_payload(expired_run.run_id)["pending_gate"]
        live_gate = registry.status_payload(live_run.run_id)["pending_gate"]

        self.assertTrue(expired_gate["expired"])
        self.assertFalse(live_gate["expired"])
        # Reporting is derived from expires_at, so it is already correct before
        # the first sweep tick rather than lagging it.
        self.assertEqual(registry.gate_watch_status()["sweeps"], 0)

    def test_expired_gate_leaves_the_run_waiting_and_unanswered(self) -> None:
        """Acceptance 2 and 3: no failure, no cancellation, no auto-answer."""
        registry, _ = self._registry()
        record = self._waiting_run(registry, timeout_seconds=0)
        gate_id = str(record.pending_gate["gate_id"])
        frames_before = len(record.buffer.replay())
        moment = _deadline(record) + timedelta(
            seconds=VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS + 600
        )

        for _ in range(4):
            registry.sweep_gates(now=moment)

        self.assertEqual(record.status, RunStatus.WAITING)
        self.assertNotIn(record.status, {RunStatus.FAILED, RunStatus.CANCELLED})
        self.assertIsNotNone(record.pending_gate)
        self.assertEqual(str(record.pending_gate["gate_id"]), gate_id)
        self.assertEqual(record.pending_gate["node_id"], "confirm_scope")
        self.assertEqual(record.answered_gates, set())
        # Nothing answered the gate, so the flow never left it: no gate_closed,
        # and none of the post-gate nodes ever ran.
        self.assertEqual(_kinds(record, FrameKind.GATE_CLOSED), [])
        emitted_nodes = {frame.node_id for frame in record.buffer.replay()}
        self.assertNotIn("route_scope", emitted_nodes)
        self.assertNotIn("research_market", emitted_nodes)
        # Only the watch frames were added; the run produced nothing else.
        self.assertEqual(len(record.buffer.replay()), frames_before + 2)

    def test_reply_after_expiry_is_accepted_and_resumes_the_run(self) -> None:
        """Acceptance 4: Scenario C - the operator comes back and it still works."""
        registry, store = self._registry()
        record = self._waiting_run(registry, timeout_seconds=0)
        first_gate_id = str(record.pending_gate["gate_id"])
        registry.sweep_gates(
            now=_deadline(record)
            + timedelta(seconds=VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS)
        )
        self.assertEqual(
            store.get_gate(record.run_id, first_gate_id)["status"], "alerted"
        )

        registry.answer_gate(
            record.run_id,
            first_gate_id,
            outcome="approve",
            fields={"category": "Design tooling"},
        )
        registry.wait(record.run_id, timeout=5)

        closed = _kinds(record, FrameKind.GATE_CLOSED)
        self.assertEqual(len(closed), 1)
        self.assertTrue(closed[0]["late"])
        self.assertEqual(record.status, RunStatus.WAITING)
        self.assertEqual(record.pending_gate["node_id"], "review_verdict")
        self.assertNotEqual(str(record.pending_gate["gate_id"]), first_gate_id)
        self.assertIsNotNone(
            store.get_gate(record.run_id, first_gate_id)["answered_at"]
        )

        registry.answer_gate(
            record.run_id,
            str(record.pending_gate["gate_id"]),
            outcome="approve",
        )
        result = registry.wait(record.run_id, timeout=5)
        self.assertEqual(record.status, RunStatus.COMPLETED)
        self.assertEqual(result["verdict"], "NEEDS_WORK")


class GateExpirySweepTests(GateExpiryTestCase):
    def test_expiry_frame_is_emitted_once_across_many_sweeps(self) -> None:
        """Acceptance 5: once per expired gate, not once per tick."""
        registry, store = self._registry()
        record = self._waiting_run(registry, timeout_seconds=0)
        gate_id = str(record.pending_gate["gate_id"])
        moment = _deadline(record) + timedelta(seconds=1)

        first = registry.sweep_gates(now=moment)
        for _ in range(5):
            registry.sweep_gates(now=moment)

        self.assertEqual(first["expired_now"], 1)
        expired_frames = _kinds(record, FrameKind.GATE_EXPIRED)
        self.assertEqual(len(expired_frames), 1)
        self.assertEqual(expired_frames[0]["gate_id"], gate_id)
        self.assertEqual(expired_frames[0]["node_id"], "confirm_scope")
        self.assertFalse(expired_frames[0]["auto_answered"])
        self.assertTrue(expired_frames[0]["resumable"])
        self.assertEqual(registry.gate_watch_status()["expiries"], 1)
        self.assertEqual(store.get_gate(record.run_id, gate_id)["status"], "expired")
        # Advisory only: the durable gate is still unanswered and still pending.
        self.assertIsNone(store.get_gate(record.run_id, gate_id)["answered_at"])
        self.assertEqual(
            store.get_pending_gate(record.run_id)["gate_id"], gate_id
        )

    def test_alert_fires_only_after_the_configured_grace_period(self) -> None:
        """Acceptance 6: R-2 is timeout + grace, never timeout."""
        registry, store = self._registry()
        record = self._waiting_run(registry, timeout_seconds=0)
        gate_id = str(record.pending_gate["gate_id"])
        deadline = _deadline(record)
        grace = timedelta(seconds=VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS)

        at_timeout = registry.sweep_gates(now=deadline)
        just_inside = registry.sweep_gates(now=deadline + grace - timedelta(seconds=1))

        self.assertEqual(at_timeout["expired"], 1)
        self.assertEqual(at_timeout["alerting"], 0)
        self.assertEqual(just_inside["alerting"], 0)
        self.assertEqual(_kinds(record, FrameKind.GATE_ALERT), [])
        self.assertEqual(registry.gate_watch_status()["alerts"], 0)
        self.assertEqual(store.get_gate(record.run_id, gate_id)["status"], "expired")

        with self.assertLogs("brief_crew.service.registry", level="ERROR") as logs:
            at_grace = registry.sweep_gates(now=deadline + grace)
            for _ in range(3):
                registry.sweep_gates(now=deadline + grace + timedelta(minutes=5))

        # One alert log line, not one per sweep.
        self.assertEqual(len(logs.records), 1)
        self.assertIn("R-2", logs.output[0])
        self.assertEqual(at_grace["alerts_now"], 1)
        alerts = _kinds(record, FrameKind.GATE_ALERT)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert"], "gate_open_without_gate_closed")
        self.assertEqual(
            alerts[0]["grace_seconds"], VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS
        )
        self.assertEqual(registry.gate_watch_status()["alerts"], 1)
        self.assertEqual(store.get_gate(record.run_id, gate_id)["status"], "alerted")
        self.assertEqual(_kinds(record, FrameKind.GATE_EXPIRED).__len__(), 1)

    def test_answered_gate_is_never_swept(self) -> None:
        registry, _ = self._registry()
        record = self._waiting_run(registry, timeout_seconds=0)
        deadline = _deadline(record)
        registry.answer_gate(
            record.run_id,
            str(record.pending_gate["gate_id"]),
            outcome="approve",
        )
        registry.wait(record.run_id, timeout=5)

        # The second gate is still live, so only it is counted.
        counters = registry.sweep_gates(now=deadline + timedelta(hours=1))
        self.assertEqual(counters["open"], 1)
        self.assertEqual(
            _kinds(record, FrameKind.GATE_EXPIRED)[0]["node_id"],
            "review_verdict",
        )


class GateExpiryRecoveryTests(GateExpiryTestCase):
    def test_gate_expired_while_down_is_reported_after_recovery(self) -> None:
        """Acceptance 7: a new registry over the same database reports it."""
        with TemporaryDirectory() as directory:
            database_url = (
                "sqlite+pysqlite:///"
                f"{(Path(directory) / 'validator-studio.db').as_posix()}"
            )
            first, first_store = self._registry(database_url=database_url)
            record = self._waiting_run(first, timeout_seconds=0)
            run_id = record.run_id
            gate_id = str(record.pending_gate["gate_id"])
            deadline = _deadline(record)
            # The process dies before any sweep runs: the gate row is still open.
            self.assertEqual(
                first_store.get_gate(run_id, gate_id)["status"], "open"
            )
            first.close()
            first_store.close()

            recovered, recovered_store = self._registry(database_url=database_url)
            payload = recovered.status_payload(run_id)

            self.assertEqual(payload["status"], RunStatus.WAITING)
            self.assertTrue(payload["pending_gate"]["expired"])
            self.assertEqual(payload["pending_gate"]["gate_id"], gate_id)

            # The sweeper finds it from the database, not from a live record.
            counters = recovered.sweep_gates(
                now=deadline
                + timedelta(seconds=VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS)
            )
            self.assertEqual(counters["expired_now"], 1)
            self.assertEqual(counters["alerts_now"], 1)
            self.assertEqual(
                recovered_store.get_gate(run_id, gate_id)["status"], "alerted"
            )
            # Windows keeps the file locked until the engine is disposed.
            recovered.close()
            recovered_store.close()

    def test_recovery_does_not_re_emit_watch_frames_already_recorded(self) -> None:
        with TemporaryDirectory() as directory:
            database_url = (
                "sqlite+pysqlite:///"
                f"{(Path(directory) / 'validator-studio.db').as_posix()}"
            )
            first, first_store = self._registry(database_url=database_url)
            record = self._waiting_run(first, timeout_seconds=0)
            run_id = record.run_id
            deadline = _deadline(record)
            first.sweep_gates(
                now=deadline
                + timedelta(seconds=VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS)
            )
            first.wait(run_id, timeout=5)
            first.close()
            first_store.close()

            recovered, recovered_store = self._registry(database_url=database_url)
            counters = recovered.sweep_gates(now=deadline + timedelta(days=1))
            restored = recovered.require(run_id)

            self.assertEqual(counters["expired_now"], 0)
            self.assertEqual(counters["alerts_now"], 0)
            self.assertEqual(len(_kinds(restored, FrameKind.GATE_EXPIRED)), 1)
            self.assertEqual(len(_kinds(restored, FrameKind.GATE_ALERT)), 1)
            self.assertTrue(
                recovered.status_payload(run_id)["pending_gate"]["expired"]
            )
            recovered.close()
            recovered_store.close()


class GateSweeperLifecycleTests(GateExpiryTestCase):
    def test_sweeper_thread_starts_and_stops_cleanly(self) -> None:
        """Acceptance 8: no hang on exit and no leaked thread."""
        before = {
            thread
            for thread in threading.enumerate()
            if thread.name == SWEEPER_THREAD_NAME
        }
        registry = RunRegistry(
            graph_version=VALIDATOR_GRAPH.version,
            node_registry=VALIDATOR_NODE_REGISTRY,
            runner=SyntheticValidatorRunner(),
            gate_sweep_interval=0.02,
        )
        started = [
            thread
            for thread in threading.enumerate()
            if thread.name == SWEEPER_THREAD_NAME and thread not in before
        ]
        self.assertEqual(len(started), 1)
        sweeper = started[0]
        self.assertTrue(sweeper.daemon)

        deadline = datetime.now(timezone.utc) + timedelta(seconds=5)
        while registry.gate_watch_status()["sweeps"] < 2:
            if datetime.now(timezone.utc) > deadline:
                self.fail("the sweeper never ran")
            time.sleep(0.005)

        registry.close()

        sweeper.join(timeout=5)
        self.assertFalse(sweeper.is_alive())
        self.assertNotIn(sweeper, threading.enumerate())
        registry.close()  # idempotent, and still must not hang

    def test_sweeper_can_be_disabled(self) -> None:
        registry = RunRegistry(
            graph_version=VALIDATOR_GRAPH.version,
            node_registry=VALIDATOR_NODE_REGISTRY,
            runner=SyntheticValidatorRunner(),
            gate_sweep_interval=0,
        )
        self.addCleanup(registry.close)
        self.assertIsNone(registry._sweeper)
        with self.assertRaises(ValueError):
            RunRegistry(
                graph_version=VALIDATOR_GRAPH.version,
                node_registry=VALIDATOR_NODE_REGISTRY,
                runner=SyntheticValidatorRunner(),
                gate_sweep_interval=-1,
            )


class GateWatchPersistenceTests(GateExpiryTestCase):
    def test_watch_ladder_keeps_the_gate_answerable(self) -> None:
        registry, store = self._registry()
        record = self._waiting_run(registry, timeout_seconds=0)
        gate_id = str(record.pending_gate["gate_id"])

        store.expire_gate(record.run_id, gate_id, status="expired")
        store.expire_gate(record.run_id, gate_id, status="alerted")
        gate = store.get_gate(record.run_id, gate_id)
        self.assertEqual(gate["status"], "alerted")
        self.assertIsNone(gate["answered_at"])
        self.assertEqual(store.get_run(record.run_id)["status"], "waiting")

        answer = store.answer_gate(record.run_id, gate_id, outcome="approve")
        self.assertTrue(answer.accepted)
        self.assertFalse(answer.conflict)

        with self.assertRaises(ValueError):
            store.expire_gate(record.run_id, gate_id, status="answered")

    def test_list_open_gates_filters_on_the_deadline(self) -> None:
        registry, store = self._registry()
        due = self._waiting_run(registry, timeout_seconds=0)
        live = self._waiting_run(
            registry,
            timeout_seconds=1800,
            session_id="gate-live",
        )
        moment = _deadline(due) + timedelta(seconds=1)

        self.assertEqual(
            {gate["run_id"] for gate in store.list_open_gates()},
            {due.run_id, live.run_id},
        )
        self.assertEqual(
            [gate["run_id"] for gate in store.list_open_gates(due_by=moment)],
            [due.run_id],
        )
        with self.assertRaises(ValueError):
            store.list_open_gates(limit=0)


if __name__ == "__main__":
    unittest.main()
