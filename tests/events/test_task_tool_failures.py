"""What a task's own output says on the frame that says it completed.

Plan 21 R6. Until this shipped the `TaskCompletedEvent` branch emitted
`{"stage": "after"}` and threw away a whole `TaskOutput`. Two keys are lifted
and the rest are deliberately left where they were:

* `tool_failure_count` and `tool_failures[]` are the pair a miner reads. A
  `ToolFailure` is a tool's OWN structured report rather than a raised error,
  so it fires no error event - a task that finished over three failed tool
  calls looks clean on every other frame this pipeline writes.
* `raw`, `output_format`, `json_dict`, `expected_output` and `pydantic` are
  NOT lifted, and the negative claim is the load-bearing half. `raw` is the
  run's own answer, and a frame that carried it would put it into an export, a
  sample and a model prompt without anybody deciding that it should; the
  prompt-absent policy (`TRACE-CONTRACT.md` section 4) is not reopened by a
  mining plan, and the same judgement is applied to the completion.

The negative tests scan EVERY key of EVERY frame rather than asserting two
absences on the one field expected to be risky, which is the shape of check
that has caught every leak this repository has had.
"""

from __future__ import annotations

from typing import Any
import unittest

from crewai.events.types.task_events import TaskCompletedEvent
from crewai.tasks.output_format import OutputFormat
from crewai.tasks.task_output import TaskOutput, ToolFailureRecord
from crewai.tools.tool_failure import ToolFailure

from brief_crew.config import MAX_TASK_TOOL_FAILURES
from tests.events.frame_case import TS, FrameCase


ROLE = "an authored role"
TASK = "an authored task"
IDENTITY = {
    "task_id": "task-1",
    "task_name": TASK,
    "agent_id": "agent-1",
    "agent_role": ROLE,
}

#: A sentence a person could have typed, so a scan for it is meaningful.
PROMPT_SENTENCE = "you are a careful analyst; here is the whole conversation"
#: The model's ANSWER. It must not reach a frame either - R6's second half.
ANSWER_SENTENCE = "Three of five claims are supported; two are not."


def task_output(**overrides: Any) -> TaskOutput:
    """A REAL `TaskOutput`, never a lookalike.

    A double that diverges from its subject certifies nothing: a bare string
    here would produce a frame reading `tool_failure_count: 0` and prove
    nothing at all about the branch under test.
    """

    fields: dict[str, Any] = {
        "description": "Verify each claim against a primary source.",
        "name": TASK,
        "expected_output": "Every claim marked supported or unsupported.",
        "raw": ANSWER_SENTENCE,
        "json_dict": {"supported": 3, "unsupported": 2},
        "agent": ROLE,
        "output_format": OutputFormat.JSON,
        "messages": [{"role": "system", "content": PROMPT_SENTENCE}],
        "tool_failures": [
            ToolFailureRecord(
                tool_name="primary_source_lookup",
                failure=ToolFailure(
                    message="the registry returned no filing for that year",
                    code="filing_not_found",
                ),
                agent_role=ROLE,
                task_name=TASK,
            )
        ],
    }
    fields.update(overrides)
    return TaskOutput(**fields)


class TaskToolFailureFrameTests(FrameCase):
    def completed(self, output: Any) -> dict[str, Any]:
        frames = self.emit(
            TaskCompletedEvent.model_construct(
                output=output, task=None, timestamp=TS, **IDENTITY
            )
        )
        self.assertEqual(1, len(frames), "one frame, the same kind as before")
        self.assertHandled("task_completed")
        return frames[0].details

    def test_the_two_keys_are_present_and_no_others(self) -> None:
        details = self.completed(task_output())
        self.assertEqual("after", details["stage"])
        self.assertIn("tool_failure_count", details)
        self.assertIn("tool_failures", details)
        for key in (
            "output_preview",
            "output_chars",
            "output_format",
            "output_json",
            "expected_output_preview",
            "expected_output_chars",
        ):
            with self.subTest(key=key):
                self.assertNotIn(key, details)

    def test_the_values_are_the_task_outputs_own(self) -> None:
        details = self.completed(task_output())
        self.assertEqual(1, details["tool_failure_count"])
        self.assertEqual(
            [{"tool": "primary_source_lookup", "error_class": "filing_not_found"}],
            [dict(row) for row in details["tool_failures"]],
        )

    def test_only_the_first_eight_failures_are_listed(self) -> None:
        """The list is a POINTER; the count is the count.

        `tool_failure_count` stays unbounded because a rate is read off it and
        a clipped count would understate a workflow's worst runs.
        """

        many = [
            ToolFailureRecord(
                tool_name=f"tool_{index}",
                failure=ToolFailure(message="no", code=f"code_{index}"),
                agent_role=ROLE,
                task_name=TASK,
            )
            for index in range(MAX_TASK_TOOL_FAILURES + 4)
        ]
        details = self.completed(task_output(tool_failures=many))
        self.assertEqual(MAX_TASK_TOOL_FAILURES + 4, details["tool_failure_count"])
        self.assertEqual(MAX_TASK_TOOL_FAILURES, len(details["tool_failures"]))

    def test_a_failure_with_no_code_falls_back_to_its_reason(self) -> None:
        """A tool failure names no exception class, so the reason is the group."""

        record = ToolFailureRecord(
            tool_name="a_tool",
            failure=ToolFailure(message="it did not work"),
            agent_role=ROLE,
            task_name=TASK,
        )
        details = self.completed(task_output(tool_failures=[record]))
        self.assertEqual("a_tool", details["tool_failures"][0]["tool"])
        self.assertTrue(details["tool_failures"][0]["error_class"])

    def test_no_tool_failures_is_a_zero_and_no_list(self) -> None:
        """The zero is the marker that says the serializer COULD look.

        A run recorded before this shipped carries no key at all, so "no tool
        failed" and "this layer could not see" stay different facts - which is
        the distinction an empty list would destroy.
        """

        details = self.completed(task_output(tool_failures=[]))
        self.assertEqual(0, details["tool_failure_count"])
        self.assertNotIn("tool_failures", details)

    # -- the branch stays TOTAL -------------------------------------------

    def test_a_none_output_emits_the_old_frame_and_raises_nothing(self) -> None:
        """A capture callback that raises is a lost frame and an emit error."""

        details = self.completed(None)
        self.assertEqual("after", details["stage"])
        self.assertNotIn("tool_failure_count", details)

    def test_an_object_that_is_not_a_task_output_is_survived(self) -> None:
        """`getattr` throughout, with no attribute assumption."""

        class NotATaskOutput:
            pass

        details = self.completed(NotATaskOutput())
        self.assertEqual("after", details["stage"])
        self.assertEqual(0, details["tool_failure_count"])

    def test_a_bare_string_output_is_survived(self) -> None:
        details = self.completed("just a string")
        self.assertEqual(0, details["tool_failure_count"])


class NoContentReachesAnyFrame(FrameCase):
    """R6's negative half, as a scan rather than as absences on one field."""

    def setUp(self) -> None:
        super().setUp()
        self.emit(
            TaskCompletedEvent.model_construct(
                output=task_output(), task=None, timestamp=TS, **IDENTITY
            )
        )
        self.frames = self.buffer.replay()

    def keys(self) -> set[str]:
        found: set[str] = set()

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    found.add(str(key))
                    walk(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

        for frame in self.frames:
            walk(frame.details)
        return found

    def blob(self) -> str:
        return repr([frame.details for frame in self.frames])

    def test_messages_is_in_no_frame_under_any_key(self) -> None:
        self.assertNotIn("messages", self.keys())

    def test_pydantic_is_in_no_frame_under_any_key(self) -> None:
        self.assertNotIn("pydantic", self.keys())

    def test_the_prompt_sentence_reaches_no_frame_at_all(self) -> None:
        """The key could be renamed; the CONTENT is what must not be there."""

        self.assertNotIn(PROMPT_SENTENCE, self.blob())

    def test_the_answer_reaches_no_frame_either(self) -> None:
        """R6: `output_preview` is not ported, and this is why it matters.

        The answer would otherwise travel into the eval-set export, the review
        sample and the model prompt at once, on the strength of a serializer
        change nobody read as a content decision.
        """

        self.assertNotIn(ANSWER_SENTENCE, self.blob())
        self.assertNotIn("unsupported", self.blob())

    def test_the_tool_failure_does_reach_the_frame(self) -> None:
        """The control. Without it every test above would pass on nothing."""

        self.assertIn("filing_not_found", self.blob())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
