"""Two people who cost nothing, for every isolation test in this package.

Plan 01's rubric 14 - one person's rows are invisible to another - is
exercised in Python two ways, and this module carries both so the test files
that need a second user do not each grow a copy of the setup:

* `AuthenticatedTwoUserCase` - `AUTH_BASE_URL` set, authentication REQUIRED,
  and `verify_token` patched to a two-entry table. The same boundary
  `tests/service/test_auth_endpoints.py` chose, for the same reason: the
  cryptography is proved against real Ed25519 signatures in
  `test_auth_jwt.py`, so repeating it here would test PyJWT twice and the
  authorisation logic once. What these tests are for is what the endpoints do
  with the answer.
* `SYNTHETIC_USER_HEADER` - plan 01 D8's header, for the cases that put the
  free path itself under test (`test_synthetic_identity.py`) or want two users
  on an app with no auth server at all.

The vault's master key is the placeholder `tests/__init__.py` exports, so
`create_app` under `AUTH_BASE_URL` passes its boot check. A test about the
UNCONFIGURED vault patches `config.CREDENTIALS_MASTER_KEY` to "" itself, the
way the key-absent tool tests clear their environment.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from brief_crew import config
from brief_crew.service.auth import AuthenticatedUser, AuthError
from tests.service.builder_registration import BuilderRegistrationCleanup

ALICE = AuthenticatedUser(id="user_alice", email="alice@example.test", name="Alice")
BOB = AuthenticatedUser(id="user_bob", email="bob@example.test", name="Bob")
ALICE_TOKEN = "alice-token"
BOB_TOKEN = "bob-token"

#: Plan 01 D8. Restated here rather than imported from `service/app.py` so a
#: rename there fails these tests instead of silently following.
SYNTHETIC_USER_HEADER = "X-Synthetic-User"

CREDENTIALS = "/api/builder/credentials"
#: An obviously fake key with an obviously greppable tail. Every assertion
#: that "no field ever leaves the vault" searches response bodies for this.
SECRET = "sk-or-v1-0123456789abcdef-NEVER-ON-THE-WIRE"


def wire(document: Any) -> dict[str, Any]:
    """A `BuilderDocument` as the browser posts it - `schema`, not `document_schema`."""

    return json.loads(document.model_dump_json())


class AuthenticatedTwoUserCase(BuilderRegistrationCleanup):
    """A synthetic app with authentication on and two people who can sign in."""

    def app_kwargs(self) -> dict[str, Any]:
        """What `create_app` is called with. Override for a limiter or a registry."""

        return {"synthetic": True}

    def setUp(self) -> None:
        super().setUp()
        tokens = {ALICE_TOKEN: ALICE, BOB_TOKEN: BOB}

        def fake_verify(token: str, **_: object) -> AuthenticatedUser:
            try:
                return tokens[token]
            except KeyError as exc:
                raise AuthError("token is not valid") from exc

        for item in (
            patch.object(config, "AUTH_BASE_URL", "https://auth.example.test"),
            patch.object(config, "VALIDATOR_REQUIRE_AUTH", True),
            patch("brief_crew.service.app.verify_token", fake_verify),
        ):
            item.start()
            self.addCleanup(item.stop)

        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.app = create_app(**self.app_kwargs())
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    @staticmethod
    def auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def as_alice(self) -> dict[str, str]:
        return self.auth(ALICE_TOKEN)

    def as_bob(self) -> dict[str, str]:
        return self.auth(BOB_TOKEN)

    def create_credential(
        self,
        headers: dict[str, str],
        *,
        kind: str = "openrouter",
        label: str = "My OpenRouter key",
        fields: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = self.client.post(
            CREDENTIALS,
            json={"kind": kind, "label": label, "fields": fields or {"api_key": SECRET}},
            headers=headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def publish(self, document: Any, headers: dict[str, str] | None) -> tuple[str, str]:
        """Create and publish `document` as `headers`, tracked for cleanup.

        Returns `(document_id, workflow_id)`. `headers=None` is an anonymous
        author, which only works on an app with authentication off.
        """

        created = self.client.post(
            "/api/builder/workflows", json={"document": wire(document)}, headers=headers
        )
        self.assertEqual(created.status_code, 201, created.text)
        document_id = created.json()["document"]["id"]
        published = self.client.post(
            f"/api/builder/workflows/{document_id}/publish", headers=headers
        )
        self.assertEqual(published.status_code, 200, published.text)
        workflow_id = published.json()["workflow_id"]
        self.track(workflow_id)
        return document_id, workflow_id
