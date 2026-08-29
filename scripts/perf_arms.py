"""Execution arms for the F42 performance harness.

Everything here drives the *real* ``ValidatorFlow`` through its existing
dependency-injected ``ValidatorCrewFactories`` seam and its existing
``no_gates=True`` mode. ``src/brief_crew/validator_flow.py`` is not modified,
imported-and-patched, or reimplemented.

The sequential baseline is produced by wrapping the three research crew
factories so their ``kickoff`` calls share one lock. The Flow still fans out
into three worker threads and still joins with ``and_()``; only the branch work
is serialized. That is the closest apples-to-apples baseline reachable without
editing the Flow, and its bias is conservative: see ``SEQUENTIAL_ARM_CAVEAT``.
"""

from __future__ import annotations

import contextlib
import threading
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence
from unittest.mock import patch

from brief_crew.events import (
    CaptureContext,
    FrameBuffer,
    StreamSinkAdapter,
    UIEventType,
    capture_events,
)
from brief_crew.schemas import (
    DimensionScore,
    Evidence,
    FeasibilityFindings,
    MarketFindings,
    Repo,
    ScopedIdea,
    SentimentFindings,
    Thread,
    ValidationReport,
    Verdict,
)
from brief_crew.service.graph import VALIDATOR_NODE_REGISTRY
from brief_crew.validator_flow import ValidatorCrewFactories, ValidatorFlow
from brief_crew.validator_guardrails import DEMAND_ANCHORS, compute_evidence_counts

from scripts.perf_metrics import MemoryProbe, PeakMemorySampler, wall_clock

DEFAULT_IDEA = "A scheduling assistant for clinics"
DEFAULT_BRANCH_SECONDS = (0.5, 0.5, 0.5)
DEFAULT_STAGE_SECONDS = 0.02
APPROVE = '{"decision": "approve"}'

SEQUENTIAL_ARM_CAVEAT = (
    "The sequential arm runs the Flow's own F04/R-3 fallback via the "
    "`sequential_branches` input, so each branch's whole method body - cache "
    "lookup, kickoff and evidence write-back - is serialized. This is the "
    "implementation R-3 would actually ship, so the ratio is a like-for-like "
    "comparison rather than the conservative lower bound this harness "
    "originally measured with an external factory lock."
)


# --------------------------------------------------------------------------
# Instrumentation primitives
# --------------------------------------------------------------------------
class FirstTouch:
    """Record the first time any thread reaches a point, once."""

    def __init__(self) -> None:
        self._value: float | None = None
        self._lock = threading.Lock()

    def mark(self) -> None:
        with self._lock:
            if self._value is None:
                self._value = wall_clock()

    def reset(self) -> None:
        with self._lock:
            self._value = None

    @property
    def value(self) -> float | None:
        with self._lock:
            return self._value


class BranchConcurrency:
    """Observe how many research branches are genuinely in flight at once."""

    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0
        self._lock = threading.Lock()

    @contextlib.contextmanager
    def track(self) -> Iterator[None]:
        with self._lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
        try:
            yield
        finally:
            with self._lock:
                self.active -= 1


class InstrumentedRunner:
    """Wrap any object with ``kickoff(inputs)`` for timing and serialization."""

    def __init__(
        self,
        inner: Any,
        *,
        lock: threading.Lock | None = None,
        concurrency: BranchConcurrency | None = None,
        on_start: Callable[[], None] | None = None,
    ) -> None:
        self.inner = inner
        self.lock = lock
        self.concurrency = concurrency
        self.on_start = on_start

    def kickoff(self, inputs: Mapping[str, Any]) -> Any:
        if self.on_start is not None:
            self.on_start()
        if self.lock is None:
            return self._tracked(inputs)
        with self.lock:
            return self._tracked(inputs)

    def _tracked(self, inputs: Mapping[str, Any]) -> Any:
        if self.concurrency is None:
            return self.inner.kickoff(dict(inputs))
        with self.concurrency.track():
            return self.inner.kickoff(dict(inputs))


class SleepingRunner:
    """A no-cost stand-in for one crew: burn wall clock, return a fixed model.

    Mirrors the ``FakeRunner`` shape already used by tests/validator/test_flow.py
    (an object exposing ``kickoff(inputs) -> result``), kept local so the harness
    does not depend on a test module other agents are editing.
    """

    def __init__(self, result: Any, seconds: float = 0.0) -> None:
        self.result = result
        self.seconds = max(0.0, float(seconds))
        self.calls = 0

    def kickoff(self, inputs: Mapping[str, Any]) -> Any:
        self.calls += 1
        if self.seconds:
            # A real branch is I/O bound (Firecrawl, HN, GitHub), so sleeping
            # models it far better than a CPU spin, which the GIL would
            # serialize and turn the parallel arm into a lie.
            threading.Event().wait(self.seconds)
        return self.result


# --------------------------------------------------------------------------
# Deterministic fixtures for the synthetic arms
# --------------------------------------------------------------------------
MARKET_URL = "https://example.com/market"
THREAD_URL = "https://news.ycombinator.com/item?id=1"
REPO_URL = "https://github.com/example/project"


@dataclass(frozen=True, slots=True)
class ValidatorFixtures:
    scope: ScopedIdea
    market: MarketFindings
    sentiment: SentimentFindings
    feasibility: FeasibilityFindings
    verdict: Verdict
    report: ValidationReport


def build_fixtures(idea: str = DEFAULT_IDEA) -> ValidatorFixtures:
    """Schema-valid outputs for every crew, so the Flow runs its real code."""
    scope = ScopedIdea(
        startup_idea=idea,
        category="Clinic scheduling software",
        target_user="Clinic operations managers",
        problem="Manual scheduling creates avoidable administrative work.",
        technology_claim="A constrained assistant can automate intake scheduling.",
        market_query="clinic scheduling software pricing market",
        community_queries=["clinic scheduling manual workaround"],
        tech_queries=["clinic scheduling assistant"],
        assumptions=[
            "Clinics own the workflow",
            "Scheduling is repetitive",
            "Data is exportable",
        ],
        scoping_gaps=["Willingness to pay is unknown."],
        as_of="2026-08-29",
    )
    market_source = Evidence(
        claim="A clinic software segment exists.",
        url=MARKET_URL,
        publisher="Example",
        dated="2026-08-01",
        retrieved_via="firecrawl",
    )
    market = MarketFindings(
        sources=[market_source],
        source_urls=[MARKET_URL],
        gaps=[],
        tool_status="ok",
        competitors=[],
    )
    sentiment = SentimentFindings(
        sources=[
            Thread(
                classification="HAS_PROBLEM",
                quote="We maintain this schedule manually.",
                url=THREAD_URL,
                date="2026-07-01",
            )
        ],
        source_urls=[THREAD_URL],
        gaps=[],
        tool_status="ok",
    )
    feasibility = FeasibilityFindings(
        sources=[
            Repo(
                name="example/project",
                license_permits_commercial=True,
                months_since_push=1,
                relevance="PARTIAL",
                url=REPO_URL,
            )
        ],
        source_urls=[REPO_URL],
        gaps=[],
        tool_status="ok",
    )
    supporting = DimensionScore(
        score=2,
        anchor_matched="Two directly relevant sources support this level.",
        evidence_urls=[MARKET_URL],
    )
    verdict = Verdict(
        demand=DimensionScore(
            score=2, anchor_matched=DEMAND_ANCHORS[2], evidence_urls=[THREAD_URL]
        ),
        market=supporting,
        competitive_room=supporting,
        feasibility=DimensionScore(
            score=3,
            anchor_matched="A small team can ship a constrained first version.",
            evidence_urls=[REPO_URL],
        ),
        headroom_over_free=DimensionScore(
            score=3,
            anchor_matched="No repository in the evidence solves the entire job.",
            evidence_urls=[REPO_URL],
        ),
        evidence_counts=compute_evidence_counts(market, sentiment, feasibility),
        market_coverage=0.2,
        sentiment_coverage=0.2,
        feasibility_coverage=0.2,
        median_market_source_age_months=1,
        branches_ok=3,
        cheapest_next_test="Interview five clinic operations managers.",
    )
    report = ValidationReport(
        markdown_body=(
            "# Validation report\n\n"
            "Evidence remains thin; run the stated interview next.\n\n"
            f"## Sources\n- {MARKET_URL}\n"
        ),
        provisional=False,
        thin_dimensions=["D", "M", "C", "F", "X"],
        sources=[market_source],
    )
    return ValidatorFixtures(scope, market, sentiment, feasibility, verdict, report)


def synthetic_factories(
    fixtures: ValidatorFixtures,
    *,
    branch_seconds: Sequence[float] = DEFAULT_BRANCH_SECONDS,
    stage_seconds: float = DEFAULT_STAGE_SECONDS,
) -> ValidatorCrewFactories:
    """Crew factories that cost nothing and make no network call."""
    market_s, sentiment_s, feasibility_s = branch_seconds
    return ValidatorCrewFactories(
        scope=lambda: SleepingRunner(fixtures.scope, stage_seconds),
        market=lambda: SleepingRunner(fixtures.market, market_s),
        sentiment=lambda: SleepingRunner(fixtures.sentiment, sentiment_s),
        feasibility=lambda: SleepingRunner(fixtures.feasibility, feasibility_s),
        synthesis=lambda *_: SleepingRunner(fixtures.verdict, stage_seconds),
        report=lambda *_: SleepingRunner(fixtures.report, stage_seconds),
    )


def live_factories() -> ValidatorCrewFactories:
    """The real, paid crews: OpenRouter plus Firecrawl, HN Algolia and GitHub."""
    return ValidatorCrewFactories()


def instrument_factories(
    base: ValidatorCrewFactories,
    *,
    lock: threading.Lock | None = None,
    concurrency: BranchConcurrency | None = None,
    on_branch_start: Callable[[], None] | None = None,
    on_report_start: Callable[[], None] | None = None,
) -> ValidatorCrewFactories:
    """Wrap only the three research branches, plus optionally the reporter."""

    def branch(factory: Callable[[], Any]) -> Callable[[], Any]:
        def make() -> Any:
            return InstrumentedRunner(
                factory(),
                lock=lock,
                concurrency=concurrency,
                on_start=on_branch_start,
            )

        return make

    def report(factory: Callable[..., Any]) -> Callable[..., Any]:
        def make(*args: Any) -> Any:
            return InstrumentedRunner(factory(*args), on_start=on_report_start)

        return make

    return replace(
        base,
        market=branch(base.market),
        sentiment=branch(base.sentiment),
        feasibility=branch(base.feasibility),
        report=report(base.report),
    )


# --------------------------------------------------------------------------
# Frame capture
# --------------------------------------------------------------------------
def drain_frames(buffer: FrameBuffer) -> list[Any]:
    """Page the whole ring out; ``replay`` caps at MAX_REPLAY_LIMIT per call."""
    frames: list[Any] = []
    cursor = 0
    while True:
        page = buffer.replay(after=cursor, limit=500)
        if not page:
            return frames
        frames.extend(page)
        cursor = page[-1].seq


def frame_report(buffer: FrameBuffer) -> dict[str, Any]:
    """Drop/gap counters from the spine plus an independent seq and pairing check."""
    stats = buffer.stats()
    frames = drain_frames(buffer)
    seqs = [frame.seq for frame in frames]
    contiguous = bool(seqs) and seqs == list(range(seqs[0], seqs[0] + len(seqs)))
    starts_from_one = seqs[0] == 1 if seqs else False

    open_nodes: dict[str, int] = {}
    for frame in frames:
        if frame.event_type == UIEventType.NODE_START:
            open_nodes[frame.node_id] = open_nodes.get(frame.node_id, 0) + 1
        elif frame.event_type == UIEventType.NODE_END:
            open_nodes[frame.node_id] = open_nodes.get(frame.node_id, 0) - 1
    unpaired = sum(count for count in open_nodes.values() if count > 0)

    return {
        "count": stats.count,
        "captured": stats.captured,
        "dropped": stats.dropped,
        "gaps": stats.gaps,
        "emit_errors": stats.emit_errors,
        "first_seq": stats.first_seq,
        "last_seq": stats.last_seq,
        "seq_contiguous": contiguous and starts_from_one,
        "unpaired_nodes": unpaired,
        "ring_capacity": buffer.capacity,
    }


# --------------------------------------------------------------------------
# One benchmark run
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RunOutcome:
    arm: str
    index: int
    ok: bool
    wall_seconds: float
    max_concurrent_branches: int
    peak_bytes: int | None
    memory: Mapping[str, Any]
    frames: Mapping[str, Any]
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "index": self.index,
            "ok": self.ok,
            "wall_seconds": self.wall_seconds,
            "max_concurrent_branches": self.max_concurrent_branches,
            "peak_bytes": self.peak_bytes,
            "memory": dict(self.memory),
            "frames": dict(self.frames),
            "error": self.error,
        }


@contextlib.contextmanager
def _flow_sandbox(output_path: Path, *, isolate_cache: bool) -> Iterator[None]:
    """Never touch output/validation.md, and keep synthetic runs off the network."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("brief_crew.validator_flow.OUTPUT_PATH", output_path))
        if isolate_cache:
            stack.enter_context(
                patch("brief_crew.validator_flow.lookup_branch_cache", return_value=[])
            )
            stack.enter_context(
                patch("brief_crew.validator_flow.index_captured_evidence", return_value=None)
            )
        yield


def run_arm_once(
    *,
    arm: str,
    index: int,
    base_factories: ValidatorCrewFactories,
    serialize: bool,
    idea: str,
    output_path: Path,
    memory_probe: MemoryProbe,
    sample_interval_s: float,
    isolate_cache: bool,
) -> RunOutcome:
    """Execute one ValidatorFlow run and measure wall clock, memory and frames."""
    concurrency = BranchConcurrency()
    # The sequential arm now drives the Flow's OWN fallback (F04 / R-3) via the
    # `sequential_branches` input, rather than the external factory lock this
    # harness used before it existed. The lock only serialized kickoff(); the
    # real fallback serializes each branch's whole method body, cache work
    # included, so the comparison is now like-for-like instead of a lower bound.
    factories = instrument_factories(base_factories, lock=None, concurrency=concurrency)

    run_id = f"perf-{arm}-{index}-{uuid.uuid4().hex[:8]}"
    buffer = FrameBuffer()
    adapter = StreamSinkAdapter(
        run_id=run_id, buffer=buffer, registry=VALIDATOR_NODE_REGISTRY
    )

    error = ""
    with PeakMemorySampler(memory_probe, interval_s=sample_interval_s) as sampler:
        started = wall_clock()
        try:
            with _flow_sandbox(output_path, isolate_cache=isolate_cache):
                with capture_events(CaptureContext(run_id=run_id, adapter=adapter)):
                    ValidatorFlow(crew_factories=factories).kickoff(
                        inputs={
                            "idea": idea,
                            "no_gates": True,
                            "sequential_branches": serialize,
                        }
                    )
        except Exception as exc:  # noqa: BLE001 - a failed run is a reportable result
            error = f"{type(exc).__name__}: {exc}"
        elapsed = wall_clock() - started

    return RunOutcome(
        arm=arm,
        index=index,
        ok=not error,
        wall_seconds=elapsed,
        max_concurrent_branches=concurrency.maximum,
        peak_bytes=sampler.peak_bytes,
        memory=sampler.as_dict(),
        frames=frame_report(buffer),
        error=error,
    )


# --------------------------------------------------------------------------
# Gate reply-to-resume probe
# --------------------------------------------------------------------------
GATE_PROBE_NOTE = (
    "Gate latency is measured with lightweight crew doubles in both modes by design: "
    "the timer stops the instant the first post-gate crew is reached, before any model "
    "call, so real crews would add cost without changing what is measured. The Pinecone "
    "branch cache is stubbed out for the same reason."
)


@dataclass(frozen=True, slots=True)
class GateLatency:
    index: int
    gate: str
    total_ms: float
    load_ms: float
    dispatch_ms: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "gate": self.gate,
            "total_ms": self.total_ms,
            "from_pending_ms": self.load_ms,
            "dispatch_ms": self.dispatch_ms,
        }


@dataclass
class GateProbeResult:
    samples: list[GateLatency] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def latencies_ms(self) -> list[float]:
        return [sample.total_ms for sample in self.samples]

    def as_dict(self) -> dict[str, Any]:
        return {
            "note": GATE_PROBE_NOTE,
            "samples": [sample.as_dict() for sample in self.samples],
            "errors": list(self.errors),
        }


def _resume_gate(
    persistence: Any,
    flow_id: str,
    factories: ValidatorCrewFactories,
    marker: FirstTouch,
) -> tuple[Any, float, float]:
    """Time a real reply -> resume: state hydration, router, next node reached."""
    marker.reset()
    started = wall_clock()
    flow = ValidatorFlow.from_pending(flow_id, persistence, crew_factories=factories)
    loaded = wall_clock()
    result = flow.resume(APPROVE)
    reached = marker.value
    if reached is None:
        # The next node never called a crew; fall back to when resume returned.
        reached = wall_clock()
    return result, (loaded - started) * 1000.0, (reached - started) * 1000.0


def _gate_round(
    *,
    index: int,
    idea: str,
    persistence: Any,
    factories: ValidatorCrewFactories,
    branch_touch: FirstTouch,
    report_touch: FirstTouch,
    output_path: Path,
) -> list[GateLatency]:
    """One full pause/resume/pause/resume cycle. Raises on any deviation."""
    from crewai.flow.async_feedback import HumanFeedbackPending

    samples: list[GateLatency] = []
    with _flow_sandbox(output_path, isolate_cache=True):
        pending = ValidatorFlow(
            persistence=persistence, crew_factories=factories
        ).kickoff(inputs={"idea": idea, "no_gates": False, "id": uuid.uuid4().hex})
        if not isinstance(pending, HumanFeedbackPending):
            raise RuntimeError("flow did not pause at the scope gate")

        second, load_ms, total_ms = _resume_gate(
            persistence, pending.context.flow_id, factories, branch_touch
        )
        samples.append(GateLatency(index, "scope", total_ms, load_ms, total_ms - load_ms))
        if not isinstance(second, HumanFeedbackPending):
            raise RuntimeError("flow did not pause at the verdict gate")

        _, load_ms, total_ms = _resume_gate(
            persistence, second.context.flow_id, factories, report_touch
        )
        samples.append(GateLatency(index, "verdict", total_ms, load_ms, total_ms - load_ms))
    return samples


def measure_gate_resume(
    *,
    rounds: int,
    idea: str,
    database_url: str,
    output_path: Path,
    attempts: int = 2,
) -> GateProbeResult:
    """Drive both native gates through pause, persist, from_pending and resume.

    A round is retried up to ``attempts`` times because CrewAI's resume path has
    been observed to fail intermittently with a RecursionError. Every failure is
    recorded in ``errors`` even when the retry succeeds, so a flaky resume stays
    visible instead of being smoothed away.
    """
    from brief_crew.service.persistence import PostgresFlowPersistence

    fixtures = build_fixtures(idea)
    branch_touch = FirstTouch()
    report_touch = FirstTouch()
    factories = instrument_factories(
        synthetic_factories(fixtures, branch_seconds=(0.0, 0.0, 0.0), stage_seconds=0.0),
        on_branch_start=branch_touch.mark,
        on_report_start=report_touch.mark,
    )

    outcome = GateProbeResult()
    persistence = PostgresFlowPersistence(database_url)
    try:
        for index in range(rounds):
            for attempt in range(max(1, attempts)):
                try:
                    outcome.samples.extend(
                        _gate_round(
                            index=index,
                            idea=idea,
                            persistence=persistence,
                            factories=factories,
                            branch_touch=branch_touch,
                            report_touch=report_touch,
                            output_path=output_path,
                        )
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - a failed probe is reportable
                    outcome.errors.append(
                        f"round {index} attempt {attempt}: {type(exc).__name__}: {exc}"
                    )
    finally:
        with contextlib.suppress(Exception):
            persistence.close()
    return outcome
