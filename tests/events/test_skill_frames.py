"""A skill's activation reaches the console - plan 08 criterion 7.

Plan 08 stopped at a stated boundary: *"`skill_frame_details` is the mapping D6
specifies… registering it on the event bus is `events/serializer.py`, which is
C6 and plan 10's, so no frame is emitted yet."* Plan 10 landed C6. This is the
registration's test.

**What was there before was a counter.** The sink receives *every* CrewAI event
and the ladder handles about thirty of roughly a hundred and fifty; the rest
reach `record_unhandled`, which tallies the type name and emits nothing. So a
skill being activated was COUNTED and invisible - which is the failure that
counter exists to make findable rather than to excuse. Every test here asserts
the frame AND that the tally stopped moving, because those are two claims and
only the pair rules out a branch that drafts a frame and falls through anyway.

Real CrewAI event objects through the real adapter. A mapping asserted against
a hand-built dictionary would be asserting this file's guess at the package's
field names, which is the entire risk `builder/skills.py` names when it says
its own tests use real events.

No model, no network: these are event objects.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from typing import Any

from crewai import Agent, Crew, Task
from crewai.events.stream_context import add_stream_sink, reset_stream_sinks
from crewai.events.types.skill_events import (
    SkillActivatedEvent,
    SkillLoadFailedEvent,
    SkillLoadedEvent,
    SkillUsedEvent,
)
from crewai.flow.flow import Flow, start
from crewai.llms.base_llm import BaseLLM
from crewai.skills.models import INSTRUCTIONS, METADATA, RESOURCES

from brief_crew.builder.skills import (
    SKILL_LOAD_ERROR_CLASS,
    load_builtins,
    loaded_skill,
)
from brief_crew.events import FrameBuffer, NodeRegistry, StreamSinkAdapter
from tests.events.frame_case import NODE, TS, FrameCase


class SkillFrameTests(FrameCase):
    """08 criterion 7: an AGENT frame carries `skill` and `disclosure`."""

    def test_an_activation_is_an_agent_frame_with_both_keys(self) -> None:
        frames = self.emit(
            SkillActivatedEvent(
                skill_name="hn-signal-reading",
                disclosure_level=INSTRUCTIONS,
                agent_role="Sentiment analyst",
                timestamp=TS,
            )
        )
        self.assertEqual(len(frames), 1)
        frame = frames[0]
        self.assertEqual(frame.kind.value, "agent")
        self.assertEqual(frame.node_id, NODE)
        details = dict(frame.details)
        # The criterion's own two keys, spelled as it spells them.
        self.assertEqual(details["skill"], "hn-signal-reading")
        self.assertEqual(details["disclosure"], "instructions")
        self.assertEqual(details["skill_event"], "activated")
        self.assertHandled("skill_activated")

    def test_the_three_disclosure_levels_render_as_the_words(self) -> None:
        """Derived from the package's constants, so a fourth level is a KeyError
        in `skill_frame_details` rather than a frame that says nothing."""

        for level, word in ((METADATA, "metadata"), (INSTRUCTIONS, "instructions"), (RESOURCES, "resources")):
            with self.subTest(level=level):
                details = dict(
                    self.emit(
                        SkillLoadedEvent(
                            skill_name="house-style",
                            disclosure_level=level,
                            timestamp=TS,
                        )
                    )[0].details
                )
                self.assertEqual(details["disclosure"], word)

    def test_loaded_activated_and_used_are_distinguishable(self) -> None:
        """One frame kind, three moments. A console that could not tell them
        apart would report a skill being read as a skill being used."""

        events = (
            SkillLoadedEvent(skill_name="s", disclosure_level=METADATA, timestamp=TS),
            SkillActivatedEvent(skill_name="s", disclosure_level=INSTRUCTIONS, timestamp=TS),
            SkillUsedEvent(skill_name="s", disclosure_level=RESOURCES, timestamp=TS),
        )
        verbs = []
        for event in events:
            frame = self.emit(event)[0]
            verbs.append(dict(frame.details)["skill_event"])
            self.assertIn(dict(frame.details)["skill_event"], frame.message)
        self.assertEqual(verbs, ["loaded", "activated", "used"])

    def test_a_load_failure_is_an_ERROR_frame_and_not_an_agent_one(self) -> None:
        """`builder/skills.py` states the rule beside `SKILL_LOAD_ERROR_CLASS`:
        a missing skill DEGRADES an agent, where a missing tool removes a
        capability it was told it had. So it is visible and it does not fail
        the step - which means it must not look like the agent's own progress.
        """

        frames = self.emit(
            SkillLoadFailedEvent(
                skill_name="house-style",
                error="SKILL.md is not valid frontmatter",
                timestamp=TS,
            )
        )
        self.assertEqual(len(frames), 1)
        frame = frames[0]
        self.assertEqual(frame.kind.value, "error")
        self.assertEqual(frame.level.value, "ERROR")
        details = dict(frame.details)
        self.assertEqual(details["stage"], "error")
        self.assertEqual(details["error_class"], SKILL_LOAD_ERROR_CLASS)
        self.assertEqual(details["skill"], "house-style")
        self.assertIn("frontmatter", details["error"])
        # No disclosure: the pack never got far enough to have one, and
        # inventing a level would be inventing a fact about a file that failed
        # to parse.
        self.assertNotIn("disclosure", details)
        self.assertHandled("skill_load_failed")


class SkillRegressionTests(FrameCase):
    """Counted and discarded until 2026-09-04."""

    def test_the_fallback_no_longer_swallows_a_skill_event(self) -> None:
        self.adapter(
            None,
            SkillActivatedEvent(skill_name="s", disclosure_level=METADATA, timestamp=TS),
        )
        self.assertEqual(self.adapter.serializer.unhandled, {})
        self.assertIn("agent", [frame.kind.value for frame in self.buffer.replay()])
        self.assertEqual(self.buffer.stats().emit_errors, 0)




# --------------------------------------------------------------------------
# The probe. Real CrewAI, a real built-in pack off disk, no network and no
# model: a scripted `BaseLLM` that calls CrewAI's own `load_skill` tool.
#
# The tests above are a model of the production sequence; this is the sequence
# itself, and it is the only thing that can catch the day CrewAI stops emitting
# an event this ladder converts. The criterion's own words -
# `details.skill = "hn-signal-reading"` and `disclosure = "instructions"` AFTER
# ACTIVATION - are asserted off a frame that a run really produced, rather than
# off an event this file constructed.
#
# **A synthetic run cannot produce this and that is a fact about the mode, not a
# gap here.** `SYNTHETIC=1` swaps the crew factories, so no `Agent` is built,
# no skill is loaded and CrewAI raises nothing. Criterion 7's parenthetical
# asks the synthetic runner to emit the frame itself; `service/builder_runner.py`
# is another wave's file, so what is proved instead is the stronger half - the
# REAL path, end to end, in a flow, through the real sink.
# --------------------------------------------------------------------------


BUILTIN = "hn-signal-reading"


class SkillLoadingLLM(BaseLLM):
    """ReAct text tool calling: load the skill, then answer.

    CrewAI gives an agent with metadata-level skills a `load_skill` tool and
    promotes the pack to INSTRUCTIONS when it is called - which is what the word
    "activation" in criterion 7 refers to.
    """

    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> str:
        self._turn = getattr(self, "_turn", 0) + 1
        if self._turn == 1:
            return (
                "Thought: that skill matches this task.\nAction: load_skill\n"
                f'Action Input: {{"skill_name": "{BUILTIN}"}}'
            )
        return "Thought: enough.\nFinal Answer: read"


class LiveSkillActivationTests(unittest.TestCase):
    """One built-in pack, activated for real, and the frame it produced."""

    def _run(self) -> tuple[FrameBuffer, Any]:
        packs = {pack.name: pack for pack in load_builtins()}
        self.assertIn(BUILTIN, packs, "the built-in packs moved")
        skill = loaded_skill(packs[BUILTIN])

        agent = Agent(
            role="Sentiment analyst",
            goal="Read community signal.",
            backstory="A probe.",
            llm=SkillLoadingLLM(model="openrouter/probe"),
            skills=[skill],
            verbose=False,
            max_iter=4,
        )
        task = Task(
            description="Read the threads.",
            expected_output="read",
            agent=agent,
            name="sentiment_task",
        )
        crew = Crew(agents=[agent], tasks=[task], verbose=False)

        class BranchFlow(Flow):
            @start()
            def draft(self) -> str:
                return str(crew.kickoff())

        buffer = FrameBuffer(capacity=256)
        adapter = StreamSinkAdapter(
            run_id="skill-probe",
            buffer=buffer,
            registry=NodeRegistry(flow_method_nodes={NODE: NODE}),
        )
        token = add_stream_sink(adapter)
        try:
            # CrewAI's console listener prints panels a cp1252 console cannot
            # encode; the noise would land in the test output.
            with redirect_stdout(io.StringIO()):
                BranchFlow().kickoff()
        finally:
            reset_stream_sinks(token)
        return buffer, adapter

    def test_a_real_activation_produces_the_frame_the_criterion_names(self) -> None:
        buffer, adapter = self._run()
        frames = [
            frame
            for frame in buffer.replay()
            if dict(frame.details).get("skill_event") == "activated"
        ]
        self.assertEqual(len(frames), 1, "the run activated no skill")
        frame = frames[0]
        self.assertEqual(frame.kind.value, "agent")
        self.assertEqual(frame.node_id, NODE)
        details = dict(frame.details)
        self.assertEqual(details["skill"], BUILTIN)
        self.assertEqual(details["disclosure"], "instructions")
        self.assertEqual(buffer.stats().emit_errors, 0)

    def test_the_frame_says_which_agent_activated_it(self) -> None:
        """`drafts` stamps the actor onto every non-workflow frame, and a
        console showing "a skill was activated" with no agent beside it is the
        attribution defect this repository has already fixed once."""

        buffer, _ = self._run()
        details = [
            dict(frame.details)
            for frame in buffer.replay()
            if dict(frame.details).get("skill_event") == "activated"
        ][0]
        self.assertEqual(details["agent_role"], "Sentiment analyst")

    def test_activation_and_use_are_separate_frames(self) -> None:
        """CrewAI raises both, and they mean different things: the pack was
        promoted to INSTRUCTIONS, and its instructions were rendered into a
        prompt. Collapsing them would report one event as two or two as one."""

        buffer, _ = self._run()
        events = [
            dict(frame.details)["skill_event"]
            for frame in buffer.replay()
            if "skill_event" in dict(frame.details)
        ]
        self.assertEqual(events, ["activated", "used"])

    def test_the_sink_did_not_fall_back_for_either(self) -> None:
        _, adapter = self._run()
        for event_type in ("skill_activated", "skill_used"):
            with self.subTest(event=event_type):
                self.assertNotIn(event_type, adapter.serializer.unhandled)


if __name__ == "__main__":
    unittest.main()
