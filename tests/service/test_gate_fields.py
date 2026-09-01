"""Per-field gate editability - what an operator's edit can actually reach.

The defect this guards: the verdict gate offered every field of a ``Verdict``
as a text input, including ``composite_score``, ``confidence``, ``fatal_floors``
and ``verdict`` itself. Those four are recomputed by
``Verdict.compute_mechanical_result`` on every validation and whatever was sent
is discarded, so the operator could set VALIDATE, submit, and watch REJECT come
back. In a human-in-the-loop system that is the worst possible lie: the gate
exists precisely so the operator's judgement is real.

Everything here is no-cost. The registry runs ``SyntheticValidatorRunner`` - two
deterministic pause/resume rounds, in-memory SQLite, no model and no network -
and the payload-shape tests call ``_gate_prompt`` directly with a real
``Verdict`` built from literals.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import unittest

from crewai.flow.async_feedback import PendingFeedbackContext

from brief_crew.schemas import ScopedIdea, Verdict
from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY
from brief_crew.service.models import GatePrompt, RunStatus
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import (
    GATE_NOTE_FIELD,
    GateFieldError,
    RunRegistry,
    WorkflowRuntime,
    _normalize_gate_prompt,
)
from brief_crew.service.runner import SyntheticValidatorRunner


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

# The seven fields `Verdict` recomputes and overwrites. Offering any of them as
# an input is the defect; each must arrive as read-only detail instead.
RECOMPUTED_FIELDS = (
    "composite_score",
    "confidence",
    "confidence_band",
    "verdict",
    "decision_reason",
    "fatal_floors",
    "provisional",
)

# The inputs to that arithmetic. Honoured by the formula, which is exactly why
# they are not a text box either: `validator_guardrails` binds a dimension's
# anchor to the rubric ladder and its URLs to what a tool returned, and those
# checks run on the Synthesist's output, never on a gate reply.
SCORED_INPUT_FIELDS = (
    "demand",
    "market",
    "competitive_room",
    "feasibility",
    "headroom_over_free",
    "evidence_counts",
    "market_coverage",
    "sentiment_coverage",
    "feasibility_coverage",
    "branches_ok",
)


def scoped_idea() -> ScopedIdea:
    return ScopedIdea(
        startup_idea="A scheduling assistant for clinics.",
        category="Clinic scheduling software",
        target_user="Clinic operations managers",
        problem="Manual scheduling creates avoidable administrative work.",
        technology_claim="A constrained assistant can automate intake scheduling.",
        market_query="clinic scheduling software pricing",
        community_queries=["clinic scheduling manual workaround"],
        tech_queries=["clinic scheduling assistant"],
        assumptions=["Clinics own it", "Scheduling repeats", "Data exports"],
        scoping_gaps=["Willingness to pay is unknown."],
        as_of="2026-08-29",
    )


def verdict() -> Verdict:
    def dimension(score: int, anchor: str) -> dict[str, object]:
        return {
            "score": score,
            "anchor_matched": anchor,
            "evidence_urls": [
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/c",
            ],
        }

    return Verdict.model_validate(
        {
            "demand": dimension(2, "Scattered complaints, no paid workaround"),
            "market": dimension(3, "Named segment with observable pricing"),
            "competitive_room": dimension(2, "Funded incumbents, no clear wedge"),
            "feasibility": dimension(4, "Open-source prior art covers the path"),
            "headroom_over_free": dimension(2, "Free tiers cover the common case"),
            "evidence_counts": {"market": 12, "sentiment": 7, "feasibility": 18},
            "market_coverage": 0.83,
            "sentiment_coverage": 0.41,
            "feasibility_coverage": 0.9,
            "median_market_source_age_months": 7.5,
            "branches_ok": 3,
            "cheapest_next_test": "Offer a paid pilot to three paying teams.",
            "kill_criteria": ["No team pays before seeing their own system"],
        }
    )


def context(method_name: str, output: object) -> PendingFeedbackContext:
    return PendingFeedbackContext(
        flow_id="flow-under-test",
        flow_class="tests.service.test_gate_fields",
        method_name=method_name,
        method_output=output,
        message="Review it.",
        emit=None,
        metadata={},
        requested_at=datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
    )


def prompt_for(method_name: str, output: object) -> dict[str, object]:
    return RunRegistry._gate_prompt("run-under-test", context(method_name, output))


class GatePromptSplitTests(unittest.TestCase):
    """Acceptance 1 and 3: derived values are shown, never offered as inputs."""

    def test_no_field_the_verdict_recomputes_is_offered_as_editable(self) -> None:
        scored = verdict()
        prompt = prompt_for("review_verdict", scored.model_dump_json())
        fields = prompt["fields"]
        derived = {item["key"]: item for item in prompt["derived"]}

        # Acceptance 1: not editable, on the payload both transports serve.
        for name in RECOMPUTED_FIELDS + SCORED_INPUT_FIELDS:
            self.assertNotIn(name, fields, f"{name} must not be an input")
            self.assertIn(name, derived, f"{name} must still be readable")

        # The whole verdict is read-only; the operator's lever is the note.
        self.assertEqual(set(fields), {GATE_NOTE_FIELD})
        self.assertEqual(fields[GATE_NOTE_FIELD], "")

    def test_every_derived_value_is_present_and_is_the_recomputed_one(self) -> None:
        scored = verdict()
        prompt = prompt_for("review_verdict", scored.model_dump_json())
        derived = {item["key"]: item["value"] for item in prompt["derived"]}

        # Acceptance 3: nothing is dropped on the way to read-only.
        self.assertEqual(set(derived), set(scored.model_dump(mode="json")))
        # And what is shown is what the schema computed, not what a model sent.
        self.assertEqual(derived["verdict"], scored.verdict)
        self.assertEqual(derived["composite_score"], json.dumps(scored.composite_score))
        self.assertEqual(derived["confidence"], json.dumps(scored.confidence))
        self.assertEqual(derived["confidence_band"], scored.confidence_band)
        self.assertEqual(
            json.loads(derived["fatal_floors"]),
            list(scored.fatal_floors),
        )
        # A dimension arrives whole and readable, not as a one-line dump.
        self.assertEqual(json.loads(derived["demand"])["score"], scored.demand.score)
        self.assertIn("\n", derived["demand"])

    def test_the_scope_gate_stays_fully_editable(self) -> None:
        scope = scoped_idea()
        prompt = prompt_for("confirm_scope", scope.model_dump_json())

        self.assertEqual(prompt["derived"], [])
        self.assertEqual(
            set(prompt["fields"]),
            set(scope.model_dump(mode="json")) | {GATE_NOTE_FIELD},
        )
        self.assertTrue(prompt["editable"])
        # Lists round-trip as JSON so an edit re-parses into the same shape.
        self.assertEqual(
            json.loads(prompt["fields"]["community_queries"]),
            list(scope.community_queries),
        )

    def test_the_prompt_still_validates_against_the_boundary_model(self) -> None:
        prompt = prompt_for("review_verdict", verdict().model_dump_json())
        validated = GatePrompt.model_validate(prompt)

        self.assertEqual(validated.fields, {GATE_NOTE_FIELD: ""})
        self.assertEqual(len(validated.derived), len(prompt["derived"]))
        self.assertIn("json", {item.kind for item in validated.derived})


class GateFeedbackTests(unittest.TestCase):
    """Acceptance 2 and 4 at the point the reply becomes Flow input."""

    def test_an_edited_scope_field_and_a_note_both_reach_the_flow(self) -> None:
        scope = scoped_idea()
        reply = RunRegistry._feedback(
            context("confirm_scope", scope.model_dump_json()),
            "revise",
            {"category": "Solo-practitioner scheduling", GATE_NOTE_FIELD: "Narrow it."},
        )
        payload = json.loads(reply)

        self.assertEqual(payload["decision"], "revise")
        # route_scope reads `feedback` and hands it to revise_scope.
        self.assertEqual(payload["feedback"], "Narrow it.")
        # ...and applies `scope` verbatim, so the edit is honoured.
        self.assertEqual(payload["scope"]["category"], "Solo-practitioner scheduling")
        self.assertEqual(payload["scope"]["target_user"], scope.target_user)
        self.assertNotIn(GATE_NOTE_FIELD, payload["scope"])

    def test_a_derived_edit_is_never_folded_into_the_verdict(self) -> None:
        scored = verdict()
        reply = RunRegistry._feedback(
            context("review_verdict", scored.model_dump_json()),
            "approve",
            {"composite_score": "9.9", "verdict": "VALIDATE"},
        )
        payload = json.loads(reply)

        # Acceptance 4, second half: even if a refusal were bypassed, nothing
        # derived reaches route_verdict, so no run can be steered by one.
        self.assertEqual(payload, {"decision": "approve"})

    def test_the_note_alone_produces_no_edited_object(self) -> None:
        reply = RunRegistry._feedback(
            context("review_verdict", verdict().model_dump_json()),
            "revise",
            {GATE_NOTE_FIELD: "  Rescore demand against the paying segment.  "},
        )

        self.assertEqual(
            json.loads(reply),
            {
                "decision": "revise",
                "feedback": "Rescore demand against the paying segment.",
            },
        )

    def test_only_revise_is_a_revision(self) -> None:
        """The `scope_revise`/`verdict_revise` aliases were unreachable.

        They are ``ValidatorFlow`` *router event* names, not gate option ids:
        ``_gate_prompt`` has only ever offered ``approve`` and ``revise``, and
        ``answer_gate`` refuses an outcome that is not one of the prompt's own
        option ids, so an alias could never arrive. This pins the contract that
        made them dead: the prompt's options, and nothing else, decide.
        """
        prompt = prompt_for("confirm_scope", scoped_idea().model_dump_json())
        self.assertEqual(
            {option["id"] for option in prompt["options"]},
            {"approve", "revise"},
        )
        for outcome, expected in (
            ("revise", "revise"),
            ("approve", "approve"),
            ("scope_revise", "approve"),
            ("verdict_revise", "approve"),
        ):
            with self.subTest(outcome=outcome):
                payload = json.loads(
                    RunRegistry._feedback(
                        context("confirm_scope", scoped_idea().model_dump_json()),
                        outcome,
                        {},
                    )
                )
                self.assertEqual(payload["decision"], expected)


class LegacyGatePromptTests(unittest.TestCase):
    """A `run_gates.request` row written before the split still recovers."""

    def test_a_stored_verdict_prompt_is_re_split_on_recovery(self) -> None:
        stored = {
            "gate_id": "gate-1",
            "node_id": "review_verdict",
            "editable": True,
            "fields": {
                "composite_score": "5.2",
                "verdict": "NEEDS_WORK",
                "fatal_floors": "[]",
                "cheapest_next_test": "Interview five users.",
            },
        }
        upgraded = _normalize_gate_prompt(dict(stored))

        self.assertEqual(upgraded["fields"], {GATE_NOTE_FIELD: ""})
        self.assertEqual(
            {item["key"] for item in upgraded["derived"]},
            set(stored["fields"]),
        )
        self.assertEqual(
            {item["key"]: item["kind"] for item in upgraded["derived"]}["fatal_floors"],
            "json",
        )

    def test_a_stored_scope_prompt_keeps_its_fields(self) -> None:
        stored = {
            "gate_id": "gate-1",
            "node_id": "confirm_scope",
            "editable": True,
            "fields": {"category": "Clinic scheduling"},
        }
        upgraded = _normalize_gate_prompt(dict(stored))

        self.assertEqual(
            upgraded["fields"],
            {"category": "Clinic scheduling", GATE_NOTE_FIELD: ""},
        )
        self.assertEqual(upgraded["derived"], [])

    def test_a_prompt_that_already_carries_the_split_is_untouched(self) -> None:
        already = {
            "node_id": "review_verdict",
            "fields": {GATE_NOTE_FIELD: ""},
            "derived": [{"key": "verdict", "value": "REJECT", "kind": "text"}],
        }
        self.assertEqual(_normalize_gate_prompt(dict(already)), already)


class GateReplyRefusalTests(unittest.TestCase):
    """Acceptance 4: a reply that edits a derived field is refused, not dropped."""

    def _registry(self) -> RunRegistry:
        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
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
        self.addCleanup(store.close)
        self.addCleanup(registry.close)
        return registry

    def _at_verdict_gate(self, registry: RunRegistry):
        record = registry.create_run(
            session_id="gate-fields",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A synthetic idea"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=5)
        scope_gate = str(record.pending_gate["gate_id"])
        registry.answer_gate(record.run_id, scope_gate, outcome="approve", fields={})
        registry.wait(record.run_id, timeout=5)
        self.assertEqual(record.pending_gate["node_id"], "review_verdict")
        return record

    def test_editing_a_derived_field_is_refused_and_the_gate_stays_open(self) -> None:
        registry = self._registry()
        record = self._at_verdict_gate(registry)
        gate_id = str(record.pending_gate["gate_id"])

        with self.assertRaises(GateFieldError) as raised:
            registry.answer_gate(
                record.run_id,
                gate_id,
                outcome="approve",
                fields={"verdict": "VALIDATE"},
            )

        self.assertEqual(raised.exception.fields, ("verdict",))
        self.assertIn(GATE_NOTE_FIELD, str(raised.exception))
        # The refusal ran before the durable compare-and-set, so the gate is
        # still answerable - a refused reply must never lock the operator out.
        self.assertEqual(record.status, RunStatus.WAITING)
        self.assertNotIn(gate_id, record.answered_gates)
        registry.answer_gate(record.run_id, gate_id, outcome="approve", fields={})
        registry.wait(record.run_id, timeout=5)
        self.assertEqual(record.status, RunStatus.COMPLETED)

    def test_an_unchanged_echo_of_a_derived_value_is_accepted(self) -> None:
        registry = self._registry()
        record = self._at_verdict_gate(registry)
        gate_id = str(record.pending_gate["gate_id"])
        issued = {
            str(item["key"]): str(item["value"])
            for item in record.pending_gate["derived"]
        }

        # A client that posts the whole payload back is not editing anything,
        # so it still answers its gate.
        registry.answer_gate(
            record.run_id,
            gate_id,
            outcome="approve",
            fields={"verdict": issued["verdict"]},
        )
        registry.wait(record.run_id, timeout=5)
        self.assertEqual(record.status, RunStatus.COMPLETED)

    def test_a_field_the_gate_never_offered_is_refused(self) -> None:
        registry = self._registry()
        record = self._at_verdict_gate(registry)

        with self.assertRaises(GateFieldError):
            registry.answer_gate(
                record.run_id,
                str(record.pending_gate["gate_id"]),
                outcome="approve",
                fields={"not_a_field": "x"},
            )

    def test_the_note_and_a_scope_edit_are_accepted(self) -> None:
        registry = self._registry()
        record = registry.create_run(
            session_id="gate-fields",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A synthetic idea"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=5)
        self.assertEqual(record.pending_gate["node_id"], "confirm_scope")

        registry.answer_gate(
            record.run_id,
            str(record.pending_gate["gate_id"]),
            outcome="revise",
            fields={"category": "Edited market", GATE_NOTE_FIELD: "Narrow it."},
        )
        registry.wait(record.run_id, timeout=5)

        # A revise now loops back to the SAME gate, which is what the shipped
        # topology's `route_scope -> revise_scope -> confirm_scope` edges have
        # always said happens. Until `SyntheticValidatorRunner` learned to read
        # `decision`, a revise fell through to the verdict gate exactly as an
        # approve did, and this assertion read the echoed reply off that wrong
        # gate's `derived` block.
        self.assertEqual(record.pending_gate["node_id"], "confirm_scope")

        # Same observation as before - the operator's edit and note on the far
        # side of the resume - taken where they now legitimately land. The
        # reopened gate carries the REVISED scope, so the edit appears in the
        # field it edited rather than inside an echoed blob, and this is `fields`
        # rather than `derived` because the scope gate is fully editable.
        fields = record.pending_gate["fields"]
        self.assertEqual(fields["category"], "Edited market")
        self.assertEqual(fields["revision_note"], "Narrow it.")
        # Untouched keys survive the round trip unchanged.
        self.assertEqual(fields["target_user"], "Synthetic operator")


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class GateFieldHttpTests(unittest.TestCase):
    """Acceptance 1 and 4 over HTTP - the WebSocket half lives in tests/integration."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.client = TestClient(create_app(synthetic=True))
        self.addCleanup(self.client.close)
        self.registry = self.client.app.state.run_registry

    def _verdict_gate(self) -> tuple[str, dict[str, object]]:
        run_id = self.client.post(
            "/api/sessions/gate-fields/runs",
            json={
                "workflow_id": "idea-validator",
                "inputs": {"idea": "A synthetic idea for the gate payload"},
            },
        ).json()["run_id"]
        self.registry.wait(run_id, timeout=5)
        scope_gate = self.client.get(f"/api/runs/{run_id}").json()["pending_gate"]
        self.assertEqual(scope_gate["node_id"], "confirm_scope")
        self.assertEqual(scope_gate["derived"], [])
        self.assertIn(GATE_NOTE_FIELD, scope_gate["fields"])
        self.client.post(
            f"/api/runs/{run_id}/gates/{scope_gate['gate_id']}",
            json={"outcome": "approve", "fields": {}},
        )
        self.registry.wait(run_id, timeout=5)
        gate = self.client.get(f"/api/runs/{run_id}").json()["pending_gate"]
        self.assertEqual(gate["node_id"], "review_verdict")
        return run_id, gate

    def test_the_served_verdict_gate_offers_only_the_note(self) -> None:
        _, gate = self._verdict_gate()

        self.assertEqual(set(gate["fields"]), {GATE_NOTE_FIELD})
        self.assertTrue(gate["derived"])
        # Acceptance 3 over the wire: the values are all still there to read.
        self.assertIn("verdict", {item["key"] for item in gate["derived"]})
        self.assertEqual(
            {item["key"]: item["value"] for item in gate["derived"]}["verdict"],
            "NEEDS_WORK",
        )

    def test_a_derived_edit_is_422_and_the_run_still_finishes(self) -> None:
        run_id, gate = self._verdict_gate()

        refused = self.client.post(
            f"/api/runs/{run_id}/gates/{gate['gate_id']}",
            json={"outcome": "approve", "fields": {"verdict": "VALIDATE"}},
        )
        self.assertEqual(refused.status_code, 422)
        self.assertIn("cannot be set", refused.json()["detail"])

        # Still WAITING, still answerable: the refusal is about the field, not
        # about the gate.
        self.assertEqual(
            self.client.get(f"/api/runs/{run_id}").json()["status"],
            "waiting",
        )
        accepted = self.client.post(
            f"/api/runs/{run_id}/gates/{gate['gate_id']}",
            json={"outcome": "approve", "fields": {GATE_NOTE_FIELD: ""}},
        )
        self.assertEqual(accepted.status_code, 202)
        self.registry.wait(run_id, timeout=5)
        self.assertEqual(
            self.client.get(f"/api/runs/{run_id}").json()["status"],
            "completed",
        )


if __name__ == "__main__":
    unittest.main()
