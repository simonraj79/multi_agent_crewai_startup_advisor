"""Where exactly does the E3 probe's planted value sit? (V-REVIEW, 2026-09-06)

The probe reports a leak over the WHOLE payload, which is the right assertion
and the wrong diagnostic: an observation's dump includes its parent chain, so
one leaking field on the run span is reported once per descendant. This walks
the structure and prints the JSON PATH of every occurrence, with the parent
chain excluded so each field is named once.

Usage:  ./.venv/Scripts/python.exe docs/observability/evidence/tests/e3_leak_locator.py
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
import sys
from unittest import mock


REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from e3_planted_key_probe import (  # noqa: E402
    DSN,
    DSN_PASSWORD,
    KEY,
    IDEA,
    build_frames,
)
from tests.observability.replay import drive, exporter_for  # noqa: E402


def shallow(observation) -> dict:
    """One observation WITHOUT its parent chain."""

    out = {}
    for field in dataclasses.fields(observation):
        if field.name == "parent":
            parent = getattr(observation, "parent", None)
            out["parent_name"] = getattr(parent, "name", None)
            continue
        out[field.name] = getattr(observation, field.name)
    return out


def walk(value, path: str, needles: dict[str, str], hits: list[tuple[str, str]]) -> None:
    if isinstance(value, str):
        for label, needle in needles.items():
            if needle in value:
                hits.append((label, f"{path} = {value[:160]!r}"))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            walk(item, f"{path}.{key}", needles, hits)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            walk(item, f"{path}[{index}]", needles, hits)
        return
    if dataclasses.is_dataclass(value):
        walk(dataclasses.asdict(value), path, needles, hits)
        return
    if value is not None and not isinstance(value, (int, float, bool)):
        walk(str(value), path, needles, hits)


def main() -> int:
    needles = {"KEY": KEY, "DSN": DSN, "PW": DSN_PASSWORD, "IDEA": IDEA}
    from brief_crew.observability.content import credential_values_in_environment

    for capture in (False, True):
        with mock.patch.dict(os.environ, {"DATABASE_URL": DSN}, clear=False):
            secrets = credential_values_in_environment()
            exporter, backend = exporter_for(
                capture_content=capture, secret_values=secrets
            )
            recorder = build_frames()
            recorder.run_failed(
                f"ConnectionError: {DSN} refused, and the provider echoed {KEY}",
                error_class="ConnectionError",
            )
            drive(exporter, recorder.frames)

        hits: list[tuple[str, str]] = []
        for index, observation in enumerate(backend.observations):
            walk(
                shallow(observation),
                f"obs[{index}]({observation.as_type}:{observation.name})",
                needles,
                hits,
            )
        walk(list(backend.scores), "scores", needles, hits)
        walk(backend.trace_output, "trace_output", needles, hits)

        print("=" * 72)
        print(f"capture_content={int(capture)}   distinct leaking fields: {len(hits)}")
        print("=" * 72)
        for label, place in hits:
            print(f"  [{label}] {place}")
        if not hits:
            print("  none")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
