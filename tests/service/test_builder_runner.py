"""A published builder graph that actually runs, and the four silent failures.

`create_app` used to install a runner that raised, so everything up to the
first node was real - compile, price, bound, register, admit, rate limit - and
then the run failed with a sentence saying no runner had been injected. This
module is the proof that the gap is closed, and it is deliberately shaped
around the four requirements in `service/builder_runner.py`'s docstring, each
of which fails SILENTLY rather than loudly:

* the `FlowDefinition` reused on resume. `FromPendingWithoutDefinitionTests`
  pins the control - the same resume without `definition=` returns having run
  nothing at all, no exception and no frame - because a requirement whose
  omission raises does not need a test and this one does.
* `builder_cancellation` around both calls, so a cancelled run reaches
  CANCELLED and not FAILED.
* `persistence=` on both paths, proved by reading the run's own pending row
  back out of the store the execution carried rather than out of a stray file.
* the no-cost path, which is a `use_crew_factories` swap over the REAL compiled
  definition rather than a second runner - so what these tests exercise is the
  production engine, the production gates, the production routers and the
  production cancellation, with only the thing that would have called a model
  replaced.

Nothing here spends anything. `SyntheticCrewFactories` is the same object
`SYNTHETIC=1` installs, and a gate calls no model by construction.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
from typing import Any
import unittest

from crewai.flow.async_feedback import HumanFeedbackPending
from crewai.flow.flow import Flow
from crewai.flow.flow_definition import FlowDefinition
from crewai.flow.persistence.sqlite import SQLiteFlowPersistence
from crewai.hooks import HookAborted

from brief_crew.builder.descriptor import BuilderWorkflow, build_builder_workflow
from brief_crew.config import RUN_RESULT_BODY_KEYS
from brief_crew.events.adapter import StreamSinkAdapter
from brief_crew.events.buffer import FrameBuffer
from brief_crew.service.builder_runner import (
    BuilderFlowRunner,
    SyntheticCrewFactories,
    synthetic_builder_runner,
)
from brief_crew.service.models import RunStatus
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import RunRegistry, WorkflowRuntime
from brief_crew.service.runner import RunExecution
from tests.builder.test_compiler import (
    gate_node,
    gated_loop,
    input_node,
    output_node,
    router_node,
    scoper_node,
    straight_line,
    transform_node,
)
from tests.builder.test_document import document, edge
from tests.service.builder_registration import forget_builder_workflow


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

BODY_KEY = RUN_RESULT_BODY_KEYS[0]
IDEA = "a scheduling assistant for clinics"


def gate_before_spend(max_turns: int = 1) -> Any:
    """`gated_loop` with the gate moved ABOVE the one billable node.

    Two things need this shape rather than `gated_loop`'s. `create_run` refuses
    an anonymous launch of a graph that reaches a billable node before any
    human gate - correctly, because human inaction is the only spend cap an
    unauthenticated Launch button has - so the HTTP test cannot use a graph
    whose agent runs first. And it makes "the resume produced output" an
    assertion about a node PAST the gate having really run, rather than about
    the gate echoing its own reply.
    """

    return document(
        [
            input_node(),
            gate_node(max_turns=max_turns, editable_fields=("notes",)),
            transform_node(
                "restate",
                op="default",
                args={"value": "${state.out__confirm}", "default": "no note"},
            ),
            router_node(key="turns__confirm", value=1),
            scoper_node(),
            output_node("report", source="${state.out__scoper}"),
        ],
        [
            edge("e1", "idea", "confirm"),
            edge("e2", "confirm", "scoper", source_port="approve"),
            edge("e3", "confirm", "restate", source_port="revise"),
            edge("e4", "restate", "again"),
            edge("e5", "again", "confirm", source_port="retry"),
            edge("e6", "again", "scoper", source_port="onward"),
            edge("e7", "scoper", "report"),
        ],
    )


def workflow_of(document: Any) -> BuilderWorkflow:
    return build_builder_workflow(document)


def capture_for(workflow: BuilderWorkflow, run_id: str) -> StreamSinkAdapter:
    """A real sink rather than a placeholder.

    The runner never touches it, but handing `RunExecution` something that is
    not a `StreamSinkAdapter` would make this file the one place the execution
    contract is a fiction, and the next person to read `capture` here would
    have to check.
    """

    return StreamSinkAdapter(
        run_id=run_id, buffer=FrameBuffer(), registry=workflow.node_registry
    )


def execution_for(
    workflow: BuilderWorkflow,
    *,
    run_id: str = "run-1",
    inputs: dict[str, Any] | None = None,
    persistence: Any = None,
    cancel_requested: threading.Event | None = None,
) -> RunExecution:
    return RunExecution(
        run_id=run_id,
        inputs=inputs if inputs is not None else {"idea": IDEA},
        capture=capture_for(workflow, run_id),
        flow_id=run_id,
        persistence=persistence,
        cancel_requested=cancel_requested,
    )


class BlockingCrew:
    """Signals that it started, then waits to be let go.

    The only way to make a cancel land WHILE a graph is executing without
    sleeping on a guess: the test can wait for `started`, cancel, and only then
    release, so the assertion is about the cancel rather than about timing.
    """

    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self._started = started
        self._release = release

    def kickoff(self, inputs: Any = None) -> str:
        self._started.set()
        self._release.wait(timeout=10)
        return json.dumps({"segment": "clinics"})


class BlockingFactories(SyntheticCrewFactories):
    """The synthetic factories, with the first billable node held open."""

    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release

    def agent_crew(self, **kwargs: Any) -> BlockingCrew:
        return BlockingCrew(self.started, self.release)


# --------------------------------------------------------------------------
# The no-cost seam itself
# --------------------------------------------------------------------------
class SyntheticCrewFactoriesTests(unittest.TestCase):
    def test_both_halves_of_the_protocol_are_answered(self) -> None:
        factories = SyntheticCrewFactories()
        agent = factories.agent_crew(
            node_id="scoper",
            agent_id="scoper",
            tier="escalation",
            tools=(),
            max_iter=2,
            guardrail_max_retries=0,
        )
        crew = factories.crew(
            node_id="scope_crew",
            crew_id="scope",
            tier="escalation",
            max_iter=2,
            guardrail_max_retries=0,
        )
        self.assertEqual(json.loads(agent.kickoff())["produced_by"], "scoper")
        self.assertEqual(json.loads(crew.kickoff())["produced_by"], "scope")

    def test_the_output_is_a_json_object_so_a_gate_shows_fields(self) -> None:
        # Prose here would leave every synthetic gate rendering one read-only
        # `summary` blob - `gate_payload` only splits an object into fields -
        # and the gate form is the half of the builder that most needs
        # exercising for free.
        raw = SyntheticCrewFactories().agent_crew(
            node_id="scoper",
            agent_id="scoper",
            tier="escalation",
            tools=(),
            max_iter=2,
            guardrail_max_retries=0,
        ).kickoff(inputs={"idea": IDEA})
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["node_id"], "scoper")
        self.assertEqual(parsed["prompt_inputs"], {"idea": IDEA})

    def test_it_is_deterministic(self) -> None:
        first = SyntheticCrewFactories().agent_crew(
            node_id="n", agent_id="scoper", tier="cheap", tools=(), max_iter=1,
            guardrail_max_retries=0,
        ).kickoff(inputs={"idea": IDEA})
        second = SyntheticCrewFactories().agent_crew(
            node_id="n", agent_id="scoper", tier="cheap", tools=(), max_iter=1,
            guardrail_max_retries=0,
        ).kickoff(inputs={"idea": IDEA})
        self.assertEqual(first, second)


# --------------------------------------------------------------------------
# The runner, driven directly
# --------------------------------------------------------------------------
class BuilderFlowRunnerTests(unittest.TestCase):
    def test_a_compiled_graph_runs_and_returns_its_output_body(self) -> None:
        workflow = workflow_of(straight_line())
        runner = BuilderFlowRunner(workflow, crew_factories=SyntheticCrewFactories())
        result = runner(execution_for(workflow))
        self.assertEqual(result["node_id"], "report")
        self.assertIn("Synthetic output for scoper", result[BODY_KEY])

    def test_the_run_id_wins_over_an_id_smuggled_in_the_request_body(self) -> None:
        # `id` is not in the compiled state default, so it is not a reserved
        # run input key and a request body can carry it. `flow_id == run_id` is
        # what every gate reply and every resume resolves through, so the
        # runner assigns it after copying the inputs rather than before.
        workflow = workflow_of(gated_loop(max_turns=1))
        runner = BuilderFlowRunner(workflow, crew_factories=SyntheticCrewFactories())
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            store = SQLiteFlowPersistence(str(Path(directory) / "flows.db"))
            paused = runner(
                execution_for(
                    workflow,
                    run_id="run-real",
                    inputs={"idea": IDEA, "id": "run-forged"},
                    persistence=store,
                )
            )
        self.assertIsInstance(paused, HumanFeedbackPending)
        self.assertEqual(paused.context.flow_id, "run-real")

    def test_a_gate_below_an_agent_shows_that_agents_own_fields(self) -> None:
        # Only true because the synthetic crew emits an object: `gate_payload`
        # splits a JSON object into the fields an operator edits and turns
        # anything else into one read-only `summary` blob.
        workflow = workflow_of(gated_loop(max_turns=1))
        runner = BuilderFlowRunner(workflow, crew_factories=SyntheticCrewFactories())
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            store = SQLiteFlowPersistence(str(Path(directory) / "flows.db"))
            paused = runner(execution_for(workflow, run_id="run-g", persistence=store))
        shown = json.loads(paused.context.method_output)
        self.assertEqual(shown["produced_by"], "scoper")
        # The declared editable field is seeded even though the agent's output
        # never carried it.
        self.assertEqual(shown["notes"], "")

    def test_a_cancelled_run_aborts_rather_than_completing(self) -> None:
        # The flag is set before the kickoff, so the FIRST node's checkpoint is
        # the one that fires. `HookAborted` and not some other exception is the
        # whole point: `RunRegistry._execute` reads that type to decide between
        # CANCELLED and FAILED.
        workflow = workflow_of(straight_line())
        runner = BuilderFlowRunner(workflow, crew_factories=SyntheticCrewFactories())
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(HookAborted):
            runner(execution_for(workflow, cancel_requested=cancelled))

    def test_the_cancel_flag_does_not_outlive_the_call(self) -> None:
        # `builder_cancellation` is a ContextVar scope, and a pooled worker
        # thread runs many runs. A flag left set would abort the NEXT run on
        # this thread at its first node, for a cancel nobody asked for.
        workflow = workflow_of(straight_line())
        runner = BuilderFlowRunner(workflow, crew_factories=SyntheticCrewFactories())
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(HookAborted):
            runner(execution_for(workflow, cancel_requested=cancelled))
        result = runner(execution_for(workflow, run_id="run-2"))
        self.assertEqual(result["node_id"], "report")

    def test_the_pending_row_lands_in_the_store_the_execution_carried(self) -> None:
        # Without `persistence=`, CrewAI builds `default_flow_persistence()` -
        # a stray SQLite file on container disk - and the service's own store
        # never sees the pause, so the gate can never be answered.
        workflow = workflow_of(gated_loop(max_turns=1))
        runner = BuilderFlowRunner(workflow, crew_factories=SyntheticCrewFactories())
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            store = SQLiteFlowPersistence(str(Path(directory) / "flows.db"))
            runner(execution_for(workflow, run_id="run-p", persistence=store))
            self.assertIsNotNone(store.load_pending_feedback("run-p"))

    def test_the_synthetic_factory_builds_a_runner_over_the_same_workflow(self) -> None:
        workflow = workflow_of(straight_line())
        runner = synthetic_builder_runner(workflow)
        self.assertIsInstance(runner, BuilderFlowRunner)
        self.assertIs(runner.workflow, workflow)
        self.assertIsInstance(runner.crew_factories, SyntheticCrewFactories)


# --------------------------------------------------------------------------
# The requirement whose omission is silent
# --------------------------------------------------------------------------
class FromPendingWithoutDefinitionTests(unittest.TestCase):
    """`definition=` on the resume, and the control that shows why.

    `Flow.from_pending` falls through to `cls(persistence=...)` when no
    definition is given - a bare `Flow` with **no methods on it at all**. The
    graph is then not merely unfinished, it does not exist: nothing downstream
    of the gate can run, and what the operator's reply reaches is CrewAI's own
    bookkeeping looking for a method the flow has never heard of.

    Measured rather than assumed, and it is worth writing down that the spec
    predicted a silent nothing: at 1.15.18 the failure surfaces as a `KeyError`
    out of `_persist_method_completion`, an exception naming a compiled ident
    with no hint that a `definition=` argument is missing. Loud, but only in
    the sense that a stack trace is loud - the run fails with a message nobody
    can act on, having produced no output whatsoever.
    """

    def setUp(self) -> None:
        # `ignore_cleanup_errors` because SQLiteFlowPersistence holds its
        # connection open and Windows refuses to unlink an open file.
        self._temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._temporary.cleanup)
        self.store = SQLiteFlowPersistence(str(Path(self._temporary.name) / "flows.db"))
        self.workflow = workflow_of(gate_before_spend())
        self.runner = BuilderFlowRunner(
            self.workflow, crew_factories=SyntheticCrewFactories()
        )
        self.paused = self.runner(
            execution_for(self.workflow, run_id="run-r", persistence=self.store)
        )
        self.assertIsInstance(self.paused, HumanFeedbackPending)

    def test_the_definition_is_parsed_once_and_both_paths_share_it(self) -> None:
        first = self.runner._flow_definition()
        self.assertIsInstance(first, FlowDefinition)
        self.assertIs(first, self.runner._flow_definition())

    def test_a_resume_carrying_the_definition_runs_the_nodes_past_the_gate(self) -> None:
        result = self.runner.resume(
            execution_for(self.workflow, run_id="run-r", persistence=self.store),
            context=self.paused.context,
            feedback=json.dumps({"decision": "approve"}),
        )
        self.assertEqual(result["node_id"], "report")
        # The agent BELOW the gate really ran; this is not the gate echoing
        # its own reply back as an output.
        self.assertIn("Synthetic output for scoper", result[BODY_KEY])

    def test_the_same_resume_without_it_has_no_methods_to_run(self) -> None:
        # The control, and the reason this requirement needs a test rather than
        # a comment: `definition=` is one keyword argument whose absence is
        # indistinguishable from its presence anywhere except here.
        bare = Flow.from_pending(self.paused.context.flow_id, self.store)
        self.assertEqual(bare._methods, {})
        with self.assertRaises(KeyError):
            bare.resume(json.dumps({"decision": "approve"}))
        # Nothing ran, so nothing was produced - the run would have reached a
        # terminal state with no output at all.
        self.assertIsNone(bare.state.get("out__report"))


# --------------------------------------------------------------------------
# The service execution path
# --------------------------------------------------------------------------
class RegistryRunTests(unittest.TestCase):
    """Through `RunRegistry`, which is what `POST /runs` actually calls."""

    def _registry(
        self, workflow: BuilderWorkflow, *, crew_factories: Any = None
    ) -> RunRegistry:
        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        runner = BuilderFlowRunner(
            workflow, crew_factories=crew_factories or SyntheticCrewFactories()
        )
        registry = RunRegistry(
            graph_version=workflow.graph_version,
            node_registry=workflow.node_registry,
            runner=runner,
            workflows={
                workflow.workflow_id: WorkflowRuntime(
                    graph_version=workflow.graph_version,
                    node_registry=workflow.node_registry,
                    runner=runner,
                    input_field=workflow.input_field,
                )
            },
            persistence=store,
        )
        self.addCleanup(store.close)
        self.addCleanup(registry.close)
        return registry

    def _launch(self, registry: RunRegistry, workflow: BuilderWorkflow) -> str:
        record = registry.create_run(
            session_id="builder-runner",
            workflow_id=workflow.workflow_id,
            inputs={workflow.input_field: IDEA},
        )
        registry.start_run(record.run_id)
        return record.run_id

    def test_an_ungated_graph_runs_to_completion_with_its_body(self) -> None:
        workflow = workflow_of(straight_line())
        registry = self._registry(workflow)
        run_id = self._launch(registry, workflow)
        registry.wait(run_id, timeout=30)
        record = registry.require(run_id)
        self.assertIs(record.status, RunStatus.COMPLETED)
        self.assertIn("Synthetic output for scoper", record.result[BODY_KEY])

    def test_a_gated_graph_pauses_resumes_and_finishes(self) -> None:
        # The whole point of the builder: compose, wire, launch, be asked, and
        # get an answer back. Every piece here is the production one except the
        # crew factories.
        workflow = workflow_of(gate_before_spend())
        registry = self._registry(workflow)
        run_id = self._launch(registry, workflow)
        registry.wait(run_id, timeout=30)
        record = registry.require(run_id)
        self.assertIs(record.status, RunStatus.WAITING)
        gate = record.pending_gate
        self.assertIsNotNone(gate)
        # The author declared `notes` editable, and the gate offers it.
        self.assertIn("notes", gate["fields"])

        registry.answer_gate(run_id, gate["gate_id"], outcome="approve", fields={})
        registry.wait(run_id, timeout=30)
        record = registry.require(run_id)
        self.assertIs(record.status, RunStatus.COMPLETED)
        self.assertIn("Synthetic output for scoper", record.result[BODY_KEY])

    def test_a_cancel_mid_run_reaches_cancelled_and_not_failed(self) -> None:
        # FAILED would be the wrong word for something an operator asked for,
        # and it is what any exception other than `HookAborted` produces.
        started, release = threading.Event(), threading.Event()
        workflow = workflow_of(straight_line())
        registry = self._registry(
            workflow, crew_factories=BlockingFactories(started, release)
        )
        run_id = self._launch(registry, workflow)
        self.assertTrue(started.wait(timeout=30), "the graph never started running")
        registry.cancel(run_id)
        release.set()
        terminal = {RunStatus.CANCELLED, RunStatus.COMPLETED, RunStatus.FAILED}
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = registry.require(run_id).status
            if status in terminal:
                break
            time.sleep(0.02)
        self.assertIs(registry.require(run_id).status, RunStatus.CANCELLED)


# --------------------------------------------------------------------------
# The wiring
# --------------------------------------------------------------------------
@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class SyntheticServiceTests(unittest.TestCase):
    """`SYNTHETIC=1` composing, publishing and RUNNING a graph, for free.

    The gated document is not a convenience: `create_run` refuses a builder
    graph with no gate before its first billable node unless
    `BUILDER_ALLOW_GATELESS_GRAPHS` is set, and that refusal is correct - an
    anonymous Launch on an ungated graph has no brake at all.
    """

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.app = create_app(
            synthetic=True, database_url="sqlite+pysqlite:///:memory:"
        )
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _publish(self) -> dict[str, Any]:
        created = self.client.post(
            "/api/builder/workflows",
            json={"document": json.loads(gate_before_spend().model_dump_json())},
        )
        self.assertEqual(created.status_code, 201, created.text)
        document_id = created.json()["document"]["id"]
        published = self.client.post(f"/api/builder/workflows/{document_id}/publish")
        self.assertEqual(published.status_code, 200, published.text)
        # A publish through the real HTTP surface writes five process-global
        # maps, and `TestClient.close` unwinds none of them. Without this the
        # graph outlived the case and was still in `WORKFLOWS` when
        # `test_builder_rehydration` later asserted that no `ug_` id was - a
        # failure in a module that had done nothing wrong, in one ordering
        # only. The suite was green because `discover` sorts rehydration first.
        body = published.json()
        self.addCleanup(forget_builder_workflow, body["workflow_id"])
        return body

    def test_a_published_graph_runs_end_to_end_with_no_model_call(self) -> None:
        published = self._publish()
        launched = self.client.post(
            "/api/sessions/synthetic-builder/runs",
            json={
                "workflow_id": published["workflow_id"],
                "inputs": {published["input_field"]: IDEA},
            },
        )
        self.assertEqual(launched.status_code, 202, launched.text)
        run_id = launched.json()["run_id"]

        registry = self.app.state.run_registry
        registry.wait(run_id, timeout=30)
        waiting = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(waiting["status"], RunStatus.WAITING.value)

        gate_id = waiting["pending_gate"]["gate_id"]
        answered = self.client.post(
            f"/api/runs/{run_id}/gates/{gate_id}",
            json={"outcome": "approve", "fields": {}},
        )
        self.assertEqual(answered.status_code, 202, answered.text)
        registry.wait(run_id, timeout=30)

        finished = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(finished["status"], RunStatus.COMPLETED.value)
        self.assertIn("Synthetic output for scoper", finished["result"][BODY_KEY])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
