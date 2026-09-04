"""What the agent SAID, what it streamed, and where it went - C6, criterion 8.

Four frames, four questions nothing could answer before:

* `utterance` - the completed response was DROPPED. `LLMCallCompletedEvent`
  carries the whole answer and the frame carried `finish_reason` and
  `response_id`, so a run view could show that a model had been called and never
  what came back.
* the coalesced chunk - `LLMStreamChunkEvent` fires per token, the ring holds
  2,000 frames and a subscriber queue 512, so a chatty authored agent evicted
  its own history. Decision 15, the owner's: coalesce at 250 ms rather than grow
  the ring, because the ring is bounded to make a run survivable.
* `edge_traversal` - which edge the run just took, ahead of the successor's own
  `NODE_START`.
* `stage` - the whole plan, at kickoff, before any node has run.

The coalescing tests drive a FAKE clock. Sleeping 250 ms per assertion would
put a quarter of a second into the suite for every one of them and would still
be a race; `monotonic` is patched instead, which is exact.
"""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Any
import unittest
from unittest.mock import patch

from crewai.events import LLMCallCompletedEvent, LLMStreamChunkEvent

from brief_crew.builder.descriptor import build_builder_workflow, plan_layers
from brief_crew.config import MAX_UTTERANCE_CHARS, STREAM_CHUNK_COALESCE_MS
from brief_crew.events import FrameKind, UIEventType
from brief_crew.events.adapter import StreamSinkAdapter
from brief_crew.events.buffer import FrameBuffer
from brief_crew.events.context import CaptureContext, capture_events
from brief_crew.events.registry import NodeRegistry
from brief_crew.events.serializer import FieldBoundedSerializer
from brief_crew.service.builder_runner import BuilderFlowRunner, SyntheticCrewFactories
from brief_crew.service.runner import RunExecution
from tests.builder.test_compiler import input_node, output_node, scoper_node
from tests.builder.test_document import document, edge

IDEA = "a scheduling assistant for clinics"


def completed(response: Any, *, call_id: str = "call-1") -> LLMCallCompletedEvent:
    return LLMCallCompletedEvent(
        messages=[{"role": "user", "content": "hello"}],
        response=response,
        call_type="llm_call",
        model="openrouter/google/gemini-3.8-flash",
        call_id=call_id,
        usage={"prompt_tokens": 11, "completion_tokens": 7},
    )


class UtteranceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.serializer = FieldBoundedSerializer()
        self.registry = NodeRegistry()

    def utterance(self, event: Any) -> dict[str, Any]:
        frames = self.serializer.drafts(None, event, self.registry)
        matching = [
            dict(frame.details)
            for frame in frames
            if dict(frame.details).get("stage") == "utterance"
        ]
        self.assertEqual(len(matching), 1, [dict(f.details) for f in frames])
        return matching[0]

    def test_a_ten_thousand_character_response_is_clipped_and_says_so(self) -> None:
        details = self.utterance(completed("x" * 10_000))
        self.assertEqual(len(details["text"]), MAX_UTTERANCE_CHARS)
        self.assertEqual(MAX_UTTERANCE_CHARS, 4096)
        self.assertTrue(details["truncated"])

    def test_a_short_response_is_whole_and_not_truncated(self) -> None:
        details = self.utterance(completed("the market is crowded"))
        self.assertEqual(details["text"], "the market is crowded")
        self.assertFalse(details["truncated"])

    def test_it_carries_the_tokens_the_model_and_the_call(self) -> None:
        details = self.utterance(completed("hello"))
        self.assertEqual(details["prompt_tokens"], 11)
        self.assertEqual(details["completion_tokens"], 7)
        self.assertEqual(details["call_id"], "call-1")
        self.assertIn("gemini", str(details["model"]))

    def test_a_structured_response_is_reduced_to_text_rather_than_dropped(self) -> None:
        """`response` is typed `Any` and is not always a string."""

        class Structured:
            content = "a paragraph from an object"

        self.assertEqual(
            self.utterance(completed(Structured()))["text"],
            "a paragraph from an object",
        )

    def test_a_response_that_is_neither_is_json_rather_than_a_repr(self) -> None:
        details = self.utterance(completed({"verdict": "NEEDS_WORK"}))
        self.assertIn("NEEDS_WORK", details["text"])

    def test_the_existing_two_frames_are_untouched(self) -> None:
        """Three frames now, and the other two are the ones that were there."""

        frames = self.serializer.drafts(None, completed("hi"), self.registry)
        stages = [dict(frame.details).get("stage") for frame in frames]
        self.assertEqual(stages.count("after"), 1)
        self.assertEqual(len(frames), 3)
        token = [frame for frame in frames if frame.kind is FrameKind.TOKEN]
        self.assertEqual(len(token), 1)


class ChunkCoalescingTests(unittest.TestCase):
    """Decision 15, on a fake clock."""

    def setUp(self) -> None:
        self.buffer = FrameBuffer()
        self.adapter = StreamSinkAdapter(
            run_id="run-1", buffer=self.buffer, registry=NodeRegistry()
        )
        self.now = 1000.0

    def tick(self, seconds: float) -> None:
        self.now += seconds

    def chunk(self, text: str, *, call_id: str = "call-1") -> None:
        with patch(
            "brief_crew.events.adapter.monotonic", lambda: self.now
        ):
            self.adapter(None, LLMStreamChunkEvent(chunk=text, call_id=call_id))

    def chunks(self) -> list[str]:
        return [
            str(dict(frame.details).get("chunk"))
            for frame in self.buffer.replay(after=0, limit=500)
            if dict(frame.details).get("stage") == "chunk"
        ]

    def test_a_burst_of_forty_tokens_is_one_frame(self) -> None:
        for index in range(40):
            self.chunk(f"{index} ")
        self.assertEqual(len(self.chunks()), 1)

    def test_nothing_is_lost_when_the_window_closes(self) -> None:
        """The text between emitted frames is concatenated into the next one."""

        for index in range(4):
            self.chunk(str(index))
        self.tick(1.0)
        self.chunk("4")
        self.assertEqual("".join(self.chunks()), "01234")

    def test_at_most_four_frames_a_second_per_call(self) -> None:
        """The criterion's own bound, driven a millisecond at a time."""

        for step in range(1000):
            self.tick(0.001)
            self.chunk("x")
        self.assertLessEqual(len(self.chunks()), 4)
        self.assertEqual(STREAM_CHUNK_COALESCE_MS, 250)

    def test_two_calls_are_coalesced_independently(self) -> None:
        self.chunk("a", call_id="one")
        self.chunk("b", call_id="two")
        by_call = {
            str(dict(frame.details).get("call_id")): str(dict(frame.details).get("chunk"))
            for frame in self.buffer.replay(after=0, limit=500)
            if dict(frame.details).get("stage") == "chunk"
        }
        self.assertEqual(by_call, {"one": "a", "two": "b"})

    def test_the_completion_flushes_what_was_still_gathered(self) -> None:
        """Lossless: the rail's last chunk and the `utterance` agree."""

        self.chunk("first ")
        self.chunk("second ")
        self.chunk("third")
        self.adapter(None, completed("first second third"))
        self.assertEqual("".join(self.chunks()), "first second third")

    def test_the_flush_comes_before_the_frame_that_closed_the_call(self) -> None:
        self.chunk("a")
        self.chunk("b")
        self.adapter(None, completed("ab"))
        stages = [
            dict(frame.details).get("stage")
            for frame in self.buffer.replay(after=0, limit=500)
        ]
        self.assertLess(
            len(stages) - 1 - stages[::-1].index("chunk"), stages.index("utterance")
        )


class EdgeTraversalTests(unittest.TestCase):
    """C6 `edge_traversal`, over a real compiled graph."""

    def frames(self, graph: Any) -> list[Any]:
        workflow = build_builder_workflow(graph)
        buffer = FrameBuffer()
        capture = StreamSinkAdapter(
            run_id="run-edge", buffer=buffer, registry=workflow.node_registry
        )
        execution = RunExecution(
            run_id="run-edge",
            inputs={"idea": IDEA},
            capture=capture,
            flow_id="run-edge",
            cancel_requested=threading.Event(),
        )
        runner = BuilderFlowRunner(workflow, crew_factories=SyntheticCrewFactories())
        with capture_events(CaptureContext(run_id="run-edge", adapter=capture)):
            runner(execution)
        return list(buffer.replay(after=0, limit=500))

    @staticmethod
    def straight() -> Any:
        return document(
            [
                input_node(),
                scoper_node("a"),
                scoper_node("b"),
                output_node("report", source="${state.out__b}"),
            ],
            [
                edge("e1", "idea", "a"),
                edge("e2", "a", "b"),
                edge("e3", "b", "report"),
            ],
        )

    def test_a_traversal_precedes_the_successors_node_start(self) -> None:
        frames = self.frames(self.straight())
        traversal = next(
            frame
            for frame in frames
            if frame.kind is FrameKind.EDGE_TAKEN
            and dict(frame.details).get("stage") == "traversal"
            and dict(frame.details).get("to") == "b"
        )
        start = next(
            frame
            for frame in frames
            if frame.node_id == "b"
            and frame.event_type is UIEventType.NODE_START
            and dict(frame.details).get("stage") == "before"
        )
        self.assertLess(traversal.seq, start.seq)
        self.assertEqual(dict(traversal.details)["from"], "a")

    def test_every_traversal_names_an_edge_the_author_actually_drew(self) -> None:
        graph = self.straight()
        drawn = {(item.source, item.target) for item in graph.edges}
        for frame in self.frames(graph):
            if dict(frame.details).get("stage") != "traversal":
                continue
            pair = (dict(frame.details)["from"], dict(frame.details)["to"])
            self.assertIn(pair, drawn, pair)

    def test_the_registry_carries_the_edges_that_make_that_possible(self) -> None:
        workflow = build_builder_workflow(self.straight())
        self.assertIn(("a", "b"), workflow.node_registry.edges)
        self.assertNotIn(("idea", "b"), workflow.node_registry.edges)

    def test_a_registry_with_no_edges_falls_back_to_execution_order(self) -> None:
        """Both hand-written flows keep their edges in `service/graph.py`."""

        self.assertEqual(NodeRegistry().edges, frozenset())


class StageFrameTests(unittest.TestCase):
    """C6 `stage`: one per topological layer, all at kickoff."""

    def graph(self) -> Any:
        return document(
            [
                input_node(),
                scoper_node("a"),
                scoper_node("b"),
                output_node("report", source="${state.out__b}"),
            ],
            [
                edge("e1", "idea", "a"),
                edge("e2", "a", "b"),
                edge("e3", "b", "report"),
            ],
        )

    def run_frames(self) -> tuple[Any, list[Any]]:
        graph = self.graph()
        workflow = build_builder_workflow(graph)
        buffer = FrameBuffer()
        capture = StreamSinkAdapter(
            run_id="run-stage", buffer=buffer, registry=workflow.node_registry
        )
        runner = BuilderFlowRunner(workflow, crew_factories=SyntheticCrewFactories())
        execution = RunExecution(
            run_id="run-stage",
            inputs={"idea": IDEA},
            capture=capture,
            flow_id="run-stage",
            cancel_requested=threading.Event(),
        )
        with capture_events(CaptureContext(run_id="run-stage", adapter=capture)):
            runner(execution)
        return graph, list(buffer.replay(after=0, limit=500))

    def stages(self, frames: list[Any]) -> list[dict[str, Any]]:
        return [
            dict(frame.details)
            for frame in frames
            if dict(frame.details).get("stage") == "plan"
        ]

    def test_there_is_one_stage_frame_per_layer(self) -> None:
        graph, frames = self.run_frames()
        layers = plan_layers(graph)
        stages = self.stages(frames)
        self.assertEqual(len(stages), len(layers))
        self.assertEqual([tuple(stage["node_ids"]) for stage in stages], list(layers))

    def test_they_are_numbered_and_all_emitted_before_the_first_node(self) -> None:
        _, frames = self.run_frames()
        stages = self.stages(frames)
        self.assertEqual([stage["index"] for stage in stages], [1, 2, 3, 4])
        self.assertTrue(all(stage["of"] == 4 for stage in stages))
        last_plan = max(
            frame.seq
            for frame in frames
            if dict(frame.details).get("stage") == "plan"
        )
        first_node = min(
            frame.seq
            for frame in frames
            if frame.event_type is UIEventType.NODE_START
            and dict(frame.details).get("stage") == "before"
        )
        self.assertLess(last_plan, first_node)

    def test_a_fan_out_is_ONE_layer_and_not_three(self) -> None:
        """The concurrency is the interesting fact - `crewStages.ts`'s judgement."""

        from tests.builder.test_compiler import fan_out_and_join

        layers = plan_layers(fan_out_and_join())
        widest = max(layers, key=len)
        self.assertEqual(set(widest), {"market", "signal"})

    def test_a_cycle_does_not_swallow_the_rest_of_the_plan(self) -> None:
        """Kahn over a cyclic graph answers short and raises nothing."""

        from tests.builder.test_compiler import gated_loop

        graph = gated_loop(max_turns=1)
        planned = {node_id for layer in plan_layers(graph) for node_id in layer}
        self.assertEqual(
            planned,
            {node.id for node in graph.nodes},
        )


class TimestampTests(unittest.TestCase):
    def test_the_utterance_frame_keeps_the_events_own_timestamp(self) -> None:
        moment = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
        event = completed("hi")
        event.timestamp = moment
        frames = FieldBoundedSerializer().drafts(None, event, NodeRegistry())
        for frame in frames:
            self.assertEqual(frame.ts, moment)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
