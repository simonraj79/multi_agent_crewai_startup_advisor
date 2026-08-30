"""Immutable, versioned frames exposed by the service transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Mapping


FRAME_VERSION = 1
MAX_MESSAGE_LENGTH = 4096
MAX_IDENTIFIER_LENGTH = 128
MAX_DETAIL_DEPTH = 4
MAX_DETAIL_ITEMS = 64


class FrameKind(str, Enum):
    RUN_STATE = "run_state"
    NODE_STATE = "node_state"
    EDGE_TAKEN = "edge_taken"
    AGENT = "agent"
    TOOL = "tool"
    LLM = "llm"
    TOKEN = "token"
    GATE_OPEN = "gate_open"
    GATE_CLOSED = "gate_closed"
    # PRD F03: an unanswered gate whose deadline has passed. Advisory only -
    # the run stays WAITING and a late reply still resumes it.
    GATE_EXPIRED = "gate_expired"
    # PRD R-2: a gate_open with no gate_closed after timeout + grace.
    GATE_ALERT = "gate_alert"
    METRICS = "metrics"
    # The deterministic score, the moment `Verdict.compute_mechanical_result`
    # has produced it. Its own kind rather than a `node_state` detail because
    # it is the run's product, not a lifecycle transition: it must survive
    # `gates: "auto"` (where no verdict gate opens to carry it) and it is what
    # `RunRecord` mirrors into `GET /api/runs/{run_id}`.
    VERDICT = "verdict"
    ERROR = "error"


class UIEventType(str, Enum):
    NODE_START = "NODE_START"
    NODE_END = "NODE_END"
    EDGE_PROCESS = "EDGE_PROCESS"
    MODEL_CALL = "MODEL_CALL"
    TOOL_CALL = "TOOL_CALL"
    AGENT_CALL = "AGENT_CALL"
    HUMAN_INTERACTION = "HUMAN_INTERACTION"
    THINKING_PROCESS = "THINKING_PROCESS"
    MEMORY_OPERATION = "MEMORY_OPERATION"
    WORKFLOW_START = "WORKFLOW_START"
    WORKFLOW_END = "WORKFLOW_END"
    # PRD F20: the event type carried by a FrameKind.METRICS snapshot. The
    # Studio client already keys metrics handling off the frame kind, so this
    # only has to name the frame honestly in logs and exports.
    METRICS_UPDATED = "METRICS_UPDATED"
    # The event type carried by a FrameKind.VERDICT frame. The name contains
    # neither "START" nor "END": the client used to route lifecycle frames by
    # substring (`event_type.includes('END')`), and a member that tripped one of
    # those tests would have read as the run finishing the instant it was
    # scored. Those branches are gone, but the constraint on the vocabulary is
    # cheap and the failure it prevents is silent.
    VERDICT_COMPUTED = "VERDICT_COMPUTED"


class FrameLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _validate_detail(value: Any, *, depth: int = 0) -> None:
    if value is None or isinstance(value, bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("frame details cannot contain non-finite numbers")
        return
    if isinstance(value, str):
        if len(value) > MAX_MESSAGE_LENGTH:
            raise ValueError("frame detail string exceeds the bound")
        return
    if depth >= MAX_DETAIL_DEPTH:
        raise ValueError("frame details exceed the maximum depth")
    if isinstance(value, Mapping):
        if len(value) > MAX_DETAIL_ITEMS:
            raise ValueError("frame details contain too many fields")
        for key, item in value.items():
            if len(str(key)) > MAX_IDENTIFIER_LENGTH:
                raise ValueError("frame detail key exceeds the bound")
            _validate_detail(item, depth=depth + 1)
        return
    if isinstance(value, list | tuple):
        if len(value) > MAX_DETAIL_ITEMS:
            raise ValueError("frame detail sequence contains too many items")
        for item in value:
            _validate_detail(item, depth=depth + 1)
        return
    raise TypeError(f"unsupported frame detail type: {type(value).__name__}")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class FrameDraft:
    """A bounded frame before the run-local sequence number is assigned."""

    ts: datetime
    kind: FrameKind
    event_type: UIEventType
    level: FrameLevel
    node_id: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError("frame timestamps must be timezone-aware")
        if not self.node_id or len(self.node_id) > MAX_IDENTIFIER_LENGTH:
            raise ValueError("node_id must contain 1-128 characters")
        if len(self.message) > MAX_MESSAGE_LENGTH:
            raise ValueError("message exceeds the frame bound")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")
        _validate_detail(self.details)
        object.__setattr__(self, "details", _freeze(self.details))


@dataclass(frozen=True, slots=True)
class FrameData:
    """The immutable public frame contract from PRD section 9.2."""

    seq: int
    run_id: str
    ts: datetime
    kind: FrameKind
    event_type: UIEventType
    level: FrameLevel
    node_id: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None
    v: int = FRAME_VERSION

    def __post_init__(self) -> None:
        if self.v != FRAME_VERSION:
            raise ValueError(f"unsupported frame version: {self.v}")
        if self.seq < 1:
            raise ValueError("seq must be positive")
        if not self.run_id or len(self.run_id) > MAX_IDENTIFIER_LENGTH:
            raise ValueError("run_id must contain 1-128 characters")
        FrameDraft(
            ts=self.ts,
            kind=self.kind,
            event_type=self.event_type,
            level=self.level,
            node_id=self.node_id,
            message=self.message,
            details=self.details,
            duration_ms=self.duration_ms,
        )
        object.__setattr__(self, "details", _freeze(self.details))

    @classmethod
    def from_draft(cls, *, seq: int, run_id: str, draft: FrameDraft) -> FrameData:
        return cls(
            seq=seq,
            run_id=run_id,
            ts=draft.ts,
            kind=draft.kind,
            event_type=draft.event_type,
            level=draft.level,
            node_id=draft.node_id,
            message=draft.message,
            details=draft.details,
            duration_ms=draft.duration_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        timestamp = self.ts.isoformat(timespec="milliseconds")
        if timestamp.endswith("+00:00"):
            timestamp = f"{timestamp[:-6]}Z"
        data: dict[str, Any] = {
            "v": self.v,
            "seq": self.seq,
            "run_id": self.run_id,
            "ts": timestamp,
            "kind": self.kind.value,
            "event_type": self.event_type.value,
            "level": self.level.value,
            "node_id": self.node_id,
            "message": self.message,
            "details": _thaw(self.details),
        }
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        return data

    def envelope(self) -> dict[str, Any]:
        return {"type": "frame", "data": self.to_dict()}
