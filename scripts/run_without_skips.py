"""Run unittest modules and FAIL if any test was skipped - D-15-32.

A skip is unittest's way of saying "this did not run", and it exits 0. That is
right for a developer without Docker and wrong for the one job in
`.github/workflows/ci.yml` whose entire purpose is to run the five
compare-and-set paths against PostgreSQL. Measured:

    $ Remove-Item Env:\\TEST_DATABASE_URL
    $ python -m unittest tests.pg.test_two_writers -v
    Ran 5 tests in 0.000s
    OK (skipped=5)                                  exit code 0

Five skips, a green check, and nothing exercised. `ci.yml` already carried a
comment naming the hazard - "a skip here would mean TEST_DATABASE_URL did not
reach the process, and the log must say ok five times rather than skipped
once" - and a comment closes nothing.

Deliberately general rather than a `TEST_DATABASE_URL` check. That variable is
one reason a skip can happen and the job's guard step asserts it separately;
this catches the others - a missing extra, a `skipUnless` somebody adds later,
an import guard - none of which the variable check would see.

    python scripts/run_without_skips.py tests.pg.test_two_writers

Exit codes: 0 when every test ran and passed, 1 on a failure, an error, or on
any skip at all. The skipped tests and their reasons are printed, because
"something was skipped" is not an actionable sentence on its own.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from collections.abc import Sequence

# `python -m unittest` puts the working directory on `sys.path`; running a
# script does not - it puts the SCRIPT'S directory there instead. Without this
# the shim answers `ModuleNotFoundError: No module named 'tests.pg'` for the
# one module it exists to run, which is a failure, but the wrong one.
_REPO_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def run(
    module_names: Sequence[str],
    *,
    verbosity: int = 2,
    stream: object | None = None,
) -> int:
    """Run the named modules; return the process exit code.

    `stream` is where the inner runner writes. It defaults to `sys.stderr`,
    which is right for the CI job and wrong for `tests/test_ci_pg_guard.py`:
    that module calls this five times from INSIDE a suite, and a nested
    runner's own "FAILED (failures=1)" landing in the outer run's output is a
    red line nobody can attribute. Measured - the full suite read
    `FAILED (failures=1)` over a green run because of it.
    """

    if not module_names:
        print(
            "usage: python scripts/run_without_skips.py <module> [<module> ...]",
            file=sys.stderr,
        )
        return 2

    loader = unittest.TestLoader()
    suite = unittest.TestSuite(
        loader.loadTestsFromName(name) for name in module_names
    )
    runner = unittest.TextTestRunner(
        verbosity=verbosity, **({} if stream is None else {"stream": stream})
    )
    result = runner.run(suite)

    if result.skipped:
        print(
            f"\n{len(result.skipped)} test(s) were SKIPPED, and this runner "
            "treats a skip as a failure: a job that proves nothing must not "
            "report success.",
            file=sys.stderr,
        )
        for test, reason in result.skipped:
            print(f"  skipped: {test} - {reason}", file=sys.stderr)
        return 1
    if not result.wasSuccessful():
        return 1
    if result.testsRun == 0:
        print("\nno tests were run at all", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str]) -> int:
    return run(list(argv[1:]))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
