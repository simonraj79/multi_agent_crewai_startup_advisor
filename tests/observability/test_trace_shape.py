"""Contract sections 1-5: what the trace looks like, and what it is keyed on.

The rows this serves are A1 (one run, one session, keyed on the run id), A2/D5
(two concurrent runs, zero cross-membership), A3 (which flow, whose, in what
mode), B1/B2 (per-agent and per-task grouping), B5 (a generation carries enough
to find a bad output without storing it) and D2 (a raising tool nested under
the agent that called it).

Everything here drives the exporter with the frame shapes the real pipeline
emits, and asserts on the observations a backend would receive.
"""

from __future__ import annotations

import importlib.util
import socket
import unittest
from uuid import uuid4

from brief_crew.events.models import FrameKind, UIEventType
from brief_crew.observability.backend import iso, trace_id_for
from brief_crew.observability.langfuse_exporter import RunFacts
from tests.observability.replay import (
    RUN_ID,
    Recorder,
    by_role,
    drive,
    exporter_for,
)


ROLE = "an authored role"
TASK = "an authored task"
IDENTITY = {"agent_role": ROLE, "task_name": TASK}

#: Contract section 3, in the order the contract lists them. `frame_ts` is the
#: eighth: the section names seven and then names `frame_ts` in the same
#: sentence, so eight keys are what "all seven keys are present" asks for.
SECTION_THREE_KEYS = (
    "run_id",
    "node_id",
    "agent_role",
    "task_name",
    "frame_seq",
    "frame_ts",
    "frame_kind",
    "event_type",
)


class TraceIdentityTests(unittest.TestCase):
    def test_the_trace_id_is_the_run_id_as_32_hex(self) -> None:
        self.assertEqual(RUN_ID.replace("-", ""), trace_id_for(RUN_ID))

    def test_a_run_id_that_is_not_a_uuid_still_gets_a_valid_trace_id(self) -> None:
        derived = trace_id_for("not-a-uuid")
        self.assertEqual(32, len(derived))
        int(derived, 16)

    def test_the_derivation_agrees_with_the_sdk_for_a_non_uuid_seed(self) -> None:
        try:
            from langfuse import Langfuse
        except Exception:  # pragma: no cover - the SDK is in the service extra
            self.skipTest("the langfuse SDK is not installed")
        self.assertEqual(
            Langfuse.create_trace_id(seed="not-a-uuid"), trace_id_for("not-a-uuid")
        )

    def test_the_derivation_is_stable(self) -> None:
        self.assertEqual(trace_id_for(RUN_ID), trace_id_for(RUN_ID))


class TraceFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for(
            facts=RunFacts(
                run_id=RUN_ID,
                workflow_id="a-published-graph",
                session_id="an-app-session",
                user_id="user-42",
                graph_version="v7",
                gates="auto",
                mode="run",
                inputs={"idea": "an idea", "no_gates": True},
            )
        )
        recorder = Recorder()
        recorder.run_started({"idea": "an idea"})
        recorder.run_completed({"ok": True})
        drive(self.exporter, recorder.frames)
        self.run_span = by_role(self.backend.observations, "run")[0]

    def test_the_session_is_the_app_run_id_verbatim(self) -> None:
        self.assertEqual(RUN_ID, self.run_span.session_id)

    def test_the_trace_is_named_for_the_workflow_and_tagged_for_filtering(self) -> None:
        self.assertEqual("a-published-graph", self.run_span.trace_name)
        self.assertEqual(
            ["a-published-graph", "gates:auto", "mode:run"], self.run_span.tags
        )

    def test_the_owner_is_on_the_trace(self) -> None:
        self.assertEqual("user-42", self.run_span.user_id)

    def test_the_metadata_answers_which_flow_whose_and_in_what_mode(self) -> None:
        metadata = self.run_span.metadata
        self.assertEqual(RUN_ID, metadata["run_id"])
        self.assertEqual("a-published-graph", metadata["workflow_id"])
        self.assertEqual("an-app-session", metadata["app_session_id"])
        self.assertEqual("auto", metadata["gates"])
        self.assertEqual("v7", metadata["graph_version"])
        self.assertTrue(metadata["synthetic"])

    def test_a_run_with_no_owner_is_anonymous_rather_than_absent(self) -> None:
        exporter, backend = exporter_for(
            facts=RunFacts(run_id=RUN_ID, workflow_id="w", user_id="anonymous")
        )
        recorder = Recorder()
        recorder.run_started({})
        recorder.run_completed({})
        drive(exporter, recorder.frames)
        self.assertEqual("anonymous", by_role(backend.observations, "run")[0].user_id)

    def test_the_gates_mode_is_read_from_the_reserved_input_key(self) -> None:
        facts = RunFacts.from_record(
            type("R", (), {"run_id": RUN_ID, "inputs": {"idea": "x"}})()
        )
        self.assertEqual("human", facts.gates)
        facts = RunFacts.from_record(
            type("R", (), {"run_id": RUN_ID, "inputs": {"idea": "x", "no_gates": True}})()
        )
        self.assertEqual("auto", facts.gates)


class HierarchyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({"idea": "an idea"})
        recorder.node_started("n1", **IDENTITY)
        recorder.tool_call("n1", "an authored tool", **IDENTITY)
        recorder.model_call("n1", "call-1", text="an answer", **IDENTITY)
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({"ok": True})
        drive(self.exporter, recorder.frames)
        self.frames = recorder.frames
        self.observations = self.backend.observations

    def test_the_shape_is_run_node_task_agent_and_then_the_work(self) -> None:
        run = by_role(self.observations, "run")[0]
        node = by_role(self.observations, "node")[0]
        task = by_role(self.observations, "task")[0]
        agent = by_role(self.observations, "agent")[0]
        tool = by_role(self.observations, "tool")[0]
        generation = by_role(self.observations, "generation")[0]
        self.assertIsNone(run.parent)
        self.assertIs(run, node.parent)
        self.assertIs(node, task.parent)
        self.assertIs(task, agent.parent)
        self.assertIs(agent, tool.parent)
        self.assertIs(agent, generation.parent)

    def test_the_spans_are_named_from_the_frames_and_nothing_else(self) -> None:
        self.assertEqual("n1", by_role(self.observations, "node")[0].name)
        self.assertEqual(TASK, by_role(self.observations, "task")[0].name)
        self.assertEqual(ROLE, by_role(self.observations, "agent")[0].name)
        self.assertEqual("an authored tool", by_role(self.observations, "tool")[0].name)
        self.assertEqual(
            "provider/model", by_role(self.observations, "generation")[0].name
        )

    def test_every_observation_carries_the_section_three_metadata(self) -> None:
        """All eight keys, on EVERY observation, the run span included.

        The run span used to be exempted from six of them - this test said so
        in a `continue` - and a live export bore that out: 11 of 33
        observations were missing keys and the run span carried `run_id` and
        nothing else. Contract section 3 says "present on every observation,
        the `run` span and edge-entered node spans included; a value the frame
        does not carry is `null`, never an absent key", and an absent key is
        exactly what breaks a reader who groups on it: a missing key and a
        null one are the same thing to `.get()` and different things to
        "which observations did this run produce".
        """

        self.assertTrue(self.observations)
        for observation in self.observations:
            with self.subTest(name=observation.name):
                for key in SECTION_THREE_KEYS:
                    self.assertIn(key, observation.metadata)

    def test_the_run_span_names_the_run_rather_than_inheriting_a_node(self) -> None:
        run = by_role(self.observations, "run")[0]
        self.assertEqual(RUN_ID, run.metadata["run_id"])
        self.assertEqual("WORKFLOW_START", run.metadata["event_type"])
        self.assertEqual(1, run.metadata["frame_seq"])

    def test_a_null_identity_is_named_because_a_null_cannot_be_sent(self) -> None:
        """The compensation for a transport that drops a null attribute.

        Section 3 asks for `null`, never an absent key, so that a reader can
        tell "this frame named no agent" from "the exporter forgot". Measured
        against the live API: an observation whose `agent_role` was set to
        `None` came back with the KEY MISSING, because the SDK maps a `None`
        metadata value to a `None` OTel attribute and OpenTelemetry drops those
        rather than sending a null.

        `null_fields` is always present and names exactly the section-3 keys
        the frame did not carry, so the distinction survives a transport that
        cannot carry a null. Empty when nothing is null - which is the half
        that makes it readable: an absent key that is NOT listed here is a
        defect, and that is now checkable.
        """

        for observation in self.observations:
            with self.subTest(name=observation.name):
                self.assertIn("null_fields", observation.metadata)
                named = [
                    key
                    for key in observation.metadata["null_fields"].split(",")
                    if key
                ]
                for key in named:
                    self.assertIsNone(observation.metadata[key])
                for key in ("agent_role", "task_name"):
                    if observation.metadata[key] is None:
                        self.assertIn(key, named)

    def test_an_edge_entered_node_carries_the_identity_keys_as_null(self) -> None:
        """The other half of section 3, and the shape that was missing them.

        A node whose span is opened by the EDGE frame that arrives at it - the
        no-cost path emits one before every node start - has no agent and no
        task to name yet. The keys must still be there and read `null`, or a
        reader cannot tell "this node named no agent" from "this exporter
        forgot to say".
        """

        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.add(
            FrameKind.EDGE_TAKEN,
            UIEventType.EDGE_PROCESS,
            "n2",
            {"from": "n1", "port": "ok"},
        )
        recorder.node_started("n2", **IDENTITY)
        recorder.node_ended("n2", **IDENTITY)
        recorder.run_completed({})
        drive(exporter, recorder.frames)
        node = by_role(backend.observations, "node")[0]
        self.assertEqual("n1", node.metadata["entered_from"])
        for key in SECTION_THREE_KEYS:
            self.assertIn(key, node.metadata)
        self.assertEqual("agent_role,task_name", node.metadata["null_fields"])

    def test_a_tool_carries_the_opening_frames_sequence_not_the_closing_one(
        self,
    ) -> None:
        """Section 3: "for a TOOL that is the `before` frame, never the `after`".

        Measured on a live export as the other way round: a tool span starting
        at 19.729 carried `frame_ts` 21.728, the after-frame's, so `frame_ts`
        contradicted the span's own start by the tool's entire duration and a
        reader joining frames to spans on `frame_seq` reached the wrong frame.
        The closing frame's OWN facts - status, result count - still land,
        which is what this asserts second.
        """

        tool = by_role(self.observations, "tool")[0]
        opening = next(
            frame
            for frame in self.frames
            if frame.kind is FrameKind.TOOL
            and dict(frame.details).get("stage") == "before"
        )
        closing = next(
            frame
            for frame in self.frames
            if frame.kind is FrameKind.TOOL
            and dict(frame.details).get("stage") == "after"
        )
        self.assertNotEqual(opening.seq, closing.seq)
        self.assertEqual(opening.seq, tool.metadata["frame_seq"])
        self.assertEqual(iso(opening.ts), tool.metadata["frame_ts"])
        self.assertEqual("ok", tool.metadata["tool_status"])
        self.assertEqual(3, tool.metadata["result_count"])

    def test_an_agent_hangs_off_the_node_when_no_task_is_named(self) -> None:
        """The contract's first fall-through, and the no-cost path's own shape.

        The synthetic runners stamp an agent role but raise no task boundary of
        their own, so this is not a hypothetical branch - it is what every free
        proof run exercises.
        """

        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.node_started("n1", agent_role=ROLE)
        recorder.model_call("n1", "call-1", agent_role=ROLE)
        recorder.node_ended("n1", agent_role=ROLE)
        recorder.run_completed({})
        drive(exporter, recorder.frames)
        self.assertEqual([], by_role(backend.observations, "task"))
        node = by_role(backend.observations, "node")[0]
        agent = by_role(backend.observations, "agent")[0]
        self.assertIs(node, agent.parent)

    def test_an_observation_hangs_off_the_node_when_nobody_is_named(self) -> None:
        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.node_started("n1")
        recorder.model_call("n1", "call-1")
        recorder.node_ended("n1")
        recorder.run_completed({})
        drive(exporter, recorder.frames)
        self.assertEqual([], by_role(backend.observations, "agent"))
        node = by_role(backend.observations, "node")[0]
        self.assertIs(node, by_role(backend.observations, "generation")[0].parent)


class GenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.node_started("n1", **IDENTITY)
        recorder.model_call(
            "n1",
            "call-1",
            model="provider/a-model",
            prompt_tokens=1200,
            completion_tokens=340,
            cost_usd=0.00512,
            response_id="gen-abc123",
            text="an answer of some length",
            **IDENTITY,
        )
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({})
        drive(self.exporter, recorder.frames)
        self.generation = by_role(self.backend.observations, "generation")[0]

    def test_the_model_the_tokens_and_the_estimate_are_all_there(self) -> None:
        self.assertEqual("provider/a-model", self.generation.model)
        self.assertEqual(
            {"input": 1200, "output": 340, "total": 1540}, self.generation.usage_details
        )
        self.assertEqual({"total": 0.00512}, self.generation.cost_details)

    def test_the_cost_says_where_it_came_from(self) -> None:
        self.assertEqual("app-estimate", self.generation.metadata["cost_source"])

    def test_the_provider_generation_id_is_carried_for_reconciliation(self) -> None:
        self.assertEqual("gen-abc123", self.generation.metadata["response_id"])

    def test_a_bad_output_can_be_traced_without_the_output(self) -> None:
        metadata = self.generation.metadata
        self.assertEqual(ROLE, metadata["agent_role"])
        self.assertEqual(TASK, metadata["task_name"])
        self.assertEqual("stop", metadata["finish_reason"])
        self.assertEqual(len("an answer of some length"), metadata["completion_chars"])
        self.assertEqual(64, len(metadata["prompt_fingerprint"]))
        self.assertEqual(
            "node|agent_role|task_name|model", metadata["prompt_fingerprint_basis"]
        )

    def test_a_model_with_no_price_on_file_carries_no_cost_rather_than_zero(self) -> None:
        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.node_started("n1", **IDENTITY)
        recorder.model_call("n1", "call-1", cost_usd=None, **IDENTITY)
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({})
        drive(exporter, recorder.frames)
        generation = by_role(backend.observations, "generation")[0]
        self.assertIsNone(generation.cost_details)
        self.assertIsNotNone(generation.usage_details)


class ToolTests(unittest.TestCase):
    def test_a_raising_tool_is_an_error_under_the_agent_that_called_it(self) -> None:
        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.node_started("n1", **IDENTITY)
        recorder.tool_call(
            "n1", "an authored tool", error="HTTPError: 402 payment required", **IDENTITY
        )
        recorder.model_call("n1", "call-1", **IDENTITY)
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({})
        drive(exporter, recorder.frames)
        tool = by_role(backend.observations, "tool")[0]
        agent = by_role(backend.observations, "agent")[0]
        self.assertIs(agent, tool.parent)
        self.assertEqual("ERROR", tool.level)
        self.assertIn("402", tool.status_message or "")
        self.assertTrue(tool.ended)
        # What the agent did next is still visible after the failure.
        self.assertEqual(1, len(by_role(backend.observations, "generation")))

    def test_the_tool_status_and_result_count_come_from_the_frame(self) -> None:
        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.node_started("n1", **IDENTITY)
        recorder.tool_call("n1", "an authored tool", status="rate_limited", **IDENTITY)
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({})
        drive(exporter, recorder.frames)
        tool = by_role(backend.observations, "tool")[0]
        self.assertEqual("rate_limited", tool.metadata["tool_status"])
        self.assertEqual(3, tool.metadata["result_count"])
        self.assertEqual("tool", tool.metadata["observation_role"])


class ConcurrencyTests(unittest.TestCase):
    """Rows A2 and D5: two runs, two traces, zero cross-membership."""

    OTHER = "99999999-8888-4777-8666-555555555555"

    def setUp(self) -> None:
        self.exporter, self.backend = exporter_for()
        self.exporter.begin_run(RunFacts(run_id=RUN_ID, workflow_id="first"))
        self.exporter.begin_run(RunFacts(run_id=self.OTHER, workflow_id="second"))
        first = Recorder(RUN_ID)
        second = Recorder(self.OTHER)
        first.run_started({})
        second.run_started({})
        first.node_started("n1", **IDENTITY)
        second.node_started("n2", agent_role="another role", task_name="another task")
        first.model_call("n1", "a-1", **IDENTITY)
        second.model_call("n2", "b-1", agent_role="another role", task_name="another task")
        first.node_ended("n1", **IDENTITY)
        second.node_ended("n2", agent_role="another role", task_name="another task")
        first.run_completed({})
        second.run_completed({})
        # Interleaved, one frame at a time, as two concurrent runs would arrive.
        from brief_crew.observability.langfuse_exporter import _Item

        for left, right in zip(first.frames, second.frames):
            self.exporter._absorb(_Item(run_id=RUN_ID, frames=(left,)))
            self.exporter._absorb(_Item(run_id=self.OTHER, frames=(right,)))
        self.exporter._settle(force=True)

    def test_each_run_gets_its_own_trace(self) -> None:
        traces = {o.trace_id for o in self.backend.observations}
        self.assertEqual({trace_id_for(RUN_ID), trace_id_for(self.OTHER)}, traces)

    def test_no_observation_sits_in_the_wrong_trace(self) -> None:
        mismatches = [
            (o.name, o.metadata.get("run_id"), o.trace_id)
            for o in self.backend.observations
            if trace_id_for(str(o.metadata.get("run_id"))) != o.trace_id
        ]
        self.assertEqual([], mismatches)

    def test_no_span_is_parented_across_traces(self) -> None:
        crossed = [
            o.name
            for o in self.backend.observations
            if o.parent is not None and o.parent.trace_id != o.trace_id
        ]
        self.assertEqual([], crossed)

    def test_each_run_reports_its_own_counters(self) -> None:
        first = self.exporter.stats(RUN_ID)
        second = self.exporter.stats(self.OTHER)
        self.assertEqual(RUN_ID, first["run_id"])
        self.assertEqual(self.OTHER, second["run_id"])
        self.assertEqual(first["frames_enqueued"], second["frames_enqueued"])


class RedeliveryTests(unittest.TestCase):
    def test_a_replayed_frame_adds_nothing(self) -> None:
        """A reconnect replays the ring; a trace must not double.

        Observation ids on this transport are OpenTelemetry span ids and cannot
        be derived from a frame, so the contract's idempotence is enforced on
        the sequence number instead - which is gapless and increasing per run.
        """

        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.node_started("n1", **IDENTITY)
        recorder.model_call("n1", "call-1", **IDENTITY)
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({})
        drive(exporter, recorder.frames)
        first = len(backend.observations)
        drive(exporter, recorder.frames)
        self.assertEqual(first, len(backend.observations))
        self.assertEqual(1, len(by_role(backend.observations, "generation")))


class FoldedFrameTests(unittest.TestCase):
    def test_an_edge_is_a_field_on_the_node_it_arrived_at(self) -> None:
        from brief_crew.events.models import FrameKind, UIEventType

        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.add(
            FrameKind.EDGE_TAKEN,
            UIEventType.EDGE_PROCESS,
            "n2",
            {"stage": "traversal", "from": "n1", "to": "n2", "port": None},
        )
        recorder.node_started("n2", **IDENTITY)
        recorder.node_ended("n2", **IDENTITY)
        recorder.run_completed({})
        drive(exporter, recorder.frames)
        nodes = by_role(backend.observations, "node")
        self.assertEqual(1, len(nodes), "an edge must not open a second node span")
        self.assertEqual("n1", nodes[0].metadata["entered_from"])

    def test_a_streamed_answer_is_counted_onto_its_own_call(self) -> None:
        from brief_crew.events.models import FrameKind, UIEventType

        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.node_started("n1", **IDENTITY)
        recorder.add(
            FrameKind.LLM,
            UIEventType.MODEL_CALL,
            "n1",
            {"stage": "before", "call_id": "call-1", "model": "m", **IDENTITY},
        )
        for _ in range(3):
            recorder.add(
                FrameKind.LLM,
                UIEventType.MODEL_CALL,
                "n1",
                {"stage": "chunk", "call_id": "call-1", "chunk": "abc", **IDENTITY},
            )
        recorder.add(
            FrameKind.LLM,
            UIEventType.MODEL_CALL,
            "n1",
            {"stage": "after", "call_id": "call-1", "model": "m", "response_id": None, **IDENTITY},
        )
        recorder.add(
            FrameKind.TOKEN,
            UIEventType.MODEL_CALL,
            "n1",
            {
                "call_id": "call-1",
                "model": "m",
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                "cost_usd": 0.1,
                **IDENTITY,
            },
        )
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({})
        drive(exporter, recorder.frames)
        generations = by_role(backend.observations, "generation")
        self.assertEqual(1, len(generations))
        self.assertEqual(3, generations[0].metadata["stream_chunks"])


@unittest.skipUnless(
    importlib.util.find_spec("langfuse") is not None, "the langfuse SDK is not installed"
)
class RootSpanTests(unittest.TestCase):
    """Contract section 1: the `run` SPAN has NO parent observation.

    The bug is the SDK's and no recording double can have it, so this
    reproduces the SDK's own construction on an OpenTelemetry provider this
    test owns. Asking for a span in a CHOSEN trace is the only way to fix the
    trace id, and `Langfuse._create_remote_parent_span` answers that request by
    GENERATING a random parent span id when none is given
    (`_client/client.py:1750-1753`); `start_observation` then starts the span
    inside that non-recording context and the exporter writes
    `parent_span_id = format_span_id(span.parent.span_id)`
    (`span_exporter.py:526`, `:681-685`) regardless of the
    `langfuse.internal.as_root` flag it also sets.

    Measured on a live export: the run span came back from
    `/api/public/observations` with a `parentObservationId` naming an id no
    observation in the trace carries, **zero** observations had a null parent,
    and the tooling's hierarchy walk reported the whole tree ORPHANED.

    A LOCAL provider rather than a `Langfuse` client, deliberately. The SDK
    sets the process-wide OpenTelemetry tracer provider the first time any
    client is built and reuses whatever is there afterwards, so a client built
    inside a suite inherits whatever the rest of the suite did to that global -
    including, measured in the full run, a tracer that answers with
    `NonRecordingSpan`. A test of a parent id that depends on which other tests
    ran first is a test that certifies nothing.
    """

    def setUp(self) -> None:
        from opentelemetry.sdk.trace import TracerProvider

        self.provider = TracerProvider(shutdown_on_exit=False)
        self.addCleanup(self.provider.shutdown)
        self.tracer = self.provider.get_tracer("a test")

    def _span_the_sdk_way(self, trace_id: str):
        """`start_observation(trace_context={"trace_id": ...})`, reproduced.

        The three statements are the SDK's own, in its order
        (`client.py:713-728`): make a non-recording remote parent carrying the
        chosen trace id and a RANDOM span id, enter it, start the span.
        """

        from opentelemetry import trace as otel_trace_api
        from opentelemetry.sdk.trace.id_generator import RandomIdGenerator

        parent = otel_trace_api.NonRecordingSpan(
            otel_trace_api.SpanContext(
                trace_id=int(trace_id, 16),
                span_id=RandomIdGenerator().generate_span_id(),
                trace_flags=otel_trace_api.TraceFlags(0x01),
                is_remote=False,
            )
        )
        with otel_trace_api.use_span(parent):
            return self.tracer.start_span(name="run")

    def test_the_sdk_gives_the_run_span_a_parent_that_is_not_there(self) -> None:
        """The premise, asserted rather than assumed.

        If a later SDK stops fabricating the parent, this fails and the fix
        below becomes dead code that somebody should delete - which is the only
        way a workaround for another package's behaviour ever gets removed.
        """

        span = self._span_the_sdk_way(trace_id_for(RUN_ID))
        self.assertIsNotNone(span.parent)
        self.assertNotEqual(span.context.span_id, span.parent.span_id)

    def test_detaching_leaves_a_root_that_keeps_the_chosen_trace_id(self) -> None:
        from opentelemetry.trace import format_trace_id

        from brief_crew.observability.backend import _detach_fabricated_parent

        trace_id = trace_id_for(RUN_ID)
        span = self._span_the_sdk_way(trace_id)

        class _Observation:
            pass

        observation = _Observation()
        observation._otel_span = span
        _detach_fabricated_parent(observation)

        self.assertIsNone(span.parent, "the run span still names a parent")
        # The half that makes the first half non-trivial: dropping the parent
        # must not drop the trace id with it, or every run would land in a
        # trace nobody can compute from a run id.
        self.assertEqual(trace_id, format_trace_id(span.context.trace_id))

    def test_it_is_total_against_a_span_it_cannot_edit(self) -> None:
        """Nothing in the instrumentation path may raise into a run (E2).

        An SDK that renames `_otel_span`, or hands back a span type with no
        writable parent, must leave the observation exactly as it was.
        """

        from brief_crew.observability.backend import _detach_fabricated_parent

        class _NoSpan:
            pass

        _detach_fabricated_parent(_NoSpan())

        class _FrozenSpan:
            __slots__ = ()

        class _Observation:
            pass

        observation = _Observation()
        observation._otel_span = _FrozenSpan()
        _detach_fabricated_parent(observation)


@unittest.skipUnless(
    importlib.util.find_spec("langfuse") is not None, "the langfuse SDK is not installed"
)
class RootSpanThroughTheBackendTests(unittest.TestCase):
    """The same property through `LangfuseBackend.open_run`, end to end.

    Nothing is sent: the client points at a port nothing is listening on and
    the keys authenticate against nothing. The public key is per-test because
    the SDK caches one resource manager per key for the life of the process -
    sharing one would mean asserting against whichever test built it first.
    """

    def setUp(self) -> None:
        from brief_crew.observability.backend import LangfuseBackend

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        self.backend = LangfuseBackend(
            public_key=f"pk-lf-not-a-real-key-{uuid4().hex}",
            secret_key="sk-lf-not-a-real-key",
            base_url=f"http://127.0.0.1:{port}",
            environment="synthetic",
            flush_interval=5.0,
            flush_at=512,
            timeout=1,
        )
        self.addCleanup(self.backend.close)

    def _open(self):
        return self.backend.open_run(
            trace_id=trace_id_for(RUN_ID),
            name="a workflow",
            metadata={"run_id": RUN_ID},
            user_id="anonymous",
            session_id=RUN_ID,
            tags=["a workflow"],
            payload_input=None,
        )

    def _require_recording(self, observation) -> object:
        span = observation._otel_span
        if not hasattr(span, "parent"):
            # A `NonRecordingSpan`: the process-wide OpenTelemetry provider the
            # SDK attached to is not recording, so this client would export
            # nothing and there is no parent id to assert about. Skipped rather
            # than passed, because passing here would be a green tick for a
            # question that was never asked.
            self.skipTest(
                "the langfuse client attached to a non-recording OpenTelemetry "
                "provider; the parent-id property is asserted deterministically "
                "in RootSpanTests"
            )
        return span

    def test_the_run_span_has_no_parent_and_keeps_the_chosen_trace_id(self) -> None:
        from opentelemetry.trace import format_trace_id

        span = self._require_recording(self._open())
        self.assertIsNone(
            span.parent,
            "the run span carries a parent that no observation in the trace is",
        )
        self.assertEqual(trace_id_for(RUN_ID), format_trace_id(span.context.trace_id))

    def test_a_child_of_the_run_span_still_has_one(self) -> None:
        """The control. An exporter that detached every parent would pass the
        test above and produce a trace of unrelated observations."""

        run = self._open()
        run_span = self._require_recording(run)
        child = self.backend.open_child(run, name="n1", as_type="span", metadata={})
        child_span = self._require_recording(child)
        self.assertIsNotNone(child_span.parent)
        self.assertEqual(run_span.context.span_id, child_span.parent.span_id)
