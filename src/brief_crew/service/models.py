"""HTTP and WebSocket boundary models for the M1 service."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from brief_crew.config import (
    MAX_RUN_INPUT_BYTES,
    MAX_RUN_INPUT_KEYS,
    RESERVED_RUN_INPUT_KEYS,
)


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
    """The one request on this service that spends the owner's money.

    The endpoint is public and unauthenticated, so ``inputs`` - which stays
    ``dict[str, Any]`` because each workflow names its own input - is bounded
    in two places, deliberately:

    * Here: the SHAPE. A key count and a total JSON size, which together bound
      nesting, key length and every non-string value. A request that trips one
      of these is a broken or hostile client, not a mistyped idea.
    * In the ``create_run`` handler: the LENGTH of the one input that becomes a
      model prompt. That check knows which key the workflow reads, so it can
      answer with a sentence naming the operator's own field instead of a
      schema error list - and FastAPI's schema errors echo the offending input
      back, which is the last thing to do with a megabyte of hostile text.

    The size check runs before anything else for exactly that reason: it caps
    what a validation failure can quote back.

    See the admission-control block in ``config.py`` for the numbers.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(default="brief-flow", min_length=1, max_length=128)
    inputs: dict[str, Any] = Field(default_factory=dict)
    #: Who answers the scope and verdict gates.
    #:
    #: ``human`` pauses at both and waits for an operator - the default, and the
    #: only mode a public deployment should accept, because the pause is what
    #: bounds the spend. ``auto`` answers them itself and runs the whole
    #: pipeline unattended; the handler refuses it unless
    #: ``VALIDATOR_ALLOW_AUTO_GATES`` is set.
    #:
    #: A named mode rather than a bare bool: it reads correctly in OpenAPI, it
    #: says what the alternative IS instead of what it is not, and it leaves
    #: room for a third answerer later.
    gates: Literal["human", "auto"] = "human"

    @field_validator("inputs")
    @classmethod
    def _bounded_inputs(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("inputs must be JSON-serialisable") from exc
        if len(encoded) > MAX_RUN_INPUT_BYTES:
            raise ValueError(
                f"inputs is limited to {MAX_RUN_INPUT_BYTES} bytes of JSON"
            )
        if len(value) > MAX_RUN_INPUT_KEYS:
            raise ValueError(f"inputs carries at most {MAX_RUN_INPUT_KEYS} keys")
        # Refuse, rather than silently drop. `inputs` is merged wholesale into
        # the flow's pydantic state by CrewAI, so before this check every field
        # on `ValidatorState` was settable from the public request body -
        # `no_gates` among them, which is the `gates` field above wearing a
        # disguise and skipping every policy attached to it. Answering 422
        # tells an honest client its request was misread; dropping the key
        # would let a stale one think it had switched modes.
        reserved = sorted(RESERVED_RUN_INPUT_KEYS.intersection(value))
        if reserved:
            raise ValueError(
                "inputs may not carry the reserved control "
                f"{'keys' if len(reserved) > 1 else 'key'} {', '.join(reserved)}; "
                "use the request's own fields instead"
            )
        return value


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


class GateDerivedField(BaseModel):
    """One value the operator must be able to read but cannot change.

    The verdict gate's whole payload lands here: the schema recomputes the
    arithmetic and discards whatever it was sent, and the evidence-scored
    inputs to that arithmetic are bound by guardrails that only run on the
    Synthesist's output. They are still the basis for approving or revising, so
    they are carried in full - just not as form inputs.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    value: str
    # "json" values are pretty-printed and belong in a block, not a line.
    kind: Literal["text", "json"] = "text"


class GatePrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: str
    node_id: str
    title: str
    summary: str
    # "this gate has at least one editable field", not "every field is". Which
    # fields those are is the fields/derived split below.
    editable: bool
    expires_at: datetime | None = None
    # PRD F03. Advisory: an expired gate still accepts a reply and still
    # resumes the run, and its run stays WAITING rather than failing.
    expired: bool = False
    options: list[GateOption]
    # Editable only. A field the operator's edit cannot reach is never offered
    # as an input, so a client that predates this split cannot render one.
    fields: dict[str, str] | None = None
    # Defaulted so a gate row persisted before this field existed still
    # validates on recovery.
    derived: list[GateDerivedField] = Field(default_factory=list)
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


class GateReplyMessageData(BaseModel):
    """The body of an inbound WebSocket ``gate_reply``.

    ``run_id`` is optional and advisory: the socket is already bound to one
    run, so a mismatch is rejected rather than honoured. Everything else
    mirrors :class:`GateReplyRequest`, because the two transports must reach
    ``registry.answer_gate`` with identical arguments.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str | None = Field(default=None, max_length=128)
    gate_id: str = Field(min_length=1, max_length=128)
    outcome: str = Field(min_length=1, max_length=64)
    fields: dict[str, str] = Field(default_factory=dict)


class GateReplyMessage(BaseModel):
    """PRD F27/F37: an operator gate reply arriving on the streaming socket."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["gate_reply"]
    request_id: str | None = Field(default=None, max_length=128)
    data: GateReplyMessageData


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
    # PRD F21: frames that reached the visible ``unattributed`` quarantine node
    # because CrewAI could not tie them to a declared graph node. Defaulted so
    # a run row written before this field existed still validates.
    unattributed: int = 0
    first_seq: int | None = None
    last_seq: int | None = None


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


class GateWatchStatus(BaseModel):
    """The PRD R-2 signal: unanswered gates, and how far past due they are."""

    model_config = ConfigDict(extra="forbid")

    open: int = 0
    expired: int = 0
    alerting: int = 0
    expiries: int = 0
    alerts: int = 0
    sweeps: int = 0


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "not_ready"]
    dependencies: dict[str, DependencyStatus]
    gates: GateWatchStatus = Field(default_factory=GateWatchStatus)


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
