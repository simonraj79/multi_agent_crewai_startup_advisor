"""The four built-in packs, parsed by the PACKAGE - plan 08 criterion 10.

The point of the criterion is stated in its own wording: "so a CrewAI upgrade
that tightens the frontmatter fails a test rather than a run". That is only true
if the parser under test is CrewAI's, so every assertion here goes through
`crewai.skills.parser.parse_skill_md` and `SkillFrontmatter` rather than through
this repository's wrapper - and the files on disk are read, not a fixture.

**The licence field is `MIT`, and it is the repository's, not invented.** Until
2026-09-04 this file pinned the field ABSENT: PLANS.md decision 11 asks which
licence header these ship under, and with no `LICENSE` at the repo root that
was not answerable - inventing one would be inventing provenance. The pin was
written to fail the moment a `LICENSE` appeared, and it did, on the owner's MIT
choice (`e7dfb86`). `test_every_pack_carries_the_repository_licence` now pins
the answer the same way the old test pinned the question: the packs' header
must match the file at the root, so neither can drift from the other.

No cost: this reads four committed files.
"""

from __future__ import annotations

import pathlib
import unittest

from brief_crew import config as project_config
from brief_crew.builder.skills import BUILTIN_SKILL_IDS, builtin_root, load_builtins


class BuiltinPackTests(unittest.TestCase):
    def test_all_four_declared_names_exist_on_disk(self) -> None:
        for name in project_config.BUILTIN_SKILL_NAMES:
            with self.subTest(name=name):
                self.assertTrue(
                    (builtin_root() / name / "SKILL.md").is_file(),
                    f"{name} is declared in BUILTIN_SKILL_NAMES and is not committed",
                )

    def test_each_one_parses_under_the_packages_own_parser(self) -> None:
        from crewai.skills.parser import parse_skill_md

        for name in project_config.BUILTIN_SKILL_NAMES:
            with self.subTest(name=name):
                frontmatter, body = parse_skill_md(builtin_root() / name / "SKILL.md")
                self.assertEqual(frontmatter.name, name)
                self.assertTrue(body.strip(), "a pack with no body teaches nothing")

    def test_the_directory_name_is_the_skill_name_which_the_loader_requires(self) -> None:
        """`validate_directory_name` raises otherwise, and `discover_skills`
        swallows that into a warning - so the pack would be silently absent."""

        from crewai.skills.loader import load_skill_metadata

        for name in project_config.BUILTIN_SKILL_NAMES:
            with self.subTest(name=name):
                skill = load_skill_metadata(builtin_root() / name)
                self.assertEqual(skill.frontmatter.name, name)

    def test_the_committed_directory_is_a_legal_crewai_SEARCH_path(self) -> None:
        """The layout C11 specifies, checked against the loader that walks it.

        `discover_skills` iterates a search path's CHILDREN, so `builtin/` is
        the search path and each pack is a child. This asserts the layout rather
        than the runtime call - `loaded_skill` passes a `Skill` object, for the
        reason `builder/skills.py`'s docstring gives.
        """

        from crewai.skills.loader import discover_skills

        found = {skill.frontmatter.name for skill in discover_skills(builtin_root())}
        self.assertEqual(found, set(project_config.BUILTIN_SKILL_NAMES))

    def test_every_description_is_within_the_packages_own_ceiling(self) -> None:
        from crewai.skills.models import MAX_DESCRIPTION_LENGTH

        for pack in load_builtins():
            with self.subTest(name=pack.name):
                self.assertLessEqual(len(pack.description), MAX_DESCRIPTION_LENGTH)
                # A description tells an agent WHEN to activate the skill.
                # Without that clause the progressive disclosure has nothing to
                # decide on, so the pack loads at METADATA and never promotes.
                # `Use when` and `Use before` are the two forms these four take.
                self.assertRegex(pack.description, r"Use (when|before|whenever) ")

    def test_every_body_is_within_this_services_own_ceiling(self) -> None:
        for pack in load_builtins():
            with self.subTest(name=pack.name):
                self.assertLessEqual(pack.size_bytes, project_config.MAX_SKILL_BYTES)

    def test_every_pack_carries_the_repository_licence(self) -> None:
        """PLANS.md decision 11, answered 2026-09-04. See the module docstring."""

        from crewai.skills.parser import parse_skill_md

        repo = pathlib.Path(__file__).resolve().parents[2]
        licence = repo / "LICENSE"
        self.assertTrue(licence.is_file(), "the repository licence file is gone")
        self.assertIn(
            "MIT License",
            licence.read_text(encoding="utf-8").splitlines()[0],
            "LICENSE is no longer MIT; the four packs' `license:` field must move with it",
        )
        for name in project_config.BUILTIN_SKILL_NAMES:
            with self.subTest(name=name):
                frontmatter, _ = parse_skill_md(builtin_root() / name / "SKILL.md")
                self.assertEqual(frontmatter.license, "MIT")

    def test_the_ids_are_derived_and_therefore_stable_across_deployments(self) -> None:
        """A built-in has no row to remember an id, so a document naming one has
        to keep resolving after a redeploy."""

        first = [pack.id for pack in load_builtins()]
        second = [pack.id for pack in load_builtins()]
        self.assertEqual(first, second)
        self.assertEqual(set(first), set(BUILTIN_SKILL_IDS))
        for skill_id in first:
            self.assertRegex(skill_id, project_config.SKILL_ID_PATTERN)

    def test_they_are_distilled_from_prompts_this_repository_already_owns(self) -> None:
        """D3's provenance, as far as a test can carry it: each pack's subject
        appears in the validator's own YAML, so none of them is inventing a
        method this product does not already use."""

        packs = {pack.name: pack.body.lower() for pack in load_builtins()}
        self.assertIn("problem", packs["hn-signal-reading"])
        self.assertIn("off_topic", packs["hn-signal-reading"])
        self.assertIn("retrieval", packs["market-research-method"])
        self.assertIn("url", packs["evidence-citation"])
        self.assertIn("markdown", packs["report-writing"])


if __name__ == "__main__":
    unittest.main()
