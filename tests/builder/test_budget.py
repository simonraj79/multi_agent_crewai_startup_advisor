"""The static budget, checked against the measured frontier it was solved on.

The two figures this module is built around are not invented for the test. The
bound sweep that originally set MAX_BILLABLE_NODES = 8 reported, for a pure
chain with every node carrying tools, every node on a cycle and the escalation
nodes deepest:

    5 escalation + 3 cheap, loop 3   288 calls   $7.3625    74% of ceiling
    6 escalation + 4 cheap, loop 3   360 calls   $10.1404  101% - OVER

So the tests below build exactly those two documents and assert the module
reproduces both, to the cent. If a term of the model is ever changed - the seed
prompt, the per-call completion estimate, how depth is counted, what a cycle
multiplies - one of these fails, and the failure names a published number rather
than a fixture nobody can check.

One consequence was recorded here rather than smoothed over, and it has since
been acted on: with NITRO_PRICE_FACTOR applied, that same 8-node pathological
corner prices at $8.44, and $10.55 once the 1.25x margin is added - so the very
worst graph the counts permitted was ALREADY refused on price. The two figures
above are FLOOR prices and the enforced figure is the other one, which means
the count never was the money bound. It bound the cheap graph instead: a
9-node chain with no tools and no cycle prices at $0.99 and was refused anyway.
MAX_BILLABLE_NODES is 13 now and `config.py` carries the arithmetic. The
relationship the paragraph was always describing is unchanged and is what the
tests here assert: the layers are INDEPENDENT, and a graph is not legal because
it fits the counts, it is legal because it fits all of them.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from brief_crew.builder import (
    BuilderDocument,
    budget_problems,
    estimate_budget,
    node_call_count,
    static_cost_usd,
    structural_problems,
    validate_document,
)
from brief_crew.builder import budget as budget_module
from brief_crew.config import (
    GRAPH_STATIC_BUDGET_MARGIN,
    MAX_BILLABLE_NODES,
    MAX_CYCLE_ITERATIONS,
    MAX_ESCALATION_NODES,
    MAX_RUN_COST_USD,
    NITRO_PRICE_FACTOR,
)
from tests.builder.test_document import (
    agent_node,
    document,
    edge,
    input_node,
    output_node,
    router_node,
    transform_node,
    validator_shaped_document,
)

MARKET_TOOL = "research_market_landscape"

# The measured frontier, from the sweep that chose the node bounds. Published
# prices, no nitro inflation - which is why they are compared against
# `floor_cost_usd` and not against the enforced figure.
FRONTIER_CALLS = 288
FRONTIER_FLOOR_USD = 7.3625
OVER_CALLS = 360
OVER_FLOOR_USD = 10.1404


def frontier_document(*, cheap: int, escalation: int, cyclic: bool = True) -> BuilderDocument:
    """The worst shape the bounds permit: a chain, tooled, escalation deepest.

    Escalation nodes go LAST because a node's prompt is the seed plus every
    upstream billable node's output, so the deepest node is the most expensive
    one to retry - and putting the expensive tier there is the ordering that
    costs the most.
    """

    ids = [f"a{index}" for index in range(cheap + escalation)]
    nodes: list[dict[str, Any]] = [input_node("idea")]
    nodes += [
        agent_node(node_id, tier="cheap" if index < cheap else "escalation", tools=(MARKET_TOOL,))
        for index, node_id in enumerate(ids)
    ]
    edges = [edge("e_in", "idea", ids[0])]
    edges += [
        edge(f"e{index}", source, target)
        for index, (source, target) in enumerate(zip(ids, ids[1:]))
    ]

    if cyclic:
        nodes.append(
            router_node(
                "loop",
                branches=(
                    {"label": "again", "op": "otherwise"},
                    {"label": "done", "op": "gte", "key": "turns", "value": 3},
                ),
            )
        )
        edges.append(edge("e_last", ids[-1], "loop"))
        edges.append(edge("e_back", "loop", ids[0], source_port="again"))
        edges.append(edge("e_done", "loop", "report", source_port="done"))
    else:
        edges.append(edge("e_last", ids[-1], "report"))

    nodes.append(output_node())
    return document(nodes, edges)


class MeasuredFrontierTests(unittest.TestCase):
    """The published sweep, rebuilt as a document and priced by this module."""

    def test_eight_billable_nodes_price_at_the_published_frontier(self) -> None:
        graph = frontier_document(cheap=3, escalation=5)
        estimate = estimate_budget(graph)
        self.assertEqual(estimate.modelled_calls, FRONTIER_CALLS)
        self.assertAlmostEqual(estimate.floor_cost_usd, FRONTIER_FLOOR_USD, places=4)
        self.assertEqual(estimate.billable_nodes, 8)
        self.assertEqual(estimate.escalation_nodes, 5)
        self.assertEqual(estimate.cycles, 1)

    def test_that_same_document_is_structurally_legal(self) -> None:
        """It has to be, or the frontier would be pricing an unbuildable graph."""

        self.assertEqual(structural_problems(frontier_document(cheap=3, escalation=5)), [])

    def test_ten_billable_nodes_price_over_the_per_run_ceiling(self) -> None:
        estimate = estimate_budget(frontier_document(cheap=4, escalation=6))
        self.assertEqual(estimate.modelled_calls, OVER_CALLS)
        self.assertAlmostEqual(estimate.floor_cost_usd, OVER_FLOOR_USD, places=4)
        self.assertGreater(estimate.floor_cost_usd, MAX_RUN_COST_USD)

    def test_the_worst_graph_the_counts_permit_is_still_refused_on_price(self) -> None:
        """The two layers are independent, and this is what that means."""

        graph = frontier_document(cheap=3, escalation=5)
        self.assertEqual(structural_problems(graph), [])
        problems = budget_problems(graph, ceiling_usd=10.0)
        self.assertEqual([problem.code for problem in problems], [budget_module.BUDGET_OVER_CEILING])
        message = problems[0].message
        self.assertIn(str(FRONTIER_CALLS), message)
        self.assertIn("8.44", message)
        self.assertIn("10.55", message)


class CycleAndDepthTests(unittest.TestCase):
    def test_a_cycle_multiplies_exactly_the_nodes_inside_it(self) -> None:
        cyclic = estimate_budget(frontier_document(cheap=3, escalation=5))
        acyclic = estimate_budget(frontier_document(cheap=3, escalation=5, cyclic=False))
        self.assertEqual(cyclic.modelled_calls, acyclic.modelled_calls * (1 + MAX_CYCLE_ITERATIONS))
        self.assertAlmostEqual(
            cyclic.floor_cost_usd, acyclic.floor_cost_usd * (1 + MAX_CYCLE_ITERATIONS), places=6
        )

    def test_a_node_outside_the_loop_is_not_multiplied(self) -> None:
        """The validator shape loops only the two revise agents."""

        graph = validator_shaped_document()
        self.assertEqual(node_call_count(graph, "scope_idea"), 3)
        self.assertEqual(node_call_count(graph, "revise_scope"), 3 * (1 + MAX_CYCLE_ITERATIONS))

    def test_the_same_nodes_cost_more_in_a_chain_than_in_a_fan_out(self) -> None:
        wide = document(
            [input_node("idea"), agent_node("a"), agent_node("b"), output_node()],
            [
                edge("e1", "idea", "a"),
                edge("e2", "idea", "b"),
                edge("e3", "a", "report"),
                edge("e4", "b", "report"),
            ],
        )
        deep = document(
            [input_node("idea"), agent_node("a"), agent_node("b"), output_node()],
            [
                edge("e1", "idea", "a"),
                edge("e2", "a", "b"),
                edge("e3", "b", "report"),
            ],
        )
        self.assertEqual(estimate_budget(wide).modelled_calls, estimate_budget(deep).modelled_calls)
        self.assertGreater(static_cost_usd(deep), static_cost_usd(wide))

    def test_a_transform_between_two_agents_adds_no_depth(self) -> None:
        with_transform = document(
            [input_node("idea"), agent_node("a"), transform_node("t"), agent_node("b"), output_node()],
            [
                edge("e1", "idea", "a"),
                edge("e2", "a", "t"),
                edge("e3", "t", "b"),
                edge("e4", "b", "report"),
            ],
        )
        without = document(
            [input_node("idea"), agent_node("a"), agent_node("b"), output_node()],
            [edge("e1", "idea", "a"), edge("e2", "a", "b"), edge("e3", "b", "report")],
        )
        self.assertAlmostEqual(static_cost_usd(with_transform), static_cost_usd(without))


class CallCountTests(unittest.TestCase):
    def test_an_agent_with_no_tools_makes_one_call_per_guardrail_attempt(self) -> None:
        graph = document(
            [input_node("idea"), agent_node("a", tools=()), output_node()],
            [edge("e1", "idea", "a"), edge("e2", "a", "report")],
        )
        self.assertEqual(node_call_count(graph, "a"), 3)

    def test_binding_a_tool_multiplies_by_the_agents_own_iteration_ceiling(self) -> None:
        graph = document(
            [input_node("idea"), agent_node("a", tools=(MARKET_TOOL,), max_iter=4), output_node()],
            [edge("e1", "idea", "a"), edge("e2", "a", "report")],
        )
        self.assertEqual(node_call_count(graph, "a"), 3 * 5)

    def test_lowering_the_guardrail_ceiling_lowers_the_price(self) -> None:
        graph = document(
            [input_node("idea"), agent_node("a", tools=(MARKET_TOOL,), guardrail_max_retries=0), output_node()],
            [edge("e1", "idea", "a"), edge("e2", "a", "report")],
        )
        self.assertEqual(node_call_count(graph, "a"), 3)

    def test_a_crew_is_priced_as_tool_using_whatever_it_declares(self) -> None:
        graph = document(
            [
                input_node("idea"),
                {
                    "id": "sweep",
                    "kind": "crew",
                    "label": "Sweep",
                    "config": {"crew_id": "sweep", "tier": "cheap", "max_iter": 2},
                },
                output_node(),
            ],
            [edge("e1", "idea", "sweep"), edge("e2", "sweep", "report")],
        )
        self.assertEqual(node_call_count(graph, "sweep"), 3 * 3)

    def test_a_node_that_calls_no_model_costs_nothing(self) -> None:
        graph = document(
            [input_node("idea"), transform_node("t"), output_node()],
            [edge("e1", "idea", "t"), edge("e2", "t", "report")],
        )
        self.assertEqual(node_call_count(graph, "t"), 0)
        self.assertEqual(node_call_count(graph, "absent"), 0)
        estimate = estimate_budget(graph)
        self.assertEqual(estimate.static_cost_usd, 0.0)
        self.assertEqual(estimate.billable_nodes, 0)


class NitroFactorTests(unittest.TestCase):
    """The interim answer to `:nitro` pricing on speed rather than price."""

    def _single(self, tier: str) -> BuilderDocument:
        return document(
            [input_node("idea"), agent_node("a", tier=tier, tools=(MARKET_TOOL,)), output_node()],
            [edge("e1", "idea", "a"), edge("e2", "a", "report")],
        )

    def test_the_cheap_tier_is_inflated_by_the_factor(self) -> None:
        estimate = estimate_budget(self._single("cheap"))
        self.assertAlmostEqual(
            estimate.static_cost_usd, estimate.floor_cost_usd * NITRO_PRICE_FACTOR, places=9
        )

    def test_the_escalation_tier_is_not(self) -> None:
        estimate = estimate_budget(self._single("escalation"))
        self.assertAlmostEqual(estimate.static_cost_usd, estimate.floor_cost_usd, places=9)

    def test_the_enforced_figure_is_never_below_the_published_floor(self) -> None:
        estimate = estimate_budget(frontier_document(cheap=3, escalation=5))
        self.assertGreater(estimate.static_cost_usd, estimate.floor_cost_usd)


class CeilingTests(unittest.TestCase):
    def _required(self, graph: BuilderDocument) -> float:
        return estimate_budget(graph).static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN

    def test_a_ceiling_exactly_at_the_required_figure_is_accepted(self) -> None:
        graph = validator_shaped_document()
        self.assertEqual(budget_problems(graph, ceiling_usd=self._required(graph)), [])

    def test_a_ceiling_one_cent_below_it_is_refused(self) -> None:
        graph = validator_shaped_document()
        problems = budget_problems(graph, ceiling_usd=self._required(graph) - 0.01)
        self.assertEqual([problem.code for problem in problems], [budget_module.BUDGET_OVER_CEILING])
        self.assertEqual(problems[0].severity, "error")

    def test_a_ceiling_the_estimate_fits_but_the_margin_does_not_is_refused(self) -> None:
        """The 1.25x is the whole difference between these two assertions."""

        graph = validator_shaped_document()
        estimate = estimate_budget(graph)
        self.assertNotEqual(budget_problems(graph, ceiling_usd=estimate.static_cost_usd), [])
        self.assertEqual(
            budget_problems(graph, ceiling_usd=estimate.static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN),
            [],
        )

    def test_a_zero_ceiling_disables_the_check_the_way_the_env_knob_does(self) -> None:
        self.assertEqual(budget_problems(frontier_document(cheap=4, escalation=6), ceiling_usd=0), [])

    def test_the_default_ceiling_is_the_services_own(self) -> None:
        graph = frontier_document(cheap=4, escalation=6)
        with patch.object(budget_module, "MAX_RUN_COST_USD", 10.0):
            self.assertNotEqual(budget_problems(graph), [])
        with patch.object(budget_module, "MAX_RUN_COST_USD", 10_000.0):
            self.assertEqual(budget_problems(graph), [])


class UnpricedModelTests(unittest.TestCase):
    """"No price on file" and "this call was free" are different facts."""

    def test_an_unpriceable_graph_is_refused_rather_than_priced_at_zero(self) -> None:
        graph = frontier_document(cheap=3, escalation=5)
        with patch.object(budget_module, "compute_cost_usd", return_value=None):
            estimate = estimate_budget(graph)
            problems = budget_problems(graph, ceiling_usd=10.0)

        self.assertEqual(estimate.static_cost_usd, 0.0)
        self.assertEqual(len(estimate.unpriced_models), 2)
        self.assertEqual(
            [problem.code for problem in problems], [budget_module.BUDGET_UNPRICED_MODEL]
        )
        self.assertIn("bound spend", problems[0].message)

    def test_a_disabled_ceiling_does_not_excuse_an_unpriceable_graph(self) -> None:
        graph = frontier_document(cheap=3, escalation=5)
        with patch.object(budget_module, "compute_cost_usd", return_value=None):
            problems = budget_problems(graph, ceiling_usd=0)
        self.assertEqual(
            [problem.code for problem in problems], [budget_module.BUDGET_UNPRICED_MODEL]
        )

    def test_the_call_count_is_unaffected_by_a_missing_price(self) -> None:
        """The graph still runs; what is missing is the ability to price it."""

        graph = frontier_document(cheap=3, escalation=5)
        with patch.object(budget_module, "compute_cost_usd", return_value=None):
            self.assertEqual(estimate_budget(graph).modelled_calls, FRONTIER_CALLS)


class BudgetBlockTests(unittest.TestCase):
    def test_as_budget_writes_the_block_the_document_carries(self) -> None:
        graph = validator_shaped_document()
        estimate = estimate_budget(graph)
        stamped = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        block = estimate.as_budget(compiled_at=stamped)

        self.assertAlmostEqual(block.static_cost_usd, estimate.static_cost_usd)
        self.assertEqual(block.billable_nodes, 8)
        self.assertEqual(block.escalation_nodes, 5)
        self.assertEqual(block.cycles, 2)
        self.assertEqual(block.compiled_at, stamped)

    def test_the_block_round_trips_onto_a_document(self) -> None:
        graph = validator_shaped_document()
        payload = graph.model_dump(mode="json", by_alias=True)
        payload["budget"] = estimate_budget(graph).as_budget().model_dump(mode="json")
        rebuilt = BuilderDocument.model_validate(payload)
        assert rebuilt.budget is not None
        self.assertEqual(rebuilt.budget.billable_nodes, 8)


class ValidateDocumentTests(unittest.TestCase):
    def test_the_validator_shaped_document_passes_structure_and_price(self) -> None:
        self.assertEqual(validate_document(validator_shaped_document(), ceiling_usd=10.0), [])

    def test_the_validator_shape_prices_well_under_the_ceiling(self) -> None:
        estimate = estimate_budget(validator_shaped_document())
        self.assertLess(estimate.static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN, 10.0)
        self.assertEqual(estimate.modelled_calls, 60)

    def test_structure_is_reported_before_price(self) -> None:
        # Sized off the bound rather than written as a literal: this used to be
        # a 10-node document, which stopped tripping `billable-count` the day
        # MAX_BILLABLE_NODES was raised to 13 - and the test then failed on a
        # missing code rather than on the ordering it is about.
        graph = frontier_document(
            cheap=MAX_BILLABLE_NODES + 1 - MAX_ESCALATION_NODES,
            escalation=MAX_ESCALATION_NODES,
        )
        problems = validate_document(graph, ceiling_usd=10.0)
        codes = [problem.code for problem in problems]
        self.assertIn("billable-count", codes)
        self.assertIn(budget_module.BUDGET_OVER_CEILING, codes)
        self.assertLess(codes.index("billable-count"), codes.index(budget_module.BUDGET_OVER_CEILING))

    def test_pricing_a_broken_document_reports_rather_than_raising(self) -> None:
        graph = document(
            [agent_node("orphan")],
            [edge("e1", "orphan", "nowhere")],
        )
        estimate = estimate_budget(graph)
        self.assertEqual(estimate.billable_nodes, 1)
        self.assertGreater(estimate.static_cost_usd, 0.0)
        self.assertTrue(validate_document(graph, ceiling_usd=10.0))


if __name__ == "__main__":
    unittest.main()
