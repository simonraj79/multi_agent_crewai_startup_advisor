"""Three deliberate outcomes for `tests/test_ci_pg_guard.py` to run BY NAME.

Not `test_*.py`, so `unittest discover` never collects it. That is the whole
reason it is a separate module: a `TestCase` with a deliberate failure and a
deliberate skip sitting in a discovered file is collected by the ordinary run
too, and the suite reports one red and one skip that mean nothing.
"""

from __future__ import annotations

import unittest


class Sample(unittest.TestCase):
    def test_passes(self) -> None:
        self.assertTrue(True)

    @unittest.skip("deliberately skipped, so the shim's exit code can be asserted")
    def test_skips(self) -> None:  # pragma: no cover - never runs, by design
        raise AssertionError("a skipped test must not execute")

    def test_fails_on_purpose(self) -> None:
        self.fail("deliberate")
