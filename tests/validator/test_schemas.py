from __future__ import annotations

import unittest

from pydantic import ValidationError

from brief_crew.schemas import (
    DimensionScore,
    Evidence,
    MarketFindings,
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
        self.assertIn("FLOOR_NO_DEMAND", result.kill_criteria)

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


if __name__ == "__main__":
    unittest.main()