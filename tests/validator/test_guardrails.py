from __future__ import annotations

import json
import unittest
from dataclasses import dataclass

from brief_crew.schemas import (
    Competitor,
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
from brief_crew.validator_guardrails import (
    DEMAND_ANCHORS,
    check_findings,
    check_report_mechanics,
    check_rubric,
    check_scope,
    compute_evidence_counts,
    make_report_guardrail,
    make_rubric_guardrail,
    parse_raw_model,
    token_overlap,
)


@dataclass
class Output:
    raw: str


MARKET_URL = "https://example.com/market"
COMPETITOR_URL = "https://example.com/competitor"
THREAD_URL = "https://news.ycombinator.com/item?id=1"
REPO_URL = "https://github.com/example/project"


def evidence() -> Evidence:
    return Evidence(
        claim="The segment pays for scheduling software.",
        url=MARKET_URL,
        publisher="Example",
        dated="2026-08-01",
        retrieved_via="firecrawl",
    )


def market_findings(status: str = "ok") -> MarketFindings:
    source_list = [evidence()]
    return MarketFindings(
        sources=source_list,
        source_urls=[source.url for source in source_list],
        gaps=[] if status == "ok" else ["Market lookup failed."],
        tool_status=status,
        competitors=[
            Competitor(
                name="Example competitor",
                pricing="not published",
                vendor_owned=False,
                url=COMPETITOR_URL,
            )
        ],
    )


def sentiment_findings() -> SentimentFindings:
    source = Thread(
        classification="HAS_PROBLEM",
        quote="We maintain this manually.",
        url=THREAD_URL,
        date="2026-07-01",
    )
    return SentimentFindings(
        sources=[source],
        source_urls=[source.url],
        gaps=[],
        tool_status="ok",
    )


def feasibility_findings() -> FeasibilityFindings:
    source = Repo(
        name="example/project",
        license_permits_commercial=True,
        months_since_push=1,
        relevance="PARTIAL",
        url=REPO_URL,
    )
    return FeasibilityFindings(
        sources=[source],
        source_urls=[source.url],
        gaps=[],
        tool_status="ok",
    )


def dimension(value: int, anchor: str, urls: list[str] | None = None) -> DimensionScore:
    return DimensionScore(
        score=value,
        anchor_matched=anchor,
        evidence_urls=urls or [MARKET_URL],
        evidence_thin=False,
    )


def synthesis(
    market: MarketFindings,
    sentiment: SentimentFindings,
    feasibility: FeasibilityFindings,
) -> Verdict:
    return Verdict(
        demand=dimension(3, DEMAND_ANCHORS[3], [THREAD_URL]),
        market=dimension(3, "Market anchor", [MARKET_URL]),
        competitive_room=dimension(3, "Competitive anchor", [COMPETITOR_URL]),
        feasibility=dimension(3, "Feasibility anchor", [REPO_URL]),
        headroom_over_free=dimension(3, "Headroom anchor", [REPO_URL]),
        evidence_counts=compute_evidence_counts(market, sentiment, feasibility),
        market_coverage=0.8,
        sentiment_coverage=0.7,
        feasibility_coverage=0.8,
        median_market_source_age_months=6,
        branches_ok=3,
        cheapest_next_test="Interview five target users.",
    )


class ParsingAndScopeTests(unittest.TestCase):
    def test_parse_fenced_json(self) -> None:
        raw = "```json\n" + json.dumps({
            "startup_idea": "Idea",
            "category": "Category",
            "target_user": "User",
            "problem": "Problem",
            "technology_claim": "Claim",
            "market_query": "Query",
            "community_queries": ["Community"],
            "tech_queries": ["Technology"],
            "assumptions": ["One", "Two", "Three"],
            "scoping_gaps": ["Unknown budget"],
            "as_of": "2026-08-29",
        }) + "\n```"

        parsed = parse_raw_model(raw, ScopedIdea)

        self.assertEqual(parsed.category, "Category")

    def test_scope_guardrail_returns_raw_unchanged(self) -> None:
        scope = ScopedIdea(
            startup_idea="Idea",
            category="Category",
            target_user="User",
            problem="Problem",
            technology_claim="Claim",
            market_query="Query",
            community_queries=["Community"],
            tech_queries=["Technology"],
            assumptions=["One", "Two", "Three"],
            scoping_gaps=["Unknown budget"],
            as_of="2026-08-29",
        )
        raw = scope.model_dump_json()

        self.assertEqual(check_scope(Output(raw)), (True, raw))

    def test_scope_guardrail_returns_actionable_schema_error(self) -> None:
        payload = {
            "startup_idea": "Idea",
            "category": "Category",
            "target_user": "User",
            "problem": "Problem",
            "technology_claim": "Claim",
            "market_query": "Query",
            "community_queries": ["Community"],
            "tech_queries": ["Technology"],
            "assumptions": ["Only one"],
            "scoping_gaps": [],
            "as_of": "2026-08-29",
        }

        passed, message = check_scope(Output(json.dumps(payload)))

        self.assertFalse(passed)
        self.assertIn("assumptions", message)
        self.assertIn("scoping_gaps", message)


class FindingsTests(unittest.TestCase):
    def test_url_closure_covers_nested_competitors(self) -> None:
        guardrail = check_findings("market", [MARKET_URL])

        passed, message = guardrail(Output(market_findings().model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("URL_CLOSURE", message)
        self.assertIn(COMPETITOR_URL, message)

    def test_status_honesty_rejects_sources_after_failure(self) -> None:
        findings = market_findings(status="failed")
        guardrail = check_findings("market", [MARKET_URL, COMPETITOR_URL])

        passed, message = guardrail(Output(findings.model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("sources must be empty", message)

    def test_status_honesty_requires_failure_gap(self) -> None:
        findings = MarketFindings(
            sources=[],
            source_urls=[],
            gaps=[],
            tool_status="rate_limited",
            competitors=[],
        )
        guardrail = check_findings("market", [])

        passed, message = guardrail(Output(findings.model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("add a gap", message)


class RubricTests(unittest.TestCase):
    def test_token_overlap_is_symmetric_and_bounded(self) -> None:
        self.assertEqual(token_overlap("one two", "one two"), 1.0)
        self.assertEqual(token_overlap("one", "one two"), 0.5)
        self.assertEqual(token_overlap("one two three", "one two"), 2 / 3)

    def test_rubric_guardrail_rejects_wrong_anchor(self) -> None:
        market = market_findings()
        sentiment = sentiment_findings()
        feasibility = feasibility_findings()
        result = synthesis(market, sentiment, feasibility).model_copy(
            update={"demand": dimension(3, "Demand seems plausible", [THREAD_URL])}
        )

        passed, message = check_rubric(Output(result.model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("ANCHOR_D", message)

    def test_contextual_rubric_guardrail_recomputes_counts(self) -> None:
        market = market_findings()
        sentiment = sentiment_findings()
        feasibility = feasibility_findings()
        result = synthesis(market, sentiment, feasibility).model_copy(
            update={"evidence_counts": {"market_sources": 99}}
        )
        guardrail = make_rubric_guardrail(market, sentiment, feasibility)

        passed, message = guardrail(Output(result.model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("EVIDENCE_COUNTS", message)

    def test_level_one_anchor_must_be_verbatim(self) -> None:
        market = market_findings()
        sentiment = sentiment_findings()
        feasibility = feasibility_findings()
        result = synthesis(market, sentiment, feasibility).model_copy(
            update={"market": dimension(1, "Evidence is thin", [MARKET_URL])}
        )

        passed, message = check_rubric(Output(result.model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("score 1 must use", message)


class ReportTests(unittest.TestCase):
    def test_report_guardrail_returns_raw_unchanged(self) -> None:
        report = ValidationReport(
            markdown_body=f"# Validation report\n\nSummary.\n\n## Sources\n{MARKET_URL}",
            provisional=False,
            thin_dimensions=[],
            sources=[evidence()],
        )
        raw = report.model_dump_json()

        self.assertEqual(check_report_mechanics(Output(raw)), (True, raw))

    def test_report_rejects_unlisted_body_url(self) -> None:
        report = ValidationReport(
            markdown_body=(
                f"# Validation report\n\nSummary.\n\n## Sources\n{MARKET_URL}\n"
                "https://example.com/invented"
            ),
            provisional=False,
            thin_dimensions=[],
            sources=[evidence()],
        )

        passed, message = check_report_mechanics(Output(report.model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("REPORT_URL_CLOSURE", message)

    def test_low_confidence_language_is_rejected(self) -> None:
        market = market_findings()
        sentiment = sentiment_findings()
        feasibility = feasibility_findings()
        result = synthesis(market, sentiment, feasibility).model_copy(
            update={
                "market_coverage": 0.1,
                "sentiment_coverage": 0.1,
                "feasibility_coverage": 0.1,
            }
        )
        result = Verdict.model_validate(result.model_dump())
        report = ValidationReport(
            markdown_body=(
                f"# Validation report\n\nThe evidence clearly confirms the idea.\n\n"
                f"## Sources\n{MARKET_URL}"
            ),
            provisional=False,
            thin_dimensions=["D", "M", "C", "F", "X"],
            sources=[evidence()],
        )
        guardrail = make_report_guardrail(result, [MARKET_URL])

        passed, message = guardrail(Output(report.model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("LOW_CONFIDENCE_CALIBRATION", message)

    def test_moderate_reject_requires_provisional_title_and_summary(self) -> None:
        market = market_findings()
        sentiment = sentiment_findings()
        feasibility = feasibility_findings()
        result = synthesis(market, sentiment, feasibility).model_copy(
            update={
                "demand": dimension(1, DEMAND_ANCHORS[1]),
                "market": dimension(1, "Evidence does not reach this question"),
                "competitive_room": dimension(1, "Evidence does not reach this question"),
                "feasibility": dimension(1, "Evidence does not reach this question"),
                "headroom_over_free": dimension(1, "Evidence does not reach this question"),
                "market_coverage": 0.5,
                "sentiment_coverage": 0.5,
                "feasibility_coverage": 0.5,
            }
        )
        result = Verdict.model_validate(result.model_dump())
        self.assertTrue(result.provisional)
        report = ValidationReport(
            markdown_body=f"# Validation report\n\nSummary.\n\n## Sources\n{MARKET_URL}",
            provisional=True,
            thin_dimensions=["D", "M", "C", "F", "X"],
            sources=[evidence()],
        )
        guardrail = make_report_guardrail(result, [MARKET_URL])

        passed, message = guardrail(Output(report.model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("PROVISIONAL_TITLE", message)
        self.assertIn("PROVISIONAL_SUMMARY", message)


if __name__ == "__main__":
    unittest.main()