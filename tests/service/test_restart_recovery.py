"""A run interrupted by a process restart must stop lying - remaining item 32.

Observed in production: run ``e0b3b65e-…`` streamed 102 frames, its API
restarted for a redeploy, and hours later the row still reported
``status: "running"`` with ``pending_gate: null``. ``cancel()`` on it only
reached CANCELLING and stayed there, because there was no live future left to
hit a ``PRE_STEP`` boundary, so the operator had no lever at all.

The chosen behaviour, and why:

* A run parked at a **gate** is resumable and is never touched here. Its
  ``run_gates`` row and its ``pending_feedback`` row survive the restart and
  ``from_pending()``/``resume()`` rebuild it - the existing recovery tests in
  ``test_gate_expiry.py`` cover that, and one test below re-proves the resume
  still works *after* a recovery sweep has run over it.
* A run that was **mid-method** is NOT resumable. ``Flow.from_pending()``
  raises ``ValueError`` with no pending-feedback row, and
  ``kickoff(inputs={"id": …})`` reloads the state with an empty completed-method
  set, which re-runs the flow from ``@start`` at full price. So it is failed
  with a reason, and the frame says so.
* ``cancelling`` becomes ``cancelled``: the operator asked for the run to stop
  and it stopped, in the least graceful way available.

Every test here is no-cost: durable rows are seeded through the store or
produced by ``SyntheticValidatorRunner``, and nothing waits on a wall clock -
the sweep takes an injected ``now`` and the false-positive test parks its
worker on a ``threading.Event`` rather than sleeping and hoping.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from fastapi.testclient import TestClient

from brief_crew.config import VALIDATOR_ORPHAN_RUN_GRACE_SECONDS
from brief_crew.events import FrameKind, FrameLevel
from brief_crew.service.app import create_app
from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY
from brief_crew.service.models import RunStatus
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import (
    INTERRUPTED_REASON,
    RunRecord,
    RunRegistry,
    WorkflowRuntime,
)
from brief_crew.service.runner import RunExecution, SyntheticValidatorRunner


def _frames(record: RunRecord, kind: FrameKind) -> list[dict[str, object]]:
    return [
        dict(frame.details)
        for frame in record.buffer.replay()
        if frame.kind is kind
    ]


class _ParkedRunner:
    """A runner that blocks inside the run until the test releases it.

    This is how "a run that is genuinely executing right now" is made
    deterministic: the worker thread is provably still inside ``__call__``
    while the sweep looks at it, with no sleeping and no timing assumption.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, execution: RunExecution) -> dict[str, object]:
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise AssertionError("the parked runner was never released")
        return {"parked": True}


class RestartRecoveryTestCase(unittest.TestCase):
    """Registries over a store the test controls, with the sweeper thread off."""

    def setUp(self) -> None:
        # The recovery logs at WARNING by design - it is the operator's only
        # notice that a run was reconciled. Quiet it so the suite output stays
        # readable; the test that asserts the log re-enables it.
        logger = logging.getLogger("brief_crew.service.registry")
        previous = logger.level
        logger.setLevel(logging.CRITICAL)
        self.addCleanup(logger.setLevel, previous)

    def _store(self, database_url: str = "sqlite+pysqlite:///:memory:"):
        store = PostgresFlowPersistence(database_url)
        self.addCleanup(store.close)
        return store

    def _registry(
        self,
        store: PostgresFlowPersistence,
        *,
        runner=None,
        orphan_grace: float | None = None,
        recover_orphans: bool | None = None,
    ) -> RunRegistry:
        """A registry over an existing store. A second one IS a restart."""
        runner = runner or SyntheticValidatorRunner()
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
            gate_sweep_interval=0.0,
            orphan_grace=orphan_grace,
            recover_orphans=recover_orphans,
        )
        self.addCleanup(registry.close)
        return registry

    def _seed_run(
        self,
        store: PostgresFlowPersistence,
        *,
        run_id: str,
        status: str,
        age: timedelta = timedelta(0),
        mode: str | None = None,
    ) -> dict[str, object]:
        """Write the durable row a dead process leaves behind.

        ``create_run`` stamps ``updated_at`` from ``created_at``, so passing an
        age here produces a row that is already outside the grace window
        without any clock patching.
        """
        return store.create_run(
            run_id=run_id,
            session_id="restart-recovery",
            workflow_id=VALIDATOR_GRAPH.id,
            graph_version=VALIDATOR_GRAPH.version,
            inputs={"idea": "A no-cost synthetic idea"},
            flow_id=run_id,
            status=status,
            created_at=datetime.now(timezone.utc) - age,
            mode=mode,
        )

    def _waiting_run(self, registry: RunRegistry) -> RunRecord:
        record = registry.create_run(
            session_id="restart-recovery",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A no-cost synthetic idea"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=5)
        self.assertEqual(record.status, RunStatus.WAITING)
        return record


class InterruptedRunTests(RestartRecoveryTestCase):
    def test_running_row_with_no_live_future_reaches_a_terminal_state(self) -> None:
        """The defect itself: a fresh registry must not leave it `running`.

        The row is seeded BEFORE the registry exists, and nothing calls the
        sweep - which is the whole point. Construction is the restart, and the
        run has to be terminal by the time anyone can ask about it.
        """
        store = self._store()
        self._seed_run(store, run_id="orphan-running", status="running")

        registry = self._registry(store, orphan_grace=0)

        self.assertEqual(registry.maintenance_status()["interrupted_runs"], 1)
        payload = registry.status_payload("orphan-running")
        self.assertEqual(payload["status"], RunStatus.FAILED)
        self.assertIsNone(payload["pending_gate"])
        self.assertIn("interrupted by a service restart", str(payload["error"]))
        # And durably, which is the half the operator's `select` reads.
        self.assertEqual(store.get_run("orphan-running")["status"], "failed")
        self.assertIsNotNone(store.get_run("orphan-running")["completed_at"])

    def test_the_trace_explains_itself_with_an_error_frame(self) -> None:
        """The client is told why, not just that it stopped."""
        store = self._store()
        self._seed_run(store, run_id="orphan-frame", status="running")
        registry = self._registry(store, orphan_grace=0)
        record = registry.require("orphan-frame")

        errors = [
            frame
            for frame in record.buffer.replay()
            if frame.kind is FrameKind.ERROR
        ]
        self.assertEqual(len(errors), 1)
        frame = errors[0]
        # The Studio maps `kind === 'error'` to a terminal error state and
        # shows `message`, so the message has to be the human sentence.
        self.assertEqual(frame.message, "Run interrupted by a service restart")
        self.assertIs(frame.level, FrameLevel.ERROR)
        self.assertEqual(frame.node_id, VALIDATOR_NODE_REGISTRY.workflow_node_id)
        self.assertEqual(frame.details["reason"], INTERRUPTED_REASON)
        self.assertEqual(frame.details["interrupted_status"], "running")
        self.assertIn("relaunch it", str(frame.details["error"]))
        # The frame is durable too, so it survives into the NDJSON/ZIP export.
        # close() drains the batching writer, which is how the queued frame
        # reaches storage without a sleep.
        registry.close()
        exported = store.replay_frames("orphan-frame")
        self.assertIn(
            "Run interrupted by a service restart",
            [row["message"] for row in exported],
        )

    def test_cancelling_row_reaches_cancelled_not_failed(self) -> None:
        """`cancel()` on an orphan reached CANCELLING and stopped there."""
        store = self._store()
        registry = self._registry(store, orphan_grace=0)
        self._seed_run(store, run_id="orphan-cancelling", status="cancelling")

        recovered = registry.recover_orphaned_runs()
        record = registry.require("orphan-cancelling")

        self.assertEqual(recovered, ["orphan-cancelling"])
        self.assertEqual(record.status, RunStatus.CANCELLED)
        self.assertEqual(store.get_run("orphan-cancelling")["status"], "cancelled")
        # A cancellation is not a failure: no ERROR frame, and the RUN_STATE
        # frame carries the same `status: cancelled` shape _execute emits, so
        # the existing client handling reaches a terminal state unchanged.
        self.assertEqual(_frames(record, FrameKind.ERROR), [])
        run_states = [
            details
            for details in _frames(record, FrameKind.RUN_STATE)
            if details.get("status") == "cancelled"
        ]
        self.assertEqual(len(run_states), 1)
        self.assertEqual(run_states[0]["reason"], INTERRUPTED_REASON)
        self.assertIsNone(record.error)

    def test_queued_row_is_reconciled_too(self) -> None:
        """A run admitted but never submitted is stranded the same way."""
        store = self._store()
        registry = self._registry(store, orphan_grace=0)
        self._seed_run(store, run_id="orphan-queued", status="queued")

        self.assertEqual(registry.recover_orphaned_runs(), ["orphan-queued"])
        self.assertEqual(store.get_run("orphan-queued")["status"], "failed")

    def test_recovery_is_counted_for_monitoring(self) -> None:
        store = self._store()
        registry = self._registry(store, orphan_grace=0)
        self._seed_run(store, run_id="orphan-count-a", status="running")
        self._seed_run(store, run_id="orphan-count-b", status="cancelling")

        registry.recover_orphaned_runs()

        self.assertEqual(registry.maintenance_status()["interrupted_runs"], 2)

    def test_recovery_is_idempotent(self) -> None:
        """A second sweep must not fail an already-terminal run again."""
        store = self._store()
        registry = self._registry(store, orphan_grace=0)
        self._seed_run(store, run_id="orphan-twice", status="running")

        first = registry.recover_orphaned_runs()
        second = registry.recover_orphaned_runs()
        record = registry.require("orphan-twice")

        self.assertEqual(first, ["orphan-twice"])
        self.assertEqual(second, [])
        self.assertEqual(len(_frames(record, FrameKind.ERROR)), 1)

    def test_recovery_announces_itself_in_the_log(self) -> None:
        store = self._store()
        registry = self._registry(store, orphan_grace=0)
        self._seed_run(store, run_id="orphan-logged", status="running")

        logging.getLogger("brief_crew.service.registry").setLevel(logging.NOTSET)
        with self.assertLogs("brief_crew.service.registry", level="WARNING") as logs:
            registry.recover_orphaned_runs()

        self.assertTrue(
            any("interrupted by a service restart" in line for line in logs.output),
            logs.output,
        )


class TestModeRunTests(RestartRecoveryTestCase):
    """10 criterion 11: a `test`-mode run is failed at startup like any other.

    Decision 17 says a test run is FINDABLE, not privileged: it holds an
    admission slot, it bills, it streams, and when the process that was running
    it dies it is an orphan exactly like a `run`. A sweep that skipped one -
    because "it was only a test" - would leave the one shape of row this whole
    mechanism exists to clear.
    """

    def test_a_test_mode_run_interrupted_mid_method_is_failed_at_startup(self) -> None:
        store = self._store()
        self._seed_run(store, run_id="orphan-test", status="running", mode="test")

        registry = self._registry(store, orphan_grace=0)

        payload = registry.status_payload("orphan-test")
        self.assertEqual(payload["status"], RunStatus.FAILED)
        self.assertIn("interrupted by a service restart", str(payload["error"]))
        row = store.get_run("orphan-test")
        self.assertEqual(row["status"], "failed")
        # And it is still a test run afterwards: the sweep changes the STATUS
        # and never the kind.
        self.assertEqual(row["mode"], "test")

    def test_a_test_run_and_an_ordinary_one_are_swept_together(self) -> None:
        store = self._store()
        self._seed_run(store, run_id="orphan-plain", status="running")
        self._seed_run(store, run_id="orphan-test-2", status="running", mode="test")

        registry = self._registry(store, orphan_grace=0)

        self.assertEqual(registry.maintenance_status()["interrupted_runs"], 2)
        for run_id in ("orphan-plain", "orphan-test-2"):
            with self.subTest(run_id=run_id):
                self.assertEqual(store.get_run(run_id)["status"], "failed")

    def test_a_row_written_with_no_mode_reads_back_as_run(self) -> None:
        """The additive column's contract, at the one place recovery reads a row."""

        store = self._store()
        self._seed_run(store, run_id="orphan-null-mode", status="running")
        self._registry(store, orphan_grace=0)
        self.assertEqual(store.get_run("orphan-null-mode")["mode"], "run")


class LiveRunIsNeverTouchedTests(RestartRecoveryTestCase):
    """The dangerous false positive: killing a run that is actually working."""

    def test_a_run_executing_right_now_is_not_recovered(self) -> None:
        store = self._store()
        runner = _ParkedRunner()
        registry = self._registry(store, runner=runner, orphan_grace=0)
        record = registry.create_run(
            session_id="restart-recovery",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A no-cost synthetic idea"},
        )
        future = registry.start_run(record.run_id)
        # Deterministic: the worker is provably inside the runner, not asleep.
        self.assertTrue(runner.entered.wait(timeout=5))
        self.assertEqual(record.status, RunStatus.RUNNING)
        self.assertEqual(store.get_run(record.run_id)["status"], "running")

        # Grace zero AND a `now` a day ahead: every time-based guard is
        # deliberately disarmed, so only the live-future guard can save it.
        recovered = registry.recover_orphaned_runs(
            now=datetime.now(timezone.utc) + timedelta(days=1)
        )

        self.assertEqual(recovered, [])
        self.assertEqual(record.status, RunStatus.RUNNING)
        self.assertEqual(_frames(record, FrameKind.ERROR), [])
        self.assertIsNone(record.error)

        runner.release.set()
        future.result(timeout=10)
        self.assertEqual(record.status, RunStatus.COMPLETED)

    def test_an_admitted_but_unsubmitted_run_is_not_recovered(self) -> None:
        """`create_run` holds a reservation, not a future, until `_submit`."""
        store = self._store()
        registry = self._registry(store, orphan_grace=0)
        record = registry.create_run(
            session_id="restart-recovery",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A no-cost synthetic idea"},
        )
        self.assertEqual(record.status, RunStatus.QUEUED)

        recovered = registry.recover_orphaned_runs(
            now=datetime.now(timezone.utc) + timedelta(days=1)
        )

        self.assertEqual(recovered, [])
        self.assertEqual(record.status, RunStatus.QUEUED)
        # The reservation still converts into a real run afterwards.
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=5)
        self.assertEqual(record.status, RunStatus.WAITING)

    def test_a_fresh_row_inside_the_grace_window_is_left_alone(self) -> None:
        """The window that covers a deploy overlap and the settle wait."""
        store = self._store()
        self._seed_run(store, run_id="recent-running", status="running")
        registry = self._registry(store)

        self.assertEqual(registry.recover_orphaned_runs(), [])
        self.assertEqual(store.get_run("recent-running")["status"], "running")

        # The same row, once the window has passed, is reconciled - so the
        # window is a delay, never an amnesty.
        later = datetime.now(timezone.utc) + timedelta(
            seconds=VALIDATOR_ORPHAN_RUN_GRACE_SECONDS + 60
        )
        self.assertEqual(registry.recover_orphaned_runs(now=later), ["recent-running"])

    def test_terminal_rows_are_never_considered(self) -> None:
        store = self._store()
        for index, status in enumerate(("completed", "failed", "cancelled")):
            self._seed_run(store, run_id=f"terminal-{index}", status=status)
        registry = self._registry(store, orphan_grace=0)

        self.assertEqual(registry.recover_orphaned_runs(), [])
        self.assertEqual(
            [row["run_id"] for row in store.list_stale_runs()],
            [],
        )

    def test_recovery_can_be_switched_off(self) -> None:
        """The escape hatch for more than one API process on one database."""
        store = self._store()
        self._seed_run(store, run_id="orphan-untouched", status="running")

        registry = self._registry(store, orphan_grace=0, recover_orphans=False)
        self.assertEqual(registry.maintenance_status()["interrupted_runs"], 0)

        self.assertEqual(registry.recover_orphaned_runs(), [])
        self.assertEqual(store.get_run("orphan-untouched")["status"], "running")


class WaitingRunIsNeverTouchedTests(RestartRecoveryTestCase):
    def test_a_gate_survives_the_recovery_and_still_resumes(self) -> None:
        """WAITING is anchored: recovery must not come near it."""
        with TemporaryDirectory() as directory:
            database_url = (
                "sqlite+pysqlite:///"
                f"{(Path(directory) / 'validator-studio.db').as_posix()}"
            )
            first_store = self._store(database_url)
            first = self._registry(first_store, orphan_grace=0)
            record = self._waiting_run(first)
            run_id = record.run_id
            gate_id = str(record.pending_gate["gate_id"])
            first.close()
            first_store.close()

            # The restart.
            second_store = self._store(database_url)
            second = self._registry(second_store, orphan_grace=0)
            recovered = second.recover_orphaned_runs(
                now=datetime.now(timezone.utc) + timedelta(days=1)
            )

            self.assertEqual(recovered, [])
            payload = second.status_payload(run_id)
            self.assertEqual(payload["status"], RunStatus.WAITING)
            self.assertEqual(payload["pending_gate"]["gate_id"], gate_id)
            self.assertIsNone(payload["error"])

            # And the whole point of leaving it alone: it still resumes.
            second.answer_gate(run_id, gate_id, outcome="approve")
            second.wait(run_id, timeout=5)
            resumed = second.require(run_id)
            self.assertEqual(resumed.status, RunStatus.WAITING)
            self.assertEqual(resumed.pending_gate["node_id"], "review_verdict")
            second.close()
            second_store.close()

    def test_a_run_interrupted_at_the_gate_write_is_healed_not_failed(self) -> None:
        """The one interrupted shape that really is resumable.

        ``_mark_pending`` writes the pending feedback and the gate row before it
        marks the record WAITING and persists the status, so a process that
        dies in between leaves ``running`` on a run that is actually parked at
        a gate. Failing that would throw away a resumable run.
        """
        store = self._store()
        first = self._registry(store, orphan_grace=0)
        record = self._waiting_run(first)
        run_id = record.run_id
        gate_id = str(record.pending_gate["gate_id"])
        # Rewind the durable row to the instant before the status write.
        store.update_run_status(run_id, "running")
        first.close()

        second = self._registry(store, orphan_grace=0)
        recovered = second.recover_orphaned_runs(
            now=datetime.now(timezone.utc) + timedelta(days=1)
        )
        restored = second.require(run_id)

        self.assertEqual(recovered, [])
        self.assertEqual(second.maintenance_status()["readopted_gates"], 1)
        self.assertEqual(restored.status, RunStatus.WAITING)
        self.assertEqual(store.get_run(run_id)["status"], "waiting")
        self.assertIsNotNone(restored.pending_context)
        self.assertEqual(_frames(restored, FrameKind.ERROR), [])
        # Answerable, which is what "healed" has to mean.
        second.answer_gate(run_id, gate_id, outcome="approve")
        second.wait(run_id, timeout=5)
        self.assertEqual(
            second.require(run_id).pending_gate["node_id"], "review_verdict"
        )


class StartupSweepTests(RestartRecoveryTestCase):
    def test_a_new_registry_reconciles_stale_rows_at_construction(self) -> None:
        """A restart is a new registry, so the boot pass is the first sweep."""
        store = self._store()
        self._seed_run(
            store,
            run_id="orphan-at-boot",
            status="running",
            age=timedelta(seconds=VALIDATOR_ORPHAN_RUN_GRACE_SECONDS + 3600),
        )

        # No explicit sweep call: construction alone must have done it.
        registry = self._registry(store)

        self.assertEqual(store.get_run("orphan-at-boot")["status"], "failed")
        self.assertEqual(registry.maintenance_status()["interrupted_runs"], 1)

    def test_the_startup_sweep_survives_a_broken_store(self) -> None:
        """A storage fault must degrade the recovery, not stop the service."""

        class _AngryStore:
            persistence_type = "angry"

            def list_stale_runs(self, **_: object) -> list[dict[str, object]]:
                raise RuntimeError("storage is down")

            def create_run(self, **_: object) -> dict[str, object]:
                return {}

        registry = RunRegistry(
            graph_version=VALIDATOR_GRAPH.version,
            node_registry=VALIDATOR_NODE_REGISTRY,
            runner=SyntheticValidatorRunner(),
            persistence=_AngryStore(),
            gate_sweep_interval=0.0,
            orphan_grace=0,
        )
        self.addCleanup(registry.close)

        self.assertEqual(registry.recover_orphaned_runs(), [])

    def test_the_recovery_rides_the_existing_maintenance_tick(self) -> None:
        """One sweeper thread, one shutdown path - not a second timer."""
        store = self._store()
        self._seed_run(
            store,
            run_id="orphan-on-tick",
            status="running",
            age=timedelta(seconds=VALIDATOR_ORPHAN_RUN_GRACE_SECONDS + 3600),
        )
        registry = self._registry(store, recover_orphans=False)
        self.assertEqual(store.get_run("orphan-on-tick")["status"], "running")

        # The tick body, run directly: no thread, no wall clock.
        registry.recover_orphans = True
        for job, _message in (
            (registry.sweep_gates, ""),
            (registry.sweep_metrics, ""),
            (registry.evict_stale_runs, ""),
            (registry.recover_orphaned_runs, ""),
        ):
            job()

        self.assertEqual(store.get_run("orphan-on-tick")["status"], "failed")


class ClientVisibleStateTests(RestartRecoveryTestCase):
    def test_the_api_reports_a_terminal_run_with_a_reason(self) -> None:
        """What the operator's browser gets after the restart."""
        store = self._store()
        self._seed_run(store, run_id="orphan-http", status="running")
        registry = self._registry(store, orphan_grace=0)

        with TestClient(create_app(registry=registry)) as client:
            response = client.get("/api/runs/orphan-http")
            frames = client.get("/api/runs/orphan-http/frames").json()["frames"]

        self.assertEqual(response.status_code, 200)
        body = response.json()
        # `failed` is what studioApi.normalizeRunStatus already maps to the
        # client's terminal `error`, so no frontend change is needed.
        self.assertEqual(body["status"], "failed")
        self.assertIsNone(body["pending_gate"])
        self.assertIn("interrupted by a service restart", body["error"])
        self.assertIn("relaunch it", body["error"])
        self.assertIn(
            "Run interrupted by a service restart",
            [frame["data"]["message"] for frame in frames],
        )

    def test_cancel_on_a_reconciled_run_reports_it_as_already_terminal(self) -> None:
        """The operator's lever comes back: no more permanent CANCELLING."""
        store = self._store()
        self._seed_run(store, run_id="orphan-cancel", status="running")
        registry = self._registry(store, orphan_grace=0)

        outcome = registry.cancel("orphan-cancel")

        self.assertEqual(outcome["status"], RunStatus.FAILED)
        self.assertEqual(outcome["effect"], "run is already terminal")


class StaleRunScanTests(RestartRecoveryTestCase):
    def test_the_scan_selects_only_live_statuses(self) -> None:
        store = self._store()
        for status in ("queued", "running", "waiting", "cancelling", "completed"):
            self._seed_run(store, run_id=f"scan-{status}", status=status)

        found = {row["run_id"] for row in store.list_stale_runs()}

        self.assertEqual(found, {"scan-queued", "scan-running", "scan-cancelling"})

    def test_the_scan_honours_the_liveness_cut_and_the_limit(self) -> None:
        store = self._store()
        self._seed_run(store, run_id="scan-old", status="running", age=timedelta(hours=2))
        self._seed_run(store, run_id="scan-new", status="running")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

        older = store.list_stale_runs(updated_before=cutoff)

        self.assertEqual([row["run_id"] for row in older], ["scan-old"])
        self.assertEqual(len(store.list_stale_runs(limit=1)), 1)
        with self.assertRaises(ValueError):
            store.list_stale_runs(limit=0)

    def test_a_persisted_frame_refreshes_the_liveness_heartbeat(self) -> None:
        """`updated_at` is a heartbeat, which is what makes the cut honest."""
        store = self._store()
        self._seed_run(store, run_id="scan-beat", status="running", age=timedelta(hours=2))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        self.assertEqual(len(store.list_stale_runs(updated_before=cutoff)), 1)

        store.append_frames(
            "scan-beat",
            [
                {
                    "v": 1,
                    "seq": 1,
                    "run_id": "scan-beat",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "kind": "node_state",
                    "event_type": "NODE_START",
                    "level": "INFO",
                    "node_id": "research_market",
                    "message": "Market Analyst started",
                    "details": {},
                }
            ],
        )

        self.assertEqual(store.list_stale_runs(updated_before=cutoff), [])


if __name__ == "__main__":  # pragma: no cover - parity with the other suites
    unittest.main()
