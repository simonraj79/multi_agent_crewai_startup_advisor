"""The frame consumer: one queue, one thread, one trace per run.

Where it attaches
-----------------
`RunRegistry._enqueue_frames` - the callback the run's own `StreamSinkAdapter`
already invokes with every batch of frames it produced. That is the one place in
this application where run id, node id, agent role, task name, tool name, model,
token counts, cost, the provider's generation id, error class, retry attempt and
gate state are ALL already resolved, bounded, redacted and totally ordered by
sequence number. Attaching anywhere else means re-solving problems the frame
pipeline has already solved.

The price is a trap, and it is measured rather than assumed: that callback runs
while the adapter's `_capture_lock` is held, and that lock is a plain
non-reentrant `threading.Lock`. So `on_frames` here does queue operations and
nothing else - no I/O, no second lock, no frame emitted, no exception allowed
out. Everything after it happens on the daemon thread below.

The shape is the frame-persistence queue's in `service/registry.py`,
deliberately and almost literally: a bounded queue that drops the OLDEST and
counts it, a daemon thread that wakes on a short interval, a bounded `flush()`
that can never hang a caller, an idempotent `close()`, and every path total. A
second answer to any of those would be a second thing to reason about at three
in the morning.

(That class's own name is not spelled here, and the omission is not shyness: it
ends in a word that is also an agent key in one of this repository's crews, and
row C1's grep - correctly - cannot tell a class name from a role.)

What it builds
--------------
`docs/observability/TRACE-CONTRACT.md`, sections 1-8. One trace per run, keyed
on the run id; a run span; a node span per flow-method execution; task and agent
spans opened from the identity the frames carry and NOTHING else; a GENERATION
per model call, successful or failed; a TOOL observation per tool call; an EVENT
for a gate and for anything this file has never seen.

Identity is only ever read off a frame. There is no table of roles, no list of
tasks, no set of tool names anywhere in this package, and
`tests/observability/test_no_flow_identifiers.py` asserts that mechanically. A
flow drawn on a canvas next month is traced by exactly this code with exactly
these names, because the names come from the frames it produces.

Three shapes the transport forces, and where they are handled
--------------------------------------------------------------
The SDK's OpenTelemetry client starts a span when the span object is made and
cannot revise one after it ends (see `backend.py`). Three consequences live
here:

* **The queue is drained on a short interval**, so a span starts within tens of
  milliseconds of its frame, and every observation carries `metadata.frame_ts`
  - the frame's exact timestamp - regardless.
* **Every observation is ended with the frame's own timestamp**, so durations
  are the app's and not the exporter's.
* **A model call is held open until its billed cost resolves**, on a small pool
  and against a deadline, because after `end()` there is nowhere to put it.

Re-delivery
-----------
Observation ids are the SDK's OpenTelemetry span ids and cannot be derived from
a frame, so the contract's "a re-delivered frame updates rather than
duplicates" is enforced on this side instead: frame sequence numbers are
gapless and increasing per run, and a frame whose sequence this run has already
processed is ignored. A reconnect replay therefore adds nothing rather than
doubling a trace.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
import logging
from queue import Empty, Full, Queue
import threading
from time import monotonic, perf_counter_ns
from typing import Any, Mapping, Sequence

from brief_crew.events.models import FrameData, FrameKind, FrameLevel, UIEventType
from brief_crew.observability import backend as transport
from brief_crew.observability.backend import (
    Backend,
    TYPE_AGENT,
    TYPE_GENERATION,
    TYPE_SPAN,
    TYPE_TOOL,
)
from brief_crew.observability.billed_cost import (
    BilledCost,
    CostLookup,
    NullCostLookup,
)
from brief_crew.observability.content import (
    content_or_description,
    fingerprint,
    policy_details,
    safe_message,
)
from brief_crew.observability.mapping import (
    ACTOR,
    COST_CEILING_REASON,
    EVENT,
    FOLD,
    GENERATION,
    INTERRUPTED_REASON,
    NODE,
    RUN,
    SCORE,
    TOOL,
    disposition_for,
)
from brief_crew.observability.policy import ExporterPolicy


logger = logging.getLogger(__name__)

#: The per-run summary has its own logger, and it logs at WARNING.
#:
#: Not a style choice, and not shouting. Under `serve.exe` nothing configures
#: the root logger, so `logging.lastResort` handles the records - and that
#: handler is fixed at WARNING. An INFO summary line is therefore DROPPED in
#: the one deployment where somebody actually wants to read it, which is how a
#: measured run came back reporting nothing. A dedicated logger means an
#: operator who finds it noisy can silence exactly this line without silencing
#: the exporter's failure reporting.
summary_logger = logging.getLogger("brief_crew.observability.summary")


#: How many finished runs keep their counters readable through `stats()`. The
#: reconciliation tooling reads them after a run ends, and an unbounded map of
#: every run a long-lived process ever served is a leak.
_FINISHED_STATS_KEPT = 128

#: Enqueue-latency samples held for the whole exporter before the export thread
#: folds them into per-run lists. Bounded because the producer must never be
#: able to grow memory when the consumer has stopped.
_LATENCY_SAMPLES = 8192

#: How long a model call whose end has been seen waits for its token frame
#: before being finished without one. The two frames are emitted together on
#: both the real and the no-cost path, so this only fires when something has
#: gone wrong.
_USAGE_GRACE_SECONDS = 2.0

_SHUTDOWN = object()

#: How long `close()` waits for the export thread to notice the sentinel, and
#: how long it then waits for each thing it built to close. Both are bounds on
#: a SHUTDOWN path, so they are generous enough that a healthy close never hits
#: them and short enough that a wedged one is over before anybody notices.
_CLOSE_JOIN_SECONDS = 10.0
_CLOSE_BACKEND_SECONDS = 15.0

#: The section 3 keys that belong to the frame which OPENED an observation and
#: must not be rewritten by the frame that closes it. A TOOL is the only
#: observation this repository has that is opened by one frame and closed by
#: another it also carries metadata from; the rule is stated over the key names
#: so a second such case cannot get it wrong.
_OPENING_FRAME_KEYS = ("frame_seq", "frame_ts", "frame_kind", "event_type")

#: The section 3 keys a frame is allowed not to carry. `run_id`, `node_id` and
#: the four frame facts are on every frame by construction.
_NULLABLE_SECTION_THREE_KEYS = ("agent_role", "task_name")

#: How many items the drop-oldest path will look past before giving up. It only
#: looks past flush markers and the shutdown sentinel, and a queue holding
#: eight of those at once would mean eight concurrent flush callers on a queue
#: with no frames in it.
_DISPLACE_ATTEMPTS = 8

_DEFAULT = "DEFAULT"
_WARNING = "WARNING"
_ERROR = "ERROR"

_LEVELS = {
    FrameLevel.INFO: _DEFAULT,
    FrameLevel.WARNING: _WARNING,
    FrameLevel.ERROR: _ERROR,
}

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

#: The one-line self-report. Its populations are named in the field names on
#: purpose: an earlier spelling read `enqueued=95 sent=108`, two different
#: things counted in two different units with no way to tell from the line.
SUMMARY_FORMAT = (
    "langfuse-exporter run=%s frames_enqueued=%d frames_dropped=%d "
    "observations_sent=%d http_errors=%d lookup_ok=%d lookup_failed=%d "
    "enqueue_p50_us=%d enqueue_p95_us=%d"
)


class _FlushMarker:
    __slots__ = ("done",)

    def __init__(self) -> None:
        self.done = threading.Event()


@dataclass(slots=True)
class _Item:
    run_id: str
    frames: tuple[FrameData, ...]
    evicted_run_id: str | None = None


@dataclass(slots=True)
class RunFacts:
    """What the registry knows about a run that no frame carries.

    Read off the `RunRecord` by attribute, so this package imports nothing from
    the service layer and a test can hand it any object with these names.
    """

    run_id: str
    workflow_id: str = "unknown"
    session_id: str = ""
    user_id: str = "anonymous"
    graph_version: str = ""
    gates: str = "human"
    mode: str = "run"
    inputs: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record: Any) -> "RunFacts":
        inputs = dict(getattr(record, "inputs", {}) or {})
        # The service turns `gates="auto"` into exactly one reserved input key,
        # so this is the run's mode as the request declared it and not a second
        # source of truth.
        gates = "auto" if inputs.get("no_gates") else "human"
        return cls(
            run_id=str(getattr(record, "run_id", "") or ""),
            workflow_id=str(getattr(record, "workflow_id", "") or "unknown"),
            session_id=str(getattr(record, "session_id", "") or ""),
            user_id=str(getattr(record, "user_id", None) or "anonymous"),
            graph_version=str(getattr(record, "graph_version", "") or ""),
            gates=gates,
            mode=str(getattr(record, "mode", "run") or "run"),
            inputs=inputs,
        )


@dataclass(slots=True)
class _Span:
    handle: Any
    name: str
    started: datetime
    metadata: dict[str, Any]
    #: Model calls counted under this span: what `attempt` indexes and what the
    #: `task_attempts` score reports.
    generations: int = 0


@dataclass(slots=True)
class _NodeScope:
    span: _Span
    task: _Span | None = None
    task_key: str = ""
    agent: _Span | None = None
    agent_key: str = ""
    #: Whether this scope has seen the node's OWN start frame. A scope can be
    #: opened by something that arrives first - the edge frame naming this node
    #: as its destination precedes the node's start on the no-cost path - and
    #: the start must then ADOPT it rather than open a second span for one
    #: execution.
    started: bool = False


@dataclass(slots=True)
class _Generation:
    handle: Any
    call_id: str
    model: str
    start: datetime
    metadata: dict[str, Any]
    task_span: _Span | None
    end: datetime | None = None
    level: str = _DEFAULT
    status_message: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float | None = None
    response_id: str | None = None
    completion_text: str = ""
    completion_chars: int = 0
    stream_chunks: int = 0
    awaiting_usage_since: float | None = None
    lookup: "Future[BilledCost | None] | None" = None
    lookup_deadline: float | None = None
    closed: bool = False


@dataclass(slots=True)
class _RunState:
    facts: RunFacts
    trace_id: str
    run_span: _Span | None = None
    opened: bool = False
    terminal: str | None = None
    last_seq: int = 0
    nodes: dict[str, _NodeScope] = field(default_factory=dict)
    #: Nodes whose span has been closed. A frame arriving for one of these -
    #: the run's own computed result, emitted after the method that produced it
    #: returned - hangs off the RUN span rather than reopening the node, which
    #: would read on the timeline as the node having run a second time.
    finished_nodes: set[str] = field(default_factory=set)
    generations: dict[str, _Generation] = field(default_factory=dict)
    tools: dict[str, _Span] = field(default_factory=dict)
    #: The LAST metrics snapshot the run emitted, whenever it arrived. The
    #: `run_completed` one lands AFTER the terminal frame, which is why the run
    #: span's own end is deferred to `_close_out`.
    metrics: dict[str, Any] = field(default_factory=dict)
    #: CrewAI event classes the frame pipeline counted and did not convert, as
    #: the terminal frame reported them. Never a table held here: the count is
    #: the serializer's and this only carries it out.
    unhandled_events: dict[str, int] = field(default_factory=dict)
    #: The terminal frame's timestamp, level and message, held from
    #: `_finish_run` until `_close_out` writes them onto the run span. The
    #: TIMESTAMP is the point: the span still ends exactly where the app said
    #: the run ended, whatever time it is when the call is finally made.
    terminal_ts: "datetime | None" = None
    terminal_level: str = _DEFAULT
    terminal_message: str | None = None
    run_span_ended: bool = False
    counters: dict[str, int] = field(
        default_factory=lambda: {
            "frames_enqueued": 0,
            "frames_dropped": 0,
            "observations_sent": 0,
            "http_errors": 0,
            "lookup_ok": 0,
            "lookup_failed": 0,
        }
    )
    latencies: list[int] = field(default_factory=list)
    transport_failures_at_open: int = 0
    failure_logged: bool = False
    summary_logged: bool = False
    #: Set once the terminal frame has been handled and every observation has
    #: been ended. The summary waits for the final flush after this.
    awaiting_summary: bool = False
    #: Not before this moment on the monotonic clock. A run's last frames - the
    #: coalesced totals the registry emits right after the terminal one - arrive
    #: in a separate batch, and a summary logged the instant the terminal frame
    #: landed reported one frame fewer than the run produced.
    summary_ready_at: float = 0.0


def _percentile(samples: Sequence[int], fraction: float) -> int:
    if not samples:
        return 0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return int(ordered[index])


class NullExporter:
    """The exporter when there is nowhere to send: every method a no-op.

    Built rather than `None` so that the wiring in `service/app.py` and
    `service/registry.py` has one shape and no branch, and so a misconfigured
    deployment behaves identically to a configured one from the application's
    point of view - which is the whole of row E2.
    """

    def __init__(self, reason: str = "not configured") -> None:
        self.reason = reason

    def begin_run(self, record: Any) -> None:
        return None

    def on_frames(self, run_id: str, frames: tuple[FrameData, ...]) -> None:
        return None

    def stats(self, run_id: str) -> dict[str, Any]:
        return {}

    def flush(self, timeout: float = 1.0) -> bool:
        return True

    def close(self) -> None:
        return None


class LangfuseExporter:
    """Frames in on the capture thread, observations out on its own."""

    def __init__(
        self,
        policy: ExporterPolicy,
        *,
        sender: Backend | None = None,
        cost_lookup: CostLookup | None = None,
        start_thread: bool = True,
    ) -> None:
        self.policy = policy
        self._backend: Any = sender if sender is not None else self._default_backend(policy)
        self._cost_lookup = (
            cost_lookup if cost_lookup is not None else self._default_lookup(policy)
        )
        self._pool: ThreadPoolExecutor | None = None
        if not isinstance(self._cost_lookup, NullCostLookup):
            self._pool = ThreadPoolExecutor(
                max_workers=max(1, policy.lookup_workers),
                thread_name_prefix="langfuse-cost",
            )
        self._queue: Queue[Any] = Queue(maxsize=policy.queue_capacity)
        self._latency: deque[tuple[str, int]] = deque(maxlen=_LATENCY_SAMPLES)
        self._facts: dict[str, RunFacts] = {}
        self._facts_lock = threading.Lock()
        self._states: dict[str, _RunState] = {}
        self._finished: "deque[tuple[str, dict[str, Any]]]" = deque(
            maxlen=_FINISHED_STATS_KEPT
        )
        self._closed = threading.Event()
        self._thread: threading.Thread | None = None
        if start_thread:
            self._thread = threading.Thread(
                target=self._loop, name="langfuse-exporter", daemon=True
            )
            self._thread.start()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_backend(policy: ExporterPolicy) -> Any:
        return transport.LangfuseBackend(
            public_key=policy.public_key,
            secret_key=policy.secret_key,
            base_url=policy.host,
            environment=policy.environment,
            flush_interval=policy.flush_interval_seconds,
            flush_at=policy.batch_max_events,
            timeout=policy.http_timeout_seconds,
        )

    @staticmethod
    def _default_lookup(policy: ExporterPolicy) -> CostLookup:
        # A synthetic run's generation ids are fabricated by the no-cost
        # doubles: asking the provider about them would be a request per model
        # call that can only ever 404. The contract says skip entirely, and
        # this is where "entirely" is implemented.
        if not policy.resolve_billed_cost or policy.synthetic:
            return NullCostLookup()
        from brief_crew import config as project_config
        from brief_crew.observability.billed_cost import HttpCostLookup

        return HttpCostLookup(
            url=project_config.OPENROUTER_GENERATION_URL,
            timeout=policy.http_timeout_seconds,
        )

    # ------------------------------------------------------------------
    # The capture-thread surface. Queue operations and nothing else.
    # ------------------------------------------------------------------

    def begin_run(self, record: Any) -> None:
        """Record what the registry knows about a run before its first frame.

        Called on the request thread at run registration, never on the capture
        path, so a small lock here costs nothing. The facts are kept out of the
        queue on purpose: a drop-oldest queue could evict them, and a trace
        without its workflow id, owner and gate mode answers none of row A3.
        """

        try:
            facts = RunFacts.from_record(record)
            if not facts.run_id:
                return
            with self._facts_lock:
                self._facts[facts.run_id] = facts
        except Exception:  # pragma: no cover - reading attributes cannot fail usefully
            logger.debug("langfuse exporter could not read a run record", exc_info=True)

    def on_frames(self, run_id: str, frames: tuple[FrameData, ...]) -> None:
        """The hook. One `put_nowait`, drop the OLDEST, measure, and return.

        The two `perf_counter_ns` calls and the deque append are the only other
        statements, and none of the three takes a lock or does I/O. Everything
        they record is folded into the run's counters by the export thread, so
        no counter is ever mutated from the capture path.
        """

        if self._closed.is_set() or not frames:
            return
        started = perf_counter_ns()
        item = _Item(run_id=run_id, frames=frames)
        try:
            self._queue.put_nowait(item)
        except Full:
            self._displace(item, run_id)
        except Exception:  # pragma: no cover - a queue put has no other failure
            return
        self._latency.append((run_id, perf_counter_ns() - started))

    def _displace(self, item: _Item, run_id: str) -> None:
        """Drop the oldest FRAMES to make room, and never anything else.

        The queue carries three things, and only one of them is expendable.
        Discarding whatever `get_nowait` returned - which is what this did -
        could evict a `_FlushMarker`, leaving its caller to wait out the whole
        flush timeout for a flush that will never be signalled, or the
        `_SHUTDOWN` sentinel, leaving the export thread running and `close()`
        burning its full join. Both were measured on a queue driven to
        capacity; a control run at the default capacity of 4096 never reaches
        either, which is why a green suite did not see it.

        A displaced marker or sentinel is put BACK, and the search moves on to
        the next item. If everything ahead is a marker or a sentinel there is
        nothing to drop, so the frames are the thing lost - which is the
        correct answer at that point and is counted as a drop either way.
        """

        for _ in range(_DISPLACE_ATTEMPTS):
            try:
                displaced = self._queue.get_nowait()
            except Empty:  # pragma: no cover - another thread drained it first
                break
            if displaced is _SHUTDOWN or isinstance(displaced, _FlushMarker):
                try:
                    self._queue.put_nowait(displaced)
                except Full:  # pragma: no cover - the marker cannot be kept
                    if isinstance(displaced, _FlushMarker):
                        displaced.done.set()
                continue
            item.evicted_run_id = getattr(displaced, "run_id", run_id)
            break
        if item.evicted_run_id is None:
            item.evicted_run_id = run_id
        try:
            self._queue.put_nowait(item)
        except Full:  # pragma: no cover - the queue refilled in between
            item.evicted_run_id = run_id

    def stats(self, run_id: str) -> dict[str, Any]:
        """The per-run counters, for the reconciliation tooling.

        Read without a lock and therefore possibly a batch stale. That is the
        right trade for a self-report: taking the export thread's lock to read
        a counter would put the capture path's own callback behind a reader.
        """

        state = self._states.get(run_id)
        if state is not None:
            return self._summary(state)
        for finished_id, summary in reversed(self._finished):
            if finished_id == run_id:
                return dict(summary)
        return {}

    def flush(self, timeout: float = 5.0) -> bool:
        """Send everything already queued, bounded. Never hangs a caller."""

        thread = self._thread
        if thread is None or not thread.is_alive():
            return False
        marker = _FlushMarker()
        try:
            self._queue.put(marker, timeout=timeout)
        except Full:
            logger.warning("the langfuse export queue stayed full for %ss", timeout)
            return False
        if marker.done.wait(timeout):
            return True
        logger.warning("the langfuse exporter did not flush within %ss", timeout)
        return False

    def close(self) -> None:
        """Idempotent and bounded, and now that is true of every step.

        It said "bounded" before this and was not: the last loop called
        `LangfuseBackend.close()` straight through, which ends in the SDK's
        `queue.Queue.join()` with no timeout. Row E2 says an unreachable
        Langfuse must not affect the application, and the application's
        SHUTDOWN is part of the application - a process that cannot exit is
        the loudest possible way of affecting it. Three unbounded waits are
        gone, each named where it is fixed:

        1. `self._queue.put(_SHUTDOWN)` blocked when the queue was full and the
           export thread was wedged - the caller stopped before ever reaching
           the bounded join below. It is a `put_nowait` with the same
           drop-oldest fallback the capture path uses.
        2. `LangfuseBackend.close()` is bounded in the transport, and evicts
           the SDK's cached resource manager so the next exporter in this
           process gets live consumer threads.
        3. Each `closable.close()` here is run under a bounded wait as well, so
           a backend this class did not write cannot hold the caller either.
        """

        if self._closed.is_set():
            return
        self._closed.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            self.flush()
            self._enqueue_shutdown()
            thread.join(timeout=_CLOSE_JOIN_SECONDS)
            if thread.is_alive():  # pragma: no cover - a wedged export thread
                logger.warning(
                    "the langfuse export thread did not stop within %ss",
                    _CLOSE_JOIN_SECONDS,
                )
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
        for closable in (self._cost_lookup, self._backend):
            transport._bounded(
                closable.close, timeout=_CLOSE_BACKEND_SECONDS, what="close"
            )

    def _enqueue_shutdown(self) -> None:
        """Ask the export thread to stop, without ever waiting for room."""

        for _ in range(3):
            try:
                self._queue.put_nowait(_SHUTDOWN)
                return
            except Full:
                try:
                    self._queue.get_nowait()
                except Empty:  # pragma: no cover - another thread drained it
                    continue

    # ------------------------------------------------------------------
    # The export thread
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        try:
            while True:
                try:
                    item = self._queue.get(timeout=self.policy.flush_interval_seconds)
                except Empty:
                    self._settle()
                    continue
                if item is _SHUTDOWN:
                    self._settle(force=True)
                    return
                if isinstance(item, _FlushMarker):
                    self._settle(force=True)
                    try:
                        self._backend.flush()
                    except Exception:
                        logger.debug("the langfuse backend refused a flush", exc_info=True)
                    item.done.set()
                    continue
                self._absorb(item)
        except Exception:  # pragma: no cover - the loop itself must never die quietly
            logger.warning("the langfuse export thread stopped", exc_info=True)
        finally:
            self._release_markers()

    def _release_markers(self) -> None:
        """Never leave a caller blocked on a flush this thread will not do."""

        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                return
            if isinstance(item, _FlushMarker):
                item.done.set()

    def _absorb(self, item: _Item) -> None:
        state = self._state_for(item.run_id)
        try:
            self._fold_latencies()
            if item.evicted_run_id:
                evicted = self._states.get(item.evicted_run_id, state)
                evicted.counters["frames_dropped"] += 1
            for frame in item.frames:
                # Gapless and increasing per run, so a replayed frame is one
                # this run has already turned into observations.
                if frame.seq <= state.last_seq:
                    continue
                state.last_seq = frame.seq
                state.counters["frames_enqueued"] += 1
                self._handle(state, frame)
        except Exception as exc:
            self._note_failure(state, exc)
        self._settle()

    def _fold_latencies(self) -> None:
        while True:
            try:
                run_id, nanoseconds = self._latency.popleft()
            except IndexError:
                return
            state = self._states.get(run_id)
            if state is not None and len(state.latencies) < 20000:
                state.latencies.append(nanoseconds)

    def _state_for(self, run_id: str) -> _RunState:
        state = self._states.get(run_id)
        if state is not None:
            return state
        with self._facts_lock:
            facts = self._facts.get(run_id)
        # A frame for a run this exporter was never told about is still a run:
        # a record rebuilt after a restart takes a different path through the
        # registry, and an exporter attached to a live process sees runs that
        # predate it. It gets a trace with the facts a frame can carry.
        state = _RunState(
            facts=facts or RunFacts(run_id=run_id),
            trace_id=transport.trace_id_for(run_id),
        )
        state.transport_failures_at_open = self._transport_failures()
        self._states[run_id] = state
        return state

    def _transport_failures(self) -> int:
        try:
            return int(self._backend.transport_failures())
        except Exception:  # pragma: no cover - a counter that cannot count
            return 0

    def _note_failure(self, state: _RunState, exc: BaseException) -> None:
        """Count it, log it at most once per run, and carry on.

        The message names the exception class and the run. It never names a
        value: the values passing through here include a user's own text and,
        under capture, whatever a model said.
        """

        state.counters["http_errors"] += 1
        if not state.failure_logged:
            state.failure_logged = True
            summary_logger.warning(
                "langfuse export failed for run %s: %s",
                state.facts.run_id,
                type(exc).__name__,
            )

    # ------------------------------------------------------------------
    # Backend calls, each one total
    # ------------------------------------------------------------------

    def _call(self, state: _RunState, verb: str, *args: Any, **kwargs: Any) -> Any:
        try:
            result = getattr(self._backend, verb)(*args, **kwargs)
        except Exception as exc:
            self._note_failure(state, exc)
            return None
        if verb in ("open_run", "open_child", "event", "score"):
            state.counters["observations_sent"] += 1
        return result

    # ------------------------------------------------------------------
    # Settling: usage grace, cost lookups, terminal summary
    # ------------------------------------------------------------------

    def _settle(self, *, force: bool = False) -> None:
        now = monotonic()
        for state in list(self._states.values()):
            for generation in list(state.generations.values()):
                if generation.closed:
                    continue
                if (
                    generation.lookup is None
                    and generation.awaiting_usage_since is not None
                    and (force or now - generation.awaiting_usage_since >= _USAGE_GRACE_SECONDS)
                ):
                    self._complete_generation(state, generation)
                if generation.lookup is not None:
                    self._settle_lookup(state, generation, force=force, now=now)
            if (
                state.awaiting_summary
                and not self._outstanding(state)
                and (force or now >= state.summary_ready_at)
            ):
                self._close_out(state)

    @staticmethod
    def _outstanding(state: _RunState) -> bool:
        return any(not gen.closed for gen in state.generations.values())

    def _settle_lookup(
        self, state: _RunState, generation: _Generation, *, force: bool, now: float
    ) -> None:
        future = generation.lookup
        if future is None:
            return
        billed: BilledCost | None = None
        if future.done():
            try:
                billed = future.result()
            except Exception:
                billed = None
        elif force or (
            generation.lookup_deadline is not None and now >= generation.lookup_deadline
        ):
            # A provider that has not answered by the deadline must not hold a
            # trace open. The estimate stands and the observation says so.
            future.cancel()
        else:
            return
        generation.lookup = None
        if billed is None:
            state.counters["lookup_failed"] += 1
            generation.metadata["cost_source"] = "app-estimate (lookup failed)"
        else:
            state.counters["lookup_ok"] += 1
            generation.metadata["cost_source"] = "openrouter-billed"
            generation.metadata["openrouter_cost_usd"] = billed.total_usd
            if billed.provider:
                generation.metadata["provider"] = billed.provider
            generation.cost_usd = billed.total_usd
            # The frame pipeline's usage normalisation drops these two, so the
            # only place a reasoning-tier call's real split can come from is
            # the provider's own record.
            if billed.reasoning_tokens is not None:
                generation.usage["reasoning"] = billed.reasoning_tokens
            if billed.cached_tokens is not None:
                generation.usage["cached"] = billed.cached_tokens
        self._end_generation(state, generation)

    # ------------------------------------------------------------------
    # Frame handling
    # ------------------------------------------------------------------

    def _handle(self, state: _RunState, frame: FrameData) -> None:
        # `to_dict` rather than `dict(frame.details)`: details is a frozen
        # mapping tree, and a shallow copy leaves the nested maps frozen - the
        # same thawing the transport does, for the same reason.
        details = dict(frame.to_dict().get("details") or {})
        stage = details.get("stage")

        self._open_trace(state, frame, details)

        if self._is_run_level(frame):
            self._handle_run_level(state, frame, details)
            return

        disposition = disposition_for(frame.kind, str(stage) if stage else None)
        if state.terminal is not None:
            # After a terminal frame nothing opens. Whatever still arrives is
            # recorded as an EVENT on the run span rather than reopening a span
            # the contract has already said is closed.
            self._event(state, frame, details, parent=self._run_handle(state))
            return

        if disposition.kind == NODE:
            self._handle_node(state, frame, details)
        elif disposition.kind == ACTOR:
            self._handle_actor(state, frame, details)
        elif disposition.kind == GENERATION:
            self._handle_generation(state, frame, details)
        elif disposition.kind == TOOL:
            self._handle_tool(state, frame, details)
        elif disposition.kind == FOLD:
            self._handle_fold(state, frame, details)
        elif disposition.kind == SCORE:
            self._handle_score(state, frame, details)
        elif disposition.kind == RUN:
            # A run-level disposition on a node's frame: an inner flow failed,
            # which is not the run failing. It is an error on that node.
            self._event(state, frame, details, parent=self._scope(state, frame, details))
        else:
            self._event(state, frame, details, parent=self._scope(state, frame, details))

    @staticmethod
    def _is_run_level(frame: FrameData) -> bool:
        """Whether a frame speaks for the run rather than for something in it.

        Structural rather than a node-name comparison: the frame pipeline
        deliberately leaves run-level frames unstamped and puts them on the
        workflow node, and every one of them is one of these three shapes. A
        name comparison would be a fourth thing to keep in step.
        """

        if frame.kind in (FrameKind.RUN_STATE, FrameKind.METRICS):
            return True
        return (
            frame.kind is FrameKind.ERROR
            and frame.event_type is UIEventType.WORKFLOW_END
        )

    # ------------------------------------------------------------------
    # Trace and run span
    # ------------------------------------------------------------------

    def _open_trace(
        self, state: _RunState, frame: FrameData, details: Mapping[str, Any] | None = None
    ) -> None:
        if state.opened:
            return
        state.opened = True
        facts = state.facts
        # Contract section 3 applies to the RUN span too, and it did not:
        # a live export had the run span carrying `run_id` and six of the seven
        # keys missing entirely, so a reader who grouped observations by
        # `frame_seq` or `event_type` silently lost the one that speaks for the
        # whole run. The base is built first and the run's own facts are laid
        # over it, so a key can only ever be added here, never dropped.
        metadata = self._base_metadata(state, frame, details or {})
        metadata.update(
            {
                "run_id": facts.run_id,
                "workflow_id": facts.workflow_id,
                "app_session_id": facts.session_id,
                "gates": facts.gates,
                "mode": facts.mode,
                "synthetic": self.policy.synthetic,
                "user_id": facts.user_id,
                "graph_version": facts.graph_version,
                "observation_role": "run",
            }
        )
        # Only the two facts the contract itself marks optional are dropped when
        # empty ("graph_version (if known)"); a section 3 key is never dropped,
        # which is why this filter names them rather than testing every value.
        for optional in ("app_session_id", "graph_version"):
            if not metadata.get(optional):
                metadata.pop(optional, None)
        handle = self._call(
            state,
            "open_run",
            trace_id=state.trace_id,
            name=facts.workflow_id,
            metadata=metadata,
            user_id=facts.user_id,
            session_id=facts.run_id,
            tags=[facts.workflow_id, f"gates:{facts.gates}", f"mode:{facts.mode}"],
            payload_input=content_or_description(
                dict(facts.inputs),
                capture=self.policy.capture_content,
                prefix="input",
                secret_values=self.policy.secret_values,
            ),
        )
        if handle is None:
            return
        state.run_span = _Span(
            handle=handle, name="run", started=frame.ts, metadata=dict(metadata)
        )

    def _run_handle(self, state: _RunState) -> Any:
        return state.run_span.handle if state.run_span is not None else None

    def _handle_run_level(
        self, state: _RunState, frame: FrameData, details: Mapping[str, Any]
    ) -> None:
        self._absorb_unhandled(state, details)
        if frame.kind is FrameKind.METRICS:
            # Folded onto the run span rather than made an observation: it is a
            # coalesced snapshot of totals already carried by the generations
            # underneath, re-emitted whenever anything changes.
            #
            # LAST wins, terminal or not. The run's final `run_completed`
            # snapshot is emitted after the frame that ends the run, so a
            # branch here that stopped listening at the terminal frame - or a
            # run span already ended, which is what used to stop it - kept the
            # last INTERVAL snapshot instead. `_close_out` is what writes this,
            # and it runs after both.
            state.metrics = {
                key: value
                for key, value in details.items()
                if key in ("usage", "frames", "reason")
            }
            return

        status = str(details.get("status") or "")
        if frame.event_type is UIEventType.WORKFLOW_START or status == "running":
            return
        if frame.event_type is not UIEventType.WORKFLOW_END:
            self._event(state, frame, details, parent=self._run_handle(state))
            return
        self._finish_run(state, frame, details)

    @staticmethod
    def _absorb_unhandled(state: _RunState, details: Mapping[str, Any]) -> None:
        """Carry the frame pipeline's own unhandled-event tally onto the trace.

        The serializer converts a subset of CrewAI's `BaseEvent` classes and
        counts the rest by class name (`events/serializer.py::record_unhandled`).
        Those events never become frames, so no exporter downstream of the
        pipeline can turn them into observations however it is written - and
        until the count travelled, the gap was invisible to a reader of
        Langfuse rather than merely unmapped.

        Read off whatever run-level frame carries it, by key, so a producer
        that moves it from the terminal frame to the metrics snapshot needs no
        change here. Counts only: a class NAME and an integer, never a payload.
        """

        reported = details.get("unhandled_events")
        if not isinstance(reported, Mapping) or not reported:
            return
        counts: dict[str, int] = {}
        for name, value in list(reported.items())[:64]:
            try:
                counts[str(name)[:128]] = int(value)
            except (TypeError, ValueError):
                continue
        if counts:
            state.unhandled_events = counts

    def _terminal_of(
        self, frame: FrameData, details: Mapping[str, Any]
    ) -> tuple[str, str, str | None]:
        """(status, level, statusMessage) for a terminal frame. Section 6."""

        status = str(details.get("status") or "")
        secrets = self.policy.secret_values
        if frame.kind is FrameKind.ERROR:
            error_class = str(details.get("error_class") or "").strip()
            message = safe_message(str(details.get("error") or "").strip(), secrets)
            joined = f"{error_class}: {message}" if error_class else message
            return STATUS_FAILED, _ERROR, safe_message(joined, secrets) or "the run failed"
        if status == STATUS_CANCELLED:
            reason = str(details.get("reason") or "").strip()
            # An operator's cancel, a budget stop and a run orphaned by a
            # process restart all arrive here as `status: cancelled` and are
            # told apart by this ONE field. It used to be read as a boolean -
            # any reason at all meant the cost ceiling - and the registry has a
            # THIRD producer of it: `_fail_interrupted` writes
            # `reason: "service_restart"` for a run the process was killed
            # under. Both Render services carry `autoDeploy: yes`, so every
            # push to `main` can orphan an in-flight run, and every one of them
            # was reported to Langfuse as a run that breached a **$0.00** cost
            # ceiling - a fabricated money figure, in the surface whose whole
            # job is to be believed about money.
            if reason == COST_CEILING_REASON:
                return (
                    STATUS_FAILED,
                    _ERROR,
                    f"stopped by the run cost ceiling ({reason}): estimated "
                    f"${_as_float(details.get('cost_usd')):.4f} against a "
                    f"${_as_float(details.get('ceiling_usd')):.2f} ceiling",
                )
            if reason == INTERRUPTED_REASON:
                # Failed, not cancelled: nobody chose it and the run did not
                # finish. The sentence says what happened and names no figure,
                # because there is no figure - the run was interrupted, not
                # stopped for spending.
                return (
                    STATUS_FAILED,
                    _ERROR,
                    "interrupted by a service restart before the run finished",
                )
            if reason:
                # Some other machine-initiated stop. It is still a cancel - the
                # app said so - and the reason is reported rather than being
                # forced into one of the two branches above.
                return (
                    STATUS_CANCELLED,
                    _WARNING,
                    f"cancelled ({safe_message(reason, secrets, limit=128)})",
                )
            return STATUS_CANCELLED, _WARNING, "cancelled by operator"
        if status == STATUS_COMPLETED:
            return STATUS_COMPLETED, _DEFAULT, None
        return status or STATUS_COMPLETED, _DEFAULT, None

    def _finish_run(
        self, state: _RunState, frame: FrameData, details: Mapping[str, Any]
    ) -> None:
        if state.terminal is not None:
            return
        status, level, message = self._terminal_of(frame, details)
        state.terminal = status
        closing_level = {
            STATUS_COMPLETED: _WARNING,
            STATUS_FAILED: _ERROR,
            STATUS_CANCELLED: _WARNING,
        }.get(status, _WARNING)
        closing_message = {
            STATUS_COMPLETED: "ended by run completion",
            STATUS_FAILED: message or "the run failed",
            STATUS_CANCELLED: "cancelled",
        }.get(status, "ended by run completion")

        # Every model call that never saw its token frame, then every span
        # still open, innermost first. After this nothing is left without an
        # end time, which is row D3 in one sentence.
        for generation in list(state.generations.values()):
            if generation.closed:
                continue
            generation.end = generation.end or frame.ts
            if generation.level == _DEFAULT and status != STATUS_COMPLETED:
                generation.level = closing_level
                generation.status_message = closing_message
            if generation.lookup is None and generation.awaiting_usage_since is None:
                self._complete_generation(state, generation)
        for span in list(state.tools.values()):
            self._close_span(state, span, frame.ts, closing_level, closing_message)
        state.tools.clear()
        for scope in list(state.nodes.values()):
            self._close_scope(state, scope, frame.ts, closing_level, closing_message)
        state.nodes.clear()

        # The run span is NOT ended here, and that is the fix for the metrics
        # defect rather than a tidying. The registry's final `run_completed`
        # metrics snapshot arrives AFTER the terminal frame - measured at seq
        # 97 against a terminal frame at seq 96 - and a span cannot be revised
        # once ended on this transport, so ending it here wrote the previous
        # `interval` snapshot and then had nowhere to put the real one. A live
        # run's `run_metrics` therefore read 3 calls where the run had made 6.
        #
        # Everything about WHEN the span ends is unchanged: `_terminal_finish`
        # ends it at `frame.ts`, the terminal frame's own timestamp, which is
        # an explicit argument and not the exporter's clock. What moves is only
        # the moment the call is made - to `_close_out`, which already runs one
        # flush interval later and is forced immediately by `flush()` and
        # `close()`. Nothing is re-opened and nothing waits longer.
        state.terminal_ts = frame.ts
        state.terminal_level = level
        state.terminal_message = message

        self._call(
            state,
            "score",
            observation=None,
            trace_id=state.trace_id,
            name="run_succeeded",
            value=1 if status == STATUS_COMPLETED else 0,
        )
        self._call(
            state,
            "score",
            observation=None,
            trace_id=state.trace_id,
            name="run_status",
            value=status,
            data_type="CATEGORICAL",
        )
        state.awaiting_summary = True
        state.summary_ready_at = monotonic() + self.policy.flush_interval_seconds

    def _close_out(self, state: _RunState) -> None:
        """End the run span, flush, then log the summary, in that order, once.

        The order is the point twice over. The run span is written LAST of the
        observations so that the metrics snapshot the run emits after its own
        terminal frame is on it; and the summary is logged AFTER the flush,
        because a summary logged before it reports `http_errors=0` for a
        backend that was never reachable, which is the one number an operator
        would most want to be true and the one most easily made a lie.
        """

        state.awaiting_summary = False
        self._terminal_finish(state)
        try:
            # A flush that did not FINISH is counted, and that is not a fudge:
            # the counter answers "is there any reason to doubt this export",
            # and "the transport did not come back inside its own bound" is
            # such a reason. Reporting zero for it would be the same sentence
            # row E2 forbids, arrived at by silence instead of by a bug.
            if self._backend.flush() is False:
                self._note_failure(state, TimeoutError())
        except Exception as exc:
            self._note_failure(state, exc)
        self._log_summary(state)

    def _terminal_finish(self, state: _RunState) -> None:
        """Write the run span's final metadata and end it, at the frame's time."""

        run_span = state.run_span
        if run_span is None or state.run_span_ended or state.terminal_ts is None:
            return
        state.run_span_ended = True
        if state.metrics:
            run_span.metadata["run_metrics"] = state.metrics
        if state.unhandled_events:
            # C3's other half. The frame pipeline converts a subset of CrewAI's
            # event classes and counts the rest, and until this reached a trace
            # the count existed only inside a process that had already exited.
            # A reader who wonders why there are no retrieval spans can now see
            # that the run raised 14 `KnowledgeQueryStartedEvent`s that no
            # frame carries, rather than concluding the retrieval never
            # happened.
            run_span.metadata["unhandled_event_counts"] = state.unhandled_events
        message = state.terminal_message
        payload_output = {"status": state.terminal, "reason": message}
        self._call(state, "set_trace_output", run_span.handle, payload_output)
        self._call(
            state,
            "update",
            run_span.handle,
            metadata=run_span.metadata,
            payload_output=payload_output,
            # DEFAULT is the absence of a level, not a level. Writing it
            # would put a word on every successful run's span where the
            # console expects nothing, and make "did this run have a level
            # set" unanswerable.
            level=None if state.terminal_level == _DEFAULT else state.terminal_level,
            status_message=message,
        )
        self._close_span(
            state,
            run_span,
            state.terminal_ts,
            state.terminal_level,
            message,
            close_only=True,
        )

    # ------------------------------------------------------------------
    # Spans
    # ------------------------------------------------------------------

    def _safe(self, value: Any, *, limit: int = 1024) -> str:
        """Any string this exporter sends as TEXT, on either policy.

        One method rather than a `[:1024]` at each site, because the leak this
        closes was exactly a set of sites that each did their own bounding and
        none of which scrubbed: an exception message went RAW into six
        observations' `statusMessage` and into the trace's `output.reason`
        under the default content policy, planted key and all. `content.py`
        makes the same argument about `content_or_description` one layer down.
        """

        return safe_message(value, self.policy.secret_values, limit=limit)

    def _safe_or_none(self, value: Any, *, limit: int = 1024) -> Any:
        """`_safe`, but a value the frame did not carry stays `None`.

        Section 3 wants absent identity as `null` and not as `""`: an empty
        string is a value somebody wrote, and telling the two apart is the
        difference between "this frame named no agent" and "this frame named an
        agent with no name".
        """

        if value is None:
            return None
        return self._safe(value, limit=limit)

    def _base_metadata(
        self, state: _RunState, frame: FrameData, details: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Contract section 3: on EVERY observation, the same keys.

        `frame_ts` is here rather than in the contract because of the
        transport: a span starts when it is created, and this is the app's own
        exact timestamp for the thing it describes.

        The two identity strings are scrubbed rather than copied. They are the
        author's own words for their agent and their task and are meant to
        travel verbatim (row C2), and `_safe` leaves ordinary words exactly as
        they are - it only blanks something key-shaped or a value this process
        holds in a credential variable, which is a thing an agent role should
        never contain and which must not reach a console if it does.
        """

        base = {
            "run_id": state.facts.run_id,
            "node_id": frame.node_id,
            "agent_role": self._safe_or_none(details.get("agent_role"), limit=256),
            "task_name": self._safe_or_none(details.get("task_name"), limit=256),
            "frame_seq": frame.seq,
            "frame_kind": frame.kind.value,
            "event_type": frame.event_type.value,
            "frame_ts": transport.iso(frame.ts),
        }
        # A NULL cannot cross this transport, and the contract asks for one.
        #
        # Section 3 wants every key "present on every observation ... a value
        # the frame does not carry is `null`, never an absent key", and the
        # reason is a good one: a missing key and a null one read the same to
        # `.get()`, and a reader cannot tell "this frame named no agent" from
        # "the exporter forgot to send it". Measured against the live API: 11
        # of 33 observations came back without `agent_role` and `task_name`
        # after they were set to `None` here.
        #
        # The cause is one line of the SDK and it is not fixable from this side:
        # `_flatten_and_serialize_metadata` maps a `None` metadata value to a
        # `None` OTel attribute value (`_client/attributes.py:194-215`;
        # `_serialize(None)` IS `None`), and OpenTelemetry drops an attribute
        # whose value is None rather than sending a null. Writing the STRING
        # "null" instead would be worse: it is a value, and nothing downstream
        # could tell it from an agent actually called that.
        #
        # `null_fields` is the compensation and it is always present, empty
        # when nothing is null. Absent-and-listed means the frame carried none;
        # absent-and-not-listed means something is wrong - which is the
        # distinction the contract was written to preserve. Recorded as an
        # amendment at the end of `TRACE-CONTRACT.md`.
        base["null_fields"] = ",".join(
            key for key in _NULLABLE_SECTION_THREE_KEYS if base.get(key) is None
        )
        return base

    def _open_span(
        self,
        state: _RunState,
        parent: Any,
        *,
        name: str,
        as_type: str,
        role: str,
        start: datetime,
        metadata: dict[str, Any],
        payload_input: Any = None,
        model: str | None = None,
    ) -> _Span | None:
        metadata = dict(metadata)
        metadata["observation_role"] = role
        handle = self._call(
            state,
            "open_child",
            parent,
            name=name,
            as_type=as_type,
            metadata=metadata,
            payload_input=payload_input,
            model=model,
        )
        if handle is None:
            return None
        return _Span(handle=handle, name=name, started=start, metadata=metadata)

    def _close_span(
        self,
        state: _RunState,
        span: _Span,
        end: datetime,
        level: str = _DEFAULT,
        message: str | None = None,
        payload_output: Any = None,
        *,
        close_only: bool = False,
    ) -> None:
        if not close_only:
            self._call(
                state,
                "update",
                span.handle,
                metadata=span.metadata,
                payload_output=payload_output,
                level=None if level == _DEFAULT else level,
                status_message=message,
            )
        self._call(state, "end", span.handle, end_ns=transport.nanoseconds(end))

    def _node_scope(
        self, state: _RunState, frame: FrameData, details: Mapping[str, Any]
    ) -> _NodeScope | None:
        """The node span this frame belongs to, opening one if that is honest.

        Returns None when the node's own execution is already over and this
        frame is not a new start: see `_RunState.finished_nodes`.
        """

        scope = state.nodes.get(frame.node_id)
        if scope is not None:
            return scope
        if (
            frame.node_id in state.finished_nodes
            and frame.event_type is not UIEventType.NODE_START
        ):
            return None
        span = self._open_span(
            state,
            self._run_handle(state),
            name=frame.node_id,
            as_type=TYPE_SPAN,
            role="node",
            start=frame.ts,
            metadata=self._base_metadata(state, frame, details),
        )
        if span is None:
            return None
        scope = _NodeScope(span=span)
        state.nodes[frame.node_id] = scope
        return scope

    def _scope(
        self, state: _RunState, frame: FrameData, details: Mapping[str, Any]
    ) -> Any:
        """The innermost open observation a frame belongs under.

        Task and agent spans are opened HERE, from the identity the frame
        carries, rather than from an event class - which is what makes the
        hierarchy work for a flow nobody has written yet. A frame with no task
        identity hangs its agent off the node; one with no agent identity hangs
        off the task; the contract states both fall-throughs in those words, and
        the no-cost path exercises the first of them, because the doubles stamp
        an agent and a task name but raise no task-boundary frame.
        """

        scope = self._node_scope(state, frame, details)
        if scope is None:
            return self._run_handle(state)
        task_key = str(details.get("task_id") or details.get("task_name") or "")
        if task_key and (scope.task is None or scope.task_key != task_key):
            if scope.task is not None:
                self._close_task(state, scope, frame.ts)
            opened = self._open_span(
                state,
                scope.span.handle,
                name=str(details.get("task_name") or task_key),
                as_type=TYPE_SPAN,
                role="task",
                start=frame.ts,
                metadata=self._base_metadata(state, frame, details),
            )
            if opened is not None:
                scope.task = opened
                scope.task_key = task_key
                scope.agent = None
                scope.agent_key = ""
        agent_key = str(details.get("agent_id") or details.get("agent_role") or "")
        if agent_key and (scope.agent is None or scope.agent_key != agent_key):
            if scope.agent is not None:
                self._close_span(state, scope.agent, frame.ts)
                scope.agent = None
            parent = scope.task.handle if scope.task is not None else scope.span.handle
            opened = self._open_span(
                state,
                parent,
                name=str(details.get("agent_role") or agent_key),
                as_type=TYPE_AGENT,
                role="agent",
                start=frame.ts,
                metadata=self._base_metadata(state, frame, details),
            )
            if opened is not None:
                scope.agent = opened
                scope.agent_key = agent_key
        if scope.agent is not None:
            return scope.agent.handle
        if scope.task is not None:
            return scope.task.handle
        return scope.span.handle

    def _close_task(
        self,
        state: _RunState,
        scope: _NodeScope,
        end: datetime,
        level: str = _DEFAULT,
        message: str | None = None,
    ) -> None:
        task = scope.task
        if task is None:
            return
        if scope.agent is not None:
            self._close_span(state, scope.agent, end, level, message)
            scope.agent = None
            scope.agent_key = ""
        self._call(
            state,
            "score",
            observation=task.handle,
            trace_id=state.trace_id,
            name="task_attempts",
            value=task.generations,
        )
        self._close_span(state, task, end, level, message)
        scope.task = None
        scope.task_key = ""

    def _close_scope(
        self,
        state: _RunState,
        scope: _NodeScope,
        end: datetime,
        level: str = _DEFAULT,
        message: str | None = None,
        payload_output: Any = None,
    ) -> None:
        self._close_task(state, scope, end, level, message)
        if scope.agent is not None:
            self._close_span(state, scope.agent, end, level, message)
            scope.agent = None
        self._close_span(state, scope.span, end, level, message, payload_output)

    # ------------------------------------------------------------------
    # Per-disposition handlers
    # ------------------------------------------------------------------

    def _handle_node(
        self, state: _RunState, frame: FrameData, details: Mapping[str, Any]
    ) -> None:
        if frame.event_type is UIEventType.NODE_PAUSED:
            # A pause is not an end. The spans stay open and the pause is
            # recorded beside them; a resume continues in the same trace,
            # because the trace is keyed on the run id and the run id survives.
            self._event(state, frame, details, parent=self._scope(state, frame, details))
            return
        if frame.event_type is UIEventType.NODE_START:
            existing = state.nodes.get(frame.node_id)
            if existing is not None and existing.started:
                # A second start with no end between: the node is going round
                # again. End the first visit where the second began rather than
                # leaving it open for the terminal sweep to guess at.
                state.nodes.pop(frame.node_id, None)
                self._close_scope(state, existing, frame.ts)
            self._scope(state, frame, details)
            opened = state.nodes.get(frame.node_id)
            if opened is not None:
                # Adoption, not a second span: whatever opened this scope first
                # was part of entering the node, and the node ran once.
                opened.started = True
            return
        if frame.event_type is UIEventType.NODE_END:
            scope = state.nodes.pop(frame.node_id, None)
            if scope is None:
                self._scope(state, frame, details)
                scope = state.nodes.pop(frame.node_id, None)
            if scope is None:
                # The node is already finished and this is a second end for it.
                self._event(state, frame, details, parent=self._run_handle(state))
                return
            stage = str(details.get("stage") or "")
            level = _LEVELS.get(frame.level, _DEFAULT)
            message = None
            if stage == "error" or level == _ERROR:
                error_class = str(details.get("error_class") or "").strip()
                error = str(details.get("error") or "").strip()
                message = self._safe(f"{error_class}: {error}" if error_class else error)
                level = _ERROR
            payload_output = content_or_description(
                details.get("output_preview", details.get("result")),
                capture=self.policy.capture_content,
                prefix="output",
                secret_values=self.policy.secret_values,
            )
            self._close_scope(state, scope, frame.ts, level, message, payload_output)
            state.finished_nodes.add(frame.node_id)
            return
        self._event(state, frame, details, parent=self._scope(state, frame, details))

    def _handle_actor(
        self, state: _RunState, frame: FrameData, details: Mapping[str, Any]
    ) -> None:
        """A task or agent boundary, closed by identity rather than by class.

        The frame pipeline gives an agent execution, a task and a crew kickoff
        the same frame kind, and tells them apart only by which identity fields
        CrewAI stamped on them. So the rule here reads the identity and not the
        shape: an ending frame closes the INNERMOST open span whose identity it
        names. CrewAI raises the agent's completion before the task's, so the
        first ending frame closes the agent and the second closes the task,
        without either being named anywhere.
        """

        stage = str(details.get("stage") or "")
        agent_key = str(details.get("agent_id") or details.get("agent_role") or "")
        task_key = str(details.get("task_id") or details.get("task_name") or "")
        parent = self._scope(state, frame, details)
        if stage not in ("after", "error"):
            # An opening frame that named an actor has already been recorded -
            # `_scope` opened the span it describes, and a second EVENT saying
            # the same thing would double every agent in the tree. One that
            # named nobody (a crew-level start) has nowhere else to go.
            if not (agent_key or task_key):
                self._event(state, frame, details, parent=parent)
            return

        scope = state.nodes.get(frame.node_id)
        level = _LEVELS.get(frame.level, _DEFAULT)
        message = None
        if stage == "error" or level == _ERROR:
            level = _ERROR
            message = self._safe(details.get("error")) or "the step failed"
        payload_output = content_or_description(
            details.get("output"),
            capture=self.policy.capture_content,
            prefix="output",
            secret_values=self.policy.secret_values,
        )
        if scope is None:
            return
        if agent_key and scope.agent is not None and scope.agent_key == agent_key:
            self._close_span(state, scope.agent, frame.ts, level, message, payload_output)
            scope.agent = None
            scope.agent_key = ""
            return
        if task_key and scope.task is not None and scope.task_key == task_key:
            self._close_task(state, scope, frame.ts, level, message)
            return
        self._event(state, frame, details, parent=parent)

    def _handle_generation(
        self, state: _RunState, frame: FrameData, details: Mapping[str, Any]
    ) -> None:
        stage = str(details.get("stage") or "")
        call_id = str(details.get("call_id") or f"seq-{frame.seq}")
        parent = self._scope(state, frame, details)
        model = str(details.get("model") or "unknown")

        if stage == "before":
            self._open_generation(state, frame, details, call_id, parent, model)
            return

        generation = state.generations.get(call_id)
        if generation is None:
            generation = self._open_generation(
                state, frame, details, call_id, parent, model
            )
        if generation is None:
            return
        if stage == "error":
            generation.end = frame.ts
            generation.level = _ERROR
            generation.status_message = (
                self._safe(details.get("error")) or "the model call failed"
            )
            # A failed call carries no provider generation id - CrewAI's failure
            # event has no field for one - so there is nothing to resolve and
            # nothing to wait for.
            self._complete_generation(state, generation)
            return
        if stage == "after":
            generation.end = frame.ts
            generation.metadata["finish_reason"] = details.get("finish_reason")
            generation.response_id = details.get("response_id") or None
            generation.metadata["response_id"] = generation.response_id
            generation.awaiting_usage_since = monotonic()
            return
        self._event(state, frame, details, parent=parent)

    def _open_generation(
        self,
        state: _RunState,
        frame: FrameData,
        details: Mapping[str, Any],
        call_id: str,
        parent: Any,
        model: str,
    ) -> _Generation | None:
        scope = state.nodes.get(frame.node_id)
        task_span = scope.task if scope is not None else None
        counter = task_span if task_span is not None else (scope.span if scope else None)
        attempt = 1
        if counter is not None:
            counter.generations += 1
            attempt = counter.generations
        metadata = self._base_metadata(state, frame, details)
        metadata.update(
            {
                "call_id": call_id,
                "attempt": attempt,
                "cost_source": "app-estimate",
                "observation_role": "generation",
            }
        )
        metadata.update(self._prompt_facts(frame, details, model))
        handle = self._call(
            state,
            "open_child",
            parent,
            name=model,
            as_type=TYPE_GENERATION,
            metadata=metadata,
            model=model,
        )
        if handle is None:
            return None
        generation = _Generation(
            handle=handle,
            call_id=call_id,
            model=model,
            start=frame.ts,
            metadata=metadata,
            task_span=task_span,
        )
        state.generations[call_id] = generation
        return generation

    def _prompt_facts(
        self, frame: FrameData, details: Mapping[str, Any], model: str
    ) -> dict[str, Any]:
        """Which prompt this call made, without the prompt (row B5).

        The fingerprint is computed by the FRAME SERIALIZER, off
        `LLMCallStartedEvent.messages`, and copied here. That division is the
        contract's (section 4) and it is the only one that can work: the
        messages exist on the CrewAI event and nowhere downstream of it, so an
        exporter reading frames cannot hash something no frame carries.

        What this used to do instead was hash the IDENTITY -
        `node|agent_role|task_name|model` - which is honest about itself and
        useless for the question: it is constant across every call an agent
        makes on a task and across every revision of the prompt, so two
        different prompts hash identically and B5's "which prompt produced this
        bad output" has the same answer for all of them. It survives as the
        FALLBACK, for a frame that carries no fingerprint - the no-cost
        doubles' before-frame is one - and `prompt_fingerprint_basis` says
        which of the two a reader is looking at, so a fallback can never be
        mistaken for the real thing.
        """

        carried = details.get("prompt_fingerprint")
        if isinstance(carried, str) and carried:
            facts: dict[str, Any] = {
                "prompt_fingerprint": self._safe(carried, limit=128),
                "prompt_fingerprint_basis": "messages",
            }
            for name in ("message_count", "prompt_chars"):
                value = details.get(name)
                try:
                    facts[name] = int(value)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    facts[name] = None
            return facts
        return {
            "prompt_fingerprint": fingerprint(
                [
                    frame.node_id,
                    str(details.get("agent_role") or ""),
                    str(details.get("task_name") or ""),
                    model,
                ]
            ),
            "prompt_fingerprint_basis": "node|agent_role|task_name|model",
            # Present-and-null rather than absent: the contract says these are
            # sent "always", and a reader who finds the key missing cannot tell
            # a call with no prompt facts from an exporter that forgot them.
            "message_count": None,
            "prompt_chars": None,
        }

    def _complete_generation(self, state: _RunState, generation: _Generation) -> None:
        """The call is over: resolve its billed cost if there is one to resolve.

        Deliberately BEFORE the end and not after it. A span cannot be revised
        once ended on this transport, so an update afterwards would land
        nowhere; and the lookup runs on a pool because it takes about half a
        second, which on the frame-processing thread would push every later
        span's start time out by that much.
        """

        generation.awaiting_usage_since = None
        if generation.closed or generation.lookup is not None:
            return
        if (
            self._pool is not None
            and generation.response_id
            and state.counters["lookup_ok"] + state.counters["lookup_failed"]
            < self.policy.max_billed_lookups_per_run
        ):
            response_id = generation.response_id
            try:
                generation.lookup = self._pool.submit(
                    self._cost_lookup.lookup, response_id
                )
                generation.lookup_deadline = (
                    monotonic() + self.policy.billed_lookup_deadline_seconds
                )
                return
            except Exception:
                generation.lookup = None
        self._end_generation(state, generation)

    def _end_generation(self, state: _RunState, generation: _Generation) -> None:
        if generation.closed:
            return
        generation.closed = True
        metadata = dict(generation.metadata)
        metadata["completion_chars"] = generation.completion_chars
        metadata["stream_chunks"] = generation.stream_chunks
        payload_output = None
        if self.policy.capture_content and generation.completion_text:
            payload_output = content_or_description(
                generation.completion_text,
                capture=True,
                prefix="output",
                secret_values=self.policy.secret_values,
            )
        cost_details = (
            {"total": float(generation.cost_usd)}
            if generation.cost_usd is not None
            else None
        )
        if not self.policy.emit_successful_generations and generation.level == _DEFAULT:
            # SUPPLEMENT mode: the provider-side integration owns the successful
            # calls and this exporter owns only the failures. One boolean, and
            # this is the only place it is read.
            self._call(
                state, "end", generation.handle, end_ns=transport.nanoseconds(
                    generation.end or generation.start
                )
            )
            return
        self._call(
            state,
            "update",
            generation.handle,
            metadata=metadata,
            payload_output=payload_output,
            level=None if generation.level == _DEFAULT else generation.level,
            status_message=generation.status_message,
            usage_details=generation.usage or None,
            cost_details=cost_details,
        )
        self._call(
            state,
            "end",
            generation.handle,
            end_ns=transport.nanoseconds(generation.end or generation.start),
        )

    def _handle_fold(
        self, state: _RunState, frame: FrameData, details: Mapping[str, Any]
    ) -> None:
        """A fact about an observation, put onto that observation."""

        if frame.kind is FrameKind.EDGE_TAKEN:
            scope = state.nodes.get(frame.node_id) or self._node_scope(
                state, frame, details
            )
            if scope is not None:
                scope.span.metadata["entered_from"] = self._safe_or_none(
                    details.get("from"), limit=256
                )
                scope.span.metadata["entered_by_port"] = self._safe_or_none(
                    details.get("port"), limit=256
                )
            return
        if frame.kind is FrameKind.VERDICT:
            if state.run_span is not None:
                state.run_span.metadata["computed_result"] = policy_details(
                    details,
                    capture=self.policy.capture_content,
                    secret_values=self.policy.secret_values,
                )
            return
        if frame.kind is FrameKind.REASONING:
            scope = state.nodes.get(frame.node_id)
            target = None
            if scope is not None:
                target = scope.agent or scope.task or scope.span
            if target is not None:
                target.metadata["reasoning_steps"] = (
                    int(target.metadata.get("reasoning_steps", 0)) + 1
                )
            return

        call_id = str(details.get("call_id") or "")
        stage = str(details.get("stage") or "")
        generation = state.generations.get(call_id) if call_id else None

        if frame.kind is FrameKind.TOKEN:
            if generation is None:
                parent = self._scope(state, frame, details)
                generation = self._open_generation(
                    state,
                    frame,
                    details,
                    call_id or f"seq-{frame.seq}",
                    parent,
                    str(details.get("model") or "unknown"),
                )
                if generation is None:
                    return
                generation.end = frame.ts
            usage = dict(details.get("usage") or {})
            generation.usage.update(_usage_details(usage))
            cost = usage.get("cost_usd", details.get("cost_usd"))
            generation.cost_usd = None if cost is None else float(cost)
            generation.end = generation.end or frame.ts
            self._complete_generation(state, generation)
            return

        if generation is None:
            # A streamed or spoken fragment for a call this exporter never saw
            # opened. It is still not dropped: it becomes an EVENT.
            self._event(state, frame, details, parent=self._scope(state, frame, details))
            return
        if stage == "chunk":
            generation.stream_chunks += 1
            return
        if stage == "utterance":
            text = str(details.get("text") or "")
            # The TRUE length, not the frame's. `text` is cut to
            # `MAX_UTTERANCE_CHARS` by the serializer, so `len(text)` reports
            # the ceiling rather than the answer for any completion that
            # reached it - and `completion_chars` is the field row B5 uses to
            # tell a truncated answer from a short one. `text_chars` is the
            # serializer's own count before its cut; `truncated` says whether
            # the two differ.
            generation.completion_chars = _as_int(
                details.get("text_chars"), default=len(text)
            )
            generation.completion_text = text
            return
        self._event(state, frame, details, parent=self._scope(state, frame, details))

    def _handle_tool(
        self, state: _RunState, frame: FrameData, details: Mapping[str, Any]
    ) -> None:
        stage = str(details.get("stage") or "")
        tool = str(details.get("tool") or "tool")
        parent = self._scope(state, frame, details)
        key = f"{frame.node_id}::{tool}"

        metadata = self._base_metadata(state, frame, details)
        extra = {
            name: details[name]
            for name in ("tool_status", "result_count", "query", "from_cache", "notes", "run_attempts")
            if details.get(name) is not None
        }
        metadata.update(
            policy_details(
                extra,
                capture=self.policy.capture_content,
                secret_values=self.policy.secret_values,
            )
        )

        if stage == "before":
            span = self._open_span(
                state,
                parent,
                name=tool,
                as_type=TYPE_TOOL,
                role="tool",
                start=frame.ts,
                metadata=metadata,
                payload_input=content_or_description(
                    details.get("args"),
                    capture=self.policy.capture_content,
                    prefix="arg",
                    secret_values=self.policy.secret_values,
                ),
            )
            if span is not None:
                state.tools[key] = span
            return

        span = state.tools.pop(key, None)
        if span is None:
            # A result with no start - a tool whose start frame was dropped by
            # the ring, or an error raised before the call was recorded. It is
            # a span of its own with the only start time there is.
            span = self._open_span(
                state,
                parent,
                name=tool,
                as_type=TYPE_TOOL,
                role="tool",
                start=frame.ts,
                metadata=metadata,
            )
            if span is None:
                return
            span.metadata.update(metadata)
        else:
            # The OPENING frame's identity survives the closing one. Contract
            # section 3 says `frame_seq` is "the sequence number of the frame
            # that OPENED the observation - for a TOOL that is the `before`
            # frame, never the `after`", and a blanket update overwrote exactly
            # those keys with the after frame's. Measured on a live export: a
            # tool span whose `startTime` was 19.729 carried `frame_ts` 21.728,
            # so `frame_ts` contradicted the span's own start by the tool's
            # entire duration and a reader who joined frames to spans on
            # `frame_seq` got the wrong frame.
            span.metadata.update(
                {
                    key: value
                    for key, value in metadata.items()
                    if key not in _OPENING_FRAME_KEYS
                }
            )
        level = _LEVELS.get(frame.level, _DEFAULT)
        message = None
        if stage == "error" or level == _ERROR:
            level = _ERROR
            message = self._safe(details.get("error")) or "the tool failed"
        elif details.get("failure"):
            level = _WARNING
            message = self._safe(details.get("failure"))
        payload_output = content_or_description(
            details.get("output_preview"),
            capture=self.policy.capture_content,
            prefix="output",
            secret_values=self.policy.secret_values,
        )
        self._close_span(state, span, frame.ts, level, message, payload_output)

    def _handle_score(
        self, state: _RunState, frame: FrameData, details: Mapping[str, Any]
    ) -> None:
        """`guardrail_passed` on the task span, falling back outwards.

        The check itself is not an observation. It is a fact about the task it
        checked, and a score is what makes a pass rate chartable over time -
        which is what row B6 asks for and an EVENT would not give.
        """

        if str(details.get("stage") or "") != "after":
            return
        scope = state.nodes.get(frame.node_id)
        target = None
        if scope is not None:
            target = scope.task or scope.agent or scope.span
        self._call(
            state,
            "score",
            observation=target.handle if target is not None else None,
            trace_id=state.trace_id,
            name="guardrail_passed",
            value=1 if bool(details.get("success")) else 0,
        )

    def _event(
        self,
        state: _RunState,
        frame: FrameData,
        details: Mapping[str, Any],
        *,
        parent: Any,
    ) -> None:
        """The catch-all, and the reason nothing is ever dropped (C3)."""

        metadata = self._base_metadata(state, frame, details)
        metadata["observation_role"] = "event"
        metadata["details"] = policy_details(
            dict(details),
            capture=self.policy.capture_content,
            secret_values=self.policy.secret_values,
        )
        level = _LEVELS.get(frame.level, _DEFAULT)
        self._call(
            state,
            "event",
            parent,
            name=_event_name(frame, details, self.policy.secret_values),
            metadata=metadata,
            level=None if level == _DEFAULT else level,
            status_message=(
                self._safe(details.get("error") or frame.message)
                if level == _ERROR
                else None
            ),
        )

    # ------------------------------------------------------------------
    # The self-report
    # ------------------------------------------------------------------

    def _summary(self, state: _RunState) -> dict[str, Any]:
        counters = dict(state.counters)
        counters["http_errors"] += max(
            0, self._transport_failures() - state.transport_failures_at_open
        )
        counters["enqueue_p50_us"] = _percentile(state.latencies, 0.50) // 1000
        counters["enqueue_p95_us"] = _percentile(state.latencies, 0.95) // 1000
        counters["run_id"] = state.facts.run_id
        counters["trace_id"] = state.trace_id
        counters["environment"] = self.policy.environment
        counters["terminal"] = state.terminal
        return counters

    def _log_summary(self, state: _RunState) -> None:
        """One line per run, in the format the reconciliation tooling parses."""

        if state.summary_logged:
            return
        state.summary_logged = True
        summary = self._summary(state)
        summary_logger.warning(
            SUMMARY_FORMAT,
            summary["run_id"],
            summary["frames_enqueued"],
            summary["frames_dropped"],
            summary["observations_sent"],
            summary["http_errors"],
            summary["lookup_ok"],
            summary["lookup_failed"],
            summary["enqueue_p50_us"],
            summary["enqueue_p95_us"],
        )
        self._finished.append((state.facts.run_id, summary))
        # The state stays reachable for a re-delivered frame; only the facts
        # are released, and only once nothing can need them.
        with self._facts_lock:
            self._facts.pop(state.facts.run_id, None)


def _as_int(value: Any, *, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _usage_details(usage: Mapping[str, Any]) -> dict[str, int]:
    """The frame's token counts in Langfuse's own names.

    `prompt`/`completion` are this application's spelling and `input`/`output`
    are Langfuse's. The cached and reasoning splits are NOT here: the frame
    serializer's usage normalisation whitelists five ordinary counts and drops
    those two, so they can only come from the provider's own record and are
    filled in by the billed-cost resolution.
    """

    mapped = {
        "input": usage.get("prompt_tokens"),
        "output": usage.get("completion_tokens"),
        "total": usage.get("total_tokens"),
    }
    out: dict[str, int] = {}
    for name, value in mapped.items():
        try:
            if value is None:
                continue
            out[name] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def _event_name(
    frame: FrameData, details: Mapping[str, Any], secret_values: Sequence[str] = ()
) -> str:
    """What an EVENT observation is called.

    A gate carries its own id, because "which gate" is the question a reader
    has. Everything else is named after the frame's own `event_type`, which is
    the contract's wording for the case this exporter does not recognise - and
    by now that case is the only one left, because every kind it does
    recognise has become a span, a generation, a score or a field.

    The gate id is scrubbed on the way into the name. It is the only part of an
    observation NAME that comes from a frame's free-form details rather than
    from the frame vocabulary, and a name is the one field a console shows
    before anybody clicks anything.
    """

    gate_id = details.get("gate_id")
    if gate_id:
        return f"gate:{safe_message(gate_id, secret_values, limit=96)}"
    if frame.kind in (
        FrameKind.GATE_OPEN,
        FrameKind.GATE_CLOSED,
        FrameKind.GATE_EXPIRED,
        FrameKind.GATE_ALERT,
    ):
        return "gate"
    return frame.event_type.value
