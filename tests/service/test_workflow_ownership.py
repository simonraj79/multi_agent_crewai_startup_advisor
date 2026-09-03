"""Plan 01 D1: a published graph belongs to whoever published it. Rubric 14.

Before this, `register_builder_workflow` recorded no owner, `create_run`
checked admission and gating but never ownership, and `GET /api/workflows/{id}`
answered for any id in the map - so user B could run user A's flow and pay for
it out of the platform key. Three checks close that, and each is asserted from
BOTH sides, because "Bob gets 404" is also what a broken registration answers:
Alice must succeed on the same id in the same test class.

Two properties carry the weight:

* The refusal is **404, not 403**, and it lands BEFORE admission. A 403
  confirms the graph exists; a slot taken for a request that is about to be
  refused is a slot a stranger can burn. `admission_status()` is read before
  and after, and the rate limiter - which deliberately runs first - is the one
  counter that IS allowed to move.
* A graph with NO owner stays launchable by anybody (00 S1 ruling 10,
  decision 26). Refusing it would strand every graph published anonymously,
  in `SYNTHETIC` mode, or before this change existed.

Nothing here spends anything: the app is `synthetic=True`, so a launch that is
admitted runs the real compiled definition over `SyntheticCrewFactories`.

**Round 2 (D-01-1).** The first version of this file sent only clean
`{"idea": ...}` bodies, and the criterion it ticked - "the 404 fires before any
admission counter moves" - was false for any body carrying one of the graph's
own state names: `CreateRunRequest.inputs`'s validator read the published
graph's registered keys and answered 422 BEFORE the rate limiter and before
the ownership 404, so a stranger could tell Alice's id from an invented one,
enumerate her node names, and never be throttled for it. The state-key classes
below send the bodies the first version did not, as Bob.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from brief_crew import config
from brief_crew.service.graph import BUILDER_WORKFLOWS
from tests.builder.test_compiler import straight_line
from tests.service.builder_registration import (
    BuilderRegistrationCleanup,
    forget_builder_workflow,
)
from tests.service.identities import (
    ALICE,
    BOB,
    SYNTHETIC_USER_HEADER,
    AuthenticatedTwoUserCase,
    wire,
)

UNKNOWN_ID = "ug_00000000"
#: A name shaped like a builder state slot that this graph does NOT declare.
#: The critic's probe distinguished `out__scoper` (422) from `out__market`
#: (404) on one id; both must now read as the plain 404 to anyone but the owner.
UNDECLARED_STATE_KEY = "out__not_a_node_here"

try:  # pragma: no cover - the service extra is optional, as elsewhere in tests/
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

IDEA = "a scheduling assistant for dental clinics"
BUILT_IN = {"brief-flow", "idea-validator"}
RUNS = "/api/sessions/session-ownership/runs"


def launch(workflow_id: str, **extra: Any) -> dict[str, Any]:
    return {"workflow_id": workflow_id, "inputs": {"idea": IDEA}, **extra}


def launch_with(workflow_id: str, state_key: str, **extra: Any) -> dict[str, Any]:
    """`launch`, plus one of the graph's own state names in `inputs`."""

    return {"workflow_id": workflow_id, "inputs": {"idea": IDEA, state_key: "x"}, **extra}


def graph_state_keys(workflow_id: str) -> list[str]:
    """The names a publish registered for this graph, beyond the global set."""

    return sorted(
        config.reserved_run_input_keys(workflow_id) - config.GLOBAL_RESERVED_RUN_INPUT_KEYS
    )


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class OwnedWorkflowTests(AuthenticatedTwoUserCase):
    """Alice publishes; Bob meets a wall that looks like nothing at all."""

    def setUp(self) -> None:
        super().setUp()
        self.document_id, self.workflow_id = self.publish(straight_line(), self.as_alice())
        self.registry = self.app.state.run_registry

    def test_the_published_graph_records_its_owner(self) -> None:
        self.assertEqual(BUILDER_WORKFLOWS[self.workflow_id].user_id, ALICE.id)

    def test_a_strangers_launch_is_404_before_any_admission_counter_moves(self) -> None:
        before = self.registry.admission_status()

        response = self.client.post(RUNS, json=launch(self.workflow_id), headers=self.as_bob())

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"], "workflow not found")
        self.assertEqual(self.registry.admission_status(), before)
        # Nothing was created for anybody: no run row, no history entry.
        self.assertEqual(
            self.client.get("/api/runs", headers=self.as_bob()).json()["runs"], []
        )
        self.assertEqual(self.registry.persistence.list_runs_for_user(BOB.id, limit=10), [])

    def test_the_ownership_404_wins_over_the_unattended_gates_403(self) -> None:
        """Ordering the UI relies on: a foreign graph is 404 whatever else is wrong."""

        response = self.client.post(
            RUNS, json=launch(self.workflow_id, gates="auto"), headers=self.as_bob()
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_the_owners_launch_is_admitted_and_completes(self) -> None:
        response = self.client.post(RUNS, json=launch(self.workflow_id), headers=self.as_alice())
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=30)
        status = self.client.get(f"/api/runs/{run_id}", headers=self.as_alice()).json()
        self.assertEqual(status["status"], "completed")

    def test_the_list_shows_the_graph_to_its_owner_alone(self) -> None:
        def ids(headers: dict[str, str] | None) -> set[str]:
            response = self.client.get("/api/workflows", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            return {entry["id"] for entry in response.json()}

        self.assertEqual(ids(self.as_alice()), BUILT_IN | {self.workflow_id})
        self.assertEqual(ids(self.as_bob()), BUILT_IN)
        # The signed-out probe the console makes on first paint keeps reading
        # exactly the two literals: a 200 with two entries, never a 401 and
        # never somebody's graph.
        self.assertEqual(ids(None), BUILT_IN)

    def test_the_owners_list_entry_carries_the_graphs_own_version(self) -> None:
        entries = self.client.get("/api/workflows", headers=self.as_alice()).json()
        # The two literals first, then what this person owns.
        self.assertEqual([entry["id"] for entry in entries[:2]], ["brief-flow", "idea-validator"])
        mine = next(entry for entry in entries if entry["id"] == self.workflow_id)
        self.assertEqual(mine["graph_version"], BUILDER_WORKFLOWS[self.workflow_id].graph_version)

    def test_the_graph_is_404_for_a_stranger_and_readable_by_its_owner(self) -> None:
        path = f"/api/workflows/{self.workflow_id}/graph"

        stranger = self.client.get(path, headers=self.as_bob())
        self.assertEqual(stranger.status_code, 404, stranger.text)
        # Not even the tag leaks: the check runs before the map is read.
        self.assertNotIn("ETag", stranger.headers)
        self.assertNotIn(self.workflow_id, stranger.text)

        owner = self.client.get(path, headers=self.as_alice())
        self.assertEqual(owner.status_code, 200, owner.text)
        self.assertIn("ETag", owner.headers)
        self.assertEqual(owner.json()["id"], self.workflow_id)

        self.assertEqual(self.client.get(path).status_code, 404)

    def test_the_built_in_graphs_stay_public(self) -> None:
        for workflow_id in sorted(BUILT_IN):
            with self.subTest(workflow_id=workflow_id):
                path = f"/api/workflows/{workflow_id}/graph"
                self.assertEqual(self.client.get(path, headers=self.as_bob()).status_code, 200)
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_an_unknown_id_and_a_foreign_id_are_the_same_answer(self) -> None:
        """The whole reason for 404: a stranger cannot tell the two apart."""

        foreign = self.client.post(RUNS, json=launch(self.workflow_id), headers=self.as_bob())
        unknown = self.client.post(RUNS, json=launch("ug_00000000"), headers=self.as_bob())
        self.assertEqual((foreign.status_code, foreign.json()), (unknown.status_code, unknown.json()))


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class StateKeyProbeTests(AuthenticatedTwoUserCase):
    """D-01-1: a body carrying one of Alice's state names tells Bob nothing.

    The order on `POST /runs` is rate limit, then ownership, then everything
    else - and "everything else" includes the reserved-key check, which for a
    published graph reads names only the owner is entitled to learn.
    """

    def setUp(self) -> None:
        super().setUp()
        self.document_id, self.workflow_id = self.publish(straight_line(), self.as_alice())
        self.registry = self.app.state.run_registry
        self.state_keys = graph_state_keys(self.workflow_id)
        # The probe space the critic used: the compiler's own marker, and one
        # `out__<node>` per node. Both must be present for the test to mean
        # anything.
        self.assertIn("__builder__", self.state_keys)
        self.assertTrue(any(key.startswith("out__") for key in self.state_keys), self.state_keys)

    def probe_keys(self) -> list[str]:
        declared_out = next(key for key in self.state_keys if key.startswith("out__"))
        return ["__builder__", declared_out, UNDECLARED_STATE_KEY]

    def test_a_strangers_state_key_probe_is_the_same_404_as_an_unknown_id(self) -> None:
        before = self.registry.admission_status()
        for key in self.probe_keys():
            with self.subTest(key=key):
                foreign = self.client.post(
                    RUNS, json=launch_with(self.workflow_id, key), headers=self.as_bob()
                )
                unknown = self.client.post(
                    RUNS, json=launch_with(UNKNOWN_ID, key), headers=self.as_bob()
                )
                self.assertEqual(foreign.status_code, 404, foreign.text)
                self.assertEqual(foreign.json(), {"detail": "workflow not found"})
                self.assertEqual(
                    (foreign.status_code, foreign.json()), (unknown.status_code, unknown.json())
                )
                # Neither the key nor the id comes back: the body is the same
                # three words whatever was sent.
                self.assertNotIn(key, foreign.text)
                self.assertNotIn(self.workflow_id, foreign.text)
        self.assertEqual(self.registry.admission_status(), before)

    def test_a_declared_and_an_undeclared_state_key_read_the_same_to_a_stranger(self) -> None:
        """The enumeration half: `out__scoper` and `out__market` were 422 and 404."""

        declared = next(key for key in self.state_keys if key.startswith("out__"))
        answers = {
            key: self.client.post(
                RUNS, json=launch_with(self.workflow_id, key), headers=self.as_bob()
            )
            for key in (declared, UNDECLARED_STATE_KEY)
        }
        self.assertEqual(
            {key: (r.status_code, r.json()) for key, r in answers.items()},
            {key: (404, {"detail": "workflow not found"}) for key in answers},
        )

    def test_the_owner_is_still_refused_a_state_key_with_a_422_naming_it(self) -> None:
        """Ownership moved the check later; it did not remove it."""

        for key in ("__builder__", next(k for k in self.state_keys if k.startswith("out__"))):
            with self.subTest(key=key):
                response = self.client.post(
                    RUNS, json=launch_with(self.workflow_id, key), headers=self.as_alice()
                )
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn(key, response.json()["detail"])
                self.assertIn("reserved control key", response.json()["detail"])

    def test_the_global_keys_are_still_refused_for_every_id_before_anything_else(self) -> None:
        """`no_gates` stays unsettable, and says so identically for any id."""

        for workflow_id in (self.workflow_id, UNKNOWN_ID):
            with self.subTest(workflow_id=workflow_id):
                response = self.client.post(
                    RUNS, json=launch_with(workflow_id, "no_gates"), headers=self.as_bob()
                )
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn("no_gates", response.text)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class StateKeyProbeIsChargedTests(AuthenticatedTwoUserCase):
    """The limiter runs FIRST, so a flood of state-key probes is throttled too.

    The critic's control: 15 rapid `__builder__` probes as a fresh user never
    tripped the 10/60 s limiter that a clean 404 probe trips on the 11th,
    because the schema refused them before the limiter saw them.
    """

    MAX_RUNS = 3

    def app_kwargs(self) -> dict[str, Any]:
        from brief_crew.service.app import RunRateLimiter

        return {
            "synthetic": True,
            "rate_limiter": RunRateLimiter(max_runs=self.MAX_RUNS, window_seconds=60),
        }

    def test_the_probe_after_the_limit_is_429(self) -> None:
        _, workflow_id = self.publish(straight_line(), self.as_alice())
        statuses = [
            self.client.post(
                RUNS, json=launch_with(workflow_id, "__builder__"), headers=self.as_bob()
            ).status_code
            for _ in range(self.MAX_RUNS + 1)
        ]
        self.assertEqual(statuses, [404] * self.MAX_RUNS + [429])
        # And the owner's bucket is her own: she is not paying for Bob's flood.
        owner = self.client.post(RUNS, json=launch(workflow_id), headers=self.as_alice())
        self.assertEqual(owner.status_code, 202, owner.text)
        self.app.state.run_registry.wait(owner.json()["run_id"], timeout=30)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class OwnershipSurvivesRestartTests(AuthenticatedTwoUserCase):
    """The boot sweep restores the owner with the row, not just the graph.

    Both Render services carry `autoDeploy: yes`, so every push restarts the
    API and every published graph comes back through `builder_rehydrate`. A
    rehydration that dropped `user_id` would turn Alice's graph into
    everybody's on the next deploy - with `builder_documents.user_id` still
    saying it was hers.
    """

    def _registry(self, persistence: Any) -> Any:
        from brief_crew.service.graph import (
            BRIEF_GRAPH,
            BRIEF_NODE_REGISTRY,
            VALIDATOR_GRAPH,
            VALIDATOR_NODE_REGISTRY,
        )
        from brief_crew.service.registry import RunRegistry, WorkflowRuntime
        from brief_crew.service.runner import SyntheticRunner, SyntheticValidatorRunner

        brief, idea = SyntheticRunner(), SyntheticValidatorRunner()
        registry = RunRegistry(
            graph_version=BRIEF_GRAPH.version,
            node_registry=BRIEF_NODE_REGISTRY,
            runner=brief,
            workflows={
                BRIEF_GRAPH.id: WorkflowRuntime(
                    graph_version=BRIEF_GRAPH.version,
                    node_registry=BRIEF_NODE_REGISTRY,
                    runner=brief,
                    input_field="topic",
                ),
                VALIDATOR_GRAPH.id: WorkflowRuntime(
                    graph_version=VALIDATOR_GRAPH.version,
                    node_registry=VALIDATOR_NODE_REGISTRY,
                    runner=idea,
                    input_field="idea",
                ),
            },
            persistence=persistence,
            gate_sweep_interval=0,
        )
        self.addCleanup(registry.close)
        return registry

    def app_kwargs(self) -> dict[str, Any]:
        from brief_crew.service.builder_runner import synthetic_builder_runner
        from brief_crew.service.persistence import PostgresFlowPersistence

        self.persistence = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.persistence.close)
        return {
            "registry": self._registry(self.persistence),
            "builder_runner_factory": synthetic_builder_runner,
        }

    def test_a_rehydrated_graph_is_still_alices_and_still_not_bobs(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app
        from brief_crew.service.builder_runner import synthetic_builder_runner

        _, workflow_id = self.publish(straight_line(), self.as_alice())
        self.assertEqual(BUILDER_WORKFLOWS[workflow_id].user_id, ALICE.id)

        # The restart: every process-local map is gone, the row is not.
        forget_builder_workflow(workflow_id)
        self.assertNotIn(workflow_id, BUILDER_WORKFLOWS)
        rebooted = create_app(
            registry=self._registry(self.persistence),
            builder_runner_factory=synthetic_builder_runner,
        )
        client = TestClient(rebooted)
        self.addCleanup(client.close)

        self.assertEqual(BUILDER_WORKFLOWS[workflow_id].user_id, ALICE.id)
        self.assertEqual(
            client.post(RUNS, json=launch(workflow_id), headers=self.as_bob()).status_code, 404
        )
        self.assertEqual(
            client.get(f"/api/workflows/{workflow_id}/graph", headers=self.as_bob()).status_code,
            404,
        )
        admitted = client.post(RUNS, json=launch(workflow_id), headers=self.as_alice())
        self.assertEqual(admitted.status_code, 202, admitted.text)
        rebooted.state.run_registry.wait(admitted.json()["run_id"], timeout=30)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class UnownedWorkflowTests(BuilderRegistrationCleanup):
    """Decision 26, built on its recommendation: nobody's graph is anybody's."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        super().setUp()
        for item in (
            patch.object(config, "AUTH_BASE_URL", ""),
            patch.object(config, "VALIDATOR_REQUIRE_AUTH", False),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.app = create_app(synthetic=True)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

        created = self.client.post("/api/builder/workflows", json={"document": wire(straight_line())})
        self.assertEqual(created.status_code, 201, created.text)
        document_id = created.json()["document"]["id"]
        published = self.client.post(f"/api/builder/workflows/{document_id}/publish")
        self.assertEqual(published.status_code, 200, published.text)
        self.workflow_id = published.json()["workflow_id"]
        self.track(self.workflow_id)

    @staticmethod
    def as_user(user_id: str) -> dict[str, str]:
        return {SYNTHETIC_USER_HEADER: user_id}

    def test_it_has_no_owner(self) -> None:
        self.assertIsNone(BUILDER_WORKFLOWS[self.workflow_id].user_id)

    def test_it_launches_for_anybody_who_is_somebody(self) -> None:
        registry = self.app.state.run_registry
        for user_id in ("alice", "bob"):
            with self.subTest(user=user_id):
                response = self.client.post(
                    RUNS, json=launch(self.workflow_id), headers=self.as_user(user_id)
                )
                self.assertEqual(response.status_code, 202, response.text)
                registry.wait(response.json()["run_id"], timeout=30)

    def test_it_is_listed_to_nobody_and_readable_by_everybody(self) -> None:
        # Listed on `/api/builder/workflows`, where the document lives; here an
        # anonymous caller must keep reading exactly the two literals.
        for headers in (self.as_user("alice"), self.as_user("bob"), None):
            with self.subTest(headers=headers):
                listed = {entry["id"] for entry in self.client.get("/api/workflows", headers=headers).json()}
                self.assertEqual(listed, BUILT_IN)
                graph = self.client.get(f"/api/workflows/{self.workflow_id}/graph", headers=headers)
                self.assertEqual(graph.status_code, 200, graph.text)

    def test_an_anonymous_launch_of_a_gateless_graph_is_still_403(self) -> None:
        """Ownership loosened nothing: the pre-existing spend cap still holds."""

        response = self.client.post(RUNS, json=launch(self.workflow_id))
        self.assertEqual(response.status_code, 403, response.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
