"""An attachment node is not a step, and the run descriptor must not draw one.

`03-node-library.md` D1 grew `NodeKind` from seven to ten, and the three new
kinds - `tool`, `mcp`, `skill` - are ATTACHMENTS: things an agent or crew *has*,
reached along an `attach` edge, rather than steps the flow performs.

The descriptor is the run console's list of things that execute. An attachment
emits no frame, occupies no position in the order and has no state to show, so
it does not belong there. Two consequences, and each one fails differently:

1. **`DESCRIPTOR_KINDS` is a total lookup over the seven FLOW kinds.** An
   attachment node reaching it raises `KeyError` and takes the whole descriptor
   with it - so `GET /api/workflows/{id}/graph` would 500 for any graph an
   author had attached a tool to. The filter is what keeps that lookup a
   subscript rather than a `.get` with a fallback; a fallback would turn the
   next missing kind into a silently mislabelled card instead of a loud error.

2. **`incoming` decides three fields**, none of them obviously about edges:
   `flow_method_type` (start versus listen), `condition_type` (AND versus OR)
   and `trigger_methods`. An agent holding three tools has three inbound edges
   and has not branched three ways, so counting them reports a join the
   compiler never emits.

**Nothing in the rest of the suite reaches either path**, because no committed
document contains an attachment node - which is exactly why these are written
against a document built here rather than against a fixture.
"""

from __future__ import annotations

import unittest

from brief_crew.builder.descriptor import DESCRIPTOR_KINDS, builder_graph_descriptor
from brief_crew.builder.document import ATTACHMENT_KINDS, BuilderDocument


def _document_with_attachments() -> BuilderDocument:
    """`start -> worker -> done`, with a tool and a skill attached to `worker`.

    Three edges arrive at `worker` and only one of them is a flow edge, which is
    the shape both assertions below turn on.
    """

    return BuilderDocument.model_validate(
        {
            "schema": "builder.flow/v1",
            "id": "ug_0123abcd",
            "version": 1,
            "name": "attachment descriptor",
            "input_field": "idea",
            "nodes": [
                {
                    "id": "start",
                    "kind": "input",
                    "label": "Idea",
                    "config": {"field": "idea"},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "id": "worker",
                    "kind": "agent",
                    "label": "Worker",
                    "config": {"agent_id": "scoper", "tier": "cheap"},
                    "position": {"x": 0, "y": 120},
                },
                {
                    "id": "done",
                    "kind": "output",
                    "label": "Report",
                    "config": {"body_key": "markdown_body"},
                    "position": {"x": 0, "y": 240},
                },
                {
                    "id": "scraper",
                    "kind": "tool",
                    "label": "Firecrawl scrape",
                    "config": {"tool_id": "firecrawl_scrape"},
                    "position": {"x": 260, "y": 120},
                },
                {
                    "id": "notes",
                    "kind": "skill",
                    "label": "House style",
                    "config": {"skill_id": "house_style"},
                    "position": {"x": 260, "y": 200},
                },
            ],
            "edges": [
                {"id": "e1", "source": "start", "source_port": "out", "target": "worker"},
                {"id": "e2", "source": "worker", "source_port": "out", "target": "done"},
                {
                    "id": "e3",
                    "source": "scraper",
                    "source_port": "attach",
                    "target": "worker",
                    "target_port": "attach",
                },
                {
                    "id": "e4",
                    "source": "notes",
                    "source_port": "attach",
                    "target": "worker",
                    "target_port": "attach",
                },
            ],
        }
    )


class AttachmentNodesAreNotStepsTests(unittest.TestCase):
    def test_the_descriptor_kind_map_covers_flow_kinds_only(self) -> None:
        """The premise, asserted rather than assumed.

        If someone later adds `tool` to `DESCRIPTOR_KINDS`, the filter stops
        being load-bearing and this test should be the thing that says so -
        before the run console starts drawing idle cards nobody can explain.
        """

        self.assertFalse(
            ATTACHMENT_KINDS & set(DESCRIPTOR_KINDS),
            "DESCRIPTOR_KINDS gained an attachment kind; the descriptor filter "
            "and this map now disagree about whether an attachment is a step",
        )

    def test_attachment_nodes_do_not_appear_in_the_descriptor(self) -> None:
        descriptor = builder_graph_descriptor(_document_with_attachments())
        ids = [node.id for node in descriptor.nodes]

        self.assertEqual(["start", "worker", "done", "unattributed"], ids)
        self.assertNotIn("scraper", ids)
        self.assertNotIn("notes", ids)

    def test_an_attach_edge_is_not_a_trigger(self) -> None:
        """Three edges arrive at `worker`; exactly one of them triggers it."""

        descriptor = builder_graph_descriptor(_document_with_attachments())
        worker = next(node for node in descriptor.nodes if node.id == "worker")

        self.assertEqual(["start"], worker.trigger_methods)

    def test_attachments_do_not_manufacture_a_join(self) -> None:
        """The failure this one prevents is a WRONG answer, not a crash.

        `condition_type` reads how many predecessors a node has. Counting the
        two attach edges would report `AND` - a join waiting on a tool and a
        skill that will never fire, because the compiler emits no such
        predicate. The console would draw a graph that cannot be the one
        running.
        """

        descriptor = builder_graph_descriptor(_document_with_attachments())
        worker = next(node for node in descriptor.nodes if node.id == "worker")

        self.assertEqual("OR", worker.condition_type)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
