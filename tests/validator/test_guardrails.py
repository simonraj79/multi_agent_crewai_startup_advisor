from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone

from brief_crew import config as project_config
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
    COMPETITIVE_ROOM_ANCHORS,
    DEMAND_ANCHORS,
    FEASIBILITY_ANCHORS,
    HEADROOM_ANCHORS,
    LEVEL_ONE_ANCHOR,
    MARKET_ANCHORS,
    RUBRIC_ANCHORS,
    check_findings,
    check_report_mechanics,
    check_rubric,
    check_scope,
    compute_confidence_inputs,
    compute_evidence_counts,
    confidence_problems,
    make_report_guardrail,
    make_rubric_guardrail,
    parse_raw_model,
    rubric_problems,
    token_overlap,
)

NOW = datetime(2026, 8, 29, tzinfo=timezone.utc)


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
    /,
    **overrides: object,
) -> Verdict:
    """A verdict that passes every mechanical check, so a test can break one."""
    inputs = compute_confidence_inputs(market, sentiment, feasibility, now=NOW)
    values: dict[str, object] = {
        "demand": dimension(3, DEMAND_ANCHORS[3], [THREAD_URL]),
        "market": dimension(3, MARKET_ANCHORS[3], [MARKET_URL]),
        "competitive_room": dimension(3, COMPETITIVE_ROOM_ANCHORS[3], [COMPETITOR_URL]),
        "feasibility": dimension(3, FEASIBILITY_ANCHORS[3], [REPO_URL]),
        "headroom_over_free": dimension(3, HEADROOM_ANCHORS[3], [REPO_URL]),
        "evidence_counts": compute_evidence_counts(market, sentiment, feasibility),
        "cheapest_next_test": "Interview five target users.",
        "kill_criteria": ["Fewer than 2 of 10 clinics keep a manual rota."],
        **inputs,
    }
    values.update(overrides)
    return Verdict.model_validate(values)


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

    def test_status_honesty_rejects_paying_segments_after_failure(self) -> None:
        findings = MarketFindings(
            sources=[],
            source_urls=[],
            gaps=["Market lookup failed."],
            tool_status="failed",
            competitors=[],
            paying_segments=["Independent clinics"],
        )
        guardrail = check_findings("market", [])

        passed, message = guardrail(Output(findings.model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("paying_segments must be empty", message)

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

    def test_clean_verdict_passes_every_mechanical_check(self) -> None:
        market = market_findings()
        sentiment = sentiment_findings()
        feasibility = feasibility_findings()
        result = synthesis(market, sentiment, feasibility)

        self.assertEqual(
            rubric_problems(result, findings=(market, sentiment, feasibility), now=NOW),
            [],
        )

    def test_every_rubric_dimension_is_anchored(self) -> None:
        """F15: four fifths of the rubric used to accept any anchor text."""
        self.assertEqual(set(RUBRIC_ANCHORS), {"D", "M", "C", "F", "X"})
        for code, ladder in RUBRIC_ANCHORS.items():
            with self.subTest(dimension=code):
                self.assertEqual(sorted(ladder), [0, 1, 2, 3, 4, 5])
                self.assertTrue(all(text.strip() for text in ladder.values()))
                self.assertTrue(ladder[1].startswith(LEVEL_ONE_ANCHOR))

    def test_rubric_anchors_are_the_config_constants(self) -> None:
        """The guardrail and the prompt must read one constant, not two."""
        self.assertIs(RUBRIC_ANCHORS, project_config.RUBRIC_ANCHORS)
        self.assertIs(DEMAND_ANCHORS, project_config.DEMAND_ANCHORS)
        self.assertIs(MARKET_ANCHORS, project_config.MARKET_ANCHORS)
        self.assertIs(COMPETITIVE_ROOM_ANCHORS, project_config.COMPETITIVE_ROOM_ANCHORS)
        self.assertIs(FEASIBILITY_ANCHORS, project_config.FEASIBILITY_ANCHORS)
        self.assertIs(HEADROOM_ANCHORS, project_config.HEADROOM_ANCHORS)

    def test_paraphrase_is_rejected_on_every_dimension(self) -> None:
        market = market_findings()
        sentiment = sentiment_findings()
        feasibility = feasibility_findings()
        fields = {
            "D": "demand",
            "M": "market",
            "C": "competitive_room",
            "F": "feasibility",
            "X": "headroom_over_free",
        }

        for code, field_name in fields.items():
            with self.subTest(dimension=code):
                result = synthesis(market, sentiment, feasibility).model_copy(
                    update={field_name: dimension(3, "It looks about right to me.", [MARKET_URL])}
                )

                passed, message = check_rubric(Output(result.model_dump_json()))

                self.assertFalse(passed)
                self.assertIn(f"ANCHOR_{code}", message)

    def test_verbatim_anchor_is_accepted_on_every_dimension(self) -> None:
        market = market_findings()
        sentiment = sentiment_findings()
        feasibility = feasibility_findings()
        ladders = {
            "demand": DEMAND_ANCHORS,
            "market": MARKET_ANCHORS,
            "competitive_room": COMPETITIVE_ROOM_ANCHORS,
            "feasibility": FEASIBILITY_ANCHORS,
            "headroom_over_free": HEADROOM_ANCHORS,
        }

        for value in (0, 2, 3, 4, 5):
            with self.subTest(score=value):
                result = synthesis(
                    market,
                    sentiment,
                    feasibility,
                    **{
                        field_name: dimension(value, ladder[value], [MARKET_URL])
                        for field_name, ladder in ladders.items()
                    },
                )

                self.assertEqual(rubric_problems(result), [])

    def test_missing_kill_criteria_is_rejected(self) -> None:
        market = market_findings()
        sentiment = sentiment_findings()
        feasibility = feasibility_findings()
        result = synthesis(market, sentiment, feasibility, kill_criteria=[])

        passed, message = check_rubric(Output(result.model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("KILL_CRITERIA", message)

    def test_contextual_rubric_guardrail_recomputes_counts(self) -> None:
        market = market_findings()
        sentiment = sentiment_findings()
        feasibility = feasibility_findings()
        result = synthesis(market, sentiment, feasibility).model_copy(
            update={"evidence_counts": {"market_sources": 99}}
        )
        guardrail = make_rubric_guardrail(market, sentiment, feasibility, now=NOW)

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


class ConfidenceInputTests(unittest.TestCase):
    """F11 - the confidence inputs are computed, not accepted."""

    def branches(self):
        return market_findings(), sentiment_findings(), feasibility_findings()

    def test_inputs_are_derived_from_the_branch_lists(self) -> None:
        market, sentiment, feasibility = self.branches()

        inputs = compute_confidence_inputs(market, sentiment, feasibility, now=NOW)

        target = project_config.VALIDATOR_COVERAGE_TARGET_SOURCES
        self.assertEqual(inputs["market_coverage"], 1 / target)
        self.assertEqual(inputs["sentiment_coverage"], 1 / target)
        self.assertEqual(inputs["feasibility_coverage"], 1 / target)
        self.assertEqual(inputs["branches_ok"], 3)
        # The single market source is dated 2026-08-01, 28 days before NOW.
        self.assertEqual(inputs["median_market_source_age_months"], 0.9)

    def test_coverage_saturates_at_one(self) -> None:
        market, sentiment, feasibility = self.branches()
        threads = [
            Thread(
                classification="HAS_PROBLEM",
                quote=f"Quote {index}.",
                url=f"https://news.ycombinator.com/item?id={index}",
                date="2026-07-01",
            )
            for index in range(9)
        ]
        wide = SentimentFindings(
            sources=threads,
            source_urls=[thread.url for thread in threads],
            gaps=[],
            tool_status="ok",
        )

        inputs = compute_confidence_inputs(market, wide, feasibility, now=NOW)

        self.assertEqual(inputs["sentiment_coverage"], 1.0)

    def test_asserted_coverage_is_rejected_against_the_evidence(self) -> None:
        market, sentiment, feasibility = self.branches()
        result = synthesis(
            market,
            sentiment,
            feasibility,
            market_coverage=0.9,
            sentiment_coverage=0.9,
            feasibility_coverage=0.9,
        )
        guardrail = make_rubric_guardrail(market, sentiment, feasibility, now=NOW)

        passed, message = guardrail(Output(result.model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("COVERAGE_MARKET", message)
        self.assertIn("COVERAGE_SENTIMENT", message)
        self.assertIn("COVERAGE_FEASIBILITY", message)
        self.assertIn("0.20", message)

    def test_only_relevant_repositories_count_towards_coverage(self) -> None:
        market, sentiment, _ = self.branches()
        irrelevant = Repo(
            name="example/unrelated",
            license_permits_commercial=True,
            months_since_push=1,
            relevance="IRRELEVANT",
            url="https://github.com/example/unrelated",
        )
        feasibility = FeasibilityFindings(
            sources=[irrelevant],
            source_urls=[irrelevant.url],
            gaps=[],
            tool_status="ok",
        )

        inputs = compute_confidence_inputs(market, sentiment, feasibility, now=NOW)

        self.assertEqual(inputs["feasibility_coverage"], 0.0)

    def test_stale_median_age_is_rejected_by_staleness_band(self) -> None:
        market, sentiment, feasibility = self.branches()
        result = synthesis(
            market,
            sentiment,
            feasibility,
            median_market_source_age_months=30.0,
        )

        problems = confidence_problems(result, market, sentiment, feasibility, now=NOW)

        self.assertEqual(len(problems), 1)
        self.assertIn("MEDIAN_SOURCE_AGE", problems[0])

    def test_a_closer_age_in_the_same_band_is_accepted(self) -> None:
        market, sentiment, feasibility = self.branches()
        result = synthesis(
            market,
            sentiment,
            feasibility,
            median_market_source_age_months=2.0,
        )

        self.assertEqual(
            confidence_problems(result, market, sentiment, feasibility, now=NOW), []
        )

    def test_median_age_is_null_exactly_when_no_market_source_exists(self) -> None:
        empty = MarketFindings(
            sources=[],
            source_urls=[],
            gaps=["Firecrawl returned nothing."],
            tool_status="empty",
            competitors=[],
        )
        sentiment = sentiment_findings()
        feasibility = feasibility_findings()

        inputs = compute_confidence_inputs(empty, sentiment, feasibility, now=NOW)
        self.assertIsNone(inputs["median_market_source_age_months"])

        asserted = synthesis(
            empty,
            sentiment,
            feasibility,
            evidence_counts=compute_evidence_counts(empty, sentiment, feasibility),
            median_market_source_age_months=6.0,
            branches_ok=2,
            market_coverage=0.0,
        )
        problems = confidence_problems(asserted, empty, sentiment, feasibility, now=NOW)

        self.assertEqual(len(problems), 1)
        self.assertIn("MEDIAN_SOURCE_AGE", problems[0])


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