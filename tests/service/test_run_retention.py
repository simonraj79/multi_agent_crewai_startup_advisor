"""Retention - plan 15 D7. Terminal runs older than the window are deleted.

CLAUDE.md closed item 32 ends with "there is still no retention or purge, so
terminal rows accumulate". This is the purge. `VALIDATOR_RUN_RETENTION_DAYS`
(config, default `0` = keep forever, PLANS.md decision 23) drives it, in the
same periodic sweep the orphan recovery uses, AFTER the recovery: a row the
recovery just failed is terminal from this tick and old from the next, never
both at once, so the two jobs cannot disagree about one run.

What it deletes: `completed` / `failed` / `cancelled` runs whose
`completed_at` (or `updated_at`, for a row that reached a terminal status
without one) is older than the window, and with them `run_frames`,
`run_node_metrics` and `run_gates` - by name, because SQLite does not honour
`ON DELETE CASCADE` without a pragma this service never sets.

What it never deletes, each pinned below: a run `waiting` on a gate at any
age; a terminal run that still has an UNANSWERED gate row (a shape
`_close_interrupted_gate` should have retired, refused anyway rather than
trusted); `queued` / `running` / `cancelling`, which are the orphan sweep's to
judge; anything inside the window; and anything that is not a run - documents,
versions, credentials, skills and tools are never touched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import time
import unittest
from unittest.mock import patch

from sqlalchemy import func, select

from brief_crew.config import VALIDATOR_RUN_RETENTION_DAYS
from brief_crew.events import FrameData, FrameKind, FrameLevel, UIEventType
from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY
from brief_crew.service.models import RunStatus
from brief_crew.service.persistence import (
    PostgresFlowPersistence,
    builder_documents,
    run_frames,
    run_gates,
    run_node_metrics,
)
from brief_crew.service.registry import RunRegistry, WorkflowRuntime
from brief_crew.service.runner import SyntheticValidatorRunner
from tests.builder.test_compiler import straight_line

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
GATE = "scope-confirmation"


def _frame(run_id: str, seq: int) -> FrameData:
    return FrameData(
        seq=seq,
        run_id=run_id,
        ts=NOW - timedelta(days=100),
        kind=FrameKind.RUN_STATE,
        event_type=UIEventType.WORKFLOW_START,
        level=FrameLevel.INFO,
        node_id="workflow",
        message=f"frame {seq}",
        details={"ordinal": seq},
    )


class RetentionCase(unittest.TestCase):
    def setUp(self) -> None:
        self.store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.store.close)
        for name in ("brief_crew.service.persistence", "brief_crew.service.registry"):
            logger = logging.getLogger(name)
            previous = logger.level
            logger.setLevel(logging.CRITICAL)
            self.addCleanup(logger.setLevel, previous)

    def seed(
        self,
        run_id: str,
        status: str,
        *,
        age_days: float,
        gate: str | None = None,
        completed_at: bool = True,
    ) -> None:
        """A run that reached `status` `age_days` before NOW, with children.

        `gate="open"` leaves an unanswered `run_gates` row behind; `"answered"`
        answers it. `completed_at=False` reaches the terminal status through
        `create_run` alone, so the column is NULL and the age has to be read
        off `updated_at` - the row shape a status write without a timestamp
        produces.
        """

        finished = NOW - timedelta(days=age_days)
        if not completed_at:
            self.store.create_run(
                run_id=run_id,
                session_id="retention",
                workflow_id=VALIDATOR_GRAPH.id,
                graph_version=VALIDATOR_GRAPH.version,
                inputs={"idea": "an old idea"},
                status=status,
                created_at=finished,
            )
            return
        self.store.create_run(
            run_id=run_id,
            session_id="retention",
            workflow_id=VALIDATOR_GRAPH.id,
            graph_version=VALIDATOR_GRAPH.version,
            inputs={"idea": "an old idea"},
            status="queued",
            created_at=finished - timedelta(minutes=5),
        )
        self.store.append_frames(run_id, [_frame(run_id, 1), _frame(run_id, 2)])
        self.store.save_node_metrics(run_id, "scope_idea", total_tokens=10, call_count=1)
        if gate is not None:
            self.store.open_gate(
                run_id,
                GATE,
                node_id="confirm_scope",
                request={"title": "Confirm the scope"},
                opened_at=finished,
            )
            if gate == "answered":
                self.store.answer_gate(run_id, GATE, outcome="ok", answered_at=finished)
        self.store.update_run_status(run_id, status, completed_at=finished)

    def children(self, run_id: str) -> tuple[int, int, int]:
        with self.store.connect() as connection:
            counts = []
            for table in (run_frames, run_node_metrics, run_gates):
                counts.append(
                    int(
                        connection.execute(
                            select(func.count()).select_from(table).where(table.c.run_id == run_id)
                        ).scalar_one()
                    )
                )
        return counts[0], counts[1], counts[2]

    def purge(self, days: int, **kwargs: object) -> int:
        return self.store.purge_expired_runs(retention_days=days, now=NOW, **kwargs)


class StorePurgeTests(RetentionCase):
    def test_zero_days_means_keep_forever(self) -> None:
        """Decision 23: the default, and the deployed behaviour today."""

        self.seed("ancient", "completed", age_days=3650)
        self.assertEqual(self.purge(0), 0)
        self.assertIsNotNone(self.store.get_run("ancient"))
        self.assertEqual(self.children("ancient"), (2, 1, 0))

    def test_a_terminal_run_older_than_the_window_goes_with_its_children(self) -> None:
        self.seed("old", "completed", age_days=40, gate="answered")
        self.assertEqual(self.children("old"), (2, 1, 1))

        self.assertEqual(self.purge(30), 1)

        self.assertIsNone(self.store.get_run("old"))
        self.assertEqual(self.children("old"), (0, 0, 0))

    def test_every_terminal_status_is_purged(self) -> None:
        for status in ("completed", "failed", "cancelled"):
            with self.subTest(status=status):
                self.seed(f"old-{status}", status, age_days=40)
        self.assertEqual(self.purge(30), 3)
        for status in ("completed", "failed", "cancelled"):
            self.assertIsNone(self.store.get_run(f"old-{status}"))

    def test_a_terminal_run_inside_the_window_survives(self) -> None:
        self.seed("recent", "completed", age_days=10)
        self.assertEqual(self.purge(30), 0)
        self.assertIsNotNone(self.store.get_run("recent"))
        self.assertEqual(self.children("recent"), (2, 1, 0))

    def test_the_boundary_is_exclusive(self) -> None:
        """Finished exactly `retention_days` ago is not yet older than it."""

        self.seed("edge", "completed", age_days=30)
        self.assertEqual(self.purge(30), 0)
        self.assertEqual(self.purge(29), 1)

    def test_a_waiting_run_is_never_purged_at_any_age(self) -> None:
        """D7: never while a run is waiting on a gate it would delete."""

        self.seed("parked", "waiting", age_days=4000, gate="open")
        self.assertEqual(self.purge(1), 0)
        self.assertEqual(self.store.get_run("parked")["status"], "waiting")
        self.assertIsNotNone(self.store.get_pending_gate("parked"))
        self.assertEqual(self.children("parked"), (2, 1, 1))

    def test_live_statuses_are_left_to_the_orphan_sweep(self) -> None:
        for status in ("queued", "running", "cancelling"):
            with self.subTest(status=status):
                self.seed(f"live-{status}", status, age_days=400)
        self.assertEqual(self.purge(1), 0)
        for status in ("queued", "running", "cancelling"):
            self.assertIsNotNone(self.store.get_run(f"live-{status}"))

    def test_a_terminal_run_with_an_unanswered_gate_is_refused_until_it_is_closed(self) -> None:
        """The shape should not exist; the predicate refuses it anyway."""

        self.seed("half-closed", "completed", age_days=40, gate="open")
        self.assertEqual(self.purge(30), 0)
        self.assertIsNotNone(self.store.get_run("half-closed"))

        self.store.answer_gate("half-closed", GATE, outcome="closed-late")
        # answer_gate puts the run back to `running`; a real close would then
        # write the terminal status again, as `_close_interrupted_gate` does.
        self.store.update_run_status(
            "half-closed", "completed", completed_at=NOW - timedelta(days=40)
        )
        self.assertEqual(self.purge(30), 1)
        self.assertIsNone(self.store.get_run("half-closed"))

    def test_age_falls_back_to_updated_at_when_completed_at_is_null(self) -> None:
        self.seed("no-stamp", "failed", age_days=40, completed_at=False)
        self.assertIsNone(self.store.get_run("no-stamp")["completed_at"])
        self.assertEqual(self.purge(30), 1)
        self.assertIsNone(self.store.get_run("no-stamp"))

    def test_limit_bounds_one_call_oldest_first(self) -> None:
        self.seed("a", "completed", age_days=50)
        self.seed("b", "completed", age_days=45)
        self.seed("c", "completed", age_days=40)
        self.assertEqual(self.purge(30, limit=2), 2)
        self.assertIsNone(self.store.get_run("a"))
        self.assertIsNone(self.store.get_run("b"))
        self.assertIsNotNone(self.store.get_run("c"))
        self.assertEqual(self.purge(30, limit=2), 1)

    def test_other_runs_are_untouched(self) -> None:
        self.seed("old", "completed", age_days=40, gate="answered")
        self.seed("young", "completed", age_days=1, gate="answered")
        self.assertEqual(self.purge(30), 1)
        self.assertEqual(self.children("young"), (2, 1, 1))
        self.assertEqual(self.children("old"), (0, 0, 0))

    def test_on_purged_is_told_each_id_after_it_is_gone(self) -> None:
        self.seed("old-a", "completed", age_days=40)
        self.seed("old-b", "cancelled", age_days=40)
        seen: list[tuple[str, bool]] = []
        self.purge(30, on_purged=lambda run_id: seen.append((run_id, self.store.get_run(run_id) is None)))
        self.assertEqual(sorted(seen), [("old-a", True), ("old-b", True)])

    def test_the_count_is_logged(self) -> None:
        self.seed("old-a", "completed", age_days=40)
        self.seed("old-b", "failed", age_days=40)
        with self.assertLogs("brief_crew.service.persistence", level="INFO") as logs:
            self.purge(30)
        self.assertTrue(any("purged 2 terminal run(s)" in line for line in logs.output), logs.output)

    def test_nothing_to_purge_logs_nothing(self) -> None:
        self.seed("young", "completed", age_days=1)
        logger = logging.getLogger("brief_crew.service.persistence")
        with patch.object(logger, "info") as info:
            self.assertEqual(self.purge(30), 0)
        info.assert_not_called()

    def test_negative_days_and_a_non_positive_limit_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.purge(-1)
        with self.assertRaises(ValueError):
            self.purge(30, limit=0)

    def test_documents_are_never_touched(self) -> None:
        """D7: documents, versions, credentials, skills and tools are not runs."""

        from brief_crew.builder.store import BuilderDocumentStore

        BuilderDocumentStore(self.store).create(straight_line())
        self.seed("old", "completed", age_days=40)
        self.assertEqual(self.purge(30), 1)
        with self.store.connect() as connection:
            documents = connection.execute(
                select(func.count()).select_from(builder_documents)
            ).scalar_one()
        self.assertEqual(int(documents), 1)


class RegistryPurgeTests(RetentionCase):
    def registry(self, **options: object) -> RunRegistry:
        runner = SyntheticValidatorRunner()
        settings: dict[str, object] = {
            "gate_sweep_interval": 0.0,
            "recover_orphans": False,
        }
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

    def test_the_window_defaults_to_the_config_knob_which_defaults_to_forever(self) -> None:
        self.assertEqual(VALIDATOR_RUN_RETENTION_DAYS, 0)
        self.assertEqual(self.registry().run_retention_days, VALIDATOR_RUN_RETENTION_DAYS)

    def test_zero_days_never_even_asks_the_store(self) -> None:
        registry = self.registry(run_retention_days=0)
        # On the class: the store is a pydantic model and refuses an
        # instance attribute it has no field for.
        with patch.object(PostgresFlowPersistence, "purge_expired_runs") as purger:
            self.assertEqual(registry.purge_expired_runs(now=NOW), 0)
        purger.assert_not_called()

    def test_a_negative_window_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.registry(run_retention_days=-1)

    def test_the_registry_purges_through_the_store_and_forgets_its_own_copy(self) -> None:
        self.seed("old", "completed", age_days=40, gate="answered")
        registry = self.registry(run_retention_days=30)
        registry.require("old")  # cached in memory, as after a page load
        self.assertIn("old", registry._records)

        self.assertEqual(registry.purge_expired_runs(now=NOW), 1)

        self.assertIsNone(self.store.get_run("old"))
        self.assertNotIn("old", registry._records)
        self.assertEqual(registry.maintenance_status()["purged_runs"], 1)
        with self.assertRaises(KeyError):
            registry.require("old")

    def test_a_waiting_run_survives_the_registry_purge_too(self) -> None:
        registry = self.registry(run_retention_days=1)
        record = registry.create_run(
            session_id="retention",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A no-cost synthetic idea"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=5)
        self.assertEqual(record.status, RunStatus.WAITING)

        far_future = datetime.now(timezone.utc) + timedelta(days=4000)
        self.assertEqual(registry.purge_expired_runs(now=far_future), 0)
        self.assertEqual(record.status, RunStatus.WAITING)
        self.assertEqual(self.store.get_run(record.run_id)["status"], "waiting")

    def test_the_count_is_logged_at_the_registry_too(self) -> None:
        self.seed("old", "completed", age_days=40)
        registry = self.registry(run_retention_days=30)
        with self.assertLogs("brief_crew.service.registry", level="INFO") as logs:
            registry.purge_expired_runs(now=NOW)
        self.assertTrue(any("purged 1 terminal run(s)" in line for line in logs.output), logs.output)

    def test_the_purge_runs_on_the_periodic_tick(self) -> None:
        """Wired into the same sweep the orphan recovery uses, not a new thread."""

        self.seed("old", "completed", age_days=40)
        registry = self.registry(run_retention_days=30, gate_sweep_interval=0.05)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and self.store.get_run("old") is not None:
            time.sleep(0.02)
        self.assertIsNone(self.store.get_run("old"))
        self.assertGreaterEqual(registry.maintenance_status()["purged_runs"], 1)

    def test_a_tick_with_the_default_window_deletes_nothing(self) -> None:
        self.seed("old", "completed", age_days=4000)
        registry = self.registry(gate_sweep_interval=0.02)
        time.sleep(0.15)
        self.assertIsNotNone(self.store.get_run("old"))
        self.assertEqual(registry.maintenance_status()["purged_runs"], 0)
