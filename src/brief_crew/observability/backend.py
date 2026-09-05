"""The transport: the Langfuse SDK's OTLP path, behind one small seam.

Why the SDK and not the ingestion API
-------------------------------------
`POST /api/public/ingestion` takes explicit ids, explicit start AND end times
and accepts updates to an observation already written - everything this
contract asks for, expressed directly. **It is sunset on 2026-11-16.** Building
on it would mean shipping instrumentation with a known expiry date, so this
uses `langfuse` 4.15.1's OpenTelemetry client instead, and the three things that
costs are stated here rather than discovered later:

1. **A span's START time is the moment it is created**, because
   `start_observation()` takes no `start_time`. The exporter therefore drains
   its queue on a short interval so that a span begins within tens of
   milliseconds of the frame that opened it, and EVERY observation carries
   `metadata.frame_ts` - the frame's own timestamp, exact, from the app's
   clock. Row B4 tolerates a second; this is two orders inside that, and the
   exact figure is on the observation for anyone who wants it.
2. **A span's END time is explicit** (`end(end_time=<nanoseconds>)`), so
   durations are the app's own and not the exporter's.
3. **A span cannot be revised once ended.** That is what moves the billed-cost
   resolution to BEFORE the end rather than after it: the exporter holds a
   generation open, resolves the provider's own figure on a small pool, updates
   `cost_details` and `usage_details`, and only then ends it with the frame's
   timestamp. See `langfuse_exporter._settle`.

The trace id
------------
Computable off-line from the run id, two ways and in this order:

* a run id is a uuid4 in this application, so `UUID(run_id).hex` IS a valid
  32-hex trace id and is the one used - `uuid.UUID("<run id>").hex`;
* anything that does not parse as a UUID falls back to the SDK's own seeded
  derivation, `Langfuse.create_trace_id(seed=run_id)`, which is
  `sha256(seed)[:16].hex()` and is re-derived here when the SDK is absent.

Both are pure functions of the run id, so a reader with a run id can compute
the trace id without asking this process anything.

Counting what the SDK sends
---------------------------
The OTLP exporter runs on its own thread inside the SDK and reports success or
failure to nobody. A run whose backend was unreachable would therefore report
`http_errors=0`, which is worse than saying nothing. `TransportFailureCounter`
attaches a logging handler to the two loggers that carry those failures and
counts them, so a black-hole host shows up in the run summary as what it is.
It is a global count sampled per run: with `RUN_CONCURRENCY` at its default of
1 that is exact, and with runs overlapping it is a bound rather than an
attribution. The alternative - reconstructing the SDK's own endpoint and
headers to wrap its exporter - would duplicate SDK internals that move between
versions.
"""

from __future__ import annotations

import atexit
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import logging
import threading
from typing import Any, Protocol
from uuid import UUID


logger = logging.getLogger(__name__)


#: The observation types the SDK understands that this exporter uses. `tool`
#: and `agent` are real types here, so the contract's fallback ("a SPAN with
#: metadata.observation_role = tool") is not needed - but the metadata key is
#: written anyway, on every span, because grouping by it is how a per-agent and
#: a per-task table get built without knowing any role or task name.
TYPE_SPAN = "span"
TYPE_GENERATION = "generation"
TYPE_TOOL = "tool"
TYPE_AGENT = "agent"


def trace_id_for(run_id: str) -> str:
    """The 32-hex Langfuse trace id for an app run id. See the module docstring."""

    try:
        return UUID(str(run_id)).hex
    except (ValueError, AttributeError, TypeError):
        pass
    try:
        from langfuse import Langfuse

        return str(Langfuse.create_trace_id(seed=run_id))
    except Exception:
        return sha256(str(run_id).encode("utf-8")).digest()[:16].hex()


def nanoseconds(moment: datetime) -> int:
    """A frame timestamp as OpenTelemetry wants an end time.

    A naive datetime is read as UTC rather than refused: this runs on the
    export thread, and telemetry that raises on a clock is the failure mode the
    whole package exists to avoid.
    """

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp() * 1_000_000_000)


def iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


# --------------------------------------------------------------------------
# The seam
# --------------------------------------------------------------------------


class Observation(Protocol):
    """Whatever the backend hands back for one observation."""


class Backend(Protocol):
    """Everything the exporter can ask a backend to do. Nine verbs, no more."""

    def open_run(
        self,
        *,
        trace_id: str,
        name: str,
        metadata: dict[str, Any],
        user_id: str,
        session_id: str,
        tags: list[str],
        payload_input: Any,
    ) -> Any: ...

    def open_child(
        self,
        parent: Any,
        *,
        name: str,
        as_type: str,
        metadata: dict[str, Any],
        payload_input: Any = None,
        model: str | None = None,
    ) -> Any: ...

    def update(self, observation: Any, **fields: Any) -> None: ...

    def end(self, observation: Any, *, end_ns: int) -> None: ...

    def event(
        self,
        parent: Any,
        *,
        name: str,
        metadata: dict[str, Any],
        level: str | None = None,
        status_message: str | None = None,
        payload_output: Any = None,
    ) -> None: ...

    def score(
        self,
        *,
        observation: Any,
        trace_id: str,
        name: str,
        value: Any,
        data_type: str | None = None,
    ) -> None: ...

    def set_trace_output(self, run_observation: Any, payload_output: Any) -> None: ...

    def transport_failures(self) -> int: ...

    def flush(self) -> bool: ...

    def close(self) -> None: ...


# --------------------------------------------------------------------------
# The recording backend - the only one any test builds
# --------------------------------------------------------------------------


@dataclass
class RecordedObservation:
    """One observation as the tests read it.

    Deliberately the exporter's whole output surface: a test asserts over these
    fields rather than over a JSON wire format, so the assertions survive the
    transport being replaced - which, given why this file exists, is not a
    hypothetical.
    """

    ident: str
    trace_id: str
    name: str
    as_type: str
    parent: "RecordedObservation | None" = None
    metadata: dict[str, Any] = field(default_factory=dict)
    payload_input: Any = None
    payload_output: Any = None
    level: str | None = None
    status_message: str | None = None
    model: str | None = None
    usage_details: dict[str, int] | None = None
    cost_details: dict[str, float] | None = None
    end_ns: int | None = None
    ended: bool = False
    user_id: str | None = None
    session_id: str | None = None
    tags: list[str] = field(default_factory=list)
    #: The TRACE's name, which is not the observation's. The real backend calls
    #: the root observation "run" and lifts the workflow id onto the trace as an
    #: attribute; a double that put the workflow id on the span instead would
    #: teach a test a shape production never produces.
    trace_name: str | None = None

    @property
    def parent_id(self) -> str | None:
        return self.parent.ident if self.parent is not None else None


@dataclass
class RecordedScore:
    trace_id: str
    observation_id: str | None
    name: str
    value: Any
    data_type: str | None = None


class RecordingBackend:
    """An in-memory backend. No network, no SDK, no global tracer provider."""

    def __init__(self, *, fail_with: BaseException | None = None) -> None:
        self.observations: list[RecordedObservation] = []
        self.scores: list[RecordedScore] = []
        self.trace_output: dict[str, Any] = {}
        self.flushes = 0
        self.closed = False
        self.fail_with = fail_with
        self._failures = 0
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"obs{self._counter:04d}"

    def _guard(self) -> None:
        if self.fail_with is not None:
            self._failures += 1
            raise self.fail_with

    def open_run(
        self,
        *,
        trace_id: str,
        name: str,
        metadata: dict[str, Any],
        user_id: str,
        session_id: str,
        tags: list[str],
        payload_input: Any,
    ) -> RecordedObservation:
        self._guard()
        observation = RecordedObservation(
            ident=self._next_id(),
            trace_id=trace_id,
            name="run",
            as_type=TYPE_SPAN,
            metadata=dict(metadata),
            payload_input=payload_input,
            user_id=user_id,
            session_id=session_id,
            tags=list(tags),
            trace_name=name,
        )
        self.observations.append(observation)
        return observation

    def open_child(
        self,
        parent: Any,
        *,
        name: str,
        as_type: str,
        metadata: dict[str, Any],
        payload_input: Any = None,
        model: str | None = None,
    ) -> RecordedObservation:
        self._guard()
        observation = RecordedObservation(
            ident=self._next_id(),
            trace_id=parent.trace_id if parent is not None else "",
            name=name,
            as_type=as_type,
            parent=parent,
            metadata=dict(metadata),
            payload_input=payload_input,
            model=model,
        )
        self.observations.append(observation)
        return observation

    def update(self, observation: Any, **fields: Any) -> None:
        self._guard()
        for key, value in fields.items():
            if value is None:
                continue
            if key == "metadata":
                observation.metadata.update(value)
            else:
                setattr(observation, key, value)

    def end(self, observation: Any, *, end_ns: int) -> None:
        self._guard()
        observation.end_ns = end_ns
        observation.ended = True

    def event(
        self,
        parent: Any,
        *,
        name: str,
        metadata: dict[str, Any],
        level: str | None = None,
        status_message: str | None = None,
        payload_output: Any = None,
    ) -> None:
        self._guard()
        observation = RecordedObservation(
            ident=self._next_id(),
            trace_id=parent.trace_id if parent is not None else "",
            name=name,
            as_type="event",
            parent=parent,
            metadata=dict(metadata),
            level=level,
            status_message=status_message,
            payload_output=payload_output,
            ended=True,
        )
        self.observations.append(observation)

    def score(
        self,
        *,
        observation: Any,
        trace_id: str,
        name: str,
        value: Any,
        data_type: str | None = None,
    ) -> None:
        self._guard()
        self.scores.append(
            RecordedScore(
                trace_id=trace_id,
                observation_id=getattr(observation, "ident", None),
                name=name,
                value=value,
                data_type=data_type,
            )
        )

    def set_trace_output(self, run_observation: Any, payload_output: Any) -> None:
        self._guard()
        self.trace_output[run_observation.trace_id] = payload_output

    def transport_failures(self) -> int:
        return self._failures

    def flush(self) -> bool:
        self.flushes += 1
        return True

    def close(self) -> None:
        self.closed = True


# --------------------------------------------------------------------------
# Counting what the SDK's own exporter could not tell us
# --------------------------------------------------------------------------

#: The two loggers that carry an export failure: the OTLP HTTP exporter's own,
#: and the SDK's. Both are package roots, so a sub-logger is covered.
_FAILURE_LOGGERS = ("opentelemetry.exporter", "langfuse")


class TransportFailureCounter(logging.Handler):
    """Counts WARNING-and-worse records from the SDK's export path.

    A handler rather than a wrapped exporter: see the module docstring. It
    never re-raises, never formats a record it does not need, and holds a lock
    only around an integer.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self._lock_ = threading.Lock()
        self._count = 0
        self._attached: list[logging.Logger] = []

    def attach(self) -> None:
        for name in _FAILURE_LOGGERS:
            target = logging.getLogger(name)
            target.addHandler(self)
            self._attached.append(target)

    def detach(self) -> None:
        for target in self._attached:
            try:
                target.removeHandler(self)
            except Exception:  # pragma: no cover - removing twice is harmless
                pass
        self._attached = []

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock_:
            self._count += 1

    @property
    def count(self) -> int:
        with self._lock_:
            return self._count


# --------------------------------------------------------------------------
# The real backend
# --------------------------------------------------------------------------


def _detach_fabricated_parent(observation: Any) -> None:
    """Make the run span a real root, which the SDK will not do on its own.

    Contract section 1: *the `run` SPAN is the root: it has NO parent
    observation*. Asking the SDK for a span in a chosen trace is the only way
    to fix the trace id, and it is exactly that request which invents a parent:
    `Langfuse._create_remote_parent_span` (`_client/client.py:1750-1753`,
    4.15.1) generates a **random span id** when `trace_context` carries a
    `trace_id` and no `parent_span_id`, and `start_observation` then starts our
    span inside that non-recording context. The span it marks
    `langfuse.internal.as_root` is exported with
    `parent_span_id = format_span_id(span.parent.span_id)`
    (`span_exporter.py:526`, `:681-685`) all the same.

    Measured consequence, and the reason this exists rather than trusting the
    flag: in a live export the run span came back from
    `/api/public/observations` with `parentObservationId` naming an id that no
    observation in the trace carries, so **zero** observations had a null
    parent and a hierarchy walk reported the whole tree ORPHANED.

    The fix is to drop the parent AFTER the span exists, which is the one
    moment at which that is free: the trace id has already been copied out of
    the parent context into `span.context` by `Tracer.start_span`, and
    `ReadableSpan.parent` is read only at export time (`Span._readable_span`,
    `opentelemetry/sdk/trace/__init__.py:947-951`). Total: an SDK that changes
    shape leaves the span exactly as it was rather than raising into a run.
    """

    try:
        span = observation._otel_span
    except Exception:  # pragma: no cover - an SDK without the private attribute
        return
    try:
        if getattr(span, "_parent", None) is not None:
            span._parent = None
    except Exception:  # pragma: no cover - a span type that forbids the write
        return


def _bounded(call: Any, *, timeout: float, what: str) -> bool:
    """Run a call that may never return, and return to the caller anyway.

    Every wait in this package is bounded except the ones inside the SDK, and
    those are the ones that hang: `Langfuse.flush()` and `Langfuse.shutdown()`
    both end at `LangfuseResourceManager.flush()`, whose last statement is
    `self._score_ingestion_queue.join()` (`resource_manager.py:631`).
    `queue.Queue.join()` takes no timeout and returns only when a consumer
    thread calls `task_done()` often enough - so an unreachable host, or a
    consumer thread that is no longer running, holds the caller forever.

    The caller here is not a test. It is `service/app.py`'s lifespan shutdown
    and, through the SDK's own `atexit` registration, interpreter exit. Row E2
    says a Langfuse that is down must not affect the application, and a process
    that cannot exit is the largest possible way of affecting it.

    The worker is a daemon thread so that a call still running when the last
    non-daemon thread finishes cannot keep the interpreter alive either.
    """

    done = threading.Event()

    def _work() -> None:
        try:
            call()
        except Exception:  # noqa: BLE001 - a closing path must never raise
            logger.debug("the langfuse backend raised during %s", what, exc_info=True)
        finally:
            done.set()

    worker = threading.Thread(
        target=_work, name=f"langfuse-{what}", daemon=True
    )
    worker.start()
    if done.wait(timeout):
        return True
    logger.warning("the langfuse backend did not %s within %ss", what, timeout)
    return False


def _evict_resource_manager(public_key: str) -> None:
    """Drop this key's SDK resource manager from the SDK's process-wide cache.

    `LangfuseResourceManager.__new__` returns a cached instance keyed on the
    public key (`resource_manager.py:137-138`) and `shutdown()` pauses and joins
    that instance's score-ingestion consumer threads **without removing it from
    the cache** (`:639-644`); only the separate `reset()` clears it (`:486-491`).

    So a second client built with the same public key in one process inherits a
    manager whose consumer threads are dead, nothing ever calls `task_done()`
    again, and the next `flush()` blocks forever on the unbounded join above.
    That is not a test-only shape: one process that closes an exporter and
    builds another - a reconfiguration, a second `create_app`, a suite - meets
    it, and the second exporter is then silently unable to send anything while
    holding whoever closes it.

    Measured by V-REVIEW on dead ports both ways: without the eviction the
    second client's flush never returned; with it, flush 5.62s, close 0.00s.

    The SDK's own `atexit.register(self.shutdown)` (`:279`) is unregistered in
    the same breath, because that handler is the same unbounded join with no
    caller left to bound it. Unregistering costs nothing when the shutdown
    already succeeded - the queue is empty and the join would return at once -
    and is the whole difference between a clean exit and a wedged one when it
    did not.
    """

    try:
        from langfuse._client.resource_manager import LangfuseResourceManager
    except Exception:  # pragma: no cover - an SDK that moved this module
        return
    try:
        with LangfuseResourceManager._lock:
            manager = LangfuseResourceManager._instances.pop(public_key, None)
    except Exception:  # pragma: no cover - an SDK without that cache
        return
    if manager is None:
        return
    try:
        atexit.unregister(manager.shutdown)
    except Exception:  # pragma: no cover - unregister is total in practice
        pass


class LangfuseBackend:
    """The Langfuse SDK, with trace-level fields written as OTel attributes.

    Trace-level values - name, owner, session, tags, metadata, input, output -
    are not span fields in this SDK; they are attributes the backend lifts off
    whichever span carries them. The SDK's own `propagate_attributes` sets them
    through an OpenTelemetry *context*, which cannot be used here: every span
    is created on one export thread shared by every concurrent run, and a
    context entered for one run would leak into the next. They are therefore
    set directly on the run's root span, under the attribute names
    `langfuse._client.propagation` maps to (`_get_propagated_span_key`), which
    is the same mapping the SDK's own context route ends at.
    """

    def __init__(
        self,
        *,
        public_key: str,
        secret_key: str,
        base_url: str,
        environment: str,
        flush_interval: float,
        flush_at: int,
        timeout: float,
    ) -> None:
        from langfuse import Langfuse

        self._failures = TransportFailureCounter()
        self._failures.attach()
        self._public_key = public_key
        # Every bound in this class is derived from the one timeout the
        # contract already gives the transport (section 9: "small (<= 5)"), so
        # there is no second knob to keep in step with it.
        #
        # The MULTIPLES are measured, not chosen. Against a port nothing is
        # listening on with `timeout=1`, the SDK's OTLP exporter retries and
        # its first failure record appears at **2.25 s** - so a flush bounded
        # at the bare request timeout returns BEFORE the transport has failed,
        # and `TransportFailureCounter` has nothing to count yet. The summary
        # line then reports `http_errors=0` for a backend nothing was listening
        # on, which is the exact lie row E2 exists to forbid. Three times the
        # request timeout clears that; a close gets twice it, because a close
        # follows a flush and is allowed to wait for one in-flight batch and no
        # longer.
        self._flush_timeout = max(3.0, float(timeout) * 3)
        self._close_timeout = max(2.0, float(timeout) * 2)
        self._client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            # `base_url=`, NOT `host=`, and the difference is not cosmetic.
            # The SDK resolves the host as
            # `base_url or os.environ["LANGFUSE_BASE_URL"] or host or
            # os.environ["LANGFUSE_HOST"] or the cloud default`
            # (`langfuse/_client/client.py:339-344`), so a `host=` argument is
            # SILENTLY OUTRANKED by the environment variable this project's
            # `.env` already sets. Measured while writing the fail-open tests:
            # a client built with `host=` pointed at a dead local port sent its
            # spans to the real project and came back `401`, which would have
            # made those tests certify nothing and could have put a test run's
            # traces in a live account.
            base_url=base_url,
            environment=environment,
            flush_interval=flush_interval,
            flush_at=flush_at,
            # The SDK takes whole seconds and hands the same figure to the OTLP
            # exporter AND to the batch processor's export timeout, so this one
            # number is what stops a black-hole host holding a shutdown.
            timeout=max(1, int(round(timeout))),
        )
        self._environment = environment

    # -- trace-level attributes -------------------------------------------

    @staticmethod
    def _set_trace_attributes(
        observation: Any,
        *,
        name: str,
        user_id: str,
        session_id: str,
        tags: list[str],
        metadata: dict[str, Any],
    ) -> None:
        from langfuse import LangfuseOtelSpanAttributes as Attr

        span = observation._otel_span
        span.set_attribute(Attr.TRACE_NAME, name)
        span.set_attribute(Attr.TRACE_USER_ID, user_id)
        span.set_attribute(Attr.TRACE_SESSION_ID, session_id)
        if tags:
            span.set_attribute(Attr.TRACE_TAGS, list(tags))
        for key, value in metadata.items():
            if value is None:
                continue
            span.set_attribute(
                f"{Attr.TRACE_METADATA}.{key}",
                value if isinstance(value, str) else str(value),
            )

    def open_run(
        self,
        *,
        trace_id: str,
        name: str,
        metadata: dict[str, Any],
        user_id: str,
        session_id: str,
        tags: list[str],
        payload_input: Any,
    ) -> Any:
        observation = self._client.start_observation(
            trace_context={"trace_id": trace_id},
            name="run",
            as_type=TYPE_SPAN,
            metadata=metadata,
            input=payload_input,
        )
        _detach_fabricated_parent(observation)
        self._set_trace_attributes(
            observation,
            name=name,
            user_id=user_id,
            session_id=session_id,
            tags=tags,
            metadata=metadata,
        )
        from langfuse import LangfuseOtelSpanAttributes as Attr

        if payload_input is not None:
            observation._otel_span.set_attribute(
                Attr.TRACE_INPUT, _as_json(payload_input)
            )
        return observation

    def open_child(
        self,
        parent: Any,
        *,
        name: str,
        as_type: str,
        metadata: dict[str, Any],
        payload_input: Any = None,
        model: str | None = None,
    ) -> Any:
        return parent.start_observation(
            name=name,
            as_type=as_type,
            metadata=metadata,
            input=payload_input,
            model=model,
        )

    def update(self, observation: Any, **fields: Any) -> None:
        payload = {
            "metadata": fields.get("metadata"),
            "output": fields.get("payload_output"),
            "input": fields.get("payload_input"),
            "level": fields.get("level"),
            "status_message": fields.get("status_message"),
            "model": fields.get("model"),
            "usage_details": fields.get("usage_details"),
            "cost_details": fields.get("cost_details"),
        }
        observation.update(**{k: v for k, v in payload.items() if v is not None})

    def end(self, observation: Any, *, end_ns: int) -> None:
        observation.end(end_time=end_ns)

    def event(
        self,
        parent: Any,
        *,
        name: str,
        metadata: dict[str, Any],
        level: str | None = None,
        status_message: str | None = None,
        payload_output: Any = None,
    ) -> None:
        parent.create_event(
            name=name,
            metadata=metadata,
            level=level,
            status_message=status_message,
            output=payload_output,
        )

    def score(
        self,
        *,
        observation: Any,
        trace_id: str,
        name: str,
        value: Any,
        data_type: str | None = None,
    ) -> None:
        self._client.create_score(
            name=name,
            value=value,
            trace_id=trace_id,
            observation_id=getattr(observation, "id", None),
            data_type=data_type,
            environment=self._environment,
        )

    def set_trace_output(self, run_observation: Any, payload_output: Any) -> None:
        from langfuse import LangfuseOtelSpanAttributes as Attr

        run_observation._otel_span.set_attribute(
            Attr.TRACE_OUTPUT, _as_json(payload_output)
        )

    def transport_failures(self) -> int:
        return self._failures.count

    def flush(self) -> bool:
        """Send what is queued, and come back either way.

        Returns whether the SDK's flush finished inside the bound. False is not
        an error the caller can act on - the batch is still being sent on the
        SDK's own threads - but it is the difference between a summary line
        that reports a clean export and one that does not.
        """

        return _bounded(self._client.flush, timeout=self._flush_timeout, what="flush")

    def close(self) -> None:
        """Bounded, and it leaves the SDK able to serve the NEXT backend.

        The eviction comes first on purpose. If the shutdown wedges, the bound
        below returns without it ever running, and a cache entry left behind
        would then hand the next exporter in this process a manager whose
        consumer threads are gone - the failure `_evict_resource_manager`
        describes, arrived at from the other direction.
        """

        try:
            _evict_resource_manager(self._public_key)
            _bounded(
                self._client.shutdown, timeout=self._close_timeout, what="shutdown"
            )
        finally:
            self._failures.detach()


def _as_json(value: Any) -> str:
    import json

    try:
        return json.dumps(value, default=str)[:65536]
    except Exception:  # pragma: no cover - default=str makes this unreachable
        return "null"
