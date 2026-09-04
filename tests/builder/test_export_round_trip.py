"""A graph the author can export is a graph somebody can import — D-15-28.

Judge round 3 found that a document containing an `mcp` or a `skill` node
exported **200** and then could not be imported by anybody, its own author
included: `nodes.N.server_id — Input should be a valid string`. The author could
produce a file nobody could open, and the console reported success.

**It survived 1742 Python, 1318 frontend and 59 E2E green tests**, and the
reason is worth keeping. The only test of that path asserted over a dict that
raises eight validation errors against `BuilderDocument` — it proved that
INVALID input is refused, which is a different claim from "valid output can be
read back". Nobody had round-tripped a document containing a node kind that did
not exist when the test was written.

It was a cross-plan defect and neither plan was careless. `export.py` was built
against seven node kinds and strips `server_id` and `skill_id` **deliberately**:
they name rows in the exporting author's own lists, and a different author
importing that file must not end up pointing at them. Isolation is the whole
point. Plan 03 then landed ten kinds, with `McpConfig.server_id` and
`SkillConfig.skill_id` REQUIRED — and required is exactly what an exported
document cannot supply.

So the round trip is the property to test, and this file tests it in the one
direction nothing else did: out and back.
"""

from __future__ import annotations

import unittest

from brief_crew.builder.document import BuilderDocument
from brief_crew.builder.export import strip_for_export


def _raw() -> dict:
    """`start → worker → done`, with an MCP server and a skill attached."""

    return {
        "schema": "builder.flow/v1",
        "id": "ug_0123abcd",
        "version": 1,
        "name": "round trip",
        "input_field": "idea",
        "nodes": [
            {"id": "start", "kind": "input", "label": "Idea",
             "config": {"field": "idea"}, "position": {"x": 0, "y": 0}},
            {"id": "worker", "kind": "agent", "label": "Worker",
             "config": {"agent_id": "scoper", "tier": "cheap"},
             "position": {"x": 0, "y": 120}},
            {"id": "done", "kind": "output", "label": "Report",
             "config": {"body_key": "markdown_body"},
             "position": {"x": 0, "y": 240}},
            {"id": "srv", "kind": "mcp", "label": "A server",
             "config": {"server_id": "some_server", "tool_names": ["alpha"]},
             "position": {"x": 260, "y": 120}},
            {"id": "pack", "kind": "skill", "label": "House style",
             "config": {"skill_id": "house_style", "skill_name": "House style"},
             "position": {"x": 260, "y": 200}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "source_port": "out", "target": "worker"},
            {"id": "e2", "source": "worker", "source_port": "out", "target": "done"},
            {"id": "e3", "source": "srv", "source_port": "attach",
             "target": "worker", "target_port": "attach"},
            {"id": "e4", "source": "pack", "source_port": "attach",
             "target": "worker", "target_port": "attach"},
        ],
    }


def _exported(raw: dict) -> tuple[dict, list[str]]:
    """Export, then put back the two keys the ENVELOPE carries, not the document.

    `id` and `version` are the importer's to supply — a file does not choose the
    id it lands under. Restoring them here is what makes this a test of the
    document shape rather than of the import route's bookkeeping.
    """

    stripped, needs = strip_for_export(raw)
    stripped["id"] = raw["id"]
    stripped["version"] = raw["version"]
    return stripped, needs


class ExportRoundTripTests(unittest.TestCase):
    def test_a_graph_with_attachments_survives_export_and_import(self) -> None:
        """The whole defect, in one assertion.

        Before the fix this raised on `nodes.3.server_id` and, once that was
        allowed, again on `nodes.3.server_hint — Extra inputs are not
        permitted`, because `BuilderModel` is `extra="forbid"` and the export
        WRITES that key.
        """

        stripped, _ = _exported(_raw())
        document = BuilderDocument.model_validate(stripped)

        self.assertEqual(5, len(document.nodes))
        self.assertEqual(
            {"input", "agent", "output", "mcp", "skill"},
            {node.kind for node in document.nodes},
        )

    def test_the_server_reference_is_gone_and_that_is_the_point(self) -> None:
        """Stripping is isolation, not a bug, and the fix must not undo it.

        `server_id` names a row in the EXPORTING author's own list. If it
        survived, an importing author would open a graph pointing at somebody
        else's server — which is the isolation rubric's whole subject.
        """

        stripped, needs = _exported(_raw())
        document = BuilderDocument.model_validate(stripped)
        server = next(node for node in document.nodes if node.id == "srv")

        self.assertIsNone(server.config.server_id)
        self.assertIn(
            "srv",
            needs,
            "the node that lost a reference must be named in needs_credentials, "
            "or the file opens green about a graph that cannot run",
        )

    def test_the_skill_name_survives_where_the_id_cannot(self) -> None:
        """`export.py`'s docstring described a field that did not exist.

        It says a node losing only a `skill_id` is absent from
        `needs_credentials` because "`skill_name` survives and is what the
        importer's own library resolves by". `SkillConfig` had no `skill_name`,
        so the export stripped the id, found nothing to leave, and wrote
        `config: {}` — a skill node with nothing in it at all.
        """

        stripped, needs = _exported(_raw())
        document = BuilderDocument.model_validate(stripped)
        skill = next(node for node in document.nodes if node.id == "pack")

        self.assertIsNone(skill.config.skill_id)
        self.assertEqual("House style", skill.config.skill_name)
        self.assertNotIn(
            "pack",
            needs,
            "a node that lost only its skill_id is resolvable by name and is "
            "deliberately NOT in needs_credentials",
        )

    def test_an_authored_document_still_requires_nothing_it_did_not_before(self) -> None:
        """The relaxation must not make an ORIGINAL document sloppier.

        `server_id` and `skill_id` became optional so an EXPORTED document can
        parse. A document an author has just drawn is a different artefact, and
        a node with neither an id nor a name is an incomplete graph — which
        `bounds.py` reports and this file does not raise on, exactly as
        `McpConfig.tool_names` already works.
        """

        raw = _raw()
        # Neither an id nor a name: parses, because parsing is not the layer
        # that decides a graph is finished.
        raw["nodes"][4]["config"] = {}
        document = BuilderDocument.model_validate(raw)
        skill = next(node for node in document.nodes if node.id == "pack")

        self.assertIsNone(skill.config.skill_id)
        self.assertIsNone(skill.config.skill_name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
