"""Plan 01 D3's boot check, and the 503 that stands in for it when auth is off.

The shape is `_assert_auth_startup_safety`'s: a configuration that starts
cleanly, serves traffic, and is wrong is refused at startup with a sentence
naming the knob. Here that configuration is "people can sign in and the vault
has no key to keep theirs with". The other half - auth off, no key - is not a
misconfiguration, it is a bare checkout, and the credential routes answer 503
naming the feature while everything else is untouched.

`tests/__init__.py` exports a placeholder master key so every OTHER module's
`create_app` under `AUTH_BASE_URL` passes this check; the tests below patch
`config.CREDENTIALS_MASTER_KEY` themselves, which is the only honest way to be
keyless in a process that already has a key.
"""

from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from brief_crew import config
from brief_crew.service.credentials import MasterKeyInvalid
from tests.builder.test_compiler import straight_line
from tests.service.identities import CREDENTIALS, SECRET, SYNTHETIC_USER_HEADER, wire

try:  # pragma: no cover
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False


def patched(**values: object) -> list[object]:
    return [patch.object(config, name, value) for name, value in values.items()]


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class BootRefusalTests(unittest.TestCase):
    def _start(self, patches: list) -> None:
        from brief_crew.service.app import create_app

        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        create_app(synthetic=True)

    def test_auth_on_and_no_master_key_refuses_to_start_naming_the_knob(self) -> None:
        with self.assertRaises(RuntimeError) as caught:
            self._start(
                patched(
                    AUTH_BASE_URL="https://auth.example.test",
                    VALIDATOR_REQUIRE_AUTH=False,
                    CREDENTIALS_MASTER_KEY="",
                )
            )
        message = str(caught.exception)
        self.assertIn("CREDENTIALS_MASTER_KEY", message)
        self.assertIn("AUTH_BASE_URL", message)
        self.assertIn("secrets.token_bytes(32)", message)

    def test_a_malformed_key_refuses_to_start_whether_or_not_auth_is_on(self) -> None:
        for auth in ("", "https://auth.example.test"):
            with self.subTest(auth=auth):
                with self.assertRaises(MasterKeyInvalid) as caught:
                    self._start(
                        patched(
                            AUTH_BASE_URL=auth,
                            VALIDATOR_REQUIRE_AUTH=False,
                            CREDENTIALS_MASTER_KEY="not base64 at all!",
                        )
                    )
                self.assertIn("CREDENTIALS_MASTER_KEY", str(caught.exception))

    def test_a_key_of_the_wrong_length_is_refused_naming_the_length(self) -> None:
        with self.assertRaises(MasterKeyInvalid) as caught:
            self._start(
                patched(
                    AUTH_BASE_URL="",
                    VALIDATOR_REQUIRE_AUTH=False,
                    CREDENTIALS_MASTER_KEY=base64.b64encode(b"\x01" * 24).decode(),
                )
            )
        self.assertIn("24 bytes", str(caught.exception))

    def test_auth_on_with_the_placeholder_key_starts(self) -> None:
        """The control: the state every other test module runs in."""

        self._start(patched(AUTH_BASE_URL="https://auth.example.test", VALIDATOR_REQUIRE_AUTH=False))


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class KeylessVaultTests(unittest.TestCase):
    """Auth off, no key: the routes say the vault is not configured, and that is all."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        for item in patched(AUTH_BASE_URL="", VALIDATOR_REQUIRE_AUTH=False, CREDENTIALS_MASTER_KEY=""):
            item.start()
            self.addCleanup(item.stop)
        self.client = TestClient(create_app(synthetic=True))
        self.addCleanup(self.client.close)
        self.alice = {SYNTHETIC_USER_HEADER: "alice"}

    def test_every_credential_route_answers_503_naming_the_feature(self) -> None:
        body = {"kind": "openrouter", "label": "k", "fields": {"api_key": SECRET}}
        for method, path, json_body in (
            ("get", CREDENTIALS, None),
            ("post", CREDENTIALS, body),
            ("get", f"{CREDENTIALS}/cr_00000000", None),
            ("delete", f"{CREDENTIALS}/cr_00000000", None),
            ("post", f"{CREDENTIALS}/cr_00000000/test", None),
        ):
            with self.subTest(method=method, path=path):
                call = getattr(self.client, method)
                response = (
                    call(path, json=json_body, headers=self.alice)
                    if json_body is not None
                    else call(path, headers=self.alice)
                )
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()["detail"], "credential vault is not configured")
                self.assertNotIn(SECRET, response.text)

    def test_the_vault_answers_before_identity_does(self) -> None:
        """A 401 here would suggest signing in would help. It would not."""

        response = self.client.get(CREDENTIALS)
        self.assertEqual(response.status_code, 503, response.text)

    def test_nothing_else_changes(self) -> None:
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/api/workflows").status_code, 200)
        validated = self.client.post(
            "/api/builder/validate", json={"document": wire(straight_line())}, headers=self.alice
        )
        self.assertEqual(validated.status_code, 200, validated.text)
        self.assertTrue(validated.json()["valid"])

    def test_a_credential_reference_is_missing_on_a_keyless_deployment_and_says_so(self) -> None:
        """Honest rather than lenient: no vault holds no rows, so a run here would fail."""

        document = wire(straight_line())
        document["nodes"][1]["config"]["credential_id"] = "cr_0000aaaa"
        validated = self.client.post(
            "/api/builder/validate", json={"document": document}, headers=self.alice
        )
        self.assertEqual(validated.status_code, 200, validated.text)
        body = validated.json()
        self.assertTrue(body["identity_checked"])
        self.assertEqual([problem["code"] for problem in body["problems"]], ["credential-missing"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
