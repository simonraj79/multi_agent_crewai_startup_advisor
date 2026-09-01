"""The query-shape contract between the Scoper and the two keyword search tools.

This exists because of a measured failure, not a style preference.

The first end-to-end paid run scored D=1 on "0 usable threads" and F=1 on thin
repository evidence, and the composite came out ``NEEDS_WORK`` with reason
``INSUFFICIENT_EVIDENCE``. Neither tool was broken. The Scoper had been told to
write community queries "in the language users would use to describe the
problem", so it produced a natural-language phrase, and both branches send their
queries **verbatim** to keyword search APIs:

    Hacker News Algolia
      "AI tool creates educational materials assessment"  -> status=empty,  0
      "AI generated assessments teachers"                 -> status=ok,     3
      "AI grading teachers"                               -> status=ok,     5
      "teachers AI quiz generator"                        -> status=ok,     7

    GitHub
      "AI tool that creates educational materials and assessments" -> 1
      "AI assessment generator education"                          -> 5
      "quiz generator LLM"                                         -> 5

Two of the three research branches returned almost nothing, and the verdict was
driven by the *absence* of evidence that a two-word query would have found. One
sentence in one prompt cost the run its demand and feasibility dimensions.

These are prompt-contract tests. They cannot prove the model complies - only a
live run does that - but they stop the constraint being deleted by someone who
reads it as redundant prose, which is exactly how it was missing in the first
place. They assert meaning, not phrasing, so the wording can still be improved.

The market branch is deliberately excluded: Firecrawl does semantic search, a
descriptive query is correct there, and it returned 21 sources in the same run.

UPDATED after the SECOND paid run, which cost 17 minutes on one branch.

The broadening loop these tests originally pinned has been REMOVED, and the
reason is worth recording because the loop was not wrong - it was expensive.
The second run measured the market branch at over 13 minutes while the other
two finished in seconds. The cause was not the retries: `MarketResearchTool`
passes `scrape_options` to Firecrawl's `search`, so ONE call scrapes every
result to markdown at 10-30s each. But the retries multiplied it, and the
operator watching a 6-minute silence reasonably concluded the app had hung.

Each branch now calls its tool EXACTLY ONCE. That moves the entire burden of
query breadth onto the Scoper, where the first run's failure actually lived:
the loop was a *correction* for a bad query, and a correction the operator
could neither see nor audit. So the contract these tests defend has inverted
rather than weakened:

  before   write a specific query, and broaden up to three times if it is empty
  after    write ONE deliberately broad query; an empty result is a real gap

The measured query table above is still the evidence, and it argues for the new
contract at least as strongly as for the old one: "AI grading teachers" was
never the third attempt anyone needed to reach, it was the query that should
have been written first. What is genuinely lost is the automatic recovery from
a narrow query, and the replacement for it is the scope gate - a human reading
the query before it is spent. That is why the gate card now states which fields
spend money and what shape they must be.
"""

from __future__ import annotations

from pathlib import Path
import unittest

import yaml


TASKS = (
    Path(__file__).resolve().parents[2]
    / "src" / "brief_crew" / "crews" / "validator_crew" / "config" / "tasks.yaml"
)


def _descriptions() -> dict[str, str]:
    loaded = yaml.safe_load(TASKS.read_text(encoding="utf-8")) or {}
    return {name: str(cfg.get("description", "")) for name, cfg in loaded.items()}


class ScoperQueryShapeTests(unittest.TestCase):
    """The Scoper writes the queries; the shape rule has to live where they are written."""

    def setUp(self) -> None:
        self.scoping = _descriptions()["scoping_task"].lower()

    def test_it_says_the_queries_reach_keyword_search(self) -> None:
        # The *reason* matters more than the rule: an agent told only "be brief"
        # will still write a brief sentence.
        self.assertIn("keyword search", self.scoping)

    def test_it_names_both_keyword_backed_tools(self) -> None:
        self.assertIn("algolia", self.scoping)
        self.assertIn("github", self.scoping)

    def test_it_bounds_the_query_length(self) -> None:
        self.assertRegex(self.scoping, r"\b2 to 4\b.*keyword")

    def test_it_forbids_a_sentence_lifted_from_the_idea(self) -> None:
        self.assertIn("never a sentence", self.scoping)

    def test_it_requires_the_single_query_to_be_deliberately_broad(self) -> None:
        """There is no second attempt, so breadth has to be in the first one.

        This test used to be named ..._last_entry, back when the Scoper wrote a
        list ordered specific-to-broad and the branch worked down it. With one
        call the list is one entry long, and "the broadest phrasing" stops being
        a fallback and becomes the whole strategy.
        """
        self.assertIn("broadest", self.scoping)
        self.assertIn("deliberately broad", self.scoping)

    def test_it_asks_for_exactly_one_query_per_branch(self) -> None:
        """A second query would be written, shown at the gate, and never run."""
        self.assertIn("exactly one", self.scoping)

    def test_it_says_why_a_narrow_query_is_dangerous(self) -> None:
        """The failure is silent: zero results score as "nobody has this problem".

        An agent told only "be broad" has no way to weigh the instruction
        against the competing pull toward a precise-sounding query.
        """
        self.assertIn("zero results", self.scoping)
        self.assertIn("reject", self.scoping)


class BranchSingleCallTests(unittest.TestCase):
    """One call per branch, and an empty result is now a real gap.

    Replaces `BranchBroadeningTests`, which pinned the opposite contract. Kept
    as a class rather than deleted because the *question* it asks is unchanged -
    "what does a branch do when its query comes back empty?" - and only the
    answer has moved. Deleting it would have left that question unasserted,
    which is how the original defect shipped.
    """

    def setUp(self) -> None:
        self.descriptions = _descriptions()

    def test_both_keyword_branches_call_their_tool_exactly_once(self) -> None:
        for task in ("sentiment_task", "feasibility_task"):
            with self.subTest(task=task):
                self.assertIn("exactly once", self.descriptions[task].lower())

    def test_both_keyword_branches_forbid_a_second_call(self) -> None:
        """The positive instruction alone loses to a tempting empty result.

        "Call it once" and "do not call it again after an empty result" are
        different instructions to a model that has just received nothing back.
        """
        for task in ("sentiment_task", "feasibility_task"):
            with self.subTest(task=task):
                text = self.descriptions[task].lower()
                self.assertIn("do not call the tool a second time", text)
                self.assertIn("real evidence gap", text)

    def test_the_gap_report_still_names_the_query_tried(self) -> None:
        """A gap nobody can audit is indistinguishable from a lazy branch.

        This survives the rewrite unchanged in intent: with one attempt the
        query that was tried is *more* important to report, not less, because
        it is the only thing that distinguishes "no demand" from "bad query".
        """
        for task in ("sentiment_task", "feasibility_task"):
            with self.subTest(task=task):
                text = self.descriptions[task].lower()
                self.assertIn("name the query that was tried", text)
                self.assertIn("single attempt", text)

    def test_no_branch_still_advertises_broadening(self) -> None:
        """The removed loop must not survive in half of one prompt."""
        for task in ("sentiment_task", "feasibility_task", "market_task"):
            with self.subTest(task=task):
                self.assertNotIn("broadening", self.descriptions[task].lower())

    def test_the_market_branch_is_left_alone(self) -> None:
        """Firecrawl is semantic; a descriptive query is right there.

        Pinned so a later pass does not 'fix' the market branch by analogy and
        make its queries worse.
        """
        self.assertNotIn("broadening", self.descriptions["market_task"].lower())


class TaskConfigIntegrityTests(unittest.TestCase):
    def test_every_task_still_parses_and_keeps_its_contract(self) -> None:
        loaded = yaml.safe_load(TASKS.read_text(encoding="utf-8")) or {}
        self.assertEqual(
            sorted(loaded),
            [
                "feasibility_task",
                "market_task",
                "reporting_task",
                "scoping_task",
                "sentiment_task",
                "synthesis_task",
            ],
        )
        for name, cfg in loaded.items():
            with self.subTest(task=name):
                self.assertTrue(str(cfg.get("description", "")).strip())
                self.assertTrue(str(cfg.get("expected_output", "")).strip())


if __name__ == "__main__":
    unittest.main()
