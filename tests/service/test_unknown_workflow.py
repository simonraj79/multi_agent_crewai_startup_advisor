"""Three defects a *third* workflow trips, none of which the two can reach.

Every one of them is a hardcoded two-workflow assumption in a code path that
reads as general. They are invisible today because ``WORKFLOWS`` holds exactly
``brief-flow`` and ``idea-validator``, and every one of them turns into a
silent wrong answer - or a 500 - the moment a third id exists:

* ``registry._runtime_for`` raised a bare ``KeyError`` for a workflow that was
  registered in ``GRAPHS`` / ``NODE_REGISTRIES`` / ``WORKFLOWS`` but not in the
  ``workflows=`` runtime map ``create_app`` builds. Nothing caught it, so
  registering in three of the four required places answered **500**, which
  says "this service is broken" about a request that is merely mistaken.
* ``create_run`` derived the request's input key as ``"idea" if workflow_id ==
  VALIDATOR_GRAPH.id else "topic"``. Any third workflow was therefore told
  ``inputs.topic must contain non-whitespace text`` about a field it never
  declared, and the operator had no way to discover the real name.
* the ``gates="auto"`` refusal compared the id to the validator's, so a third
  workflow that genuinely declares ``@human_feedback`` methods was refused with
  ``has no gates to skip`` - a sentence contradicted by its own descriptor.

The three third-workflow cases below are the ones that fail before the fix.
The built-in cases beside them are controls: the two-workflow behaviour must
not move, because ``test_gates_mode`` and ``test_run_admission`` pin it.

No cost: the runners are local callables, nothing reaches a model or a socket.
"""

from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

# A workflow id that is deliberately neither of the two built-ins, so every
# assertion below is about the general path rather than about a special case.
THIRD_ID = "third-workflow"
THIRD_INPUT_FIELD = "brief"


class InertRunner:
    """A run that finishes immediately having spent nothing.

    Not a mock: every assertion here is about what the *service* answers, and a
    runner that recorded its call would only let a test assert that it had been
    told what to record.
    """

    def __call__(self, execution: object) -> dict[str, object]:
        return {"ok": True}


def _third_descriptor(*, gated: bool):
    """A minimal third graph descriptor, gated or not.

    Hand-built rather than derived from a Flow: ``build_graph_descriptor``
    would need a real ``Flow`` subclass and CrewAI's structure builder, and the
    only fact under test is the one field the handler has to read -
    ``human_feedback``, which ``build_graph_descriptor`` itself sets from
    CrewAI's own report of which methods carry ``@human_feedback``.
    """

    from brief_crew.service.models import GraphDescriptor, GraphNode

    nodes = [
        GraphNode(
            id="start_here",
            label="Start here",
            kind="start",
            description="Seed the run.",
            eyebrow="01",
            position={"x": 0, "y": 0},
        )
    ]
    if gated:
        nodes.append(
            GraphNode(
                id="confirm_it",
                label="Confirm it",
                kind="gate",
                description="Ask a person.",
                eyebrow="GATE",
                position={"x": 0, "y": 170},
                human_feedback=True,
            )
        )
    return GraphDescriptor(
        id=THIRD_ID,
        name="Third Workflow",
        version="deadbeefdeadbeef",
        start_nodes=["start_here"],
        nodes=nodes,
        edges=[],
    )


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ThirdWorkflowTestCase(unittest.TestCase):
    """Builders shared by every case below."""

    def registry(self, *, workflows):
        from brief_crew.service.graph import BRIEF_GRAPH, BRIEF_NODE_REGISTRY
        from brief_crew.service.registry import RunRegistry

        registry = RunRegistry(
            graph_version=BRIEF_GRAPH.version,
            node_registry=BRIEF_NODE_REGISTRY,
            runner=InertRunner(),
            workflows=workflows,
            gate_sweep_interval=0,
        )
        self.addCleanup(registry.close)
        return registry

    def client(self, registry):
        from fastapi.testclient import TestClient

        from brief_crew.service.app import RunRateLimiter, create_app

        client = TestClient(
            create_app(registry=registry, rate_limiter=RunRateLimiter(max_runs=0)),
            # Without this an uncaught handler exception propagates into the
            # test instead of becoming the 500 a real client would see, and
            # "did this answer 404 or 500" is the whole question here.
            raise_server_exceptions=False,
        )
        self.addCleanup(client.close)
        return client

    def builtin_client(self):
        """The real two-workflow app, no-cost, for the control cases."""

        from fastapi.testclient import TestClient

        from brief_crew.service.app import RunRateLimiter, create_app

        client = TestClient(
            create_app(synthetic=True, rate_limiter=RunRateLimiter(max_runs=0))
        )
        self.addCleanup(client.close)
        return client

    def register_third(self, *, gated: bool, input_field: str | None):
        """Put a third workflow in the three maps the handler consults."""

        from brief_crew.service.graph import BRIEF_GRAPH, BRIEF_NODE_REGISTRY
        from brief_crew.service.models import WorkflowSummary
        from brief_crew.service.registry import WorkflowRuntime

        runner = InertRunner()
        descriptor = _third_descriptor(gated=gated)
        registry = self.registry(
            workflows={
                BRIEF_GRAPH.id: WorkflowRuntime(
                    graph_version=BRIEF_GRAPH.version,
                    node_registry=BRIEF_NODE_REGISTRY,
                    runner=runner,
                ),
                THIRD_ID: WorkflowRuntime(
                    graph_version=descriptor.version,
                    node_registry=BRIEF_NODE_REGISTRY,
                    runner=runner,
                    input_field=input_field,
                ),
            }
        )
        summary = WorkflowSummary(
            id=THIRD_ID, name=descriptor.name, graph_version=descriptor.version
        )
        # `app.py` binds these dicts by name at import and reads them as module
        # globals, so patching the attribute patches the object the handler
        # actually consults.
        self.enterContext(
            patch.dict("brief_crew.service.app.WORKFLOWS", {THIRD_ID: summary})
        )
        self.enterContext(
            patch.dict("brief_crew.service.app.GRAPHS", {THIRD_ID: descriptor})
        )
        return self.client(registry)

    @staticmethod
    def launch(client, body):
        return client.post("/api/sessions/s-third/runs", json=body)


class UnknownWorkflowRuntimeTests(ThirdWorkflowTestCase):
    """``_runtime_for`` on an id it has no runtime for."""

    def test_an_unregistered_runtime_raises_the_named_error(self) -> None:
        from brief_crew.service.graph import BRIEF_GRAPH, BRIEF_NODE_REGISTRY
        from brief_crew.service.registry import UnknownWorkflowError, WorkflowRuntime

        registry = self.registry(
            workflows={
                BRIEF_GRAPH.id: WorkflowRuntime(
                    graph_version=BRIEF_GRAPH.version,
                    node_registry=BRIEF_NODE_REGISTRY,
                    runner=InertRunner(),
                )
            }
        )

        with self.assertRaises(UnknownWorkflowError) as caught:
            registry.create_run(
                session_id="s-third",
                workflow_id="idea-validator",
                inputs={"idea": "a clinic scheduler"},
            )

        self.assertEqual(caught.exception.workflow_id, "idea-validator")
        self.assertIn("idea-validator", str(caught.exception))

    def test_it_is_still_a_KeyError(self) -> None:
        # Nothing that already catches the broad type may change behaviour -
        # `registry.require` raising KeyError for an unknown run is how the
        # transport already answers 404, and this joins that vocabulary.
        from brief_crew.service.registry import UnknownWorkflowError

        self.assertTrue(issubclass(UnknownWorkflowError, KeyError))

    def test_the_message_is_not_repr_wrapped(self) -> None:
        # KeyError.__str__ reprs its argument, so an un-overridden subclass
        # renders the whole sentence inside quotes and any transport that
        # forwarded it would ship a stray pair of them to the operator.
        from brief_crew.service.registry import UnknownWorkflowError

        message = str(UnknownWorkflowError(THIRD_ID))
        self.assertFalse(message.startswith("'"), message)
        self.assertIn(THIRD_ID, message)

    def test_a_registered_workflow_still_resolves(self) -> None:
        from brief_crew.service.graph import BRIEF_GRAPH, BRIEF_NODE_REGISTRY
        from brief_crew.service.registry import WorkflowRuntime

        runtime = WorkflowRuntime(
            graph_version=BRIEF_GRAPH.version,
            node_registry=BRIEF_NODE_REGISTRY,
            runner=InertRunner(),
        )
        registry = self.registry(workflows={BRIEF_GRAPH.id: runtime})

        self.assertIs(registry.workflow_runtime(BRIEF_GRAPH.id), runtime)

    def test_a_registry_with_no_workflow_map_still_serves_everything(self) -> None:
        # The single-runtime constructor is still legal and still answers for
        # any id; the refusal exists only for a registry that DOES declare a
        # map, which is the shape `create_app` builds.
        registry = self.registry(workflows=None)

        self.assertIsNotNone(registry.workflow_runtime("anything-at-all"))


class UnknownWorkflowHttpTests(ThirdWorkflowTestCase):
    """Three of the four registration places is a 404, not a 500."""

    def test_a_workflow_with_no_runtime_answers_404(self) -> None:
        from brief_crew.service.graph import BRIEF_GRAPH, BRIEF_NODE_REGISTRY
        from brief_crew.service.registry import WorkflowRuntime

        registry = self.registry(
            workflows={
                BRIEF_GRAPH.id: WorkflowRuntime(
                    graph_version=BRIEF_GRAPH.version,
                    node_registry=BRIEF_NODE_REGISTRY,
                    runner=InertRunner(),
                )
            }
        )
        client = self.client(registry)

        response = self.launch(
            client,
            {"workflow_id": "idea-validator", "inputs": {"idea": "a clinic scheduler"}},
        )

        self.assertEqual(response.status_code, 404, response.text)
        self.assertIn("idea-validator", response.json()["detail"])

    def test_a_workflow_nobody_declared_still_answers_404(self) -> None:
        # The control for the case above: an id in no map at all was already a
        # 404 and must stay one.
        registry = self.registry(workflows=None)
        client = self.client(registry)

        response = self.launch(
            client, {"workflow_id": "no-such-workflow", "inputs": {"topic": "x"}}
        )

        self.assertEqual(response.status_code, 404, response.text)


class WorkflowInputFieldTests(ThirdWorkflowTestCase):
    """The request-input key is the workflow's own, not the validator's negation."""

    def test_a_third_workflow_is_asked_for_its_OWN_field(self) -> None:
        client = self.register_third(gated=False, input_field=THIRD_INPUT_FIELD)

        response = self.launch(client, {"workflow_id": THIRD_ID, "inputs": {}})

        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertIn(f"inputs.{THIRD_INPUT_FIELD}", detail)
        self.assertNotIn("inputs.topic", detail)

    def test_a_third_workflow_launches_on_its_own_field(self) -> None:
        client = self.register_third(gated=False, input_field=THIRD_INPUT_FIELD)

        response = self.launch(
            client,
            {"workflow_id": THIRD_ID, "inputs": {THIRD_INPUT_FIELD: "a real brief"}},
        )

        self.assertEqual(response.status_code, 202, response.text)

    def test_the_prompt_length_bound_names_the_third_field_too(self) -> None:
        from brief_crew.config import MAX_RUN_INPUT_CHARS

        client = self.register_third(gated=False, input_field=THIRD_INPUT_FIELD)

        response = self.launch(
            client,
            {
                "workflow_id": THIRD_ID,
                "inputs": {THIRD_INPUT_FIELD: "x" * (MAX_RUN_INPUT_CHARS + 1)},
            },
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn(f"inputs.{THIRD_INPUT_FIELD}", response.json()["detail"])

    def test_a_workflow_that_declares_no_input_field_says_so(self) -> None:
        # The failure that replaces the silent "topic": a workflow registered
        # without declaring its input key is refused with its own id in the
        # sentence, rather than being asked for a field it never had.
        client = self.register_third(gated=False, input_field=None)

        response = self.launch(
            client, {"workflow_id": THIRD_ID, "inputs": {THIRD_INPUT_FIELD: "hello"}}
        )

        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertIn(THIRD_ID, detail)
        self.assertNotIn("inputs.topic", detail)

    def test_the_two_built_ins_are_unchanged(self) -> None:
        client = self.builtin_client()

        for workflow_id, field in (("brief-flow", "topic"), ("idea-validator", "idea")):
            with self.subTest(workflow_id=workflow_id):
                response = client.post(
                    "/api/sessions/s-builtin/runs",
                    json={"workflow_id": workflow_id, "inputs": {}},
                )
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn(f"inputs.{field}", response.json()["detail"])


class AutoGatesRuleTests(ThirdWorkflowTestCase):
    """``gates="auto"`` turns on whether the graph HAS gates, not on its id."""

    def _launch_auto(self, client):
        with patch("brief_crew.config.VALIDATOR_ALLOW_AUTO_GATES", True):
            return self.launch(
                client,
                {
                    "workflow_id": THIRD_ID,
                    "inputs": {THIRD_INPUT_FIELD: "a real brief"},
                    "gates": "auto",
                },
            )

    def test_a_third_workflow_that_HAS_gates_may_skip_them(self) -> None:
        client = self.register_third(gated=True, input_field=THIRD_INPUT_FIELD)

        response = self._launch_auto(client)

        self.assertEqual(response.status_code, 202, response.text)

    def test_a_third_workflow_with_no_gates_is_still_refused(self) -> None:
        client = self.register_third(gated=False, input_field=THIRD_INPUT_FIELD)

        response = self._launch_auto(client)

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn(THIRD_ID, response.json()["detail"])

    def test_brief_flow_is_still_refused_and_the_validator_still_allowed(self) -> None:
        # The two controls `test_gates_mode` already pins, restated here so a
        # change to the rule fails in the file that owns the rule.
        client = self.builtin_client()

        with patch("brief_crew.config.VALIDATOR_ALLOW_AUTO_GATES", True):
            refused = client.post(
                "/api/sessions/s-builtin-auto/runs",
                json={
                    "workflow_id": "brief-flow",
                    "inputs": {"topic": "anything"},
                    "gates": "auto",
                },
            )
            allowed = client.post(
                "/api/sessions/s-builtin-auto/runs",
                json={
                    "workflow_id": "idea-validator",
                    "inputs": {"idea": "a clinic scheduler"},
                    "gates": "auto",
                },
            )

        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertEqual(allowed.status_code, 202, allowed.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
