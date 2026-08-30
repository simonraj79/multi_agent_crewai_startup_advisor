"""A flow inside the run is not the run - pinned on both sides.

CrewAI fires `FlowStartedEvent` and `FlowFinishedEvent` for **every** Flow it
runs, and `crewai.experimental.agent_executor.AgentExecutor` is a Flow. The
serializer mapped both events straight onto `RUN_STATE` / `WORKFLOW_START` and
`RUN_STATE` / `WORKFLOW_END`, so a real paid run (`8b5a0a78-...`) streamed this:

    seq=1   node=workflow  WORKFLOW_START  "ValidatorFlow started"   status=running
    seq=6   node=workflow  WORKFLOW_START  "AgentExecutor started"   status=running
    seq=10  node=workflow  WORKFLOW_END    "AgentExecutor completed" status=completed

Ten frames in, when the Scoper - the *first* of six agents - finished, the
Studio client read that third frame, called `setStatus('completed')` and ran the
terminal branch: it stopped the edge animations and dropped the localStorage
pointer that refresh recovery depends on. A `gate_open` moments later put the
status back; nothing put the pointer back.

Nothing caught it because nothing nested. `SyntheticRunner` and
`SyntheticValidatorRunner` emit exactly one `WORKFLOW_START` and one
`WORKFLOW_END` each, so the case did not exist in any double. This module is the
double that nests: hand-built events for the exact production sequence, and a
real two-flow CrewAI kickoff for the shape itself. It also writes
`frontend/tests/fixtures/backendNestedFlowFrames.json`, which
`frontend/tests/nestedFlowRunState.spec.ts` feeds to the real composable, so the
two languages cannot drift apart on this either. Regenerate deliberately with:

    .\\.venv\\Scripts\\python.exe tests\\events\\test_nested_flow_frames.py --write
"""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import unittest

from crewai.events import FlowFailedEvent, FlowFinishedEvent, FlowStartedEvent
from crewai.events.stream_context import add_stream_sink, reset_stream_sinks
from crewai.flow.flow import Flow, start
from crewai.flow.flow_context import current_flow_method_name

from brief_crew.events import (
    FrameBuffer,
    FrameData,
    NodeRegistry,
    StreamSinkAdapter,
)
from brief_crew.events.serializer import FieldBoundedSerializer, FlowScope


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    REPO_ROOT / "frontend" / "tests" / "fixtures" / "backendNestedFlowFrames.json"
)

#: Must equal `RUN_ID` in `frontend/tests/helpers.ts`. The composable drops any
#: frame belonging to another run, so a fixture built under a different id would
#: be ignored in silence rather than failing loudly.
FIXTURE_RUN_ID = "run-under-test"

#: Frozen so the fixture is byte-stable and a diff means a real shape change.
FIXTURE_TS = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)

#: The run's own flow, and the flow CrewAI runs inside it. The second name is
#: what production really sent; it is a fixture value, never a rule. Nothing in
#: `serializer.py` knows this string, and the test below proves it by nesting a
#: differently named flow and getting the same answer.
ROOT_FLOW = "ValidatorFlow"
INNER_FLOW = "AgentExecutor"

#: The node that was executing when the inner flow started. `resolve_event`
#: reads CrewAI's `current_flow_method_name`, which the probe in this module
#: sets the way a live `scope_idea` invocation would.
EXECUTING_NODE = "scope_idea"

FIXTURE_INPUTS = {"idea": "A scheduling assistant for clinics"}
FIXTURE_RESULT = {"verdict": "NEEDS_WORK"}


def _adapter(buffer: FrameBuffer, run_id: str = FIXTURE_RUN_ID) -> StreamSinkAdapter:
    return StreamSinkAdapter(
        run_id=run_id,
        buffer=buffer,
        registry=NodeRegistry(flow_method_nodes={EXECUTING_NODE: EXECUTING_NODE}),
    )


def build_nested_frames() -> tuple[FrameData, ...]:
    """The production sequence: root open, a whole inner flow, root closed."""

    buffer = FrameBuffer(capacity=16)
    adapter = _adapter(buffer)
    adapter(
        None,
        FlowStartedEvent(
            flow_name=ROOT_FLOW,
            inputs=dict(FIXTURE_INPUTS),
            timestamp=FIXTURE_TS,
        ),
    )
    # Everything between here and the reset happens while the root flow is open
    # and one of its methods is on the stack - which is the only way an inner
    # flow can ever start.
    token = current_flow_method_name.set(EXECUTING_NODE)
    try:
        adapter(
            None,
            FlowStartedEvent(flow_name=INNER_FLOW, inputs=None, timestamp=FIXTURE_TS),
        )
        adapter(
            None,
            FlowFinishedEvent(
                flow_name=INNER_FLOW,
                result="completed",
                state={},
                timestamp=FIXTURE_TS,
            ),
        )
        adapter(
            None,
            FlowFailedEvent(
                flow_name=INNER_FLOW,
                error=RuntimeError("the agent gave up"),
                timestamp=FIXTURE_TS,
            ),
        )
    finally:
        current_flow_method_name.reset(token)
    adapter(
        None,
        FlowFinishedEvent(
            flow_name=ROOT_FLOW,
            result=dict(FIXTURE_RESULT),
            state={},
            timestamp=FIXTURE_TS,
        ),
    )
    # An emit that raised is swallowed into `emit_errors` and would leave a
    # short, silently-wrong fixture behind, so refuse to build one.
    stats = buffer.stats()
    if stats.emit_errors or stats.dropped:
        raise AssertionError(f"frame capture lost frames: {stats}")
    return buffer.replay()


def fixture_payload() -> str:
    frames = [frame.to_dict() for frame in build_nested_frames()]
    return json.dumps(frames, indent=2) + "\n"


class NestedFlowFrameTests(unittest.TestCase):
    def setUp(self) -> None:
        frames = build_nested_frames()
        self.assertEqual(len(frames), 5, "one frame per event, in order")
        (
            self.root_started,
            self.inner_started,
            self.inner_finished,
            self.inner_failed,
            self.root_finished,
        ) = frames
        self.frames = frames

    def test_the_root_flow_still_opens_and_closes_the_run(self) -> None:
        """The half that must not regress while the other half is fixed."""

        self.assertEqual(self.root_started.kind.value, "run_state")
        self.assertEqual(self.root_started.event_type.value, "WORKFLOW_START")
        self.assertEqual(self.root_started.details["status"], "running")
        self.assertEqual(self.root_started.node_id, "workflow")

        self.assertEqual(self.root_finished.kind.value, "run_state")
        self.assertEqual(self.root_finished.event_type.value, "WORKFLOW_END")
        self.assertEqual(self.root_finished.details["status"], "completed")
        self.assertEqual(dict(self.root_finished.details["result"]), FIXTURE_RESULT)

    def test_an_inner_flow_never_produces_a_run_terminal_frame(self) -> None:
        """The regression itself, stated as narrowly as the client reads it.

        `useValidatorRun.applyFrame` ends a run three ways, and an inner flow
        must be unable to reach any of them: `kind == "run_state"` carrying a
        terminal `details.status`, `kind == "run_state"` carrying `WORKFLOW_END`
        with no status at all (the fallback), and `kind == "error"`.
        """

        for frame in (self.inner_started, self.inner_finished, self.inner_failed):
            with self.subTest(message=frame.message):
                self.assertNotEqual(frame.kind.value, "run_state", frame.message)
                self.assertNotEqual(frame.kind.value, "error", frame.message)
                self.assertNotIn("status", frame.details)
                self.assertNotIn("WORKFLOW", frame.event_type.value)

    def test_an_inner_flow_is_kept_as_a_nested_agent_frame(self) -> None:
        """Dropped events are lost trace fidelity; these are kept, and marked."""

        self.assertEqual(
            [frame.kind.value for frame in self.frames[1:4]],
            ["agent", "agent", "agent"],
        )
        self.assertEqual(
            [frame.message for frame in self.frames[1:4]],
            [
                f"{INNER_FLOW} started",
                f"{INNER_FLOW} completed",
                f"{INNER_FLOW} failed",
            ],
        )
        for frame in self.frames[1:4]:
            with self.subTest(message=frame.message):
                self.assertIs(frame.details["nested"], True)
                self.assertEqual(frame.details["flow"], INNER_FLOW)
                # Attributed to the node it ran inside, not to `workflow`.
                self.assertEqual(frame.node_id, EXECUTING_NODE)
        self.assertEqual(self.inner_failed.level.value, "ERROR")
        self.assertEqual(self.inner_started.details["stage"], "before")
        self.assertEqual(self.inner_finished.details["stage"], "after")
        self.assertEqual(self.inner_failed.details["stage"], "error")

    def test_the_root_is_the_first_flow_seen_and_not_a_known_name(self) -> None:
        """No denylist. The rule is positional, so it cannot rot upstream.

        Naming CrewAI's inner flow classes would be a guess about a library this
        repo does not own; renaming one there would silently restore the bug.
        Whatever flow opens the run owns the run, and everything else nested
        inside it does not - even a flow nobody here has heard of.
        """

        buffer = FrameBuffer(capacity=16)
        adapter = _adapter(buffer, run_id="unfamiliar-run")
        adapter(None, FlowStartedEvent(flow_name="SomeFutureFlow", inputs=None))
        adapter(None, FlowStartedEvent(flow_name="AnUnknownInnerFlow", inputs=None))
        adapter(
            None,
            FlowFinishedEvent(
                flow_name="AnUnknownInnerFlow", result=None, state={}
            ),
        )
        adapter(
            None,
            FlowFinishedEvent(flow_name="SomeFutureFlow", result=None, state={}),
        )

        frames = buffer.replay()
        self.assertEqual(
            [frame.kind.value for frame in frames],
            ["run_state", "agent", "agent", "run_state"],
        )

    def test_three_concurrent_inner_flows_are_all_nested(self) -> None:
        """The validator fans out into three branches at once.

        Depth counting would need starts and finishes to interleave predictably
        across three worker threads. Matching the root's *name* does not care in
        which order they arrive.
        """

        buffer = FrameBuffer(capacity=32)
        adapter = _adapter(buffer, run_id="fan-out-run")
        adapter(None, FlowStartedEvent(flow_name=ROOT_FLOW, inputs=None))
        for branch in ("market", "sentiment", "feasibility"):
            adapter(None, FlowStartedEvent(flow_name=f"{INNER_FLOW}-{branch}", inputs=None))
        for branch in ("feasibility", "market", "sentiment"):
            adapter(
                None,
                FlowFinishedEvent(
                    flow_name=f"{INNER_FLOW}-{branch}", result=None, state={}
                ),
            )
        adapter(None, FlowFinishedEvent(flow_name=ROOT_FLOW, result=None, state={}))

        kinds = [frame.kind.value for frame in buffer.replay()]
        self.assertEqual(kinds, ["run_state"] + ["agent"] * 6 + ["run_state"])

    def test_a_resumed_root_flow_still_finishes_the_run(self) -> None:
        """The reason the root is remembered by name rather than by "seen once".

        `Flow.resume()` emits a second `FlowStartedEvent` for the same root flow
        - CrewAI emits it unconditionally so that a resumed run is not reported
        as finishing without ever having started. A rule that latched on the
        first start event and refused every later one would classify that resume
        as nested, and then the run's real completion with it: two durable gate
        round trips means the validator resumes twice on the way to a report.
        """

        buffer = FrameBuffer(capacity=32)
        adapter = _adapter(buffer, run_id="resumed-run")
        adapter(None, FlowStartedEvent(flow_name=ROOT_FLOW, inputs=None))
        adapter(None, FlowStartedEvent(flow_name=INNER_FLOW, inputs=None))
        adapter(None, FlowFinishedEvent(flow_name=INNER_FLOW, result=None, state={}))
        # The gate reply lands and CrewAI resumes the same flow.
        adapter(None, FlowStartedEvent(flow_name=ROOT_FLOW, inputs=None))
        adapter(None, FlowFinishedEvent(flow_name=ROOT_FLOW, result="done", state={}))

        frames = buffer.replay()
        self.assertEqual(
            [frame.kind.value for frame in frames],
            ["run_state", "agent", "agent", "run_state", "run_state"],
        )
        self.assertEqual(frames[-1].details["status"], "completed")

    def test_a_finish_with_no_start_behind_it_still_ends_the_run(self) -> None:
        """Fail open, deliberately, on the one direction that strands a run.

        A run recovered into a fresh adapter has no start event in its scope
        yet. Treating that finish as nested would leave a run that can never
        report finishing, which is worse than the frame it replaces; a finish
        does not get to *claim* the root, so it cannot mislabel a later one.
        """

        buffer = FrameBuffer(capacity=16)
        adapter = _adapter(buffer, run_id="recovered-run")
        adapter(None, FlowFinishedEvent(flow_name=ROOT_FLOW, result=None, state={}))

        frame = buffer.replay()[0]
        self.assertEqual(frame.kind.value, "run_state")
        self.assertEqual(frame.details["status"], "completed")

    def test_the_scope_is_per_run(self) -> None:
        """Two runs in one process must not teach each other what the root is."""

        first, second = FrameBuffer(capacity=8), FrameBuffer(capacity=8)
        first_adapter, second_adapter = _adapter(first, "run-a"), _adapter(second, "run-b")
        self.assertIsNot(first_adapter.flow_scope, second_adapter.flow_scope)

        first_adapter(None, FlowStartedEvent(flow_name="FlowA", inputs=None))
        second_adapter(None, FlowStartedEvent(flow_name="FlowB", inputs=None))

        self.assertEqual(first_adapter.flow_scope.root_flow_name, "FlowA")
        self.assertEqual(second_adapter.flow_scope.root_flow_name, "FlowB")
        self.assertEqual(first.replay()[0].kind.value, "run_state")
        self.assertEqual(second.replay()[0].kind.value, "run_state")

    def test_a_bare_serializer_call_treats_its_event_as_the_run(self) -> None:
        """`flow_scope` is optional, and its default must not invent nesting.

        A caller converting one event in isolation has said nothing about a run;
        the only honest reading is that the event it handed over is the run's.
        """

        serializer = FieldBoundedSerializer()
        drafts = serializer.drafts(
            None,
            FlowFinishedEvent(flow_name=INNER_FLOW, result=None, state={}),
            NodeRegistry(),
        )
        self.assertEqual(drafts[0].kind.value, "run_state")

        scope = FlowScope(root_flow_name=ROOT_FLOW)
        nested = serializer.drafts(
            None,
            FlowFinishedEvent(flow_name=INNER_FLOW, result=None, state={}),
            NodeRegistry(),
            flow_scope=scope,
        )
        self.assertEqual(nested[0].kind.value, "agent")

    def test_a_real_nested_crewai_flow_produces_one_run_state_pair(self) -> None:
        """The hand-built events above are a model; this is the thing itself.

        Two trivial Flows, no agent, no model, no network: CrewAI's own runtime
        emits the nested pair, through the real stream sink, and the run gets
        exactly one start and one end. This is the case no double in the suite
        had - and the reason the defect reached production.
        """

        class InnerProbeFlow(Flow):
            @start()
            def go(self) -> str:
                return "inner-done"

        class OuterProbeFlow(Flow):
            @start()
            def scope_idea(self) -> str:
                return str(InnerProbeFlow().kickoff())

        buffer = FrameBuffer(capacity=64)
        adapter = _adapter(buffer, run_id="real-nested-run")
        token = add_stream_sink(adapter)
        try:
            # CrewAI's console listener prints panels with emoji, which a cp1252
            # Windows console cannot encode; the bus catches that, but the noise
            # would land in the test output.
            with redirect_stdout(io.StringIO()):
                OuterProbeFlow().kickoff()
        finally:
            reset_stream_sinks(token)

        frames = buffer.replay()
        run_states = [frame for frame in frames if frame.kind.value == "run_state"]
        self.assertEqual(
            [frame.event_type.value for frame in run_states],
            ["WORKFLOW_START", "WORKFLOW_END"],
            [f"{frame.kind.value}/{frame.message}" for frame in frames],
        )
        self.assertEqual(
            [frame.message for frame in run_states],
            ["OuterProbeFlow started", "OuterProbeFlow completed"],
        )
        nested = [frame for frame in frames if frame.details.get("nested")]
        self.assertEqual(
            [frame.message for frame in nested],
            ["InnerProbeFlow started", "InnerProbeFlow completed"],
        )
        # And attributed where it happened: CrewAI's `current_flow_method_name`
        # still names the outer method while the inner flow starts.
        self.assertEqual({frame.node_id for frame in nested}, {EXECUTING_NODE})

    def test_frontend_fixture_matches_the_serializer(self) -> None:
        """The other half of the pin.

        `frontend/tests/nestedFlowRunState.spec.ts` drives the real composable
        with this file. If the serializer's output moves and the fixture does
        not, the frontend goes on being tested against frames the backend no
        longer emits.
        """

        self.assertTrue(
            FIXTURE_PATH.is_file(),
            f"missing {FIXTURE_PATH}; regenerate with --write",
        )
        self.assertEqual(
            FIXTURE_PATH.read_text(encoding="utf-8"),
            fixture_payload(),
            "the serializer no longer emits the frames the frontend fixture "
            "holds. Review the change on both sides, then regenerate:\n"
            "    .\\.venv\\Scripts\\python.exe "
            "tests\\events\\test_nested_flow_frames.py --write",
        )


def _write_fixture() -> None:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(fixture_payload(), encoding="utf-8")
    print(f"wrote {FIXTURE_PATH}")


if __name__ == "__main__":
    if "--write" in sys.argv:
        _write_fixture()
    else:
        unittest.main()
