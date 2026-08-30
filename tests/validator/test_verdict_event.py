"""The deterministic verdict must leave the flow, in every gate mode.

`Verdict.compute_mechanical_result` recomputes and overwrites the Synthesist's
arithmetic; the rubric, the guardrails and the whole escalation-tier synthesis
step exist so the label is derived rather than generated. Before
`VerdictComputedEvent` that derivation escaped the flow through exactly one
door - the verdict gate's read-only `derived` block - and the run modes below
are the two that show why that was not enough:

* Unattended (`no_gates=True`, which is what the service's `gates: "auto"`
  selects) opens no verdict gate at all, so the score was structurally
  unreachable in the one mode designed to produce it without a human.
* Gated runs did carry it, once, at the moment the gate opened - and a revise
  re-runs synthesis and recomputes the whole verdict, which the operator then
  saw only if a second gate happened to open with it.

Every test here runs the real `ValidatorFlow` against injected crew doubles, so
nothing calls a model and nothing touches the network.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crewai.flow import build_flow_structure

from brief_crew.events import (
    CaptureContext,
    FrameBuffer,
    FrameData,
    FrameKind,
    NodeRegistry,
    StreamSinkAdapter,
    capture_events,
)
from brief_crew.schemas import DimensionScore, Verdict
from brief_crew.validator_flow import (
    ValidatorCrewFactories,
    ValidatorFeedbackProvider,
    ValidatorFlow,
)

from tests.validator.test_flow import FakeRunner, fixtures


class SequenceRunner:
    """A crew double whose answer changes between calls.

    The revise loop is only meaningful when the second synthesis disagrees with
    the first: a double that returns the same object twice would let a flow that
    republished nothing pass, because the frame it failed to emit would have
    carried identical values anyway.
    """

    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.calls = 0

    def kickoff(self, inputs: dict[str, object]) -> object:
        self.calls += 1
        return self.results[min(self.calls, len(self.results)) - 1]


def _rescored(base: Verdict, score: int) -> Verdict:
    """`base` with every dimension moved to `score`, revalidated.

    Built through the schema rather than by editing fields, because rebuilding
    is what re-runs `compute_mechanical_result` - which is the thing under test.
    """

    dimension = DimensionScore(
        score=score,
        anchor_matched=f"A rubric anchor standing in for level {score}.",
        evidence_urls=list(base.demand.evidence_urls),
    )
    return Verdict.model_validate(
        {
            **base.model_dump(),
            "demand": dimension.model_dump(),
            "market": dimension.model_dump(),
            "competitive_room": dimension.model_dump(),
            "feasibility": dimension.model_dump(),
            "headroom_over_free": dimension.model_dump(),
        }
    )


class VerdictEventTestCase(unittest.TestCase):
    def setUp(self) -> None:
        patch(
            "brief_crew.validator_flow.lookup_branch_cache", return_value=[]
        ).start()
        patch(
            "brief_crew.validator_flow.index_captured_evidence", return_value=0
        ).start()
        self.addCleanup(patch.stopall)
        self.registry = NodeRegistry.from_flow_structure(
            build_flow_structure(ValidatorFlow)
        )

    def _capture(self, run_id: str) -> tuple[FrameBuffer, CaptureContext]:
        buffer = FrameBuffer()
        adapter = StreamSinkAdapter(
            run_id=run_id, buffer=buffer, registry=self.registry
        )
        return buffer, CaptureContext(run_id=run_id, adapter=adapter)

    @staticmethod
    def _verdict_frames(buffer: FrameBuffer) -> list[FrameData]:
        return [
            frame
            for frame in buffer.replay(after=0, limit=500)
            if frame.kind is FrameKind.VERDICT
        ]

    def _run(
        self,
        *,
        run_id: str,
        factories: ValidatorCrewFactories,
        inputs: dict[str, object],
        provider=None,
    ) -> tuple[FrameBuffer, object]:
        buffer, capture = self._capture(run_id)
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with contextlib.ExitStack() as stack:
                stack.enter_context(
                    patch("brief_crew.validator_flow.OUTPUT_PATH", output_path)
                )
                if provider is not None:
                    stack.enter_context(
                        patch.object(
                            ValidatorFeedbackProvider, "request_feedback", provider
                        )
                    )
                stack.enter_context(capture_events(capture))
                result = ValidatorFlow(crew_factories=factories).kickoff(inputs=inputs)
        return buffer, result

    # ------------------------------------------------------------ unattended

    def test_unattended_runs_publish_the_verdict_with_no_gate_to_carry_it(self) -> None:
        """The whole point of the event.

        `no_gates=True` is what `gates: "auto"` sets, and it auto-approves both
        gates through `ValidatorFeedbackProvider`. No verdict gate ever opens,
        so before this frame the composite, the confidence and the label of an
        unattended run were unavailable to anyone - not on the socket, not on
        `GET /api/runs/{id}`, not in the exported log.
        """

        scope, market, sentiment, feasibility, verdict, report = fixtures()
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market),
            sentiment=lambda: FakeRunner(sentiment),
            feasibility=lambda: FakeRunner(feasibility),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
        )
        buffer, result = self._run(
            run_id="unattended",
            factories=factories,
            inputs={"idea": scope.startup_idea, "no_gates": True},
        )

        self.assertEqual(result, report)
        # And no gate opened, which is the precondition that makes this the only
        # carrier rather than a convenience.
        self.assertEqual(
            [
                frame
                for frame in buffer.replay(after=0, limit=500)
                if frame.kind is FrameKind.GATE_OPEN
            ],
            [],
        )
        frames = self._verdict_frames(buffer)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].node_id, "synthesize")
        self.assertEqual(frames[0].details["verdict"], verdict.verdict)
        self.assertEqual(
            frames[0].details["composite_score"], verdict.composite_score
        )
        self.assertEqual(frames[0].details["confidence"], verdict.confidence)

    # ----------------------------------------------------------------- gated

    def test_gated_runs_publish_the_same_frame(self) -> None:
        """The mode that already had a door still gets the second one.

        A gated run's verdict reached the operator inside the gate prompt, which
        is a different payload with a different lifetime: it is cleared the
        moment the gate is answered. The frame is durable, replayable and
        mirrored into the run snapshot, so a client that reconnects after the
        gate closed can still show the score.
        """

        scope, market, sentiment, feasibility, verdict, report = fixtures()
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market),
            sentiment=lambda: FakeRunner(sentiment),
            feasibility=lambda: FakeRunner(feasibility),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
        )
        replies = ['{"decision": "approve"}', '{"decision": "approve"}']

        def scripted(_provider: object, _context: object, _flow: object) -> str:
            return replies.pop(0)

        buffer, result = self._run(
            run_id="gated",
            factories=factories,
            inputs={"idea": scope.startup_idea},
            provider=scripted,
        )

        self.assertEqual(result, report)
        frames = self._verdict_frames(buffer)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].details["verdict"], verdict.verdict)

    # ---------------------------------------------------------------- revise

    def test_a_revise_republishes_the_recomputed_verdict(self) -> None:
        """A correction the operator asked for must reach them.

        `revise_verdict` sends the Synthesist back to rescore against the same
        evidence, and `compute_mechanical_result` runs again on what comes back
        - so the composite, the band, the floors and the label can all change.
        Publishing only the first would leave a stale score on screen and in the
        run snapshot, contradicting the report the same run then writes.

        This is also why the emit site is `_run_synthesis` rather than
        `synthesize`: both entry points to that helper produce a verdict, and
        only one of them is the first.
        """

        scope, market, sentiment, feasibility, verdict, report = fixtures()
        rescored = _rescored(verdict, 5)
        self.assertNotEqual(rescored.composite_score, verdict.composite_score)
        synthesis = SequenceRunner(verdict, rescored)
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market),
            sentiment=lambda: FakeRunner(sentiment),
            feasibility=lambda: FakeRunner(feasibility),
            synthesis=lambda *_: synthesis,
            report=lambda *_: FakeRunner(report),
        )
        replies = [
            '{"decision": "approve"}',
            '{"decision": "revise", "feedback": "recheck the demand score"}',
            '{"decision": "approve"}',
        ]
        asked: list[str] = []

        def scripted(_provider: object, context: object, _flow: object) -> str:
            asked.append(context.method_name)
            return replies.pop(0)

        buffer, result = self._run(
            run_id="revised",
            factories=factories,
            inputs={"idea": scope.startup_idea},
            provider=scripted,
        )

        self.assertEqual(result, report)
        self.assertEqual(
            asked, ["confirm_scope", "review_verdict", "review_verdict"]
        )
        self.assertEqual(synthesis.calls, 2)

        frames = self._verdict_frames(buffer)
        self.assertEqual(len(frames), 2)
        # Ordered, and the second is the one the run stands behind.
        self.assertEqual(frames[0].details["verdict"], verdict.verdict)
        self.assertEqual(
            frames[0].details["composite_score"], verdict.composite_score
        )
        self.assertEqual(frames[1].details["verdict"], rescored.verdict)
        self.assertEqual(
            frames[1].details["composite_score"], rescored.composite_score
        )
        self.assertLess(frames[0].seq, frames[1].seq)
        # Both on the node the client shows the score on, so the correction
        # replaces the stale value instead of appearing beside it.
        self.assertEqual({frame.node_id for frame in frames}, {"synthesize"})

    # --------------------------------------------------------------- scoping

    def test_publishing_outside_a_capture_scope_is_a_no_op_not_a_failure(self) -> None:
        """The CLI has no sink, and must still finish.

        `validate --idea ...` runs the same flow with no `capture_events`
        context, so `publish_stream_event` fans out to nothing. A run that could
        only complete when someone was watching would be a worse bug than the
        one this event fixes.
        """

        scope, market, sentiment, feasibility, verdict, report = fixtures()
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market),
            sentiment=lambda: FakeRunner(sentiment),
            feasibility=lambda: FakeRunner(feasibility),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
        )
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output" / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path):
                result = ValidatorFlow(crew_factories=factories).kickoff(
                    inputs={"idea": scope.startup_idea, "no_gates": True}
                )
        self.assertEqual(result, report)


if __name__ == "__main__":
    unittest.main()
