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
    ATTACH_SOURCE_KINDS,
    ATTACH_TARGET_KINDS,
    ATTACHMENT_KINDS,
    BILLABLE_KINDS,
    MEMBER_SOURCE_KINDS,
    MEMBER_TARGET_KINDS,
    ROUTING_KINDS,
    AuthoredCrewConfig,
    BuilderDocument,
    BuilderEdge,
    BuilderNode,
    GateConfig,
    InputConfig,
    McpConfig,
    RouterConfig,
    SkillConfig,
)
from brief_crew.config import (
    BUILDER_ERROR_ROUTER_PREFIX,
    BUILDER_EVENT_LABEL_PATTERN,
    BUILDER_GATE_ROUTER_PREFIX,
    BUILDER_METHOD_IDENT_PATTERN,
    BUILDER_STATE_ERROR_PREFIX,
    BUILDER_STATE_OUTPUT_PREFIX,
    MAX_ATTACHMENT_NODES,
    MAX_ATTACHMENTS_PER_NODE,
    MAX_BILLABLE_NODES,
    MAX_CREW_MEMBERS,
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
ATTACH_TARGET_NOT_AGENT = "attach-target-not-agent"
MEMBER_TARGET_NOT_CREW = "member-target-not-crew"
MEMBER_AGENT_HAS_FLOW_EDGES = "member-agent-has-flow-edges"
ATTACHMENT_UNATTACHED = "attachment-unattached"
ATTACHMENTS_OVER_MAX = "attachments-over-max"
ATTACHMENT_NODES_OVER_MAX = "attachment-nodes-over-max"
CREW_MEMBERS_OUT_OF_RANGE = "crew-members-out-of-range"

# 09-compiler.md's four, added 2026-09-04 with the authored compile path.
#
# The first two are about `document.state` (D6): the compiler OWNS `out__*`,
# `err__*`, `turns__*`, `__builder__` and the input field, and a declared key
# under one of those names would let a request body overwrite a node's output.
# The third is the `on_error: route` port with nothing drawn from it - legal,
# and almost certainly not what was meant. The fourth is what an IMPORTED graph
# looks like: `export.py` strips `server_id` and `skill_id` deliberately, so a
# node whose reference did not survive is an author-visible problem rather than
# a crash inside the compiler.
STATE_KEY_RESERVED = "state-key-reserved"
STATE_SCHEMA_INVALID = "state-schema-invalid"
ERROR_PORT_UNCONNECTED = "error-port-unconnected"
ATTACHMENT_REFERENCE_MISSING = "attachment-reference-missing"

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
    #: WHICH CONTROL, when the code alone cannot say - C8's optional `field`,
    #: requested by 04 D7 and consumed by `useBuilderProblems.fieldFor`.
    #:
    #: The client's `FIELD_CODES` holds ONE string per code, which is the right
    #: shape for `router-branch-count` and the wrong shape for the three codes
    #: whose control varies with the document: `model-lacks-capability` blames
    #: `llm.response_format` on one node and `llm.reasoning_effort` on the next.
    #: Those checks already know the answer - `_capability_problems` takes the
    #: field name as an argument - so naming it here costs nothing and is the
    #: only way the inspector can open the right disclosure and focus the right
    #: control.
    #:
    #: `None` on every problem whose code already answers the question. A client
    #: that has never heard of this key falls back to its own map, which is what
    #: makes adding it additive.
    field: str | None = None


def has_errors(problems: Iterable[Problem]) -> bool:
    """Whether anything here blocks a publish. Warnings do not."""

    return any(problem.severity == "error" for problem in problems)


# --------------------------------------------------------------------------
# Graph analysis - shared with budget.py, which prices what these find
# --------------------------------------------------------------------------
def is_flow_edge(edge: BuilderEdge) -> bool:
    """Whether this edge is the FLOW - the thing that happens next.

    `attach` and `member` edges are structural: they say what a node HAS, not
    where the run goes. **Every graph question in this module asks it through
    here**, and 03-node-library.md D2 is a list of the consequences: an agent
    holding three tools has not fanned out three ways, a tool cannot be part of
    a cycle, and a crew's members are not three more steps between its input
    and its output.

    Getting this wrong is not a wrong number, it is a wrong SHAPE - a
    fan-out-width error on a well-drawn agent, a `back-edge-not-router` on a
    tool, and a `billable_depths` that charges an author for their own
    attachments. Edge class is a pure function of `target_port` and of nothing
    else, which is what keeps this one line the whole rule.
    """

    return edge.target_port == "in"


def flow_edges(document: BuilderDocument) -> tuple[BuilderEdge, ...]:
    """Just the edges the run travels along."""

    return tuple(edge for edge in document.edges if is_flow_edge(edge))


def attachment_edges(document: BuilderDocument) -> tuple[BuilderEdge, ...]:
    """Just the `attach` edges - what each agent or crew HAS."""

    return tuple(edge for edge in document.edges if edge.target_port == "attach")


def member_edges(document: BuilderDocument) -> tuple[BuilderEdge, ...]:
    """Just the `member` edges - which agents are inside which crew."""

    return tuple(edge for edge in document.edges if edge.target_port == "member")


def member_agent_ids(document: BuilderDocument) -> frozenset[str]:
    """Agents that are inside a crew, and so are not steps of their own.

    A member agent is billable INSIDE its crew - the crew's price multiplies by
    its membership (09) - and counting it again against MAX_BILLABLE_NODES
    would charge the same agent twice against a bound that is about shape.
    """

    return frozenset(edge.source for edge in member_edges(document))


def routes_errors(node: BuilderNode) -> bool:
    """Whether this node's failure takes an `error` port instead of ending the run."""

    return getattr(node.config, "on_error", None) == "route"


def error_router_labels(node: BuilderNode) -> tuple[str, ...]:
    """The two event labels an `on_error: route` node's paired router emits.

    `ok` and `error`, NOT the port names `out` and `error` - C5 spells them that
    way and the asymmetry is worth keeping: `out` is where the value goes and
    `ok` is what happened, and a label named after a port would read as though
    the router were choosing a port rather than reporting an outcome.
    """

    return ("ok", "error") if routes_errors(node) and node.kind not in ROUTING_KINDS else ()


def is_routed(node: BuilderNode) -> bool:
    """Whether this node compiles a router at all - a gate, a router, or an error port."""

    return node.kind in ROUTING_KINDS or routes_errors(node)


def member_of(document: BuilderDocument) -> dict[str, str]:
    """Member agent id -> the crew it is inside. Last member edge wins."""

    return {edge.source: edge.target for edge in member_edges(document)}


def step_nodes(document: BuilderDocument) -> tuple[BuilderNode, ...]:
    """The nodes that become FLOW METHODS, in document order.

    Two families are excluded and neither is a step. An ATTACHMENT is something
    an agent HAS: it never runs, so there is no moment at which the flow would
    move on from it. A MEMBER agent runs inside its crew, in the crew's own
    order, so compiling it as a method too would run it twice and leave nothing
    downstream able to say which output it was reading - which is exactly what
    `member-agent-has-flow-edges` refuses an author for drawing.
    """

    members = member_of(document)
    return tuple(
        node
        for node in document.nodes
        if node.kind not in ATTACHMENT_KINDS and node.id not in members
    )


def _edges_by_source(document: BuilderDocument) -> dict[str, list[BuilderEdge]]:
    """Outgoing FLOW edges per node id, in document order (so results are stable)."""

    grouped: dict[str, list[BuilderEdge]] = defaultdict(list)
    for edge in document.edges:
        if is_flow_edge(edge):
            grouped[edge.source].append(edge)
    return grouped


def _indexed_edges_by_source(
    document: BuilderDocument,
) -> dict[str, list[tuple[int, BuilderEdge]]]:
    """Outgoing FLOW edges per node id, each paired with its document position.

    The position is into `document.edges` - the WHOLE list, attachments and all
    - because `back_edge_indices` publishes positions and `budget.py` removes
    exactly those to be left with a DAG. Filtering during the walk rather than
    re-indexing a filtered list is what keeps those positions meaningful.
    """

    grouped: dict[str, list[tuple[int, BuilderEdge]]] = defaultdict(list)
    for position, edge in enumerate(document.edges):
        if is_flow_edge(edge):
            grouped[edge.source].append((position, edge))
    return grouped


def _edges_by_target(document: BuilderDocument) -> dict[str, list[BuilderEdge]]:
    """Incoming FLOW edges per node id, in document order."""

    grouped: dict[str, list[BuilderEdge]] = defaultdict(list)
    for edge in document.edges:
        if is_flow_edge(edge):
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
        if (
            position in closing
            or not is_flow_edge(edge)
            or edge.source not in known
            or edge.target not in known
        ):
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
        if (
            position in loops
            or not is_flow_edge(edge)
            or edge.source not in known
            or edge.target not in known
        ):
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
    for node in step_nodes(document):
        own = [f"n{index}_{node.id}"]
        routing_index = index
        index += 1
        if node.kind == "gate":
            routing_index = index
            own.append(f"n{index}_{BUILDER_GATE_ROUTER_PREFIX}{node.id}")
            index += 1
        elif routes_errors(node):
            # 09 D3: a step whose `on_error` is `route` compiles to TWO methods
            # for the same reason a gate does - only a `@router` can choose an
            # event, so the step records `err__<node>` and a paired router reads
            # it. The second index is consumed here so the two generators cannot
            # drift; the compiler asserts they have not.
            routing_index = index
            own.append(f"n{index}_{BUILDER_ERROR_ROUTER_PREFIX}{node.id}")
            index += 1
        methods[node.id] = tuple(own)

        emitted = [f"e{routing_index}_{port}" for port in error_router_labels(node) or node.out_ports] if is_routed(node) else []
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
    problems += _attachment_problems(document)
    problems += _membership_problems(document)
    problems += _router_problems(document)
    problems += _cycle_problems(document)
    problems += _input_output_problems(document)
    problems += _join_problems(document)
    problems += _state_problems(document)
    problems += _error_port_problems(document)
    problems += _identifier_problems(document)
    return problems


def _count_problems(document: BuilderDocument) -> list[Problem]:
    """The node counts: total, attachments, billable, escalation.

    **`MAX_GRAPH_NODES` counts FLOW nodes only** (D2). The 24 is derived from
    the frame ring - 24 nodes at the production rate of ~7 frames each is ~175
    frames against a 2,000-frame ring - and an attachment emits no frames at
    all, so counting one against that ceiling would be applying an arithmetic
    to a thing it was not about. Attachments have their own count below.
    """

    problems: list[Problem] = []
    flow_nodes = [node for node in document.nodes if node.kind not in ATTACHMENT_KINDS]
    attachments = [node for node in document.nodes if node.kind in ATTACHMENT_KINDS]

    if len(attachments) > MAX_ATTACHMENT_NODES:
        problems.append(
            Problem(
                code=ATTACHMENT_NODES_OVER_MAX,
                severity="error",
                message=(
                    f"this graph has {len(attachments)} tool, MCP and skill nodes and the "
                    f"ceiling is {MAX_ATTACHMENT_NODES} (MAX_ATTACHMENT_NODES). Attachments "
                    "are counted separately from steps - they never run and never bill - so "
                    "this is a bound on the document rather than on what the run costs"
                ),
                node_id=attachments[MAX_ATTACHMENT_NODES].id,
            )
        )

    if len(flow_nodes) > MAX_GRAPH_NODES:
        problems.append(
            Problem(
                code=NODE_COUNT,
                severity="error",
                message=(
                    f"this graph has {len(flow_nodes)} nodes and the ceiling is "
                    f"{MAX_GRAPH_NODES} (MAX_GRAPH_NODES); above that a single pass of the "
                    "graph no longer fits comfortably in the 2,000-frame replay ring, and a "
                    "reconnecting client would receive an incomplete run with nothing saying so"
                ),
            )
        )

    # A MEMBER agent is billable inside its crew, not as a node of its own: the
    # crew's price multiplies by its membership (09), so counting the agent
    # again here would charge one agent twice against a bound about shape.
    members = member_agent_ids(document)
    billable = [
        node
        for node in document.nodes
        if node.kind in BILLABLE_KINDS and node.id not in members
    ]
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
            # Four kinds refuse an inbound edge, for two different reasons, and
            # the sentence has to give the right one - "an input node starts the
            # run" said about a tool is a message an author cannot act on.
            because = (
                "an input node starts the run and has nothing upstream of it"
                if target.kind == "input"
                else (
                    f"a {target.kind} node is something an agent HAS, not a step: it is "
                    "reached by attaching it to an agent, and nothing ever flows into it"
                )
            )
            problems.append(
                Problem(
                    code=EDGE_TARGET_REFUSES_INCOMING,
                    severity="error",
                    message=f"edge {edge.id!r} arrives at {edge.target!r}, and {because}",
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


def _attachment_problems(document: BuilderDocument) -> list[Problem]:
    """The `attach` class: who may reach whom, how many, and who is left hanging.

    Three rules, and the first is the one that carries the family's whole
    meaning: an attachment reaches an agent, never the other way round and
    never as a step. Drawing it that way is what makes the edge class a pure
    function of `target_port` - there is no second rule about what the source
    happened to be, only this check that the pair agrees.
    """

    problems: list[Problem] = []
    nodes = document.nodes_by_id()

    for edge in document.edges:
        source = nodes.get(edge.source)
        target = nodes.get(edge.target)
        if source is None or target is None:
            # `edge-unknown-endpoint` has already said so, and a second sentence
            # about an edge one of whose ends does not exist is noise.
            continue

        if not target.accepts_incoming:
            # `edge-target-refuses-incoming` has already named this one, and it
            # names it for the right reason - two rows in the dock for one
            # dropped edge is how a problems panel becomes unreadable.
            continue

        if edge.target_port == "attach":
            if source.kind not in ATTACH_SOURCE_KINDS or target.kind not in ATTACH_TARGET_KINDS:
                problems.append(
                    Problem(
                        code=ATTACH_TARGET_NOT_AGENT,
                        severity="error",
                        message=(
                            f"edge {edge.id!r} attaches a {source.kind} node to a "
                            f"{target.kind} node. An attach edge runs from a tool, an MCP "
                            "server or a skill TO an agent or a crew, and only that way: it "
                            "says what that agent has, so there is nothing for it to mean "
                            "in any other direction"
                        ),
                        node_id=source.id,
                        edge_id=edge.id,
                    )
                )
        elif is_flow_edge(edge) and source.kind in ATTACHMENT_KINDS:
            problems.append(
                Problem(
                    code=ATTACH_TARGET_NOT_AGENT,
                    severity="error",
                    message=(
                        f"edge {edge.id!r} leaves the {source.kind} node {source.id!r} as a "
                        "flow edge, and an attachment is not a step: it never runs, so there "
                        f"is no moment at which the run would move on from it. Drop it onto "
                        f"{edge.target!r}'s attach port instead"
                    ),
                    node_id=source.id,
                    edge_id=edge.id,
                )
            )

    held: dict[str, int] = defaultdict(int)
    attached: set[str] = set()
    for edge in attachment_edges(document):
        held[edge.target] += 1
        attached.add(edge.source)
    for node_id, count in held.items():
        if count > MAX_ATTACHMENTS_PER_NODE:
            problems.append(
                Problem(
                    code=ATTACHMENTS_OVER_MAX,
                    severity="error",
                    message=(
                        f"{node_id!r} holds {count} attachments and the ceiling is "
                        f"{MAX_ATTACHMENTS_PER_NODE} (MAX_ATTACHMENTS_PER_NODE). What this "
                        "bounds is the agent's system prompt rather than the run's price: "
                        "every attachment contributes a tool schema or a skill preamble, and "
                        "past some width an agent stops choosing between them well"
                    ),
                    node_id=node_id,
                )
            )

    for edge in attachment_edges(document):
        source = nodes.get(edge.source)
        if source is None:
            continue
        config = source.config
        missing = None
        if isinstance(config, McpConfig) and not config.server_id:
            missing = "MCP server"
        elif isinstance(config, SkillConfig) and not config.skill_id:
            missing = "skill"
        if missing is None:
            continue
        problems.append(
            Problem(
                code=ATTACHMENT_REFERENCE_MISSING,
                severity="error",
                message=(
                    f"{source.id!r} is attached to {edge.target!r} and names no {missing}. "
                    "An exported graph has this shape on purpose - the reference pointed at "
                    "a row in the exporting author's own library and could not travel - so "
                    "pick one of yours before this graph will run"
                ),
                node_id=source.id,
                edge_id=edge.id,
            )
        )

    for node in document.nodes:
        if node.kind in ATTACHMENT_KINDS and node.id not in attached:
            problems.append(
                Problem(
                    code=ATTACHMENT_UNATTACHED,
                    severity="warning",
                    message=(
                        f"{node.id!r} is a {node.kind} node attached to nothing, so nothing "
                        "in this graph can use it. That is legal - it is what a node looks "
                        "like the moment it is dropped - but a run would never reach it"
                    ),
                    node_id=node.id,
                )
            )
    return problems


def _membership_problems(document: BuilderDocument) -> list[Problem]:
    """The `member` class: who may be inside a crew, and how many.

    A member agent is a crew's agent and not a step of the flow, which is why
    the third rule exists: an agent that is BOTH - inside a crew and wired into
    the flow - would run twice, once as itself and once as part of its crew,
    and nothing downstream could tell which output it was reading.
    """

    problems: list[Problem] = []
    nodes = document.nodes_by_id()
    members: dict[str, list[str]] = defaultdict(list)

    for edge in member_edges(document):
        source = nodes.get(edge.source)
        target = nodes.get(edge.target)
        if source is None or target is None:
            continue
        if source.kind not in MEMBER_SOURCE_KINDS or target.kind not in MEMBER_TARGET_KINDS:
            problems.append(
                Problem(
                    code=MEMBER_TARGET_NOT_CREW,
                    severity="error",
                    message=(
                        f"edge {edge.id!r} makes a {source.kind} node a member of a "
                        f"{target.kind} node. Membership runs from an agent TO a crew: a "
                        "crew is a team of agents, and nothing else can be one of them"
                    ),
                    node_id=source.id,
                    edge_id=edge.id,
                )
            )
            continue
        members[target.id].append(source.id)

    flow_touched: dict[str, list[str]] = defaultdict(list)
    for edge in document.edges:
        if not is_flow_edge(edge):
            continue
        for node_id in (edge.source, edge.target):
            flow_touched[node_id].append(edge.id)

    for agent_id in sorted(member_agent_ids(document)):
        drawn = flow_touched.get(agent_id, [])
        if not drawn:
            continue
        problems.append(
            Problem(
                code=MEMBER_AGENT_HAS_FLOW_EDGES,
                severity="error",
                message=(
                    f"{agent_id!r} is a member of a crew and also carries "
                    f"{len(drawn)} flow edge(s). It cannot be both: as a member it runs "
                    "inside its crew, in the crew's own order, and as a step it runs again "
                    "on its own - so nothing downstream could say which of the two outputs "
                    "it was reading. Remove the flow edges, or the member edge"
                ),
                node_id=agent_id,
                edge_id=drawn[0],
            )
        )

    for node in document.nodes:
        if node.kind != "crew":
            continue
        count = len(members.get(node.id, ()))
        authored = isinstance(node.config, AuthoredCrewConfig)
        if authored and not 1 <= count <= MAX_CREW_MEMBERS:
            problems.append(
                Problem(
                    code=CREW_MEMBERS_OUT_OF_RANGE,
                    severity="error",
                    message=(
                        f"the authored crew {node.id!r} has {count} member agents and a crew "
                        f"takes 1 to {MAX_CREW_MEMBERS} (MAX_CREW_MEMBERS, the shipped "
                        "validator's own six). With none it compiles to a Crew with no tasks "
                        "and hands back nothing; the ceiling is the largest team this "
                        "repository has ever run"
                    ),
                    node_id=node.id,
                )
            )
        elif not authored and count:
            problems.append(
                Problem(
                    code=CREW_MEMBERS_OUT_OF_RANGE,
                    severity="error",
                    message=(
                        f"{node.id!r} names a registered crew and has {count} member agents "
                        "drawn into it. A registered crew declares its own agents in Python, "
                        "and members drawn here would be silently ignored - which is why "
                        "they are refused instead"
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
        for edge in flow_edges(document):
            adjacency[edge.source].append(edge.target)
        reached = _reachable([node.id for node in inputs], adjacency)
        members = member_agent_ids(document)
        for node in document.nodes:
            # Two families are reachable along something OTHER than a flow edge,
            # and asking this question of them gets the wrong answer for both.
            #
            # An ATTACHMENT is never reachable from an input and never should
            # be: nothing flows into a possession. Whether it is attached at all
            # is `attachment-unattached`'s question, and answering it twice -
            # once as a warning about the thing and once as an error about the
            # graph - would put two rows in the dock for one omission.
            #
            # A MEMBER agent is reached through its crew, which is a step and is
            # checked here in its own right. If the crew is unreachable the crew
            # says so, and one row is the right number.
            if node.kind in ATTACHMENT_KINDS or node.id in members:
                continue
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


#: What a declared state key may not be called, because the compiler owns it.
#: `_Plan.state_default()` writes every one of these, and a document key under
#: the same name would let a run request overwrite a node's output, a node's
#: failure, or a gate's turn counter.
def _reserved_state_prefixes() -> tuple[str, ...]:
    # Imported inside the function: two of the three live in `runtime.py`, which
    # is a wire detail between two modules of this package rather than a
    # platform constant, and a module-level import would make `bounds` depend on
    # the module that loads YAML.
    from brief_crew.builder.runtime import BUILDER_STATE_TURNS_PREFIX

    return (
        BUILDER_STATE_OUTPUT_PREFIX,
        BUILDER_STATE_ERROR_PREFIX,
        BUILDER_STATE_TURNS_PREFIX,
    )


#: The four python types the four declared scalar types accept as a default.
#: `bool` is checked BEFORE `int` deliberately: `isinstance(True, int)` is
#: `True` in python, so an integer field defaulting to `True` would validate.
_STATE_DEFAULT_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (float, int),
    "integer": (int,),
    "boolean": (bool,),
}


def _state_problems(document: BuilderDocument) -> list[Problem]:
    """`document.state` (09 D6): reserved keys refused, defaults typed.

    Reported rather than raised, both of them, because both are positions on a
    canvas: a key with a reserved name is renamed in the state panel, and a
    default of the wrong type is retyped in the same box that declared it.
    """

    problems: list[Problem] = []
    declared = document.state
    if declared is None:
        return problems

    from brief_crew.builder.runtime import BUILDER_STATE_KEY

    reserved = _reserved_state_prefixes()
    for key, field in declared.fields.items():
        if key == BUILDER_STATE_KEY or key.startswith(reserved):
            problems.append(
                Problem(
                    code=STATE_KEY_RESERVED,
                    severity="error",
                    message=(
                        f"the state key {key!r} is one the compiler owns "
                        f"({BUILDER_STATE_KEY}, and anything starting "
                        f"{', '.join(reserved)}). A declared key under that name would be "
                        "overwritten by a node's own output, or would overwrite it - "
                        "rename it"
                    ),
                    field=key,
                )
            )
            continue
        if key == document.input_field:
            problems.append(
                Problem(
                    code=STATE_KEY_RESERVED,
                    severity="error",
                    message=(
                        f"the state key {key!r} is this graph's input field, which the run "
                        "request already seeds. Declaring it again would give one name two "
                        "sources and no rule for which wins"
                    ),
                    field=key,
                )
            )
            continue
        accepted = _STATE_DEFAULT_TYPES.get(field.type, ())
        default = field.default
        wrong = default is not None and (
            not isinstance(default, accepted)
            or (field.type != "boolean" and isinstance(default, bool))
        )
        if wrong:
            problems.append(
                Problem(
                    code=STATE_SCHEMA_INVALID,
                    severity="error",
                    message=(
                        f"the state key {key!r} is declared {field.type!r} and defaults to "
                        f"{default!r}, which is a {type(default).__name__}. CrewAI validates "
                        "a json_schema state at kickoff, so this would fail the run at its "
                        "first method rather than here"
                    ),
                    field=key,
                )
            )
    return problems


def _error_port_problems(document: BuilderDocument) -> list[Problem]:
    """An `on_error: route` node whose error port goes nowhere (09 criterion 4).

    A WARNING, and the severity is the whole judgement. The graph is legal - the
    error router still fires and the run still ends - but the author asked for a
    recovery path and then did not draw one, so the failure they wanted to
    handle would end the run silently anyway. The mirror-image mistake, an edge
    leaving `error` on a node whose policy is `fail`, is an ERROR and is already
    reported as `edge-unknown-port`, because such a node has no `error` port at
    all.
    """

    problems: list[Problem] = []
    drawn = {(edge.source, edge.source_port) for edge in flow_edges(document)}
    for node in document.nodes:
        if not routes_errors(node) or node.kind in ROUTING_KINDS:
            continue
        if (node.id, "error") in drawn:
            continue
        problems.append(
            Problem(
                code=ERROR_PORT_UNCONNECTED,
                severity="warning",
                message=(
                    f"{node.id!r} routes its failures out of an `error` port and nothing is "
                    "drawn from it, so a failure here still ends the run - which is what "
                    "`on_error: fail` already does. Draw the recovery path, or set the "
                    "policy back to fail"
                ),
                node_id=node.id,
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
