from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import unittest

from crewai.events import MethodExecutionFinishedEvent, MethodExecutionStartedEvent
from crewai.events.stream_context import publish_stream_event

from brief_crew.events import (
    CaptureContext,
    FieldBoundedSerializer,
    FrameBuffer,
    FrameKind,
    FrameLevel,
    NodeRegistry,
    StreamSinkAdapter,
    UIEventType,
    capture_events,
    ui_run_id,
)


class EventSpineTests(unittest.TestCase):
    def test_capture_is_scoped_ordered_and_immutable(self) -> None:
        structure = {
            "nodes": {"step": {}},
            "edges": [],
            "router_methods": [],
        }
        buffer = FrameBuffer(capacity=8)
        adapter = StreamSinkAdapter(
            run_id="run-a",
            buffer=buffer,
            registry=NodeRegistry.from_flow_structure(structure),
        )

        start = MethodExecutionStartedEvent(
            flow_name="SyntheticFlow", method_name="step", state={}, params=None
        )
        finish = MethodExecutionFinishedEvent(
            flow_name="SyntheticFlow", method_name="step", state={}, result="ok"
        )

        with capture_events(CaptureContext(run_id="run-a", adapter=adapter)):
            self.assertEqual(ui_run_id.get(), "run-a")
            publish_stream_event(None, start)
            publish_stream_event(None, finish)

        self.assertIsNone(ui_run_id.get())
        publish_stream_event(None, start)
        frames = buffer.replay()
        self.assertEqual([frame.seq for frame in frames], [1, 2])
        self.assertEqual(
            [frame.event_type for frame in frames],
            [UIEventType.NODE_START, UIEventType.NODE_END],
        )
        with self.assertRaises(FrozenInstanceError):
            frames[0].seq = 4  # type: ignore[misc]
        with self.assertRaises(TypeError):
            frames[0].details["changed"] = True  # type: ignore[index]

    def test_ring_reports_eviction_as_drop_and_gap(self) -> None:
        buffer = FrameBuffer(capacity=3)
        adapter = StreamSinkAdapter(
            run_id="run-b", buffer=buffer, registry=NodeRegistry()
        )
        for index in range(5):
            adapter.emit(
                kind=FrameKind.METRICS,
                event_type=UIEventType.WORKFLOW_START,
                node_id="workflow",
                message=f"frame {index}",
                level=FrameLevel.INFO,
            )

        self.assertEqual([frame.seq for frame in buffer.replay()], [3, 4, 5])
        stats = buffer.stats()
        self.assertEqual(stats.captured, 5)
        self.assertEqual(stats.dropped, 2)
        self.assertEqual(stats.gaps, 2)
        self.assertEqual(stats.emit_errors, 0)

    def test_router_finish_emits_node_end_then_edge(self) -> None:
        structure = {
            "nodes": {"route": {}, "hit": {}},
            "edges": [
                {
                    "source": "route",
                    "target": "hit",
                    "is_router_event": True,
                    "router_event": "cache_hit",
                }
            ],
            "router_methods": ["route"],
        }
        buffer = FrameBuffer()
        adapter = StreamSinkAdapter(
            run_id="run-c",
            buffer=buffer,
            registry=NodeRegistry.from_flow_structure(structure),
        )
        adapter(
            None,
            MethodExecutionFinishedEvent(
                flow_name="SyntheticFlow",
                method_name="route",
                state={},
                result="cache_hit",
            ),
        )

        frames = buffer.replay()
        self.assertEqual(
            [frame.event_type for frame in frames],
            [UIEventType.NODE_END, UIEventType.EDGE_PROCESS],
        )
        self.assertEqual(frames[1].details["to"], "hit")

    def test_serializer_clips_fields_without_serializing_live_objects(self) -> None:
        serializer = FieldBoundedSerializer()

        class Unsafe:
            def __repr__(self) -> str:
                return "x" * 10_000

        clipped = serializer.clip({"unsafe": Unsafe(), "text": "y" * 10_000})
        self.assertLessEqual(len(clipped["unsafe"]), serializer.limits.max_repr)
        self.assertLessEqual(len(clipped["text"]), serializer.limits.max_string)

    def test_concurrent_contexts_do_not_leak_frames(self) -> None:
        structure = {
            "nodes": {"step": {}},
            "edges": [],
            "router_methods": [],
        }

        def capture(run_id: str) -> tuple[str, ...]:
            buffer = FrameBuffer(capacity=32)
            adapter = StreamSinkAdapter(
                run_id=run_id,
                buffer=buffer,
                registry=NodeRegistry.from_flow_structure(structure),
            )
            with capture_events(CaptureContext(run_id=run_id, adapter=adapter)):
                for _ in range(10):
                    publish_stream_event(
                        None,
                        MethodExecutionStartedEvent(
                            flow_name="SyntheticFlow",
                            method_name="step",
                            state={},
                            params=None,
                        ),
                    )
            return tuple(frame.run_id for frame in buffer.replay())

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(capture, "run-one")
            second = executor.submit(capture, "run-two")

        self.assertEqual(first.result(), ("run-one",) * 10)
        self.assertEqual(second.result(), ("run-two",) * 10)

    def test_frame_model_rejects_unbounded_manual_details(self) -> None:
        buffer = FrameBuffer()
        adapter = StreamSinkAdapter(
            run_id="run-d", buffer=buffer, registry=NodeRegistry()
        )
        frame = adapter.emit(
            kind=FrameKind.METRICS,
            event_type=UIEventType.WORKFLOW_START,
            node_id="workflow",
            message="bounded",
            details={"text": "x" * 10_000},
        )
        self.assertIsNotNone(frame)
        self.assertLessEqual(len(frame.details["text"]), 4096)


if __name__ == "__main__":
    unittest.main()