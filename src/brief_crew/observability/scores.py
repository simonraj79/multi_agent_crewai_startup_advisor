"""A generic score hook: one score against one run's trace, after it closed.

Plan 18 section 2.2. `docs/observability/DEFINITION-OF-DONE.md` section 5.6
permits a flow's own metric to be scored *"through a declared, generic hook
later"*, and **the owner has now asked for this integration, so 5.6's
authorisation is given and this module is that hook.**

WHY THIS IS NOT A FRAME
-----------------------
Everything else this package exports is driven by the frame pipeline, which is
what makes it generic by construction. A rating cannot be: it arrives **after
the trace closed**, sometimes days later, from a person clicking a button on a
finished run. There is no frame to attach it to and inventing one would mean
reopening a run's export to carry a fact that is not about the run's
execution. So this is addressed by TRACE ID instead, and `trace_id_for` is
IMPORTED from `backend.py` rather than re-derived - a second derivation of the
same id is a second answer to "which trace is this run", and the two would
disagree the first time either changed. A12 proves the import by patching it.

IT NAMES NOTHING
----------------
No agent, no task, no tool, no crew, no flow, no workflow. The score's `name`
is the caller's, and the two this repository passes - `human_rating` and
`gate_outcome` - are facts about a run rather than about anything a particular
product does. `tests/observability/test_no_flow_identifiers.py` therefore
passes over this file **unmodified**, which is A13, and a planted identifier
still fails it.

IT CANNOT FAIL A CALLER
-----------------------
The package's own rule, stated in `observability/__init__.py`: *"it cannot fail
a run."* A rating is a person pressing a button, and telemetry must never be
the reason that button reports an error. Every path here is total, the work
happens on a bounded daemon worker, and the return value is a plain bool the
caller may ignore.

CONTENT
-------
`comment` is free text a person typed, so it is written **only when
`LANGFUSE_CAPTURE_CONTENT` is on**. The default is not a denylist: a note is
user content and the content policy's whole argument is that a new field
carrying text must fail closed rather than open.

A DELETE AND A CREATE ARE NOT ON THE SAME CLOCK
-----------------------------------------------
The one thing to know before changing anything below. `create_score` goes into
the SDK's **asynchronous batch queue**; `delete_score` is a **synchronous HTTP
call**. Issue both in one breath and the delete lands first, answers 404
against a score that does not exist yet, and the queued create arrives
afterwards and stays.

That is not theoretical - it was measured through the real route: four ratings
inside eight seconds left TWO scores on a trace permanently. The design that
produced it wrote good/bad under a NUMERIC id and `unsure` under a CATEGORICAL
one, deleting the loser on every write; a person correcting a misclick within
seconds is the commonest reason anybody re-rates, so the race was the main
path rather than an edge.

So **a write never deletes**. There is ONE score id per run, always
CATEGORICAL, and the value is the word itself - so every re-rating is an
upsert of the same id and rapid re-rating converges by last-write-wins with no
ordering assumption at all. The only delete is a CLEAR, and even that is
issued twice: once immediately and once on a deferred timer, because the
create it is chasing may still be in the queue.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import logging
import threading
from typing import Any

from brief_crew.observability.backend import trace_id_for

__all__ = [
    "RATING_SCORE_ID_SUFFIX",
    "SCORE_GATE_OUTCOME",
    "SCORE_HUMAN_RATING",
    "record_run_rating",
    "record_run_score",
    "set_score_exporter",
    "sweep_cleared_rating",
]

logger = logging.getLogger(__name__)

#: The two names this repository writes. Facts about a run - was it any good,
#: and did a person approve or send it back - and neither names a flow.
SCORE_HUMAN_RATING = "human_rating"
SCORE_GATE_OUTCOME = "gate_outcome"

#: THE score id a rating lives under, appended to the run's trace id.
#:
#: One id, and the reasoning is in the module docstring: `create_score` with
#: no id APPENDS, so an id is required to make a re-rating an edit - and TWO
#: ids raced, because the write that upserted one had to delete the other and
#: a synchronous delete overtakes a queued create.
#:
#: The score is therefore always **CATEGORICAL** and its value is the word
#: itself. That costs the mean a NUMERIC pair would have allowed and buys the
#: only property that matters here: every write is an upsert of one id with no
#: delete beside it, so four ratings a second apart converge on the last one
#: however the queue reorders them. Langfuse counts a categorical score by
#: value, which is the aggregate a three-word vocabulary actually wants.
RATING_SCORE_ID_SUFFIX = f"-{SCORE_HUMAN_RATING}"

#: The three words, and nothing else reaches Langfuse. `rating_api` owns the
#: vocabulary; this is the guard that a value which is not one of them is not
#: silently written as a score somebody would then try to count.
RATING_SCORE_VALUES: tuple[str, ...] = ("good", "bad", "unsure")

#: How long a caller may be kept waiting for a score to be handed to the SDK.
#: The SDK's own `create_score` is an enqueue, so this is a bound on a bound;
#: it exists because `close()` on the Langfuse client has been measured to
#: wedge (`langfuse_exporter` defect 1) and no path here may inherit that.
_WORKER_TIMEOUT_SECONDS = 2.0

#: The process's exporter, set beside `registry.frame_observer` in `app.py`.
#: A module global rather than an argument on every call because a rating
#: route holds a registry and not an exporter, and threading one through four
#: call sites to reach one object is how a second, quieter wiring starts.
_exporter: Any = None
_lock = threading.Lock()

#: One pending clear sweep per run id, so a second clear REPLACES the first
#: rather than queueing a second timer against the same score. Bounded, and
#: entries remove themselves when they fire: a dict of timers that only ever
#: grew would be a leak in the one module whose rule is that it cannot cost a
#: run anything.
_sweeps: dict[str, Any] = {}
_sweep_lock = threading.Lock()

#: The most pending sweeps this process will hold. Reaching it means somebody
#: is clearing ratings faster than the window, and the OLDEST is dropped -
#: losing a second delete on a score whose first delete very likely worked,
#: which is the cheapest thing on this page to lose.
_MAX_PENDING_SWEEPS = 256


def set_score_exporter(exporter: Any) -> None:
    """Point the hook at this process's exporter. Idempotent, never raises."""

    global _exporter
    with _lock:
        _exporter = exporter


def _current(exporter: Any = None) -> Any:
    if exporter is not None:
        return exporter
    with _lock:
        return _exporter


def record_run_score(
    run_id: str,
    *,
    name: str,
    value: Any = None,
    data_type: str | None = None,
    comment: str | None = None,
    score_id_suffix: str | None = None,
    delete_id_suffixes: Sequence[str] = (),
    exporter: Any = None,
) -> bool:
    """Write and/or sweep one run's scores. `False` when nothing was sent.

    Returns whether the backend was asked, not whether the score arrived - the
    SDK batches and this hook does not wait for a network round trip. `False`
    means the exporter is off, has no backend, or refused; in every case the
    caller's own work has already succeeded and this is telemetry.

    `score_id_suffix` and `delete_id_suffixes` are appended to the derived
    trace id, so a caller names WHICH score without re-deriving the id - the
    same reason `trace_id_for` is imported here rather than copied. With no
    suffix the score is appended under an id Langfuse mints, which is what
    the exporter's own automatic scores want and what a rating must not have.
    `value=None` with suffixes to delete is a pure sweep: a cleared rating.

    **A rating never passes both**, and the module docstring says why: a
    synchronous delete overtakes a queued create, so a write that also deleted
    raced itself. The two arguments coexist because a delete-only call still
    needs the trace derivation, not because any caller uses them together.

    `exporter` is an injection point for tests and for a caller that holds one
    already; omitted, the module's own is used. Both spellings resolve to the
    same object in a running service.
    """

    target = _current(exporter)
    if target is None:
        return False
    backend = getattr(target, "_backend", None)
    if backend is None or not hasattr(backend, "score"):
        # A `NullExporter` - the shape a misconfigured or unconfigured
        # deployment gets - has no backend at all, and that is the state this
        # returns False for rather than raising.
        return False
    try:
        trace_id = trace_id_for(run_id)
    except Exception:  # noqa: BLE001 - telemetry never fails a caller
        logger.debug("could not derive a trace id for %s", run_id)
        return False

    writing = value is not None or data_type is not None
    doomed = [f"{trace_id}{suffix}" for suffix in delete_id_suffixes]
    if not writing and not doomed:
        return False

    fields: dict[str, Any] = {
        "observation": None,
        "trace_id": trace_id,
        "name": name,
        "value": value,
        "data_type": data_type,
    }
    if score_id_suffix:
        fields["score_id"] = f"{trace_id}{score_id_suffix}"
    if comment is not None and _capture_content(target):
        fields["comment"] = comment

    def send() -> None:
        if writing:
            _write(backend, dict(fields), name)
        for score_id in doomed:
            # Best effort, one at a time, and a failure here is not the
            # caller's problem: a 404 is the ordinary answer when the score
            # was never ingested, and that is this call's goal rather than its
            # failure.
            try:
                backend.delete_score(score_id)
            except Exception:  # noqa: BLE001 - telemetry never fails a caller
                logger.debug("score %s could not be removed", score_id)

    worker = threading.Thread(
        target=send, name="langfuse-score", daemon=True
    )
    worker.start()
    # ONE budget for the whole operation and not one per call, or a clear
    # would cost twice what a rating does on the same button press. Bounded,
    # and a timeout is not an error: the thread is a daemon and the SDK's
    # queue outlives this call. Joining at all is what keeps a test able to
    # assert without sleeping.
    worker.join(_WORKER_TIMEOUT_SECONDS)
    return True


def _write(backend: Any, fields: dict[str, Any], name: str) -> None:
    """One `create_score`, degrading through the two optional arguments.

    A backend older than either `comment` or `score_id` still gets the
    value: the word is the point, the note is an annotation, and the id is
    an optimisation that only affects what a SECOND rating does.
    """

    for drop in (None, "comment", "score_id"):
        if drop is not None:
            if drop not in fields:
                continue
            fields.pop(drop, None)
        try:
            backend.score(**fields)
            return
        except TypeError:
            continue
        except Exception:  # noqa: BLE001
            logger.debug("score %s could not be written", name)
            return
    logger.debug("score %s could not be written", name)


def record_run_rating(
    run_id: str,
    rating: str | None,
    *,
    comment: str | None = None,
    exporter: Any = None,
    still_cleared: Callable[[], bool] | None = None,
    sweep_after_seconds: float | None = None,
) -> bool:
    """Mirror one run's human rating: one score id, upserted, never raced.

    A rating is an **upsert of one CATEGORICAL id with no delete beside it**,
    so `good` -> `bad` -> `unsure` -> `good` a second apart is four writes to
    one id that converge on the last one whatever order the SDK's queue
    delivers them in.

    A **clear** is the only delete, and it is issued twice: once now, and once
    on a deferred daemon timer `RATING_SCORE_CLEAR_SWEEP_SECONDS` later. The
    second is not belt-and-braces - it is the fix for the measured race, where
    the immediate delete answers 404 against a create that is still queued and
    the create then lands behind it. `still_cleared` is asked first, so a
    person who re-rates inside the window keeps their rating; `write_rating`
    passes a closure that re-reads the database, which is the source of truth
    the trace is a mirror of.

    `sweep_after_seconds` exists for tests - 0 fires the sweep on the next
    tick rather than in three quarters of a minute, and the suite never
    sleeps for real.
    """

    if rating is None:
        sent = record_run_score(
            run_id,
            name=SCORE_HUMAN_RATING,
            delete_id_suffixes=(RATING_SCORE_ID_SUFFIX,),
            exporter=exporter,
        )
        if sent:
            _schedule_clear_sweep(
                run_id,
                exporter=exporter,
                still_cleared=still_cleared,
                after_seconds=sweep_after_seconds,
            )
        return sent
    word = str(rating).strip().lower()
    if word not in RATING_SCORE_VALUES:
        # A vocabulary this module does not know is not written at all: a
        # score nobody can count is worse than no score, and the request model
        # already refused it long before here.
        return False
    return record_run_score(
        run_id,
        name=SCORE_HUMAN_RATING,
        value=word,
        # ALWAYS categorical - never a type change, because a type change
        # needs two ids and two ids race. The module docstring has the
        # measurement.
        data_type="CATEGORICAL",
        comment=comment,
        score_id_suffix=RATING_SCORE_ID_SUFFIX,
        exporter=exporter,
    )


def _schedule_clear_sweep(
    run_id: str,
    *,
    exporter: Any,
    still_cleared: Callable[[], bool] | None,
    after_seconds: float | None,
) -> None:
    """Arm the deferred second delete. One per run id, replaceable, total."""

    from brief_crew.config import RATING_SCORE_CLEAR_SWEEP_SECONDS

    delay = (
        RATING_SCORE_CLEAR_SWEEP_SECONDS
        if after_seconds is None
        else max(0.0, float(after_seconds))
    )
    try:
        timer = threading.Timer(
            delay,
            sweep_cleared_rating,
            kwargs={
                "run_id": run_id,
                "exporter": exporter,
                "still_cleared": still_cleared,
            },
        )
        timer.daemon = True
        with _sweep_lock:
            previous = _sweeps.pop(run_id, None)
            if previous is not None:
                # A second clear REPLACES the first: two timers against one
                # score id would be two deletes for one decision.
                previous.cancel()
            while len(_sweeps) >= _MAX_PENDING_SWEEPS:
                _, stale = _sweeps.popitem()
                stale.cancel()
            _sweeps[run_id] = timer
        timer.start()
    except Exception:  # noqa: BLE001 - telemetry never fails a caller
        logger.debug("could not schedule a clear sweep for %s", run_id)


def sweep_cleared_rating(
    *,
    run_id: str,
    exporter: Any = None,
    still_cleared: Callable[[], bool] | None = None,
) -> bool:
    """The deferred half of a clear. Returns whether a delete was issued.

    Asks the SOURCE OF TRUTH before acting. A person who cleared a rating by
    accident and re-rated four seconds later must not have that second rating
    deleted forty seconds after they made it, so a `still_cleared` that
    answers False - or that raises, which is the same uncertainty - means this
    does nothing at all.

    Exported and callable directly, which is how the tests exercise it
    without waiting three quarters of a minute.
    """

    with _sweep_lock:
        _sweeps.pop(run_id, None)
    if still_cleared is not None:
        try:
            if not still_cleared():
                return False
        except Exception:  # noqa: BLE001 - an unreadable store is not a licence
            logger.debug("could not confirm %s is still cleared", run_id)
            return False
    return record_run_score(
        run_id,
        name=SCORE_HUMAN_RATING,
        delete_id_suffixes=(RATING_SCORE_ID_SUFFIX,),
        exporter=exporter,
    )


def pending_clear_sweeps() -> int:
    """How many deferred sweeps are armed. For tests and for a health read."""

    with _sweep_lock:
        return len(_sweeps)


def _capture_content(exporter: Any) -> bool:
    """Whether this exporter's policy lets user text leave the process."""

    policy = getattr(exporter, "policy", None)
    return bool(getattr(policy, "capture_content", False))
