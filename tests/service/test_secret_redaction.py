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
import pathlib
import re
import unittest
import zipfile
from typing import Any

from brief_crew.config import CREDENTIAL_FIELDS, CREDENTIAL_PUBLIC_FIELDS
from brief_crew.events import FrameKind, FrameLevel, UIEventType
from brief_crew.events.redaction import (
    REDACTED,
    SECRET_KEYS,
    SECRET_KEY_SUFFIXES,
    STRUCTURAL_KEY_NAMES,
    is_secret_key,
    redact_mapping,
)
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
#: The seven key names in this repository's own `.env` (CLAUDE.md: "it holds
#: seven live keys"), none of which the exact-match list caught, plus the two
#: session-library spellings the round-1 critic named. Matched on suffix now.
ENV_KEY_NAMES = (
    "OPENROUTER_API_KEY",
    "FIRECRAWL_API_KEY",
    "PINECONE_API_KEY",
    "COHERE_API_KEY",
    "RENDER_API_KEY",
    "GITHUB_TOKEN",
    "OPENROUTER_MANAGEMENT_KEY",
)
SUFFIX_FIXTURES: dict[str, Any] = {
    **{name: f"LEAK-ENV-{index}" for index, name in enumerate(ENV_KEY_NAMES)},
    "auth_token": "LEAK-S1",
    "session_token": "LEAK-S2",
    "credentials_master_key": "LEAK-S3",
    "db_password": "LEAK-S4",
    "webhook.secret": "LEAK-S5",
    "SQL_DSN": "LEAK-S6",
}
#: The vault's `http_header` / `mcp_header` pair used to be `("name", "value")`
#: and this file carried its own `HEADER_PAIR = {"name", "value"}` pinning BOTH
#: halves as not-secret - a test asserting the opposite of the criterion it
#: belongs to, for the field that actually holds the header secret (D-01-6,
#: D-01-10). The secret half is `header_value` now, which the list covers by
#: name, and the one genuinely public field is declared by the PRODUCT in
#: `config.CREDENTIAL_PUBLIC_FIELDS` rather than by a constant in here.
LEAKS = (
    "LEAK-A", "LEAK-B", "LEAK-C", "LEAK-D", "LEAK-E", "LEAK-F", "LEAK-G", "LEAK-H", "LEAK-N",
    *SUFFIX_FIXTURES.values(),
)


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

    def test_the_plan_records_the_fields_exclusion_beside_the_pin(self) -> None:
        """D-01-3: the deviation above is written INTO criterion 6, dated, naming this pin.

        Round 1 found criterion 6 ticked `done` while its text - "every D6 key
        name" - was contradicted by the test above, with the reason living only
        in a Status row. A deviation the plan does not carry is a tick that a
        one-line probe breaks. This test holds the criterion's own text to the
        exclusion, so the note and the pin cannot part company silently: delete
        either and the other fails.
        """

        plan = pathlib.Path(__file__).resolve().parents[2] / ".agent" / "plans" / "01-auth-and-workspaces.md"
        self.assertTrue(plan.is_file(), plan)
        text = plan.read_text(encoding="utf-8")
        # Criterion 6 is the numbered item that names this file; the note is
        # the indented paragraph under it, before item 7.
        match = re.search(
            r"^6\. `tests/service/test_secret_redaction\.py`:(?P<body>.*?)(?=^7\. )",
            text,
            re.M | re.S,
        )
        self.assertIsNotNone(match, "criterion 6 not found in the plan")
        body = match.group("body")
        self.assertIn("Amended 2026-09-03", body)
        self.assertIn("`fields`", body)
        self.assertIn("test_fields_is_deliberately_not_on_the_list", body)
        self.assertIn(self.test_the_plan_records_the_fields_exclusion_beside_the_pin.__name__, body)

    def test_ordinary_keys_are_left_alone(self) -> None:
        for key in (
            "total_tokens", "prompt_tokens", "completion_tokens", "tokens", "status", "result",
            "inputs", "idea", "node_id", "graph_version", "reserved_input_keys", "keys",
        ):
            with self.subTest(key=key):
                self.assertFalse(is_secret_key(key))

    def test_the_seven_env_key_names_are_secret(self) -> None:
        """Every name `.env` actually uses, none of which exact matching caught."""

        for name in ENV_KEY_NAMES:
            with self.subTest(name=name):
                self.assertTrue(is_secret_key(name))

    def test_names_are_matched_on_a_normalised_suffix(self) -> None:
        self.assertEqual(SECRET_KEY_SUFFIXES, ("key", "token", "secret", "password", "dsn"))
        for name in ("auth_token", "session_token", "authToken", "MasterKey", "db-password", "SQL_DSN", "webhook.secret", "CREDENTIALS_MASTER_KEY"):
            with self.subTest(name=name):
                self.assertTrue(is_secret_key(name))

    def test_every_vault_field_name_is_pinned(self) -> None:
        """Derived from `config.CREDENTIAL_FIELDS`, so a new kind's field is pinned the day it exists.

        A field that is neither on the redaction list nor declared public in
        `config.CREDENTIAL_PUBLIC_FIELDS` fails here, which is the decision it
        deserves: is its value a secret or a name? Both halves of the answer
        now live in the product - the list and the public set - so this test
        checks them against each other instead of asserting a third opinion.
        """

        for kind, fields in CREDENTIAL_FIELDS.items():
            for field in fields:
                with self.subTest(kind=kind, field=field):
                    self.assertEqual(
                        is_secret_key(field),
                        field not in CREDENTIAL_PUBLIC_FIELDS,
                    )

    def test_the_header_pair_secret_half_is_covered_and_the_name_half_is_not(self) -> None:
        """D-01-6: the field holding an `Authorization` header value is secret.

        The alternative the row proposed - putting the bare word `value` on
        the list - was tried and measured: six tests red across four modules,
        three of them the gate surface, because a gate `derived` entry is
        `{"key": name, "value": display, "kind": kind}` and its read-only
        panel went to `***`. `value` is also a router branch's compare
        operand, a transform's `args.value` and an output node's body slot, so
        the entry would have redacted a compiled graph's own logic in the
        persisted state. The FIELD moved instead.
        """

        self.assertEqual(CREDENTIAL_FIELDS["http_header"], ("name", "header_value"))
        self.assertEqual(CREDENTIAL_FIELDS["mcp_header"], ("name", "header_value"))
        self.assertTrue(is_secret_key("header_value"))
        self.assertTrue(is_secret_key("headerValue"))
        self.assertTrue(is_secret_key("Header-Value"))
        self.assertFalse(is_secret_key("name"))
        self.assertEqual(
            redact_mapping({"name": "Authorization", "header_value": "Bearer LEAK-P"}),
            {"name": "Authorization", "header_value": REDACTED},
        )

    def test_no_vault_field_is_excluded_by_a_constant_in_this_file(self) -> None:
        """D-01-10: the only exclusion left is the product's own, and it is one word.

        Criterion 6's `fields` exclusion is a dated amendment in the plan.
        Its second exclusion was neither: it lived here, in a test constant,
        and covered the header secret. There is no such constant now, and the
        set that replaces it is small enough to assert whole.
        """

        self.assertEqual(CREDENTIAL_PUBLIC_FIELDS, frozenset({"name"}))
        secret_fields = {
            field
            for fields in CREDENTIAL_FIELDS.values()
            for field in fields
            if field not in CREDENTIAL_PUBLIC_FIELDS
        }
        self.assertEqual(
            secret_fields,
            {"api_key", "token", "dsn", "header_value"},
        )
        for field in secret_fields:
            with self.subTest(field=field):
                self.assertTrue(is_secret_key(field))

    def test_the_bare_word_key_names_a_field_and_is_not_redacted(self) -> None:
        """`{"key": name, "value": ..., "kind": ...}` is every gate `derived` entry."""

        self.assertFalse(is_secret_key("key"))
        self.assertEqual(
            redact_mapping({"key": "score", "value": "7.2", "kind": "number"}),
            {"key": "score", "value": "7.2", "kind": "number"},
        )
        # The other four bare words are exact entries and stay redacted.
        for word in ("token", "secret", "password", "dsn"):
            self.assertTrue(is_secret_key(word), word)

    def test_a_name_that_names_a_key_is_not_one(self) -> None:
        """`body_key` is an output node's config field: the NAME of a slot, never a credential.

        Builder document rows go through the persistence walk, so redacting
        it turned every stored document with an output node into one the
        service "no longer parses" - 107 assertions in eleven modules, found
        by the full suite and not by this file. The store round trip below is
        the pin this file lacked.
        """

        self.assertEqual(STRUCTURAL_KEY_NAMES, frozenset({"bodykey"}))
        for spelling in ("body_key", "bodyKey", "BODY_KEY"):
            with self.subTest(spelling=spelling):
                self.assertFalse(is_secret_key(spelling))
        # The list is exact-match on the normalised name: a real key that
        # merely contains the word is still a key.
        self.assertTrue(is_secret_key("body_api_key"))

    def test_a_builder_state_slot_is_never_redacted_for_its_node_id(self) -> None:
        """`out__<node>` carries a node's output; the node id is the author's word."""

        for slot in ("out__token", "out__api_key", "out__password", "out__secret", "out__dsn"):
            with self.subTest(slot=slot):
                self.assertFalse(is_secret_key(slot))
        # The exemption is on the raw prefix, not on anything that merely
        # contains it.
        self.assertTrue(is_secret_key("timeout__token"))

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

    def test_env_key_names_round_trip_as_the_marker_at_any_depth(self) -> None:
        clipped = FieldBoundedSerializer().clip(
            {**SUFFIX_FIXTURES, "nested": {"deeper": SUFFIX_FIXTURES}, "out__token": "kept"}
        )
        for key in SUFFIX_FIXTURES:
            self.assertEqual(clipped[key], REDACTED, key)
            self.assertEqual(clipped["nested"]["deeper"][key], REDACTED, key)
        self.assertEqual(clipped["out__token"], "kept")
        assert_nothing_leaked(self, json.dumps(clipped))


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

    def test_a_builder_document_with_an_output_node_survives_the_store(self) -> None:
        """The round trip the suffix rule broke: `body_key` in, `body_key` out."""

        from brief_crew.builder.store import BuilderDocumentStore
        from tests.builder.test_compiler import straight_line

        store = BuilderDocumentStore(self.store)
        document = straight_line()
        self.assertTrue(
            any(getattr(node.config, "body_key", None) for node in document.nodes),
            "the fixture graph carries no output node; the test would prove nothing",
        )
        created = store.create(document, user_id="user_redaction")
        loaded = store.load(created.id, user_id="user_redaction")
        body_keys = sorted(
            node.config.body_key for node in loaded.document.nodes if hasattr(node.config, "body_key")
        )
        self.assertTrue(body_keys)
        self.assertNotIn(REDACTED, body_keys)
        self.assertEqual(
            body_keys,
            sorted(node.config.body_key for node in document.nodes if hasattr(node.config, "body_key")),
        )

    def test_a_state_carrying_env_key_names_is_stored_redacted_and_a_slot_is_not(self) -> None:
        """The row walk asks the same predicate as the ring walk, suffixes included."""

        self.store.save_state(
            "flow-env", "method", {"id": "flow-env", **SUFFIX_FIXTURES, "out__token": "kept"}
        )
        loaded = self.store.load_state("flow-env")
        for key in SUFFIX_FIXTURES:
            self.assertEqual(loaded[key], REDACTED, key)
        self.assertEqual(loaded["out__token"], "kept")
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
            details={
                **D6_FIXTURES,
                **SUFFIX_FIXTURES,
                "nested": {"headers": {"Authorization": "Bearer LEAK-C"}},
            },
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
