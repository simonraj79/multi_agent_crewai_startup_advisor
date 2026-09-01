"""Verification of the Better Auth JWT this service is handed as a Bearer token.

WHY A TOKEN AND NOT A COOKIE
----------------------------
The SPA is served from the Better Auth origin, where an httpOnly session cookie
works normally. This API is a *different* origin, and ``onrender.com`` is on the
Public Suffix List, so no cookie can span the two. The SPA therefore calls
``/api/auth/token`` on its own origin - authenticated by that cookie - and gets
a short-lived JWT, which it sends here in an ``Authorization: Bearer`` header.

WHY OFFLINE VERIFICATION
------------------------
The auth service publishes its public keys at ``${AUTH_BASE_URL}/api/auth/jwks``.
Verifying against those means this service never calls back into the auth
service to serve a request: no added latency on the hot path, no shared secret
to distribute, and an auth service that is asleep (it is on a smaller Render
plan) cannot take the API down with it. The cost is that revocation is not
immediate - a signed token stays valid until it expires. That is bounded by the
15-minute ``expirationTime`` set in ``frontend/server/auth.ts``, which is why
that number is small and why it should stay small.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from .. import config

logger = logging.getLogger(__name__)

__all__ = [
    "AuthenticatedUser",
    "AuthError",
    "JwksCache",
    "auth_is_required",
    "bearer_token_from_header",
    "reset_jwks_cache",
    "verify_token",
]


class AuthError(Exception):
    """A token was absent, malformed, expired or not signed by the auth server.

    Deliberately one exception rather than a family. The caller turns this into
    a flat 401 with a generic message: telling an unauthenticated caller *which*
    check failed - bad signature versus expired versus wrong audience - is free
    reconnaissance and buys a legitimate client nothing, because a legitimate
    client's remedy is the same in every case (fetch a fresh token).
    """


@dataclass(frozen=True)
class AuthenticatedUser:
    """The verified identity behind one request.

    Frozen because a request handler must not be able to edit who it is acting
    for after the check has happened.
    """

    id: str
    email: str | None = None
    name: str | None = None
    image: str | None = None

    @property
    def label(self) -> str:
        """A human-readable handle for logs and the UI."""
        return self.name or self.email or self.id


def auth_is_required() -> bool:
    """Whether this process refuses unauthenticated callers.

    Read through a function rather than the constant directly so tests can patch
    one place, and so the answer is always the current config rather than a
    value captured at import time.
    """
    return bool(config.VALIDATOR_REQUIRE_AUTH)


def bearer_token_from_header(header: str | None) -> str | None:
    """Pull the credential out of an ``Authorization`` header.

    The scheme comparison is case-insensitive because RFC 9110 says the scheme
    token is; the credential itself is never touched.
    """
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


class JwksCache:
    """Fetches and caches the auth server's public keys.

    Two behaviours matter here and neither is the obvious one:

    * An **unknown ``kid`` forces an immediate refetch**, once, before the token
      is rejected. Better Auth mints a new key pair on rotation, and without
      this every session would fail for up to ``AUTH_JWKS_CACHE_SECONDS`` after
      a rotation, with a signature error that names nothing.
    * A refetch that **fails keeps serving the previous keys**. The auth service
      is on a plan that sleeps; a cold start there must not log every user of
      this API out. Stale-but-working beats correct-but-down.
    """

    def __init__(
        self,
        base_url: str,
        *,
        ttl_seconds: int | None = None,
        fetcher: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # `is None`, not `or`: a caller passing 0 means "never trust the
        # cache", and `0 or DEFAULT` silently hands them 3600 instead - the
        # exact opposite. Found by a test that asked for ttl=0 and got a
        # cache that never refreshed.
        self._ttl = (
            config.AUTH_JWKS_CACHE_SECONDS if ttl_seconds is None else ttl_seconds
        )
        self._fetcher = fetcher
        self._lock = threading.Lock()
        self._keys: dict[str, Any] = {}
        self._fetched_at = 0.0

    @property
    def url(self) -> str:
        return f"{self.base_url}/api/auth/jwks"

    def _fetch(self) -> dict[str, Any]:
        if self._fetcher is not None:
            return self._fetcher(self.url)
        import requests

        response = requests.get(self.url, timeout=10)
        response.raise_for_status()
        return response.json()

    def _refresh(self) -> None:
        """Replace the cached keys. Never clears them on failure."""
        try:
            document = self._fetch()
        except Exception as exc:  # noqa: BLE001 - any transport failure is equal here
            logger.warning("JWKS refresh from %s failed: %s", self.url, exc)
            return

        import jwt

        keys: dict[str, Any] = {}
        for entry in document.get("keys", []) or []:
            kid = entry.get("kid")
            if not kid:
                continue
            try:
                keys[kid] = jwt.PyJWK(entry).key
            except Exception as exc:  # noqa: BLE001
                # One unusable key must not discard the usable ones beside it.
                logger.warning("skipping unusable JWKS entry %s: %s", kid, exc)

        if keys:
            self._keys = keys
            self._fetched_at = time.monotonic()

    def key_for(self, kid: str | None) -> Any:
        """Return the signing key for ``kid``, refreshing at most once."""
        if not kid:
            raise AuthError("token header carries no key id")

        with self._lock:
            expired = (time.monotonic() - self._fetched_at) > self._ttl
            if kid not in self._keys or expired:
                self._refresh()
            key = self._keys.get(kid)

        if key is None:
            raise AuthError("token was signed by an unknown key")
        return key


_cache_lock = threading.Lock()
_cache: JwksCache | None = None


def _shared_cache() -> JwksCache:
    global _cache
    with _cache_lock:
        wanted = config.AUTH_BASE_URL.rstrip("/")
        if not wanted:
            raise AuthError("no auth server is configured")
        if _cache is None or _cache.base_url != wanted:
            _cache = JwksCache(wanted)
        return _cache


def reset_jwks_cache() -> None:
    """Drop the process-wide cache. For tests, and after a config change."""
    global _cache
    with _cache_lock:
        _cache = None


def verify_token(token: str, *, cache: JwksCache | None = None) -> AuthenticatedUser:
    """Verify a Bearer token and return who it belongs to.

    Raises ``AuthError`` for every failure mode.
    """
    import jwt

    if not token:
        raise AuthError("no token supplied")

    resolved = cache or _shared_cache()

    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:  # noqa: BLE001
        raise AuthError("token header is not readable") from exc

    key = resolved.key_for(header.get("kid"))

    try:
        claims = jwt.decode(
            token,
            key=key,
            # An ALLOWLIST, not the token's own `alg` header. Trusting that
            # header is the classic JWT break: it lets an attacker present
            # `alg: none`, or sign with HMAC using the public key as the shared
            # secret, and be believed.
            algorithms=list(config.AUTH_JWT_ALGORITHMS),
            issuer=config.AUTH_BASE_URL,
            audience=config.AUTH_BASE_URL,
            leeway=config.AUTH_JWT_LEEWAY_SECONDS,
            options={
                "require": ["exp", "iss", "aud", "sub"],
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
                "verify_signature": True,
            },
        )
    except Exception as exc:  # noqa: BLE001
        # The reason is logged for an operator and withheld from the caller.
        logger.info("token rejected: %s", exc)
        raise AuthError("token is not valid") from exc

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise AuthError("token carries no subject")

    def _text(name: str) -> str | None:
        value = claims.get(name)
        return value if isinstance(value, str) and value else None

    return AuthenticatedUser(
        id=subject,
        email=_text("email"),
        name=_text("name"),
        image=_text("image"),
    )
