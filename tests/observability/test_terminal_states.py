"""Definition of Done row D6, and the rest of contract section 6.

D6 is the cost-ceiling abort: a run stopped by `MAX_RUN_COST_USD` must end the
trace at status `failed` with the ceiling NAMED, not merely `cancelled`. The
distinction is the whole point - an operator pressing Cancel and a run hitting
its own spend limit arrive at the app by the same path and are told apart by one
field on one frame, and a trace that collapses them tells a reader the wrong
story about their money.

The other cases are here because section 6 is a table and a table wants a row
each: completed, failed, cancelled, and the rule that binds all four - after a
terminal frame nothing is left without an end time (row D3).
"""

from __future__ import annotations

import pathlib
import unittest

from brief_crew.events.models import FrameKind, FrameLevel, UIEventType
from brief_crew.observability.backend import nanoseconds
from brief_crew.observability.langfuse_exporter import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
)
from brief_crew.observability.mapping import COST_CEILING_REASON, INTERRUPTED_REASON
from tests.observability.replay import Recorder, by_role, drive, exporter_for


IDENTITY = {"agent_role": "an authored role", "task_name": "an authored task"}

#: The exact detail keys `RunRegistry._execute` puts on the frame when the
#: ceiling fires. Copied from that branch rather than invented: the reason is a
#: constant the registry owns, and the two figures are floats it reads off the
#: run.
BUDGET_STOP = {
    "reason": "cost_ceiling",
    "cost_usd": 10.4213,
    "ceiling_usd": 10.0,
}


def _mid_run(recorder: Recorder) -> None:
    """A run that is genuinely in flight when the terminal frame arrives."""

    recorder.run_started({"idea": "an idea"})
    recorder.node_started("n1", **IDENTITY)
    recorder.tool_call("n1", "an authored tool", **IDENTITY)
    recorder.add(
        recorder.frames[0].kind.__class__.LLM,
        recorder.frames[0].event_type.__class__.MODEL_CALL,
        "n1",
        {"stage": "before", "call_id": "call-1", "model": "provider/model", **IDENTITY},
    )


class BudgetStopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for()
        recorder = Recorder()
        _mid_run(recorder)
        recorder.run_cancelled(**BUDGET_STOP)
        drive(self.exporter, recorder.frames)
        self.observations = self.backend.observations
        self.run_span = by_role(self.observations, "run")[0]

    def test_the_trace_ends_failed_and_not_cancelled(self) -> None:
        output = self.backend.trace_output[self.run_span.trace_id]
        self.assertEqual(STATUS_FAILED, output["status"])

    def test_the_reason_names_the_ceiling_and_the_figure(self) -> None:
        message = self.run_span.status_message or ""
        self.assertIn("cost ceiling", message)
        self.assertIn("cost_ceiling", message)
        self.assertIn("$10.00", message)
        self.assertIn("$10.4213", message)

    def test_the_run_span_is_at_error_level(self) -> None:
        self.assertEqual("ERROR", self.run_span.level)

    def test_the_run_status_score_says_failed(self) -> None:
        scores = {s.name: s.value for s in self.backend.scores}
        self.assertEqual(STATUS_FAILED, scores["run_status"])
        self.assertEqual(0, scores["run_succeeded"])

    def test_nothing_is_left_without_an_end_time(self) -> None:
        self.assertEqual([], [o.name for o in self.observations if not o.ended])
        for observation in self.observations:
            if observation.as_type != "event":
                self.assertIsNotNone(observation.end_ns, observation.name)

    def test_the_work_still_open_is_ended_at_the_terminal_timestamp(self) -> None:
        """The node and the unfinished model call end where the run did.

        The tool span is deliberately excluded: it had already finished on its
        own frame, and an exporter that re-dated it to the terminal moment
        would be inventing a duration.
        """

        terminal = max(o.end_ns or 0 for o in self.observations)
        node = by_role(self.observations, "node")[0]
        generation = by_role(self.observations, "generation")[0]
        self.assertEqual(terminal, node.end_ns)
        self.assertEqual(terminal, generation.end_ns)
        tool = by_role(self.observations, "tool")[0]
        self.assertLess(tool.end_ns or 0, terminal)


class OperatorCancelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for()
        recorder = Recorder()
        _mid_run(recorder)
        recorder.run_cancelled()
        drive(self.exporter, recorder.frames)
        self.observations = self.backend.observations
        self.run_span = by_role(self.observations, "run")[0]

    def test_a_cancel_with_no_reason_stays_cancelled(self) -> None:
        output = self.backend.trace_output[self.run_span.trace_id]
        self.assertEqual(STATUS_CANCELLED, output["status"])
        self.assertEqual("cancelled by operator", self.run_span.status_message)
        self.assertEqual("WARNING", self.run_span.level)

    def test_open_work_is_ended_and_marked_cancelled(self) -> None:
        spans = [o for o in self.observations if o.as_type in ("span", "tool", "agent")]
        self.assertTrue(spans)
        self.assertEqual([], [o.name for o in spans if not o.ended])
        node = by_role(self.observations, "node")[0]
        self.assertEqual("WARNING", node.level)
        self.assertEqual("cancelled", node.status_message)


class RunFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for()
        recorder = Recorder()
        _mid_run(recorder)
        recorder.run_failed("the upstream refused", error_class="ProviderError")
        drive(self.exporter, recorder.frames)
        self.observations = self.backend.observations
        self.run_span = by_role(self.observations, "run")[0]

    def test_the_trace_ends_failed_with_the_class_and_the_message(self) -> None:
        output = self.backend.trace_output[self.run_span.trace_id]
        self.assertEqual(STATUS_FAILED, output["status"])
        self.assertEqual("ProviderError: the upstream refused", self.run_span.status_message)
        self.assertEqual("ERROR", self.run_span.level)

    def test_open_work_is_ended_at_error_level(self) -> None:
        node = by_role(self.observations, "node")[0]
        self.assertEqual("ERROR", node.level)
        self.assertEqual([], [o.name for o in self.observations if not o.ended])


class CompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({"idea": "an idea"})
        recorder.node_started("n1", **IDENTITY)
        recorder.model_call("n1", "call-1", text="an answer", **IDENTITY)
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({"ok": True})
        drive(self.exporter, recorder.frames)
        self.observations = self.backend.observations
        self.run_span = by_role(self.observations, "run")[0]

    def test_the_trace_ends_completed_with_no_reason(self) -> None:
        output = self.backend.trace_output[self.run_span.trace_id]
        self.assertEqual(STATUS_COMPLETED, output["status"])
        self.assertIsNone(output["reason"])
        self.assertIsNone(self.run_span.level)

    def test_a_completed_run_scores_one(self) -> None:
        scores = {s.name: s.value for s in self.backend.scores}
        self.assertEqual(1, scores["run_succeeded"])
        self.assertEqual(STATUS_COMPLETED, scores["run_status"])


class GatePauseTests(unittest.TestCase):
    def test_a_gate_is_not_terminal_and_leaves_the_spans_open(self) -> None:
        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({"idea": "an idea"})
        recorder.node_started("n1", **IDENTITY)
        recorder.gate_opened("n1", "gate-scope")
        drive(exporter, recorder.frames)
        node = by_role(backend.observations, "node")[0]
        self.assertFalse(node.ended, "a pause must not end the node it paused")
        gates = [o for o in backend.observations if o.name.startswith("gate:")]
        self.assertEqual(["gate:gate-scope"], [o.name for o in gates])
        self.assertEqual({}, backend.trace_output)


class InterruptedRunTests(unittest.TestCase):
    """The THIRD producer of `reason`, and the one that read as a money figure.

    `RunRegistry._fail_interrupted` emits `{"status": "cancelled", "reason":
    "service_restart"}` for a run the process was killed under, and
    `_terminal_of` used to treat any truthy `reason` as the cost ceiling. So an
    orphaned run arrived in Langfuse as "stopped by the run cost ceiling
    (service_restart): estimated $0.0000 against a $0.00 ceiling" - a run that
    breached a **zero-dollar** ceiling, invented, in the surface whose whole
    job is to be believed about money. Both Render services carry
    `autoDeploy: yes`, so every push to `main` can produce one.

    A green module did not see it because no test fed a cancelled frame
    carrying a reason that is not the ceiling. This is that test.
    """

    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for()
        recorder = Recorder()
        _mid_run(recorder)
        recorder.run_cancelled(reason=INTERRUPTED_REASON)
        drive(self.exporter, recorder.frames)
        self.observations = self.backend.observations
        self.run_span = by_role(self.observations, "run")[0]

    def test_it_is_reported_as_an_interruption_and_not_as_a_budget_stop(self) -> None:
        message = self.run_span.status_message or ""
        self.assertIn("restart", message)
        self.assertNotIn("ceiling", message)
        self.assertNotIn("$", message)

    def test_it_ends_failed_because_nobody_chose_it(self) -> None:
        output = self.backend.trace_output[self.run_span.trace_id]
        self.assertEqual(STATUS_FAILED, output["status"])
        self.assertEqual("ERROR", self.run_span.level)
        self.assertEqual([], [o.name for o in self.observations if not o.ended])

    def test_an_unrecognised_reason_stays_a_cancel_and_is_reported(self) -> None:
        """Neither of the two known reasons: it is still a cancel, and the word
        the app used travels rather than being forced into one of them."""

        exporter, backend = exporter_for()
        recorder = Recorder()
        _mid_run(recorder)
        recorder.run_cancelled(reason="quota_exhausted")
        drive(exporter, recorder.frames)
        run_span = by_role(backend.observations, "run")[0]
        self.assertEqual(
            STATUS_CANCELLED, backend.trace_output[run_span.trace_id]["status"]
        )
        self.assertIn("quota_exhausted", run_span.status_message or "")
        self.assertNotIn("ceiling", run_span.status_message or "")


class ReasonConstantMirrorTests(unittest.TestCase):
    """The anti-rot half of a mirror, which this repository builds them with.

    `mapping.py` copies two constants out of `service/registry.py` rather than
    importing them, so that instrumentation pulls no web framework into a
    process that only wanted to write a span. A copy without a test agreed with
    itself at the wrong number for weeks the last time this repository made
    one; this is what makes a rename on either side loud.
    """

    def test_both_reasons_match_the_registrys_own_constants(self) -> None:
        from brief_crew.service import registry as service_registry

        self.assertEqual(service_registry.COST_CEILING_REASON, COST_CEILING_REASON)
        self.assertEqual(service_registry.INTERRUPTED_REASON, INTERRUPTED_REASON)


class FinalMetricsTests(unittest.TestCase):
    """The run's LAST metrics snapshot, which arrives after the terminal frame.

    Measured on a live export: the run span's `run_metrics` read
    `{"reason": "interval", "usage": {"call_count": 3, ...}}` for a run that
    made **6** calls and spent twice that. The app emitted two `METRICS_UPDATED`
    frames - an `interval` one at seq 51 and the `run_completed` one at seq
    **97** - and the terminal `WORKFLOW_END` is seq **96**, so the final figure
    arrives AFTER the frame that ends the run. A span cannot be revised once
    ended on this transport, so the exporter wrote the interval snapshot and
    had nowhere to put the real one.

    The fix defers the run span's own end to `_close_out` - the SAME timestamp,
    the terminal frame's, passed explicitly - so the later snapshot lands
    before the span closes and nothing is re-opened.
    """

    @staticmethod
    def _snapshot(reason: str, calls: int, cost: float) -> dict:
        return {
            "reason": reason,
            "usage": {
                "call_count": calls,
                "cost_usd": cost,
                "total_tokens": calls * 700,
            },
            "frames": {"captured": 90, "dropped": 0},
        }

    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({"idea": "an idea"})
        recorder.node_started("n1", **IDENTITY)
        recorder.model_call("n1", "call-1", **IDENTITY)
        recorder.add(
            FrameKind.METRICS,
            UIEventType.METRICS_UPDATED,
            "workflow",
            self._snapshot("interval", 3, 0.0011385),
        )
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({"ok": True})
        # AFTER the terminal frame, which is the order the registry emits in.
        recorder.add(
            FrameKind.METRICS,
            UIEventType.METRICS_UPDATED,
            "workflow",
            self._snapshot("run_completed", 6, 0.0022745),
        )
        drive(self.exporter, recorder.frames)
        self.frames = recorder.frames
        self.observations = self.backend.observations
        self.run_span = by_role(self.observations, "run")[0]

    def test_the_run_span_carries_the_final_snapshot_not_the_interval_one(self) -> None:
        metrics = self.run_span.metadata["run_metrics"]
        self.assertEqual("run_completed", metrics["reason"])
        self.assertEqual(6, metrics["usage"]["call_count"])

    def test_the_run_span_still_ends_at_the_terminal_frames_timestamp(self) -> None:
        """The thing the deferral must not change.

        The end time is an explicit argument, so moving WHEN the call is made
        cannot move the recorded end - and if it ever did, a run's duration
        would silently become "until the exporter got round to it".
        """

        terminal = next(
            frame
            for frame in self.frames
            if frame.event_type is UIEventType.WORKFLOW_END
        )
        self.assertEqual(nanoseconds(terminal.ts), self.run_span.end_ns)
        self.assertTrue(self.run_span.ended)

    def test_the_late_snapshot_reopens_nothing(self) -> None:
        """A frame after the terminal one must not resurrect a node or add a span.

        One run span, one node span, and every observation ended: a metrics
        frame that opened anything would be a node appearing on the timeline
        after the run finished.
        """

        self.assertEqual(1, len(by_role(self.observations, "run")))
        self.assertEqual(1, len(by_role(self.observations, "node")))
        self.assertEqual([], [o.name for o in self.observations if not o.ended])


class UnhandledTallyOnEveryTerminalTests(unittest.TestCase):
    """C3's tally must reach the trace on the endings that are NOT completion.

    The serializer's ladder drafts the tally onto `FlowFinishedEvent` and
    `FlowFailedEvent`. A run that is cancelled at a gate, stopped by its cost
    ceiling, or orphaned by a service restart ends on a frame `RunRegistry`
    writes directly through `capture.emit` and the ladder never sees - so the
    count reached Langfuse for a completed run and for no other ending, which
    is exactly the half of a run population a blind spot is worst in: the ones
    somebody is investigating.

    The registry now spreads `serializer.unhandled_report()` into all five of
    those terminals. This asserts the exporter's half over one terminal of each
    kind, because the exporter reads the key off ANY run-level frame and that
    is what makes the producer side a one-line change per site rather than a
    branch.
    """

    TALLY = {"KnowledgeQueryStartedEvent": 14, "MemorySaveStartedEvent": 3}

    def _trace_metadata(self, terminal) -> dict:
        exporter, backend = exporter_for()
        recorder = Recorder()
        _mid_run(recorder)
        terminal(recorder)
        drive(exporter, recorder.frames)
        return by_role(backend.observations, "run")[0].metadata

    def test_a_cancelled_run_carries_the_tally(self) -> None:
        metadata = self._trace_metadata(
            lambda r: r.run_cancelled(unhandled_events=self.TALLY)
        )
        self.assertEqual(self.TALLY, metadata["unhandled_event_counts"])

    def test_a_budget_stopped_run_carries_the_tally(self) -> None:
        metadata = self._trace_metadata(
            lambda r: r.run_cancelled(**BUDGET_STOP, unhandled_events=self.TALLY)
        )
        self.assertEqual(self.TALLY, metadata["unhandled_event_counts"])

    def test_an_interrupted_run_carries_the_tally(self) -> None:
        metadata = self._trace_metadata(
            lambda r: r.run_cancelled(
                reason=INTERRUPTED_REASON, unhandled_events=self.TALLY
            )
        )
        self.assertEqual(self.TALLY, metadata["unhandled_event_counts"])

    def test_a_failed_run_carries_the_tally(self) -> None:
        exporter, backend = exporter_for()
        recorder = Recorder()
        _mid_run(recorder)
        recorder.add(
            FrameKind.ERROR,
            UIEventType.WORKFLOW_END,
            "workflow",
            {
                "error": "the upstream refused",
                "error_class": "ProviderError",
                "unhandled_events": self.TALLY,
            },
            level=recorder.frames[0].level.__class__.ERROR,
        )
        drive(exporter, recorder.frames)
        run_span = by_role(backend.observations, "run")[0]
        self.assertEqual(self.TALLY, run_span.metadata["unhandled_event_counts"])
        self.assertEqual(STATUS_FAILED, backend.trace_output[run_span.trace_id]["status"])

    def test_the_registry_spreads_the_tally_into_every_terminal_it_writes(self) -> None:
        """The producer half, read off the source.

        The exporter cannot be tested into carrying a tally nothing sends, and
        the five sites are in a module this package does not import. Reading
        them is the same anti-rot technique the frame-pipeline mapping already
        uses on `events/serializer.py`, and it is what makes "every terminal"
        checkable rather than asserted.
        """

        source = (
            pathlib.Path(__file__).resolve().parents[2]
            / "src"
            / "brief_crew"
            / "service"
            / "registry.py"
        ).read_text(encoding="utf-8")
        terminals = source.count("UIEventType.WORKFLOW_END")
        spreads = source.count("record.capture.serializer.unhandled_report()")
        self.assertGreaterEqual(terminals, 5)
        self.assertEqual(
            terminals,
            spreads,
            "a terminal frame the registry writes does not carry the unhandled "
            "tally; every WORKFLOW_END it emits must spread "
            "`record.capture.serializer.unhandled_report()` into its details",
        )


class RunMetricsFallbackTests(unittest.TestCase):
    """`run_metrics` when the app emitted no METRICS frame at all.

    Measured on the paid `builder-agentfail` run: `trace.metadata.run_metrics`
    was **null**. The app emits a metrics snapshot only when usage MOVES, and
    that run made six model calls of which every one failed - so nothing was
    billed, nothing changed, and no snapshot was ever emitted. A reader opening
    the run most obviously worth reading found no totals, which reads as "the
    exporter lost them" rather than as "there were none".

    `source` distinguishes the two origins, because they are not equally
    trustworthy: `app-snapshot` is the registry's own reconciled view;
    `exporter-tally` is only what this exporter managed to emit.
    """

    def test_a_run_with_no_metrics_frame_gets_the_exporters_own_tally(self) -> None:
        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({"idea": "an idea"})
        recorder.node_started("n1", **IDENTITY)
        recorder.model_call_failed("n1", "call-1", **IDENTITY)
        recorder.run_failed("every call failed", error_class="BadRequestError")
        drive(exporter, recorder.frames)
        metrics = by_role(backend.observations, "run")[0].metadata["run_metrics"]
        self.assertEqual("exporter-tally", metrics["source"])
        self.assertEqual(1, metrics["usage"]["call_count"])
        # Nothing was priced, and zero dollars is a claim nobody made.
        self.assertIsNone(metrics["usage"]["cost_usd"])
        self.assertEqual(STATUS_FAILED, metrics["reason"])

    def test_a_run_with_a_snapshot_still_uses_the_apps_own_figures(self) -> None:
        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({"idea": "an idea"})
        recorder.node_started("n1", **IDENTITY)
        recorder.model_call("n1", "call-1", **IDENTITY)
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({"ok": True})
        recorder.add(
            FrameKind.METRICS,
            UIEventType.METRICS_UPDATED,
            "workflow",
            {
                "reason": "run_completed",
                "usage": {"call_count": 6, "cost_usd": 0.0022745},
                "frames": {"captured": 90, "dropped": 0},
            },
        )
        drive(exporter, recorder.frames)
        metrics = by_role(backend.observations, "run")[0].metadata["run_metrics"]
        self.assertEqual("app-snapshot", metrics["source"])
        self.assertEqual(6, metrics["usage"]["call_count"])

    def test_the_tally_totals_what_the_exporter_actually_emitted(self) -> None:
        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({"idea": "an idea"})
        recorder.node_started("n1", **IDENTITY)
        recorder.model_call("n1", "call-1", prompt_tokens=100, completion_tokens=20, **IDENTITY)
        recorder.model_call("n1", "call-2", prompt_tokens=40, completion_tokens=5, **IDENTITY)
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({"ok": True})
        drive(exporter, recorder.frames)
        metrics = by_role(backend.observations, "run")[0].metadata["run_metrics"]
        self.assertEqual("exporter-tally", metrics["source"])
        self.assertEqual(2, metrics["usage"]["call_count"])
        self.assertEqual(140, metrics["usage"]["prompt_tokens"])
        self.assertEqual(25, metrics["usage"]["completion_tokens"])
        self.assertAlmostEqual(0.002, metrics["usage"]["cost_usd"], places=6)


class BuilderAgentFailureTests(unittest.TestCase):
    """The real frame sequence of a paid failing run, replayed (B3 / D1).

    Copied from `evidence/proof/builder-agentfail-2/frames.ndjson` seq 44-50,
    because the two rounds that got this wrong were both wrong about the SHAPE
    rather than about the intent, and a made-up failure would have passed both
    times:

      44  AGENT_CALL  ERROR  `error`, no class      (crew-level)
      45  AGENT_CALL  ERROR  `error`, no class      <- closes the agent and task
      46  AGENT_CALL  ERROR  `error`, no class
      47  ERROR/NODE_END     `error_class`, text under **`message`**  <- closes NOTHING
      48  NODE_END    ERROR  `error`, no class      <- closes the node
      49  ERROR/WORKFLOW_END `error`, and now a class
      50  ERROR/WORKFLOW_END the registry's copy

    Two things make it hard and both are in that table. The one frame carrying
    the class closes nothing and puts its sentence under a different key; and
    the agent and task close on seq 45, TWO frames before the class exists - so
    no amount of propagating inward from the node can reach them in frame
    order. The exporter holds them open instead, with the timestamp they would
    have ended at, and ends them when the class arrives.
    """

    PROVIDER_MESSAGE = (
        "Error code: 400 - {'error': {'message': \"This endpoint's maximum "
        "context length is 8192 tokens\"}}"
    )

    #: CrewAI stamps four identity keys on every agent, task and LLM event, and
    #: the real seq 44-46 differ in WHICH of them they carry - which is what
    #: decides who closes what. Copied rather than simplified.
    FULL_IDENTITY = {
        **IDENTITY,
        "agent_id": "b0f2f0d0-0000-4000-8000-000000000001",
        "task_id": "44c89b2c-3cf5-45a1-9295-86c83d6e9d90",
    }

    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({"idea": "an idea"})
        recorder.node_started("sound_the_channel", **self.FULL_IDENTITY)
        recorder.add(
            FrameKind.LLM,
            UIEventType.MODEL_CALL,
            "sound_the_channel",
            {"stage": "before", "call_id": "c1", "model": "m", **self.FULL_IDENTITY},
        )
        # seq 44-46, verbatim in shape: a crew-level failure naming a bare
        # `task`, then the TASK failure naming `task_name` and `task_id` and no
        # agent at all - that is the frame that closes the task span and, under
        # it, the agent - then a second crew-level one naming nobody.
        for extra in (
            {"task": "Task"},
            {
                "task_name": IDENTITY["task_name"],
                "task_id": self.FULL_IDENTITY["task_id"],
            },
            {},
        ):
            recorder.add(
                FrameKind.AGENT,
                UIEventType.AGENT_CALL,
                "sound_the_channel",
                {"stage": "error", "error": self.PROVIDER_MESSAGE, **extra},
                level=FrameLevel.ERROR,
            )
        # seq 47: the builder runtime's own frame - the ONLY one with the class,
        # its text under `message`, and it closes nothing.
        recorder.add(
            FrameKind.ERROR,
            UIEventType.NODE_END,
            "sound_the_channel",
            {
                "stage": "error",
                "error_class": "BadRequestError",
                "message": f"BadRequestError: {self.PROVIDER_MESSAGE}",
                "attempt": 1,
                "will_retry": False,
                "routed": False,
            },
            level=FrameLevel.ERROR,
        )
        # seq 48: the frame that actually closes the node.
        recorder.add(
            FrameKind.NODE_STATE,
            UIEventType.NODE_END,
            "sound_the_channel",
            {"stage": "error", "error": self.PROVIDER_MESSAGE},
            level=FrameLevel.ERROR,
        )
        # seq 49: the run's terminal, which since 2026-09-06 names the class.
        recorder.add(
            FrameKind.ERROR,
            UIEventType.WORKFLOW_END,
            "workflow",
            {"error": self.PROVIDER_MESSAGE, "error_class": "BadRequestError"},
            level=FrameLevel.ERROR,
        )
        drive(self.exporter, recorder.frames)
        self.frames = recorder.frames
        self.observations = self.backend.observations

    def test_all_four_observations_name_the_exception_class(self) -> None:
        """The row, in one assertion. Pass 2 had `None` on every one of these."""

        for role in ("agent", "task", "node", "run"):
            with self.subTest(role=role):
                observation = by_role(self.observations, role)[0]
                self.assertEqual(
                    "BadRequestError",
                    observation.metadata.get("error_class"),
                    f"{role} still does not name the class",
                )
                self.assertTrue(
                    (observation.status_message or "").startswith("BadRequestError: "),
                    observation.status_message,
                )

    def test_the_trace_output_names_it_too(self) -> None:
        run_span = by_role(self.observations, "run")[0]
        output = self.backend.trace_output[run_span.trace_id]
        self.assertEqual(STATUS_FAILED, output["status"])
        self.assertEqual("BadRequestError", output["error_class"])
        self.assertTrue(str(output["reason"]).startswith("BadRequestError: "))

    def test_the_class_is_not_prefixed_twice(self) -> None:
        """Seq 47 has already written `BadRequestError: …` into its own text."""

        for observation in self.observations:
            with self.subTest(name=observation.name):
                self.assertNotIn(
                    "BadRequestError: BadRequestError", observation.status_message or ""
                )

    def test_every_span_still_ends_at_its_own_closing_frames_timestamp(self) -> None:
        """The property holding a span open must not cost (D3, and B4).

        `end_time` is explicit on this transport, so a span released three
        frames later still records the moment it actually closed. If that ever
        stopped being true, a held agent would appear to have run until the end
        of the run.
        """

        by_seq = {frame.seq: frame for frame in self.frames}
        agent = by_role(self.observations, "agent")[0]
        task = by_role(self.observations, "task")[0]
        node = by_role(self.observations, "node")[0]
        run = by_role(self.observations, "run")[0]
        # seq 5 is the agent/task closer here (the recorder numbers from 1);
        # find it by shape rather than by a magic number.
        # The agent span is closed by the AGENT frame that NAMES the agent -
        # seq 45 in the paid run. Seq 44 names only a task and seq 46 names
        # nobody, and both become events, which is the shape this test would
        # otherwise assert against the wrong frame.
        agent_closer = next(
            frame
            for frame in self.frames
            if frame.kind is FrameKind.AGENT
            and dict(frame.details).get("stage") == "error"
            and dict(frame.details).get("task_id")
        )
        node_closer = next(
            frame
            for frame in self.frames
            if frame.kind is FrameKind.NODE_STATE
            and frame.event_type is UIEventType.NODE_END
        )
        terminal = next(
            frame
            for frame in self.frames
            if frame.event_type is UIEventType.WORKFLOW_END
        )
        del by_seq
        self.assertEqual(nanoseconds(agent_closer.ts), agent.end_ns)
        self.assertEqual(nanoseconds(agent_closer.ts), task.end_ns)
        self.assertEqual(nanoseconds(node_closer.ts), node.end_ns)
        self.assertEqual(nanoseconds(terminal.ts), run.end_ns)

    def test_nothing_is_left_without_an_end_time(self) -> None:
        self.assertEqual(
            [], [o.name for o in self.observations if o.as_type != "event" and not o.ended]
        )
        for observation in self.observations:
            if observation.as_type != "event":
                self.assertIsNotNone(observation.end_ns, observation.name)

    def test_the_frame_that_closed_nothing_is_still_recorded(self) -> None:
        """Seq 47 carries `attempt`, `will_retry` and `routed` - a retry story
        no other frame tells - so it stays an EVENT as well as being merged."""

        events = [o for o in self.observations if o.as_type == "event"]
        retry = [o for o in events if "attempt" in (o.metadata.get("details") or {})]
        self.assertEqual(1, len(retry))
        self.assertFalse(retry[0].metadata["details"]["will_retry"])

    def test_a_held_span_is_released_even_if_the_node_never_names_a_class(self) -> None:
        """The other exit: the run terminal releases whatever is still held.

        Without it a failing run whose node frame carried no class would leave
        the agent and task open for ever, which is a worse defect than the one
        being fixed.
        """

        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.node_started("n1", **IDENTITY)
        recorder.add(
            FrameKind.AGENT,
            UIEventType.AGENT_CALL,
            "n1",
            {"stage": "error", "error": "no class anywhere", **IDENTITY},
            level=FrameLevel.ERROR,
        )
        recorder.run_failed("no class anywhere", error_class="")
        drive(exporter, recorder.frames)
        spans = [o for o in backend.observations if o.as_type != "event"]
        self.assertEqual([], [o.name for o in spans if not o.ended])
        agent = by_role(backend.observations, "agent")[0]
        self.assertIn("error_class", agent.metadata)
        self.assertIsNone(agent.metadata["error_class"])
