"""Attaching a pack at the step, and what its events say - plan 08 criteria 5, 7.

Criterion 5 is asserted at `bind_attachments`, which is where FD10 says the
dereferencing happens: a `skill` attachment carries an ID, and the pack it
names is looked up against the run's owner - built-ins passing for everyone -
materialised, and handed to `Agent.skills` as a typed `Skill`.

Criterion 7 asks for an AGENT frame carrying `details.skill` and
`details.disclosure`. `skill_frame_details` is that mapping and it is tested
here against REAL CrewAI event objects rather than dictionaries, because the
whole risk is that the package's field names are not what this repository
guessed. **Registering it on the event bus is not done here**: the sink is
`events/serializer.py`, which is C6 and belongs to plan 10, so this side is
written and proved and the wave that owns the sink calls it. Recorded as
partial in the plan's Status rather than claimed.

No cost: the store is stubbed and the packs are the committed built-ins.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from brief_crew.builder import runtime as runtime_module
from brief_crew.builder import skills as skills_module
from brief_crew.builder.skills import (
    BUILTIN_SKILL_IDS,
    SKILL_LOAD_ERROR_CLASS,
    load_builtins,
    skill_frame_details,
)


class BindSkillTests(unittest.TestCase):
    """Criterion 5, at the entrypoint."""

    def test_a_builtin_binds_for_a_run_with_no_store_at_all(self) -> None:
        """Built-ins are committed files with derived ids, so they resolve
        before any identity does - which is what makes a fresh account's
        palette usable and a `SYNTHETIC=1` instance able to run one."""

        with patch.object(runtime_module, "_attachment_store", lambda _n: (None, None)):
            bound = runtime_module.bind_attachments(
                [{"kind": "skill", "skill_id": BUILTIN_SKILL_IDS[1]}],
                node_id="n1_agent",
            )
        self.assertEqual(len(bound.skills), 1)
        self.assertEqual(bound.skills[0].frontmatter.name, "hn-signal-reading")

    def test_what_is_passed_is_a_Skill_and_never_a_str(self) -> None:
        """A bare string in `Agent.skills` is an AMP registry lookup, so this is
        the assertion that stops an author's pack name being sent to a
        marketplace."""

        from crewai.skills.models import METADATA, Skill

        with patch.object(runtime_module, "_attachment_store", lambda _n: (None, None)):
            bound = runtime_module.bind_attachments(
                [{"kind": "skill", "skill_id": BUILTIN_SKILL_IDS[0]}],
                node_id="n1_agent",
            )
        skill = bound.skills[0]
        self.assertIsInstance(skill, Skill)
        self.assertNotIsInstance(skill, str)
        self.assertEqual(skill.disclosure_level, METADATA)

    def test_it_loads_at_METADATA_so_the_body_costs_nothing_until_it_is_used(self) -> None:
        """The whole point of the primitive: the name and description are in
        the agent's context and the body is not."""

        with patch.object(runtime_module, "_attachment_store", lambda _n: (None, None)):
            bound = runtime_module.bind_attachments(
                [{"kind": "skill", "skill_id": BUILTIN_SKILL_IDS[3]}],
                node_id="n1_agent",
            )
        self.assertIsNone(bound.skills[0].instructions)

        from crewai.skills.loader import activate_skill
        from crewai.skills.models import INSTRUCTIONS

        activated = activate_skill(bound.skills[0])
        self.assertEqual(activated.disclosure_level, INSTRUCTIONS)
        self.assertIn("Markdown", activated.instructions or "")

    def test_a_users_own_pack_is_looked_up_for_the_RUNS_owner(self) -> None:
        pack = load_builtins()[0]
        mine = skills_module.SkillPack(
            id="sk_0123456789ab",
            name=pack.name,
            description=pack.description,
            version=1,
            body=pack.body,
            owner="me",
            user_id="user_alice",
        )

        class Store:
            @staticmethod
            def get(user_id: str, skill_id: str) -> Any:
                from brief_crew.service.attachments import AttachmentNotYours

                if user_id != "user_alice" or skill_id != mine.id:
                    raise AttachmentNotYours(skill_id)
                return mine

        with patch.object(
            runtime_module,
            "_attachment_store",
            lambda name: (Store(), "user_alice") if name == "SkillStore" else (None, None),
        ):
            bound = runtime_module.bind_attachments(
                [{"kind": "skill", "skill_id": mine.id}], node_id="n1_agent"
            )
        self.assertEqual(bound.skills[0].frontmatter.name, pack.name)

    def test_somebody_elses_pack_fails_the_node_with_a_sentence(self) -> None:
        class Store:
            @staticmethod
            def get(_user: str, skill_id: str) -> Any:
                from brief_crew.service.attachments import AttachmentNotYours

                raise AttachmentNotYours(skill_id)

        with patch.object(
            runtime_module,
            "_attachment_store",
            lambda name: (Store(), "user_alice") if name == "SkillStore" else (None, None),
        ):
            with self.assertRaises(runtime_module.BuilderRuntimeError) as caught:
                runtime_module.bind_attachments(
                    [{"kind": "skill", "skill_id": "sk_ffffffffffff"}], node_id="n1_agent"
                )
        self.assertIn("not one of yours", str(caught.exception))

    def test_several_attachments_of_different_kinds_keep_their_own_lanes(self) -> None:
        """A skill must not arrive in `tools` and a tool must not arrive in
        `skills`: `Agent` reads three different fields and mixing them is a
        silently different agent."""

        with patch.object(runtime_module, "_attachment_store", lambda _n: (None, None)):
            bound = runtime_module.bind_attachments(
                [
                    {"kind": "skill", "skill_id": BUILTIN_SKILL_IDS[0]},
                    {"kind": "tool", "tool_id": "scrape_website"},
                    {"kind": "skill", "skill_id": BUILTIN_SKILL_IDS[2]},
                ],
                node_id="n1_agent",
            )
        self.assertEqual(len(bound.skills), 2)
        self.assertEqual(len(bound.tools), 1)
        self.assertEqual(bound.mcps, ())
        # Author order is preserved: the tool list an agent reads is the order
        # the author drew, so two identical graphs produce identical prompts.
        self.assertEqual(
            [skill.frontmatter.name for skill in bound.skills],
            ["market-research-method", "evidence-citation"],
        )


class SkillFrameTests(unittest.TestCase):
    """Criterion 7's mapping, against the package's own event objects."""

    def test_an_activation_carries_the_name_and_the_disclosure_word(self) -> None:
        from crewai.events.types.skill_events import SkillActivatedEvent
        from crewai.skills.models import INSTRUCTIONS

        details = skill_frame_details(
            SkillActivatedEvent(
                skill_name="hn-signal-reading",
                skill_path="data/skills/builtin/hn-signal-reading",
                disclosure_level=INSTRUCTIONS,
            )
        )
        self.assertEqual(details["skill"], "hn-signal-reading")
        self.assertEqual(details["disclosure"], "instructions")

    def test_the_three_levels_map_to_the_three_words(self) -> None:
        from crewai.events.types.skill_events import SkillLoadedEvent
        from crewai.skills.models import INSTRUCTIONS, METADATA, RESOURCES

        for level, word in (
            (METADATA, "metadata"),
            (INSTRUCTIONS, "instructions"),
            (RESOURCES, "resources"),
        ):
            with self.subTest(level=level):
                details = skill_frame_details(
                    SkillLoadedEvent(skill_name="x", skill_path="y", disclosure_level=level)
                )
                self.assertEqual(details["disclosure"], word)

    def test_a_load_failure_carries_an_error_class_the_error_edge_can_route(self) -> None:
        from crewai.events.types.skill_events import SkillLoadFailedEvent

        details = skill_frame_details(
            SkillLoadFailedEvent(skill_name="gone", skill_path="p", error="no such file")
        )
        self.assertEqual(details["error_class"], SKILL_LOAD_ERROR_CLASS)
        self.assertIn("no such file", details["error"])

    def test_an_event_with_no_disclosure_level_omits_the_key_rather_than_guessing(self) -> None:
        from crewai.events.types.skill_events import SkillDiscoveryStartedEvent

        details = skill_frame_details(
            SkillDiscoveryStartedEvent(skill_name="", skill_path="", search_path="p")
        )
        self.assertNotIn("disclosure", details)

    def test_the_words_are_derived_from_the_packages_own_constants(self) -> None:
        """A fourth level appearing upstream must be a visible failure rather
        than a frame that silently says nothing."""

        from crewai.skills.models import INSTRUCTIONS, METADATA, RESOURCES

        self.assertEqual(sorted({METADATA, INSTRUCTIONS, RESOURCES}), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
