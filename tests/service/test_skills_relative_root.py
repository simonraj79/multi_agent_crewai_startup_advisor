"""A user's skill body survives the round trip on the SHIPPED `SKILLS_ROOT`.

**This file exists because every other skill test is blind to the defect it
pins, and blind for one identical reason.** `test_skills_materialise.py:60`,
`test_skills_endpoint.py:95`, `test_skills_import.py:73` and
`test_skills_isolation.py:80` each patch `SKILLS_ROOT` to a `tempfile`
directory, and a `tempfile` directory is **absolute**. `SkillStore._pack` only
prefixed the root onto a path that was *not* absolute, so on all four the
prefixing branch never executed and the round trip was never tested at all.

The shipped default is `SKILLS_ROOT = "data/skills"` (`config.py`), which is
**relative** — and it is what production, a fresh checkout and the E2E backend
run on. There, `create` stored `data\\skills\\users\\<user>\\<name>\\SKILL.md`
and `_pack` read `data\\skills\\data\\skills\\users\\...`, whose `OSError` was
swallowed into `body = ""`. 2,420 green tests, and a user's content discarded on
every read.

So this file does the one thing the others cannot: it `chdir`s into a temporary
directory laid out like a checkout and leaves `SKILLS_ROOT` **at its relative
default**. The `RelativeRootTests` case fails on the pre-fix code with
`body length 0` and passes after.

No cost: in-memory SQLite, a temporary directory, no network and no model.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
import unittest
from unittest.mock import patch

from brief_crew import config as project_config
from brief_crew.builder import skills as skills_module
from brief_crew.service.attachments import SkillBodyUnreadable, SkillStore
from brief_crew.service.persistence import PostgresFlowPersistence, user_skills

BODY = """---
name: relative-root-probe
description: A method of mine. Use when testing the shipped root.
metadata:
  version: "1"
---

# My method

Do the thing carefully, and read it back with every byte still there.
"""


class _CheckoutShapedTempDir(unittest.TestCase):
    """A tempdir laid out like the repository, entered as the process cwd.

    The built-ins are copied rather than the root repointed, for the reason
    `test_skills_endpoint.py` already gives: repointing would make the built-in
    half of any assertion vacuous. Here it matters more, because leaving the
    root alone is the entire point of the file.
    """

    def setUp(self) -> None:
        super().setUp()
        source = skills_module.builtin_root().resolve()
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="skills-relative-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        root = self.tmp / project_config.SKILLS_ROOT
        root.mkdir(parents=True)
        if source.is_dir():
            shutil.copytree(source, root / "builtin")
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.tmp)
        self.store = PostgresFlowPersistence("sqlite://")
        self.skills = SkillStore(self.store)

    def stored_path(self) -> str:
        from sqlalchemy import select

        with self.store.connect() as connection:
            row = connection.execute(select(user_skills)).mappings().one()
        return str(row["path"])


class RelativeRootTests(_CheckoutShapedTempDir):
    def test_the_shipped_relative_root_reads_back_every_byte(self) -> None:
        created = self.skills.create("e2e-user", BODY)
        self.assertGreater(created.size_bytes, 0)

        fetched = self.skills.get("e2e-user", created.id)
        self.assertEqual(fetched.body, created.body)
        self.assertEqual(fetched.size_bytes, created.size_bytes)

        listed = [pack for pack in self.skills.list("e2e-user") if pack.id == created.id]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].body, created.body)

    def test_the_stored_path_is_already_rooted_and_is_not_prefixed_twice(self) -> None:
        """The measurement the defect was reported with, asserted directly."""

        created = self.skills.create("e2e-user", BODY)
        stored = self.stored_path()
        self.assertFalse(pathlib.Path(stored).is_absolute())
        self.assertTrue(
            skills_module._is_rooted(
                pathlib.Path(stored), skills_module.skills_root()
            ),
            f"{stored} should already begin with {skills_module.skills_root()}",
        )
        resolved = skills_module.resolve_stored_path(stored)
        self.assertTrue(resolved.exists(), f"{resolved} should be the file on disk")
        self.assertEqual(resolved, pathlib.Path(stored))
        self.assertEqual(created.body, resolved.read_text(encoding="utf-8"))

    def test_a_body_that_cannot_be_read_reports_instead_of_blanking(self) -> None:
        created = self.skills.create("e2e-user", BODY)
        pathlib.Path(self.stored_path()).unlink()
        with self.assertRaises(SkillBodyUnreadable) as caught:
            self.skills.get("e2e-user", created.id)
        self.assertIn("users", str(caught.exception))
        with self.assertRaises(SkillBodyUnreadable):
            self.skills.list("e2e-user")


class AbsoluteOverrideTests(_CheckoutShapedTempDir):
    """The same round trip with `SKILLS_ROOT` overridden to an absolute path.

    This is the arrangement the four existing skill tests run under, and it
    passed before the fix. It is asserted here so the fix cannot be a swap of
    one broken case for the other.
    """

    def test_an_absolute_root_still_reads_back_every_byte(self) -> None:
        absolute = self.tmp / "elsewhere"
        absolute.mkdir()
        with patch.object(project_config, "SKILLS_ROOT", str(absolute)):
            created = self.skills.create("e2e-user", BODY)
            stored = pathlib.Path(self.stored_path())
            self.assertTrue(stored.is_absolute())
            self.assertEqual(
                skills_module.resolve_stored_path(str(stored)), stored
            )
            self.assertEqual(self.skills.get("e2e-user", created.id).body, BODY)


class ResolveStoredPathTests(unittest.TestCase):
    """The rule itself, over the four shapes a row can hold."""

    def resolve(self, root: str, stored: str) -> str:
        with patch.object(project_config, "SKILLS_ROOT", root):
            return str(skills_module.resolve_stored_path(stored))

    def test_a_relative_row_already_inside_a_relative_root_is_left_alone(self) -> None:
        self.assertEqual(
            self.resolve("data/skills", os.path.join("data", "skills", "users", "u", "n", "SKILL.md")),
            os.path.join("data", "skills", "users", "u", "n", "SKILL.md"),
        )

    def test_a_relative_row_outside_a_relative_root_is_joined(self) -> None:
        self.assertEqual(
            self.resolve("data/skills", os.path.join("users", "u", "n", "SKILL.md")),
            os.path.join("data", "skills", "users", "u", "n", "SKILL.md"),
        )

    def test_a_relative_row_under_an_absolute_root_is_joined(self) -> None:
        root = os.path.abspath(os.path.join(os.sep, "srv", "skills"))
        self.assertEqual(
            self.resolve(root, os.path.join("users", "u", "n", "SKILL.md")),
            os.path.join(root, "users", "u", "n", "SKILL.md"),
        )

    def test_an_absolute_row_is_never_joined(self) -> None:
        absolute = os.path.abspath(os.path.join(os.sep, "srv", "skills", "users", "u", "n", "SKILL.md"))
        self.assertEqual(self.resolve("data/skills", absolute), absolute)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
