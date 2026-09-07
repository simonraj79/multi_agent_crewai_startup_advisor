"""Audit M11: an authored agent gets a wall clock, and it is bounded.

Every LIBRARY agent has had one since the day it was written - `agents.yaml`
gives the six validator agents 120-300 s and the three brief agents 300-600 s -
and CrewAI's own default for `Agent.max_execution_time` is `None`, which is no
clock at all. An AUTHORED agent carried no value, `runtime._present` dropped the
key, and the agent ran unbounded. RUN_CONCURRENCY defaults to 1, so the one
worker thread held by an agent whose model or tool never answers is the whole
service: the eight runs MAX_QUEUED_RUNS admits behind it wait for a call that is
not coming back.

Three properties, and the middle one is the trap. `document.py` bounds what an
author may ask for; `runtime._authored_agent` fills in the default when they
asked for nothing; and it does so with an `is None` test rather than
`setdefault`, because `compiler._authored_agent_with` writes all six `advanced`
keys unconditionally - so the key is always PRESENT and `setdefault` would have
been a no-op that shipped looking like a fix.

No cost: it builds `Agent` objects and reads their attributes, and never runs
one.
"""

from __future__ import annotations

import unittest
from typing import Any

import pydantic

from brief_crew.builder import BuilderDocument
from brief_crew.builder.compiler import compile_document
from brief_crew.builder.runtime import AuthoredAgentSpec, DefaultCrewFactories
from brief_crew.config import (
    BUILDER_DEFAULT_AGENT_SECONDS,
    BUILDER_MAX_AGENT_SECONDS,
)
from tests.builder.test_document import (
    document,
    edge,
    input_node,
    node as raw_node,
)


def authored_agent_node(node_id: str = "draft", **advanced: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "role": "Market analyst",
        "goal": "find who already sells this",
        "backstory": "you have priced twenty categories",
        "task": {"description": "research ${state.idea}", "expected_output": "a paragraph"},
        "llm": {"model": "google/gemini-3.5-flash-lite"},
        "tier": "cheap",
    }
    config.update(advanced)
    return {"id": node_id, "kind": "agent", "label": node_id, "config": config}


def one_agent(**advanced: Any) -> BuilderDocument:
    return document(
        [
            input_node("idea"),
            authored_agent_node(**advanced),
            raw_node(
                "report",
                "output",
                {"body_key": "markdown_body", "source": "${state.out__draft}"},
            ),
        ],
        [edge("e1", "idea", "draft"), edge("e2", "draft", "report")],
    )


def spec_from(document_: BuilderDocument) -> AuthoredAgentSpec:
    """The `with:` block the compiler actually writes, as the runtime reads it.

    Through `compile_document` rather than by hand, because the defect is
    precisely about which keys the compiler emits: a spec assembled in this file
    could omit `max_execution_time` and make `setdefault` look correct.
    """

    compiled = compile_document(document_, ceiling_usd=0.0)
    for method in compiled.definition["methods"].values():
        block = dict(method.get("do", {}).get("with", {}))
        if block.get("role"):
            block.pop("cancel_token", None)
            block.pop("state_sink", None)
            return AuthoredAgentSpec(
                **{
                    key: value
                    for key, value in block.items()
                    if key in AuthoredAgentSpec.__dataclass_fields__
                }
            )
    raise AssertionError("the compiled document has no authored agent method")


class TheCompilerAlwaysWritesTheKeyTests(unittest.TestCase):
    """The premise the `is None` test rests on, asserted rather than assumed."""

    def test_max_execution_time_is_present_and_none_when_unset(self) -> None:
        advanced = dict(spec_from(one_agent()).advanced)
        self.assertIn("max_execution_time", advanced)
        self.assertIsNone(advanced["max_execution_time"])


class AuthoredAgentWallClockTests(unittest.TestCase):
    def test_an_agent_that_names_no_clock_is_given_the_default(self) -> None:
        agent = DefaultCrewFactories()._authored_agent(
            spec_from(one_agent()), node_id="draft"
        )
        self.assertEqual(agent.max_execution_time, BUILDER_DEFAULT_AGENT_SECONDS)
        self.assertEqual(agent.max_execution_time, 300)

    def test_the_authors_own_value_is_kept(self) -> None:
        agent = DefaultCrewFactories()._authored_agent(
            spec_from(one_agent(max_execution_time=45)), node_id="draft"
        )
        self.assertEqual(agent.max_execution_time, 45)

    def test_the_ceiling_is_itself_buildable(self) -> None:
        agent = DefaultCrewFactories()._authored_agent(
            spec_from(one_agent(max_execution_time=BUILDER_MAX_AGENT_SECONDS)),
            node_id="draft",
        )
        self.assertEqual(agent.max_execution_time, BUILDER_MAX_AGENT_SECONDS)


class MaxExecutionTimeCeilingTests(unittest.TestCase):
    """The document refuses a clock above the ceiling, naming the ceiling."""

    def test_one_second_over_the_ceiling_is_refused(self) -> None:
        with self.assertRaises(pydantic.ValidationError) as raised:
            one_agent(max_execution_time=BUILDER_MAX_AGENT_SECONDS + 1)
        message = str(raised.exception)
        self.assertIn("max_execution_time", message)
        self.assertIn(str(BUILDER_MAX_AGENT_SECONDS), message)
        self.assertIn(str(BUILDER_MAX_AGENT_SECONDS + 1), message)

    def test_nine_hundred_and_one_is_the_audits_own_figure(self) -> None:
        with self.assertRaises(pydantic.ValidationError) as raised:
            one_agent(max_execution_time=901)
        self.assertIn("less than or equal to 900", str(raised.exception))

    def test_zero_is_still_refused_from_below(self) -> None:
        """`ge=1` was already there; the ceiling must not have loosened it."""

        with self.assertRaises(pydantic.ValidationError):
            one_agent(max_execution_time=0)

    def test_the_ceiling_is_a_named_constant_and_not_a_literal(self) -> None:
        self.assertGreater(BUILDER_MAX_AGENT_SECONDS, BUILDER_DEFAULT_AGENT_SECONDS)
        self.assertEqual(BUILDER_MAX_AGENT_SECONDS, 900)
        self.assertEqual(BUILDER_DEFAULT_AGENT_SECONDS, 300)


if __name__ == "__main__":
    unittest.main()
