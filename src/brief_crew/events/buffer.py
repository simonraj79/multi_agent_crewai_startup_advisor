"""Thread-safe, bounded per-run frame storage."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import RLock
from typing import Iterable

from brief_crew.events.models import FrameData, FrameDraft, FrameKind
from brief_crew.events.registry import QUARANTINE_NODE_ID


DEFAULT_RING_CAPACITY = 2000
MAX_REPLAY_LIMIT = 500


@dataclass(frozen=True, slots=True)
class FrameBufferStats:
    count: int
    captured: int
    dropped: int
    gaps: int
    emit_errors: int
    # PRD F21: frames CrewAI could not attribute to a declared node and that
    # landed on the visible quarantine node. Counted at push time, so ring
    # eviction never lowers it and a restored run recomputes the same total
    # from its replayed frames.
    unattributed: int
    first_seq: int | None
    last_seq: int | None


class FrameBuffer:
    """A ring that assigns one total order to all frames in a run."""

    def __init__(
        self,
        capacity: int = DEFAULT_RING_CAPACITY,
        *,
        quarantine_node_id: str = QUARANTINE_NODE_ID,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.quarantine_node_id = quarantine_node_id
        self._frames: deque[FrameData] = deque(maxlen=capacity)
        self._next_seq = 1
        self._captured = 0
        self._dropped = 0
        self._gaps = 0
        self._emit_errors = 0
        self._unattributed = 0
        self._lock = RLock()

    def push(self, run_id: str, draft: FrameDraft) -> FrameData:
        return self.push_many(run_id, (draft,))[0]

    def push_many(
        self, run_id: str, drafts: Iterable[FrameDraft]
    ) -> tuple[FrameData, ...]:
        appended: list[FrameData] = []
        with self._lock:
            for draft in drafts:
                frame = FrameData.from_draft(
                    seq=self._next_seq,
                    run_id=run_id,
                    draft=draft,
                )
                self._next_seq += 1
                self._captured += 1
                if frame.node_id == self.quarantine_node_id:
                    self._unattributed += 1
                if len(self._frames) == self.capacity:
                    self._dropped += 1
                    self._gaps += 1
                self._frames.append(frame)
                appended.append(frame)
        return tuple(appended)

    def note_gap(self, count: int = 1) -> None:
        if count < 0:
            raise ValueError("gap count cannot be negative")
        with self._lock:
            self._gaps += count

    def note_emit_error(self) -> None:
        with self._lock:
            self._emit_errors += 1

    def replay(
        self,
        *,
        after: int = 0,
        limit: int = MAX_REPLAY_LIMIT,
        kinds: set[FrameKind] | None = None,
    ) -> tuple[FrameData, ...]:
        if after < 0:
            raise ValueError("after cannot be negative")
        if not 1 <= limit <= MAX_REPLAY_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_REPLAY_LIMIT}")
        with self._lock:
            return tuple(
                frame
                for frame in self._frames
                if frame.seq > after and (kinds is None or frame.kind in kinds)
            )[:limit]

    def stats(self) -> FrameBufferStats:
        with self._lock:
            return FrameBufferStats(
                count=len(self._frames),
                captured=self._captured,
                dropped=self._dropped,
                gaps=self._gaps,
                emit_errors=self._emit_errors,
                unattributed=self._unattributed,
                first_seq=self._frames[0].seq if self._frames else None,
                last_seq=self._frames[-1].seq if self._frames else None,
            )
