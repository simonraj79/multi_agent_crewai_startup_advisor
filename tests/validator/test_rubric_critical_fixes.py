"""The two Critical findings of `docs/rubric-review.md`, and what they touch.

Every scenario here is one the review executed against the shipped code and
reported a measured outcome for. The two worked examples are reproduced first
and asserted at their new outcome; the cases the review lists under "What did
not break" follow, so a later change cannot buy F1 and F2 by breaking them.

F1 - `FLOOR_ALREADY_FREE` counted GitHub repositories only, so a free PRODUCT
     covering the core job could not reach X=0. Measured: composite 9.4,
     confidence 0.90 HIGH, `VALIDATE`, no guardrail problems.
F2 - `zero_ok = usable >= 1 and problems == 0`, so one off-hand comment fired
     the demand floor. Measured: `REJECT / FLOOR_NO_DEMAND` at confidence 0.60
     with `provisional=False`, no guardrail problems.

The arithmetic is deliberately re-asserted alongside each: `Verdict` still
recomputes and overwrites every model-supplied number, and both fixes work by
rejecting a SCORE the evidence cannot carry, never by changing what a set of
five integers means.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from brief_crew.config import RUBRIC_ANCHORS, RUBRIC_FLOOR_MIN_USABLE_THREADS
from brief_crew.schemas import (
    Competitor,
    DimensionScore,
    Evidence,
    FeasibilityFindings,
    MarketFindings,
    Repo,
    SentimentFindings,
    Thread,
    Verdict,
)
from brief_crew.validator_guardrails import (
    compute_confidence_inputs,
    compute_evidence_counts,
    rubric_problems,
    rubric_support,
    score_support_problems,
)

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)
Branches = tuple[MarketFindings, SentimentFindings, FeasibilityFindings]
RECENT = "2026-06-01"

FIELD_BY_CODE = {
    "D": "demand",
    "M": "market",
    "C": "competitive_room",
    "F": "feasibility",
    "X": "headroom_over_free",
}


def market_source(index: int) -> Evidence:
    return Evidence(
        claim=f"Independent clinics budget for scheduling software ({index}).",
        url=f"https://example.com/market-{index}",
        publisher="Example Analyst",
        dated=RECENT,
        retrieved_via="firecrawl",
    )


def market_findings(
    *,
    sources: int = 5,
    segments: list[str] | None = None,
    competitors: list[Competitor] | None = None,
    tool_status: str = "ok",
) -> MarketFindings:
    rows = [market_source(index) for index in range(sources)]
    if competitors is None:
        # `free_core_coverage="NONE"` on the DEFAULTS, since RATIFICATION C3.
        # These two are paid incumbents whose pricing the branch read, so
        # "nothing here is free" is a finding it actually made. Leaving them
        # null would make every scenario in this module an unsettled one, which
        # now caps X at 3 - and the scenarios exist to exercise the top of the
        # ladder, not the unsettled case (which has its own tests).
        competitors = [
            Competitor(
                name="Incumbent A",
                pricing="$12/seat",
                vendor_owned=False,
                free_core_coverage="NONE",
            ),
            Competitor(
                name="Incumbent B",
                pricing="$30/seat",
                vendor_owned=False,
                free_core_coverage="NONE",
            ),
        ]
    return MarketFindings(
        sources=rows,
        source_urls=[row.url for row in rows],
        gaps=[] if tool_status == "ok" else ["Market lookup failed."],
        tool_status=tool_status,
        competitors=competitors,
        paying_segments=["Independent clinics"] if segments is None else segments,
    )


def free_product(coverage: str | None, *, name: str = "Freebie") -> Competitor:
    """A competitor that gives some part of the core job away."""
    return Competitor(
        name=name,
        pricing="free",
        vendor_owned=False,
        url="https://example.com/free-product",
        free_core_coverage=coverage,
    )


def threads(*classifications: str, dated: str = RECENT) -> SentimentFindings:
    rows = [
        Thread(
            classification=classification,
            quote=f"Quote {index}.",
            url=f"https://news.ycombinator.com/item?id={index}",
            date=dated,
        )
        for index, classification in enumerate(classifications)
    ]
    return SentimentFindings(
        sources=rows,
        source_urls=[row.url for row in rows],
        gaps=[] if rows else ["Nothing usable."],
        tool_status="ok" if rows else "empty",
    )


def strong_demand() -> SentimentFindings:
    """Five recent problem threads, two of them acted on: enough for D=5."""
    return threads(
        "HAS_PROBLEM",
        "HAS_PROBLEM",
        "HAS_PROBLEM",
        "PAYS",
        "BUILT_WORKAROUND",
    )


def repo(index: int, **overrides: object) -> Repo:
    values: dict[str, object] = {
        "name": f"example/project-{index}",
        "license_permits_commercial": True,
        "months_since_push": 2,
        "relevance": "PARTIAL",
        "url": f"https://github.com/example/project-{index}",
    }
    values.update(overrides)
    return Repo.model_validate(values)


def feasibility_findings(*repos: Repo, tool_status: str = "ok") -> FeasibilityFindings:
    return FeasibilityFindings(
        sources=list(repos),
        source_urls=[item.url for item in repos],
        gaps=[] if repos else ["Nothing returned."],
        tool_status=tool_status,
    )


def partial_repos(count: int) -> FeasibilityFindings:
    return feasibility_findings(*(repo(index) for index in range(count)))


def verdict_for(
    market: MarketFindings,
    sentiment: SentimentFindings,
    feasibility: FeasibilityFindings,
    scores: dict[str, int],
) -> Verdict:
    """A Verdict whose every mechanical input is recomputed from the findings.

    Only the five anchored integers are the caller's, which is the split the
    schema enforces: everything else here comes from the branch lists, so a
    guardrail complaint can only be about a score.
    """
    urls = sorted(
        {source.url for source in market.sources}
        | {source.url for source in sentiment.sources}
        | {source.url for source in feasibility.sources}
    )[:3]
    values: dict[str, object] = {
        FIELD_BY_CODE[code]: DimensionScore(
            score=value,
            anchor_matched=RUBRIC_ANCHORS[code][value],
            evidence_urls=urls,
        )
        for code, value in scores.items()
    }
    values.update(
        {
            "evidence_counts": compute_evidence_counts(market, sentiment, feasibility),
            "cheapest_next_test": "Interview five clinic operations managers.",
            "kill_criteria": ["Fewer than 2 of 10 clinics keep a manual rota."],
            **compute_confidence_inputs(market, sentiment, feasibility, now=NOW),
        }
    )
    return Verdict.model_validate(values)


def legal_scores(
    code: str,
    market: MarketFindings,
    sentiment: SentimentFindings,
    feasibility: FeasibilityFindings,
    others: dict[str, int],
) -> set[int]:
    """Every score this dimension can take without a support complaint."""
    accepted = set()
    for value in range(6):
        scores = dict(others)
        scores[code] = value
        problems = [
            problem
            for problem in score_support_problems(
                verdict_for(market, sentiment, feasibility, scores),
                market,
                sentiment,
                feasibility,
                now=NOW,
            )
            if problem.split(":")[0].endswith(f"_{code}")
        ]
        if not problems:
            accepted.add(value)
    return accepted


class HeadroomSeesFreeProductsTests(unittest.TestCase):
    """F1: the floor could not see the commonest free substitute there is."""

    def scenario(self, coverage: str | None) -> Branches:
        """The review's F1 evidence state, with the free product's coverage varied.

        Five market sources, two competitors, one paying segment, five problem
        threads (two acted on) and three PARTIAL repositories: everything else
        at maximum, so the only thing under test is the free product.
        """
        market = market_findings(
            competitors=[
                # SETTLED at "NONE", so the only unsettled thing in this
                # scenario can be the free product itself - which is what the
                # docstring above promises. Left null, this incumbent capped X
                # at 3 under RATIFICATION C3 no matter what `coverage` was, and
                # the two cases became indistinguishable again.
                Competitor(
                    name="Incumbent A",
                    pricing="$12/seat",
                    vendor_owned=False,
                    free_core_coverage="NONE",
                ),
                free_product(coverage),
            ]
        )
        return market, strong_demand(), partial_repos(3)

    def test_a_free_product_covering_the_whole_job_makes_the_floor_reachable(self) -> None:
        """The kill the PRD calls this system's most valuable output.

        Before: no `Competitor` field could say "this is free and does the whole
        job", so X=0 was unreachable for anything that is not a GitHub
        repository and the run scored X=3 - which clears `min(scores) >= 3`.
        """
        market, sentiment, feasibility = self.scenario("WHOLE_JOB")
        support = rubric_support(market, sentiment, feasibility, now=NOW)["X"]

        self.assertTrue(support.zero_ok)
        self.assertFalse(support.one_ok)
        self.assertEqual(support.ceiling, 2)
        self.assertIn(2, support.forbidden)
        self.assertEqual(
            legal_scores("X", market, sentiment, feasibility, {"D": 5, "M": 5, "C": 5, "F": 5}),
            {0},
            "a whole-job free product must leave X=0 as the only score, exactly as a "
            "live free substitute repository does",
        )

        result = verdict_for(market, sentiment, feasibility, {"D": 5, "M": 5, "C": 5, "F": 5, "X": 0})

        self.assertEqual(rubric_problems(result, findings=(market, sentiment, feasibility), now=NOW), [])
        self.assertEqual(result.verdict, "REJECT")
        self.assertEqual(result.decision_reason, "FLOOR_ALREADY_FREE")
        self.assertIn("FLOOR_ALREADY_FREE", result.fatal_floors)

    def test_the_measured_validate_at_composite_94_is_now_rejected(self) -> None:
        """The review's headline number, reproduced and then blocked.

        The arithmetic is untouched: those five integers still compute to 9.4
        and still say VALIDATE. What changed is that the evidence can no longer
        carry X=3, so the Synthesist cannot claim it.
        """
        market, sentiment, feasibility = self.scenario("MOST_OF_JOB")
        as_measured = verdict_for(
            market, sentiment, feasibility, {"D": 5, "M": 5, "C": 5, "F": 5, "X": 3}
        )

        self.assertEqual(as_measured.composite_score, 9.4)
        self.assertEqual(as_measured.confidence, 0.90)
        self.assertEqual(as_measured.confidence_band, "HIGH")
        self.assertEqual(as_measured.verdict, "VALIDATE")

        problems = rubric_problems(as_measured, findings=(market, sentiment, feasibility), now=NOW)

        self.assertEqual(len(problems), 1, problems)
        self.assertIn("SCORE_SUPPORT_X", problems[0])
        self.assertIn("free product(s) covering the whole core job", problems[0])

    def test_a_free_product_covering_most_of_the_job_blocks_validate(self) -> None:
        """The severity inversion, corrected: a live free competitor now costs
        at least as much as an archived repository doing the same job."""
        market, sentiment, feasibility = self.scenario("MOST_OF_JOB")

        self.assertEqual(
            legal_scores("X", market, sentiment, feasibility, {"D": 5, "M": 5, "C": 5, "F": 5}),
            {2},
        )

        result = verdict_for(market, sentiment, feasibility, {"D": 5, "M": 5, "C": 5, "F": 5, "X": 2})

        self.assertEqual(rubric_problems(result, findings=(market, sentiment, feasibility), now=NOW), [])
        self.assertEqual(result.composite_score, 9.1)
        self.assertEqual(result.verdict, "NEEDS_WORK")
        self.assertIsNone(result.decision_reason)

    def test_a_separable_part_free_product_lands_on_level_three(self) -> None:
        """F5's dead band. A free product covering part of the job satisfied no
        anchor at all, so the Synthesist had to quote a false one."""
        market, sentiment, feasibility = self.scenario("SEPARABLE_PART")

        self.assertEqual(
            legal_scores("X", market, sentiment, feasibility, {"D": 5, "M": 5, "C": 5, "F": 5}),
            {2, 3},
            "3 is the honest score and 2 stays available as caution; 4 and 5 assert no "
            "free product was named, and 0 and 1 are bounded from below",
        )

        result = verdict_for(market, sentiment, feasibility, {"D": 5, "M": 5, "C": 5, "F": 5, "X": 3})

        self.assertEqual(rubric_problems(result, findings=(market, sentiment, feasibility), now=NOW), [])

    def test_an_unanswered_free_question_is_not_a_free_product(self) -> None:
        """`None` is "the branch did not establish this", never "nothing is
        free" - the same tri-state rule `Repo.archived` follows. X=4 and X=5
        rest on "no free product is named", and an unasked question must not
        satisfy that on its own any more than it did before the field existed.

        ⚠️ SPLIT BY RATIFICATION C3 (2026-09-01). This looped over `None` AND
        `"NONE"` asserting an IDENTICAL ceiling of 5 - which asserts that the
        two are the same, the exact opposite of the sentence above. A test
        written to defend the tri-state was pinning its erasure, and that is
        why 796 green tests could not see that an unasked question was earning
        the top of this ladder.
        """
        # SETTLED as "nothing is free": the branch looked and answered. The top
        # of the ladder is legitimately reachable.
        market, sentiment, feasibility = self.scenario("NONE")
        settled = rubric_support(market, sentiment, feasibility, now=NOW)["X"]

        self.assertEqual(settled.ceiling, 5)
        self.assertFalse(settled.zero_ok)
        self.assertEqual(settled.forbidden, frozenset())
        self.assertEqual(
            legal_scores(
                "X", market, sentiment, feasibility, {"D": 5, "M": 5, "C": 5, "F": 5}
            ),
            {2, 3, 4, 5},
        )

        # UNSETTLED: nobody asked. X=4 and X=5 both assert "no free product",
        # a claim about evidence that was never gathered, so the ceiling stops
        # at 3. It must NOT collapse to the floor either - an unanswered
        # question is not grounds to reject.
        market, sentiment, feasibility = self.scenario(None)
        unsettled = rubric_support(market, sentiment, feasibility, now=NOW)["X"]

        self.assertEqual(unsettled.ceiling, 3)
        self.assertFalse(unsettled.zero_ok)
        self.assertEqual(unsettled.forbidden, frozenset())
        self.assertEqual(
            legal_scores(
                "X", market, sentiment, feasibility, {"D": 5, "M": 5, "C": 5, "F": 5}
            ),
            {2, 3},
        )

    def test_unsettled_and_settled_coverage_are_not_the_same_state(self) -> None:
        """The one assertion the split exists to make, stated on its own.

        Before C3 these produced a BYTE-IDENTICAL `DimensionSupport`.
        """
        settled = rubric_support(*self.scenario("NONE"), now=NOW)["X"]
        unsettled = rubric_support(*self.scenario(None), now=NOW)["X"]

        self.assertNotEqual(settled.ceiling, unsettled.ceiling)
        self.assertGreater(settled.ceiling, unsettled.ceiling)

    def test_the_repository_half_of_the_floor_is_unchanged(self) -> None:
        """"What did not break", re-asserted: the `forbidden={2}` rule is the
        best piece of engineering in the rubric and F1 must not cost it."""
        market, sentiment = market_findings(), strong_demand()
        live = feasibility_findings(repo(0, relevance="SOLVES_ENTIRELY"))
        dead = feasibility_findings(
            repo(0, relevance="SOLVES_ENTIRELY", months_since_push=40, archived=True)
        )

        self.assertEqual(
            legal_scores("X", market, sentiment, live, {"D": 5, "M": 5, "C": 5, "F": 3}),
            {0},
        )
        self.assertEqual(
            legal_scores("X", market, sentiment, dead, {"D": 5, "M": 5, "C": 5, "F": 2}),
            {2},
        )

    def test_no_repository_and_no_free_product_reaches_only_level_one(self) -> None:
        """X=3 now requires a named free product, so the state that names none
        and returns no relevant repository has exactly one true anchor."""
        market = market_findings(competitors=[])
        sentiment = strong_demand()
        feasibility = feasibility_findings(repo(0, relevance="IRRELEVANT"))
        support = rubric_support(market, sentiment, feasibility, now=NOW)["X"]

        self.assertTrue(support.one_ok)
        self.assertEqual(support.ceiling, 1)
        self.assertEqual(
            # F=2, not F=0: RATIFICATION C4 retired F's level 0, and this
            # score is only filler for the OTHER dimensions while X is varied.
            legal_scores("X", market, sentiment, feasibility, {"D": 5, "M": 5, "C": 1, "F": 2}),
            {1},
        )


class DemandFloorNeedsABranchThatLookedTests(unittest.TestCase):
    """F2: one stray comment could produce a final, non-provisional REJECT."""

    def scenario(self, sentiment: SentimentFindings) -> Branches:
        """The review's F2 evidence state: five market sources, four PARTIAL
        repositories, and whatever the sentiment branch came back with."""
        return market_findings(), sentiment, partial_repos(4)

    def test_one_usable_thread_can_no_longer_reject(self) -> None:
        market, sentiment, feasibility = self.scenario(threads("OPINION"))
        as_measured = verdict_for(
            market, sentiment, feasibility, {"D": 0, "M": 5, "C": 3, "F": 4, "X": 5}
        )

        # The review measured 0.60 here. RATIFICATION C6 moved it to 0.67, and
        # the movement is the fix rather than a side effect: `sentiment_coverage`
        # counted PROBLEM threads, so it was 0.0 by construction whenever the
        # demand floor fired - the confidence attached to "nobody wants this"
        # was computed entirely from the two branches with nothing to say about
        # demand. It now counts USABLE (non-OFF_TOPIC) threads, so a branch that
        # retrieved one on-topic thread is credited for having looked, once.
        self.assertEqual(as_measured.confidence, 0.67)
        self.assertEqual(as_measured.verdict, "REJECT")
        self.assertEqual(as_measured.decision_reason, "FLOOR_NO_DEMAND")
        self.assertFalse(as_measured.provisional)

        # And the score that produced it is now rejected.
        problems = rubric_problems(as_measured, findings=(market, sentiment, feasibility), now=NOW)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("SCORE_FLOOR_D", problems[0])
        self.assertIn("1 usable thread(s)", problems[0])

        self.assertEqual(
            legal_scores("D", market, sentiment, feasibility, {"M": 5, "C": 3, "F": 4, "X": 5}),
            {1},
            "one on-topic comment stating no problem is 'we did not reach the question'",
        )

        honest = verdict_for(market, sentiment, feasibility, {"D": 1, "M": 5, "C": 3, "F": 4, "X": 5})
        self.assertEqual(rubric_problems(honest, findings=(market, sentiment, feasibility), now=NOW), [])
        self.assertEqual(honest.verdict, "NEEDS_WORK")
        self.assertIsNone(honest.decision_reason)
        self.assertNotIn("FLOOR_NO_DEMAND", honest.fatal_floors)

    def test_nine_off_topic_threads_and_one_opinion_cannot_reject(self) -> None:
        """The review's more obviously wrong variant of the same state."""
        sentiment = threads(*(["OFF_TOPIC"] * 9), "OPINION")
        market, sentiment, feasibility = self.scenario(sentiment)

        self.assertEqual(
            legal_scores("D", market, sentiment, feasibility, {"M": 5, "C": 3, "F": 4, "X": 5}),
            {1},
        )

    def test_the_floor_still_fires_when_the_branch_really_looked(self) -> None:
        """The repair is a precondition, not a retirement. Three on-topic
        threads in which nobody states the problem is still a REJECT."""
        sentiment = threads(*(["OPINION"] * RUBRIC_FLOOR_MIN_USABLE_THREADS))
        market, sentiment, feasibility = self.scenario(sentiment)
        support = rubric_support(market, sentiment, feasibility, now=NOW)["D"]

        self.assertTrue(support.zero_ok)
        self.assertFalse(support.one_ok)
        self.assertEqual(
            legal_scores("D", market, sentiment, feasibility, {"M": 5, "C": 3, "F": 4, "X": 5}),
            {0},
        )

        result = verdict_for(market, sentiment, feasibility, {"D": 0, "M": 5, "C": 3, "F": 4, "X": 5})

        self.assertEqual(rubric_problems(result, findings=(market, sentiment, feasibility), now=NOW), [])
        self.assertEqual(result.verdict, "REJECT")
        self.assertEqual(result.decision_reason, "FLOOR_NO_DEMAND")

    def test_the_floor_still_cannot_be_claimed_over_problem_threads(self) -> None:
        market, sentiment, feasibility = self.scenario(strong_demand())

        self.assertNotIn(
            0,
            legal_scores("D", market, sentiment, feasibility, {"M": 5, "C": 3, "F": 4, "X": 5}),
        )

    def test_level_one_still_cannot_be_claimed_by_a_branch_that_answered(self) -> None:
        """The level-1 reservation is the strongest part of the design and the
        widened lower bound must not cost it: one problem thread is enough to
        make "the evidence does not reach this question" false."""
        for sentiment in (strong_demand(), threads("HAS_PROBLEM"), threads("HAS_PROBLEM", "OFF_TOPIC")):
            with self.subTest(threads=len(sentiment.sources)):
                market, sentiment, feasibility = self.scenario(sentiment)

                self.assertNotIn(
                    1,
                    legal_scores(
                        "D", market, sentiment, feasibility, {"M": 5, "C": 3, "F": 4, "X": 5}
                    ),
                )

    def test_an_empty_sentiment_branch_still_scores_one(self) -> None:
        market, sentiment, feasibility = self.scenario(threads())

        self.assertEqual(
            legal_scores("D", market, sentiment, feasibility, {"M": 5, "C": 3, "F": 4, "X": 5}),
            {1},
        )

    def test_every_demand_state_has_at_least_one_legal_score(self) -> None:
        """The deadlock guard, and the reason D=1's lower bound had to widen
        with D=0's floor rather than after it.

        Raising D=0 to three usable threads on its own orphans "1 or 2 usable
        threads, none of them a problem thread": D=2 needs a problem thread, so
        the ceiling sits at 1, `zero_ok` is false and `one_ok` was false too -
        every score from 0 to 5 rejected, and a synthesis task that can never
        pass its own guardrail. Totality is the property that stops it, so it
        is asserted over the states rather than argued in a comment.
        """
        market, feasibility = market_findings(), partial_repos(4)
        classifications = ("OFF_TOPIC", "OPINION", "HAS_PROBLEM", "PAYS", "BUILT_WORKAROUND")

        for count in range(5):
            for index, classification in enumerate(classifications):
                # A run of one classification, then mixtures with OFF_TOPIC.
                for off_topic in range(3):
                    sentiment = threads(*([classification] * count), *(["OFF_TOPIC"] * off_topic))
                    with self.subTest(kind=classification, count=count, off_topic=off_topic):
                        self.assertTrue(
                            legal_scores(
                                "D",
                                market,
                                sentiment,
                                feasibility,
                                {"M": 5, "C": 3, "F": 4, "X": 5},
                            ),
                            "no score 0-5 is legal for this evidence state",
                        )


class MarketFloorTests(unittest.TestCase):
    """F3, in the half that needs no anchor rewrite.

    M=0 asserts no source names a buyer segment. A recorded paying segment is,
    by `market_task`'s own definition of that field, an attributed source
    naming a buyer segment, so it contradicts the anchor outright. The review's
    other conjunct - at least 3 sources - is not taken here; see the report.
    """

    def test_the_floor_cannot_be_claimed_when_a_paying_segment_was_recorded(self) -> None:
        market = market_findings(segments=["Independent clinics"])
        sentiment = threads("HAS_PROBLEM", "HAS_PROBLEM")
        feasibility = partial_repos(2)

        self.assertFalse(rubric_support(market, sentiment, feasibility, now=NOW)["M"].zero_ok)
        self.assertNotIn(
            0, legal_scores("M", market, sentiment, feasibility, {"D": 2, "C": 3, "F": 3, "X": 5})
        )

    def test_the_floor_still_fires_when_no_segment_was_recorded(self) -> None:
        market = market_findings(segments=[])
        sentiment = threads("HAS_PROBLEM", "HAS_PROBLEM")
        feasibility = partial_repos(2)

        self.assertTrue(rubric_support(market, sentiment, feasibility, now=NOW)["M"].zero_ok)

        result = verdict_for(market, sentiment, feasibility, {"D": 2, "M": 0, "C": 3, "F": 3, "X": 5})

        self.assertEqual(rubric_problems(result, findings=(market, sentiment, feasibility), now=NOW), [])
        self.assertEqual(result.decision_reason, "FLOOR_NO_MARKET")


class ProvisionalTests(unittest.TestCase):
    """What a verdict at 0.17 confidence is allowed to look like.

    The first real paid run scored D=1 M=4 C=2 F=1 X=3 at composite 4.2 and
    confidence 0.17, with two of three branches returning nothing - and
    `provisional` false. `provisional` now also covers the low-confidence
    override, so the report has to say so in its title and summary line.
    """

    def scenario(self) -> Branches:
        return market_findings(sources=2, segments=[]), threads(), feasibility_findings()

    def test_a_verdict_below_the_override_is_provisional(self) -> None:
        """The live run's shape, not its exact arithmetic: two branches empty,
        D and F at the reserved level 1, confidence far below 0.35."""
        market, sentiment, feasibility = self.scenario()
        result = verdict_for(market, sentiment, feasibility, {"D": 1, "M": 4, "C": 2, "F": 1, "X": 3})

        self.assertEqual(result.composite_score, 4.2)

        self.assertLess(result.confidence, 0.35)
        self.assertEqual(result.confidence_band, "LOW")
        self.assertEqual(result.verdict, "NEEDS_WORK")
        self.assertEqual(result.decision_reason, "INSUFFICIENT_EVIDENCE")
        self.assertTrue(result.provisional)

    def test_the_prd_reject_band_is_unchanged(self) -> None:
        """PRD §10.3's rule is kept exactly; it is now the REJECT case of a
        wider one rather than the whole of it."""
        base = verdict_for(*self.scenario(), {"D": 0, "M": 1, "C": 1, "F": 1, "X": 1})
        coverage: dict[str, float] = {
            "market_coverage": 0.5,
            "sentiment_coverage": 0.5,
            "feasibility_coverage": 0.5,
        }
        moderate = Verdict.model_validate({**base.model_dump(), **coverage, "branches_ok": 3})
        confident = Verdict.model_validate(
            {**base.model_dump(), "market_coverage": 1.0, "sentiment_coverage": 1.0,
             "feasibility_coverage": 1.0, "branches_ok": 3, "median_market_source_age_months": 1.0}
        )

        self.assertEqual(moderate.confidence, 0.50)
        self.assertEqual(moderate.verdict, "REJECT")
        self.assertTrue(moderate.provisional)

        self.assertEqual(confident.confidence, 1.00)
        self.assertEqual(confident.verdict, "REJECT")
        self.assertFalse(confident.provisional, "a confident REJECT is final and must say so")

    def test_provisional_is_monotonic_in_confidence(self) -> None:
        """The defect this closes, stated as a property: the flag keys on
        confidence, so it cannot be false at 0.17 and true at 0.36."""
        base = verdict_for(*self.scenario(), {"D": 0, "M": 1, "C": 1, "F": 1, "X": 1})

        for coverage in (0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.6, 0.8, 1.0):
            with self.subTest(coverage=coverage):
                result = Verdict.model_validate(
                    {
                        **base.model_dump(),
                        "market_coverage": coverage,
                        "sentiment_coverage": coverage,
                        "feasibility_coverage": coverage,
                        "branches_ok": 3,
                        "median_market_source_age_months": 1.0,
                    }
                )

                self.assertEqual(result.provisional, result.confidence < 0.60)

    def test_a_validate_is_never_provisional(self) -> None:
        market, sentiment, feasibility = market_findings(), strong_demand(), partial_repos(3)
        result = verdict_for(market, sentiment, feasibility, {"D": 5, "M": 5, "C": 5, "F": 5, "X": 5})

        self.assertEqual(result.verdict, "VALIDATE")
        self.assertFalse(result.provisional)


class ArithmeticIsUnchangedTests(unittest.TestCase):
    """Both fixes reject scores; neither touches what five integers mean."""

    def test_the_reviewed_composites_still_compute(self) -> None:
        market, sentiment, feasibility = market_findings(), strong_demand(), partial_repos(3)
        cases = {
            (5, 5, 5, 5, 3): 9.4,
            (5, 5, 5, 5, 2): 9.1,
            (5, 5, 5, 5, 0): 8.5,
            (1, 4, 2, 1, 3): 4.2,
            (5, 5, 5, 3, 0): 7.9,
            (0, 5, 3, 4, 5): 5.9,
        }

        for scores, composite in cases.items():
            with self.subTest(scores=scores):
                result = verdict_for(
                    market,
                    sentiment,
                    feasibility,
                    dict(zip(("D", "M", "C", "F", "X"), scores)),
                )

                self.assertEqual(result.composite_score, composite)

    def test_model_supplied_arithmetic_is_still_discarded(self) -> None:
        market, sentiment, feasibility = market_findings(), strong_demand(), partial_repos(3)
        honest = verdict_for(market, sentiment, feasibility, {"D": 5, "M": 5, "C": 5, "F": 5, "X": 0})
        lying = Verdict.model_validate(
            {
                **honest.model_dump(),
                "composite_score": 1.0,
                "verdict": "VALIDATE",
                "fatal_floors": [],
                "confidence": 0.99,
                "provisional": True,
            }
        )

        self.assertEqual(lying.composite_score, honest.composite_score)
        self.assertEqual(lying.verdict, "REJECT")
        self.assertEqual(lying.fatal_floors, ["FLOOR_ALREADY_FREE"])
        self.assertEqual(lying.confidence, honest.confidence)
        self.assertEqual(lying.provisional, honest.provisional)


if __name__ == "__main__":
    unittest.main()


class VendorOwnedIsTriStateTests(unittest.TestCase):
    """RATIFICATION C5: C=5 must not be awarded for an absence of evidence.

    `vendor_owned` was the only two-state flag on `Competitor` carrying a
    three-state question, while `free_core_coverage`, `Repo.archived`,
    `Thread.points` and `Evidence.dated_is_retrieval_time` are all tri-state.
    Measured: three competitors whose ownership no source established became
    three `False`s, `vendor_owned == 0`, and the ceiling was 5 - the top of the
    ladder, for a question nobody answered.
    """

    def branch(self, *ownership: bool | None) -> Branches:
        competitors = [
            Competitor(
                name=f"Incumbent {index}",
                pricing="$12/seat",
                vendor_owned=value,
                free_core_coverage="NONE",
            )
            for index, value in enumerate(ownership)
        ]
        return market_findings(competitors=competitors), strong_demand(), partial_repos(3)

    def ceiling(self, *ownership: bool | None) -> int:
        return rubric_support(*self.branch(*ownership), now=NOW)["C"].ceiling

    def test_unestablished_ownership_caps_below_the_top(self) -> None:
        """The defect, stated directly. This was 5."""
        self.assertEqual(self.ceiling(None, None, None), 4)

    def test_established_independence_still_reaches_the_top(self) -> None:
        """The control: a branch that ANSWERED keeps its 5."""
        self.assertEqual(self.ceiling(False, False), 5)

    def test_one_unknown_among_known_still_caps(self) -> None:
        """`vendor_unknown == 0` is required, not a majority."""
        self.assertEqual(self.ceiling(False, None), 4)

    def test_all_vendor_owned_still_opens_the_floor(self) -> None:
        """`zero_ok` counts `is True`, so the floor is unchanged where it was right."""
        support = rubric_support(*self.branch(True, True), now=NOW)["C"]
        self.assertTrue(support.zero_ok)

    def test_a_healthy_branch_that_names_no_competitor_is_not_level_one(self) -> None:
        """C=1 now means "the branch returned nothing", mirroring M=1.

        It used to mean "named no competitor", which is a FALSE sentence about a
        branch that returned five sources and found an uncontested market - and
        it forced a compulsory 1 on exactly the idea worth looking at.
        """
        market = market_findings(competitors=[])
        support = rubric_support(market, strong_demand(), partial_repos(3), now=NOW)["C"]

        self.assertEqual(support.ceiling, 2)
        self.assertFalse(support.one_ok)

    def test_a_branch_that_returned_nothing_is_level_one(self) -> None:
        """The state C=1 is now reserved for."""
        empty = market_findings(sources=0, segments=[], competitors=[], tool_status="empty")
        support = rubric_support(empty, strong_demand(), partial_repos(3), now=NOW)["C"]

        self.assertTrue(support.one_ok)
        self.assertEqual(support.ceiling, 1)
