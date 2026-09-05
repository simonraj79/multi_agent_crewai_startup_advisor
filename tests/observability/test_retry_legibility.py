"""Definition of Done row D4: a retry is legible as a retry.

Two retries, two mechanisms, and the trace has to show both without either
being named in this exporter.

**A guardrail rejection re-runs the whole task.** The frames say so: two model
calls under one task with a guardrail result between them. A reader must be able
to see two generations under the same task, in order, with the attempt index on
each, and the guardrail's verdict recorded as a score on the task it judged -
because a rate over time is what row B6 asks for and an event on a timeline is
not chartable.

**A transport failure is a call that happened and produced nothing.** The frames
say that too: a model call at `stage: error` with no token frame, then another
call that succeeds. A reader must see the failed one at `level=ERROR` with the
message, followed by the success - not a gap, and not one call that took a long
time.
"""

from __future__ import annotations

import unittest

from tests.observability.replay import Recorder, RunFacts, by_role, drive, exporter_for


IDENTITY = {"agent_role": "an authored role", "task_name": "an authored task"}


class GuardrailRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for(
            facts=RunFacts(
                run_id="11111111-2222-4333-8444-555555555555",
                workflow_id="a-workflow",
                session_id="s1",
            )
        )
        recorder = Recorder()
        recorder.run_started({"idea": "an idea"})
        recorder.node_started("n1", **IDENTITY)
        recorder.model_call("n1", "call-1", text="a first answer", **IDENTITY)
        recorder.guardrail("n1", success=False, retry_count=1, **IDENTITY)
        recorder.model_call("n1", "call-2", text="a second answer", **IDENTITY)
        recorder.guardrail("n1", success=True, retry_count=1, **IDENTITY)
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({"ok": True})
        drive(self.exporter, recorder.frames)
        self.observations = self.backend.observations

    def test_both_calls_are_generations_under_the_same_task(self) -> None:
        tasks = by_role(self.observations, "task")
        self.assertEqual(1, len(tasks))
        generations = by_role(self.observations, "generation")
        self.assertEqual(2, len(generations))
        agents = by_role(self.observations, "agent")
        self.assertEqual(1, len(agents))
        for generation in generations:
            self.assertIs(agents[0], generation.parent)
        self.assertIs(tasks[0], agents[0].parent)

    def test_the_retry_index_is_on_each_generation(self) -> None:
        attempts = [o.metadata["attempt"] for o in by_role(self.observations, "generation")]
        self.assertEqual([1, 2], attempts)

    def test_the_guardrail_verdict_is_a_score_on_the_task(self) -> None:
        tasks = by_role(self.observations, "task")
        guardrails = [s for s in self.backend.scores if s.name == "guardrail_passed"]
        self.assertEqual([0, 1], [s.value for s in guardrails])
        for score in guardrails:
            self.assertEqual(tasks[0].ident, score.observation_id)

    def test_the_task_carries_its_attempt_count_as_a_score(self) -> None:
        attempts = [s for s in self.backend.scores if s.name == "task_attempts"]
        self.assertEqual(1, len(attempts))
        self.assertEqual(2, attempts[0].value)

    def test_no_observation_is_left_open(self) -> None:
        self.assertEqual([], [o.name for o in self.observations if not o.ended])


class TransportRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({"idea": "an idea"})
        recorder.node_started("n1", **IDENTITY)
        recorder.model_call_failed(
            "n1", "call-1", error="APIConnectionError: the upstream closed", **IDENTITY
        )
        recorder.model_call("n1", "call-2", text="the answer", **IDENTITY)
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({"ok": True})
        drive(self.exporter, recorder.frames)
        self.generations = by_role(self.backend.observations, "generation")

    def test_the_failed_call_is_a_generation_at_error_level(self) -> None:
        self.assertEqual(2, len(self.generations))
        failed, succeeded = self.generations
        self.assertEqual("ERROR", failed.level)
        self.assertIn("APIConnectionError", failed.status_message or "")
        self.assertIsNone(succeeded.level)

    def test_the_failed_call_has_no_usage_and_the_next_one_does(self) -> None:
        failed, succeeded = self.generations
        self.assertIsNone(failed.usage_details)
        self.assertEqual({"input": 100, "output": 20, "total": 120}, succeeded.usage_details)

    def test_a_failed_call_carries_no_provider_generation_id(self) -> None:
        """CrewAI's failure event has no field for one, so neither has this."""

        failed = self.generations[0]
        self.assertIsNone(failed.metadata.get("response_id"))

    def test_the_order_is_failure_then_success(self) -> None:
        failed, succeeded = self.generations
        self.assertLess(failed.end_ns or 0, succeeded.end_ns or 0)
        self.assertEqual([1, 2], [o.metadata["attempt"] for o in self.generations])
