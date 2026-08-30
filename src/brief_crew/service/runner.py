"""Injectable production and synthetic run implementations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from threading import Event
from typing import Any, Mapping, Protocol

from brief_crew.events import (
    FrameKind,
    FrameLevel,
    StreamSinkAdapter,
    UIEventType,
)
from brief_crew.events.verdict import (
    VERDICT_NODE_ID,
    verdict_frame_details,
    verdict_frame_message,
)
from brief_crew.schemas.validator import DimensionScore, Verdict


@dataclass(frozen=True, slots=True)
class RunExecution:
    run_id: str
    inputs: Mapping[str, Any]
    capture: StreamSinkAdapter
    flow_id: str | None = None
    persistence: Any = None
    cancel_requested: Event | None = None

    def checkpoint(self, step_name: str) -> None:
        """Abort at an explicit runner boundary when cancellation was requested."""
        if self.cancel_requested is not None and self.cancel_requested.is_set():
            from crewai.hooks import HookAborted

            raise HookAborted(f"cancelled before {step_name}")


class Runner(Protocol):
    def __call__(self, execution: RunExecution) -> Any: ...


class ResumableRunner(Runner, Protocol):
    def resume(
        self,
        execution: RunExecution,
        *,
        context: Any,
        feedback: str,
    ) -> Any: ...


class BriefFlowRunner:
    """Run the existing BriefFlow; imported lazily to keep service imports light."""

    def __call__(self, execution: RunExecution) -> Any:
        from brief_crew.main import BriefFlow

        return BriefFlow().kickoff(inputs=dict(execution.inputs))


@dataclass(slots=True)
class ValidatorFlowRunner:
    """Run and resume ValidatorFlow with the service persistence backend."""

    crew_factories: Any = None

    def __call__(self, execution: RunExecution) -> Any:
        from brief_crew.validator_flow import ValidatorCrewFactories, ValidatorFlow

        factories = self.crew_factories or ValidatorCrewFactories()
        flow = ValidatorFlow(
            persistence=execution.persistence,
            crew_factories=factories,
        )
        inputs = dict(execution.inputs)
        inputs["id"] = execution.flow_id or execution.run_id
        return flow.kickoff(inputs=inputs)

    def resume(
        self,
        execution: RunExecution,
        *,
        context: Any,
        feedback: str,
    ) -> Any:
        from brief_crew.validator_flow import ValidatorCrewFactories, ValidatorFlow

        factories = self.crew_factories or ValidatorCrewFactories()
        flow = ValidatorFlow.from_pending(
            context.flow_id,
            execution.persistence,
            crew_factories=factories,
        )
        return flow.resume(feedback)


class SyntheticRunner:
    """Deterministic no-network runner for tests and local transport checks.

    The RUN_STATE frames below mirror
    `events/serializer.py::FieldBoundedSerializer.drafts` field for field -
    `{"status": ..., "inputs": ...}` on the way in and
    `{"status": ..., "result": ...}` on the way out. A double that emits a
    different shape is not a double: this one used to omit `status`, which is
    the key the Studio client reads, and the omission hid a real defect behind
    a green suite.
    """

    def __call__(self, execution: RunExecution) -> dict[str, Any]:
        topic = str(execution.inputs.get("topic", "synthetic topic"))
        execution.capture.emit(
            kind=FrameKind.RUN_STATE,
            event_type=UIEventType.WORKFLOW_START,
            node_id="workflow",
            message="Synthetic run started",
            details={"status": "running", "inputs": {"topic": topic}},
        )
        execution.capture.emit(
            kind=FrameKind.NODE_STATE,
            event_type=UIEventType.NODE_START,
            node_id="retrieve_cached",
            message="retrieve_cached started",
        )
        execution.capture.emit(
            kind=FrameKind.NODE_STATE,
            event_type=UIEventType.NODE_END,
            node_id="retrieve_cached",
            message="retrieve_cached completed",
        )
        result = {"synthetic": True, "topic": topic}
        execution.capture.emit(
            kind=FrameKind.RUN_STATE,
            event_type=UIEventType.WORKFLOW_END,
            node_id="workflow",
            message="Synthetic run completed",
            details={"status": "completed", "result": result},
            level=FrameLevel.INFO,
        )
        return result


SYNTHETIC_REPORT_MARKDOWN = """# Validation report - {verdict}

**Idea.** {idea}

> This report is produced by `SyntheticValidatorRunner`. No model was called
> and no source was retrieved. It exists so the console's report rendering is
> exercisable at zero cost.

## Score breakdown

| Dimension | Score | Weight | Note |
| --- | --- | --- | --- |
| Demand | {demand} | 0.30 | Synthetic placeholder |
| Market | {market} | 0.20 | Synthetic placeholder |
| Competitive room | {competitive_room} | 0.20 | Synthetic placeholder |
| Feasibility | {feasibility} | 0.15 | Synthetic placeholder |
| Headroom over free | {headroom_over_free} | 0.15 | Synthetic placeholder |

Composite **{composite}** at `{band}` confidence.

## Cheapest next test

1. Interview five target users.
2. Price the wedge against the free alternative.

## Sources

- [Synthetic market note](https://example.com/synthetic-market)
- [Synthetic HN thread](https://news.ycombinator.com/item?id=1)
"""


def _synthetic_report_markdown(idea: str) -> str:
    """The report body, agreeing with `_synthetic_verdict()` by construction."""
    verdict = _synthetic_verdict()
    return SYNTHETIC_REPORT_MARKDOWN.format(
        idea=idea,
        verdict=verdict.verdict,
        demand=verdict.demand.score,
        market=verdict.market.score,
        competitive_room=verdict.competitive_room.score,
        feasibility=verdict.feasibility.score,
        headroom_over_free=verdict.headroom_over_free.score,
        composite=f"{verdict.composite_score:.1f}",
        band=verdict.confidence_band,
    )


def _synthetic_verdict() -> Verdict:
    """A real `Verdict`, not a hand-written summary of one.

    Built through the schema so `compute_mechanical_result` decides the label,
    the composite, the band and the floors here exactly as it does on the paid
    path. A dict of plausible-looking numbers would be a double that certifies
    nothing - the same trap `_finish` records for the report body - and the
    arithmetic is precisely what this frame exists to carry.

    The inputs are chosen so the answer matches what this runner's verdict gate
    already shows: three coverages of 0.62 with a fresh median source age and
    all three branches reporting gives confidence 0.62, and five 3s give a
    composite of 6.0, which is NEEDS_WORK with no floor and no override.
    """

    dimension = DimensionScore(
        score=3,
        anchor_matched="Synthetic evidence supports a middling score.",
        evidence_urls=["https://example.com/synthetic-market"],
    )
    return Verdict(
        demand=dimension,
        market=dimension,
        competitive_room=dimension,
        feasibility=dimension,
        headroom_over_free=dimension,
        evidence_counts={"market_sources": 1, "sentiment_sources": 1},
        market_coverage=0.62,
        sentiment_coverage=0.62,
        feasibility_coverage=0.62,
        median_market_source_age_months=1,
        branches_ok=3,
        cheapest_next_test="Interview five target users.",
    )


class SyntheticValidatorRunner:
    """Synthetic validator that exercises two durable pause/resume rounds."""

    def __call__(self, execution: RunExecution) -> Any:
        execution.checkpoint("scope_idea")
        idea = str(execution.inputs.get("idea", "synthetic idea"))
        execution.capture.emit(
            kind=FrameKind.RUN_STATE,
            event_type=UIEventType.WORKFLOW_START,
            node_id="workflow",
            message="Synthetic validator started",
            details={"status": "running", "inputs": {"idea": idea}},
        )
        self._node(execution, "scope_idea", "Scoper")
        # Unattended mode runs straight through, the way ValidatorFlow does
        # when `ValidatorFeedbackProvider` answers its own gates. Without this
        # branch the toggle would be untestable at zero cost - the double would
        # pause where the real flow does not, which is the same divergence that
        # let the missing report body survive behind a green suite.
        if execution.inputs.get("no_gates"):
            return self._run_unattended(execution, idea)
        return self._pending(
            execution,
            method_name="confirm_scope",
            message="Confirm the parsed scope.",
            output={
                "startup_idea": idea,
                "category": "Synthetic market",
                "target_user": "Synthetic operator",
                "market_query": f"{idea} market",
            },
            stage=1,
        )

    def _run_unattended(self, execution: RunExecution, idea: str) -> Any:
        """Both gates auto-approved: every node runs, nothing pauses."""
        for node_id, label in (
            ("confirm_scope", "Confirm scope"),
            ("route_scope", "Scope router"),
        ):
            self._node(execution, node_id, label)
        execution.checkpoint("research_market")
        for node_id, label in (
            ("research_market", "Market Analyst"),
            ("research_sentiment", "Sentiment Analyst"),
            ("research_feasibility", "Feasibility Analyst"),
            ("synthesize", "Synthesist"),
        ):
            self._node(execution, node_id, label)
        # Unattended is the mode where this frame is the ONLY way the score
        # reaches anyone: no verdict gate opens, so there is no `derived` block
        # to read it out of.
        self._verdict(execution)
        for node_id, label in (
            ("review_verdict", "Review verdict"),
            ("route_verdict", "Verdict router"),
        ):
            self._node(execution, node_id, label)
        execution.checkpoint("write_report")
        self._node(execution, "write_report", "Reporter")
        self._node(execution, "persist", "Validation brief")
        return self._finish(execution, idea, {"decision": "approve", "unattended": True})

    def resume(
        self,
        execution: RunExecution,
        *,
        context: Any,
        feedback: str,
    ) -> Any:
        payload = json.loads(feedback or "{}")
        stage = int(context.metadata.get("synthetic_stage", 1))
        if stage == 1:
            self._node(execution, "route_scope", "Scope router")
            execution.checkpoint("research_market")
            for node_id, label in (
                ("research_market", "Market Analyst"),
                ("research_sentiment", "Sentiment Analyst"),
                ("research_feasibility", "Feasibility Analyst"),
                ("synthesize", "Synthesist"),
            ):
                self._node(execution, node_id, label)
            self._verdict(execution)
            return self._pending(
                execution,
                method_name="review_verdict",
                message="Review the scored verdict.",
                output={
                    "verdict": "NEEDS_WORK",
                    "confidence": 0.62,
                    "cheapest_next_test": "Interview five target users.",
                    "scope_reply": payload,
                },
                stage=2,
            )

        self._node(execution, "route_verdict", "Verdict router")
        execution.checkpoint("write_report")
        self._node(execution, "write_report", "Reporter")
        self._node(execution, "persist", "Validation brief")
        idea = str(execution.inputs.get("idea", "synthetic idea"))
        return self._finish(execution, idea, payload)

    @staticmethod
    def _finish(execution: RunExecution, idea: str, payload: Any) -> Any:
        # Shaped like `schemas/validator.py::ValidationReport`, because the
        # console reads `result.markdown_body` and this double used to return a
        # result with no body at all. That made report rendering *untestable*
        # on the free path - no unit test, no E2E test and no local synthetic
        # run could ever exercise it - which is how the client came to drop the
        # report at three layers behind 133 green tests. Keep this in the real
        # shape; a double that diverges from its subject certifies nothing.
        result = {
            "synthetic": True,
            # Rendered from the SAME `Verdict` the verdict frame carries, not from
            # hardcoded numbers. They disagreed once - the scorecard read 6.0
            # while the prose underneath it read 5.6 - and a double whose two
            # halves contradict each other is worse than no double, because it
            # teaches whoever reads it that one of the two is lying without
            # saying which.
            "markdown_body": _synthetic_report_markdown(idea),
            "provisional": True,
            "thin_dimensions": ["D", "X"],
            "sources": [
                {"url": "https://example.com/synthetic-market", "title": "Synthetic market note"},
                {"url": "https://news.ycombinator.com/item?id=1", "title": "Synthetic HN thread"},
            ],
            "idea": idea,
            "verdict": "NEEDS_WORK",
            "feedback": payload,
        }
        execution.capture.emit(
            kind=FrameKind.RUN_STATE,
            event_type=UIEventType.WORKFLOW_END,
            node_id="workflow",
            message="Synthetic validator completed",
            details={"status": "completed", "result": result},
        )
        return result

    @staticmethod
    def _verdict(execution: RunExecution) -> None:
        """Publish the deterministic score the way the real serializer does.

        The paid path raises a `VerdictComputedEvent` and the serializer turns
        it into this frame; a synthetic run has no flow to raise one, so it
        emits the frame directly - through the same payload builder, so the two
        cannot drift.
        """

        verdict = _synthetic_verdict()
        execution.capture.emit(
            kind=FrameKind.VERDICT,
            event_type=UIEventType.VERDICT_COMPUTED,
            node_id=VERDICT_NODE_ID,
            message=verdict_frame_message(verdict),
            details=verdict_frame_details(verdict),
        )

    @staticmethod
    def _node(execution: RunExecution, node_id: str, label: str) -> None:
        execution.capture.emit(
            kind=FrameKind.NODE_STATE,
            event_type=UIEventType.NODE_START,
            node_id=node_id,
            message=f"{label} started",
        )
        execution.capture.emit(
            kind=FrameKind.NODE_STATE,
            event_type=UIEventType.NODE_END,
            node_id=node_id,
            message=f"{label} completed",
        )

    @staticmethod
    def _pending(
        execution: RunExecution,
        *,
        method_name: str,
        message: str,
        output: dict[str, Any],
        stage: int,
    ) -> Any:
        from crewai.flow.async_feedback import HumanFeedbackPending, PendingFeedbackContext

        return HumanFeedbackPending(
            context=PendingFeedbackContext(
                flow_id=execution.flow_id or execution.run_id,
                flow_class="brief_crew.service.runner.SyntheticValidatorRunner",
                method_name=method_name,
                method_output=output,
                message=message,
                emit=None,
                metadata={"synthetic_stage": stage},
                requested_at=datetime.now(timezone.utc),
            ),
            callback_info={"synthetic": True},
        )
