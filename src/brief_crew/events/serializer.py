"""Field-by-field CrewAI event serialization with hard payload bounds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
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


#: The head of the JSON envelope every tool in `brief_crew.tools` returns,
#: mapped to the frame detail key that carries it. `results` is deliberately
#: absent: it is the whole payload - scraped page bodies, comment trees - and a
#: 2,000-frame ring cannot hold 2,000 of them. Its length is kept instead.
#:
#: `status` is renamed. `details["status"]` already means "the run's own status"
#: to `useValidatorRun.applyRunState`, and a tool reporting `"rate_limited"` is
#: a different sentence in the same grammar; a reader that ever stops checking
#: the frame kind first would conflate them.
_TOOL_ENVELOPE_FIELDS = {
    "status": "tool_status",
    "query": "query",
    "result_count": "result_count",
    "notes": "notes",
    "retrieved_at": "retrieved_at",
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


@dataclass(slots=True)
class FlowScope:
    """Which flow a run-lifecycle frame is allowed to speak for.

    CrewAI fires `FlowStartedEvent` and `FlowFinishedEvent` for *every* Flow it
    runs, and its own `AgentExecutor` is a Flow. So a real paid run emitted
    `WORKFLOW_END` carrying `status: "completed"` on the `workflow` node the
    moment the **first agent** finished, ten frames into a run that had barely
    started. The Studio client believed it: it flipped the console to Completed,
    stopped every edge animation and - the damage that does not undo itself -
    dropped the localStorage pointer refresh recovery reads, for a run that was
    still in flight.

    The run's own flow is identified by *name*, claimed by the first
    `FlowStartedEvent` this run sees. Deliberately not a list of CrewAI's inner
    flow classes: a denylist against an upstream library rots the first time it
    renames one, and it cannot see a nested flow this repo has not met yet.

    Claiming a name, rather than latching "the first start wins, once", is what
    keeps resume working. `Flow.resume()` emits a second `FlowStartedEvent` for
    the same root flow (crewai/flow/runtime/__init__.py: "Emitted
    unconditionally ... a resumed flow reported finishing without ever having
    started"), and the run must still be able to finish after it. A run that is
    recovered into a fresh adapter re-claims the same name from that start.

    Mutated only from `StreamSinkAdapter.__call__`, which holds the capture
    lock, so the three concurrent research branches cannot race here.
    """

    root_flow_name: str | None = None

    def is_root(self, flow_name: str | None, *, claim: bool) -> bool:
        """Report whether `flow_name` is the run's own top-level flow.

        `claim` is true only for a start event. A finish or a failure arriving
        with no start behind it is still treated as the run's own - there is no
        other lifecycle statement coming, and a run that can never report
        finishing is the worse failure - but it does not get to define the root.
        """

        name = (flow_name or "").strip()
        if self.root_flow_name is None:
            if claim:
                self.root_flow_name = name
            return True
        return name == self.root_flow_name


@dataclass(frozen=True, slots=True)
class SerializerLimits:
    max_string: int = 4096
    max_key: int = 128
    max_items: int = 64
    max_depth: int = 4
    max_repr: int = 512
    #: The largest tool output this serializer will hand to `json.loads`.
    #: A market envelope carrying ten scraped pages is comfortably inside it;
    #: anything larger is not parsed at all, so a pathological output can never
    #: turn a capture callback into real work on the run's own thread.
    max_tool_output: int = 1_048_576
    #: The bound on each individual field lifted out of a tool envelope. These
    #: are queries, one-word statuses and a sentence of notes; the general
    #: `max_string` of 4096 would let four of them outweigh the frame they are
    #: meant to annotate.
    max_tool_field: int = 512


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

    def drafts(
        self,
        source: Any,
        event: Any,
        registry: NodeRegistry,
        *,
        flow_scope: FlowScope | None = None,
    ) -> tuple[FrameDraft, ...]:
        del source
        timestamp = getattr(event, "timestamp", None)
        if not isinstance(timestamp, datetime):
            timestamp = datetime.now(timezone.utc)
        node_id = registry.resolve_event(event)
        # A caller with no per-run scope gets one in which this event is the
        # run's own, which is all a single isolated conversion can mean.
        # `StreamSinkAdapter` always passes the run's, so the live path is the
        # stateful one.
        scope = flow_scope if flow_scope is not None else FlowScope()

        # A RUN_STATE frame is the transport's statement about the run's status,
        # and the Studio client reads `details.status` to move out of its
        # pre-run state. The drafts below say so explicitly: without it a real
        # run streamed to a finished graph while the header still said "queued".
        # The cancellation frames in `service/registry.py` set the same key, so
        # every RUN_STATE frame the service emits is self-describing.
        #
        # Each one is gated on `FlowScope`, because that statement is only the
        # transport's to make about the run's *own* flow. CrewAI fires these
        # same three events for the flows it runs inside the run - see the
        # `FlowScope` docstring for what believing them cost.
        if isinstance(event, FlowStartedEvent):
            if not scope.is_root(event.flow_name, claim=True):
                return (self._nested_flow_draft(timestamp, node_id, event.flow_name, "started", "before", {"inputs": self.clip(event.inputs)}),)
            return (self._draft(timestamp, FrameKind.RUN_STATE, UIEventType.WORKFLOW_START, registry.workflow_node_id, f"{event.flow_name} started", {"status": "running", "inputs": self.clip(event.inputs)}),)
        if isinstance(event, FlowFinishedEvent):
            if not scope.is_root(event.flow_name, claim=False):
                return (self._nested_flow_draft(timestamp, node_id, event.flow_name, "completed", "after", {"result": self.clip(event.result)}),)
            return (self._draft(timestamp, FrameKind.RUN_STATE, UIEventType.WORKFLOW_END, registry.workflow_node_id, f"{event.flow_name} completed", {"status": "completed", "result": self.clip(event.result)}),)
        if isinstance(event, FlowFailedEvent):
            # A nested failure is not the run failing either. `FrameKind.ERROR`
            # is read by the client as exactly that, and `error` is terminal, so
            # an inner flow that raised would destroy the stored run pointer the
            # same way a false completion does.
            if not scope.is_root(event.flow_name, claim=False):
                return (self._nested_flow_draft(timestamp, node_id, event.flow_name, "failed", "error", {"error": self.clip(str(event.error))}, FrameLevel.ERROR),)
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
            return (self._draft(timestamp, FrameKind.TOOL, UIEventType.TOOL_CALL, node_id, f"{event.tool_name} started", {"stage": "before", "tool": event.tool_name, "query": self.tool_query(event.tool_args), "args": self.clip(event.tool_args)}),)
        if isinstance(event, ToolUsageFinishedEvent):
            duration_ms = max(0, int((event.finished_at - event.started_at).total_seconds() * 1000))
            level = FrameLevel.WARNING if event.failure is not None else FrameLevel.INFO
            envelope = self.tool_envelope(event.output)
            # The query the *tool* reports is the one it actually ran, so it
            # wins over the arguments it was handed.
            query = envelope.pop("query", None) or self.tool_query(event.tool_args)
            details = {"stage": "after", "tool": event.tool_name, "query": query, "from_cache": event.from_cache, "failure": self.clip(event.failure)}
            details.update(envelope)
            return (self._draft(timestamp, FrameKind.TOOL, UIEventType.TOOL_CALL, node_id, f"{event.tool_name} completed", details, level, duration_ms),)
        if isinstance(event, ToolUsageErrorEvent):
            return (self._draft(timestamp, FrameKind.TOOL, UIEventType.TOOL_CALL, node_id, f"{event.tool_name} failed", {"stage": "error", "tool": event.tool_name, "query": self.tool_query(event.tool_args), "error": self.clip(event.error)}, FrameLevel.ERROR),)

        if isinstance(event, LLMCallStartedEvent):
            return (self._draft(timestamp, FrameKind.LLM, UIEventType.MODEL_CALL, node_id, f"{event.model or 'model'} call started", {"stage": "before", "call_id": event.call_id, "model": event.model}),)
        if isinstance(event, LLMCallCompletedEvent):
            model = str(event.model or "unknown")
            usage: dict[str, int | float | None] = dict(
                normalize_usage(event.usage or {}, completed_call=True)
            )
            cost_usd = compute_cost_usd(
                model,
                int(usage["prompt_tokens"] or 0),
                int(usage["completion_tokens"] or 0),
            )
            # Carried in BOTH places on purpose. `details["cost_usd"]` is where
            # `RunRegistry._record_usage` and the log export read it; the copy
            # inside `usage` is where the Studio client reads it, because
            # `usageFromDetails` narrows to `details.usage` the moment that key
            # is an object and then never looks at the level above. Cost sat
            # beside `usage` rather than inside it, so a client that had every
            # token frame still totalled $0.0000. `normalize_usage` whitelists
            # five token aliases and ignores this key, so no path double-counts
            # it.
            #
            # `None` means the model is not in the price table. It is NOT 0.0:
            # see `config.compute_cost_usd`.
            usage["cost_usd"] = cost_usd
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

    def tool_query(self, tool_args: Any) -> str | None:
        """The search string a tool call was asked to run, if it names one.

        Every tool in `brief_crew.tools` takes a `query`, and the first paid run
        failed on exactly that value: the Scoper wrote prose where a keyword API
        wanted keywords, and the trace could not show it because the query never
        reached a frame. Read from the arguments rather than from any table of
        tool names, so a tool that does not take a query simply reports none.
        """

        try:
            query = self._loads(tool_args, "query")
        except Exception:
            return None
        return query[: self.limits.max_tool_field] if isinstance(query, str) else None

    def tool_envelope(self, output: Any) -> dict[str, Any]:
        """The diagnostic head of a tool's JSON envelope - never its `results`.

        `status`, `query`, `result_count` and `notes` are the four fields that
        would have made the first paid run's D=1 and F=1 scores diagnosable from
        the trace instead of by re-running the tools by hand. `results` is the
        one field that must not be here: a single market envelope carries ten
        scraped page bodies, and the run ring holds two thousand frames.

        Anything that is not one of those envelopes - a plain string, a tool
        that failed and returned prose, a JSON document with none of these keys
        - falls back to the clipped raw output this frame carried before. This
        runs inside a capture callback, so it does not raise: an output that
        cannot be read is a worse frame, never a broken run.
        """

        try:
            payload = self._loads(output)
            if payload is None:
                return {"output": self.clip(output)}
            lifted: dict[str, Any] = {}
            for key, name in _TOOL_ENVELOPE_FIELDS.items():
                if key in payload:
                    lifted[name] = self._envelope_field(payload[key])
            if not lifted:
                return {"output": self.clip(output)}
            results = payload.get("results")
            if "result_count" not in lifted and isinstance(results, Sequence) and not isinstance(results, str | bytes | bytearray):
                lifted["result_count"] = len(results)
            if isinstance(output, str):
                # What was dropped, stated rather than implied.
                lifted["output_chars"] = len(output)
            return lifted
        except Exception:
            return {"output": self.clip(output)}

    def _loads(self, value: Any, key: str | None = None) -> Any:
        """Read a tool payload that may arrive as JSON text or as an object.

        Bounded before parsing: a string longer than `max_tool_output` is not
        handed to `json.loads` at all, so no tool return value can turn a
        capture callback into real work on the run's own thread.
        """

        payload = value
        if isinstance(payload, str):
            text = payload.strip()
            if not text.startswith("{") or len(payload) > self.limits.max_tool_output:
                return None
            try:
                payload = json.loads(text)
            except (ValueError, RecursionError):
                return None
        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="python")
        if not isinstance(payload, Mapping):
            return None
        return payload if key is None else payload.get(key)

    def _envelope_field(self, value: Any) -> Any:
        """One scalar out of a tool envelope, bounded hard and never nested."""

        if value is None or isinstance(value, bool | int | float):
            return value
        if isinstance(value, str):
            return value[: self.limits.max_tool_field]
        return self._safe_repr(value)[: self.limits.max_tool_field]

    def _nested_flow_draft(
        self,
        timestamp: datetime,
        node_id: str,
        flow_name: str,
        verb: str,
        stage: str,
        payload: Mapping[str, Any],
        level: FrameLevel = FrameLevel.INFO,
    ) -> FrameDraft:
        """A flow CrewAI ran *inside* the run, never a statement about the run.

        Dropping it would lose trace fidelity - an agent executor is often the
        only frame between a task starting and a tool call - so it is kept, as
        an agent frame. `FrameKind.AGENT` moves no run status and no node state
        anywhere in the client, and neither `WORKFLOW_START` nor `WORKFLOW_END`
        appears on it, so the `event_type` fallback in `applyRunState` cannot
        fire on it either. `nested` is the marker the client refuses lifecycle
        frames on, belt to that braces.

        It is attributed to the node that was executing when the inner flow
        started rather than to the `workflow` node, because that is where it
        actually happened; an inner flow with no enclosing method resolves to
        the visible `unattributed` quarantine node like anything else.
        """

        return self._draft(
            timestamp,
            FrameKind.AGENT,
            UIEventType.AGENT_CALL,
            node_id,
            f"{flow_name} {verb}",
            {"stage": stage, "flow": flow_name, "nested": True, **payload},
            level,
        )

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
