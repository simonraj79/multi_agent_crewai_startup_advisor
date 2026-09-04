"""Plan 01 D8: `X-Synthetic-User`, honoured under two conditions and no other.

`create_app(synthetic=True)` AND `AUTH_BASE_URL` unset - the same fail-closed
shape as `expose_docs = EXPOSE_API_DOCS or synthetic`. Three configurations
are asserted, and the two where the header must be IGNORED matter more than
the one where it works: a header a stranger can type must never become an
identity on a deployment that has a real one.

The discriminator throughout is `POST /api/builder/credentials`, which is
401 for nobody and 201 for somebody, so "who am I" has an observable answer
without a whoami endpoint. The last class takes the header onto the WebSocket
handshake, where a run launched under a synthetic identity is OWNED and the
console would otherwise be closed with 4404 by its own run.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from starlette.websockets import WebSocketDisconnect

from brief_crew import config
from brief_crew.service.auth import AuthError, AuthenticatedUser
from tests.service.identities import (
    ALICE,
    CREDENTIALS,
    SECRET,
    SYNTHETIC_USER_HEADER,
)

try:  # pragma: no cover
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

BODY = {"kind": "openrouter", "label": "k", "fields": {"api_key": SECRET}}


def as_user(user_id: str) -> dict[str, str]:
    return {SYNTHETIC_USER_HEADER: user_id}


def build(*, synthetic: bool, auth: str, verify: object | None = None, case: unittest.TestCase) -> "TestClient":
    from fastapi.testclient import TestClient

    from brief_crew.service.app import create_app

    patches = [
        patch.object(config, "AUTH_BASE_URL", auth),
        patch.object(config, "VALIDATOR_REQUIRE_AUTH", False),
    ]
    if verify is not None:
        patches.append(patch("brief_crew.service.app.verify_token", verify))
    for item in patches:
        item.start()
        case.addCleanup(item.stop)
    client = TestClient(create_app(synthetic=synthetic, database_url="sqlite+pysqlite:///:memory:"))
    case.addCleanup(client.close)
    return client


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class HonouredTests(unittest.TestCase):
    """Synthetic, no auth server: the header IS the identity."""

    def setUp(self) -> None:
        self.client = build(synthetic=True, auth="", case=self)

    def test_the_header_makes_somebody_and_two_headers_make_two(self) -> None:
        created = self.client.post(CREDENTIALS, json=BODY, headers=as_user("alice"))
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(len(self.client.get(CREDENTIALS, headers=as_user("alice")).json()), 1)
        self.assertEqual(self.client.get(CREDENTIALS, headers=as_user("bob")).json(), [])

    def test_no_header_is_nobody(self) -> None:
        response = self.client.post(CREDENTIALS, json=BODY)
        self.assertEqual(response.status_code, 401, response.text)
        self.assertIn("Bearer", response.headers.get("WWW-Authenticate", ""))

    def test_a_run_launched_under_the_header_is_owned_by_it(self) -> None:
        launched = self.client.post(
            "/api/sessions/s/runs",
            json={"workflow_id": "idea-validator", "inputs": {"idea": "a scheduling tool for clinics"}},
            headers=as_user("alice"),
        )
        self.assertEqual(launched.status_code, 202, launched.text)
        run_id = launched.json()["run_id"]
        self.assertEqual(self.client.get(f"/api/runs/{run_id}", headers=as_user("alice")).status_code, 200)
        self.assertEqual(self.client.get(f"/api/runs/{run_id}", headers=as_user("bob")).status_code, 404)
        self.assertEqual(self.client.get(f"/api/runs/{run_id}").status_code, 404)
        self.assertEqual(
            [entry["run_id"] for entry in self.client.get("/api/runs", headers=as_user("alice")).json()["runs"]],
            [run_id],
        )

    def test_a_malformed_value_is_400_naming_the_header(self) -> None:
        for value in ("Alice", "al ice", "a" * 65, "alice@example.test", ""):
            with self.subTest(value=value):
                response = self.client.get(CREDENTIALS, headers=as_user(value))
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn(SYNTHETIC_USER_HEADER, response.json()["detail"])

    def test_the_boundary_values_are_accepted(self) -> None:
        for value in ("a", "a" * 64, "user_1-x"):
            with self.subTest(value=value):
                self.assertEqual(self.client.get(CREDENTIALS, headers=as_user(value)).status_code, 200)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class IgnoredUnderAuthTests(unittest.TestCase):
    """An auth server is configured: the bearer path is the only identity."""

    def setUp(self) -> None:
        def verify(token: str, **_: object) -> AuthenticatedUser:
            if token == "alice-token":
                return ALICE
            raise AuthError("token is not valid")

        self.client = build(synthetic=True, auth="https://auth.example.test", verify=verify, case=self)

    def test_the_header_alone_is_nobody(self) -> None:
        self.assertEqual(self.client.post(CREDENTIALS, json=BODY, headers=as_user("alice")).status_code, 401)

    def test_the_bearer_wins_and_the_header_names_nobody_else(self) -> None:
        bearer = {"Authorization": "Bearer alice-token"}
        created = self.client.post(CREDENTIALS, json=BODY, headers={**bearer, **as_user("mallory")})
        self.assertEqual(created.status_code, 201, created.text)
        # The row is the bearer's - visible without the header, and the
        # header on its own is still nobody.
        self.assertEqual(len(self.client.get(CREDENTIALS, headers=bearer).json()), 1)
        self.assertEqual(self.client.get(CREDENTIALS, headers=as_user("mallory")).status_code, 401)

    def test_a_bad_bearer_is_refused_even_with_the_header_beside_it(self) -> None:
        response = self.client.get(
            CREDENTIALS, headers={"Authorization": "Bearer nonsense", **as_user("alice")}
        )
        self.assertEqual(response.status_code, 401)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class IgnoredOnAPaidAppTests(unittest.TestCase):
    """Not synthetic, no auth server: the caller is anonymous, header or not."""

    def setUp(self) -> None:
        # `synthetic=False` builds the paid runners; constructing them is free
        # and nothing here launches anything.
        self.client = build(synthetic=False, auth="", case=self)

    def test_the_header_is_ignored(self) -> None:
        self.assertEqual(self.client.post(CREDENTIALS, json=BODY, headers=as_user("alice")).status_code, 401)
        self.assertEqual(self.client.get(CREDENTIALS, headers=as_user("alice")).status_code, 401)

    def test_a_malformed_header_is_not_even_looked_at(self) -> None:
        self.assertEqual(self.client.get(CREDENTIALS, headers=as_user("Not Valid")).status_code, 401)

    def test_public_reads_are_still_public(self) -> None:
        self.assertEqual(self.client.get("/api/workflows", headers=as_user("alice")).status_code, 200)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class HandshakeTests(unittest.TestCase):
    """The same header on the WebSocket upgrade, under the same two conditions."""

    def setUp(self) -> None:
        self.client = build(synthetic=True, auth="", case=self)
        launched = self.client.post(
            "/api/sessions/s-ws/runs",
            json={"workflow_id": "idea-validator", "inputs": {"idea": "a scheduling tool for clinics"}},
            headers=as_user("alice"),
        )
        self.assertEqual(launched.status_code, 202, launched.text)
        self.run_id = launched.json()["run_id"]
        self.path = f"/ws?session_id=s-ws&run_id={self.run_id}"

    def test_the_owner_streams_her_own_run(self) -> None:
        with self.client.websocket_connect(self.path, headers=as_user("alice")) as websocket:
            first = websocket.receive_json()
        self.assertIn(first["type"], {"frame", "ping"})

    def test_anybody_else_and_nobody_are_closed_with_4404(self) -> None:
        for headers in (as_user("bob"), {}):
            with self.subTest(headers=headers):
                with self.assertRaises(WebSocketDisconnect) as caught:
                    with self.client.websocket_connect(self.path, headers=headers) as websocket:
                        websocket.receive_json()
                self.assertEqual(caught.exception.code, 4404)

    def test_a_malformed_header_is_closed_with_4400(self) -> None:
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect(self.path, headers=as_user("Not Valid")) as websocket:
                websocket.receive_json()
        self.assertEqual(caught.exception.code, 4400)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
