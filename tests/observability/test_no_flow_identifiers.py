"""Definition of Done row C1: the instrumentation path names no flow of ours.

The claim being tested is the one the whole design rests on: a flow somebody
draws next month is traced completely by code that has never heard of it. The
only way that can be true is if the exporter reads identity off frames and holds
no table of its own - so this greps the package for every agent role, agent key,
task key, tool name, crew name and skill-pack name this repository ships, and
asserts zero hits.

**What counts as an identifier, and what deliberately does not.** Whole strings:
the role sentences from `agents.yaml`, the agent and task keys, the tool names
and tool class names, the crew class names, and the four built-in skill packs.
NOT single dictionary words lifted out of a role sentence - "evidence",
"technical", "startup" - because that reading is incoherent here: the Python
package this code lives in is `brief_crew`, so the word from one agent key would
fail on every import line in the file. The identifiers below are the strings a
grep for "does this file know about our flows" would actually look for.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

import yaml


REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "src" / "brief_crew" / "observability"
CREWS = REPO / "src" / "brief_crew" / "crews"
TOOLS = REPO / "src" / "brief_crew" / "tools"
SKILLS = REPO / "data" / "skills" / "builtin"


def _package_sources() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE.glob("*.py"))
    }


def _yaml_identifiers() -> set[str]:
    found: set[str] = set()
    for path in sorted(CREWS.glob("*/config/agents.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key, body in document.items():
            found.add(str(key))
            if isinstance(body, dict):
                role = " ".join(str(body.get("role", "")).split())
                if role:
                    found.add(role)
    for path in sorted(CREWS.glob("*/config/tasks.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        found.update(str(key) for key in document)
    return {value for value in found if value}


def _tool_identifiers() -> set[str]:
    found: set[str] = set()
    for path in sorted(TOOLS.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        found.update(re.findall(r'^TOOL_NAME\s*=\s*"([^"]+)"', source, re.M))
        found.update(re.findall(r'^\s*name:\s*str\s*=\s*"([^"]+)"', source, re.M))
        found.update(re.findall(r"^class\s+(\w*Tool)\b", source, re.M))
    scrape = CREWS / "brief_crew" / "scrape_tool.py"
    if scrape.exists():
        found.update(
            re.findall(r"^class\s+(\w+)\b", scrape.read_text(encoding="utf-8"), re.M)
        )
    return {value for value in found if value and not value.startswith("_")}


def _crew_identifiers() -> set[str]:
    found: set[str] = set()
    for path in sorted(CREWS.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        found.update(re.findall(r"^class\s+(\w*Crew)\b", source, re.M))
    return found


def _skill_identifiers() -> set[str]:
    found: set[str] = set()
    if not SKILLS.exists():
        return found
    for pack in sorted(SKILLS.iterdir()):
        if not pack.is_dir():
            continue
        found.add(pack.name)
        card = pack / "SKILL.md"
        if card.exists():
            found.update(
                re.findall(r"^name:\s*(.+)$", card.read_text(encoding="utf-8"), re.M)
            )
    return {value.strip() for value in found if value.strip()}


class NoFlowIdentifiersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sources = _package_sources()
        self.assertTrue(self.sources, "the exporter package has no source files")

    def _assert_absent(self, identifiers: set[str], what: str) -> None:
        self.assertTrue(identifiers, f"no {what} were found to check against")
        hits: list[str] = []
        for identifier in sorted(identifiers):
            needle = identifier.lower()
            for name, source in self.sources.items():
                if needle in source.lower():
                    hits.append(f"{name}: {identifier!r}")
        self.assertEqual(
            [],
            hits,
            f"the exporter names {what} from this repository: {hits}",
        )

    def test_no_agent_role_or_key_from_either_crew(self) -> None:
        self._assert_absent(_yaml_identifiers(), "agent roles, agent keys or task keys")

    def test_no_tool_name_or_tool_class(self) -> None:
        self._assert_absent(_tool_identifiers(), "tool names or tool classes")

    def test_no_crew_class_name(self) -> None:
        self._assert_absent(_crew_identifiers(), "crew names")

    @unittest.skipUnless(SKILLS.exists(), "the built-in skill packs are not on disk")
    def test_no_built_in_skill_pack_name(self) -> None:
        self._assert_absent(_skill_identifiers(), "skill pack names")

    def test_the_extraction_found_the_things_it_claims_to_check(self) -> None:
        """A grep that finds nothing to grep for passes for the wrong reason.

        This is the control for the four tests above: if a rename, a moved file
        or a changed YAML shape made the extractors return an empty set, every
        one of them would pass while checking nothing. The counts are floors,
        not exact figures, so ordinary growth does not fail them.
        """

        self.assertGreaterEqual(len(_yaml_identifiers()), 20)
        self.assertGreaterEqual(len(_tool_identifiers()), 6)
        self.assertGreaterEqual(len(_crew_identifiers()), 6)

    def test_the_package_reads_identity_from_frame_details_only(self) -> None:
        """The positive half of C1: it does read identity, from one place.

        `_assert_absent` proves the exporter names none of our flows. On its own
        that is also true of an exporter that names nothing at all and traces
        nothing. This asserts the mechanism that makes the absence work.
        """

        exporter = self.sources["langfuse_exporter.py"]
        for expression in (
            'details.get("agent_role")',
            'details.get("task_name")',
            'details.get("tool")',
            'details.get("model")',
            "frame.node_id",
        ):
            with self.subTest(expression=expression):
                self.assertIn(expression, exporter)
