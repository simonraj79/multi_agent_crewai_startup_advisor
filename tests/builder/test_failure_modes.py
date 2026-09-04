"""A tool that throws, and where the run ends up - plan 06 criterion 8.

**This file is plan 12's** in the ownership map, and it did not exist. What is
in it is one case: the one plan 06's own criterion 8 names, which is the only
one this wave is entitled to write. Plan 12's remaining failure modes (a
guardrail, a cancel, a cost ceiling) belong to plan 12 and are not here.

The criterion is *"`tool_failure_policy: raise` on an agent with a tool that
throws makes the paired router emit `error` and the run reach the error edge's
target; `warn` completes the step"*, and it is three claims in a row, each of
which can hold while the next fails:

1. **The word travels.** `tool_failure_policy` is written on a document node,
   survives the compiler into `AuthoredAgentSpec`, and reaches both the `Agent`
   and every tool bound to it. `test_tool_factories.py::FailurePolicyTests`
   already proves the last hop; what it could not prove is that the word on the
   document is the word the run uses.
2. **The package honours it.** Measured here rather than assumed:
   `raise` turns a tool's `RuntimeError` into a `ToolExecutionFailedError` out
   of `Crew.kickoff`, and `warn` swallows it and completes. That is CrewAI's
   behaviour, not this repository's, so it is exercised against the real
   `Agent`, `Task` and `Crew` rather than described.
3. **The graph routes it.** The failed step returns normally having written
   `err__<node>`, its paired router fires the error port, and the run reaches
   the error edge's TARGET - which is the half that distinguishes a routed
   failure from a dead one.

**No money and no network.** The LLM is a scripted `BaseLLM` that emits one
ReAct tool call and then a final answer, and the tool raises before it can dial
anything. The agent itself is built by the REAL `DefaultCrewFactories`, so the
policy under test is the one the document set and not one this file passed in;
only its `llm` and its tool body are swapped, and the swapped tool inherits the
policy the real factory computed for the real one.
"""

from __future__ import annotations

import io
import threading
import unittest
from contextlib import redirect_stdout
from typing import Any

from crewai import Agent, Crew, Task
from crewai.llms.base_llm import BaseLLM
from crewai.tools import BaseTool
from crewai.tools.tool_failure import ToolFailurePolicy
from pydantic import BaseModel, Field

from brief_crew.builder.descriptor import build_builder_workflow
from brief_crew.builder.runtime import DefaultCrewFactories
from brief_crew.events import FrameKind
from brief_crew.events.adapter import StreamSinkAdapter
from brief_crew.events.buffer import FrameBuffer
from brief_crew.events.context import CaptureContext, capture_events
from brief_crew.service.builder_runner import BuilderFlowRunner, SyntheticCrewFactories
from brief_crew.service.runner import RunExecution
from tests.builder.test_compiler import (
    attach_edge,
    authored_agent_node,
    input_node,
    output_node,
)
from tests.builder.test_document import document, edge, node as builder_node

IDEA = "a scheduling assistant for clinics"

#: What the tool raises. Distinctive, so a frame carrying it can be identified
#: as THIS failure rather than as any failure.
BOOM = "the upstream API is down"

#: A builtin that needs no credential, so the document is legal with nothing in
#: the vault and the run's refusal is about the tool rather than about a key.
TOOL_ID = "scrape_website"


class ProbeInput(BaseModel):
    query: str = Field(...)


class ThrowingTool(BaseTool):
    """A tool body that fails. Everything else about it is the real one's."""

    name: str = "probe_tool"
    description: str = "Fetch a page. Always fails, in this test."
    args_schema: type[BaseModel] = ProbeInput

    def _run(self, query: str) -> str:
        raise RuntimeError(BOOM)


class ScriptedLLM(BaseLLM):
    """ReAct text tool calling: one tool call, then a final answer.

    The same shape `tests/events/test_tool_frame_attribution.py` uses for its
    live CrewAI probes. It calls nothing and costs nothing.
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
        if self._turn % 2 == 1:
            return (
                "Thought: I need the page.\nAction: probe_tool\n"
                'Action Input: {"query": "clinic scheduling"}'
            )
        return "Thought: enough.\nFinal Answer: the page was unavailable"

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return True


class ThrowingToolFactories(SyntheticCrewFactories):
    """Real `Agent`, real policy, real CrewAI - and a tool body that raises.

    Only the node under test is replaced; every other node still gets the free
    synthetic crew, so the run around the failure is the ordinary one.
    `policies` records what the SPEC said, which is what makes "the word on the
    document is the word the run used" a thing this file can assert rather than
    a thing it arranges.
    """

    def __init__(self, node_id: str = "draft") -> None:
        super().__init__(failures=None)
        self.node_id = node_id
        self.policies: list[str] = []
        self.agents: list[Any] = []

    def authored_agent_crew(self, *, node_id: str, spec: Any) -> Any:
        if node_id != self.node_id:
            return super().authored_agent_crew(node_id=node_id, spec=spec)
        self.policies.append(spec.tool_failure_policy)
        agent = DefaultCrewFactories()._authored_agent(spec, node_id=node_id)
        self.agents.append(agent)
        # The document's word, as the REAL factory resolved it onto the REAL
        # tool. Carried onto the throwing body rather than passed in, so the
        # policy under test cannot be one this file chose.
        built = agent.tools[0]
        agent.tools = [ThrowingTool(tool_failure_policy=built.tool_failure_policy)]
        agent.llm = ScriptedLLM(model="openrouter/probe")
        task = Task(
            description="Fetch the page and summarise it.",
            expected_output="a paragraph",
            agent=agent,
            name=f"{node_id}_task",
        )
        return Crew(agents=[agent], tasks=[task], verbose=False)


def tool_graph(*, policy: str, on_error: str) -> Any:
    """`idea -> draft -> report`, `draft` holding one tool, error port wired."""

    nodes: list[Any] = [
        input_node(),
        authored_agent_node("draft", on_error=on_error, tool_failure_policy=policy),
        builder_node("fetch", "tool", {"tool_id": TOOL_ID, "params": {}}),
        output_node(
            "report",
            source="${state.out__apology}"
            if on_error == "route"
            else "${state.out__draft}",
        ),
    ]
    edges: list[Any] = [
        edge("e1", "idea", "draft"),
        edge("e2", "draft", "report"),
        attach_edge("a1", "fetch", "draft"),
    ]
    if on_error == "route":
        nodes.append(authored_agent_node("apology", source="idea"))
        edges.append(edge("e3", "draft", "apology", source_port="error"))
        edges.append(edge("e4", "apology", "report"))
    return document(nodes, edges)


class ToolFailurePolicyRoutingTests(unittest.TestCase):
    """Criterion 8, end to end: the document's word decides where the run goes."""

    def _run(self, graph: Any) -> tuple[Any, FrameBuffer, ThrowingToolFactories]:
        workflow = build_builder_workflow(graph)
        buffer = FrameBuffer(capacity=512)
        capture = StreamSinkAdapter(
            run_id="run-tool-failure", buffer=buffer, registry=workflow.node_registry
        )
        execution = RunExecution(
            run_id="run-tool-failure",
            inputs={"idea": IDEA},
            capture=capture,
            flow_id="run-tool-failure",
            cancel_requested=threading.Event(),
        )
        factories = ThrowingToolFactories()
        runner = BuilderFlowRunner(workflow, crew_factories=factories)
        with capture_events(
            CaptureContext(run_id="run-tool-failure", adapter=capture)
        ):
            # CrewAI's console listener prints panels a cp1252 console cannot
            # encode, and the noise would land in the test output.
            with redirect_stdout(io.StringIO()):
                try:
                    return runner(execution), buffer, factories
                except Exception as exc:  # noqa: BLE001 - the `fail` arm asserts on it
                    return exc, buffer, factories

    def _errors(self, buffer: FrameBuffer) -> list[dict[str, Any]]:
        return [
            dict(frame.details)
            for frame in buffer.replay(after=0, limit=500)
            if frame.kind is FrameKind.ERROR
            and dict(frame.details).get("stage") == "error"
        ]

    def test_the_documents_word_is_the_word_the_run_uses(self) -> None:
        """Claim 1. Without this the two below could pass on a policy nobody set."""

        _, _, factories = self._run(tool_graph(policy="raise", on_error="route"))
        self.assertEqual(factories.policies, ["raise"])
        self.assertEqual(
            factories.agents[0].tool_failure_policy, ToolFailurePolicy.RAISE
        )
        self.assertEqual(
            factories.agents[0].tools[0].tool_failure_policy, ToolFailurePolicy.RAISE
        )

    def test_raise_reaches_the_error_edges_target(self) -> None:
        """Claims 2 and 3 together, which is the criterion's own sentence.

        The result is the APOLOGY node's output. That is the load-bearing
        assertion: a run that merely survived the failure would return the
        report built from `out__draft`, and a run that died would return
        nothing at all.
        """

        result, buffer, _ = self._run(tool_graph(policy="raise", on_error="route"))
        self.assertNotIsInstance(result, Exception)
        self.assertIn("Synthetic output for apology", str(result))

        errors = self._errors(buffer)
        self.assertTrue(errors, "the failing node emitted no node_error frame")
        self.assertTrue(errors[0]["routed"])
        self.assertFalse(errors[0]["will_retry"])
        # And the frame says what actually went wrong, not just that something did.
        self.assertIn(BOOM, str(errors[0]))

    def test_raise_with_no_error_port_fails_the_run_rather_than_hiding_it(
        self,
    ) -> None:
        """The control for the routing half.

        `route` and `fail` are the same failure and the same frame; only
        `routed` and where the run ends differ. If `raise` did not really
        propagate, this arm would complete and the arm above would be passing
        for the wrong reason.
        """

        raised, buffer, _ = self._run(tool_graph(policy="raise", on_error="fail"))
        self.assertIsInstance(raised, Exception)
        self.assertIn(BOOM, str(raised))
        errors = self._errors(buffer)
        self.assertTrue(errors)
        self.assertFalse(errors[0]["routed"])

    def test_warn_completes_the_step(self) -> None:
        """The other half of the criterion, on the same graph and the same tool.

        The only thing that differs between this and the arm above is the word
        on the document - so the two together are the whole of what
        `tool_failure_policy` means to an author.
        """

        result, buffer, factories = self._run(
            tool_graph(policy="warn", on_error="fail")
        )
        self.assertNotIsInstance(result, Exception)
        self.assertEqual(factories.policies, ["warn"])
        self.assertEqual(
            factories.agents[0].tools[0].tool_failure_policy, ToolFailurePolicy.WARN
        )
        # The agent's own final answer, reached DESPITE the tool having thrown.
        self.assertIn("the page was unavailable", str(result))
        self.assertEqual(
            self._errors(buffer), [], "warn emitted a node_error; it should not"
        )


if __name__ == "__main__":
    unittest.main()
