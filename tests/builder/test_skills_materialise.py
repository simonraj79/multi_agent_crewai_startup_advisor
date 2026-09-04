"""Parsing, materialising and attaching a pack - plan 08 criteria 4 and 5.

Criterion 4 asks that `materialise` write the file once, return the same `Path`
on a second call, and rewrite after a `PUT`. The freshness test here is CONTENT
rather than a timestamp, and that is a decision rather than a shortcut: this
runs on Windows locally and Linux in production, and comparing an mtime against
a database `updated_at` reports the two clocks rather than the file. Reading
64 KiB to decide whether to write 64 KiB is not a cost worth a wrong answer.

**Criterion 5 is where the plan and the package part company**, and the
departure is asserted here rather than argued. The criterion says
`Agent(skills=[Path])` and `load_skill` on that path returns a `Skill` at
METADATA. Measured: `load_skill` treats a `Path` as a SEARCH path and
`discover_skills` iterates its children, so the pack's own directory answers
`[]` and its parent answers every sibling pack. `loaded_skill` therefore passes
a `Skill` object - which `Agent.skills` also accepts, which is still not a
`str`, and which names exactly the one pack the author attached. Both halves are
asserted: the empty answer that motivated the change, and the `Skill` at
METADATA that `activate_skill` promotes.

No cost: this writes to a temporary directory.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest.mock import patch

from brief_crew import config as project_config
from brief_crew.builder import skills as skills_module
from brief_crew.builder.skills import (
    SkillError,
    SkillPack,
    bumped,
    loaded_skill,
    materialise,
    pack_directory,
    parse_pack,
    search_path,
)

BODY = """---
name: my-method
description: A method of mine. Use when testing.
metadata:
  version: "1"
---

# My method

Do the thing carefully.
"""


class TemporaryRootCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="skills-"))
        patcher = patch.object(project_config, "SKILLS_ROOT", str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)

    def pack(self, body: str = BODY, **overrides) -> SkillPack:
        parsed = parse_pack(body, skill_id="sk_0123456789ab", owner="me")
        return SkillPack(
            id=parsed.id,
            name=parsed.name,
            description=parsed.description,
            version=parsed.version,
            body=parsed.body,
            owner="me",
            user_id="user_alice",
            **overrides,
        )


class ParseTests(unittest.TestCase):
    def test_it_reads_the_frontmatter_the_package_reads(self) -> None:
        pack = parse_pack(BODY)
        self.assertEqual(pack.name, "my-method")
        self.assertEqual(pack.description, "A method of mine. Use when testing.")
        self.assertEqual(pack.version, 1)

    def test_a_bad_name_is_refused_with_the_PACKAGES_own_sentence(self) -> None:
        """Criterion 2's half that lives here: there is no second validator.

        The message names the pattern, and the pattern is CrewAI's - so a pack
        this service accepts is exactly a pack the package will load, and there
        is no wording of ours to drift away from theirs.
        """

        bad = BODY.replace("name: my-method", 'name: "Bad Name"')
        with self.assertRaises(SkillError) as caught:
            parse_pack(bad)
        self.assertIn("pattern", str(caught.exception))

    def test_a_missing_frontmatter_delimiter_is_the_parsers_own_message(self) -> None:
        with self.assertRaises(SkillError) as caught:
            parse_pack("# just a heading\n")
        self.assertIn("frontmatter", str(caught.exception))

    def test_a_body_over_the_ceiling_is_refused_before_anything_is_written(self) -> None:
        """64 KiB is `persistence.MAX_STRING_LENGTH`, whose `_sanitize_json`
        RAISES rather than truncates - so a larger cap loses the row."""

        huge = BODY + ("x" * project_config.MAX_SKILL_BYTES)
        with self.assertRaises(SkillError) as caught:
            parse_pack(huge)
        self.assertIn(str(project_config.MAX_SKILL_BYTES), str(caught.exception))

    def test_version_defaults_to_one_and_is_read_from_the_metadata(self) -> None:
        self.assertEqual(parse_pack(BODY.replace('version: "1"', 'version: "7"')).version, 7)
        without = BODY.replace('metadata:\n  version: "1"\n', "")
        self.assertEqual(parse_pack(without).version, 1)

    def test_bumped_increments_the_frontmatter_and_still_parses(self) -> None:
        once = bumped(BODY)
        self.assertEqual(parse_pack(once).version, 2)
        self.assertEqual(parse_pack(bumped(once)).version, 3)
        self.assertIn("Do the thing carefully.", once)

    def test_bumped_adds_a_metadata_block_when_there_is_none(self) -> None:
        without = BODY.replace('metadata:\n  version: "1"\n', "")
        self.assertEqual(parse_pack(bumped(without)).version, 2)


class MaterialiseTests(TemporaryRootCase):
    """Criterion 4."""

    def test_it_writes_the_file_once_and_returns_the_same_path(self) -> None:
        pack = self.pack()
        first = materialise(pack)
        written = (first / "SKILL.md").read_text(encoding="utf-8")
        stamp = (first / "SKILL.md").stat().st_mtime_ns

        second = materialise(pack)
        self.assertEqual(first, second)
        self.assertEqual((second / "SKILL.md").read_text(encoding="utf-8"), written)
        self.assertEqual((second / "SKILL.md").stat().st_mtime_ns, stamp)

    def test_it_rewrites_after_an_edit(self) -> None:
        pack = self.pack()
        directory = materialise(pack)
        edited = self.pack(bumped(BODY).replace("carefully", "twice as carefully"))
        materialise(edited)
        self.assertIn(
            "twice as carefully", (directory / "SKILL.md").read_text(encoding="utf-8")
        )

    def test_it_repairs_a_file_a_restart_removed(self) -> None:
        """The disk is a cache. On Render it empties, and the first run that
        attaches the skill writes it again - `builder_rehydrate`'s lesson
        applied by construction rather than by a boot sweep."""

        pack = self.pack()
        directory = materialise(pack)
        (directory / "SKILL.md").unlink()
        self.assertTrue((materialise(pack) / "SKILL.md").is_file())

    def test_a_users_pack_and_a_builtin_land_in_different_places(self) -> None:
        mine = pack_directory(self.pack())
        builtin = pack_directory(
            SkillPack(id="sk_x", name="my-method", description="d", version=1, body=BODY)
        )
        self.assertNotEqual(mine, builtin)
        self.assertIn("users", str(mine))
        self.assertIn("builtin", str(builtin))

    def test_a_user_id_that_is_not_a_legal_path_segment_is_made_into_one(self) -> None:
        """Ids are opaque and can hold anything, including a separator."""

        pack = self.pack()
        awkward = SkillPack(
            id=pack.id,
            name=pack.name,
            description=pack.description,
            version=pack.version,
            body=pack.body,
            owner="me",
            user_id="../../etc/passwd",
        )
        directory = pack_directory(awkward)
        self.assertNotIn("..", directory.parts)
        self.assertTrue(str(directory).startswith(str(self.root)))


class AttachmentTests(TemporaryRootCase):
    """Criterion 5, and the measured reason it is a `Skill` and not a `Path`."""

    def test_a_pack_directory_is_NOT_what_load_skill_walks(self) -> None:
        """The measurement that changed the design, kept so it is not re-argued."""

        from crewai.skills.loader import load_skill

        directory = materialise(self.pack())
        self.assertEqual(load_skill(directory, activate=False), [])
        self.assertEqual(
            [skill.frontmatter.name for skill in load_skill(search_path(self.pack()), activate=False)],
            ["my-method"],
        )

    def test_loaded_skill_is_a_Skill_at_METADATA_naming_exactly_this_pack(self) -> None:
        from crewai.skills.models import METADATA, Skill

        skill = loaded_skill(self.pack())
        self.assertIsInstance(skill, Skill)
        self.assertNotIsInstance(skill, str)
        self.assertEqual(skill.frontmatter.name, "my-method")
        self.assertEqual(skill.disclosure_level, METADATA)
        self.assertIsNone(skill.instructions)

    def test_activating_it_promotes_to_INSTRUCTIONS_with_the_body(self) -> None:
        """The mechanism the whole plan exists to expose, and it is the
        package's - so a CrewAI upgrade that improves it improves the product."""

        from crewai.skills.loader import activate_skill
        from crewai.skills.models import INSTRUCTIONS

        activated = activate_skill(loaded_skill(self.pack()))
        self.assertEqual(activated.disclosure_level, INSTRUCTIONS)
        self.assertIn("Do the thing carefully.", activated.instructions or "")

    def test_two_packs_of_one_user_do_not_load_each_other(self) -> None:
        """A `Skill` object names one pack. A search path would name both, which
        is the reason this is not a `Path`."""

        other = BODY.replace("name: my-method", "name: other-method")
        materialise(self.pack())
        second = self.pack(other)
        self.assertEqual(loaded_skill(second).frontmatter.name, "other-method")
        self.assertEqual(loaded_skill(self.pack()).frontmatter.name, "my-method")


if __name__ == "__main__":
    unittest.main()
