"""The tool catalogue fixture is CURRENT - plan 06 criterion 11.

The sibling of `test_client_fixtures.py`, which does the same regenerate-and-
byte-compare for the back-edge and problem-code mirrors. A separate file rather
than three more cases in that one because that file is the Integrator's (S9's
ownership table) and this fixture is 06's; the mechanism is identical and the
docstring there is the fuller explanation of why it exists.

**What this fixture IS, and is not.** It is not a client catalogue - nothing
under `frontend/src` holds a copy of these rows, because a client-side catalogue
would offer tools the compiler has never heard of, which is cut-list item 17.
It is a TEST fixture, and the failure it guards is the other one: a spec whose
hand-built entry has quietly stopped resembling a real one. A double that
diverges from its subject certifies nothing, which is the lesson CLAUDE.md's
closed items 20 and 33 both record from opposite ends.

**Line endings.** `core.autocrlf` is `true` here, so a raw byte comparison would
report the platform rather than the drift. `committed()` normalises first, which
is the same call `test_client_fixtures.py` makes and for the same reason.

No cost: this reads `brief_crew.builder.tools` and one JSON file.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO))

from scripts.emit_builder_fixtures import (  # noqa: E402
    TOOL_CATALOGUE_PATH,
    build_tool_catalogue,
    committed,
    render,
)

REGENERATE = "./.venv/Scripts/python.exe scripts/emit_builder_fixtures.py"


class ToolCatalogueFixtureTests(unittest.TestCase):
    def test_the_committed_fixture_is_what_the_generator_produces_now(self) -> None:
        self.assertEqual(
            committed(TOOL_CATALOGUE_PATH),
            render(build_tool_catalogue()),
            "frontend/tests/fixtures/builderToolCatalogue.json is stale, so the "
            "TypeScript specs are mounting components over an answer this build "
            "no longer gives. Regenerate with:\n    " + REGENERATE,
        )

    def test_it_carries_every_entry_including_the_flagged_one(self) -> None:
        """A fixture that only held what today's flags enable would go stale the
        moment a flag moved, and the shape of a withheld entry is exactly what a
        client needs to be able to render if it ever is."""

        from brief_crew.builder.tools import TOOL_CATALOGUE

        payload = build_tool_catalogue()
        self.assertEqual(
            [entry["tool_id"] for entry in payload["entries"]],
            [entry.id for entry in TOOL_CATALOGUE],
        )
        self.assertIn("code_interpreter", [entry["tool_id"] for entry in payload["entries"]])

    def test_no_entry_carries_a_server_side_field(self) -> None:
        """The factory is a callable and a fixture is JSON, so a leak would be a
        serialisation error rather than a silent one - but `class_ref` is a
        STRING in the plan's own interface, and a string serialises fine."""

        for entry in build_tool_catalogue()["entries"]:
            with self.subTest(tool=entry["tool_id"]):
                self.assertNotIn("class_ref", entry)
                self.assertNotIn("factory", entry)
                self.assertNotIn("flag", entry)

    def test_it_is_valid_json_and_reads_back_as_what_was_written(self) -> None:
        raw = committed(TOOL_CATALOGUE_PATH)
        self.assertIsNotNone(raw, "the fixture is not committed")
        self.assertEqual(json.loads(raw or b"{}"), build_tool_catalogue())


if __name__ == "__main__":
    unittest.main()
