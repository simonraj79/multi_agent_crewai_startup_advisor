"""Every compile-time bound, at n and at n+1, plus the rule about routers.

The shape of this module is deliberate: for each bound there is a document that
sits exactly ON it and is expected to be COMPLETELY clean, and the same document
with one more of whatever the bound counts. A test that only asserts the
violation cannot tell a working bound from one that fires on everything.

The bound that is not a count gets the most attention, because it is the one
that was measured rather than derived: a loop closed by anything other than a
router does not fail loudly, it makes `kickoff()` return normally having
produced nothing.
"""

from __future__ import annotations

import unittest
from typing import Any, Iterable

from brief_crew.builder import (
    BuilderDocument,
    Problem,
    back_edges,
    billable_depths,
    compiled_identifiers,
    has_errors,
    nodes_on_cycles,
    structural_problems,
)
from brief_crew.builder import bounds
from brief_crew.config import (
    BUILDER_GATE_ROUTER_PREFIX,
    BUILDER_MAX_ID_CHARS,
    BUILDER_MAX_IDENT_BODY_CHARS,
    MAX_BILLABLE_NODES,
    MAX_CYCLE_ITERATIONS,
    MAX_CYCLES,
    MAX_ESCALATION_NODES,
    MAX_FANOUT_WIDTH,
    MAX_GRAPH_NODES,
    MIN_ROUTER_BRANCHES,
)
from tests.builder.test_document import (
    agent_node,
    chain,
    document,
    edge,
    gate_node,
    input_node,
    node,
    output_node,
    router_node,
    transform_node,
    validator_shaped_document,
)


def codes(problems: Iterable[Problem]) -> list[str]:
    return sorted(problem.code for problem in problems)


def error_codes(problems: Iterable[Problem]) -> list[str]:
    return sorted(problem.code for problem in problems if problem.severity == "error")


def find(problems: Iterable[Problem], code: str) -> Problem:
    for problem in problems:
        if problem.code == code:
            return problem
    raise AssertionError(f"no {code} problem in {codes(problems)}")


def linear(*payloads: dict[str, Any], **overrides: Any) -> BuilderDocument:
    """A document wiring the given nodes nose to tail on their `out` ports."""

    ids = [payload["id"] for payload in payloads]
    return document(list(payloads), chain(*ids), **overrides)


def looping_document(cycle_count: int) -> BuilderDocument:
    """A chain with `cycle_count` router-closed loops in it.

    Each loop is one transform followed by a router whose `again` branch goes
    back to that transform - the minimum legal cycle, since the loop-closing
    node has to be a router.
    """

    nodes: list[dict[str, Any]] = [input_node("idea")]
    edges: list[dict[str, Any]] = []
    previous, port = "idea", "out"
    for index in range(cycle_count):
        body, router = f"body{index}", f"route{index}"
        nodes += [transform_node(body), router_node(router)]
        edges += [
            edge(f"e{index}a", previous, body, source_port=port),
            edge(f"e{index}b", body, router),
            edge(f"e{index}c", router, body, source_port="again"),
        ]
        previous, port = router, "onward"
    nodes.append(output_node())
    edges.append(edge("e_out", previous, "report", source_port=port))
    return document(nodes, edges)


def gated_document(gate_id: str = "confirm", *, max_turns: int = 1) -> BuilderDocument:
    """input -> gate -> output, with the gate answered on its `approve` port."""

    return document(
        [input_node("idea"), gate_node(gate_id, max_turns=max_turns), output_node()],
        [edge("e1", "idea", gate_id), edge("e2", gate_id, "report", source_port="approve")],
    )


class NodeCountTests(unittest.TestCase):
    def _chain_of(self, transforms: int) -> BuilderDocument:
        payloads = [input_node("idea")]
        payloads += [transform_node(f"t{index}") for index in range(transforms)]
        payloads.append(output_node())
        return linear(*payloads)

    def test_a_graph_of_exactly_the_ceiling_is_clean(self) -> None:
        graph = self._chain_of(MAX_GRAPH_NODES - 2)
        self.assertEqual(len(graph.nodes), MAX_GRAPH_NODES)
        self.assertEqual(structural_problems(graph), [])

    def test_one_node_over_the_ceiling_is_refused_with_the_number_quoted(self) -> None:
        graph = self._chain_of(MAX_GRAPH_NODES - 1)
        problem = find(structural_problems(graph), bounds.NODE_COUNT)
        self.assertEqual(problem.severity, "error")
        self.assertIn(str(MAX_GRAPH_NODES + 1), problem.message)
        self.assertIn(str(MAX_GRAPH_NODES), problem.message)
        self.assertIn("MAX_GRAPH_NODES", problem.message)


class BillableCountTests(unittest.TestCase):
    def _with_agents(self, count: int, *, tier: str = "cheap") -> BuilderDocument:
        payloads = [input_node("idea")]
        payloads += [agent_node(f"a{index}", tier=tier) for index in range(count)]
        payloads.append(output_node())
        return linear(*payloads)

    def test_exactly_the_billable_ceiling_is_clean(self) -> None:
        graph = self._with_agents(MAX_BILLABLE_NODES)
        self.assertEqual(structural_problems(graph), [])

    def test_one_billable_node_over_is_refused(self) -> None:
        problem = find(
            structural_problems(self._with_agents(MAX_BILLABLE_NODES + 1)), bounds.BILLABLE_COUNT
        )
        self.assertIn(str(MAX_BILLABLE_NODES + 1), problem.message)
        self.assertIn("MAX_BILLABLE_NODES", problem.message)

    def test_a_crew_node_counts_as_billable_too(self) -> None:
        payloads = [input_node("idea")]
        payloads += [agent_node(f"a{index}") for index in range(MAX_BILLABLE_NODES)]
        payloads.append(node("sweep", "crew", {"crew_id": "sweep", "tier": "cheap"}))
        payloads.append(output_node())
        self.assertIn(bounds.BILLABLE_COUNT, codes(structural_problems(linear(*payloads))))

    def test_exactly_the_escalation_ceiling_is_clean(self) -> None:
        graph = self._with_agents(MAX_ESCALATION_NODES, tier="escalation")
        self.assertEqual(structural_problems(graph), [])

    def test_one_escalation_node_over_is_refused_and_names_a_node(self) -> None:
        graph = self._with_agents(MAX_ESCALATION_NODES + 1, tier="escalation")
        problem = find(structural_problems(graph), bounds.ESCALATION_COUNT)
        self.assertIn(str(MAX_ESCALATION_NODES + 1), problem.message)
        self.assertEqual(problem.node_id, f"a{MAX_ESCALATION_NODES}")

    def test_cheap_nodes_do_not_count_against_the_escalation_ceiling(self) -> None:
        payloads = [input_node("idea")]
        payloads += [agent_node(f"e{index}", tier="escalation") for index in range(MAX_ESCALATION_NODES)]
        payloads += [agent_node(f"c{index}") for index in range(MAX_BILLABLE_NODES - MAX_ESCALATION_NODES)]
        payloads.append(output_node())
        self.assertEqual(structural_problems(linear(*payloads)), [])


class FanoutTests(unittest.TestCase):
    def _fanning(self, width: int) -> BuilderDocument:
        payloads = [input_node("idea")]
        payloads += [transform_node(f"t{index}") for index in range(width)]
        payloads.append(output_node())
        edges = [edge(f"out{index}", "idea", f"t{index}") for index in range(width)]
        edges += [edge(f"in{index}", f"t{index}", "report") for index in range(width)]
        return document(payloads, edges)

    def test_exactly_the_fanout_ceiling_is_clean(self) -> None:
        self.assertEqual(structural_problems(self._fanning(MAX_FANOUT_WIDTH)), [])

    def test_one_edge_wider_is_refused_and_names_the_node(self) -> None:
        problem = find(structural_problems(self._fanning(MAX_FANOUT_WIDTH + 1)), bounds.FANOUT_WIDTH)
        self.assertEqual(problem.node_id, "idea")
        self.assertIn(str(MAX_FANOUT_WIDTH + 1), problem.message)
        self.assertIn("MAX_FANOUT_WIDTH", problem.message)


class CycleTests(unittest.TestCase):
    def test_exactly_the_cycle_ceiling_is_clean(self) -> None:
        graph = looping_document(MAX_CYCLES)
        self.assertEqual(len(back_edges(graph)), MAX_CYCLES)
        self.assertEqual(structural_problems(graph), [])

    def test_one_cycle_over_is_refused_and_names_the_offending_edge(self) -> None:
        graph = looping_document(MAX_CYCLES + 1)
        problem = find(structural_problems(graph), bounds.CYCLE_COUNT)
        self.assertIn(str(MAX_CYCLES + 1), problem.message)
        self.assertIn("MAX_CYCLES", problem.message)
        self.assertIsNotNone(problem.edge_id)

    def test_a_cycle_closed_by_a_plain_node_is_refused_and_names_the_router_to_insert(self) -> None:
        """The measured failure: a plain loop-closing node ends the run silently."""

        graph = document(
            [
                input_node("idea"),
                gate_node("confirm_scope"),
                agent_node("revise_scope", tier="escalation"),
                output_node(),
            ],
            [
                edge("e1", "idea", "confirm_scope"),
                edge("e2", "confirm_scope", "report", source_port="approve"),
                edge("e3", "confirm_scope", "revise_scope", source_port="revise"),
                edge("e4", "revise_scope", "confirm_scope"),
            ],
        )
        problem = find(structural_problems(graph), bounds.BACK_EDGE_NOT_ROUTER)
        self.assertEqual(problem.severity, "error")
        self.assertEqual(problem.node_id, "revise_scope")
        self.assertEqual(problem.edge_id, "e4")
        self.assertIn("router", problem.message)
        self.assertIn("revise_scope", problem.message)
        self.assertIn("confirm_scope", problem.message)
        self.assertIn("insert a router node", problem.message)

    def test_the_same_loop_closed_by_a_router_is_accepted(self) -> None:
        graph = document(
            [
                input_node("idea"),
                gate_node("confirm_scope"),
                agent_node("revise_scope", tier="escalation"),
                router_node(
                    "route_revise",
                    branches=(
                        {"label": "again", "op": "otherwise"},
                        {"label": "give_up", "op": "gte", "key": "turns", "value": 3},
                    ),
                ),
                output_node(),
            ],
            [
                edge("e1", "idea", "confirm_scope"),
                edge("e2", "confirm_scope", "report", source_port="approve"),
                edge("e3", "confirm_scope", "revise_scope", source_port="revise"),
                edge("e4", "revise_scope", "route_revise"),
                edge("e5", "route_revise", "confirm_scope", source_port="again"),
                edge("e6", "route_revise", "report", source_port="give_up"),
            ],
        )
        self.assertEqual(structural_problems(graph), [])

    def test_a_gate_may_close_a_loop_because_its_second_method_is_a_router(self) -> None:
        graph = document(
            [
                input_node("idea"),
                transform_node("prepare"),
                gate_node("confirm"),
                output_node(),
            ],
            [
                edge("e1", "idea", "prepare"),
                edge("e2", "prepare", "confirm"),
                edge("e3", "confirm", "prepare", source_port="revise"),
                edge("e4", "confirm", "report", source_port="approve"),
            ],
        )
        self.assertEqual(len(back_edges(graph)), 1)
        self.assertEqual(structural_problems(graph), [])

    def test_a_self_loop_on_a_plain_node_is_caught_by_the_same_rule(self) -> None:
        graph = document(
            [input_node("idea"), transform_node("t"), output_node()],
            [
                edge("e1", "idea", "t"),
                edge("e2", "t", "t"),
                edge("e3", "t", "report"),
            ],
        )
        self.assertIn(bounds.BACK_EDGE_NOT_ROUTER, codes(structural_problems(graph)))

    def test_nodes_on_cycles_is_the_loop_body_and_nothing_else(self) -> None:
        graph = validator_shaped_document()
        self.assertEqual(
            nodes_on_cycles(graph),
            frozenset(
                {
                    "confirm_scope",
                    "revise_scope",
                    "route_revise",
                    "review_verdict",
                    "revise_verdict",
                    "route_reverdict",
                }
            ),
        )

    def test_a_detached_cycle_is_still_counted(self) -> None:
        """A loop nothing reaches is unreachable AND a cycle - both are said."""

        graph = document(
            [
                input_node("idea"),
                output_node(),
                transform_node("orphan"),
                router_node("orphan_route"),
            ],
            [
                edge("e1", "idea", "report"),
                edge("e2", "orphan", "orphan_route"),
                edge("e3", "orphan_route", "orphan", source_port="again"),
            ],
        )
        self.assertEqual(len(back_edges(graph)), 1)
        self.assertIn(bounds.NODE_UNREACHABLE, codes(structural_problems(graph)))


class GateTurnTests(unittest.TestCase):
    def _with_turns(self, turns: int) -> BuilderDocument:
        return gated_document(max_turns=turns)

    def test_exactly_the_iteration_ceiling_is_clean(self) -> None:
        graph = self._with_turns(MAX_CYCLE_ITERATIONS)
        self.assertEqual(error_codes(structural_problems(graph)), [])

    def test_one_turn_over_is_refused_and_explains_why_it_is_not_five(self) -> None:
        problem = find(
            structural_problems(self._with_turns(MAX_CYCLE_ITERATIONS + 1)),
            bounds.CYCLE_ITERATIONS,
        )
        self.assertEqual(problem.node_id, "confirm")
        self.assertIn(str(MAX_CYCLE_ITERATIONS + 1), problem.message)
        self.assertIn("MAX_CYCLE_ITERATIONS", problem.message)
        self.assertIn("human in the loop", problem.message)


class RouterRuleTests(unittest.TestCase):
    def _with_branches(self, branches: tuple[dict[str, Any], ...]) -> BuilderDocument:
        payloads = [input_node("idea"), router_node("route", branches=branches), output_node()]
        edges = [edge("e1", "idea", "route")]
        edges += [
            edge(f"b{index}", "route", "report", source_port=branch["label"])
            for index, branch in enumerate(branches)
        ]
        return document(payloads, edges)

    def _numbered(self, count: int) -> tuple[dict[str, Any], ...]:
        branches: list[dict[str, Any]] = [
            {"label": f"b{index}", "op": "eq", "key": "score", "value": index}
            for index in range(count - 1)
        ]
        branches.append({"label": "fallback", "op": "otherwise"})
        return tuple(branches)

    def test_the_minimum_and_maximum_branch_counts_are_clean(self) -> None:
        for count in (MIN_ROUTER_BRANCHES, MAX_FANOUT_WIDTH):
            with self.subTest(branches=count):
                self.assertEqual(structural_problems(self._with_branches(self._numbered(count))), [])

    def test_one_branch_is_refused(self) -> None:
        problem = find(
            structural_problems(self._with_branches(({"label": "only", "op": "otherwise"},))),
            bounds.ROUTER_BRANCH_COUNT,
        )
        self.assertIn(str(MIN_ROUTER_BRANCHES), problem.message)

    def test_one_branch_over_the_fanout_ceiling_is_refused(self) -> None:
        problems = structural_problems(self._with_branches(self._numbered(MAX_FANOUT_WIDTH + 1)))
        problem = find(problems, bounds.ROUTER_BRANCH_COUNT)
        self.assertIn(str(MAX_FANOUT_WIDTH + 1), problem.message)
        self.assertEqual(problem.node_id, "route")

    def test_no_otherwise_branch_is_refused_because_a_miss_would_wedge_the_run(self) -> None:
        branches = (
            {"label": "pass", "op": "gte", "key": "score", "value": 6},
            {"label": "fail", "op": "lt", "key": "score", "value": 6},
        )
        problem = find(structural_problems(self._with_branches(branches)), bounds.ROUTER_OTHERWISE)
        self.assertIn("0 otherwise", problem.message)

    def test_two_otherwise_branches_are_refused_too(self) -> None:
        branches = (
            {"label": "one", "op": "otherwise"},
            {"label": "two", "op": "otherwise"},
        )
        problem = find(structural_problems(self._with_branches(branches)), bounds.ROUTER_OTHERWISE)
        self.assertIn("2 otherwise", problem.message)

    def test_a_duplicate_branch_label_is_refused(self) -> None:
        branches = (
            {"label": "same", "op": "gte", "key": "score", "value": 6},
            {"label": "same", "op": "otherwise"},
        )
        self.assertIn(bounds.ROUTER_DUPLICATE_BRANCH, codes(structural_problems(self._with_branches(branches))))

    def test_an_unconnected_branch_is_a_warning_and_does_not_block(self) -> None:
        graph = document(
            [input_node("idea"), router_node("route"), output_node()],
            [edge("e1", "idea", "route"), edge("e2", "route", "report", source_port="again")],
        )
        problems = structural_problems(graph)
        problem = find(problems, bounds.ROUTER_BRANCH_UNCONNECTED)
        self.assertEqual(problem.severity, "warning")
        self.assertFalse(has_errors(problems))


class EdgeWiringTests(unittest.TestCase):
    def test_an_edge_to_a_node_that_does_not_exist_is_refused(self) -> None:
        graph = document(
            [input_node("idea"), output_node()],
            [edge("e1", "idea", "ghost"), edge("e2", "idea", "report")],
        )
        problem = find(structural_problems(graph), bounds.EDGE_UNKNOWN_ENDPOINT)
        self.assertEqual(problem.edge_id, "e1")
        self.assertIn("ghost", problem.message)

    def test_a_port_the_kind_does_not_offer_is_refused_and_lists_the_ones_it_has(self) -> None:
        graph = document(
            [input_node("idea"), gate_node("confirm"), output_node()],
            [
                edge("e1", "idea", "confirm"),
                edge("e2", "confirm", "report", source_port="out"),
            ],
        )
        problem = find(structural_problems(graph), bounds.EDGE_UNKNOWN_PORT)
        self.assertIn("approve", problem.message)
        self.assertIn("revise", problem.message)

    def test_an_edge_arriving_at_an_input_node_is_refused(self) -> None:
        graph = document(
            [input_node("idea"), transform_node("t"), output_node()],
            [
                edge("e1", "idea", "t"),
                edge("e2", "t", "report"),
                edge("e3", "t", "idea"),
            ],
        )
        self.assertIn(bounds.EDGE_TARGET_REFUSES_INCOMING, codes(structural_problems(graph)))

    def test_an_edge_leaving_an_output_node_is_refused(self) -> None:
        graph = document(
            [input_node("idea"), output_node(), transform_node("after")],
            [edge("e1", "idea", "report"), edge("e2", "report", "after")],
        )
        problem = find(structural_problems(graph), bounds.EDGE_UNKNOWN_PORT)
        self.assertIn("no outputs at all", problem.message)

    def test_duplicate_node_and_edge_ids_are_refused(self) -> None:
        graph = document(
            [input_node("idea"), transform_node("t"), transform_node("t"), output_node()],
            [edge("e1", "idea", "t"), edge("e1", "t", "report")],
        )
        found = codes(structural_problems(graph))
        self.assertIn(bounds.DUPLICATE_NODE_ID, found)
        self.assertIn(bounds.DUPLICATE_EDGE_ID, found)


class InputAndReachabilityTests(unittest.TestCase):
    def test_a_graph_with_no_input_node_is_refused(self) -> None:
        graph = document([transform_node("t")], [])
        self.assertIn(bounds.NO_INPUT_NODE, codes(structural_problems(graph)))

    def test_the_declared_input_field_must_be_asked_for_by_an_input_node(self) -> None:
        graph = linear(input_node("brief", field="topic"), output_node(), input_field="idea")
        problem = find(structural_problems(graph), bounds.INPUT_FIELD_UNDECLARED)
        self.assertIn("idea", problem.message)
        self.assertIn("topic", problem.message)

    def test_two_input_nodes_asking_for_the_same_field_are_refused(self) -> None:
        graph = document(
            [input_node("first", "idea"), input_node("second", "idea"), output_node()],
            [edge("e1", "first", "report"), edge("e2", "second", "report")],
        )
        problem = find(structural_problems(graph), bounds.INPUT_FIELD_AMBIGUOUS)
        self.assertEqual(problem.node_id, "second")

    def test_two_input_nodes_asking_for_different_fields_are_fine(self) -> None:
        graph = document(
            [input_node("first", "idea"), input_node("second", "namespace"), output_node()],
            [edge("e1", "first", "report"), edge("e2", "second", "report")],
        )
        self.assertEqual(structural_problems(graph), [])

    def test_a_node_nothing_leads_to_is_refused(self) -> None:
        graph = document(
            [input_node("idea"), output_node(), transform_node("stranded")],
            [edge("e1", "idea", "report")],
        )
        problem = find(structural_problems(graph), bounds.NODE_UNREACHABLE)
        self.assertEqual(problem.node_id, "stranded")

    def test_a_graph_with_no_output_node_is_only_warned_about(self) -> None:
        graph = linear(input_node("idea"), transform_node("t"))
        problems = structural_problems(graph)
        self.assertEqual(find(problems, bounds.NO_OUTPUT_NODE).severity, "warning")
        self.assertFalse(has_errors(problems))


class JoinDeclarationTests(unittest.TestCase):
    def test_a_join_on_a_node_that_does_not_exist_is_refused(self) -> None:
        graph = linear(input_node("idea"), output_node(), joins={"ghost": "all"})
        self.assertIn(bounds.JOIN_UNKNOWN_NODE, codes(structural_problems(graph)))

    def test_a_join_over_one_edge_is_a_warning(self) -> None:
        graph = linear(input_node("idea"), transform_node("t"), output_node(), joins={"t": "all"})
        problems = structural_problems(graph)
        self.assertEqual(find(problems, bounds.JOIN_SINGLE_PREDECESSOR).severity, "warning")
        self.assertFalse(has_errors(problems))

    def test_a_join_over_three_edges_is_clean(self) -> None:
        self.assertEqual(structural_problems(validator_shaped_document()), [])


class CompiledIdentifierTests(unittest.TestCase):
    """Blocker 8: two namespaces, and the assertion that they stay apart."""

    def test_a_gate_compiles_to_two_methods_and_consumes_two_indices(self) -> None:
        methods, _ = compiled_identifiers(gated_document())
        self.assertEqual(methods["idea"], ("n0_idea",))
        self.assertEqual(methods["confirm"], ("n1_confirm", "n2_route_confirm"))
        self.assertEqual(methods["report"], ("n3_report",))

    def test_method_idents_and_event_labels_never_intersect(self) -> None:
        methods, labels = compiled_identifiers(validator_shaped_document())
        flat_methods = {ident for group in methods.values() for ident in group}
        flat_labels = {label for group in labels.values() for label in group}
        self.assertTrue(flat_methods)
        self.assertTrue(flat_labels)
        self.assertTrue(flat_methods.isdisjoint(flat_labels))
        self.assertTrue(all(ident.startswith("n") for ident in flat_methods))
        self.assertTrue(all(label.startswith("e") for label in flat_labels))

    def test_a_gates_id_has_six_characters_less_room_than_any_other_nodes(self) -> None:
        """`route_` is a real bound, not decoration - this is where it bites."""

        longest = BUILDER_MAX_IDENT_BODY_CHARS - len(BUILDER_GATE_ROUTER_PREFIX)
        fits = "g" * longest
        over = "g" * (longest + 1)
        self.assertLess(len(over), BUILDER_MAX_ID_CHARS)  # legal as a node id

        clean = gated_document(fits)
        self.assertEqual(error_codes(structural_problems(clean)), [])

        graph = gated_document(over)
        problem = find(structural_problems(graph), bounds.IDENT_PATTERN)
        self.assertEqual(problem.node_id, over)
        self.assertIn(BUILDER_GATE_ROUTER_PREFIX, problem.message)

    def test_two_nodes_can_never_compile_to_one_method_name(self) -> None:
        """The index prefix is what guarantees it; duplicate ids prove it holds."""

        graph = document(
            [input_node("idea"), transform_node("t"), transform_node("t"), output_node()],
            [edge("e1", "idea", "t"), edge("e2", "t", "report")],
        )
        methods, _ = compiled_identifiers(graph)
        self.assertEqual(methods["t"], ("n2_t",))  # the second one wins the map
        self.assertNotIn(bounds.IDENT_COLLISION, codes(structural_problems(graph)))
        self.assertIn(bounds.DUPLICATE_NODE_ID, codes(structural_problems(graph)))


class DepthTests(unittest.TestCase):
    """`billable_depths` is what makes a deep graph cost more than a wide one."""

    def test_depth_counts_billable_nodes_upstream_not_nodes(self) -> None:
        graph = linear(
            input_node("idea"),
            transform_node("t1"),
            agent_node("a1"),
            transform_node("t2"),
            agent_node("a2"),
            output_node(),
        )
        depths = billable_depths(graph)
        self.assertEqual(depths["a1"], 0)
        self.assertEqual(depths["t2"], 1)
        self.assertEqual(depths["a2"], 1)
        self.assertEqual(depths["report"], 2)

    def test_a_fan_out_is_shallower_than_a_chain_of_the_same_nodes(self) -> None:
        wide = document(
            [input_node("idea"), agent_node("a1"), agent_node("a2"), output_node()],
            [
                edge("e1", "idea", "a1"),
                edge("e2", "idea", "a2"),
                edge("e3", "a1", "report"),
                edge("e4", "a2", "report"),
            ],
        )
        deep = linear(input_node("idea"), agent_node("a1"), agent_node("a2"), output_node())
        self.assertEqual(billable_depths(wide)["a2"], 0)
        self.assertEqual(billable_depths(deep)["a2"], 1)

    def test_a_cycle_does_not_make_the_depth_computation_diverge(self) -> None:
        depths = billable_depths(validator_shaped_document())
        self.assertEqual(depths["scope_idea"], 0)
        self.assertEqual(depths["synthesize"], 2)


class NeverRaisesTests(unittest.TestCase):
    """The contract: a wrong document produces problems, not a traceback."""

    def test_a_thoroughly_broken_document_reports_and_does_not_raise(self) -> None:
        graph = document(
            [
                transform_node("t"),
                transform_node("t"),
                node("route", "router", {"branches": []}),
                agent_node("orphan"),
            ],
            [
                edge("x1", "t", "nowhere"),
                edge("x1", "ghost", "t"),
                edge("x2", "route", "t", source_port="nope"),
            ],
            joins={"missing": "all"},
        )
        problems = structural_problems(graph)
        self.assertTrue(has_errors(problems))
        for expected in (
            bounds.DUPLICATE_NODE_ID,
            bounds.DUPLICATE_EDGE_ID,
            bounds.EDGE_UNKNOWN_ENDPOINT,
            bounds.EDGE_UNKNOWN_PORT,
            bounds.ROUTER_BRANCH_COUNT,
            bounds.ROUTER_OTHERWISE,
            bounds.NO_INPUT_NODE,
            bounds.JOIN_UNKNOWN_NODE,
        ):
            with self.subTest(code=expected):
                self.assertIn(expected, codes(problems))

    def test_an_empty_document_reports_rather_than_dividing_by_zero(self) -> None:
        graph = document([], [])
        self.assertEqual(error_codes(structural_problems(graph)), [bounds.NO_INPUT_NODE])

    def test_every_problem_carries_a_message_that_names_something(self) -> None:
        graph = looping_document(MAX_CYCLES + 1)
        for problem in structural_problems(graph):
            with self.subTest(code=problem.code):
                self.assertGreater(len(problem.message), 40)
                self.assertIn(problem.severity, ("error", "warning"))


#: The shipped validator's own four counts, read off `service/graph.py` and
#: reproduced by `validator_shaped_document`. Written out as literals on
#: purpose: they are a MEASUREMENT of a topology, not a restatement of a bound,
#: and comparing them to the bounds is the whole point of the tests below. When
#: they were the same numbers as the bounds, that comparison could not be made
#: and the template's zero headroom was invisible.
VALIDATOR_BILLABLE = 8
VALIDATOR_ESCALATION = 5
VALIDATOR_CYCLES = 2
VALIDATOR_FANOUT = 4


class ValidatorShapedTests(unittest.TestCase):
    """The realistic document, and the headroom it is now allowed."""

    def _counts(self, graph: BuilderDocument) -> tuple[int, int, int, int]:
        billable = [item for item in graph.nodes if item.is_billable]
        widths = [
            len([e for e in graph.edges if e.source == item.id]) for item in graph.nodes
        ]
        return (
            len(billable),
            len([n for n in billable if n.tier == "escalation"]),
            len(back_edges(graph)),
            max(widths),
        )

    def test_it_has_no_problems_at_all(self) -> None:
        self.assertEqual(structural_problems(validator_shaped_document()), [])

    def test_it_reproduces_the_shipped_validator_counts(self) -> None:
        self.assertEqual(
            self._counts(validator_shaped_document()),
            (VALIDATOR_BILLABLE, VALIDATOR_ESCALATION, VALIDATOR_CYCLES, VALIDATOR_FANOUT),
        )

    def test_the_gallery_template_has_room_to_grow(self) -> None:
        """The bound this template ships against must be ABOVE its own count.

        This is the assertion the previous version of this class could not
        make, because it compared the template's counts to the bounds and found
        them equal - which reads as rigour and was in fact the defect. A hero
        graph sitting exactly on three ceilings errors on the first node a user
        adds, and the sentence it errors with talks about money.
        """

        self.assertGreater(MAX_BILLABLE_NODES, VALIDATOR_BILLABLE)
        self.assertGreater(MAX_ESCALATION_NODES, VALIDATOR_ESCALATION)
        self.assertGreater(MAX_CYCLES, VALIDATOR_CYCLES)

    def test_the_fan_out_bound_is_still_exactly_on_the_template(self) -> None:
        """Recorded rather than smoothed over, because it is the one exception.

        MAX_FANOUT_WIDTH bounds concurrent threads and an external rate limit,
        not price, so it did not move with the others and `config.py` says why.
        A fifth branch off the scope gate is refused, and that refusal is
        deliberate - if this ever stops failing, somebody widened the fan-out
        and the note above the constant needs re-reading, not deleting.
        """

        self.assertEqual(self._counts(validator_shaped_document())[3], MAX_FANOUT_WIDTH)

    def test_a_ninth_billable_node_is_now_accepted(self) -> None:
        graph = validator_shaped_document()
        payload = graph.model_dump(mode="json", by_alias=True)
        payload["nodes"].append(agent_node("extra"))
        payload["edges"].append(edge("e20", "synthesize", "extra"))
        payload["edges"].append(edge("e21", "extra", "report"))
        self.assertEqual(structural_problems(BuilderDocument.model_validate(payload)), [])

    def test_one_node_past_the_raised_ceiling_is_still_refused(self) -> None:
        """The bound moved; it did not stop existing."""

        graph = validator_shaped_document()
        payload = graph.model_dump(mode="json", by_alias=True)
        previous = "synthesize"
        for index in range(MAX_BILLABLE_NODES - VALIDATOR_BILLABLE + 1):
            node_id = f"extra{index}"
            payload["nodes"].append(agent_node(node_id))
            payload["edges"].append(edge(f"e2{index}", previous, node_id))
            previous = node_id
        payload["edges"].append(edge("e_tail", previous, "report"))
        problems = structural_problems(BuilderDocument.model_validate(payload))
        self.assertIn(bounds.BILLABLE_COUNT, codes(problems))


if __name__ == "__main__":
    unittest.main()
