"""Plan 01 D6: nothing secret reaches a frame, a row, a log or an export.

Two walks apply one list. `service/persistence.py` redacted on the way to a
row for a long time, so the database was clean - and `events/serializer.py`
bounded every frame and redacted nothing, so the live stream, `/frames` and
the NDJSON export, all served from the in-memory ring, carried whatever a tool
or an agent had put under `api_key`. `events/redaction.py` is the one list
both walks now import, and this file holds each walk to it separately and
then the whole service end to end.

**`fields` is deliberately NOT on the list, and a test says so.** Plan 01 D6
asks for it; `pending_gate.fields` is the editable half of every gate payload,
and redacting it by name turned every gate form into the string `***` on the
first synthetic run. The vault's own plaintext object is called `fields` too,
but it never reaches a frame - it lives in `ResolvedCredential`, whose `repr`
hides it, and is handed to one constructor. The per-field names below are
what carry the plan's intent, and the deviation is pinned here so the next
reader of D6 finds the reason beside the test rather than re-adding the key.

The end-to-end half runs a runner that LEAKS on purpose through the real
`create_app`, then reads every surface a secret could reach.
"""

from __future__ import annotations

import io
import json
import unittest
import zipfile
from typing import Any

from brief_crew.events import FrameKind, FrameLevel, UIEventType
from brief_crew.events.redaction import REDACTED, SECRET_KEYS, is_secret_key, redact_mapping
from brief_crew.events.serializer import FieldBoundedSerializer
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.runner import RunExecution

try:  # pragma: no cover
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

#: Every key name plan 01 D6 lists, each with a value nothing else in a frame
#: could contain, so a search for the VALUE is a search for a leak.
D6_FIXTURES: dict[str, Any] = {
    "api_key": "sk-live-LEAK-A",
    "token": "ghp_LEAK-B",
    "authorization": "Bearer LEAK-C",
    "headers": {"X-Api-Key": "LEAK-D", "Accept": "application/json"},
    "dsn": "postgresql://user:LEAK-E@db.internal/app",
    "secret": "LEAK-F",
    "password": "LEAK-G",
    "ciphertext": "LEAK-H",
}
#: The four this repository redacted before D6, and the spellings that must
#: normalise onto the list.
SPELLINGS = ("apiKey", "API-Key", "x-api-key", "Authorization", "accessToken", "refresh_token", "clientSecret", "Set-Cookie", "privateKey", "nonce")
LEAKS = ("LEAK-A", "LEAK-B", "LEAK-C", "LEAK-D", "LEAK-E", "LEAK-F", "LEAK-G", "LEAK-H", "LEAK-N")


def assert_nothing_leaked(test: unittest.TestCase, rendered: str) -> None:
    for leak in LEAKS:
        test.assertNotIn(leak, rendered)


class ListTests(unittest.TestCase):
    def test_every_d6_key_is_on_the_list(self) -> None:
        for key in D6_FIXTURES:
            with self.subTest(key=key):
                self.assertTrue(is_secret_key(key))

    def test_matching_is_on_the_normalised_spelling(self) -> None:
        for spelling in SPELLINGS:
            with self.subTest(spelling=spelling):
                self.assertTrue(is_secret_key(spelling))

    def test_fields_is_deliberately_not_on_the_list(self) -> None:
        """See the module docstring. A gate form is a mapping called `fields`."""

        self.assertFalse(is_secret_key("fields"))
        self.assertNotIn("fields", SECRET_KEYS)

    def test_ordinary_keys_are_left_alone(self) -> None:
        for key in ("total_tokens", "tokens", "status", "result", "inputs", "idea", "node_id"):
            with self.subTest(key=key):
                self.assertFalse(is_secret_key(key))

    def test_redact_mapping_is_the_same_rule_shallowly(self) -> None:
        redacted = redact_mapping({"api_key": "x", "idea": "kept"})
        self.assertEqual(redacted, {"api_key": REDACTED, "idea": "kept"})


class SerializerWalkTests(unittest.TestCase):
    """The ring: `adapter.emit` and every event draft go through `clip`."""

    def test_every_d6_key_round_trips_as_the_marker_at_any_depth(self) -> None:
        clipped = FieldBoundedSerializer().clip(
            {
                **D6_FIXTURES,
                "nested": {"deeper": {**D6_FIXTURES, "nonce": "LEAK-N"}},
                "list": [{"token": "ghp_LEAK-B"}],
                "kept": "visible",
            }
        )
        for key in D6_FIXTURES:
            self.assertEqual(clipped[key], REDACTED, key)
            self.assertEqual(clipped["nested"]["deeper"][key], REDACTED, key)
        self.assertEqual(clipped["nested"]["deeper"]["nonce"], REDACTED)
        self.assertEqual(clipped["list"][0]["token"], REDACTED)
        self.assertEqual(clipped["kept"], "visible")
        assert_nothing_leaked(self, json.dumps(clipped))

    def test_a_gate_forms_fields_survive_the_walk(self) -> None:
        clipped = FieldBoundedSerializer().clip({"fields": {"segment": "clinics", "notes": ""}})
        self.assertEqual(clipped["fields"], {"segment": "clinics", "notes": ""})


class PersistenceWalkTests(unittest.TestCase):
    """The row: `_sanitize_json` on states and on frames."""

    def setUp(self) -> None:
        self.store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.store.close)

    def test_a_flow_state_carrying_every_d6_key_is_stored_redacted(self) -> None:
        self.store.save_state("flow-secrets", "method", {"id": "flow-secrets", **D6_FIXTURES, "kept": 1})
        loaded = self.store.load_state("flow-secrets")
        for key in D6_FIXTURES:
            self.assertEqual(loaded[key], REDACTED, key)
        self.assertEqual(loaded["kept"], 1)
        assert_nothing_leaked(self, json.dumps(loaded))

    def test_a_frame_row_carrying_every_d6_key_is_stored_redacted(self) -> None:
        # Frames hang off a run row; `append_frames` refuses an orphan.
        self.store.create_run(
            session_id="s", workflow_id="brief-flow", graph_version="v", run_id="run-secrets"
        )
        frame = {
            "run_id": "run-secrets",
            "seq": 1,
            "v": 1,
            "ts": "2026-09-03T00:00:00+00:00",
            "kind": "node_state",
            "event_type": "NODE_START",
            "level": "INFO",
            "node_id": "scoper",
            "message": "scoper started",
            "details": {**D6_FIXTURES, "kept": "visible"},
            "duration_ms": None,
        }
        self.store.append_frames("run-secrets", [frame])
        rows = self.store.replay_frames("run-secrets")
        self.assertEqual(len(rows), 1)
        for key in D6_FIXTURES:
            self.assertEqual(rows[0]["details"][key], REDACTED, key)
        self.assertEqual(rows[0]["details"]["kept"], "visible")
        assert_nothing_leaked(self, json.dumps(rows))


class LeakingRunner:
    """A `brief-flow` runner that puts every D6 key into its frames on purpose."""

    def __call__(self, execution: RunExecution) -> dict[str, Any]:
        execution.capture.emit(
            kind=FrameKind.RUN_STATE,
            event_type=UIEventType.WORKFLOW_START,
            node_id="workflow",
            message="Leaky run started",
            details={"status": "running", "inputs": {"topic": "logs", **D6_FIXTURES}},
        )
        execution.capture.emit(
            kind=FrameKind.NODE_STATE,
            event_type=UIEventType.NODE_START,
            node_id="retrieve_cached",
            message="retrieve_cached started",
            details={**D6_FIXTURES, "nested": {"headers": {"Authorization": "Bearer LEAK-C"}}},
        )
        execution.capture.emit(
            kind=FrameKind.NODE_STATE,
            event_type=UIEventType.NODE_END,
            node_id="retrieve_cached",
            message="retrieve_cached failed",
            details={"stage": "error", "error": "provider said no", "nonce": "LEAK-N"},
            level=FrameLevel.ERROR,
        )
        result = {"synthetic": True, "topic": "logs"}
        execution.capture.emit(
            kind=FrameKind.RUN_STATE,
            event_type=UIEventType.WORKFLOW_END,
            node_id="workflow",
            message="Leaky run completed",
            details={"status": "completed", "result": result},
        )
        return result


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class EndToEndTests(unittest.TestCase):
    """Every surface a frame reaches, read after a run that leaked into all of them."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.client = TestClient(
            create_app(runner=LeakingRunner(), database_url="sqlite+pysqlite:///:memory:")
        )
        self.addCleanup(self.client.close)
        created = self.client.post(
            "/api/sessions/session-leaks/runs",
            json={"workflow_id": "brief-flow", "inputs": {"topic": "logs"}},
        )
        self.assertEqual(created.status_code, 202, created.text)
        self.run_id = created.json()["run_id"]
        self.registry = self.client.app.state.run_registry
        self.registry.wait(self.run_id, timeout=10)

    def test_the_ndjson_export_contains_none_of_the_fixtures(self) -> None:
        response = self.client.get(f"/api/runs/{self.run_id}/logs?format=ndjson")
        self.assertEqual(response.status_code, 200)
        body = response.text
        assert_nothing_leaked(self, body)
        self.assertIn(REDACTED, body)
        # And the frames are all there - a redaction that dropped frames would
        # pass the search above for the wrong reason.
        self.assertEqual(body.count('"type":"frame"'), 4)

    def test_the_zip_export_contains_none_of_the_fixtures(self) -> None:
        response = self.client.get(f"/api/runs/{self.run_id}/logs?format=zip")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for name in archive.namelist():
                with self.subTest(member=name):
                    assert_nothing_leaked(self, archive.read(name).decode("utf-8"))

    def test_the_frames_endpoint_and_the_status_contain_none_of_the_fixtures(self) -> None:
        frames = self.client.get(f"/api/runs/{self.run_id}/frames?after=0&limit=50")
        self.assertEqual(frames.status_code, 200)
        assert_nothing_leaked(self, frames.text)
        status = self.client.get(f"/api/runs/{self.run_id}")
        self.assertEqual(status.status_code, 200)
        assert_nothing_leaked(self, status.text)

    def test_the_rows_behind_them_are_clean_too(self) -> None:
        rows = self.registry.persistence.replay_frames(self.run_id)
        self.assertEqual(len(rows), 4)
        assert_nothing_leaked(self, json.dumps(rows))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
