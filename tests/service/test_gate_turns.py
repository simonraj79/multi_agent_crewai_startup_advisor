"""What the operator is OFFERED once the revise budget runs out.

The router's bound (``tests/validator/test_gate_turns.py``) is durable and
final, but on its own it would produce the worst possible interface: a Revise
button that the server accepts, charges nothing for, and silently treats as an
approval. So the gate stops advertising the option, which - because
``answer_gate`` already refuses any outcome that is not one of the prompt's own
option ids - is simultaneously the transport-level refusal. These tests drive
the real ``ValidatorFlow`` through the real HTTP surface with crew doubles, so
what is asserted is the payload an operator's client would actually receive.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from crewai.flow.async_feedback import PendingFeedbackContext

from brief_crew.config import GATE_REVISE_TURNS_METADATA_KEY
from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import (
    GATE_REVISE_MAX_KEY,
    GATE_REVISE_REMAINING_KEY,
    RunRegistry,
    WorkflowRuntime,
    _metadata_turns_used,
)
from brief_crew.service.runner import ValidatorFlowRunner
from brief_crew.validator_flow import ValidatorCrewFactories
from tests.validator.test_flow import FakeRunner, fixtures


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

CAP = 1


def _option_ids(gate: dict) -> list[str]:
    return [option["id"] for option in gate["options"]]


class MetadataTurnsUsedTests(unittest.TestCase):
    """The count arrives as free-form JSON, so reading it must not be able to fail.

    ``PendingFeedbackContext.metadata`` is a plain dict that has been through
    JSON on its way to and from ``pending_feedback``. A gate is built at the
    exact moment a human is about to be asked something, so a ``ValueError``
    here would fail the run at its least forgivable point - and would do it for
    a *display* number.
    """

    def _context(self, metadata: dict | None) -> PendingFeedbackContext:
        return PendingFeedbackContext(
            flow_id="f",
            flow_class="c",
            method_name="confirm_scope",
            method_output="{}",
            message="",
            metadata=metadata if metadata is not None else {},
        )

    def test_a_plain_integer_is_read(self) -> None:
        self.assertEqual(
            _metadata_turns_used(self._context({GATE_REVISE_TURNS_METADATA_KEY: 3})), 3
        )

    def test_a_missing_key_means_nothing_has_been_spent(self) -> None:
        # The synthetic runner and any non-validator flow open gates with no
        # such key. "Nothing spent" is the honest reading, not an error.
        self.assertEqual(_metadata_turns_used(self._context({})), 0)

    def test_a_json_round_trip_shape_is_read(self) -> None:
        for raw in (2.0, "2"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    _metadata_turns_used(
                        self._context({GATE_REVISE_TURNS_METADATA_KEY: raw})
                    ),
                    2,
                )

    def test_nonsense_degrades_to_zero_rather_than_raising(self) -> None:
        for raw in (None, "many", [1], {"a": 1}):
            with self.subTest(raw=raw):
                self.assertEqual(
                    _metadata_turns_used(
                        self._context({GATE_REVISE_TURNS_METADATA_KEY: raw})
                    ),
                    0,
                )

    def test_a_negative_count_cannot_manufacture_extra_turns(self) -> None:
        self.assertEqual(
            _metadata_turns_used(
                self._context({GATE_REVISE_TURNS_METADATA_KEY: -50})
            ),
            0,
        )


class LegacyGatePromptTests(unittest.TestCase):
    """A gate row written before the bound existed must still validate."""

    def test_the_two_new_keys_are_optional(self) -> None:
        from brief_crew.service.models import GatePrompt

        prompt = GatePrompt(
            gate_id="g",
            node_id="confirm_scope",
            title="Confirm scope",
            summary="",
            editable=True,
            options=[{"id": "approve", "label": "Approve"}],
        )
        # None, not 0. A gate that predates the bound has an unknown budget;
        # 0 would mean "no revises left", which is a claim nobody made.
        self.assertIsNone(prompt.revise_turns_remaining)
        self.assertIsNone(prompt.max_revise_turns)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class GateTurnPayloadTests(unittest.TestCase):
    """The whole journey, over HTTP, against the real Flow with crew doubles."""

    def _harness(self):
        scope, market, sentiment, feasibility, verdict, report = fixtures()
        runners = {
            "scope": FakeRunner(scope),
            "market": FakeRunner(market),
            "sentiment": FakeRunner(sentiment),
            "feasibility": FakeRunner(feasibility),
            "synthesis": FakeRunner(verdict),
            "report": FakeRunner(report),
        }
        factories = ValidatorCrewFactories(
            scope=lambda: runners["scope"],
            market=lambda: runners["market"],
            sentiment=lambda: runners["sentiment"],
            feasibility=lambda: runners["feasibility"],
            synthesis=lambda *_: runners["synthesis"],
            report=lambda *_: runners["report"],
        )
        runner = ValidatorFlowRunner(crew_factories=factories)
        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        registry = RunRegistry(
            graph_version=VALIDATOR_GRAPH.version,
            node_registry=VALIDATOR_NODE_REGISTRY,
            runner=runner,
            workflows={
                VALIDATOR_GRAPH.id: WorkflowRuntime(
                    graph_version=VALIDATOR_GRAPH.version,
                    node_registry=VALIDATOR_NODE_REGISTRY,
                    runner=runner,
                )
            },
            persistence=store,
        )
        self.addCleanup(store.close)
        self.addCleanup(registry.close)
        return scope, runners, registry

    def _client(self, registry, directory: str):
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        patches = [
            patch(
                "brief_crew.validator_flow.OUTPUT_PATH",
                Path(directory) / "validation.md",
            ),
            patch("brief_crew.validator_flow.lookup_branch_cache", return_value=[]),
            # Both modules bind the knob by value at import, so both are
            # patched: the flow decides whether to honour a revise, the
            # registry decides whether to offer one. A test that patched only
            # one would be testing the two halves disagreeing.
            patch("brief_crew.validator_flow.VALIDATOR_MAX_GATE_TURNS", CAP),
            patch("brief_crew.service.registry.VALIDATOR_MAX_GATE_TURNS", CAP),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return TestClient(create_app(registry=registry))

    def _launch(self, client, registry, scope) -> tuple[str, dict]:
        run_id = client.post(
            "/api/sessions/gate-turns/runs",
            json={
                "workflow_id": "idea-validator",
                "inputs": {"idea": scope.startup_idea},
            },
        ).json()["run_id"]
        registry.wait(run_id, timeout=5)
        return run_id, client.get(f"/api/runs/{run_id}").json()["pending_gate"]

    def _reply(self, client, registry, run_id: str, gate: dict, outcome: str):
        response = client.post(
            f"/api/runs/{run_id}/gates/{gate['gate_id']}",
            json={"outcome": outcome, "fields": {}},
        )
        if response.status_code == 202:
            registry.wait(run_id, timeout=5)
        return response

    def test_a_fresh_gate_offers_revise_and_says_how_many_are_left(self) -> None:
        scope, _, registry = self._harness()
        with TemporaryDirectory() as directory:
            with self._client(registry, directory) as client:
                _, gate = self._launch(client, registry, scope)

        self.assertEqual(gate["node_id"], "confirm_scope")
        self.assertEqual(_option_ids(gate), ["approve", "revise"])
        # Both numbers, not just the remainder: a client needs the budget to
        # render "1 of 1 left" rather than a bare count with no scale.
        self.assertEqual(gate[GATE_REVISE_REMAINING_KEY], CAP)
        self.assertEqual(gate[GATE_REVISE_MAX_KEY], CAP)

    def test_the_gate_stops_offering_revise_once_the_budget_is_gone(self) -> None:
        scope, runners, registry = self._harness()
        with TemporaryDirectory() as directory:
            with self._client(registry, directory) as client:
                run_id, first = self._launch(client, registry, scope)
                self.assertEqual(
                    self._reply(client, registry, run_id, first, "revise").status_code,
                    202,
                )
                second = client.get(f"/api/runs/{run_id}").json()["pending_gate"]

        # Same gate node, reopened after the Scoper reran - and this time with
        # nothing left to spend, so the button is gone rather than inert.
        self.assertEqual(second["node_id"], "confirm_scope")
        self.assertEqual(_option_ids(second), ["approve"])
        self.assertEqual(second[GATE_REVISE_REMAINING_KEY], 0)
        self.assertEqual(second[GATE_REVISE_MAX_KEY], CAP)
        self.assertEqual(len(runners["scope"].inputs), 2)

    def test_a_revise_at_the_cap_is_refused_with_a_reason(self) -> None:
        scope, runners, registry = self._harness()
        with TemporaryDirectory() as directory:
            with self._client(registry, directory) as client:
                run_id, first = self._launch(client, registry, scope)
                self._reply(client, registry, run_id, first, "revise")
                second = client.get(f"/api/runs/{run_id}").json()["pending_gate"]
                refused = self._reply(client, registry, run_id, second, "revise")
                after = client.get(f"/api/runs/{run_id}").json()

        self.assertEqual(refused.status_code, 422, refused.text)
        detail = refused.json()["detail"]
        # "outcome must be one of ['approve']" would be true and useless. The
        # operator watched a button disappear; the refusal has to name the
        # budget and say what to do instead.
        self.assertIn("revise turns", detail)
        self.assertIn("approve", detail)
        # And the refusal is inert: the gate is still open, unanswered, and no
        # further escalation-tier call was made.
        self.assertEqual(after["status"], "waiting")
        self.assertEqual(after["pending_gate"]["gate_id"], second["gate_id"])
        self.assertEqual(len(runners["scope"].inputs), 2)

    def test_approve_still_works_at_the_cap_and_the_run_goes_on(self) -> None:
        # The capped gate must not be a dead end. Approve is the offered exit
        # and it has to take the run forward to the next gate.
        scope, _, registry = self._harness()
        with TemporaryDirectory() as directory:
            with self._client(registry, directory) as client:
                run_id, first = self._launch(client, registry, scope)
                self._reply(client, registry, run_id, first, "revise")
                second = client.get(f"/api/runs/{run_id}").json()["pending_gate"]
                self.assertEqual(
                    self._reply(client, registry, run_id, second, "approve").status_code,
                    202,
                )
                third = client.get(f"/api/runs/{run_id}").json()["pending_gate"]

        self.assertEqual(third["node_id"], "review_verdict")
        # A fresh gate with its own untouched budget: spending the scope's
        # revises must not disarm the operator at the verdict.
        self.assertEqual(_option_ids(third), ["approve", "revise"])
        self.assertEqual(third[GATE_REVISE_REMAINING_KEY], CAP)

    def test_cancel_still_works_at_the_cap(self) -> None:
        """The other exit, and the one that must never be removed with Revise.

        Cancel is a different endpoint on a different path - it does not go
        through ``answer_gate`` or the prompt's option list at all - so a
        change that pruned options could plausibly have taken it with it. An
        operator who has run out of revises and does not want to approve has to
        be able to stop the run.
        """
        scope, runners, registry = self._harness()
        with TemporaryDirectory() as directory:
            with self._client(registry, directory) as client:
                run_id, first = self._launch(client, registry, scope)
                self._reply(client, registry, run_id, first, "revise")
                second = client.get(f"/api/runs/{run_id}").json()["pending_gate"]
                self.assertEqual(second[GATE_REVISE_REMAINING_KEY], 0)

                cancelled = client.post(f"/api/runs/{run_id}/cancel")
                after = client.get(f"/api/runs/{run_id}").json()

        self.assertEqual(cancelled.status_code, 202, cancelled.text)
        self.assertEqual(after["status"], "cancelled")
        self.assertIsNone(after["pending_gate"])
        self.assertEqual(len(runners["scope"].inputs), 2)

    def test_the_gate_open_frame_carries_the_same_numbers(self) -> None:
        """A reconnecting client rebuilds the gate from frames, not from GET.

        ``GATE_OPEN`` carries the prompt verbatim, so if the budget lived only
        on the REST response a client that reconnected mid-gate would render
        the Revise button back.
        """
        scope, _, registry = self._harness()
        with TemporaryDirectory() as directory:
            with self._client(registry, directory) as client:
                run_id, first = self._launch(client, registry, scope)
                self._reply(client, registry, run_id, first, "revise")
                frames = client.get(
                    f"/api/runs/{run_id}/frames", params={"limit": 500}
                ).json()["frames"]

        # `/frames` returns transport envelopes: {"type": "frame", "data": ...}.
        opens = [
            frame["data"]["details"]
            for frame in frames
            if frame["data"]["kind"] == "gate_open"
            and frame["data"]["details"].get("node_id") == "confirm_scope"
        ]
        self.assertEqual(
            [details[GATE_REVISE_REMAINING_KEY] for details in opens], [CAP, 0]
        )
        self.assertEqual(
            [[option["id"] for option in details["options"]] for details in opens],
            [["approve", "revise"], ["approve"]],
        )


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class SyntheticGateTurnTests(unittest.TestCase):
    """The no-cost runner opens gates too, and must not be broken by the bound.

    ``SyntheticValidatorRunner`` builds its own ``PendingFeedbackContext`` and
    knows nothing about turn accounting, so its gates carry no stamp. The
    payload still has to be well formed - this is the app the E2E suite and
    every local UI session run against.
    """

    def test_a_synthetic_gate_reports_a_full_budget(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app
        from brief_crew.config import VALIDATOR_MAX_GATE_TURNS

        with TestClient(create_app(synthetic=True)) as client:
            run_id = client.post(
                "/api/sessions/synthetic-turns/runs",
                json={
                    "workflow_id": "idea-validator",
                    "inputs": {"idea": "a clinic scheduler"},
                },
            ).json()["run_id"]
            client.app.state.run_registry.wait(run_id, timeout=5)
            gate = client.get(f"/api/runs/{run_id}").json()["pending_gate"]

        self.assertEqual(_option_ids(gate), ["approve", "revise"])
        self.assertEqual(gate[GATE_REVISE_REMAINING_KEY], VALIDATOR_MAX_GATE_TURNS)
        self.assertEqual(gate[GATE_REVISE_MAX_KEY], VALIDATOR_MAX_GATE_TURNS)


if __name__ == "__main__":
    unittest.main()
