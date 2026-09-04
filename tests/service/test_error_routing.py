"""`on_error: route` catches, records and returns - 10 D4, criterion 5.

The claim is that a run whose only failing node is routed reaches `completed`,
and the mechanism is that the step method returns NORMALLY on final failure
having written `err__<node>`, so its paired router - and only a `@router` can
choose an event - fires the error port.

Driven through the SERVICE, not just the runner, because "the run reaches
completed" is a statement about a run record and a durable row, and a runner
called directly has neither.
"""

from __future__ import annotations

import importlib.util
import threading
from typing import Any
import unittest

from brief_crew.builder.descriptor import build_builder_workflow
from brief_crew.events import FrameKind
from brief_crew.events.adapter import StreamSinkAdapter
from brief_crew.events.buffer import FrameBuffer
from brief_crew.events.context import CaptureContext, capture_events
from brief_crew.service.builder_runner import BuilderFlowRunner, SyntheticCrewFactories
from brief_crew.service.models import RunStatus
from brief_crew.service.runner import RunExecution
from tests.builder.test_compiler import (
    authored_agent_node,
    input_node,
    output_node,
)
from tests.builder.test_document import document, edge
from tests.service.identities import AuthenticatedTwoUserCase

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
IDEA = "a scheduling assistant for clinics"


def routed_graph(on_error: str = "route") -> Any:
    """idea -> draft -> report, with `draft`'s error port going to `apology`."""

    nodes = [
        input_node(),
        authored_agent_node("draft", on_error=on_error),
        output_node(
            "report",
            source="${state.out__apology}" if on_error == "route" else "${state.out__draft}",
        ),
    ]
    edges = [edge("e1", "idea", "draft"), edge("e2", "draft", "report")]
    if on_error == "route":
        nodes.append(authored_agent_node("apology", source="idea"))
        edges.append(edge("e3", "draft", "apology", source_port="error"))
        edges.append(edge("e4", "apology", "report"))
    return document(nodes, edges)


class ErrorRoutingRunnerTests(unittest.TestCase):
    """The state and the frame, in process."""

    def _run(self, graph: Any, failures: str) -> tuple[Any, FrameBuffer, Any]:
        workflow = build_builder_workflow(graph)
        buffer = FrameBuffer()
        capture = StreamSinkAdapter(
            run_id="run-route", buffer=buffer, registry=workflow.node_registry
        )
        execution = RunExecution(
            run_id="run-route",
            inputs={"idea": IDEA},
            capture=capture,
            flow_id="run-route",
            cancel_requested=threading.Event(),
        )
        runner = BuilderFlowRunner(
            workflow, crew_factories=SyntheticCrewFactories(failures=failures)
        )
        with capture_events(CaptureContext(run_id="run-route", adapter=capture)):
            try:
                result = runner(execution)
            except Exception as exc:  # noqa: BLE001 - the `fail` arm asserts on it
                return exc, buffer, None
        return result, buffer, None

    def errors(self, buffer: FrameBuffer) -> list[dict[str, Any]]:
        return [
            dict(frame.details)
            for frame in buffer.replay(after=0, limit=500)
            if frame.kind is FrameKind.ERROR
            and dict(frame.details).get("stage") == "error"
        ]

    def test_route_takes_the_error_port_and_the_successor_runs(self) -> None:
        result, buffer, _ = self._run(routed_graph(), "draft:refusal")
        self.assertIn("Synthetic output for apology", str(result))
        error = self.errors(buffer)[0]
        self.assertTrue(error["routed"])
        self.assertFalse(error["will_retry"])

    def test_fail_raises_and_the_frame_is_the_same_shape(self) -> None:
        raised, buffer, _ = self._run(routed_graph("fail"), "draft:refusal")
        self.assertIsInstance(raised, Exception)
        error = self.errors(buffer)[0]
        # The SAME `node_error` frame - only `routed` differs, which is the
        # whole of the difference between the two policies as a client sees it.
        self.assertFalse(error["routed"])
        self.assertFalse(error["will_retry"])
        # `refusal`, not the base class's `synthetic-failure` placeholder: 12 D8
        # gives each of the five running modes its own C6 `error_class`, because
        # a client switching on "synthetic-failure" learns nothing about what
        # happened and the whole point of the table is that the six are told
        # apart on screen.
        self.assertEqual(error["error_class"], "refusal")
        self.assertEqual(error["attempt"], 1)

    def test_the_error_class_survives_onto_the_frame(self) -> None:
        _, buffer, _ = self._run(routed_graph(), "draft:rate_limit")
        self.assertEqual(self.errors(buffer)[0]["error_class"], "rate_limit")


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ErrorRoutingRunTests(AuthenticatedTwoUserCase):
    """The run STATUS, which only a real run record can answer."""

    def app_kwargs(self) -> dict[str, Any]:
        return {"synthetic": True}

    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry

    def launch(self, workflow_id: str) -> str:
        response = self.client.post(
            "/api/sessions/s1/runs",
            json={"workflow_id": workflow_id, "inputs": {"idea": IDEA}},
            headers=self.as_alice(),
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["run_id"]

    def _with_failure(self, graph: Any, failures: str) -> str:
        """Publish `graph` and swap its runner's factories for failing ones.

        The runner is built at publish, so the failure has to be installed on
        the object the registry already holds rather than through the
        environment - which is the honest way round: `SYNTHETIC_FAILURE` is read
        per instance, and this test needs one instance to fail and the app's
        others not to.
        """

        _, workflow_id = self.publish(graph, self.as_alice())
        runtime = self.registry.workflow_runtime(workflow_id)
        runtime.runner.crew_factories = SyntheticCrewFactories(failures=failures)
        return workflow_id

    def test_a_routed_failure_reaches_completed_with_err_in_state(self) -> None:
        workflow_id = self._with_failure(routed_graph(), "draft:refusal")
        run_id = self.launch(workflow_id)
        self.registry.wait(run_id, timeout=20)
        body = self.client.get(f"/api/runs/{run_id}", headers=self.as_alice()).json()
        self.assertEqual(body["status"], RunStatus.COMPLETED.value)
        state = self.client.get(
            f"/api/runs/{run_id}/state", headers=self.as_alice()
        ).json()["state"]
        self.assertIn("err__draft", state)
        self.assertIn("SyntheticRefusal", state["err__draft"])

    def test_a_failing_node_with_on_error_fail_reaches_failed(self) -> None:
        workflow_id = self._with_failure(routed_graph("fail"), "draft:refusal")
        run_id = self.launch(workflow_id)
        self.registry.wait(run_id, timeout=20)
        body = self.client.get(f"/api/runs/{run_id}", headers=self.as_alice()).json()
        self.assertEqual(body["status"], RunStatus.FAILED.value)
        self.assertIsNotNone(body["error"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
