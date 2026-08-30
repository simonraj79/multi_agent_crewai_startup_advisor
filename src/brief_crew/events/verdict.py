"""The deterministic verdict, published on the run's own event stream.

`Verdict.compute_mechanical_result` is the deliverable this product is built
around: it recomputes and *discards* whatever arithmetic the Synthesist
supplied, so the composite, the confidence band, the fatal floors and the
VALIDATE / NEEDS_WORK / REJECT label are derived facts rather than a model's
opinion. Until this event existed that derivation reached an operator through
exactly one door - the read-only `derived` block the registry builds when the
verdict gate opens - which had two consequences worth stating:

* With `gates: "auto"` no verdict gate ever opens, so the score was
  structurally unavailable in the one mode designed to produce it unattended.
* `GET /api/runs/{run_id}` returns a `ValidationReport`, which carries
  `markdown_body`, `provisional`, `thin_dimensions` and `sources` - and no
  score, in either gate mode.

A custom `BaseEvent` is the cheapest correct second door.
`crewai_event_bus.emit(source, event)` calls `_prepare_event`, which calls
`publish_stream_event` (crewai/events/event_bus.py:569), which fans the event
out to every sink registered *in the current context* through
`crewai.events.stream_context`. That is exactly how `events/context.py` installs
this run's `StreamSinkAdapter`, so an event raised inside a Flow method reaches
that run's sink synchronously and in order, with no global handler to register
and no way for one run's verdict to land in another run's ring. The scoping is
the point: the three research branches and any concurrently executing run each
carry their own copy of that ContextVar.

Deliberately NOT a field on `ValidationReport`. That model is `output_pydantic`
on `reporting_task`, so anything added to it becomes something the *Reporter*
has to emit - which would hand the arithmetic back to an LLM, the single
outcome `compute_mechanical_result` exists to prevent.
"""

from __future__ import annotations

import logging
from typing import Any

from crewai.events.base_events import BaseEvent
from crewai.events.event_bus import crewai_event_bus

from brief_crew.schemas.validator import Verdict


logger = logging.getLogger(__name__)


#: The graph node a verdict frame is attributed to. `synthesize` is the
#: Synthesist ("03 - SCORE" in `service/graph.py`), and a verdict recomputed by
#: the revise loop is still that node's output: `revise_verdict` re-runs the
#: same crew through the same `_run_synthesis`. Pinned rather than resolved from
#: the calling flow method on purpose - resolution would put the first verdict
#: on `synthesize` and its correction on `revise_verdict`, so a client showing
#: "the score" would have to know which of two nodes to read, and the corrected
#: one would not replace the stale one it disagrees with.
VERDICT_NODE_ID = "synthesize"


def verdict_frame_details(verdict: Verdict) -> dict[str, Any]:
    """The `FrameKind.VERDICT` payload: a frozen contract, hand-picked.

    Deliberately not `verdict.model_dump()`. A whole `Verdict` carries five
    `DimensionScore` objects with their anchor prose and evidence URLs, the
    `evidence_counts` map and the kill criteria - hundreds of fields, of which
    the 2,000-frame run ring would happily hold two thousand copies. The seven
    values that are actually the deliverable are exactly the ones
    `compute_mechanical_result` overwrites, so those are what this carries, plus
    the five integers they are computed from. The verdict gate's `derived` block
    remains the place to read the whole object.

    Every string here is bounded well inside `SerializerLimits.max_string`
    (4096) by the schema itself: `verdict`, `confidence_band` and
    `decision_reason` are `Literal` unions of at most 21 characters, and
    `fatal_floors` is a list of at most four `FloorCode` literals. Nothing in
    this payload can be clipped. `decision_reason` is nullable - it names the
    floor or the low-confidence override that decided the label, and a verdict
    decided by the composite alone has none.

    Shared with `service/runner.py` rather than inlined in the serializer,
    because the synthetic runner has to emit this same shape: a double that
    diverges from its subject certifies nothing, and the free path is where both
    the E2E suite and anyone looking at the UI without a key see a verdict.
    """

    return {
        "verdict": verdict.verdict,
        "composite_score": verdict.composite_score,
        "confidence": verdict.confidence,
        "confidence_band": verdict.confidence_band,
        "provisional": verdict.provisional,
        "fatal_floors": list(verdict.fatal_floors),
        "decision_reason": verdict.decision_reason,
        "dimensions": {
            "demand": verdict.demand.score,
            "market": verdict.market.score,
            "competitive_room": verdict.competitive_room.score,
            "feasibility": verdict.feasibility.score,
            "headroom_over_free": verdict.headroom_over_free.score,
        },
    }


def verdict_frame_message(verdict: Verdict) -> str:
    """The one-line summary a log or an activity rail shows for a verdict."""

    return (
        f"Verdict {verdict.verdict} at {verdict.composite_score}"
        f" (confidence {verdict.confidence})"
    )


class VerdictComputedEvent(BaseEvent):
    """A validated `Verdict` has been produced by the synthesis step.

    `type` is what `crewai_event_bus._prepare_event` matches against its scope
    tables, so the string is namespaced: an event this repo raises must never
    collide with a CrewAI lifecycle pair and get treated as opening or closing
    an event scope it knows nothing about.
    """

    type: str = "validator_verdict_computed"
    verdict: Verdict


def publish_verdict(source: Any, verdict: Verdict) -> None:
    """Publish `verdict` to whichever run sink owns the current context.

    Never raises. This runs on the flow's own thread immediately after the
    Synthesist's output has been validated, and a run must not fail because
    something downstream of it could not render a frame - the same rule
    `StreamSinkAdapter` applies to every other capture path, one layer up.
    Failure here is a programming error rather than a data one (the adapter
    counts its own errors into `emit_errors`), so it is logged loudly instead of
    being swallowed silently.
    """

    try:
        crewai_event_bus.emit(source, VerdictComputedEvent(verdict=verdict))
    except Exception:  # pragma: no cover - defensive; see the docstring
        logger.warning("could not publish the computed verdict", exc_info=True)
