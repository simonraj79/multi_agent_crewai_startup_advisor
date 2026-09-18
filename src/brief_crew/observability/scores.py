"""A generic score hook: one number against one run's trace, after it closed.

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
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from brief_crew.observability.backend import trace_id_for

__all__ = [
    "SCORE_GATE_OUTCOME",
    "SCORE_HUMAN_RATING",
    "record_run_score",
    "set_score_exporter",
]

logger = logging.getLogger(__name__)

#: The two names this repository writes. Facts about a run - was it any good,
#: and did a person approve or send it back - and neither names a flow.
SCORE_HUMAN_RATING = "human_rating"
SCORE_GATE_OUTCOME = "gate_outcome"

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
    value: Any,
    data_type: str,
    comment: str | None = None,
    exporter: Any = None,
) -> bool:
    """Write one score against a run's trace. `False` when nothing was sent.

    Returns whether the backend was asked, not whether the score arrived - the
    SDK batches and this hook does not wait for a network round trip. `False`
    means the exporter is off, has no backend, or refused; in every case the
    caller's own work has already succeeded and this is telemetry.

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

    fields: dict[str, Any] = {
        "observation": None,
        "trace_id": trace_id,
        "name": name,
        "value": value,
        "data_type": data_type,
    }
    if comment is not None and _capture_content(target):
        fields["comment"] = comment

    def send() -> None:
        try:
            backend.score(**fields)
        except TypeError:
            # A backend whose `score` predates the optional `comment`. Send
            # the score without it rather than losing the score: the number is
            # the point and the note is the annotation.
            fields.pop("comment", None)
            try:
                backend.score(**fields)
            except Exception:  # noqa: BLE001
                logger.debug("score %s could not be written", name)
        except Exception:  # noqa: BLE001
            logger.debug("score %s could not be written", name)

    worker = threading.Thread(
        target=send, name="langfuse-score", daemon=True
    )
    worker.start()
    # Bounded, and a timeout is not an error: the thread is a daemon and the
    # SDK's queue outlives this call. Joining at all is what keeps a test able
    # to assert on the backend without sleeping.
    worker.join(_WORKER_TIMEOUT_SECONDS)
    return True


def _capture_content(exporter: Any) -> bool:
    """Whether this exporter's policy lets user text leave the process."""

    policy = getattr(exporter, "policy", None)
    return bool(getattr(policy, "capture_content", False))


def rating_score_value(rating: str | None) -> tuple[Any, str] | None:
    """One rating as `(value, data_type)`, or `None` for "do not score".

    `good` -> 1 and `bad` -> 0 as a NUMERIC, which is the pair a mean over a
    window is worth taking. `unsure` is deliberately **not** a made-up number
    in between: it is a person declining to say, and averaging it as 0.5 would
    invent an opinion nobody expressed. It goes as a CATEGORICAL companion
    instead, so it is countable and not averageable.

    A cleared rating scores nothing at all: Langfuse has no "unset a score"
    and writing a third value to mean "they took it back" would be a fourth
    thing to interpret.
    """

    if rating == "good":
        return 1, "NUMERIC"
    if rating == "bad":
        return 0, "NUMERIC"
    if rating == "unsure":
        return "unsure", "CATEGORICAL"
    return None
