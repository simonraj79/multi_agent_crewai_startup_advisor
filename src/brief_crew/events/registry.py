"""Stable joins between CrewAI event identity and graph node identity."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from crewai.flow.flow_context import current_flow_method_name


QUARANTINE_NODE_ID = "unattributed"
WORKFLOW_NODE_ID = "workflow"


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

        active_method = method_name or current_flow_method_name.get()
        if active_method in self.flow_method_nodes:
            return self.flow_method_nodes[active_method]
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

    def is_router(self, method_name: str) -> bool:
        return method_name in self.router_methods

    def resolve_route(self, method_name: str, route: str) -> str:
        return self.route_targets.get(
            (method_name, route), self.quarantine_node_id
        )
