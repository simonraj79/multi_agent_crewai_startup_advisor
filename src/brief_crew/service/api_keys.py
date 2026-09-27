"""Personal API keys: run your published workflows from your own code (plan 22).

WHY THIS EXISTS
---------------
Every other credential this service accepts is a 15-minute Better Auth JWT
minted from a cookie on the SPA's origin, so the only client that could ever
drive Crew Studio was its own browser tab. A key is the long-lived,
revocable, per-person credential a backend, a cron job or a CI step can hold.

WHY A FAST HASH
---------------
The key's random part is 256 bits from `secrets`. A slow password hash exists
to make guessing a LOW-entropy secret expensive; nobody guesses 256 bits, so
bcrypt/argon2 would only add tens of milliseconds to every scripted request.
SHA-256 of the whole key, looked up by indexed equality, is the standard shape
(GitHub, Stripe) and it means the secret itself is never written anywhere.

WHAT A KEY MAY NOT DO
---------------------
A key resolves to its owner through the SAME `optional_user` chokepoint as a
session, so ownership, 404-not-403, the per-user rate limit and the spend cap
all apply unchanged. Three things are refused because a leaked key must not be
able to escalate: managing keys, the credential vault, and the admin console.
`require_session` is the gate for the first two; `auth.require_admin` refuses
`via == "api_key"` for the third.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import config
from .auth import AuthenticatedUser

__all__ = [
    "API_KEY_INVALID_DETAIL",
    "SESSION_REQUIRED_DETAIL",
    "create_account_router",
    "generate_api_key",
    "hash_api_key",
    "is_api_key",
    "resolve_api_key",
]

API_KEY_INVALID_DETAIL = "this API key is not valid or has been revoked"
SESSION_REQUIRED_DETAIL = (
    "API keys cannot manage API keys or credentials; sign in to the console"
)


def is_api_key(token: str | None) -> bool:
    """Whether a bearer credential is shaped like one of our keys."""

    return bool(token) and token.startswith(config.API_KEY_PREFIX)


def hash_api_key(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return `(secret, secret_hash, display_prefix)` for a fresh key."""

    secret = config.API_KEY_PREFIX + secrets.token_urlsafe(config.API_KEY_SECRET_BYTES)
    return secret, hash_api_key(secret), secret[: config.API_KEY_DISPLAY_CHARS]


def resolve_api_key(persistence: Any, token: str) -> AuthenticatedUser | None:
    """The owner of a live key, or None for an unknown or revoked one.

    Stamps `last_used_at` at most once per interval. A failure to stamp is
    swallowed: bookkeeping must never refuse a request the key is good for.
    """

    if persistence is None or not is_api_key(token):
        return None
    # Bounded before hashing: a megabyte "key" is refused, not digested.
    if len(token) > len(config.API_KEY_PREFIX) + 4 * config.API_KEY_SECRET_BYTES:
        return None
    row = persistence.resolve_api_key(hash_api_key(token))
    if row is None:
        return None
    try:
        persistence.touch_api_key(
            row["id"], min_interval_seconds=config.API_KEY_LAST_USED_WRITE_SECONDS
        )
    except Exception:  # noqa: BLE001 - see docstring
        pass
    return AuthenticatedUser(
        id=row["user_id"],
        email=row.get("user_email"),
        name=row.get("user_name"),
        via="api_key",
        api_key_id=row["id"],
    )


class CreateApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=config.API_KEY_NAME_MAX_CHARS)

    @field_validator("name")
    @classmethod
    def _clean(cls, value: str) -> str:
        # Control characters stripped (a NUL is a 500 on PostgreSQL - gotcha
        # 86), then trimmed; a name that was only whitespace is refused.
        cleaned = "".join(ch for ch in value if ch.isprintable()).strip()
        if not cleaned:
            raise ValueError("name must contain a visible character")
        return cleaned


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "prefix": row["prefix"],
        "created_at": _iso(row["created_at"]),
        "last_used_at": _iso(row["last_used_at"]),
    }


def create_account_router(
    *,
    current_user: Callable[..., AuthenticatedUser | None],
    require_user: Callable[[AuthenticatedUser | None], AuthenticatedUser],
    persistence_factory: Callable[[], Any],
) -> APIRouter:
    """`/api/account/*`. Every handler is a sync `def` (gotcha 91)."""

    router = APIRouter(prefix="/api/account", tags=["account"])

    def _store() -> Any:
        persistence = persistence_factory()
        if persistence is None:
            raise HTTPException(
                status_code=503, detail="this deployment has no storage for API keys"
            )
        return persistence

    def _session(user: AuthenticatedUser | None) -> AuthenticatedUser:
        resolved = require_user(user)
        if resolved.via != "session":
            raise HTTPException(status_code=403, detail=SESSION_REQUIRED_DETAIL)
        return resolved

    @router.get("/whoami")
    def whoami(user: AuthenticatedUser | None = Depends(current_user)) -> dict[str, Any]:
        """The one route a script calls to check its key works."""

        resolved = require_user(user)
        return {
            "id": resolved.id,
            "email": resolved.email,
            "name": resolved.name,
            "via": resolved.via,
        }

    @router.get("/api-keys")
    def list_keys(user: AuthenticatedUser | None = Depends(current_user)) -> dict[str, Any]:
        owner = _session(user)
        rows = _store().list_api_keys(owner.id)
        return {
            "keys": [_public(row) for row in rows],
            "limit": config.MAX_API_KEYS_PER_USER,
        }

    @router.post("/api-keys", status_code=201)
    def create_key(
        request: CreateApiKeyRequest,
        user: AuthenticatedUser | None = Depends(current_user),
    ) -> dict[str, Any]:
        owner = _session(user)
        secret, secret_hash, prefix = generate_api_key()
        row = _store().create_api_key(
            key_id="key_" + secrets.token_hex(12),
            user_id=owner.id,
            name=request.name,
            prefix=prefix,
            secret_hash=secret_hash,
            user_email=owner.email,
            user_name=owner.name,
            max_active=config.MAX_API_KEYS_PER_USER,
        )
        if row is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"you already have {config.MAX_API_KEYS_PER_USER} API keys; "
                    "revoke one before creating another"
                ),
            )
        # The ONLY response that ever carries the secret.
        return {"key": _public(row), "secret": secret}

    @router.delete("/api-keys/{key_id}", status_code=204)
    def revoke_key(
        key_id: str, user: AuthenticatedUser | None = Depends(current_user)
    ) -> Response:
        owner = _session(user)
        if not _store().revoke_api_key(owner.id, key_id):
            raise HTTPException(status_code=404, detail="API key not found")
        return Response(status_code=204)

    return router
