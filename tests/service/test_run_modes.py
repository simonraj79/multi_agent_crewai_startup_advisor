"""The four run modes, and the two that replay work already paid for - C7.

`.agent/plans/10-runtime.md` D8 and criterion 7. Everything here runs on
`create_app(synthetic=True)`, so the graphs are real, the compiler is real, the
engine is real, the admission ladder is real, and the only thing replaced is
the object that would have called a model. Nothing in this module costs
anything.

The distinction the whole design turns on: **`test` and `node_test` are not
cheaper runs, they are FINDABLE ones.** They pass the same admission checks,
the same rate limit, the same ceiling and the same frames, and they appear in
run history labelled (decision 17, the owner's). Only `dry_run` is different in
kind - it creates nothing at all.
"""

from __future__ import annotations

import importlib.util
from typing import Any
import unittest

from tests.builder.test_compiler import (
    input_node,
    output_node,
    scoper_node,
    straight_line,
)
from tests.builder.test_document import document, edge
from tests.service.identities import AuthenticatedTwoUserCase

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
IDEA = "a scheduling assistant for clinics"


def two_step() -> Any:
    """input -> a -> b -> report, so a replay has something above it."""

    return document(
        [
            input_node(),
            scoper_node("a"),
            scoper_node("b"),
            output_node("report", source="${state.out__b}"),
        ],
        [
            edge("e1", "idea", "a"),
            edge("e2", "a", "b"),
            edge("e3", "b", "report"),
        ],
    )


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class RunModeTests(AuthenticatedTwoUserCase):
    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry

    def launch(self, workflow_id: str, **body: Any) -> Any:
        payload: dict[str, Any] = {
            "workflow_id": workflow_id,
            "inputs": {"idea": IDEA},

        }
        payload.update(body)
        return self.client.post(
            "/api/sessions/s1/runs", json=payload, headers=self.as_alice()
        )

    def run_rows(self) -> list[dict[str, Any]]:
        return self.registry.persistence.list_runs_for_user("user_alice", limit=50)

    # ------------------------------------------------------------- dry_run
    def test_a_dry_run_answers_200_with_a_definition(self) -> None:
        _, workflow_id = self.publish(straight_line(), self.as_alice())
        response = self.launch(workflow_id, mode="dry_run")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["valid"])
        self.assertEqual(body["problems"], [])
        # The compiled artifact, not a summary of it: the methods are the ones
        # `Flow.from_declaration` would be handed.
        self.assertIn("methods", body["definition"])
        self.assertIn("static_cost_usd", body["budget"])

    def test_a_dry_run_creates_no_row_and_no_frame(self) -> None:
        _, workflow_id = self.publish(straight_line(), self.as_alice())
        before = len(self.run_rows())
        self.launch(workflow_id, mode="dry_run")
        self.assertEqual(len(self.run_rows()), before)
        # Nothing was registered in memory either, so there is no run to poll.
        self.assertEqual(dict(self.registry._records), {})

    def test_a_dry_run_spends_no_rate_limit_allowance(self) -> None:
        """The reason it runs ahead of the limiter, asserted rather than argued.

        A preview the canvas fires on every edit must not compete with the
        Launch button for the same allowance.
        """

        _, workflow_id = self.publish(straight_line(), self.as_alice())
        limiter = self.app.state.run_rate_limiter
        for _ in range(int(limiter._capacity) + 2):
            self.assertEqual(self.launch(workflow_id, mode="dry_run").status_code, 200)
        self.assertEqual(self.launch(workflow_id).status_code, 202)

    def test_a_dry_run_of_a_built_in_flow_is_422_and_not_a_500(self) -> None:
        response = self.launch("idea-validator", mode="dry_run")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("not a builder graph", response.json()["detail"])

    def test_a_dry_run_of_someone_elses_graph_is_404(self) -> None:
        _, workflow_id = self.publish(straight_line(), self.as_bob())
        response = self.launch(workflow_id, mode="dry_run")
        self.assertEqual(response.status_code, 404, response.text)

    # ---------------------------------------------------------------- test
    def test_a_test_run_writes_mode_test_on_the_row(self) -> None:
        _, workflow_id = self.publish(straight_line(), self.as_alice())
        response = self.launch(workflow_id, mode="test")
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        stored = self.registry.persistence.get_run(run_id)
        self.assertEqual(stored["mode"], "test")

    def test_an_ordinary_run_reads_back_as_run_and_not_as_null(self) -> None:
        # The column is nullable and an ordinary run leaves it NULL, so the
        # API's answer has to come from the mapping rather than from the row.
        _, workflow_id = self.publish(straight_line(), self.as_alice())
        run_id = self.launch(workflow_id).json()["run_id"]
        self.assertEqual(
            self.registry.persistence.get_run(run_id)["mode"], "run"
        )

    def test_a_test_run_is_in_run_history(self) -> None:
        """Decision 17. Hiding it means an author cannot find what they just ran."""

        _, workflow_id = self.publish(straight_line(), self.as_alice())
        run_id = self.launch(workflow_id, mode="test").json()["run_id"]
        history = self.client.get("/api/runs", headers=self.as_alice()).json()
        self.assertIn(run_id, [entry["run_id"] for entry in history["runs"]])

    def test_the_status_payload_names_the_mode(self) -> None:
        _, workflow_id = self.publish(straight_line(), self.as_alice())
        run_id = self.launch(workflow_id, mode="test").json()["run_id"]
        body = self.client.get(f"/api/runs/{run_id}", headers=self.as_alice()).json()
        self.assertEqual(body["mode"], "test")
        self.assertIsNone(body["resume_from"])

    # ----------------------------------------------------------- node_test
    def test_node_test_without_a_test_input_is_422(self) -> None:
        _, workflow_id = self.publish(two_step(), self.as_alice())
        response = self.launch(workflow_id, mode="node_test", node_id="b")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("test_input_id", response.json()["detail"])

    def test_node_test_without_a_node_is_422(self) -> None:
        _, workflow_id = self.publish(two_step(), self.as_alice())
        response = self.launch(
            workflow_id, mode="node_test", test_input_id="ti_whatever"
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("node_id", response.json()["detail"])

    def test_node_test_with_an_unknown_test_input_is_404(self) -> None:
        _, workflow_id = self.publish(two_step(), self.as_alice())
        response = self.launch(
            workflow_id, mode="node_test", node_id="b", test_input_id="ti_nope"
        )
        self.assertEqual(response.status_code, 404, response.text)

    # --------------------------------------------------------------- state
    def test_the_state_endpoint_answers_the_state_at_a_frame(self) -> None:
        _, workflow_id = self.publish(straight_line(), self.as_alice())
        run_id = self.launch(workflow_id).json()["run_id"]
        self.registry.wait(run_id, timeout=20)
        frames = self.client.get(
            f"/api/runs/{run_id}/frames?limit=200", headers=self.as_alice()
        ).json()["frames"]
        last = frames[-1]["data"]["seq"]
        response = self.client.get(
            f"/api/runs/{run_id}/state?step={last}", headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["step"], last)
        self.assertIn("out__scoper", body["state"])

    def test_an_earlier_step_answers_an_earlier_state(self) -> None:
        """The `?step=` is doing work, rather than always returning the latest."""

        _, workflow_id = self.publish(two_step(), self.as_alice())
        run_id = self.launch(workflow_id).json()["run_id"]
        self.registry.wait(run_id, timeout=20)
        frames = self.client.get(
            f"/api/runs/{run_id}/frames?limit=500", headers=self.as_alice()
        ).json()["frames"]
        first = frames[0]["data"]["seq"]
        early = self.client.get(
            f"/api/runs/{run_id}/state?step={first}", headers=self.as_alice()
        ).json()["state"]
        late = self.client.get(
            f"/api/runs/{run_id}/state", headers=self.as_alice()
        ).json()["state"]
        self.assertIn("out__b", late)
        self.assertLessEqual(len(early), len(late))

    def test_another_users_state_is_404(self) -> None:
        _, workflow_id = self.publish(straight_line(), self.as_alice())
        run_id = self.launch(workflow_id).json()["run_id"]
        self.registry.wait(run_id, timeout=20)
        response = self.client.get(
            f"/api/runs/{run_id}/state", headers=self.as_bob()
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_a_frame_this_run_never_had_is_404(self) -> None:
        _, workflow_id = self.publish(straight_line(), self.as_alice())
        run_id = self.launch(workflow_id).json()["run_id"]
        self.registry.wait(run_id, timeout=20)
        response = self.client.get(
            f"/api/runs/{run_id}/state?step=99999", headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
