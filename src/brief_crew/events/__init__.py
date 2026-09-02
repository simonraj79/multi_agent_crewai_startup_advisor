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
from brief_crew.events.registry import (
    NodeRegistry,
    QUARANTINE_NODE_ID,
    ROUTING_NODE_KINDS,
    WORKFLOW_NODE_ID,
)
from brief_crew.events.serializer import FieldBoundedSerializer, SerializerLimits
from brief_crew.events.verdict import (
    VERDICT_NODE_ID,
    VerdictComputedEvent,
    publish_verdict,
    verdict_frame_node,
)


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
    "ROUTING_NODE_KINDS",
    "SerializerLimits",
    "StreamSinkAdapter",
    "UIEventListener",
    "UIEventType",
    "VERDICT_NODE_ID",
    "VerdictComputedEvent",
    "WORKFLOW_NODE_ID",
    "capture_events",
    "current_capture",
    "publish_verdict",
    "ui_run_id",
    "verdict_frame_node",
]
