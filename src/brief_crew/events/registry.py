"""Stable joins between CrewAI event identity and graph node identity."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from crewai.flow.flow_context import current_flow_method_name


QUARANTINE_NODE_ID = "unattributed"
WORKFLOW_NODE_ID = "workflow"


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
        if enclosing is not None and enclosing in self.flow_method_nodes.values():
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
