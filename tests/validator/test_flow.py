from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from brief_crew.config import CHEAP_MODEL
from crewai.flow.async_feedback import HumanFeedbackPending, PendingFeedbackContext
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
    ValidatorCrewFactories,
    ValidatorFeedbackProvider,
    ValidatorFlow,
    validate,
)
from brief_crew.validator_guardrails import DEMAND_ANCHORS, compute_evidence_counts

MARKET_URL = "https://example.com/market"
THREAD_URL = "https://news.ycombinator.com/item?id=1"
REPO_URL = "https://github.com/example/project"


class FakeRunner:
    def __init__(self, result: object, tracker: ConcurrencyTracker | None = None) -> None:
        self.result = result
        self.tracker = tracker
        self.inputs: list[dict[str, object]] = []

    def kickoff(self, inputs: dict[str, object]) -> object:
        self.inputs.append(inputs)
        if self.tracker is not None:
            self.tracker.enter()
        return self.result


class ConcurrencyTracker:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0
        self.lock = threading.Lock()

    def enter(self) -> None:
        with self.lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
        time.sleep(0.08)
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
        tracker = ConcurrencyTracker()
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
        self.assertEqual(scope_gate.llm, CHEAP_MODEL)
        self.assertEqual(verdict_gate.llm, CHEAP_MODEL)
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


if __name__ == "__main__":
    unittest.main()