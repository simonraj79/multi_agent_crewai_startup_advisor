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

import ast
import inspect
from pathlib import Path
import re
import unittest

import yaml


REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "src" / "brief_crew" / "observability"
CREWS = REPO / "src" / "brief_crew" / "crews"
TOOLS = REPO / "src" / "brief_crew" / "tools"
SKILLS = REPO / "data" / "skills" / "builtin"
GRAPH = REPO / "src" / "brief_crew" / "service" / "graph.py"
BUILDER_TOOLS = REPO / "src" / "brief_crew" / "builder" / "tools.py"


def _package_sources() -> dict[str, str]:
    """The instrumentation path: the package, plus the serializer's two new bits.

    The serializer as a whole is NOT the instrumentation path - it is the frame
    pipeline, it converts CrewAI events for the whole application, and it names
    plenty of things this row is not about. What row C1 gained on 2026-09-06 is
    two functions inside it that exist only to feed this exporter, so those two
    are pulled in by source and nothing else is.
    """

    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE.glob("*.py"))
    }
    from brief_crew.events import serializer

    sources["serializer.prompt_digest"] = inspect.getsource(serializer.prompt_digest)
    sources["serializer.unhandled_report"] = inspect.getsource(
        serializer.FieldBoundedSerializer.unhandled_report
    )
    return sources


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


def _flow_method_identifiers() -> set[str]:
    """The NODE IDS, which are the flow methods, by introspecting the classes.

    This is the extractor the test did not have, and its absence is the gap a
    second review found: `if frame.node_id == "confirm_scope"` is the exact
    hardcoding this row forbids, and nothing here could see it. A node id is a
    flow method name - `service/graph.py` derives the topology from the
    decorated class and the frames carry the method name as `node_id` - so the
    authoritative list is the classes themselves.

    INTROSPECTION rather than an AST walk of the two modules, and the
    difference is not stylistic. Walking the module picks up every nested
    helper and every inner class's methods: `flush`, `write`, `writelines`,
    `served`, `turn`, `sink`, `plot`, `validate`. None is a node id, all are
    ordinary English or file-object verbs, and a grep for them over an exporter
    that legitimately flushes and writes reports hits on prose - which is how a
    check like this ends up either noisy or quietly disabled. Asking the `Flow`
    subclasses which methods they own answers the question that was asked.
    """

    from crewai.flow.flow import Flow

    import brief_crew.main as brief_module
    import brief_crew.validator_flow as validator_module

    found: set[str] = set()
    for module in (brief_module, validator_module):
        for _, obj in vars(module).items():
            if not (inspect.isclass(obj) and issubclass(obj, Flow) and obj is not Flow):
                continue
            found.add(obj.__name__)
            for name in vars(obj):
                # `model_post_init` is pydantic's hook, declared on every Flow;
                # it is framework vocabulary, not this repository's topology.
                if name.startswith("_") or hasattr(Flow, name):
                    continue
                found.add(name)
    return {value for value in found if len(value) >= 4}


def _workflow_id_identifiers() -> set[str]:
    """The ids the registry knows the two hand-written flows by."""

    source = GRAPH.read_text(encoding="utf-8")
    return set(re.findall(r'^[A-Z_]*WORKFLOW_ID\s*=\s*"([^"]+)"', source, re.M))


def _builder_library_identifiers() -> set[str]:
    """What a builder document may NAME: library keys, refs, platform tools.

    The builder half of the row and the half that generalises: a graph somebody
    draws next month picks its agent and its crew out of these registries, and
    an exporter that recognised one of them by name would be the same defect as
    one that recognised `market_analyst`.
    """

    from brief_crew import config
    from brief_crew.builder import runtime

    found: set[str] = set()
    for key, spec in runtime.BUILDER_AGENT_LIBRARY.items():
        found.add(str(key))
        role = getattr(spec, "role", None)
        if isinstance(role, str) and role.strip():
            found.add(" ".join(role.split()))
    found |= {str(key) for key in runtime.BUILDER_CREW_LIBRARY}
    found |= {str(value) for value in runtime.BUILDER_CREW_LIBRARY.values()}
    found |= {str(ref) for ref in config.BUILDER_ACTION_REFS}
    if BUILDER_TOOLS.exists():
        found |= set(
            re.findall(
                r'^\s*id="([^"]+)",', BUILDER_TOOLS.read_text(encoding="utf-8"), re.M
            )
        )
    try:
        from brief_crew.builder.tools import TOOL_CATALOGUE

        found |= {str(entry.id) for entry in TOOL_CATALOGUE}
    except Exception:  # pragma: no cover - the catalogue is a hard dependency
        pass
    return {value for value in found if len(value) >= 4}


#: Bare lowercase words are searched only as QUOTED literals; anything with a
#: separator, a space or internal capitals is searched as a whole word too.
#:
#: The distinction is the one the module docstring already draws for role
#: sentences, applied to identifiers: `confirm_scope` cannot occur in an
#: English sentence, so its presence anywhere - prose included - means this
#: code is talking about one specific flow. `persist` occurs in English all the
#: time, so only `"persist"` means anything, and that is exactly the shape a
#: hardcode takes: `frame.node_id == "persist"`.
def _is_distinctive(identifier: str) -> bool:
    return (
        "_" in identifier
        or " " in identifier
        or "-" in identifier
        or ":" in identifier
        or any(character.isupper() for character in identifier[1:])
    )


def _find(identifier: str, source: str) -> int | None:
    """The line an identifier is used on, or None. See `_is_distinctive`."""

    quoted = re.search(
        r"""['"]""" + re.escape(identifier) + r"""['"]""", source, re.I
    )
    match = quoted
    if match is None and _is_distinctive(identifier):
        match = re.search(r"\b" + re.escape(identifier) + r"\b", source, re.I)
    if match is None:
        return None
    return source.count("\n", 0, match.start()) + 1


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

    def _assert_not_used(self, identifiers: set[str], what: str) -> None:
        """The sharper half: a USE of the identifier, not a substring of prose.

        `_assert_absent` is a case-insensitive substring search and it is right
        for role sentences and tool names, which are distinctive enough that any
        occurrence is a finding. It is wrong for a node id like `persist` or a
        workflow id fragment, because those are English words and the exporter
        legitimately persists things - a substring rule over them reports the
        docstrings and gets switched off. `_find` asks the question that
        matters instead: is this identifier QUOTED here, or written in a shape
        no sentence produces?
        """

        self.assertTrue(identifiers, f"no {what} were found to check against")
        hits: list[str] = []
        for identifier in sorted(identifiers):
            for name, source in self.sources.items():
                line = _find(identifier, source)
                if line is not None:
                    hits.append(f"{name}:{line}: {identifier!r}")
        self.assertEqual(
            [],
            hits,
            f"the instrumentation path names {what} from this repository: {hits}",
        )

    def test_no_flow_method_name_which_is_to_say_no_node_id(self) -> None:
        """The gap a second review found, closed.

        Nothing in this file could catch `if frame.node_id == "confirm_scope"`
        before 2026-09-06: there was no extractor for flow method names, and a
        node id IS a flow method name. It is the single most likely way for
        this exporter to stop generalising, because it is the one identifier a
        frame actually carries.
        """

        self._assert_not_used(
            _flow_method_identifiers(), "flow method (node) names or flow classes"
        )

    def test_no_registered_workflow_id(self) -> None:
        self._assert_not_used(_workflow_id_identifiers(), "registered workflow ids")

    def test_no_builder_library_key_action_ref_or_platform_tool_id(self) -> None:
        self._assert_not_used(
            _builder_library_identifiers(),
            "builder library keys, action refs or platform tool ids",
        )

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
        self.assertGreaterEqual(len(_flow_method_identifiers()), 15)
        self.assertGreaterEqual(len(_workflow_id_identifiers()), 2)
        self.assertGreaterEqual(len(_builder_library_identifiers()), 20)

    def test_the_search_can_actually_find_a_planted_node_id(self) -> None:
        """The control for the three tests above, and the one that matters.

        A grep that cannot fail is not evidence, and this row is judged on a
        grep. `confirm_scope` is a real node id of a real flow; if `_find`
        cannot see it in a line shaped exactly like the hardcode this row
        forbids, then the three assertions above are decoration.
        """

        planted = 'if frame.node_id == "confirm_scope":  # a hardcode'
        self.assertIn("confirm_scope", _flow_method_identifiers())
        self.assertEqual(1, _find("confirm_scope", planted))
        # And the other direction: prose about persisting is not a hardcode,
        # while the quoted node id is.
        self.assertIsNone(_find("persist", "the exporter persists nothing here"))
        self.assertEqual(1, _find("persist", 'node_id == "persist"'))

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
