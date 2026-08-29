from __future__ import annotations

import unittest

from pydantic import ValidationError

from brief_crew.schemas import (
    Competitor,
    DimensionScore,
    Evidence,
    MarketFindings,
    Repo,
    Thread,
    Verdict,
)


def score(value: int, urls: list[str] | None = None) -> DimensionScore:
    return DimensionScore(
        score=value,
        anchor_matched=f"anchor {value}",
        evidence_urls=urls or [
            "https://example.com/one",
            "https://example.com/two",
            "https://example.com/three",
        ],
        evidence_thin=True,
    )


def verdict(**overrides: object) -> Verdict:
    values: dict[str, object] = {
        "demand": score(4),
        "market": score(4),
        "competitive_room": score(3),
        "feasibility": score(3),
        "headroom_over_free": score(3),
        "evidence_counts": {"market_sources": 3},
        "market_coverage": 0.60,
        "sentiment_coverage": 0.60,
        "feasibility_coverage": 0.60,
        "median_market_source_age_months": 12,
        "branches_ok": 3,
        "cheapest_next_test": "Interview five target users.",
        "kill_criteria": ["Fewer than 2 of 10 clinics keep a manual rota."],
        "composite_score": 99,
        "verdict": "REJECT",
        "confidence": 1,
        "confidence_band": "HIGH",
        "provisional": True,
    }
    values.update(overrides)
    return Verdict.model_validate(values)


class UrlAndFindingTests(unittest.TestCase):
    def test_url_error_is_actionable(self) -> None:
        with self.assertRaisesRegex(ValidationError, "must start with http:// or https://"):
            Evidence(
                claim="Claim",
                url="example.com/source",
                publisher="Publisher",
                dated="2026-08-29",
                retrieved_via="firecrawl",
            )

    def test_source_urls_must_exactly_mirror_sources(self) -> None:
        source = Evidence(
            claim="Claim",
            url="https://example.com/source",
            publisher="Publisher",
            dated="2026-08-29",
            retrieved_via="firecrawl",
        )
        with self.assertRaisesRegex(ValidationError, "must exactly match"):
            MarketFindings(
                sources=[source],
                source_urls=["https://example.com/different"],
                gaps=[],
                tool_status="ok",
                competitors=[],
            )

    def test_dimension_thin_flag_is_computed(self) -> None:
        self.assertFalse(score(3).evidence_thin)
        self.assertTrue(score(3, ["https://example.com/only"]).evidence_thin)

    def test_duplicate_dimension_urls_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "duplicate URLs"):
            score(3, ["https://example.com/one", "https://example.com/one"])

    def test_score_does_not_coerce_strings(self) -> None:
        with self.assertRaises(ValidationError):
            DimensionScore(
                score="3",  # type: ignore[arg-type]
                anchor_matched="anchor",
                evidence_urls=[],
                evidence_thin=True,
            )


class VerdictTests(unittest.TestCase):
    def test_validate_threshold_and_derived_fields(self) -> None:
        result = verdict()

        self.assertEqual(result.composite_score, 7.0)
        self.assertEqual(result.confidence, 0.60)
        self.assertEqual(result.confidence_band, "MODERATE")
        self.assertEqual(result.verdict, "VALIDATE")
        self.assertIsNone(result.decision_reason)
        self.assertFalse(result.provisional)

    def test_low_confidence_beats_hard_floors(self) -> None:
        result = verdict(
            demand=score(0),
            market=score(0),
            competitive_room=score(0),
            feasibility=score(0),
            headroom_over_free=score(0),
            market_coverage=0.30,
            sentiment_coverage=0.30,
            feasibility_coverage=0.30,
        )

        self.assertEqual(result.confidence, 0.30)
        self.assertEqual(result.verdict, "NEEDS_WORK")
        self.assertEqual(result.decision_reason, "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result.confidence_band, "LOW")
        self.assertIn("FLOOR_NO_DEMAND", result.fatal_floors)

    def test_floor_evaluation_order(self) -> None:
        result = verdict(demand=score(0), headroom_over_free=score(0))

        self.assertEqual(result.verdict, "REJECT")
        self.assertEqual(result.decision_reason, "FLOOR_NO_DEMAND")

    def test_not_buildable_caps_at_needs_work(self) -> None:
        result = verdict(feasibility=score(0))

        self.assertEqual(result.verdict, "NEEDS_WORK")
        self.assertEqual(result.decision_reason, "FLOOR_NOT_BUILDABLE")

    def test_already_free_floor_rejects(self) -> None:
        result = verdict(headroom_over_free=score(0))

        self.assertEqual(result.verdict, "REJECT")
        self.assertEqual(result.decision_reason, "FLOOR_ALREADY_FREE")

    def test_no_market_floor_requires_weak_demand(self) -> None:
        result = verdict(market=score(0), demand=score(2))

        self.assertEqual(result.verdict, "REJECT")
        self.assertEqual(result.decision_reason, "FLOOR_NO_MARKET")

    def test_composite_below_four_rejects_without_floor(self) -> None:
        result = verdict(
            demand=score(2),
            market=score(2),
            competitive_room=score(1),
            feasibility=score(1),
            headroom_over_free=score(1),
        )

        self.assertEqual(result.composite_score, 3.0)
        self.assertEqual(result.verdict, "REJECT")
        self.assertIsNone(result.decision_reason)

    def test_non_threshold_result_needs_work(self) -> None:
        result = verdict(
            demand=score(3),
            market=score(3),
            competitive_room=score(3),
            feasibility=score(3),
            headroom_over_free=score(2),
        )

        self.assertEqual(result.verdict, "NEEDS_WORK")
        self.assertIsNone(result.decision_reason)

    def test_moderate_confidence_reject_is_provisional(self) -> None:
        result = verdict(
            demand=score(1),
            market=score(1),
            competitive_room=score(1),
            feasibility=score(1),
            headroom_over_free=score(1),
            market_coverage=0.50,
            sentiment_coverage=0.50,
            feasibility_coverage=0.50,
        )

        self.assertEqual(result.composite_score, 2.0)
        self.assertEqual(result.confidence, 0.50)
        self.assertEqual(result.verdict, "REJECT")
        self.assertTrue(result.provisional)

    def test_staleness_and_branch_penalty_are_mechanical(self) -> None:
        result = verdict(
            market_coverage=1.0,
            sentiment_coverage=1.0,
            feasibility_coverage=1.0,
            median_market_source_age_months=24,
            branches_ok=2,
        )

        self.assertEqual(result.confidence, 0.51)

    def test_unknown_source_age_takes_the_worst_staleness_band(self) -> None:
        """A null median is not "no penalty"; it is the 0.70 band already."""
        coverage: dict[str, object] = {
            "market_coverage": 1.0,
            "sentiment_coverage": 1.0,
            "feasibility_coverage": 1.0,
        }
        fresh = verdict(median_market_source_age_months=0.0, **coverage)
        unknown = verdict(median_market_source_age_months=None, **coverage)

        self.assertEqual(fresh.confidence, 1.00)
        self.assertEqual(unknown.confidence, 0.70)

    def test_model_kill_criteria_survive_validation(self) -> None:
        """F09: judgement is kept, arithmetic is overwritten."""
        supplied = [
            "Fewer than 2 of 10 clinics keep a manual rota.",
            "No clinic will pay more than the receptionist hour it replaces.",
        ]

        result = verdict(demand=score(0), kill_criteria=supplied)

        self.assertEqual(result.kill_criteria, supplied)
        self.assertEqual(result.fatal_floors, ["FLOOR_NO_DEMAND"])

    def test_fatal_floors_are_recomputed_and_overwrite_the_model(self) -> None:
        result = verdict(
            headroom_over_free=score(0),
            fatal_floors=["FLOOR_NOT_BUILDABLE"],
        )

        self.assertEqual(result.fatal_floors, ["FLOOR_ALREADY_FREE"])
        self.assertEqual(result.decision_reason, "FLOOR_ALREADY_FREE")

    def test_a_nonsense_floor_list_is_discarded_rather_than_failing_the_run(self) -> None:
        """PRD §10.1: a model that miscomputes gets a correct verdict, not an error."""
        result = verdict(demand=score(0), fatal_floors=["not a floor code at all"])

        self.assertEqual(result.fatal_floors, ["FLOOR_NO_DEMAND"])

    def test_kill_criteria_shape_is_validated(self) -> None:
        with self.assertRaisesRegex(ValidationError, "must be non-empty"):
            verdict(kill_criteria=["Real criterion.", "   "])
        with self.assertRaisesRegex(ValidationError, "duplicates"):
            verdict(kill_criteria=["Same criterion.", "Same criterion."])

    def test_arithmetic_is_reproducible_whatever_the_judgement_says(self) -> None:
        """Two runs over one set of scores agree, kill criteria notwithstanding."""
        first = verdict(kill_criteria=["One phrasing of the falsifier."])
        second = verdict(kill_criteria=["A completely different phrasing.", "And another."])

        for field_name in (
            "composite_score",
            "confidence",
            "confidence_band",
            "verdict",
            "decision_reason",
            "provisional",
            "fatal_floors",
        ):
            with self.subTest(field=field_name):
                self.assertEqual(getattr(first, field_name), getattr(second, field_name))
        self.assertNotEqual(first.kill_criteria, second.kill_criteria)

    def test_confidence_band_boundaries(self) -> None:
        moderate = verdict(
            market_coverage=0.35,
            sentiment_coverage=0.35,
            feasibility_coverage=0.35,
        )
        high = verdict(
            market_coverage=0.70,
            sentiment_coverage=0.70,
            feasibility_coverage=0.70,
        )

        self.assertEqual(moderate.confidence_band, "MODERATE")
        self.assertEqual(high.confidence_band, "HIGH")


class SpecFieldTests(unittest.TestCase):
    """F05, F06 and F07 - fields the spec names that the schemas lacked."""

    def market(self, **overrides: object) -> MarketFindings:
        source = Evidence(
            claim="Independent clinics budget for scheduling software.",
            url="https://example.com/source",
            publisher="Publisher",
            dated="2026-08-29",
            retrieved_via="firecrawl",
        )
        values: dict[str, object] = {
            "sources": [source],
            "source_urls": [source.url],
            "gaps": [],
            "tool_status": "ok",
            "competitors": [
                Competitor(name="Incumbent", pricing="not published", vendor_owned=False)
            ],
        }
        values.update(overrides)
        return MarketFindings.model_validate(values)

    def thread(self, **overrides: object) -> Thread:
        values: dict[str, object] = {
            "classification": "HAS_PROBLEM",
            "quote": "We keep the rota on a whiteboard.",
            "url": "https://news.ycombinator.com/item?id=1",
            "date": "2026-07-01",
        }
        values.update(overrides)
        return Thread.model_validate(values)

    def repo(self, **overrides: object) -> Repo:
        values: dict[str, object] = {
            "name": "example/project",
            "license_permits_commercial": True,
            "months_since_push": 1,
            "relevance": "PARTIAL",
            "url": "https://github.com/example/project",
        }
        values.update(overrides)
        return Repo.model_validate(values)

    def test_market_findings_name_paying_segments(self) -> None:
        self.assertEqual(self.market().paying_segments, [])
        named = self.market(paying_segments=["Independent physiotherapy clinics"])
        self.assertEqual(named.paying_segments, ["Independent physiotherapy clinics"])

    def test_paying_segments_reject_blanks_and_duplicates(self) -> None:
        with self.assertRaisesRegex(ValidationError, "must be non-empty"):
            self.market(paying_segments=["Clinics", " "])
        with self.assertRaisesRegex(ValidationError, "duplicates"):
            self.market(paying_segments=["Clinics", "clinics"])

    def test_thread_counts_default_to_unreported_not_zero(self) -> None:
        default = self.thread()
        self.assertIsNone(default.points)
        self.assertIsNone(default.num_comments)

        counted = self.thread(points=0, num_comments=42)
        self.assertEqual(counted.points, 0)
        self.assertEqual(counted.num_comments, 42)

        with self.assertRaises(ValidationError):
            self.thread(points=-1)

    def evidence(self, **overrides: object) -> Evidence:
        values: dict[str, object] = {
            "claim": "Independent clinics budget for scheduling software.",
            "url": "https://example.com/source",
            "publisher": "Publisher",
            "dated": "2026-08-29",
            "retrieved_via": "firecrawl",
        }
        values.update(overrides)
        return Evidence.model_validate(values)

    def test_evidence_flags_a_retrieval_time_fallback(self) -> None:
        """F12: `dated` alone cannot say whether the page published that date."""
        self.assertFalse(self.evidence().dated_is_retrieval_time)
        self.assertTrue(self.evidence(dated_is_retrieval_time=True).dated_is_retrieval_time)

        with self.assertRaises(ValidationError):
            self.evidence(dated_is_retrieval_time="yes")

    def test_thread_flags_a_retrieval_time_fallback(self) -> None:
        """F16: the twin of `Evidence.dated_is_retrieval_time`, on the branch
        that feeds the heaviest dimension. An undated thread dated "today" is
        always within 24 months, so D could reach its top anchors on threads of
        entirely unknown age."""
        self.assertFalse(self.thread().date_is_retrieval_time)
        self.assertTrue(self.thread(date_is_retrieval_time=True).date_is_retrieval_time)

        with self.assertRaises(ValidationError):
            self.thread(date_is_retrieval_time="yes")

    def test_months_since_push_is_required_but_nullable(self) -> None:
        """F16: the tool reports null for a repository GitHub gave no push date.

        It used to be `int` with `ge=0` against a tool that emitted -1 and said
        so in its notes, so the honest copy failed validation. Required, so the
        model must answer; nullable, so it can answer "not reported".
        """
        self.assertEqual(self.repo().months_since_push, 1)
        self.assertIsNone(self.repo(months_since_push=None).months_since_push)

        with self.assertRaises(ValidationError):
            self.repo(months_since_push=-1)
        values = {
            "name": "example/project",
            "license_permits_commercial": True,
            "relevance": "PARTIAL",
            "url": "https://github.com/example/project",
        }
        with self.assertRaises(ValidationError):
            Repo.model_validate(values)

    def test_repo_archived_state_is_tri_state(self) -> None:
        self.assertIsNone(self.repo().archived)
        self.assertTrue(self.repo(archived=True).archived)
        self.assertFalse(self.repo(archived=False).archived)

        with self.assertRaises(ValidationError):
            self.repo(archived="yes")


if __name__ == "__main__":
    unittest.main()