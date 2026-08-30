"""Ordered, non-blocking capture adapter for CrewAI stream sinks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from crewai.events import MethodExecutionStartedEvent

from brief_crew.events.buffer import FrameBuffer
from brief_crew.events.models import (
    FrameData,
    FrameDraft,
    FrameKind,
    FrameLevel,
    UIEventType,
)
from brief_crew.events.registry import NodeRegistry, enter_node_scope
from brief_crew.events.serializer import FieldBoundedSerializer, FlowScope


FrameCallback = Callable[[tuple[FrameData, ...]], None]


class StreamSinkAdapter:
    """Serialize and append inline; callbacks may only schedule later work."""

    def __init__(
        self,
        *,
        run_id: str,
        buffer: FrameBuffer,
        registry: NodeRegistry,
        serializer: FieldBoundedSerializer | None = None,
        on_frames: FrameCallback | None = None,
    ) -> None:
        self.run_id = run_id
        self.buffer = buffer
        self.registry = registry
        self.serializer = serializer or FieldBoundedSerializer()
        self.on_frames = on_frames
        # Per-run, because "which flow is this run's own flow" is a fact about
        # the run and nothing else. The serializer stays stateless and is free
        # to be shared; this object is not, and is read and written only under
        # the capture lock below.
        self.flow_scope = FlowScope()
        self._capture_lock = Lock()

    def __call__(self, source: Any, event: Any) -> None:
        try:
            with self._capture_lock:
                self._track_node_scope(event)
                drafts = self.serializer.drafts(
                    source, event, self.registry, flow_scope=self.flow_scope
                )
                frames = self.buffer.push_many(self.run_id, drafts)
                self._notify(frames)
        except Exception:
            self.buffer.note_emit_error()

    def _track_node_scope(self, event: Any) -> None:
        """Name the declared node this execution context is now running inside.

        Done here rather than in the serializer because it is a fact about the
        context the sink was called in, and the sink is called synchronously
        from `crewai_event_bus._prepare_event` - inside the very coroutine that
        is about to `copy_context()` the flow method into a worker thread. Every
        tool, model and agent event raised underneath that method inherits the
        copy and can be joined back to this node. See `registry.current_node_scope`.

        Only a *declared* method start writes, so CrewAI's nested AgentExecutor
        flow cannot claim the scope on its way past. Nothing here can fail in a
        way that matters: a write to a `ContextVar` does no I/O, and the caller
        turns any exception into a counted emit error rather than a broken run.

        The `UIEventListener` fallback path in `listener.py` calls the adapter
        from an async event-bus handler, whose context is not the flow method's.
        Attribution there degrades to the quarantine node exactly as it does
        today; that listener is documented as an opt-in safety net, and CrewAI's
        own `current_flow_method_name` is equally unreadable from it.
        """

        if not isinstance(event, MethodExecutionStartedEvent):
            return
        node_id = self.registry.declared_node(getattr(event, "method_name", None))
        if node_id is not None:
            enter_node_scope(node_id)

    def emit(
        self,
        *,
        kind: FrameKind,
        event_type: UIEventType,
        node_id: str,
        message: str,
        details: Mapping[str, Any] | None = None,
        level: FrameLevel = FrameLevel.INFO,
        duration_ms: int | None = None,
    ) -> FrameData | None:
        try:
            draft = FrameDraft(
                ts=datetime.now(timezone.utc),
                kind=kind,
                event_type=event_type,
                level=level,
                node_id=node_id[:128] or self.registry.quarantine_node_id,
                message=message[: self.serializer.limits.max_string],
                details=self.serializer.clip(details or {}),
                duration_ms=duration_ms,
            )
            with self._capture_lock:
                frame = self.buffer.push(self.run_id, draft)
                self._notify((frame,))
            return frame
        except Exception:
            self.buffer.note_emit_error()
            return None

    def _notify(self, frames: tuple[FrameData, ...]) -> None:
        if not frames or self.on_frames is None:
            return
        try:
            self.on_frames(frames)
        except Exception:
            self.buffer.note_emit_error()
