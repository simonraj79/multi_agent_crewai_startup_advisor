"""Ordered, non-blocking capture adapter for CrewAI stream sinks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any

from crewai.events import MethodExecutionStartedEvent

from brief_crew.config import STREAM_CHUNK_COALESCE_MS
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
        # --- 10 D6/D7 sequencing state, all of it PER RUN and all of it read
        # and written under `_capture_lock`. The serializer stays stateless and
        # shared between runs; none of this could live there.
        #: Text gathered for one `call_id` since its last emitted chunk frame.
        self._chunk_pending: dict[str, list[str]] = {}
        #: When that call last had a chunk frame emitted, on the monotonic clock.
        self._chunk_flushed: dict[str, float] = {}
        #: The last DECLARED node whose method finished - C6 `edge_traversal`'s
        #: `from`.
        self._last_finished: str | None = None

    def __call__(self, source: Any, event: Any) -> None:
        try:
            with self._capture_lock:
                self._track_node_scope(event)
                drafts = self.serializer.drafts(
                    source, event, self.registry, flow_scope=self.flow_scope
                )
                frames = self.buffer.push_many(self.run_id, self._sequenced(drafts))
                self._notify(frames)
        except Exception:
            self.buffer.note_emit_error()

    # ----------------------------------------------------------------------
    # Coalescing and edge traversal - .agent/plans/10-runtime.md D6 and D7
    # ----------------------------------------------------------------------
    def _sequenced(self, drafts: tuple[FrameDraft, ...]) -> tuple[FrameDraft, ...]:
        """The serializer's drafts, coalesced and with `edge_traversal` inserted.

        HERE and not in the serializer for one reason: this needs state, and
        that module is documented stateless and shared between runs. Everything
        below is per-run and already under the capture lock the caller holds, so
        no second lock is taken and the order the buffer sees is the order this
        method returns.
        """

        out: list[FrameDraft] = []
        for draft in drafts:
            call_id = str(dict(draft.details).get("call_id") or "")
            if self._is_chunk(draft):
                merged = self._coalesce_chunk(draft, call_id)
                if merged is not None:
                    out.append(merged)
                continue
            if call_id:
                # Any OTHER frame for this call ends its streaming window - the
                # completion, the failure, the token frame. Flushing here is
                # what makes the coalescing lossless: whatever was gathered and
                # not yet emitted goes out ahead of the frame that closes the
                # call, so the rail's last chunk and the `utterance` agree.
                flushed = self._flush_chunks(call_id, draft)
                if flushed is not None:
                    out.append(flushed)
            out.extend(self._traversal_for(draft))
            out.append(draft)
        return tuple(out)

    @staticmethod
    def _is_chunk(draft: FrameDraft) -> bool:
        return draft.kind is FrameKind.LLM and dict(draft.details).get("stage") == "chunk"

    def _coalesce_chunk(self, draft: FrameDraft, call_id: str) -> FrameDraft | None:
        """One chunk in; one frame out at most every STREAM_CHUNK_COALESCE_MS.

        Decision 15, the owner's, 2026-09-04: coalesce rather than grow the
        ring. `LLMStreamChunkEvent` fires per token, the ring holds 2,000 frames
        and a subscriber queue 512, so one chatty authored agent evicts its own
        history - and the ring is bounded precisely to make a run survivable, so
        trading that known bound for an unknown one is the wrong direction.

        Nothing is dropped. The text between emitted frames is CONCATENATED into
        the next one, so a rail renders the same characters in the same order,
        in fewer frames.
        """

        text = str(dict(draft.details).get("chunk") or "")
        self._chunk_pending.setdefault(call_id, []).append(text)
        now = monotonic()
        last = self._chunk_flushed.get(call_id)
        if last is not None and (now - last) * 1000 < STREAM_CHUNK_COALESCE_MS:
            return None
        self._chunk_flushed[call_id] = now
        return self._merged_chunk(draft, call_id)

    def _flush_chunks(self, call_id: str, at: FrameDraft) -> FrameDraft | None:
        """Whatever is still gathered for `call_id`, as one last chunk frame."""

        if not self._chunk_pending.get(call_id):
            self._chunk_pending.pop(call_id, None)
            self._chunk_flushed.pop(call_id, None)
            return None
        merged = self._merged_chunk(at, call_id)
        self._chunk_flushed.pop(call_id, None)
        return merged

    def _merged_chunk(self, at: FrameDraft, call_id: str) -> FrameDraft:
        text = "".join(self._chunk_pending.pop(call_id, ()))
        carried = {
            key: value
            for key, value in dict(at.details).items()
            if key not in ("chunk", "stage")
        }
        return FrameDraft(
            ts=at.ts,
            kind=FrameKind.LLM,
            event_type=UIEventType.MODEL_CALL,
            level=FrameLevel.INFO,
            node_id=at.node_id,
            message="Model stream chunk",
            details={
                **carried,
                "stage": "chunk",
                "chunk": text[: self.serializer.limits.max_string],
            },
        )

    def _traversal_for(self, draft: FrameDraft) -> tuple[FrameDraft, ...]:
        """C6's `edge_traversal`, ahead of the successor's own `NODE_START`.

        `from` is the last DECLARED node whose method finished, which is the
        predecessor for a sequential edge and for every arm of a fan-out, and
        for a fan-in is the arrival that actually triggered the join. Where the
        registry knows the author's edges - every builder graph does - a pair
        that is not one of them emits nothing, so two branches interleaving
        cannot invent an edge the canvas does not draw. A registry with no edges
        (both hand-written flows) falls back to execution order, which is the
        only thing there is to know there.
        """

        if draft.kind is not FrameKind.NODE_STATE:
            return ()
        node_id = draft.node_id
        if node_id not in self.registry.declared_node_ids:
            return ()
        if draft.event_type is UIEventType.NODE_END:
            self._last_finished = node_id
            return ()
        if draft.event_type is not UIEventType.NODE_START:
            return ()
        source = self._last_finished
        if source is None or source == node_id:
            return ()
        if self.registry.edges and (source, node_id) not in self.registry.edges:
            return ()
        return (
            FrameDraft(
                ts=draft.ts,
                kind=FrameKind.EDGE_TAKEN,
                event_type=UIEventType.EDGE_PROCESS,
                level=FrameLevel.INFO,
                node_id=node_id,
                message=f"{source} to {node_id}",
                details={
                    "stage": "traversal",
                    "from": source,
                    "to": node_id,
                    "port": None,
                },
            ),
        )

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
