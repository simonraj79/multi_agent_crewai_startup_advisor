from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from crewai.flow.async_feedback.types import PendingFeedbackContext
from crewai.flow.persistence import FlowPersistence
from pydantic import BaseModel
from sqlalchemy import inspect

from brief_crew.events import FrameData, FrameKind, FrameLevel, UIEventType
from brief_crew.service.persistence import (
    PersistenceValueError,
    PostgresFlowPersistence,
)


class ExampleState(BaseModel):
    id: str
    count: int
    nested: dict[str, str]


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")

    def tearDown(self) -> None:
        self.store.close()

    def test_schema_and_flow_state_roundtrip(self) -> None:
        self.assertIsInstance(self.store, FlowPersistence)
        self.assertEqual(
            {
                "flow_states",
                "pending_feedback",
                "run_frames",
                "run_gates",
                "run_node_metrics",
                "runs",
            },
            set(inspect(self.store.engine).get_table_names()),
        )

        self.store.save_state(
            "flow-a",
            "scope",
            ExampleState(id="flow-a", count=1, nested={"stage": "first"}),
        )
        self.store.save_state(
            "flow-a",
            "research",
            {"id": "flow-a", "count": 2, "api_key": "must-not-be-stored"},
        )

        self.assertEqual(
            self.store.load_state("flow-a"),
            {"id": "flow-a", "count": 2, "api_key": "[REDACTED]"},
        )
        with self.assertRaises(PersistenceValueError):
            self.store.save_state("flow-a", "bad", {"live": object()})

    def test_pending_feedback_roundtrip_and_clear(self) -> None:
        requested_at = datetime(2026, 8, 29, 12, 30, tzinfo=timezone.utc)
        context = PendingFeedbackContext(
            flow_id="flow-b",
            flow_class="tests.ReviewFlow",
            method_name="review_scope",
            method_output={"scope": "focused"},
            message="Approve the scope",
            emit=["approved", "revised"],
            default_outcome="revised",
            metadata={"request": "gate-1"},
            llm="openrouter/test-model",
            requested_at=requested_at,
            execution_uuid="execution-b",
        )

        self.store.save_pending_feedback(
            "flow-b", context, {"id": "flow-b", "scope": "focused"}
        )
        recovered = self.store.load_pending_feedback("flow-b")

        self.assertIsNotNone(recovered)
        state, loaded_context = recovered  # type: ignore[misc]
        self.assertEqual(state, {"id": "flow-b", "scope": "focused"})
        self.assertEqual(loaded_context.flow_id, "flow-b")
        self.assertEqual(loaded_context.method_name, "review_scope")
        self.assertEqual(loaded_context.requested_at, requested_at)
        self.assertEqual(self.store.load_state("flow-b"), state)

        self.store.clear_pending_feedback("flow-b")
        self.assertIsNone(self.store.load_pending_feedback("flow-b"))
        self.assertEqual(self.store.load_state("flow-b"), state)

    def test_frames_are_batched_ordered_idempotent_and_replayable(self) -> None:
        self._create_run("run-frames")
        frames = [
            self._frame("run-frames", 3, FrameKind.METRICS, "third"),
            self._frame("run-frames", 1, FrameKind.RUN_STATE, "first"),
            self._frame("run-frames", 2, FrameKind.NODE_STATE, "second"),
        ]

        self.assertEqual(self.store.append_frames("run-frames", frames), 3)
        self.assertEqual(self.store.append_frames("run-frames", frames), 0)
        self.assertEqual(
            [frame["seq"] for frame in self.store.replay_frames("run-frames")],
            [1, 2, 3],
        )
        self.assertEqual(
            [frame["seq"] for frame in self.store.replay_frames(
                "run-frames", after=1, limit=1
            )],
            [2],
        )
        self.assertEqual(
            [frame["seq"] for frame in self.store.replay_frames(
                "run-frames", kinds={FrameKind.METRICS}
            )],
            [3],
        )

        snapshot = self.store.get_run("run-frames")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["frames"]["count"], 3)  # type: ignore[index]
        self.assertEqual(snapshot["frames"]["captured"], 3)  # type: ignore[index]
        self.assertEqual(snapshot["frames"]["first_seq"], 1)  # type: ignore[index]
        self.assertEqual(snapshot["frames"]["last_seq"], 3)  # type: ignore[index]

    def test_run_status_roundtrip(self) -> None:
        created = self._create_run("run-status")
        self.assertEqual(created["status"], "queued")
        self.assertEqual(created["inputs"], {"idea": "durable storage"})

        running = self.store.update_run_status("run-status", "running")
        self.assertEqual(running["status"], "running")
        self.assertIsNotNone(running["started_at"])

        completed = self.store.update_run_status(
            "run-status",
            "completed",
            result={"verdict": "VALIDATE"},
            usage={"prompt_tokens": 12, "completion_tokens": 3},
            dropped_frames=2,
            frame_gaps=2,
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"], {"verdict": "VALIDATE"})
        self.assertEqual(completed["usage"]["prompt_tokens"], 12)
        self.assertEqual(completed["frames"]["dropped"], 2)
        self.assertEqual(completed["frames"]["gaps"], 2)
        self.assertIsNotNone(completed["completed_at"])

        self.store.save_node_metrics(
            "run-status",
            "market_research",
            model="openrouter/test-model",
            prompt_tokens=12,
            completion_tokens=3,
            total_tokens=15,
            call_count=1,
            elapsed_ms=250,
            cost_usd="0.001250",
        )
        metrics = self.store.get_node_metrics("run-status")
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["node_id"], "market_research")
        self.assertEqual(metrics[0]["total_tokens"], 15)

    def _create_run(self, run_id: str) -> dict[str, object]:
        return self.store.create_run(
            run_id=run_id,
            session_id="session-a",
            workflow_id="validator-flow",
            graph_version="graph-v1",
            inputs={"idea": "durable storage"},
        )

    @staticmethod
    def _frame(
        run_id: str, seq: int, kind: FrameKind, message: str
    ) -> FrameData:
        return FrameData(
            seq=seq,
            run_id=run_id,
            ts=datetime(2026, 8, 29, 12, 0, seq, tzinfo=timezone.utc),
            kind=kind,
            event_type=UIEventType.WORKFLOW_START,
            level=FrameLevel.INFO,
            node_id="workflow",
            message=message,
            details={"ordinal": seq},
        )


class GateRecoveryTests(unittest.TestCase):
    def test_gate_recovers_across_store_instances_and_duplicate_reply_conflicts(self) -> None:
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "persistence.db"
            database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"

            first_store = PostgresFlowPersistence(database_url)
            first_store.create_run(
                run_id="run-gate",
                session_id="session-gate",
                workflow_id="validator-flow",
                graph_version="graph-v1",
            )
            first_store.open_gate(
                "run-gate",
                "scope-review",
                node_id="scope_gate",
                request={"title": "Confirm scope", "options": ["approve", "revise"]},
            )
            first_store.close()

            recovered_store = PostgresFlowPersistence(database_url)
            try:
                recovered = recovered_store.get_pending_gate("run-gate")
                self.assertIsNotNone(recovered)
                self.assertEqual(recovered["gate_id"], "scope-review")  # type: ignore[index]
                self.assertEqual(recovered_store.get_run("run-gate")["status"], "waiting")  # type: ignore[index]

                accepted = recovered_store.answer_gate(
                    "run-gate", "scope-review", outcome="approve"
                )
                duplicate = recovered_store.answer_gate(
                    "run-gate", "scope-review", outcome="revise"
                )

                self.assertTrue(accepted.accepted)
                self.assertFalse(accepted.conflict)
                self.assertFalse(duplicate.accepted)
                self.assertTrue(duplicate.conflict)
                self.assertEqual(duplicate.gate["response"], {"outcome": "approve"})
                self.assertIsNone(recovered_store.get_pending_gate("run-gate"))
                self.assertEqual(recovered_store.get_run("run-gate")["status"], "running")  # type: ignore[index]
            finally:
                recovered_store.close()


if __name__ == "__main__":
    unittest.main()