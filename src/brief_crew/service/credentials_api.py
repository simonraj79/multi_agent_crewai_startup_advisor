"""`/api/builder/credentials` - the vault's HTTP surface (plan 01 C4).

Four routes and a read, every one behind an identity, and none of them ever
returns a field: the list and the single-row read answer `{id, kind, label,
created_at, updated_at, last_used_at}`, a create answers the same shape, and
the probe answers `{ok, detail}`. What the author typed goes into the vault
and comes back out only inside `service/credentials.py::resolve_credential`,
for a run they own.

**The body is parsed by hand, and that is a security decision rather than a
style.** A pydantic request model would hand a malformed body to FastAPI's
default 422 handler, which echoes the offending INPUT back in the response -
and on this route the input is a key. `service/app.py` has no app-wide
`RequestValidationError` handler (its `_validation_detail` serves the
WebSocket only), so this module reads the JSON itself and every refusal names a
field, never a value.

**Vault before identity.** With authentication on, `create_app` refuses to
start without a master key, so the order cannot be observed there. With it
off, an anonymous caller on a keyless deployment gets the 503 that says the
feature is not configured, rather than a 401 that suggests signing in would
help (01 D3). The 401 is still the one `require_user` writes, so the
`WWW-Authenticate: Bearer` header and the sentence are the same as on every
other owned route.

The probe is rate-limited under the RUN limiter's key for this user, because a
probe is a user-initiated call to a third party and the run limiter is the
one bucket that already means "spend per person".
"""

# NO `from __future__ import annotations` - the same reason `builder_api.py`
# gives: FastAPI resolves handler annotations against module globals, and
# `Request`, `Response` and `Depends` are imported inside the factory because
# FastAPI is an optional dependency.

from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from brief_crew.service.builder_api import BUILDER_API_PREFIX
from brief_crew.service.credentials import (
    CredentialInvalid,
    CredentialLabelTaken,
    CredentialNotYours,
    CredentialStore,
    CredentialSummary,
    CredentialTooLarge,
    CredentialUndecryptable,
    VaultUnavailable,
    probe_credential,
)

__all__ = [
    "CREDENTIALS_API_PREFIX",
    "CredentialModel",
    "ProbeModel",
    "create_credentials_router",
]

#: Under the builder prefix, so the body-size exemption `create_app` grants
#: that prefix applies, and so the client reaches it through the same
#: `authedFetch` path as every other builder call.
CREDENTIALS_API_PREFIX = f"{BUILDER_API_PREFIX}/credentials"


class CredentialModel(BaseModel):
    """The only shape a credential ever has on the wire."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    label: str
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None

    @classmethod
    def of(cls, summary: CredentialSummary) -> "CredentialModel":
        return cls(**summary.as_public())


class ProbeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    detail: str


def _retry_after(seconds: float) -> dict[str, str]:
    """Whole seconds, never 0 - the arithmetic `app._retry_after_header` uses."""

    return {"Retry-After": str(max(1, int(seconds) + (1 if seconds % 1 else 0)))}


def create_credentials_router(
    *,
    store_factory: Callable[[], CredentialStore | None],
    current_user: Callable[..., Any],
    require_user: Callable[[Any], Any],
    rate_limiter: Any,
    limit_key: Callable[[Any], str],
) -> Any:
    """The router, closed over the app's own dependencies like the builder's.

    `store_factory` answers None when this service has no durable store, and a
    `CredentialStore` whose `configured` is False when it has a store and no
    master key; the two are different sentences to whoever is holding the
    browser and both are 503.
    """

    from fastapi import APIRouter, Depends, HTTPException, Request, Response

    router = APIRouter(prefix=CREDENTIALS_API_PREFIX, tags=["credentials"])

    def vault(user: Any = Depends(current_user)) -> tuple[CredentialStore, Any]:
        store = store_factory()
        if store is None:
            raise HTTPException(
                status_code=503,
                detail="this service has no durable store, so it cannot keep credentials",
            )
        if not store.configured:
            raise HTTPException(status_code=503, detail=str(VaultUnavailable()))
        return store, require_user(user)

    def guarded(action: Callable[[], Any]) -> Any:
        """Run a vault call, translating each refusal into its status.

        404 for absent and foreign alike - one exception class, one status,
        for the reason every 404 in this service gives.
        """

        try:
            return action()
        except CredentialNotYours as exc:
            raise HTTPException(status_code=404, detail="credential not found") from exc
        except CredentialLabelTaken as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CredentialTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except CredentialInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except VaultUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except CredentialUndecryptable as exc:
            # The deployment's fault, not the caller's: a 404 would send the
            # author off to recreate a row the operator lost.
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def json_object(request: Request) -> dict[str, Any]:
        """The body as a mapping, or a 422 that quotes nothing back."""

        try:
            payload = await request.json()
        except Exception as exc:  # noqa: BLE001 - any parse failure is equal here
            raise HTTPException(status_code=422, detail="body must be a JSON object") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="body must be a JSON object")
        return payload

    @router.get("", response_model=list[CredentialModel])
    async def list_credentials(
        scope: tuple[CredentialStore, Any] = Depends(vault),
    ) -> list[CredentialModel]:
        store, user = scope
        return [CredentialModel.of(row) for row in guarded(lambda: store.list(user.id))]

    @router.post("", response_model=CredentialModel, status_code=201)
    async def create_credential(
        request: Request,
        scope: tuple[CredentialStore, Any] = Depends(vault),
    ) -> CredentialModel:
        store, user = scope
        payload = await json_object(request)
        kind = payload.get("kind")
        if not isinstance(kind, str):
            raise HTTPException(status_code=422, detail="kind must be a string")
        if "fields" not in payload:
            raise HTTPException(status_code=422, detail="fields is required")
        created = guarded(
            lambda: store.create(
                user.id, kind=kind, label=payload.get("label"), fields=payload["fields"]
            )
        )
        return CredentialModel.of(created)

    @router.get("/{credential_id}", response_model=CredentialModel)
    async def get_credential(
        credential_id: str,
        scope: tuple[CredentialStore, Any] = Depends(vault),
    ) -> CredentialModel:
        store, user = scope
        return CredentialModel.of(guarded(lambda: store.get(user.id, credential_id)))

    @router.delete("/{credential_id}", status_code=204)
    async def delete_credential(
        credential_id: str,
        scope: tuple[CredentialStore, Any] = Depends(vault),
    ) -> Response:
        store, user = scope
        guarded(lambda: store.delete(user.id, credential_id))
        return Response(status_code=204)

    @router.post("/{credential_id}/test", response_model=ProbeModel)
    async def test_credential(
        credential_id: str,
        scope: tuple[CredentialStore, Any] = Depends(vault),
    ) -> ProbeModel:
        store, user = scope
        retry_after = rate_limiter.acquire(limit_key(user))
        if retry_after > 0:
            raise HTTPException(
                status_code=429,
                detail="too many credential checks; wait and try again",
                headers=_retry_after(retry_after),
            )
        # `touch=False`: the author checking a key is not a run using it.
        resolved = guarded(lambda: store.resolve(user.id, credential_id, touch=False))
        result = probe_credential(resolved.kind, resolved.fields)
        return ProbeModel(ok=result.ok, detail=result.detail)

    return router
