"""Regenerate the rubric-11 goldens - 09 D9, criterion 10.

    ./.venv/Scripts/python.exe scripts/emit_rubric11_goldens.py

Writes one file per fixture into `tests/builder/fixtures/rubric11/`, each the
compiled definition, the frame sequence, the result body and the pinned budget.
`test_rubric11.py` regenerates the same thing three ways - twice in this process
and once in a fresh one - and byte-compares.

Run this ONLY when a golden's change is the thing you meant to make, and read
the diff before committing it. A golden regenerated to make a test pass is a
test that has stopped checking anything, which is the failure the whole of this
plan set's determinism work exists to prevent.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO))

from tests.builder.rubric11_documents import FIXTURES, REPLAYS  # noqa: E402
from tests.builder.rubric11_harness import artefact, render  # noqa: E402

GOLDEN_DIR = REPO / "tests" / "builder" / "fixtures" / "rubric11"


def names() -> list[str]:
    return [*FIXTURES, *REPLAYS]


def main() -> int:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name in names():
        path = GOLDEN_DIR / f"{name}.json"
        path.write_text(render(artefact(name)), encoding="utf-8")
        print(f"wrote {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
