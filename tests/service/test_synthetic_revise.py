"""The synthetic double now branches on `decision`, and this pins that it does.

Closes the half of remaining-work item 15 that no test could reach: `resume()`
read `synthetic_stage` alone and never looked at `decision`, so a `revise` reply
advanced exactly as an `approve` did. Nothing anywhere - unit, E2E or a local
synthetic run - ever traversed `route_scope -> revise_scope` or
`route_verdict -> revise_verdict`, which are real edges in the shipped topology.

A double that diverges from its subject certifies nothing. That lesson is
already recorded twice in this repo (the missing `RUN_STATE.status`, the missing
report body); this is the third instance, and the tests below exist so it is not
a fourth.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from brief_crew.service.runner import (
    SYNTHETIC_MAX_REVISE_TURNS,
    SyntheticValidatorRunner,
)


class _Capture:
    """Records the frames the runner emits, which is all these tests read."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    def emit(self, **kwargs: Any) -> None:
        self.frames.append(kwargs)

    def started(self) -> list[str]:
        return [
            str(frame.get("node_id"))
            for frame in self.frames
            if str(getattr(frame.get("event_type"), "value", frame.get("event_type"))).endswith(
                "NODE_START"
            )
            or "START" in str(frame.get("event_type"))
        ]


class _Execution:
    def __init__(self, idea: str = "a synthetic idea") -> None:
        self.capture = _Capture()
        self.inputs = {"idea": idea}
        self.run_id = "run-synthetic"
        self.flow_id = "flow-synthetic"
        self.checkpoints: list[str] = []

    def checkpoint(self, name: str) -> None:
        self.checkpoints.append(name)


class _Context:
    def __init__(self, stage: int, revise_turns: int = 0) -> None:
        self.metadata = {
            "synthetic_stage": stage,
            "synthetic_revise_turns": revise_turns,
        }


def _reply(decision: str, note: str = "") -> str:
    payload: dict[str, Any] = {"decision": decision}
    if note:
        payload["feedback"] = note
    return json.dumps(payload)


class SyntheticScopeReviseTests(unittest.TestCase):
    """The scope gate, revised."""

    def setUp(self) -> None:
        self.runner = SyntheticValidatorRunner()

    def test_revise_runs_the_revise_node(self) -> None:
        execution = _Execution()
        self.runner.resume(
            execution, context=_Context(stage=1), feedback=_reply("revise", "narrow it")
        )
        self.assertIn("revise_scope", execution.capture.started())

    def test_revise_reopens_the_same_gate(self) -> None:
        execution = _Execution()
        pending = self.runner.resume(
            execution, context=_Context(stage=1), feedback=_reply("revise")
        )
        self.assertEqual(pending.context.method_name, "confirm_scope")
        self.assertEqual(pending.context.metadata["synthetic_stage"], 1)

    def test_revise_does_not_start_the_research_branches(self) -> None:
        # The bug in one assertion: a revise used to run the whole fan-out.
        execution = _Execution()
        self.runner.resume(execution, context=_Context(stage=1), feedback=_reply("revise"))
        started = execution.capture.started()
        for node_id in ("research_market", "research_sentiment", "research_feasibility"):
            self.assertNotIn(node_id, started)

    def test_the_router_runs_on_a_revise_too(self) -> None:
        # Reading the decision is the router's job, so it runs either way.
        execution = _Execution()
        self.runner.resume(execution, context=_Context(stage=1), feedback=_reply("revise"))
        self.assertIn("route_scope", execution.capture.started())

    def test_revise_counts_a_turn(self) -> None:
        execution = _Execution()
        pending = self.runner.resume(
            execution, context=_Context(stage=1), feedback=_reply("revise")
        )
        self.assertEqual(pending.context.metadata["synthetic_revise_turns"], 1)

    def test_turns_accumulate_across_revisions(self) -> None:
        execution = _Execution()
        pending = self.runner.resume(
            execution, context=_Context(stage=1, revise_turns=1), feedback=_reply("revise")
        )
        self.assertEqual(pending.context.metadata["synthetic_revise_turns"], 2)

    def test_at_the_cap_a_revise_goes_forward(self) -> None:
        # The real flow makes the same trade at `VALIDATOR_MAX_GATE_TURNS`:
        # going forward keeps the money already spent and bounds the rest.
        execution = _Execution()
        pending = self.runner.resume(
            execution,
            context=_Context(stage=1, revise_turns=SYNTHETIC_MAX_REVISE_TURNS),
            feedback=_reply("revise"),
        )
        self.assertEqual(pending.context.method_name, "review_verdict")
        self.assertNotIn("revise_scope", execution.capture.started())

    def test_approve_still_advances_to_the_verdict_gate(self) -> None:
        execution = _Execution()
        pending = self.runner.resume(
            execution, context=_Context(stage=1), feedback=_reply("approve")
        )
        self.assertEqual(pending.context.method_name, "review_verdict")
        self.assertEqual(pending.context.metadata["synthetic_stage"], 2)
        self.assertIn("research_market", execution.capture.started())

    def test_approve_does_not_run_the_revise_node(self) -> None:
        execution = _Execution()
        self.runner.resume(execution, context=_Context(stage=1), feedback=_reply("approve"))
        self.assertNotIn("revise_scope", execution.capture.started())

    def test_the_verdict_gate_starts_with_a_fresh_turn_budget(self) -> None:
        # Turns are per gate, matching `claim_revise_turn`'s scope/verdict keys.
        execution = _Execution()
        pending = self.runner.resume(
            execution, context=_Context(stage=1, revise_turns=2), feedback=_reply("approve")
        )
        self.assertEqual(pending.context.metadata["synthetic_revise_turns"], 0)


class SyntheticVerdictReviseTests(unittest.TestCase):
    """The verdict gate, revised."""

    def setUp(self) -> None:
        self.runner = SyntheticValidatorRunner()

    def test_revise_runs_the_revise_node_and_reopens_the_gate(self) -> None:
        execution = _Execution()
        pending = self.runner.resume(
            execution, context=_Context(stage=2), feedback=_reply("revise")
        )
        self.assertIn("revise_verdict", execution.capture.started())
        self.assertEqual(pending.context.method_name, "review_verdict")
        self.assertEqual(pending.context.metadata["synthetic_stage"], 2)

    def test_revise_does_not_write_the_report(self) -> None:
        execution = _Execution()
        self.runner.resume(execution, context=_Context(stage=2), feedback=_reply("revise"))
        started = execution.capture.started()
        self.assertNotIn("write_report", started)
        self.assertNotIn("persist", started)

    def test_revise_rescores(self) -> None:
        # `revise_verdict` re-runs synthesis, so a fresh verdict frame must
        # follow it - otherwise the console would show a stale score beside a
        # gate that has just been reopened.
        execution = _Execution()
        self.runner.resume(execution, context=_Context(stage=2), feedback=_reply("revise"))
        kinds = [str(frame.get("kind")) for frame in execution.capture.frames]
        self.assertTrue(any("VERDICT" in kind.upper() for kind in kinds), kinds)

    def test_at_the_cap_a_revise_finishes_the_run(self) -> None:
        execution = _Execution()
        result = self.runner.resume(
            execution,
            context=_Context(stage=2, revise_turns=SYNTHETIC_MAX_REVISE_TURNS),
            feedback=_reply("revise"),
        )
        self.assertIsInstance(result, dict)
        self.assertIn("markdown_body", result)
        self.assertIn("write_report", execution.capture.started())

    def test_approve_finishes_the_run(self) -> None:
        execution = _Execution()
        result = self.runner.resume(
            execution, context=_Context(stage=2), feedback=_reply("approve")
        )
        self.assertIsInstance(result, dict)
        self.assertIn("persist", execution.capture.started())
        self.assertNotIn("revise_verdict", execution.capture.started())


class SyntheticReplyParsingTests(unittest.TestCase):
    """What counts as a revise, and what does not."""

    def setUp(self) -> None:
        self.runner = SyntheticValidatorRunner()

    def test_an_empty_reply_is_an_approval(self) -> None:
        execution = _Execution()
        pending = self.runner.resume(execution, context=_Context(stage=1), feedback="")
        self.assertEqual(pending.context.method_name, "review_verdict")

    def test_the_decision_is_read_case_insensitively(self) -> None:
        execution = _Execution()
        pending = self.runner.resume(
            execution, context=_Context(stage=1), feedback=json.dumps({"decision": "  REVISE "})
        )
        self.assertEqual(pending.context.method_name, "confirm_scope")

    def test_an_unknown_decision_is_not_a_revise(self) -> None:
        # `_feedback` only ever sends approve or revise; anything else must
        # go forward rather than loop, so a malformed reply cannot wedge a run.
        execution = _Execution()
        pending = self.runner.resume(
            execution, context=_Context(stage=1), feedback=json.dumps({"decision": "maybe"})
        )
        self.assertEqual(pending.context.method_name, "review_verdict")

    def test_a_missing_turn_count_reads_as_zero(self) -> None:
        execution = _Execution()
        context = _Context(stage=1)
        del context.metadata["synthetic_revise_turns"]
        pending = self.runner.resume(execution, context=context, feedback=_reply("revise"))
        self.assertEqual(pending.context.metadata["synthetic_revise_turns"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
