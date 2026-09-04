"""Stable joins between CrewAI event identity and graph node identity."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from crewai.flow.flow_context import current_flow_method_name

from brief_crew.events.models import MAX_IDENTIFIER_LENGTH


QUARANTINE_NODE_ID = "unattributed"
WORKFLOW_NODE_ID = "workflow"

#: Which builder node kinds compile to a CrewAI `@router`, and so are the only
#: kinds whose outgoing edges are route targets rather than plain successors.
#:
#: Restated here rather than imported from `brief_crew.builder.document`, which
#: is where the same set is declared as `ROUTING_KINDS`. The event spine is
#: imported by the compiler and by the service; the builder package imports
#: `config` and the whole document schema, and pulling that in from here would
#: put a cycle one `import` away from anyone who later has `builder` reach for a
#: registry. The duplication is bounded by
#: `tests/builder/test_from_document.py::RoutingKindTests`, which asserts the two
#: sets are equal - so drift is a failing test rather than a router whose edges
#: quietly stop resolving.
ROUTING_NODE_KINDS: frozenset[str] = frozenset({"gate", "router"})


#: The declared graph node whose flow method is running in *this* execution
#: context - the join that CrewAI's own `current_flow_method_name` cannot make.
#:
#: A tool call does not happen inside the flow method that reads as its owner.
#: `crewai.experimental.agent_executor.AgentExecutor` is itself a `Flow`, and
#: the flow runtime sets `current_flow_method_name` for every method of every
#: flow it runs. So by the time a `ToolUsageStartedEvent` is emitted, that
#: variable names an *AgentExecutor* method - `execute_tool_action` on the text
#: path, `execute_native_tool` on the native function-calling path - and neither
#: is a node in this repo's graph. Every tool, LLM and token frame of the first
#: paid run therefore landed on the `unattributed` quarantine node: 148 frames
#: that could not say which agent ran which query, and a per-node cost readout
#: that stayed at zero.
#:
#: The fix has to be positional rather than nominal. A tool-name to node table
#: would rot the first time a tool is shared by two branches, and a table of
#: CrewAI's inner method names would rot the first time upstream renames one -
#: as `execute_tool_action` versus `execute_native_tool` already shows, one
#: library version apart.
#:
#: This is written once per *declared* flow method start, from the stream sink,
#: in the context the flow runtime is about to `copy_context()` into the worker
#: thread that runs the method body. Everything the method does downstream -
#: `Crew.kickoff()`, the nested AgentExecutor flow, its thread pool for parallel
#: native tool calls - inherits that copy, because CrewAI propagates context
#: explicitly at every one of those boundaries. That is not an assumption: the
#: stream sink itself is reached through a `ContextVar`, so any event arriving
#: here has already proved the chain holds.
#:
#: The three research branches run as sibling `asyncio` tasks, and a task copies
#: its context at creation, so a branch cannot overwrite a sibling's node. It is
#: written and never reset: the value only means anything while something is
#: executing inside the method, and the next declared method start in the same
#: context replaces it.
current_node_scope: ContextVar[str | None] = ContextVar(
    "brief_crew_node_scope", default=None
)


def enter_node_scope(node_id: str) -> None:
    """Record the declared node whose flow method now owns this context."""

    current_node_scope.set(node_id)


def _normalized(value: str | None) -> str:
    return (value or "").strip().casefold()


def _field(item: Any, name: str, default: Any = None) -> Any:
    """One declared field of a document node or edge, however it arrived.

    A builder document reaches this module either as the parsed
    `BuilderDocument` (what the compiler holds) or as the raw JSON a store read
    back (what a cached descriptor holds). Both are read through here rather
    than normalising one into the other, because `model_dump()` on the parsed
    form would rebuild the whole tree to look at three keys per object, and
    importing `BuilderDocument` to isinstance-check it is the dependency this
    module deliberately does not take.
    """

    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _compiled_idents(value: str | Sequence[str], *, node_id: str) -> tuple[str, ...]:
    """The flow method identifiers one document node compiles to, in order.

    A `gate` compiles to TWO - the pause and the deterministic router that reads
    its answer - so this is a sequence rather than a name, and **the last entry
    is the routing method**. That ordering is `builder.bounds.compiled_identifiers`'
    own: it appends the gate router after the pause, and every other kind emits
    exactly one identifier, which is therefore also its last.
    """

    idents = (value,) if isinstance(value, str) else tuple(str(name) for name in value)
    if not idents or not all(idents):
        raise ValueError(
            f"node {node_id!r} was given no compiled flow method name; pass the "
            "identifier the compiler emitted, or omit the node from method_names "
            "to use its own id"
        )
    return idents


@dataclass(frozen=True, slots=True)
class NodeRegistry:
    """Resolve events only through explicitly declared, stable identifiers."""

    task_nodes: Mapping[str, str] = field(default_factory=dict)
    agent_role_prefixes: Mapping[str, str] = field(default_factory=dict)
    flow_method_nodes: Mapping[str, str] = field(default_factory=dict)
    route_targets: Mapping[tuple[str, str], str] = field(default_factory=dict)
    router_methods: frozenset[str] = frozenset()
    quarantine_node_id: str = QUARANTINE_NODE_ID
    workflow_node_id: str = WORKFLOW_NODE_ID
    #: The node a `FrameKind.VERDICT` frame belongs to, when this graph names
    #: one. `None` means "fall back to the literal `VERDICT_NODE_ID`", which is
    #: what every registry built by `from_flow_structure` does and is why the
    #: validator's verdict frames land on `synthesize` unchanged.
    #:
    #: **A declared seam, and nothing in this build sets it.** Say that plainly
    #: rather than describing a failure it prevents: `publish_verdict` is called
    #: from exactly one place, `validator_flow._run_synthesis`, so today the
    #: only graph that emits a verdict frame is the one whose node really is
    #: called `synthesize`. No builder node KIND scores anything, and
    #: `builder_node_registry` accordingly passes no `verdict_node_id`.
    #:
    #: It is kept because the day a builder scoring node exists is the day the
    #: literal starts filing that graph's one deliverable under the visible
    #: quarantine node - "could not say where this came from" - and the
    #: alternative to a seam here is `serializer.py` learning a validator node
    #: id. `from_document` still validates it against the document's own nodes,
    #: because a frame attributed to a node the canvas does not draw is
    #: invisible rather than merely misplaced.
    #:
    #: This is a resolved GRAPH NODE ID, not a flow method name - it bypasses
    #: `declared_node` rather than being looked up through it, because a
    #: compiled flow's method idents (`n8_score`) are not its node ids
    #: (`score`), and asking an author for the ident would leak the compiler's
    #: naming scheme into the document.
    verdict_node_id: str | None = None
    #: Every declared successor edge as `(from node id, to node id)`, for the
    #: one question no other field answers: was the node that just finished
    #: really this one's predecessor?
    #:
    #: `StreamSinkAdapter` emits C6's `edge_traversal` frame from the last
    #: declared method to FINISH to the next one to START, and without this it
    #: would have to believe execution order - which is right for a sequential
    #: edge and for a fan-out, and wrong the moment two branches interleave. An
    #: EMPTY set means "believe execution order", which is what every registry
    #: built by `from_flow_structure` gets: the two hand-written flows' edges
    #: live in `service/graph.py`, not here, and inventing a second copy of them
    #: for this is exactly the drift this repository keeps paying for.
    edges: frozenset[tuple[str, str]] = frozenset()
    #: `flow_method_nodes.values()` as a set, computed once.
    #:
    #: `resolve()`'s last fallback asks whether the enclosing node scope is one
    #: of ours, and `values()` on a `MappingProxyType` is an O(n) scan - run on
    #: EVERY event that does not name a flow method, which is most of them
    #: (every tool, model, token and agent frame). At the validator's 14 nodes
    #: that is invisible; a builder graph is bounded at `MAX_GRAPH_NODES` = 24
    #: and a gate compiles to two methods, so the scan grows while the frame
    #: rate does not fall.
    declared_node_ids: frozenset[str] = field(
        default=frozenset(), init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_nodes", MappingProxyType(dict(self.task_nodes)))
        object.__setattr__(
            self,
            "agent_role_prefixes",
            MappingProxyType(dict(self.agent_role_prefixes)),
        )
        object.__setattr__(
            self, "flow_method_nodes", MappingProxyType(dict(self.flow_method_nodes))
        )
        object.__setattr__(
            self, "route_targets", MappingProxyType(dict(self.route_targets))
        )
        object.__setattr__(self, "router_methods", frozenset(self.router_methods))
        object.__setattr__(
            self, "declared_node_ids", frozenset(self.flow_method_nodes.values())
        )

    @classmethod
    def from_flow_structure(cls, structure: Mapping[str, Any]) -> NodeRegistry:
        flow_nodes = {name: name for name in structure.get("nodes", {})}
        route_targets = {
            (str(edge["source"]), str(edge["router_event"])): str(edge["target"])
            for edge in structure.get("edges", [])
            if edge.get("is_router_event") and edge.get("router_event") is not None
        }
        return cls(
            flow_method_nodes=flow_nodes,
            route_targets=route_targets,
            router_methods=frozenset(structure.get("router_methods", [])),
        )

    @classmethod
    def from_document(
        cls,
        document: Any,
        *,
        method_names: Mapping[str, str | Sequence[str]] | None = None,
        event_labels: Mapping[str, Mapping[str, str]] | None = None,
        verdict_node_id: str | None = None,
        quarantine_node_id: str = QUARANTINE_NODE_ID,
        workflow_node_id: str = WORKFLOW_NODE_ID,
    ) -> NodeRegistry:
        """Join a builder document's node ids to the flow the compiler emitted.

        `from_flow_structure` cannot do this job. It reads CrewAI's static
        introspection of a *decorated class*, and a flow built at runtime tells
        it three lies: the method names are the compiler's identifiers rather
        than anything an author wrote, a `@router` created with `type()` reports
        no statically declared events at all (so every route target comes back
        empty and every `EDGE_TAKEN` frame points at the quarantine node), and
        the node kinds are gone. All three answers are in the document, which is
        why this constructor reads the document instead.

        `method_names` maps a document node id to the flow method identifier -
        or identifiers, since a `gate` compiles to two - that the compiler
        emitted for it. Omit a node, or the whole argument, and its own id is
        used, which is legal only while every id already matches CrewAI's
        `^[A-Za-z_][A-Za-z0-9_]*$` for flow method names; it refuses the entire
        flow definition otherwise, so the compiler normally supplies the map.
        The result is deliberately many-to-one: `flow_method_nodes` is a
        `Mapping[str, str]` and nothing anywhere requires it to be an identity.

        `event_labels` maps a node id to `{out port: emitted router label}`. The
        compiler holds both halves already - `compiled_identifiers` returns its
        labels in each node's own `out_ports` order - so the call site is
        `dict(zip(node.out_ports, labels[node.id]))`. Omitting it means the port
        IS the label, which is what a compiler that does not rename ports emits.
        Ports are read from the edges rather than from the node's config so this
        module never learns the taxonomy of a router's branches.

        `task_nodes` and `agent_role_prefixes` are left EMPTY on purpose. Both
        are consulted BEFORE the method name in `resolve()`, and two builder
        nodes may legitimately name the same allowlisted `agent_id` - the
        validator's own `scope_idea` / `revise_scope` pair already does - so a
        role prefix would collapse both onto whichever node was registered
        first, silently and for the whole run.

        One port may carry several edges - the validator's own scope gate
        approves into three research branches - and `route_targets` maps one
        `(method, label)` to one node, so the last edge drawn wins. That is not
        a decision taken here: `from_flow_structure` collapses a fan-out the
        same way, because the `EDGE_TAKEN` frame has one `to` field and the
        client animates one edge. What actually runs is every listener on the
        label, unaffected either way.
        """

        idents = dict(method_names or {})
        labels = dict(event_labels or {})

        flow_method_nodes: dict[str, str] = {}
        routing_methods: dict[str, str] = {}
        node_kinds: dict[str, str] = {}
        for node in _field(document, "nodes", ()) or ():
            node_id = str(_field(node, "id", "") or "")
            if not node_id:
                raise ValueError("every builder node must carry an id")
            if len(node_id) > MAX_IDENTIFIER_LENGTH:
                # `serializer._draft` clips `node_id` to 128 characters with no
                # error, so two nodes agreeing on their first 128 would merge
                # into one on the canvas and stay merged. Refusing here is the
                # only place that truncation is still visible.
                raise ValueError(
                    f"node id {node_id[:64]!r}... is {len(node_id)} characters and the "
                    f"frame bound is {MAX_IDENTIFIER_LENGTH}; a longer id is silently "
                    "truncated into the frame, merging two nodes into one"
                )
            node_kinds[node_id] = str(_field(node, "kind", "") or "")
            compiled = _compiled_idents(idents.get(node_id, node_id), node_id=node_id)
            for ident in compiled:
                flow_method_nodes[ident] = node_id
            routing_methods[node_id] = compiled[-1]

        route_targets: dict[tuple[str, str], str] = {}
        for edge in _field(document, "edges", ()) or ():
            source = str(_field(edge, "source", "") or "")
            if node_kinds.get(source) not in ROUTING_NODE_KINDS:
                # A plain successor edge is not a route: CrewAI takes it because
                # the listener fired, and no router ever returns a label for it.
                continue
            port = str(_field(edge, "source_port", "out") or "out")
            label = labels.get(source, {}).get(port, port)
            route_targets[routing_methods[source], label] = str(
                _field(edge, "target", "") or ""
            )

        registry = cls(
            flow_method_nodes=flow_method_nodes,
            route_targets=route_targets,
            router_methods=frozenset(
                routing_methods[node_id]
                for node_id, kind in node_kinds.items()
                if kind in ROUTING_NODE_KINDS
            ),
            quarantine_node_id=quarantine_node_id,
            workflow_node_id=workflow_node_id,
            verdict_node_id=verdict_node_id,
            # Every edge the author drew, attachment edges included: the
            # question `edge_traversal` asks is "is this pair adjacent", and an
            # attachment edge is adjacency the author can see on the canvas.
            edges=frozenset(
                (
                    str(_field(edge, "source", "") or ""),
                    str(_field(edge, "target", "") or ""),
                )
                for edge in _field(document, "edges", ()) or ()
            ),
        )
        if (
            verdict_node_id is not None
            and verdict_node_id not in registry.declared_node_ids
        ):
            raise ValueError(
                f"verdict_node_id {verdict_node_id!r} is not a node in this document; "
                "a verdict frame attributed to a node the canvas does not draw is "
                "invisible rather than merely misplaced"
            )
        return registry

    def resolve(
        self,
        *,
        task_name: str | None = None,
        agent_role: str | None = None,
        method_name: str | None = None,
    ) -> str:
        if task_name and task_name in self.task_nodes:
            return self.task_nodes[task_name]

        normalized_role = _normalized(agent_role)
        for prefix, node_id in self.agent_role_prefixes.items():
            if normalized_role.startswith(_normalized(prefix)):
                return node_id

        if method_name is not None:
            # An event that names a flow method of its own is a statement about
            # that method's lifecycle, so it is resolved by that name alone.
            # A name this graph does not declare belongs to a flow this graph
            # does not draw, and the quarantine node is the honest answer:
            # re-attributing it to the enclosing node would turn every inner
            # `MethodExecution*` pair - dozens per agent - into a NODE_START /
            # NODE_END on a research node, and `applyNodeState` in the Studio
            # client does not take `completed` back. That is the same asymmetry
            # `FlowScope` guards for flow lifecycle events.
            return self.flow_method_nodes.get(method_name, self.quarantine_node_id)

        active_method = current_flow_method_name.get()
        if active_method in self.flow_method_nodes:
            return self.flow_method_nodes[active_method]

        # Nothing named a method of ours, so this happened *inside* one: a tool
        # call, a model call, an agent or a task, all of which CrewAI runs from
        # within its own nested flows. See `current_node_scope`.
        enclosing = current_node_scope.get()
        if enclosing is not None and enclosing in self.declared_node_ids:
            return enclosing
        return self.quarantine_node_id

    def resolve_event(self, event: Any) -> str:
        task = getattr(event, "task", None)
        agent = getattr(event, "agent", None)
        task_name = getattr(event, "task_name", None) or getattr(task, "name", None)
        agent_role = getattr(event, "agent_role", None) or getattr(agent, "role", None)
        return self.resolve(
            task_name=task_name,
            agent_role=agent_role,
            method_name=getattr(event, "method_name", None),
        )

    def declared_node(self, method_name: str | None) -> str | None:
        """The graph node a flow method name declares, or None if it is not ours."""

        if method_name is None:
            return None
        return self.flow_method_nodes.get(method_name)

    def is_router(self, method_name: str) -> bool:
        return method_name in self.router_methods

    def resolve_route(self, method_name: str, route: str) -> str:
        return self.route_targets.get(
            (method_name, route), self.quarantine_node_id
        )
