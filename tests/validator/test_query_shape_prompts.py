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

    def test_it_requires_a_deliberately_broad_last_entry(self) -> None:
        """The fallback only exists if the Scoper wrote one to fall back to."""
        self.assertIn("broadest", self.scoping)
        self.assertIn("deliberately broad", self.scoping)


class BranchBroadeningTests(unittest.TestCase):
    """An empty first attempt is a narrow query, not an absent market."""

    def setUp(self) -> None:
        self.descriptions = _descriptions()

    def test_both_keyword_branches_retry_before_reporting_a_gap(self) -> None:
        for task in ("sentiment_task", "feasibility_task"):
            with self.subTest(task=task):
                text = self.descriptions[task].lower()
                self.assertIn("not an evidence gap yet", text)
                self.assertIn("broadening", text)

    def test_the_retry_is_bounded(self) -> None:
        """Unbounded retry is how a cheap branch becomes an expensive one."""
        for task in ("sentiment_task", "feasibility_task"):
            with self.subTest(task=task):
                self.assertIn("at most three", self.descriptions[task].lower())

    def test_the_gap_report_names_the_queries_tried(self) -> None:
        """A gap nobody can audit is indistinguishable from a lazy branch."""
        for task in ("sentiment_task", "feasibility_task"):
            with self.subTest(task=task):
                self.assertIn("name the queries", self.descriptions[task].lower())

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
