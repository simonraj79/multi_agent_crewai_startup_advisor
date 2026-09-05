"""A gate's payload reaches a prompt as PROSE, and everything else is untouched.

**The defect this file pins was found by spending money, twice.** Run
`877f393f` put a gate's reply metadata into three specialists' task
descriptions (`benchmarks/paid-runs.md` defect 3, fixed by the
`decision__<gate>` namespace); run `d1fdeea6` then proved the right value was
reaching them and showed what it read as:

    Size the market for {"summary": "Plan the launch of a keyboard-first task
    manager for engineering teams."} and name the buyer.

Every model answered on topic, so the envelope cost nothing that day. It is
fixed anyway, because the next author to write a gate with three fields is the
one who finds out what a three-key envelope reads as, and they find out for
money.

**The boundary under test is READER versus STORE**, and half of this file is
about the half that must NOT move. `out__<gate>` stays JSON: 10 D5's replay
restores it, `gate_payload` parses it back into a form, the State tab shows it
and the export carries it. Only `prompt_inputs` - the one place a state
reference becomes text a MODEL reads - is rendered.

Three tests are therefore negative, and they are the ones that would catch a
future edit moving the rendering one layer down into `_record`: the stored
output, the router's operand comparison, and the run's own deliverable.

No cost. Every crew here is a local double whose `kickoff` returns a canned
string; the compiler, the flow engine and the state plumbing are all real.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Sequence

from crewai.flow.flow import Flow

from brief_crew.builder.compiler import compile_document
from brief_crew.builder.runtime import state_ref_text, use_crew_factories
from brief_crew.config import RUN_RESULT_BODY_KEYS
from tests.builder.test_document import document, edge, node

BODY_KEY = RUN_RESULT_BODY_KEYS[0]

#: The exact payload the paid run's gate rendered, spelled once. A single-key
#: object, because `gate_payload` wraps anything that is not already a JSON
#: object into one `summary` field - which is the commonest gate shape there is.
PAID_RUN_PAYLOAD = json.dumps(
    {
        "summary": (
            "Plan the launch of a keyboard-first task manager for engineering teams."
        )
    }
)

PAID_RUN_PROSE = "Plan the launch of a keyboard-first task manager for engineering teams."


# --------------------------------------------------------------------------
# The rendering rules
# --------------------------------------------------------------------------
class RenderingTests(unittest.TestCase):
    """Every rule in `state_ref_text`, one test each."""

    def test_a_single_key_object_becomes_its_bare_value(self) -> None:
        self.assertEqual(state_ref_text(PAID_RUN_PAYLOAD), PAID_RUN_PROSE)

    def test_a_multi_key_object_becomes_one_key_value_line_per_key(self) -> None:
        payload = json.dumps({"segment": "clinics", "notes": "book by phone"})
        self.assertEqual(
            state_ref_text(payload), "segment: clinics\nnotes: book by phone"
        )

    def test_the_lines_keep_the_payload_own_order_and_are_not_sorted(self) -> None:
        # A gate form renders its fields in the order the payload carries them,
        # so a prompt that re-sorted them would read in a different order from
        # the screen the operator answered.
        payload = json.dumps({"zeta": "1", "alpha": "2", "middle": "3"})
        self.assertEqual(state_ref_text(payload), "zeta: 1\nalpha: 2\nmiddle: 3")

    def test_a_nested_value_is_compact_json_and_not_flattened(self) -> None:
        payload = json.dumps({"scope": {"users": ["nurses"], "n": 2}, "note": "ok"})
        self.assertEqual(
            state_ref_text(payload),
            'scope: {"users":["nurses"],"n":2}\nnote: ok',
        )

    def test_a_single_key_object_whose_value_is_nested_renders_that_value(self) -> None:
        payload = json.dumps({"scope": {"users": ["nurses"]}})
        self.assertEqual(state_ref_text(payload), '{"users":["nurses"]}')

    def test_a_null_field_is_blank_and_never_the_word_null(self) -> None:
        payload = json.dumps({"segment": "clinics", "notes": None})
        self.assertEqual(state_ref_text(payload), "segment: clinics\nnotes: ")

    def test_a_mapping_renders_by_the_same_rules_as_its_json_spelling(self) -> None:
        # `decision__<gate>` is a real mapping in state rather than a string, so
        # an author who points a prompt at one gets prose too.
        self.assertEqual(
            state_ref_text({"decision": "approve", "honoured": False}),
            "decision: approve\nhonoured: false",
        )

    def test_an_empty_object_renders_as_nothing(self) -> None:
        self.assertEqual(state_ref_text("{}"), "")


class UntouchedTests(unittest.TestCase):
    """Everything that is not a JSON object comes back as the SAME object.

    `assertIs` and not `assertEqual` throughout: the promise is that nothing
    which works today renders differently, and an equal-but-new string would
    still be a new value handed to CrewAI's `interpolate_only`.
    """

    def test_a_plain_prose_string_is_returned_unchanged(self) -> None:
        value = "Plan the launch of a keyboard-first task manager."
        self.assertIs(state_ref_text(value), value)

    def test_a_string_that_only_LOOKS_like_json_is_returned_unchanged(self) -> None:
        # Braces at both ends and not parseable. This is the case a regex would
        # get wrong, which is why `_json_object` asks `json.loads`.
        value = '{"segment": "clinics", }'
        self.assertIs(state_ref_text(value), value)

    def test_a_prompt_template_in_braces_is_returned_unchanged(self) -> None:
        value = "{brief} and then {tone}"
        self.assertIs(state_ref_text(value), value)

    def test_a_json_ARRAY_string_is_returned_unchanged(self) -> None:
        value = '["clinics", "dentists"]'
        self.assertIs(state_ref_text(value), value)

    def test_a_number_is_returned_unchanged_and_is_not_stringified(self) -> None:
        self.assertIs(state_ref_text(7), 7)

    def test_a_list_is_returned_unchanged(self) -> None:
        value = ["clinics", "dentists"]
        self.assertIs(state_ref_text(value), value)

    def test_none_is_returned_unchanged(self) -> None:
        self.assertIsNone(state_ref_text(None))


# --------------------------------------------------------------------------
# The reader is wired - through the real compiler and the real flow engine
# --------------------------------------------------------------------------
class _Crew:
    """One canned answer, and a record of what it was kicked off with."""

    def __init__(self, factories: "_Factories", node_id: str) -> None:
        self._factories = factories
        self._node_id = node_id

    def kickoff(self, inputs: Any = None) -> str:
        self._factories.kickoffs.append((self._node_id, dict(inputs or {})))
        return self._factories.answers.get(self._node_id, self._node_id + " said so")


class _Factories:
    def __init__(self, answers: dict[str, str] | None = None) -> None:
        self.answers = answers or {}
        self.kickoffs: list[tuple[str, dict[str, Any]]] = []

    def agent_crew(
        self,
        *,
        node_id: str,
        agent_id: str,
        tier: str,
        tools: Sequence[str],
        max_iter: int,
        guardrail_max_retries: int,
        **_: Any,
    ) -> _Crew:
        return _Crew(self, node_id)

    def crew(self, *, node_id: str, crew_id: str, **_: Any) -> _Crew:
        return _Crew(self, node_id)

    def authored_agent_crew(self, *, node_id: str, spec: Any) -> _Crew:
        return _Crew(self, node_id)

    def authored_crew(self, *, node_id: str, spec: Any) -> _Crew:
        return _Crew(self, node_id)


def _scoper(node_id: str = "scoper") -> dict[str, Any]:
    return node(
        node_id,
        "agent",
        {
            "agent_id": "scoper",
            "tier": "escalation",
            "prompt_inputs": {"idea": "${state.out__idea}", "human_override": ""},
        },
    )


def _reader(node_id: str, source: str) -> dict[str, Any]:
    """An agent whose whole prompt input is one reference to `source`."""

    return node(
        node_id,
        "agent",
        {
            "agent_id": "market_analyst",
            "tier": "cheap",
            "prompt_inputs": {
                "scoped_idea_json": "${state.out__" + source + "}",
                "market_query": "clinic scheduling",
                "cached_evidence_block": "",
            },
        },
    )


def _crew_reader(node_id: str, source: str) -> dict[str, Any]:
    return node(
        node_id,
        "crew",
        {
            "crew_id": "scope",
            "tier": "escalation",
            "prompt_inputs": {"brief": "${state.out__" + source + "}"},
        },
    )


def _output(node_id: str = "post", source: str = "${state.out__reader}") -> dict[str, Any]:
    return node(node_id, "output", {"body_key": BODY_KEY, "source": source})


def _chain(factories: _Factories, reader: dict[str, Any] | None = None):
    """input -> scoper -> reader -> output, run for free."""

    reader_node = reader or _reader("reader", "scoper")
    reader_id = str(reader_node["id"])
    return _run(
        [
            node("idea", "input", {"field": "idea"}),
            _scoper(),
            reader_node,
            _output(source="${state.out__" + reader_id + "}"),
        ],
        [
            edge("e1", "idea", "scoper"),
            edge("e2", "scoper", reader_id),
            edge("e3", reader_id, "post"),
        ],
        factories,
    )


def _run(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    factories: _Factories,
) -> tuple[Any, Any]:
    compiled = compile_document(document(nodes, edges))
    flow = Flow.from_declaration(contents=compiled.definition, suppress_flow_events=True)
    with use_crew_factories(factories):
        result = flow.kickoff(inputs={"idea": "a scheduling assistant for clinics"})
    return result, flow


class WiredThroughTheCompilerTests(unittest.TestCase):
    """The reference resolves, then renders, then reaches the crew."""

    def test_an_agent_reading_a_single_key_object_is_briefed_on_the_bare_value(self) -> None:
        factories = _Factories({"scoper": PAID_RUN_PAYLOAD})
        _chain(factories)
        seen = dict(factories.kickoffs)["reader"]
        self.assertEqual(seen["scoped_idea_json"], PAID_RUN_PROSE)
        # The paid run's exact symptom, asserted as an absence.
        self.assertNotIn("{", seen["scoped_idea_json"])

    def test_a_crew_reading_a_single_key_object_is_briefed_on_the_bare_value(self) -> None:
        # The shape `hierarchical-delegation` ships: one crew node whose whole
        # `brief` is `${state.out__<gate>}`, and three members interpolating it.
        factories = _Factories({"scoper": PAID_RUN_PAYLOAD})
        _chain(factories, _crew_reader("team", "scoper"))
        self.assertEqual(dict(factories.kickoffs)["team"]["brief"], PAID_RUN_PROSE)

    def test_a_multi_key_upstream_output_reaches_the_prompt_as_lines(self) -> None:
        factories = _Factories(
            {"scoper": json.dumps({"segment": "clinics", "job": "book"})}
        )
        _chain(factories)
        self.assertEqual(
            dict(factories.kickoffs)["reader"]["scoped_idea_json"],
            "segment: clinics\njob: book",
        )

    def test_an_ordinary_prose_answer_reaches_the_prompt_exactly_as_before(self) -> None:
        factories = _Factories({"scoper": "clinics book appointments by phone"})
        _chain(factories)
        self.assertEqual(
            dict(factories.kickoffs)["reader"]["scoped_idea_json"],
            "clinics book appointments by phone",
        )

    def test_a_literal_prompt_input_the_author_typed_is_not_rendered(self) -> None:
        factories = _Factories()
        _chain(factories)
        self.assertEqual(
            dict(factories.kickoffs)["reader"]["market_query"], "clinic scheduling"
        )


class TheStoreIsUntouchedTests(unittest.TestCase):
    """The three readers that deliberately did NOT get the rendering."""

    def test_the_stored_output_is_still_the_json_the_node_produced(self) -> None:
        # This is the assertion that fails if somebody moves the rendering into
        # `_record`: replay, the State tab, the export and `gate_payload` all
        # read this key and all of them want the object back.
        factories = _Factories({"scoper": PAID_RUN_PAYLOAD})
        _, flow = _chain(factories)
        self.assertEqual(flow.state["out__scoper"], PAID_RUN_PAYLOAD)
        self.assertEqual(json.loads(flow.state["out__scoper"])["summary"], PAID_RUN_PROSE)

    def test_the_deliverable_is_still_the_json_and_not_prose(self) -> None:
        factories = _Factories({"scoper": PAID_RUN_PAYLOAD})
        result, _ = _run(
            [
                node("idea", "input", {"field": "idea"}),
                _scoper(),
                _output(source="${state.out__scoper}"),
            ],
            [edge("e1", "idea", "scoper"), edge("e2", "scoper", "post")],
            factories,
        )
        self.assertEqual(json.loads(result[BODY_KEY]), json.loads(PAID_RUN_PAYLOAD))

    def test_a_router_still_compares_the_raw_value(self) -> None:
        # `route_branch` reads `state.get(key)` and never a rendered string, so
        # an `eq` against the stored JSON still matches. A router that started
        # comparing prose would answer differently for the same document.
        factories = _Factories({"scoper": PAID_RUN_PAYLOAD})
        router = node(
            "pick",
            "router",
            {
                "branches": [
                    {
                        "label": "match",
                        "op": "eq",
                        "key": "out__scoper",
                        "value": PAID_RUN_PAYLOAD,
                    },
                    {"label": "other", "op": "otherwise"},
                ]
            },
        )
        _run(
            [
                node("idea", "input", {"field": "idea"}),
                _scoper(),
                router,
                _reader("hit", "pick"),
                _reader("miss", "pick"),
                _output(source="${state.out__hit}"),
            ],
            [
                edge("e1", "idea", "scoper"),
                edge("e2", "scoper", "pick"),
                edge("e3", "pick", "hit", source_port="match"),
                edge("e4", "pick", "miss", source_port="other"),
                edge("e5", "hit", "post"),
            ],
            factories,
        )
        ran = [node_id for node_id, _ in factories.kickoffs]
        self.assertIn("hit", ran)
        self.assertNotIn("miss", ran)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
