"""The orphan sweep claims a run before it fails it - plan 15 D8's fourth path.

Plan 15 D8 and CLAUDE.md remaining-work item 3 both count the orphan-run
sweep among the `UPDATE ... WHERE ...; rowcount` compare-and-set paths. Until
this change it was not one: `_fail_interrupted` reached storage through
`update_run_status`, which guards on `id` alone, so two API instances sweeping
one store - a deploy overlapping the instance it replaces, which
`autoDeploy: yes` makes routine - would BOTH reconcile the same stale row, each
writing its own terminal status and its own frames.

`claim_run_status` is the guard: `UPDATE runs SET status = ... WHERE id = ...
AND status IN (<what the sweeper loaded>)`. Exactly one sweeper's claim lands;
the other sees `rowcount == 0`, learns the row is already terminal, drops the
stale in-memory copy and counts nothing. `tests/pg/test_two_writers.py` drives
two real processes into that UPDATE on PostgreSQL; this module pins the shape
on SQLite, where the loser is simulated by a write that lands between the
sweeper's read and its claim.

The adopt path (`running` with a real open gate behind it, put back to
`waiting`) is deliberately NOT claimed: two adoptions write the same status
over the same anchor and the reply that follows is guarded by `answer_gate`'s
own compare-and-set.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import unittest
from unittest.mock import patch

from brief_crew.events import FrameKind
from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY
from brief_crew.service.models import RunStatus
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import RunRegistry, WorkflowRuntime
from brief_crew.service.runner import SyntheticValidatorRunner


class ClaimCase(unittest.TestCase):
    def setUp(self) -> None:
        self.store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.store.close)
        logger = logging.getLogger("brief_crew.service.registry")
        previous = logger.level
        logger.setLevel(logging.CRITICAL)
        self.addCleanup(logger.setLevel, previous)

    def seed(self, run_id: str, status: str, *, age: timedelta = timedelta(hours=2)) -> None:
        self.store.create_run(
            run_id=run_id,
            session_id="claim",
            workflow_id=VALIDATOR_GRAPH.id,
            graph_version=VALIDATOR_GRAPH.version,
            inputs={"idea": "an interrupted idea"},
            flow_id=run_id,
            status=status,
            created_at=datetime.now(timezone.utc) - age,
        )

    def registry(self, **options: object) -> RunRegistry:
        runner = SyntheticValidatorRunner()
        settings: dict[str, object] = {"gate_sweep_interval": 0.0, "recover_orphans": False}
        settings.update(options)
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
            persistence=self.store,
            **settings,
        )
        self.addCleanup(registry.close)
        return registry


class StoreClaimTests(ClaimCase):
    def test_a_claim_from_the_loaded_status_lands_and_stamps_completion(self) -> None:
        self.seed("orphan", "running")
        self.assertTrue(
            self.store.claim_run_status("orphan", "failed", expected_statuses=("running",))
        )
        row = self.store.get_run("orphan")
        self.assertEqual(row["status"], "failed")
        self.assertIsNotNone(row["completed_at"])

    def test_a_second_claim_from_the_same_loaded_status_is_refused(self) -> None:
        """The whole point: two sweepers, one winner."""

        self.seed("orphan", "running")
        first = self.store.claim_run_status("orphan", "failed", expected_statuses=("running",))
        second = self.store.claim_run_status(
            "orphan", "cancelled", expected_statuses=("running",)
        )
        self.assertEqual((first, second), (True, False))
        self.assertEqual(self.store.get_run("orphan")["status"], "failed")

    def test_the_expected_set_may_name_several_statuses(self) -> None:
        self.seed("orphan", "cancelling")
        self.assertTrue(
            self.store.claim_run_status(
                "orphan",
                RunStatus.CANCELLED,
                expected_statuses=(RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.CANCELLING),
            )
        )
        self.assertEqual(self.store.get_run("orphan")["status"], "cancelled")

    def test_a_non_terminal_target_leaves_completed_at_alone(self) -> None:
        self.seed("orphan", "running")
        self.assertTrue(
            self.store.claim_run_status("orphan", "waiting", expected_statuses=("running",))
        )
        self.assertIsNone(self.store.get_run("orphan")["completed_at"])

    def test_an_unknown_run_is_a_false_not_an_error(self) -> None:
        self.assertFalse(
            self.store.claim_run_status("missing", "failed", expected_statuses=("running",))
        )

    def test_an_empty_expected_set_is_refused_by_name(self) -> None:
        self.seed("orphan", "running")
        with self.assertRaises(ValueError):
            self.store.claim_run_status("orphan", "failed", expected_statuses=())


class SweepLoserTests(ClaimCase):
    def _reconciled_elsewhere_first(self, run_id: str) -> None:
        """Wrap the claim so another process's write lands just before it.

        Patched on the class: the store is a pydantic model and refuses an
        instance attribute it has no field for.
        """

        real = PostgresFlowPersistence.claim_run_status

        def claim(store: PostgresFlowPersistence, *args: object, **kwargs: object) -> bool:
            store.update_run_status(run_id, "failed", error="reconciled elsewhere")
            return real(store, *args, **kwargs)

        patcher = patch.object(PostgresFlowPersistence, "claim_run_status", claim)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_loser_counts_nothing_writes_nothing_and_drops_its_copy(self) -> None:
        self.seed("orphan", "running")
        registry = self.registry()
        registry.recover_orphans = True
        self._reconciled_elsewhere_first("orphan")

        recovered = registry.recover_orphaned_runs()

        self.assertEqual(recovered, [])
        self.assertEqual(registry.maintenance_status()["interrupted_runs"], 0)
        self.assertNotIn("orphan", registry._records)
        # Storage carries the OTHER process's reconciliation, untouched.
        row = self.store.get_run("orphan")
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error"], "reconciled elsewhere")
        registry.close()
        self.assertEqual(
            [f["message"] for f in self.store.replay_frames("orphan") if f["kind"] == "error"],
            [],
        )

    def test_the_loser_s_next_read_is_the_stored_truth(self) -> None:
        self.seed("orphan", "running")
        registry = self.registry()
        registry.recover_orphans = True
        self._reconciled_elsewhere_first("orphan")
        registry.recover_orphaned_runs()

        record = registry.require("orphan")
        self.assertIs(record.status, RunStatus.FAILED)
        self.assertEqual(record.error, "reconciled elsewhere")

    def test_the_loser_says_so_in_the_log(self) -> None:
        self.seed("orphan", "running")
        registry = self.registry()
        registry.recover_orphans = True
        self._reconciled_elsewhere_first("orphan")
        with self.assertLogs("brief_crew.service.registry", level="INFO") as logs:
            registry.recover_orphaned_runs()
        self.assertTrue(
            any("reconciled by another process first" in line for line in logs.output),
            logs.output,
        )


class SweepWinnerTests(ClaimCase):
    def test_the_winner_still_fails_the_run_loudly(self) -> None:
        """The existing behaviour, re-proved through the claim."""

        self.seed("orphan", "running")
        registry = self.registry()
        registry.recover_orphans = True

        self.assertEqual(registry.recover_orphaned_runs(), ["orphan"])

        self.assertEqual(registry.maintenance_status()["interrupted_runs"], 1)
        record = registry.require("orphan")
        self.assertIs(record.status, RunStatus.FAILED)
        self.assertEqual(
            len([f for f in record.buffer.replay() if f.kind is FrameKind.ERROR]), 1
        )
        self.assertEqual(self.store.get_run("orphan")["status"], "failed")

    def test_a_cancelling_orphan_is_claimed_as_cancelled(self) -> None:
        self.seed("orphan", "cancelling")
        registry = self.registry()
        registry.recover_orphans = True
        self.assertEqual(registry.recover_orphaned_runs(), ["orphan"])
        self.assertEqual(self.store.get_run("orphan")["status"], "cancelled")

    def test_a_store_without_the_claim_keeps_the_old_unconditional_sweep(self) -> None:
        self.seed("orphan", "running")
        registry = self.registry()
        registry.recover_orphans = True
        # An older persistence, or a double, with no compare-and-set to offer.
        with patch.object(PostgresFlowPersistence, "claim_run_status", None):
            self.assertEqual(registry.recover_orphaned_runs(), ["orphan"])
        self.assertEqual(self.store.get_run("orphan")["status"], "failed")
