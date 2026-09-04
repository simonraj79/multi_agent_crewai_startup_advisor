"""The PostgreSQL CI job must FAIL when it proves nothing - D-15-32.

`.github/workflows/ci.yml`'s `postgres` job is the only place the five
compare-and-set paths meet a second writer on the dialect production runs
(CLAUDE.md remaining-work item 3, plan 15 criterion 9). Judge round 3 measured
what it did when `TEST_DATABASE_URL` did not reach the process:

    Ran 5 tests in 0.000s
    OK (skipped=5)
    EXIT CODE: 0

A green check over nothing. The job's own comment already named the hazard -
"a skip here would mean TEST_DATABASE_URL did not reach the process" - and a
comment closes nothing, because nothing reads it.

Two guards now, and they catch different things: a shell step that fails when
the variable is empty, and `scripts/run_without_skips.py`, which fails on a
skip for ANY reason - a missing extra, a `skipUnless` added later, an import
guard. This module pins both: the shim's behaviour directly, and the workflow's
text, so a later edit that drops either one turns this red rather than turning
the job quietly green again.

It does NOT run the PostgreSQL suite, needs no database and no Docker, and is
never skipped - which is the property a test about skipping had better have.
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import unittest

from scripts.run_without_skips import run

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PG_MODULE = "tests.pg.test_two_writers"


#: Three deliberate outcomes, in a module `unittest discover` does NOT collect
#: (it is not `test_*.py`). They lived in this file for one run and that was
#: enough to show why they cannot: a `TestCase` carrying a deliberate failure
#: and a deliberate skip is collected by the ordinary suite as well, which then
#: reports one red and one skip that mean nothing.
SAMPLES = "tests.ci_guard_samples.Sample"


class ShimTests(unittest.TestCase):
    """`run()` returns the exit code the job needs, not the one unittest gives."""

    def _run(self, name: str) -> int:
        # verbosity 0 AND a throwaway stream: this module asserts an exit code,
        # and the sample suite's deliberate failure would otherwise print its
        # traceback - and its own "FAILED (failures=1)" - into the outer run.
        # Measured: the full suite reported one failure over a green tree
        # because of exactly that.
        return run([f"{SAMPLES}.{name}"], verbosity=0, stream=io.StringIO())

    def test_a_passing_test_is_zero(self) -> None:
        self.assertEqual(0, self._run("test_passes"))

    def test_a_SKIPPED_test_is_one_and_that_is_the_whole_point(self) -> None:
        """Plain `unittest` answers 0 here. That is the defect."""

        self.assertEqual(1, self._run("test_skips"))

    def test_a_failing_test_is_still_one(self) -> None:
        self.assertEqual(1, self._run("test_fails_on_purpose"))

    def test_a_run_with_no_tests_at_all_is_one(self) -> None:
        """An empty selection is not a pass; it is a job that ran nothing."""

        self.assertEqual(
            1, run([f"{SAMPLES}.no_such_test"], verbosity=0, stream=io.StringIO())
        )

    def test_no_arguments_is_a_usage_error(self) -> None:
        # stderr captured: the usage line is the behaviour under test, and
        # printing it into a green suite log reads as a real error.
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            code = run([])
        self.assertEqual(2, code)
        self.assertIn("usage:", captured.getvalue())


class WorkflowTests(unittest.TestCase):
    """The job's text, so the guard cannot be dropped without a red test."""

    @classmethod
    def setUpClass(cls) -> None:
        import yaml

        cls.workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        cls.job = cls.workflow["jobs"]["postgres"]
        cls.steps = cls.job["steps"]

    def test_the_job_still_runs_on_main_only(self) -> None:
        """PLANS.md decision 25, kept: the guard was the ask, not the trigger.

        A `pull_request` event runs at `refs/pull/N/merge` and a branch push at
        its own ref, so both skip this job and it runs once per merge.
        """

        self.assertEqual("github.ref == 'refs/heads/main'", self.job["if"])

    def test_the_service_still_sets_the_url_the_guard_checks(self) -> None:
        self.assertIn("TEST_DATABASE_URL", self.job["env"])
        self.assertIn("postgres:18", str(self.job["services"]["postgres"]["image"]))

    def test_a_step_fails_the_job_when_the_url_is_empty(self) -> None:
        guards = [
            step
            for step in self.steps
            if 'if [ -z "${TEST_DATABASE_URL}" ]' in str(step.get("run", ""))
            and "exit 1" in str(step.get("run", ""))
        ]
        self.assertEqual(
            1,
            len(guards),
            "the postgres job needs exactly one step that fails when "
            "TEST_DATABASE_URL is empty; without it the suite skips all five "
            "paths and the job reports success",
        )

    def test_the_suite_runs_through_the_fail_on_skip_shim(self) -> None:
        runners = [
            step
            for step in self.steps
            if PG_MODULE in str(step.get("run", ""))
        ]
        self.assertEqual(1, len(runners), "one step runs the two-writer suite")
        command = " ".join(str(runners[0]["run"]).split())
        self.assertIn("scripts/run_without_skips.py", command)
        self.assertNotIn(
            "-m unittest",
            command,
            "plain `python -m unittest` exits 0 over a suite it skipped "
            "entirely, which is the defect this shim exists to close",
        )

    def test_the_guard_runs_before_the_suite(self) -> None:
        """Order matters: the actionable sentence must come first.

        With the suite first, a misconfigured job fails on "5 tests were
        skipped" rather than on "TEST_DATABASE_URL is empty", and the second
        sentence is the one an operator can act on.
        """

        names = [str(step.get("run", "")) for step in self.steps]
        guard = next(
            index for index, run_ in enumerate(names) if "TEST_DATABASE_URL" in run_
        )
        suite = next(index for index, run_ in enumerate(names) if PG_MODULE in run_)
        self.assertLess(guard, suite)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
