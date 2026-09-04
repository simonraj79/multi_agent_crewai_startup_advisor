"""HTTP and WebSocket boundary models for the M1 service."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from brief_crew.config import (
    MAX_RUN_INPUT_BYTES,
    MAX_RUN_INPUT_KEYS,
    declared_reserved_run_input_keys,
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

    # --- CrewAI facts, derived from the Flow itself ------------------------
    # Everything below is read out of `build_flow_structure` or
    # `Flow.flow_definition()` rather than typed by hand, and is promoted to a
    # first-class field precisely because `metadata` was already carrying most
    # of it and the client had no field to receive it: `GraphNodeDefinition` in
    # `types/studio.ts` had no `metadata` key at all, so every one of these
    # travelled the wire and was dropped on arrival.
    #
    # `flow_method_type` is CrewAI's own vocabulary, not this file's. CrewAI's
    # Flow topology has exactly three node types - start, listen, router
    # (`flow/visualization/builder.py:180,183,188`) - where `kind` above has
    # seven, of which "gate" is not a CrewAI word anywhere in the package and
    # "step" collides with both the PRE_STEP hook point and Plan-and-Execute
    # step numbers. `kind` stays because the UI keys its iconography off it;
    # this field is what the UI should *say*.
    flow_method_type: Literal["start", "listen", "router"] | None = None
    # True when the method carries @human_feedback. Derived from
    # `FlowDefinition`, which `build_flow_structure` discards - so this is the
    # one fact the UI asserted ("kind": "gate") about something CrewAI knows
    # for certain and the projection threw away.
    human_feedback: bool = False
    # "AND" or "OR" - which is what makes the three-branch fan-in into
    # `synthesize` structurally visible. Note a bare @listen("x") also reports
    # "OR", so this is the trigger's semantics, not evidence the author wrote
    # or_().
    condition_type: str | None = None
    # The upstream method names this node waits on.
    trigger_methods: list[str] = Field(default_factory=list)
    # For routers: every branch label the method can emit.
    router_events: list[str] = Field(default_factory=list)

    # --- Crew wiring, hand-declared but test-bound -------------------------
    # These name the Crew, Agent role and Task that actually run at this node.
    # They are declared rather than derived because deriving them means
    # constructing the crews, and constructing a crew builds an LLM client, an
    # httpx pool and an SSL trust store per agent - the exact cost that
    # `llm=None` on the gates exists to avoid. `tests/service/test_graph_crew_binding.py`
    # constructs them once and asserts these strings match, so a drift is a
    # test failure rather than a lie on screen.
    crew: str | None = None
    agent_role: str | None = None
    task_name: str | None = None

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


class ResumeFrom(BaseModel):
    """Which run to replay, and where to start running for real again."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=128)


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
    #: What KIND of run this is - .agent/plans/10-runtime.md D8, contract C7.
    #:
    #: `run` is the default and is everything this endpoint did before. `test`
    #: is an ordinary run that is LABELLED one (decision 17: a test run appears
    #: in run history, because hiding it means an author cannot find the run
    #: they just made) and passes every admission check, the same rate limit,
    #: the same ceiling and the same frames - it is not a cheaper run, it is a
    #: findable one. `node_test` runs ONE node over a saved input with every
    #: node above it replayed. `dry_run` creates nothing at all.
    #:
    #: A named mode rather than three booleans, for `gates`' own reason: it
    #: reads correctly in OpenAPI and it leaves room for a fourth.
    mode: Literal["run", "test", "dry_run", "node_test"] = "run"
    #: A `builder_test_inputs` row of the caller's (C10). Required for
    #: `node_test`, which has nothing to run the node against without one.
    test_input_id: str | None = Field(default=None, max_length=128)
    #: The one node `node_test` runs for real. Every step above it replays.
    node_id: str | None = Field(default=None, max_length=128)
    #: Start again from a node of a run that already happened, replaying
    #: everything above it. The source run must be the caller's own and must be
    #: terminal - resuming from a run that is still going would replay a state
    #: that is still being written.
    resume_from: ResumeFrom | None = None

    @field_validator("inputs")
    @classmethod
    def _bounded_inputs(
        cls, value: dict[str, Any], info: ValidationInfo
    ) -> dict[str, Any]:
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
        #
        # PER WORKFLOW, because a user-authored graph declares its own state
        # names and "reserved" stopped being one global fact the moment a third
        # workflow could exist: `verdict` is a control key on the validator and
        # an ordinary word on somebody's competitor-sweep graph. This works
        # without moving the check off the model - which is what keeps the
        # 403-versus-422 distinction in `create_run` meaningful - because
        # pydantic validates fields in DECLARATION order and `workflow_id` is
        # declared above `inputs`, so `info.data` already carries a VALIDATED
        # workflow id here.
        #
        # DECLARED keys only, and the distinction is the whole reason there are
        # two functions. This layer holds a workflow id and nothing else - no
        # registry, no descriptor, no runtime - so it cannot tell "registered on
        # this service but undeclared in config" from "invented". Failing closed
        # to the union of every workflow's keys here therefore refused a third
        # workflow's own prompt field: `brief` is Brief Crew's result slot and
        # somebody else's perfectly ordinary public input, and its author was
        # told their prompt was a reserved control key by a workflow that has
        # never heard of their graph.
        #
        # The union still applies - `create_run` asks for it, once it has
        # resolved the workflow and knows which single key is its prompt. What
        # survives here is the part that needs no registry to be right: the keys
        # CrewAI's own runtime reads on ANY flow, refused for every id including
        # invented ones. `no_gates` is one of them, so setting it in `create_run`
        # remains the only way it can become true.
        #
        # And NOTHING a publish registered (D-01-1). This validator runs before
        # `create_run`'s rate limiter and before its ownership check, so any
        # answer that differs between a published id and an invented one is an
        # unthrottled oracle for which ids exist and what their nodes are
        # called - which is exactly what it was while
        # `declared_reserved_run_input_keys` read the registered map. It now
        # answers the two public built-ins' declared names and the global set
        # for every other id; a published graph's own keys are refused by
        # `create_run`, after the caller has been allowed to see that graph.
        reserved = sorted(
            declared_reserved_run_input_keys(
                info.data.get("workflow_id")
            ).intersection(value)
        )
        if reserved:
            raise ValueError(
                "inputs may not carry the reserved control "
                f"{'keys' if len(reserved) > 1 else 'key'} {', '.join(reserved)}; "
                "use the request's own fields instead"
            )
        return value


class DryRunResponse(BaseModel):
    """C7's `mode: dry_run` answer: `POST /validate` plus the artifact.

    A 200 and not a 202, because nothing was accepted for later - there is no
    run to poll. The definition is the literal document
    `Flow.from_declaration` would have been handed, which is the only version of
    it worth showing: a second rendering would be wrong the first time the
    compiler changed.
    """

    model_config = ConfigDict(extra="forbid")

    valid: bool
    problems: list[dict[str, Any]] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    definition: dict[str, Any] = Field(default_factory=dict)


class RunStateResponse(BaseModel):
    """C7's `GET /api/runs/{run_id}/state?step=` - the flow state at one frame."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    step: int
    state: dict[str, Any] = Field(default_factory=dict)


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
    # How many `decision: "revise"` replies this gate will still honour, and
    # the budget that number counts down from. A client displays them ("2 of 5
    # revisions left"); it must not have to INFER the limit from the absence of
    # a Revise option, because the absence of an option is also what an older
    # server looks like.
    #
    # Both are defaulted to None so a `run_gates.request` row written before the
    # cap existed still validates on recovery. None means "this gate predates
    # the bound", which is a different statement from 0, and 0 is the one that
    # means "no revises left".
    revise_turns_remaining: int | None = None
    max_revise_turns: int | None = None
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
    # The deterministic score, mirrored off this run's `verdict` frame so a REST
    # consumer gets it without scanning frames - and so it exists at all under
    # `gates: "auto"`, where no verdict gate opens to carry it. Deliberately not
    # folded into `result`: `result` is the flow's own return value, a
    # `ValidationReport`, and putting the score there would mean the Reporter
    # had to emit arithmetic the schema recomputes. Untyped for the same reason
    # `result` is: the shape is the frame contract in `events/serializer.py`,
    # pinned by a fixture on both sides, and a second declaration here could
    # only drift from it.
    verdict: dict[str, Any] | None = None
    error: str | None = None
    # Why a non-completed run ended, when `status` alone does not say. `None`
    # for an ordinary end - including an operator pressing Cancel, which is a
    # human already knowing why. `"cost_ceiling"` means the run stopped itself
    # on MAX_RUN_COST_USD; `error` carries the sentence and the figures. The
    # reasons are `registry.COST_CEILING_REASON` and `INTERRUPTED_REASON`, and
    # this is a string rather than a Literal so adding a third does not become
    # a breaking API change.
    stop_reason: str | None = None
    #: C7: which KIND of run this was. `run` for everything written before the
    #: column existed - the table's NULL reads as `run`, and nothing is
    #: backfilled.
    mode: str = "run"
    #: `{run_id, node_id}` when this run replayed another one, else None.
    resume_from: dict[str, str] | None = None


class RunHistoryEntry(BaseModel):
    """One row of "your runs".

    A summary, not a `RunStatusResponse`. It deliberately carries no frames, no
    node usage, no pending gate and no result body - a 25-row list would
    otherwise ship several megabytes of report Markdown to render a list of
    dates, and the client already has `GET /api/runs/{id}` for the one row the
    operator actually opens.

    `session_id` is absent for a different reason: it is a capability. Anyone
    holding a run id AND its session id can open the run's WebSocket, so
    listing it beside every historical run would hand out a bundle of live
    stream credentials to render a sidebar.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    workflow_id: str
    status: RunStatus
    created_at: datetime
    completed_at: datetime | None = None
    # The `idea` (or `topic`) the run was launched with, clipped for a list.
    # This is what makes the row recognisable - a column of uuids is not a
    # history anyone can use.
    label: str = ""
    total_tokens: int = 0
    cost_usd: float = 0.0


class RunHistoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[RunHistoryEntry] = Field(default_factory=list)


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
