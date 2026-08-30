"""The node cards' CrewAI claims, bound to the crews that actually run.

`VALIDATOR_OVERLAY` and `VALIDATOR_CREW_WIRING` are hand-written: the label, the
tier badge, the tool name, the Crew, the Agent role and the Task are strings a
human typed, and until this module existed nothing compared any of them to the
code that runs at that node. The consequence was not hypothetical. `scrape_web`
on the Brief graph carried `"model": "Cheap tier", "tool": "Web search"` while
the method ran a three-agent crew - a researcher on CHEAP_MODEL and an analyst
and a writer on ESCALATION_MODEL - holding two Firecrawl tools. The node card
was simply false, through a green suite, because the exact-set match in
`build_graph_descriptor` guards node *existence* and never looks at a value.

`tests/validator/test_crews.py` already asserts the crews wire the right model
constants. That is the other half of the same fact and it does not close this
gap: it compares the crews to `config.py`, never to the strings the operator
reads. A badge can be wrong while both of those tests pass.

These tests construct the real crews once, in `setUpClass`. That is why they
live here rather than as an import-time assertion in `graph.py`: each
constructed agent builds an LLM client, an httpx pool and an SSL trust store,
which is the cost the gates' `llm=None` exists to avoid paying twice per run.
"""

from __future__ import annotations

import unittest

from brief_crew.config import CHEAP_MODEL, ESCALATION_MODEL
from brief_crew.crews.validator_crew import (
    FeasibilityCrew,
    MarketCrew,
    ReportCrew,
    ScopeCrew,
    SentimentCrew,
    SynthesisCrew,
)
from brief_crew.service.graph import (
    VALIDATOR_CREW_WIRING,
    VALIDATOR_GRAPH,
    VALIDATOR_OVERLAY,
)
from tests.validator.test_crews import findings, verdict


def _strip(model: str) -> str:
    """CrewAI's `LLM.__new__` drops the provider prefix for native providers.

    So `agent.llm.model` reads `z-ai/glm-5.3-flash` where `config.py` declares
    `openrouter/z-ai/glm-5.3-flash`. Comparing the raw strings is the mistake
    that made `cost_usd` read 0.0 after 128,069 real tokens - `PRICES` was keyed
    on the prefixed spelling and the event reported the stripped one. Normalise
    both sides rather than assuming either.
    """

    return model.split("/", 1)[1] if model.startswith("openrouter/") else model


class ValidatorCrewBindingTests(unittest.TestCase):
    """Every CrewAI string on a validator node names something that exists."""

    @classmethod
    def setUpClass(cls) -> None:
        market, sentiment, feasibility = findings()
        scope = ScopeCrew().crew()
        synthesis = SynthesisCrew(market, sentiment, feasibility).crew()
        cls.crews = {
            "scope_idea": scope,
            # Deliberately the same object as scope_idea: one Scoper serves both
            # nodes. Asserting the wiring per node rather than per crew is what
            # keeps that true if someone ever splits them.
            "revise_scope": scope,
            "research_market": MarketCrew().crew(),
            "research_sentiment": SentimentCrew().crew(),
            "research_feasibility": FeasibilityCrew().crew(),
            "synthesize": synthesis,
            "revise_verdict": synthesis,
            "write_report": ReportCrew(verdict(), set()).crew(),
        }

    def test_the_wiring_table_covers_exactly_the_nodes_that_run_a_crew(self) -> None:
        self.assertEqual(set(VALIDATOR_CREW_WIRING), set(self.crews))

    def test_every_wired_node_names_the_agent_that_runs_there(self) -> None:
        for node_id, wiring in VALIDATOR_CREW_WIRING.items():
            with self.subTest(node=node_id):
                crew = self.crews[node_id]
                self.assertEqual(
                    len(crew.agents),
                    1,
                    f"{node_id} is wired as a single-agent crew; if that ever "
                    "changes, agent_role can no longer name one agent and the "
                    "node card needs a different shape",
                )
                self.assertEqual(crew.agents[0].role.strip(), wiring["agent_role"])

    def test_every_wired_node_names_the_task_that_runs_there(self) -> None:
        for node_id, wiring in VALIDATOR_CREW_WIRING.items():
            with self.subTest(node=node_id):
                crew = self.crews[node_id]
                self.assertEqual(len(crew.tasks), 1)
                self.assertEqual(crew.tasks[0].name, wiring["task_name"])

    def test_the_tier_badge_names_the_tier_the_agent_is_wired_to(self) -> None:
        """The defect this whole module exists for."""

        tiers = {
            _strip(CHEAP_MODEL): "Cheap tier",
            _strip(ESCALATION_MODEL): "Escalation tier",
        }
        for node_id in VALIDATOR_CREW_WIRING:
            with self.subTest(node=node_id):
                actual = _strip(str(self.crews[node_id].agents[0].llm.model))
                self.assertIn(
                    actual, tiers, f"{node_id} runs an unrecognised model {actual!r}"
                )
                self.assertEqual(
                    VALIDATOR_OVERLAY[node_id].get("model"),
                    tiers[actual],
                    f"{node_id}'s badge does not name the tier it runs on",
                )

    def test_a_node_claims_a_tool_exactly_when_its_agent_has_one(self) -> None:
        for node_id in VALIDATOR_CREW_WIRING:
            with self.subTest(node=node_id):
                tools = list(self.crews[node_id].agents[0].tools or [])
                claims_tool = VALIDATOR_OVERLAY[node_id].get("tool") is not None
                self.assertEqual(
                    claims_tool,
                    bool(tools),
                    f"{node_id} claims tool="
                    f"{VALIDATOR_OVERLAY[node_id].get('tool')!r} but wires "
                    f"{len(tools)} tools",
                )

    def test_the_toolless_boundary_is_still_toolless(self) -> None:
        """Scoper, Synthesist and Reporter carry no tools, by platform rule."""

        for node_id in (
            "scope_idea",
            "revise_scope",
            "synthesize",
            "revise_verdict",
            "write_report",
        ):
            with self.subTest(node=node_id):
                self.assertEqual(list(self.crews[node_id].agents[0].tools or []), [])

    def test_the_descriptor_carries_the_wiring_to_the_client(self) -> None:
        by_id = {node.id: node for node in VALIDATOR_GRAPH.nodes}
        for node_id, wiring in VALIDATOR_CREW_WIRING.items():
            with self.subTest(node=node_id):
                node = by_id[node_id]
                self.assertEqual(node.crew, wiring["crew"])
                self.assertEqual(node.agent_role, wiring["agent_role"])
                self.assertEqual(node.task_name, wiring["task_name"])

    def test_nodes_that_run_no_crew_claim_none(self) -> None:
        """A gate, a router and the persist step must not claim an agent."""

        for node in VALIDATOR_GRAPH.nodes:
            if node.id in VALIDATOR_CREW_WIRING:
                continue
            with self.subTest(node=node.id):
                self.assertIsNone(node.crew)
                self.assertIsNone(node.agent_role)
                self.assertIsNone(node.task_name)


class DerivedCrewAIFactsTests(unittest.TestCase):
    """The facts CrewAI computes, as the descriptor now reports them.

    None of these is asserted anywhere else: `build_flow_structure` returned
    them all along, `graph.py` filed them under an opaque `metadata` blob, and
    `GraphNodeDefinition` in `types/studio.ts` had no field to receive them - so
    they travelled the wire on every graph request and were dropped on arrival.
    """

    def setUp(self) -> None:
        self.by_id = {node.id: node for node in VALIDATOR_GRAPH.nodes}

    def test_human_feedback_is_derived_and_finds_both_gates(self) -> None:
        gates = {node.id for node in VALIDATOR_GRAPH.nodes if node.human_feedback}
        self.assertEqual(gates, {"confirm_scope", "review_verdict"})

    def test_kind_gate_and_human_feedback_can_never_disagree(self) -> None:
        """`build_graph_descriptor` raises rather than letting these drift.

        This asserts the outcome; the guard itself is what makes a new
        @human_feedback method impossible to add without also drawing it as a
        gate, and impossible to draw as a gate without declaring it.
        """

        for node in VALIDATOR_GRAPH.nodes:
            with self.subTest(node=node.id):
                self.assertEqual(node.human_feedback, node.kind == "gate")

    def test_flow_method_type_uses_crewais_own_three_names(self) -> None:
        for node in VALIDATOR_GRAPH.nodes:
            if node.id == "unattributed":
                # Instrumentation, not a CrewAI method.
                self.assertIsNone(node.flow_method_type)
                continue
            with self.subTest(node=node.id):
                self.assertIn(node.flow_method_type, {"start", "listen", "router"})

    def test_exactly_one_start_method_and_it_is_the_scoper(self) -> None:
        starts = [n.id for n in VALIDATOR_GRAPH.nodes if n.flow_method_type == "start"]
        self.assertEqual(starts, ["scope_idea"])
        self.assertEqual(list(VALIDATOR_GRAPH.start_nodes), ["scope_idea"])

    def test_the_fan_in_before_synthesis_is_an_AND_over_all_three_branches(self) -> None:
        """The structural reason all three branches must finish.

        This is the one genuinely interesting fact in the topology and the UI
        had no way to draw it: the three fan-in edges carried
        `condition_type: "AND"` on the wire and the client mapped only
        `label` and `active`.
        """

        synthesize = self.by_id["synthesize"]
        self.assertEqual(synthesize.condition_type, "AND")
        self.assertEqual(
            sorted(synthesize.trigger_methods),
            ["research_feasibility", "research_market", "research_sentiment"],
        )

    def test_the_three_branches_all_wait_on_the_same_router_branch(self) -> None:
        for node_id in (
            "research_market",
            "research_sentiment",
            "research_feasibility",
        ):
            with self.subTest(node=node_id):
                self.assertEqual(
                    self.by_id[node_id].trigger_methods, ["scope_approved"]
                )

    def test_routers_carry_every_branch_they_can_emit(self) -> None:
        self.assertEqual(
            sorted(self.by_id["route_scope"].router_events),
            ["scope_approved", "scope_revise"],
        )
        self.assertEqual(
            sorted(self.by_id["route_verdict"].router_events),
            ["verdict_approved", "verdict_revise"],
        )

    def test_only_routers_declare_router_events(self) -> None:
        for node in VALIDATOR_GRAPH.nodes:
            if node.router_events:
                with self.subTest(node=node.id):
                    self.assertEqual(node.flow_method_type, "router")

    def test_both_gates_re_enter_from_their_revise_partner(self) -> None:
        """The `or_()` that the revise loop depends on, as topology."""

        self.assertEqual(
            sorted(self.by_id["confirm_scope"].trigger_methods),
            ["revise_scope", "scope_idea"],
        )
        self.assertEqual(
            sorted(self.by_id["review_verdict"].trigger_methods),
            ["revise_verdict", "synthesize"],
        )


if __name__ == "__main__":
    unittest.main()
