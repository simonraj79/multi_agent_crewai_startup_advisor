"""The free path now emits the C6 frames the run console narrates.

Plan 11 consumes five frame shapes (C6): `stage`, `edge_traversal`,
`utterance`, forwarded stream `chunk`s and `node_error`. Three of them already
reach a published builder graph on the free path, because `SYNTHETIC=1`
replaces only the crew factories and everything else - the compiled flow, the
adapter, the runner's own plan emitter - is the production code.

Two did not, and this module pins both repairs:

* `SyntheticValidatorRunner` emitted no `edge_taken` frame and no `llm` frame
  of any kind, so the console's edge march and its whole dialogue surface were
  structurally unobservable on the only path a test, an E2E run or a local
  session can use.
* `_SyntheticCrew` calls no model, so a published graph produced no
  `utterance` either.

Both are the same defect this repository has now recorded four times: a double
that cannot produce the thing under test certifies nothing (CLAUDE.md closed
items 20 and 33, and `SyntheticValidatorRunner._tool_call`'s own docstring).

What the tests below actually check is that the doubles match their SUBJECT.
Every field assertion names the production emitter it is mirroring, because a
double whose shape has drifted is worse than no double - it teaches the client
to read a key that will never arrive.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from brief_crew.service.graph import VALIDATOR_GRAPH
from brief_crew.service.runner import SyntheticValidatorRunner


class _Capture:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    def emit(self, **kwargs: Any) -> None:
        self.frames.append(kwargs)

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [
            frame
            for frame in self.frames
            if str(getattr(frame["kind"], "value", frame["kind"])) == kind
        ]

    def staged(self, stage: str) -> list[dict[str, Any]]:
        return [
            frame
            for frame in self.frames
            if dict(frame.get("details") or {}).get("stage") == stage
        ]


class _Execution:
    def __init__(self, idea: str = "a scheduling assistant") -> None:
        self.capture = _Capture()
        self.inputs = {"idea": idea, "no_gates": True}
        self.run_id = "run-choreography"
        self.flow_id = "flow-choreography"
        self.checkpoints: list[str] = []

    def checkpoint(self, name: str) -> None:
        self.checkpoints.append(name)


def _unattended() -> _Execution:
    execution = _Execution()
    SyntheticValidatorRunner()(execution)
    return execution


class EdgeTraversalTests(unittest.TestCase):
    """`edge_taken`, and that every pair it names is an edge the graph draws."""

    def setUp(self) -> None:
        self.execution = _unattended()

    def test_the_run_emits_traversals(self) -> None:
        self.assertTrue(self.execution.capture.of_kind("edge_taken"))

    def test_every_traversal_is_a_real_edge(self) -> None:
        """The whole reason the predecessor is named at each call site.

        A "whichever node finished last" rule reports
        `research_market -> research_sentiment` at the fan-out, which the
        topology does not contain; `events/adapter.py::_traversal_for` refuses
        that pair by consulting `NodeRegistry.edges`, and this asserts the
        double reaches the same answer by construction.
        """

        edges = {(edge.source, edge.target) for edge in VALIDATOR_GRAPH.edges}
        for frame in self.execution.capture.of_kind("edge_taken"):
            details = dict(frame["details"])
            with self.subTest(edge=(details["from"], details["to"])):
                self.assertIn((details["from"], details["to"]), edges)

    def test_the_fan_out_leaves_the_router_three_times(self) -> None:
        pairs = [
            (dict(frame["details"])["from"], dict(frame["details"])["to"])
            for frame in self.execution.capture.of_kind("edge_taken")
        ]
        for branch in ("research_market", "research_sentiment", "research_feasibility"):
            self.assertIn(("route_scope", branch), pairs)

    def test_the_details_mirror_the_real_emitter(self) -> None:
        """`{stage, from, to, port}` and nothing else - adapter.py:186-200."""

        details = dict(self.execution.capture.of_kind("edge_taken")[0]["details"])
        self.assertEqual(set(details), {"stage", "from", "to", "port"})
        self.assertEqual(details["stage"], "traversal")
        self.assertIsNone(details["port"])

    def test_the_frame_is_attributed_to_the_target(self) -> None:
        """As the real one is: the traversal precedes the successor's START."""

        for frame in self.execution.capture.of_kind("edge_taken"):
            self.assertEqual(frame["node_id"], dict(frame["details"])["to"])


class UtteranceTests(unittest.TestCase):
    """The chunks and the `utterance`, against `events/serializer.py`."""

    def setUp(self) -> None:
        self.execution = _unattended()

    def test_every_agent_node_says_something(self) -> None:
        spoke = {frame["node_id"] for frame in self.execution.capture.staged("utterance")}
        self.assertEqual(
            spoke,
            {
                "scope_idea",
                "research_market",
                "research_sentiment",
                "research_feasibility",
                "synthesize",
                "write_report",
            },
        )

    def test_a_router_says_nothing(self) -> None:
        """A router reads a structured reply and calls no model (PRD §7.0)."""

        spoke = {frame["node_id"] for frame in self.execution.capture.staged("utterance")}
        self.assertNotIn("route_scope", spoke)
        self.assertNotIn("route_verdict", spoke)
        self.assertNotIn("persist", spoke)

    def test_the_utterance_details_mirror_the_serializer(self) -> None:
        """The seven keys `serializer.py` writes at `stage="utterance"`."""

        details = dict(self.execution.capture.staged("utterance")[0]["details"])
        self.assertEqual(
            set(details),
            {
                "stage",
                "call_id",
                "text",
                "truncated",
                "prompt_tokens",
                "completion_tokens",
                "model",
            },
        )
        self.assertFalse(details["truncated"])
        self.assertTrue(details["text"])

    def test_the_chunk_details_mirror_the_coalescer(self) -> None:
        """`_merged_chunk` drops every key but `call_id`, `stage` and `chunk`."""

        details = dict(self.execution.capture.staged("chunk")[0]["details"])
        self.assertEqual(set(details), {"stage", "call_id", "chunk"})

    def test_the_chunks_concatenate_to_the_utterance(self) -> None:
        """The rail's contract: what streamed in equals what was said."""

        utterance = self.execution.capture.staged("utterance")[0]
        call_id = dict(utterance["details"])["call_id"]
        streamed = "".join(
            str(dict(frame["details"])["chunk"])
            for frame in self.execution.capture.staged("chunk")
            if dict(frame["details"])["call_id"] == call_id
        )
        self.assertEqual(streamed, dict(utterance["details"])["text"])

    def test_a_call_id_is_unique_per_node(self) -> None:
        ids = [
            dict(frame["details"])["call_id"]
            for frame in self.execution.capture.staged("utterance")
        ]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_model_is_not_a_prefixed_slug(self) -> None:
        """CrewAI's `LLM.__new__` strips the provider prefix before the event.

        So the real `utterance` never carries `openrouter/...`, and a double
        that did would let a client key on a spelling production never sends.
        """

        model = str(dict(self.execution.capture.staged("utterance")[0]["details"])["model"])
        self.assertNotIn("openrouter/", model)


class SyntheticCrewUtteranceTests(unittest.TestCase):
    """The builder-side double, whose output is JSON and whose rail is the same."""

    def _crew(self) -> Any:
        from brief_crew.service.builder_runner import SyntheticCrewFactories

        return SyntheticCrewFactories().agent_crew(
            node_id="scoper",
            agent_id="a1",
            tier="cheap",
            tools=(),
            max_iter=3,
            guardrail_max_retries=2,
        )

    def test_the_payload_is_unchanged(self) -> None:
        """Speaking must not alter what the node RETURNS - every downstream
        node reads this string, and plan 09's compiler tests assert its shape."""

        payload = json.loads(self._crew().kickoff({"idea": "x"}))
        self.assertEqual(payload["node_id"], "scoper")
        self.assertEqual(payload["prompt_inputs"], {"idea": "x"})

    def test_speaking_outside_a_capture_scope_is_silent(self) -> None:
        """`_emit_frame` swallows a missing context; a run must not fail on it."""

        self.assertTrue(self._crew().kickoff({}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
