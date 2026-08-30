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
        result = {
            "synthetic": True,
            "idea": str(execution.inputs.get("idea", "synthetic idea")),
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
