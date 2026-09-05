"""V-REVIEW's INDEPENDENT C3 partition check (second pass, 2026-09-06).

Not a committed test. It enumerates CrewAI `BaseEvent` subclasses WITHOUT using
`mapping.crewai_event_classes()` - walking `crewai.events.types` and
`crewai.skills.events` from scratch - so the enumeration the exporter's own
table is compared against is not the exporter's own enumeration.

It then reports:

  * the independent count, and the count `mapping.crewai_event_classes()` gives
  * mapped (FRAME_PIPELINE_EVENTS) and unmapped (UNMAPPED_WITH_REASON) sizes
  * classes in NEITHER table (C3 fails if non-empty)
  * classes in BOTH tables (a class cannot be mapped and deliberately unmapped)
  * names in either table that CrewAI no longer declares (stale rows)
  * every FRAME_PIPELINE_EVENTS name that is NOT an `isinstance` branch in the
    frame serializer, checked against the AST rather than by substring
  * the reason string for every unmapped class, grouped, so a placeholder
    reason is visible rather than counted

Usage:  ./.venv/Scripts/python.exe docs/observability/evidence/tests/c3_partition_check.py
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
from collections import defaultdict
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))


def independent_enumeration() -> dict[str, str]:
    from crewai.events.base_events import BaseEvent
    import crewai.events.types as types_package

    found: dict[str, str] = {}

    def collect(module, label: str) -> None:
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseEvent)
                and obj is not BaseEvent
                and obj.__module__ == module.__name__
            ):
                found[name] = label

    for info in pkgutil.iter_modules(types_package.__path__):
        collect(importlib.import_module(f"crewai.events.types.{info.name}"), info.name)

    # Anything OUTSIDE crewai.events.types. Walked by import path, and the
    # search below reports what a broader walk finds, so a third module cannot
    # hide the way crewai.skills.events did.
    for path in ("crewai.skills.events",):
        try:
            collect(importlib.import_module(path), path.rsplit(".", 1)[-1])
        except Exception as exc:  # pragma: no cover
            print(f"  ! could not import {path}: {exc}")
    return found


def broader_sweep() -> dict[str, str]:
    """Every module under `crewai` whose FILE text declares a BaseEvent subclass.

    A text sweep rather than an import sweep: importing the whole package to
    answer a question about events is what `mapping.py` declines to do, and the
    point here is only to prove no THIRD module was missed.
    """

    import crewai

    root = Path(crewai.__file__).parent
    found: dict[str, str] = {}
    for path in root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                for base in node.bases
            }
            if bases & {"BaseEvent"}:
                found[node.name] = str(path.relative_to(root)).replace("\\", "/")
    return found


def serializer_isinstance_names() -> set[str]:
    source = (REPO / "src" / "brief_crew" / "events" / "serializer.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "isinstance"
            and len(node.args) == 2
        ):
            target = node.args[1]
            candidates = target.elts if isinstance(target, ast.Tuple) else [target]
            for item in candidates:
                if isinstance(item, ast.Name):
                    names.add(item.id)
                elif isinstance(item, ast.Attribute):
                    names.add(item.attr)
    return names


def main() -> int:
    from brief_crew.observability import mapping

    independent = independent_enumeration()
    theirs = dict(mapping.crewai_event_classes())
    mapped = set(mapping.FRAME_PIPELINE_EVENTS)
    unmapped = set(mapping.UNMAPPED_WITH_REASON)

    print("=" * 72)
    print("C3 PARTITION")
    print("=" * 72)
    print(f"independent enumeration          : {len(independent)}")
    print(f"mapping.crewai_event_classes()   : {len(theirs)}")
    print(f"  they agree                     : {set(independent) == set(theirs)}")
    print(f"FRAME_PIPELINE_EVENTS (mapped)   : {len(mapped)}")
    print(f"UNMAPPED_WITH_REASON (unmapped)  : {len(unmapped)}")
    print(f"mapped + unmapped                : {len(mapped) + len(unmapped)}")
    print(f"overlap (must be empty)          : {sorted(mapped & unmapped)}")
    print(f"in NEITHER table (must be empty) : {sorted(set(independent) - mapped - unmapped)}")
    print(f"stale mapped rows                : {sorted(mapped - set(independent))}")
    print(f"stale unmapped rows              : {sorted(unmapped - set(independent))}")

    sweep = broader_sweep()
    outside = {
        name: where
        for name, where in sweep.items()
        if name not in independent and not name.startswith("_")
    }
    print(f"\nbroader text sweep of the crewai package: {len(sweep)} declarations")
    print(f"  declared but OUTSIDE the enumeration   : {len(outside)}")
    for name, where in sorted(outside.items()):
        print(f"    {name}  ({where})")

    isinstance_names = serializer_isinstance_names()
    missing = sorted(mapped - isinstance_names)
    print(f"\nmapped names that are NOT an isinstance branch in serializer.py: {len(missing)}")
    for name in missing:
        print(f"    {name}")

    print("\n" + "=" * 72)
    print("UNMAPPED REASONS, grouped (spot-check for placeholders)")
    print("=" * 72)
    grouped: dict[str, list[str]] = defaultdict(list)
    for name in sorted(unmapped):
        grouped[mapping.UNMAPPED_WITH_REASON[name]].append(name)
    for reason, names in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        print(f"\n[{len(names)} classes] {reason}")
        print("    " + ", ".join(names))

    print("\n" + "=" * 72)
    print("unmapped_reason() for a class CrewAI has never declared:")
    print(f"    {mapping.unmapped_reason('AnEventNobodyHasWrittenYet', 'nowhere')!r}")
    print("(empty string = the fallback that made the row unfailable is gone)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
