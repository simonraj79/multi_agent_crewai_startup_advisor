"""Structural validation of a builder document. Reports; never raises.

Every function here answers with a list of `Problem`s. That is the whole
contract, and it is not a style preference: an author is looking at a canvas
with a Save button, and the useful answer is "these four nodes are wrong",
each one selectable, not the first exception a validator happened to hit.
`document.py` raises, because a malformed *shape* is not a fixable position on a
canvas - it is a client sending something the schema does not have.

What is enforced here is the compile-time half of the bounds table: the counts
(nodes, billable nodes, escalation nodes, fan-out width, cycles, cycle
iterations), the router rules, the rule that a loop-closing node must be a
router, and the disjointness of the two compiled namespaces. `budget.py` adds
the dollar row on top, using this module's own cycle analysis.

THE ONE RULE THAT IS NOT A COUNT, and the reason this module exists at all:
**every node that closes a loop must be a router.** With the loop-closing node
compiled as plain code, the measured outcome is that the join fires once, the
second arrival is suppressed, and `kickoff()` RETURNS NORMALLY having produced
nothing - no exception, no warning, no frame. With the same node compiled as a
router emitting a label the join listens for, the cycle completes. CrewAI's own
exemption tests whether the LISTENER is a router, not the trigger, so nothing
downstream can rescue a plain node here.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from brief_crew.builder.document import (
    BILLABLE_KINDS,
    ROUTING_KINDS,
    BuilderDocument,
    BuilderEdge,
    GateConfig,
    InputConfig,
    RouterConfig,
)
from brief_crew.config import (
    BUILDER_EVENT_LABEL_PATTERN,
    BUILDER_GATE_ROUTER_PREFIX,
    BUILDER_METHOD_IDENT_PATTERN,
    MAX_BILLABLE_NODES,
    MAX_CYCLE_ITERATIONS,
    MAX_CYCLES,
    MAX_ESCALATION_NODES,
    MAX_FANOUT_WIDTH,
    MAX_GRAPH_NODES,
    MIN_ROUTER_BRANCHES,
)

Severity = Literal["error", "warning"]

# Problem codes. Named constants rather than inline strings because the canvas
# will branch on them (which node to select, which bound to quote) and the
# tests assert on them; a typo in a string literal would be a silently absent
# check on one side and a passing test on the other.
NODE_COUNT = "node-count"
DUPLICATE_NODE_ID = "duplicate-node-id"
DUPLICATE_EDGE_ID = "duplicate-edge-id"
EDGE_UNKNOWN_ENDPOINT = "edge-unknown-endpoint"
EDGE_UNKNOWN_PORT = "edge-unknown-port"
EDGE_TARGET_REFUSES_INCOMING = "edge-target-refuses-incoming"
BILLABLE_COUNT = "billable-count"
ESCALATION_COUNT = "escalation-count"
FANOUT_WIDTH = "fanout-width"
CYCLE_COUNT = "cycle-count"
CYCLE_ITERATIONS = "cycle-iterations"
ROUTER_BRANCH_COUNT = "router-branch-count"
ROUTER_OTHERWISE = "router-otherwise"
ROUTER_DUPLICATE_BRANCH = "router-duplicate-branch"
ROUTER_BRANCH_UNCONNECTED = "router-branch-unconnected"
BACK_EDGE_NOT_ROUTER = "back-edge-not-router"
IDENT_PATTERN = "ident-pattern"
IDENT_COLLISION = "ident-collision"
NO_INPUT_NODE = "no-input-node"
INPUT_FIELD_UNDECLARED = "input-field-undeclared"
INPUT_FIELD_AMBIGUOUS = "input-field-ambiguous"
NODE_UNREACHABLE = "node-unreachable"
NO_OUTPUT_NODE = "no-output-node"
JOIN_UNKNOWN_NODE = "join-unknown-node"
JOIN_SINGLE_PREDECESSOR = "join-single-predecessor"

_METHOD_IDENT = re.compile(BUILDER_METHOD_IDENT_PATTERN)
_EVENT_LABEL = re.compile(BUILDER_EVENT_LABEL_PATTERN)


@dataclass(frozen=True)
class Problem:
    """One thing wrong with a document, addressed to the person who drew it.

    `node_id` and `edge_id` are what the canvas selects and centres when the
    author clicks the entry, so a problem about a node carries the node even
    when it was found by counting edges.
    """

    code: str
    severity: Severity
    message: str
    node_id: str | None = None
    edge_id: str | None = None


def has_errors(problems: Iterable[Problem]) -> bool:
    """Whether anything here blocks a publish. Warnings do not."""

    return any(problem.severity == "error" for problem in problems)


# --------------------------------------------------------------------------
# Graph analysis - shared with budget.py, which prices what these find
# --------------------------------------------------------------------------
def _edges_by_source(document: BuilderDocument) -> dict[str, list[BuilderEdge]]:
    """Outgoing edges per node id, in document order (so results are stable)."""

    grouped: dict[str, list[BuilderEdge]] = defaultdict(list)
    for edge in document.edges:
        grouped[edge.source].append(edge)
    return grouped


def _indexed_edges_by_source(
    document: BuilderDocument,
) -> dict[str, list[tuple[int, BuilderEdge]]]:
    """Outgoing edges per node id, each paired with its document position."""

    grouped: dict[str, list[tuple[int, BuilderEdge]]] = defaultdict(list)
    for position, edge in enumerate(document.edges):
        grouped[edge.source].append((position, edge))
    return grouped


def _edges_by_target(document: BuilderDocument) -> dict[str, list[BuilderEdge]]:
    """Incoming edges per node id, in document order."""

    grouped: dict[str, list[BuilderEdge]] = defaultdict(list)
    for edge in document.edges:
        grouped[edge.target].append(edge)
    return grouped


def back_edge_indices(document: BuilderDocument) -> tuple[int, ...]:
    """Positions in `document.edges` of the edges that close a loop.

    Positions rather than the edges themselves, because two parallel edges
    between the same pair are equal as values and only their position tells
    them apart - and `budget.py` has to REMOVE exactly these to be left with a
    DAG it can compute a longest path over.
    """

    return tuple(index for index, _ in _back_edges_with_index(document))


def back_edges(document: BuilderDocument) -> tuple[BuilderEdge, ...]:
    """The edges that close a loop, found by depth-first search.

    An edge is a back edge when its target is still on the search stack, which
    is the textbook definition and the one that makes "remove these and the
    rest is a DAG" true - which is what `budget.py` relies on to compute a
    node's depth.

    The search starts at the `input` nodes so the numbering matches the way the
    graph actually runs, then sweeps any node the inputs cannot reach, so a
    detached cycle is still counted rather than silently free.
    """

    return tuple(edge for _, edge in _back_edges_with_index(document))


def _back_edges_with_index(document: BuilderDocument) -> tuple[tuple[int, BuilderEdge], ...]:
    """The loop-closing edges, each with its position in `document.edges`."""

    outgoing = _indexed_edges_by_source(document)
    known = {node.id for node in document.nodes}
    roots = [node.id for node in document.nodes if node.kind == "input"]
    roots += [node.id for node in document.nodes]

    state: dict[str, int] = {}  # 1 = on the stack, 2 = finished
    found: list[tuple[int, BuilderEdge]] = []
    for root in roots:
        if state.get(root):
            continue
        state[root] = 1
        stack: list[tuple[str, Iterator[tuple[int, BuilderEdge]]]] = [
            (root, iter(outgoing.get(root, ())))
        ]
        while stack:
            node_id, pending = stack[-1]
            descended = False
            for position, edge in pending:
                if edge.target not in known:
                    continue
                target_state = state.get(edge.target, 0)
                if target_state == 1:
                    found.append((position, edge))
                elif target_state == 0:
                    state[edge.target] = 1
                    stack.append((edge.target, iter(outgoing.get(edge.target, ()))))
                    descended = True
                    break
            if not descended:
                state[node_id] = 2
                stack.pop()
    return tuple(found)


def _reachable(
    starts: Iterable[str], adjacency: Mapping[str, Sequence[str]]
) -> set[str]:
    """Every node reachable from `starts`, inclusive, over `adjacency`."""

    seen: set[str] = set()
    queue = list(starts)
    while queue:
        node_id = queue.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        queue.extend(adjacency.get(node_id, ()))
    return seen


def nodes_on_cycles(document: BuilderDocument) -> frozenset[str]:
    """Every node that a back edge can carry round again.

    For a back edge u -> v, that is the nodes v can reach which can in turn
    reach u. This is what makes the static price honest about a loop: a cycle
    does not multiply the whole graph, it multiplies the nodes inside it.
    """

    loops = _back_edges_with_index(document)
    if not loops:
        return frozenset()

    known = {node.id for node in document.nodes}
    forward: dict[str, list[str]] = defaultdict(list)
    backward: dict[str, list[str]] = defaultdict(list)
    closing = {position for position, _ in loops}
    for position, edge in enumerate(document.edges):
        if position in closing or edge.source not in known or edge.target not in known:
            continue
        forward[edge.source].append(edge.target)
        backward[edge.target].append(edge.source)

    members: set[str] = set()
    for _, edge in loops:
        if edge.source not in known or edge.target not in known:
            continue
        members |= {edge.source, edge.target}
        members |= _reachable([edge.target], forward) & _reachable([edge.source], backward)
    return frozenset(members)


def billable_depths(document: BuilderDocument) -> dict[str, int]:
    """How many billable nodes sit upstream of each node, worst path.

    Back edges are removed first, so this is a longest path over a DAG and
    terminates. It is the term that makes a deep chain cost more than a wide
    fan-out of the same node count: every upstream node's output is context the
    next node pays for on every one of its calls.
    """

    loops = set(back_edge_indices(document))
    known = {node.id for node in document.nodes}
    nodes = document.nodes_by_id()

    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {node_id: 0 for node_id in known}
    for position, edge in enumerate(document.edges):
        if position in loops or edge.source not in known or edge.target not in known:
            continue
        outgoing[edge.source].append(edge.target)
        indegree[edge.target] += 1

    depth = {node_id: 0 for node_id in known}
    queue = [node.id for node in document.nodes if indegree[node.id] == 0]
    ordered: list[str] = []
    while queue:
        node_id = queue.pop(0)
        ordered.append(node_id)
        for target in outgoing.get(node_id, ()):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    for node_id in ordered:
        cost = 1 if nodes[node_id].is_billable else 0
        for target in outgoing.get(node_id, ()):
            depth[target] = max(depth[target], depth[node_id] + cost)
    return depth


def compiled_identifiers(
    document: BuilderDocument,
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """The flow method idents and router event labels this document compiles to.

    Returned per node id so a problem can name the node rather than the ident.
    A `gate` produces TWO methods - the pause and the deterministic router that
    reads its answer - and consumes two indices, which is why the second is not
    simply the first with a suffix.

    Generating them here, in the module that also asserts they are disjoint, is
    deliberate: the guarantee that `n...` and `e...` cannot collide is only ever
    worth what the generator does, and the generator is right here to be read.
    """

    methods: dict[str, tuple[str, ...]] = {}
    labels: dict[str, tuple[str, ...]] = {}
    loop_sources = {edge.source for edge in back_edges(document)}

    index = 0
    for node in document.nodes:
        own = [f"n{index}_{node.id}"]
        routing_index = index
        index += 1
        if node.kind == "gate":
            routing_index = index
            own.append(f"n{index}_{BUILDER_GATE_ROUTER_PREFIX}{node.id}")
            index += 1
        methods[node.id] = tuple(own)

        emitted = [f"e{routing_index}_{port}" for port in node.out_ports] if node.kind in ROUTING_KINDS else []
        # A loop-closing node also declares a rejoin label. Under the rule above
        # it is arguably redundant - a back edge can only leave a router or a
        # gate, and it leaves by a branch label that is already in `emitted` -
        # but the taxonomy declares it, and a namespace check that considers a
        # SUPERSET of what the compiler emits can only ever be conservative.
        if node.id in loop_sources:
            emitted.append(f"e{routing_index}_rejoin")
        labels[node.id] = tuple(emitted)
    return methods, labels


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------
def structural_problems(document: BuilderDocument) -> list[Problem]:
    """Every compile-time structural objection to this document.

    Ordered coarse to fine - counts, then wiring, then the compiled namespace -
    so the first entry in a canvas's error list is the one most likely to be
    the actual mistake.
    """

    problems: list[Problem] = []
    problems += _count_problems(document)
    problems += _identity_problems(document)
    problems += _edge_problems(document)
    problems += _router_problems(document)
    problems += _cycle_problems(document)
    problems += _input_output_problems(document)
    problems += _join_problems(document)
    problems += _identifier_problems(document)
    return problems


def _count_problems(document: BuilderDocument) -> list[Problem]:
    """The three node counts: total, billable, escalation."""

    problems: list[Problem] = []
    if len(document.nodes) > MAX_GRAPH_NODES:
        problems.append(
            Problem(
                code=NODE_COUNT,
                severity="error",
                message=(
                    f"this graph has {len(document.nodes)} nodes and the ceiling is "
                    f"{MAX_GRAPH_NODES} (MAX_GRAPH_NODES); above that a single pass of the "
                    "graph no longer fits comfortably in the 2,000-frame replay ring, and a "
                    "reconnecting client would receive an incomplete run with nothing saying so"
                ),
            )
        )

    billable = [node for node in document.nodes if node.kind in BILLABLE_KINDS]
    if len(billable) > MAX_BILLABLE_NODES:
        problems.append(
            Problem(
                code=BILLABLE_COUNT,
                severity="error",
                message=(
                    f"this graph has {len(billable)} nodes that call a model and the ceiling is "
                    f"{MAX_BILLABLE_NODES} (MAX_BILLABLE_NODES), which is the shipped "
                    "validator's 8 with the same 1.7 headroom MAX_GRAPH_NODES applies. This "
                    "bound is about shape rather than spend - what a graph COSTS is checked "
                    "separately, against the per-run ceiling, and that check names a dollar "
                    "figure you can act on"
                ),
            )
        )

    escalation = [node for node in billable if node.tier == "escalation"]
    if len(escalation) > MAX_ESCALATION_NODES:
        problems.append(
            Problem(
                code=ESCALATION_COUNT,
                severity="error",
                message=(
                    f"this graph puts {len(escalation)} nodes on the escalation tier and the "
                    f"ceiling is {MAX_ESCALATION_NODES} (MAX_ESCALATION_NODES), the validator's "
                    "own measured split of 5 escalation to 3 cheap carried up by the same "
                    "headroom as the node count. Move one to the cheap tier"
                ),
                node_id=escalation[MAX_ESCALATION_NODES].id,
            )
        )
    return problems


def _identity_problems(document: BuilderDocument) -> list[Problem]:
    """Duplicate node and edge ids, which make every later message ambiguous."""

    problems: list[Problem] = []
    for label, code, seen in (
        ("node", DUPLICATE_NODE_ID, [node.id for node in document.nodes]),
        ("edge", DUPLICATE_EDGE_ID, [edge.id for edge in document.edges]),
    ):
        counted: dict[str, int] = defaultdict(int)
        for identifier in seen:
            counted[identifier] += 1
        for identifier, count in counted.items():
            if count > 1:
                problems.append(
                    Problem(
                        code=code,
                        severity="error",
                        message=(
                            f"{count} {label}s share the id {identifier!r}; ids address a node "
                            "in every frame, every edge and every problem message, so they must "
                            "be unique"
                        ),
                        node_id=identifier if label == "node" else None,
                        edge_id=identifier if label == "edge" else None,
                    )
                )
    return problems


def _edge_problems(document: BuilderDocument) -> list[Problem]:
    """Endpoints that exist, ports that exist, and fan-out width."""

    problems: list[Problem] = []
    nodes = document.nodes_by_id()

    for edge in document.edges:
        for role, node_id in (("source", edge.source), ("target", edge.target)):
            if node_id not in nodes:
                problems.append(
                    Problem(
                        code=EDGE_UNKNOWN_ENDPOINT,
                        severity="error",
                        message=(
                            f"edge {edge.id!r} names {node_id!r} as its {role}, and no node has "
                            "that id"
                        ),
                        edge_id=edge.id,
                    )
                )
        source = nodes.get(edge.source)
        target = nodes.get(edge.target)
        if source is not None and edge.source_port not in source.out_ports:
            offered = ", ".join(source.out_ports) or "no outputs at all"
            problems.append(
                Problem(
                    code=EDGE_UNKNOWN_PORT,
                    severity="error",
                    message=(
                        f"edge {edge.id!r} leaves {edge.source!r} by the port "
                        f"{edge.source_port!r}, and a {source.kind} node offers {offered}"
                    ),
                    node_id=source.id,
                    edge_id=edge.id,
                )
            )
        if target is not None and not target.accepts_incoming:
            problems.append(
                Problem(
                    code=EDGE_TARGET_REFUSES_INCOMING,
                    severity="error",
                    message=(
                        f"edge {edge.id!r} arrives at {edge.target!r}, which is the graph's "
                        "input: an input node starts the run and has nothing upstream of it"
                    ),
                    node_id=target.id,
                    edge_id=edge.id,
                )
            )

    outgoing = _edges_by_source(document)
    for node in document.nodes:
        width = len(outgoing.get(node.id, ()))
        if width > MAX_FANOUT_WIDTH:
            problems.append(
                Problem(
                    code=FANOUT_WIDTH,
                    severity="error",
                    message=(
                        f"{node.id!r} fans out to {width} nodes and the ceiling is "
                        f"{MAX_FANOUT_WIDTH} (MAX_FANOUT_WIDTH), the validator's own measured "
                        "maximum. What this bounds is concurrent branches, and the real "
                        "constraint behind it is GitHub's 10 requests a minute per IP"
                    ),
                    node_id=node.id,
                )
            )
    return problems


def _router_problems(document: BuilderDocument) -> list[Problem]:
    """Branch count, exactly one `otherwise`, unique labels, all connected."""

    problems: list[Problem] = []
    outgoing = _edges_by_source(document)
    for node in document.nodes:
        if node.kind != "router" or not isinstance(node.config, RouterConfig):
            continue
        branches = node.config.branches
        if not MIN_ROUTER_BRANCHES <= len(branches) <= MAX_FANOUT_WIDTH:
            problems.append(
                Problem(
                    code=ROUTER_BRANCH_COUNT,
                    severity="error",
                    message=(
                        f"router {node.id!r} declares {len(branches)} branches; a router takes "
                        f"{MIN_ROUTER_BRANCHES} to {MAX_FANOUT_WIDTH}. Fewer than "
                        f"{MIN_ROUTER_BRANCHES} is a decision that cannot go either way, and "
                        f"more than {MAX_FANOUT_WIDTH} crosses MAX_FANOUT_WIDTH"
                    ),
                    node_id=node.id,
                )
            )

        otherwise = [branch for branch in branches if branch.is_otherwise]
        if len(otherwise) != 1:
            problems.append(
                Problem(
                    code=ROUTER_OTHERWISE,
                    severity="error",
                    message=(
                        f"router {node.id!r} declares {len(otherwise)} otherwise branches and "
                        "must declare exactly one. Without it a value that matches no "
                        "comparison wedges the run at this router; with two, which one takes "
                        "an unmatched value is a coin toss written into the document"
                    ),
                    node_id=node.id,
                )
            )

        counted: dict[str, int] = defaultdict(int)
        for branch in branches:
            counted[branch.label] += 1
        for label, count in counted.items():
            if count > 1:
                problems.append(
                    Problem(
                        code=ROUTER_DUPLICATE_BRANCH,
                        severity="error",
                        message=(
                            f"router {node.id!r} declares the branch {label!r} {count} times; a "
                            "branch label is the port an edge leaves by, so a duplicate makes "
                            "the drawn edge ambiguous"
                        ),
                        node_id=node.id,
                    )
                )

        drawn = {edge.source_port for edge in outgoing.get(node.id, ())}
        for branch in branches:
            if branch.label not in drawn:
                problems.append(
                    Problem(
                        code=ROUTER_BRANCH_UNCONNECTED,
                        severity="warning",
                        message=(
                            f"router {node.id!r} declares the branch {branch.label!r} and no "
                            "edge leaves by it, so a run taking that branch stops here. That is "
                            "legal - it is how a graph ends early - but it is rarely intended"
                        ),
                        node_id=node.id,
                    )
                )
    return problems


def _cycle_problems(document: BuilderDocument) -> list[Problem]:
    """The cycle count, the router-back-edge rule, and gate revise turns."""

    problems: list[Problem] = []
    nodes = document.nodes_by_id()
    loops = back_edges(document)

    if len(loops) > MAX_CYCLES:
        problems.append(
            Problem(
                code=CYCLE_COUNT,
                severity="error",
                message=(
                    f"this graph closes {len(loops)} loops and the ceiling is {MAX_CYCLES} "
                    "(MAX_CYCLES), the validator's own measured back-edge count. Each loop "
                    "multiplies the price of every node inside it"
                ),
                edge_id=loops[MAX_CYCLES].id,
            )
        )

    for edge in loops:
        source = nodes.get(edge.source)
        if source is None or source.kind in ROUTING_KINDS:
            continue
        problems.append(
            Problem(
                code=BACK_EDGE_NOT_ROUTER,
                severity="error",
                message=(
                    f"edge {edge.id!r} closes a loop from {edge.source!r} back to "
                    f"{edge.target!r}, and {edge.source!r} is a {source.kind} node. A "
                    "loop-closing node MUST be a router: insert a router node between "
                    f"{edge.source!r} and {edge.target!r} and draw the back edge from that "
                    "router instead. This is measured, not cautious - with a plain node here "
                    "the join fires once, the second arrival is suppressed, and the run ends "
                    "normally having produced nothing, with no exception and no warning"
                ),
                node_id=source.id,
                edge_id=edge.id,
            )
        )

    for node in document.nodes:
        if node.kind != "gate" or not isinstance(node.config, GateConfig):
            continue
        if node.config.max_turns > MAX_CYCLE_ITERATIONS:
            problems.append(
                Problem(
                    code=CYCLE_ITERATIONS,
                    severity="error",
                    # No dollar figure here, and that is the same correction
                    # BILLABLE_COUNT and ESCALATION_COUNT already carry. The
                    # only figure available at this line is a FLOOR - the
                    # published cheap-tier price, before the `:nitro` spread -
                    # and comparing a floor against the ENFORCED ceiling is the
                    # category error MAX_CYCLE_ITERATIONS' own note in
                    # config.py draws in as many words. What a graph costs is
                    # checked separately, against the per-run ceiling, and that
                    # check names a figure an author can act on.
                    message=(
                        f"gate {node.id!r} allows {node.config.max_turns} revise turns and the "
                        f"ceiling is {MAX_CYCLE_ITERATIONS} (MAX_CYCLE_ITERATIONS), because a "
                        "revise loop is a cycle and every node on one is billed again each time "
                        "round. It is deliberately below the validator's own 5: that number "
                        "prices a human in the loop, who is both the cause of the delay and the "
                        "brake on it, and a builder cycle need not have one"
                    ),
                    node_id=node.id,
                )
            )
    return problems


def _input_output_problems(document: BuilderDocument) -> list[Problem]:
    """One declared input field, and every node reachable from an input."""

    problems: list[Problem] = []
    inputs = [node for node in document.nodes if node.kind == "input"]
    if not inputs:
        problems.append(
            Problem(
                code=NO_INPUT_NODE,
                severity="error",
                message=(
                    "this graph has no input node, so there is nothing to seed a run with and "
                    "no field for the run request to carry"
                ),
            )
        )

    declaring = [
        node
        for node in inputs
        if isinstance(node.config, InputConfig) and node.config.field == document.input_field
    ]
    if inputs and not declaring:
        offered = ", ".join(
            sorted(node.config.field for node in inputs if isinstance(node.config, InputConfig))
        )
        problems.append(
            Problem(
                code=INPUT_FIELD_UNDECLARED,
                severity="error",
                message=(
                    f"the document declares input_field {document.input_field!r} and no input "
                    f"node asks for it; the input nodes ask for {offered}"
                ),
            )
        )
    elif len(declaring) > 1:
        problems.append(
            Problem(
                code=INPUT_FIELD_AMBIGUOUS,
                severity="error",
                message=(
                    f"{len(declaring)} input nodes both ask for {document.input_field!r}; the "
                    "run request carries one value under that name and there would be no "
                    "saying which node it seeded"
                ),
                node_id=declaring[1].id,
            )
        )

    if inputs:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in document.edges:
            adjacency[edge.source].append(edge.target)
        reached = _reachable([node.id for node in inputs], adjacency)
        for node in document.nodes:
            if node.id not in reached:
                problems.append(
                    Problem(
                        code=NODE_UNREACHABLE,
                        severity="error",
                        message=(
                            f"nothing leads to {node.id!r} from an input node, so it can never "
                            "run. Connect it, or delete it"
                        ),
                        node_id=node.id,
                    )
                )

    if not any(node.kind == "output" for node in document.nodes):
        problems.append(
            Problem(
                code=NO_OUTPUT_NODE,
                severity="warning",
                message=(
                    "this graph has no output node, so a completed run hands back no body. "
                    "Everything it produced would be visible only as streamed frames"
                ),
            )
        )
    return problems


def _join_problems(document: BuilderDocument) -> list[Problem]:
    """`joins` must name real nodes, and a join wants something to join."""

    problems: list[Problem] = []
    nodes = document.nodes_by_id()
    incoming = _edges_by_target(document)
    for node_id in document.joins:
        if node_id not in nodes:
            problems.append(
                Problem(
                    code=JOIN_UNKNOWN_NODE,
                    severity="error",
                    message=f"joins names {node_id!r}, and no node has that id",
                )
            )
            continue
        arrivals = len(incoming.get(node_id, ()))
        if arrivals < 2:
            problems.append(
                Problem(
                    code=JOIN_SINGLE_PREDECESSOR,
                    severity="warning",
                    message=(
                        f"{node_id!r} is declared a join and {arrivals} edge(s) arrive at it. "
                        "A join over one edge is the same as no join at all"
                    ),
                    node_id=node_id,
                )
            )
    return problems


def _identifier_problems(document: BuilderDocument) -> list[Problem]:
    """The compiled namespace: every ident legal, and the two sets disjoint.

    Method idents all begin `n` and event labels all begin `e`, so a collision
    should be impossible. The assertion is here anyway, because that guarantee
    is a property of the generator rather than of the design, and a generator
    can be changed by somebody who has not read this comment.
    """

    problems: list[Problem] = []
    methods, labels = compiled_identifiers(document)

    for node_id, idents in methods.items():
        for ident in idents:
            if not _METHOD_IDENT.match(ident):
                problems.append(
                    Problem(
                        code=IDENT_PATTERN,
                        severity="error",
                        message=(
                            f"{node_id!r} compiles to the flow method {ident!r}, which does not "
                            f"match {BUILDER_METHOD_IDENT_PATTERN}. A gate compiles to two "
                            f"methods and the second is prefixed "
                            f"{BUILDER_GATE_ROUTER_PREFIX!r}, so a gate's id has six characters "
                            "less room than any other node's; shorten it"
                        ),
                        node_id=node_id,
                    )
                )
    for node_id, emitted in labels.items():
        for label in emitted:
            if not _EVENT_LABEL.match(label):
                problems.append(
                    Problem(
                        code=IDENT_PATTERN,
                        severity="error",
                        message=(
                            f"{node_id!r} emits the router label {label!r}, which does not match "
                            f"{BUILDER_EVENT_LABEL_PATTERN}; shorten the node id or the branch "
                            "label"
                        ),
                        node_id=node_id,
                    )
                )

    all_methods = [ident for idents in methods.values() for ident in idents]
    all_labels = [label for emitted in labels.values() for label in emitted]
    collisions = sorted(set(all_methods) & set(all_labels))
    if collisions:
        problems.append(
            Problem(
                code=IDENT_COLLISION,
                severity="error",
                message=(
                    "the compiled flow method names and the router event labels share "
                    f"{', '.join(collisions)}. They are separate namespaces to CrewAI and one "
                    "name in both is a listener that fires on the wrong thing"
                ),
            )
        )
    for group, kind in ((all_methods, "flow method"), (all_labels, "router label")):
        counted: dict[str, int] = defaultdict(int)
        for name in group:
            counted[name] += 1
        for name, count in sorted(counted.items()):
            if count > 1:
                problems.append(
                    Problem(
                        code=IDENT_COLLISION,
                        severity="error",
                        message=(
                            f"{count} nodes compile to the same {kind} {name!r}; frames from "
                            "both would attribute to one node"
                        ),
                    )
                )
    return problems
