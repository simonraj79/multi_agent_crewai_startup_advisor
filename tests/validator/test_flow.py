from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from brief_crew.config import CHEAP_MODEL
from crewai.flow import build_flow_structure
from crewai.flow.async_feedback import HumanFeedbackPending, PendingFeedbackContext
from brief_crew.events import (
    CaptureContext,
    FrameBuffer,
    NodeRegistry,
    QUARANTINE_NODE_ID,
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
from brief_crew.validator_flow import (
    BRANCH_NODES,
    BRANCH_ORDER,
    BranchSequencer,
    PrefixedStdout,
    ValidatorCrewFactories,
    ValidatorFeedbackProvider,
    ValidatorFlow,
    ValidatorState,
    branch_output,
    validate,
)
from brief_crew.validator_guardrails import DEMAND_ANCHORS, compute_evidence_counts

MARKET_URL = "https://example.com/market"
THREAD_URL = "https://news.ycombinator.com/item?id=1"
REPO_URL = "https://github.com/example/project"


class FakeRunner:
    def __init__(
        self,
        result: object,
        tracker: ConcurrencyTracker | None = None,
        label: str = "",
        chatter: str = "",
    ) -> None:
        self.result = result
        self.tracker = tracker
        self.label = label
        self.chatter = chatter
        self.inputs: list[dict[str, object]] = []

    def kickoff(self, inputs: dict[str, object]) -> object:
        self.inputs.append(inputs)
        if self.chatter:
            print(self.chatter)
        if self.tracker is not None:
            self.tracker.enter(self.label)
        return self.result


#: How long a branch waits at the barrier for its siblings before giving up.
#:
#: Generous on purpose. It is not a latency budget - it is the point at which
#: "the branches are not concurrent" becomes the only remaining explanation.
BRANCH_RENDEZVOUS_TIMEOUT_SECONDS = 10.0


class ConcurrencyTracker:
    """Observes whether the three research branches genuinely overlap.

    `expect` arms a RENDEZVOUS, and that is the difference between a test that
    proves concurrency and one that merely tends to observe it.

    Without it, `enter` held its slot for a fixed 80ms and the parallel tests
    asserted `maximum == 3` - so all three threads had to be inside the same
    80ms window. That is a race against the machine, not against the code, and
    it lost: this suite failed once in nine runs on 2026-09-01 while sixteen
    subagents and a Playwright run saturated the CPU. A thread scheduled 80ms
    late made `maximum` 2, and `assertEqual(3)` reported a concurrency defect
    that did not exist.

    With `expect=3` every branch blocks until all three have arrived, so
    `maximum` is 3 whenever the fan-out is real and the timing of the machine
    cannot change the answer. It is also a STRICTER claim: the old version
    accepted three overlapping arrivals, this one requires all three to be in
    flight simultaneously, and a genuinely serialized fan-out now fails by
    timeout rather than by luck.

    Left unarmed (`expect=None`) for the sequential tests, where a barrier of
    three would be waiting for siblings that by definition never arrive.
    """

    def __init__(self, expect: int | None = None) -> None:
        self.active = 0
        self.maximum = 0
        self.order: list[str] = []
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(expect) if expect else None

    def enter(self, label: str = "") -> None:
        with self.lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            if label:
                self.order.append(label)
        if self.barrier is None:
            time.sleep(0.08)
        else:
            try:
                self.barrier.wait(timeout=BRANCH_RENDEZVOUS_TIMEOUT_SECONDS)
            except threading.BrokenBarrierError:
                # Swallowed deliberately. The caller's `assertEqual(maximum, 3)`
                # is the assertion that should report this, with a number the
                # reader can interpret - an exception raised from inside a
                # CrewAI worker thread would surface as an unrelated branch
                # failure and say nothing about concurrency.
                pass
        with self.lock:
            self.active -= 1


def fixtures() -> tuple[
    ScopedIdea,
    MarketFindings,
    SentimentFindings,
    FeasibilityFindings,
    Verdict,
    ValidationReport,
]:
    scope = ScopedIdea(
        startup_idea="A scheduling assistant for clinics.",
        category="Clinic scheduling software",
        target_user="Clinic operations managers",
        problem="Manual scheduling creates avoidable administrative work.",
        technology_claim="A constrained assistant can automate intake scheduling.",
        market_query="clinic scheduling software pricing market",
        community_queries=["clinic scheduling manual workaround"],
        tech_queries=["clinic scheduling assistant"],
        assumptions=["Clinics own the workflow", "Scheduling is repetitive", "Data is exportable"],
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
    thread = Thread(
        classification="HAS_PROBLEM",
        quote="We maintain this schedule manually.",
        url=THREAD_URL,
        date="2026-07-01",
    )
    sentiment = SentimentFindings(
        sources=[thread],
        source_urls=[THREAD_URL],
        gaps=[],
        tool_status="ok",
    )
    repo = Repo(
        name="example/project",
        license_permits_commercial=True,
        months_since_push=1,
        relevance="PARTIAL",
        url=REPO_URL,
    )
    feasibility = FeasibilityFindings(
        sources=[repo],
        source_urls=[REPO_URL],
        gaps=[],
        tool_status="ok",
    )
    demand = DimensionScore(
        score=2,
        anchor_matched=DEMAND_ANCHORS[2],
        evidence_urls=[THREAD_URL],
    )
    other = DimensionScore(
        score=2,
        anchor_matched="Two directly relevant sources support this level.",
        evidence_urls=[MARKET_URL],
    )
    result = Verdict(
        demand=demand,
        market=other,
        competitive_room=other,
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
    return scope, market, sentiment, feasibility, result, report


class ValidatorFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache_lookup = patch(
            "brief_crew.validator_flow.lookup_branch_cache", return_value=[]
        ).start()
        self.addCleanup(patch.stopall)

    def test_no_gate_flow_fans_out_transitions_and_persists(self) -> None:
        scope, market, sentiment, feasibility, verdict, report = fixtures()
        tracker = ConcurrencyTracker(expect=3)
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market, tracker),
            sentiment=lambda: FakeRunner(sentiment, tracker),
            feasibility=lambda: FakeRunner(feasibility, tracker),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
        )

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path):
                flow = ValidatorFlow(crew_factories=factories)
                result = flow.kickoff(
                    inputs={"idea": scope.startup_idea, "no_gates": True}
                )

            self.assertEqual(result, report)
            self.assertEqual(tracker.maximum, 3)
            self.assertEqual(flow.state.scope_route, "scope_approved")
            self.assertEqual(flow.state.verdict_route, "verdict_approved")
            self.assertEqual(flow.state.market, market)
            self.assertEqual(flow.state.sentiment, sentiment)
            self.assertEqual(flow.state.feasibility, feasibility)
            self.assertEqual(flow.state.verdict, verdict)
            self.assertEqual(flow.state.report, report)
            self.assertEqual(output_path.read_text(encoding="utf-8"), report.markdown_body)

    def test_validate_headless_entry_point_uses_injected_factories(self) -> None:
        scope, market, sentiment, feasibility, verdict, report = fixtures()
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market),
            sentiment=lambda: FakeRunner(sentiment),
            feasibility=lambda: FakeRunner(feasibility),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
        )

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path):
                result = validate(
                    scope.startup_idea,
                    no_gates=True,
                    crew_factories=factories,
                )

            self.assertEqual(result, report)
            self.assertEqual(output_path.read_text(encoding="utf-8"), report.markdown_body)

    def test_feedback_provider_uses_native_pending_signal(self) -> None:
        provider = ValidatorFeedbackProvider()
        flow = ValidatorFlow()
        context = PendingFeedbackContext(
            flow_id=flow.flow_id,
            flow_class="brief_crew.validator_flow.ValidatorFlow",
            method_name="confirm_scope",
            method_output="{}",
            message="Confirm scope",
            llm=CHEAP_MODEL,
        )

        with self.assertRaises(HumanFeedbackPending) as raised:
            provider.request_feedback(context, flow)

        self.assertEqual(raised.exception.context, context)
        self.assertEqual(raised.exception.callback_info, {"gate": "confirm_scope"})
        flow.state.no_gates = True
        self.assertEqual(
            provider.request_feedback(context, flow),
            '{"decision": "approve"}',
        )

    def test_flow_definition_uses_native_gates_and_deterministic_routers(self) -> None:
        definition = ValidatorFlow.flow_definition()
        scope_gate = definition.methods["confirm_scope"].human_feedback
        verdict_gate = definition.methods["review_verdict"].human_feedback

        self.assertIsNotNone(scope_gate)
        self.assertIsNotNone(verdict_gate)
        self.assertIsNone(scope_gate.emit)
        self.assertIsNone(verdict_gate.emit)
        # No gate LLM. With `emit=None` CrewAI can never call it, but it
        # deserializes the value before it checks `emit`, so naming a model
        # here costs two discarded completion clients per run. Pinned as None
        # so a future edit cannot quietly reintroduce that cost.
        self.assertIsNone(scope_gate.llm)
        self.assertIsNone(verdict_gate.llm)
        self.assertTrue(definition.methods["route_scope"].router)
        self.assertTrue(definition.methods["route_verdict"].router)

    def test_flow_definition_has_three_siblings_and_one_join(self) -> None:
        definition = ValidatorFlow.flow_definition()
        siblings = {
            "research_market",
            "research_sentiment",
            "research_feasibility",
        }

        for name in siblings:
            self.assertEqual(definition.methods[name].listen, "scope_approved")
        join = definition.methods["synthesize"].listen
        self.assertEqual(set(join["and"]), siblings)

    def test_market_cache_supplements_but_never_skips_live_research(self) -> None:
        scope, market, *_ = fixtures()
        order: list[str] = []
        runner = FakeRunner(market)
        original_kickoff = runner.kickoff

        def kickoff(inputs: dict[str, object]) -> object:
            order.append("live")
            return original_kickoff(inputs)

        runner.kickoff = kickoff  # type: ignore[method-assign]
        factories = ValidatorCrewFactories(market=lambda: runner)
        flow = ValidatorFlow(crew_factories=factories)
        flow.state.scope = scope
        cached = [
            {
                "text": "Dated cached market evidence.",
                "url": "https://cache.example/market",
                "publisher": "Cache Example",
                "published_date": "2026-08-01",
                "indexed_at": "2026-08-20T00:00:00+00:00",
                "rerank_score": 0.8,
            }
        ]
        self.cache_lookup.side_effect = lambda *args, **kwargs: (
            order.append("lookup") or cached
        )

        with patch(
            "brief_crew.validator_flow.index_captured_evidence",
            side_effect=lambda *args, **kwargs: order.append("index"),
        ):
            result = flow.research_market()

        self.assertEqual(result, market)
        self.assertEqual(order, ["lookup", "live", "index"])
        self.assertEqual(len(runner.inputs), 1)
        cache_block = str(runner.inputs[0]["cached_evidence_block"])
        self.assertIn("SUPPLEMENTAL, NOT A CONCLUSION", cache_block)
        self.assertIn("source_date: 2026-08-01", cache_block)

    def test_sentiment_branch_never_looks_up_cache(self) -> None:
        scope, _, sentiment, *_ = fixtures()
        runner = FakeRunner(sentiment)
        flow = ValidatorFlow(
            crew_factories=ValidatorCrewFactories(sentiment=lambda: runner)
        )
        flow.state.scope = scope
        self.cache_lookup.reset_mock()

        result = flow.research_sentiment()

        self.assertEqual(result, sentiment)
        self.cache_lookup.assert_not_called()


class SequentialFallbackTests(unittest.TestCase):
    """PRD R-3 / F04: the withdrawal decision needs something to withdraw to.

    The fallback must be the *same* six agents on the *same* graph, so every
    test here also asserts that nothing about the topology moved.
    """

    def setUp(self) -> None:
        patch(
            "brief_crew.validator_flow.lookup_branch_cache", return_value=[]
        ).start()
        patch(
            "brief_crew.validator_flow.index_captured_evidence", return_value=0
        ).start()
        self.addCleanup(patch.stopall)

    def _run(
        self,
        *,
        sequential: bool | None,
        tracker: ConcurrencyTracker | None = None,
        chatter: dict[str, str] | None = None,
        capture: CaptureContext | None = None,
    ) -> tuple[object, ValidationReport]:
        scope, market, sentiment, feasibility, verdict, report = fixtures()
        noise = chatter or {}
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market, tracker, "market", noise.get("market", "")),
            sentiment=lambda: FakeRunner(
                sentiment, tracker, "sentiment", noise.get("sentiment", "")
            ),
            feasibility=lambda: FakeRunner(
                feasibility, tracker, "feasibility", noise.get("feasibility", "")
            ),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
        )
        inputs: dict[str, object] = {"idea": scope.startup_idea, "no_gates": True}
        if sequential is not None:
            inputs["sequential_branches"] = sequential

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path):
                flow = ValidatorFlow(crew_factories=factories)
                stack = contextlib.ExitStack()
                with stack:
                    if capture is not None:
                        stack.enter_context(capture_events(capture))
                    result = flow.kickoff(inputs=inputs)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"), report.markdown_body
            )
        return result, report

    # ---------------------------------------------------------------- default

    def test_parallel_stays_the_default_for_state_and_for_every_caller(self) -> None:
        # Nothing about an existing call site may change: no argument, no
        # kickoff input, no environment - and the fan-out still fans out.
        self.assertFalse(ValidatorState().sequential_branches)
        tracker = ConcurrencyTracker(expect=3)
        self._run(sequential=None, tracker=tracker)
        self.assertEqual(tracker.maximum, 3)

    def test_validate_entry_point_keeps_parallel_unless_asked(self) -> None:
        scope, market, sentiment, feasibility, verdict, report = fixtures()
        tracker = ConcurrencyTracker(expect=3)
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market, tracker, "market"),
            sentiment=lambda: FakeRunner(sentiment, tracker, "sentiment"),
            feasibility=lambda: FakeRunner(feasibility, tracker, "feasibility"),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
        )
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path):
                parallel = validate(
                    scope.startup_idea, no_gates=True, crew_factories=factories
                )
        self.assertEqual(parallel, report)
        self.assertEqual(tracker.maximum, 3)

    # ------------------------------------------------------------- sequential

    def test_sequential_mode_runs_one_branch_at_a_time_in_graph_order(self) -> None:
        tracker = ConcurrencyTracker()
        self._run(sequential=True, tracker=tracker)

        self.assertEqual(tracker.maximum, 1)
        self.assertEqual(tracker.order, list(BRANCH_ORDER))

    def test_sequential_and_parallel_produce_the_same_report(self) -> None:
        sequential, report = self._run(sequential=True)
        parallel, _ = self._run(sequential=False)

        self.assertIsInstance(sequential, ValidationReport)
        self.assertEqual(sequential, report)
        self.assertEqual(parallel, report)
        self.assertEqual(sequential, parallel)

    def test_sequential_validate_entry_point_serializes_the_branches(self) -> None:
        scope, market, sentiment, feasibility, verdict, report = fixtures()
        tracker = ConcurrencyTracker()
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market, tracker, "market"),
            sentiment=lambda: FakeRunner(sentiment, tracker, "sentiment"),
            feasibility=lambda: FakeRunner(feasibility, tracker, "feasibility"),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
        )
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path):
                result = validate(
                    scope.startup_idea,
                    no_gates=True,
                    sequential_branches=True,
                    crew_factories=factories,
                )
        self.assertEqual(result, report)
        self.assertEqual(tracker.maximum, 1)

    # ------------------------------------------------------- identical graph

    def test_flow_definition_and_graph_descriptor_are_identical_in_both_modes(
        self,
    ) -> None:
        # A sequential fallback implemented by adding a second Flow definition
        # would show up here: two nodes fewer, two join edges fewer, a new
        # graph version, and a UI drawing a topology that is not the system.
        from brief_crew.service.graph import (
            VALIDATOR_CREW_WIRING,
            VALIDATOR_GRAPH,
            VALIDATOR_OVERLAY,
            VALIDATOR_WORKFLOW_ID,
            VALIDATOR_WORKFLOW_NAME,
            build_graph_descriptor,
        )

        before = build_flow_structure(ValidatorFlow)
        self._run(sequential=True)
        after = build_flow_structure(ValidatorFlow)
        self.assertEqual(before, after)

        # Every input the canonical VALIDATOR_GRAPH is built from, including
        # the crew wiring: the version hashes the rendered nodes, so omitting
        # an input here would compare a differently-built graph and fail for a
        # reason that has nothing to do with sequential mode.
        descriptor = build_graph_descriptor(
            ValidatorFlow,
            workflow_id=VALIDATOR_WORKFLOW_ID,
            workflow_name=VALIDATOR_WORKFLOW_NAME,
            overlay=VALIDATOR_OVERLAY,
            crew_wiring=VALIDATOR_CREW_WIRING,
        )
        self.assertEqual(descriptor.version, VALIDATOR_GRAPH.version)
        self.assertEqual(
            [node.id for node in descriptor.nodes],
            [node.id for node in VALIDATOR_GRAPH.nodes],
        )

        definition = ValidatorFlow.flow_definition()
        for branch, node_id in BRANCH_NODES.items():
            self.assertEqual(definition.methods[node_id].listen, "scope_approved")
            self.assertIn(branch, BRANCH_ORDER)
        self.assertEqual(
            set(definition.methods["synthesize"].listen["and"]),
            set(BRANCH_NODES.values()),
        )

    def test_frame_attribution_is_identical_in_both_modes(self) -> None:
        registry = NodeRegistry.from_flow_structure(build_flow_structure(ValidatorFlow))

        def node_counts(sequential: bool) -> dict[str, int]:
            buffer = FrameBuffer()
            run_id = f"test-{'seq' if sequential else 'par'}"
            adapter = StreamSinkAdapter(
                run_id=run_id, buffer=buffer, registry=registry
            )
            self._run(
                sequential=sequential,
                capture=CaptureContext(run_id=run_id, adapter=adapter),
            )
            counts: dict[str, int] = {}
            frames = buffer.replay(after=0, limit=500)
            for frame in frames:
                if frame.event_type in (UIEventType.NODE_START, UIEventType.NODE_END):
                    counts[frame.node_id] = counts.get(frame.node_id, 0) + 1
            return counts

        parallel = node_counts(False)
        sequential = node_counts(True)

        self.assertEqual(parallel, sequential)
        for node_id in BRANCH_NODES.values():
            self.assertEqual(sequential.get(node_id), 2, node_id)
        self.assertNotIn(QUARANTINE_NODE_ID, sequential)

    # ------------------------------------------------------------- turnstile

    def test_a_branch_that_never_arrives_degrades_instead_of_deadlocking(self) -> None:
        # Ordering is a readability and memory nicety. It must never be able to
        # hang a run, or the service run queue stalls behind it forever.
        sequencer = BranchSequencer(timeout_s=0.05)
        started = time.monotonic()
        with sequencer.turn("feasibility", enabled=True):
            pass
        self.assertLess(time.monotonic() - started, 5.0)
        # The turnstile resynchronised rather than drifting: market is next.
        entered: list[str] = []
        with sequencer.turn("market", enabled=True):
            entered.append("market")
        self.assertEqual(entered, ["market"])

    def test_disabled_turnstile_never_blocks(self) -> None:
        sequencer = BranchSequencer(timeout_s=0.01)
        with sequencer.turn("feasibility", enabled=False):
            pass
        self.assertEqual(sequencer.served, 0)


class BranchOutputPrefixTests(unittest.TestCase):
    """F40 / PRD 7.5: three crews on one stdout must stay attributable."""

    def setUp(self) -> None:
        patch(
            "brief_crew.validator_flow.lookup_branch_cache", return_value=[]
        ).start()
        patch(
            "brief_crew.validator_flow.index_captured_evidence", return_value=0
        ).start()
        self.addCleanup(patch.stopall)

    def test_concurrent_branch_output_carries_its_node_name(self) -> None:
        scope, market, sentiment, feasibility, verdict, report = fixtures()
        tracker = ConcurrencyTracker(expect=3)
        chatter = {
            "market": "MARKET-LINE",
            "sentiment": "SENTIMENT-LINE",
            "feasibility": "FEASIBILITY-LINE",
        }
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market, tracker, "market", chatter["market"]),
            sentiment=lambda: FakeRunner(
                sentiment, tracker, "sentiment", chatter["sentiment"]
            ),
            feasibility=lambda: FakeRunner(
                feasibility, tracker, "feasibility", chatter["feasibility"]
            ),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
        )

        buffer = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path):
                with contextlib.redirect_stdout(buffer):
                    ValidatorFlow(crew_factories=factories).kickoff(
                        inputs={"idea": scope.startup_idea, "no_gates": True}
                    )

        printed = buffer.getvalue()
        # All three really did overlap, so this is the interleaved case.
        self.assertEqual(tracker.maximum, 3)
        for branch, line in chatter.items():
            node_id = BRANCH_NODES[branch]
            self.assertIn(f"[{node_id}] {line}", printed)
        # No copy escaped without its tag.
        for line in printed.splitlines():
            for branch, text in chatter.items():
                if text in line:
                    self.assertTrue(
                        line.startswith(f"[{BRANCH_NODES[branch]}]"),
                        f"untagged branch output: {line!r}",
                    )

    def test_sequential_branch_output_is_tagged_too(self) -> None:
        scope, market, sentiment, feasibility, verdict, report = fixtures()
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market, None, "market", "M"),
            sentiment=lambda: FakeRunner(sentiment, None, "sentiment", "S"),
            feasibility=lambda: FakeRunner(feasibility, None, "feasibility", "F"),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
        )
        buffer = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path):
                with contextlib.redirect_stdout(buffer):
                    ValidatorFlow(crew_factories=factories).kickoff(
                        inputs={
                            "idea": scope.startup_idea,
                            "no_gates": True,
                            "sequential_branches": True,
                        }
                    )
        printed = buffer.getvalue()
        self.assertIn("[research_market] M", printed)
        self.assertIn("[research_sentiment] S", printed)
        self.assertIn("[research_feasibility] F", printed)

    def test_partial_writes_are_held_until_the_line_ends(self) -> None:
        sink = io.StringIO()
        stream = PrefixedStdout(sink)
        with patch.object(sys, "stdout", stream):
            with branch_output("research_market"):
                stream.write("half ")
                self.assertEqual(sink.getvalue(), "")
                stream.write("a line\nnext")
                self.assertEqual(sink.getvalue(), "[research_market] half a line\n")
        self.assertEqual(
            sink.getvalue(),
            "[research_market] half a line\n[research_market] next\n",
        )

    def test_stdout_is_restored_and_untouched_outside_a_branch(self) -> None:
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):
            original = sys.stdout
            with branch_output("research_market"):
                self.assertIsInstance(sys.stdout, PrefixedStdout)
                print("inside")
            self.assertIs(sys.stdout, original)
            print("outside")
        self.assertEqual(
            sink.getvalue(), "[research_market] inside\noutside\n"
        )

    def test_nested_branches_restore_the_stream_only_once_all_have_left(self) -> None:
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):
            original = sys.stdout
            with branch_output("research_market"):
                with branch_output("research_sentiment"):
                    print("inner")
                self.assertIsInstance(sys.stdout, PrefixedStdout)
                print("outer")
            self.assertIs(sys.stdout, original)
        self.assertEqual(
            sink.getvalue(),
            "[research_sentiment] inner\n[research_market] outer\n",
        )


if __name__ == "__main__":
    unittest.main()

class InProcessGateReviseTests(unittest.TestCase):
    """The revise loop when the gate is answered on a live flow object.

    Every shipped gate reply travels ``from_pending()`` -> ``resume()``, which
    builds a *new* flow, and CrewAI's one-shot suppression of a multi-event
    ``or_()`` listener lives in a ``PrivateAttr`` that is never persisted. So
    the durable path has always closed the loop and always will. These tests
    cover the other half - answering a gate in process - which is what a
    scripted provider, a future auto mode, and any in-process test actually do,
    and where the suppression used to end the run silently after a paid model
    call.
    """

    def setUp(self) -> None:
        patch("brief_crew.validator_flow.lookup_branch_cache", return_value=[]).start()
        self.addCleanup(patch.stopall)

    def test_in_process_revise_reopens_both_gates_and_still_reports(self) -> None:
        scope, market, sentiment, feasibility, verdict, report = fixtures()
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market),
            sentiment=lambda: FakeRunner(sentiment),
            feasibility=lambda: FakeRunner(feasibility),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
        )
        replies = [
            '{"decision": "revise", "feedback": "narrow it to dental clinics"}',
            '{"decision": "approve"}',
            '{"decision": "revise", "feedback": "recheck the demand score"}',
            '{"decision": "approve"}',
        ]
        asked: list[str] = []

        def scripted(_provider: object, context: object, _flow: object) -> str:
            asked.append(context.method_name)
            return replies.pop(0)

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path), patch.object(
                ValidatorFeedbackProvider, "request_feedback", scripted
            ):
                flow = ValidatorFlow(crew_factories=factories)
                result = flow.kickoff(inputs={"idea": scope.startup_idea})

            # Each gate is asked twice: once for the revise, once for the
            # approve that follows it. Before the fix this list was
            # ["confirm_scope"] and the run ended there, having returned a
            # ScopedIdea that reads exactly like success.
            self.assertEqual(
                asked,
                ["confirm_scope", "confirm_scope", "review_verdict", "review_verdict"],
            )
            self.assertEqual(result, report)
            self.assertEqual(flow.state.scope_revision, "narrow it to dental clinics")
            self.assertEqual(flow.state.verdict_revision, "recheck the demand score")
            self.assertEqual(flow.state.scope_route, "scope_approved")
            self.assertEqual(flow.state.verdict_route, "verdict_approved")
            self.assertEqual(
                output_path.read_text(encoding="utf-8"), report.markdown_body
            )

    def test_crewai_still_exposes_the_or_listener_rearm_hook(self) -> None:
        """Pin the private CrewAI hook the revise loop depends on.

        ``revise_scope`` and ``revise_verdict`` call ``_discard_or_listener``
        because CrewAI offers no public way to re-arm a fired multi-event
        ``or_()`` listener. If an upgrade renames or removes it, fail here with
        a legible message rather than deep inside a paid run - and the two
        preconditions the call sites rely on are asserted with it: it takes one
        name, and it is a no-op when that listener has not fired, which is
        exactly the state on the durable resume path.
        """
        flow = ValidatorFlow()
        discard = getattr(flow, "_discard_or_listener", None)
        self.assertTrue(
            callable(discard),
            "crewai no longer exposes Flow._discard_or_listener; the revise "
            "loop in validator_flow.py needs the router variant instead",
        )
        self.assertEqual(flow._fired_or_listeners, set())
        discard("confirm_scope")
        self.assertEqual(flow._fired_or_listeners, set())
