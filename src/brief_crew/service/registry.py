"""Workflow-aware run registry with durable state and live subscriptions."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
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
    RUN_CONCURRENCY,
    VALIDATOR_FRAME_BATCH_SIZE,
    VALIDATOR_FRAME_FLUSH_INTERVAL_SECONDS,
    VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS,
    VALIDATOR_GATE_SWEEP_INTERVAL_SECONDS,
    VALIDATOR_GATE_TIMEOUT_SECONDS,
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


def _usage_from_result(result: Any) -> dict[str, int] | None:
    for attribute in ("usage_metrics", "token_usage"):
        value = getattr(result, attribute, None)
        if value is None:
            continue
        usage = normalize_usage(value)
        if any(usage.values()):
            return usage
    return None


@dataclass(frozen=True, slots=True)
class WorkflowRuntime:
    graph_version: str
    node_registry: NodeRegistry
    runner: Runner


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
            self.result = self.capture.serializer.clip(result)
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
                "error": self.error,
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
        cost_usd = compute_cost_usd(
            model,
            usage["prompt_tokens"],
            usage["completion_tokens"],
        )
        measured: dict[str, int | float | str] = {
            **usage,
            "elapsed_ms": elapsed_ms,
            "cost_usd": cost_usd,
        }
        for field_name in _USAGE_INTEGER_FIELDS:
            self.usage[field_name] = int(self.usage.get(field_name, 0)) + int(
                measured[field_name]
            )
        self.usage["cost_usd"] = round(
            float(self.usage.get("cost_usd", 0.0)) + cost_usd,
            12,
        )

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
        node["cost_usd"] = round(float(node["cost_usd"]) + cost_usd, 12)
        self._usage_revision += 1

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
    ) -> None:
        if max_workers is None:
            max_workers = RUN_CONCURRENCY
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self.gate_sweep_interval = (
            VALIDATOR_GATE_SWEEP_INTERVAL_SECONDS
            if gate_sweep_interval is None
            else float(gate_sweep_interval)
        )
        if self.gate_sweep_interval < 0:
            raise ValueError("gate_sweep_interval cannot be negative")
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
        self._sweeper_stop = Event()
        self._sweeper: Thread | None = None
        if self.gate_sweep_interval > 0:
            self._sweeper = Thread(
                target=self._sweep_loop,
                name="validator-gate-sweeper",
                daemon=True,
            )
            self._sweeper.start()

    def _runtime_for(self, workflow_id: str) -> WorkflowRuntime:
        if self.workflows:
            try:
                return self.workflows[workflow_id]
            except KeyError as exc:
                raise KeyError(workflow_id) from exc
        return self._default_runtime

    def create_run(
        self,
        *,
        session_id: str,
        workflow_id: str,
        inputs: Mapping[str, Any],
    ) -> RunRecord:
        runtime = self._runtime_for(workflow_id)
        run_id = str(uuid.uuid4())
        flow_id = run_id if hasattr(runtime.runner, "resume") else None
        record = RunRecord(
            run_id=run_id,
            session_id=session_id,
            workflow_id=workflow_id,
            graph_version=runtime.graph_version,
            inputs=inputs,
            node_registry=runtime.node_registry,
            flow_id=flow_id,
            on_frames=self._enqueue_frames,
            ring_capacity=self.ring_capacity,
        )
        if self.persistence is not None:
            self.persistence.create_run(
                run_id=run_id,
                session_id=session_id,
                workflow_id=workflow_id,
                flow_id=flow_id,
                graph_version=runtime.graph_version,
                inputs=inputs,
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
            raise ValueError(f"outcome must be one of {sorted(option_ids)}")

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
            node_id=context.method_name,
            message=f"{prompt['title']} answered",
            details={
                "gate_id": gate_id,
                "outcome": outcome,
                "fields": dict(fields or {}),
                "late": late,
            },
        )
        feedback = self._feedback(context, outcome, fields or {})
        return self._submit(record, context=context, feedback=feedback)

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
        with self._lock:
            current = self._futures.get(record.run_id)
            if current is not None and not current.done():
                raise RuntimeError(f"run {record.run_id} is already executing")
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
                        "timeout_seconds": VALIDATOR_GATE_TIMEOUT_SECONDS,
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
                        "timeout_seconds": VALIDATOR_GATE_TIMEOUT_SECONDS,
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
                    VALIDATOR_GATE_TIMEOUT_SECONDS,
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
        context = record.pending_context
        node_id = str(
            prompt.get("node_id")
            or (context.method_name if context is not None else "")
        )
        return node_id or record.node_registry.workflow_node_id

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
            record.capture.emit(
                kind=FrameKind.RUN_STATE,
                event_type=UIEventType.WORKFLOW_END,
                node_id=record.node_registry.workflow_node_id,
                message="Run cancelled at a step boundary",
                details={"status": "cancelled"},
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
        prompt = self._gate_prompt(record.run_id, context)
        if self.persistence is not None:
            state = self.persistence.load_state(context.flow_id) or {
                "id": context.flow_id
            }
            self.persistence.save_pending_feedback(context.flow_id, context, state)
            self.persistence.open_gate(
                record.run_id,
                str(prompt["gate_id"]),
                node_id=context.method_name,
                request=prompt,
                opened_at=context.requested_at,
                expires_at=datetime.fromisoformat(str(prompt["expires_at"])),
            )
        record.mark_waiting(prompt, context)
        record.capture.emit(
            kind=FrameKind.GATE_OPEN,
            event_type=UIEventType.HUMAN_INTERACTION,
            node_id=context.method_name,
            message=str(prompt["title"]),
            details=prompt,
        )
        # The run is now idle until a human answers, so this is the natural
        # place for a reconciled snapshot: nothing more will change until the
        # reply lands, and the next tick would only repeat these numbers.
        record.emit_metrics("gate_open")
        self._persist_status(record)

    @staticmethod
    def _gate_prompt(
        run_id: str,
        context: PendingFeedbackContext,
    ) -> dict[str, Any]:
        output = context.method_output
        if isinstance(output, str):
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                parsed = {"feedback": output}
        elif isinstance(output, Mapping):
            parsed = dict(output)
        else:
            model_dump = getattr(output, "model_dump", None)
            parsed = model_dump(mode="json") if model_dump is not None else {}

        fields = {
            str(key): value if isinstance(value, str) else json.dumps(value)
            for key, value in parsed.items()
        }
        scope_gate = context.method_name == "confirm_scope"
        title = "Confirm scope" if scope_gate else "Review verdict"
        summary = (
            str(parsed.get("category") or parsed.get("startup_idea") or context.message)
            if scope_gate
            else str(parsed.get("cheapest_next_test") or context.message)
        )
        gate_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{run_id}:{context.method_name}:{context.requested_at.isoformat()}",
            )
        )
        expires_at = context.requested_at + timedelta(
            seconds=VALIDATOR_GATE_TIMEOUT_SECONDS
        )
        return {
            "gate_id": gate_id,
            "node_id": context.method_name,
            "title": title,
            "summary": summary[:4096],
            "editable": True,
            "expires_at": expires_at.isoformat(),
            "options": [
                {"id": "approve", "label": "Approve", "emphasis": "primary"},
                {"id": "revise", "label": "Revise"},
            ],
            "fields": fields,
            "verdict": parsed.get("verdict"),
            "confidence": parsed.get("confidence"),
        }

    @staticmethod
    def _feedback(
        context: PendingFeedbackContext,
        outcome: str,
        fields: Mapping[str, str],
    ) -> str:
        decision = "revise" if outcome in {"revise", "scope_revise", "verdict_revise"} else "approve"
        payload: dict[str, Any] = {"decision": decision}
        if fields:
            output = context.method_output
            if isinstance(output, str):
                try:
                    original = json.loads(output)
                except json.JSONDecodeError:
                    original = {}
            elif isinstance(output, Mapping):
                original = dict(output)
            else:
                original = {}
            for key, value in fields.items():
                try:
                    original[key] = json.loads(value)
                except json.JSONDecodeError:
                    original[key] = value
            payload["scope" if context.method_name == "confirm_scope" else "verdict"] = original
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
