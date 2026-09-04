"""D2's edge classes: each rule fires on a minimal document AND NOWHERE ELSE.

03-node-library.md D2, criterion 3. Two halves, and the second is the one worth
writing down because it is the half a careless implementation passes:

**The positive half** is one minimal document per code - a graph that is
otherwise clean, wrong in exactly one way, so that a rule firing on the right
thing is distinguishable from a rule firing on everything.

**The negative half is "and nowhere else"**, and it is an ABSENCE, which is
worth nothing until it has failed once. Two documents carry it: `clean_graph()`,
which draws every legal use of both new edge classes at once - two tools and a
skill attached to an agent, a crew with three members - and must return ZERO
problems of any severity; and the exclusion tests below, which assert that
`attach` and `member` edges are invisible to the four graph questions that would
otherwise count them. Each of those four is a real defect if it regresses:

* **fan-out** - an agent holding five tools would report `fanout-width`, and the
  message would quote GitHub's rate limit at somebody who drew no branches.
* **cycles** - `attach` is directional and a tool cannot be in a loop, but a
  crew whose member's output feeds it looks exactly like one to a DFS that
  counts every edge, and the answer would be `back-edge-not-router` on an agent.
* **MAX_GRAPH_NODES** - the 24 is derived from the 2,000-frame replay ring, and
  an attachment emits no frames at all.
* **billable_depths** - depth is "how much upstream context does this node pay
  for on every call", and an attachment produces no context and no call.

These were verified by BREAKING them: reverting `is_flow_edge` to `True` makes
the fan-out, cycle and depth assertions fail together, and counting attachments
against `MAX_GRAPH_NODES` makes `test_attachments_do_not_count_toward_the_graph
_ceiling` fail with 25 against 24. See the plan's Status.

No cost: this parses dicts and walks graphs. No network, no model, no credential.
"""

from __future__ import annotations

import unittest
from typing import Any

from brief_crew.builder import (
    BuilderDocument,
    back_edges,
    billable_depths,
    structural_problems,
)
from brief_crew.builder.bounds import (
    ATTACH_TARGET_NOT_AGENT,
    ATTACHMENT_NODES_OVER_MAX,
    ATTACHMENT_UNATTACHED,
    ATTACHMENTS_OVER_MAX,
    CREW_MEMBERS_OUT_OF_RANGE,
    MEMBER_AGENT_HAS_FLOW_EDGES,
    MEMBER_TARGET_NOT_CREW,
    flow_edges,
    member_agent_ids,
)
from brief_crew.config import (
    MAX_ATTACHMENT_NODES,
    MAX_ATTACHMENTS_PER_NODE,
    MAX_BILLABLE_NODES,
    MAX_CREW_MEMBERS,
    MAX_FANOUT_WIDTH,
    MAX_GRAPH_NODES,
)
from tests.builder.test_authored_nodes import authored_crew_config
from tests.builder.test_bounds import codes, error_codes, find
from tests.builder.test_document import (
    agent_node,
    chain,
    document,
    edge,
    input_node,
    node,
    output_node,
    transform_node,
)

D2_CODES = (
    ATTACH_TARGET_NOT_AGENT,
    MEMBER_TARGET_NOT_CREW,
    MEMBER_AGENT_HAS_FLOW_EDGES,
    ATTACHMENT_UNATTACHED,
    ATTACHMENTS_OVER_MAX,
    ATTACHMENT_NODES_OVER_MAX,
    CREW_MEMBERS_OUT_OF_RANGE,
)


# --------------------------------------------------------------------------
# Factories
# --------------------------------------------------------------------------
def tool_node(node_id: str, *, kind: str = "tool") -> dict[str, Any]:
    config: dict[str, Any] = {
        "tool": {"tool_id": "firecrawl_scrape"},
        "mcp": {"server_id": "filesystem", "tool_names": ["read_file"]},
        "skill": {"skill_id": "pricing"},
    }[kind]
    return node(node_id, kind, config)


def authored_crew_node(node_id: str, **overrides: Any) -> dict[str, Any]:
    return node(node_id, "crew", authored_crew_config(**overrides))


def attach(edge_id: str, source: str, target: str) -> dict[str, Any]:
    return {
        "id": edge_id,
        "source": source,
        "source_port": "attach",
        "target": target,
        "target_port": "attach",
    }


def member(edge_id: str, source: str, target: str) -> dict[str, Any]:
    return {
        "id": edge_id,
        "source": source,
        "source_port": "out",
        "target": target,
        "target_port": "member",
    }


def clean_graph() -> BuilderDocument:
    """Every legal use of both new edge classes, in one document.

    `idea -> worker -> team -> report`, with two tools and a skill on `worker`
    and three member agents inside `team`. This is the "and nowhere else"
    control: it exercises attach edges, member edges, an attachment on an agent,
    a crew with members, and member agents carrying no flow edges - and it must
    come back with NOTHING, not even a warning.
    """

    return document(
        [
            input_node(),
            agent_node("worker"),
            authored_crew_node("team", task_order=["m1", "m2", "m3"]),
            output_node(),
            tool_node("scraper"),
            tool_node("files", kind="mcp"),
            tool_node("pricing", kind="skill"),
            agent_node("m1"),
            agent_node("m2"),
            agent_node("m3"),
        ],
        [
            *chain("idea", "worker", "team", "report"),
            attach("a1", "scraper", "worker"),
            attach("a2", "files", "worker"),
            attach("a3", "pricing", "worker"),
            member("m_1", "m1", "team"),
            member("m_2", "m2", "team"),
            member("m_3", "m3", "team"),
        ],
    )


# --------------------------------------------------------------------------
# The control: every legal shape at once, and nothing to say about it
# --------------------------------------------------------------------------
class CleanGraphTests(unittest.TestCase):
    def test_the_fully_wired_graph_reports_nothing_at_all(self) -> None:
        self.assertEqual(codes(structural_problems(clean_graph())), [])

    def test_none_of_the_seven_new_codes_fires_on_it(self) -> None:
        """'And nowhere else', stated per code so a failure names the rule."""

        produced = set(codes(structural_problems(clean_graph())))
        for code in D2_CODES:
            with self.subTest(code=code):
                self.assertNotIn(code, produced)

    def test_the_shipped_validator_topology_is_still_clean(self) -> None:
        """The regression guard: no D2 rule may fire on a graph with no attachments."""

        from tests.builder.test_document import validator_shaped_document

        produced = set(codes(structural_problems(validator_shaped_document())))
        for code in D2_CODES:
            with self.subTest(code=code):
                self.assertNotIn(code, produced)


# --------------------------------------------------------------------------
# One minimal document per rule
# --------------------------------------------------------------------------
class AttachRuleTests(unittest.TestCase):
    def test_a_tool_attached_to_a_gate_names_both_kinds(self) -> None:
        graph = document(
            [input_node(), node("confirm", "gate", {"message": "ok?"}), output_node(), tool_node("scraper")],
            [
                edge("e1", "idea", "confirm"),
                edge("e2", "confirm", "report", source_port="approve"),
                edge("e3", "confirm", "report", source_port="revise"),
                attach("a1", "scraper", "confirm"),
            ],
        )
        problem = find(structural_problems(graph), ATTACH_TARGET_NOT_AGENT)
        self.assertEqual(problem.node_id, "scraper")
        self.assertEqual(problem.edge_id, "a1")
        self.assertIn("gate", problem.message)

    def test_an_agent_attached_to_an_agent_is_not_an_attachment(self) -> None:
        graph = document(
            [input_node(), agent_node("worker"), agent_node("helper"), output_node()],
            [*chain("idea", "worker", "report"), attach("a1", "helper", "worker")],
        )
        self.assertIn(ATTACH_TARGET_NOT_AGENT, error_codes(structural_problems(graph)))

    def test_an_attachment_wired_as_a_flow_step_is_refused_with_a_reason(self) -> None:
        """The other direction: a tool is not a step, so it has no `out`."""

        graph = document(
            [input_node(), agent_node("worker"), output_node(), tool_node("scraper")],
            [
                *chain("idea", "worker", "report"),
                {
                    "id": "f1",
                    "source": "scraper",
                    "source_port": "attach",
                    "target": "report",
                    "target_port": "in",
                },
            ],
        )
        problem = find(structural_problems(graph), ATTACH_TARGET_NOT_AGENT)
        self.assertIn("not a step", problem.message)

    def test_an_edge_INTO_a_tool_is_the_refuses_incoming_rule_and_says_why(self) -> None:
        """One dropped edge, one row: the attach rule stands down here."""

        graph = document(
            [input_node(), agent_node("worker"), output_node(), tool_node("scraper")],
            [*chain("idea", "worker", "report"), edge("x1", "worker", "scraper")],
        )
        produced = codes(structural_problems(graph))
        self.assertEqual(produced.count(ATTACH_TARGET_NOT_AGENT), 0)
        problem = find(structural_problems(graph), "edge-target-refuses-incoming")
        self.assertIn("something an agent HAS", problem.message)

    def test_an_unattached_attachment_is_a_warning_and_not_an_error(self) -> None:
        graph = document(
            [input_node(), agent_node("worker"), output_node(), tool_node("scraper")],
            [*chain("idea", "worker", "report")],
        )
        problems = structural_problems(graph)
        problem = find(problems, ATTACHMENT_UNATTACHED)
        self.assertEqual(problem.severity, "warning")
        self.assertEqual(problem.node_id, "scraper")
        self.assertEqual(error_codes(problems), [])

    def test_an_unattached_attachment_is_exempt_from_node_unreachable(self) -> None:
        """Two rows for one omission is how a problems panel becomes unreadable."""

        graph = document(
            [input_node(), agent_node("worker"), output_node(), tool_node("scraper")],
            [*chain("idea", "worker", "report")],
        )
        self.assertNotIn("node-unreachable", codes(structural_problems(graph)))

    def test_the_per_node_attachment_ceiling_fires_at_n_plus_one_only(self) -> None:
        def graph(count: int) -> BuilderDocument:
            return document(
                [
                    input_node(),
                    agent_node("worker"),
                    output_node(),
                    *[tool_node(f"t{index}") for index in range(count)],
                ],
                [
                    *chain("idea", "worker", "report"),
                    *[attach(f"a{index}", f"t{index}", "worker") for index in range(count)],
                ],
            )

        self.assertEqual(codes(structural_problems(graph(MAX_ATTACHMENTS_PER_NODE))), [])
        problem = find(
            structural_problems(graph(MAX_ATTACHMENTS_PER_NODE + 1)), ATTACHMENTS_OVER_MAX
        )
        self.assertEqual(problem.node_id, "worker")
        self.assertIn(str(MAX_ATTACHMENTS_PER_NODE), problem.message)

    def test_the_document_attachment_ceiling_fires_at_n_plus_one_only(self) -> None:
        def graph(count: int) -> BuilderDocument:
            # Spread across enough agents that the PER-NODE ceiling never fires,
            # so this test is about the document count and nothing else.
            holders = [f"h{index}" for index in range((count // MAX_ATTACHMENTS_PER_NODE) + 1)]
            return document(
                [
                    input_node(),
                    *[agent_node(holder) for holder in holders],
                    output_node(),
                    *[tool_node(f"t{index}") for index in range(count)],
                ],
                [
                    *chain("idea", *holders, "report"),
                    *[
                        attach(f"a{index}", f"t{index}", holders[index % len(holders)])
                        for index in range(count)
                    ],
                ],
            )

        self.assertNotIn(
            ATTACHMENT_NODES_OVER_MAX, codes(structural_problems(graph(MAX_ATTACHMENT_NODES)))
        )
        problem = find(
            structural_problems(graph(MAX_ATTACHMENT_NODES + 1)), ATTACHMENT_NODES_OVER_MAX
        )
        self.assertIn(str(MAX_ATTACHMENT_NODES), problem.message)


class MemberRuleTests(unittest.TestCase):
    def test_an_agent_made_a_member_of_a_transform_names_both_kinds(self) -> None:
        graph = document(
            [input_node(), transform_node("step"), agent_node("worker"), output_node()],
            [*chain("idea", "step", "report"), member("m1", "worker", "step")],
        )
        problem = find(structural_problems(graph), MEMBER_TARGET_NOT_CREW)
        self.assertEqual(problem.node_id, "worker")
        self.assertEqual(problem.edge_id, "m1")
        self.assertIn("transform", problem.message)

    def test_a_transform_made_a_member_of_a_crew_is_refused_too(self) -> None:
        graph = document(
            [
                input_node(),
                authored_crew_node("team"),
                transform_node("step"),
                agent_node("m1"),
                output_node(),
            ],
            [
                *chain("idea", "team", "report"),
                member("mm", "m1", "team"),
                member("bad", "step", "team"),
            ],
        )
        self.assertIn(MEMBER_TARGET_NOT_CREW, error_codes(structural_problems(graph)))

    def test_a_member_agent_that_is_also_a_step_is_refused(self) -> None:
        graph = document(
            [
                input_node(),
                authored_crew_node("team"),
                agent_node("worker"),
                output_node(),
            ],
            [
                *chain("idea", "team", "report"),
                edge("x1", "idea", "worker"),
                member("m1", "worker", "team"),
            ],
        )
        problem = find(structural_problems(graph), MEMBER_AGENT_HAS_FLOW_EDGES)
        self.assertEqual(problem.node_id, "worker")
        self.assertIn("cannot be both", problem.message)

    def test_a_crew_member_count_fires_at_zero_and_at_n_plus_one_only(self) -> None:
        def graph(count: int) -> BuilderDocument:
            members = [f"m{index}" for index in range(count)]
            return document(
                [
                    input_node(),
                    authored_crew_node("team", task_order=members),
                    output_node(),
                    *[agent_node(name) for name in members],
                ],
                [
                    *chain("idea", "team", "report"),
                    *[member(f"mm{index}", name, "team") for index, name in enumerate(members)],
                ],
            )

        self.assertEqual(codes(structural_problems(graph(1))), [])
        self.assertEqual(codes(structural_problems(graph(MAX_CREW_MEMBERS))), [])

        empty = find(structural_problems(graph(0)), CREW_MEMBERS_OUT_OF_RANGE)
        self.assertIn("hands back nothing", empty.message)
        over = find(structural_problems(graph(MAX_CREW_MEMBERS + 1)), CREW_MEMBERS_OUT_OF_RANGE)
        self.assertIn(str(MAX_CREW_MEMBERS), over.message)

    def test_a_library_crew_takes_no_members_and_needs_none(self) -> None:
        library = document(
            [
                input_node(),
                node("team", "crew", {"crew_id": "scope", "tier": "cheap"}),
                output_node(),
            ],
            [*chain("idea", "team", "report")],
        )
        self.assertEqual(codes(structural_problems(library)), [])

        with_members = document(
            [
                input_node(),
                node("team", "crew", {"crew_id": "scope", "tier": "cheap"}),
                output_node(),
                agent_node("m1"),
            ],
            [*chain("idea", "team", "report"), member("mm", "m1", "team")],
        )
        problem = find(structural_problems(with_members), CREW_MEMBERS_OUT_OF_RANGE)
        self.assertIn("declares its own agents", problem.message)


# --------------------------------------------------------------------------
# The exclusions - the negative half, and the reason each one matters
# --------------------------------------------------------------------------
class ExclusionTests(unittest.TestCase):
    def test_one_tool_shared_by_five_agents_is_not_a_five_way_fan_out(self) -> None:
        """Fan-out counts OUTGOING edges, so the shape that exercises this is a
        shared tool rather than a well-equipped agent. Five agents holding one
        scraper is an ordinary graph; reported as a fan-out it would quote
        GitHub's rate limit at somebody who drew no branches at all."""

        count = MAX_FANOUT_WIDTH + 1
        holders = [f"h{index}" for index in range(count)]
        graph = document(
            [
                input_node(),
                *[agent_node(name) for name in holders],
                output_node(),
                tool_node("scraper"),
            ],
            [
                *chain("idea", *holders, "report"),
                *[attach(f"a{index}", "scraper", name) for index, name in enumerate(holders)],
            ],
        )
        self.assertEqual(codes(structural_problems(graph)), [])

    def test_one_agent_in_five_crews_is_not_a_five_way_fan_out_either(self) -> None:
        count = MAX_FANOUT_WIDTH + 1
        crews = [f"c{index}" for index in range(count)]
        graph = document(
            [
                input_node(),
                agent_node("m1"),
                *[authored_crew_node(name, task_order=["m1"]) for name in crews],
                output_node(),
            ],
            [
                *chain("idea", *crews, "report"),
                *[member(f"mm{index}", "m1", name) for index, name in enumerate(crews)],
            ],
        )
        self.assertEqual(codes(structural_problems(graph)), [])

    def test_a_member_edge_pointing_upstream_is_not_a_back_edge(self) -> None:
        """The exclusion is what keeps ONE mistake to ONE message.

        `idea -> team -> step -> m1` with `m1` a member of `team` is a document
        an author really can draw, and it is wrong for exactly one reason: `m1`
        cannot be both a member and a step. Count the member edge as flow and
        the DFS finds `m1 -> team` closing a loop onto a node still on the
        stack, so the author is additionally told that a loop-closing node must
        be a router - about an edge they drew to express membership.
        """

        graph = document(
            [
                input_node(),
                authored_crew_node("team", task_order=["m1"]),
                transform_node("step"),
                agent_node("m1"),
                output_node(),
            ],
            [
                *chain("idea", "team", "step", "m1"),
                edge("e_out", "m1", "report"),
                member("mm", "m1", "team"),
            ],
        )
        self.assertEqual(back_edges(graph), ())
        produced = codes(structural_problems(graph))
        self.assertIn(MEMBER_AGENT_HAS_FLOW_EDGES, produced)
        self.assertNotIn("back-edge-not-router", produced)
        self.assertNotIn("cycle-count", produced)

    def test_an_attach_edge_is_not_a_back_edge_even_pointing_upstream(self) -> None:
        graph = document(
            [input_node(), agent_node("worker"), output_node(), tool_node("scraper")],
            [*chain("idea", "worker", "report"), attach("a1", "scraper", "worker")],
        )
        self.assertEqual(back_edges(graph), ())

    def test_attachments_do_not_count_toward_the_graph_ceiling(self) -> None:
        """MAX_GRAPH_NODES is the frame ring's arithmetic, and these emit none."""

        flow = [input_node(), agent_node("worker"), output_node()]
        attachments = [tool_node(f"t{index}") for index in range(MAX_GRAPH_NODES)]
        graph = document(
            [*flow, *attachments],
            [
                *chain("idea", "worker", "report"),
                *[
                    attach(f"a{index}", f"t{index}", "worker")
                    for index in range(MAX_GRAPH_NODES)
                ],
            ],
        )
        self.assertGreater(len(graph.nodes), MAX_GRAPH_NODES)
        self.assertNotIn("node-count", codes(structural_problems(graph)))

    def test_a_member_adds_no_depth_to_the_crew_it_is_inside(self) -> None:
        """Depth is "how much upstream context does this node pay for on every
        call", and a member agent is not upstream of its crew - it is inside
        it. Counted as a predecessor it adds a billable level, and the crew is
        then priced for context produced by an agent whose output never leaves
        it."""

        plain = document(
            [input_node(), authored_crew_node("team"), output_node()],
            [*chain("idea", "team", "report")],
        )
        crewed = document(
            [
                input_node(),
                authored_crew_node("team", task_order=["m1"]),
                agent_node("m1"),
                output_node(),
            ],
            [*chain("idea", "team", "report"), member("mm", "m1", "team")],
        )
        self.assertEqual(billable_depths(plain)["report"], 1)
        self.assertEqual(billable_depths(crewed)["report"], 1)

    def test_attachments_add_no_depth_and_no_billable_context(self) -> None:
        """Depth is upstream context paid for per call; a tool produces none."""

        plain = document(
            [input_node(), agent_node("worker"), output_node()],
            [*chain("idea", "worker", "report")],
        )
        tooled = document(
            [input_node(), agent_node("worker"), output_node(), tool_node("scraper")],
            [*chain("idea", "worker", "report"), attach("a1", "scraper", "worker")],
        )
        self.assertEqual(billable_depths(plain)["report"], billable_depths(tooled)["report"])

    def test_a_member_agent_is_billed_inside_its_crew_and_not_again_as_a_node(self) -> None:
        """MAX_BILLABLE_NODES counts crews and NON-member agents (D2)."""

        members = [f"m{index}" for index in range(MAX_CREW_MEMBERS)]
        steps = [f"a{index}" for index in range(MAX_BILLABLE_NODES - 1)]
        graph = document(
            [
                input_node(),
                authored_crew_node("team", task_order=members),
                *[agent_node(name) for name in members],
                *[agent_node(name) for name in steps],
                output_node(),
            ],
            [
                *chain("idea", "team", *steps, "report"),
                *[member(f"mm{index}", name, "team") for index, name in enumerate(members)],
            ],
        )
        self.assertEqual(member_agent_ids(graph), frozenset(members))
        self.assertNotIn("billable-count", codes(structural_problems(graph)))

    def test_flow_edges_is_the_one_predicate_all_of_this_rests_on(self) -> None:
        graph = clean_graph()
        self.assertEqual(len(graph.edges), 9)
        self.assertEqual(len(flow_edges(graph)), 3)


if __name__ == "__main__":
    unittest.main()
