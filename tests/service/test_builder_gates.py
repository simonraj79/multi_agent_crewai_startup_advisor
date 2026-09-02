"""A gate somebody DREW, answered through the service that was built for two.

Every gate in this repository until now was one of exactly two, compiled into
`ValidatorFlow` by hand, and `service/registry.py` knew both of them by name.
A builder graph breaks all six of those assumptions at once, and each break is
silent - the run pauses, the API answers 200, and something the operator needs
is wrong:

* the pause happens in the compiler's identifier (`n2_confirm`) while the
  canvas, and therefore every node-state key the client holds, calls it
  `confirm` - so the node an operator is being asked about never turns
  `waiting`;
* every gate is titled "Review verdict" over a summary read from
  `cheapest_next_test`, a key no authored payload has;
* `GateConfig.editable_fields` is ignored and the entire payload offered as a
  text box, with a refusal message about dimension scores this graph does not
  have;
* the operator's edits are filed under a `verdict` slot that no builder router
  reads - and, because `GatePrompt.verdict` is `str | None`, a mapping there
  makes `GET /api/runs/{id}` answer 500 for the rest of the run's life;
* the revise budget is reported as VALIDATOR_MAX_GATE_TURNS while `route_gate`
  honours the gate's own `max_turns`, so the extra Revise buttons are silent
  downgrades to approve;
* `GateConfig.expiry_seconds` is authored, range-validated and read by nothing.

Nothing here costs anything. The one agent node is built by an injected
factory, a gate never calls a model by construction (`llm` is explicitly
null), and the database is in-memory SQLite. The flow engine, the compiler,
the routers, the durable pause and the whole of `RunRegistry` are real: this
file drives `create_run` -> pause -> `answer_gate` -> resume the same way the
HTTP layer does, because the defects above are all in what the registry
publishes and none of them is visible to a test that calls the compiler alone.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any
import unittest

from crewai.flow.async_feedback import PendingFeedbackContext

from brief_crew.builder.descriptor import build_builder_workflow
from brief_crew.config import (
    GATE_EDITABLE_FIELDS_METADATA_KEY,
    GATE_EXPIRY_METADATA_KEY,
    GATE_LABEL_METADATA_KEY,
    GATE_MAX_TURNS_METADATA_KEY,
    VALIDATOR_GATE_TIMEOUT_SECONDS,
    VALIDATOR_MAX_GATE_TURNS,
)
from brief_crew.events import FrameKind
from brief_crew.service.builder_runner import BuilderFlowRunner
from brief_crew.service.models import GatePrompt, RunStatus
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import (
    GATE_NOTE_FIELD,
    GateFieldError,
    RunRegistry,
    WorkflowRuntime,
)
from tests.builder.test_compiler import (
    StubFactories,
    input_node,
    output_node,
    router_node,
    scoper_node,
    transform_node,
)
from tests.builder.test_document import document, edge, node

JOIN_TIMEOUT = 20.0
# What the one stubbed agent above the gate "produces". Two keys, because the
# whole editable/derived split is about telling them apart.
SCOPER_OUTPUT = json.dumps({"segment": "clinics", "notes": ""})
GATE_LABEL = "Approve the shortlist"
GATE_MESSAGE = "Confirm the scope."
# Deliberately not a round fraction of the global 1800s window, so an assertion
# on it cannot pass by coincidence.
GATE_EXPIRY_SECONDS = 137


def gate_node(
    *,
    label: str = GATE_LABEL,
    max_turns: int = 1,
    editable_fields: tuple[str, ...] = ("notes",),
    expiry_seconds: int = GATE_EXPIRY_SECONDS,
) -> dict[str, Any]:
    """One gate whose label, budget, editable keys and window all DIFFER.

    Every one of these four values is chosen to be distinguishable from what
    the service used to assume: the label is not "Review verdict", the budget
    is not VALIDATOR_MAX_GATE_TURNS, `segment` is deliberately left out of
    `editable_fields`, and the window is not VALIDATOR_GATE_TIMEOUT_SECONDS.
    An assertion that passes here cannot be passing on the old behaviour.
    """

    drawn = node(
        "confirm",
        "gate",
        {
            "message": GATE_MESSAGE,
            "max_turns": max_turns,
            "editable_fields": list(editable_fields),
            "expiry_seconds": expiry_seconds,
        },
    )
    drawn["label"] = label
    return drawn


def gated_document(**gate_options: Any) -> Any:
    """input -> scoper -> gate; revise loops back through a router.

    The same shape as `tests.builder.test_compiler.gated_loop`, with a gate
    this module can parameterise. The loop is what makes a SECOND turn
    reachable, which is where the revise budget and the 500 both live.
    """

    return document(
        [
            input_node(),
            scoper_node(),
            gate_node(**gate_options),
            transform_node(
                "restate",
                op="default",
                args={"value": "${state.out__confirm}", "default": "no note"},
            ),
            router_node(key="turns__confirm", value=1),
            output_node("report", source="${state.out__confirm}"),
        ],
        [
            edge("e1", "idea", "scoper"),
            edge("e2", "scoper", "confirm"),
            edge("e3", "confirm", "report", source_port="approve"),
            edge("e4", "confirm", "restate", source_port="revise"),
            edge("e5", "restate", "again"),
            edge("e6", "again", "confirm", source_port="retry"),
            edge("e7", "again", "report", source_port="onward"),
        ],
    )


def validator_context(
    method_name: str,
    output: Any,
    *,
    metadata: dict[str, Any] | None = None,
) -> PendingFeedbackContext:
    """A pause context shaped like the one `ValidatorFlow` produces.

    `metadata` defaults to EMPTY, which is the whole discriminator: the
    validator's `@human_feedback` decorators declare no `metadata=` at all, so
    a context with none is one of the two shipped gates.
    """

    return PendingFeedbackContext(
        flow_id="flow-under-test",
        flow_class="tests.service.test_builder_gates",
        method_name=method_name,
        method_output=output,
        message="Review it.",
        emit=None,
        metadata=metadata or {},
        requested_at=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
    )


class BuilderGateTestCase(unittest.TestCase):
    """One compiled graph, one registry, driven to its gate and answered."""

    def _registry(self, **gate_options: Any) -> tuple[RunRegistry, Any]:
        workflow = build_builder_workflow(gated_document(**gate_options))
        factories = StubFactories(outputs={"scoper": SCOPER_OUTPUT})
        # The PRODUCTION runner, not a local copy of it. This module shipped
        # with its own `CompiledFlowRunner` because `BuilderFlowRunner` did not
        # exist yet; it does now, it takes `crew_factories` as an injected
        # field, and a double that outlives its subject is how a green suite
        # certifies nothing - closed items 20 and 33 are both that story. The
        # gate contract below is worth pinning precisely because it is pinned
        # against the object `create_app` actually installs.
        runner = BuilderFlowRunner(workflow, crew_factories=factories)
        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        registry = RunRegistry(
            graph_version=workflow.descriptor.version,
            node_registry=workflow.node_registry,
            runner=runner,
            workflows={
                workflow.workflow_id: WorkflowRuntime(
                    graph_version=workflow.descriptor.version,
                    node_registry=workflow.node_registry,
                    runner=runner,
                    input_field=workflow.document.input_field,
                )
            },
            persistence=store,
            gate_sweep_interval=0.0,
        )
        self.addCleanup(store.close)
        self.addCleanup(registry.close)
        return registry, workflow

    def _at_gate(self, **gate_options: Any) -> tuple[RunRegistry, Any, dict[str, Any]]:
        registry, workflow = self._registry(**gate_options)
        record = registry.create_run(
            session_id="builder-gates",
            workflow_id=workflow.workflow_id,
            inputs={"idea": "A scheduling assistant for clinics"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=JOIN_TIMEOUT)
        self.assertEqual(record.status, RunStatus.WAITING)
        prompt = record.pending_gate
        assert prompt is not None
        return registry, record, dict(prompt)

    def _reply(
        self,
        registry: RunRegistry,
        record: Any,
        prompt: dict[str, Any],
        *,
        outcome: str,
        fields: dict[str, str] | None = None,
    ) -> None:
        registry.answer_gate(
            record.run_id,
            str(prompt["gate_id"]),
            outcome=outcome,
            fields=fields or {},
        )
        registry.wait(record.run_id, timeout=JOIN_TIMEOUT)

    def _frames(self, registry: RunRegistry, record: Any, kind: str) -> list[Any]:
        return [
            frame
            for frame in registry.all_frames(record.run_id)
            if frame.get("kind") == kind
        ]


class BuilderGateNodeIdTests(BuilderGateTestCase):
    """The compiled ident never reaches a client. Defect 1 of six."""

    def test_the_prompt_names_the_node_the_canvas_drew(self) -> None:
        _, _, prompt = self._at_gate()
        self.assertEqual(prompt["node_id"], "confirm")

    def test_the_compiled_identifier_is_what_the_flow_actually_paused_in(self) -> None:
        # Without this the test above proves nothing: the two names have to
        # really differ for resolving between them to mean anything.
        _, record, _ = self._at_gate()
        context = record.pending_context
        assert context is not None
        self.assertEqual(context.method_name, "n2_confirm")
        self.assertEqual(
            record.node_registry.declared_node(context.method_name), "confirm"
        )

    def test_the_gate_open_frame_names_the_canvas_node(self) -> None:
        # This is the one that decides whether the node turns `waiting`:
        # `applyGate` does `setNodeState(frame.node_id, 'waiting')`, and a key
        # no drawn node has sets nothing at all, silently.
        registry, record, _ = self._at_gate()
        opened = self._frames(registry, record, FrameKind.GATE_OPEN.value)
        self.assertTrue(opened)
        self.assertEqual({frame["node_id"] for frame in opened}, {"confirm"})

    def test_the_gate_closed_frame_names_the_canvas_node(self) -> None:
        registry, record, prompt = self._at_gate()
        self._reply(registry, record, prompt, outcome="approve")
        closed = self._frames(registry, record, FrameKind.GATE_CLOSED.value)
        self.assertTrue(closed)
        self.assertEqual({frame["node_id"] for frame in closed}, {"confirm"})

    def test_the_durable_gate_row_names_the_canvas_node(self) -> None:
        # The row is what the expiry sweeper and every restart read, so a row
        # holding the ident would put the ident back into a frame hours later.
        registry, record, prompt = self._at_gate()
        stored = registry.persistence.get_gate(record.run_id, str(prompt["gate_id"]))
        assert stored is not None
        self.assertEqual(stored["node_id"], "confirm")


class BuilderGateDescriptionTests(BuilderGateTestCase):
    """It is the author's gate, so it is the author's words. Defect 2."""

    def test_the_title_is_the_authors_label(self) -> None:
        _, _, prompt = self._at_gate()
        self.assertEqual(prompt["title"], GATE_LABEL)
        self.assertNotEqual(prompt["title"], "Review verdict")

    def test_the_summary_is_the_authors_own_message(self) -> None:
        _, _, prompt = self._at_gate()
        self.assertIn(GATE_MESSAGE, prompt["summary"])

    def test_the_prompt_still_validates_as_a_gate_prompt(self) -> None:
        _, _, prompt = self._at_gate()
        validated = GatePrompt.model_validate(prompt)
        self.assertEqual(validated.node_id, "confirm")
        self.assertEqual(validated.title, GATE_LABEL)


class BuilderGateEditableFieldsTests(BuilderGateTestCase):
    """`editable_fields` decides the form, not the client's imagination. 3."""

    def test_only_the_declared_field_and_the_note_are_offered(self) -> None:
        _, _, prompt = self._at_gate()
        self.assertEqual(set(prompt["fields"]), {"notes", GATE_NOTE_FIELD})

    def test_an_undeclared_key_is_shown_read_only_rather_than_dropped(self) -> None:
        _, _, prompt = self._at_gate()
        derived = {item["key"]: item["value"] for item in prompt["derived"]}
        self.assertEqual(derived, {"segment": "clinics"})

    def test_the_declared_field_is_accepted(self) -> None:
        registry, record, prompt = self._at_gate()
        self._reply(
            registry,
            record,
            prompt,
            outcome="approve",
            fields={"notes": "prefer single-site clinics"},
        )
        self.assertEqual(record.status, RunStatus.COMPLETED)

    def test_an_undeclared_field_is_refused_before_the_gate_is_answered(self) -> None:
        registry, record, prompt = self._at_gate()
        with self.assertRaises(GateFieldError) as raised:
            registry.answer_gate(
                record.run_id,
                str(prompt["gate_id"]),
                outcome="approve",
                fields={"segment": "hospitals"},
            )
        self.assertEqual(raised.exception.fields, ("segment",))
        # Still answerable: the refusal happens before the durable
        # compare-and-set, so a rejected edit must not lock the operator out.
        self._reply(registry, record, prompt, outcome="approve")
        self.assertEqual(record.status, RunStatus.COMPLETED)

    def test_the_refusal_explains_THIS_gate_rather_than_a_verdict(self) -> None:
        registry, record, prompt = self._at_gate()
        with self.assertRaises(GateFieldError) as raised:
            registry.answer_gate(
                record.run_id,
                str(prompt["gate_id"]),
                outcome="approve",
                fields={"segment": "hospitals"},
            )
        message = str(raised.exception)
        self.assertNotIn("dimension scores", message)
        self.assertIn("author declared", message)

    def test_a_gate_declaring_nothing_editable_still_takes_a_note(self) -> None:
        # Otherwise the operator has no lever but Approve: the note is how a
        # revise says what to reconsider, and it is not part of the payload.
        _, _, prompt = self._at_gate(editable_fields=())
        self.assertEqual(set(prompt["fields"]), {GATE_NOTE_FIELD})


class BuilderGateFeedbackSlotTests(BuilderGateTestCase):
    """Where an operator's edits land in the reply the router parses. 4."""

    def test_edits_are_filed_under_fields_not_verdict(self) -> None:
        context = validator_context(
            "n2_confirm",
            SCOPER_OUTPUT,
            metadata={
                GATE_LABEL_METADATA_KEY: GATE_LABEL,
                GATE_EDITABLE_FIELDS_METADATA_KEY: ["notes"],
                GATE_MAX_TURNS_METADATA_KEY: 1,
                GATE_EXPIRY_METADATA_KEY: GATE_EXPIRY_SECONDS,
            },
        )
        payload = json.loads(
            RunRegistry._feedback(
                context,
                "revise",
                {"notes": "narrower", GATE_NOTE_FIELD: "one site only"},
            )
        )
        self.assertNotIn("verdict", payload)
        self.assertNotIn("scope", payload)
        self.assertEqual(payload["decision"], "revise")
        self.assertEqual(payload["feedback"], "one site only")
        # The whole payload with the edit laid over it, so the node downstream
        # of the revise branch can read the corrected values rather than a diff.
        self.assertEqual(payload["fields"], {"segment": "clinics", "notes": "narrower"})

    def test_an_edit_reaches_the_gate_nodes_own_output(self) -> None:
        # `route_gate` records every non-`decision` key as `out__confirm`, which
        # is what `${state.out__confirm}` resolves to downstream. That is the
        # whole reason the slot name matters.
        registry, record, prompt = self._at_gate()
        self._reply(
            registry,
            record,
            prompt,
            outcome="revise",
            fields={"notes": "narrower", GATE_NOTE_FIELD: "one site only"},
        )
        reopened = record.pending_gate
        assert reopened is not None
        shown = json.loads(str(record.pending_context.method_output))
        self.assertEqual(shown["fields"]["notes"], "narrower")


class BuilderGateReviseBudgetTests(BuilderGateTestCase):
    """The gate's own `max_turns`, which `route_gate` has always honoured. 5."""

    def test_the_budget_reported_is_the_gates_own(self) -> None:
        _, _, prompt = self._at_gate(max_turns=1)
        self.assertEqual(prompt["max_revise_turns"], 1)
        self.assertEqual(prompt["revise_turns_remaining"], 1)
        self.assertNotEqual(prompt["max_revise_turns"], VALIDATOR_MAX_GATE_TURNS)

    def test_a_spent_turn_closes_the_budget_on_the_reopened_gate(self) -> None:
        registry, record, prompt = self._at_gate(max_turns=1)
        self._reply(registry, record, prompt, outcome="revise")
        reopened = record.pending_gate
        assert reopened is not None
        self.assertEqual(reopened["revise_turns_remaining"], 0)
        self.assertEqual(
            {option["id"] for option in reopened["options"]}, {"approve"}
        )

    def test_a_revise_past_the_budget_is_refused_by_naming_it(self) -> None:
        registry, record, prompt = self._at_gate(max_turns=1)
        self._reply(registry, record, prompt, outcome="revise")
        reopened = record.pending_gate
        assert reopened is not None
        with self.assertRaises(ValueError) as raised:
            registry.answer_gate(
                record.run_id,
                str(reopened["gate_id"]),
                outcome="revise",
            )
        self.assertIn("revise turns", str(raised.exception))

    def test_a_gate_declaring_no_revises_never_offers_the_button(self) -> None:
        _, _, prompt = self._at_gate(max_turns=0)
        self.assertEqual(prompt["max_revise_turns"], 0)
        self.assertEqual({option["id"] for option in prompt["options"]}, {"approve"})

    def test_the_run_reads_the_run_after_a_revise(self) -> None:
        # The 500 in full: a builder gate's edits used to be filed under
        # `verdict`, the reopened prompt read that key back, and
        # `GatePrompt.verdict` is `str | None` - so the second turn of any
        # revise loop made `GET /api/runs/{id}` fail validation for good.
        registry, record, prompt = self._at_gate(max_turns=1)
        self._reply(
            registry,
            record,
            prompt,
            outcome="revise",
            fields={"notes": "narrower"},
        )
        payload = registry.status_payload(record.run_id)
        self.assertIsNotNone(payload["pending_gate"])
        GatePrompt.model_validate(payload["pending_gate"])


class BuilderGateExpiryTests(BuilderGateTestCase):
    """`GateConfig.expiry_seconds` is honoured, which is why it survives. 6."""

    def test_the_gate_closes_on_the_window_its_author_declared(self) -> None:
        _, record, prompt = self._at_gate()
        context = record.pending_context
        assert context is not None
        expires_at = datetime.fromisoformat(str(prompt["expires_at"]))
        self.assertEqual(
            expires_at - context.requested_at,
            timedelta(seconds=GATE_EXPIRY_SECONDS),
        )

    def test_the_global_window_is_not_imposed_on_a_shorter_gate(self) -> None:
        _, record, prompt = self._at_gate()
        context = record.pending_context
        assert context is not None
        self.assertLess(
            datetime.fromisoformat(str(prompt["expires_at"])),
            context.requested_at + timedelta(seconds=VALIDATOR_GATE_TIMEOUT_SECONDS),
        )

    def test_the_expiry_sweep_reports_the_window_that_was_really_used(self) -> None:
        # A frame that went on reporting 1800 would tell an operator their gate
        # had half an hour when the document gave it two minutes.
        registry, record, prompt = self._at_gate()
        context = record.pending_context
        assert context is not None
        # Aware, because `_gate_deadline` normalises the prompt's naive
        # `expires_at` to UTC before comparing - the same mismatch the sweep's
        # own timeout arithmetic has to survive.
        opened = context.requested_at.replace(tzinfo=timezone.utc)
        counters = registry.sweep_gates(
            now=opened + timedelta(seconds=GATE_EXPIRY_SECONDS + 1)
        )
        self.assertEqual(counters["expired_now"], 1)
        expired = self._frames(registry, record, FrameKind.GATE_EXPIRED.value)
        self.assertTrue(expired)
        details = expired[0]["details"]
        self.assertEqual(details["timeout_seconds"], GATE_EXPIRY_SECONDS)
        self.assertEqual(expired[0]["node_id"], "confirm")


class AuthoredGateDegradationTests(unittest.TestCase):
    """Malformed metadata degrades; it never fails the run at the pause."""

    def _prompt(self, metadata: dict[str, Any]) -> dict[str, Any]:
        return RunRegistry._gate_prompt(
            "run-under-test", validator_context("n2_confirm", SCOPER_OUTPUT, metadata=metadata)
        )

    def test_a_string_where_a_field_list_belongs_offers_no_edits(self) -> None:
        # A string iterates into single characters, which is the one malformed
        # shape that produces a plausible-looking answer instead of an obvious
        # one. Falling back to "nothing is editable" is the safe direction: a
        # refused edit is recoverable, an accepted one that nothing honours is
        # what the whole fields/derived split exists to prevent.
        prompt = self._prompt(
            {
                GATE_EDITABLE_FIELDS_METADATA_KEY: "notes",
                GATE_MAX_TURNS_METADATA_KEY: 1,
            }
        )
        self.assertEqual(set(prompt["fields"]), {GATE_NOTE_FIELD})

    def test_a_gate_whose_metadata_predates_the_label_uses_its_node_id(self) -> None:
        # Reachable, and not through a document: `BuilderNode.label` has
        # `min_length=1`, so a compiled gate always carries one. What does not
        # is a `pending_feedback` row written by the version BEFORE the label
        # was put on the metadata - a run paused across a deploy, which is the
        # single most likely way this branch is ever taken. The node id is the
        # honest fallback, being the other thing the author typed.
        prompt = self._prompt(
            {
                GATE_EDITABLE_FIELDS_METADATA_KEY: ["notes"],
                GATE_MAX_TURNS_METADATA_KEY: 1,
            }
        )
        self.assertEqual(prompt["title"], "n2_confirm")
        self.assertNotEqual(prompt["title"], "Review verdict")

    def test_a_non_numeric_budget_reads_as_no_revises(self) -> None:
        prompt = self._prompt(
            {
                GATE_EDITABLE_FIELDS_METADATA_KEY: ["notes"],
                GATE_MAX_TURNS_METADATA_KEY: "two",
            }
        )
        self.assertEqual(prompt["max_revise_turns"], 0)
        self.assertEqual({option["id"] for option in prompt["options"]}, {"approve"})

    def test_a_missing_window_falls_back_to_the_services_own(self) -> None:
        prompt = self._prompt({GATE_EDITABLE_FIELDS_METADATA_KEY: ["notes"]})
        expires_at = datetime.fromisoformat(str(prompt["expires_at"]))
        self.assertEqual(
            expires_at - datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
            timedelta(seconds=VALIDATOR_GATE_TIMEOUT_SECONDS),
        )

    def test_a_window_longer_than_the_service_keeps_is_clamped(self) -> None:
        # The document schema already caps this field, so a value past the cap
        # can only arrive from a hand-edited pending row - and a gate that
        # claimed to outlive the sweep would be a promise nothing keeps.
        prompt = self._prompt(
            {
                GATE_EDITABLE_FIELDS_METADATA_KEY: ["notes"],
                GATE_EXPIRY_METADATA_KEY: VALIDATOR_GATE_TIMEOUT_SECONDS * 10,
            }
        )
        expires_at = datetime.fromisoformat(str(prompt["expires_at"]))
        self.assertEqual(
            expires_at - datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
            timedelta(seconds=VALIDATOR_GATE_TIMEOUT_SECONDS),
        )

    def test_a_headline_verdict_that_is_not_a_string_is_dropped(self) -> None:
        # `GatePrompt.verdict` is `str | None` and forbids extras, so an
        # authored payload carrying an OBJECT under `verdict` - exactly what a
        # gate downstream of a scoring node produces - was a 500 on every
        # subsequent read of the run rather than a display defect.
        prompt = RunRegistry._gate_prompt(
            "run-under-test",
            validator_context(
                "n2_confirm",
                json.dumps({"verdict": {"score": 4.2}, "confidence": "high"}),
                metadata={GATE_EDITABLE_FIELDS_METADATA_KEY: []},
            ),
        )
        self.assertIsNone(prompt["verdict"])
        self.assertIsNone(prompt["confidence"])
        GatePrompt.model_validate(prompt)


class ValidatorGatesAreUnmovedTests(unittest.TestCase):
    """The two shipped gates declare none of this, and nothing about them moved.

    `tests/service/test_gates_mode.py`, `tests/integration/test_ws_gate_replies.py`
    and `tests/service/test_gate_resume_race.py` pin the validator's behaviour
    end to end. What is pinned HERE is narrower and is the thing this package
    could plausibly have broken: that the absence of authored metadata is what
    keeps a validator gate on the old path, rather than a flag somebody has to
    remember to set.
    """

    def _prompt(self, method_name: str, output: Any) -> dict[str, Any]:
        return RunRegistry._gate_prompt(
            "run-under-test", validator_context(method_name, output)
        )

    def test_the_scope_gate_keeps_its_title_and_its_editable_payload(self) -> None:
        prompt = self._prompt(
            "confirm_scope", json.dumps({"category": "Clinic ops", "segment": "clinics"})
        )
        self.assertEqual(prompt["node_id"], "confirm_scope")
        self.assertEqual(prompt["title"], "Confirm scope")
        self.assertEqual(prompt["summary"], "Clinic ops")
        self.assertEqual(prompt["derived"], [])
        self.assertEqual(
            set(prompt["fields"]), {"category", "segment", GATE_NOTE_FIELD}
        )

    def test_the_verdict_gate_still_derives_every_key(self) -> None:
        prompt = self._prompt(
            "review_verdict",
            json.dumps(
                {
                    "verdict": "NEEDS_WORK",
                    "confidence": 0.42,
                    "cheapest_next_test": "Interview five clinics.",
                }
            ),
        )
        self.assertEqual(prompt["title"], "Review verdict")
        self.assertEqual(prompt["summary"], "Interview five clinics.")
        self.assertEqual(set(prompt["fields"]), {GATE_NOTE_FIELD})
        self.assertEqual(
            {item["key"] for item in prompt["derived"]},
            {"verdict", "confidence", "cheapest_next_test"},
        )
        self.assertEqual(prompt["verdict"], "NEEDS_WORK")
        self.assertEqual(prompt["confidence"], 0.42)

    def test_the_validators_budget_and_window_are_the_global_ones(self) -> None:
        prompt = self._prompt("confirm_scope", json.dumps({"category": "Clinic ops"}))
        self.assertEqual(prompt["max_revise_turns"], VALIDATOR_MAX_GATE_TURNS)
        expires_at = datetime.fromisoformat(str(prompt["expires_at"]))
        self.assertEqual(
            expires_at - datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
            timedelta(seconds=VALIDATOR_GATE_TIMEOUT_SECONDS),
        )

    def test_a_validator_edit_still_goes_to_the_slot_route_scope_reads(self) -> None:
        payload = json.loads(
            RunRegistry._feedback(
                validator_context(
                    "confirm_scope", json.dumps({"category": "Clinic ops"})
                ),
                "revise",
                {"category": "Solo practitioners", GATE_NOTE_FIELD: "Narrow it."},
            )
        )
        self.assertEqual(payload["scope"], {"category": "Solo practitioners"})
        self.assertNotIn("fields", payload)


if __name__ == "__main__":  # pragma: no cover - parity with the other suites
    unittest.main()
