"""`GET /api/runs/{run_id}` must carry the deterministic score.

The run snapshot's `result` is the flow's own return value - a
`ValidationReport`, which carries `markdown_body`, `provisional`,
`thin_dimensions` and `sources`. No composite, no confidence, no label. So a
REST consumer of a finished run could read the *prose* of a verdict and never
the verdict, in either gate mode, and under `gates: "auto"` there was no gate
prompt to fall back to either.

The obvious fix - a `verdict` field on `ValidationReport` - is the wrong one:
that model is `output_pydantic` on `reporting_task`, so the Reporter would have
to *emit* the arithmetic `Verdict.compute_mechanical_result` exists to take away
from it. The mirror below reads the run's own `verdict` frame instead, so the
snapshot and the stream cannot disagree and no model is asked for a number.
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from brief_crew.events import FrameKind
from brief_crew.service.app import create_app
from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY
from brief_crew.service.models import RunStatus, RunStatusResponse
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import RunRegistry, WorkflowRuntime
from brief_crew.service.runner import SyntheticValidatorRunner


VERDICT_KEYS = {
    "verdict",
    "composite_score",
    "confidence",
    "confidence_band",
    "provisional",
    "fatal_floors",
    "decision_reason",
    "dimensions",
}


def _poll(client: TestClient, run_id: str, done) -> dict:
    deadline = time.monotonic() + 10.0
    snapshot: dict = {}
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/runs/{run_id}").json()
        if done(snapshot):
            return snapshot
        time.sleep(0.05)
    return snapshot


class UnattendedSnapshotTests(unittest.TestCase):
    """The mode with no gate to read the score out of."""

    def test_an_auto_run_reports_its_verdict_on_the_run_endpoint(self) -> None:
        app = create_app(synthetic=True)
        client = TestClient(app)
        with patch("brief_crew.config.VALIDATOR_ALLOW_AUTO_GATES", True):
            created = client.post(
                "/api/sessions/s-verdict/runs",
                json={
                    "workflow_id": "idea-validator",
                    "inputs": {"idea": "a clinic scheduler"},
                    "gates": "auto",
                },
            )
        self.assertEqual(created.status_code, 202, created.text)
        run_id = created.json()["run_id"]

        snapshot = _poll(
            client,
            run_id,
            lambda s: s["status"] in {"completed", "failed", "error"},
        )
        self.assertEqual(snapshot["status"], "completed", snapshot)
        # Nobody was asked anything, and the score is still there.
        self.assertIsNone(snapshot["pending_gate"])
        self.assertEqual(set(snapshot["verdict"]), VERDICT_KEYS)
        self.assertEqual(
            set(snapshot["verdict"]["dimensions"]),
            {
                "demand",
                "market",
                "competitive_room",
                "feasibility",
                "headroom_over_free",
            },
        )
        # And it is JSON, not a frozen mapping that only looked like one in
        # process: the response came back over HTTP through `RunStatusResponse`,
        # which is `extra="forbid"` and would have rejected an undeclared field.
        self.assertIsInstance(snapshot["verdict"]["composite_score"], float)

    def test_a_run_that_has_not_scored_anything_reports_null(self) -> None:
        """Absent, not an empty object.

        A queued or mid-research run has no verdict, and saying so as `null` is
        what lets a client tell "not yet" from "scored zero" without inspecting
        the fields.
        """

        app = create_app(synthetic=True)
        client = TestClient(app)
        created = client.post(
            "/api/sessions/s-early/runs",
            json={
                "workflow_id": "idea-validator",
                "inputs": {"idea": "a clinic scheduler"},
            },
        )
        run_id = created.json()["run_id"]
        snapshot = _poll(client, run_id, lambda s: s["pending_gate"] is not None)

        # Parked at the scope gate, long before synthesis.
        self.assertEqual(snapshot["status"], "waiting")
        self.assertIsNone(snapshot["verdict"])


class SnapshotSourceTests(unittest.TestCase):
    """The mirror's source, and what survives a restart."""

    def _store(self) -> PostgresFlowPersistence:
        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(store.close)
        return store

    def _registry(self, store: PostgresFlowPersistence) -> RunRegistry:
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
            gate_sweep_interval=0.0,
        )
        self.addCleanup(registry.close)
        return registry

    def _completed_run(self, registry: RunRegistry) -> str:
        record = registry.create_run(
            session_id="verdict-snapshot",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "a clinic scheduler", "no_gates": True},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=10)
        self.assertEqual(record.status, RunStatus.COMPLETED)
        return record.run_id

    def test_the_snapshot_is_the_frame_verbatim(self) -> None:
        """One source of truth, so the stream and the snapshot cannot diverge.

        The client watching the socket and the client polling the endpoint have
        to be looking at the same verdict. Deriving the snapshot a second way -
        from the flow state, or from the gate prompt - is how those two come to
        disagree after a revise.
        """

        registry = self._registry(self._store())
        run_id = self._completed_run(registry)
        record = registry.require(run_id)
        frames = [
            frame
            for frame in record.buffer.replay(after=0, limit=500)
            if frame.kind is FrameKind.VERDICT
        ]

        self.assertEqual(len(frames), 1)
        self.assertEqual(
            registry.status_payload(run_id)["verdict"],
            frames[0].to_dict()["details"],
        )

    def test_the_verdict_survives_a_restart(self) -> None:
        """A second registry over the same store IS a restart.

        The `runs` row has no column for a verdict and does not need one: the
        frame is durable, so recovery rebuilds the mirror by replaying it. That
        is why the frame was made the source - a run's score needs no migration
        to outlive the process that computed it.
        """

        store = self._store()
        original = self._registry(store)
        run_id = self._completed_run(original)
        expected = original.status_payload(run_id)["verdict"]
        self.assertIsNotNone(expected)

        restarted = self._registry(store)
        recovered = restarted.status_payload(run_id)["verdict"]

        self.assertEqual(recovered, expected)
        self.assertEqual(set(recovered), VERDICT_KEYS)
        # And it still validates through the boundary model the endpoint uses.
        response = RunStatusResponse.model_validate(restarted.status_payload(run_id))
        self.assertEqual(response.verdict, expected)


if __name__ == "__main__":
    unittest.main()


class SyntheticDoubleConsistencyTests(unittest.TestCase):
    """The synthetic report and the synthetic verdict must agree.

    They did not, once: the console's new scorecard read a composite of 6.0 from
    the verdict frame while the report body rendered directly beneath it read
    5.6, because the markdown was a hardcoded string and the Verdict was built
    through the schema. Nothing failed - both halves were internally valid - and
    the only way to notice was to look at the screen.

    That is the same shape as the two defects this module's siblings were written
    for: a double that diverges from its subject in a dimension nobody asserts
    on. Here the double diverges from *itself*, which is worse, because it
    teaches a reader that one of the two numbers is lying without saying which.
    """

    def test_the_report_body_renders_the_verdicts_own_numbers(self) -> None:
        from brief_crew.service.runner import _synthetic_report_markdown, _synthetic_verdict

        verdict = _synthetic_verdict()
        body = _synthetic_report_markdown("a clinic scheduler")

        self.assertIn(f"Composite **{verdict.composite_score:.1f}**", body)
        self.assertIn(f"`{verdict.confidence_band}` confidence", body)
        self.assertIn(f"# Validation report - {verdict.verdict}", body)
        for label, score in (
            ("Demand", verdict.demand.score),
            ("Market", verdict.market.score),
            ("Competitive room", verdict.competitive_room.score),
            ("Feasibility", verdict.feasibility.score),
            ("Headroom over free", verdict.headroom_over_free.score),
        ):
            with self.subTest(dimension=label):
                self.assertIn(f"| {label} | {score} |", body)
