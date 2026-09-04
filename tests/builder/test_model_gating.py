"""What a document may ask a model to do - plan 05 criterion 7, D7.

Three codes, three different repairs, and the interesting thing about them is
which ones can be provoked against the LIVE registry and which cannot:

* ``model-unknown`` - live. `openai/o4-mini` is genuinely absent from the roster.
* ``model-lacks-capability`` - live for reasoning, and only for reasoning:
  `openai/gpt-4.1-nano` and `openai/gpt-4o-mini` publish no `reasoning` in their
  `supported_parameters` (measured 2026-09-04), while all ten roster rows
  support JSON mode. So the reasoning half is proved against the shipped
  registry and the JSON half needs a patched row - and the tests below say which
  is which rather than hiding the difference behind one fixture.
* ``model-over-ceiling`` - NOT live, and cannot be. `config.py` refuses an
  over-ceiling row at import, so the only way this code fires is on a document
  published before a catalogue price moved. That is exactly the state the test
  reproduces, and it is why `model_problems` takes a `registry` argument at all.

Enforced twice, and the second time is the point: the inspector disables the
control AND the server reports it anyway, so a stale client cannot smuggle in a
parameter the compiler would silently drop. A silently-dropped parameter is what
the gauntlet names as the single most infuriating competitor behaviour, and a
client-side-only gate is exactly how you ship one.

No cost: documents and a dict. No network, no model, no credential.
"""

from __future__ import annotations

import unittest
from typing import Any

from brief_crew.builder import (
    MODEL_LACKS_CAPABILITY,
    MODEL_OVER_CEILING,
    MODEL_UNKNOWN,
    BuilderDocument,
    model_problems,
    validate_document,
)
from brief_crew.config import MODEL_BY_ID, MODEL_PRICE_CEILING_IN
from tests.builder.test_document import (
    document,
    edge,
    input_node,
    node,
    output_node,
)

ROSTER_MODEL = "google/gemini-3.8-flash"
#: Measured 2026-09-04: `reasoning` is absent from its `supported_parameters`,
#: and the registry records `supports_reasoning: false`. A LIVE example, so this
#: half of D7 is not proved by a fixture arguing with itself.
NO_REASONING_MODEL = "openai/gpt-4.1-nano"
#: One endpoint, $1.10/M input. Under `provider.max_price` every candidate is
#: filtered and the request fails rather than overspending, so it is refused
#: from the roster up front rather than merely priced out of a graph.
UNSERVABLE_MODEL = "openai/o4-mini"


def authored_agent(
    node_id: str = "draft",
    *,
    model: str = ROSTER_MODEL,
    llm: dict[str, Any] | None = None,
    **config: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "tier": "escalation",
        "role": "Market analyst",
        "goal": "Find who already sells this",
        "backstory": "You have priced twenty categories and been wrong about three.",
        "task": {
            "description": "Research the market for ${state.idea}",
            "expected_output": "Three competitors with URLs",
        },
        "llm": {"model": model, **(llm or {})},
    }
    body.update(config)
    return node(node_id, "agent", body)


def one_agent(**kwargs: Any) -> BuilderDocument:
    return document(
        [input_node("idea"), authored_agent(**kwargs), output_node()],
        [edge("e1", "idea", "draft"), edge("e2", "draft", "report")],
    )


def attach(edge_id: str, source: str, target: str) -> dict[str, Any]:
    """An attachment edge, spelled as `test_attachment_bounds.py` spells it.

    `test_document.edge` hardcodes `target_port: "in"` - the FLOW port - and an
    attachment is not a step, so it needs the other spelling.
    """

    return {
        "id": edge_id,
        "source": source,
        "source_port": "attach",
        "target": target,
        "target_port": "attach",
    }


def codes(problems: list[Any]) -> list[str]:
    return [problem.code for problem in problems]


def patched_registry(model_id: str, **fields: Any) -> dict[str, Any]:
    """The live registry with ONE row edited, as a plain dict.

    A whole fake roster would be a second registry that could drift; one edited
    row keeps every other model exactly as it ships and makes the test's subject
    the single field it changed.
    """

    edited = dict(MODEL_BY_ID)
    edited[model_id] = MODEL_BY_ID[model_id]._replace(**fields)
    return edited


class UnknownModelTests(unittest.TestCase):
    def test_a_model_outside_the_roster_is_reported_by_name(self) -> None:
        problems = model_problems(one_agent(model=UNSERVABLE_MODEL))
        self.assertEqual(codes(problems), [MODEL_UNKNOWN])
        self.assertIn(UNSERVABLE_MODEL, problems[0].message)
        self.assertEqual(problems[0].node_id, "draft")

    def test_it_reaches_validate_document_and_not_only_this_module(self) -> None:
        """The composition, because a check nothing calls is not a check.

        `validate_document` is what `/api/builder/validate`, the saved-document
        view and `compile_document` all reach, so this is the assertion that the
        model rules are actually in the author's path.
        """

        self.assertIn(MODEL_UNKNOWN, codes(validate_document(one_agent(model=UNSERVABLE_MODEL))))

    def test_a_roster_model_produces_nothing(self) -> None:
        self.assertEqual(model_problems(one_agent()), [])

    def test_the_prefix_and_the_variant_still_resolve(self) -> None:
        """A hand-edited document must not read as `model-unknown` on a spelling.

        `ModelSlug` checks SHAPE only, so `openrouter/` and `:nitro` both reach
        here in practice. Resolving them is what keeps the reported problem
        about a real model rather than about a string.
        """

        for spelling in (
            f"openrouter/{ROSTER_MODEL}",
            "google/gemini-3.5-flash-lite:nitro",
            f"openrouter/google/gemini-3.5-flash-lite:nitro",
        ):
            with self.subTest(spelling=spelling):
                self.assertEqual(model_problems(one_agent(model=spelling)), [])

    def test_a_fallback_model_is_checked_too(self) -> None:
        """`retry.fallback_model` is the model of the LAST attempt.

        Which is precisely the attempt nobody exercises before publishing, so an
        unresolvable one would first be discovered by a run that had already
        failed once and was trying to recover.
        """

        graph = one_agent(retry={"max_retries": 1, "fallback_model": UNSERVABLE_MODEL})
        problems = model_problems(graph)
        self.assertEqual(codes(problems), [MODEL_UNKNOWN])
        self.assertIn("retry.fallback_model", problems[0].message)


class OverCeilingTests(unittest.TestCase):
    """The code that cannot fire against a healthy build, and why it exists."""

    def test_a_row_whose_price_crossed_the_ceiling_is_reported(self) -> None:
        problems = model_problems(
            one_agent(model="openai/gpt-4o-mini"),
            registry=patched_registry("openai/gpt-4o-mini", cost_in=1.5),
        )
        self.assertEqual(codes(problems), [MODEL_OVER_CEILING])
        self.assertIn("1.5", problems[0].message)
        self.assertIn(f"${MODEL_PRICE_CEILING_IN:.2f}", problems[0].message)

    def test_the_same_row_at_its_real_price_is_silent(self) -> None:
        """The control. Without it the test above would pass over any patch."""

        self.assertEqual(model_problems(one_agent(model="openai/gpt-4o-mini")), [])

    def test_no_shipped_row_can_produce_it(self) -> None:
        """Because `config.py` refuses one at import. Stated as an assertion.

        If this ever fails, the registry loader's admission check has stopped
        working and every other guarantee in this file is resting on nothing.
        """

        for model in MODEL_BY_ID.values():
            with self.subTest(model=model.id):
                self.assertLessEqual(model.cost_in, MODEL_PRICE_CEILING_IN)


class CapabilityTests(unittest.TestCase):
    """D7's table, and which halves are live."""

    def test_json_mode_is_admitted_on_a_model_that_has_it(self) -> None:
        """Criterion 7's third clause, against the shipped registry.

        All ten roster rows support JSON mode as measured on 2026-09-04, so an
        author asking for it never meets a refusal today. That is the useful
        thing to assert first: the gate has to be silent when the answer is yes.
        """

        graph = one_agent(model=NO_REASONING_MODEL, llm={"response_format": "json_object"})
        self.assertTrue(MODEL_BY_ID[NO_REASONING_MODEL].supports_json_mode)
        self.assertEqual(model_problems(graph), [])

    def test_json_mode_on_a_model_without_it_is_refused(self) -> None:
        graph = one_agent(model="openai/gpt-4o-mini", llm={"response_format": "json_object"})
        problems = model_problems(
            graph, registry=patched_registry("openai/gpt-4o-mini", supports_json_mode=False)
        )
        self.assertEqual(codes(problems), [MODEL_LACKS_CAPABILITY])
        self.assertIn("JSON mode", problems[0].message)
        self.assertIn("openai/gpt-4o-mini", problems[0].message)

    def test_reasoning_effort_on_a_non_reasoning_model_is_refused_LIVE(self) -> None:
        """No patched row: `openai/gpt-4.1-nano` really does not reason.

        Measured 2026-09-04 - it publishes no `reasoning` object at all and
        `reasoning` is absent from its `supported_parameters`. So this half of
        D7 is proved against the registry this build ships, which is a stronger
        statement than the JSON half can currently make.
        """

        self.assertFalse(MODEL_BY_ID[NO_REASONING_MODEL].supports_reasoning)
        problems = model_problems(
            one_agent(model=NO_REASONING_MODEL, llm={"reasoning_effort": "high"})
        )
        self.assertEqual(codes(problems), [MODEL_LACKS_CAPABILITY])
        self.assertIn("reasoning", problems[0].message)

    def test_reasoning_effort_on_a_reasoning_model_is_admitted(self) -> None:
        graph = one_agent(model=ROSTER_MODEL, llm={"reasoning_effort": "high"})
        self.assertTrue(MODEL_BY_ID[ROSTER_MODEL].supports_reasoning)
        self.assertEqual(model_problems(graph), [])

    def test_a_tool_attached_to_a_model_that_cannot_call_tools_is_refused(self) -> None:
        """The `attach` port, gated by `supports_tools`.

        Every roster model is tool-capable - `refresh_models.py` filters on it -
        so this needs a patched row. It is here because the failure it prevents
        is silent at run time: the agent is built, the tool is bound, and the
        model simply never calls it.
        """

        graph = document(
            [
                input_node("idea"),
                authored_agent(model="openai/gpt-4o-mini"),
                node("scrape", "tool", {"tool_id": "firecrawl_scrape", "params": {}}),
                output_node(),
            ],
            [
                edge("e1", "idea", "draft"),
                edge("e2", "draft", "report"),
                attach("e3", "scrape", "draft"),
            ],
        )
        problems = model_problems(
            graph, registry=patched_registry("openai/gpt-4o-mini", supports_tools=False)
        )
        self.assertEqual(codes(problems), [MODEL_LACKS_CAPABILITY])
        self.assertIn("tool calling", problems[0].message)

    def test_the_same_graph_with_a_tool_capable_model_is_silent(self) -> None:
        graph = document(
            [
                input_node("idea"),
                authored_agent(model="openai/gpt-4o-mini"),
                node("scrape", "tool", {"tool_id": "firecrawl_scrape", "params": {}}),
                output_node(),
            ],
            [
                edge("e1", "idea", "draft"),
                edge("e2", "draft", "report"),
                attach("e3", "scrape", "draft"),
            ],
        )
        self.assertEqual(model_problems(graph), [])

    def test_an_unknown_model_reports_once_and_not_twice(self) -> None:
        """One repair, one sentence.

        A node naming a model nobody has cannot also be told its parameters are
        unsupported - that would be a second sentence about the same edit, and
        the canvas groups by code, so the author would see two entries for one
        thing to fix.
        """

        graph = one_agent(model=UNSERVABLE_MODEL, llm={"reasoning_effort": "high"})
        self.assertEqual(codes(model_problems(graph)), [MODEL_UNKNOWN])


class LibraryArmTests(unittest.TestCase):
    """A library node names no model, so none of the three can fire on one."""

    def test_a_library_agent_produces_no_model_problem(self) -> None:
        from tests.builder.test_document import agent_node

        graph = document(
            [input_node("idea"), agent_node("draft", tier="escalation"), output_node()],
            [edge("e1", "idea", "draft"), edge("e2", "draft", "report")],
        )
        self.assertEqual(model_problems(graph), [])


if __name__ == "__main__":
    unittest.main()
