"""Rubric 11: the same document compiles and runs to the same bytes. 20 of 20.

09 D9, criterion 10. Every fixture is compiled and run **twice in this process
and once in a fresh one**, and the definition, the frame sequence and the result
body are byte-equal to a committed golden all three ways.

**Why three legs and not one.** Each catches something the others cannot.

* Twice in one process catches state that survives a run - a module-level
  cache, a `ContextVar` not reset, a `_fired_or_listeners` set that makes the
  second kickoff of a cyclic graph differ from the first.
* A fresh process catches HASH ORDER. `PYTHONHASHSEED` is randomised per
  process unless pinned, so any `set` or `dict` iteration order reaching the
  emitted definition would differ there and nowhere else. The Integrator's
  pre-flight measured one digest across four seeds before this wave started, so
  the compile path is clean today; this is what says so tomorrow.
* Against a COMMITTED golden catches the thing neither of the above can: a
  change of behaviour that is perfectly reproducible and wrong.

**`compiled_at` is pinned, not stripped.** `budget.as_budget` defaults it to
`datetime.now(timezone.utc)` and it drifts between two calls a second apart, so
a golden carrying a budget could not be compared while that default applied.
`rubric11_harness.COMPILED_AT` fixes it. A normalisation step that dropped the
field would have been a field the test stopped checking.

**Line endings.** `core.autocrlf` is `true` here, so a raw byte comparison would
report the platform instead of the drift. `committed()` normalises first, which
keeps the comparison about content while staying exact about it.

No cost. Every billable node is built by `SyntheticCrewFactories`, the same
object `SYNTHETIC=1` installs; no model is called, no network is touched, and
the subprocess leg inherits the same environment.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO))

from tests.builder.rubric11_documents import FIXTURES, REPLAYS  # noqa: E402
from tests.builder.rubric11_harness import artefact, render  # noqa: E402

GOLDEN_DIR = REPO / "tests" / "builder" / "fixtures" / "rubric11"
REGENERATE = "./.venv/Scripts/python.exe scripts/emit_rubric11_goldens.py"
NAMES = [*FIXTURES, *REPLAYS]


def committed(name: str) -> str:
    """One golden, with line endings normalised. See the module docstring."""

    return (
        (GOLDEN_DIR / f"{name}.json")
        .read_text(encoding="utf-8")
        .replace("\r\n", "\n")
    )


def stale(name: str, leg: str) -> str:
    return (
        f"the rubric-11 golden for {name!r} does not match what this build "
        f"produces ({leg}). If the change is the one you meant to make, read the "
        f"diff and regenerate with:\n    {REGENERATE}"
    )


class FixtureSetTests(unittest.TestCase):
    """Twenty, and a golden for every one of them."""

    def test_there_are_twenty_fixtures(self) -> None:
        self.assertEqual(len(FIXTURES), 20, "rubric 11 is scored out of twenty")

    def test_every_fixture_and_replay_has_a_committed_golden(self) -> None:
        for name in NAMES:
            with self.subTest(fixture=name):
                self.assertTrue(
                    (GOLDEN_DIR / f"{name}.json").exists(),
                    f"no golden for {name}. Regenerate with:\n    {REGENERATE}",
                )

    def test_no_golden_is_orphaned(self) -> None:
        on_disk = sorted(path.stem for path in GOLDEN_DIR.glob("*.json"))
        self.assertEqual(on_disk, sorted(NAMES))

    def test_the_fixtures_cover_every_node_kind(self) -> None:
        """A fixture set that missed a kind would score 20/20 over nineteen."""

        from brief_crew.builder.document import NodeKind
        from typing import get_args

        seen = {
            node.kind
            for build in FIXTURES.values()
            for node in build().nodes
        }
        self.assertEqual(sorted(seen), sorted(get_args(NodeKind)))

    def test_the_fixtures_cover_both_families_of_both_billable_kinds(self) -> None:
        from brief_crew.builder.document import (
            AuthoredAgentConfig,
            AuthoredCrewConfig,
            LibraryAgentConfig,
            LibraryCrewConfig,
        )

        configs = [node.config for build in FIXTURES.values() for node in build().nodes]
        for arm in (
            LibraryAgentConfig,
            AuthoredAgentConfig,
            LibraryCrewConfig,
            AuthoredCrewConfig,
        ):
            with self.subTest(arm=arm.__name__):
                self.assertTrue(any(isinstance(config, arm) for config in configs))


class DeterminismTests(unittest.TestCase):
    """The three legs, per fixture."""

    def test_every_fixture_matches_its_golden_twice_in_this_process(self) -> None:
        for name in NAMES:
            with self.subTest(fixture=name):
                expected = committed(name)
                first = render(artefact(name))
                second = render(artefact(name))
                self.assertEqual(first, expected, stale(name, "first run"))
                self.assertEqual(second, expected, stale(name, "second run"))

    def test_the_definition_frames_and_result_are_all_three_compared(self) -> None:
        """A golden that carried only the definition would be a weaker claim.

        The definition is the compiler's answer; the frames are what an operator
        watches; the result is the deliverable. A change to any of the three
        without a change to the other two is exactly the kind that gets shipped.
        """

        for name in NAMES:
            with self.subTest(fixture=name):
                golden = json.loads(committed(name))
                self.assertEqual(
                    sorted(golden), ["budget", "definition", "frames", "result"]
                )
                self.assertTrue(golden["definition"]["methods"])
                self.assertTrue(golden["frames"])

    def test_the_budget_is_pinned_rather_than_stripped(self) -> None:
        from tests.builder.rubric11_harness import COMPILED_AT

        for name in NAMES:
            with self.subTest(fixture=name):
                golden = json.loads(committed(name))
                self.assertEqual(
                    golden["budget"]["compiled_at"],
                    COMPILED_AT.isoformat().replace("+00:00", "Z"),
                )


class SubprocessTests(unittest.TestCase):
    """The third leg: a fresh process, and so a fresh `PYTHONHASHSEED`."""

    #: Computed once for the whole class. What the third leg buys is a fresh
    #: `PYTHONHASHSEED`, and one fresh process buys it for every fixture at
    #: once - twenty-two interpreter starts cost two minutes of CrewAI imports
    #: and buy no additional guarantee.
    _fresh: dict[str, object] | None = None

    @classmethod
    def setUpClass(cls) -> None:
        from tests.builder.rubric11_harness import BEGIN

        completed = subprocess.run(
            [sys.executable, "-m", "tests.builder.rubric11_harness", "--all"],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=900,
        )
        if completed.returncode != 0:  # pragma: no cover - a broken harness
            raise AssertionError(
                "the rubric-11 harness failed in a fresh process: "
                + completed.stderr[-4000:]
            )
        # The flow engine prints its own panels to stdout and there is no way to
        # ask it not to, so the harness marks where its own output starts.
        text = completed.stdout.replace("\r\n", "\n")
        cls._fresh = json.loads(text.split(BEGIN + "\n", 1)[1])

    def test_every_fixture_matches_its_golden_in_a_fresh_process(self) -> None:
        assert self._fresh is not None
        for name in NAMES:
            with self.subTest(fixture=name):
                self.assertEqual(
                    render(self._fresh[name]),
                    committed(name),
                    stale(name, "subprocess"),
                )

    def test_the_fresh_process_really_produced_every_fixture(self) -> None:
        assert self._fresh is not None
        self.assertEqual(sorted(self._fresh), sorted(NAMES))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
