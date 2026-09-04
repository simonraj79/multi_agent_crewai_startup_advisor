"""The credential vault: AES-256-GCM rows, resolved for the run's owner only.

Plan 01 D3-D5 and D7. This is the only module that sees a plaintext secret
outside a tool or `LLM(...)` constructor, and it is written so that reading it
is enough to audit that claim: nothing here logs, prints, or puts a field value
into an exception message. `git grep -n "api_key\\|token" -- src/brief_crew/service/credentials.py`
is plan 01's review item 13 and should keep answering with names only.

**The cipher, and what the associated data is for.** AES-256-GCM from
`cryptography`, a fresh 12-byte random nonce on every write, and the row's own
`(id, user_id)` bound in as associated data. That last part is what makes the
database's own integrity irrelevant to the answer: a ciphertext copied under
another user's id, or under another credential id, fails to authenticate and
decrypts to nothing rather than to somebody else's key. Flowise's primitive -
`crypto-js` `AES.encrypt(json, passphrase)`, OpenSSL's KDF, CBC, no tag
(`docs/flowise-notes.md` section 4) - has none of these properties, and its
shape (plaintext label beside encrypted data, never returned to the client) is
the part worth keeping.

**Where the key comes from.** `config.CREDENTIALS_MASTER_KEY`, base64 of 32
random bytes, read there and nowhere else so the section 6 scan finds it. A
malformed value is refused with a sentence naming the knob and the command that
mints a good one; an EMPTY value is "no vault": `CredentialStore.configured` is
false, the routes answer 503, and the boot check in `service/app.py` refuses
to start only when authentication is on - because a deployment that can sign
people in and cannot keep their keys is misconfigured, while a bare checkout
running `SYNTHETIC=1` is merely keyless.

**Resolution is scoped, not looked up.** `resolve_credential(credential_id)`
takes no user and no store: both come from ContextVars that
`service/builder_runner.py` sets around `kickoff` and `resume`, exactly as
`builder_cancellation` scopes the cancel flag. A compiled definition carries
ids only (C5), so the only path from an id to a key runs through the run's
OWNER, and an unowned run resolves nothing at all. Absent and foreign are one
exception, `CredentialNotYours`, for the reason every 404 in this service
gives: a distinguishable refusal is an oracle for other people's ids.

**The postgres probe dials public hosts only, and decides that before it
dials.** `POST /{id}/test` on a `postgres` row used to run `SELECT 1` against
whatever DSN a signed-in user had stored - and a signed-in user is not a
trusted one. "Whatever DSN" includes `127.0.0.1:5432` (this service's own
database), `10.x` (anything on the deployment's private network),
`169.254.169.254` (the cloud metadata endpoint) and any hostname that resolves
to one of those: server-side request forgery with a five-second timeout and a
friendly sentence back, one credential at a time. `postgres_probe_target`
parses the DSN with libpq's own rules, classifies every host it names as
loopback, link-local, private or otherwise non-public, refuses on the first
hit, and pins `hostaddr` to the addresses it vetted so libpq dials exactly
what was checked rather than resolving the name a second time.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import json
import re
import secrets
import socket
from types import MappingProxyType
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from brief_crew import config
from brief_crew.events.redaction import REDACTED
from brief_crew.service.persistence import (
    PostgresFlowPersistence,
    identifier,
    user_credentials,
    utcnow,
)

__all__ = [
    "associated_data",
    "credential_scope",
    "CredentialInvalid",
    "CredentialLabelTaken",
    "CredentialNotYours",
    "CredentialStore",
    "CredentialSummary",
    "CredentialTooLarge",
    "CredentialUndecryptable",
    "CURRENT_KEY_VERSION",
    "current_run_user",
    "decrypt_fields",
    "encrypt_fields",
    "EncryptedFields",
    "HostResolver",
    "load_master_key",
    "MasterKey",
    "MasterKeyInvalid",
    "normalize_fields",
    "parse_master_key",
    "POSTGRES_PROBE_REFUSAL",
    "postgres_probe_target",
    "probe_credential",
    "ProbeResult",
    "resolve_credential",
    "ResolvedCredential",
    "VaultError",
    "VaultUnavailable",
]

#: AES-GCM's standard nonce. 96 bits, random per write: at 2^32 writes under one
#: key the birthday bound is ~2^-32, which is far past any row count this table
#: will see, and a counter would need durable state that a two-process
#: deployment cannot share.
NONCE_BYTES = 12
KEY_BYTES = 32
#: The version every row written by this build carries. A re-encrypt pass under
#: a new key bumps this and keeps the old key readable until it is done.
CURRENT_KEY_VERSION = 1

# Owned by config.py (S1 ruling 3) and re-exported here under the names
# the routes and the tests import. Values and reasoning live there.
VAULT_NOT_CONFIGURED_DETAIL = config.VAULT_NOT_CONFIGURED_DETAIL
CREDENTIAL_PROBE_TIMEOUT_SECONDS = config.CREDENTIAL_PROBE_TIMEOUT_SECONDS
OPENROUTER_KEY_PROBE_URL = config.OPENROUTER_KEY_PROBE_URL
GITHUB_RATE_LIMIT_PROBE_URL = config.GITHUB_RATE_LIMIT_PROBE_URL
MAX_CREDENTIAL_LABEL_CHARS = config.MAX_CREDENTIAL_LABEL_CHARS

_CREDENTIAL_ID = re.compile(config.CREDENTIAL_ID_PATTERN)
#: RFC 9110 `token` characters: what an HTTP header NAME may contain.
_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
_MINT_ATTEMPTS = 4


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------
class VaultError(RuntimeError):
    """Base for every refusal the vault makes. Never carries a field value."""


class VaultUnavailable(VaultError):
    """No master key: the routes answer 503 and a run cannot resolve anything."""

    def __init__(self, detail: str = VAULT_NOT_CONFIGURED_DETAIL) -> None:
        super().__init__(detail)


class MasterKeyInvalid(VaultError):
    """`CREDENTIALS_MASTER_KEY` is set and not base64 of 32 bytes."""


class CredentialNotYours(VaultError, LookupError):
    """The id names no row this caller may use - absent or somebody else's.

    One class for both causes, on purpose. At the API it is a 404; at run time
    it is the `node_error` frame's `error_class` (C6), read off the attribute
    below by `events/serializer.py::error_class_of` so that module never has to
    import this one.
    """

    error_class = "credential-not-yours"

    def __init__(self, credential_id: str) -> None:
        super().__init__(f"credential {credential_id} is not one of yours")
        self.credential_id = credential_id


class CredentialInvalid(VaultError, ValueError):
    """An unknown kind, a missing or extra field, a bad label: 422."""


class CredentialTooLarge(VaultError):
    """The fields JSON is over `MAX_CREDENTIAL_BYTES`: 413."""


class CredentialLabelTaken(VaultError):
    """This user already has a credential under that label: 409.

    The unique constraint is `(user_id, label)` (15 D6), and the label is the
    only thing a picker shows, so two rows with one label would be two rows the
    author cannot tell apart.
    """


class CredentialUndecryptable(VaultError):
    """A row exists and does not authenticate under this master key.

    Either the master key changed without a re-encrypt pass, the row carries a
    key version this deployment no longer holds, or its `id` / `user_id` were
    edited underneath it. All three are operator problems rather than caller
    problems, so this is deliberately NOT `CredentialNotYours`: a 404 here would
    send the author to recreate a credential that the deployment, not the
    author, has lost.
    """


# --------------------------------------------------------------------------
# The key
# --------------------------------------------------------------------------
class MasterKey:
    """Every key version this deployment can read, and the one it writes."""

    __slots__ = ("_keys", "version")

    def __init__(self, key: bytes, *, version: int = CURRENT_KEY_VERSION) -> None:
        if len(key) != KEY_BYTES:
            raise MasterKeyInvalid(f"a master key is exactly {KEY_BYTES} bytes")
        self._keys: dict[int, bytes] = {int(version): bytes(key)}
        self.version = int(version)

    def cipher(self, key_version: int) -> AESGCM:
        key = self._keys.get(int(key_version))
        if key is None:
            raise CredentialUndecryptable(
                f"key version {key_version} is not held by this deployment; "
                f"it writes version {self.version}"
            )
        return AESGCM(key)

    @property
    def versions(self) -> tuple[int, ...]:
        return tuple(sorted(self._keys))

    def __repr__(self) -> str:  # never the bytes
        return f"MasterKey(versions={list(self.versions)})"


def _mint_hint(name: str) -> str:
    return (
        f"{name} must be base64 of exactly {KEY_BYTES} random bytes; mint one with "
        "python -c \"import base64, secrets; "
        f"print(base64.b64encode(secrets.token_bytes({KEY_BYTES})).decode())\""
    )


def parse_master_key(raw: str, *, name: str = "CREDENTIALS_MASTER_KEY") -> MasterKey:
    """Strict base64, exactly 32 bytes, or a sentence naming the knob."""

    try:
        decoded = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MasterKeyInvalid(f"{name} is not valid base64. {_mint_hint(name)}") from exc
    if len(decoded) != KEY_BYTES:
        raise MasterKeyInvalid(
            f"{name} decodes to {len(decoded)} bytes, not {KEY_BYTES}. {_mint_hint(name)}"
        )
    return MasterKey(decoded)


def load_master_key(raw: str | None = None) -> MasterKey | None:
    """The configured key, or None when the knob is empty. Malformed raises."""

    value = (config.CREDENTIALS_MASTER_KEY if raw is None else raw).strip()
    if not value:
        return None
    return parse_master_key(value)


# --------------------------------------------------------------------------
# The cipher
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EncryptedFields:
    ciphertext: bytes
    nonce: bytes
    key_version: int


def associated_data(credential_id: str, user_id: str) -> bytes:
    """What the tag commits to besides the plaintext: this row, this owner.

    NUL-separated because neither id may contain one, so the pair is
    unambiguous - `cr_1` + `2x` and `cr_12` + `x` are different byte strings.
    """

    return f"{credential_id}\x00{user_id}".encode("utf-8")


def _serialize_fields(fields: Mapping[str, str]) -> bytes:
    return json.dumps(dict(fields), sort_keys=True, separators=(",", ":")).encode("utf-8")


def encrypt_fields(
    key: MasterKey, *, credential_id: str, user_id: str, fields: Mapping[str, str]
) -> EncryptedFields:
    plaintext = _serialize_fields(fields)
    if len(plaintext) > config.MAX_CREDENTIAL_BYTES:
        raise CredentialTooLarge(
            f"a credential is limited to {config.MAX_CREDENTIAL_BYTES} bytes of fields; "
            f"this one is {len(plaintext)}"
        )
    nonce = secrets.token_bytes(NONCE_BYTES)
    ciphertext = key.cipher(key.version).encrypt(
        nonce, plaintext, associated_data(credential_id, user_id)
    )
    return EncryptedFields(ciphertext=ciphertext, nonce=nonce, key_version=key.version)


def decrypt_fields(
    key: MasterKey,
    *,
    credential_id: str,
    user_id: str,
    ciphertext: bytes,
    nonce: bytes,
    key_version: int,
) -> dict[str, str]:
    if len(nonce) != NONCE_BYTES:
        raise CredentialUndecryptable(
            f"credential {credential_id} carries a {len(nonce)}-byte nonce; "
            f"this vault writes {NONCE_BYTES}"
        )
    try:
        plaintext = key.cipher(key_version).decrypt(
            bytes(nonce), bytes(ciphertext), associated_data(credential_id, user_id)
        )
    except InvalidTag as exc:
        raise CredentialUndecryptable(
            f"credential {credential_id} does not authenticate under key version "
            f"{key_version} for this owner; the row was re-labelled or "
            "CREDENTIALS_MASTER_KEY changed without a re-encrypt pass"
        ) from exc
    decoded = json.loads(plaintext.decode("utf-8"))
    if not isinstance(decoded, dict) or not all(
        isinstance(name, str) and isinstance(value, str) for name, value in decoded.items()
    ):
        raise CredentialUndecryptable(
            f"credential {credential_id} decrypted to something other than a "
            "string-to-string object"
        )
    return decoded


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True, repr=False)
class ResolvedCredential:
    """What a constructor is handed and then drops. `repr` hides the fields."""

    kind: str
    fields: Mapping[str, str]

    def __repr__(self) -> str:
        return f"ResolvedCredential(kind={self.kind!r}, fields=<{len(self.fields)} {REDACTED}>)"

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class CredentialSummary:
    """Everything the API ever returns about a row. No field is ever here."""

    id: str
    user_id: str
    kind: str
    label: str
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None

    def as_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_used_at": self.last_used_at,
        }


def normalize_fields(kind: str, fields: Any) -> dict[str, str]:
    """The fields a `kind` requires, exactly, or a refusal naming the FIELD.

    Values are kept verbatim - a key is not ours to trim - except that a line
    break or NUL is refused, because every consumer puts these into an HTTP
    header, a connection string or a constructor argument, and a value that
    cannot go there is a value that will fail at the first paid node instead.
    """

    if kind not in config.CREDENTIAL_KINDS:
        raise CredentialInvalid(
            f"unknown credential kind {kind!r}; the kinds are "
            f"{', '.join(sorted(config.CREDENTIAL_KINDS))}"
        )
    if not isinstance(fields, Mapping):
        raise CredentialInvalid("fields must be an object of field name to value")
    required = config.CREDENTIAL_FIELDS[kind]
    for name in required:
        if name not in fields:
            raise CredentialInvalid(f"a {kind} credential needs the field {name}")
    for name in fields:
        if name not in required:
            raise CredentialInvalid(
                f"a {kind} credential has no field {name!s}; it takes {', '.join(required)}"
            )
    for name in required:
        value = fields[name]
        if not isinstance(value, str):
            raise CredentialInvalid(f"the field {name} must be a string")
        if not value.strip():
            raise CredentialInvalid(f"the field {name} is empty")
        if any(character in value for character in "\r\n\x00"):
            raise CredentialInvalid(f"the field {name} contains a line break or NUL")
    return {name: fields[name] for name in required}


def _checked_label(label: Any) -> str:
    rendered = str(label).strip() if label is not None else ""
    if not rendered:
        raise CredentialInvalid("label must not be empty")
    if len(rendered) > MAX_CREDENTIAL_LABEL_CHARS:
        raise CredentialInvalid(
            f"label is limited to {MAX_CREDENTIAL_LABEL_CHARS} characters; "
            f"this one is {len(rendered)}"
        )
    return rendered


def _checked_user(user_id: Any) -> str:
    if not user_id:
        raise CredentialInvalid("a credential needs an owner")
    return identifier(user_id, label="user_id")


def _aware(value: datetime | None) -> datetime | None:
    """A row's timestamp as the aware UTC instant it was written as.

    `DateTime(timezone=True)` is a request SQLite cannot honour: it stores the
    text and hands back a NAIVE datetime, so a row read back serialised
    without the `Z` that the create response - built from `utcnow()` - had
    carried, and a client comparing the two saw two different instants for one
    write. Every timestamp this module writes is UTC, so a naive one is UTC.
    """

    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def new_credential_id() -> str:
    """`cr_` + 8 hex, minted like `ug_` document ids (`store.py::new_document_id`)."""

    return f"cr_{secrets.token_hex(4)}"


# --------------------------------------------------------------------------
# The store
# --------------------------------------------------------------------------
_UNSET = object()


class CredentialStore:
    """Read and write `user_credentials` on the service's own engine.

    Takes the `PostgresFlowPersistence` rather than an engine, for the reason
    `BuilderDocumentStore` gives: on in-memory SQLite the database exists only
    as long as its one connection does, and that store's guard is what stops
    two threads sharing one transaction.

    Every read that names a row is scoped `WHERE user_id = :caller` in SQL
    (01 D2, rule 2), so a bug in the layer above cannot leak a row that was
    never selected, and a miss - absent or foreign - is one exception.
    """

    __slots__ = ("_key", "_store")

    def __init__(
        self, store: PostgresFlowPersistence, *, master_key: Any = _UNSET
    ) -> None:
        self._store = store
        self._key: MasterKey | None = (
            load_master_key() if master_key is _UNSET else master_key
        )

    @property
    def configured(self) -> bool:
        return self._key is not None

    def _require_key(self) -> MasterKey:
        if self._key is None:
            raise VaultUnavailable()
        return self._key

    @staticmethod
    def _summary(row: Mapping[str, Any]) -> CredentialSummary:
        return CredentialSummary(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            kind=str(row["kind"]),
            label=str(row["label"]),
            created_at=_aware(row["created_at"]),
            updated_at=_aware(row["updated_at"]),
            last_used_at=_aware(row["last_used_at"]),
        )

    @staticmethod
    def _owned(user_id: str, credential_id: str) -> Any:
        return (user_credentials.c.id == credential_id) & (
            user_credentials.c.user_id == user_id
        )

    # ----------------------------------------------------------------- write
    def create(
        self, user_id: str, *, kind: str, label: Any, fields: Any
    ) -> CredentialSummary:
        key = self._require_key()
        owner = _checked_user(user_id)
        clean_label = _checked_label(label)
        clean_fields = normalize_fields(kind, fields)
        now = utcnow()
        for attempt in range(_MINT_ATTEMPTS):
            credential_id = new_credential_id()
            sealed = encrypt_fields(
                key, credential_id=credential_id, user_id=owner, fields=clean_fields
            )
            try:
                with self._store.begin() as connection:
                    taken = connection.execute(
                        select(user_credentials.c.id).where(
                            user_credentials.c.user_id == owner,
                            user_credentials.c.label == clean_label,
                        )
                    ).first()
                    if taken is not None:
                        raise CredentialLabelTaken(
                            f"you already have a credential labelled {clean_label!r}"
                        )
                    connection.execute(
                        insert(user_credentials).values(
                            id=credential_id,
                            user_id=owner,
                            kind=kind,
                            label=clean_label,
                            ciphertext=sealed.ciphertext,
                            nonce=sealed.nonce,
                            key_version=sealed.key_version,
                            created_at=now,
                            updated_at=now,
                            last_used_at=None,
                        )
                    )
            except IntegrityError:
                # Either the label raced another writer between the select and
                # the insert, or eight hex characters collided. The second is
                # 2^-32 per attempt; the first is what the constraint is for.
                if attempt + 1 == _MINT_ATTEMPTS:
                    raise CredentialLabelTaken(
                        f"you already have a credential labelled {clean_label!r}"
                    ) from None
                continue
            return CredentialSummary(
                id=credential_id,
                user_id=owner,
                kind=kind,
                label=clean_label,
                created_at=now,
                updated_at=now,
                last_used_at=None,
            )
        raise VaultError("could not mint a credential id")  # pragma: no cover

    def delete(self, user_id: str, credential_id: str) -> None:
        owner = _checked_user(user_id)
        if not _CREDENTIAL_ID.match(str(credential_id)):
            raise CredentialNotYours(str(credential_id))
        with self._store.begin() as connection:
            result = connection.execute(
                delete(user_credentials).where(self._owned(owner, credential_id))
            )
        if result.rowcount != 1:
            raise CredentialNotYours(credential_id)

    # ------------------------------------------------------------------ read
    def list(self, user_id: str) -> list[CredentialSummary]:
        owner = _checked_user(user_id)
        with self._store.connect() as connection:
            rows = connection.execute(
                select(user_credentials)
                .where(user_credentials.c.user_id == owner)
                .order_by(user_credentials.c.updated_at.desc(), user_credentials.c.id)
            ).mappings().all()
        return [self._summary(row) for row in rows]

    def _row(self, user_id: str, credential_id: str) -> Mapping[str, Any]:
        owner = _checked_user(user_id)
        if not _CREDENTIAL_ID.match(str(credential_id)):
            raise CredentialNotYours(str(credential_id))
        with self._store.connect() as connection:
            row = connection.execute(
                select(user_credentials).where(self._owned(owner, credential_id))
            ).mappings().one_or_none()
        if row is None:
            raise CredentialNotYours(credential_id)
        return row

    def get(self, user_id: str, credential_id: str) -> CredentialSummary:
        return self._summary(self._row(user_id, credential_id))

    def exists(self, user_id: str | None, credential_id: str) -> bool:
        """The predicate `validate` and `publish` check a document with."""

        if not user_id:
            return False
        try:
            self._row(user_id, credential_id)
        except CredentialNotYours:
            return False
        return True

    def resolve(
        self, user_id: str, credential_id: str, *, touch: bool = True
    ) -> ResolvedCredential:
        """Decrypt one row for its owner, recording the use.

        `touch=False` is for the probe, which is the author checking a key
        rather than a run spending it; `last_used_at` answers "when did a run
        last need this", and a probe would make every row look freshly used.
        """

        key = self._require_key()
        row = self._row(user_id, credential_id)
        fields = decrypt_fields(
            key,
            credential_id=str(row["id"]),
            user_id=str(row["user_id"]),
            ciphertext=row["ciphertext"],
            nonce=row["nonce"],
            key_version=int(row["key_version"]),
        )
        if touch:
            with self._store.begin() as connection:
                connection.execute(
                    update(user_credentials)
                    .where(self._owned(str(row["user_id"]), str(row["id"])))
                    .values(last_used_at=utcnow())
                )
        return ResolvedCredential(kind=str(row["kind"]), fields=MappingProxyType(fields))


# --------------------------------------------------------------------------
# Run-time resolution - scoped by the runner, called from an entrypoint
# --------------------------------------------------------------------------
#: The owner of the run executing on this thread and everything it spawns, set
#: by `service/builder_runner.py` around `kickoff` and `resume`. CrewAI copies
#: the context into every worker it starts, so a parallel branch resolves
#: against the same owner without being handed it.
current_run_user: ContextVar[str | None] = ContextVar(
    "brief_crew_current_run_user", default=None
)
_current_store: ContextVar[CredentialStore | None] = ContextVar(
    "brief_crew_credential_store", default=None
)


@contextmanager
def credential_scope(*, user_id: str | None, persistence: Any) -> Iterator[None]:
    """Scope one run's owner and vault over everything this thread starts.

    `persistence` is whatever the execution carried. Only the service's own
    store can back a vault; a bare CrewAI `SQLiteFlowPersistence` - which the
    runner tests hand in - scopes an owner with no store, and a resolve under
    it is `VaultUnavailable` rather than a stray table on a file nobody chose.
    """

    store = (
        CredentialStore(persistence)
        if isinstance(persistence, PostgresFlowPersistence)
        else None
    )
    user_token = current_run_user.set(user_id)
    store_token = _current_store.set(store)
    try:
        yield
    finally:
        _current_store.reset(store_token)
        current_run_user.reset(user_token)


def resolve_credential(credential_id: str) -> ResolvedCredential:
    """One row, for the run's owner, decrypted, `last_used_at` written.

    Raises `CredentialNotYours` for absent AND foreign - and for an unowned run,
    because every credential has an owner and a run with none can own nothing.
    Raises `VaultUnavailable` when no vault is in scope or none is configured.
    """

    store = _current_store.get()
    if store is None:
        raise VaultUnavailable(
            "no credential vault is in scope; credentials resolve only inside a "
            "builder run the service started"
        )
    user_id = current_run_user.get()
    if not user_id:
        raise CredentialNotYours(str(credential_id))
    return store.resolve(user_id, str(credential_id))


# --------------------------------------------------------------------------
# Probes - plan 01 D4
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ProbeResult:
    ok: bool
    detail: str


#: `(url, headers, timeout_seconds) -> (status, body_text)`. Injectable so a
#: test never reaches the network; the default is `requests`, which
#: `service/auth.py` already depends on for JWKS.
HttpGet = Callable[[str, Mapping[str, str], float], tuple[int, str]]
#: `(dsn, timeout_seconds) -> None`, raising on failure.
SqlPing = Callable[[str, float], None]
#: `(host) -> [address, ...]`: what a name resolves to. Injectable so a test
#: never touches DNS; the default is `socket.getaddrinfo`.
HostResolver = Callable[[str], list[str]]

#: The first clause of every refusal the postgres probe writes. The second
#: clause names the host and its class, never the DSN.
POSTGRES_PROBE_REFUSAL = "the postgres probe dials public database hosts only"


def _default_http_get(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, str]:
    import requests

    response = requests.get(url, headers=dict(headers), timeout=timeout)
    return response.status_code, response.text[:4096]


def _default_sql_ping(dsn: str, timeout: float) -> None:
    import psycopg

    # `connect_timeout` is libpq's own parameter, forwarded through **kwargs.
    with psycopg.connect(dsn, connect_timeout=max(1, int(timeout))) as connection:
        connection.execute("SELECT 1")


def _default_resolve_host(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    # `%scope` on a link-local IPv6 answer is not part of the address.
    return sorted({str(info[4][0]).split("%", 1)[0] for info in infos})


def _address_class(address: str) -> str | None:
    """None for a public address; else the class named in the refusal.

    Order matters, because `ipaddress` overlaps its predicates: `127.0.0.1`
    and `169.254.169.254` are both `is_private` in Python 3.13, and `0.0.0.0`
    is both unspecified and private. The more specific word wins so the
    sentence an author reads says what the address actually is. An
    IPv4-mapped IPv6 address (`::ffff:10.0.0.5`) is classified as the IPv4
    address it carries.
    """

    ip = ipaddress.ip_address(address)
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return "non-public"
    if ip.is_private:
        return "private"
    if not ip.is_global:
        return "non-public"
    return None


def _refuse(host: str, why: str) -> str:
    return f"{POSTGRES_PROBE_REFUSAL}; {host[:80]!r} {why}"


def postgres_probe_target(dsn: str, resolve: HostResolver) -> tuple[str | None, str]:
    """Vet every host a DSN names BEFORE anything dials it.

    Returns `(refusal, target)`. `refusal` is a sentence when any host is
    loopback, link-local, private or otherwise non-public - or when the DSN
    names no host at all (libpq would then dial a local socket), names a Unix
    socket path, cannot be parsed, or names something DNS cannot resolve -
    and None when every host is public. `target` is then the DSN with
    `hostaddr` pinned to the addresses that were vetted, one per host in
    libpq's positional pairing, so the dial cannot land somewhere the check
    did not look (a name that answered one address here and another to libpq
    a moment later). A DSN that already carries `hostaddr` is vetted on those
    literals and dialled unchanged.

    Never raises for a malformed DSN: this runs on a request path, and an
    author's typo is a refusal, not a 500. The sentence names the host the
    author typed and its class; it never carries the DSN, so the password in
    it stays where it was.
    """

    try:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        params = conninfo_to_dict(dsn)
    except Exception:  # noqa: BLE001 - psycopg's own ProgrammingError, or an import failure
        return f"{POSTGRES_PROBE_REFUSAL}; this DSN could not be parsed", dsn

    hostaddr = str(params.get("hostaddr") or "")
    if hostaddr:
        for literal in hostaddr.split(","):
            literal = literal.strip()
            try:
                cls = _address_class(literal)
            except ValueError:
                return _refuse(literal, "is not an IP address"), dsn
            if cls is not None:
                return _refuse(literal, f"is a {cls} address"), dsn
        return None, dsn

    hosts = [host.strip() for host in str(params.get("host") or "").split(",")]
    if not any(hosts):
        return (
            f"{POSTGRES_PROBE_REFUSAL}; this DSN names no host, so libpq would dial a local socket",
            dsn,
        )
    pinned: list[str] = []
    for host in hosts:
        if not host:
            return f"{POSTGRES_PROBE_REFUSAL}; one of the hosts in this DSN is empty", dsn
        if host.startswith("/") or host.startswith("@"):
            return _refuse(host, "is a Unix socket path"), dsn
        lowered = host.lower().rstrip(".")
        if lowered == "localhost" or lowered.endswith(".localhost"):
            return _refuse(host, "is loopback"), dsn
        try:
            addresses = [str(ipaddress.ip_address(host))]
            literal = True
        except ValueError:
            literal = False
            try:
                addresses = list(resolve(host))
            except (OSError, ValueError):
                addresses = []
            if not addresses:
                return _refuse(host, "could not be resolved"), dsn
        for address in addresses:
            try:
                cls = _address_class(address)
            except ValueError:
                return _refuse(host, "resolved to something that is not an IP address"), dsn
            if cls is not None:
                verb = "is" if literal else "resolves to"
                return _refuse(host, f"{verb} a {cls} address"), dsn
        pinned.append(addresses[0])
    return None, make_conninfo(dsn, hostaddr=",".join(pinned))


def _scrub(text: str, fields: Mapping[str, str]) -> str:
    """A provider's sentence with every field value blanked, bounded."""

    rendered = str(text)
    for value in fields.values():
        if value:
            rendered = rendered.replace(value, REDACTED)
    return rendered.strip()[:300]


def _provider_sentence(body: str) -> str:
    """`error.message` or `message` out of a JSON body, else the body's start."""

    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return body.strip()[:200]
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(error, str):
            return error
        if isinstance(parsed.get("message"), str):
            return parsed["message"]
    return body.strip()[:200]


def _http_probe(
    provider: str,
    url: str,
    headers: Mapping[str, str],
    fields: Mapping[str, str],
    http_get: HttpGet,
    noun: str,
) -> ProbeResult:
    try:
        status, body = http_get(url, headers, CREDENTIAL_PROBE_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - any transport failure is equal here
        # The class name and nothing else: a transport error's text can carry
        # the URL, and a URL is not a secret, but a sentence is what the
        # author gets and a traceback is not.
        return ProbeResult(False, f"could not reach {provider}: {type(exc).__name__}")
    if 200 <= status < 300:
        return ProbeResult(True, f"{provider} accepted this {noun}")
    sentence = _scrub(_provider_sentence(body), fields)
    if status in (401, 403):
        detail = f"{provider} rejected this {noun} (HTTP {status})"
    else:
        detail = f"{provider} answered HTTP {status}"
    return ProbeResult(False, f"{detail}: {sentence}" if sentence else detail)


def _format_only(kind: str, fields: Mapping[str, str], why: str) -> ProbeResult:
    if kind in ("http_header", "mcp_header"):
        if not _HEADER_NAME.match(fields.get("name", "")):
            return ProbeResult(False, "the header name is not a valid HTTP field name")
    return ProbeResult(True, f"format looks right; {why}")


def probe_credential(
    kind: str,
    fields: Mapping[str, str],
    *,
    http_get: HttpGet | None = None,
    sql_ping: SqlPing | None = None,
    resolve_host: HostResolver | None = None,
) -> ProbeResult:
    """Ask the provider whether this credential works, where a free call exists.

    Plan 01 D4's table. Three kinds have a free authenticated read and are
    asked; every other kind is a format check, and `detail` SAYS it was only a
    format check, so an author is never told a key works when nothing tried it.
    The serper / tavily / exa / brave probes arrive with the web-search tool
    (plan 06) and are format checks until then.
    """

    get = http_get or _default_http_get
    ping = sql_ping or _default_sql_ping
    if kind == "openrouter":
        return _http_probe(
            "OpenRouter",
            OPENROUTER_KEY_PROBE_URL,
            {"Authorization": f"Bearer {fields['api_key']}"},
            fields,
            get,
            "key",
        )
    if kind == "github":
        return _http_probe(
            "GitHub",
            GITHUB_RATE_LIMIT_PROBE_URL,
            {
                "Authorization": f"Bearer {fields['token']}",
                "Accept": "application/vnd.github+json",
                # Required by GitHub, and `tools/github_feasibility.py` says so.
                "User-Agent": "brief-crew-credential-probe",
            },
            fields,
            get,
            "token",
        )
    if kind == "postgres":
        # Vetted BEFORE the dial, whatever `ping` is: an injected ping is a
        # test's, and the refusal must hold for it too.
        refusal, target = postgres_probe_target(
            fields["dsn"], resolve_host or _default_resolve_host
        )
        if refusal is not None:
            return ProbeResult(False, refusal)
        try:
            ping(target, CREDENTIAL_PROBE_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001
            scrubbed = _scrub(str(exc), {**fields, "target": target})
            return ProbeResult(False, f"SELECT 1 failed: {scrubbed or type(exc).__name__}")
        return ProbeResult(True, "SELECT 1 succeeded")
    if kind == "firecrawl":
        return _format_only(
            kind, fields, "Firecrawl has no free authenticated read, so this key was not sent anywhere"
        )
    if kind in ("serper", "tavily", "exa", "brave"):
        return _format_only(
            kind, fields, f"the {kind} probe arrives with the web-search tool, so this key was not sent anywhere"
        )
    if kind == "e2b":
        return _format_only(kind, fields, "nothing constructs from an e2b credential in this build")
    return _format_only(kind, fields, f"a {kind} credential has no probe; it was not sent anywhere")
