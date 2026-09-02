"""Tests that need a real PostgreSQL and are skipped without one.

This file exists so `unittest discover` walks into the directory at all -
gotcha 20: a test directory without an `__init__.py` is skipped in silence
and reported as a green `OK` over tests that never ran.
"""
