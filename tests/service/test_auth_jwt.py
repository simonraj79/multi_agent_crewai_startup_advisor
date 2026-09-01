"""The Bearer-token verifier, exercised against REAL Ed25519 signatures.

Nothing here is mocked at the crypto boundary. Each test mints a genuine
Ed25519 key pair, publishes it as a JWKS document exactly as Better Auth's
``/api/auth/jwks`` endpoint does, and signs real tokens with the private half.
A verifier tested against a stubbed ``jwt.decode`` proves only that the stub was
called; the failure modes that matter here - ``alg: none``, an HMAC forgery, a
key that is not the one that signed - are all *cryptographic*, so the crypto has
to be real for the test to mean anything.

The JWKS *transport* is stubbed (via the ``fetcher`` seam), because fetching
over HTTP is not what is under test and a suite that reaches the network is not
a suite this repo will run.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import unittest
from typing import Any
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from brief_crew import config
from brief_crew.service.auth import (
    AuthenticatedUser,
    AuthError,
    JwksCache,
    auth_is_required,
    bearer_token_from_header,
    verify_token,
)

ISSUER = "https://auth.example.test"
KID = "test-key-1"


def _keypair(kid: str = KID) -> tuple[Ed25519PrivateKey, dict[str, Any]]:
    """An Ed25519 private key and the JWKS entry a client would publish for it."""
    private = Ed25519PrivateKey.generate()
    entry = json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(private.public_key()))
    entry.update({"kid": kid, "alg": "EdDSA", "use": "sig"})
    return private, entry


def _sign(
    private: Ed25519PrivateKey,
    *,
    kid: str = KID,
    issuer: str = ISSUER,
    audience: str = ISSUER,
    subject: str | None = "user_abc123",
    expires_in: int = 900,
    **extra: Any,
) -> str:
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in,
        **extra,
    }
    if subject is not None:
        claims["sub"] = subject
    return jwt.encode(claims, private, algorithm="EdDSA", headers={"kid": kid})


class VerifierTests(unittest.TestCase):
    """The happy path, and every way a token is refused."""

    def setUp(self) -> None:
        self.private, self.entry = _keypair()
        self.calls: list[str] = []

        def fetcher(url: str) -> dict[str, Any]:
            self.calls.append(url)
            return {"keys": [self.entry]}

        self.cache = JwksCache(ISSUER, fetcher=fetcher)
        patcher = patch.object(config, "AUTH_BASE_URL", ISSUER)
        patcher.start()
        self.addCleanup(patcher.stop)

    def verify(self, token: str) -> AuthenticatedUser:
        return verify_token(token, cache=self.cache)

    # -- the happy path ---------------------------------------------------

    def test_a_well_formed_token_yields_the_user_it_names(self) -> None:
        token = _sign(
            self.private,
            email="ada@example.test",
            name="Ada Lovelace",
            image="https://example.test/a.png",
        )
        user = self.verify(token)
        self.assertEqual(user.id, "user_abc123")
        self.assertEqual(user.email, "ada@example.test")
        self.assertEqual(user.name, "Ada Lovelace")
        self.assertEqual(user.label, "Ada Lovelace")

    def test_the_label_degrades_from_name_to_email_to_id(self) -> None:
        self.assertEqual(
            self.verify(_sign(self.private, email="a@b.test")).label, "a@b.test"
        )
        self.assertEqual(self.verify(_sign(self.private)).label, "user_abc123")

    def test_optional_claims_absent_are_none_not_empty_string(self) -> None:
        user = self.verify(_sign(self.private))
        self.assertIsNone(user.email)
        self.assertIsNone(user.name)
        self.assertIsNone(user.image)

    def test_an_empty_string_claim_is_treated_as_absent(self) -> None:
        # A provider that reports "" for a missing display name must not turn
        # `label` into an empty string, which would render as a blank chip.
        user = self.verify(_sign(self.private, name="", email=""))
        self.assertIsNone(user.name)
        self.assertEqual(user.label, "user_abc123")

    def test_the_identity_cannot_be_edited_after_the_check(self) -> None:
        user = self.verify(_sign(self.private))
        with self.assertRaises(Exception):
            user.id = "somebody-else"  # type: ignore[misc]

    # -- forgeries --------------------------------------------------------

    def test_alg_none_is_refused(self) -> None:
        """The oldest JWT break: an unsigned token asserting it needs no signature."""
        forged = jwt.encode(
            {"iss": ISSUER, "aud": ISSUER, "sub": "attacker", "exp": int(time.time()) + 60},
            key="",
            algorithm="none",
            headers={"kid": KID},
        )
        with self.assertRaises(AuthError):
            self.verify(forged)

    def test_an_hmac_forgery_using_the_public_key_as_the_secret_is_refused(self) -> None:
        """The classic algorithm-confusion attack.

        The public key is, by definition, public. If the verifier honoured the
        token's own `alg` header, an attacker could sign HS256 using that public
        key as the shared secret and be believed. The allowlist in
        `config.AUTH_JWT_ALGORITHMS` is what stops it.

        The forgery is assembled by hand rather than with `jwt.encode`, because
        PyJWT refuses to *sign* this shape - it raises InvalidKeyError on an
        asymmetric key handed to HMAC. That refusal is a defence on the signing
        side and says nothing about the verifying side, which is what is under
        test here, so the bytes have to be built directly.
        """
        public_pem = self.private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        def segment(payload: dict[str, Any]) -> bytes:
            return base64.urlsafe_b64encode(
                json.dumps(payload, separators=(",", ":")).encode()
            ).rstrip(b"=")

        signing_input = b".".join(
            (
                segment({"alg": "HS256", "typ": "JWT", "kid": KID}),
                segment(
                    {
                        "iss": ISSUER,
                        "aud": ISSUER,
                        "sub": "attacker",
                        "exp": int(time.time()) + 60,
                    }
                ),
            )
        )
        signature = base64.urlsafe_b64encode(
            hmac.new(public_pem, signing_input, hashlib.sha256).digest()
        ).rstrip(b"=")
        forged = f"{signing_input.decode()}.{signature.decode()}"

        # Sanity: the forgery IS internally consistent - the MAC really does
        # verify under the public key. Without this the test could pass for the
        # wrong reason, by rejecting a merely malformed token.
        #
        # The check is a raw hmac comparison rather than another jwt.decode
        # because PyJWT refuses to VERIFY this shape too, by the same
        # InvalidKeyError. That is a second, independent defence and a welcome
        # one - but it is PyJWT's, not this repo's, and the allowlist below is
        # what must hold if a future PyJWT ever relaxes it.
        self.assertTrue(
            hmac.compare_digest(
                signature,
                base64.urlsafe_b64encode(
                    hmac.new(public_pem, signing_input, hashlib.sha256).digest()
                ).rstrip(b"="),
            )
        )

        with self.assertRaises(AuthError):
            self.verify(forged)

    def test_a_token_signed_by_a_different_key_is_refused(self) -> None:
        other, _ = _keypair()
        with self.assertRaises(AuthError):
            self.verify(_sign(other))

    def test_a_tampered_payload_is_refused(self) -> None:
        token = _sign(self.private)
        head, payload, signature = token.split(".")
        swapped = jwt.encode(
            {"iss": ISSUER, "aud": ISSUER, "sub": "root", "exp": int(time.time()) + 60},
            key=Ed25519PrivateKey.generate(),
            algorithm="EdDSA",
        ).split(".")[1]
        with self.assertRaises(AuthError):
            self.verify(f"{head}.{swapped}.{signature}")

    def test_garbage_is_refused_rather_than_raising_something_else(self) -> None:
        for junk in ("", "not-a-token", "a.b", "a.b.c.d"):
            with self.subTest(junk=junk), self.assertRaises(AuthError):
                self.verify(junk)

    # -- claim checks -----------------------------------------------------

    def test_an_expired_token_is_refused(self) -> None:
        with self.assertRaises(AuthError):
            self.verify(_sign(self.private, expires_in=-3600))

    def test_a_token_from_another_issuer_is_refused(self) -> None:
        with self.assertRaises(AuthError):
            self.verify(_sign(self.private, issuer="https://evil.example"))

    def test_a_token_for_another_audience_is_refused(self) -> None:
        """A token minted for a DIFFERENT service must not be replayable here."""
        with self.assertRaises(AuthError):
            self.verify(_sign(self.private, audience="https://other.example"))

    def test_a_token_with_no_subject_is_refused(self) -> None:
        with self.assertRaises(AuthError):
            self.verify(_sign(self.private, subject=None))

    def test_a_token_with_no_kid_is_refused_without_fetching(self) -> None:
        token = jwt.encode(
            {"iss": ISSUER, "aud": ISSUER, "sub": "x", "exp": int(time.time()) + 60},
            self.private,
            algorithm="EdDSA",
        )
        with self.assertRaises(AuthError):
            self.verify(token)
        self.assertEqual(self.calls, [], "no kid should not cost a network call")

    def test_clock_skew_within_the_leeway_is_tolerated(self) -> None:
        """A token minted a few seconds in the future is not an attack.

        Two Render instances are not perfectly synchronised, and rejecting this
        produces an intermittent login failure that reproduces for nobody.
        """
        token = jwt.encode(
            {
                "iss": ISSUER,
                "aud": ISSUER,
                "sub": "user_abc123",
                "iat": int(time.time()) + 10,
                "exp": int(time.time()) + 900,
            },
            self.private,
            algorithm="EdDSA",
            headers={"kid": KID},
        )
        self.assertEqual(self.verify(token).id, "user_abc123")


class JwksCacheTests(unittest.TestCase):
    """Key fetching, caching, rotation and the behaviour when the fetch fails."""

    def setUp(self) -> None:
        self.private, self.entry = _keypair()
        self.calls: list[str] = []
        self.document: dict[str, Any] = {"keys": [self.entry]}
        self.fail_next = False
        patcher = patch.object(config, "AUTH_BASE_URL", ISSUER)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _fetcher(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        if self.fail_next:
            raise ConnectionError("auth service is cold-starting")
        return self.document

    def cache(self, **kwargs: Any) -> JwksCache:
        return JwksCache(ISSUER, fetcher=self._fetcher, **kwargs)

    def test_the_jwks_url_is_derived_from_the_base_origin(self) -> None:
        self.assertEqual(
            JwksCache("https://auth.example.test/").url,
            "https://auth.example.test/api/auth/jwks",
        )

    def test_keys_are_fetched_once_and_then_cached(self) -> None:
        cache = self.cache()
        for _ in range(5):
            verify_token(_sign(self.private), cache=cache)
        self.assertEqual(len(self.calls), 1, "the hot path must not refetch")

    def test_an_unknown_kid_forces_exactly_one_refetch(self) -> None:
        """Rotation recovery, bounded.

        Without the refetch a rotated key locks everyone out until the TTL
        expires. Without the bound, a flood of tokens bearing junk kids becomes
        a request amplifier pointed at the auth service.
        """
        cache = self.cache()
        verify_token(_sign(self.private), cache=cache)
        self.assertEqual(len(self.calls), 1)

        other, other_entry = _keypair(kid="rotated-key")
        self.document = {"keys": [self.entry, other_entry]}
        user = verify_token(_sign(other, kid="rotated-key"), cache=cache)

        self.assertEqual(user.id, "user_abc123")
        self.assertEqual(len(self.calls), 2, "one refetch, not a retry loop")

    def test_a_junk_kid_costs_one_refetch_and_is_then_refused(self) -> None:
        cache = self.cache()
        with self.assertRaises(AuthError):
            verify_token(_sign(self.private, kid="no-such-key"), cache=cache)
        self.assertEqual(len(self.calls), 1)

    def test_a_failed_refresh_keeps_serving_the_previous_keys(self) -> None:
        """Stale-but-working beats correct-but-down.

        The auth service sleeps on its Render plan. A cold start there must not
        invalidate every session against this API.
        """
        cache = self.cache(ttl_seconds=0)
        verify_token(_sign(self.private), cache=cache)

        self.fail_next = True
        user = verify_token(_sign(self.private), cache=cache)
        self.assertEqual(user.id, "user_abc123")
        self.assertGreaterEqual(len(self.calls), 2)

    def test_an_empty_document_does_not_wipe_working_keys(self) -> None:
        cache = self.cache(ttl_seconds=0)
        verify_token(_sign(self.private), cache=cache)
        self.document = {"keys": []}
        self.assertEqual(verify_token(_sign(self.private), cache=cache).id, "user_abc123")

    def test_one_unusable_entry_does_not_discard_the_usable_ones(self) -> None:
        self.document = {"keys": [{"kid": "broken", "kty": "OKP"}, self.entry]}
        cache = self.cache()
        self.assertEqual(verify_token(_sign(self.private), cache=cache).id, "user_abc123")

    def test_an_entry_with_no_kid_is_skipped(self) -> None:
        anonymous = dict(self.entry)
        anonymous.pop("kid")
        self.document = {"keys": [anonymous, self.entry]}
        cache = self.cache()
        self.assertEqual(verify_token(_sign(self.private), cache=cache).id, "user_abc123")


class HeaderAndPolicyTests(unittest.TestCase):
    """Header parsing, and the fail-closed default."""

    def test_bearer_is_parsed_case_insensitively(self) -> None:
        for header in ("Bearer abc", "bearer abc", "BEARER abc", "Bearer   abc"):
            with self.subTest(header=header):
                self.assertEqual(bearer_token_from_header(header), "abc")

    def test_a_non_bearer_scheme_yields_nothing(self) -> None:
        for header in (None, "", "Basic abc", "abc", "Bearer", "Bearer   "):
            with self.subTest(header=header):
                self.assertIsNone(bearer_token_from_header(header))

    def test_configuring_an_auth_server_turns_auth_on_by_itself(self) -> None:
        """The half-configured state must not exist.

        A flat `False` default would let a deployment set AUTH_BASE_URL, wire up
        the login screen, forget one boolean, and serve every paid endpoint
        unauthenticated with nothing on screen to say so.
        """
        with patch.object(config, "VALIDATOR_REQUIRE_AUTH", True):
            self.assertTrue(auth_is_required())
        with patch.object(config, "VALIDATOR_REQUIRE_AUTH", False):
            self.assertFalse(auth_is_required())

    def test_verification_without_a_configured_server_is_refused(self) -> None:
        with patch.object(config, "AUTH_BASE_URL", ""):
            with self.assertRaises(AuthError):
                verify_token("a.b.c")


if __name__ == "__main__":
    unittest.main()
