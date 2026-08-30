"""The HITL / no-HITL toggle, and the undeclared path it replaces.

Before this contract existed, ``inputs.no_gates`` reached ``ValidatorState``
verbatim: CrewAI merges kickoff inputs into the flow's pydantic state
(``{**current_state, **inputs}`` then ``model_validate``), the service forwarded
``request.inputs`` unfiltered through ``ValidatorFlowRunner``, and no layer of
``brief_crew.service`` mentioned the key at all. So the expensive unattended
mode was reachable from a public, unauthenticated endpoint with no flag, no
validation, no policy and no record that it had been used.

The tests that matter most here are therefore the refusals.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from brief_crew.service.app import create_app
from brief_crew.service.models import CreateRunRequest


class GatesModeRequestTests(unittest.TestCase):
    """The schema half: the mode is declared, the smuggled key is refused."""

    def test_gates_defaults_to_human(self) -> None:
        request = CreateRunRequest(workflow_id="idea-validator", inputs={"idea": "x"})
        self.assertEqual(request.gates, "human")

    def test_gates_accepts_the_two_named_modes(self) -> None:
        for mode in ("human", "auto"):
            with self.subTest(mode=mode):
                request = CreateRunRequest(
                    workflow_id="idea-validator", inputs={"idea": "x"}, gates=mode
                )
                self.assertEqual(request.gates, mode)

    def test_gates_refuses_an_unknown_mode(self) -> None:
        with self.assertRaises(ValueError):
            CreateRunRequest(workflow_id="idea-validator", inputs={"idea": "x"}, gates="off")

    def test_inputs_may_not_carry_no_gates(self) -> None:
        with self.assertRaises(ValueError) as caught:
            CreateRunRequest(
                workflow_id="idea-validator", inputs={"idea": "x", "no_gates": True}
            )
        self.assertIn("reserved control key", str(caught.exception))
        self.assertIn("no_gates", str(caught.exception))

    def test_inputs_may_not_carry_sequential_branches(self) -> None:
        # The sibling field. Its own source comment documents that request
        # inputs reach the state verbatim, which is what made `no_gates`
        # reachable too; both are reserved for the same reason.
        with self.assertRaises(ValueError) as caught:
            CreateRunRequest(
                workflow_id="idea-validator",
                inputs={"idea": "x", "sequential_branches": True},
            )
        self.assertIn("sequential_branches", str(caught.exception))

    def test_a_false_value_is_still_refused(self) -> None:
        # Refusal is on the KEY, not the value. `no_gates: false` is harmless in
        # effect but means the client believes it is steering something it is
        # not, and a client that thinks it disabled the unattended mode is worse
        # off than one told its request was misread.
        with self.assertRaises(ValueError):
            CreateRunRequest(
                workflow_id="idea-validator", inputs={"idea": "x", "no_gates": False}
            )

    def test_ordinary_inputs_still_pass(self) -> None:
        request = CreateRunRequest(
            workflow_id="idea-validator", inputs={"idea": "x", "namespace": "team-a"}
        )
        self.assertEqual(request.inputs["namespace"], "team-a")


class GatesModePolicyTests(unittest.TestCase):
    """The handler half: the deployment decides whether auto is allowed."""

    def setUp(self) -> None:
        self.app = create_app(synthetic=True)
        self.client = TestClient(self.app)
        # Session ids are caller-supplied; there is no mint endpoint.
        self.session_id = "s-gates"

    def _post(self, **body: object) -> object:
        return self.client.post(
            f"/api/sessions/{self.session_id}/runs",
            json={"workflow_id": "idea-validator", "inputs": {"idea": "a clinic scheduler"}, **body},
        )

    def test_human_gates_are_accepted_by_default(self) -> None:
        response = self._post()
        self.assertEqual(response.status_code, 202, response.text)

    def test_auto_gates_are_refused_when_the_deployment_has_not_opted_in(self) -> None:
        with patch("brief_crew.config.VALIDATOR_ALLOW_AUTO_GATES", False):
            response = self._post(gates="auto")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("unattended runs are disabled", response.json()["detail"])

    def test_auto_gates_are_accepted_when_the_deployment_opts_in(self) -> None:
        with patch("brief_crew.config.VALIDATOR_ALLOW_AUTO_GATES", True):
            response = self._post(gates="auto")
        self.assertEqual(response.status_code, 202, response.text)

    def test_auto_gates_are_refused_for_a_workflow_with_no_gates(self) -> None:
        with patch("brief_crew.config.VALIDATOR_ALLOW_AUTO_GATES", True):
            response = self.client.post(
                f"/api/sessions/{self.session_id}/runs",
                json={
                    "workflow_id": "brief-flow",
                    "inputs": {"topic": "anything"},
                    "gates": "auto",
                },
            )
        self.assertEqual(response.status_code, 422, response.text)

    def test_the_smuggled_key_is_refused_over_http(self) -> None:
        # The end-to-end version of the schema test: this exact body used to
        # start an unattended run against the public endpoint.
        response = self.client.post(
            f"/api/sessions/{self.session_id}/runs",
            json={
                "workflow_id": "idea-validator",
                "inputs": {"idea": "a clinic scheduler", "no_gates": True},
            },
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_the_smuggled_key_is_refused_even_when_auto_is_allowed(self) -> None:
        # Opting in to `gates: "auto"` must not reopen the undeclared door: the
        # policy check is worth nothing if there is a second way in beside it.
        with patch("brief_crew.config.VALIDATOR_ALLOW_AUTO_GATES", True):
            response = self.client.post(
                f"/api/sessions/{self.session_id}/runs",
                json={
                    "workflow_id": "idea-validator",
                    "inputs": {"idea": "a clinic scheduler", "no_gates": True},
                },
            )
        self.assertEqual(response.status_code, 422, response.text)


class UnattendedRunTests(unittest.TestCase):
    """An auto run reaches a terminal state without anyone answering a gate."""

    def test_an_auto_run_completes_with_no_gate_reply(self) -> None:
        app = create_app(synthetic=True)
        client = TestClient(app)
        session_id = "s-auto"
        with patch("brief_crew.config.VALIDATOR_ALLOW_AUTO_GATES", True):
            created = client.post(
                f"/api/sessions/{session_id}/runs",
                json={
                    "workflow_id": "idea-validator",
                    "inputs": {"idea": "a clinic scheduler"},
                    "gates": "auto",
                },
            )
        self.assertEqual(created.status_code, 202, created.text)
        run_id = created.json()["run_id"]

        snapshot = _await_terminal(client, run_id)
        self.assertEqual(snapshot["status"], "completed", snapshot)
        self.assertIsNone(snapshot["pending_gate"])
        # The whole point of the mode: a report exists and nobody was asked.
        self.assertIn("markdown_body", snapshot["result"])

    def test_a_human_run_stops_at_the_first_gate_instead(self) -> None:
        app = create_app(synthetic=True)
        client = TestClient(app)
        session_id = "s-human"
        created = client.post(
            f"/api/sessions/{session_id}/runs",
            json={"workflow_id": "idea-validator", "inputs": {"idea": "a clinic scheduler"}},
        )
        run_id = created.json()["run_id"]

        snapshot = _await_gate(client, run_id)
        self.assertEqual(snapshot["status"], "waiting")
        self.assertIsNotNone(snapshot["pending_gate"])


def _poll(client: TestClient, run_id: str, done) -> dict:
    import time

    deadline = time.monotonic() + 10.0
    snapshot: dict = {}
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/runs/{run_id}").json()
        if done(snapshot):
            return snapshot
        time.sleep(0.05)
    return snapshot


def _await_terminal(client: TestClient, run_id: str) -> dict:
    return _poll(client, run_id, lambda s: s["status"] in {"completed", "failed", "error"})


def _await_gate(client: TestClient, run_id: str) -> dict:
    return _poll(client, run_id, lambda s: s["pending_gate"] is not None)


if __name__ == "__main__":
    unittest.main()


class ReservedKeyCoverageTests(unittest.TestCase):
    """Every ``ValidatorState`` field is either public or reserved.

    CrewAI merges kickoff inputs into the flow's state wholesale, so each field
    on that model is part of the public HTTP surface whether anyone intended it
    or not. The first version of ``RESERVED_RUN_INPUT_KEYS`` named two while its
    comment claimed to describe all of them - this test is what makes the claim
    checkable, and it fails when a new state field is added without someone
    deciding which side of the line it falls on.
    """

    def test_no_state_field_is_unaccounted_for(self) -> None:
        from brief_crew.config import PUBLIC_RUN_INPUT_KEYS, RESERVED_RUN_INPUT_KEYS
        from brief_crew.validator_flow import ValidatorState

        unaccounted = (
            set(ValidatorState.model_fields) - RESERVED_RUN_INPUT_KEYS - PUBLIC_RUN_INPUT_KEYS
        )
        self.assertEqual(
            unaccounted,
            set(),
            "new ValidatorState field(s) reachable from the public run endpoint; "
            "add each to RESERVED_RUN_INPUT_KEYS or PUBLIC_RUN_INPUT_KEYS in config.py",
        )

    def test_the_two_categories_do_not_overlap(self) -> None:
        from brief_crew.config import PUBLIC_RUN_INPUT_KEYS, RESERVED_RUN_INPUT_KEYS

        self.assertEqual(RESERVED_RUN_INPUT_KEYS & PUBLIC_RUN_INPUT_KEYS, set())

    def test_the_deployment_cache_knob_is_not_settable_per_request(self) -> None:
        # `feasibility_cache_enabled` mirrors VALIDATOR_FEASIBILITY_CACHE_ENABLED,
        # a deployment-level env knob. An anonymous caller flipping it per run is
        # the same class of defect as the `no_gates` hole this module exists for.
        with self.assertRaises(ValueError) as caught:
            CreateRunRequest(
                workflow_id="idea-validator",
                inputs={"idea": "x", "feasibility_cache_enabled": True},
            )
        self.assertIn("feasibility_cache_enabled", str(caught.exception))

    def test_the_legitimate_inputs_still_pass(self) -> None:
        for name in ("idea", "topic", "namespace"):
            with self.subTest(name=name):
                CreateRunRequest(workflow_id="idea-validator", inputs={name: "x"})
