"""Graph descriptors derived from CrewAI's static Flow definitions."""

from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any, TYPE_CHECKING

from crewai.flow import build_flow_structure

from brief_crew.events import NodeRegistry, QUARANTINE_NODE_ID
from brief_crew.main import BriefFlow
from brief_crew.service.models import GraphDescriptor, GraphEdge, GraphNode, WorkflowSummary
from brief_crew.validator_flow import ValidatorFlow


if TYPE_CHECKING:  # pragma: no cover - typing only
    # Under TYPE_CHECKING because the dependency runs the other way at runtime:
    # `builder/descriptor.py` imports `service/models.py`, and importing the
    # builder package from here would drag the compiler, the runtime and the
    # whole document schema into every module that only wanted a graph.
    from brief_crew.builder.descriptor import BuilderWorkflow


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


# Which Crew, Agent and Task actually run at each Flow method.
#
# Declared, not derived: deriving it means constructing the crews, and every
# constructed agent builds an LLM client, an httpx pool and an SSL trust store
# - the same cost that `llm=None` on the two gates exists to avoid, paid at
# import of this module. `tests/service/test_graph_crew_binding.py` builds them
# once and asserts every string here, so drift fails a test instead of
# appearing on a node card.
#
# Note two pairs share a crew: `scope_idea`/`revise_scope` are the same Scoper,
# and `synthesize`/`revise_verdict` are the same Synthesist. The graph draws
# four cards; there are two agents.
VALIDATOR_CREW_WIRING: dict[str, dict[str, str]] = {
    "scope_idea": {"crew": "ScopeCrew", "agent_role": "Startup validation scoper", "task_name": "scoping_task"},
    "revise_scope": {"crew": "ScopeCrew", "agent_role": "Startup validation scoper", "task_name": "scoping_task"},
    "research_market": {"crew": "MarketCrew", "agent_role": "Market evidence analyst", "task_name": "market_task"},
    "research_sentiment": {"crew": "SentimentCrew", "agent_role": "Community demand analyst", "task_name": "sentiment_task"},
    "research_feasibility": {"crew": "FeasibilityCrew", "agent_role": "Technical feasibility analyst", "task_name": "feasibility_task"},
    "synthesize": {"crew": "SynthesisCrew", "agent_role": "Startup validation synthesist", "task_name": "synthesis_task"},
    "revise_verdict": {"crew": "SynthesisCrew", "agent_role": "Startup validation synthesist", "task_name": "synthesis_task"},
    "write_report": {"crew": "ReportCrew", "agent_role": "Validation report writer", "task_name": "reporting_task"},
}

BRIEF_CREW_WIRING: dict[str, dict[str, str]] = {
    # One node, a three-agent crew. Named for the crew rather than for any one
    # agent, because no single role is the truth here - which is exactly what
    # the "Cheap tier" badge got wrong.
    "scrape_web": {"crew": "BriefCrew (track B)"},
}


def _human_feedback_methods(flow_class: type[Any]) -> frozenset[str]:
    """Flow methods that declare @human_feedback, straight from CrewAI.

    `build_flow_structure` reads a method's `human_feedback` only for its
    `emit` value (`flow/visualization/builder.py:77-82`), and both validator
    gates declare `emit=None` - so the projection this graph is built from
    cannot tell a human gate from any other listener, and `"kind": "gate"` in
    the overlay was a hand-typed claim about a fact CrewAI holds with
    certainty. `FlowDefinition` still has it.
    """

    definition = getattr(flow_class, "flow_definition", None)
    if definition is None:
        return frozenset()
    try:
        methods = definition().methods
    except Exception:  # pragma: no cover - a flow with no definition
        return frozenset()
    return frozenset(
        name
        for name, method in methods.items()
        if getattr(method, "human_feedback", None) is not None
    )


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
    crew_wiring: dict[str, dict[str, str]] | None = None,
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

    human_feedback_methods = _human_feedback_methods(flow_class)
    wiring = crew_wiring or {}

    nodes: list[GraphNode] = []
    for index, (node_id, metadata) in enumerate(structure["nodes"].items()):
        display = overlay[node_id] if overlay is not None else {}
        crew_binding = wiring.get(node_id, {})
        # A gate is a gate because CrewAI says so, not because someone typed it.
        # Guarding both directions: an overlay that forgets to mark a new
        # @human_feedback method, and one that marks a method that is not one.
        declares_feedback = node_id in human_feedback_methods
        if overlay is not None and declares_feedback != (display.get("kind") == "gate"):
            raise RuntimeError(
                f"node {node_id!r}: CrewAI reports human_feedback="
                f"{declares_feedback} but the overlay kind is "
                f"{display.get('kind')!r}; the two must agree"
            )
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
                flow_method_type=metadata.get("type"),
                human_feedback=declares_feedback,
                condition_type=metadata.get("condition_type"),
                trigger_methods=list(metadata.get("trigger_methods", [])),
                router_events=list(metadata.get("router_events", [])),
                crew=crew_binding.get("crew"),
                agent_role=crew_binding.get("agent_role"),
                task_name=crew_binding.get("task_name"),
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

BRIEF_GRAPH = build_graph_descriptor(overlay=BRIEF_OVERLAY, crew_wiring=BRIEF_CREW_WIRING)
VALIDATOR_GRAPH = build_graph_descriptor(
    ValidatorFlow,
    workflow_id=VALIDATOR_WORKFLOW_ID,
    workflow_name=VALIDATOR_WORKFLOW_NAME,
    overlay=VALIDATOR_OVERLAY,
    crew_wiring=VALIDATOR_CREW_WIRING,
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


# --------------------------------------------------------------------------
# Builder graphs, registered additively at runtime
#
# The three maps above are literals because both hand-written flows exist at
# import. A builder graph does not: it is a row in a database that somebody
# published after this module was imported, so registration is a MUTATION of
# the same three dicts plus a fourth of its own.
#
# Additive by construction, and the measurement is why that word is doing real
# work here. Registering a third workflow into the three maps and running the
# whole suite is `Ran 809 tests ... OK`, with the validator's ETag byte
# identical either side. MUTATING the validator's topology instead - which is
# what any attempt to route a builder graph through `build_graph_descriptor`
# would eventually require - is 480 run / 77 errors across 28 modules, because
# the overlay assertion at `:150` raises inside the module-level constant at
# `:251` and every importer dies at import.
#
# So: nothing below touches BRIEF_*, VALIDATOR_*, either overlay, or
# `build_graph_descriptor`. A builder descriptor is built directly from its
# document by `builder/descriptor.py`.
#
# `GET /api/workflows` is deliberately NOT fed from `WORKFLOWS`; it returns the
# two literals, and builder graphs are listed on their own route. That literal
# is the only reason `test_validator_service`'s set equality still holds, and
# relaxing it to make room here would be a weakening rather than a feature.
# --------------------------------------------------------------------------
BUILDER_WORKFLOWS: dict[str, "BuilderWorkflow"] = {}


def register_builder_workflow(workflow: "BuilderWorkflow") -> "BuilderWorkflow":
    """Put a compiled builder graph into every map that has to know about it.

    Four places, and omitting any one of them is a distinct wrong answer rather
    than a missing feature:

    * `GRAPHS` - or `GET /api/workflows/{id}/graph` answers 404 for a graph the
      service is willing to run, and `workflow_has_gates` fails closed on it.
    * `NODE_REGISTRIES` - or every frame the run emits lands on the
      quarantine node.
    * `WORKFLOWS` - or `create_run` answers 404 before it reaches the runtime.
    * `BUILDER_WORKFLOWS` - the record `app.py` reads for the two policy
      questions a hand-written flow never raises: is there a gate before the
      first billable node, and what does this graph cost before it starts.
    * and `config.register_workflow_reserved_run_input_keys`, which is not a
      map on this module but is the fifth thing that must move in step: a
      builder graph declares its own state names, and until they are declared
      here `reserved_run_input_keys` fails closed to the union - refusing an
      author's perfectly ordinary `verdict` key because the validator reserves
      one.

    The RUNTIME map `create_app` builds is the sixth, and it is not touched
    here: this module has no registry instance. `service/builder_api.py`
    registers that half in the same request, and `UnknownWorkflowError` is what
    reports it if the two ever come apart.

    Re-registering the same workflow id replaces every entry, which is what a
    republish is.
    """

    from brief_crew.config import register_workflow_reserved_run_input_keys

    workflow_id = workflow.workflow_id
    GRAPHS[workflow_id] = workflow.descriptor
    NODE_REGISTRIES[workflow_id] = workflow.node_registry
    WORKFLOWS[workflow_id] = WorkflowSummary(
        id=workflow_id,
        name=workflow.descriptor.name,
        graph_version=workflow.graph_version,
    )
    BUILDER_WORKFLOWS[workflow_id] = workflow
    register_workflow_reserved_run_input_keys(
        workflow_id, workflow.reserved_input_keys
    )
    return workflow


def unregister_builder_workflow(workflow_id: str) -> None:
    """Remove a builder graph from all FIVE maps, refusing to touch a built-in.

    Five, because `register_builder_workflow` writes five, and this function
    said four and cleared four for long enough that three separate reviewers
    filed it independently. The missing one is
    `config.WORKFLOW_RESERVED_RUN_INPUT_KEYS`, and it is the one whose staleness
    does not announce itself: the other four make a deleted graph 404, which is
    loud, while a left-behind reserved-key declaration silently goes on
    refusing that dead graph's state names in some later author's `inputs` -
    and, through `all_reserved_run_input_keys`, in every unknown id's answer
    too. Publish rollback, rehydration rollback and delete all land here, so
    all three leaked it.

    The guard is not defensive politeness: `GRAPHS` and `WORKFLOWS` are the
    dicts the two hand-written flows live in, and a delete keyed on an
    attacker- or bug-supplied id would take `idea-validator` out of the service
    with no error anywhere.
    """

    from brief_crew.config import forget_workflow_reserved_run_input_keys

    if workflow_id in {BRIEF_GRAPH.id, VALIDATOR_GRAPH.id}:
        raise ValueError(f"{workflow_id} is a built-in workflow and is not removable")
    BUILDER_WORKFLOWS.pop(workflow_id, None)
    GRAPHS.pop(workflow_id, None)
    NODE_REGISTRIES.pop(workflow_id, None)
    WORKFLOWS.pop(workflow_id, None)
    forget_workflow_reserved_run_input_keys(workflow_id)


def builder_workflow(workflow_id: str) -> "BuilderWorkflow | None":
    """The builder record for this id, or None for a built-in or unknown id."""

    return BUILDER_WORKFLOWS.get(workflow_id)
