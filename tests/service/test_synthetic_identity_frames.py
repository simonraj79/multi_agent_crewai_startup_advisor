"""The synthetic double now says WHO produced each frame, and this pins it.

The fourth instance of one defect, and the docstrings in `service/runner.py`
record the first three: the double omitted `RUN_STATE.status`, then the report
body, then every tool, llm and token frame, and each time a green suite could
not see it because the surface under test had no producer on the free path.

This time the omission was documented as a decision. `_utterance`'s docstring
said "Deliberately NO `agent_role` or `task_name`: the real frame has neither",
and the real frame has both:
`FieldBoundedSerializer.drafts` (`events/serializer.py:328-392`) wraps the whole
ladder and merges `_actor(event)` into every frame whose node is not the
workflow's, because CrewAI populates `agent_role`, `task_name`, `agent_id` and
`task_id` on `BaseEvent` for every agent, task, tool and LLM event. So a client
written against this double could not join a frame to an agent - the field is
always there in production and was never there for free.

Three claims, and the third is the one that keeps this honest:

1. every frame of an agent node's visit carries `agent_role` and `task_name`,
2. the `agent` pair brackets that node's tool and llm frames,
3. the synthetic details are a SUBSET of what the real serializer writes for the
   same kind and stage - so closing this gap cannot open the mirror-image one,
   a double carrying a field production never sends.

The reference for (3) is `frontend/tests/fixtures/serializerFrames.ndjson`'s
generator, which is the real ladder over real CrewAI events. Comparing against
the real thing rather than a list typed here is the whole point: a list would
be a third copy of the frame contract, and this repository's own history says
what happens to those.

No cost: no network, no model, no credential.
"""

from __future__ import annotations

from typing import Any
import unittest

from brief_crew.service.graph import VALIDATOR_CREW_WIRING
from brief_crew.service.runner import _SPEAKING_NODES, SyntheticValidatorRunner
from tests.events.test_trace_fixture import build_frames

#: The four identity keys `_actor` may add to ANY non-workflow frame, plus the
#: retry counter it carries beside them. They are legal on every kind for the
#: same reason: `drafts` stamps uniformly and the ladder never sees them.
ACTOR_KEYS = frozenset({"agent_role", "task_name", "agent_id", "task_id", "run_attempts"})

#: Two kinds this file makes no claim about, and neither exclusion is an
#: oversight.
#:
#: `edge_taken` mirrors `events/adapter.py::_traversal_for`, which the ADAPTER
#: emits about an edge rather than the ladder drafting it from an event - so it
#: has no actor on the real path either, and the double leaves it unstamped for
#: the same reason (`_node`'s docstring).
#:
#: `verdict` is built by `events/verdict.py`, which the real path and this
#: double already SHARE - a single payload builder, so there is nothing there
#: that could drift. It lands on `synthesize`, an agent node, and still carries
#: no role: `VerdictComputedEvent` is raised by the flow method rather than by
#: an agent, so `_actor` finds nothing to stamp on the paid path either.
UNCOMPARED_KINDS = frozenset({"edge_taken", "verdict"})


class _Capture:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    def emit(self, **kwargs: Any) -> None:
        self.frames.append(kwargs)


class _Execution:
    def __init__(self) -> None:
        self.capture = _Capture()
        self.inputs = {"idea": "a claim auditor for newsrooms", "no_gates": True}
        self.run_id = "run-identity"
        self.flow_id = "flow-identity"

    def checkpoint(self, name: str) -> None:
        return None


def _kind(frame: dict[str, Any]) -> str:
    return str(getattr(frame["kind"], "value", frame["kind"]))


def _stage(frame: dict[str, Any]) -> str | None:
    stage = dict(frame.get("details") or {}).get("stage")
    return None if stage is None else str(stage)


def _run() -> list[dict[str, Any]]:
    """One unattended synthetic run, every frame it emitted, in order."""

    execution = _Execution()
    SyntheticValidatorRunner()(execution)
    return execution.capture.frames


class SyntheticIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frames = _run()
        self.agent_nodes = frozenset(VALIDATOR_CREW_WIRING)

    def test_the_speaking_nodes_are_exactly_the_wired_agent_nodes(self) -> None:
        """Two files, one fact. A drift between them is a node with no name."""

        self.assertEqual(set(_SPEAKING_NODES), self.agent_nodes)

    def test_every_frame_of_an_agent_node_names_its_agent_and_its_task(self) -> None:
        checked = 0
        for frame in self.frames:
            node_id = str(frame["node_id"])
            if node_id not in self.agent_nodes:
                continue
            if _kind(frame) in UNCOMPARED_KINDS:
                continue
            details = dict(frame.get("details") or {})
            wiring = VALIDATOR_CREW_WIRING[node_id]
            self.assertEqual(
                details.get("agent_role"),
                wiring["agent_role"],
                f"{_kind(frame)}/{_stage(frame)} on {node_id} named no agent",
            )
            self.assertEqual(details.get("task_name"), wiring["task_name"])
            checked += 1
        # A guard on the guard: a refactor that stopped emitting agent-node
        # frames entirely would otherwise pass the loop above vacuously.
        self.assertGreater(checked, 40, "too few agent-node frames to be a run")

    def test_a_router_and_the_output_node_name_no_agent(self) -> None:
        """The other half of the claim: identity where there IS an agent.

        `route_scope` reads a structured reply and `persist` writes a file.
        Neither runs an agent on the paid path, so neither raises an event
        carrying a role - and a double that invented one would teach the
        console that a router talks.
        """

        for node_id in ("route_scope", "route_verdict", "persist", "confirm_scope"):
            for frame in self.frames:
                if str(frame["node_id"]) != node_id:
                    continue
                details = dict(frame.get("details") or {})
                self.assertNotIn("agent_role", details, f"{node_id} claimed an agent")
                self.assertNotIn("task_name", details)

    def test_the_agent_pair_brackets_the_nodes_tool_and_llm_frames(self) -> None:
        """`agent` before, then the work, then `agent` after, inside the node."""

        for node_id in sorted(self.agent_nodes):
            sequence = [
                (_kind(frame), _stage(frame))
                for frame in self.frames
                if str(frame["node_id"]) == node_id
                # The edge INTO the node is emitted before the node opens and
                # the verdict frame is the run's statement rather than this
                # visit's; neither is part of the visit's own bracket.
                and _kind(frame) not in UNCOMPARED_KINDS
            ]
            if not sequence:
                continue  # a revise-only node this unattended run never reaches
            kinds = [kind for kind, _ in sequence]
            agent_positions = [
                index
                for index, (kind, stage) in enumerate(sequence)
                if kind == "agent" and stage in ("before", "after")
            ]
            self.assertEqual(
                len(agent_positions), 2, f"{node_id}: {sequence}"
            )
            opening, closing = agent_positions
            self.assertEqual(sequence[opening][1], "before")
            self.assertEqual(sequence[closing][1], "after")
            # The node's own lifecycle is OUTSIDE the pair, and the model and
            # tool work is INSIDE it - which is where CrewAI puts them: the
            # agent begins its loop inside the method the flow has already
            # reported as started.
            self.assertEqual(kinds[0], "node_state")
            self.assertEqual(kinds[-1], "node_state")
            self.assertLess(0, opening)
            self.assertLess(closing, len(sequence) - 1)
            for index, (kind, _) in enumerate(sequence):
                if kind in ("llm", "tool", "token"):
                    self.assertTrue(
                        opening < index < closing,
                        f"{node_id}: a {kind} frame fell outside the agent pair",
                    )

    def test_the_agent_pair_says_the_role_started_and_completed(self) -> None:
        frames = [
            frame
            for frame in self.frames
            if _kind(frame) == "agent" and str(frame["node_id"]) == "research_market"
        ]
        role = VALIDATOR_CREW_WIRING["research_market"]["agent_role"]
        self.assertEqual(
            [str(frame["message"]) for frame in frames],
            [f"{role} started", f"{role} completed"],
        )
        after = dict(frames[1]["details"])
        self.assertEqual(after["task"], VALIDATOR_CREW_WIRING["research_market"]["task_name"])
        # The completion carries what the agent said, not a second invented
        # string: the same words the `utterance` frame in the same visit did.
        utterance = next(
            dict(frame["details"])["text"]
            for frame in self.frames
            if str(frame["node_id"]) == "research_market"
            and dict(frame.get("details") or {}).get("stage") == "utterance"
        )
        self.assertEqual(after["output"], utterance)

    def test_the_synthetic_details_are_a_subset_of_the_real_serializers(self) -> None:
        """The claim that stops this fix opening the opposite defect.

        `real` is built from the fixture generator - the actual ladder over
        actual CrewAI events - grouped by kind and stage, unioned with the five
        keys `_actor` may add to any frame. A synthetic key outside that set is
        a field production never sends, which is exactly what the corrected
        docstring in `_utterance` was worried about; it was simply wrong about
        which fields those were.
        """

        real: dict[tuple[str, str | None], set[str]] = {}
        for frame in build_frames():
            key = (str(frame["kind"]), _stage(frame))
            real.setdefault(key, set()).update(dict(frame["details"]).keys())
        for key in real:
            real[key] |= ACTOR_KEYS

        compared = 0
        for frame in self.frames:
            kind = _kind(frame)
            if kind in UNCOMPARED_KINDS:
                continue
            key = (kind, _stage(frame))
            self.assertIn(
                key,
                real,
                f"the double emits {key} and the real ladder has no such frame",
            )
            extra = set(dict(frame.get("details") or {})) - real[key]
            self.assertEqual(extra, set(), f"{key} carries keys production does not")
            compared += 1
        self.assertGreater(compared, 40)

    def test_the_two_id_keys_are_absent_rather_than_invented(self) -> None:
        """`agent_id` and `task_id` are CrewAI's UUIDs and this run has none."""

        for frame in self.frames:
            details = dict(frame.get("details") or {})
            self.assertNotIn("agent_id", details)
            self.assertNotIn("task_id", details)


class BuilderSyntheticIdentityTests(unittest.TestCase):
    """The same field, in the half of the product where the graph is a stranger's.

    A builder-compiled `Task` is built with a description and an expected
    output and no `name` (`builder/runtime.py:910`), so `task_name` is absent
    from a real builder frame too and the double must not write one. The role
    is present on the paid path - `Agent(role=...)` at `:704` for an authored
    agent and the YAML `role` at `:619` for a library one - and was absent for
    free.
    """

    def frames_for(self, crew: Any) -> list[dict[str, Any]]:
        emitted: list[dict[str, Any]] = []

        def record(kind: Any, event_type: Any, **kwargs: Any) -> None:
            emitted.append({"kind": kind, **kwargs})

        import brief_crew.builder.runtime as runtime

        original = runtime._emit_frame
        runtime._emit_frame = record  # type: ignore[assignment]
        try:
            crew.kickoff({"idea": "a claim auditor"})
        finally:
            runtime._emit_frame = original  # type: ignore[assignment]
        return emitted

    def test_a_library_agent_node_carries_the_yaml_role(self) -> None:
        from brief_crew.service.builder_runner import SyntheticCrewFactories

        crew = SyntheticCrewFactories().agent_crew(
            node_id="n1",
            agent_id="market_analyst",
            tier="cheap",
            tools=(),
            max_iter=3,
            guardrail_max_retries=2,
        )
        for frame in self.frames_for(crew):
            details = dict(frame["details"])
            self.assertEqual(details["agent_role"], "Market evidence analyst")
            self.assertNotIn("task_name", details)

    def test_an_authored_agent_node_carries_the_authors_own_role(self) -> None:
        from types import SimpleNamespace

        from brief_crew.service.builder_runner import SyntheticCrewFactories

        crew = SyntheticCrewFactories().authored_agent_crew(
            node_id="n2",
            spec=SimpleNamespace(role="Fact Checker", tier="cheap", llm={}),
        )
        for frame in self.frames_for(crew):
            self.assertEqual(dict(frame["details"])["agent_role"], "Fact Checker")

    def test_a_multi_agent_crew_node_claims_no_single_role(self) -> None:
        """No single role is the truth at a crew node, so none is written."""

        from brief_crew.service.builder_runner import SyntheticCrewFactories

        crew = SyntheticCrewFactories().crew(
            node_id="n3",
            crew_id="validator",
            tier="cheap",
            max_iter=3,
            guardrail_max_retries=2,
        )
        for frame in self.frames_for(crew):
            self.assertNotIn("agent_role", dict(frame["details"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
