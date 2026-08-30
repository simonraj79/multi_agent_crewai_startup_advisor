"""Tool frames must say which node ran the tool, and what the tool answered.

The first end-to-end paid run produced 148 frames and could not explain itself.
Every `tool` frame looked like this:

    seq=47  kind=tool  node_id=unattributed  "analyze_community_sentiment started"
            details={"stage": "before", "tool": "analyze_community_sentiment",
                     "args": {...}}
    seq=50  kind=tool  node_id=unattributed  "analyze_community_sentiment completed"
            details={"stage": "after", "tool": "analyze_community_sentiment",
                     "output": "<4096 characters of the results array>"}

Two separate defects, and the run scored `D=1` on "0 usable threads" and `F=1`
on thin repository evidence with neither of them answerable from the trace.

**Attribution.** Not one tool frame joined to `research_market`,
`research_sentiment` or `research_feasibility`. `NodeRegistry.resolve` fell back
to CrewAI's `current_flow_method_name`, and a tool does not run inside the flow
method that owns it: `crewai.experimental.agent_executor.AgentExecutor` is
itself a `Flow`, so at tool time that variable names one of *its* methods -
`execute_tool_action` on the text path, `execute_native_tool` on the native
function-calling path. Neither is a node in this graph, so every tool, model and
token frame went to the visible quarantine node, taking the per-node cost
readout with it. `registry.current_node_scope` is the fix, and the live probes
at the bottom of this module are the runs that would have caught it.

**Payload.** Every tool in `brief_crew.tools` returns a JSON envelope carrying
`status`, `query`, `retrieved_at`, `result_count`, `results` and `notes`, and
the frame kept only a 4096-character prefix of the serialized whole - which is
`results`, because `results` sits ahead of `notes` in the document. The four
fields that would have named the defect never survived. Diagnosing the run meant
re-running the tools by hand to discover the queries were prose sent to keyword
APIs. `FieldBoundedSerializer.tool_envelope` lifts the head and drops the body.

**Three calls, not three copies.** That run showed three `started` and three
`completed` frames per tool. `test_three_tool_frames_are_three_real_calls` is
why they are not deduplicated: CrewAI emits exactly one pair per invocation, and
a task guardrail retry re-runs the agent, tool calls included. Three frames are
three real calls, and now they can be told apart, because each one carries the
query it ran.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import threading
import time
from types import SimpleNamespace
from typing import Any
import unittest

from crewai import Agent, Crew, Task
from crewai.events import (
    LLMCallCompletedEvent,
    MethodExecutionFinishedEvent,
    MethodExecutionStartedEvent,
    ToolUsageErrorEvent,
    ToolUsageFinishedEvent,
    ToolUsageStartedEvent,
)
from crewai.events.stream_context import (
    add_stream_sink,
    publish_stream_event,
    reset_stream_sinks,
)
from crewai.flow.flow import Flow, listen, start
from crewai.llms.base_llm import BaseLLM
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from brief_crew.events import (
    CaptureContext,
    FrameBuffer,
    FrameData,
    NodeRegistry,
    QUARANTINE_NODE_ID,
    StreamSinkAdapter,
    capture_events,
)
from brief_crew.events.registry import current_node_scope
from brief_crew.events.serializer import FieldBoundedSerializer


#: The three research branches, exactly as `service/graph.py` declares them.
BRANCH_NODES = ("research_market", "research_sentiment", "research_feasibility")
SCOPE_NODE = "scope_idea"
FLOW_NAME = "ValidatorFlow"

#: One of CrewAI's own AgentExecutor methods. A fixture value, never a rule:
#: nothing in `registry.py` knows this string, and the live probes below reach
#: the same answer through whichever method the installed version really uses.
INNER_METHOD = "execute_tool_action"

TS = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)


def envelope(
    *,
    status: str = "ok",
    tool: str = "analyze_community_sentiment",
    query: str = "clinic scheduling",
    result_count: int | None = None,
    results: list[dict[str, Any]] | None = None,
    notes: str = "",
) -> str:
    """The shape `brief_crew.tools` returns, built the way the tools build it."""

    rows = results if results is not None else []
    return json.dumps(
        {
            "status": status,
            "tool": tool,
            "query": query,
            "retrieved_at": "2026-08-30T11:59:00Z",
            "result_count": result_count if result_count is not None else len(rows),
            "results": rows,
            "notes": notes,
        },
        ensure_ascii=True,
    )


def registry(*node_ids: str) -> NodeRegistry:
    return NodeRegistry(flow_method_nodes={name: name for name in node_ids})


def adapter_for(
    buffer: FrameBuffer, *node_ids: str, run_id: str = "tool-run"
) -> StreamSinkAdapter:
    return StreamSinkAdapter(run_id=run_id, buffer=buffer, registry=registry(*node_ids))


def enter(adapter: StreamSinkAdapter, method_name: str) -> None:
    """Start a flow method the way CrewAI does, through the real event."""

    adapter(
        None,
        MethodExecutionStartedEvent(
            flow_name=FLOW_NAME,
            method_name=method_name,
            state={},
            params=None,
            timestamp=TS,
        ),
    )


def started(
    tool: str = "analyze_community_sentiment", **args: Any
) -> ToolUsageStartedEvent:
    return ToolUsageStartedEvent(
        tool_name=tool,
        tool_args=args or {"query": "clinic scheduling"},
        agent_role="Sentiment analyst",
        task_name="sentiment_task",
        timestamp=TS,
    )


def finished(
    output: Any, tool: str = "analyze_community_sentiment", **args: Any
) -> ToolUsageFinishedEvent:
    return ToolUsageFinishedEvent(
        tool_name=tool,
        tool_args=args or {"query": "clinic scheduling"},
        agent_role="Sentiment analyst",
        task_name="sentiment_task",
        output=output,
        started_at=TS,
        finished_at=TS + timedelta(milliseconds=1500),
        timestamp=TS,
    )


def tool_frames(buffer: FrameBuffer) -> list[FrameData]:
    return [frame for frame in buffer.replay() if frame.kind.value == "tool"]


class ScopedTestCase(unittest.TestCase):
    """Start every case inside no node, and leave the suite as it was found.

    `current_node_scope` is context state, and `unittest` runs a whole suite in
    one context. Production gets this from `capture_events`, which clears the
    scope when it installs a run's sink; a test that reaches past that has to
    clear it itself or it hands the next module a node it never entered.
    """

    def setUp(self) -> None:
        token = current_node_scope.set(None)
        self.addCleanup(current_node_scope.reset, token)


class ToolFrameAttributionTests(ScopedTestCase):
    """Part one: which node ran the tool."""

    def test_a_tool_frame_joins_the_node_whose_method_is_running(self) -> None:
        """The defect itself, stated as narrowly as the graph reads it."""

        buffer = FrameBuffer(capacity=32)
        adapter = adapter_for(buffer, SCOPE_NODE, *BRANCH_NODES)
        enter(adapter, "research_sentiment")
        adapter(None, started())
        adapter(None, finished(envelope()))
        adapter(
            None,
            ToolUsageErrorEvent(
                tool_name="analyze_community_sentiment",
                tool_args={"query": "q"},
                error="boom",
                timestamp=TS,
            ),
        )

        frames = tool_frames(buffer)
        self.assertEqual([frame.node_id for frame in frames], ["research_sentiment"] * 3)
        self.assertEqual(buffer.stats().emit_errors, 0)

    def test_a_tool_frame_raised_inside_crewais_own_flow_still_joins(self) -> None:
        """The exact production shape: an inner flow method is on the stack.

        CrewAI's `AgentExecutor` is a Flow, so between the branch method and the
        tool there is always a `MethodExecution*` pair for a method this graph
        never declared. Attribution has to survive it.
        """

        buffer = FrameBuffer(capacity=32)
        adapter = adapter_for(buffer, SCOPE_NODE, *BRANCH_NODES)
        enter(adapter, "research_feasibility")
        enter(adapter, INNER_METHOD)  # CrewAI's, not ours
        adapter(None, started(tool="assess_technical_feasibility"))
        adapter(
            None,
            finished(
                envelope(tool="assess_technical_feasibility"),
                tool="assess_technical_feasibility",
            ),
        )

        self.assertEqual(
            [frame.node_id for frame in tool_frames(buffer)],
            ["research_feasibility", "research_feasibility"],
        )

    def test_an_inner_flow_method_frame_is_still_quarantined(self) -> None:
        """The half of the attribution fix that must NOT happen.

        An inner `MethodExecution*` pair names a method, so it is a statement
        about that method's node lifecycle. Re-attributing it to the enclosing
        research node would emit NODE_START / NODE_END on that node dozens of
        times per agent, and `useValidatorRun.applyNodeState` does not take
        `completed` back - the same asymmetry `FlowScope` guards for flows.
        """

        buffer = FrameBuffer(capacity=32)
        adapter = adapter_for(buffer, SCOPE_NODE, *BRANCH_NODES)
        enter(adapter, "research_market")
        enter(adapter, INNER_METHOD)
        adapter(
            None,
            MethodExecutionFinishedEvent(
                flow_name="AgentExecutor",
                method_name=INNER_METHOD,
                state={},
                result="tool_completed",
                timestamp=TS,
            ),
        )

        inner = [frame for frame in buffer.replay() if INNER_METHOD in frame.message]
        self.assertEqual([frame.node_id for frame in inner], [QUARANTINE_NODE_ID] * 2)
        self.assertEqual([frame.kind.value for frame in inner], ["node_state"] * 2)

    def test_a_tool_frame_with_no_method_behind_it_is_still_quarantined(self) -> None:
        """Fail visible. A tool nobody can place belongs in the badge."""

        buffer = FrameBuffer(capacity=16)
        adapter = adapter_for(buffer, SCOPE_NODE, *BRANCH_NODES, run_id="unscoped-run")
        with capture_events(CaptureContext(run_id="unscoped-run", adapter=adapter)):
            adapter(None, started())

        self.assertEqual(tool_frames(buffer)[0].node_id, QUARANTINE_NODE_ID)

    def test_a_run_never_inherits_the_previous_runs_node(self) -> None:
        """The service executes runs on a pooled worker thread.

        `asyncio.run` copies the calling thread's context into the flow, so a
        second run on a reused thread would start inside whatever node the last
        run left behind. `capture_events` clears the scope on the way in - the
        same place it installs the sink, because it is the same fact: this
        context now belongs to one run and to nothing before it.
        """

        outgoing_buffer = FrameBuffer(capacity=16)
        outgoing = adapter_for(outgoing_buffer, *BRANCH_NODES, run_id="run-a")
        with capture_events(CaptureContext(run_id="run-a", adapter=outgoing)):
            enter(outgoing, "research_feasibility")
            outgoing(None, started())
        self.assertEqual(tool_frames(outgoing_buffer)[-1].node_id, "research_feasibility")

        incoming_buffer = FrameBuffer(capacity=16)
        incoming = adapter_for(incoming_buffer, *BRANCH_NODES, run_id="run-b")
        with capture_events(CaptureContext(run_id="run-b", adapter=incoming)):
            incoming(None, started())

        self.assertEqual(tool_frames(incoming_buffer)[0].node_id, QUARANTINE_NODE_ID)

    def test_a_node_scope_is_never_borrowed_across_graphs(self) -> None:
        """Brief Flow and the validator share one process and one ContextVar.

        A registry only answers with nodes it declares, so a scope entered by
        one workflow cannot leak a node id into the other's frames.
        """

        buffer = FrameBuffer(capacity=16)
        validator = adapter_for(buffer, *BRANCH_NODES, run_id="validator-run")
        enter(validator, "research_market")

        brief_buffer = FrameBuffer(capacity=16)
        brief = adapter_for(
            brief_buffer, "scrape_web", "write_brief", run_id="brief-run"
        )
        brief(None, started(tool="scrape_website"))

        self.assertEqual(tool_frames(brief_buffer)[0].node_id, QUARANTINE_NODE_ID)

    def test_model_and_token_frames_are_attributed_too(self) -> None:
        """The same fallback, and the reason per-node cost read zero.

        `RunRegistry._record_usage` bills a `token` frame to `frame.node_id`.
        Model calls happen inside the AgentExecutor exactly as tool calls do, so
        every token frame of the paid run was billed to `unattributed`.
        """

        buffer = FrameBuffer(capacity=32)
        adapter = adapter_for(buffer, SCOPE_NODE, *BRANCH_NODES)
        enter(adapter, "research_market")
        adapter(
            None,
            LLMCallCompletedEvent(
                call_id="call-1",
                messages=[],
                response="ok",
                call_type="llm_call",
                model="openrouter/anthropic/claude-sonnet-4.5",
                usage={"prompt_tokens": 100, "completion_tokens": 20},
                timestamp=TS,
            ),
        )

        billed = [frame for frame in buffer.replay() if frame.kind.value == "token"]
        self.assertEqual([frame.node_id for frame in billed], ["research_market"])
        self.assertEqual(billed[0].details["usage"]["total_tokens"], 120)


class ToolEnvelopeCaptureTests(ScopedTestCase):
    """Part two: what the tool actually answered."""

    def _finished_details(self, output: Any) -> dict[str, Any]:
        buffer = FrameBuffer(capacity=16)
        adapter = adapter_for(buffer, *BRANCH_NODES)
        enter(adapter, "research_sentiment")
        adapter(None, finished(output))
        self.assertEqual(buffer.stats().emit_errors, 0)
        return dict(tool_frames(buffer)[-1].details)

    def test_the_envelope_head_reaches_the_frame(self) -> None:
        """`status`, `query`, `result_count`, `notes` - the four that mattered."""

        details = self._finished_details(
            envelope(
                status="empty",
                query="clinic scheduling",
                results=[],
                notes="Algolia returned no stories; the query may be too narrow",
            )
        )
        self.assertEqual(details["tool_status"], "empty")
        self.assertEqual(details["query"], "clinic scheduling")
        self.assertEqual(details["result_count"], 0)
        self.assertIn("too narrow", details["notes"])
        self.assertEqual(details["retrieved_at"], "2026-08-30T11:59:00Z")

    def test_the_started_frame_carries_the_query_it_was_asked_to_run(self) -> None:
        """The value the first paid run failed on, present before the answer.

        A run that dies mid-branch has no `completed` frame at all, and the
        query is exactly what a reader needs from the one frame that exists.
        """

        buffer = FrameBuffer(capacity=16)
        adapter = adapter_for(buffer, *BRANCH_NODES)
        enter(adapter, "research_sentiment")
        adapter(None, started(query="a scheduling assistant that helps clinics book"))
        adapter(
            None,
            ToolUsageErrorEvent(
                tool_name="analyze_community_sentiment",
                tool_args={"query": "clinic booking"},
                error="HTTP 429",
                timestamp=TS,
            ),
        )

        frames = tool_frames(buffer)
        self.assertEqual(
            frames[0].details["query"], "a scheduling assistant that helps clinics book"
        )
        self.assertEqual(frames[1].details["query"], "clinic booking")

    def test_a_large_results_array_never_reaches_the_frame(self) -> None:
        """The bound. The ring holds 2,000 frames; `results` holds page bodies."""

        rows = [
            {"url": f"https://example.com/{i}", "text": "x" * 20_000} for i in range(50)
        ]
        payload = envelope(results=rows, notes="fifty pages")
        self.assertGreater(len(payload), 1_000_000)

        details = self._finished_details(payload)
        rendered = json.dumps(details)
        self.assertNotIn("xxxxxxxxxx", rendered)
        self.assertNotIn("example.com", rendered)
        self.assertNotIn("output", details)
        self.assertEqual(details["result_count"], 50)
        self.assertEqual(details["output_chars"], len(payload))
        # Every field the frame gained is bounded by `max_tool_field`, so the
        # whole annotation stays smaller than the single clipped string it
        # replaced.
        self.assertLess(len(rendered), FieldBoundedSerializer().limits.max_string)

    def test_an_output_too_large_to_parse_is_not_parsed(self) -> None:
        """`max_tool_output` is a bound on work done on the run's own thread."""

        serializer = FieldBoundedSerializer()
        payload = envelope(
            results=[{"text": "y" * serializer.limits.max_tool_output}]
        )
        self.assertGreater(len(payload), serializer.limits.max_tool_output)

        details = self._finished_details(payload)
        self.assertNotIn("tool_status", details)
        self.assertLessEqual(len(details["output"]), serializer.limits.max_string)

    def test_a_non_json_tool_output_degrades_to_the_raw_output(self) -> None:
        """Not every tool is one of ours, and a failing one returns prose."""

        for output in (
            "I could not complete that request.",
            "{not json at all",
            json.dumps({"unrelated": "document"}),
            json.dumps(["a", "list"]),
            b"\x00\x01raw bytes",
            None,
            12345,
        ):
            with self.subTest(output=repr(output)[:40]):
                details = self._finished_details(output)
                self.assertNotIn("tool_status", details)
                self.assertIn("output", details)

    def test_an_output_that_cannot_be_read_at_all_never_breaks_the_run(self) -> None:
        """A capture callback that raises loses the frame and counts an error.

        The whole point of the spine is that it cannot cost a run anything, so
        an object that explodes on inspection still has to produce a frame.
        """

        class Hostile:
            def __repr__(self) -> str:
                raise RuntimeError("no")

            def __str__(self) -> str:
                raise RuntimeError("no")

            def model_dump(self, **_: Any) -> Any:
                raise RuntimeError("no")

        details = self._finished_details(Hostile())
        self.assertIn("output", details)
        self.assertEqual(details["output"], "<Hostile>")

    def test_the_tool_reported_query_wins_over_the_arguments(self) -> None:
        """A tool that broadened its own query says so; believe the tool."""

        buffer = FrameBuffer(capacity=16)
        adapter = adapter_for(buffer, *BRANCH_NODES)
        enter(adapter, "research_sentiment")
        adapter(
            None,
            finished(envelope(query="clinic scheduling"), query="a long prose question"),
        )

        self.assertEqual(tool_frames(buffer)[0].details["query"], "clinic scheduling")


# --------------------------------------------------------------------------
# The probes. Real CrewAI, no network and no model: a scripted `BaseLLM` and a
# tool that returns a canned envelope. The hand-built events above are a model
# of the production sequence; these are the sequence itself, and they are the
# only thing that can catch the day CrewAI renames the method the old fallback
# used to read.
# --------------------------------------------------------------------------


ENVELOPE = envelope(
    tool="probe_tool",
    query="clinic scheduling",
    results=[{"url": f"https://example.com/{i}", "text": "x" * 4000} for i in range(3)],
    notes="two of five stories had no comments",
)


class ProbeInput(BaseModel):
    query: str = Field(...)


class ProbeTool(BaseTool):
    name: str = "probe_tool"
    description: str = "Return a canned research envelope."
    args_schema: type[BaseModel] = ProbeInput

    def _run(self, query: str) -> str:
        return ENVELOPE


class TextToolCallingLLM(BaseLLM):
    """ReAct text tool calling: one tool call, then a final answer."""

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
        if self._turn % 2 == 1:
            return (
                "Thought: I need evidence.\nAction: probe_tool\n"
                'Action Input: {"query": "clinic scheduling"}'
            )
        return "Thought: enough.\nFinal Answer: done"

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return True


class NativeToolCallingLLM(BaseLLM):
    """The other executor path, which runs under a differently named method."""

    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> Any:
        self._turn = getattr(self, "_turn", 0) + 1
        if self._turn == 1:
            return [
                SimpleNamespace(
                    id="call_1",
                    function=SimpleNamespace(
                        name="probe_tool",
                        arguments=json.dumps({"query": "clinic scheduling"}),
                    ),
                )
            ]
        return "done"

    def supports_function_calling(self) -> bool:
        return True

    def supports_stop_words(self) -> bool:
        return False


def probe_crew(llm: BaseLLM, *, guardrails: list[Any] | None = None) -> Crew:
    agent = Agent(
        role="Sentiment analyst",
        goal="Find community evidence.",
        backstory="A probe.",
        tools=[ProbeTool()],
        llm=llm,
        verbose=False,
        max_iter=6,
    )
    task = Task(
        description="Call probe_tool.",
        expected_output="done",
        agent=agent,
        name="sentiment_task",
        guardrails=guardrails or [],
    )
    return Crew(agents=[agent], tasks=[task], verbose=False)


class LiveCrewAIProbeTests(ScopedTestCase):
    """No hand-built double can catch this; only CrewAI's own runtime can."""

    def _run_branch(self, llm: BaseLLM) -> FrameBuffer:
        class BranchFlow(Flow):
            @start()
            def research_sentiment(self) -> str:
                return str(probe_crew(llm).kickoff())

        buffer = FrameBuffer(capacity=256)
        adapter = adapter_for(buffer, *BRANCH_NODES, run_id="probe-run")
        token = add_stream_sink(adapter)
        try:
            # CrewAI's console listener prints emoji panels a cp1252 console
            # cannot encode; the noise would land in the test output.
            with redirect_stdout(io.StringIO()):
                BranchFlow().kickoff()
        finally:
            reset_stream_sinks(token)
        return buffer

    def test_a_real_text_tool_call_is_attributed_and_carries_its_envelope(self) -> None:
        buffer = self._run_branch(TextToolCallingLLM(model="openrouter/probe"))
        frames = tool_frames(buffer)

        self.assertEqual(
            [frame.node_id for frame in frames], ["research_sentiment"] * 2
        )
        self.assertEqual(
            [frame.details["query"] for frame in frames], ["clinic scheduling"] * 2
        )
        completed = frames[-1].details
        self.assertEqual(completed["tool_status"], "ok")
        self.assertEqual(completed["result_count"], 3)
        self.assertNotIn("output", completed)
        self.assertEqual(buffer.stats().emit_errors, 0)

    def test_the_native_function_calling_path_is_attributed_too(self) -> None:
        """A different inner method name reaches the same node.

        The text path runs under `execute_tool_action` and this one under
        `execute_native_tool`. Two names, one CrewAI version apart, is why the
        join is positional rather than a table of method names.
        """

        buffer = self._run_branch(NativeToolCallingLLM(model="openrouter/probe"))

        self.assertEqual(
            [frame.node_id for frame in tool_frames(buffer)],
            ["research_sentiment", "research_sentiment"],
        )

    def test_three_concurrent_branches_do_not_borrow_each_others_node(self) -> None:
        """The fan-out is three sibling `@listen` methods running at once.

        Any per-adapter "last node seen" would hand all six frames to whichever
        branch started last. An `asyncio` task copies its context at creation,
        so each branch carries its own.
        """

        buffer = FrameBuffer(capacity=256)
        adapter = adapter_for(
            buffer, SCOPE_NODE, *BRANCH_NODES, run_id="fan-out-run"
        )

        def branch(name: str, delay: float) -> str:
            # Sleep first, so all three method starts land before any tool
            # event: a leaking scope would be visible rather than lucky.
            time.sleep(delay)
            publish_stream_event(None, started(tool=f"{name}_tool", query=name))
            publish_stream_event(
                None,
                finished(
                    envelope(tool=f"{name}_tool", query=name),
                    tool=f"{name}_tool",
                    query=name,
                ),
            )
            return name

        class FanOutFlow(Flow):
            @start()
            def scope_idea(self) -> str:
                return "scoped"

            @listen(scope_idea)
            def research_market(self, _: Any) -> str:
                return branch("research_market", 0.30)

            @listen(scope_idea)
            def research_sentiment(self, _: Any) -> str:
                return branch("research_sentiment", 0.20)

            @listen(scope_idea)
            def research_feasibility(self, _: Any) -> str:
                return branch("research_feasibility", 0.10)

        token = add_stream_sink(adapter)
        try:
            with redirect_stdout(io.StringIO()):
                FanOutFlow().kickoff()
        finally:
            reset_stream_sinks(token)

        frames = tool_frames(buffer)
        self.assertEqual(len(frames), 6, [frame.message for frame in frames])
        for frame in frames:
            with self.subTest(message=frame.message):
                # Each frame names its own branch in the tool name, so a
                # borrowed node cannot pass as the right one.
                self.assertEqual(
                    frame.node_id, frame.details["tool"].removesuffix("_tool")
                )
                self.assertEqual(frame.details["query"], frame.node_id)
        self.assertEqual(buffer.stats().emit_errors, 0)

    def test_three_tool_frames_are_three_real_calls(self) -> None:
        """Why the duplicates are not deduplicated: they are not duplicates.

        The paid run showed three `started` and three `completed` per tool. Both
        executor paths emit exactly one pair per invocation (the two tests
        above: two frames each, from one call). The multiplier is real work: a
        guardrail rejection re-runs the whole agent loop, tool calls included.
        Collapsing them would hide two thirds of a branch's spend and two thirds
        of its queries.

        That paid run predates the retry cap. `Task.guardrail_max_retries`
        defaults to 3 in CrewAI (`crewai/task.py:279`), which is what produced
        the three attempts observed; the six validator tasks now set it to 2 in
        `crews/validator_crew/config/tasks.yaml`, so a live branch bottoms out
        at two attempts per guardrail. The frame arithmetic under test is
        unchanged either way - this note exists so the "defaults to 3" reasoning
        is not mistaken for the shipped value.
        """

        attempts = {"n": 0}

        def flaky(output: Any) -> tuple[bool, str]:
            attempts["n"] += 1
            if attempts["n"] < 3:
                return False, "source_urls must mirror sources[].url"
            return True, str(getattr(output, "raw", output))

        buffer = FrameBuffer(capacity=256)
        adapter = adapter_for(buffer, *BRANCH_NODES, run_id="retry-run")
        raw: list[str] = []

        def counting_sink(source: Any, event: Any) -> None:
            del source
            if isinstance(event, ToolUsageStartedEvent | ToolUsageFinishedEvent):
                raw.append(type(event).__name__)

        tokens = [add_stream_sink(adapter), add_stream_sink(counting_sink)]
        try:
            with redirect_stdout(io.StringIO()):
                probe_crew(
                    TextToolCallingLLM(model="openrouter/probe"), guardrails=[flaky]
                ).kickoff()
        finally:
            for token in reversed(tokens):
                reset_stream_sinks(token)

        self.assertEqual(attempts["n"], 3)
        self.assertEqual(raw.count("ToolUsageStartedEvent"), 3)
        self.assertEqual(raw.count("ToolUsageFinishedEvent"), 3)
        # One frame per event: the spine adds no copies of its own.
        self.assertEqual(len(tool_frames(buffer)), 6)


class CaptureThreadSafetyTests(ScopedTestCase):
    def test_the_scope_is_per_context_not_per_adapter(self) -> None:
        """The same adapter, two threads, two different declared nodes."""

        buffer = FrameBuffer(capacity=64)
        adapter = adapter_for(buffer, *BRANCH_NODES, run_id="threaded-run")
        barrier = threading.Barrier(2)

        def run(node: str) -> None:
            enter(adapter, node)
            barrier.wait(timeout=5)
            adapter(None, started(tool=f"{node}_tool"))

        threads = [
            threading.Thread(target=run, args=(node,)) for node in BRANCH_NODES[:2]
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        frames = tool_frames(buffer)
        self.assertEqual(len(frames), 2)
        for frame in frames:
            self.assertEqual(frame.node_id, frame.details["tool"].removesuffix("_tool"))


if __name__ == "__main__":
    unittest.main()
