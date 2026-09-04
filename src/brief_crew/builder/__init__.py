"""The drag-and-drop flow builder: document, bounds, static budget.

Three modules, and the split is a contract rather than a filing convention:

* `document.py` parses SHAPE and raises. One object at a time.
* `bounds.py` checks STRUCTURE and reports. Counts, wiring, cycles, the
  compiled namespace - everything that needs to see more than one node.
* `budget.py` prices what was drawn and reports. The only module that reads
  `PRICES`.
* `registry.py` checks the models a document NAMES against the roster
  `config.py` loaded, and reports. The only module that reads capability flags.

Nothing here executes a flow, constructs an agent, or reaches a network. The
compiler and the runtime are separate; this package is what says yes.
"""

from __future__ import annotations

from brief_crew.builder.bounds import (
    Problem,
    Severity,
    back_edge_indices,
    back_edges,
    billable_depths,
    compiled_identifiers,
    has_errors,
    nodes_on_cycles,
    structural_problems,
)
from brief_crew.builder.budget import (
    BudgetEstimate,
    NodeCost,
    budget_problems,
    estimate_budget,
    node_call_count,
    node_model,
    static_cost_usd,
)
from brief_crew.builder.registry import (
    MODEL_LACKS_CAPABILITY,
    MODEL_OVER_CEILING,
    MODEL_UNKNOWN,
    model_problems,
    registry_document,
    registry_payload,
)
from brief_crew.builder.document import (
    AgentConfig,
    AuthoredAgentConfig,
    AuthoredCrewConfig,
    BuilderBudget,
    BuilderDocument,
    BuilderEdge,
    BuilderModel,
    BuilderNode,
    CrewConfig,
    FlowStateField,
    FlowStateSchema,
    GateConfig,
    InputConfig,
    LibraryAgentConfig,
    LibraryCrewConfig,
    LlmConfig,
    McpConfig,
    NodeKind,
    OutputConfig,
    PlanningConfig,
    RetryConfig,
    SkillConfig,
    TaskConfig,
    ToolConfig,
    Position,
    RouterBranch,
    RouterConfig,
    Tier,
    TransformConfig,
)

__all__ = [
    "MODEL_LACKS_CAPABILITY",
    "MODEL_OVER_CEILING",
    "MODEL_UNKNOWN",
    "AgentConfig",
    "AuthoredAgentConfig",
    "AuthoredCrewConfig",
    "BudgetEstimate",
    "NodeCost",
    "BuilderBudget",
    "BuilderDocument",
    "BuilderEdge",
    "BuilderModel",
    "BuilderNode",
    "CrewConfig",
    "FlowStateField",
    "FlowStateSchema",
    "GateConfig",
    "InputConfig",
    "LibraryAgentConfig",
    "LibraryCrewConfig",
    "LlmConfig",
    "McpConfig",
    "NodeKind",
    "OutputConfig",
    "PlanningConfig",
    "Position",
    "RetryConfig",
    "SkillConfig",
    "TaskConfig",
    "ToolConfig",
    "Problem",
    "RouterBranch",
    "RouterConfig",
    "Severity",
    "Tier",
    "TransformConfig",
    "back_edge_indices",
    "back_edges",
    "billable_depths",
    "budget_problems",
    "compiled_identifiers",
    "estimate_budget",
    "has_errors",
    "model_problems",
    "registry_document",
    "registry_payload",
    "node_call_count",
    "node_model",
    "nodes_on_cycles",
    "static_cost_usd",
    "structural_problems",
    "validate_document",
]


def validate_document(
    document: BuilderDocument, *, ceiling_usd: float | None = None
) -> list[Problem]:
    """Every reason this document may not be published, structure then price.

    The order matters to whoever reads the list: a graph that is over budget
    because it is also miswired should say what is miswired first, and the
    price problem is then the consequence rather than the finding. The model
    checks sit BETWEEN the two for the same reason: a node naming a model this
    build does not have is also a node `budget.py` cannot price, and reading
    "this graph cannot be priced" before "this model is not in the roster"
    describes the symptom before the cause.

    It answers about STRUCTURE and PRICE only, and deliberately not about the
    agent and crew library: `structural_problems` reads a document on its own
    terms, while `library_problems` asks whether this deployment can build what
    the document names. Keeping them apart is what lets every fixture in
    `tests/builder/` wire a realistic topology out of placeholder agent ids.
    The service composes both - see `document_problems` in `compiler.py`, which
    is what every endpoint an author touches actually calls.
    """

    return (
        structural_problems(document)
        + model_problems(document)
        + budget_problems(document, ceiling_usd=ceiling_usd)
    )
