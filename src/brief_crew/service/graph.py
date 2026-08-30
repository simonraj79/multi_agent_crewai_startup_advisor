"""Graph descriptors derived from CrewAI's static Flow definitions."""

from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any

from crewai.flow import build_flow_structure

from brief_crew.events import NodeRegistry, QUARANTINE_NODE_ID
from brief_crew.main import BriefFlow
from brief_crew.service.models import GraphDescriptor, GraphEdge, GraphNode, WorkflowSummary
from brief_crew.validator_flow import ValidatorFlow


BRIEF_WORKFLOW_ID = "brief-flow"
BRIEF_WORKFLOW_NAME = "Brief Flow"
VALIDATOR_WORKFLOW_ID = "idea-validator"
VALIDATOR_WORKFLOW_NAME = "Idea Validator"


BRIEF_OVERLAY: dict[str, dict[str, Any]] = {
    "retrieve_cached": {"label": "Retrieve cached", "kind": "start", "eyebrow": "01 - CACHE", "position": {"x": 430, "y": 20}},
    "check_cache": {"label": "Check cache", "kind": "router", "eyebrow": "ROUTE", "position": {"x": 430, "y": 180}},
    # Three agents run at this one node - BriefCrew(track="B") wires a researcher
    # on CHEAP_MODEL and an analyst and a writer on ESCALATION_MODEL - so the
    # badge names the most expensive tier present, not the first agent's. It read
    # "Cheap tier / Web search" until 2026-08-30, which was false twice over: two
    # of the three agents are escalation tier, and the researcher carries two
    # Firecrawl tools, not one invented category. See _assert_overlay_tiers.
    "scrape_web": {"label": "Research live web", "kind": "agent", "eyebrow": "02 - RESEARCH", "position": {"x": 780, "y": 350}, "model": "Mixed tier", "tool": "Firecrawl search + scrape"},
    "index_content": {"label": "Index content", "kind": "step", "eyebrow": "03 - INDEX", "position": {"x": 780, "y": 520}},
    # Escalation tier only on the cache_hit path. On cache_miss this method
    # returns immediately having made zero model calls, because scrape_web's
    # crew already wrote the brief (main.py). The badge is conditional and the
    # node card cannot express that, so it names the path that does spend.
    "write_brief": {"label": "Write brief", "kind": "agent", "eyebrow": "04 - WRITE", "position": {"x": 430, "y": 700}, "model": "Escalation tier"},
    "persist": {"label": "Brief", "kind": "output", "eyebrow": "OUTPUT", "position": {"x": 430, "y": 870}},
}

VALIDATOR_OVERLAY: dict[str, dict[str, Any]] = {
    "scope_idea": {"label": "Scoper", "kind": "agent", "eyebrow": "01 - DEFINE", "position": {"x": 430, "y": 20}, "model": "Escalation tier"},
    "confirm_scope": {"label": "Confirm scope", "kind": "gate", "eyebrow": "GATE 01", "position": {"x": 430, "y": 180}},
    "route_scope": {"label": "Route scope", "kind": "router", "eyebrow": "DECISION", "position": {"x": 430, "y": 340}},
    "revise_scope": {"label": "Revise scope", "kind": "agent", "eyebrow": "01R - REVISE", "position": {"x": 825, "y": 180}, "model": "Escalation tier"},
    "research_market": {"label": "Market Analyst", "kind": "agent", "eyebrow": "02A - MARKET", "position": {"x": 35, "y": 520}, "model": "Cheap tier", "tool": "Firecrawl"},
    "research_sentiment": {"label": "Sentiment Analyst", "kind": "agent", "eyebrow": "02B - DEMAND", "position": {"x": 430, "y": 520}, "model": "Cheap tier", "tool": "HN Algolia"},
    "research_feasibility": {"label": "Feasibility Analyst", "kind": "agent", "eyebrow": "02C - BUILD", "position": {"x": 825, "y": 520}, "model": "Cheap tier", "tool": "GitHub"},
    "synthesize": {"label": "Synthesist", "kind": "agent", "eyebrow": "03 - SCORE", "position": {"x": 430, "y": 720}, "model": "Escalation tier"},
    "review_verdict": {"label": "Review verdict", "kind": "gate", "eyebrow": "GATE 02", "position": {"x": 430, "y": 880}},
    "route_verdict": {"label": "Route verdict", "kind": "router", "eyebrow": "DECISION", "position": {"x": 430, "y": 1040}},
    "revise_verdict": {"label": "Revise verdict", "kind": "agent", "eyebrow": "03R - REVISE", "position": {"x": 825, "y": 880}, "model": "Escalation tier"},
    "write_report": {"label": "Reporter", "kind": "agent", "eyebrow": "04 - WRITE", "position": {"x": 430, "y": 1200}, "model": "Escalation tier"},
    "persist": {"label": "Validation brief", "kind": "output", "eyebrow": "OUTPUT", "position": {"x": 430, "y": 1360}},
}


def _label(identifier: str) -> str:
    return identifier.replace("_", " ").strip().title()


def _description(flow_class: type[Any], method_name: str) -> str:
    method = getattr(flow_class, method_name, None)
    doc = inspect.getdoc(method) or ""
    return doc.splitlines()[0] if doc else _label(method_name)


def build_graph_descriptor(
    flow_class: type[Any] = BriefFlow,
    *,
    workflow_id: str = BRIEF_WORKFLOW_ID,
    workflow_name: str = BRIEF_WORKFLOW_NAME,
    overlay: dict[str, dict[str, Any]] | None = None,
) -> GraphDescriptor:
    """Derive and validate a stable graph from CrewAI's public builder."""

    structure = build_flow_structure(flow_class)
    for router_name in structure["router_methods"]:
        router_events = structure["nodes"][router_name].get("router_events", [])
        if not router_events:
            raise RuntimeError(
                f"router {router_name!r} has no statically declared events"
            )

    if overlay is not None:
        derived_ids = set(structure["nodes"])
        overlay_ids = set(overlay)
        if derived_ids != overlay_ids:
            missing = sorted(derived_ids - overlay_ids)
            unknown = sorted(overlay_ids - derived_ids)
            raise RuntimeError(
                f"graph overlay does not match derived topology; missing={missing}, "
                f"unknown={unknown}"
            )

    nodes: list[GraphNode] = []
    for index, (node_id, metadata) in enumerate(structure["nodes"].items()):
        display = overlay[node_id] if overlay is not None else {}
        nodes.append(
            GraphNode(
                id=node_id,
                label=str(display.get("label", _label(node_id))),
                kind=display.get(
                    "kind",
                    "router"
                    if metadata.get("is_router")
                    else "start"
                    if metadata.get("type") == "start"
                    else "step",
                ),
                description=str(
                    display.get("description", _description(flow_class, node_id))
                ),
                eyebrow=str(display.get("eyebrow", metadata.get("type", "step")).upper()),
                position=display.get("position", {"x": 430, "y": index * 170}),
                model=display.get("model"),
                tool=display.get("tool"),
                metadata={
                    key: value
                    for key, value in metadata.items()
                    if key not in {"class_name", "type"}
                },
            )
        )
    nodes.append(
        GraphNode(
            id=QUARANTINE_NODE_ID,
            label="Unattributed",
            kind="quarantine",
            description="Events that could not be joined to a declared node.",
            eyebrow="INSTRUMENTATION",
            position={"x": 1130, "y": 20},
        )
    )

    edges = [
        GraphEdge(
            id=f"{edge['source']}->{edge['target']}:{edge.get('router_event') or ''}",
            source=str(edge["source"]),
            target=str(edge["target"]),
            label=edge.get("router_event"),
            condition_type=edge.get("condition_type"),
            route=edge.get("router_event"),
        )
        for edge in structure["edges"]
    ]

    version_input = {
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "edges": [edge.model_dump(mode="json") for edge in edges],
        "start_nodes": structure["start_methods"],
    }
    version = hashlib.sha256(
        json.dumps(version_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return GraphDescriptor(
        id=workflow_id,
        name=workflow_name,
        version=version,
        start_nodes=list(structure["start_methods"]),
        nodes=nodes,
        edges=edges,
    )


BRIEF_STRUCTURE = build_flow_structure(BriefFlow)
VALIDATOR_STRUCTURE = build_flow_structure(ValidatorFlow)

BRIEF_GRAPH = build_graph_descriptor(overlay=BRIEF_OVERLAY)
VALIDATOR_GRAPH = build_graph_descriptor(
    ValidatorFlow,
    workflow_id=VALIDATOR_WORKFLOW_ID,
    workflow_name=VALIDATOR_WORKFLOW_NAME,
    overlay=VALIDATOR_OVERLAY,
)
BRIEF_NODE_REGISTRY = NodeRegistry.from_flow_structure(BRIEF_STRUCTURE)
VALIDATOR_NODE_REGISTRY = NodeRegistry.from_flow_structure(VALIDATOR_STRUCTURE)
BRIEF_WORKFLOW = WorkflowSummary(
    id=BRIEF_GRAPH.id,
    name=BRIEF_GRAPH.name,
    graph_version=BRIEF_GRAPH.version,
)
VALIDATOR_WORKFLOW = WorkflowSummary(
    id=VALIDATOR_GRAPH.id,
    name=VALIDATOR_GRAPH.name,
    graph_version=VALIDATOR_GRAPH.version,
)

GRAPHS = {
    BRIEF_GRAPH.id: BRIEF_GRAPH,
    VALIDATOR_GRAPH.id: VALIDATOR_GRAPH,
}
NODE_REGISTRIES = {
    BRIEF_GRAPH.id: BRIEF_NODE_REGISTRY,
    VALIDATOR_GRAPH.id: VALIDATOR_NODE_REGISTRY,
}
WORKFLOWS = {
    BRIEF_WORKFLOW.id: BRIEF_WORKFLOW,
    VALIDATOR_WORKFLOW.id: VALIDATOR_WORKFLOW,
}
