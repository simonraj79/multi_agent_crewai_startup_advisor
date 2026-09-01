"""The last two steps must not be able to destroy the run.

`write_report` and `persist` sit at the end of the pipeline, which is the worst
possible place for an un-guarded failure. By the time either runs, the operator
has already paid for an escalation-tier scope, three live research branches,
two gate round trips and an escalation-tier synthesis. Both used to discard all
of it:

* `write_report` called `.kickoff()` bare, while all three research branches
  wrapped the identical call. There are three ordinary ways to get an exception
  out of it - `Crew.kickoff` re-raises, guardrail exhaustion raises a plain
  `Exception`, and `Agent.execute_task` deliberately re-raises `TimeoutError`
  rather than routing it through `_handle_execution_error`.
* `persist` is the flow's TERMINAL listener, so its return value *is* what
  `kickoff()` hands back, what `RunRecord.mark_completed` stores, and what
  `GET /api/runs/{id}` serves as `result` - and `mark_failed` never assigns
  `self.result` at all. Its `mkdir`/`write_text` were unguarded, so a read-only
  volume or an exhausted disk turned a finished report into no output at all.

The policy pinned here is the same one `test_branch_degradation.py` pins one
layer up: an unexpected exception degrades to an honest, clearly-labelled
result, and a control-flow exception still propagates.

Deliberately NOT extended to `_run_synthesis`. A mechanically fabricated
`Verdict` would carry a REJECT or a `FLOOR_*` that no evidence supports, and
the schema would then recompute a composite score over invented dimensions. A
missing verdict must fail loudly; a missing *rendering* of a real verdict must
not.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crewai.flow.async_feedback import HumanFeedbackPending, PendingFeedbackContext

from brief_crew.schemas import ValidationReport
from brief_crew.validator_guardrails import report_mechanics_problems
from brief_crew.validator_flow import (
    ValidatorCrewFactories,
    ValidatorFlow,
    _degraded_report,
)

from tests.validator.test_branch_degradation import ExplodingRunner, _factories
from tests.validator.test_flow import fixtures


class DegradedReportShapeTests(unittest.TestCase):
    """The rendering itself, independent of the flow."""

    def setUp(self) -> None:
        self.fx = fixtures()

    def _report(self, exc: BaseException | None = None) -> ValidationReport:
        scope, market, sentiment, feasibility, verdict, _ = self.fx
        return _degraded_report(
            scope,
            verdict,
            (market, sentiment, feasibility),
            exc or RuntimeError("guardrail retries exhausted"),
        )

    def test_it_is_a_valid_validation_report(self) -> None:
        """Not a dict shaped like one. Every downstream reader assumes the model."""
        report = self._report()
        self.assertIsInstance(report, ValidationReport)
        self.assertTrue(report.markdown_body.strip())

    def test_the_first_line_says_it_was_not_written_by_the_reporter(self) -> None:
        """An operator must never mistake this for the Reporter's prose.

        It is machine-assembled from validated state - the scores and citations
        are real - but the analysis is missing, and that is the failure.
        """
        report = self._report(TimeoutError("execution timed out"))
        body = report.markdown_body
        self.assertIn("assembled mechanically", body)
        self.assertIn("TimeoutError", body)

    def test_it_carries_the_real_verdict_rather_than_inventing_one(self) -> None:
        *_, verdict, _ = self.fx
        report = self._report()

        self.assertEqual(report.provisional, verdict.provisional)
        self.assertIn(verdict.verdict, report.markdown_body)
        self.assertIn(verdict.cheapest_next_test, report.markdown_body)
        # Every dimension's score and its matched anchor reach the page.
        for dimension in (
            verdict.demand,
            verdict.market,
            verdict.competitive_room,
            verdict.feasibility,
            verdict.headroom_over_free,
        ):
            self.assertIn(dimension.anchor_matched, report.markdown_body)

    def test_thin_dimensions_are_read_off_the_verdict(self) -> None:
        *_, verdict, _ = self.fx
        expected = [
            code
            for code, dimension in (
                ("D", verdict.demand),
                ("M", verdict.market),
                ("C", verdict.competitive_room),
                ("F", verdict.feasibility),
                ("X", verdict.headroom_over_free),
            )
            if dimension.evidence_thin
        ]
        self.assertEqual(self._report().thin_dimensions, expected)

    def test_sources_are_projected_from_all_three_branches(self) -> None:
        """The branches do NOT share a source type, and only market's is Evidence.

        `SentimentFindings.sources` is `list[Thread]` and
        `FeasibilityFindings.sources` is `list[Repo]`, while
        `ValidationReport.sources` demands `Evidence`. Projecting them wrong
        raises inside the handler that exists to stop things raising.
        """
        _, market, sentiment, feasibility, _, _ = self.fx
        report = self._report()
        urls = {source.url for source in report.sources}

        for branch in (market, sentiment, feasibility):
            for source in branch.sources:
                self.assertIn(source.url, urls)

    def test_a_url_in_two_branches_appears_once(self) -> None:
        """`validate_unique_sources` rejects duplicates outright, and the same
        URL legitimately turns up in more than one branch."""
        report = self._report()
        urls = [source.url for source in report.sources]
        self.assertEqual(len(urls), len(set(urls)))

    def test_it_satisfies_the_project_s_own_report_guardrail(self) -> None:
        """The fallback obeys the SAME contract every other report obeys.

        It did not, at first: `report_mechanics_problems` requires the word
        "provisional" in both the title and the first summary line whenever the
        verdict is provisional, and the degraded body carried neither. A
        fallback that would be rejected by the project's own guardrail is a
        second-class artefact, and that is exactly the quiet divergence that
        makes a degrade path untrustworthy.
        """
        *_, verdict, _ = self.fx
        report = self._report()

        self.assertEqual(report_mechanics_problems(report, verdict=verdict), [])
        # And the labelling is real, not incidental - this fixture IS provisional.
        self.assertTrue(verdict.provisional)
        self.assertIn("provisional", report.markdown_body.splitlines()[0].casefold())

    def test_a_pipe_or_newline_cannot_break_the_document(self) -> None:
        """`anchor_matched` and `claim` are free text the models write.

        Three of the constructs here are line-oriented - an ATX heading, a
        table row and a list item - so an unescaped `|` adds a phantom column
        and silently shifts every cell after it, and a newline ends the
        construct early.
        """
        scope, market, sentiment, feasibility, verdict, _ = self.fx
        hostile = verdict.model_copy(
            update={
                "demand": verdict.demand.model_copy(
                    update={"anchor_matched": "a | b\nc | d"}
                ),
                "cheapest_next_test": "ask five\nusers | quickly",
            }
        )
        report = _degraded_report(
            scope, hostile, (market, sentiment, feasibility), RuntimeError("x")
        )

        rows = [
            line
            for line in report.markdown_body.splitlines()
            if line.startswith("| Demand")
        ]
        self.assertEqual(len(rows), 1)
        # Four unescaped pipes = the two outer ones plus three column
        # separators. Escaped pipes from the hostile text do not count.
        self.assertEqual(rows[0].count("|") - rows[0].count("\\|"), 4)
        # The hostile newline was flattened rather than ending the row.
        self.assertIn("a \\| b c \\| d", rows[0])

    def test_a_repository_is_never_dated_as_though_it_were_published(self) -> None:
        """Closed-ledger item 25: a retrieval timestamp read as freshness biases
        `median_market_source_age_months` young. GitHub reports no publication
        date, so every projected repo must carry the flag."""
        _, _, _, feasibility, _, _ = self.fx
        repo_urls = {repo.url for repo in feasibility.sources}
        projected = [s for s in self._report().sources if s.url in repo_urls]

        self.assertTrue(projected)
        for source in projected:
            self.assertTrue(source.dated_is_retrieval_time)


class ReportStepDegradationTests(unittest.TestCase):
    """The flow, driven end to end with a failing report crew."""

    def setUp(self) -> None:
        patch(
            "brief_crew.validator_flow.ValidatorFlow._index_evidence",
            lambda *args, **kwargs: None,
        ).start()
        self.addCleanup(patch.stopall)

    def _run(self, **overrides):
        fx = fixtures()
        scope = fx[0]
        factories = _factories(fx, **overrides)
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path):
                flow = ValidatorFlow(crew_factories=factories)
                result = flow.kickoff(
                    inputs={"idea": scope.startup_idea, "no_gates": True}
                )
                written = output_path.read_text(encoding="utf-8") if output_path.exists() else None
        return flow, result, written

    def test_a_failing_reporter_still_produces_a_report(self) -> None:
        """The whole point. This raised before 2026-09-01, losing everything."""
        _, result, written = self._run(
            report=lambda *_: ExplodingRunner(
                Exception("Task failed guardrail validation after 2 retries.")
            )
        )

        self.assertIsInstance(result, ValidationReport)
        self.assertIn("assembled mechanically", result.markdown_body)
        # And the degraded body is what reached disk, not the Reporter's.
        self.assertIsNotNone(written)
        self.assertIn("assembled mechanically", written or "")

    def test_a_timed_out_reporter_degrades_too(self) -> None:
        """`Agent.execute_task` re-raises TimeoutError rather than handling it."""
        _, result, _ = self._run(
            report=lambda *_: ExplodingRunner(
                TimeoutError("Task execution timed out after 120 seconds")
            )
        )
        self.assertIsInstance(result, ValidationReport)
        self.assertIn("TimeoutError", result.markdown_body)

    def test_a_healthy_reporter_is_untouched(self) -> None:
        """Control: the degrade path must not shadow the real report."""
        fx = fixtures()
        expected = fx[5]
        _, result, _ = self._run()

        self.assertEqual(result.markdown_body, expected.markdown_body)
        self.assertNotIn("assembled mechanically", result.markdown_body)

    def test_control_flow_exceptions_still_propagate(self) -> None:
        """`HumanFeedbackPending` is how a durable gate suspends a run.

        Swallowing it here would turn a gate into a fabricated report and lose
        the pending-feedback row the resume depends on.
        """
        # Built OUTSIDE the lambda deliberately. Constructing it inside would
        # make a wrong signature raise a TypeError from within `write_report`'s
        # own try block, which degrades - so the test would pass for the exact
        # reason it is meant to detect. (That is what happened first.)
        pending = HumanFeedbackPending(
            PendingFeedbackContext(
                flow_id="test-flow",
                flow_class="ValidatorFlow",
                method_name="write_report",
                method_output=None,
                message="waiting on a human",
            )
        )

        _, result, written = self._run(report=lambda *_: ExplodingRunner(pending))

        # `kickoff()` RETURNS the pause rather than raising it - that is how
        # CrewAI suspends a flow for a durable gate, and it is why this test
        # cannot simply use `assertRaises`. What matters is that `write_report`
        # did not convert it into a report.
        self.assertIsInstance(result, HumanFeedbackPending)
        self.assertNotIsInstance(result, ValidationReport)
        self.assertIsNone(written)


class PersistCannotVetoTests(unittest.TestCase):
    """A convenience file must never cost the deliverable."""

    def setUp(self) -> None:
        patch(
            "brief_crew.validator_flow.ValidatorFlow._index_evidence",
            lambda *args, **kwargs: None,
        ).start()
        self.addCleanup(patch.stopall)

    def test_an_unwritable_path_does_not_fail_the_run(self) -> None:
        """Measured: this raised `FileExistsError` from `kickoff()` while
        `flow.state.report` held the finished report the operator had paid for.

        The parent of the output path is made a FILE, so `mkdir(parents=True)`
        cannot succeed - which is the cheap, portable stand-in for a read-only
        volume or an exhausted disk on a container.
        """
        fx = fixtures()
        scope, expected = fx[0], fx[5]
        factories = _factories(fx)

        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "output"
            blocker.write_text("I am a file, not a directory.", encoding="utf-8")
            output_path = blocker / "validation.md"

            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path):
                flow = ValidatorFlow(crew_factories=factories)
                result = flow.kickoff(
                    inputs={"idea": scope.startup_idea, "no_gates": True}
                )

        self.assertIsInstance(result, ValidationReport)
        self.assertEqual(result.markdown_body, expected.markdown_body)
        self.assertEqual(flow.state.report, result)

    def test_the_file_is_still_written_when_it_can_be(self) -> None:
        """Control: best-effort must not become never-effort."""
        fx = fixtures()
        scope, expected = fx[0], fx[5]
        factories = _factories(fx)

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path):
                ValidatorFlow(crew_factories=factories).kickoff(
                    inputs={"idea": scope.startup_idea, "no_gates": True}
                )

            self.assertTrue(output_path.exists())
            self.assertEqual(
                output_path.read_text(encoding="utf-8"), expected.markdown_body
            )


if __name__ == "__main__":
    unittest.main()
