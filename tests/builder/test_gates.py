"""The durable pause: what the operator is shown, what they reply, where it goes.

The centre of this module is `DurableGateTests`, which compiles a gated
document, kicks it off for real, watches it pause, resumes it through
`from_pending()` exactly the way `RunRegistry` does, and reads which branch it
actually took. That is the only kind of test that can catch the failure this
whole design is shaped around: a gate that accepts a reply of `revise` and runs
the approve branch anyway, with no exception, no warning and a returned value
that reads as success.

No model is called anywhere here. The one agent in the fixture is built by an
injected factory, and a gate itself never calls a model by construction -
`llm` is explicitly null precisely so it cannot.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from crewai.flow.async_feedback import HumanFeedbackPending, PendingFeedbackContext
from crewai.flow.flow import Flow
from crewai.flow.flow_definition import FlowDefinition
from crewai.flow.flow_context import current_flow_method_name
from crewai.flow.persistence.sqlite import SQLiteFlowPersistence

from brief_crew.builder.compiler import compile_document
from brief_crew.builder.gates import (
    GATE_PROVIDER,
    GATE_SUMMARY_FIELD,
    BuilderFeedbackProvider,
    gate_decision,
    gate_payload,
)
from brief_crew.builder.runtime import (
    BUILDER_STATE_KEY,
    BuilderRuntimeError,
    render_gate,
    route_gate,
    use_crew_factories,
)
from brief_crew.config import GATE_REVISE_TURNS_METADATA_KEY, RUN_RESULT_BODY_KEYS
from tests.builder.test_compiler import StubFactories, gated_loop

BODY_KEY = RUN_RESULT_BODY_KEYS[0]


class GatePayloadTests(unittest.TestCase):
    def test_an_object_is_shown_as_its_own_fields(self) -> None:
        self.assertEqual(
            gate_payload("confirm", {"segment": "clinics", "job": "rota"}),
            {"segment": "clinics", "job": "rota"},
        )

    def test_json_arriving_as_text_is_parsed_rather_than_escaped(self) -> None:
        # A gate downstream of an agent receives that agent's output as a
        # string; showing it raw would put one wall of escaped JSON in front of
        # the operator instead of the fields they are being asked about.
        self.assertEqual(
            gate_payload("confirm", '{"segment": "clinics"}'),
            {"segment": "clinics"},
        )

    def test_prose_becomes_one_summary_field(self) -> None:
        self.assertEqual(
            gate_payload("confirm", "a scheduling assistant"),
            {GATE_SUMMARY_FIELD: "a scheduling assistant"},
        )

    def test_nothing_at_all_still_produces_a_field(self) -> None:
        self.assertEqual(gate_payload("confirm", None), {GATE_SUMMARY_FIELD: ""})

    def test_a_declared_editable_field_the_payload_lacks_is_added_empty(self) -> None:
        # Dropping it is the silent half: the form renders every key it is
        # given, so a missing key is an input that never appears with nothing
        # on screen to say why.
        self.assertEqual(
            gate_payload("confirm", {"segment": "clinics"}, ["segment", "notes"]),
            {"segment": "clinics", "notes": ""},
        )

    def test_a_declared_editable_field_does_not_overwrite_a_real_value(self) -> None:
        self.assertEqual(
            gate_payload("confirm", {"notes": "keep me"}, ["notes"]),
            {"notes": "keep me"},
        )


class GateDecisionTests(unittest.TestCase):
    def test_revise_is_read_as_revise(self) -> None:
        decision, rest = gate_decision(json.dumps({"decision": "revise", "feedback": "narrower"}))
        self.assertEqual(decision, "revise")
        self.assertEqual(rest, {"feedback": "narrower"})

    def test_anything_that_is_not_revise_is_an_approval(self) -> None:
        for reply in ('{"decision": "approve"}', '{"decision": "yes"}', "{}"):
            with self.subTest(reply=reply):
                self.assertEqual(gate_decision(reply)[0], "approve")

    def test_case_and_whitespace_do_not_change_the_decision(self) -> None:
        self.assertEqual(gate_decision('{"decision": " ReViSe "}')[0], "revise")

    def test_an_unparseable_reply_goes_forward_and_keeps_the_text(self) -> None:
        # Forward rather than wedged: the operator has already answered, and a
        # router that refuses to choose parks the run at a gate with nothing
        # left to do but expire.
        decision, rest = gate_decision("please narrow this down")
        self.assertEqual(decision, "approve")
        self.assertEqual(rest, {"feedback": "please narrow this down"})

    def test_an_edited_object_survives_into_the_gate_nodes_output(self) -> None:
        _, rest = gate_decision(
            json.dumps({"decision": "revise", "scope": {"segment": "dental"}})
        )
        self.assertEqual(rest["scope"], {"segment": "dental"})


class ProviderTests(unittest.TestCase):
    def _context(self, metadata: dict[str, Any]) -> PendingFeedbackContext:
        return PendingFeedbackContext(
            flow_id="flow-1",
            flow_class="Flow",
            method_name="n2_confirm",
            method_output="{}",
            message="Confirm.",
            metadata=metadata,
        )

    class _Flow:
        def __init__(self, state: dict[str, Any]) -> None:
            self.state = state

    def test_the_provider_pauses_instead_of_reading_a_console(self) -> None:
        with self.assertRaises(HumanFeedbackPending) as raised:
            GATE_PROVIDER.request_feedback(
                self._context({"gate_id": "confirm"}), self._Flow({})
            )
        self.assertEqual(raised.exception.callback_info["node_id"], "confirm")

    def test_the_declarations_metadata_dict_is_never_mutated(self) -> None:
        # A declarative gate ALWAYS declares metadata, and the engine passes the
        # definition's own dict by reference - so writing in place would leak
        # one run's gate state into every other run of the same compiled flow.
        declared = {"gate_id": "confirm", "canvas_node": "confirm"}
        with self.assertRaises(HumanFeedbackPending):
            GATE_PROVIDER.request_feedback(
                self._context(declared), self._Flow({"turns__confirm": 2})
            )
        self.assertEqual(declared, {"gate_id": "confirm", "canvas_node": "confirm"})

    def test_the_revise_turns_already_spent_are_stamped_for_the_service(self) -> None:
        # `service/registry.py` reads this off the pending context to stop
        # OFFERING a Revise button the router would decline to honour.
        context = self._context({"gate_id": "confirm"})
        with self.assertRaises(HumanFeedbackPending):
            GATE_PROVIDER.request_feedback(context, self._Flow({"turns__confirm": 2}))
        self.assertEqual(context.metadata[GATE_REVISE_TURNS_METADATA_KEY], 2)

    def test_a_junk_turn_count_does_not_raise_inside_the_pause(self) -> None:
        context = self._context({"gate_id": "confirm"})
        with self.assertRaises(HumanFeedbackPending):
            GATE_PROVIDER.request_feedback(
                context, self._Flow({"turns__confirm": "not a number"})
            )
        self.assertEqual(context.metadata[GATE_REVISE_TURNS_METADATA_KEY], 0)

    def test_an_explicit_no_gates_run_answers_itself(self) -> None:
        reply = GATE_PROVIDER.request_feedback(
            self._context({"gate_id": "confirm"}), self._Flow({"no_gates": True})
        )
        self.assertEqual(json.loads(reply), {"decision": "approve"})

    def test_the_module_singleton_is_the_provider_the_ref_resolves_to(self) -> None:
        from crewai.flow.runtime._actions import resolve_ref

        resolved = resolve_ref("brief_crew.builder.gates:GATE_PROVIDER", field="do")
        self.assertIs(resolved, GATE_PROVIDER)
        self.assertIsInstance(resolved, BuilderFeedbackProvider)


class RouteGateTests(unittest.TestCase):
    """The router half, driven directly, with the routing table it is given."""

    class _Flow:
        def __init__(self, state: dict[str, Any]) -> None:
            self.state = state

        def _discard_or_listener(self, name: str) -> None:
            self.state.setdefault("rearmed", []).append(str(name))

    class _Result:
        def __init__(self, feedback: str) -> None:
            self.feedback = feedback

    def _flow(self, *, max_turns: int = 2, used: int = 0) -> "RouteGateTests._Flow":
        return self._Flow(
            {
                "turns__confirm": used,
                # What `render_gate` left here: the payload the operator was
                # SHOWN. Every assertion below about the router not touching it
                # is meaningless against a `None`.
                "out__confirm": '{"segment": "clinics", "notes": ""}',
                "decision__confirm": None,
                BUILDER_STATE_KEY: {
                    "gates": {
                        "n3_route_confirm": {
                            "node_id": "confirm",
                            "approve": "e3_approve",
                            "revise": "e3_revise",
                            "max_turns": max_turns,
                            "rearm": ["n2_confirm"],
                        }
                    }
                },
            }
        )

    def _route(self, flow: Any, reply: str) -> str:
        token = current_flow_method_name.set("n3_route_confirm")
        try:
            return route_gate(flow, self._Result(reply))
        finally:
            current_flow_method_name.reset(token)

    def test_an_approval_returns_the_approve_label(self) -> None:
        flow = self._flow()
        self.assertEqual(self._route(flow, '{"decision": "approve"}'), "e3_approve")
        self.assertEqual(flow.state["turns__confirm"], 0)

    def test_a_revise_returns_the_revise_label_and_spends_a_turn(self) -> None:
        flow = self._flow()
        self.assertEqual(self._route(flow, '{"decision": "revise"}'), "e3_revise")
        self.assertEqual(flow.state["turns__confirm"], 1)

    def test_a_revise_at_the_cap_goes_forward_rather_than_looping(self) -> None:
        # Failing would discard everything already paid for; refusing would
        # park the run at a gate with nothing left to do but expire.
        flow = self._flow(max_turns=1, used=1)
        self.assertEqual(self._route(flow, '{"decision": "revise"}'), "e3_approve")
        self.assertEqual(flow.state["turns__confirm"], 1)
        self.assertFalse(flow.state["decision__confirm"]["honoured"])

    def test_the_decision_is_recorded_under_the_gates_own_namespace(self) -> None:
        flow = self._flow()
        self._route(flow, '{"decision": "revise", "feedback": "narrower"}')
        self.assertEqual(
            flow.state["decision__confirm"],
            {"decision": "revise", "honoured": True, "turns_used": 1, "feedback": "narrower"},
        )

    def test_the_router_never_touches_the_payload_the_operator_was_shown(self) -> None:
        """Paid-run defect 3, as an assertion.

        This is the whole of it. `route_gate` used to `_record` its decision,
        which writes `out__<gate>` - the key `render_gate` had already filled
        with the gate's SUBJECT and the key every downstream
        `${state.out__<gate>}` resolves through. Measured in run `877f393f`:
        three specialists were briefed on
        `{'decision': 'approve', 'honoured': False, 'turns_used': 0}` and wrote
        about credit default swaps.
        """

        for reply in ('{"decision": "approve"}', '{"decision": "revise"}'):
            with self.subTest(reply=reply):
                flow = self._flow()
                before = flow.state["out__confirm"]
                self._route(flow, reply)
                self.assertEqual(flow.state["out__confirm"], before)
                self.assertNotIn("decision", flow.state["out__confirm"])

    def test_an_operators_edits_replace_the_payload_and_nothing_else(self) -> None:
        """The one thing the router may write there: the operator's own object.

        `service/registry.py::_feedback_payload` sends an authored gate's edits
        back under `fields`, and that mapping is the whole payload with the
        edits applied - so it replaces the rendered one. The decision, the
        `honoured` flag and the turn count never travel with it.
        """

        flow = self._flow()
        self._route(
            flow,
            json.dumps(
                {
                    "decision": "approve",
                    "fields": {"segment": "dental", "notes": "start with one clinic"},
                }
            ),
        )
        self.assertEqual(
            json.loads(flow.state["out__confirm"]),
            {"segment": "dental", "notes": "start with one clinic"},
        )
        self.assertEqual(flow.state["decision__confirm"]["decision"], "approve")

    def test_a_reply_with_no_edits_leaves_the_rendered_payload_alone(self) -> None:
        flow = self._flow()
        self._route(flow, '{"decision": "approve", "feedback": "looks right"}')
        self.assertEqual(
            json.loads(flow.state["out__confirm"]), {"segment": "clinics", "notes": ""}
        )
        self.assertEqual(flow.state["decision__confirm"]["feedback"], "looks right")

    def test_re_entering_a_loop_re_arms_the_listener_first(self) -> None:
        # A multi-event or_() listener is fired once and skipped forever after,
        # and the run then ends normally having produced nothing.
        flow = self._flow()
        self._route(flow, '{"decision": "revise"}')
        self.assertEqual(flow.state["rearmed"], ["n2_confirm"])

    def test_an_approval_does_not_re_arm_anything(self) -> None:
        flow = self._flow()
        self._route(flow, '{"decision": "approve"}')
        self.assertNotIn("rearmed", flow.state)

    def test_a_routing_table_the_run_overwrote_is_refused_loudly(self) -> None:
        # Degrading here would route a gate on data a request body supplied.
        flow = self._Flow({BUILDER_STATE_KEY: {"gates": {}}})
        with self.assertRaises(BuilderRuntimeError):
            self._route(flow, '{"decision": "approve"}')


class RenderGateTests(unittest.TestCase):
    class _Flow:
        def __init__(self) -> None:
            self.state: dict[str, Any] = {}

    def test_the_last_predecessor_with_a_value_is_what_the_gate_shows(self) -> None:
        # The revise loop's output is still null on the first pass, so the gate
        # shows the original; on the second it shows the revision.
        flow = self._Flow()
        first = json.loads(render_gate(flow, node_id="g", source=["original", None]))
        second = json.loads(render_gate(flow, node_id="g", source=["original", "revised"]))
        self.assertEqual(first[GATE_SUMMARY_FIELD], "original")
        self.assertEqual(second[GATE_SUMMARY_FIELD], "revised")

    def test_the_payload_is_published_as_this_nodes_output(self) -> None:
        flow = self._Flow()
        rendered = render_gate(flow, node_id="g", source={"segment": "clinics"})
        self.assertEqual(flow.state["out__g"], rendered)
        self.assertEqual(json.loads(rendered), {"segment": "clinics"})


class DurableGateTests(unittest.TestCase):
    """Compile, run, pause, resume - through the real engine and real SQLite."""

    def setUp(self) -> None:
        # `ignore_cleanup_errors` because SQLiteFlowPersistence keeps its
        # connection open, and Windows refuses to unlink an open file.
        self._temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._temporary.cleanup)
        self.store = SQLiteFlowPersistence(str(Path(self._temporary.name) / "flows.db"))
        self.compiled = compile_document(gated_loop(max_turns=1))
        self.definition = FlowDefinition.from_declaration(contents=self.compiled.definition)
        self.factories = StubFactories(outputs={"scoper": '{"segment": "clinics"}'})

    def _start(self) -> Flow:
        flow = Flow.from_declaration(
            contents=self.compiled.definition,
            persistence=self.store,
            suppress_flow_events=True,
        )
        with use_crew_factories(self.factories):
            self.paused = flow.kickoff(inputs={"idea": "a scheduling assistant"})
        return flow

    def _resume(self, flow_id: str, reply: dict[str, Any]) -> tuple[Any, Flow]:
        # `from_pending`, not `flow.resume()`: resuming the live paused object
        # raises "No pending feedback context", and this is the path
        # `RunRegistry` takes for every gate reply the service accepts.
        resumed = Flow.from_pending(
            flow_id, self.store, definition=self.definition, suppress_flow_events=True
        )
        with use_crew_factories(self.factories):
            return resumed.resume(json.dumps(reply)), resumed

    def test_the_run_pauses_at_the_gate_without_reading_a_console(self) -> None:
        flow = self._start()
        self.assertIsInstance(self.paused, HumanFeedbackPending)
        gate, _ = self.compiled.method_idents["confirm"]
        self.assertEqual(self.paused.context.method_name, gate)
        # The scoper ran; nothing past the gate did.
        self.assertEqual([node for node, _ in self.factories.kickoffs], ["scoper"])
        self.assertIsNone(flow.state["out__report"])

    def test_the_operator_sees_the_upstream_nodes_fields(self) -> None:
        self._start()
        shown = json.loads(self.paused.context.method_output)
        self.assertEqual(shown["segment"], "clinics")
        self.assertEqual(shown["notes"], "")

    def test_the_declared_message_and_the_reply_instruction_both_reach_them(self) -> None:
        self._start()
        self.assertIn("Confirm the scope.", self.paused.context.message)
        self.assertIn("decision=approve", self.paused.context.message)

    def test_an_approve_reply_completes_the_run(self) -> None:
        """And the OUTPUT node downstream of the gate carries the gate's subject.

        `gated_loop`'s report node is `source: "${state.out__confirm}"`, which
        is the reference paid-run defect 3 was found through. Until 2026-09-05
        this run's deliverable was
        `{"decision": "approve", "honoured": false, "turns_used": 0}` - and the
        assertion here was `result[BODY_KEY] == json.dumps(state["out__confirm"])`,
        which is true of whatever that key happens to hold and therefore proved
        nothing. It names the payload now.
        """

        flow = self._start()
        result, resumed = self._resume(flow.state["id"], {"decision": "approve"})
        self.assertEqual(json.loads(result[BODY_KEY]), {"segment": "clinics", "notes": ""})
        self.assertEqual(json.loads(resumed.state["out__confirm"]), json.loads(result[BODY_KEY]))
        self.assertEqual(resumed.state["decision__confirm"]["decision"], "approve")
        self.assertEqual(resumed.state["turns__confirm"], 0)

    def test_a_revise_reply_really_loops_back_to_the_gate(self) -> None:
        # The measured failure this asserts against: with the loop closed by
        # anything but a router, or the decision collapsed by `emit`, this
        # returns normally having produced nothing.
        flow = self._start()
        again, resumed = self._resume(
            flow.state["id"], {"decision": "revise", "feedback": "narrower"}
        )
        self.assertIsInstance(again, HumanFeedbackPending)
        gate, _ = self.compiled.method_idents["confirm"]
        self.assertEqual(again.context.method_name, gate)
        self.assertEqual(resumed.state["turns__confirm"], 1)
        self.assertIsNone(resumed.state["out__report"])
        # The operator's own words reached the node on the revise path - through
        # `decision__confirm`, which is where they are recorded, and never over
        # the top of the payload the gate was about.
        self.assertEqual(resumed.state["out__restate"]["feedback"], "narrower")
        self.assertEqual(resumed.state["decision__confirm"]["feedback"], "narrower")
        # `out__confirm` is NOT still the first payload here, and that is the
        # fixture rather than the contract: `restate` feeds back into the gate,
        # so `render_gate` runs a second time and republishes what the revise
        # path produced. What the contract guarantees is that the ROUTER never
        # writes there - `RouteGateTests` drives that half directly.

    def test_the_second_gate_shows_what_the_revision_produced(self) -> None:
        flow = self._start()
        again, _ = self._resume(
            flow.state["id"], {"decision": "revise", "feedback": "narrower"}
        )
        self.assertEqual(json.loads(again.context.method_output)["feedback"], "narrower")

    def test_the_loop_closes_and_the_run_finishes_on_the_second_pass(self) -> None:
        flow = self._start()
        self._resume(flow.state["id"], {"decision": "revise", "feedback": "narrower"})
        result, resumed = self._resume(flow.state["id"], {"decision": "approve"})
        self.assertNotIsInstance(result, HumanFeedbackPending)
        self.assertEqual(resumed.state["turns__confirm"], 1)
        self.assertIn(BODY_KEY, result)

    def test_a_revise_past_the_cap_goes_forward_instead_of_looping_again(self) -> None:
        flow = self._start()
        self._resume(flow.state["id"], {"decision": "revise", "feedback": "once"})
        result, resumed = self._resume(
            flow.state["id"], {"decision": "revise", "feedback": "twice"}
        )
        self.assertNotIsInstance(result, HumanFeedbackPending)
        self.assertEqual(resumed.state["turns__confirm"], 1)
        self.assertFalse(resumed.state["decision__confirm"]["honoured"])

    def test_an_explicit_no_gates_run_never_pauses_at_all(self) -> None:
        # The service sets `no_gates` only after checking its own flag, and it
        # is a RESERVED run input key so a request body cannot. This is the
        # whole unattended path, end to end.
        flow = Flow.from_declaration(
            contents=self.compiled.definition,
            persistence=self.store,
            suppress_flow_events=True,
        )
        with use_crew_factories(self.factories):
            result = flow.kickoff(
                inputs={"idea": "a scheduling assistant", "no_gates": True}
            )
        self.assertNotIsInstance(result, HumanFeedbackPending)
        self.assertIn(BODY_KEY, result)
        self.assertEqual(flow.state["turns__confirm"], 0)

    def test_the_pause_is_durable_with_no_persist_block_in_the_definition(self) -> None:
        # The engine writes `pending_feedback` itself; the compiled definition
        # declares no `persist:` and does not need to.
        flow = self._start()
        self.assertNotIn("persist", self.compiled.definition)
        rows = self.store.load_pending_feedback(flow.state["id"])
        self.assertIsNotNone(rows)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
