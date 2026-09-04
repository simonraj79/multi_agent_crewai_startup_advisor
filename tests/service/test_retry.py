"""Retry, backoff, fallback and what is NOT retried - 10 D3, criterion 4.

Everything here runs the REAL compiled definition through the REAL engine with
the REAL entrypoints, and replaces only the object that would have called a
model - the same `SyntheticCrewFactories` that `SYNTHETIC=1` installs, told to
fail by `SYNTHETIC_FAILURE`. Nothing costs anything.

Two things this module is careful about, because both have bitten this
repository before:

* **The frames are captured through `capture_events`**, which is what the
  service does, rather than by reading a buffer the runner was handed and never
  writes to. `runtime._emit_frame` reads `current_capture`, so a test that
  skipped this would assert on an empty list and pass.
* **The fallback is proved by WHICH MODEL an attempt ran on**, not by counting
  attempts. `SyntheticCrewFactories.calls` records `(node_id, model)` per built
  crew; without it, "three attempts happened" and "the third used the fallback"
  are the same assertion.
"""

from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Any, Iterator
import unittest
from unittest.mock import patch

from brief_crew.builder.descriptor import BuilderWorkflow, build_builder_workflow
from brief_crew.events import FrameKind
from brief_crew.events.adapter import StreamSinkAdapter
from brief_crew.events.buffer import FrameBuffer
from brief_crew.events.context import CaptureContext, capture_events
from brief_crew.service.builder_runner import (
    BuilderFlowRunner,
    SyntheticCrewFactories,
    SyntheticRateLimitError,
    SyntheticRefusal,
    parse_synthetic_failures,
)
from brief_crew.service.runner import RunExecution
from tests.builder.test_compiler import (
    AUTHORED_MODEL,
    authored_agent_node,
    input_node,
    output_node,
)
from tests.builder.test_document import document, edge

FALLBACK_MODEL = "google/gemini-3.5-flash-lite"


def retrying_graph(
    *, retry: dict[str, Any] | None, on_error: str = "fail"
) -> Any:
    """idea -> a -> b -> report, with `b` carrying the retry policy."""

    return document(
        [
            input_node(),
            authored_agent_node("a"),
            authored_agent_node("b", source="a", retry=retry, on_error=on_error),
            output_node("report", source="${state.out__b}"),
        ],
        [
            edge("e1", "idea", "a"),
            edge("e2", "a", "b"),
            edge("e3", "b", "report"),
        ],
    )


class Harness(unittest.TestCase):
    """One compiled graph, run under a real capture scope, with frames kept."""

    def workflow(self, graph: Any) -> BuilderWorkflow:
        return build_builder_workflow(graph)

    @contextmanager
    def running(
        self, workflow: BuilderWorkflow, factories: SyntheticCrewFactories
    ) -> Iterator[tuple[BuilderFlowRunner, RunExecution, FrameBuffer]]:
        buffer = FrameBuffer()
        capture = StreamSinkAdapter(
            run_id="run-retry", buffer=buffer, registry=workflow.node_registry
        )
        execution = RunExecution(
            run_id="run-retry",
            inputs={"idea": "a scheduling assistant for clinics"},
            capture=capture,
            flow_id="run-retry",
            cancel_requested=threading.Event(),
        )
        runner = BuilderFlowRunner(workflow, crew_factories=factories)
        with capture_events(CaptureContext(run_id="run-retry", adapter=capture)):
            yield runner, execution, buffer

    @staticmethod
    def details(buffer: FrameBuffer, *, kind: FrameKind, stage: str) -> list[dict]:
        return [
            dict(frame.details)
            for frame in buffer.replay(after=0, limit=500)
            if frame.kind is kind and dict(frame.details).get("stage") == stage
        ]


class RetryFrameTests(Harness):
    def test_three_attempts_two_retries_and_the_third_on_the_fallback(self) -> None:
        """The criterion's own scenario, with every attempt failing.

        `max_retries: 2` is THREE attempts, the third on the fallback model, and
        `on_error: route` is what makes the run reach `completed` with all three
        of them failed: the node returns normally having written `err__b`, and
        its paired router takes the error port. Retry and the error port are one
        story, and this is the shape in which an author actually meets it.
        """

        workflow = self.workflow(
            document(
                [
                    input_node(),
                    authored_agent_node(
                        "b",
                        source="idea",
                        on_error="route",
                        retry={
                            "max_retries": 2,
                            "backoff_seconds": 0,
                            "fallback_model": FALLBACK_MODEL,
                        },
                    ),
                    authored_agent_node("sorry", source="idea"),
                    output_node("report", source="${state.out__sorry}"),
                ],
                [
                    edge("e1", "idea", "b"),
                    edge("e2", "b", "report"),
                    edge("e3", "b", "sorry", source_port="error"),
                    edge("e4", "sorry", "report"),
                ],
            )
        )
        factories = SyntheticCrewFactories(failures="b:rate_limit")
        with self.running(workflow, factories) as (runner, execution, buffer):
            result = runner(execution)

        errors = self.details(buffer, kind=FrameKind.ERROR, stage="error")
        retries = self.details(buffer, kind=FrameKind.NODE_STATE, stage="retry")
        self.assertEqual(len(errors), 3, errors)
        self.assertEqual(len(retries), 2, retries)
        self.assertEqual([error["attempt"] for error in errors], [1, 2, 3])
        self.assertEqual([True, True, False], [error["will_retry"] for error in errors])
        # The third attempt, and only the third, ran on the fallback.
        self.assertEqual(
            [call[1] for call in factories.calls if call[0] == "b"],
            [AUTHORED_MODEL, AUTHORED_MODEL, FALLBACK_MODEL],
        )
        self.assertIsNone(errors[0]["fallback_model"])
        self.assertEqual(errors[2]["fallback_model"], FALLBACK_MODEL)
        self.assertTrue(errors[2]["routed"])
        # And the run produced its recovery node's output rather than dying.
        self.assertIn("Synthetic output for sorry", str(result))

    def test_a_fallback_that_succeeds_finishes_the_run_on_it(self) -> None:
        """`b:rate_limit:2` - the first two attempts fail and the third works.

        This is the other reading of the criterion, and it is the one that
        proves the fallback model is USED rather than merely named: the run
        completes normally, on `on_error: fail`, having produced `b`'s output.
        """

        workflow = self.workflow(
            retrying_graph(
                retry={
                    "max_retries": 2,
                    "backoff_seconds": 0,
                    "fallback_model": FALLBACK_MODEL,
                }
            )
        )
        factories = SyntheticCrewFactories(failures="b:rate_limit:2")
        with self.running(workflow, factories) as (runner, execution, buffer):
            result = runner(execution)

        self.assertEqual(len(self.details(buffer, kind=FrameKind.ERROR, stage="error")), 2)
        self.assertEqual(
            len(self.details(buffer, kind=FrameKind.NODE_STATE, stage="retry")), 2
        )
        self.assertEqual(
            [call[1] for call in factories.calls if call[0] == "b"],
            [AUTHORED_MODEL, AUTHORED_MODEL, FALLBACK_MODEL],
        )
        self.assertIn("Synthetic output for b", str(result))

    def test_the_retry_frame_names_the_model_the_next_attempt_will_use(self) -> None:
        workflow = self.workflow(
            retrying_graph(
                retry={
                    "max_retries": 2,
                    "backoff_seconds": 0,
                    "fallback_model": FALLBACK_MODEL,
                },
                on_error="route",
            )
        )
        with self.running(
            workflow, SyntheticCrewFactories(failures="b:rate_limit")
        ) as (runner, execution, buffer):
            runner(execution)
        retries = self.details(buffer, kind=FrameKind.NODE_STATE, stage="retry")
        self.assertEqual([retry["attempt"] for retry in retries], [2, 3])
        self.assertEqual([retry["of"] for retry in retries], [3, 3])
        self.assertEqual([retry["model"] for retry in retries], [None, FALLBACK_MODEL])

    def test_max_retries_zero_fails_at_the_first_attempt(self) -> None:
        workflow = self.workflow(retrying_graph(retry={"max_retries": 0}))
        factories = SyntheticCrewFactories(failures="b:rate_limit")
        with self.running(workflow, factories) as (runner, execution, buffer):
            with self.assertRaises(SyntheticRateLimitError):
                runner(execution)
        errors = self.details(buffer, kind=FrameKind.ERROR, stage="error")
        self.assertEqual(len(errors), 1)
        self.assertFalse(errors[0]["will_retry"])
        self.assertFalse(errors[0]["routed"])
        self.assertEqual(len([c for c in factories.calls if c[0] == "b"]), 1)

    def test_no_retry_block_at_all_is_one_attempt(self) -> None:
        workflow = self.workflow(retrying_graph(retry=None))
        factories = SyntheticCrewFactories(failures="b:rate_limit")
        with self.running(workflow, factories) as (runner, execution, _):
            with self.assertRaises(SyntheticRateLimitError):
                runner(execution)
        self.assertEqual(len([c for c in factories.calls if c[0] == "b"]), 1)


class NotRetryableTests(Harness):
    """Decision 16, and the closed list, made observable."""

    def test_a_refusal_is_not_retried_however_many_attempts_were_bought(self) -> None:
        """A model that declines is a decision, not a transport fault.

        Retrying it with a fallback model is asking a second judge until one
        agrees. The node is configured for three attempts and takes ONE.
        """

        workflow = self.workflow(
            retrying_graph(
                retry={
                    "max_retries": 2,
                    "backoff_seconds": 0,
                    "fallback_model": FALLBACK_MODEL,
                }
            )
        )
        factories = SyntheticCrewFactories(failures="b:refusal")
        with self.running(workflow, factories) as (runner, execution, buffer):
            with self.assertRaises(SyntheticRefusal):
                runner(execution)
        self.assertEqual(len([c for c in factories.calls if c[0] == "b"]), 1)
        self.assertEqual(
            len(self.details(buffer, kind=FrameKind.NODE_STATE, stage="retry")), 0
        )
        errors = self.details(buffer, kind=FrameKind.ERROR, stage="error")
        self.assertEqual(len(errors), 1)
        self.assertFalse(errors[0]["will_retry"])

    def test_the_classifier_reads_a_status_code_and_a_listed_name(self) -> None:
        from brief_crew.builder.runtime import BuilderRuntimeError, _is_retryable

        class Wrapped(RuntimeError):
            status_code = 503

        class Named(RuntimeError):
            pass

        Named.__name__ = "RateLimitError"
        self.assertTrue(_is_retryable(Wrapped()))
        self.assertTrue(_is_retryable(Named()))
        self.assertFalse(_is_retryable(ValueError("nope")))
        # A document, wiring or credential fault fails identically the second
        # time and tells nobody anything new.
        self.assertFalse(_is_retryable(BuilderRuntimeError("no such tier")))

    def test_a_deliberate_break_of_the_closed_list_would_be_visible(self) -> None:
        """The list is what stops a refusal being retried, and here is the proof.

        Patching `_is_retryable` to say yes to everything turns the refusal test
        above into three attempts. Asserting that here is what makes the closed
        list a mechanism rather than a comment.
        """

        workflow = self.workflow(
            retrying_graph(retry={"max_retries": 2, "backoff_seconds": 0})
        )
        factories = SyntheticCrewFactories(failures="b:refusal")
        with patch("brief_crew.builder.runtime._is_retryable", lambda exc: True):
            with self.running(workflow, factories) as (runner, execution, _):
                with self.assertRaises(SyntheticRefusal):
                    runner(execution)
        self.assertEqual(len([c for c in factories.calls if c[0] == "b"]), 3)


class CancelBetweenAttemptsTests(Harness):
    def test_a_cancel_between_attempts_reaches_hook_aborted(self) -> None:
        """`checkpoint` is per ATTEMPT, not per node - 10 D3.

        A node bought three attempts and Cancel lands after the first: without
        the per-attempt checkpoint the run would spend two more before noticing.
        """

        from crewai.hooks import HookAborted

        workflow = self.workflow(
            retrying_graph(retry={"max_retries": 2, "backoff_seconds": 0})
        )
        cancel = threading.Event()

        class CancelAfterFirst(SyntheticCrewFactories):
            def _record(self, node_id: str, model: str) -> None:
                super()._record(node_id, model)

        factories = CancelAfterFirst(failures="b:rate_limit")
        original = factories._record

        def record_then_cancel(node_id: str, model: str) -> None:
            if node_id == "b":
                cancel.set()
            original(node_id, model)

        factories._record = record_then_cancel  # type: ignore[method-assign]

        buffer = FrameBuffer()
        capture = StreamSinkAdapter(
            run_id="run-cancel", buffer=buffer, registry=workflow.node_registry
        )
        execution = RunExecution(
            run_id="run-cancel",
            inputs={"idea": "a scheduling assistant for clinics"},
            capture=capture,
            flow_id="run-cancel",
            cancel_requested=cancel,
        )
        runner = BuilderFlowRunner(workflow, crew_factories=factories)
        with capture_events(CaptureContext(run_id="run-cancel", adapter=capture)):
            with self.assertRaises(HookAborted):
                runner(execution)
        # One attempt, then the checkpoint at the head of the second refused.
        self.assertEqual(len([c for c in factories.calls if c[0] == "b"]), 1)

    def test_hook_aborted_is_never_swallowed_by_the_error_policy(self) -> None:
        """Cancel must not become a shrug on an `on_error: route` node."""

        from crewai.hooks import HookAborted

        from brief_crew.builder.runtime import _is_control_flow

        self.assertTrue(_is_control_flow(HookAborted("stop")))


class ParseTests(unittest.TestCase):
    def test_the_grammar(self) -> None:
        self.assertEqual(parse_synthetic_failures(None), ())
        self.assertEqual(parse_synthetic_failures(""), ())
        self.assertEqual(parse_synthetic_failures("nonsense"), ())
        (every,) = parse_synthetic_failures("rate_limit")
        self.assertIsNone(every.node_id)
        self.assertIsNone(every.times)
        (scoped,) = parse_synthetic_failures("b:rate_limit")
        self.assertEqual(scoped.node_id, "b")
        (counted,) = parse_synthetic_failures("b:rate_limit:2")
        self.assertEqual(counted.times, 2)
        self.assertEqual(len(parse_synthetic_failures("a:refusal,b:rate_limit")), 2)

    def test_a_typo_is_no_failure_rather_than_a_crash(self) -> None:
        """This is read on a path that runs for real; a typo must not stop a boot."""

        self.assertEqual(parse_synthetic_failures("b:rate_limit:banana")[0].times, None)
        self.assertEqual(parse_synthetic_failures(":::"), ())

    def test_the_environment_is_read_per_instance(self) -> None:
        import os

        with patch.dict(os.environ, {"SYNTHETIC_FAILURE": "rate_limit"}):
            self.assertEqual(len(SyntheticCrewFactories().plans), 1)
        self.assertEqual(SyntheticCrewFactories().plans, ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
