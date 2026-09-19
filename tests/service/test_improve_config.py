"""Plan 21's constants, its one knob, and the ceiling checked at import.

Two questions, and the second is the interesting one:

* **Twelve plain constants and exactly ONE environment knob.** The split is
  the whole design of that block: eleven of the twelve bound a shape and
  cannot be raised back to the defect by an operator, and the one knob governs
  the one thing that spends money. A second knob would also move a documented
  count (`docs/tech-stack.md` section 6 is generated from the canonical scan),
  so this is checked by RUNNING that scan rather than by reading the file.
* **R9: the ceiling DISABLES rather than raises.** `worst_case_digest_cost()`
  is under `DIGEST_MAX_COST_USD` today, and patching `PRICES` upward makes
  `_assert_digest_cost_ceiling()` turn the feature off and log an ERROR - it
  does NOT raise, because `config.py` is imported by every test module, every
  console script and the ASGI factory, and a raise here would take the whole
  product down over a feature that is off by default. A ceiling that cannot be
  made to fail is a comment, not a check; a ceiling that fails by making the
  package unimportable is a different defect with the same good intentions.
"""

from __future__ import annotations

import pathlib
import re
import unittest
from unittest.mock import patch

from brief_crew import config


#: The twelve. Named here rather than derived, because "twelve constants" is
#: the claim and a derivation would agree with whatever the file happened to
#: hold. `MAX_RATING_NOTE_CHARS` is plan 20's and is listed because the same
#: no-environment-override property is being asserted over it.
PLAIN_CONSTANTS = (
    "IMPROVE_MIN_RUNS",
    "IMPROVE_MIN_COMPARE_RUNS",
    "DIGEST_MAX_SAMPLE_RUNS",
    "DIGEST_MAX_SAMPLE_FRAMES",
    "DIGEST_MAX_INPUT_CHARS",
    "DIGEST_MAX_OUTPUT_TOKENS",
    "DIGEST_MAX_COST_USD",
    "EVALSET_MAX_RUNS",
    "EVALSET_MAX_RESULT_CHARS",
    "EVALSET_MAX_BYTES",
    "MAX_TASK_TOOL_FAILURES",
    "MAX_RATING_NOTE_CHARS",
)

#: The canonical scan from CLAUDE.md, run over the two files that read the
#: environment. Multiline, never line-anchored - a line-anchored grep is
#: gotcha 6, and it under-reported this file by four for months.
_KNOB = re.compile(
    r'(?:os\.getenv|os\.environ\.get|_env_[a-z_]+)\(\s*"([A-Z_][A-Z0-9_]*)"', re.S
)


def scanned_knobs() -> set[str]:
    root = pathlib.Path(config.__file__).resolve().parent
    names: set[str] = set()
    for name in ("config.py", "service/app.py"):
        names.update(_KNOB.findall((root / name).read_text(encoding="utf-8")))
    return names


class ConstantsTests(unittest.TestCase):
    def test_the_twelve_constants_are_present_and_plain(self) -> None:
        for name in PLAIN_CONSTANTS:
            with self.subTest(name=name):
                self.assertTrue(hasattr(config, name), f"{name} is missing")
                self.assertIsInstance(getattr(config, name), (int, float))

    def test_the_values_are_the_plans(self) -> None:
        """The plan's own numbers, to the digit.

        Pinned because every one of them is a bound somebody reads off the
        screen - "up to $0.05", "needs 5 runs" - and a value drifting from
        the plan would make the panel's own sentences wrong.
        """

        self.assertEqual(5, config.IMPROVE_MIN_RUNS)
        self.assertEqual(5, config.IMPROVE_MIN_COMPARE_RUNS)
        self.assertEqual(12, config.DIGEST_MAX_SAMPLE_RUNS)
        self.assertEqual(400, config.DIGEST_MAX_SAMPLE_FRAMES)
        self.assertEqual(40_000, config.DIGEST_MAX_INPUT_CHARS)
        self.assertEqual(1_200, config.DIGEST_MAX_OUTPUT_TOKENS)
        self.assertEqual(0.05, config.DIGEST_MAX_COST_USD)
        self.assertEqual(2000, config.EVALSET_MAX_RUNS)
        self.assertEqual(2000, config.EVALSET_MAX_RESULT_CHARS)
        self.assertEqual(8 * 1024 * 1024, config.EVALSET_MAX_BYTES)
        self.assertEqual(8, config.MAX_TASK_TOOL_FAILURES)
        self.assertEqual(500, config.MAX_RATING_NOTE_CHARS)


class OneKnobTests(unittest.TestCase):
    def test_the_knob_defaults_off(self) -> None:
        """Read from the source, not from this process's environment.

        A developer with `IMPROVE_DIGEST_ENABLED=1` in a shell would otherwise
        make this pass or fail for a reason that has nothing to do with the
        default - item 63's failure, which cost this repository a red CI for
        seven commits.
        """

        source = pathlib.Path(config.__file__).read_text(encoding="utf-8")
        self.assertIn(
            'IMPROVE_DIGEST_ENABLED = _env_flag("IMPROVE_DIGEST_ENABLED", False)',
            source,
        )

    def test_digest_enabled_reads_the_global_at_call_time(self) -> None:
        """So one `patch.object` is enough, and no caller holds a copy."""

        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True):
            self.assertTrue(config.digest_enabled())
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", False):
            self.assertFalse(config.digest_enabled())

    def test_the_scan_finds_exactly_one_knob_from_this_plan(self) -> None:
        """The real content: this plan adds ONE name to the canonical scan.

        The scan is the contract - `docs/tech-stack.md` section 6 is generated
        from it and `tests/test_env_knob_doc.py` asserts the two agree - so a
        second knob here would move a documented count as a side effect. This
        checks the shape of the addition rather than the total, because the
        total is a documentation row and moves for reasons that are not this
        plan's.
        """

        knobs = scanned_knobs()
        self.assertIn("IMPROVE_DIGEST_ENABLED", knobs)
        plan_21_shaped = {
            name
            for name in knobs
            if name.startswith(("IMPROVE_", "DIGEST_", "EVALSET_"))
        }
        self.assertEqual({"IMPROVE_DIGEST_ENABLED"}, plan_21_shaped)

    def test_the_other_twelve_are_not_environment_readable(self) -> None:
        """Eleven bounds and a price ceiling, none raisable by a shell."""

        knobs = scanned_knobs()
        for name in PLAIN_CONSTANTS:
            with self.subTest(name=name):
                self.assertNotIn(name, knobs)


class DigestCeilingTests(unittest.TestCase):
    """The ceiling holds, it can be made to fire, and firing is not a raise."""

    def test_the_worst_case_is_under_the_ceiling(self) -> None:
        worst = config.worst_case_digest_cost()
        self.assertLessEqual(worst, config.DIGEST_MAX_COST_USD)
        # And it is a real number rather than a zero standing in for "no price
        # on file", which is the defect that once priced 128,069 tokens at $0.
        self.assertGreater(worst, 0.0)

    def test_the_arithmetic_is_the_plans(self) -> None:
        """Prompt tokens are `DIGEST_MAX_INPUT_CHARS / 4`, plus the max output.

        Recomputed here from the two constants rather than compared to a
        figure typed into this file: a number in a test is as stale as a
        number in prose.
        """

        base = config.compute_cost_usd(
            config.CHEAP_MODEL,
            config.DIGEST_MAX_INPUT_CHARS // 4,
            config.DIGEST_MAX_OUTPUT_TOKENS,
        )
        self.assertIsNotNone(base)
        self.assertGreaterEqual(config.worst_case_digest_cost(), base)

    def test_patching_prices_upward_disables_rather_than_raising(self) -> None:
        """R9, and the check that proves the check.

        The ceiling must be able to FIRE - a ceiling that cannot is prose -
        and firing must not make `config` unimportable. So the observable
        effect is the flag: on before, forced off after, with one ERROR
        naming the model and the figure.
        """

        dearer = dict(config.PRICES)
        dearer[config.CHEAP_MODEL] = (900.0, 900.0)
        with patch.object(config, "PRICES", dearer), patch.object(
            config, "_PRICE_INDEX", None, create=True
        ), patch.object(config, "IMPROVE_DIGEST_ENABLED", True):
            with self.assertLogs(config.__name__, level="ERROR") as logs:
                config._assert_digest_cost_ceiling()
            self.assertFalse(config.digest_enabled())
        blob = "\n".join(logs.output)
        self.assertIn("DIGEST_MAX_COST_USD", blob)
        self.assertIn(config.CHEAP_MODEL, blob)

    def test_an_unpriceable_model_disables_rather_than_costing_nothing(
        self,
    ) -> None:
        """`None` from `compute_cost_usd` is "no price on file", never free.

        `worst_case_digest_cost` RAISES on it, because a ceiling that
        cannot be proved must not be reported as proved; the caller catches
        that and turns the feature off, for R9's reason.
        """

        with patch.object(config, "compute_cost_usd", lambda *_a, **_k: None):
            with self.assertRaises(RuntimeError) as caught:
                config.worst_case_digest_cost()
            self.assertIn("not in PRICES", str(caught.exception))
            with patch.object(config, "IMPROVE_DIGEST_ENABLED", True):
                with self.assertLogs(config.__name__, level="ERROR"):
                    config._assert_digest_cost_ceiling()
                self.assertFalse(config.digest_enabled())

    def test_importing_the_module_is_what_runs_it(self) -> None:
        """The call is at module level, so a broken cap is loud at import
        rather than at the click - which is the whole point of doing the
        arithmetic ahead of time."""

        source = pathlib.Path(config.__file__).read_text(encoding="utf-8")
        self.assertIn("\n_assert_digest_cost_ceiling()\n", source)

    def test_the_flag_survives_a_ceiling_that_holds(self) -> None:
        """The control: a check that disabled unconditionally would pass
        every assertion above and turn the feature off for everybody."""

        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True):
            config._assert_digest_cost_ceiling()
            self.assertTrue(config.digest_enabled())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
