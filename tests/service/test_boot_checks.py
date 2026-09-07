"""Plan 01 D3's boot check, and the 503 that stands in for it when auth is off.

The shape is `_assert_auth_startup_safety`'s: a configuration that starts
cleanly, serves traffic, and is wrong is refused at startup with a sentence
naming the knob. Here that configuration is "people can sign in and the vault
has no key to keep theirs with". The other half - auth off, no key - is not a
misconfiguration, it is a bare checkout, and the credential routes answer 503
naming the feature while everything else is untouched.

Since audit L4 there is a third refusal on the same check: a key that is
PUBLISHED is refused on the same terms as an absent one.
`tests/__init__.py` exports `Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE=`
(base64 of `ci-placeholder-not-a-master-key!`) so a keyless module still has a
vault, and CLAUDE.md's E2E recipe pastes the same string into a shell - so a
deployment that copied the recipe would boot cleanly and encrypt every user's
API keys under a value anyone can read here. With no `AUTH_BASE_URL` nobody
can sign in and there is nothing real to keep, which is why the suites, the
E2E backend and a bare checkout still run on it untouched.

The tests below patch `config.CREDENTIALS_MASTER_KEY` themselves, which is the
only honest way to be keyless - or placeholder-keyed, or properly keyed - in a
process that already has one in its environment.
"""

from __future__ import annotations

import base64
import secrets
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

    def test_auth_on_with_a_real_key_starts(self) -> None:
        """The control. Every refusal above and below must be able to fail."""

        self._start(
            patched(
                AUTH_BASE_URL="https://auth.example.test",
                VALIDATOR_REQUIRE_AUTH=False,
                CREDENTIALS_MASTER_KEY=REAL_KEY,
            )
        )


#: A key minted the way the refusal's own sentence tells an operator to mint
#: one. Random, so nothing here can quietly become the next published key.
REAL_KEY = base64.b64encode(secrets.token_bytes(32)).decode()

#: The one `tests/__init__.py` exports and CLAUDE.md's E2E recipe pastes.
PLACEHOLDER_KEY = "Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class AuditL4PublishedPlaceholderKeyTests(BootRefusalTests):
    """A PUBLISHED master key is not a key - audit L4.

    The placeholder is a perfectly valid 32-byte AES-256-GCM key, so every
    check that existed before this one passed it: `load_master_key` parses it,
    the vault encrypts with it, `/readyz` reports a configured vault, and a
    deployment that copy-pasted the E2E recipe from CLAUDE.md would have
    protected its users' OpenRouter, Firecrawl and Postgres credentials with a
    string printed in a public repository. AES-256-GCM under a known key is an
    encoding.

    The refusal is scoped to the one configuration where it is a lie:
    `AUTH_BASE_URL` set means people can sign in, so there are real credentials
    in the vault. Without it there is no vault worth the name and no user to
    have one, and the suites, SYNTHETIC mode, the E2E backend and a bare
    checkout must all keep running on the placeholder - which is what the
    second test here pins.

    Subclasses `BootRefusalTests` deliberately: those four cases must keep
    passing beside these, because this rule adds a refusal and must not have
    moved an existing one.
    """

    def test_l4_the_placeholder_with_auth_on_refuses_to_start(self) -> None:
        with self.assertRaises(RuntimeError) as caught:
            self._start(
                patched(
                    AUTH_BASE_URL="https://auth.example.test",
                    VALIDATOR_REQUIRE_AUTH=False,
                    CREDENTIALS_MASTER_KEY=PLACEHOLDER_KEY,
                )
            )
        message = str(caught.exception)
        # Named as what it is, not merely refused: an operator who reads
        # "invalid" would go looking for a typo in a key that decodes fine.
        self.assertIn("placeholder", message)
        self.assertIn("CREDENTIALS_MASTER_KEY", message)
        self.assertIn("AUTH_BASE_URL", message)
        # And the way out, in the same sentence as the refusal.
        self.assertIn("secrets.token_bytes(32)", message)
        # The key itself is never echoed - it is public, but echoing a
        # credential-shaped value into a log is a habit, not an exception.
        self.assertNotIn(PLACEHOLDER_KEY, message)

    def test_l4_the_placeholder_with_no_auth_server_still_starts(self) -> None:
        """The carve-out, and it is the state most of this repository runs in.

        `SYNTHETIC=1` on :8099 with this exact key is the E2E recipe, the
        credential routes there hold nobody's secrets, and refusing it would
        break every free run to protect nothing.
        """

        self._start(
            patched(
                AUTH_BASE_URL="",
                VALIDATOR_REQUIRE_AUTH=False,
                CREDENTIALS_MASTER_KEY=PLACEHOLDER_KEY,
            )
        )

    def test_l4_a_real_key_with_auth_on_starts(self) -> None:
        """The control for the refusal: it is the VALUE, not the configuration."""

        self._start(
            patched(
                AUTH_BASE_URL="https://auth.example.test",
                VALIDATOR_REQUIRE_AUTH=False,
                CREDENTIALS_MASTER_KEY=REAL_KEY,
            )
        )

    def test_l4_the_refused_key_is_the_one_the_test_harness_publishes(self) -> None:
        """The two halves cannot drift: if `tests/__init__.py` ever mints a
        different placeholder, this fails rather than the refusal quietly
        ceasing to cover the string that is actually published."""

        import os

        self.assertIn(PLACEHOLDER_KEY, config.KNOWN_PLACEHOLDER_MASTER_KEYS)
        self.assertEqual(os.environ.get("CREDENTIALS_MASTER_KEY"), PLACEHOLDER_KEY)
        self.assertEqual(
            base64.b64decode(PLACEHOLDER_KEY), b"ci-placeholder-not-a-master-key!"
        )

    def test_l4_every_published_key_is_refused_not_only_the_first(self) -> None:
        """It is a set so that retiring a leaked key later is an append.

        Iterating it here means a second entry is covered the day it is added,
        rather than the day somebody remembers to write a test for it.
        """

        for key in config.KNOWN_PLACEHOLDER_MASTER_KEYS:
            with self.subTest(key=key[:8]):
                with self.assertRaises(RuntimeError) as caught:
                    self._start(
                        patched(
                            AUTH_BASE_URL="https://auth.example.test",
                            VALIDATOR_REQUIRE_AUTH=False,
                            CREDENTIALS_MASTER_KEY=key,
                        )
                    )
                self.assertIn("placeholder", str(caught.exception))


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
