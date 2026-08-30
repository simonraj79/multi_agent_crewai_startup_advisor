"""Field-by-field CrewAI event serialization with hard payload bounds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel

from crewai.events import (
    AgentExecutionCompletedEvent,
    AgentExecutionErrorEvent,
    AgentExecutionStartedEvent,
    CrewKickoffCompletedEvent,
    CrewKickoffFailedEvent,
    CrewKickoffStartedEvent,
    FlowFailedEvent,
    FlowFinishedEvent,
    FlowStartedEvent,
    HumanFeedbackReceivedEvent,
    HumanFeedbackRequestedEvent,
    LLMCallCompletedEvent,
    LLMCallFailedEvent,
    LLMCallStartedEvent,
    LLMStreamChunkEvent,
    MethodExecutionFailedEvent,
    MethodExecutionFinishedEvent,
    MethodExecutionStartedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskStartedEvent,
    ToolUsageErrorEvent,
    ToolUsageFinishedEvent,
    ToolUsageStartedEvent,
)

from brief_crew.events.models import (
    FrameDraft,
    FrameKind,
    FrameLevel,
    UIEventType,
)
from brief_crew.events.registry import NodeRegistry
from brief_crew.config import compute_cost_usd


_USAGE_ALIASES = {
    "successful_requests": (
        "successful_requests",
        "successful_request_count",
    ),
    "prompt_tokens": (
        "prompt_tokens",
        "prompt_token_count",
        "input_tokens",
        "input_token_count",
    ),
    "completion_tokens": (
        "completion_tokens",
        "completion_token_count",
        "output_tokens",
        "output_token_count",
    ),
    "total_tokens": ("total_tokens", "total_token_count"),
    "call_count": ("call_count", "request_count"),
}


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        return dumped if isinstance(dumped, Mapping) else None
    return None


def _usage_value(
    value: Any,
    aliases: tuple[str, ...],
    *,
    depth: int = 0,
) -> int | None:
    mapping = _as_mapping(value)
    if mapping is None or depth > 4:
        return None
    normalized = {
        str(key).strip().casefold().replace("-", "_"): item
        for key, item in mapping.items()
    }
    for alias in aliases:
        candidate = normalized.get(alias)
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return max(0, candidate)
        if isinstance(candidate, float) and candidate.is_integer():
            return max(0, int(candidate))
        if isinstance(candidate, str) and candidate.strip().isdigit():
            return int(candidate.strip())
    for item in mapping.values():
        if _as_mapping(item) is None:
            continue
        nested = _usage_value(item, aliases, depth=depth + 1)
        if nested is not None:
            return nested
    return None


def normalize_usage(
    value: Any,
    *,
    completed_call: bool = False,
) -> dict[str, int]:
    """Normalize provider and CrewAI token aliases without double-counting details."""

    normalized = {
        field: _usage_value(value, aliases)
        for field, aliases in _USAGE_ALIASES.items()
    }
    prompt_tokens = normalized["prompt_tokens"] or 0
    completion_tokens = normalized["completion_tokens"] or 0
    total_tokens = normalized["total_tokens"]
    return {
        "successful_requests": normalized["successful_requests"]
        if normalized["successful_requests"] is not None
        else int(completed_call),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": (
            total_tokens
            if total_tokens is not None
            else prompt_tokens + completion_tokens
        ),
        "call_count": normalized["call_count"]
        if normalized["call_count"] is not None
        else int(completed_call),
    }


@dataclass(frozen=True, slots=True)
class SerializerLimits:
    max_string: int = 4096
    max_key: int = 128
    max_items: int = 64
    max_depth: int = 4
    max_repr: int = 512


class FieldBoundedSerializer:
    """Convert supported events without traversing live CrewAI objects."""

    def __init__(self, limits: SerializerLimits | None = None) -> None:
        self.limits = limits or SerializerLimits()

    def clip(self, value: Any, *, depth: int = 0) -> Any:
        if value is None or isinstance(value, bool | int | float):
            return value
        if isinstance(value, str):
            return value[: self.limits.max_string]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return self.clip(value.value, depth=depth)
        if depth >= self.limits.max_depth:
            return self._safe_repr(value)
        if isinstance(value, BaseModel):
            return self.clip(value.model_dump(mode="python"), depth=depth + 1)
        if isinstance(value, Mapping):
            clipped: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= self.limits.max_items:
                    clipped["__truncated__"] = True
                    break
                clipped[str(key)[: self.limits.max_key]] = self.clip(
                    item, depth=depth + 1
                )
            return clipped
        if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
            clipped_items = [
                self.clip(item, depth=depth + 1)
                for item in value[: self.limits.max_items]
            ]
            if len(value) > self.limits.max_items:
                clipped_items.append("<truncated>")
            return clipped_items
        if isinstance(value, bytes | bytearray):
            return f"<{len(value)} bytes>"
        return self._safe_repr(value)

    def drafts(self, source: Any, event: Any, registry: NodeRegistry) -> tuple[FrameDraft, ...]:
        del source
        timestamp = getattr(event, "timestamp", None)
        if not isinstance(timestamp, datetime):
            timestamp = datetime.now(timezone.utc)
        node_id = registry.resolve_event(event)

        # A RUN_STATE frame is the transport's statement about the run's status,
        # and the Studio client reads `details.status` to move out of its
        # pre-run state. Both drafts below carry it explicitly: without it a
        # real run streamed to a finished graph while the header still said
        # "queued". The cancellation frames in `service/registry.py` set the
        # same key, so every RUN_STATE frame the service emits is self-describing.
        if isinstance(event, FlowStartedEvent):
            return (self._draft(timestamp, FrameKind.RUN_STATE, UIEventType.WORKFLOW_START, registry.workflow_node_id, f"{event.flow_name} started", {"status": "running", "inputs": self.clip(event.inputs)}),)
        if isinstance(event, FlowFinishedEvent):
            return (self._draft(timestamp, FrameKind.RUN_STATE, UIEventType.WORKFLOW_END, registry.workflow_node_id, f"{event.flow_name} completed", {"status": "completed", "result": self.clip(event.result)}),)
        if isinstance(event, FlowFailedEvent):
            return (self._draft(timestamp, FrameKind.ERROR, UIEventType.WORKFLOW_END, registry.workflow_node_id, f"{event.flow_name} failed", {"error": self.clip(str(event.error))}, FrameLevel.ERROR),)

        if isinstance(event, MethodExecutionStartedEvent):
            return (self._draft(timestamp, FrameKind.NODE_STATE, UIEventType.NODE_START, node_id, f"{event.method_name} started", {"stage": "before", "params": self.clip(event.params)}),)
        if isinstance(event, MethodExecutionFinishedEvent):
            frames = [self._draft(timestamp, FrameKind.NODE_STATE, UIEventType.NODE_END, node_id, f"{event.method_name} completed", {"stage": "after", "result": self.clip(event.result)})]
            if registry.is_router(event.method_name) and event.result is not None:
                route = str(event.result)
                frames.append(self._draft(timestamp, FrameKind.EDGE_TAKEN, UIEventType.EDGE_PROCESS, node_id, f"{event.method_name} routed to {route}", {"from": node_id, "to": registry.resolve_route(event.method_name, route), "route": self.clip(route)}))
            return tuple(frames)
        if isinstance(event, MethodExecutionFailedEvent):
            return (self._draft(timestamp, FrameKind.NODE_STATE, UIEventType.NODE_END, node_id, f"{event.method_name} failed", {"stage": "error", "error": self.clip(str(event.error))}, FrameLevel.ERROR),)

        if isinstance(event, HumanFeedbackRequestedEvent):
            return (self._draft(timestamp, FrameKind.GATE_OPEN, UIEventType.HUMAN_INTERACTION, node_id, event.message, {"stage": "before", "gate_id": event.request_id, "options": self.clip(event.emit), "output": self.clip(event.output)}),)
        if isinstance(event, HumanFeedbackReceivedEvent):
            return (self._draft(timestamp, FrameKind.GATE_CLOSED, UIEventType.HUMAN_INTERACTION, node_id, f"Feedback received for {event.method_name}", {"stage": "after", "gate_id": event.request_id, "feedback": self.clip(event.feedback), "outcome": self.clip(event.outcome)}),)

        if isinstance(event, ToolUsageStartedEvent):
            return (self._draft(timestamp, FrameKind.TOOL, UIEventType.TOOL_CALL, node_id, f"{event.tool_name} started", {"stage": "before", "tool": event.tool_name, "args": self.clip(event.tool_args)}),)
        if isinstance(event, ToolUsageFinishedEvent):
            duration_ms = max(0, int((event.finished_at - event.started_at).total_seconds() * 1000))
            level = FrameLevel.WARNING if event.failure is not None else FrameLevel.INFO
            return (self._draft(timestamp, FrameKind.TOOL, UIEventType.TOOL_CALL, node_id, f"{event.tool_name} completed", {"stage": "after", "tool": event.tool_name, "output": self.clip(event.output), "from_cache": event.from_cache, "failure": self.clip(event.failure)}, level, duration_ms),)
        if isinstance(event, ToolUsageErrorEvent):
            return (self._draft(timestamp, FrameKind.TOOL, UIEventType.TOOL_CALL, node_id, f"{event.tool_name} failed", {"stage": "error", "tool": event.tool_name, "error": self.clip(event.error)}, FrameLevel.ERROR),)

        if isinstance(event, LLMCallStartedEvent):
            return (self._draft(timestamp, FrameKind.LLM, UIEventType.MODEL_CALL, node_id, f"{event.model or 'model'} call started", {"stage": "before", "call_id": event.call_id, "model": event.model}),)
        if isinstance(event, LLMCallCompletedEvent):
            model = str(event.model or "unknown")
            usage = normalize_usage(event.usage or {}, completed_call=True)
            cost_usd = compute_cost_usd(
                model,
                usage["prompt_tokens"],
                usage["completion_tokens"],
            )
            return (
                self._draft(timestamp, FrameKind.LLM, UIEventType.MODEL_CALL, node_id, f"{event.model or 'model'} call completed", {"stage": "after", "call_id": event.call_id, "model": event.model, "finish_reason": event.finish_reason, "response_id": event.response_id}),
                self._draft(timestamp, FrameKind.TOKEN, UIEventType.MODEL_CALL, node_id, "Token usage recorded", {"call_id": event.call_id, "model": model, "usage": usage, "cost_usd": cost_usd}),
            )
        if isinstance(event, LLMCallFailedEvent):
            return (self._draft(timestamp, FrameKind.LLM, UIEventType.MODEL_CALL, node_id, f"{event.model or 'model'} call failed", {"stage": "error", "call_id": event.call_id, "model": event.model, "error": self.clip(event.error)}, FrameLevel.ERROR),)
        if isinstance(event, LLMStreamChunkEvent):
            return (self._draft(timestamp, FrameKind.LLM, UIEventType.MODEL_CALL, node_id, "Model stream chunk", {"stage": "chunk", "call_id": event.call_id, "chunk": self.clip(event.chunk)}),)

        if isinstance(event, AgentExecutionStartedEvent):
            return (self._draft(timestamp, FrameKind.AGENT, UIEventType.AGENT_CALL, node_id, f"{self._agent_role(event)} started", {"stage": "before", "task": self._task_name(event)}),)
        if isinstance(event, AgentExecutionCompletedEvent):
            return (self._draft(timestamp, FrameKind.AGENT, UIEventType.AGENT_CALL, node_id, f"{self._agent_role(event)} completed", {"stage": "after", "task": self._task_name(event), "output": self.clip(event.output)}),)
        if isinstance(event, AgentExecutionErrorEvent):
            return (self._draft(timestamp, FrameKind.AGENT, UIEventType.AGENT_CALL, node_id, f"{self._agent_role(event)} failed", {"stage": "error", "task": self._task_name(event), "error": self.clip(event.error)}, FrameLevel.ERROR),)

        if isinstance(event, TaskStartedEvent):
            return (self._draft(timestamp, FrameKind.AGENT, UIEventType.AGENT_CALL, node_id, f"{self._task_name(event)} started", {"stage": "before"}),)
        if isinstance(event, TaskCompletedEvent):
            return (self._draft(timestamp, FrameKind.AGENT, UIEventType.AGENT_CALL, node_id, f"{self._task_name(event)} completed", {"stage": "after"}),)
        if isinstance(event, TaskFailedEvent):
            return (self._draft(timestamp, FrameKind.AGENT, UIEventType.AGENT_CALL, node_id, f"{self._task_name(event)} failed", {"stage": "error", "error": self.clip(event.error)}, FrameLevel.ERROR),)

        if isinstance(event, CrewKickoffStartedEvent):
            return (self._draft(timestamp, FrameKind.AGENT, UIEventType.AGENT_CALL, node_id, f"{event.crew_name or 'Crew'} started", {"stage": "before"}),)
        if isinstance(event, CrewKickoffCompletedEvent):
            return (self._draft(timestamp, FrameKind.AGENT, UIEventType.AGENT_CALL, node_id, f"{event.crew_name or 'Crew'} completed", {"stage": "after", "total_tokens": event.total_tokens}),)
        if isinstance(event, CrewKickoffFailedEvent):
            return (self._draft(timestamp, FrameKind.AGENT, UIEventType.AGENT_CALL, node_id, f"{event.crew_name or 'Crew'} failed", {"stage": "error", "error": self.clip(event.error)}, FrameLevel.ERROR),)
        return ()

    def _draft(
        self,
        timestamp: datetime,
        kind: FrameKind,
        event_type: UIEventType,
        node_id: str,
        message: str,
        details: Mapping[str, Any],
        level: FrameLevel = FrameLevel.INFO,
        duration_ms: int | None = None,
    ) -> FrameDraft:
        return FrameDraft(
            ts=timestamp,
            kind=kind,
            event_type=event_type,
            level=level,
            node_id=str(node_id)[:128] or "unattributed",
            message=str(message)[: self.limits.max_string],
            details=self.clip(details),
            duration_ms=duration_ms,
        )

    def _safe_repr(self, value: Any) -> str:
        try:
            rendered = repr(value)
        except Exception:
            rendered = f"<{type(value).__name__}>"
        return rendered[: self.limits.max_repr]

    @staticmethod
    def _agent_role(event: Any) -> str:
        return str(getattr(getattr(event, "agent", None), "role", "Agent")).strip()

    @staticmethod
    def _task_name(event: Any) -> str:
        task = getattr(event, "task", None)
        return str(getattr(task, "name", None) or getattr(event, "task_name", None) or "Task")
