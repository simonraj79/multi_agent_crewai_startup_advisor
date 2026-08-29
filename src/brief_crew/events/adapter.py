"""Ordered, non-blocking capture adapter for CrewAI stream sinks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from brief_crew.events.buffer import FrameBuffer
from brief_crew.events.models import (
    FrameData,
    FrameDraft,
    FrameKind,
    FrameLevel,
    UIEventType,
)
from brief_crew.events.registry import NodeRegistry
from brief_crew.events.serializer import FieldBoundedSerializer


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
        self._capture_lock = Lock()

    def __call__(self, source: Any, event: Any) -> None:
        try:
            with self._capture_lock:
                drafts = self.serializer.drafts(source, event, self.registry)
                frames = self.buffer.push_many(self.run_id, drafts)
                self._notify(frames)
        except Exception:
            self.buffer.note_emit_error()

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
