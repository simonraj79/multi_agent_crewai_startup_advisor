"""A streaming crew is DRAINED, or the graph runs nothing - found by a paid run.

This module exists because of one measured failure, and the failure is worth
stating in full because nothing in a 2,441-test suite could see it.

Every authored crew carries `Crew(stream=True)` - plan 10 D7, `runtime.py:677`
and `:763` - so that the dialogue rail has per-token `LLMStreamChunkEvent`s to
render instead of one block of text at the end. CrewAI answers `stream=True`
with a **lazy** `CrewStreamingOutput`: a generator wrapping a worker thread that
has not been started (`crewai/crew.py::kickoff`, verified at 1.15.18). Nothing
runs until somebody iterates it.

Nobody did. On 2026-09-05 the first paid run of a builder graph
(`c5df456d-27e0-4e91-9309-e232aceaa5d2`, `news-to-social`) reported
**`completed` in 1.5 seconds** with `cost_usd 0.0`, zero tokens, zero
`successful_requests`, a terminal `WORKFLOW_END`, and this as the deliverable:

    <crewai.types.streaming.CrewStreamingOutput object at 0x0000026581AAC050>

Each node handed that same string to the next node as its prompt input. The run
was green, terminal and non-empty - which is exactly what the template E2E
asserts - and no model had been called.

**Why the doubles could not catch it, and why this file uses the real class.**
Every unit double in this repository returns a string or a `CrewOutput` from a
stubbed `kickoff`, and the synthetic runner never builds a `Crew` at all. The
one shape that breaks is the one shape no double constructs. So the crew below
is a stub but its return value is the genuine `CrewStreamingOutput`, driven the
way CrewAI drives it: a generator that does the work and publishes the result,
and a `.result` property that raises until the generator has been exhausted. A
test that stubbed the streaming class too would pass against the bug.

No cost: no model, no network, no credential.
"""

from __future__ import annotations

import pathlib
import unittest
from typing import Any

from crewai.crews.crew_output import CrewOutput
from crewai.types.streaming import CrewStreamingOutput

from brief_crew.builder import runtime


class StreamingCrew:
    """A crew whose `kickoff` is lazy, exactly as `Crew(stream=True)` is.

    `ran` flips inside the generator body rather than inside `kickoff`, which is
    the whole point: CrewAI's own `run_crew` closure only executes once the
    chunk generator is pulled, so a caller that never iterates never bills and
    never fails.
    """

    def __init__(self, text: str = "the crew's real answer") -> None:
        self.text = text
        self.ran = False
        self.inputs: dict[str, Any] | None = None

    def kickoff(self, inputs: dict[str, Any] | None = None) -> CrewStreamingOutput:
        self.inputs = dict(inputs or {})
        holder: list[CrewStreamingOutput] = []

        def chunks() -> Any:
            self.ran = True
            holder[0]._set_result(CrewOutput(raw=self.text))
            return
            yield  # unreachable, and what makes this a generator

        streaming = CrewStreamingOutput(sync_iterator=chunks())
        holder.append(streaming)
        return streaming


class PlainCrew:
    """A library crew: no `stream`, so `kickoff` returns a `CrewOutput`."""

    def __init__(self, text: str = "a library crew's answer") -> None:
        self.text = text
        self.inputs: dict[str, Any] | None = None

    def kickoff(self, inputs: dict[str, Any] | None = None) -> CrewOutput:
        self.inputs = dict(inputs or {})
        return CrewOutput(raw=self.text)


class StreamingKickoffTests(unittest.TestCase):
    def test_a_streaming_kickoff_is_drained_and_yields_the_crews_own_output(self) -> None:
        crew = StreamingCrew()

        result = runtime._kickoff(crew, {"topic": "clinic scheduling"})

        self.assertTrue(crew.ran, "the stream was never drained, so the crew never ran")
        self.assertIsInstance(result, CrewOutput)
        self.assertEqual("the crew's real answer", runtime._as_text(result))

    def test_the_undrained_object_stringifies_to_the_repr_that_shipped(self) -> None:
        """The defect itself, pinned as a fact about CrewAI rather than a story.

        Without the drain `_as_text` reaches its `str(value)` fallback, and what
        an operator is handed as the deliverable is an address in this process.
        """

        crew = StreamingCrew()
        undrained = crew.kickoff(inputs={})

        self.assertFalse(crew.ran)
        self.assertIn("CrewStreamingOutput object at", runtime._as_text(undrained))

    def test_a_plain_crew_output_passes_through_untouched(self) -> None:
        """A library crew sets no `stream`; the drain must not assume one."""

        crew = PlainCrew()

        result = runtime._kickoff(crew, {"idea": "a scheduling assistant"})

        self.assertIsInstance(result, CrewOutput)
        self.assertEqual("a library crew's answer", runtime._as_text(result))

    def test_the_inputs_reach_the_crew_unchanged(self) -> None:
        """`_kickoff` copies the mapping; it must not drop or rename a key."""

        crew = StreamingCrew()

        runtime._kickoff(crew, {"topic": "one", "feedback": "two"})

        self.assertEqual({"topic": "one", "feedback": "two"}, crew.inputs)

    def test_no_call_site_kicks_off_a_crew_without_going_through_the_drain(self) -> None:
        """The guard, because the fix is a habit and habits revert.

        Four call sites in `runtime.py` run a crew, and each was
        `_as_text(crew.kickoff(...))` before 2026-09-05. A fifth added later
        without `_kickoff` would fail silently and expensively, in the one way
        this suite has already proved it cannot otherwise see - so the check is
        on the source text, which is the only place the omission is visible.
        """

        source = pathlib.Path(runtime.__file__).read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in source.splitlines()
            if ".kickoff(" in line and "_kickoff" not in line and "streamed = crew.kickoff" not in line
        ]

        self.assertEqual(
            [],
            offenders,
            "a crew is kicked off outside `_kickoff`. With `Crew(stream=True)` that "
            "returns a lazy CrewStreamingOutput, nothing runs, and the node's output "
            "becomes the object's repr - see this module's docstring for the paid run "
            "that measured it.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
