from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from brief_crew.events import FrameKind, UIEventType
from brief_crew.service.graph import (
    BRIEF_GRAPH,
    BRIEF_NODE_REGISTRY,
    VALIDATOR_GRAPH,
    VALIDATOR_NODE_REGISTRY,
)
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import RunRegistry, WorkflowRuntime
from brief_crew.service.runner import RunExecution, ValidatorFlowRunner
from brief_crew.validator_flow import ValidatorCrewFactories
from tests.validator.test_flow import FakeRunner, fixtures


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class ValidatorServiceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.client = TestClient(create_app(synthetic=True))

    def tearDown(self) -> None:
        self.client.close()

    def test_both_graphs_are_exposed_with_derived_routes(self) -> None:
        workflows = self.client.get("/api/workflows")
        self.assertEqual(workflows.status_code, 200)
        self.assertEqual(
            {workflow["id"] for workflow in workflows.json()},
            {"brief-flow", "idea-validator"},
        )

        brief = self.client.get("/api/workflows/brief-flow/graph").json()
        brief_routes = {
            (edge["source"], edge["route"], edge["target"])
            for edge in brief["edges"]
        }
        self.assertIn(("check_cache", "cache_hit", "write_brief"), brief_routes)
        self.assertIn(("check_cache", "cache_miss", "scrape_web"), brief_routes)

        validator = self.client.get("/api/workflows/idea-validator/graph").json()
        node_by_id = {node["id"]: node for node in validator["nodes"]}
        self.assertEqual(node_by_id["confirm_scope"]["kind"], "gate")
        self.assertEqual(node_by_id["review_verdict"]["kind"], "gate")
        self.assertEqual(node_by_id["unattributed"]["kind"], "quarantine")
        self.assertEqual(node_by_id["research_market"]["position"], {"x": 35.0, "y": 520.0})

        routes = {
            (edge["source"], edge["route"], edge["target"])
            for edge in validator["edges"]
        }
        self.assertEqual(
            {
                target
                for source, route, target in routes
                if source == "route_scope" and route == "scope_approved"
            },
            {"research_market", "research_sentiment", "research_feasibility"},
        )
        self.assertIn(("route_scope", "scope_revise", "revise_scope"), routes)
        self.assertIn(("route_verdict", "verdict_revise", "revise_verdict"), routes)

    def test_two_gate_round_trips_duplicate_replay_and_logs(self) -> None:
        run_id = self._start_validator()
        registry = self.client.app.state.run_registry
        registry.wait(run_id, timeout=2)

        first_status = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(first_status["status"], "waiting")
        first_gate = first_status["pending_gate"]
        self.assertEqual(first_gate["node_id"], "confirm_scope")
        self.assertTrue(first_gate["editable"])
        self.assertEqual(
            {option["id"] for option in first_gate["options"]},
            {"approve", "revise"},
        )

        first_reply = self.client.post(
            f"/api/runs/{run_id}/gates/{first_gate['gate_id']}",
            json={"outcome": "approve", "fields": {"category": "Design tooling"}},
        )
        self.assertEqual(first_reply.status_code, 202)
        registry.wait(run_id, timeout=2)

        duplicate = self.client.post(
            f"/api/runs/{run_id}/gates/{first_gate['gate_id']}",
            json={"outcome": "approve", "fields": {}},
        )
        self.assertEqual(duplicate.status_code, 409)

        second_status = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(second_status["status"], "waiting")
        second_gate = second_status["pending_gate"]
        self.assertEqual(second_gate["node_id"], "review_verdict")
        self.assertEqual(second_gate["verdict"], "NEEDS_WORK")
        self.assertEqual(second_gate["confidence"], 0.62)
        self.assertNotEqual(second_gate["gate_id"], first_gate["gate_id"])

        before_second_reply = self.client.get(
            f"/api/runs/{run_id}/frames?after=0&limit=500"
        ).json()["frames"]
        reconnect_after = before_second_reply[-2]["data"]["seq"]
        expected_replay = [
            envelope["data"]
            for envelope in before_second_reply
            if envelope["data"]["seq"] > reconnect_after
        ]
        with self.client.websocket_connect(
            f"/ws?session_id=session-validator&run_id={run_id}&after={reconnect_after}"
        ) as websocket:
            replayed = [websocket.receive_json() for _ in expected_replay]
            self.assertTrue(all(envelope["type"] == "frame" for envelope in replayed))
            self.assertEqual(
                [envelope["data"]["seq"] for envelope in replayed],
                [frame["seq"] for frame in expected_replay],
            )
            websocket.send_json({"type": "ping"})
            self.assertEqual(websocket.receive_json()["type"], "pong")

        second_reply = self.client.post(
            f"/api/runs/{run_id}/gates/{second_gate['gate_id']}",
            json={"outcome": "approve", "fields": {}},
        )
        self.assertEqual(second_reply.status_code, 202)
        result = registry.wait(run_id, timeout=2)
        self.assertEqual(result["verdict"], "NEEDS_WORK")

        completed = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(completed["status"], "completed")
        self.assertIsNone(completed["pending_gate"])

        page = self.client.get(f"/api/runs/{run_id}/frames?after=0&limit=500").json()
        frames = [envelope["data"] for envelope in page["frames"]]
        self.assertEqual(
            [frame["seq"] for frame in frames],
            list(range(1, len(frames) + 1)),
        )
        self.assertEqual(
            [frame["kind"] for frame in frames].count(FrameKind.GATE_OPEN.value),
            2,
        )
        self.assertEqual(
            [frame["kind"] for frame in frames].count(FrameKind.GATE_CLOSED.value),
            2,
        )

        log_response = self.client.get(f"/api/runs/{run_id}/logs?format=ndjson")
        self.assertEqual(log_response.status_code, 200)
        log_frames = [json.loads(line) for line in log_response.text.splitlines()]
        self.assertEqual(len(log_frames), len(frames))
        self.assertEqual(log_frames[0]["type"], "frame")
        self.assertEqual(
            [entry["data"]["seq"] for entry in log_frames],
            [frame["seq"] for frame in frames],
        )

        duplicate_second = self.client.post(
            f"/api/runs/{run_id}/gates/{second_gate['gate_id']}",
            json={"outcome": "approve", "fields": {}},
        )
        self.assertEqual(duplicate_second.status_code, 409)

    def _start_validator(self) -> str:
        response = self.client.post(
            "/api/sessions/session-validator/runs",
            json={
                "workflow_id": "idea-validator",
                "inputs": {"idea": "A synthetic product for deterministic tests"},
            },
        )
        self.assertEqual(response.status_code, 202)
        return response.json()["run_id"]


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class DurableRecoveryIntegrationTests(unittest.TestCase):
    def test_pending_gate_recovers_and_resumes_in_a_new_app(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        with TemporaryDirectory() as directory:
            path = Path(directory) / "validator-studio.db"
            database_url = f"sqlite+pysqlite:///{path.as_posix()}"

            with TestClient(
                create_app(synthetic=True, database_url=database_url)
            ) as first_client:
                response = first_client.post(
                    "/api/sessions/recovery-session/runs",
                    json={
                        "workflow_id": "idea-validator",
                        "inputs": {"idea": "Recover this synthetic validation"},
                    },
                )
                run_id = response.json()["run_id"]
                first_client.app.state.run_registry.wait(run_id, timeout=2)
                gate_id = first_client.get(f"/api/runs/{run_id}").json()[
                    "pending_gate"
                ]["gate_id"]

            with TestClient(
                create_app(synthetic=True, database_url=database_url)
            ) as recovered_client:
                recovered = recovered_client.get(f"/api/runs/{run_id}")
                self.assertEqual(recovered.status_code, 200)
                self.assertEqual(recovered.json()["status"], "waiting")
                reply = recovered_client.post(
                    f"/api/runs/{run_id}/gates/{gate_id}",
                    json={"outcome": "approve", "fields": {}},
                )
                self.assertEqual(reply.status_code, 202)
                recovered_client.app.state.run_registry.wait(run_id, timeout=2)
                self.assertEqual(
                    recovered_client.get(f"/api/runs/{run_id}").json()["status"],
                    "waiting",
                )

    def test_native_validator_flow_pauses_and_resumes_twice(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        scope, market, sentiment, feasibility, verdict, report = fixtures()
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market),
            sentiment=lambda: FakeRunner(sentiment),
            feasibility=lambda: FakeRunner(feasibility),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
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

        with TemporaryDirectory() as directory:
            output_path = Path(directory) / "validation.md"
            with patch("brief_crew.validator_flow.OUTPUT_PATH", output_path), patch(
                "brief_crew.validator_flow.lookup_branch_cache", return_value=[]
            ):
                with TestClient(create_app(registry=registry)) as client:
                    started = client.post(
                        "/api/sessions/native-session/runs",
                        json={
                            "workflow_id": "idea-validator",
                            "inputs": {"idea": scope.startup_idea},
                        },
                    )
                    run_id = started.json()["run_id"]
                    registry.wait(run_id, timeout=3)

                    first_gate = client.get(f"/api/runs/{run_id}").json()[
                        "pending_gate"
                    ]
                    self.assertEqual(first_gate["node_id"], "confirm_scope")
                    self.assertEqual(
                        client.post(
                            f"/api/runs/{run_id}/gates/{first_gate['gate_id']}",
                            json={"outcome": "approve", "fields": {}},
                        ).status_code,
                        202,
                    )
                    registry.wait(run_id, timeout=3)

                    second_gate = client.get(f"/api/runs/{run_id}").json()[
                        "pending_gate"
                    ]
                    self.assertEqual(second_gate["node_id"], "review_verdict")
                    self.assertEqual(
                        client.post(
                            f"/api/runs/{run_id}/gates/{second_gate['gate_id']}",
                            json={"outcome": "approve", "fields": {}},
                        ).status_code,
                        202,
                    )
                    final_result = registry.wait(run_id, timeout=3)

                    self.assertEqual(final_result, report)
                    self.assertEqual(
                        client.get(f"/api/runs/{run_id}").json()["status"],
                        "completed",
                    )
                    self.assertEqual(
                        output_path.read_text(encoding="utf-8"),
                        report.markdown_body,
                    )


class BoundaryRunner:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self.reached_second_boundary = False

    def __call__(self, execution: RunExecution) -> dict[str, bool]:
        from crewai.flow import Flow, listen, start

        owner = self

        class BoundaryFlow(Flow):
            @start()
            def first(self) -> str:
                owner.entered.set()
                owner.release.wait(timeout=10)
                return "first"

            @listen(first)
            def second(self, _: str) -> dict[str, bool]:
                owner.reached_second_boundary = True
                return {"completed": True}

        return BoundaryFlow().kickoff()


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class CancellationIntegrationTests(unittest.TestCase):
    def test_cancel_stops_at_next_runner_boundary(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        runner = BoundaryRunner()
        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        registry = RunRegistry(
            graph_version=BRIEF_GRAPH.version,
            node_registry=BRIEF_NODE_REGISTRY,
            runner=runner,
            persistence=store,
        )
        self.addCleanup(store.close)
        self.addCleanup(registry.close)

        with TestClient(create_app(registry=registry)) as client:
            response = client.post(
                "/api/sessions/cancel-session/runs",
                json={"workflow_id": "brief-flow", "inputs": {"topic": "test"}},
            )
            run_id = response.json()["run_id"]
            self.assertTrue(runner.entered.wait(timeout=5))

            cancel = client.post(f"/api/runs/{run_id}/cancel")
            self.assertEqual(cancel.status_code, 202)
            self.assertEqual(cancel.json()["status"], "cancelling")
            self.assertEqual(cancel.json()["effect"], "stops at the next step boundary")

            runner.release.set()
            registry.wait(run_id, timeout=2)
            self.assertFalse(runner.reached_second_boundary)
            self.assertEqual(
                client.get(f"/api/runs/{run_id}").json()["status"],
                "cancelled",
            )


if __name__ == "__main__":
    unittest.main()