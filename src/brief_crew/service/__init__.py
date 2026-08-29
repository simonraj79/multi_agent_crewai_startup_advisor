"""M1 in-memory service surface."""

from brief_crew.service.app import ServiceDependencyError, create_app
from brief_crew.service.graph import (
    BRIEF_GRAPH,
    BRIEF_NODE_REGISTRY,
    BRIEF_WORKFLOW,
    GRAPHS,
    NODE_REGISTRIES,
    VALIDATOR_GRAPH,
    VALIDATOR_NODE_REGISTRY,
    VALIDATOR_WORKFLOW,
    WORKFLOWS,
    build_graph_descriptor,
)
from brief_crew.service.registry import RunRecord, RunRegistry, WorkflowRuntime
from brief_crew.service.runner import (
    BriefFlowRunner,
    RunExecution,
    Runner,
    SyntheticRunner,
    SyntheticValidatorRunner,
    ValidatorFlowRunner,
)


__all__ = [
    "BRIEF_GRAPH",
    "BRIEF_NODE_REGISTRY",
    "BRIEF_WORKFLOW",
    "GRAPHS",
    "NODE_REGISTRIES",
    "VALIDATOR_GRAPH",
    "VALIDATOR_NODE_REGISTRY",
    "VALIDATOR_WORKFLOW",
    "WORKFLOWS",
    "BriefFlowRunner",
    "RunExecution",
    "RunRecord",
    "RunRegistry",
    "Runner",
    "ServiceDependencyError",
    "SyntheticRunner",
    "SyntheticValidatorRunner",
    "ValidatorFlowRunner",
    "WorkflowRuntime",
    "build_graph_descriptor",
    "create_app",
]
