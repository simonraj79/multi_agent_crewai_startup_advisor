"""The graph node and the frames must name the agent with the SAME string.

`GraphNode.agent_role` is what the canvas draws on a card;
`details.agent_role` is what every frame of that node carries. A console joins
one to the other - that is the whole point of having the field twice - so if
they disagree the join silently matches nothing, and neither side looks wrong
on its own. That is exactly the state the tree was in until 2026-09-05:

* `descriptor.py` set `agent_role` to `getattr(node.config, "agent_id", None)`.
  For a LIBRARY agent that is a registry key (`market_analyst`) and not a role
  ("Market evidence analyst"); for an AUTHORED agent - the arm the gauntlet is
  actually about - `AuthoredAgentConfig` has no `agent_id` at all, so the
  answer was `None` and the node the author had just named carried no identity.
* the synthetic crew emitted no `agent_role` on any frame, so the free path had
  nothing to join even if the descriptor had been right.

Both are fixed, and this file is the assertion that they stay fixed TOGETHER.
It runs one published graph carrying one of each kind of agent node through the
production `BuilderFlowRunner` with the same `SyntheticCrewFactories` that
`SYNTHETIC=1` installs, and compares the descriptor to the frames node by node.
Testing either half alone would pass with the two halves disagreeing, which is
the failure mode this replaces.

`task_name` is absent from both, and that is correct rather than a gap:
`builder/runtime.py:910` builds an authored `Task` with a description and an
expected output and no `name`, so a real builder frame carries none either.

No cost: `SyntheticCrewFactories` calls no model and a gate calls none by
construction.
"""

from __future__ import annotations

from typing import Any
import unittest

from brief_crew.builder.descriptor import (
    BuilderWorkflow,
    build_builder_workflow,
    library_agent_role,
    node_agent_role,
)
from brief_crew.builder.document import BuilderDocument
from brief_crew.events.adapter import StreamSinkAdapter
from brief_crew.events.buffer import FrameBuffer
from brief_crew.events.context import CaptureContext, current_capture
from brief_crew.service.builder_runner import BuilderFlowRunner, SyntheticCrewFactories
from brief_crew.service.runner import RunExecution
from tests.builder.test_compiler import (
    authored_agent_node,
    authored_crew_node,
    input_node,
    output_node,
    scoper_node,
)
from tests.builder.test_document import document, edge

#: The role the author typed, which `authored_agent_node` derives from the id.
AUTHORED_ROLE = "auditor specialist"
#: The role the YAML gives `agent_id: "scoper"`, which is NOT "scoper".
LIBRARY_ROLE = "Startup validation scoper"


def mixed_document() -> dict[str, Any]:
    """One library agent and one authored agent, in one graph.

    Both arms in one document rather than two, because the defect was
    per-arm - the library node published a key and the authored node published
    nothing - and a graph with only one of them would have found only one.
    """

    return document(
        [
            input_node(),
            scoper_node(tier="cheap"),
            authored_agent_node("auditor", source="scoper"),
            output_node("report", source="${state.out__auditor}"),
        ],
        [
            edge("e1", "idea", "scoper"),
            edge("e2", "scoper", "auditor"),
            edge("e3", "auditor", "report"),
        ],
    )


def run_frames(workflow: BuilderWorkflow) -> list[dict[str, Any]]:
    """Every frame one synthetic run of `workflow` emitted, as dicts.

    A real `StreamSinkAdapter` over a real `FrameBuffer`, scoped through
    `current_capture` the way `RunRegistry` scopes it for a live run - so what
    `builder/runtime.py::_emit_frame` writes here is what it writes in
    production, node attribution included.
    """

    buffer = FrameBuffer(capacity=512)
    adapter = StreamSinkAdapter(
        run_id="run-parity", buffer=buffer, registry=workflow.node_registry
    )
    token = current_capture.set(CaptureContext(run_id="run-parity", adapter=adapter))
    try:
        BuilderFlowRunner(workflow, crew_factories=SyntheticCrewFactories())(
            RunExecution(
                run_id="run-parity",
                inputs={"idea": "a claim auditor for newsrooms"},
                capture=adapter,
                flow_id="run-parity",
            )
        )
    finally:
        current_capture.reset(token)
    return [frame.to_dict() for frame in buffer.replay()]


class DescriptorRoleTests(unittest.TestCase):
    """The descriptor half, in isolation, before the parity claim."""

    def setUp(self) -> None:
        self.document = BuilderDocument.model_validate(mixed_document())
        self.nodes = {node.id: node for node in self.document.nodes}

    def role_of(self, node_id: str) -> str | None:
        return node_agent_role(self.nodes[node_id])

    def test_an_authored_agent_carries_the_role_the_author_typed(self) -> None:
        self.assertEqual(self.role_of("auditor"), AUTHORED_ROLE)

    def test_a_library_agent_carries_the_YAML_role_and_not_its_id(self) -> None:
        self.assertEqual(self.role_of("scoper"), LIBRARY_ROLE)
        # The regression in one line: the id is what this field used to hold.
        self.assertNotEqual(self.role_of("scoper"), "scoper")

    def test_a_crew_node_nominates_nobody(self) -> None:
        """Several agents run there and no single role is the truth."""

        crew = BuilderDocument.model_validate(
            document(
                [input_node(), authored_crew_node("panel"), output_node("report", source="${state.out__panel}")],
                [edge("e1", "idea", "panel"), edge("e2", "panel", "report")],
            )
        )
        by_id = {node.id: node for node in crew.nodes}
        self.assertIsNone(node_agent_role(by_id["panel"]))

    def test_a_node_that_is_not_an_agent_nominates_nobody(self) -> None:
        for node_id in ("idea", "report"):
            self.assertIsNone(self.role_of(node_id))

    def test_an_unknown_library_id_answers_none_rather_than_raising(self) -> None:
        """A label on a card must never be the reason a graph cannot describe itself."""

        self.assertIsNone(library_agent_role("no_such_agent"))

    def test_the_descriptor_publishes_what_the_helper_answers(self) -> None:
        workflow = build_builder_workflow(self.document)
        roles = {node.id: node.agent_role for node in workflow.descriptor.nodes}
        self.assertEqual(roles["scoper"], LIBRARY_ROLE)
        self.assertEqual(roles["auditor"], AUTHORED_ROLE)
        self.assertIsNone(roles["idea"])
        # `task_name` is None everywhere, because a compiled builder Task has
        # no name and a real frame carries none.
        self.assertEqual(
            {node.task_name for node in workflow.descriptor.nodes}, {None}
        )


class DescriptorAndFrameParityTests(unittest.TestCase):
    """The claim neither half can make alone."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = build_builder_workflow(
            BuilderDocument.model_validate(mixed_document())
        )
        cls.frames = run_frames(cls.workflow)
        cls.declared = {
            node.id: node.agent_role for node in cls.workflow.descriptor.nodes
        }

    def roles_on_frames(self, node_id: str) -> set[str | None]:
        return {
            dict(frame["details"]).get("agent_role")
            for frame in self.frames
            if frame["node_id"] == node_id
        }

    def test_the_run_produced_frames_for_both_agent_nodes(self) -> None:
        """A guard on the guard: the parity claim below is vacuous without this."""

        for node_id in ("scoper", "auditor"):
            self.assertTrue(
                [frame for frame in self.frames if frame["node_id"] == node_id],
                f"{node_id} emitted nothing, so parity proves nothing",
            )

    def test_every_frame_of_an_agent_node_names_the_role_the_card_shows(self) -> None:
        for node_id in ("scoper", "auditor"):
            self.assertEqual(
                self.roles_on_frames(node_id),
                {self.declared[node_id]},
                f"{node_id}: the card and its frames name different agents",
            )

    def test_the_two_strings_are_the_real_roles_and_not_ids(self) -> None:
        self.assertEqual(self.declared["scoper"], LIBRARY_ROLE)
        self.assertEqual(self.declared["auditor"], AUTHORED_ROLE)

    def test_no_frame_invents_a_task_name(self) -> None:
        for frame in self.frames:
            self.assertNotIn("task_name", dict(frame["details"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
