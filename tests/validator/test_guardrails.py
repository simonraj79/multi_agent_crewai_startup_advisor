from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import ValidationError

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
    anchor_problems,
    check_findings,
    check_report_mechanics,
    check_rubric,
    check_scope,
    compute_confidence_inputs,
    compute_evidence_counts,
    confidence_problems,
    make_report_guardrail,
    make_rubric_guardrail,
    is_live_free_substitute,
    is_reusable_repository,
    median_market_source_age_months,
    parse_raw_model,
    rubric_problems,
    rubric_support,
    score_support_problems,
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
    """A verdict that passes every mechanical check, so a test can break one.

    Demand sits at 2 rather than 3 because `sentiment_findings()` carries one
    problem thread, and `score_support_problems` now holds every score to what
    the branch lists can carry. The other four are at 3, which their one-source
    fixtures do support.
    """
    inputs = compute_confidence_inputs(market, sentiment, feasibility, now=NOW)
    values: dict[str, object] = {
        "demand": dimension(2, DEMAND_ANCHORS[2], [THREAD_URL]),
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

    def market_with(self, *dates: tuple[str, bool]) -> MarketFindings:
        """A market branch of `(dated, dated_is_retrieval_time)` sources."""
        sources = [
            Evidence(
                claim=f"Claim {index}.",
                url=f"https://example.com/source-{index}",
                publisher="Example",
                dated=dated,
                dated_is_retrieval_time=is_fallback,
                retrieved_via="firecrawl",
            )
            for index, (dated, is_fallback) in enumerate(dates)
        ]
        return MarketFindings(
            sources=sources,
            source_urls=[source.url for source in sources],
            gaps=[],
            tool_status="ok",
            competitors=[],
        )

    def test_a_retrieval_date_is_not_a_fresh_publication_date(self) -> None:
        """F12. Every source was fetched today and none published a date.

        The old code took the retrieval timestamp as the publication date, so
        this branch scored a 0.0-month median and a 1.00 staleness multiplier -
        maximum confidence about recency it had measured nothing about.
        """
        undated = self.market_with(
            ("2026-08-29T00:00:00Z", True),
            ("2026-08-29T00:00:00Z", True),
            ("2026-08-29T00:00:00Z", True),
        )
        _, sentiment, feasibility = self.branches()

        inputs = compute_confidence_inputs(undated, sentiment, feasibility, now=NOW)

        self.assertIsNone(inputs["median_market_source_age_months"])
        self.assertEqual(
            median_market_source_age_months(undated.sources, NOW),
            inputs["median_market_source_age_months"],
        )
        # The same three rows, if their dates were real, would be maximally fresh.
        dated = self.market_with(
            ("2026-08-29T00:00:00Z", False),
            ("2026-08-29T00:00:00Z", False),
            ("2026-08-29T00:00:00Z", False),
        )
        self.assertEqual(median_market_source_age_months(dated.sources, NOW), 0.0)

    def test_one_fresh_source_cannot_outvote_unknown_recency(self) -> None:
        mixed = self.market_with(
            ("2026-08-01", False),
            ("2026-08-29T00:00:00Z", True),
            ("2026-08-29T00:00:00Z", True),
        )

        self.assertIsNone(median_market_source_age_months(mixed.sources, NOW))

    def test_a_dated_majority_reports_a_real_published_age(self) -> None:
        mixed = self.market_with(
            ("2026-08-01", False),
            ("2026-08-01", False),
            ("2026-08-29T00:00:00Z", True),
        )

        self.assertEqual(median_market_source_age_months(mixed.sources, NOW), 0.9)

    def test_the_fallback_flag_is_the_only_way_an_age_can_be_unknown(self) -> None:
        """`Evidence.dated` already refuses anything that will not parse, so a
        retrieval-time fallback is the one remaining source of unknown recency -
        and it used to be invisible."""
        with self.assertRaises(ValidationError):
            self.market_with(("not a date at all", False))

    def test_unknown_recency_lowers_the_computed_confidence(self) -> None:
        _, sentiment, feasibility = self.branches()
        dated = self.market_with(("2026-08-01", False))
        undated = self.market_with(("2026-08-29T00:00:00Z", True))

        confident = synthesis(
            dated,
            sentiment,
            feasibility,
            **compute_confidence_inputs(dated, sentiment, feasibility, now=NOW),
        )
        cautious = synthesis(
            undated,
            sentiment,
            feasibility,
            **compute_confidence_inputs(undated, sentiment, feasibility, now=NOW),
        )

        self.assertEqual(confident.median_market_source_age_months, 0.9)
        self.assertIsNone(cautious.median_market_source_age_months)
        # Same coverage, same branches: only the staleness multiplier moved.
        self.assertEqual(cautious.confidence, round(confident.confidence * 0.70, 2))
        self.assertLess(cautious.confidence, confident.confidence)

    def test_an_asserted_fresh_age_is_rejected_when_recency_is_unknown(self) -> None:
        _, sentiment, feasibility = self.branches()
        undated = self.market_with(
            ("2026-08-29T00:00:00Z", True),
            ("2026-08-29T00:00:00Z", True),
        )
        result = synthesis(
            undated,
            sentiment,
            feasibility,
            **{
                **compute_confidence_inputs(undated, sentiment, feasibility, now=NOW),
                "median_market_source_age_months": 0.0,
            },
        )

        problems = confidence_problems(result, undated, sentiment, feasibility, now=NOW)

        self.assertEqual(len(problems), 1)
        self.assertIn("MEDIAN_SOURCE_AGE", problems[0])
        self.assertIn("retrieval-time fallback", problems[0])

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



class CounterTests(unittest.TestCase):
    """F16 - the counters the rewritten ladders actually score on."""

    def sentiment_of(self, *classifications: str) -> SentimentFindings:
        threads = [
            Thread(
                classification=classification,
                quote=f"Quote {index}.",
                url=f"https://news.ycombinator.com/item?id={index}",
                date="2026-08-01",
            )
            for index, classification in enumerate(classifications)
        ]
        return SentimentFindings(
            sources=threads,
            source_urls=[thread.url for thread in threads],
            gaps=[],
            tool_status="ok",
        )

    def feasibility_of(self, *repos: Repo) -> FeasibilityFindings:
        return FeasibilityFindings(
            sources=list(repos),
            source_urls=[repo.url for repo in repos],
            gaps=[],
            tool_status="ok",
        )

    def repo(self, index: int = 0, **overrides: object) -> Repo:
        values: dict[str, object] = {
            "name": f"example/project-{index}",
            "license_permits_commercial": True,
            "months_since_push": 3,
            "relevance": "PARTIAL",
            "url": f"https://github.com/example/project-{index}",
        }
        values.update(overrides)
        return Repo.model_validate(values)

    def test_usable_threads_separate_the_demand_floor_from_a_missed_search(self) -> None:
        """D=0 is a REJECT floor and D=1 is "we did not find out".

        The boundary is whether any thread was on topic at all, and no counter
        could express that, so the Synthesist alone decided which side a run
        landed on.
        """
        found_nothing_relevant = self.sentiment_of("OFF_TOPIC", "OFF_TOPIC")
        found_no_problem = self.sentiment_of("OFF_TOPIC", "OPINION")
        market, feasibility = market_findings(), feasibility_findings()

        self.assertEqual(
            compute_evidence_counts(market, found_nothing_relevant, feasibility)[
                "sentiment_usable_threads"
            ],
            0,
        )
        counts = compute_evidence_counts(market, found_no_problem, feasibility)
        self.assertEqual(counts["sentiment_usable_threads"], 1)
        self.assertEqual(counts["sentiment_problem_threads"], 0)

        support = rubric_support(market, found_nothing_relevant, feasibility, now=NOW)["D"]
        self.assertTrue(support.one_ok)
        self.assertFalse(support.zero_ok)

        # One usable thread that is not a problem thread no longer satisfies the
        # D=0 floor. It used to: `zero_ok = usable >= 1 and problems == 0`, which
        # let a single off-hand OPINION produce a final REJECT / FLOOR_NO_DEMAND
        # at confidence 0.60 with provisional=False - "nobody wants this", on one
        # comment. The floor now needs RUBRIC_FLOOR_MIN_USABLE_THREADS, and the
        # 1-2 thread states fall to level 1 rather than becoming unscorable.
        support = rubric_support(market, found_no_problem, feasibility, now=NOW)["D"]
        self.assertTrue(support.one_ok)
        self.assertFalse(support.zero_ok)

    def test_reusable_repositories_need_a_licence_and_a_known_recent_push(self) -> None:
        market, sentiment = market_findings(), sentiment_findings()
        cases = {
            "reusable": (self.repo(0), True),
            "irrelevant": (self.repo(1, relevance="IRRELEVANT"), False),
            "non commercial": (self.repo(2, license_permits_commercial=False), False),
            "stale": (self.repo(3, months_since_push=30), False),
            "unknown push date": (self.repo(4, months_since_push=None), False),
        }

        for label, (repo, expected) in cases.items():
            with self.subTest(case=label):
                self.assertEqual(is_reusable_repository(repo), expected)

        feasibility = self.feasibility_of(*(repo for repo, _ in cases.values()))
        counts = compute_evidence_counts(market, sentiment, feasibility)

        self.assertEqual(counts["feasibility_reusable_repos"], 1)
        self.assertEqual(counts["feasibility_repos"], 5)

    def test_a_live_free_substitute_is_the_x_kill_and_a_null_flag_is_not(self) -> None:
        """`archived is not True`, deliberately: an unreported flag must score
        as it did before the field existed, never as a dead project."""
        cases = {
            "live, flag unreported": (self.repo(0, relevance="SOLVES_ENTIRELY"), True),
            "live, flag false": (
                self.repo(1, relevance="SOLVES_ENTIRELY", archived=False),
                True,
            ),
            "archived": (self.repo(2, relevance="SOLVES_ENTIRELY", archived=True), False),
            "stale": (
                self.repo(3, relevance="SOLVES_ENTIRELY", months_since_push=24),
                False,
            ),
            "push date unknown": (
                self.repo(4, relevance="SOLVES_ENTIRELY", months_since_push=None),
                False,
            ),
            "only partial": (self.repo(5), False),
        }

        for label, (repo, expected) in cases.items():
            with self.subTest(case=label):
                self.assertEqual(is_live_free_substitute(repo), expected)

        feasibility = self.feasibility_of(*(repo for repo, _ in cases.values()))
        counts = compute_evidence_counts(market_findings(), sentiment_findings(), feasibility)

        self.assertEqual(counts["feasibility_live_substitutes"], 2)
        self.assertEqual(counts["feasibility_complete_repos"], 5)


class ScoreSupportTests(unittest.TestCase):
    """F16 - the anchor check reads the text; this reads the evidence."""

    def threads(self, *specs: tuple[str, str]) -> SentimentFindings:
        """`specs` are (classification, date); a date of "" is undated."""
        threads = [
            Thread(
                classification=classification,
                quote=f"Quote {index}.",
                url=f"https://news.ycombinator.com/item?id={index}",
                date=date or "2026-08-29",
                date_is_retrieval_time=not date,
            )
            for index, (classification, date) in enumerate(specs)
        ]
        return SentimentFindings(
            sources=threads,
            source_urls=[thread.url for thread in threads],
            gaps=[],
            tool_status="ok",
        )

    def strong_demand_branch(self) -> SentimentFindings:
        """Five recent problem threads, two of them acted on: enough for D=5."""
        return self.threads(
            ("HAS_PROBLEM", "2026-01-01"),
            ("HAS_PROBLEM", "2026-02-01"),
            ("HAS_PROBLEM", "2026-03-01"),
            ("PAYS", "2026-04-01"),
            ("BUILT_WORKAROUND", "2026-05-01"),
        )

    def scored(self, code: str, value: int) -> dict[str, object]:
        field_name = {
            "D": "demand",
            "M": "market",
            "C": "competitive_room",
            "F": "feasibility",
            "X": "headroom_over_free",
        }[code]
        return {field_name: dimension(value, RUBRIC_ANCHORS[code][value], [MARKET_URL])}

    def problems(
        self,
        code: str,
        value: int,
        *,
        market: MarketFindings | None = None,
        sentiment: SentimentFindings | None = None,
        feasibility: FeasibilityFindings | None = None,
    ) -> list[str]:
        market = market if market is not None else market_findings()
        sentiment = sentiment if sentiment is not None else sentiment_findings()
        feasibility = feasibility if feasibility is not None else feasibility_findings()
        verdict = synthesis(market, sentiment, feasibility, **self.scored(code, value))
        return [
            problem
            for problem in score_support_problems(
                verdict, market, sentiment, feasibility, now=NOW
            )
            if problem.split(":")[0].endswith(f"_{code}")
        ]

    def test_the_top_anchor_quoted_verbatim_over_two_stale_threads_is_rejected(self) -> None:
        """The gap this closes, stated as the report stated it.

        `anchor_problems` compares `anchor_matched` against the D=5 anchor and
        is perfectly satisfied - the text IS the D=5 anchor. Nothing looked at
        whether five recent problem threads existed.
        """
        stale = self.threads(("HAS_PROBLEM", "2019-01-01"), ("PAYS", "2020-01-01"))
        claim = dimension(5, DEMAND_ANCHORS[5], [MARKET_URL])

        self.assertEqual(anchor_problems("D", claim), [])

        problems = self.problems("D", 5, sentiment=stale)

        self.assertEqual(len(problems), 1)
        self.assertIn("SCORE_SUPPORT_D", problems[0])
        self.assertIn("at most D=2", problems[0])
        self.assertIn("2 problem thread(s)", problems[0])

    def test_undated_threads_cannot_reach_the_recency_clauses(self) -> None:
        """Task 1 and Task 3 meeting: three problem threads, none with a date
        of its own. Before the flag each read as posted today, so "at least 1
        of them dated within 24 months" was automatically satisfied."""
        undated = self.threads(("HAS_PROBLEM", ""), ("HAS_PROBLEM", ""), ("PAYS", ""))
        dated = self.threads(
            ("HAS_PROBLEM", "2026-01-01"),
            ("HAS_PROBLEM", "2026-02-01"),
            ("PAYS", "2026-03-01"),
        )

        self.assertEqual(rubric_support(market_findings(), undated, feasibility_findings(), now=NOW)["D"].ceiling, 2)
        self.assertEqual(rubric_support(market_findings(), dated, feasibility_findings(), now=NOW)["D"].ceiling, 4)
        self.assertEqual(len(self.problems("D", 3, sentiment=undated)), 1)
        self.assertEqual(self.problems("D", 3, sentiment=dated), [])

    def test_a_partial_downgrade_is_always_allowed(self) -> None:
        """PRD §10.2: "partial satisfaction of anchor N scores N-1". A ceiling
        permits N-1 and everything under it by construction, so an honest
        downgrade never trips the check."""
        market = MarketFindings(
            sources=market_findings().sources,
            source_urls=market_findings().source_urls,
            gaps=[],
            tool_status="ok",
            competitors=market_findings().competitors,
            paying_segments=["Independent clinics"],
        )
        sentiment = self.strong_demand_branch()

        self.assertEqual(
            rubric_support(market, sentiment, feasibility_findings(), now=NOW)["D"].ceiling,
            5,
        )
        for value in (5, 4, 3, 2):
            with self.subTest(score=value):
                self.assertEqual(self.problems("D", value, market=market, sentiment=sentiment), [])

    def test_claiming_level_one_over_a_branch_that_answered_is_rejected(self) -> None:
        """Level 1 says "the evidence does not reach this question". Reaching
        for it is how a run dodges a floor it does not like."""
        cases = {
            "D": {"sentiment": self.strong_demand_branch()},
            "M": {},
            "C": {},
            "F": {},
            "X": {},
        }

        for code, findings in cases.items():
            with self.subTest(dimension=code):
                problems = self.problems(code, 1, **findings)  # type: ignore[arg-type]

                self.assertEqual(len(problems), 1)
                self.assertIn(f"SCORE_LEVEL_ONE_{code}", problems[0])

    def test_level_one_is_accepted_when_the_branch_really_returned_nothing(self) -> None:
        empty_market = MarketFindings(
            sources=[], source_urls=[], gaps=["Nothing."], tool_status="empty", competitors=[]
        )
        empty_sentiment = SentimentFindings(
            sources=[], source_urls=[], gaps=["Nothing."], tool_status="empty"
        )
        empty_feasibility = FeasibilityFindings(
            sources=[], source_urls=[], gaps=["Nothing."], tool_status="empty"
        )

        for code in ("D", "M", "C", "F", "X"):
            with self.subTest(dimension=code):
                self.assertEqual(
                    self.problems(
                        code,
                        1,
                        market=empty_market,
                        sentiment=empty_sentiment,
                        feasibility=empty_feasibility,
                    ),
                    [],
                )

    def test_the_demand_floor_cannot_be_claimed_over_problem_threads(self) -> None:
        """D=0 is a REJECT. Its anchor is fully countable, so it is enforced in
        both directions rather than only from above."""
        problems = self.problems("D", 0, sentiment=self.strong_demand_branch())

        self.assertEqual(len(problems), 1)
        self.assertIn("SCORE_FLOOR_D", problems[0])
        self.assertIn("5 problem thread(s)", problems[0])

        # The floor is still claimable over threads that carry no problem - but it
        # now takes RUBRIC_FLOOR_MIN_USABLE_THREADS of them, not one. This case
        # was the defect: a single OPINION thread was enough to assert that
        # nobody has the problem.
        found_no_problem = self.threads(*[("OPINION", "2026-01-01")] * 3)
        self.assertEqual(self.problems("D", 0, sentiment=found_no_problem), [])

        # And one thread is now refused, which is the whole point of the change.
        too_thin = self.threads(("OPINION", "2026-01-01"))
        thin_problems = self.problems("D", 0, sentiment=too_thin)
        self.assertEqual(len(thin_problems), 1)
        self.assertIn("SCORE_FLOOR_D", thin_problems[0])

    def test_the_feasibility_floor_cannot_be_claimed_over_relevant_repositories(self) -> None:
        problems = self.problems("F", 0)

        self.assertEqual(len(problems), 1)
        self.assertIn("SCORE_FLOOR_F", problems[0])

    def test_the_headroom_kill_is_determined_in_both_directions(self) -> None:
        """X=0 is the PRD's most valuable output. With a live free substitute
        in the evidence it is the only reachable level: 1 needs no relevant
        repository, 3/4/5 all open "No free substitute", and 2 asserts every
        substitute is dead, non-commercial or stale."""
        live = FeasibilityFindings(
            sources=[
                Repo(
                    name="free/substitute",
                    license_permits_commercial=True,
                    months_since_push=2,
                    relevance="SOLVES_ENTIRELY",
                    url="https://github.com/free/substitute",
                )
            ],
            source_urls=["https://github.com/free/substitute"],
            gaps=[],
            tool_status="ok",
        )

        self.assertEqual(self.problems("X", 0, feasibility=live), [])
        for evaded in (1, 2, 3, 4, 5):
            with self.subTest(score=evaded):
                problems = self.problems("X", evaded, feasibility=live)
                self.assertEqual(len(problems), 1)
        self.assertIn("SCORE_FLOOR_X", self.problems("X", 2, feasibility=live)[0])

    def test_a_dead_free_substitute_scores_two_and_never_the_kill(self) -> None:
        dead = FeasibilityFindings(
            sources=[
                Repo(
                    name="free/abandoned",
                    license_permits_commercial=True,
                    months_since_push=40,
                    relevance="SOLVES_ENTIRELY",
                    archived=True,
                    url="https://github.com/free/abandoned",
                )
            ],
            source_urls=["https://github.com/free/abandoned"],
            gaps=[],
            tool_status="ok",
        )

        self.assertEqual(self.problems("X", 2, feasibility=dead), [])
        self.assertIn("SCORE_FLOOR_X", self.problems("X", 0, feasibility=dead)[0])
        self.assertIn("SCORE_SUPPORT_X", self.problems("X", 4, feasibility=dead)[0])

    def test_judgement_clauses_leave_the_middle_of_every_ladder_open(self) -> None:
        """M=2/M=3 and C=3 rest on reading prose ("names a buyer segment",
        "states an axis of beatability"). Those clauses are dropped from the
        bound, so a one-source, one-competitor branch still reaches 3."""
        support = rubric_support(
            market_findings(), sentiment_findings(), feasibility_findings(), now=NOW
        )

        self.assertEqual(support["M"].ceiling, 3)
        self.assertEqual(support["C"].ceiling, 3)
        for code in ("M", "C"):
            with self.subTest(dimension=code):
                self.assertEqual(self.problems(code, 3), [])
                self.assertEqual(len(self.problems(code, 4)), 1)

    def test_an_unknown_push_date_cannot_make_a_repository_reusable(self) -> None:
        """Task 2 meeting Task 3: the tri-state field is only worth having if
        the ladders honour the null."""
        unknown = FeasibilityFindings(
            sources=[
                Repo(
                    name="example/project",
                    license_permits_commercial=True,
                    months_since_push=None,
                    relevance="PARTIAL",
                    url="https://github.com/example/project",
                )
            ],
            source_urls=["https://github.com/example/project"],
            gaps=[],
            tool_status="ok",
        )

        support = rubric_support(market_findings(), sentiment_findings(), unknown, now=NOW)

        self.assertEqual(support["F"].ceiling, 2)
        self.assertIn("SCORE_SUPPORT_F", self.problems("F", 3, feasibility=unknown)[0])
        self.assertEqual(self.problems("F", 2, feasibility=unknown), [])

    def market_with(self, *dates: str, segments: list[str] | None = None) -> MarketFindings:
        """`dates` are publication dates; an empty string means undated."""
        sources = [
            Evidence(
                claim=f"Claim {index}.",
                url=f"https://example.com/market-{index}",
                publisher="Example",
                dated=date or "2026-08-29",
                dated_is_retrieval_time=not date,
                retrieved_via="firecrawl",
            )
            for index, date in enumerate(dates)
        ]
        return MarketFindings(
            sources=sources,
            source_urls=[source.url for source in sources],
            gaps=[],
            tool_status="ok",
            competitors=market_findings().competitors,
            paying_segments=segments or [],
        )

    def test_undated_market_sources_cannot_reach_the_market_recency_clauses(self) -> None:
        """The other half of the same rule: M=4/M=5 and C=4/C=5 count sources
        "dated within 24 months", and a retrieval-time fallback is not one."""
        undated = self.market_with("", "", "", segments=["Independent clinics"])
        dated = self.market_with(
            "2026-01-01", "2026-02-01", "2026-03-01", segments=["Independent clinics"]
        )

        self.assertEqual(
            rubric_support(undated, sentiment_findings(), feasibility_findings(), now=NOW)[
                "M"
            ].ceiling,
            3,
        )
        self.assertEqual(
            rubric_support(dated, sentiment_findings(), feasibility_findings(), now=NOW)[
                "M"
            ].ceiling,
            5,
        )
        self.assertIn("SCORE_SUPPORT_M", self.problems("M", 4, market=undated)[0])
        self.assertEqual(self.problems("M", 5, market=dated), [])

    def test_a_source_just_past_the_window_does_not_fail_an_honest_score(self) -> None:
        """`RUBRIC_RECENCY_GRACE_MONTHS` exists because 24 "months" here is 720
        days while the Synthesist reasons in calendar months. The bound is an
        upper bound, so slack can only let an honest score through."""
        borderline = "2024-08-20"  # ~24.3 30-day months before NOW.
        market = self.market_with(borderline, borderline, segments=["Independent clinics"])

        self.assertEqual(
            rubric_support(market, sentiment_findings(), feasibility_findings(), now=NOW)[
                "M"
            ].ceiling,
            4,
        )
        self.assertEqual(self.problems("M", 4, market=market), [])

    def test_the_contextual_guardrail_carries_the_check_end_to_end(self) -> None:
        market, sentiment, feasibility = (
            market_findings(),
            sentiment_findings(),
            feasibility_findings(),
        )
        result = synthesis(
            market,
            sentiment,
            feasibility,
            demand=dimension(5, DEMAND_ANCHORS[5], [THREAD_URL]),
        )
        guardrail = make_rubric_guardrail(market, sentiment, feasibility, now=NOW)

        passed, message = guardrail(Output(result.model_dump_json()))

        self.assertFalse(passed)
        self.assertIn("SCORE_SUPPORT_D", message)
        # The anchor text itself was never the problem.
        self.assertNotIn("ANCHOR_D", message)

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