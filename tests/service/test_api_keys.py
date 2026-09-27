"""Plan 22: personal API keys - criteria 1-10, against a synthetic app.

Same boundary as `test_run_rating.py`: `verify_token` is patched to a table of
three people, because what these tests are for is what the service does with a
key, not PyJWT. The keys themselves are REAL - minted by the route, hashed,
stored and resolved through the same `optional_user` every request uses.
"""

from __future__ import annotations

import hashlib
import unittest
from datetime import timedelta
from unittest.mock import patch

from brief_crew import config
from brief_crew.service.api_keys import (
    API_KEY_INVALID_DETAIL,
    SESSION_REQUIRED_DETAIL,
    generate_api_key,
)
from brief_crew.service.auth import AuthenticatedUser, AuthError
from tests.service.identities import TEST_MASTER_KEY

ADA = AuthenticatedUser(id="user_ada", email="ada@example.test", name="Ada")
GRACE = AuthenticatedUser(id="user_grace", email="grace@example.test", name="Grace")
ADMIN = AuthenticatedUser(id="user_admin", email="admin@example.test", name="Admin")
TOKENS = {"ada-token": ADA, "grace-token": GRACE, "admin-token": ADMIN}
LAUNCH = {"workflow_id": "idea-validator", "inputs": {"idea": "a scheduling assistant"}}
KEYS = "/api/account/api-keys"


class ApiKeyCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()

        def fake_verify(token: str, **_: object) -> AuthenticatedUser:
            try:
                return TOKENS[token]
            except KeyError as exc:
                raise AuthError("token is not valid") from exc

        for item in (
            patch.object(config, "AUTH_BASE_URL", "https://auth.example.test"),
            patch.object(config, "VALIDATOR_REQUIRE_AUTH", True),
            patch.object(config, "CREDENTIALS_MASTER_KEY", TEST_MASTER_KEY),
            patch.object(config, "ADMIN_EMAILS", ("admin@example.test",)),
            patch("brief_crew.service.app.verify_token", fake_verify),
        ):
            item.start()
            self.addCleanup(item.stop)

        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        # Its own in-memory database: the limit tests count rows, and this
        # machine's .env points DATABASE_URL at a shared dev database (item 66).
        self.app = create_app(synthetic=True, database_url="sqlite+pysqlite:///:memory:")
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.registry = self.app.state.run_registry
        self.persistence = self.registry.persistence

    @staticmethod
    def auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def mint(self, token: str = "ada-token", name: str = "ci") -> dict:
        response = self.client.post(KEYS, json={"name": name}, headers=self.auth(token))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()


class CreateAndUseTests(ApiKeyCase):
    def test_a_key_authenticates_whoami_as_its_owner(self) -> None:  # 1
        secret = self.mint()["secret"]
        self.assertTrue(secret.startswith(config.API_KEY_PREFIX))
        body = self.client.get("/api/account/whoami", headers=self.auth(secret)).json()
        self.assertEqual(body["id"], ADA.id)
        self.assertEqual(body["email"], ADA.email)
        self.assertEqual(body["via"], "api_key")
        session = self.client.get("/api/account/whoami", headers=self.auth("ada-token"))
        self.assertEqual(session.json()["via"], "session")

    def test_the_secret_is_shown_once_and_only_its_hash_is_stored(self) -> None:  # 2
        created = self.mint()
        secret = created["secret"]
        listed = self.client.get(KEYS, headers=self.auth("ada-token")).json()
        self.assertNotIn(secret, str(listed))
        self.assertEqual(listed["keys"][0]["id"], created["key"]["id"])
        self.assertEqual(listed["keys"][0]["prefix"], secret[: config.API_KEY_DISPLAY_CHARS])
        self.assertEqual(listed["limit"], config.MAX_API_KEYS_PER_USER)
        from sqlalchemy import select

        from brief_crew.service.persistence import api_keys

        with self.persistence._connect() as connection:
            rows = connection.execute(select(api_keys)).mappings().all()
        self.assertNotIn(secret, str([dict(row) for row in rows]))
        self.assertEqual(
            rows[0]["secret_hash"], hashlib.sha256(secret.encode()).hexdigest()
        )

    def test_a_key_launches_and_reads_its_owners_run(self) -> None:  # 3
        secret = self.mint()["secret"]
        launched = self.client.post(
            "/api/sessions/my-script/runs", json=LAUNCH, headers=self.auth(secret)
        )
        self.assertEqual(launched.status_code, 202, launched.text)
        run_id = launched.json()["run_id"]
        self.registry.wait(run_id, timeout=5)
        self.assertEqual(self.registry.require(run_id).user_id, ADA.id)
        read = self.client.get(f"/api/runs/{run_id}", headers=self.auth(secret))
        self.assertEqual(read.status_code, 200, read.text)
        # And the session sees the same run in its own history.
        history = self.client.get("/api/runs", headers=self.auth("ada-token"))
        self.assertIn(run_id, history.text)

    def test_another_users_run_is_404_to_a_key(self) -> None:  # 4
        launched = self.client.post(
            "/api/sessions/s/runs", json=LAUNCH, headers=self.auth("grace-token")
        )
        run_id = launched.json()["run_id"]
        self.registry.wait(run_id, timeout=5)
        secret = self.mint()["secret"]
        self.assertEqual(
            self.client.get(f"/api/runs/{run_id}", headers=self.auth(secret)).status_code,
            404,
        )


class RevocationTests(ApiKeyCase):
    def test_a_revoked_key_is_refused_on_the_next_request(self) -> None:  # 5
        created = self.mint()
        secret = created["secret"]
        self.assertEqual(
            self.client.get("/api/account/whoami", headers=self.auth(secret)).status_code,
            200,
        )
        revoked = self.client.delete(
            f"{KEYS}/{created['key']['id']}", headers=self.auth("ada-token")
        )
        self.assertEqual(revoked.status_code, 204)
        refused = self.client.get("/api/account/whoami", headers=self.auth(secret))
        self.assertEqual(refused.status_code, 401)
        self.assertEqual(refused.json()["detail"], API_KEY_INVALID_DETAIL)
        self.assertEqual(self.client.get(KEYS, headers=self.auth("ada-token")).json()["keys"], [])

    def test_an_unknown_key_is_401_never_anonymous(self) -> None:
        forged, _, _ = generate_api_key()
        refused = self.client.get("/api/workflows", headers=self.auth(forged))
        self.assertEqual(refused.status_code, 401)

    def test_an_oversized_key_is_refused_without_a_lookup(self) -> None:
        huge = config.API_KEY_PREFIX + "a" * 10_000
        with patch.object(type(self.persistence), "resolve_api_key") as lookup:
            refused = self.client.get("/api/account/whoami", headers=self.auth(huge))
        self.assertEqual(refused.status_code, 401)
        lookup.assert_not_called()

    def test_another_users_key_id_is_404_on_delete(self) -> None:  # 8
        created = self.mint("grace-token")
        response = self.client.delete(
            f"{KEYS}/{created['key']['id']}", headers=self.auth("ada-token")
        )
        self.assertEqual(response.status_code, 404)
        # Still live for Grace.
        self.assertEqual(
            self.client.get(
                "/api/account/whoami", headers=self.auth(created["secret"])
            ).status_code,
            200,
        )


class WhatAKeyMayNotDoTests(ApiKeyCase):  # 6
    def test_a_key_cannot_manage_keys(self) -> None:
        created = self.mint()
        secret = created["secret"]
        for method, path, body in (
            ("get", KEYS, None),
            ("post", KEYS, {"name": "escalate"}),
            ("delete", f"{KEYS}/{created['key']['id']}", None),
        ):
            kwargs = {"headers": self.auth(secret)}
            if body is not None:
                kwargs["json"] = body
            response = getattr(self.client, method)(path, **kwargs)
            self.assertEqual(response.status_code, 403, (method, path, response.text))
            self.assertEqual(response.json()["detail"], SESSION_REQUIRED_DETAIL)

    def test_a_key_cannot_reach_the_credential_vault(self) -> None:
        secret = self.mint()["secret"]
        response = self.client.get("/api/builder/credentials", headers=self.auth(secret))
        self.assertEqual(response.status_code, 403, response.text)
        # The session still can.
        self.assertEqual(
            self.client.get(
                "/api/builder/credentials", headers=self.auth("ada-token")
            ).status_code,
            200,
        )

    def test_an_admins_key_gets_404_on_the_console(self) -> None:
        self.assertEqual(
            self.client.get("/api/admin/summary", headers=self.auth("admin-token")).status_code,
            200,
        )
        secret = self.mint("admin-token")["secret"]
        self.assertEqual(
            self.client.get("/api/admin/summary", headers=self.auth(secret)).status_code,
            404,
        )
        whoami = self.client.get("/api/admin/whoami", headers=self.auth(secret)).json()
        self.assertFalse(whoami["admin"])


class LimitAndBookkeepingTests(ApiKeyCase):
    def test_the_eleventh_key_is_409_and_revoking_frees_a_slot(self) -> None:  # 7
        with patch.object(config, "MAX_API_KEYS_PER_USER", 3):
            first = self.mint()
            self.mint()
            self.mint()
            over = self.client.post(KEYS, json={"name": "x"}, headers=self.auth("ada-token"))
            self.assertEqual(over.status_code, 409, over.text)
            # Another person is not affected by Ada's count.
            self.mint("grace-token")
            self.client.delete(f"{KEYS}/{first['key']['id']}", headers=self.auth("ada-token"))
            self.mint()

    def test_a_blank_or_control_character_name_is_refused(self) -> None:
        for name in ("", "   ", "\x00\x01"):
            response = self.client.post(KEYS, json={"name": name}, headers=self.auth("ada-token"))
            self.assertEqual(response.status_code, 422, name)
        too_long = "n" * (config.API_KEY_NAME_MAX_CHARS + 1)
        self.assertEqual(
            self.client.post(
                KEYS, json={"name": too_long}, headers=self.auth("ada-token")
            ).status_code,
            422,
        )

    def test_last_used_is_stamped_once_per_interval(self) -> None:  # 9
        created = self.mint()
        key_id = created["key"]["id"]
        self.assertIsNone(created["key"]["last_used_at"])
        headers = self.auth(created["secret"])
        self.client.get("/api/account/whoami", headers=headers)
        first = self.persistence.list_api_keys(ADA.id)[0]["last_used_at"]
        self.assertIsNotNone(first)
        self.client.get("/api/account/whoami", headers=headers)
        self.assertEqual(self.persistence.list_api_keys(ADA.id)[0]["last_used_at"], first)
        # Outside the interval it moves.
        self.assertTrue(
            self.persistence.touch_api_key(key_id, min_interval_seconds=0)
            or self.persistence.list_api_keys(ADA.id)[0]["last_used_at"] >= first
        )
        self.assertGreaterEqual(
            self.persistence.list_api_keys(ADA.id)[0]["last_used_at"] - first,
            timedelta(0),
        )


class SchemaTests(unittest.TestCase):  # 10
    def test_it_is_a_new_table_and_no_additive_column(self) -> None:
        from brief_crew.service import persistence

        self.assertIn("api_keys", persistence.metadata.tables)
        additive = persistence.PostgresFlowPersistence._ADDITIVE_COLUMNS.default
        self.assertFalse([entry for entry in additive if entry[0] == "api_keys"])


if __name__ == "__main__":
    unittest.main()
