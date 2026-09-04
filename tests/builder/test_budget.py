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
    node_model,
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
from brief_crew.config import (
    CHEAP_MODEL,
    ESCALATION_MODEL,
    MODEL_BY_ID,
)
from tests.builder.test_document import (
    agent_node,
    node as raw_node,
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


def authored_agent_node(
    node_id: str,
    *,
    model: str,
    tier: str = "cheap",
    max_iter: int = 2,
    guardrail_max_retries: int = 2,
) -> dict[str, Any]:
    """An agent the AUTHOR wrote, which is the only arm that NAMES a model.

    Deliberately the same retry and iteration ceilings `agent_node` uses, so the
    per-model documents below make the SAME number of calls as the library
    frontier and the only variable between them is the price of one token.
    """

    return raw_node(
        node_id,
        "agent",
        {
            "tier": tier,
            "max_iter": max_iter,
            "guardrail_max_retries": guardrail_max_retries,
            "role": "Analyst",
            "goal": "Find who already sells this",
            "backstory": "You have priced twenty categories and been wrong about three.",
            "task": {
                "description": "Research the market for ${state.idea}",
                "expected_output": "Three competitors with URLs",
            },
            "llm": {"model": model},
        },
    )


def authored_frontier(*, cheap: int, escalation: int, model: str) -> BuilderDocument:
    """`frontier_document`'s shape with every billable node NAMING one model.

    Same chain, same tools-priced call count, same cycle - so a difference in
    the total is a difference in the model's price and in nothing else.
    """

    ids = [f"a{index}" for index in range(cheap + escalation)]
    nodes: list[dict[str, Any]] = [input_node("idea")]
    nodes += [
        authored_agent_node(
            node_id, model=model, tier="cheap" if index < cheap else "escalation"
        )
        for index, node_id in enumerate(ids)
    ]
    edges = [edge("e_in", "idea", ids[0])]
    edges += [
        edge(f"e{index}", source, target)
        for index, (source, target) in enumerate(zip(ids, ids[1:]))
    ]
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
    nodes.append(output_node())
    return document(nodes, edges)


class PerModelPricingTests(unittest.TestCase):
    """Plan 05 criterion 6 and D6: a node is priced at ITS model, not its tier.

    Before this, every billable node was priced at one of two constants, which
    made the model picker a control with no effect on the meter beside it. The
    two documents here are byte-for-byte the same shape - same chain, same
    cycle, same 468 worst-case calls - and differ only in one string.

    THE FRONTIER USED HERE IS THE BOUND-DERIVED ONE, 13 billable and 8
    escalation, not the 8-node document `MeasuredFrontierTests` prices. That is
    deliberate and it is worth stating, because the criterion says "still
    refused" and the smaller document is NOT: at `deepseek-r1` prices the
    published 8-node frontier comes to $6.47, $8.08 with the margin, and is
    admitted. `MAX_BILLABLE_NODES` moved 8 -> 13 and `MAX_ESCALATION_NODES`
    5 -> 8 when the gallery hero errored on the first node a user added; the
    worst graph the counts now permit is the one that has to stay refused on
    price, and it is.
    """

    #: Measured at head 2026-09-04 by running this module's own functions.
    FRONTIER_CALLS = 468

    def frontier(self, model: str) -> BuilderDocument:
        return authored_frontier(
            cheap=MAX_BILLABLE_NODES - MAX_ESCALATION_NODES,
            escalation=MAX_ESCALATION_NODES,
            model=model,
        )

    def test_per_model_pricing(self) -> None:
        """Criterion 6, both halves, over one document shape.

        `deepseek/deepseek-r1` is $0.70/$2.50 and the roster's dearest input
        price; `qwen/qwen3.7-flash` is $0.03/$0.13 and its cheapest. The ratio
        of the two totals is the ratio of their prices, and the ceiling falls
        between them - which is the whole claim that a model choice moves the
        meter.
        """

        dear = estimate_budget(self.frontier("deepseek/deepseek-r1"))
        cheap = estimate_budget(self.frontier("qwen/qwen3.7-flash"))

        self.assertEqual(dear.modelled_calls, self.FRONTIER_CALLS)
        self.assertEqual(cheap.modelled_calls, self.FRONTIER_CALLS)
        self.assertEqual(dear.billable_nodes, MAX_BILLABLE_NODES)
        self.assertEqual(dear.escalation_nodes, MAX_ESCALATION_NODES)

        self.assertGreater(
            dear.static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN, MAX_RUN_COST_USD
        )
        self.assertLess(
            cheap.static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN, MAX_RUN_COST_USD
        )

        self.assertEqual(
            [problem.code for problem in budget_problems(self.frontier("deepseek/deepseek-r1"))],
            [budget_module.BUDGET_OVER_CEILING],
        )
        self.assertEqual(budget_problems(self.frontier("qwen/qwen3.7-flash")), [])

    def test_the_two_totals_are_in_the_ratio_of_the_two_prices(self) -> None:
        """The strongest available check that the model is what moved the number.

        Both documents make the same calls with the same prompt sizes, so the
        totals divide out to the price ratio exactly. A pricing path that read
        the TIER would give a ratio of 1.0 and this fails loudly rather than by
        a few cents.
        """

        dear = estimate_budget(self.frontier("deepseek/deepseek-r1")).floor_cost_usd
        cheap = estimate_budget(self.frontier("qwen/qwen3.7-flash")).floor_cost_usd
        r1 = MODEL_BY_ID["deepseek/deepseek-r1"]
        qwen = MODEL_BY_ID["qwen/qwen3.7-flash"]

        # One call's prompt/completion mix is fixed across the two documents, so
        # the ratio is a weighted mean of the two per-token ratios and sits
        # between them.
        self.assertGreater(dear / cheap, min(r1.cost_in / qwen.cost_in, r1.cost_out / qwen.cost_out) - 0.01)
        self.assertLess(dear / cheap, max(r1.cost_in / qwen.cost_in, r1.cost_out / qwen.cost_out) + 0.01)

    def test_a_plain_id_is_not_inflated_by_the_nitro_factor(self) -> None:
        """D5: the factor applies to a `:nitro` id and to nothing else.

        Applying 1.8 to a plain id would invent a number in both directions -
        the three OpenAI first-party rows spread 1.1x and `openai/gpt-oss-120b`
        spreads 9.5x - so a plain slug is priced at what it publishes.
        """

        estimate = estimate_budget(self.frontier("qwen/qwen3.7-flash"))
        self.assertAlmostEqual(estimate.static_cost_usd, estimate.floor_cost_usd, places=6)

    def test_a_library_node_is_still_priced_at_its_tier(self) -> None:
        """The other arm, unchanged: a library node has no model to name.

        Its LLMs are built inside the YAML crew from `config.py`'s constants, so
        the tier word is the whole of what the document gets to say - and
        pricing it any other way would price a model the run will not use.
        """

        graph = frontier_document(cheap=1, escalation=1)
        by_id = graph.nodes_by_id()
        self.assertEqual(node_model(by_id["a0"]), CHEAP_MODEL)
        self.assertEqual(node_model(by_id["a1"]), ESCALATION_MODEL)

    def test_an_authored_node_is_priced_at_the_model_it_names(self) -> None:
        graph = self.frontier("qwen/qwen3.7-flash")
        self.assertEqual(
            node_model(graph.nodes_by_id()["a0"]), "openrouter/qwen/qwen3.7-flash"
        )

    def test_the_nitro_factor_for_the_cheap_preset_is_the_measured_ratio(self) -> None:
        """1.8 is a MEASUREMENT for this one slug and a guess for every other.

        `google/gemini-3.5-flash-lite` is $0.30 headline and $0.54 on its two
        `priority` endpoints - 1.8 to the cent, measured 2026-09-04. That is
        where the constant came from, and it is why replacing the blanket factor
        with the per-model ratio left `MeasuredFrontierTests`' published figures
        untouched. Any other roster row would have moved them.
        """

        row = MODEL_BY_ID["google/gemini-3.5-flash-lite"]
        self.assertAlmostEqual(row.cost_in_max_endpoint / row.cost_in, NITRO_PRICE_FACTOR, places=6)
        self.assertAlmostEqual(
            budget_module._nitro_multiplier(CHEAP_MODEL), NITRO_PRICE_FACTOR, places=6
        )
        self.assertEqual(budget_module._nitro_multiplier(ESCALATION_MODEL), 1.0)


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
