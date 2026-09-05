"""Frame-building helpers, shared by every test in this package.

Named so `unittest discover`'s default `test*.py` pattern walks past it. The
frames it builds are the real `FrameData` the transport carries, not a
lookalike: a double that diverges from its subject certifies nothing, and this
repository has paid for that lesson four times over.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from brief_crew.events.models import FrameData, FrameKind, FrameLevel, UIEventType
from brief_crew.observability.backend import RecordingBackend, RecordedObservation
from brief_crew.observability.langfuse_exporter import LangfuseExporter, RunFacts
from brief_crew.observability.policy import ExporterPolicy


BASE = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
RUN_ID = "11111111-2222-4333-8444-555555555555"


class Recorder:
    """A frame sequence builder that keeps its own sequence numbers."""

    def __init__(self, run_id: str = RUN_ID) -> None:
        self.run_id = run_id
        self._seq = 0
        self.frames: list[FrameData] = []

    def add(
        self,
        kind: FrameKind,
        event_type: UIEventType,
        node_id: str,
        details: dict[str, Any] | None = None,
        *,
        level: FrameLevel = FrameLevel.INFO,
        message: str = "frame",
        offset_ms: int | None = None,
        duration_ms: int | None = None,
    ) -> FrameData:
        self._seq += 1
        frame = FrameData(
            seq=self._seq,
            run_id=self.run_id,
            ts=BASE + timedelta(milliseconds=offset_ms if offset_ms is not None else self._seq),
            kind=kind,
            event_type=event_type,
            level=level,
            node_id=node_id,
            message=message,
            details=details or {},
            duration_ms=duration_ms,
        )
        self.frames.append(frame)
        return frame

    # -- the shapes the frame pipeline actually produces ------------------

    def run_started(self, inputs: dict[str, Any] | None = None) -> None:
        self.add(
            FrameKind.RUN_STATE,
            UIEventType.WORKFLOW_START,
            "workflow",
            {"status": "running", "inputs": inputs or {}},
        )

    def run_completed(self, result: Any = None) -> None:
        self.add(
            FrameKind.RUN_STATE,
            UIEventType.WORKFLOW_END,
            "workflow",
            {"status": "completed", "result": result},
        )

    def run_failed(self, error: str, error_class: str = "RuntimeError") -> None:
        self.add(
            FrameKind.ERROR,
            UIEventType.WORKFLOW_END,
            "workflow",
            {"error": error, "error_class": error_class},
            level=FrameLevel.ERROR,
        )

    def run_cancelled(self, **extra: Any) -> None:
        self.add(
            FrameKind.RUN_STATE,
            UIEventType.WORKFLOW_END,
            "workflow",
            {"status": "cancelled", **extra},
            level=FrameLevel.WARNING,
        )

    def node_started(self, node_id: str, **identity: Any) -> None:
        self.add(
            FrameKind.NODE_STATE,
            UIEventType.NODE_START,
            node_id,
            {"stage": "before", **identity},
        )

    def node_ended(self, node_id: str, **identity: Any) -> None:
        self.add(
            FrameKind.NODE_STATE,
            UIEventType.NODE_END,
            node_id,
            {"stage": "after", **identity},
        )

    def model_call(
        self,
        node_id: str,
        call_id: str,
        model: str = "provider/model",
        *,
        prompt_tokens: int = 100,
        completion_tokens: int = 20,
        cost_usd: float | None = 0.001,
        response_id: str | None = None,
        text: str = "",
        **identity: Any,
    ) -> None:
        self.add(
            FrameKind.LLM,
            UIEventType.MODEL_CALL,
            node_id,
            {"stage": "before", "call_id": call_id, "model": model, **identity},
        )
        self.add(
            FrameKind.LLM,
            UIEventType.MODEL_CALL,
            node_id,
            {
                "stage": "after",
                "call_id": call_id,
                "model": model,
                "finish_reason": "stop",
                "response_id": response_id,
                **identity,
            },
        )
        if text:
            self.add(
                FrameKind.LLM,
                UIEventType.MODEL_CALL,
                node_id,
                {
                    "stage": "utterance",
                    "call_id": call_id,
                    "text": text,
                    "truncated": False,
                    "model": model,
                    **identity,
                },
            )
        usage = {
            "successful_requests": 1,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "call_count": 1,
            "cost_usd": cost_usd,
        }
        self.add(
            FrameKind.TOKEN,
            UIEventType.MODEL_CALL,
            node_id,
            {"call_id": call_id, "model": model, "usage": usage, "cost_usd": cost_usd, **identity},
        )

    def model_call_failed(
        self,
        node_id: str,
        call_id: str,
        model: str = "provider/model",
        error: str = "ProviderError: upstream refused the request",
        **identity: Any,
    ) -> None:
        self.add(
            FrameKind.LLM,
            UIEventType.MODEL_CALL,
            node_id,
            {"stage": "before", "call_id": call_id, "model": model, **identity},
        )
        self.add(
            FrameKind.LLM,
            UIEventType.MODEL_CALL,
            node_id,
            {"stage": "error", "call_id": call_id, "model": model, "error": error, **identity},
            level=FrameLevel.ERROR,
        )

    def guardrail(self, node_id: str, *, success: bool, retry_count: int = 0, **identity: Any) -> None:
        self.add(
            FrameKind.GUARDRAIL,
            UIEventType.GUARDRAIL_CHECK,
            node_id,
            {
                "stage": "after",
                "guardrail": "output check",
                "success": success,
                "retry_count": retry_count,
                **identity,
            },
            level=FrameLevel.INFO if success else FrameLevel.WARNING,
        )

    def tool_call(
        self,
        node_id: str,
        tool: str,
        *,
        args: dict[str, Any] | None = None,
        status: str = "ok",
        error: str | None = None,
        **identity: Any,
    ) -> None:
        self.add(
            FrameKind.TOOL,
            UIEventType.TOOL_CALL,
            node_id,
            {
                "stage": "before",
                "tool": tool,
                "query": "a query",
                "args": args or {},
                "input_preview": str(args or {}),
                **identity,
            },
        )
        if error is not None:
            self.add(
                FrameKind.TOOL,
                UIEventType.TOOL_CALL,
                node_id,
                {"stage": "error", "tool": tool, "query": "a query", "error": error, **identity},
                level=FrameLevel.ERROR,
            )
            return
        self.add(
            FrameKind.TOOL,
            UIEventType.TOOL_CALL,
            node_id,
            {
                "stage": "after",
                "tool": tool,
                "query": "a query",
                "tool_status": status,
                "result_count": 3,
                "from_cache": False,
                "output_preview": "some result text",
                **identity,
            },
        )

    def gate_opened(self, node_id: str, gate_id: str) -> None:
        self.add(
            FrameKind.GATE_OPEN,
            UIEventType.HUMAN_INTERACTION,
            node_id,
            {"stage": "before", "gate_id": gate_id, "options": [], "output": {}},
        )


def exporter_for(
    backend: RecordingBackend | None = None,
    *,
    facts: RunFacts | None = None,
    **policy_overrides: Any,
) -> tuple[LangfuseExporter, RecordingBackend]:
    """An exporter with NO background thread, driving a recording backend.

    `start_thread=False` on purpose: a test that drives the queue itself is
    deterministic, and one that races a daemon thread is the flaky test this
    repository has already paid for twice in its E2E suite.
    """

    recording = backend if backend is not None else RecordingBackend()
    policy = ExporterPolicy(
        public_key="pk",
        secret_key="sk",
        base_url="http://langfuse.invalid",
        enabled=True,
        environment="synthetic",
        **policy_overrides,
    )
    exporter = LangfuseExporter(policy, sender=recording, start_thread=False)
    if facts is not None:
        exporter.begin_run(facts)
    return exporter, recording


def drive(exporter: LangfuseExporter, frames: Iterable[FrameData], run_id: str = RUN_ID) -> None:
    """Push frames through the exporter exactly as the capture path does."""

    from brief_crew.observability.langfuse_exporter import _Item

    exporter._absorb(_Item(run_id=run_id, frames=tuple(frames)))
    exporter._settle(force=True)


def by_role(observations: Iterable[RecordedObservation], role: str) -> list[RecordedObservation]:
    return [o for o in observations if o.metadata.get("observation_role") == role]


def child_of(
    observations: Iterable[RecordedObservation], parent: RecordedObservation
) -> list[RecordedObservation]:
    return [o for o in observations if o.parent is parent]
