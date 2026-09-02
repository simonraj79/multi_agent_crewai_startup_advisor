"""Two small refusals that presented as something much worse.

**`POST /api/builder/validate` answered 500 on a non-numeric `version`.** It is
the only endpoint that reads a version off the request BODY rather than off a
typed field - `save` has `expected_version: int | None` and `publish` has a
`Query(ge=1)`, both of which pydantic refuses before the handler runs - so it
was the one place a bare `int(...)` had nothing standing in front of it. The
canvas treats every 5xx as `unreachable`, so `{"version": "soon"}` presented as
a document that mysteriously would not validate, pointing at the network rather
than at a field.

**A publish this build cannot host answered 500.** `BuilderServiceUnavailable`
carried a docstring promising a 503 and had no handler anywhere, so a registry
with no `workflows` map - the older single-workflow shape a dozen test modules
build - turned a refusal the service had a good reason to make into the one
status that says the fault is the server's. Its sibling refusal, a missing
document store, already answered 503 from `require_store`.

**`list_my_runs` labelled history with `inputs.get("idea") or
inputs.get("topic")`**, the same two-literal guess `create_run` used to make and
that `workflow_input_field` was written to retire. It is right for exactly the
two built-in workflows, so a builder graph whose input field is anything else
drew an EMPTY row - which reads as a run that lost its inputs rather than as a
sidebar asking the wrong key.

Nothing here calls a model or touches a network: the validate half is pure
parsing, and the history half asks a `RunRegistry` for a `WorkflowRuntime` and
never runs anything.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from brief_crew.service.registry import (
    RunRegistry,
    UnknownWorkflowError,
    WorkflowRuntime,
)
from tests.builder.test_compiler import straight_line
from tests.service.builder_registration import BuilderRegistrationCleanup

try:  # pragma: no cover - the service extra is optional, as elsewhere in tests/
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False


IDEA = "A scheduling assistant for dental clinics"


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class ValidateVersionGuardTests(unittest.TestCase):
    """The 500 that looked like the server being down."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.app = create_app(synthetic=True, database_url="sqlite+pysqlite:///:memory:")
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.document = json.loads(straight_line().model_dump_json())

    def _validate(self, version: Any) -> Any:
        payload = dict(self.document)
        payload["version"] = version
        return self.client.post("/api/builder/validate", json={"document": payload})

    def test_a_word_where_a_version_should_be_is_a_422_and_not_a_500(self) -> None:
        response = self._validate("not-a-number")
        self.assertEqual(response.status_code, 422, response.text)

    def test_the_refusal_says_what_is_wrong_and_quotes_what_was_sent(self) -> None:
        detail = self._validate("soon").json()["detail"]
        self.assertIn("whole number", detail)
        self.assertIn("soon", detail)

    def test_a_list_and_a_mapping_are_refused_the_same_way(self) -> None:
        """`int()` raises TypeError rather than ValueError for these two."""

        for version in ([1, 2], {"v": 1}):
            with self.subTest(version=version):
                self.assertEqual(self._validate(version).status_code, 422)

    def test_a_float_string_is_refused_rather_than_silently_truncated(self) -> None:
        self.assertEqual(self._validate("1.9").status_code, 422)

    def test_a_real_version_still_validates(self) -> None:
        response = self._validate(3)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["valid"])

    def test_a_numeric_string_is_still_accepted(self) -> None:
        """Behaviour preserved on purpose: the old `int()` took this."""

        self.assertEqual(self._validate("3").status_code, 200)

    def test_a_missing_version_still_validates(self) -> None:
        payload = dict(self.document)
        payload.pop("version", None)
        response = self.client.post("/api/builder/validate", json={"document": payload})
        self.assertEqual(response.status_code, 200, response.text)

    def test_zero_and_empty_still_mean_the_author_did_not_say(self) -> None:
        for version in (0, "", None):
            with self.subTest(version=version):
                self.assertEqual(self._validate(version).status_code, 200)

    def test_a_document_naming_an_unbuildable_crew_is_reported_here(self) -> None:
        """Item 6's other half, at the endpoint the canvas actually polls.

        `library_problems` used to run only inside `compile_document`, so this
        answered `valid: true` and Publish then refused - and the author had no
        way to tell that from a broken server.
        """

        from tests.builder.test_crew_library_arity import one_crew_document

        payload = json.loads(one_crew_document("synthesis").model_dump_json())
        response = self.client.post("/api/builder/validate", json={"document": payload})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["valid"])
        self.assertTrue(
            any("SynthesisCrew" in problem["message"] for problem in body["problems"])
        )


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class PublishWithNowhereToRegisterTests(BuilderRegistrationCleanup):
    """The 500 that should always have been a 503.

    A registry built with no `workflows` map answers for ANY id from one
    default runtime, so putting a builder graph into it would change what every
    OTHER workflow resolves to - `_register_runtime` refuses that shape rather
    than quietly upgrading it, and refusing is right. What was wrong was the
    status: nothing caught the exception, so the author was told the server had
    broken on a request it had understood and deliberately declined.
    """

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app
        from brief_crew.service.graph import BRIEF_GRAPH, BRIEF_NODE_REGISTRY
        from brief_crew.service.persistence import PostgresFlowPersistence

        super().setUp()
        persistence = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(persistence.close)
        # Persistence but NO `workflows` map: the store answers, so the routes
        # get past `require_store`'s own 503 and reach the one this pins.
        self.registry = RunRegistry(
            graph_version=BRIEF_GRAPH.version,
            node_registry=BRIEF_NODE_REGISTRY,
            runner=_NoRunner(),
            persistence=persistence,
            gate_sweep_interval=0,
        )
        self.addCleanup(self.registry.close)
        app = create_app(
            registry=self.registry,
            builder_runner_factory=lambda workflow: _NoRunner(),
        )
        # `raise_server_exceptions=False` so an unhandled exception comes back
        # as the 500 a browser would see. Without it the reverted code raises
        # into the test instead, which is a different failure and a much less
        # legible one.
        self.client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def test_publishing_into_a_single_workflow_registry_is_a_503(self) -> None:
        created = self.client.post(
            "/api/builder/workflows",
            json={"document": json.loads(straight_line().model_dump_json())},
        )
        self.assertEqual(created.status_code, 201, created.text)
        document_id = created.json()["document"]["id"]

        published = self.client.post(f"/api/builder/workflows/{document_id}/publish")

        self.assertEqual(published.status_code, 503, published.text)
        self.assertIn("single-workflow registry", published.json()["detail"])
        # Refused, and refused CLEANLY: the module maps are rolled back, so a
        # graph is never left registered with no runtime behind it - which is
        # the 404 on launch that reads as a service defect.
        self.assertEqual(
            [entry["id"] for entry in self.client.get("/api/workflows").json()],
            ["brief-flow", "idea-validator"],
        )


class _NoRunner:
    """A `Runner` that is never called: these tests resolve, they do not run."""

    def __call__(self, execution: Any) -> Any:  # pragma: no cover - never invoked
        raise AssertionError("no run should start in a labelling test")


def _runtime(input_field: str | None) -> WorkflowRuntime:
    from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY

    return WorkflowRuntime(
        graph_version=VALIDATOR_GRAPH.version,
        node_registry=VALIDATOR_NODE_REGISTRY,
        runner=_NoRunner(),
        input_field=input_field,
    )


class HistoryLabelTests(unittest.TestCase):
    """The sidebar reads the workflow's own input key, not two literals."""

    def _registry(self, workflows: dict[str, WorkflowRuntime]) -> RunRegistry:
        from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY

        registry = RunRegistry(
            graph_version=VALIDATOR_GRAPH.version,
            node_registry=VALIDATOR_NODE_REGISTRY,
            runner=_NoRunner(),
            workflows=workflows,
        )
        self.addCleanup(registry.close)
        return registry

    def test_a_builder_graph_with_its_own_input_field_is_labelled(self) -> None:
        from brief_crew.service.app import run_history_label

        registry = self._registry({"ug_abc": _runtime("brief")})
        self.assertEqual(
            run_history_label(registry, "ug_abc", {"brief": IDEA}),
            IDEA,
        )

    def test_that_row_used_to_be_blank(self) -> None:
        """The defect itself, stated as the thing that no longer happens."""

        from brief_crew.service.app import run_history_label

        registry = self._registry({"ug_abc": _runtime("brief")})
        inputs = {"brief": IDEA}
        self.assertEqual(inputs.get("idea") or inputs.get("topic") or "", "")
        self.assertNotEqual(run_history_label(registry, "ug_abc", inputs), "")

    def test_the_two_built_in_workflows_are_unchanged(self) -> None:
        from brief_crew.service.app import run_history_label
        from brief_crew.service.graph import BRIEF_GRAPH, VALIDATOR_GRAPH

        registry = self._registry(
            {
                VALIDATOR_GRAPH.id: _runtime("idea"),
                BRIEF_GRAPH.id: _runtime("topic"),
            }
        )
        self.assertEqual(
            run_history_label(registry, VALIDATOR_GRAPH.id, {"idea": IDEA}), IDEA
        )
        self.assertEqual(
            run_history_label(registry, BRIEF_GRAPH.id, {"topic": "Rust"}), "Rust"
        )

    def test_a_runtime_that_declares_nothing_falls_back_to_the_two_literals(self) -> None:
        """Every `WorkflowRuntime` built before `input_field` existed is here."""

        from brief_crew.service.app import run_history_label

        registry = self._registry({"legacy": _runtime(None)})
        self.assertEqual(run_history_label(registry, "legacy", {"idea": IDEA}), IDEA)
        self.assertEqual(run_history_label(registry, "legacy", {"topic": "Rust"}), "Rust")

    def test_an_unregistered_workflow_is_answered_rather_than_raised(self) -> None:
        """A builder graph published before the process restarted.

        Its rows are still in the table, and a history PAGE must not fail whole
        because one of them names a workflow this process has never heard of.
        """

        from brief_crew.service.app import run_history_label

        registry = self._registry({"ug_abc": _runtime("brief")})
        with self.assertRaises(UnknownWorkflowError):
            registry.workflow_runtime("ug_gone")
        self.assertEqual(run_history_label(registry, "ug_gone", {"idea": IDEA}), IDEA)
        self.assertEqual(run_history_label(registry, "ug_gone", {"brief": IDEA}), "")

    def test_an_empty_declared_field_falls_back_rather_than_blanking(self) -> None:
        """A row written before the workflow declared this key."""

        from brief_crew.service.app import run_history_label

        registry = self._registry({"ug_abc": _runtime("brief")})
        self.assertEqual(
            run_history_label(registry, "ug_abc", {"brief": "", "idea": IDEA}), IDEA
        )

    def test_nothing_to_say_is_the_empty_string_and_not_a_crash(self) -> None:
        from brief_crew.service.app import run_history_label

        registry = self._registry({"ug_abc": _runtime("brief")})
        self.assertEqual(run_history_label(registry, "ug_abc", {}), "")

    def test_a_non_string_input_is_rendered_rather_than_dropped(self) -> None:
        from brief_crew.service.app import run_history_label

        registry = self._registry({"ug_abc": _runtime("count")})
        self.assertEqual(run_history_label(registry, "ug_abc", {"count": 7}), "7")


if __name__ == "__main__":
    unittest.main()
