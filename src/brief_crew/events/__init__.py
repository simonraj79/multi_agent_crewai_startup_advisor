"""Public event-capture surface for the HTTP/WebSocket service."""

from brief_crew.events.adapter import StreamSinkAdapter
from brief_crew.events.buffer import (
    DEFAULT_RING_CAPACITY,
    MAX_REPLAY_LIMIT,
    FrameBuffer,
    FrameBufferStats,
)
from brief_crew.events.context import CaptureContext, capture_events, current_capture, ui_run_id
from brief_crew.events.listener import UIEventListener
from brief_crew.events.models import (
    FRAME_VERSION,
    FrameData,
    FrameDraft,
    FrameKind,
    FrameLevel,
    UIEventType,
)
from brief_crew.events.registry import NodeRegistry, QUARANTINE_NODE_ID, WORKFLOW_NODE_ID
from brief_crew.events.serializer import FieldBoundedSerializer, SerializerLimits


__all__ = [
    "CaptureContext",
    "DEFAULT_RING_CAPACITY",
    "FRAME_VERSION",
    "FieldBoundedSerializer",
    "FrameBuffer",
    "FrameBufferStats",
    "FrameData",
    "FrameDraft",
    "FrameKind",
    "FrameLevel",
    "MAX_REPLAY_LIMIT",
    "NodeRegistry",
    "QUARANTINE_NODE_ID",
    "SerializerLimits",
    "StreamSinkAdapter",
    "UIEventListener",
    "UIEventType",
    "WORKFLOW_NODE_ID",
    "capture_events",
    "current_capture",
    "ui_run_id",
]
