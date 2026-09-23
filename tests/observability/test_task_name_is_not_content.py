"""A builder task's `task_name` is the user's words, and it never reaches Langfuse.

Found 2026-09-23 while fixing the Improve panel's task grouping. CrewAI 1.15.18
fills `event.task_name` with `task.name or task.description`
(`crewai/events/base_events.py:104`), and a builder task is built with no
`name` - so on every builder frame the serializer stamps `task_name` with the
RENDERED task description, the user's own input interpolated into it. The
exporter copied it into the task span's NAME, into `metadata.task_name` on
every observation, and into the fallback prompt fingerprint's basis. With
`LANGFUSE_CAPTURE_CONTENT` off none of that is allowed: the contract's
content rule covers observation names and metadata as much as payloads.

The fix is at the point of reading, with `config.declared_task_name()`: a
declared name (an identifier) travels as before, anything else is treated as
absent and the span is named after the node. The test drives a whole run and
then searches EVERY argument of EVERY backend call, rather than asserting on
the fields somebody thought of - which is what makes it fail if a new field
starts carrying the value.
"""

from __future__ import annotations

from typing import Any
import unittest

from brief_crew.events.models import FrameKind, FrameLevel, UIEventType
from brief_crew.observability.backend import RecordingBackend
from brief_crew.observability.langfuse_exporter import RunFacts

from tests.observability.replay import RUN_ID, Recorder, by_role, drive, exporter_for

#: Distinctive enough that a hit cannot be a coincidence.
PLANTED = "Please add three more seats for zebra-quartz-7741 hires"
DESCRIPTION = f"Answer this account message. MESSAGE: {PLANTED}"
TASK_ID = "0f5a3c1e-9b7d-4e2a-8c61-7d2f1e0a9b44"


class SpyBackend(RecordingBackend):
    """A recording backend that also keeps `repr` of every call it was given."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def _note(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        # The observation handles are this double's own objects; their repr
        # carries their names and metadata too, which is only more coverage.
        self.calls.append(f"{name}{args!r}{kwargs!r}")

    def open_run(self, *args: Any, **kwargs: Any) -> Any:
        self._note("open_run", args, kwargs)
        return super().open_run(*args, **kwargs)

    def open_child(self, *args: Any, **kwargs: Any) -> Any:
        self._note("open_child", args, kwargs)
        return super().open_child(*args, **kwargs)

    def update(self, observation: Any, **fields: Any) -> None:
        self._note("update", (), fields)
        super().update(observation, **fields)

    def event(self, *args: Any, **kwargs: Any) -> Any:
        self._note("event", args, kwargs)
        return super().event(*args, **kwargs)

    def score(self, *args: Any, **kwargs: Any) -> Any:
        self._note("score", args, kwargs)
        return super().score(*args, **kwargs)

    def set_trace_output(self, run_observation: Any, payload_output: Any) -> None:
        self._note("set_trace_output", (payload_output,), {})
        super().set_trace_output(run_observation, payload_output)


def builder_run(task_name: str) -> Recorder:
    """One builder node, one unnamed task, the frames the serializer writes.

    Every identity-carrying frame carries `task_name` exactly as `_actor`
    stamps it, and the task frames' `message` is the serializer's own
    `f"{task_name} completed"` sentence.
    """

    identity = {"agent_role": "Account agent", "task_name": task_name, "task_id": TASK_ID}
    rec = Recorder()
    rec.run_started()
    rec.node_started("account")
    rec.add(
        FrameKind.AGENT,
        UIEventType.AGENT_CALL,
        "account",
        {"stage": "before", **identity},
        message=f"{task_name} started",
    )
    rec.add(
        FrameKind.AGENT,
        UIEventType.AGENT_CALL,
        "account",
        {"stage": "before", "task": task_name, **identity},
        message="Account agent started",
    )
    rec.model_call("account", "call-1", **identity)
    rec.tool_call("account", "crm_lookup", error="ValueError: no such account", **identity)
    rec.guardrail("account", success=False, retry_count=1, **identity)
    rec.add(
        FrameKind.AGENT,
        UIEventType.AGENT_CALL,
        "account",
        {"stage": "after", "task": task_name, "output": "an answer", **identity},
        message="Account agent completed",
    )
    rec.add(
        FrameKind.AGENT,
        UIEventType.AGENT_CALL,
        "account",
        {"stage": "after", "tool_failure_count": 1, **identity},
        message=f"{task_name} completed",
    )
    rec.add(
        FrameKind.AGENT,
        UIEventType.AGENT_CALL,
        "account",
        {"stage": "error", "error": "boom", "error_class": "ValueError", **identity},
        level=FrameLevel.ERROR,
        message=f"{task_name} failed",
    )
    rec.node_ended("account")
    rec.run_completed()
    # A frame arriving after the terminal one becomes an EVENT on the run span,
    # which is the path that copies a frame's `details` into metadata through
    # the content policy and, at ERROR level, falls back to the frame's own
    # `message` for its statusMessage - here the serializer's task sentence.
    rec.add(
        FrameKind.AGENT,
        UIEventType.AGENT_CALL,
        "account",
        {"stage": "error", "task": task_name, **identity},
        level=FrameLevel.ERROR,
        message=f"{task_name} failed",
    )
    return rec


def export(task_name: str) -> SpyBackend:
    backend = SpyBackend()
    exporter, _ = exporter_for(backend, facts=RunFacts(run_id=RUN_ID, workflow_id="ug_triage001"))
    drive(exporter, builder_run(task_name).frames)
    return backend


class ARenderedDescriptionNeverReachesLangfuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = export(DESCRIPTION)

    def test_the_planted_input_is_in_no_backend_call_at_all(self) -> None:
        self.assertTrue(self.backend.calls, "the exporter recorded nothing; the test proves nothing")
        leaking = [call for call in self.backend.calls if PLANTED in call]
        self.assertEqual([], leaking)
        for observation in self.backend.observations:
            with self.subTest(name=observation.name):
                self.assertNotIn(PLANTED, repr(observation))
        for score in self.backend.scores:
            self.assertNotIn(PLANTED, repr(score))

    def test_the_task_span_is_still_there_and_named_after_the_node(self) -> None:
        tasks = by_role(self.backend.observations, "task")
        self.assertEqual(1, len(tasks), [o.name for o in tasks])
        self.assertEqual("account", tasks[0].name)
        self.assertIsNone(tasks[0].metadata.get("task_name"))

    def test_the_late_event_names_the_task_as_a_length_and_a_hash(self) -> None:
        events = by_role(self.backend.observations, "event")
        carrying = [e for e in events if "task_name" in (e.metadata.get("details") or {})]
        self.assertTrue(carrying, [e.name for e in events])
        described = carrying[-1].metadata["details"]["task_name"]
        self.assertEqual({"chars", "sha256"}, set(described))
        self.assertEqual("the task failed", carrying[-1].status_message)

    def test_the_agent_still_hangs_off_the_task(self) -> None:
        tasks = by_role(self.backend.observations, "task")
        agents = by_role(self.backend.observations, "agent")
        self.assertTrue(agents)
        self.assertIs(tasks[0], agents[0].parent)


class ADeclaredTaskNameStillTravelsTests(unittest.TestCase):
    """The control: an identifier is an identity value (row C2) and is kept."""

    def setUp(self) -> None:
        self.backend = export("market_task")

    def test_the_task_span_is_named_after_the_declared_name(self) -> None:
        tasks = by_role(self.backend.observations, "task")
        self.assertEqual(["market_task"], [task.name for task in tasks])
        self.assertEqual("market_task", tasks[0].metadata.get("task_name"))

    def test_every_observation_carries_it_in_metadata(self) -> None:
        carried = [
            o for o in self.backend.observations if o.metadata.get("task_name") == "market_task"
        ]
        self.assertGreater(len(carried), 3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
