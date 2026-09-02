"""Tests for the builder document, its bounds and its static budget.

This file exists so `unittest discover` descends into the directory at all. A
test directory without an `__init__.py` is walked past in SILENCE and the run
reports a green OK over tests it never imported - the reason this project's
Python count sat at 65 for far longer than it should have.

The factories every module here shares live in `test_document.py`, which is the
convention the rest of the suite already uses (`tests/validator/test_flow.py`
exports `fixtures` and `FakeRunner` to five other modules).
"""
