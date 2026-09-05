"""V-REVIEW's INDEPENDENT C1 grep (second pass, 2026-09-06).

Not a committed test and not part of any suite: it is the verifier's own
extractor, deliberately WIDER than
`tests/observability/test_no_flow_identifiers.py`, so that the row is checked
rather than the test being re-run.

It extracts, from the repository:

  * every agent key and role sentence in `crews/*/config/agents.yaml`
  * every task key in `crews/*/config/tasks.yaml`
  * every tool name / tool class in `src/brief_crew/tools/**` and the brief
    crew's scrape tool
  * every `*Crew` class name under `src/brief_crew/crews/**`
  * the four built-in skill packs (directory name + SKILL.md `name:`)
  * the builder library registries: `BUILDER_AGENT_LIBRARY` keys and their role
    strings, `BUILDER_CREW_LIBRARY` keys and class names, `BUILDER_ACTION_REFS`
  * the builder platform tool ids in `builder/tools.py`
  * the two hand-written flows' REGISTERED workflow ids and flow class names
    and every flow method name (which ARE the node ids)

and greps all of it, case-insensitively, over

  * every file in `src/brief_crew/observability/`
  * the two new serializer functions row C1's second pass names:
    `prompt_digest` and `EventSerializer._unhandled_report`

Usage:  ./.venv/Scripts/python.exe docs/observability/evidence/tests/c1_identifier_grep.py
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import re
import sys


REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

PACKAGE = REPO / "src" / "brief_crew" / "observability"
CREWS = REPO / "src" / "brief_crew" / "crews"
TOOLS = REPO / "src" / "brief_crew" / "tools"
SKILLS = REPO / "data" / "skills" / "builtin"


def yaml_identifiers() -> dict[str, list[str]]:
    import yaml

    agents: set[str] = set()
    tasks: set[str] = set()
    for path in sorted(CREWS.glob("*/config/agents.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key, body in document.items():
            agents.add(str(key))
            if isinstance(body, dict):
                role = " ".join(str(body.get("role", "")).split())
                if role:
                    agents.add(role)
    for path in sorted(CREWS.glob("*/config/tasks.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tasks.update(str(key) for key in document)
    return {"agent keys and roles": sorted(agents), "task keys": sorted(tasks)}


def tool_identifiers() -> list[str]:
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
    return sorted(v for v in found if v and not v.startswith("_"))


def crew_identifiers() -> list[str]:
    found: set[str] = set()
    for path in sorted(CREWS.rglob("*.py")):
        found.update(
            re.findall(r"^class\s+(\w*Crew)\b", path.read_text(encoding="utf-8"), re.M)
        )
    return sorted(found)


def skill_identifiers() -> list[str]:
    found: set[str] = set()
    if SKILLS.exists():
        for pack in sorted(SKILLS.iterdir()):
            if not pack.is_dir():
                continue
            found.add(pack.name)
            card = pack / "SKILL.md"
            if card.exists():
                found.update(
                    re.findall(
                        r"^name:\s*(.+)$", card.read_text(encoding="utf-8"), re.M
                    )
                )
    return sorted(v.strip() for v in found if v.strip())


def builder_identifiers() -> dict[str, list[str]]:
    from brief_crew.builder import runtime
    from brief_crew import config

    agents: set[str] = set()
    for key, spec in runtime.BUILDER_AGENT_LIBRARY.items():
        agents.add(str(key))
        for attr in ("role", "goal", "backstory"):
            value = getattr(spec, attr, None)
            if isinstance(value, str) and value.strip():
                agents.add(" ".join(value.split()))
    crews = {str(k) for k in runtime.BUILDER_CREW_LIBRARY} | {
        str(v) for v in runtime.BUILDER_CREW_LIBRARY.values()
    }
    refs = {str(r) for r in config.BUILDER_ACTION_REFS}

    tools_source = (REPO / "src" / "brief_crew" / "builder" / "tools.py").read_text(
        encoding="utf-8"
    )
    platform_tools = set(re.findall(r'^\s*id="([^"]+)",', tools_source, re.M))
    try:
        from brief_crew.builder.tools import TOOL_CATALOGUE

        platform_tools |= {str(entry.id) for entry in TOOL_CATALOGUE}
    except Exception:
        pass
    return {
        "builder agent library": sorted(agents),
        "builder crew library": sorted(crews),
        "builder action refs": sorted(refs),
        "builder platform tools": sorted(platform_tools),
    }


def flow_identifiers() -> list[str]:
    """Registered workflow ids, flow class names, and flow METHOD names.

    The method names are the node ids the frames carry, so `if frame.node_id ==
    "confirm_scope"` is the exact hardcoding row C1 forbids and the committed
    test has no extractor for.
    """

    found: set[str] = set()
    graph = (REPO / "src" / "brief_crew" / "service" / "graph.py").read_text(
        encoding="utf-8"
    )
    found.update(re.findall(r'^[A-Z_]*WORKFLOW_ID\s*=\s*"([^"]+)"', graph, re.M))
    for module in ("validator_flow.py", "main.py"):
        path = REPO / "src" / "brief_crew" / module
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                found.add(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    found.add(node.name)
    return sorted(v for v in found if len(v) >= 4)


def haystack() -> dict[str, str]:
    sources = {
        f"observability/{p.name}": p.read_text(encoding="utf-8")
        for p in sorted(PACKAGE.glob("*.py"))
    }
    from brief_crew.events import serializer

    sources["serializer.prompt_digest"] = inspect.getsource(serializer.prompt_digest)
    sources["serializer._unhandled_report"] = inspect.getsource(
        serializer.FieldBoundedSerializer._unhandled_report
    )
    sources["serializer.record_unhandled"] = inspect.getsource(
        serializer.FieldBoundedSerializer.record_unhandled
    )
    return sources


def main() -> int:
    groups: dict[str, list[str]] = {}
    groups.update(yaml_identifiers())
    groups["tool names and classes"] = tool_identifiers()
    groups["crew classes"] = crew_identifiers()
    groups["built-in skill packs"] = skill_identifiers()
    groups.update(builder_identifiers())
    groups["flow ids, classes and method (node) names"] = flow_identifiers()

    sources = haystack()
    total = sum(len(v) for v in groups.values())

    print("=" * 72)
    print("IDENTIFIERS EXTRACTED  (total %d, over %d groups)" % (total, len(groups)))
    print("=" * 72)
    for name, values in groups.items():
        print("\n-- %s (%d) --" % (name, len(values)))
        print(json.dumps(values, indent=1))

    print("\n" + "=" * 72)
    print("HAYSTACK: %d sources" % len(sources))
    for name in sources:
        print("   ", name, "(%d chars)" % len(sources[name]))
    print("=" * 72)

    hits: list[tuple[str, str, str, str]] = []
    for group, values in groups.items():
        for identifier in values:
            needle = identifier.lower()
            if len(needle) < 3:
                continue
            for name, source in sources.items():
                lowered = source.lower()
                start = lowered.find(needle)
                if start >= 0:
                    line_no = source.count("\n", 0, start) + 1
                    line = source.splitlines()[line_no - 1].strip()
                    hits.append((group, identifier, f"{name}:{line_no}", line[:150]))

    print("\nRAW HITS: %d" % len(hits))
    for group, identifier, where, line in hits:
        print(f"  [{group}] {identifier!r}\n      {where}  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
