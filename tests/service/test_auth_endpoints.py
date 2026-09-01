"""Authentication at the HTTP boundary: who is refused, and who owns what.

The endpoint that spends money was unauthenticated by design, and CLAUDE.md is
explicit about why that was survivable: a gated run stops after one escalation
call, so *human inaction was the de facto spend cap*. These tests cover what
replaces that argument.

Two properties carry most of the weight and neither is obvious:

* A run belonging to somebody else answers **404, not 403**. A 403 confirms the
  run exists.
* A run with **no owner** stays readable. Rows written before authentication
  existed cannot be given an owner retroactively, and refusing them would make
  deploying this change destroy the history it was meant to organise.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from brief_crew import config
from brief_crew.service.app import create_app, _assert_auth_startup_safety
from brief_crew.service.auth import AuthenticatedUser, AuthError

ADA = AuthenticatedUser(id="user_ada", email="ada@example.test", name="Ada")
GRACE = AuthenticatedUser(id="user_grace", email="grace@example.test", name="Grace")

LAUNCH = {"workflow_id": "idea-validator", "inputs": {"idea": "a scheduling tool for clinics"}}


class AuthEnabledCase(unittest.TestCase):
    """A synthetic app with authentication switched on and tokens stubbed.

    `verify_token` is patched rather than real tokens being minted, and the
    boundary is chosen deliberately: the cryptography is covered exhaustively
    against genuine Ed25519 signatures in `test_auth_jwt.py`, so repeating it
    here would test PyJWT twice and the *authorisation* logic once. What these
    tests are for is what the endpoints do with the answer.
    """

    def setUp(self) -> None:
        self.tokens: dict[str, AuthenticatedUser] = {
            "ada-token": ADA,
            "grace-token": GRACE,
        }

        def fake_verify(token: str, **_: object) -> AuthenticatedUser:
            try:
                return self.tokens[token]
            except KeyError as exc:
                raise AuthError("token is not valid") from exc

        patches = [
            patch.object(config, "AUTH_BASE_URL", "https://auth.example.test"),
            patch.object(config, "VALIDATOR_REQUIRE_AUTH", True),
            patch("brief_crew.service.app.verify_token", fake_verify),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        self.app = create_app(synthetic=True)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def auth(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def launch_as(self, token: str) -> str:
        response = self.client.post(
            "/api/sessions/session-1/runs", json=LAUNCH, headers=self.auth(token)
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["run_id"]


class RefusalTests(AuthEnabledCase):
    """Every endpoint that costs money or reveals a run demands a token."""

    def test_launching_without_a_token_is_refused(self) -> None:
        response = self.client.post("/api/sessions/session-1/runs", json=LAUNCH)
        self.assertEqual(response.status_code, 401)

    def test_a_401_names_the_scheme_the_client_should_use(self) -> None:
        """RFC 9110 requires it, and it is how a client knows it is not cookies."""
        response = self.client.post("/api/sessions/session-1/runs", json=LAUNCH)
        self.assertIn("Bearer", response.headers.get("WWW-Authenticate", ""))

    def test_an_unparseable_token_is_refused(self) -> None:
        response = self.client.post(
            "/api/sessions/session-1/runs", json=LAUNCH, headers=self.auth("nonsense")
        )
        self.assertEqual(response.status_code, 401)

    def test_a_non_bearer_scheme_is_refused(self) -> None:
        response = self.client.post(
            "/api/sessions/session-1/runs",
            json=LAUNCH,
            headers={"Authorization": "Basic ada-token"},
        )
        self.assertEqual(response.status_code, 401)

    def test_every_run_endpoint_refuses_an_anonymous_caller(self) -> None:
        run_id = self.launch_as("ada-token")
        for method, path in (
            ("get", f"/api/runs/{run_id}"),
            ("get", f"/api/runs/{run_id}/frames"),
            ("get", f"/api/runs/{run_id}/logs"),
            ("post", f"/api/runs/{run_id}/cancel"),
            ("post", f"/api/runs/{run_id}/gates/scope-confirmation"),
        ):
            with self.subTest(path=path):
                call = getattr(self.client, method)
                response = call(path) if method == "get" else call(path, json={"outcome": "scope_ok"})
                self.assertEqual(response.status_code, 401, path)

    def test_health_and_readiness_stay_open(self) -> None:
        """Monitoring must not need a credential, or an outage looks like an outage."""
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertIn(self.client.get("/readyz").status_code, (200, 503))


class OwnershipTests(AuthEnabledCase):
    """One person's run is invisible to another, and looks absent rather than forbidden."""

    def test_the_owner_can_read_their_own_run(self) -> None:
        run_id = self.launch_as("ada-token")
        response = self.client.get(f"/api/runs/{run_id}", headers=self.auth("ada-token"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run_id"], run_id)

    def test_another_user_gets_404_not_403(self) -> None:
        """403 would confirm the run exists. 404 tells a stranger nothing."""
        run_id = self.launch_as("ada-token")
        response = self.client.get(f"/api/runs/{run_id}", headers=self.auth("grace-token"))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(run_id, response.text)

    def test_a_stranger_is_refused_on_every_run_endpoint(self) -> None:
        run_id = self.launch_as("ada-token")
        for method, path in (
            ("get", f"/api/runs/{run_id}"),
            ("get", f"/api/runs/{run_id}/frames"),
            ("get", f"/api/runs/{run_id}/logs"),
            ("post", f"/api/runs/{run_id}/cancel"),
        ):
            with self.subTest(path=path):
                call = getattr(self.client, method)
                headers = self.auth("grace-token")
                response = call(path, headers=headers) if method == "get" else call(
                    path, headers=headers, json={}
                )
                self.assertEqual(response.status_code, 404, path)

    def test_a_stranger_cannot_cancel_a_run_they_do_not_own(self) -> None:
        """The sharpest case: a refusal that is merely cosmetic would let anyone
        signed in stop anyone else's paid run."""
        run_id = self.launch_as("ada-token")
        self.client.post(f"/api/runs/{run_id}/cancel", headers=self.auth("grace-token"))
        still_mine = self.client.get(f"/api/runs/{run_id}", headers=self.auth("ada-token"))
        self.assertEqual(still_mine.status_code, 200)
        self.assertNotIn(still_mine.json()["status"], {"cancelled", "cancelling"})


class HistoryTests(AuthEnabledCase):
    """`GET /api/runs` returns the caller's own rows and nobody else's."""

    def test_a_new_user_has_an_empty_history(self) -> None:
        response = self.client.get("/api/runs", headers=self.auth("grace-token"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["runs"], [])

    def test_history_holds_only_the_callers_runs(self) -> None:
        mine = self.launch_as("ada-token")
        theirs = self.launch_as("grace-token")

        ada = self.client.get("/api/runs", headers=self.auth("ada-token")).json()["runs"]
        ada_ids = {row["run_id"] for row in ada}
        self.assertIn(mine, ada_ids)
        self.assertNotIn(theirs, ada_ids)

    def test_a_history_row_is_recognisable_without_opening_it(self) -> None:
        """A column of uuids is not a history anyone can use."""
        self.launch_as("ada-token")
        row = self.client.get("/api/runs", headers=self.auth("ada-token")).json()["runs"][0]
        self.assertIn("scheduling tool", row["label"])
        self.assertEqual(row["workflow_id"], "idea-validator")

    def test_a_history_row_does_not_leak_the_session_id(self) -> None:
        """`session_id` plus `run_id` opens the run's live socket. A list of
        historical runs must not hand out a bundle of stream credentials."""
        self.launch_as("ada-token")
        row = self.client.get("/api/runs", headers=self.auth("ada-token")).json()["runs"][0]
        self.assertNotIn("session_id", row)

    def test_an_anonymous_caller_gets_nothing_rather_than_everything(self) -> None:
        """The dangerous reading of "no user" is "no filter"."""
        self.launch_as("ada-token")
        with patch.object(config, "VALIDATOR_REQUIRE_AUTH", False):
            response = self.client.get("/api/runs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["runs"], [])

    def test_the_limit_is_bounded(self) -> None:
        self.assertEqual(
            self.client.get("/api/runs?limit=0", headers=self.auth("ada-token")).status_code,
            422,
        )
        self.assertEqual(
            self.client.get("/api/runs?limit=500", headers=self.auth("ada-token")).status_code,
            422,
        )


class RateLimitKeyTests(AuthEnabledCase):
    """The limit follows the person, not the address.

    The limiter is INJECTED with `max_runs=1` rather than patched into
    `config`. `RunRateLimiter.__init__` reads the constant once, at
    construction, inside `create_app` - so a `patch.object(config, ...)` in a
    test body arrives after the limiter already holds the default of 10, and
    every assertion below would pass because nothing was ever throttled. The
    first test is the control that proves the limit is actually biting.
    """

    def setUp(self) -> None:
        super().setUp()
        from brief_crew.service.app import RunRateLimiter

        self.client.close()
        self.app = create_app(synthetic=True, rate_limiter=RunRateLimiter(max_runs=1))
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_the_limit_is_actually_in_force(self) -> None:
        """The control. Without this, the test below proves nothing."""
        first = self.client.post(
            "/api/sessions/s/runs", json=LAUNCH, headers=self.auth("ada-token")
        )
        second = self.client.post(
            "/api/sessions/s/runs", json=LAUNCH, headers=self.auth("ada-token")
        )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 429)

    def test_two_users_from_one_address_do_not_share_a_bucket(self) -> None:
        """Behind Render's proxy the socket peer IS the proxy, so an
        address-keyed limit puts every visitor on earth in one bucket and the
        first person to press Launch rate-limits everybody else.
        """
        first = self.client.post(
            "/api/sessions/s/runs", json=LAUNCH, headers=self.auth("ada-token")
        )
        second = self.client.post(
            "/api/sessions/s/runs", json=LAUNCH, headers=self.auth("grace-token")
        )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(
            second.status_code,
            202,
            "a second USER was throttled by the first user's launch",
        )


class UnauthenticatedDeploymentTests(unittest.TestCase):
    """With no auth server configured, nothing changes from before."""

    def setUp(self) -> None:
        patcher = patch.object(config, "AUTH_BASE_URL", "")
        patcher.start()
        self.addCleanup(patcher.stop)
        flag = patch.object(config, "VALIDATOR_REQUIRE_AUTH", False)
        flag.start()
        self.addCleanup(flag.stop)
        self.client = TestClient(create_app(synthetic=True))
        self.addCleanup(self.client.close)

    def test_an_anonymous_run_still_works(self) -> None:
        response = self.client.post("/api/sessions/session-1/runs", json=LAUNCH)
        self.assertEqual(response.status_code, 202, response.text)

    def test_a_token_is_ignored_rather_than_refused_when_nothing_can_verify_it(
        self,
    ) -> None:
        """With no AUTH_BASE_URL there are no keys, no issuer and no audience.

        401 would tell the client its credential was bad; the truth is that this
        service cannot judge it and did not ask for one. `stream_frames` already
        took this position for the WebSocket, and the two paths disagreeing
        about who is signed in is worse than either answer.
        """
        response = self.client.post(
            "/api/sessions/session-1/runs",
            json=LAUNCH,
            headers={"Authorization": "Bearer some-token-from-another-deployment"},
        )
        self.assertEqual(response.status_code, 202, response.text)

    def test_an_unowned_run_is_readable_by_anyone(self) -> None:
        """Rows written before auth existed have no owner and cannot be given
        one. Refusing them would make deploying this change destroy the history
        it was meant to organise."""
        run_id = self.client.post("/api/sessions/session-1/runs", json=LAUNCH).json()["run_id"]
        self.assertEqual(self.client.get(f"/api/runs/{run_id}").status_code, 200)


class StartupSafetyTests(unittest.TestCase):
    """Two configurations that would start cleanly and be wrong."""

    def test_requiring_auth_without_a_server_is_refused(self) -> None:
        with patch.object(config, "VALIDATOR_REQUIRE_AUTH", True), patch.object(
            config, "AUTH_BASE_URL", ""
        ):
            with self.assertRaises(RuntimeError) as caught:
                _assert_auth_startup_safety()
            self.assertIn("AUTH_BASE_URL", str(caught.exception))

    def test_wildcard_cors_with_auth_is_refused(self) -> None:
        """`config.py` states the rule: the wildcard is survivable only while
        there is nothing to steal."""
        with patch.object(config, "VALIDATOR_REQUIRE_AUTH", True), patch.object(
            config, "AUTH_BASE_URL", "https://auth.example.test"
        ), patch.object(config, "CORS_ALLOW_ORIGINS", ("*",)):
            with self.assertRaises(RuntimeError) as caught:
                _assert_auth_startup_safety()
            self.assertIn("*", str(caught.exception))

    def test_the_unauthenticated_default_still_starts(self) -> None:
        with patch.object(config, "VALIDATOR_REQUIRE_AUTH", False):
            _assert_auth_startup_safety()

    def test_authorization_is_an_allowed_cors_request_header(self) -> None:
        """Not decoration: `Authorization` is not CORS-safelisted, so without it
        the browser preflights, drops the real request, and the failure looks
        like the API being down rather than a header being missing."""
        self.assertIn("Authorization", config.CORS_ALLOW_HEADERS)


if __name__ == "__main__":
    unittest.main()
