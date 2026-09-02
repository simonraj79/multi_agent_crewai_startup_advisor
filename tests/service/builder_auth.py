"""Two signed-in authors and one stranger, for every builder route test.

Plan 15's routes are all about who may see what, so their tests share one
shape: an app with authentication ON, two identities the token stub knows
(`ADA` and `GRACE` from `test_auth_endpoints`), and an anonymous caller. The
token stub is that module's `AuthEnabledCase` - `verify_token` patched rather
than real signatures minted, because the cryptography is proved against genuine
Ed25519 tokens in `test_auth_jwt.py` and repeating it here would test PyJWT a
third time and the authorisation logic once.

A helper module rather than a base class copied into five files, for the reason
`builder_registration.py` gives: the copy is how two halves drift.
"""

from __future__ import annotations

import json
from typing import Any

from brief_crew.builder.document import BuilderDocument
from tests.builder.test_compiler import straight_line
from tests.service.test_auth_endpoints import ADA, GRACE, AuthEnabledCase

ADA_TOKEN = "ada-token"
GRACE_TOKEN = "grace-token"

__all__ = [
    "ADA",
    "ADA_TOKEN",
    "GRACE",
    "GRACE_TOKEN",
    "BuilderAuthCase",
    "document_payload",
]


def document_payload(document: BuilderDocument | None = None, **overrides: Any) -> dict[str, Any]:
    """A document as the canvas sends it: wire spelling, id and version included.

    The server overwrites `id` and `version` on every ingress, so leaving them
    in is harmless and is what a real client does.
    """

    payload = (document or straight_line()).model_dump(mode="json", by_alias=True)
    payload.update(overrides)
    return json.loads(json.dumps(payload))


class BuilderAuthCase(AuthEnabledCase):
    """`AuthEnabledCase` plus the four calls every builder-route test makes."""

    def create_as(self, token: str | None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.client.post(
            "/api/builder/workflows",
            json={"document": payload or document_payload()},
            headers=self.auth(token) if token else {},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def get_as(self, token: str | None, document_id: str, **params: Any) -> Any:
        return self.client.get(
            f"/api/builder/workflows/{document_id}",
            params=params or None,
            headers=self.auth(token) if token else {},
        )

    def list_ids_as(self, token: str | None) -> list[str]:
        response = self.client.get(
            "/api/builder/workflows", headers=self.auth(token) if token else {}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return [row["id"] for row in response.json()]

    def save_as(
        self,
        token: str | None,
        document_id: str,
        payload: dict[str, Any],
        *,
        expected_version: int,
    ) -> Any:
        return self.client.put(
            f"/api/builder/workflows/{document_id}",
            json={"document": payload, "expected_version": expected_version},
            headers=self.auth(token) if token else {},
        )

    def export_as(self, token: str | None, document_id: str, **params: Any) -> Any:
        return self.client.get(
            f"/api/builder/workflows/{document_id}/export",
            params=params or None,
            headers=self.auth(token) if token else {},
        )

    def import_as(self, token: str | None, envelope: dict[str, Any]) -> Any:
        return self.client.post(
            "/api/builder/workflows/import",
            json=envelope,
            headers=self.auth(token) if token else {},
        )

    def store(self) -> Any:
        """The document store over the app's own persistence, for seeding."""

        from brief_crew.builder.store import BuilderDocumentStore

        return BuilderDocumentStore(self.app.state.run_registry.persistence)
