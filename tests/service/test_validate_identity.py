"""Plan 01 D10: `validate` with an identity checks the vault; without one, says so.

`POST /api/builder/validate` was anonymous by design while validation touched
no per-user state. A `credential_id` is per-user state: whether it names a
row, and whose, are questions only an identity can answer. So the endpoint
takes one when offered, emits `credential-missing` (C8) for a reference the
caller's vault does not hold - absent and foreign are ONE code, because a
canvas that could tell them apart would be an oracle for other people's ids -
and reports `identity_checked: false` when it had nobody to ask for, so the
client can say why a problem may still appear at publish.

Publish re-validates with the publisher's identity, which is where a document
naming somebody else's credential is refused with the same code and a 422.
The published definition is then checked for the id and against the secret,
because the whole point of the id is that it is all the definition carries.

Free throughout: the app is synthetic, identities are D8 headers, and nothing
is launched.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import patch

from brief_crew import config
from brief_crew.service.graph import BUILDER_WORKFLOWS
from tests.builder.test_compiler import straight_line
from tests.service.builder_registration import BuilderRegistrationCleanup
from tests.service.identities import CREDENTIALS, SECRET, SYNTHETIC_USER_HEADER, wire

try:  # pragma: no cover
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

VALIDATE = "/api/builder/validate"


def as_user(user_id: str) -> dict[str, str]:
    return {SYNTHETIC_USER_HEADER: user_id}


def referencing(credential_id: str | None) -> dict[str, Any]:
    """`straight_line()` on the wire, with its one agent naming `credential_id`."""

    document = wire(straight_line())
    if credential_id is not None:
        document["nodes"][1]["config"]["credential_id"] = credential_id
    return document


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class ValidateIdentityTests(BuilderRegistrationCleanup):
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
        self.client = TestClient(create_app(synthetic=True))
        self.addCleanup(self.client.close)
        created = self.client.post(
            CREDENTIALS,
            json={"kind": "openrouter", "label": "alice's key", "fields": {"api_key": SECRET}},
            headers=as_user("alice"),
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.credential_id = created.json()["id"]

    def validate(self, document: dict[str, Any], headers: dict[str, str] | None) -> dict[str, Any]:
        response = self.client.post(VALIDATE, json={"document": document}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    @staticmethod
    def codes(body: dict[str, Any]) -> list[str]:
        return [problem["code"] for problem in body["problems"]]

    def test_the_owner_validates_clean_and_the_check_is_reported(self) -> None:
        body = self.validate(referencing(self.credential_id), as_user("alice"))
        self.assertTrue(body["valid"])
        self.assertEqual(self.codes(body), [])
        self.assertTrue(body["identity_checked"])

    def test_a_foreign_id_is_credential_missing_anchored_to_the_node(self) -> None:
        body = self.validate(referencing(self.credential_id), as_user("bob"))
        self.assertFalse(body["valid"])
        self.assertTrue(body["identity_checked"])
        self.assertEqual(self.codes(body), ["credential-missing"])
        problem = body["problems"][0]
        self.assertEqual(problem["severity"], "error")
        self.assertEqual(problem["node_id"], "scoper")
        self.assertIn(self.credential_id, problem["message"])
        self.assertIn("vault", problem["message"])

    def test_an_absent_id_is_the_same_code_for_the_owner(self) -> None:
        body = self.validate(referencing("cr_deadbeef"), as_user("alice"))
        self.assertEqual(self.codes(body), ["credential-missing"])

    def test_without_an_identity_nothing_is_emitted_and_the_response_says_why(self) -> None:
        body = self.validate(referencing(self.credential_id), None)
        self.assertTrue(body["valid"])
        self.assertEqual(self.codes(body), [])
        self.assertFalse(body["identity_checked"])

    def test_a_document_naming_no_credential_is_still_checked_and_clean(self) -> None:
        body = self.validate(referencing(None), as_user("bob"))
        self.assertTrue(body["valid"])
        self.assertTrue(body["identity_checked"])

    def test_a_malformed_id_is_the_schemas_422_not_a_problem_code(self) -> None:
        response = self.client.post(
            VALIDATE, json={"document": referencing("cr_XYZ")}, headers=as_user("alice")
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertNotIn(SECRET, response.text)

    def test_a_deleted_credential_turns_its_references_missing(self) -> None:
        deleted = self.client.delete(f"{CREDENTIALS}/{self.credential_id}", headers=as_user("alice"))
        self.assertEqual(deleted.status_code, 204)
        body = self.validate(referencing(self.credential_id), as_user("alice"))
        self.assertEqual(self.codes(body), ["credential-missing"])

    def test_the_response_never_carries_a_field_value(self) -> None:
        for headers in (as_user("alice"), as_user("bob"), None):
            response = self.client.post(
                VALIDATE, json={"document": referencing(self.credential_id)}, headers=headers
            )
            self.assertNotIn(SECRET, response.text)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class PublishIdentityTests(ValidateIdentityTests):
    """Publish is the last door, and it re-validates with the publisher's vault."""

    def _create(self, document: dict[str, Any], headers: dict[str, str]) -> str:
        created = self.client.post("/api/builder/workflows", json={"document": document}, headers=headers)
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()["document"]["id"]

    def test_bob_cannot_publish_a_graph_naming_alices_credential(self) -> None:
        document_id = self._create(referencing(self.credential_id), as_user("bob"))
        published = self.client.post(f"/api/builder/workflows/{document_id}/publish", headers=as_user("bob"))
        self.assertEqual(published.status_code, 422, published.text)
        detail = published.json()["detail"]
        self.assertEqual([problem["code"] for problem in detail["problems"]], ["credential-missing"])
        self.assertNotIn(SECRET, published.text)
        self.assertFalse(any(key.startswith("ug_") for key in BUILDER_WORKFLOWS))

    def test_alice_publishes_and_the_definition_carries_the_id_only(self) -> None:
        document_id = self._create(referencing(self.credential_id), as_user("alice"))
        published = self.client.post(f"/api/builder/workflows/{document_id}/publish", headers=as_user("alice"))
        self.assertEqual(published.status_code, 200, published.text)
        workflow_id = published.json()["workflow_id"]
        self.track(workflow_id)
        rendered = json.dumps(BUILDER_WORKFLOWS[workflow_id].compiled.definition)
        self.assertIn(self.credential_id, rendered)
        self.assertNotIn(SECRET, rendered)
        self.assertEqual(BUILDER_WORKFLOWS[workflow_id].user_id, "alice")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
