"""HTTP and WebSocket boundary models for the M1 service."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


class WorkflowSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    graph_version: str


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    kind: Literal[
        "agent",
        "gate",
        "output",
        "quarantine",
        "router",
        "start",
        "step",
    ]
    description: str
    eyebrow: str
    position: dict[Literal["x", "y"], float]
    model: str | None = None
    tool: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    target: str
    label: str | None = None
    condition_type: str | None = None
    route: str | None = None


class GraphDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: str
    start_nodes: list[str]
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(default="brief-flow", min_length=1, max_length=128)
    inputs: dict[str, Any] = Field(default_factory=dict)


class CreateRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    graph_version: str


class GateOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    emphasis: Literal["primary", "danger"] | None = None


class GatePrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: str
    node_id: str
    title: str
    summary: str
    editable: bool
    expires_at: datetime | None = None
    options: list[GateOption]
    fields: dict[str, str] | None = None
    verdict: str | None = None
    confidence: float | None = None


class GateReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str = Field(min_length=1, max_length=64)
    fields: dict[str, str] = Field(default_factory=dict)


class GateReplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    gate_id: str
    status: RunStatus


class CancelRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    effect: str
    eta_hint: str


class FrameCounters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    captured: int
    dropped: int
    gaps: int
    emit_errors: int
    subscriber_dropped: int
    first_seq: int | None
    last_seq: int | None


class UsageMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    successful_requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    elapsed_ms: int = 0
    cost_usd: float = 0.0


class NodeUsage(UsageMetrics):
    node_id: str
    model: str


class RunStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    session_id: str
    workflow_id: str
    graph_version: str
    status: RunStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    pending_gate: GatePrompt | None
    frames: FrameCounters
    usage: UsageMetrics
    node_usage: list[NodeUsage] = Field(default_factory=list)
    result: Any = None
    error: str | None = None


class DependencyStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "error", "not_configured"]
    backend: str | None = None
    workers: int | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "not_ready"]
    dependencies: dict[str, DependencyStatus]


class FramePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    after: int
    next_after: int
    count: int
    frames: list[dict[str, Any]]


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str
