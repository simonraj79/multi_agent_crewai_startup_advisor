"""A tool that throws, an MCP server that is not there, and D8's six modes.

THREE PLANS SHARE THIS FILE, and the split is worth reading before adding to it.
The first two sections are plan 06 criterion 8 (`tool_failure_policy: raise`)
and plan 07 criterion 8 (`test_mcp_unreachable`), which named plan 12's file
before plan 12 wrote it. The third is 12 D8's own table - the five failure modes
that RUN, the one that never does, and the sentinel that must not leak from any
of them - and it starts at `SYNTHETIC FAILURE MODES` below.

They are together rather than in three files because they are one question asked
three ways: what does a builder graph do when a step fails, and what is a person
told. Nothing here is shared between the sections but the fixtures, and each
says which plan it answers to.

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

import importlib.util
import io
import json
import os
import threading
import unittest
import zipfile
from contextlib import redirect_stdout
from typing import Any
from unittest.mock import patch

from crewai import Agent, Crew, Task
from crewai.llms.base_llm import BaseLLM
from crewai.tools import BaseTool
from crewai.tools.tool_failure import ToolFailurePolicy
from pydantic import BaseModel, Field

from brief_crew.builder import mcp as mcp_module
from brief_crew.builder import structural_problems
from brief_crew.builder.descriptor import build_builder_workflow
from brief_crew.builder.runtime import DefaultCrewFactories
from brief_crew.events import FrameKind
from brief_crew.events.adapter import StreamSinkAdapter
from brief_crew.events.buffer import FrameBuffer
from brief_crew.events.context import CaptureContext, capture_events
from brief_crew.config import RUN_RESULT_BODY_KEYS
from brief_crew.service.builder_runner import (
    SYNTHETIC_FAILURE_REASONS,
    BuilderFlowRunner,
    SyntheticCrewFactories,
    parse_synthetic_failures,
)
from brief_crew.service.runner import RunExecution
from tests.builder.test_compiler import (
    attach_edge,
    authored_agent_node,
    input_node,
    output_node,
)
from tests.builder.test_document import document, edge, node as builder_node
from tests.service.identities import SECRET, AuthenticatedTwoUserCase

IDEA = "a scheduling assistant for clinics"
#: Plan 12's half needs `fastapi` for the service cases; the two above do not.
FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
BODY_KEY = RUN_RESULT_BODY_KEYS[0]

#: `mcp` ships with CrewAI's MCP support; if it is ever absent the MCP arm skips
#: rather than fails, because a missing optional package is not a defect here.
#:
#: TWO MORE NAMES JOINED THIS BLOCK when the three plans' branches met in one
#: file. `MCP_CONNECTION_ERROR_CLASS` and `tests/service/mcp_fixture_server.py`
#: are plan 07's, and only `McpUnreachableTests` reads either - so importing
#: them at module scope made the WHOLE file unimportable in a tree that had one
#: branch and not another, taking plan 06's and plan 12's sections down with a
#: dependency neither has. The guard is the shape this file already used for
#: the package itself; delete it once every branch has landed and the names are
#: unconditionally there.
try:  # pragma: no cover
    import mcp as _mcp  # noqa: F401

    from brief_crew.builder.mcp import MCP_CONNECTION_ERROR_CLASS
    from tests.service import mcp_fixture_server as fixture

    MCP_AVAILABLE = True
except Exception:  # pragma: no cover
    MCP_CONNECTION_ERROR_CLASS = "mcp_connection_failed"
    fixture = None  # type: ignore[assignment]
    MCP_AVAILABLE = False

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




# --------------------------------------------------------------------------
# Plan 07 criterion 8's second half: `test_mcp_unreachable`.
# --------------------------------------------------------------------------
#
# The criterion is *"`MCPConnectionFailedEvent` during a run produces a
# `node_error` frame and, under `raise`, the error edge fires"*, and plan 07
# called it *"honestly two things"*. `tests/events/test_mcp_frames.py` is the
# mapping - the event to the frame. This is the other thing: that the failure
# reaches the graph.
#
# **CrewAI raises the event itself here.** `MCPClient` emits
# `MCPConnectionFailedEvent` from its own failure path and then raises
# `MCPConnectionError`, so pointing the real resolver at a port nothing is
# listening on produces BOTH halves for real: the event that becomes the frame,
# and the exception that reaches `_attempted` and its error port. Nothing is
# simulated and nothing is hand-raised.
#
# "Under `raise`" is read as the node's `on_error`, not as
# `tool_failure_policy`: an MCP connection failure is raised while an agent's
# clients are being resolved, before any tool runs, so no tool policy is in the
# path. `on_error: route` and `on_error: fail` are both asserted, which is what
# that clause distinguishes.


class McpUnreachableFactories(SyntheticCrewFactories):
    """Resolves a REAL MCP config against a dead port, then would kick off.

    The resolver call is `builder/mcp.py`'s own `_default_resolver` - the one
    the discovery route uses - so this exercises the same code path a run's
    agent construction does, and CrewAI emits its own connection events on the
    way through.
    """

    def __init__(self, node_id: str = "draft") -> None:
        super().__init__(failures=None)
        self.node_id = node_id
        self.attempts = 0

    def authored_agent_crew(self, *, node_id: str, spec: Any) -> Any:
        if node_id != self.node_id:
            return super().authored_agent_crew(node_id=node_id, spec=spec)
        self.attempts += 1
        record = mcp_module.McpServerRecord(
            id="mcp_deadbeef1234",
            user_id="user_alice",
            label="a server that is not there",
            transport="http",
            url=f"http://127.0.0.1:{fixture.free_port()}/mcp",
        )
        config = mcp_module.server_config(record)
        # Raises `MCPConnectionError`, and emits `MCPConnectionFailedEvent` on
        # the way out. Both are CrewAI's.
        list(mcp_module._default_resolver(config))
        raise AssertionError("the dead port answered, which cannot happen")


def mcp_graph(*, on_error: str) -> Any:
    """The same shape as `tool_graph`, with an `mcp` node instead of a `tool`."""

    nodes: list[Any] = [
        input_node(),
        authored_agent_node("draft", on_error=on_error),
        builder_node(
            "servers",
            "mcp",
            {"server_id": "mcp_deadbeef1234", "tool_names": ["search"]},
        ),
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
        attach_edge("a1", "servers", "draft"),
    ]
    if on_error == "route":
        nodes.append(authored_agent_node("apology", source="idea"))
        edges.append(edge("e3", "draft", "apology", source_port="error"))
        edges.append(edge("e4", "apology", "report"))
    return document(nodes, edges)


@unittest.skipUnless(MCP_AVAILABLE, "the mcp package is not installed")
class McpUnreachableTests(unittest.TestCase):
    """`test_mcp_unreachable` - plan 07 criterion 8's error-edge half."""

    def _run(self, graph: Any) -> tuple[Any, FrameBuffer]:
        workflow = build_builder_workflow(graph)
        buffer = FrameBuffer(capacity=512)
        capture = StreamSinkAdapter(
            run_id="run-mcp-down", buffer=buffer, registry=workflow.node_registry
        )
        execution = RunExecution(
            run_id="run-mcp-down",
            inputs={"idea": IDEA},
            capture=capture,
            flow_id="run-mcp-down",
            cancel_requested=threading.Event(),
        )
        runner = BuilderFlowRunner(
            workflow, crew_factories=McpUnreachableFactories()
        )
        with capture_events(CaptureContext(run_id="run-mcp-down", adapter=capture)):
            with redirect_stdout(io.StringIO()):
                try:
                    return runner(execution), buffer
                except Exception as exc:  # noqa: BLE001 - the `fail` arm asserts on it
                    return exc, buffer

    @staticmethod
    def _errors(buffer: FrameBuffer) -> list[dict[str, Any]]:
        return [
            dict(frame.details)
            for frame in buffer.replay(after=0, limit=500)
            if frame.kind is FrameKind.ERROR
        ]

    def test_the_connection_failure_becomes_a_node_error_frame_in_a_real_run(
        self,
    ) -> None:
        """The event is CrewAI's own, raised by its own client, in a real run."""

        _, buffer = self._run(mcp_graph(on_error="route"))
        classes = [details.get("error_class") for details in self._errors(buffer)]
        self.assertIn(
            MCP_CONNECTION_ERROR_CLASS,
            classes,
            "no frame named the MCP connection failure; the run's error frames "
            f"were {classes}",
        )
        named = [
            details
            for details in self._errors(buffer)
            if details.get("error_class") == MCP_CONNECTION_ERROR_CLASS
        ][0]
        self.assertEqual(named["stage"], "error")
        self.assertTrue(named["server"], "the frame did not say which server")

    def test_under_route_the_error_edges_target_runs(self) -> None:
        result, buffer = self._run(mcp_graph(on_error="route"))
        self.assertNotIsInstance(result, Exception)
        self.assertIn("Synthetic output for apology", str(result))
        # The node-level frame beside the connection-level one: the run's own
        # accounting of the attempt, which the MCP frame deliberately does not
        # carry because a connection is not an attempt.
        node_level = [
            details
            for details in self._errors(buffer)
            if "routed" in details
        ]
        self.assertTrue(node_level)
        self.assertTrue(node_level[0]["routed"])

    def test_with_no_error_port_the_run_fails(self) -> None:
        """The control: without it the arm above could pass on a run that never
        met the failure at all."""

        raised, buffer = self._run(mcp_graph(on_error="fail"))
        self.assertIsInstance(raised, Exception)
        node_level = [
            details for details in self._errors(buffer) if "routed" in details
        ]
        self.assertTrue(node_level)
        self.assertFalse(node_level[0]["routed"])


# ==========================================================================
# SYNTHETIC FAILURE MODES - 12 D8, criteria 3 and 4
# ==========================================================================
#
# The table in `.agent/plans/12-error-handling.md` D8 names six ways a builder
# graph fails, and for each a trigger, what the canvas says, what the log says
# and what the author does next. This is the Python half of that table.
#
# **Five of the six RUN and one never does**, and that asymmetry is the whole
# argument of the plan. A bad key, a tool timeout, a refusal, a malformed answer
# and a rate limit are all discovered by executing something; a cyclic graph is
# refused by `bounds.py` at validate and again at publish, so there is no run,
# no node and no frame - which is why `SYNTHETIC_FAILURE_REASONS` has five
# entries and not six. Flowise's equivalent check (`docs/flowise-notes.md` §1)
# drops the edge silently on the canvas and finds out at run time; this one is a
# sentence with the closing edge named in it, before anything bills.
#
# Every mode is one value of `SYNTHETIC_FAILURE`, read PER INSTANCE, so a critic
# triggering all six from a browser restarts nothing. `SYNTHETIC_FAILURE_NODE`
# says which node when the entry does not, which is what makes the knob usable
# on a graph whose ids the person setting it did not write.
#
# `test_no_secret_in_any_failure` is criterion 4, and it is the one that would
# go vacuous most easily: a synthetic factory that never resolves a credential
# would pass a leak test having never held the secret. `ResolvingFactories`
# builds the REAL `Agent` and so the REAL `LLM` - which resolves the key and
# costs nothing, because construction calls no model - and the test asserts it
# held the sentinel BEFORE asserting the sentinel is nowhere else.
#
# No cost: every billable node here is built by the double `SYNTHETIC=1`
# installs, and the two places a real `Agent` is constructed call no model.

#: D8's five running modes, as `(SYNTHETIC_FAILURE reason, C6 error_class)`.
#: Written out rather than derived from `SYNTHETIC_FAILURE_REASONS`, because a
#: table derived from the thing it checks agrees with itself by construction.
RUNNING_MODES: tuple[tuple[str, str], ...] = (
    ("bad_key", "auth"),
    ("tool_timeout", "tool_timeout"),
    ("refusal", "refusal"),
    ("malformed_output", "schema"),
    ("rate_limit", "rate_limit"),
)


def two_step(*, retry: dict[str, Any] | None = None, on_error: str = "fail") -> Any:
    """`idea -> a -> b -> report`, both steps authored.

    Two billable steps and not one, because criterion 3 asks that
    `resume_from` the failed node completes - and a resume that replayed
    nothing would prove only that a run can be started twice. `b` is the node
    every mode below is aimed at, so `a`'s output is what the replay carries.
    """

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


def cyclic() -> Any:
    """A loop closed by a plain agent - D8's sixth mode, which never runs.

    The closer is `b`, an agent, and not a router. `bounds.py`'s own module
    docstring records what happens when such a document is compiled anyway: the
    join fires once, the second arrival is suppressed, and `kickoff()` returns
    normally having produced nothing.
    """

    return document(
        [
            input_node(),
            authored_agent_node("a"),
            authored_agent_node("b", source="a"),
            output_node("report", source="${state.out__b}"),
        ],
        [
            edge("e1", "idea", "a"),
            edge("e2", "a", "b"),
            edge("e3", "b", "a"),
            edge("e4", "b", "report"),
        ],
    )


class ResolvingFactories(SyntheticCrewFactories):
    """Builds the real `Agent` (and so the real `LLM`), kicks off synthetically.

    The same shape `tests/service/test_credentials_runtime.py` uses, and here
    for the same reason: a plain synthetic factory never calls `_authored_llm`,
    so a leak test over one would be green without the secret ever having been
    fetched. `built` keeps the agents so the control assertion can look at
    where the plaintext ended up.

    The real construction happens BEFORE `_record`, so a mode that raises still
    resolves the credential first - which is what makes this usable for the
    failure paths as well as for the happy one.
    """

    def __init__(self, failures: str | None = None) -> None:
        super().__init__(failures=failures)
        self.built: list[Any] = []

    def authored_agent_crew(self, *, node_id: str, spec: Any) -> Any:
        self.built.append(DefaultCrewFactories()._authored_agent(spec, node_id=node_id))
        return super().authored_agent_crew(node_id=node_id, spec=spec)


class SyntheticFailureGrammarTests(unittest.TestCase):
    """The knob itself, before anything is run with it."""

    def test_the_five_running_modes_are_the_declared_reasons(self) -> None:
        self.assertEqual(
            sorted(reason for reason, _ in RUNNING_MODES),
            sorted(SYNTHETIC_FAILURE_REASONS),
        )

    def test_there_is_deliberately_no_cyclic_graph_reason(self) -> None:
        """The sixth mode has no runtime trigger because it has no run.

        A reason that produced one would be a synthetic double diverging from
        its subject, which is the failure CLAUDE.md's closed items 20 and 33
        both are.
        """

        self.assertNotIn("cyclic_graph", SYNTHETIC_FAILURE_REASONS)

    def test_each_reason_carries_d8s_error_class(self) -> None:
        for reason, error_class in RUNNING_MODES:
            with self.subTest(reason=reason):
                self.assertEqual(
                    SYNTHETIC_FAILURE_REASONS[reason].error_class, error_class
                )

    def test_the_default_node_applies_only_where_no_node_was_named(self) -> None:
        """`SYNTHETIC_FAILURE_NODE`, and the precedence that keeps it additive."""

        plans = parse_synthetic_failures("refusal", default_node="b")
        self.assertEqual([plan.node_id for plan in plans], ["b"])
        self.assertTrue(plans[0].applies_to("b"))
        self.assertFalse(plans[0].applies_to("a"))

        named = parse_synthetic_failures("a:refusal", default_node="b")
        self.assertEqual([plan.node_id for plan in named], ["a"])

        everywhere = parse_synthetic_failures("refusal")
        self.assertTrue(everywhere[0].applies_to("anything at all"))

    def test_the_environment_is_what_a_bare_factory_reads(self) -> None:
        with patch.dict(
            os.environ,
            {"SYNTHETIC_FAILURE": "refusal", "SYNTHETIC_FAILURE_NODE": "b"},
        ):
            factories = SyntheticCrewFactories()
        self.assertEqual([plan.node_id for plan in factories.plans], ["b"])

    def test_an_unreadable_value_is_no_failure_rather_than_a_crash(self) -> None:
        """A typo in a testing knob must not be how a free backend refuses to start."""

        self.assertEqual(parse_synthetic_failures("not_a_mode"), ())
        self.assertEqual(parse_synthetic_failures(None), ())


class CyclicGraphTests(unittest.TestCase):
    """D8's sixth mode, which is refused before anything can bill."""

    def test_a_loop_closed_by_an_agent_is_refused_with_the_edge_named(self) -> None:
        problems = [
            problem
            for problem in structural_problems(cyclic())
            if problem.code == "back-edge-not-router"
        ]
        self.assertEqual(len(problems), 1, "the closing edge is not reported")
        problem = problems[0]
        self.assertEqual(problem.severity, "error")
        self.assertEqual(problem.edge_id, "e3")
        self.assertEqual(problem.node_id, "b")
        self.assertIn("router", problem.message)


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class FailureModeCase(AuthenticatedTwoUserCase):
    """A published two-step graph and one knob, per mode."""

    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry

    def install(self, graph: Any, reason: str | None, *, node_id: str = "b") -> str:
        """Publish `graph` and give its runner factories built from the KNOB.

        The environment is what the factory reads, so what is exercised is the
        knob a critic would set and not a constructor argument only a test can
        reach. The runner is built at publish, so the swap happens on the object
        the registry already holds - `test_error_routing.py` does the same, and
        for the same reason: this app has other runners that must not fail.
        """

        _, workflow_id = self.publish(graph, self.as_alice())
        environment = (
            {"SYNTHETIC_FAILURE": reason, "SYNTHETIC_FAILURE_NODE": node_id}
            if reason
            else {"SYNTHETIC_FAILURE": "", "SYNTHETIC_FAILURE_NODE": ""}
        )
        with patch.dict(os.environ, environment):
            factories = SyntheticCrewFactories()
        self.registry.workflow_runtime(workflow_id).runner.crew_factories = factories
        return workflow_id

    def clear_failure(self, workflow_id: str) -> None:
        """What "fix the credential and re-run" means to a synthetic backend."""

        with patch.dict(os.environ, {"SYNTHETIC_FAILURE": "", "SYNTHETIC_FAILURE_NODE": ""}):
            self.registry.workflow_runtime(workflow_id).runner.crew_factories = (
                SyntheticCrewFactories()
            )

    def run_to_end(self, workflow_id: str, **body: Any) -> str:
        payload: dict[str, Any] = {"workflow_id": workflow_id, "inputs": {"idea": IDEA}}
        payload.update(body)
        response = self.client.post(
            "/api/sessions/s1/runs", json=payload, headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=30)
        return run_id

    def frames(self, run_id: str) -> list[dict[str, Any]]:
        page = self.client.get(
            f"/api/runs/{run_id}/frames?limit=500", headers=self.as_alice()
        ).json()
        return [frame["data"] for frame in page["frames"]]

    def node_errors(self, run_id: str) -> list[dict[str, Any]]:
        """The C6 `node_error` frames, and only those.

        `stage: "error"` alone is not the discriminator: `serializer.py:455`
        raises one for CrewAI's own `MethodExecutionFailedEvent`, and a tool, an
        llm call and a crew each raise another. Those are the package narrating
        the same failure from its own side and they carry no `attempt`, which is
        the field this plan's frames are told apart by - `attempt` and
        `will_retry` are decisions the RUNTIME made and CrewAI has no event for
        either.
        """

        return [
            dict(frame["details"])
            for frame in self.frames(run_id)
            if dict(frame["details"] or {}).get("stage") == "error"
            and "attempt" in dict(frame["details"] or {})
        ]

    def snapshot(self, run_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/runs/{run_id}", headers=self.as_alice()).json()

    def assert_mode(self, reason: str, error_class: str, **graph: Any) -> str:
        """D8's row, asserted: the frame, its class, and a terminal `failed`."""

        workflow_id = self.install(two_step(**graph), reason)
        run_id = self.run_to_end(workflow_id)

        errors = self.node_errors(run_id)
        self.assertTrue(errors, f"{reason} produced no node_error frame at all")
        self.assertEqual(errors[-1]["error_class"], error_class)
        # The node the knob named, and not the one before it.
        failed = [
            frame["node_id"]
            for frame in self.frames(run_id)
            if dict(frame["details"] or {}).get("stage") == "error"
            and "attempt" in dict(frame["details"] or {})
        ]
        self.assertEqual(set(failed), {"b"})
        self.assertEqual(self.snapshot(run_id)["status"], "failed")
        return workflow_id


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class RunningModeTests(FailureModeCase):
    """The five that run, one test each - criterion 3."""

    def test_bad_api_key(self) -> None:
        """401. Not retryable: the same key is rejected identically next time."""

        self.assert_mode("bad_key", "auth")

    def test_tool_timeout(self) -> None:
        """408, and the one of the five the node loop WILL spend an attempt on."""

        self.assert_mode("tool_timeout", "tool_timeout")

    def test_model_refusal(self) -> None:
        """Decision 16 made observable: a refusal is a decision, never retried."""

        workflow_id = self.assert_mode("refusal", "refusal")
        run_id = self.run_to_end(workflow_id)
        self.assertFalse(
            any(error["will_retry"] for error in self.node_errors(run_id)),
            "a refusal was retried; decision 16 says a second judge is not a retry",
        )

    def test_malformed_output(self) -> None:
        """The schema failed after the guardrail loop; another attempt is not the repair."""

        workflow_id = self.assert_mode("malformed_output", "schema")
        run_id = self.run_to_end(workflow_id)
        self.assertFalse(any(error["will_retry"] for error in self.node_errors(run_id)))

    def test_rate_limit(self) -> None:
        """429, retried, and the retry frames say attempt N of M - D8's row."""

        workflow_id = self.install(
            two_step(retry={"max_retries": 2, "backoff_seconds": 0}), "rate_limit"
        )
        run_id = self.run_to_end(workflow_id)

        errors = self.node_errors(run_id)
        self.assertEqual([error["error_class"] for error in errors], ["rate_limit"] * 3)
        self.assertEqual([error["attempt"] for error in errors], [1, 2, 3])
        # Amber while retrying, red once exhausted: the first two say another
        # attempt is coming and the last one does not.
        self.assertEqual(
            [error["will_retry"] for error in errors], [True, True, False]
        )
        self.assertEqual(self.snapshot(run_id)["status"], "failed")

    def test_a_clean_run_of_the_same_graph_is_the_control(self) -> None:
        """Without this, every assertion above would pass over a graph that never works."""

        workflow_id = self.install(two_step(), None)
        run_id = self.run_to_end(workflow_id)
        self.assertEqual(self.node_errors(run_id), [])
        self.assertEqual(self.snapshot(run_id)["status"], "completed")


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class RecoveryTests(FailureModeCase):
    """Criterion 3's second half: `resume_from` the failed node completes.

    Every one of D8's recovery columns ends in **Re-run from here**, and the
    repair before it - a new key, a looser schema, a longer timeout - is a thing
    a human does between the two runs. Clearing the knob is what that looks like
    to a synthetic backend.
    """

    def test_every_running_mode_resumes_from_the_node_that_failed(self) -> None:
        for reason, _ in RUNNING_MODES:
            with self.subTest(reason=reason):
                workflow_id = self.install(two_step(), reason)
                failed = self.run_to_end(workflow_id)
                self.assertEqual(self.snapshot(failed)["status"], "failed")

                self.clear_failure(workflow_id)
                resumed = self.run_to_end(
                    workflow_id, resume_from={"run_id": failed, "node_id": "b"}
                )
                body = self.snapshot(resumed)
                self.assertEqual(body["status"], "completed", body.get("error"))
                self.assertIn(BODY_KEY, body["result"])

    def test_the_resume_replays_the_node_that_had_already_been_paid_for(self) -> None:
        """The point of resuming rather than relaunching, stated as an assertion."""

        workflow_id = self.install(two_step(), "refusal")
        failed = self.run_to_end(workflow_id)
        self.clear_failure(workflow_id)
        resumed = self.run_to_end(
            workflow_id, resume_from={"run_id": failed, "node_id": "b"}
        )
        replayed = {
            frame["node_id"]
            for frame in self.frames(resumed)
            if dict(frame["details"] or {}).get("replayed") is True
        }
        self.assertEqual(replayed, {"idea", "a"})
        self.assertNotIn("b", replayed)

    def test_a_routed_failure_completes_instead_of_failing(self) -> None:
        """D3's other recovery: the error PORT, rather than a second run.

        Asserted here beside the resume because D8's table offers the two as
        alternatives on the same row, and a reader of one wants the other.
        """

        graph = document(
            [
                input_node(),
                authored_agent_node("a"),
                authored_agent_node("b", source="a", on_error="route"),
                authored_agent_node("fallback", source="a"),
                output_node("report", source="${state.out__fallback}"),
            ],
            [
                edge("e1", "idea", "a"),
                edge("e2", "a", "b"),
                edge("e3", "b", "fallback", source_port="error"),
                edge("e4", "fallback", "report"),
            ],
        )
        workflow_id = self.install(graph, "tool_timeout")
        run_id = self.run_to_end(workflow_id)
        self.assertEqual(self.snapshot(run_id)["status"], "completed")
        self.assertTrue(self.node_errors(run_id)[-1]["routed"])


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class SentinelTests(AuthenticatedTwoUserCase):
    """Criterion 4: no failure mode leaks the key, on any surface.

    One run per mode, each one REALLY resolving the credential, then the five
    places the plaintext could have reached: the frames, the run row, the status
    payload, the NDJSON export and the ZIP.
    """

    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry
        self.credential = self.create_credential(self.as_alice())["id"]

    def run_with(self, reason: str) -> tuple[str, ResolvingFactories]:
        graph = document(
            [
                input_node(),
                builder_node(
                    "b",
                    "agent",
                    {
                        **authored_agent_node("b")["config"],
                        "credential_id": self.credential,
                        "task": {
                            "description": "work from ${state.out__idea}",
                            "expected_output": "a paragraph",
                        },
                    },
                ),
                output_node("report", source="${state.out__b}"),
            ],
            [edge("e1", "idea", "b"), edge("e2", "b", "report")],
        )
        _, workflow_id = self.publish(graph, self.as_alice())
        with patch.dict(
            os.environ,
            {"SYNTHETIC_FAILURE": reason, "SYNTHETIC_FAILURE_NODE": "b"},
        ):
            factories = ResolvingFactories()
        self.registry.workflow_runtime(workflow_id).runner.crew_factories = factories
        response = self.client.post(
            "/api/sessions/s1/runs",
            json={"workflow_id": workflow_id, "inputs": {"idea": IDEA}},
            headers=self.as_alice(),
        )
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=30)
        return run_id, factories

    def test_no_secret_in_any_failure(self) -> None:
        for reason, _ in RUNNING_MODES:
            with self.subTest(reason=reason):
                run_id, factories = self.run_with(reason)

                # The control, first. Without it the five assertions below would
                # be satisfied by a run that never held the key.
                self.assertTrue(
                    factories.built, f"{reason} built no real agent; this would be vacuous"
                )
                self.assertEqual(factories.built[0].llm.api_key, SECRET)

                frames = self.client.get(
                    f"/api/runs/{run_id}/frames?limit=500", headers=self.as_alice()
                )
                self.assertNotIn(SECRET, frames.text)

                row = self.registry.persistence.get_run(run_id)
                self.assertNotIn(SECRET, json.dumps(row, default=str))

                snapshot = self.client.get(
                    f"/api/runs/{run_id}", headers=self.as_alice()
                )
                self.assertNotIn(SECRET, snapshot.text)

                ndjson = self.client.get(
                    f"/api/runs/{run_id}/logs?format=ndjson", headers=self.as_alice()
                )
                self.assertEqual(ndjson.status_code, 200, ndjson.text)
                self.assertNotIn(SECRET, ndjson.text)

                archive = self.client.get(
                    f"/api/runs/{run_id}/logs?format=zip", headers=self.as_alice()
                )
                self.assertEqual(archive.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
                    for name in zipped.namelist():
                        self.assertNotIn(
                            SECRET, zipped.read(name).decode("utf-8", "replace")
                        )

    def test_the_failure_sentence_names_the_node_and_not_the_key(self) -> None:
        """D8's log column: the credential LABEL, never the value."""

        run_id, _ = self.run_with("bad_key")
        page = self.client.get(
            f"/api/runs/{run_id}/frames?limit=500", headers=self.as_alice()
        ).json()
        sentences = [
            str(dict(frame["data"]["details"] or {}).get("message", ""))
            for frame in page["frames"]
            if "attempt" in dict(frame["data"]["details"] or {})
        ]
        self.assertTrue(sentences)
        self.assertIn("SyntheticBadCredential", " ".join(sentences))
        self.assertIn("b", " ".join(sentences))
        self.assertNotIn(SECRET, " ".join(sentences))


if __name__ == "__main__":
    unittest.main()
