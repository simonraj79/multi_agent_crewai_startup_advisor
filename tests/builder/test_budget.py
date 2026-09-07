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
been acted on: with the endpoint inflation applied, that same 8-node
pathological corner prices at $13.25, and $16.57 once the 1.25x margin is
added - so the very worst graph the counts permitted was ALREADY refused on
price. The two figures above are FLOOR prices and the enforced figure is the
other one, which means the count never was the money bound. It bound the cheap
graph instead: a 9-node chain with no tools and no cycle prices at $0.99 and
was refused anyway. MAX_BILLABLE_NODES is 13 now and `config.py` carries the
arithmetic. The relationship the paragraph was always describing is unchanged
and is what the tests here assert: the layers are INDEPENDENT, and a graph is
not legal because it fits the counts, it is legal because it fits all of them.

EVERY ENFORCED FIGURE ON THIS PAGE MOVED WITH AUDIT M14, and each one says so
where it sits. $8.44 became $13.25 because the inflation stopped being a
`:nitro` special case: this project states `provider.max_price` and
deliberately no `provider.sort`, so any endpoint under the ceiling may serve
any slug, and every model is now priced at the registry's own measured
`cost_in_max_endpoint / cost_in`. The two FLOOR figures above did NOT move,
and that is the check worth naming - M14 changed what is enforced, not how a
graph is counted or what its published price is.
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
from brief_crew.builder.bounds import back_edges, cycle_multiplier
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
    MODEL_REGISTRY,
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

    def test_a_slug_served_at_one_price_is_not_inflated(self) -> None:
        """AMENDED BY AUDIT M14: the figure did not move, the REASON did.

        This read `test_a_plain_id_is_not_inflated_by_the_nitro_factor` and
        asserted that being a PLAIN id was what left the total at its headline.
        It passed for the wrong reason. `qwen/qwen3.7-flash` publishes $0.03/M
        and its dearest endpoint is also $0.03/M, so its measured spread is
        1.0x and it is unchanged under either rule - while its own docstring
        cited `openai/gpt-oss-120b` at 9.5x as the reason not to inflate a
        plain slug, which is the row that proves the opposite.

        What the document here can support is the narrow claim: a slug with one
        price has nothing to inflate. `EndpointSpreadTests` below carries the
        general rule and the 9.5x row that tells the two rules apart.
        """

        row = MODEL_BY_ID["qwen/qwen3.7-flash"]
        self.assertEqual(row.cost_in_max_endpoint, row.cost_in)
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

    def test_both_presets_are_priced_at_their_own_measured_ratio(self) -> None:
        """1.8 is a MEASUREMENT for two slugs and a guess for every other.

        `google/gemini-3.5-flash-lite` is $0.30 headline and $0.54 on its two
        `priority` endpoints - 1.8 to the cent, measured 2026-09-04 - and
        `google/gemini-3.8-flash` spreads $0.75 to $1.35, which is also 1.8.
        That coincidence is where NITRO_PRICE_FACTOR came from, and it is why
        the cheap preset's own figures never moved when the blanket factor was
        replaced by the per-model ratio.

        AMENDED BY AUDIT M14. The last line asserted the ESCALATION preset sat
        at 1.0 because it carries no `:nitro` suffix. That was the finding: the
        suffix is not what decides which endpoint serves a request -
        `provider.max_price` with no pinned endpoint is - so the escalation
        preset now answers its own measured 1.8, exactly as the cheap one
        always did.
        """

        cheap_row = MODEL_BY_ID["google/gemini-3.5-flash-lite"]
        dear_row = MODEL_BY_ID["google/gemini-3.8-flash"]
        self.assertAlmostEqual(
            cheap_row.cost_in_max_endpoint / cheap_row.cost_in, NITRO_PRICE_FACTOR, places=6
        )
        self.assertAlmostEqual(
            budget_module._endpoint_multiplier(CHEAP_MODEL), NITRO_PRICE_FACTOR, places=6
        )
        self.assertAlmostEqual(
            budget_module._endpoint_multiplier(ESCALATION_MODEL),
            dear_row.cost_in_max_endpoint / dear_row.cost_in,
            places=6,
        )


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
        # $8.44 / $10.55 until audit M14. The graph's FLOOR is unchanged at
        # $7.3625 and its call count is unchanged at 288; what moved is that
        # its five escalation nodes are now inflated by their own measured 1.8x
        # endpoint spread instead of by 1.0. It was refused before and it is
        # refused now, which is what this test is about - the arithmetic below
        # is pinned so the refusal cannot start quoting a stale figure.
        self.assertIn("13.25", message)
        self.assertIn("16.57", message)


class CycleAndDepthTests(unittest.TestCase):
    def test_a_cycle_multiplies_exactly_the_nodes_inside_it(self) -> None:
        cyclic = estimate_budget(frontier_document(cheap=3, escalation=5))
        acyclic = estimate_budget(frontier_document(cheap=3, escalation=5, cyclic=False))
        self.assertEqual(cyclic.modelled_calls, acyclic.modelled_calls * (1 + MAX_CYCLE_ITERATIONS))
        self.assertAlmostEqual(
            cyclic.floor_cost_usd, acyclic.floor_cost_usd * (1 + MAX_CYCLE_ITERATIONS), places=6
        )

    def test_a_node_outside_the_loop_is_not_multiplied(self) -> None:
        """The validator shape loops only the two revise agents.

        The multiplier is `cycle_multiplier(len(back_edges))` and this document
        closes TWO loops, so a node on either of them is priced at 4 ** 2 = 16
        passes rather than at 4. It read 4 until audit M8, while the backstop
        `compiler._Plan.max_method_calls` compiles for the same document has
        always been 16 - the meter and the runtime describing different graphs.
        """

        graph = validator_shaped_document()
        self.assertEqual(len(back_edges(graph)), 2)
        self.assertEqual(node_call_count(graph, "scope_idea"), 3)
        self.assertEqual(
            node_call_count(graph, "revise_scope"), 3 * cycle_multiplier(2)
        )
        self.assertEqual(node_call_count(graph, "revise_scope"), 48)

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


class TierInflationTests(unittest.TestCase):
    """What each library tier is ENFORCED at, above its published headline.

    `NitroFactorTests` until audit M14, when the answer stopped depending on
    which of the two presets carries a `:nitro` suffix. Both are priced at
    their own registry-measured endpoint spread now, and both spreads are 1.8 -
    so the cheap arm below is unchanged to ten decimal places and the
    escalation arm is the one the finding moved.
    """

    def _single(self, tier: str) -> BuilderDocument:
        return document(
            [input_node("idea"), agent_node("a", tier=tier, tools=(MARKET_TOOL,)), output_node()],
            [edge("e1", "idea", "a"), edge("e2", "a", "report")],
        )

    def _spread(self, model_id: str) -> float:
        row = MODEL_BY_ID[model_id]
        return row.cost_in_max_endpoint / row.cost_in

    def test_the_cheap_tier_is_inflated_by_its_measured_spread(self) -> None:
        estimate = estimate_budget(self._single("cheap"))
        self.assertAlmostEqual(
            estimate.static_cost_usd,
            estimate.floor_cost_usd * self._spread("google/gemini-3.5-flash-lite"),
            places=9,
        )

    def test_the_escalation_tier_is_too(self) -> None:
        """`test_the_escalation_tier_is_not` until audit M14 - it now IS.

        The escalation preset is a plain slug and was left at its headline, on
        the reading that only `:nitro` routes away from the published price.
        `openrouter_escalation_params` sends `provider.max_price` and a
        throughput `sort` and pins no endpoint, so a $1.35/M endpoint may serve
        it - and an estimate that is not an upper bound is not a bound.
        """

        estimate = estimate_budget(self._single("escalation"))
        self.assertAlmostEqual(
            estimate.static_cost_usd,
            estimate.floor_cost_usd * self._spread("google/gemini-3.8-flash"),
            places=9,
        )
        self.assertGreater(estimate.static_cost_usd, estimate.floor_cost_usd)

    def test_the_enforced_figure_is_never_below_the_published_floor(self) -> None:
        estimate = estimate_budget(frontier_document(cheap=3, escalation=5))
        self.assertGreater(estimate.static_cost_usd, estimate.floor_cost_usd)


class EndpointSpreadTests(unittest.TestCase):
    """Audit M14: EVERY model is priced at the dearest endpoint serving it.

    THE DEFECT. `budget._nitro_multiplier` inflated a `:nitro` slug by the
    registry's measured endpoint spread and returned 1.0 for every other
    spelling, on the stated reading that "a plain slug is not routed on speed,
    so its headline is what it bills". The request this project actually sends
    says otherwise: `config.openrouter_authored_params` states
    `provider.max_price` and DELIBERATELY no `provider.sort`, so OpenRouter may
    serve an authored node's plain slug from ANY endpoint under the $1.00/M
    ceiling. `openai/gpt-oss-120b` publishes $0.037/M and its dearest endpoint
    is $0.350/M - 9.5x - so a graph of those nodes was admitted against a ninth
    of what it could bill. An estimate that is not an upper bound is not a
    bound, which is the same failure as the run reported at $0.00 over 128,069
    genuinely billed tokens.

    THE FOUR TESTS BELOW ARE THE FINDING, ITS CONTROL, ITS RULE AND ITS
    CONSEQUENCE - in that order, and each names what it read before the fix.
    """

    #: The roster's widest spread, 9.5x, and the finding's own evidence.
    WIDE_SPREAD_MODEL = "openai/gpt-oss-120b"
    #: A slug served at ONE price, 1.0x - the control that must not move.
    FLAT_MODEL = "qwen/qwen3.7-flash"

    def _spread(self, model_id: str) -> float:
        row = MODEL_BY_ID[model_id]
        return row.cost_in_max_endpoint / row.cost_in

    def test_M14_a_plain_slug_is_priced_at_its_dearest_endpoint(self) -> None:
        """The finding. A plain id with a wide spread is now inflated by it.

        FAILS on the unfixed module: `_nitro_multiplier` answered 1.0 for any
        spelling without a `:nitro` suffix, so `static_cost_usd` equalled
        `floor_cost_usd` here and the enforced figure was $0.0072 against a
        graph that could bill $0.0679 - the same 9.4595x the registry records
        between this row's headline and its dearest endpoint.
        """

        spread = self._spread(self.WIDE_SPREAD_MODEL)
        self.assertGreater(
            spread, 9.0, "the roster row this test rests on has been re-measured"
        )

        estimate = estimate_budget(one_authored_agent(llm={"model": self.WIDE_SPREAD_MODEL}))
        self.assertAlmostEqual(
            estimate.static_cost_usd, estimate.floor_cost_usd * spread, places=12
        )
        # To the cent, and past it, because a single agent is cents. The floor
        # is what this document cost before M14 AND after it - only the
        # enforced figure moved.
        self.assertAlmostEqual(estimate.floor_cost_usd, 0.00717309, places=8)
        self.assertAlmostEqual(estimate.static_cost_usd, 0.06785355, places=8)

    def test_M14_a_slug_whose_two_figures_are_equal_is_unchanged(self) -> None:
        """The control. A model with one endpoint price has nothing to inflate.

        Passes before and after, and that is the point: the fix must not be a
        blanket multiplier wearing a new name. `qwen/qwen3.7-flash` publishes
        $0.03/M, its dearest endpoint is $0.03/M, and its enforced figure is
        still its floor to twelve places.
        """

        row = MODEL_BY_ID[self.FLAT_MODEL]
        self.assertEqual(row.cost_in_max_endpoint, row.cost_in)
        self.assertEqual(
            budget_module._endpoint_multiplier(f"openrouter/{self.FLAT_MODEL}"), 1.0
        )

        estimate = estimate_budget(one_authored_agent(llm={"model": self.FLAT_MODEL}))
        self.assertGreater(estimate.floor_cost_usd, 0.0)
        self.assertAlmostEqual(estimate.static_cost_usd, estimate.floor_cost_usd, places=12)

    def test_M14_every_roster_row_answers_its_own_measured_ratio(self) -> None:
        """The rule, over the whole roster and all four spellings of each id.

        The ratios run 1.0x to 9.5x across ten rows, which is why one constant
        was wrong for nine of them in one direction or the other. All four
        spellings answer alike because `registry_model` strips the provider
        prefix and the routing variant: a `:nitro` id and its plain form name
        ONE slug with ONE set of endpoints.

        FAILS on the unfixed module for every row: the two prefix spellings
        answered 1.0 rather than the row's ratio, and the two `:nitro`
        spellings answered `max(ratio, NITRO_PRICE_FACTOR)` rather than the
        ratio - which is a different number for the six rows under 1.8.
        """

        self.assertGreaterEqual(len(MODEL_REGISTRY), 2)
        for row in MODEL_REGISTRY:
            expected = row.cost_in_max_endpoint / row.cost_in
            for spelling in (
                row.id,
                f"openrouter/{row.id}",
                f"{row.id}:nitro",
                f"openrouter/{row.id}:nitro",
            ):
                with self.subTest(spelling=spelling):
                    self.assertAlmostEqual(
                        budget_module._endpoint_multiplier(spelling), expected, places=12
                    )

    def test_M14_a_graph_the_old_estimate_admitted_is_refused_now(self) -> None:
        """The consequence, in the one currency admission actually speaks.

        Six library agents on the escalation tier, chained, tooled, on one
        cycle - 216 calls, 6 billable, 6 escalation, structurally legal under
        every count. Its published floor is $5.4914 and has not moved. Before
        M14 that floor WAS the enforced figure, because the escalation preset
        is a plain slug and was multiplied by 1.0: $6.86 with the 1.25x margin,
        comfortably admitted under the $10.00 ceiling. Priced at the $1.35/M
        dearest endpoint the registry records for `google/gemini-3.8-flash` it
        is $9.8845, $12.36 with the margin, and refused.

        Nothing about the graph changed. What changed is that the number
        admission compares to the ceiling is now an upper bound on what the
        graph can bill.
        """

        graph = frontier_document(cheap=0, escalation=6)
        self.assertEqual(structural_problems(graph), [])

        estimate = estimate_budget(graph)
        self.assertEqual(estimate.modelled_calls, 216)
        self.assertEqual(estimate.billable_nodes, 6)
        self.assertEqual(estimate.escalation_nodes, 6)
        self.assertAlmostEqual(estimate.floor_cost_usd, 5.4914, places=4)
        self.assertAlmostEqual(estimate.static_cost_usd, 9.8845, places=4)

        # The floor - which is what this graph was enforced against before M14
        # - fits the ceiling with the margin; the enforced figure does not.
        self.assertLess(
            estimate.floor_cost_usd * GRAPH_STATIC_BUDGET_MARGIN, MAX_RUN_COST_USD
        )
        self.assertGreater(
            estimate.static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN, MAX_RUN_COST_USD
        )
        self.assertEqual(
            [problem.code for problem in budget_problems(graph, ceiling_usd=10.0)],
            [budget_module.BUDGET_OVER_CEILING],
        )


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
        """60 until audit M8, and 132 because the shape closes TWO loops.

        Six of its eight billable nodes sit outside both loops and are
        unchanged; the two revise agents went from 4 passes each to 16, which
        is 2 x 3 x (16 - 4) = 72 calls more. It is still well inside the
        ceiling - $5.09, $6.37 with the margin - which is the point: the
        correction costs the shipped shape nothing and closes the gate on the
        shape that was exploiting it.

        $3.34 / $4.18 until audit M14, over the same 132 calls. Five of its
        eight billable nodes run on the escalation preset, which used to be
        priced at its $0.75/M headline and is now priced at the $1.35/M dearest
        endpoint the registry records for it. The floor is $2.83 and did not
        move.
        """

        estimate = estimate_budget(validator_shaped_document())
        self.assertLess(estimate.static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN, 10.0)
        self.assertEqual(estimate.modelled_calls, 132)

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




# --------------------------------------------------------------------------
# 09 D4 - what retry, a crew's membership and a fallback do to the price
# --------------------------------------------------------------------------
AUTHORED_MODEL = "google/gemini-3.8-flash"
CHEAPER_MODEL = "google/gemini-3.5-flash-lite"


def authored_agent(node_id: str, **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "role": f"{node_id} specialist",
        "goal": "do the work",
        "backstory": "years of it",
        "task": {"description": "work", "expected_output": "a paragraph"},
        "llm": {"model": AUTHORED_MODEL},
        "tier": "cheap",
    }
    config.update(overrides)
    return {"id": node_id, "kind": "agent", "label": node_id, "config": config}


def one_authored_agent(**overrides: Any) -> BuilderDocument:
    return document(
        [
            input_node("idea"),
            authored_agent("draft", **overrides),
            raw_node("report", "output", {"body_key": "markdown_body", "source": "${state.out__draft}"}),
        ],
        [edge("e1", "idea", "draft"), edge("e2", "draft", "report")],
    )


def authored_crew(
    *,
    process: str,
    members: int,
    member_config: dict[str, Any] | None = None,
    **overrides: Any,
) -> BuilderDocument:
    """A crew and its members. `member_config` is what each MEMBER declares.

    Parameterised for audit M7: until it was fixed, an authored crew was priced
    at the crew's own `max_iter` times a member COUNT, so every test here held
    with members that happened to share the crew's ceilings and none of them
    could see the field the runtime discards. A member that differs is the only
    shape that tells the two arithmetics apart.
    """

    member_ids = [f"m{index}" for index in range(members)]
    config: dict[str, Any] = {
        "process": process,
        "tier": "cheap",
        "task_order": tuple(member_ids),
    }
    if process == "hierarchical":
        config["manager_llm"] = {"model": AUTHORED_MODEL}
    config.update(overrides)
    return document(
        [
            input_node("idea"),
            {"id": "team", "kind": "crew", "label": "team", "config": config},
            *[
                authored_agent(member_id, **(member_config or {}))
                for member_id in member_ids
            ],
            raw_node("report", "output", {"body_key": "markdown_body", "source": "${state.out__team}"}),
        ],
        [
            edge("e1", "idea", "team"),
            edge("e2", "team", "report"),
            *[
                {
                    "id": f"m{index}",
                    "source": member_id,
                    "source_port": "out",
                    "target": "team",
                    "target_port": "member",
                }
                for index, member_id in enumerate(member_ids)
            ],
        ],
    )


class RetryPricingTests(unittest.TestCase):
    """09 D4: a whole-node retry multiplies everything below it."""

    def test_two_retries_price_three_times_the_calls(self) -> None:
        once = estimate_budget(one_authored_agent()).modelled_calls
        thrice = estimate_budget(
            one_authored_agent(retry={"max_retries": 2, "backoff_seconds": 0})
        ).modelled_calls
        self.assertEqual(thrice, once * 3)

    def test_the_multiplier_is_visible_per_node(self) -> None:
        estimate = estimate_budget(
            one_authored_agent(retry={"max_retries": 2, "backoff_seconds": 0})
        )
        plain = estimate_budget(one_authored_agent())
        self.assertEqual(estimate.per_node["draft"].calls, plain.per_node["draft"].calls * 3)
        self.assertGreater(estimate.per_node["draft"].usd, plain.per_node["draft"].usd)

    def test_a_fallback_is_priced_at_the_dearer_of_the_two(self) -> None:
        """A fallback is what the LAST attempt uses, so it can be what it costs.

        Pricing it at the cheap model it usually runs on would under-price
        exactly the node whose author expected it to fail - which is the shape
        of the defect that reported 128,069 real tokens at $0.00.
        """

        cheap_named = one_authored_agent(llm={"model": CHEAPER_MODEL})
        with_dear_fallback = one_authored_agent(
            llm={"model": CHEAPER_MODEL},
            retry={"max_retries": 1, "fallback_model": AUTHORED_MODEL},
        )
        self.assertEqual(
            estimate_budget(with_dear_fallback).per_node["draft"].model,
            f"openrouter/{AUTHORED_MODEL}",
        )
        self.assertEqual(
            estimate_budget(cheap_named).per_node["draft"].model,
            f"openrouter/{CHEAPER_MODEL}",
        )

    def test_a_cheaper_fallback_does_not_lower_the_price(self) -> None:
        dear_named = one_authored_agent(
            llm={"model": AUTHORED_MODEL},
            retry={"max_retries": 1, "fallback_model": CHEAPER_MODEL},
        )
        self.assertEqual(
            estimate_budget(dear_named).per_node["draft"].model,
            f"openrouter/{AUTHORED_MODEL}",
        )


class CrewMembershipPricingTests(unittest.TestCase):
    """An authored crew runs one task per member, and a manager delegates each."""

    def test_a_sequential_crew_prices_one_task_per_member(self) -> None:
        one = estimate_budget(authored_crew(process="sequential", members=1))
        three = estimate_budget(authored_crew(process="sequential", members=3))
        self.assertEqual(three.per_node["team"].calls, one.per_node["team"].calls * 3)

    def test_a_hierarchical_crew_of_three_prices_three_manager_calls(self) -> None:
        sequential = estimate_budget(authored_crew(process="sequential", members=3))
        hierarchical = estimate_budget(authored_crew(process="hierarchical", members=3))
        self.assertEqual(
            hierarchical.per_node["team"].calls - sequential.per_node["team"].calls,
            3,
            "a hierarchical manager makes one call per task it delegates",
        )

    def test_a_member_agent_is_not_billed_twice(self) -> None:
        """It bills INSIDE its crew; counting it again would charge it twice."""

        estimate = estimate_budget(authored_crew(process="sequential", members=3))
        self.assertEqual(estimate.billable_nodes, 1)
        self.assertEqual(sorted(estimate.per_node), ["team"])


class CrewIsPricedAtItsMembersTests(unittest.TestCase):
    """Audit M7: a crew bills for its MEMBERS, at each member's own numbers.

    `runtime.authored_crew` builds one `Agent(max_iter=member.max_iter)` and one
    `Task(guardrail_max_retries=member.guardrail_max_retries)` per member, and
    hands `Crew(...)` NEITHER of the crew node's own two numbers. The estimate
    priced the crew's `max_iter` times a member count, which is the one field
    the runtime throws away - and it priced every member at the crew's TIER
    preset rather than at the model each one names, so an escalation team drawn
    inside a `tier: cheap` crew counted as zero escalation nodes.
    """

    def poc(self) -> BuilderDocument:
        """The audit's proof of concept, verbatim.

        Sequential, `tier: cheap`, `max_iter: 1`; six members at `max_iter: 8`
        on the escalation model. Before the fix this metered 12 calls and 0
        escalation nodes; the runtime makes 54, every one of them escalation.
        """

        return authored_crew(
            process="sequential",
            members=6,
            max_iter=1,
            guardrail_max_retries=0,
            member_config={
                "tier": "escalation",
                "max_iter": 8,
                "guardrail_max_retries": 0,
                "llm": {"model": ESCALATION_MODEL.split("openrouter/", 1)[-1]},
            },
        )

    def test_the_proof_of_concept_prices_the_members_calls(self) -> None:
        estimate = estimate_budget(self.poc())
        # 6 members x (0 guardrail retries + 1 attempt) x (max_iter 8 + 1). The
        # crew's own max_iter 1 appears nowhere, because Crew() never receives
        # it. Before the fix: 1 attempt x (1 + 1) x 6 members = 12.
        self.assertEqual(estimate.modelled_calls, 54)
        self.assertEqual(estimate.per_node["team"].calls, 54)

    def test_the_proof_of_concept_counts_an_escalation_node(self) -> None:
        estimate = estimate_budget(self.poc())
        self.assertEqual(estimate.escalation_nodes, 1)
        self.assertEqual(
            estimate.per_node["team"].model,
            ESCALATION_MODEL,
            "the members' model is what the crew's calls are billed at",
        )

    def test_the_escalation_ceiling_sees_the_members(self) -> None:
        """MAX_ESCALATION_NODES was derived from a list that dropped them."""

        # Six escalation members against a ceiling of 8: under it, so the
        # audit's own document is not refused here - the count including them
        # is what the next document proves, by crossing the ceiling with
        # members alone.
        self.assertEqual(
            [
                problem.code
                for problem in structural_problems(self.poc())
                if problem.code == "escalation-count"
            ],
            [],
        )
        crowded = authored_crew(
            process="sequential",
            members=MAX_ESCALATION_NODES + 1,
            member_config={"tier": "escalation"},
        )
        self.assertIn(
            "escalation-count",
            [problem.code for problem in structural_problems(crowded)],
        )

    def test_a_members_own_max_iter_moves_the_price(self) -> None:
        lean = estimate_budget(
            authored_crew(process="sequential", members=2, member_config={"max_iter": 1})
        )
        greedy = estimate_budget(
            authored_crew(process="sequential", members=2, member_config={"max_iter": 3})
        )
        # BUILDER_MAX_AGENT_ITER is the ceiling on both: 1 -> 2 calls an
        # attempt, 3 -> 4, so the members' own field doubles the crew's price.
        self.assertEqual(greedy.per_node["team"].calls, lean.per_node["team"].calls * 2)

    def test_the_crews_own_max_iter_moves_nothing(self) -> None:
        """It configures nothing at run time, so it must price nothing."""

        one = estimate_budget(authored_crew(process="sequential", members=2, max_iter=1))
        eight = estimate_budget(authored_crew(process="sequential", members=2, max_iter=8))
        self.assertEqual(one.modelled_calls, eight.modelled_calls)

    def test_the_crew_warns_that_its_own_ceilings_reach_nothing(self) -> None:
        problems = structural_problems(
            authored_crew(
                process="sequential", members=2, max_iter=1, member_config={"max_iter": 8}
            )
        )
        warned = [
            problem for problem in problems if problem.code == "crew-max-iter-ignored"
        ]
        self.assertEqual(len(warned), 1)
        self.assertEqual(warned[0].severity, "warning")
        self.assertEqual(warned[0].node_id, "team")
        self.assertIn("m0", warned[0].message)

    def test_a_crew_whose_members_agree_with_it_is_not_warned(self) -> None:
        self.assertEqual(
            [
                problem.code
                for problem in structural_problems(
                    authored_crew(process="sequential", members=2)
                )
                if problem.code == "crew-max-iter-ignored"
            ],
            [],
        )

    def test_a_library_crew_is_still_priced_at_its_own_ceilings(self) -> None:
        """Its `max_iter` really is passed on, so it really does price."""

        def library(max_iter: int) -> BuilderDocument:
            return document(
                [
                    input_node("idea"),
                    raw_node(
                        "sweep",
                        "crew",
                        {"crew_id": "sweep", "tier": "cheap", "max_iter": max_iter},
                    ),
                    output_node(),
                ],
                [edge("e1", "idea", "sweep"), edge("e2", "sweep", "report")],
            )

        self.assertEqual(node_call_count(library(1), "sweep"), 3 * 2)
        self.assertEqual(node_call_count(library(4), "sweep"), 3 * 5)


def nested_loops(*, loops: int, tier: str = "cheap") -> BuilderDocument:
    """One agent with `loops` router-closed back edges around it.

    Every back edge leaves a ROUTER, which `back-edge-not-router` requires, and
    every one of them returns to the same agent - so the agent takes `loops + 1`
    incoming edges and is declared `joins: any`, the mode that lets one arrival
    start it rather than waiting for all of them. That is the exact shape audit
    M8 is about: three loops with no per-cycle counter anywhere at run time.
    """

    routers = [f"r{index}" for index in range(loops)]
    # `scoper` rather than the node id: this document is COMPILED by one of the
    # tests below, and `library_problems` refuses an `agent_id` that is not one
    # of `config.py`'s registered YAML agents.
    agent = agent_node("a", tier=tier, tools=(MARKET_TOOL,))
    agent["config"]["agent_id"] = "scoper"
    agent["config"]["prompt_inputs"] = {"human_override": "", "idea": "${state.idea}"}
    nodes: list[Any] = [input_node("idea"), agent]
    edges = [edge("e_in", "idea", "a"), edge("e_a", "a", routers[0])]
    for index, router_id in enumerate(routers):
        nodes.append(
            router_node(
                router_id,
                branches=(
                    {"label": "again", "op": "otherwise"},
                    {"label": "on", "op": "gte", "key": "turns", "value": 3},
                ),
            )
        )
        edges.append(edge(f"e_back{index}", router_id, "a", source_port="again"))
        onward = routers[index + 1] if index + 1 < len(routers) else "report"
        edges.append(edge(f"e_on{index}", router_id, onward, source_port="on"))
    nodes.append(
        raw_node(
            "report",
            "output",
            {"body_key": "markdown_body", "source": "${state.out__a}"},
        )
    )
    graph = document(nodes, edges)
    payload = graph.model_dump(mode="json")
    payload["joins"] = {"a": "any"}
    return BuilderDocument.model_validate(payload)


class CycleMultiplierTests(unittest.TestCase):
    """Audit M8: the meter and the runtime backstop are one arithmetic.

    `budget` multiplied an on-cycle node by `1 + MAX_CYCLE_ITERATIONS` ONCE
    however many loops a graph closed, while `compiler._Plan.max_method_calls`
    has always sized CrewAI's per-method backstop at
    `(1 + MAX_CYCLE_ITERATIONS) ** cycles`. A router-closed loop has no
    per-cycle counter at run time, so three loops were metered at 4x against a
    runtime permitting 64x - a static price describing a smaller graph than the
    one that would run.
    """

    def test_three_back_edges_price_at_the_cube(self) -> None:
        flat = estimate_budget(nested_loops(loops=1))
        deep = estimate_budget(nested_loops(loops=3))
        self.assertEqual(len(back_edges(nested_loops(loops=3))), 3)
        self.assertEqual(
            deep.per_node["a"].calls,
            flat.per_node["a"].calls * (1 + MAX_CYCLE_ITERATIONS) ** 2,
        )
        # 3 attempts x (max_iter 2 + 1) x 4 ** 3.
        self.assertEqual(deep.per_node["a"].calls, 9 * 64)

    def test_a_single_cycle_prices_exactly_as_before(self) -> None:
        """The one-loop case is untouched, which is what makes this safe."""

        self.assertEqual(estimate_budget(nested_loops(loops=1)).modelled_calls, 9 * 4)
        frontier = estimate_budget(frontier_document(cheap=3, escalation=5))
        self.assertEqual(frontier.modelled_calls, FRONTIER_CALLS)
        self.assertAlmostEqual(frontier.floor_cost_usd, FRONTIER_FLOOR_USD, places=4)

    def test_the_three_loop_graph_is_refused_at_the_ceiling(self) -> None:
        graph = nested_loops(loops=3, tier="escalation")
        codes = [problem.code for problem in budget_problems(graph, ceiling_usd=10.0)]
        self.assertIn(budget_module.BUDGET_OVER_CEILING, codes)
        # And the one-loop version of the same graph is not, so the refusal is
        # the multiplier's doing and not the tier's.
        self.assertEqual(
            budget_problems(nested_loops(loops=1, tier="escalation"), ceiling_usd=10.0),
            [],
        )

    def test_the_budget_and_the_compiler_multiply_by_the_same_figure(self) -> None:
        """One helper, asked from both sides, so they cannot drift again."""

        from brief_crew.builder.compiler import compile_document

        for loops in (1, 2, 3):
            graph = nested_loops(loops=loops)
            with self.subTest(loops=loops):
                # The ceiling is disabled here on purpose: three loops price
                # this graph OVER $10 - which is the finding - and the question
                # this test asks is whether the two multipliers agree, not
                # whether the document may be published.
                compiled = compile_document(graph, ceiling_usd=0.0)
                self.assertEqual(
                    budget_module._cycle_multiplier(graph),
                    compiled.definition["config"]["max_method_calls"],
                )


class NitroSpellingTests(unittest.TestCase):
    """A `:nitro` id and its plain spelling name ONE slug, so they price alike.

    `NitroPricingTests.test_a_nitro_id_is_inflated_and_a_plain_one_is_not`
    until audit M14, where it asserted the opposite: the nitro spelling cost
    1.8x the plain one. That gap WAS the defect. `:nitro` is a routing
    instruction rather than a distinct model - `registry_model` strips it and
    both spellings reach one row with one set of endpoints - and the request
    carrying the plain spelling pins no endpoint either. Two prices for one
    slug meant the cheaper of them bounded nothing.
    """

    def test_a_nitro_id_and_its_plain_spelling_price_identically(self) -> None:
        nitro = estimate_budget(one_authored_agent(llm={"model": f"{CHEAPER_MODEL}:nitro"}))
        published = estimate_budget(one_authored_agent(llm={"model": CHEAPER_MODEL}))

        self.assertAlmostEqual(nitro.floor_cost_usd, published.floor_cost_usd, places=10)
        self.assertAlmostEqual(nitro.static_cost_usd, published.static_cost_usd, places=10)

    def test_both_spellings_are_inflated_by_the_slugs_measured_spread(self) -> None:
        row = MODEL_BY_ID[CHEAPER_MODEL]
        spread = row.cost_in_max_endpoint / row.cost_in
        # 1.8 for this row, which is NITRO_PRICE_FACTOR - a coincidence of the
        # slug the constant was measured on. Asserted as the REGISTRY's figure
        # so a re-measure moves this test rather than contradicting it.
        self.assertAlmostEqual(spread, NITRO_PRICE_FACTOR, places=6)
        for spelling in (CHEAPER_MODEL, f"{CHEAPER_MODEL}:nitro"):
            with self.subTest(spelling=spelling):
                estimate = estimate_budget(one_authored_agent(llm={"model": spelling}))
                self.assertAlmostEqual(
                    estimate.static_cost_usd, estimate.floor_cost_usd * spread, places=10
                )


class PerNodeCostTests(unittest.TestCase):
    """C5's `per_node`: the same figure the total sums, exposed not recomputed."""

    def test_the_per_node_dollars_sum_to_the_total(self) -> None:
        estimate = estimate_budget(frontier_document(cheap=5, escalation=3))
        self.assertAlmostEqual(
            sum(cost.usd for cost in estimate.per_node.values()),
            estimate.static_cost_usd,
            places=6,
        )

    def test_the_per_node_calls_sum_to_modelled_calls(self) -> None:
        estimate = estimate_budget(frontier_document(cheap=5, escalation=3))
        self.assertEqual(
            sum(cost.calls for cost in estimate.per_node.values()), estimate.modelled_calls
        )

    def test_only_billable_nodes_appear(self) -> None:
        estimate = estimate_budget(one_authored_agent())
        self.assertEqual(sorted(estimate.per_node), ["draft"])


class FrontierStillRefusedTests(unittest.TestCase):
    """The bound sweep's own worst case, after 09 changed the model."""

    def test_the_frontier_document_is_still_refused_at_ten_dollars(self) -> None:
        estimate = estimate_budget(
            frontier_document(
                cheap=MAX_BILLABLE_NODES - MAX_ESCALATION_NODES,
                escalation=MAX_ESCALATION_NODES,
            )
        )
        self.assertEqual(estimate.billable_nodes, MAX_BILLABLE_NODES)
        self.assertEqual(estimate.escalation_nodes, MAX_ESCALATION_NODES)
        self.assertEqual(estimate.modelled_calls, 468)
        self.assertGreater(estimate.static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN, 10.0)
        codes = [
            problem.code
            for problem in budget_problems(
                frontier_document(
                    cheap=MAX_BILLABLE_NODES - MAX_ESCALATION_NODES,
                    escalation=MAX_ESCALATION_NODES,
                ),
                ceiling_usd=10.0,
            )
        ]
        self.assertIn("budget-over-ceiling", codes)


if __name__ == "__main__":
    unittest.main()
