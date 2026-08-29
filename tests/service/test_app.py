from __future__ import annotations

import importlib.util
import io
import json
import unittest
from unittest.mock import patch
import zipfile


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None


class FastAPIDependencyTests(unittest.TestCase):
    @unittest.skipIf(FASTAPI_AVAILABLE, "FastAPI is installed")
    def test_factory_reports_missing_service_extra(self) -> None:
        from brief_crew.service.app import ServiceDependencyError, create_app

        with self.assertRaisesRegex(ServiceDependencyError, "service extra"):
            create_app(synthetic=True)


@unittest.skipUnless(
    FASTAPI_AVAILABLE,
    "FastAPI is not installed; install the existing project service extra",
)
class FastAPIContractTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.client = TestClient(create_app(synthetic=True))

    def tearDown(self) -> None:
        self.client.close()

    def test_graph_run_status_and_frames_contract(self) -> None:
        graph_response = self.client.get("/api/workflows/brief-flow/graph")
        self.assertEqual(graph_response.status_code, 200)
        self.assertTrue(graph_response.headers["etag"])

        create_response = self.client.post(
            "/api/sessions/session-a/runs",
            json={"workflow_id": "brief-flow", "inputs": {"topic": "test"}},
        )
        self.assertEqual(create_response.status_code, 202)
        run_id = create_response.json()["run_id"]
        self.client.app.state.run_registry.wait(run_id, timeout=2)

        status_response = self.client.get(f"/api/runs/{run_id}")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["status"], "completed")

        frames_response = self.client.get(
            f"/api/runs/{run_id}/frames", params={"after": 0, "limit": 500}
        )
        self.assertEqual(frames_response.status_code, 200)
        self.assertGreater(frames_response.json()["count"], 0)

        frame_count = frames_response.json()["count"]
        with self.client.websocket_connect(
            f"/ws?session_id=session-a&run_id={run_id}&after=0"
        ) as websocket:
            for _ in range(frame_count):
                self.assertEqual(websocket.receive_json()["type"], "frame")
            websocket.send_json({"type": "ping"})
            self.assertEqual(websocket.receive_json()["type"], "pong")

    def test_health_readiness_and_log_exports(self) -> None:
        for path in ("/healthz", "/readyz"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["dependencies"]["storage"]["status"], "ok")
            self.assertNotIn("DATABASE_URL", response.text)
            self.assertNotIn("sqlite+pysqlite", response.text)

        create_response = self.client.post(
            "/api/sessions/session-logs/runs",
            json={"workflow_id": "brief-flow", "inputs": {"topic": "logs"}},
        )
        run_id = create_response.json()["run_id"]
        self.client.app.state.run_registry.wait(run_id, timeout=2)

        ndjson_response = self.client.get(f"/api/runs/{run_id}/logs?format=ndjson")
        self.assertEqual(ndjson_response.status_code, 200)
        self.assertTrue(ndjson_response.content.endswith(b"\n"))

        zip_response = self.client.get(f"/api/runs/{run_id}/logs?format=zip")
        self.assertEqual(zip_response.status_code, 200)
        self.assertEqual(zip_response.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(zip_response.content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"frames.ndjson", "run.json", "node-metrics.json"},
            )
            run = json.loads(archive.read("run.json"))
            node_metrics = json.loads(archive.read("node-metrics.json"))
            self.assertEqual(run["run_id"], run_id)
            self.assertEqual(node_metrics, run["node_usage"])

    def test_startup_rejects_non_openrouter_model_constants(self) -> None:
        from brief_crew.service.app import _assert_openrouter_startup_safety

        with patch("brief_crew.config.CHEAP_MODEL", "openai/gpt-4o"):
            with self.assertRaisesRegex(RuntimeError, "CHEAP_MODEL"):
                _assert_openrouter_startup_safety()


if __name__ == "__main__":
    unittest.main()