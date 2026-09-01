"""A failing research branch must degrade, not destroy the run.

This exists because of a measured production failure, not a hypothetical.

The market branch timed out (`max_execution_time`), and the whole run died:
`market_task failed` -> `MarketCrew failed` -> `research_market failed` ->
`ValidatorFlow failed` -> `Run failed`. The operator lost the escalation-tier
scope they had already paid for, both gate round trips, AND the completed
evidence from the other two branches - Sentiment and Feasibility had both
logged `Guardrail Passed` before Market gave up.

The mechanism is worth stating, because none of it is visible from the flow:

* CrewAI raises the timeout from `Agent._execute_with_timeout`, on a DIFFERENT
  THREAD from the tool's own `try`. The market tool's careful `failed` /
  `rate_limited` envelopes were therefore unreachable for the one failure that
  actually happened to it.
* `Agent.execute_task` re-raises `TimeoutError` deliberately instead of routing
  it through `_handle_execution_error` the way it routes every other exception.
* The three branches run under `asyncio.gather` with no `return_exceptions`, so
  the first exception propagates at once and the siblings are abandoned mid
  flight.
* `and_(...)` therefore never fires and synthesis never runs.

So the fix cannot live in the tool, and it cannot live in CrewAI. It lives at
the one place that knows a branch is optional: the flow method itself.

What these tests pin is a POLICY, not an implementation: an unexpected
exception in a branch becomes an honest empty-evidence result, and a control
flow exception still propagates. The second half matters as much as the first -
`HookAborted` subclasses plain `Exception` and is the only signal for both
operator cancel and the run cost ceiling, so a careless `except Exception` here
would silently disable the Cancel button and the budget cap.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brief_crew.schemas import (
    FeasibilityFindings,
    MarketFindings,
    SentimentFindings,
)
from brief_crew.validator_flow import (
    ValidatorCrewFactories,
    ValidatorFlow,
    _degraded_findings,
)

from tests.validator.test_flow import FakeRunner, fixtures


class ExplodingRunner:
    """A crew whose kickoff fails the way a timed-out agent fails."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def kickoff(self, inputs: dict[str, object]) -> object:
        raise self.error


def _factories(fx, **overrides):
    """Healthy factories for all six crews, with named ones swapped out.

    `fx` is the 6-tuple from `fixtures()` rather than six positional
    parameters, because parameters named `market`/`sentiment`/`feasibility`
    collide with the `**overrides` keys that have to use those exact names.
    """
    scope, market, sentiment, feasibility, verdict, report = fx
    base = dict(
        scope=lambda: FakeRunner(scope),
        market=lambda: FakeRunner(market),
        sentiment=lambda: FakeRunner(sentiment),
        feasibility=lambda: FakeRunner(feasibility),
        synthesis=lambda *_: FakeRunner(verdict),
        report=lambda *_: FakeRunner(report),
    )
    base.update(overrides)
    return ValidatorCrewFactories(**base)


class DegradedFindingsTests(unittest.TestCase):
    """The shape itself, independent of the flow."""

    def test_every_branch_model_accepts_the_degraded_shape(self) -> None:
        """All three share sources/source_urls/gaps/tool_status; only one adds
        `competitors`, and forgetting it would raise inside the handler that
        exists to stop things raising."""
        for model, branch in (
            (MarketFindings, "market"),
            (SentimentFindings, "sentiment"),
            (FeasibilityFindings, "feasibility"),
        ):
            with self.subTest(branch=branch):
                findings = _degraded_findings(model, branch, TimeoutError("slow"))
                self.assertEqual(findings.sources, [])
                self.assertEqual(findings.source_urls, [])
                self.assertEqual(findings.tool_status, "failed")

    def test_the_gap_names_the_branch_and_the_error(self) -> None:
        """A gap that does not say what broke is indistinguishable from a
        branch that genuinely found nothing - and those need opposite fixes."""
        findings = _degraded_findings(
            MarketFindings, "market", TimeoutError("execution timed out")
        )
        self.assertEqual(len(findings.gaps), 1)
        gap = findings.gaps[0]
        self.assertIn("market", gap)
        self.assertIn("TimeoutError", gap)
        self.assertIn("execution timed out", gap)

    def test_the_gap_is_bounded(self) -> None:
        """It reaches a frame, a report and a 2000-frame ring."""
        findings = _degraded_findings(
            MarketFindings, "market", RuntimeError("x" * 5_000)
        )
        self.assertLessEqual(len(findings.gaps[0]), 500)

    def test_tool_status_failed_is_a_declared_status(self) -> None:
        """Not a new sentinel - the schema and the ladders already read it."""
        findings = _degraded_findings(MarketFindings, "market", RuntimeError("x"))
        self.assertIn(
            findings.tool_status, ("ok", "empty", "rate_limited", "failed")
        )


class BranchDegradationTests(unittest.TestCase):
    def setUp(self) -> None:
        patch(
            "brief_crew.validator_flow.lookup_branch_cache", return_value=[]
        ).start()
        self.addCleanup(patch.stopall)

    def _run(self, **overrides):
        fx = fixtures()
        scope, market, sentiment, feasibility, verdict, report = fx
        factories = _factories(fx, **overrides)
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path):
                flow = ValidatorFlow(crew_factories=factories)
                result = flow.kickoff(
                    inputs={"idea": scope.startup_idea, "no_gates": True}
                )
        return flow, result, (market, sentiment, feasibility, report)

    def test_a_timed_out_market_branch_no_longer_fails_the_run(self) -> None:
        """The exact production failure: the run now reaches its report."""
        flow, result, (_, sentiment, feasibility, report) = self._run(
            market=lambda: ExplodingRunner(
                TimeoutError("Task execution timed out after 120 seconds")
            )
        )

        self.assertEqual(result, report)
        self.assertEqual(flow.state.market.tool_status, "failed")
        self.assertEqual(flow.state.market.sources, [])
        # The whole point: the two branches that DID finish keep their evidence.
        self.assertEqual(flow.state.sentiment, sentiment)
        self.assertEqual(flow.state.feasibility, feasibility)

    def test_each_branch_degrades_independently(self) -> None:
        for branch, model in (
            ("market", MarketFindings),
            ("sentiment", SentimentFindings),
            ("feasibility", FeasibilityFindings),
        ):
            with self.subTest(branch=branch):
                flow, _, _ = self._run(
                    **{branch: lambda: ExplodingRunner(TimeoutError("slow"))}
                )
                self.assertEqual(getattr(flow.state, branch).tool_status, "failed")
                others = {"market", "sentiment", "feasibility"} - {branch}
                for other in others:
                    self.assertNotEqual(
                        getattr(flow.state, other).tool_status,
                        "failed",
                        f"{other} was collateral damage from {branch} failing",
                    )

    def test_a_malformed_branch_output_also_degrades(self) -> None:
        """Not only timeouts. `_extract_model` raises on unparseable output,
        and that used to kill the run just as thoroughly."""
        flow, _, (_, _, _, report) = self._run(
            market=lambda: FakeRunner("this is not a MarketFindings object")
        )
        self.assertEqual(flow.state.market.tool_status, "failed")

    def test_cancellation_still_propagates(self) -> None:
        """The half of this fix that is a safety property, not a convenience.

        `HookAborted` subclasses `Exception` and carries BOTH operator cancel
        and the run cost ceiling. If the degrade path swallowed it, Cancel would
        appear to work and the run would keep spending.
        """
        from crewai.hooks import HookAborted

        with self.assertRaises(HookAborted):
            self._run(market=lambda: ExplodingRunner(HookAborted("cancelled")))

    def test_both_control_flow_exceptions_are_excluded_from_the_degrade_path(
        self,
    ) -> None:
        """Asserted on the guard tuple itself, not through a flow run.

        Driving `HumanFeedbackPending` out of a *branch* crew tests CrewAI's
        flow-level handling of an exception no branch crew actually raises -
        branch crews have no gates - rather than testing this repo's policy. The
        policy is the tuple, so the tuple is what gets pinned.

        `HookAborted` is the one that must never be lost: it subclasses plain
        `Exception` and carries BOTH operator cancel and the run cost ceiling,
        so a bare `except Exception` in a branch would leave Cancel looking like
        it worked while the run kept spending. That path is exercised for real
        in `test_cancellation_still_propagates`.
        """
        from crewai.flow.async_feedback import HumanFeedbackPending
        from crewai.hooks import HookAborted

        from brief_crew.validator_flow import _BRANCH_CONTROL_FLOW

        self.assertIn(HumanFeedbackPending, _BRANCH_CONTROL_FLOW)
        self.assertIn(HookAborted, _BRANCH_CONTROL_FLOW)
        # Both subclass Exception, which is precisely why they need naming.
        for exc in _BRANCH_CONTROL_FLOW:
            self.assertTrue(issubclass(exc, Exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
