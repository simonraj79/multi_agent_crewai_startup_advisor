"""Workflow-aware run registry with durable state and live subscriptions."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, wait as wait_for_futures
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread, current_thread
from time import monotonic
from types import MappingProxyType
from typing import Any, Callable, Mapping
import uuid

from crewai.flow.async_feedback import HumanFeedbackPending, PendingFeedbackContext
from crewai.hooks import HookAborted, InterceptionPoint
from crewai.hooks.dispatch import register_scoped, scoped_hooks

from brief_crew.config import (
    GATE_EDITABLE_FIELDS_METADATA_KEY,
    GATE_EXPIRY_METADATA_KEY,
    GATE_LABEL_METADATA_KEY,
    GATE_MAX_TURNS_METADATA_KEY,
    GATE_REVISE_TURNS_METADATA_KEY,
    MAX_QUEUED_RUNS,
    MAX_RUN_COST_USD,
    MAX_RUN_RESULT_BODY_CHARS,
    RUN_ADMISSION_RETRY_AFTER_SECONDS,
    RUN_CONCURRENCY,
    RUN_RESULT_BODY_KEYS,
    RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS,
    VALIDATOR_FRAME_BATCH_SIZE,
    VALIDATOR_FRAME_FLUSH_INTERVAL_SECONDS,
    VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS,
    VALIDATOR_GATE_SWEEP_INTERVAL_SECONDS,
    VALIDATOR_GATE_TIMEOUT_SECONDS,
    VALIDATOR_MAX_GATE_TURNS,
    VALIDATOR_ORPHAN_RUN_GRACE_SECONDS,
    VALIDATOR_ORPHAN_RUN_RECOVERY,
    VALIDATOR_PERSIST_QUEUE_CAPACITY,
    VALIDATOR_RUN_RETENTION_SECONDS,
    compute_cost_usd,
)
from brief_crew.events import (
    CaptureContext,
    DEFAULT_RING_CAPACITY,
    FrameBuffer,
    FrameData,
    FrameDraft,
    FrameKind,
    FrameLevel,
    MAX_REPLAY_LIMIT,
    NodeRegistry,
    StreamSinkAdapter,
    UIEventType,
    capture_events,
)
from brief_crew.service.models import RunStatus
from brief_crew.service.runner import BriefFlowRunner, RunExecution, Runner
from brief_crew.events.serializer import normalize_usage


DEFAULT_SUBSCRIBER_CAPACITY = 512
# PRD F30: statuses a run can never leave on its own. Everything else -
# QUEUED, RUNNING, CANCELLING and above all WAITING - is still live work and
# is never evicted from memory, however old it is.
TERMINAL_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
)
# Remaining-work item 32: statuses that assert "a worker is doing this right
# now". WAITING is deliberately absent - it is durably anchored by the
# run_gates row and the pending_feedback row, so it survives a restart and
# resumes. These three do not: their Future died with the process.
INTERRUPTIBLE_STATUSES = frozenset(
    {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.CANCELLING}
)
# One reason string, used by the frame, the durable `error` column and the
# gate row, so the trace, the API and the database all say the same thing.
INTERRUPTED_REASON = "service_restart"
INTERRUPTED_ERROR = (
    "interrupted by a service restart: the process executing this run exited "
    "before it finished, and a run that was mid-method carries no resumable "
    "checkpoint - relaunch it"
)
# The same one-reason-string pattern for the OTHER way a run stops without
# anybody asking it to: it ran out of money. A budget stop travels the
# cooperative-cancellation path, so without this it would be indistinguishable
# at the API from an operator pressing Cancel - `status: "cancelled"`, `error:
# null`, and no way to tell "I stopped this" from "this stopped itself". The
# reason goes on the terminal frame's `details.reason` and the sentence goes in
# the durable `error` column, which is what `GET /api/runs/{run_id}` returns.
COST_CEILING_REASON = "cost_ceiling"
# `stop_reason` is in-memory only and is NOT a `runs` column, deliberately:
# `metadata.create_all()` creates missing tables and never adds a column to an
# existing one, so a new column would be silently absent on the live PostgreSQL
# database and every insert naming it would fail. The durable carrier is the
# `error` column, which already exists and is already returned by
# `GET /api/runs/{run_id}`; this prefix is how a restored record recovers the
# reason from it. Keep the two in step - `_restore_record` matches on it.
COST_CEILING_ERROR_PREFIX = "stopped by the per-run cost ceiling:"
COST_CEILING_ERROR = (
    f"{COST_CEILING_ERROR_PREFIX} this run's estimated spend reached "
    "${spent:.4f} against a MAX_RUN_COST_USD ceiling of ${ceiling:.2f}. The "
    "figure is an estimate recomputed from brief_crew.config.PRICES, it counts "
    "only completed LLM calls, and it excludes embedding, rerank and Firecrawl "
    "spend - so the real bill is higher than the number in this message."
)

# PRD F20: a METRICS snapshot carries one row per (node, model) pair. The frame
# contract caps a detail sequence at 64 entries, and no declared graph has
# anywhere near that many, so this only guards against a pathological run.
MAX_METRICS_NODES = 64
_USAGE_INTEGER_FIELDS = (
    "successful_requests",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "call_count",
    "elapsed_ms",
)
logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _restored_stop_reason(stored_error: Any) -> str | None:
    """Recover `stop_reason` from the durable `error` column.

    `stop_reason` has no column of its own on purpose - see
    COST_CEILING_ERROR_PREFIX - so a run reloaded after a restart would
    otherwise come back as an ordinary cancel with a puzzling error string
    attached. The `error` text IS the durable record; this reads the reason back
    out of it.
    """
    if not isinstance(stored_error, str):
        return None
    if stored_error.startswith(COST_CEILING_ERROR_PREFIX):
        return COST_CEILING_REASON
    return None


def _gate_deadline(prompt: Mapping[str, Any] | None) -> datetime | None:
    """The gate's ``expires_at`` as an aware datetime, or None if it carries none.

    The prompt round-trips through JSON and through the ``run_gates`` row, so the
    value arrives as an ISO string on one path and as a datetime on the other.
    """
    if not prompt:
        return None
    raw = prompt.get("expires_at")
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        deadline = raw
    else:
        try:
            deadline = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
    return deadline if deadline.tzinfo is not None else deadline.replace(
        tzinfo=timezone.utc
    )


def _empty_usage() -> dict[str, int | float]:
    return {
        "successful_requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "call_count": 0,
        "elapsed_ms": 0,
        "cost_usd": 0.0,
    }


def _result_body_fields(result: Any) -> dict[str, str]:
    """The deliverable's own text, read off the UN-clipped flow result.

    Read from the original object rather than from the clipped copy, because
    the clipped copy is exactly what has already lost the tail.
    """
    mapping = result if isinstance(result, Mapping) else None
    bodies: dict[str, str] = {}
    for key in RUN_RESULT_BODY_KEYS:
        try:
            # `result` is whatever a flow returned. A property that raises must
            # not turn a finished run into a failed one, and the frame-clipped
            # copy is still a correct - if shorter - answer.
            value = getattr(result, key, None)
            if value is None and mapping is not None:
                value = mapping.get(key)
        except Exception:
            continue
        if isinstance(value, str) and value:
            bodies[key] = value[:MAX_RUN_RESULT_BODY_CHARS]
    return bodies


def _clip_run_result(serializer: Any, result: Any) -> Any:
    """Bound a terminal result without truncating the thing it was run for.

    The frame serializer stays in charge of the shape - depth, item counts, the
    refusal to walk a live CrewAI object - so a flow returning something
    unexpected is bounded exactly as before. The one departure is
    `RUN_RESULT_BODY_KEYS`: those are re-read from the source at
    `MAX_RUN_RESULT_BODY_CHARS`, because `SerializerLimits.max_string` is a
    bound on a streaming frame and has no business being the bound on the
    document the run exists to produce. A result that IS a bare string is the
    same case with no key to name.

    Deliberately per-key rather than a wholesale bigger `SerializerLimits`: a
    generous ceiling applied to every string in an arbitrary result multiplies
    by `max_items`, and `persistence._sanitize_json` would then reject the
    whole row instead of trimming one field.
    """
    if isinstance(result, str):
        return result[:MAX_RUN_RESULT_BODY_CHARS]
    clipped = serializer.clip(result)
    if isinstance(clipped, dict):
        clipped.update(_result_body_fields(result))
    return clipped


def _usage_from_result(result: Any) -> dict[str, int] | None:
    for attribute in ("usage_metrics", "token_usage"):
        value = getattr(result, attribute, None)
        if value is None:
            continue
        usage = normalize_usage(value)
        if any(usage.values()):
            return usage
    return None


# ----------------------------------------------------------------- gate fields

SCOPE_GATE_NODE = "confirm_scope"
VERDICT_GATE_NODE = "review_verdict"

# The one field every gate carries, and the only one the verdict gate carries.
# Both validator routers read the reply's top-level ``feedback`` and hand it to
# the crew that reruns the step - ``route_scope`` -> ``revise_scope``,
# ``route_verdict`` -> ``revise_verdict`` - so this is how an operator's
# judgement re-enters the run rather than being typed over the top of it.
GATE_NOTE_FIELD = "feedback"

# The two prompt keys that tell a client how much of the revise budget is left.
# `revise_turns_remaining` is what a client displays; `max_revise_turns` is what
# turns "2" into "2 of 5". Both are computed when the gate OPENS, from the
# count the flow stamped on the pending context, so a replayed GATE_OPEN frame
# and the stored `run_gates.request` row report the same numbers the operator
# was actually shown.
GATE_REVISE_REMAINING_KEY = "revise_turns_remaining"
GATE_REVISE_MAX_KEY = "max_revise_turns"

# Matches SerializerLimits.max_string, so a value that survives this bound also
# survives the frame the gate is announced on and comes back from replay intact.
MAX_GATE_VALUE_CHARS = 4096


class RunBusyError(RuntimeError):
    """A run cannot be (re)submitted because its previous execution is live.

    A ``RuntimeError`` subclass so nothing that already catches the broad type
    changes behaviour, and its own class so the transport can answer 503
    ("try again") rather than 500 ("this broke"). ``_submit`` raises it only
    after waiting ``RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS`` for the previous future,
    so by the time a caller sees it the run really is still working.
    """

    __slots__ = ("run_id",)

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} is already executing")
        self.run_id = run_id


class RunAdmissionError(RuntimeError):
    """A NEW run was refused because the server already has enough work.

    Distinct from :class:`RunBusyError`, and the distinction is the whole
    point. ``RunBusyError`` means *this* run is mid-execution and resending the
    same reply is the fix, so the transport answers 503. This one means the
    server is full: nothing is wrong with the request, it is simply not being
    admitted, which is a 429 with a Retry-After.

    RUN_CONCURRENCY bounded parallelism and nothing bounded admission -
    CPython's ThreadPoolExecutor queues submissions without limit - so on a
    public unauthenticated endpoint a flood of accepted runs starved the
    owner's own run for as long as the flood lasted. This is that bound.
    """

    __slots__ = ("active", "limit", "retry_after_seconds")

    def __init__(self, *, active: int, limit: int) -> None:
        super().__init__(
            f"{active} runs are already queued or executing; the limit is {limit}"
        )
        self.active = active
        self.limit = limit
        self.retry_after_seconds = RUN_ADMISSION_RETRY_AFTER_SECONDS


class UnknownWorkflowError(KeyError):
    """A workflow id reached this registry with no runtime registered for it.

    A third sibling of :class:`RunBusyError` and :class:`RunAdmissionError`,
    and the same idea: the transport can only answer honestly if the registry
    says *which* kind of no this is. ``_runtime_for`` raised a bare
    ``KeyError`` and nothing caught it, so a workflow registered in ``GRAPHS``,
    ``NODE_REGISTRIES`` and ``WORKFLOWS`` but omitted from the ``workflows=``
    map ``create_app`` builds - three of the four places, which is exactly the
    mistake a fourth registration site invites - surfaced as an uncaught
    exception and a **500**. That tells the caller the service is broken about
    a request that is merely naming something this service does not run.

    A ``KeyError`` subclass rather than a ``RuntimeError`` one, deliberately:
    ``KeyError`` is already this module's vocabulary for "no such thing"
    (``require`` raises one for an unknown run and ``app.py`` turns it into a
    404), so nothing that catches the broad type changes behaviour, and the
    404 the transport now answers is the same answer for the same reason.

    ``__str__`` is overridden because ``KeyError.__str__`` reprs its argument;
    without it the sentence below would arrive wrapped in a stray pair of
    quotes wherever it is forwarded.
    """

    __slots__ = ("workflow_id",)

    def __init__(self, workflow_id: str) -> None:
        super().__init__(
            f"workflow {workflow_id} is not registered on this service"
        )
        self.workflow_id = workflow_id

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


class GateFieldError(ValueError):
    """A gate reply tried to set a field the gate does not accept.

    A ``ValueError`` so a caller that only knows the old contract still refuses
    the reply, with the offending names attached for a precise message.
    """

    def __init__(self, gate_id: str, fields: tuple[str, ...], detail: str) -> None:
        super().__init__(detail)
        self.gate_id = gate_id
        self.fields = fields


def _parsed_gate_output(output: Any) -> dict[str, Any]:
    """The gate's model output as a plain mapping, whatever CrewAI handed over.

    One implementation for the prompt and for the reply: they must agree on what
    the gate is showing, or the reply would fold an edit into a different object
    than the operator was looking at.
    """
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return {GATE_NOTE_FIELD: output}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    if isinstance(output, Mapping):
        return dict(output)
    model_dump = getattr(output, "model_dump", None)
    if model_dump is None:
        return {}
    dumped = model_dump(mode="json")
    return dict(dumped) if isinstance(dumped, Mapping) else {}


def _metadata_turns_used(context: PendingFeedbackContext) -> int:
    """Revise turns already spent at this gate, per the pending context.

    Defensive about the value because ``metadata`` is a free-form dict that has
    been through JSON on the way to and from ``pending_feedback``: a float, a
    numeric string or a missing key all have to resolve to a whole number of
    turns rather than raise inside gate construction, which would fail the run
    at the exact moment a human was about to be asked something.
    """
    raw = (context.metadata or {}).get(GATE_REVISE_TURNS_METADATA_KEY, 0)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True, slots=True)
class _AuthoredGate:
    """What a gate somebody DREW on the builder canvas declares about itself.

    Everything this module used to know about a gate it knew because there were
    exactly two of them and both were compiled into ``validator_flow`` by hand.
    A builder graph breaks all four assumptions at once: its gate is called
    whatever its author called it, it declares which of its payload's keys an
    operator may edit, it carries its own revise budget - which ``route_gate``
    already honours, so a prompt offering more was offering buttons the router
    would decline - and it may close sooner than the service's global timeout.

    ``from_context`` returning ``None`` IS the discriminator between the two
    shipped gates and an authored one. The validator's ``@human_feedback``
    decorators declare no ``metadata=`` at all, so its contexts carry only the
    revise count its provider stamps on; a compiled gate always carries the
    four keys below. Nothing has to remember to set a flag.

    Every field is read defensively. ``metadata`` is a free-form dict that has
    been through JSON on the way to and from ``pending_feedback``, so a float,
    a numeric string or a list of non-strings all have to resolve to something
    rather than raise inside gate construction - which would fail the run at
    the exact moment a human was about to be asked something.
    """

    label: str
    editable_fields: frozenset[str]
    max_turns: int
    expiry_seconds: int

    @classmethod
    def from_context(cls, context: PendingFeedbackContext) -> _AuthoredGate | None:
        metadata = context.metadata or {}
        if GATE_EDITABLE_FIELDS_METADATA_KEY not in metadata:
            return None
        declared = metadata.get(GATE_EDITABLE_FIELDS_METADATA_KEY) or ()
        if not isinstance(declared, list | tuple):
            # A string would iterate into single characters, which is the one
            # malformed shape that produces a plausible-looking answer instead
            # of an obvious one.
            declared = ()
        return cls(
            label=str(metadata.get(GATE_LABEL_METADATA_KEY) or "").strip(),
            editable_fields=frozenset(str(name) for name in declared),
            max_turns=_metadata_int(metadata, GATE_MAX_TURNS_METADATA_KEY, 0),
            expiry_seconds=min(
                # Bounded by the global timeout rather than trusted: the
                # document schema caps `expiry_seconds` at exactly this value,
                # and a gate that outlived the service's own sweep would be a
                # promise nothing keeps. `max(1, ...)` because a zero here
                # would open a gate that has already expired.
                VALIDATOR_GATE_TIMEOUT_SECONDS,
                max(
                    1,
                    _metadata_int(
                        metadata,
                        GATE_EXPIRY_METADATA_KEY,
                        VALIDATOR_GATE_TIMEOUT_SECONDS,
                    ),
                ),
            ),
        )


def _metadata_int(metadata: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(metadata[key])
    except (KeyError, TypeError, ValueError):
        return default


def _gate_derived_keys(
    node_id: str,
    parsed: Mapping[str, Any],
    authored: _AuthoredGate | None = None,
) -> frozenset[str]:
    """The keys at this gate whose value an operator edit cannot change.

    An AUTHORED gate answers this itself: everything its ``editable_fields``
    does not name is read-only, which is what makes that field mean something
    rather than merely seed the payload. It is inverted deliberately - the
    author lists what may be edited, and a key their upstream node started
    emitting later is read-only by default rather than editable by default.
    The note field is never derived whatever they declared, because it is not
    part of the payload at all: it is how a ``revise`` is expressed, and a gate
    that cannot carry one has no lever left but Approve.

    ``review_verdict`` shows a ``Verdict``, and every field of that model is one
    of two things. Seven are arithmetic the schema recomputes and discards on
    every validation - ``composite_score``, ``confidence``, ``confidence_band``,
    ``verdict``, ``decision_reason``, ``fatal_floors`` and ``provisional`` - so
    an edit there is a no-op the operator would watch come back changed. The
    rest are the inputs to that arithmetic: the five ``DimensionScore`` objects,
    the three coverages, ``branches_ok``, ``evidence_counts`` and the median
    source age. Those *are* honoured by the formula, which is exactly why they
    must not be a text box: ``validator_guardrails`` binds a dimension's
    ``anchor_matched`` to the rubric ladder and its ``evidence_urls`` to URLs a
    tool actually returned, and those checks run on the Synthesist's output, not
    on a gate reply. A hand-typed 5 would therefore produce a composite the
    report presents as evidence-scored when nothing scored it.

    So the whole verdict is read-only and the operator's lever is
    ``decision=revise`` plus feedback, which is what the Flow was built for:
    ``revise_verdict`` sends the Synthesist back to rescore against the same
    evidence, with the guardrails running again.

    ``confirm_scope`` shows a ``ScopedIdea``. Nothing in it is derived and
    ``route_scope`` applies the edited object verbatim, so all of it is
    editable - revising the scope is the entire point of that gate.

    Any other gate keeps the historical behaviour of everything editable: a gate
    this module has never seen is one whose semantics it cannot assert.
    """
    if authored is not None:
        return frozenset(
            str(key)
            for key in parsed
            if str(key) not in authored.editable_fields and str(key) != GATE_NOTE_FIELD
        )
    if node_id == VERDICT_GATE_NODE:
        return frozenset(str(key) for key in parsed)
    return frozenset()


def _gate_field_value(value: Any) -> str:
    """One editable value as the string the form input carries and returns.

    ``default=str`` so a value CrewAI hands over unserialized degrades to a
    readable field rather than raising inside the gate-open path and failing
    the run over a display concern.
    """
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text[:MAX_GATE_VALUE_CHARS]


def _gate_summary_str(value: Any) -> str | None:
    """A gate prompt's headline ``verdict``, or nothing.

    ``GatePrompt`` declares this ``str | None`` and forbids extras, so anything
    else here is not a display defect - it is a 500 on ``GET /api/runs/{id}``
    for every subsequent read of that run. A gate on a canvas may show a key
    called ``verdict`` holding an object, so the coercion has to happen where
    the prompt is built rather than where it is rendered.
    """
    return value if isinstance(value, str) else None


def _gate_summary_float(value: Any) -> float | None:
    """The same for ``confidence``: a real number, or nothing at all."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _gate_display_value(value: Any) -> tuple[str, str]:
    """One read-only value, plus how it should be rendered.

    ``json`` values are pretty-printed because nothing round-trips them: they
    exist to be read, and a one-line dump of a ``DimensionScore`` is not.
    """
    if isinstance(value, str):
        return value[:MAX_GATE_VALUE_CHARS], "text"
    if isinstance(value, Mapping | list | tuple):
        return json.dumps(value, indent=2, default=str)[:MAX_GATE_VALUE_CHARS], "json"
    return json.dumps(value, default=str)[:MAX_GATE_VALUE_CHARS], "text"


def _display_kind(text: str) -> str:
    try:
        return "json" if isinstance(json.loads(text), dict | list) else "text"
    except (json.JSONDecodeError, TypeError):
        return "text"


def _split_gate_fields(
    node_id: str,
    parsed: Mapping[str, Any],
    authored: _AuthoredGate | None = None,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Separate what an operator may edit from what they may only read.

    ``fields`` is pruned rather than annotated on purpose. A client that has
    never heard of the split renders exactly the inputs it is given, so pruning
    means the defect cannot survive a stale UI; an ``editable`` flag beside a
    full dump would leave an old client inviting the impossible edit forever.
    """
    derived_keys = _gate_derived_keys(node_id, parsed, authored)
    fields: dict[str, str] = {}
    derived: list[dict[str, str]] = []
    for key, value in parsed.items():
        name = str(key)
        if name in derived_keys:
            display, kind = _gate_display_value(value)
            derived.append({"key": name, "value": display, "kind": kind})
        else:
            fields[name] = _gate_field_value(value)
    # setdefault, not assignment: a gate whose output could not be parsed keeps
    # its raw text under this key rather than having it silently blanked.
    fields.setdefault(GATE_NOTE_FIELD, "")
    return fields, derived


def _normalize_gate_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    """Re-split a ``run_gates.request`` row written before the split existed.

    Such a row lists every field of the model dump as editable and carries no
    ``derived`` list at all. Recovering it verbatim would put the verdict's
    recomputed arithmetic straight back into the form, so the same policy is
    applied to the stored strings on the way out. The values are already
    stringified; this only moves them between the two buckets.
    """
    if "derived" in prompt:
        return prompt
    stored = prompt.get("fields")
    if not isinstance(stored, Mapping):
        prompt["derived"] = []
        return prompt
    derived_keys = _gate_derived_keys(str(prompt.get("node_id") or ""), stored)
    fields: dict[str, str] = {}
    derived: list[dict[str, str]] = []
    for key, value in stored.items():
        name = str(key)
        text = value if isinstance(value, str) else _gate_field_value(value)
        if name in derived_keys:
            derived.append({"key": name, "value": text, "kind": _display_kind(text)})
        else:
            fields[name] = text
    fields.setdefault(GATE_NOTE_FIELD, "")
    prompt["fields"] = fields
    prompt["derived"] = derived
    prompt["editable"] = bool(fields)
    return prompt


@dataclass(frozen=True, slots=True)
class WorkflowRuntime:
    """Everything the registry needs to execute one workflow.

    ``input_field`` is the request-input key this workflow reads - ``topic``
    for Brief Flow, ``idea`` for the validator - and it is declared here
    because the runtime is the one per-workflow record the service already
    keeps. ``create_run`` used to derive it as ``"idea" if workflow_id ==
    VALIDATOR_GRAPH.id else "topic"``, which is correct for exactly two
    workflows and silently wrong for every other: a third would be told its
    ``inputs.topic`` was missing, naming a field it never declared.

    ``None`` means "this runtime declares nothing", which is not the same as
    "topic". It is the state every ``WorkflowRuntime`` constructed before this
    field existed is in - a dozen of them in ``tests/`` - so ``app.py`` resolves
    it against its own per-workflow declaration and refuses, naming the
    workflow, when neither knows. Silently guessing is the defect being fixed.
    """

    graph_version: str
    node_registry: NodeRegistry
    runner: Runner
    input_field: str | None = None


class _FlushMarker:
    """A queued request to write everything ahead of it, right now.

    A marker rather than a flag on a side channel because the writer parks in
    ``Queue.get``: a flag would go unnoticed until the next frame or the next
    interval, while a queued marker wakes it immediately and keeps FIFO order
    with the frames already in flight. It carries its own completion event, so
    a caller waiting on a flush can never outlive the writer thread.
    """

    __slots__ = ("done",)

    def __init__(self) -> None:
        self.done = Event()


_SHUTDOWN = None
# Matches the join bounds already used for this module's other threads: a
# caller waits a bounded time for a background thread and then reports, rather
# than blocking the process forever on one that has gone away.
_WRITER_JOIN_TIMEOUT_SECONDS = 5.0


class _PersistenceWriter:
    """Single non-blocking ingress with time- and size-bounded batched writes.

    PRD F31. ``enqueue`` is the only call a CrewAI event handler makes, and it
    is a ``put_nowait`` onto a bounded queue: no database work, no lock the
    database can hold, no blocking. Everything below runs on this thread.

    The batch closes on whichever comes first - ``VALIDATOR_FRAME_BATCH_SIZE``
    frames, or ``VALIDATOR_FRAME_FLUSH_INTERVAL_SECONDS`` since the batch
    opened. Size alone bounds throughput but not latency, so the tail of a
    quiet run would sit in memory until the next burst, which a reconnecting
    client reads as a gap and a crash loses outright.
    """

    def __init__(
        self,
        store: Any,
        on_error: Callable[[str], None],
        *,
        batch_size: int = VALIDATOR_FRAME_BATCH_SIZE,
        flush_interval: float = VALIDATOR_FRAME_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if flush_interval <= 0:
            raise ValueError("flush_interval must be positive")
        self.store = store
        self.on_error = on_error
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue: Queue[Any] = Queue(maxsize=VALIDATOR_PERSIST_QUEUE_CAPACITY)
        self._closed = Event()
        self.thread = Thread(
            target=self._run,
            name="validator-frame-writer",
            daemon=True,
        )
        self.thread.start()

    def enqueue(self, run_id: str, frames: tuple[FrameData, ...]) -> None:
        try:
            self.queue.put_nowait((run_id, frames))
        except Full:
            self.on_error(run_id)

    def flush(self, timeout: float = _WRITER_JOIN_TIMEOUT_SECONDS) -> bool:
        """Write everything already queued without waiting out the interval.

        Returns whether the flush completed. It is bounded on purpose: a
        caller must never hang because the writer thread is gone, which is
        exactly what a ``Queue.join`` would do after a shutdown.
        """
        if not self.thread.is_alive():
            return False
        marker = _FlushMarker()
        try:
            self.queue.put(marker, timeout=timeout)
        except Full:
            logger.warning("the frame writer queue stayed full for %ss", timeout)
            return False
        if marker.done.wait(timeout):
            return True
        logger.warning("the frame writer did not flush within %ss", timeout)
        return False

    def close(self) -> None:
        """Idempotent: a second close must not wait on a stopped thread."""
        if self._closed.is_set():
            return
        self._closed.set()
        self.flush()
        self.queue.put(_SHUTDOWN)
        self.thread.join(timeout=_WRITER_JOIN_TIMEOUT_SECONDS)
        if self.thread.is_alive():
            logger.warning(
                "the frame writer did not stop within %ss",
                _WRITER_JOIN_TIMEOUT_SECONDS,
            )

    def _run(self) -> None:
        batch: list[tuple[str, tuple[FrameData, ...]]] = []
        markers: list[_FlushMarker] = []
        queued_frames = 0
        deadline: float | None = None
        try:
            while True:
                timeout = (
                    None if deadline is None else max(0.0, deadline - monotonic())
                )
                try:
                    item = self.queue.get(timeout=timeout)
                except Empty:
                    # The coalescing window closed first: write the partial batch.
                    self._write(batch, markers)
                    batch, markers, queued_frames, deadline = [], [], 0, None
                    continue

                if item is _SHUTDOWN:
                    self._write(batch, markers)
                    return
                if isinstance(item, _FlushMarker):
                    markers.append(item)
                    self._write(batch, markers)
                    batch, markers, queued_frames, deadline = [], [], 0, None
                    continue

                batch.append(item)
                queued_frames += len(item[1])
                if deadline is None:
                    deadline = monotonic() + self.flush_interval
                if queued_frames >= self.batch_size:
                    self._write(batch, markers)
                    batch, markers, queued_frames, deadline = [], [], 0, None
        finally:
            # Never leave a caller blocked on a flush this thread will not do.
            self._release_stragglers()

    def _write(
        self,
        batch: list[tuple[str, tuple[FrameData, ...]]],
        markers: list[_FlushMarker],
    ) -> None:
        grouped: dict[str, list[FrameData]] = defaultdict(list)
        for run_id, frames in batch:
            grouped[run_id].extend(frames)
        try:
            for run_id, frames in grouped.items():
                self.store.append_frames(run_id, frames)
        except Exception:
            for run_id in grouped:
                self.on_error(run_id)
        finally:
            for marker in markers:
                marker.done.set()

    def _release_stragglers(self) -> None:
        """Drain what this thread will never write, and account for it.

        Markers are released so no caller is left blocked, and abandoned frames
        are reported through ``on_error`` exactly as a queue overflow is, so a
        shutdown-time loss stays visible in the run's emit-error counter.
        """
        while True:
            try:
                item = self.queue.get_nowait()
            except Empty:
                return
            if isinstance(item, _FlushMarker):
                item.done.set()
            elif item is not _SHUTDOWN:
                self.on_error(item[0])


class FrameSubscription:
    """A run-loop-owned queue fed by O(1) thread-safe scheduling calls."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        capacity: int,
        on_drop: Callable[[], None],
    ) -> None:
        if capacity < 1:
            raise ValueError("subscription capacity must be positive")
        self.loop = loop
        self.queue: asyncio.Queue[FrameData] = asyncio.Queue(maxsize=capacity)
        self.on_drop = on_drop
        self.closed = False

    def publish(self, frames: tuple[FrameData, ...]) -> None:
        if self.closed:
            return
        try:
            self.loop.call_soon_threadsafe(self._publish_on_loop, frames)
        except RuntimeError:
            self.closed = True

    def close(self) -> None:
        self.closed = True

    def _publish_on_loop(self, frames: tuple[FrameData, ...]) -> None:
        if self.closed:
            return
        for frame in frames:
            if self.queue.full():
                self.queue.get_nowait()
                self.on_drop()
            self.queue.put_nowait(frame)


@dataclass(slots=True)
class RunRecord:
    run_id: str
    session_id: str
    workflow_id: str
    graph_version: str
    inputs: Mapping[str, Any]
    node_registry: NodeRegistry
    # Better Auth's `user.id` for whoever launched this, or None when the
    # service is running unauthenticated (tests, SYNTHETIC mode, a bare local
    # checkout). Every ownership decision in service/app.py reads this, and it
    # is set once at creation and never reassigned - a run does not change
    # hands.
    user_id: str | None = None
    flow_id: str | None = None
    on_frames: Callable[[str, tuple[FrameData, ...]], None] | None = None
    ring_capacity: int = DEFAULT_RING_CAPACITY
    status: RunStatus = RunStatus.QUEUED
    created_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: Any = None
    error: str | None = None
    pending_gate: dict[str, Any] | None = None
    # The last deterministic score this run published, mirrored off its own
    # `verdict` frame. Read `_on_frames` for why the frame is the source: it is
    # already the one thing both gate modes produce, and re-deriving the summary
    # here would be a second implementation of a frozen contract.
    verdict: dict[str, Any] | None = None
    # Why this run stopped, when "stopped" is not the whole story. `status`
    # already says CANCELLED; this says whether a human asked for that (None)
    # or the run hit its own limit (COST_CEILING_REASON). Read by `_execute`'s
    # HookAborted branch, which is the only place a frame CAN be emitted for a
    # budget stop - see `_enforce_cost_ceiling`.
    stop_reason: str | None = None
    # The per-run spend ceiling in USD, 0 meaning none. A field rather than a
    # direct read of the constant so a registry - and a test - can set one
    # without reaching into the environment at import time.
    max_cost_usd: float = MAX_RUN_COST_USD
    usage: dict[str, int | float] = field(default_factory=_empty_usage)
    node_usage: dict[tuple[str, str], dict[str, int | float | str]] = field(
        default_factory=dict
    )
    subscriber_dropped: int = 0
    cancel_requested: Event = field(default_factory=Event)
    pending_context: PendingFeedbackContext | None = None
    answered_gates: set[str] = field(default_factory=set)
    expired_gates: set[str] = field(default_factory=set)
    alerted_gates: set[str] = field(default_factory=set)
    buffer: FrameBuffer = field(init=False)
    capture: StreamSinkAdapter = field(init=False)
    _subscribers: dict[str, FrameSubscription] = field(default_factory=dict, init=False)
    _llm_started_at: dict[tuple[str, str], datetime] = field(
        default_factory=dict, init=False
    )
    _llm_elapsed_ms: dict[tuple[str, str], int] = field(
        default_factory=dict, init=False
    )
    # PRD F20: token usage is versioned rather than flagged so the metrics
    # snapshot can be coalesced. Both counters are guarded by _lock, which is
    # the lock _record_usage already holds, so marking usage dirty needs no
    # second lock and cannot invert the emit ordering below.
    _usage_revision: int = field(default=0, init=False)
    _metrics_revision: int = field(default=0, init=False)
    # Models this run has already warned about having no price for. Guarded by
    # _lock, which _record_usage already holds. Not part of `usage`: both
    # `UsageMetrics` and `RunStatusResponse` are `extra="forbid"`, so the run
    # payload has no room for a counter - the unpriced call announces itself on
    # its own `token` frame instead, as `cost_usd: null`.
    _unpriced_models: set[str] = field(default_factory=set, init=False)
    _lock: RLock = field(default_factory=RLock, init=False)
    # Deliberately NOT _lock. Emitting takes the capture lock and the capture
    # callback then takes _lock, so a sweeper holding _lock across an emit would
    # invert that order. This lock guards the F03 bookkeeping sets and nothing
    # else, and is never held while a frame is emitted.
    _gate_watch_lock: RLock = field(default_factory=RLock, init=False)

    def __post_init__(self) -> None:
        self.inputs = MappingProxyType(dict(self.inputs))
        self.buffer = FrameBuffer(
            self.ring_capacity,
            quarantine_node_id=self.node_registry.quarantine_node_id,
        )
        self.capture = StreamSinkAdapter(
            run_id=self.run_id,
            buffer=self.buffer,
            registry=self.node_registry,
            on_frames=self._on_frames,
        )

    def mark_running(self) -> None:
        with self._lock:
            self.status = RunStatus.RUNNING
            if self.started_at is None:
                self.started_at = _utcnow()

    def mark_waiting(
        self,
        prompt: dict[str, Any],
        context: PendingFeedbackContext,
    ) -> None:
        with self._lock:
            self.status = RunStatus.WAITING
            self.pending_gate = prompt
            self.pending_context = context

    def mark_completed(self, result: Any) -> None:
        with self._lock:
            self.status = RunStatus.COMPLETED
            self.result = _clip_run_result(self.capture.serializer, result)
            self.pending_gate = None
            self.pending_context = None
            self.completed_at = _utcnow()

    def mark_failed(self, error: BaseException) -> None:
        with self._lock:
            self.status = RunStatus.FAILED
            self.error = str(error)[:4096]
            self.completed_at = _utcnow()

    def mark_cancelling(self) -> None:
        with self._lock:
            self.status = RunStatus.CANCELLING
            self.cancel_requested.set()

    def mark_cancelled(self) -> None:
        with self._lock:
            self.status = RunStatus.CANCELLED
            self.pending_gate = None
            self.pending_context = None
            self.completed_at = _utcnow()

    def subscribe(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        capacity: int = DEFAULT_SUBSCRIBER_CAPACITY,
    ) -> tuple[str, FrameSubscription]:
        subscription_id = str(uuid.uuid4())
        subscription = FrameSubscription(
            loop=loop,
            capacity=capacity,
            on_drop=self._note_subscriber_drop,
        )
        with self._lock:
            self._subscribers[subscription_id] = subscription
        return subscription_id, subscription

    def unsubscribe(self, subscription_id: str) -> None:
        with self._lock:
            subscription = self._subscribers.pop(subscription_id, None)
        if subscription is not None:
            subscription.close()

    def has_subscribers(self) -> bool:
        """PRD F30: a still-connected socket pins this run in memory."""
        with self._lock:
            return any(
                not subscription.closed
                for subscription in self._subscribers.values()
            )

    def claim_gate_expiry(self, gate_id: str) -> bool:
        """True exactly once per gate, so the F03 frame is not emitted per tick."""
        with self._gate_watch_lock:
            if gate_id in self.answered_gates or gate_id in self.expired_gates:
                return False
            self.expired_gates.add(gate_id)
            return True

    def claim_gate_alert(self, gate_id: str) -> bool:
        """True exactly once per gate, so the R-2 alert is not raised per tick."""
        with self._gate_watch_lock:
            if gate_id in self.answered_gates or gate_id in self.alerted_gates:
                return False
            self.alerted_gates.add(gate_id)
            return True

    def adopt_gate_watch(self, gate_id: str, status: str) -> None:
        """Replay a durable watch state so recovery does not re-emit its frames."""
        with self._gate_watch_lock:
            if status in {"expired", "alerted"}:
                self.expired_gates.add(gate_id)
            if status == "alerted":
                self.alerted_gates.add(gate_id)

    def pending_gate_payload(
        self,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """The open gate with F03 expiry resolved at read time.

        Derived rather than stored: the answer is correct between sweep ticks and
        immediately after a restore, and it never contradicts ``expires_at``.
        """
        prompt = self.pending_gate
        if prompt is None:
            return None
        payload = dict(prompt)
        deadline = _gate_deadline(prompt)
        payload["expired"] = deadline is not None and deadline <= (now or _utcnow())
        return payload

    def status_payload(self) -> dict[str, Any]:
        stats = self.buffer.stats()
        with self._lock:
            return {
                "run_id": self.run_id,
                "session_id": self.session_id,
                "workflow_id": self.workflow_id,
                "graph_version": self.graph_version,
                "status": self.status,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "pending_gate": self.pending_gate_payload(),
                "frames": {
                    "count": stats.count,
                    "captured": stats.captured,
                    "dropped": stats.dropped,
                    "gaps": stats.gaps,
                    "emit_errors": stats.emit_errors,
                    "subscriber_dropped": self.subscriber_dropped,
                    # PRD F21: how much of this run the graph could not place.
                    "unattributed": stats.unattributed,
                    "first_seq": stats.first_seq,
                    "last_seq": stats.last_seq,
                },
                "usage": dict(self.usage),
                "node_usage": self.node_usage_payload(),
                "result": self.result,
                "verdict": self.verdict,
                "error": self.error,
                # None for an operator cancel, COST_CEILING_REASON for a run
                # that stopped itself. Both arrive as `status: "cancelled"`, so
                # without this the API cannot tell them apart.
                "stop_reason": self.stop_reason,
            }

    def node_usage_payload(self) -> list[dict[str, int | float | str]]:
        return [
            dict(self.node_usage[key])
            for key in sorted(self.node_usage)
        ]

    def emit_metrics(self, reason: str) -> FrameData | None:
        """Push one PRD F20 ``metrics`` snapshot if usage moved since the last.

        Coalesced by design. Live per-call totals already reach the client as
        ``token`` frames; this frame is the periodic *reconciled* view - run
        totals, the per-node/per-model breakdown and the capture counters - so
        a client that reconnected, missed token frames or was replayed from a
        truncated ring can still show correct numbers. Emitting one per model
        call would duplicate the token stream and burn the 2,000-frame ring.

        Returns the frame, or ``None`` when nothing changed since the last
        snapshot. Never emitted while ``_lock`` is held: ``capture.emit`` takes
        the capture lock and its callback then takes ``_lock``, so holding
        ``_lock`` across the emit would invert that order.
        """
        with self._lock:
            revision = self._usage_revision
            if revision == self._metrics_revision:
                return None
            stats = self.buffer.stats()
            details: dict[str, Any] = {
                "reason": reason,
                "usage": dict(self.usage),
                "nodes": self.node_usage_payload()[:MAX_METRICS_NODES],
                "frames": {
                    "captured": stats.captured,
                    "dropped": stats.dropped,
                    "gaps": stats.gaps,
                    "emit_errors": stats.emit_errors,
                    "subscriber_dropped": self.subscriber_dropped,
                    "unattributed": stats.unattributed,
                },
            }
        frame = self.capture.emit(
            kind=FrameKind.METRICS,
            event_type=UIEventType.METRICS_UPDATED,
            node_id=self.node_registry.workflow_node_id,
            message="Run metrics updated",
            details=details,
        )
        if frame is None:
            # The emit failed and was counted as an emit error; leave the run
            # dirty so the next tick retries rather than losing the snapshot.
            return None
        with self._lock:
            self._metrics_revision = revision
        return frame

    def _on_frames(self, frames: tuple[FrameData, ...]) -> None:
        with self._lock:
            for frame in frames:
                if frame.kind is FrameKind.LLM:
                    self._track_llm_timing(frame)
                elif frame.kind is FrameKind.TOKEN:
                    self._record_usage(frame)
                elif frame.kind is FrameKind.GATE_OPEN:
                    self.pending_gate = dict(frame.details)
                    self.status = RunStatus.WAITING
                elif frame.kind is FrameKind.GATE_CLOSED:
                    self.pending_gate = None
                    self.status = RunStatus.RUNNING
                elif frame.kind is FrameKind.VERDICT:
                    # `to_dict()` rather than `dict(frame.details)`: details is
                    # a frozen `MappingProxyType` tree, and the nested
                    # `dimensions` map inside a shallow copy would still be one.
                    # This is the same thawing the transport does, and it runs
                    # at most twice per run.
                    self.verdict = frame.to_dict()["details"]
            subscribers = tuple(self._subscribers.values())
        for subscription in subscribers:
            subscription.publish(frames)
        if self.on_frames is not None:
            self.on_frames(self.run_id, frames)

    def _track_llm_timing(self, frame: FrameData) -> None:
        call_id = str(frame.details.get("call_id") or "")
        if not call_id:
            return
        key = (frame.node_id, call_id)
        stage = frame.details.get("stage")
        if stage == "before":
            self._llm_started_at[key] = frame.ts
        elif stage in {"after", "error"}:
            started_at = self._llm_started_at.pop(key, None)
            if started_at is not None:
                self._llm_elapsed_ms[key] = max(
                    0,
                    int((frame.ts - started_at).total_seconds() * 1000),
                )

    def _record_usage(self, frame: FrameData) -> None:
        usage = normalize_usage(
            frame.details.get("usage", {}),
            completed_call=True,
        )
        model = str(frame.details.get("model") or "unknown")[:255]
        call_id = str(frame.details.get("call_id") or "")
        elapsed_ms = self._llm_elapsed_ms.pop((frame.node_id, call_id), 0)
        # None means "this model has no price on file", which is not the same
        # statement as "this call was free" and must never be added to a total
        # as if it were. The run total is then the sum over PRICED calls only,
        # and the fact that it is a partial sum is on the frame (`cost_usd:
        # null`) and in this log line - the two places that have room for it.
        cost_usd = compute_cost_usd(
            model,
            usage["prompt_tokens"],
            usage["completion_tokens"],
        )
        if cost_usd is None and model not in self._unpriced_models:
            self._unpriced_models.add(model)
            logger.warning(
                "No price on file for model %r; run %s reports an estimated "
                "cost that excludes every call to it. Add it to "
                "brief_crew.config.PRICES.",
                model,
                self.run_id,
            )
        priced = 0.0 if cost_usd is None else cost_usd
        measured: dict[str, int | float | str] = {
            **usage,
            "elapsed_ms": elapsed_ms,
            "cost_usd": priced,
        }
        for field_name in _USAGE_INTEGER_FIELDS:
            self.usage[field_name] = int(self.usage.get(field_name, 0)) + int(
                measured[field_name]
            )
        self.usage["cost_usd"] = round(
            float(self.usage.get("cost_usd", 0.0)) + priced,
            12,
        )
        # Every priced call in the process flows through the line above, so this
        # is the one place a per-run spend ceiling can be enforced without a
        # second accounting path to keep in step with the first.
        self._enforce_cost_ceiling()

        key = (frame.node_id, model)
        node = self.node_usage.setdefault(
            key,
            {
                "node_id": frame.node_id,
                "model": model,
                **_empty_usage(),
            },
        )
        for field_name in _USAGE_INTEGER_FIELDS:
            node[field_name] = int(node[field_name]) + int(measured[field_name])
        node["cost_usd"] = round(float(node["cost_usd"]) + priced, 12)
        self._usage_revision += 1

    def _enforce_cost_ceiling(self) -> None:
        """Ask this run to stop once its estimated spend reaches ``max_cost_usd``.

        Called from ``_record_usage``, which holds ``_lock`` - an ``RLock``, so
        the ``mark_cancelling()`` below re-acquires it on the same thread rather
        than deadlocking. That re-entrancy is load-bearing and is asserted in
        ``tests/service/test_cost_ceiling.py``.

        WHY IT DOES NOT RAISE, AND WHY IT EMITS NO FRAME. This method runs
        inside a CrewAI event handler: ``StreamSinkAdapter.__call__`` holds a
        plain (non-reentrant) ``threading.Lock`` while it notifies
        ``_on_frames``, which is what called this. Emitting from here would
        deadlock the capture thread on that lock, and raising would surface as a
        counted emit error rather than as a stopped run. So this sets the
        ``cancel_requested`` Event that ``_cancel_guard`` and
        ``RunExecution.checkpoint`` already test at each CrewAI ``PRE_STEP``
        boundary, and ``_execute``'s ``HookAborted`` branch does the announcing.

        WHAT IT IS ENFORCING, honestly, in the three ways it falls short of
        "this run cost at most N dollars". The knob's comment in ``config.py``
        carries the full derivation; these are the same three facts stated where
        the code acts on them:

        * AN ESTIMATE, NOT AN INVOICE. ``compute_cost_usd`` recomputes from the
          ``PRICES`` table because OpenRouter's own per-generation cost never
          reaches a CrewAI event. Cached-prompt discounts, BYOK fees and any
          price change since that table was written all move the billed number.
        * ONE CALL OF GRANULARITY, SO IT OVERSHOOTS. The total only moves when a
          call *completes*, and the stop lands at the next step boundary - a
          call already in flight runs to the end and is paid for. Expect to
          exceed the ceiling by about one escalation-tier call, ~$0.05 at the
          measured average, and by more if that call is a long one.
        * BLIND TO EVERYTHING THAT IS NOT AN LLM CALL. Embeddings, Cohere rerank
          and Firecrawl raise no ``LLMCallCompletedEvent``, never reach
          ``_record_usage`` and are absent from ``usage["cost_usd"]``. That is
          ~$0.006-$0.02 per run the total structurally UNDERCOUNTS, so the
          enforced figure is a lower bound on the real spend and the stop
          always comes a little later than it looks.

        An unpriced model contributes ``0.0`` here, because ``compute_cost_usd``
        returns ``None`` - never ``0.0`` - for a model absent from ``PRICES``
        and ``_record_usage`` adds ``priced`` rather than the ``None``. So a run
        made entirely of unpriced calls can never trip this ceiling however many
        tokens it burns. That is deliberate: guessing a price in order to
        enforce a limit would be inventing the number the whole ``None``
        convention exists to refuse. The warning ``_record_usage`` already logs
        by model name is where that gap is reported.
        """
        ceiling = float(self.max_cost_usd or 0.0)
        if ceiling <= 0:
            return  # MAX_RUN_COST_USD=0 - explicitly no ceiling.
        if self.stop_reason == COST_CEILING_REASON:
            return  # Already tripped; do not re-announce on every later call.
        spent = float(self.usage.get("cost_usd", 0.0))
        # `>=` and not `>`: the ceiling is a budget, not a target, and a run
        # that has spent exactly it has no headroom left for the next call.
        if spent < ceiling:
            return
        self.stop_reason = COST_CEILING_REASON
        self.error = COST_CEILING_ERROR.format(spent=spent, ceiling=ceiling)
        logger.warning(
            "run %s reached the per-run cost ceiling: estimated $%.4f spent "
            "against MAX_RUN_COST_USD=$%.2f. Requesting cancellation at the "
            "next step boundary; the call in flight will still be paid for, "
            "and this estimate excludes embedding, rerank and Firecrawl spend.",
            self.run_id,
            spent,
            ceiling,
        )
        self.mark_cancelling()

    def _note_subscriber_drop(self) -> None:
        with self._lock:
            self.subscriber_dropped += 1


class RunRegistry:
    """Own run execution while mirroring recoverable state to persistence."""

    def __init__(
        self,
        *,
        graph_version: str,
        node_registry: NodeRegistry,
        runner: Runner | None = None,
        workflows: Mapping[str, WorkflowRuntime] | None = None,
        persistence: Any = None,
        max_workers: int | None = None,
        ring_capacity: int = DEFAULT_RING_CAPACITY,
        gate_sweep_interval: float | None = None,
        submit_settle_timeout: float | None = None,
        max_queued_runs: int | None = None,
        orphan_grace: float | None = None,
        recover_orphans: bool | None = None,
        max_run_cost_usd: float | None = None,
    ) -> None:
        if max_workers is None:
            max_workers = RUN_CONCURRENCY
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        # The per-run spend ceiling every record this registry creates inherits.
        # 0 is a legal value and means "no ceiling"; negative is not, for the
        # same reason `_env_non_negative_float` refuses it - a nonsense value
        # must not silently become "disabled".
        self.max_run_cost_usd = (
            MAX_RUN_COST_USD if max_run_cost_usd is None else float(max_run_cost_usd)
        )
        if self.max_run_cost_usd < 0:
            raise ValueError("max_run_cost_usd cannot be negative")
        self.max_queued_runs = (
            MAX_QUEUED_RUNS if max_queued_runs is None else int(max_queued_runs)
        )
        if self.max_queued_runs < 1:
            raise ValueError("max_queued_runs must be positive")
        self.submit_settle_timeout = (
            RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS
            if submit_settle_timeout is None
            else float(submit_settle_timeout)
        )
        if self.submit_settle_timeout <= 0:
            raise ValueError("submit_settle_timeout must be positive")
        self.gate_sweep_interval = (
            VALIDATOR_GATE_SWEEP_INTERVAL_SECONDS
            if gate_sweep_interval is None
            else float(gate_sweep_interval)
        )
        if self.gate_sweep_interval < 0:
            raise ValueError("gate_sweep_interval cannot be negative")
        # How long a run may claim live work with no durable write before this
        # process treats it as interrupted. See VALIDATOR_ORPHAN_RUN_GRACE_
        # SECONDS in config.py for what has to fit inside the window; zero is
        # allowed so a test can sweep without inventing a clock.
        self.orphan_grace = (
            VALIDATOR_ORPHAN_RUN_GRACE_SECONDS
            if orphan_grace is None
            else float(orphan_grace)
        )
        if self.orphan_grace < 0:
            raise ValueError("orphan_grace cannot be negative")
        self.recover_orphans = (
            VALIDATOR_ORPHAN_RUN_RECOVERY
            if recover_orphans is None
            else bool(recover_orphans)
        )
        self.max_workers = max_workers
        self.graph_version = graph_version
        self.node_registry = node_registry
        self.runner = runner or BriefFlowRunner()
        self.workflows = dict(workflows or {})
        self._default_runtime = WorkflowRuntime(
            graph_version=graph_version,
            node_registry=node_registry,
            runner=self.runner,
        )
        self.persistence = persistence
        self.ring_capacity = ring_capacity
        self._records: dict[str, RunRecord] = {}
        self._futures: dict[str, Future[Any]] = {}
        # Runs admitted by create_run that do not have a future yet. Without
        # this the admission check and the submission would be two separate
        # critical sections, and concurrent creations could all read the same
        # "one slot left".
        self._reserved: set[str] = set()
        self._refused_runs = 0
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="brief-run"
        )
        self._writer = (
            _PersistenceWriter(persistence, self._note_persistence_error)
            if persistence is not None
            else None
        )
        self._gate_expiries = 0
        self._gate_alerts = 0
        self._gate_sweeps = 0
        self._metrics_frames = 0
        self._evicted_runs = 0
        self._interrupted_runs = 0
        self._readopted_gates = 0
        self._sweeper_stop = Event()
        self._sweeper: Thread | None = None
        if self.gate_sweep_interval > 0:
            self._sweeper = Thread(
                target=self._sweep_loop,
                name="validator-gate-sweeper",
                daemon=True,
            )
            self._sweeper.start()
        # Remaining-work item 32. A restart is exactly this: a brand-new
        # registry looking at a database full of rows the dead process was
        # responsible for. Running the reconciliation once here - rather than
        # only on the first maintenance tick - means a run stranded by the
        # PREVIOUS boot is terminal before the operator's first page load,
        # instead of a `running` row that is still lying for another interval.
        # A run stranded seconds before THIS boot is still inside the grace
        # window and is picked up by a later tick, which is why the sweep has
        # to be periodic as well as eager.
        #
        # Never fatal: a storage problem must degrade the recovery, not stop
        # the service from starting.
        try:
            self.recover_orphaned_runs()
        except Exception:
            logger.exception("the interrupted-run recovery sweep failed at startup")

    def workflow_runtime(self, workflow_id: str) -> WorkflowRuntime:
        """The runtime that executes ``workflow_id``.

        Public because the transport needs it before it needs a run: the
        request-input key and the gate policy are both properties of the
        workflow, and reaching through ``_runtime_for`` for them would be a
        handler depending on a private name.

        Raises :class:`UnknownWorkflowError` when this registry declares a
        workflow map that has no entry for the id. A registry constructed
        WITHOUT a map still answers for any id from its single default runtime,
        which is the older single-workflow shape and is still legal.
        """

        return self._runtime_for(workflow_id)

    def _runtime_for(self, workflow_id: str) -> WorkflowRuntime:
        if self.workflows:
            try:
                return self.workflows[workflow_id]
            except KeyError as exc:
                raise UnknownWorkflowError(workflow_id) from exc
        return self._default_runtime

    def _active_slots(self) -> int:
        """Executions submitted-but-unfinished, plus admitted-but-unsubmitted.

        Caller must hold ``self._lock``. A run WAITING at a human gate is
        deliberately NOT counted: ``_execute`` has already returned by then and
        its worker thread is free, so a room full of people thinking about a
        scope costs no admission slots.
        """
        active = sum(
            1 for future in self._futures.values() if not future.done()
        )
        return active + len(self._reserved)

    def admission_status(self) -> dict[str, int]:
        """What the admission bound currently sees. Monitoring, not a control."""
        with self._lock:
            return {
                "active": self._active_slots(),
                "limit": self.max_queued_runs,
                "refused": self._refused_runs,
            }

    def create_run(
        self,
        *,
        session_id: str,
        workflow_id: str,
        inputs: Mapping[str, Any],
        user_id: str | None = None,
    ) -> RunRecord:
        """Admit and register one NEW run.

        Raises :class:`RunAdmissionError` when too much work is already queued
        or executing. The check happens BEFORE the durable row is written, so a
        refused run leaves nothing behind to clean up, and it reserves the slot
        inside the same critical section so two simultaneous callers cannot
        both take the last one.

        Resumes do not come through here - they go straight to ``_submit`` -
        which is deliberate: a gate reply must never be refused for capacity,
        or a flood would strand every operator mid-run.

        CONTRACT: an admitted run must reach ``start_run`` (or ``_submit``),
        which is where the reservation is handed over to the run's future. A
        caller that admits a run and then abandons it holds one slot for the
        life of the process. Every path in ``service/app.py`` submits on the
        next line, and ``_submit`` releases the reservation before it can
        refuse or raise, so the only way to leak one is to invent a third
        caller that does neither.
        """
        runtime = self._runtime_for(workflow_id)
        run_id = str(uuid.uuid4())
        with self._lock:
            active = self._active_slots()
            if active >= self.max_queued_runs:
                self._refused_runs += 1
                raise RunAdmissionError(active=active, limit=self.max_queued_runs)
            self._reserved.add(run_id)
        try:
            return self._register_run(
                run_id,
                runtime=runtime,
                session_id=session_id,
                workflow_id=workflow_id,
                inputs=inputs,
                user_id=user_id,
            )
        except BaseException:
            # The slot is only held for a run that exists. A durable write that
            # failed must not leak one for the life of the process.
            with self._lock:
                self._reserved.discard(run_id)
            raise

    def _register_run(
        self,
        run_id: str,
        *,
        runtime: WorkflowRuntime,
        session_id: str,
        workflow_id: str,
        inputs: Mapping[str, Any],
        user_id: str | None = None,
    ) -> RunRecord:
        flow_id = run_id if hasattr(runtime.runner, "resume") else None
        record = RunRecord(
            run_id=run_id,
            session_id=session_id,
            workflow_id=workflow_id,
            graph_version=runtime.graph_version,
            inputs=inputs,
            user_id=user_id,
            node_registry=runtime.node_registry,
            flow_id=flow_id,
            on_frames=self._enqueue_frames,
            ring_capacity=self.ring_capacity,
            max_cost_usd=self.max_run_cost_usd,
        )
        if self.persistence is not None:
            self.persistence.create_run(
                run_id=run_id,
                session_id=session_id,
                workflow_id=workflow_id,
                flow_id=flow_id,
                graph_version=runtime.graph_version,
                inputs=inputs,
                user_id=user_id,
            )
        with self._lock:
            self._records[run_id] = record
        return record

    def start_run(self, run_id: str) -> Future[Any]:
        record = self.require(run_id)
        return self._submit(record)

    def answer_gate(
        self,
        run_id: str,
        gate_id: str,
        *,
        outcome: str,
        fields: Mapping[str, str] | None = None,
    ) -> Future[Any]:
        record = self.require(run_id)
        prompt = record.pending_gate
        context = record.pending_context
        if prompt is None or context is None or prompt.get("gate_id") != gate_id:
            stored_gate = (
                self.persistence.get_gate(run_id, gate_id)
                if self.persistence is not None
                else None
            )
            if gate_id in record.answered_gates or (
                stored_gate is not None and stored_gate.get("answered_at") is not None
            ):
                raise FileExistsError(gate_id)
            raise KeyError((run_id, gate_id))

        option_ids = {
            str(option.get("id"))
            for option in prompt.get("options", [])
            if isinstance(option, Mapping)
        }
        if option_ids and outcome not in option_ids:
            # Say *why* when the missing option is Revise and the reason is the
            # turn cap. "outcome must be one of ['approve']" is true but leaves
            # an operator who just watched the button disappear guessing at a
            # bug; naming the budget makes the refusal self-explanatory, and it
            # is the same number the prompt has been carrying all along.
            if outcome == "revise" and prompt.get(GATE_REVISE_REMAINING_KEY) == 0:
                raise ValueError(
                    "this gate has used all "
                    f"{prompt.get(GATE_REVISE_MAX_KEY, VALIDATOR_MAX_GATE_TURNS)} "
                    "of its revise turns; reply with outcome=approve to continue "
                    "or cancel the run"
                )
            raise ValueError(f"outcome must be one of {sorted(option_ids)}")

        # Before the durable compare-and-set, never after: a refusal that ran
        # later would have already marked the gate answered and locked the
        # operator out of a run the server would otherwise finish.
        self._reject_uneditable_fields(
            gate_id,
            prompt,
            fields or {},
            authored=_AuthoredGate.from_context(context) is not None,
        )

        if self.persistence is not None:
            answer = self.persistence.answer_gate(
                run_id,
                gate_id,
                outcome=outcome,
                fields=fields,
            )
            if answer.conflict:
                record.answered_gates.add(gate_id)
                raise FileExistsError(gate_id)
        elif gate_id in record.answered_gates:
            raise FileExistsError(gate_id)

        deadline = _gate_deadline(prompt)
        # F03: lateness is recorded, never rejected. An expired gate is advisory,
        # so the reply is accepted and the run resumes exactly as an on-time one.
        late = deadline is not None and deadline <= _utcnow()
        record.answered_gates.add(gate_id)
        record.pending_gate = None
        record.capture.emit(
            kind=FrameKind.GATE_CLOSED,
            event_type=UIEventType.HUMAN_INTERACTION,
            node_id=self._gate_node_id(record, prompt),
            message=f"{prompt['title']} answered",
            details={
                "gate_id": gate_id,
                "outcome": outcome,
                "fields": dict(fields or {}),
                "late": late,
            },
        )
        feedback = self._feedback(context, outcome, fields or {})
        try:
            return self._submit(record, context=context, feedback=feedback)
        except RunBusyError:
            # The durable answer above already stood, so leaving it would hand
            # the operator a run that is RUNNING, has no gate to answer and
            # returns 409 to every retry. Put the gate back instead.
            self._reopen_gate(record, gate_id, prompt, context)
            raise

    @staticmethod
    def _reject_uneditable_fields(
        gate_id: str,
        prompt: Mapping[str, Any],
        fields: Mapping[str, str],
        *,
        authored: bool = False,
    ) -> None:
        """Refuse an edit the gate never offered, rather than dropping it.

        Silently ignoring one would reproduce the defect this replaced: the
        operator sets ``verdict`` to VALIDATE, is told 202, and watches REJECT
        come back. The refusal names the field and points at ``revise``.

        An *unchanged echo* of a value the server itself issued is not an edit,
        so it passes: a client that posts the whole payload back - or an older
        one holding a pre-split prompt - still answers its gate. The refusal is
        derived from the prompt's own ``derived`` list rather than recomputed,
        so the server never refuses something it presented as editable.
        """
        if not fields:
            return
        offered = prompt.get("fields") or {}
        unchanged = {
            str(item.get("key")): str(item.get("value", ""))
            for item in prompt.get("derived") or ()
            if isinstance(item, Mapping)
        }
        rejected = tuple(
            sorted(
                key
                for key, value in fields.items()
                if key not in offered
                and not (key in unchanged and str(value) == unchanged[key])
            )
        )
        if not rejected:
            return
        editable = ", ".join(sorted(offered)) or "none"
        # Two gates, two reasons, and telling an operator the wrong one is
        # worse than telling them nothing: "recomputed from the dimension
        # scores" is a sentence about a Verdict, and a graph somebody drew has
        # no dimension scores. Its read-only keys are read-only because its
        # author said which keys were not.
        why = (
            "This gate's author declared which of its fields an operator may "
            "edit, and the rest are shown for reading only"
            if authored
            else "A derived value is recomputed from the dimension scores and "
            "the evidence behind them"
        )
        raise GateFieldError(
            gate_id,
            rejected,
            f"these fields cannot be set at this gate: {', '.join(rejected)}. "
            f"Editable fields: {editable}. {why}, so reply with "
            f"outcome=revise and say what to reconsider in {GATE_NOTE_FIELD!r} "
            "instead.",
        )

    def cancel(self, run_id: str) -> dict[str, Any]:
        record = self.require(run_id)
        if record.status in {
            RunStatus.CANCELLED,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
        }:
            return {
                "run_id": run_id,
                "status": record.status,
                "effect": "run is already terminal",
                "eta_hint": "none",
            }

        with self._lock:
            future = self._futures.get(run_id)
        if record.status is RunStatus.QUEUED and future is not None and future.cancel():
            record.mark_cancelled()
            record.emit_metrics("run_cancelled")
            self._persist_status(record)
            return {
                "run_id": run_id,
                "status": record.status,
                "effect": "cancelled before execution",
                "eta_hint": "immediate",
            }

        if record.status is RunStatus.WAITING:
            prompt = record.pending_gate
            if prompt is not None and self.persistence is not None:
                answer = self.persistence.answer_gate(
                    run_id,
                    str(prompt["gate_id"]),
                    outcome="cancelled",
                )
                if answer.accepted and record.flow_id:
                    self.persistence.clear_pending_feedback(record.flow_id)
            record.mark_cancelled()
            record.capture.emit(
                kind=FrameKind.RUN_STATE,
                event_type=UIEventType.WORKFLOW_END,
                node_id=record.node_registry.workflow_node_id,
                message="Run cancelled at the human gate boundary",
                details={"status": "cancelled"},
                level=FrameLevel.WARNING,
            )
            record.emit_metrics("run_cancelled")
            self._persist_status(record)
            return {
                "run_id": run_id,
                "status": record.status,
                "effect": "cancelled at the current step boundary",
                "eta_hint": "immediate",
            }

        record.mark_cancelling()
        self._persist_status(record)
        return {
            "run_id": run_id,
            "status": record.status,
            "effect": "stops at the next step boundary",
            "eta_hint": "up to one agent turn",
        }

    def _submit(
        self,
        record: RunRecord,
        *,
        context: PendingFeedbackContext | None = None,
        feedback: str = "",
    ) -> Future[Any]:
        """Queue one execution, waiting out a previous one that is settling.

        The gate is visible to the client before the run that opened it has
        finished: ``_mark_pending`` writes the durable gate, marks the record
        WAITING and pushes GATE_OPEN, and only *then* does ``_execute`` return
        and its future complete. A reply that arrives in that window is not a
        second execution - it is the resume of the one that is settling - so
        refusing it wedged the run: the durable answer stood, no work was
        queued, and every retry came back 409.

        The wait is deliberately outside ``self._lock``. ``_execute``'s tail
        emits frames, and a frame emitted while the persistence queue is full
        reaches ``_note_persistence_error``, which takes ``self._lock``.
        Holding it here while waiting for that thread would deadlock the
        process.
        """
        with self._lock:
            current = self._futures.get(record.run_id)
        if current is not None and not current.done():
            wait_for_futures([current], timeout=self.submit_settle_timeout)
        with self._lock:
            # The admission reservation ends here, whichever way this goes: the
            # future below replaces it as the thing that holds the slot, and a
            # refusal means the run never occupies one at all.
            self._reserved.discard(record.run_id)
            current = self._futures.get(record.run_id)
            if current is not None and not current.done():
                raise RunBusyError(record.run_id)
            future = self._executor.submit(
                self._execute,
                record,
                context,
                feedback,
            )
            self._futures[record.run_id] = future
            return future

    def require(self, run_id: str) -> RunRecord:
        with self._lock:
            record = self._records.get(run_id)
        if record is None and self.persistence is not None:
            snapshot = self.persistence.get_run(run_id)
            if snapshot is not None:
                record = self._restore_record(snapshot)
                with self._lock:
                    self._records[run_id] = record
        if record is None:
            raise KeyError(run_id)
        return record

    def status_payload(self, run_id: str) -> dict[str, Any]:
        record = self.require(run_id)
        return record.status_payload()

    def sweep_gates(self, *, now: datetime | None = None) -> dict[str, int]:
        """Apply the F03/R-2 watch ladder to every unanswered gate.

        Advisory only, by PRD F03: nothing here fails a run, auto-answers a gate
        or clears ``pending_gate``. The run stays ``WAITING`` and a late reply
        still resumes it. ``now`` is injectable so tests need no wall clock.
        """
        moment = now or _utcnow()
        grace = timedelta(seconds=VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS)
        self._hydrate_due_gates(moment)
        counters = {
            "open": 0,
            "expired": 0,
            "alerting": 0,
            "expired_now": 0,
            "alerts_now": 0,
        }
        for record, prompt, gate_id, deadline in self._open_gates():
            counters["open"] += 1
            if deadline is None or deadline > moment:
                continue
            counters["expired"] += 1
            node_id = self._gate_node_id(record, prompt)
            title = str(prompt.get("title") or "Gate")
            overdue = int((moment - deadline).total_seconds())
            timeout_seconds = self._gate_timeout_seconds(record, deadline)
            if record.claim_gate_expiry(gate_id):
                counters["expired_now"] += 1
                self._persist_gate_watch(record, gate_id, "expired")
                record.capture.emit(
                    kind=FrameKind.GATE_EXPIRED,
                    event_type=UIEventType.HUMAN_INTERACTION,
                    node_id=node_id,
                    message=f"{title} expired unanswered; the run stays resumable",
                    details={
                        "gate_id": gate_id,
                        "node_id": node_id,
                        "title": title,
                        "status": "expired",
                        "expires_at": deadline.isoformat(),
                        "timeout_seconds": timeout_seconds,
                        "overdue_seconds": overdue,
                        "auto_answered": False,
                        "resumable": True,
                    },
                    level=FrameLevel.WARNING,
                )
            if moment - deadline < grace:
                continue
            counters["alerting"] += 1
            if record.claim_gate_alert(gate_id):
                counters["alerts_now"] += 1
                self._persist_gate_watch(record, gate_id, "alerted")
                record.capture.emit(
                    kind=FrameKind.GATE_ALERT,
                    event_type=UIEventType.HUMAN_INTERACTION,
                    node_id=node_id,
                    message=f"{title} has no reply {overdue}s past its deadline",
                    details={
                        "gate_id": gate_id,
                        "node_id": node_id,
                        "title": title,
                        "status": "alerted",
                        "alert": "gate_open_without_gate_closed",
                        "expires_at": deadline.isoformat(),
                        "timeout_seconds": timeout_seconds,
                        "grace_seconds": VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS,
                        "overdue_seconds": overdue,
                    },
                    level=FrameLevel.ERROR,
                )
                logger.error(
                    "R-2: gate %s on run %s has no gate_closed %ss past its "
                    "%ss deadline",
                    gate_id,
                    record.run_id,
                    overdue,
                    timeout_seconds,
                )
        with self._lock:
            self._gate_sweeps += 1
            self._gate_expiries += counters["expired_now"]
            self._gate_alerts += counters["alerts_now"]
        return counters

    def gate_watch_status(self, *, now: datetime | None = None) -> dict[str, int]:
        """The R-2 signal a monitoring endpoint reads - counters, not prose."""
        moment = now or _utcnow()
        grace = timedelta(seconds=VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS)
        open_gates = expired = alerting = 0
        for _, _, _, deadline in self._open_gates():
            open_gates += 1
            if deadline is None or deadline > moment:
                continue
            expired += 1
            if moment - deadline >= grace:
                alerting += 1
        with self._lock:
            return {
                "open": open_gates,
                "expired": expired,
                "alerting": alerting,
                "expiries": self._gate_expiries,
                "alerts": self._gate_alerts,
                "sweeps": self._gate_sweeps,
            }

    def _sweep_loop(self) -> None:
        # One maintenance tick drives all three periodic jobs, so there is a
        # single background thread with a single shutdown path rather than one
        # thread per concern. Event.wait parks it for the whole interval and
        # returns early the moment close() sets the flag, so this is neither a
        # busy-wait nor a source of shutdown latency. Each job is isolated:
        # one failing must not stop the others or kill the thread.
        jobs: tuple[tuple[Callable[[], Any], str], ...] = (
            (self.sweep_gates, "the human-gate expiry sweep failed"),
            (self.sweep_metrics, "the run metrics sweep failed"),
            (self.evict_stale_runs, "the terminal-run eviction sweep failed"),
            (
                self.recover_orphaned_runs,
                "the interrupted-run recovery sweep failed",
            ),
        )
        while not self._sweeper_stop.wait(self.gate_sweep_interval):
            for job, message in jobs:
                try:
                    job()
                except Exception:
                    logger.exception(message)

    def sweep_metrics(self) -> int:
        """Push one coalesced PRD F20 metrics snapshot per changed live run.

        This rides the existing maintenance tick rather than a timer of its
        own, which fixes the cadence at one frame per run per tick *and only
        when token usage actually moved*. A run with no model calls emits
        nothing at all; a busy run costs a few frames a minute against a
        2,000-frame ring, so the snapshot can never push real frames out.

        Terminal runs are skipped: their final snapshot was already emitted by
        the transition that made them terminal.
        """
        with self._lock:
            records = tuple(self._records.values())
        emitted = 0
        for record in records:
            if record.status in TERMINAL_STATUSES:
                continue
            if record.emit_metrics("interval") is not None:
                emitted += 1
        if emitted:
            with self._lock:
                self._metrics_frames += emitted
        return emitted

    def evict_stale_runs(self, *, now: datetime | None = None) -> list[str]:
        """Drop finished runs from memory once the retention window has passed.

        PRD F30. ``_records`` is a replay and status cache, not the system of
        record: the run row, its frames, its node metrics and its gates all
        live in storage, and ``require()`` rebuilds a record from them on the
        next request. Nothing durable is deleted here.

        A run is evicted only when every one of these holds:

        * it is COMPLETED, FAILED or CANCELLED - so QUEUED, RUNNING,
          CANCELLING and above all **WAITING** are never evicted at any age. A
          gate answered late is deliberate wave-2 behaviour (PRD Scenario C),
          and evicting a waiting run would drop the in-memory
          ``PendingFeedbackContext`` that its resume needs;
        * it finished at least ``VALIDATOR_RUN_RETENTION_SECONDS`` ago;
        * no WebSocket subscriber is still attached to it;
        * its execution future is finished, so no worker still owns it;
        * persistence is configured, because without it memory *is* the only
          copy and eviction would destroy the run.
        """
        if self.persistence is None:
            return []
        moment = now or _utcnow()
        horizon = timedelta(seconds=VALIDATOR_RUN_RETENTION_SECONDS)
        # Two phases so the registry lock is never held while a record lock is
        # taken. The candidate list is a snapshot; the predicate is rechecked
        # under the lock before anything is dropped.
        with self._lock:
            candidates = tuple(self._records.items())
        stale = [
            run_id
            for run_id, record in candidates
            if self._is_evictable(record, moment, horizon)
        ]
        evicted: list[str] = []
        with self._lock:
            for run_id in stale:
                record = self._records.get(run_id)
                if record is None or record.status not in TERMINAL_STATUSES:
                    continue
                future = self._futures.get(run_id)
                if future is not None and not future.done():
                    continue
                self._records.pop(run_id, None)
                self._futures.pop(run_id, None)
                evicted.append(run_id)
            self._evicted_runs += len(evicted)
        if evicted:
            logger.info(
                "evicted %d terminal run(s) from memory after %ss; storage is "
                "unchanged and a later read rehydrates them",
                len(evicted),
                VALIDATOR_RUN_RETENTION_SECONDS,
            )
        return evicted

    def recover_orphaned_runs(self, *, now: datetime | None = None) -> list[str]:
        """Reconcile runs whose worker died with the process. Item 32.

        The defect this closes: a run executing when the API restarts is
        orphaned forever. The ``Future`` dies with the process, the ``runs``
        row still says ``running``, no code path resumes it, and ``cancel()``
        only reaches CANCELLING because there is no live future left to hit a
        PRE_STEP boundary. The operator is left with a run that lies and no
        lever at all.

        **Such a run is not resumable, and this does not pretend otherwise.**
        A gate has a durable anchor - the ``run_gates`` row plus the
        ``pending_feedback`` row CrewAI writes when ``HumanFeedbackPending`` is
        raised - and ``from_pending()``/``resume()`` rebuilds it. A run that
        was mid-method has neither: ``Flow.from_pending()`` raises
        ``ValueError`` without that row, and ``kickoff(inputs={"id": ...})``
        reloads the STATE with an empty completed-method set, which re-runs the
        flow from ``@start`` at full price rather than resuming it. So the
        honest terminal state is a failure with a reason.

        Three guards keep a live run out of this:

        * status. Only QUEUED, RUNNING and CANCELLING are considered; WAITING
          is anchored and is never touched, at any age.
        * a live future or an admission reservation in THIS registry, which is
          what "something is still executing it" means inside one process.
        * the grace window on ``runs.updated_at``, which every frame batch
          bumps. That is what covers the two windows the future test cannot
          see: a deploy where the draining instance is still working, and
          ``_submit``'s settle wait, during which a healthy run is RUNNING with
          no future installed yet.

        One case genuinely IS resumable and is healed rather than failed: a
        process that died between ``open_gate`` and the status write leaves
        ``running`` on the row with a real open gate behind it. That run is put
        back to WAITING with its pending context, exactly as a gate recovery
        would.
        """
        if not self.recover_orphans or self.persistence is None:
            return []
        lister = getattr(self.persistence, "list_stale_runs", None)
        if not callable(lister):
            return []
        moment = now or _utcnow()
        cutoff = moment - timedelta(seconds=self.orphan_grace)
        try:
            stale = lister(updated_before=cutoff)
        except Exception:
            logger.exception("could not list interrupted runs for recovery")
            return []
        recovered: list[str] = []
        readopted = 0
        for row in stale:
            run_id = str(row.get("run_id") or "")
            if not run_id or self._has_live_work(run_id):
                continue
            try:
                record = self.require(run_id)
            except KeyError:
                continue
            except Exception:
                logger.exception("could not load interrupted run %s", run_id)
                continue
            # Re-checked now that the row is in memory. The first check asked
            # about a run this process had never heard of; this one asks again
            # after require() may have raced a live submission into _futures.
            if self._has_live_work(run_id):
                continue
            if record.status not in INTERRUPTIBLE_STATUSES:
                continue
            try:
                if self._adopt_interrupted_gate(record):
                    readopted += 1
                    continue
                self._fail_interrupted(record)
            except Exception:
                logger.exception("could not reconcile interrupted run %s", run_id)
                continue
            recovered.append(run_id)
        if recovered or readopted:
            with self._lock:
                self._interrupted_runs += len(recovered)
                self._readopted_gates += readopted
            logger.warning(
                "reconciled %d run(s) interrupted by a service restart and "
                "re-adopted %d gate(s); nothing durable was deleted",
                len(recovered),
                readopted,
            )
        return recovered

    def _has_live_work(self, run_id: str) -> bool:
        """True while THIS process still owns the run's execution.

        An admission reservation counts: ``create_run`` holds one between the
        durable write and ``_submit``, and in that window a perfectly healthy
        run has a ``queued`` row and no future yet.
        """
        with self._lock:
            if run_id in self._reserved:
                return True
            future = self._futures.get(run_id)
            return future is not None and not future.done()

    def _adopt_interrupted_gate(self, record: RunRecord) -> bool:
        """Heal the one interrupted shape that really is resumable.

        ``_mark_pending`` writes the pending feedback and the gate row, and
        only then marks the record WAITING and persists the status. A process
        that died between those leaves ``running`` on a run that is in fact
        parked at a gate, with both durable anchors intact. Failing it would
        throw away a resumable run, so it is put back to WAITING instead and
        the operator answers the gate as normal.
        """
        prompt = record.pending_gate
        if prompt is None or not record.flow_id or self.persistence is None:
            return False
        loader = getattr(self.persistence, "load_pending_feedback", None)
        if not callable(loader):
            return False
        loaded = loader(record.flow_id)
        if loaded is None:
            return False
        _, context = loaded
        record.mark_waiting(dict(prompt), context)
        self._persist_status(record)
        logger.warning(
            "run %s was interrupted at gate %s and has been restored to "
            "waiting; the gate is answerable again",
            record.run_id,
            prompt.get("gate_id"),
        )
        return True

    def _fail_interrupted(self, record: RunRecord) -> None:
        """Take one orphaned run to a terminal state, loudly.

        The frames deliberately reuse the two shapes ``_execute`` already
        emits - ``ERROR``/``WORKFLOW_END`` for a failure, ``RUN_STATE``/
        ``WORKFLOW_END`` with ``status: cancelled`` for a cancellation - so
        every existing client reaches a terminal state with no change: the
        Studio maps an ``error`` frame to a terminal error and reads its
        ``message``, and ``normalizeRunStatus`` already maps ``failed`` to
        ``error`` on a refresh.

        CANCELLING becomes CANCELLED rather than FAILED. The operator asked
        for the run to stop; it stopped, in the least graceful way available.
        Reporting that as a failure would blame the run for doing what it was
        told.
        """
        cancelling = record.status is RunStatus.CANCELLING
        node_id = record.node_registry.workflow_node_id
        # A durable gate that could not be adopted must not stay open, or the
        # F03 sweeper keeps finding a gate on a terminal run forever.
        self._close_interrupted_gate(record)
        record.pending_gate = None
        record.pending_context = None
        if cancelling:
            record.capture.emit(
                kind=FrameKind.RUN_STATE,
                event_type=UIEventType.WORKFLOW_END,
                node_id=node_id,
                message=(
                    "Run cancelled: the service restarted before it reached a "
                    "step boundary"
                ),
                details={"status": "cancelled", "reason": INTERRUPTED_REASON},
                level=FrameLevel.WARNING,
            )
            record.mark_cancelled()
            record.emit_metrics("run_cancelled")
        else:
            record.capture.emit(
                kind=FrameKind.ERROR,
                event_type=UIEventType.WORKFLOW_END,
                node_id=node_id,
                message="Run interrupted by a service restart",
                details={
                    "error": INTERRUPTED_ERROR,
                    "reason": INTERRUPTED_REASON,
                    "interrupted_status": record.status.value,
                },
                level=FrameLevel.ERROR,
            )
            record.mark_failed(RuntimeError(INTERRUPTED_ERROR))
            record.emit_metrics("run_failed")
        self._persist_status(record)

    def _close_interrupted_gate(self, record: RunRecord) -> None:
        gate_id = str((record.pending_gate or {}).get("gate_id") or "")
        if not gate_id or self.persistence is None:
            return
        try:
            answer = self.persistence.answer_gate(
                record.run_id,
                gate_id,
                outcome=INTERRUPTED_REASON,
            )
        except Exception:
            logger.exception(
                "could not close gate %s on interrupted run %s",
                gate_id,
                record.run_id,
            )
            return
        if answer.accepted and record.flow_id:
            self.persistence.clear_pending_feedback(record.flow_id)
        record.answered_gates.add(gate_id)

    @staticmethod
    def _is_evictable(
        record: RunRecord,
        moment: datetime,
        horizon: timedelta,
    ) -> bool:
        if record.status not in TERMINAL_STATUSES:
            return False
        finished_at = record.completed_at or record.created_at
        if finished_at is None or moment - finished_at < horizon:
            return False
        return not record.has_subscribers()

    def maintenance_status(self) -> dict[str, int]:
        """Counters for the periodic jobs - live runs, snapshots, evictions."""
        with self._lock:
            return {
                "tracked_runs": len(self._records),
                "metrics_frames": self._metrics_frames,
                "evicted_runs": self._evicted_runs,
                # Item 32: runs this process took to a terminal state because
                # the process that owned them is gone, and gates it put back.
                "interrupted_runs": self._interrupted_runs,
                "readopted_gates": self._readopted_gates,
            }

    def _open_gates(
        self,
    ) -> list[tuple[RunRecord, Mapping[str, Any], str, datetime | None]]:
        with self._lock:
            records = tuple(self._records.values())
        open_gates: list[
            tuple[RunRecord, Mapping[str, Any], str, datetime | None]
        ] = []
        for record in records:
            if record.status is not RunStatus.WAITING:
                continue
            prompt = record.pending_gate
            if not prompt:
                continue
            gate_id = str(prompt.get("gate_id") or "")
            if not gate_id or gate_id in record.answered_gates:
                continue
            open_gates.append((record, prompt, gate_id, _gate_deadline(prompt)))
        return open_gates

    def _hydrate_due_gates(self, moment: datetime) -> None:
        """Pull runs whose gate expired while this process was down into memory."""
        lister = getattr(self.persistence, "list_open_gates", None)
        if not callable(lister):
            return
        try:
            due = lister(due_by=moment)
        except Exception:
            logger.exception("could not list durable open gates for the sweep")
            return
        for gate in due:
            run_id = str(gate.get("run_id") or "")
            if not run_id:
                continue
            with self._lock:
                if run_id in self._records:
                    continue
            try:
                self.require(run_id)
            except KeyError:
                continue
            except Exception:
                logger.exception("could not recover run %s for the sweep", run_id)

    def _persist_gate_watch(
        self,
        record: RunRecord,
        gate_id: str,
        status: str,
    ) -> None:
        expire_gate = getattr(self.persistence, "expire_gate", None)
        if not callable(expire_gate):
            return
        try:
            expire_gate(record.run_id, gate_id, status=status)
        except KeyError:
            pass
        except Exception:
            logger.exception(
                "could not persist gate %s as %s for run %s",
                gate_id,
                status,
                record.run_id,
            )

    @staticmethod
    def _gate_node_id(record: RunRecord, prompt: Mapping[str, Any]) -> str:
        """Which node on the CANVAS this gate is, for every frame that names it.

        The prompt's own ``node_id`` first, because that is the one an operator
        has already been shown. The fallback resolves the pending context's
        method name through the node registry rather than using it raw: a
        compiled builder gate pauses in ``n2_confirm`` while the canvas - and
        therefore every node-state key the client holds - calls it ``confirm``,
        so a frame carrying the ident marks no node at all. For the validator
        the two are the same string and this changes nothing, which is exactly
        how it stayed wrong until a graph existed whose names differed.
        """
        context = record.pending_context
        node_id = str(prompt.get("node_id") or "")
        if not node_id and context is not None:
            node_id = (
                record.node_registry.declared_node(context.method_name)
                or context.method_name
            )
        return node_id or record.node_registry.workflow_node_id

    @staticmethod
    def _gate_timeout_seconds(record: RunRecord, deadline: datetime) -> int:
        """How long this gate was actually open for, as the frames report it.

        `GateConfig.expiry_seconds` lets an authored gate close sooner than the
        service's global window, and `_gate_prompt` honours it - so a frame
        that went on reporting VALIDATOR_GATE_TIMEOUT_SECONDS would tell an
        operator their gate had thirty minutes when it had five. Derived from
        the deadline the prompt actually carries rather than re-read from the
        metadata, because the deadline is the thing the sweep just acted on.
        A record hydrated from the database after a restart has no pending
        context to subtract from, and the global window is the honest fallback
        there: it is what every gate opened before this field was honoured had.
        """
        context = record.pending_context
        if context is None:
            return VALIDATOR_GATE_TIMEOUT_SECONDS
        # `_gate_deadline` normalises a naive `expires_at` to UTC, and CrewAI
        # stamps `requested_at` naive, so subtracting them raw is a TypeError
        # on the ordinary path rather than an exotic one - and it would be
        # raised from inside a background sweep, where nothing is watching.
        opened = record.pending_context.requested_at
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        return max(0, int((deadline - opened).total_seconds()))

    def dependency_status(self) -> dict[str, dict[str, Any]]:
        storage = {"status": "not_configured"}
        if self.persistence is not None:
            health_status = getattr(self.persistence, "health_status", None)
            if callable(health_status):
                try:
                    storage = dict(health_status())
                except Exception:
                    storage = {"status": "error"}
            else:
                storage = {"status": "error"}
        return {
            "executor": {"status": "ok", "workers": self.max_workers},
            "storage": storage,
        }

    def replay_frames(
        self,
        run_id: str,
        *,
        after: int = 0,
        limit: int = MAX_REPLAY_LIMIT,
        kinds: set[FrameKind] | None = None,
    ) -> list[dict[str, Any]]:
        record = self.require(run_id)
        persisted = (
            self.persistence.replay_frames(
                run_id,
                after=after,
                limit=limit,
                kinds=kinds,
            )
            if self.persistence is not None
            else []
        )
        combined = {int(frame["seq"]): frame for frame in persisted}
        for frame in record.buffer.replay(after=after, limit=limit, kinds=kinds):
            combined[frame.seq] = frame.to_dict()
        return [combined[seq] for seq in sorted(combined)[:limit]]

    def all_frames(self, run_id: str) -> list[dict[str, Any]]:
        frames: list[dict[str, Any]] = []
        after = 0
        while True:
            page = self.replay_frames(
                run_id,
                after=after,
                limit=MAX_REPLAY_LIMIT,
            )
            if not page:
                return frames
            frames.extend(page)
            after = int(page[-1]["seq"])
            if len(page) < MAX_REPLAY_LIMIT:
                return frames

    def wait(self, run_id: str, timeout: float | None = None) -> Any:
        with self._lock:
            future = self._futures.get(run_id)
        if future is None:
            raise RuntimeError(f"run {run_id} has not been started")
        result = future.result(timeout=timeout)
        if self._writer is not None:
            self._writer.flush()
        return result

    def close(self) -> None:
        self._sweeper_stop.set()
        sweeper = self._sweeper
        if sweeper is not None and sweeper is not current_thread():
            sweeper.join(timeout=5)
            if sweeper.is_alive():
                logger.warning("gate expiry sweeper did not stop within 5s")
        self._executor.shutdown(wait=True, cancel_futures=True)
        if self._writer is not None:
            self._writer.close()

    def _execute(
        self,
        record: RunRecord,
        context: PendingFeedbackContext | None,
        feedback: str,
    ) -> Any:
        record.mark_running()
        self._persist_status(record)
        execution = RunExecution(
            run_id=record.run_id,
            inputs=record.inputs,
            capture=record.capture,
            flow_id=record.flow_id,
            persistence=self.persistence,
            cancel_requested=record.cancel_requested,
        )
        try:
            with scoped_hooks():
                register_scoped(
                    InterceptionPoint.PRE_STEP,
                    lambda hook_context: self._cancel_guard(record, hook_context),
                )
                with capture_events(
                    CaptureContext(run_id=record.run_id, adapter=record.capture)
                ):
                    runtime = self._runtime_for(record.workflow_id)
                    if context is None:
                        result = runtime.runner(execution)
                    else:
                        resume = getattr(runtime.runner, "resume", None)
                        if resume is None:
                            raise RuntimeError(
                                f"workflow {record.workflow_id!r} cannot resume"
                            )
                        result = resume(
                            execution,
                            context=context,
                            feedback=feedback,
                        )
        except HookAborted:
            # A budget stop and an operator cancel arrive here by the same
            # path - both set `cancel_requested` and both abort at a PRE_STEP
            # boundary - so this is where the two are told apart. The frame
            # carries `reason` exactly as `_fail_interrupted` does for a
            # restart, and the run keeps the `error` sentence
            # `_enforce_cost_ceiling` already wrote, so the trace, the API and
            # the durable row all say the same thing. This is also the only
            # place a frame CAN be emitted for a budget stop: the ceiling is
            # detected inside a capture callback that already holds the
            # adapter's non-reentrant lock.
            budget_stop = record.stop_reason == COST_CEILING_REASON
            details: dict[str, Any] = {"status": "cancelled"}
            if budget_stop:
                details["reason"] = COST_CEILING_REASON
                details["cost_usd"] = float(record.usage.get("cost_usd", 0.0))
                details["ceiling_usd"] = float(record.max_cost_usd)
            record.capture.emit(
                kind=FrameKind.RUN_STATE,
                event_type=UIEventType.WORKFLOW_END,
                node_id=record.node_registry.workflow_node_id,
                message=(
                    "Run stopped at a step boundary: it reached its cost ceiling"
                    if budget_stop
                    else "Run cancelled at a step boundary"
                ),
                details=details,
                level=FrameLevel.WARNING,
            )
            record.mark_cancelled()
            record.emit_metrics("run_cancelled")
            self._persist_status(record)
            return None
        except Exception as exc:
            record.capture.emit(
                kind=FrameKind.ERROR,
                event_type=UIEventType.WORKFLOW_END,
                node_id=record.node_registry.workflow_node_id,
                message="Run failed",
                details={"error": str(exc)},
                level=FrameLevel.ERROR,
            )
            record.mark_failed(exc)
            record.emit_metrics("run_failed")
            self._persist_status(record)
            return None
        if isinstance(result, HumanFeedbackPending):
            self._mark_pending(record, result)
            return result
        self._log_usage_reconciliation(record, result)
        record.mark_completed(result)
        # Terminal: the last token frame has already been counted, so this
        # snapshot is the authoritative end-of-run total in the stream, the
        # NDJSON export and the ZIP export.
        record.emit_metrics("run_completed")
        if self.persistence is not None and record.flow_id is not None:
            self.persistence.clear_pending_feedback(record.flow_id)
        self._persist_status(record)
        return result

    @staticmethod
    def _cancel_guard(record: RunRecord, hook_context: Any) -> None:
        if record.cancel_requested.is_set():
            step_name = getattr(hook_context, "step_name", None) or "next step"
            raise HookAborted(f"cancelled before {step_name}")

    def _mark_pending(
        self,
        record: RunRecord,
        pending: HumanFeedbackPending,
    ) -> None:
        context = pending.context
        record.flow_id = context.flow_id
        prompt = self._gate_prompt(record.run_id, context, record.node_registry)
        # One node id, resolved once by the prompt and read back out of it
        # everywhere else. The durable row and the frame must agree, because
        # `_gate_node_id` reads the row on recovery and the expiry sweeper
        # reads it again from there - a gate that announced itself on one node
        # and expired on another would light up two cards for one pause.
        node_id = str(prompt["node_id"])
        if self.persistence is not None:
            state = self.persistence.load_state(context.flow_id) or {
                "id": context.flow_id
            }
            self.persistence.save_pending_feedback(context.flow_id, context, state)
            self.persistence.open_gate(
                record.run_id,
                str(prompt["gate_id"]),
                node_id=node_id,
                request=prompt,
                opened_at=context.requested_at,
                expires_at=datetime.fromisoformat(str(prompt["expires_at"])),
            )
        record.mark_waiting(prompt, context)
        record.capture.emit(
            kind=FrameKind.GATE_OPEN,
            event_type=UIEventType.HUMAN_INTERACTION,
            node_id=node_id,
            message=str(prompt["title"]),
            details=prompt,
        )
        # The run is now idle until a human answers, so this is the natural
        # place for a reconciled snapshot: nothing more will change until the
        # reply lands, and the next tick would only repeat these numbers.
        record.emit_metrics("gate_open")
        self._persist_status(record)

    def _reopen_gate(
        self,
        record: RunRecord,
        gate_id: str,
        prompt: Mapping[str, Any],
        context: PendingFeedbackContext,
    ) -> None:
        """Roll one accepted-but-unstarted gate reply back to an open gate.

        The reply is durably accepted before the resume is queued, so a resume
        that never starts leaves the run committed to work nobody is doing:
        status RUNNING, ``pending_gate`` null, and 409 on every retry - the
        wedged state this whole path exists to prevent. Rolling back is
        preferred over failing the run because nothing about the run is
        actually broken: one resubmission lost a race, the flow state and the
        pending feedback are untouched on disk, and the same reply sent again
        resumes it.

        Everything the reply did is undone in the reverse order it happened:
        the durable compare-and-set, the in-memory answered set, and finally
        the frames - a GATE_ALERT saying why, then the original GATE_OPEN
        re-emitted verbatim so a client that already applied GATE_CLOSED gets
        its card back. Re-emitting is what restores ``pending_gate`` and the
        WAITING status, because ``_on_frames`` is what set them the first time.
        """
        watch_status = "open"
        if gate_id in record.alerted_gates:
            watch_status = "alerted"
        elif gate_id in record.expired_gates:
            watch_status = "expired"
        if self.persistence is not None:
            try:
                self.persistence.reopen_gate(
                    record.run_id,
                    gate_id,
                    status=watch_status,
                )
            except Exception:
                # A failed rollback must not mask the RunBusyError the caller
                # is about to see, but it does mean the durable answer stands.
                logger.exception(
                    "could not reopen gate %s on run %s after a busy resubmit",
                    gate_id,
                    record.run_id,
                )
                return
        record.answered_gates.discard(gate_id)
        restored = dict(prompt)
        record.mark_waiting(restored, context)
        # Off the restored prompt, so the reopened gate lands on the same node
        # the original GATE_OPEN did: a client that already applied GATE_CLOSED
        # is being handed its card back, and a card that comes back on a
        # different node is not the same card.
        node_id = self._gate_node_id(record, restored)
        record.capture.emit(
            kind=FrameKind.GATE_ALERT,
            event_type=UIEventType.HUMAN_INTERACTION,
            node_id=node_id,
            message=f"{prompt['title']} reopened; the reply could not be started",
            details={
                "gate_id": gate_id,
                "reason": "run_busy",
                "detail": (
                    "the previous execution was still running when the reply "
                    "was accepted, so the reply was rolled back - send it again"
                ),
            },
            level=FrameLevel.WARNING,
        )
        record.capture.emit(
            kind=FrameKind.GATE_OPEN,
            event_type=UIEventType.HUMAN_INTERACTION,
            node_id=node_id,
            message=str(prompt["title"]),
            details=restored,
        )
        self._persist_status(record)

    @staticmethod
    def _gate_prompt(
        run_id: str,
        context: PendingFeedbackContext,
        node_registry: NodeRegistry | None = None,
    ) -> dict[str, Any]:
        """One pending pause as the payload both transports serve.

        ``node_registry`` is how the prompt learns the node id the CANVAS
        drew. A builder gate's method name is the compiler's identifier -
        ``n2_confirm`` - and the client keys its node states by document node
        id, so a prompt naming the ident marks nothing: the gate node stays
        `idle` while the run waits on it, which is the one state an operator
        has to be able to see. It is optional and defaults to the method name
        because the validator's method names ARE its node ids, which is exactly
        why this went unnoticed until a graph existed whose names differed.
        """
        authored = _AuthoredGate.from_context(context)
        parsed = _parsed_gate_output(context.method_output)
        fields, derived = _split_gate_fields(context.method_name, parsed, authored)
        node_id = (
            node_registry.declared_node(context.method_name)
            if node_registry is not None
            else None
        ) or context.method_name
        scope_gate = context.method_name == SCOPE_GATE_NODE
        if authored is not None:
            # The author's own label and their own message. Reading the
            # validator's summary keys off a graph somebody drew is how every
            # builder gate came to be titled "Review verdict" over a summary
            # pulled from `cheapest_next_test`, a key no authored payload has.
            # The label is empty only for a gate paused by a build that had not
            # yet put it on the metadata - a run held across a deploy - since
            # `BuilderNode.label` is `min_length=1`. The node id is the honest
            # fallback there, being the other thing the author typed.
            title = authored.label or node_id
            summary = str(context.message)
        else:
            title = "Confirm scope" if scope_gate else "Review verdict"
            summary = (
                str(
                    parsed.get("category")
                    or parsed.get("startup_idea")
                    or context.message
                )
                if scope_gate
                else str(parsed.get("cheapest_next_test") or context.message)
            )
        gate_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{run_id}:{context.method_name}:{context.requested_at.isoformat()}",
            )
        )
        timeout_seconds = (
            authored.expiry_seconds
            if authored is not None
            else VALIDATOR_GATE_TIMEOUT_SECONDS
        )
        expires_at = context.requested_at + timedelta(seconds=timeout_seconds)
        # How much of this gate's revise budget is left, and therefore whether
        # Revise is offered at all.
        #
        # Pruning the option rather than annotating it is the same policy the
        # fields/derived split follows, for the same reason: a client that has
        # never heard of turn limits renders exactly the options it is given,
        # so a gate that has run out of revises cannot present a button the
        # router would decline to honour. `answer_gate` already refuses any
        # outcome that is not one of the prompt's own option ids, so removing
        # the option IS the transport-level refusal - no second check needed.
        #
        # The count comes off `context.metadata`, stamped by
        # `ValidatorFeedbackProvider` from the persisted state. A context
        # without it - the synthetic runner, or a gate opened by some other
        # flow - reads 0 used, which is the honest answer for a run that has
        # never spent a turn.
        #
        # An authored gate counts against ITS OWN budget. `route_gate` already
        # honours `max_turns` off the compiled routing table, so a prompt
        # offering five revises on a gate declared with one was offering four
        # buttons whose replies the router silently downgrades to approvals -
        # the operator sends "revise", the run goes forward, and nothing
        # anywhere says why.
        used = _metadata_turns_used(context)
        max_turns = (
            authored.max_turns if authored is not None else VALIDATOR_MAX_GATE_TURNS
        )
        remaining = max(0, max_turns - used)
        options = [{"id": "approve", "label": "Approve", "emphasis": "primary"}]
        if remaining > 0:
            options.append({"id": "revise", "label": "Revise"})
        return {
            "gate_id": gate_id,
            "node_id": node_id,
            "title": title,
            "summary": summary[:MAX_GATE_VALUE_CHARS],
            # Legacy flag, kept for the persisted contract: it now means "this
            # gate has at least one editable field", not "every field is".
            # Per-field editability is the fields/derived split itself.
            "editable": bool(fields),
            "expires_at": expires_at.isoformat(),
            "options": options,
            GATE_REVISE_REMAINING_KEY: remaining,
            GATE_REVISE_MAX_KEY: max_turns,
            "fields": fields,
            "derived": derived,
            # Type-checked rather than passed through, because these two keys
            # are the validator's vocabulary read off whatever the upstream
            # node happened to emit. `GatePrompt.verdict` is `str | None`, so
            # an authored payload carrying a `verdict` OBJECT - which is
            # exactly what a gate downstream of a scoring node produces - made
            # `GET /api/runs/{id}` fail validation and answer 500, permanently,
            # for the rest of that run's life. A value of the wrong type is not
            # this gate's verdict; it is a key that happens to share a name.
            "verdict": _gate_summary_str(parsed.get("verdict")),
            "confidence": _gate_summary_float(parsed.get("confidence")),
        }

    @staticmethod
    def _feedback(
        context: PendingFeedbackContext,
        outcome: str,
        fields: Mapping[str, str],
    ) -> str:
        """Turn one gate reply into the JSON both validator routers parse.

        ``route_scope`` and ``route_verdict`` read three things: ``decision``,
        an optional ``feedback`` string that becomes the reviving crew's
        ``human_override``, and an optional edited object. Only fields this gate
        declared editable are folded into that object, so a reply can never
        push a value into a model that would discard it (the verdict's
        arithmetic) or reject it (a mistyped literal, which would fail the run
        rather than the reply).

        ``outcome`` is compared against ``revise`` alone. The prompt has only
        ever offered ``approve`` and ``revise``, and ``answer_gate`` refuses any
        outcome that is not one of the prompt's own option ids, so the
        ``scope_revise``/``verdict_revise`` aliases this used to accept were
        unreachable - they are the Flow's *router event* names, which never
        travel as an outcome.
        """
        decision = "revise" if outcome == "revise" else "approve"
        payload: dict[str, Any] = {"decision": decision}
        note = str(fields.get(GATE_NOTE_FIELD, "")).strip()
        if note:
            payload["feedback"] = note

        authored = _AuthoredGate.from_context(context)
        original = _parsed_gate_output(context.method_output)
        derived_keys = _gate_derived_keys(context.method_name, original, authored)
        edits = {
            key: value
            for key, value in fields.items()
            if key != GATE_NOTE_FIELD
            and key in original
            and key not in derived_keys
        }
        if edits:
            for key, value in edits.items():
                try:
                    original[key] = json.loads(value)
                except json.JSONDecodeError:
                    original[key] = value
            # An authored gate's edits go under `fields` - the name the request
            # body, the prompt and `GateConfig.editable_fields` all already use
            # - not under `verdict`. `verdict` is a slot `route_verdict` reads,
            # and there is no `route_verdict` in a builder graph: `route_gate`
            # hands every non-`decision` key of the reply to `gate_decision`,
            # which records them as the gate node's own output for a downstream
            # `${state.out__<gate>}` to read. So filing them under `verdict`
            # did two things at once - it named the operator's edits after a
            # model this graph has never heard of, and it put a mapping under a
            # key `GatePrompt.verdict` declares to be a string, which is a 500
            # on the next read of the run.
            slot = (
                "fields"
                if authored is not None
                else ("scope" if context.method_name == SCOPE_GATE_NODE else "verdict")
            )
            payload[slot] = original
        return json.dumps(payload)

    def _enqueue_frames(
        self,
        run_id: str,
        frames: tuple[FrameData, ...],
    ) -> None:
        if self._writer is not None:
            self._writer.enqueue(run_id, frames)

    def _note_persistence_error(self, run_id: str) -> None:
        # Deliberately not require(): this runs on the writer thread, and
        # require() would read - and after F30 eviction, fully rehydrate - the
        # run from the database. A counter bump is never worth a database read
        # on the writer thread, and an evicted run has no live ring to mark.
        with self._lock:
            record = self._records.get(run_id)
        if record is not None:
            record.buffer.note_emit_error()

    def _persist_status(self, record: RunRecord) -> None:
        if self.persistence is None:
            return
        stats = record.buffer.stats()
        self.persistence.update_run_status(
            record.run_id,
            record.status,
            started_at=record.started_at,
            completed_at=record.completed_at,
            result=record.result,
            error=record.error,
            usage=record.usage,
            dropped_frames=stats.dropped,
            frame_gaps=stats.gaps,
            emit_errors=stats.emit_errors,
            subscriber_dropped=record.subscriber_dropped,
        )
        for metrics in record.node_usage_payload():
            self.persistence.save_node_metrics(
                record.run_id,
                str(metrics["node_id"]),
                model=str(metrics["model"]),
                successful_requests=int(metrics["successful_requests"]),
                prompt_tokens=int(metrics["prompt_tokens"]),
                completion_tokens=int(metrics["completion_tokens"]),
                total_tokens=int(metrics["total_tokens"]),
                call_count=int(metrics["call_count"]),
                elapsed_ms=int(metrics["elapsed_ms"]),
                cost_usd=float(metrics["cost_usd"]),
            )

    @staticmethod
    def _log_usage_reconciliation(record: RunRecord, result: Any) -> None:
        flow_usage = _usage_from_result(result)
        if flow_usage is None:
            return
        event_usage = {
            field_name: int(record.usage.get(field_name, 0))
            for field_name in (
                "successful_requests",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
            )
        }
        delta = {
            field_name: event_usage[field_name] - flow_usage[field_name]
            for field_name in event_usage
        }
        if any(delta.values()):
            logger.warning(
                "Flow usage totals differ from event-derived totals for run %s: "
                "event=%s flow=%s delta=%s",
                record.run_id,
                event_usage,
                flow_usage,
                delta,
            )
        else:
            logger.info(
                "Flow usage totals match event-derived totals for run %s",
                record.run_id,
            )

    def _restore_record(self, snapshot: Mapping[str, Any]) -> RunRecord:
        runtime = self._runtime_for(str(snapshot["workflow_id"]))
        stored_gate = snapshot.get("pending_gate")
        prompt = (
            dict(stored_gate.get("request", {}))
            if isinstance(stored_gate, Mapping)
            else None
        )
        if prompt is not None and not prompt.get("expires_at"):
            # Older prompts predate the deadline in the request body; the
            # run_gates row has carried it since open_gate() either way.
            stored_expiry = stored_gate.get("expires_at")
            if isinstance(stored_expiry, datetime):
                prompt["expires_at"] = stored_expiry.isoformat()
            elif stored_expiry:
                prompt["expires_at"] = str(stored_expiry)
        if prompt is not None:
            # A gate opened by an earlier build stored every field as editable.
            # Re-split it here so recovery shows the same affordance a fresh
            # gate does, and so the reply check refuses the same edits.
            prompt = _normalize_gate_prompt(prompt)
        context = None
        flow_id = snapshot.get("flow_id")
        if flow_id and snapshot.get("status") == RunStatus.WAITING.value:
            loaded = self.persistence.load_pending_feedback(str(flow_id))
            if loaded is not None:
                _, context = loaded
        stored_usage = _empty_usage()
        stored_usage.update(dict(snapshot.get("usage", {})))
        stored_node_usage = {
            (str(metrics["node_id"]), str(metrics["model"])): {
                field_name: (
                    float(metrics[field_name])
                    if field_name == "cost_usd"
                    else metrics[field_name]
                )
                for field_name in (
                    "node_id",
                    "model",
                    *_USAGE_INTEGER_FIELDS,
                    "cost_usd",
                )
            }
            for metrics in self.persistence.get_node_metrics(str(snapshot["run_id"]))
        }
        record = RunRecord(
            run_id=str(snapshot["run_id"]),
            session_id=str(snapshot["session_id"]),
            workflow_id=str(snapshot["workflow_id"]),
            graph_version=str(snapshot["graph_version"]),
            inputs=dict(snapshot.get("inputs", {})),
            node_registry=runtime.node_registry,
            flow_id=str(flow_id) if flow_id else None,
            on_frames=self._enqueue_frames,
            ring_capacity=self.ring_capacity,
            max_cost_usd=self.max_run_cost_usd,
            # A recovered run keeps spending against the ceiling in force NOW,
            # not the one it was admitted under, and its already-spent total
            # comes back with it in `usage` below - so a run restored mid-flight
            # trips at the same place it would have without the restart.
            stop_reason=_restored_stop_reason(snapshot.get("error")),
            status=RunStatus(str(snapshot["status"])),
            created_at=snapshot["created_at"],
            started_at=snapshot.get("started_at"),
            completed_at=snapshot.get("completed_at"),
            result=snapshot.get("result"),
            error=snapshot.get("error"),
            pending_gate=prompt,
            pending_context=context,
            usage=stored_usage,
            node_usage=stored_node_usage,
            subscriber_dropped=int(
                snapshot.get("frames", {}).get("subscriber_dropped", 0)
            ),
        )
        if isinstance(stored_gate, Mapping):
            # F03 across a restart: the durable status says which watch frames
            # this gate already produced, so recovery reports the gate expired
            # without re-emitting an expiry or a second R-2 alert for it.
            recovered_gate_id = str(
                (prompt or {}).get("gate_id") or stored_gate.get("gate_id") or ""
            )
            if recovered_gate_id:
                record.adopt_gate_watch(
                    recovered_gate_id,
                    str(stored_gate.get("status") or ""),
                )
        after = 0
        while True:
            page = self.persistence.replay_frames(
                record.run_id,
                after=after,
                limit=MAX_REPLAY_LIMIT,
            )
            if not page:
                break
            # Recovered from the frames rather than from the `runs` row, which
            # has no column for it. That is not a workaround: the durable frame
            # IS the record of the verdict, so this reconstruction cannot
            # disagree with what the client replays, and it needs no migration
            # for a value the run already persists. Replay is ordered, so the
            # last one wins - a revise re-scores, and the corrected verdict is
            # the one this run stands behind.
            for frame in page:
                if str(frame["kind"]) == FrameKind.VERDICT.value:
                    record.verdict = dict(frame.get("details", {}))
            drafts = [
                FrameDraft(
                    ts=datetime.fromisoformat(str(frame["ts"]).replace("Z", "+00:00")),
                    kind=FrameKind(str(frame["kind"])),
                    event_type=UIEventType(str(frame["event_type"])),
                    level=FrameLevel(str(frame["level"])),
                    node_id=str(frame["node_id"]),
                    message=str(frame["message"]),
                    details=dict(frame.get("details", {})),
                    duration_ms=frame.get("duration_ms"),
                )
                for frame in page
            ]
            record.buffer.push_many(record.run_id, drafts)
            after = int(page[-1]["seq"])
            if len(page) < MAX_REPLAY_LIMIT:
                break
        return record
