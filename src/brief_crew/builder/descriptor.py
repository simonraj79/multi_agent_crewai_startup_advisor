"""A builder document, drawn: `BuilderDocument` -> `GraphDescriptor`.

**This never calls `build_graph_descriptor`, and that is the whole design.**
That function derives a topology from a *decorated Flow class* and then
asserts, at module import, that a hand-written overlay names exactly the
methods CrewAI found (`service/graph.py`). Both halves are wrong here twice
over. A builder flow is compiled at runtime, so there is no class to
introspect; and there is no overlay, because the labels, kinds and positions
are the ones the author typed - asking CrewAI what they should be would throw
away the only information the canvas has.

The measured cost of getting this wrong is on record: mutating the validator's
topology so that overlay assertion fires takes the suite from **809 OK** to
**480 run / 77 errors across 28 modules**, because the assertion raises inside
a module-level constant and every importer dies at import. Nothing in this
module raises at import time, and nothing in it reads `VALIDATOR_OVERLAY`.

What it does produce is the same `GraphDescriptor` the console already renders,
so the builder canvas and the validator canvas are one component reading one
shape.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json

from brief_crew import config as project_config
from brief_crew.builder.bounds import back_edges, flow_edges, step_nodes
from brief_crew.builder.compiler import CompiledFlow, compile_document
from brief_crew.builder.document import (
    BILLABLE_KINDS,
    FLOW_KINDS,
    ROUTING_KINDS,
    BuilderDocument,
    BuilderNode,
)
from brief_crew.events import NodeRegistry, QUARANTINE_NODE_ID
from brief_crew.service.models import GraphDescriptor, GraphEdge, GraphNode


# The seven authored kinds, projected onto the seven the descriptor has. Two
# are genuinely lossy and both losses are deliberate:
#
# * `crew` draws as an `agent`, because a crew node IS one billable step on the
#   canvas and the console's iconography has no third billable shape. The
#   distinction survives in `crew`, which names the registered `@CrewBase`.
# * `transform` draws as a `step`, which is already what the descriptor calls a
#   node that does work and makes no decision.
#
# `input` -> `start` rather than an eighth word, because `GraphNode.kind` is a
# closed Literal in `service/models.py` and widening it would change the wire
# shape of the two hand-written graphs for a word only this module needs.
DESCRIPTOR_KINDS: dict[str, str] = {
    "input": "start",
    "agent": "agent",
    "crew": "agent",
    "gate": "gate",
    "router": "router",
    "transform": "step",
    "output": "output",
}

# CrewAI's own three-word vocabulary for a flow method, which `GraphNode`
# carries beside `kind`. A gate compiles to TWO methods - the pause and its
# router - and this reports the FIRST, because the canvas draws one node and
# that node is the pause. Which of its ports was taken is an edge fact.
FLOW_METHOD_TYPES: dict[str, str] = {
    "input": "start",
    "router": "router",
}

# What a node card says about spend, in the same words `VALIDATOR_OVERLAY`
# uses, so the two graphs read alike.
TIER_LABELS: dict[str, str] = {
    "cheap": "Cheap tier",
    "escalation": "Escalation tier",
}

# Where the canvas parks the instrumentation node: off the authored grid, to
# the right of the widest layout the bounds allow.
QUARANTINE_POSITION: dict[str, float] = {"x": 1130.0, "y": 20.0}


def _eyebrow(index: int, node: BuilderNode) -> str:
    """The small-caps line above a node's label: ordinal, then what it is."""

    return f"{index + 1:02d} - {node.kind.upper()}"


def _description(node: BuilderNode) -> str:
    """One line about what this node does, derived from its own config.

    Derived rather than authored: a document has a `label` and no free text at
    all except a gate's message, and a description that repeated the label
    would be worse than one naming the agent, the tier and the tools.
    """

    config = node.config
    if node.kind == "input":
        return f"Seed the run from inputs.{config.field}."
    if node.kind == "agent":
        # An AUTHORED agent names no library id and binds no `tools` tuple - its
        # hands are `attach` edges - so it describes itself by the role its
        # author wrote, which is the one sentence that is genuinely about this
        # node rather than about the registry.
        role = getattr(config, "role", None)
        if role is not None:
            return f"Run the authored agent {role!r} on the {config.tier} tier."
        tools = ", ".join(config.tools) if config.tools else "no tools"
        return f"Run the {config.agent_id} agent on the {config.tier} tier with {tools}."
    if node.kind == "crew":
        process = getattr(config, "process", None)
        if process is not None:
            return f"Run an authored {process} crew on the {config.tier} tier."
        return f"Run the {config.crew_id} crew on the {config.tier} tier."
    if node.kind == "gate":
        return config.message
    if node.kind == "router":
        branches = ", ".join(branch.label for branch in config.branches)
        return f"Branch on {branches or 'nothing declared'}."
    if node.kind == "transform":
        return f"Apply the {config.op} transform."
    return f"Hand back the run result under {config.body_key}."


def _model_badge(node: BuilderNode) -> str | None:
    """The tier badge, or None for a node that runs no model."""

    tier = node.tier
    return TIER_LABELS.get(tier) if tier is not None else None


def _tool_badge(node: BuilderNode) -> str | None:
    tools = getattr(node.config, "tools", ())
    return ", ".join(tools) if tools else None


def _is_routing(node: BuilderNode | None) -> bool:
    return node is not None and node.kind in ROUTING_KINDS


def library_agent_role(agent_id: str) -> str | None:
    """The `Agent.role` a library agent id resolves to, or None.

    `runtime.py:619` builds the real agent with
    `Agent(config=agents_config[spec.agent_key])`, and `role` is a key of that
    YAML block - so this reads the identity out of the same file the paid path
    does rather than restating it. This repository's prompts live in YAML by
    platform rule, and a role copied into Python would be a second place one
    of them lives.

    **It lives here rather than in `runtime.py` because two callers need it and
    this is the one both can reach**: the descriptor, which puts the role on a
    graph node, and `service/builder_runner.py::SyntheticCrewFactories`, which
    puts it on every frame a free run emits. Those two strings must be the same
    string for the same node or the console joins a frame to the wrong card, so
    there is one function and `tests/service/test_builder_identity_parity.py`
    asserts the two agree.

    Any failure answers None. This is a label on a card and a field on a
    telemetry frame; a missing YAML key must never be the reason a graph fails
    to describe itself or a free run fails to start.
    """

    try:
        from brief_crew.builder.runtime import _yaml_config, agent_spec

        spec = agent_spec(agent_id)
        block = _yaml_config("agents.yaml").get(spec.agent_key) or {}
        role = str(dict(block).get("role", "")).strip()
        return role or None
    except Exception:  # pragma: no cover - defensive, see the docstring
        return None


def node_agent_role(node: BuilderNode) -> str | None:
    """The role CrewAI will stamp on this node's frames, or None.

    Three arms, and the None is as deliberate as the two strings:

    * an **authored** agent carries its own `role`, which is exactly what
      `runtime.py:704` passes to `Agent(role=...)`;
    * a **library** agent carries an `agent_id`, which is a registry KEY and
      not a role - `market_analyst` is not what CrewAI stamps, "Market evidence
      analyst" is - so it is resolved through the YAML;
    * a **crew** node runs several agents and no single role is the truth, so
      it claims none rather than nominating one arbitrarily.

    **This field used to be `getattr(node.config, "agent_id", None)`**, which
    was wrong in two different ways at once and neither announced itself. For a
    library agent it published the id under the name `agent_role`, so anything
    joining a graph node to a frame by role compared a key against a sentence
    and never matched. For an authored agent - the half of the builder the
    gauntlet is actually about - `AuthoredAgentConfig` has no `agent_id` at
    all, so the answer was silently `None` and the node the author had just
    named had no identity on it.

    `task_name` stays None for every builder node, and that one is correct:
    `runtime.py:910` builds an authored `Task` with a description and an
    expected output and no `name`, so a real builder frame carries no task name
    either. Writing one here would be the descriptor claiming something
    production never sends.
    """

    role = getattr(node.config, "role", None)
    if isinstance(role, str) and role.strip():
        return role.strip()
    agent_id = getattr(node.config, "agent_id", None)
    if isinstance(agent_id, str) and agent_id.strip():
        return library_agent_role(agent_id.strip())
    return None


def builder_workflow_id(document: BuilderDocument | str) -> str:
    """The workflow id a compiled document registers under: its own id.

    `BUILDER_DOCUMENT_ID_PATTERN` is `^ug_[0-9a-f]{8}$` and both built-in ids
    are hyphenated words, so a builder graph cannot collide with `brief-flow`
    or `idea-validator` by construction rather than by convention. A prefix
    would say the same thing a second time.
    """

    return document if isinstance(document, str) else document.id


def builder_graph_descriptor(document: BuilderDocument) -> GraphDescriptor:
    """One descriptor node per drawn node, plus the quarantine node.

    A gate compiles to two flow methods and still draws as ONE node here. The
    descriptor is what the author drew; the compiled identifiers are the
    `NodeRegistry`'s business, and conflating the two would put a
    `route_confirm_scope` card on a canvas nobody drew it on.
    """

    by_id = document.nodes_by_id()

    # ATTACHMENT nodes are not steps and never appear in a descriptor.
    #
    # The descriptor drives the RUN console: it is the list of things that
    # execute, in the order a frame can arrive for them. A tool, an MCP server
    # or a skill is something an agent HAS, not something the flow does - it
    # emits no frame, occupies no position in the order, and has no state to
    # show. Drawing one here would put a card on the run canvas that can only
    # ever sit idle, which is precisely the "design-time animation in a slot
    # nothing writes" trap the sprite work already walked into.
    #
    # This is not a defensive skip. Before 03-node-library.md D1 grew the union
    # to ten, `DESCRIPTOR_KINDS[node.kind]` below was a total lookup over seven
    # keys; an attachment node reaching it raises KeyError and takes the whole
    # descriptor with it. Filtering here is what keeps that lookup total, which
    # is why it stays a subscript and not a `.get` with a fallback - a fallback
    # would turn the next missing kind into a silently mislabelled card.
    flow_nodes = [node for node in document.nodes if node.kind in FLOW_KINDS]

    # `attach` and `member` edges are excluded for the same reason, and this is
    # load-bearing rather than tidy: `incoming` decides `flow_method_type`
    # (start versus listen), `condition_type` (AND versus OR) and
    # `trigger_methods`. An agent holding three tools has three inbound edges
    # and has not branched three ways, so counting them would report a join
    # that the compiler never emits.
    incoming: dict[str, list[str]] = {}
    for edge in document.edges:
        if edge.target_port != "in":
            continue
        incoming.setdefault(edge.target, []).append(edge.source)

    nodes: list[GraphNode] = []
    for index, node in enumerate(flow_nodes):
        nodes.append(
            GraphNode(
                id=node.id,
                label=node.label,
                kind=DESCRIPTOR_KINDS[node.kind],
                description=_description(node),
                eyebrow=_eyebrow(index, node),
                position={"x": float(node.position.x), "y": float(node.position.y)},
                model=_model_badge(node),
                tool=_tool_badge(node),
                flow_method_type=FLOW_METHOD_TYPES.get(
                    node.kind, "start" if node.id not in incoming else "listen"
                ),
                human_feedback=node.kind == "gate",
                # A declared join is the only AND a compiled builder flow ever
                # carries: `compiler.py` emits `{"and": [...]}` for a node named
                # in `joins` and alternatives for every other multi-predecessor
                # node. So this reports what will be compiled, not how many
                # edges happen to arrive.
                condition_type=(
                    ("AND" if document.joins.get(node.id) == "all" else "OR")
                    if node.id in incoming
                    else None
                ),
                trigger_methods=list(dict.fromkeys(incoming.get(node.id, []))),
                # The author's own port names, not the compiled `e3_approve`
                # labels. The canvas draws what was drawn; the compiled label is
                # what `NodeRegistry.route_targets` joins a frame on, and the
                # two namespaces are kept apart deliberately.
                router_events=list(node.out_ports) if node.kind in ROUTING_KINDS else [],
                crew=getattr(node.config, "crew_id", None),
                agent_role=node_agent_role(node),
            )
        )

    nodes.append(
        GraphNode(
            id=QUARANTINE_NODE_ID,
            label="Unattributed",
            kind="quarantine",
            description="Events that could not be joined to a declared node.",
            eyebrow="INSTRUMENTATION",
            position=dict(QUARANTINE_POSITION),
        )
    )

    edges = [
        GraphEdge(
            id=edge.id,
            source=edge.source,
            target=edge.target,
            label=edge.source_port if _is_routing(by_id.get(edge.source)) else None,
            condition_type="AND" if document.joins.get(edge.target) == "all" else "OR",
            route=edge.source_port if _is_routing(by_id.get(edge.source)) else None,
        )
        for edge in document.edges
    ]

    start_nodes = [node.id for node in document.nodes if node.kind == "input"]
    return GraphDescriptor(
        id=builder_workflow_id(document),
        name=document.name,
        version=_descriptor_version(document, nodes, edges, start_nodes),
        start_nodes=start_nodes,
        nodes=nodes,
        edges=edges,
    )


def _descriptor_version(
    document: BuilderDocument,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    start_nodes: list[str],
) -> str:
    """The graph ETag: a content hash that also carries the document version.

    Hashed the same way `build_graph_descriptor` hashes the two hand-written
    graphs, so `/api/workflows/{id}/graph`'s conditional GET behaves identically
    for all three and `_etag_matches` needs no special case.

    The document's own `version` is folded INTO the hash rather than used as the
    tag. Locked spec C derives the ETag from the version, and this is that
    derivation plus a guarantee the bare integer does not give: two documents at
    version 3 have different tags, and a republish that changed no node still
    changes the tag - which is what the stored budget is versioned against, so
    an in-flight admission read cannot be looking at a different graph under the
    same name.
    """

    version_input = {
        "document": document.id,
        "document_version": document.version,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "edges": [edge.model_dump(mode="json") for edge in edges],
        "start_nodes": start_nodes,
    }
    return hashlib.sha256(
        json.dumps(version_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def builder_node_registry(
    document: BuilderDocument, compiled: CompiledFlow
) -> NodeRegistry:
    """Attribution for a compiled builder flow.

    `from_flow_structure` cannot do this job - a flow built at runtime reports
    the compiler's identifiers as its method names and no statically declared
    router events at all - so this is `from_document`, fed the compiler's own
    two maps. `port_labels` is the join between the author's `approve` and the
    `e4_approve` CrewAI actually emits; without it every `EDGE_TAKEN` frame from
    a gate lands on the quarantine node.
    """

    return NodeRegistry.from_document(
        document,
        method_names=compiled.method_idents,
        event_labels=compiled.port_labels,
    )


def plan_layers(document: BuilderDocument) -> tuple[tuple[str, ...], ...]:
    """The graph's step nodes in topological layers - C6's `stage` frames.

    One layer is a set of nodes with no ordering between them, which for a
    fan-out is the whole point: three research branches are ONE stage because
    their concurrency is the interesting fact, and a plain topological sort
    would emit them as three steps and lose it. `frontend/src/data/crewStages.ts`
    makes the same judgement by hand for the validator; this derives it, because
    a graph a user drew has nobody to declare it.

    BACK EDGES ARE REMOVED FIRST, and that is what makes this terminate at all.
    A builder graph may carry up to `MAX_CYCLES` loops - a revise gate is one -
    and Kahn's algorithm over a cyclic graph produces no layers and no error,
    just a shorter answer than the node count. `bounds.back_edges` is the same
    set `budget.py` removes to price a cycle, so the two agree by construction
    rather than by two walks that could differ.

    A node the layering cannot reach - which after the back-edge removal means
    an unreachable one - lands in a final layer of its own rather than being
    dropped: a stage list that silently omits a node is exactly the "the boat
    skipped a rower" failure `assertStageCoverage` exists to prevent.
    """

    nodes = [node.id for node in step_nodes(document)]
    known = set(nodes)
    loops = {id(edge) for edge in back_edges(document)}
    successors: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    indegree: dict[str, int] = {node_id: 0 for node_id in nodes}
    for edge in flow_edges(document):
        if id(edge) in loops:
            continue
        if edge.source not in known or edge.target not in known:
            continue
        if edge.target in successors[edge.source]:
            continue
        successors[edge.source].add(edge.target)
        indegree[edge.target] += 1

    layers: list[tuple[str, ...]] = []
    placed: set[str] = set()
    frontier = [node_id for node_id in nodes if indegree[node_id] == 0]
    while frontier:
        layer = tuple(frontier)
        layers.append(layer)
        placed.update(layer)
        nxt: list[str] = []
        for node_id in layer:
            for target in sorted(successors[node_id]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    nxt.append(target)
        frontier = nxt
    stranded = tuple(node_id for node_id in nodes if node_id not in placed)
    if stranded:
        layers.append(stranded)
    return tuple(layers)


def gate_before_first_billable(document: BuilderDocument) -> bool:
    """Whether every path from an input reaches a gate before it spends money.

    This is the whole of the anonymous-launch policy, and it is the validator's
    own brake restated for a graph nobody wrote by hand: a run that stops at a
    gate before the first billable node costs at most the nodes above that gate,
    and an unanswered gate expires. A graph with no such gate runs every
    billable node it declares with nobody watching.

    Computed by walking forward from the input nodes and NOT expanding through a
    gate: the gate is reached, and what is behind it is only reached by
    answering it. If a billable node turns up in that frontier there is a path
    that spends before anybody is asked.

    A graph with no billable nodes answers True - there is nothing to brake -
    which is why the question is "before the first billable node" rather than
    "has a gate".
    """

    by_id = document.nodes_by_id()
    successors: dict[str, list[str]] = {}
    for edge in document.edges:
        successors.setdefault(edge.source, []).append(edge.target)

    seen: set[str] = set()
    frontier = [node.id for node in document.nodes if node.kind == "input"]
    while frontier:
        node_id = frontier.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        node = by_id.get(node_id)
        if node is None:
            continue
        if node.kind in BILLABLE_KINDS:
            return False
        if node.kind == "gate":
            continue
        frontier.extend(successors.get(node_id, ()))
    return True


def static_cost_over_ceiling(
    static_cost_usd: float, *, ceiling_usd: float | None = None
) -> bool:
    """Whether this graph's stored estimate breaches the run cost ceiling.

    Read at ADMISSION from the figure stored with the document rather than
    recomputed, because the estimate is versioned with the graph ETag precisely
    so a republish cannot race an in-flight admission read.

    A ceiling of zero or less is DISABLED - the same spelling `MAX_RUN_COST_USD`
    already uses, and the same escape hatch, so a deployment that has turned the
    runtime ceiling off does not get a static one it never asked for.
    """

    ceiling = (
        project_config.MAX_RUN_COST_USD if ceiling_usd is None else float(ceiling_usd)
    )
    if ceiling <= 0:
        return False
    return static_cost_usd * project_config.GRAPH_STATIC_BUDGET_MARGIN > ceiling


@dataclass(frozen=True, slots=True)
class BuilderWorkflow:
    """One compiled, registrable builder graph and everything the service asks.

    A record rather than five parallel dicts, because every field here is a
    property of the same document at the same version, and the four
    registration maps must never end up holding a mixture of two.
    """

    document: BuilderDocument
    descriptor: GraphDescriptor
    node_registry: NodeRegistry
    compiled: CompiledFlow
    #: The `inputs` keys this workflow refuses: every key its compiled state
    #: declares, except the one public prompt.
    reserved_input_keys: frozenset[str]
    #: True when an anonymous launch is bounded by a human - see
    #: `gate_before_first_billable`.
    gated_before_spend: bool
    #: Who published it, copied from the document row (plan 01 D1). None for
    #: a graph published anonymously or before ownership was recorded, and
    #: such a graph stays launchable by anyone - `service/graph.py::
    #: workflow_visible_to` is the one place that rule is applied.
    user_id: str | None = None

    @property
    def workflow_id(self) -> str:
        return self.descriptor.id

    @property
    def graph_version(self) -> str:
        return self.descriptor.version

    @property
    def input_field(self) -> str:
        return self.document.input_field

    @property
    def static_cost_usd(self) -> float:
        return float(self.compiled.budget.static_cost_usd)


def build_builder_workflow(
    document: BuilderDocument,
    *,
    ceiling_usd: float | None = None,
    user_id: str | None = None,
    credential_check: Callable[[str], bool] | None = None,
) -> BuilderWorkflow:
    """Compile a document and derive everything the four maps need.

    Raises `BuilderCompileError` for a document that must not be published,
    which is every reason `validate_document` reports plus the compiler's own
    guards over what it emitted.

    `credential_check` is the publisher's identity, as a predicate over
    credential ids: a publish re-validates with it (plan 01 D10) so a graph
    naming somebody else's row is refused here rather than failing its first
    billable node. Rehydration passes none - a boot has no identity, and a
    credential deleted since publish is the run-time `credential-not-yours`.

    Nothing is registered here. Registration is `service/graph.py`'s job, and
    keeping the two apart is what lets the API validate and preview a document
    with no side effect on what this service will run.
    """

    compiled = compile_document(
        document, ceiling_usd=ceiling_usd, credential_check=credential_check
    )
    declared_state = compiled.definition["state"]["default"]
    # Every state key the compiled flow declares is a control key, because
    # CrewAI merges `inputs` into state wholesale - except the one the input
    # node reads, which is the public prompt and the whole point of the run.
    reserved = frozenset(declared_state) - {document.input_field}
    return BuilderWorkflow(
        document=document,
        descriptor=builder_graph_descriptor(document),
        node_registry=builder_node_registry(document, compiled),
        compiled=compiled,
        reserved_input_keys=reserved,
        gated_before_spend=gate_before_first_billable(document),
        user_id=user_id,
    )
