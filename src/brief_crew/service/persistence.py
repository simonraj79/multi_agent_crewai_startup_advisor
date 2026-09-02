"""SQLAlchemy persistence for CrewAI flow state and durable service runs."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import json
import logging
import math
import re
from typing import TYPE_CHECKING, Any
import uuid

from crewai.flow.persistence import FlowPersistence
from pydantic import BaseModel, Field, PrivateAttr
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from threading import RLock

from brief_crew.events import FrameData
from brief_crew.events.redaction import (
    REDACTED,
    SECRET_KEYS,
    normalize_secret_key as _normalize_secret_key,
)


if TYPE_CHECKING:
    from crewai.flow.async_feedback.types import PendingFeedbackContext


logger = logging.getLogger(__name__)

MAX_JSON_BYTES = 1_048_576
MAX_JSON_DEPTH = 16
MAX_CONTAINER_ITEMS = 10_000
MAX_STRING_LENGTH = 65_536
MAX_ERROR_LENGTH = 4096
MAX_FRAME_REPLAY = 500
MAX_OPEN_GATE_SCAN = 500
MAX_STALE_RUN_SCAN = 500

_UNSET = object()
_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})
# Statuses that assert "a worker somewhere is supposed to be doing this".
# `waiting` is deliberately absent: it is durably anchored by run_gates and
# pending_feedback, so it survives a restart and must never be swept.
_LIVE_RUN_STATUSES = ("queued", "running", "cancelling")
# F03/R-2 watch ladder for an unanswered gate: open -> expired -> alerted.
_GATE_WATCH_STATUSES = frozenset({"expired", "alerted"})
# One list, shared with the frame serializer - `events/redaction.py` says why
# it left this module. The old name is kept because tests and the docstring
# above `_sanitize_json` refer to it.
_SECRET_KEYS = SECRET_KEYS
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@", re.I)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_type() -> JSON:
    return JSON(none_as_null=True).with_variant(
        JSONB(none_as_null=True), "postgresql"
    )


metadata = MetaData()

flow_states = Table(
    "flow_states",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("flow_uuid", String(128), nullable=False),
    Column("method_name", String(255), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("state", _json_type(), nullable=False),
)
Index("ix_flow_states_uuid_id", flow_states.c.flow_uuid, flow_states.c.id)

pending_feedback = Table(
    "pending_feedback",
    metadata,
    Column("flow_uuid", String(128), primary_key=True),
    Column("context", _json_type(), nullable=False),
    Column("state", _json_type(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

runs = Table(
    "runs",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("session_id", String(128), nullable=False),
    # The authenticated owner: Better Auth's `user.id`, or NULL.
    #
    # NULLABLE is a decision, not an oversight, and it has to stay that way for
    # two distinct reasons. Rows written before authentication existed have no
    # owner and cannot be given one retroactively - a NOT NULL column could not
    # be added to the live table at all without inventing an owner for them. And
    # the service still runs unauthenticated by design in tests, in SYNTHETIC
    # mode and in a bare local checkout, where there is no identity to record.
    #
    # There is deliberately NO ForeignKey to a `user` table. That table is owned
    # by Better Auth in a different language and its migrations are run by a
    # different tool; a constraint here would make the Python service's schema
    # depend on the Node service having migrated first, and would fail an insert
    # at runtime rather than at deploy. Ownership is enforced in the service
    # layer, where the 404-versus-403 decision is made anyway.
    Column("user_id", String(128)),
    Column("workflow_id", String(128), nullable=False),
    Column("flow_id", String(128)),
    Column("graph_version", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    # C7 (10-runtime.md): `run` / `test` / `node_test`. NULL reads as `run`,
    # and it is NULLable because `runs` shipped without it - see
    # _ADDITIVE_COLUMNS below for why a NOT NULL here would never reach the
    # live table at all.
    Column("mode", String(16)),
    Column("inputs", _json_type(), nullable=False),
    Column("usage", _json_type(), nullable=False),
    Column("result", _json_type()),
    Column("error", Text),
    Column("captured_frames", Integer, nullable=False, default=0),
    Column("dropped_frames", Integer, nullable=False, default=0),
    Column("frame_gaps", Integer, nullable=False, default=0),
    Column("emit_errors", Integer, nullable=False, default=0),
    Column("subscriber_dropped", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("ix_runs_session_created", runs.c.session_id, runs.c.created_at)
# "my runs, newest first" is the only query the history list makes, and without
# this it is a full scan of every run by every user.
Index("ix_runs_user_created", runs.c.user_id, runs.c.created_at)
Index("ix_runs_flow_id", runs.c.flow_id)
Index("ix_runs_status_created", runs.c.status, runs.c.created_at)

run_node_metrics = Table(
    "run_node_metrics",
    metadata,
    Column("run_id", String(128), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
    Column("node_id", String(128), primary_key=True),
    Column("model", String(255), primary_key=True, default=""),
    Column("successful_requests", Integer, nullable=False, default=0),
    Column("prompt_tokens", Integer, nullable=False, default=0),
    Column("completion_tokens", Integer, nullable=False, default=0),
    Column("total_tokens", Integer, nullable=False, default=0),
    Column("call_count", Integer, nullable=False, default=0),
    Column("elapsed_ms", Integer, nullable=False, default=0),
    Column("cost_usd", Numeric(12, 6), nullable=False, default=Decimal("0")),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("ix_run_node_metrics_run", run_node_metrics.c.run_id)

run_frames = Table(
    "run_frames",
    metadata,
    Column("run_id", String(128), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("v", Integer, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("level", String(16), nullable=False),
    Column("node_id", String(128), nullable=False),
    Column("message", String(4096), nullable=False),
    Column("details", _json_type(), nullable=False),
    Column("duration_ms", Integer),
)
Index("ix_run_frames_run_kind_seq", run_frames.c.run_id, run_frames.c.kind, run_frames.c.seq)

run_gates = Table(
    "run_gates",
    metadata,
    Column("run_id", String(128), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
    Column("gate_id", String(128), primary_key=True),
    Column("node_id", String(128), nullable=False),
    Column("status", String(16), nullable=False),
    Column("request", _json_type(), nullable=False),
    Column("response", _json_type()),
    Column("opened_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True)),
    Column("answered_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("ix_run_gates_pending", run_gates.c.run_id, run_gates.c.status)

# --------------------------------------------------------------------------
# Builder documents
#
# Two tables, and the split is the versioning: `builder_documents` is the ONE
# row per graph that says what its current version is, and
# `builder_document_versions` is the append-only history keyed by
# `(document_id, version)`, which is exactly the storage shape locked spec C
# names. A save writes the new version row and then compare-and-sets the head
# pointer, so two browsers saving the same graph produce two versions and one
# 409 rather than one lost edit.
#
# The document itself is stored as JSON rather than shredded into columns. It
# is validated by `builder/document.py` on the way in and on the way out, and
# a relational projection of a seven-kind polymorphic node would be a second
# schema to keep in step with the first for no query that anybody makes - the
# only predicates here are by id, by owner and by version.
#
# `user_id` is nullable for the same two reasons `runs.user_id` is: this
# service still runs unauthenticated by design in tests and in SYNTHETIC mode,
# and there is no ForeignKey to a `user` table that Better Auth owns in another
# language. Ownership is enforced in the service layer, where the 404-not-403
# decision already lives.
builder_documents = Table(
    "builder_documents",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("user_id", String(128)),
    Column("name", String(255), nullable=False),
    # The head version. Every UPDATE of this column is a compare-and-set
    # against the version the client was editing.
    Column("version", Integer, nullable=False),
    # "draft" until a compile has succeeded and the graph was registered;
    # "published" after. A draft is editable and unrunnable, which is why the
    # status lives on the head row rather than on a version.
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
# "my graphs, newest edit first" is the only query the builder list makes.
Index(
    "ix_builder_documents_user_updated",
    builder_documents.c.user_id,
    builder_documents.c.updated_at,
)

builder_document_versions = Table(
    "builder_document_versions",
    metadata,
    Column(
        "document_id",
        String(128),
        ForeignKey("builder_documents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("version", Integer, primary_key=True),
    Column("document", _json_type(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


# --------------------------------------------------------------------------
# Gauntlet tables - contract C10, owned by .agent/plans/15-persistence.md D6
#
# Six tables and one additive column, landed together by the Integrator before
# any Stage 1 feature branched, so that 01 (credentials), 06 (custom tools),
# 07 (MCP servers), 08 (skills) and 13 (test inputs) build against one shape
# rather than five. None of these tables has ever shipped, so `create_all()`
# creates each one WITH its indexes and constraints; the additive-column rule
# below applies only to `runs.mode`, because `runs` has shipped.
#
# Every table carries a NOT NULL `user_id`. These rows never existed before
# authentication did, so unlike `runs.user_id` and `builder_documents.user_id`
# there are no legacy rows to protect and no reason to admit an ownerless one
# (01 D2, isolation rule 1). There is still no ForeignKey to a `user` table,
# for the reason given above `runs`.
# --------------------------------------------------------------------------
user_credentials = Table(
    "user_credentials",
    metadata,
    # `cr_` + 8 hex (config.CREDENTIAL_ID_PATTERN), minted by
    # service/credentials.py the way store.py mints `ug_` document ids.
    # String(128) like every other id column here - 15 D6 wrote a longer id
    # and 01 C4 a shorter one; the Integrator's S1 ruling is in 00's Status.
    Column("id", String(128), primary_key=True),
    Column("user_id", String(128), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("label", String(80), nullable=False),
    # AES-256-GCM over the fields JSON. The nonce is 12 random bytes per write,
    # and the associated data binds `id` and `user_id` into the ciphertext, so
    # a row copied under another user or id fails to authenticate rather than
    # decrypting (01 D3). The plaintext never appears in any other table.
    Column("ciphertext", LargeBinary, nullable=False),
    Column("nonce", LargeBinary, nullable=False),
    Column("key_version", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("last_used_at", DateTime(timezone=True)),
    UniqueConstraint("user_id", "label", name="uq_user_credentials_user_label"),
)
Index("ix_user_credentials_user_kind", user_credentials.c.user_id, user_credentials.c.kind)

# The index row for a SKILL.md pack on disk (08 owns the files, C11).
user_skills = Table(
    "user_skills",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("user_id", String(128), nullable=False),
    Column("name", String(64), nullable=False),
    Column("description", String(1024), nullable=False),
    Column("path", String(255), nullable=False),
    Column("bytes", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("user_id", "name", name="uq_user_skills_user_name"),
)
Index("ix_user_skills_user_updated", user_skills.c.user_id, user_skills.c.updated_at)

# A per-user MCP server record and its last discovery result (07 owns
# discovery, C12). `header_credential_id` / `env_credential_id` name rows in
# `user_credentials` with no ForeignKey, as `runs.user_id` has none: a deleted
# credential makes the server validate as `credential-missing`, not fail DDL.
mcp_servers = Table(
    "mcp_servers",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("user_id", String(128), nullable=False),
    Column("label", String(80), nullable=False),
    Column("transport", String(8), nullable=False),
    Column("url", String(2048)),
    Column("command", String(255)),
    Column("args", _json_type()),
    Column("header_credential_id", String(128)),
    Column("env_credential_id", String(128)),
    Column("status", String(16), nullable=False),
    Column("discovered_tools", _json_type()),
    Column("discovered_at", DateTime(timezone=True)),
    Column("last_error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("ix_mcp_servers_user_updated", mcp_servers.c.user_id, mcp_servers.c.updated_at)

# The declarative custom HTTP tool (00 D8, 06): a schema grid and a request
# template, never code.
user_tools = Table(
    "user_tools",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("user_id", String(128), nullable=False),
    Column("name", String(64), nullable=False),
    Column("description", String(1024), nullable=False),
    Column("input_schema", _json_type(), nullable=False),
    Column("request", _json_type(), nullable=False),
    Column("credential_id", String(128)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("user_id", "name", name="uq_user_tools_user_name"),
)

# A saved set of run inputs for the docked test panel (13). The ForeignKey is
# real here because both tables are ours and a document's test inputs have no
# meaning once the document is gone.
builder_test_inputs = Table(
    "builder_test_inputs",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("user_id", String(128), nullable=False),
    Column(
        "document_id",
        String(128),
        ForeignKey("builder_documents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("label", String(80), nullable=False),
    Column("inputs", _json_type(), nullable=False),
    Column("node_mocks", _json_type()),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index(
    "ix_builder_test_inputs_document_updated",
    builder_test_inputs.c.document_id,
    builder_test_inputs.c.updated_at,
)

# The tables above, by name, for the boot-time inspector assertion and the
# isolation matrix. Order is the order they were declared.
GAUNTLET_TABLES: tuple[str, ...] = (
    "user_credentials",
    "user_skills",
    "mcp_servers",
    "user_tools",
    "builder_test_inputs",
)


@dataclass(frozen=True, slots=True)
class GateAnswerResult:
    """Result of the compare-and-set used to answer a durable gate."""

    accepted: bool
    conflict: bool
    gate: dict[str, Any]

    def __bool__(self) -> bool:
        return self.accepted


class PersistenceValueError(ValueError):
    """Raised when a value cannot be safely stored as bounded JSON."""


def _redact_text(value: str) -> str:
    return _URL_CREDENTIALS.sub(r"\g<scheme>[REDACTED]@", value)


def _sanitize_json(value: Any, *, label: str, depth: int = 0) -> Any:
    if depth > MAX_JSON_DEPTH:
        raise PersistenceValueError(f"{label} exceeds the maximum JSON depth")
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PersistenceValueError(f"{label} contains a non-finite number")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise PersistenceValueError(f"{label} contains a non-finite decimal")
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return _sanitize_json(value.value, label=label, depth=depth)
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise PersistenceValueError(f"{label} contains an oversized string")
        return _redact_text(value)
    if isinstance(value, BaseModel):
        return _sanitize_json(
            value.model_dump(mode="json"), label=label, depth=depth + 1
        )
    if isinstance(value, Mapping):
        if len(value) > MAX_CONTAINER_ITEMS:
            raise PersistenceValueError(f"{label} contains too many fields")
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            if len(normalized_key) > 255:
                raise PersistenceValueError(f"{label} contains an oversized key")
            if _normalize_secret_key(normalized_key) in _SECRET_KEYS:
                sanitized[normalized_key] = REDACTED
            else:
                sanitized[normalized_key] = _sanitize_json(
                    item, label=label, depth=depth + 1
                )
        return sanitized
    if isinstance(value, list | tuple):
        if len(value) > MAX_CONTAINER_ITEMS:
            raise PersistenceValueError(f"{label} contains too many items")
        return [
            _sanitize_json(item, label=label, depth=depth + 1) for item in value
        ]
    raise PersistenceValueError(
        f"{label} contains unsupported live object {type(value).__name__}"
    )


def _bounded_json(value: Any, *, label: str) -> Any:
    sanitized = _sanitize_json(value, label=label)
    try:
        payload = json.dumps(
            sanitized, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise PersistenceValueError(f"{label} is not JSON serializable") from exc
    if len(payload.encode("utf-8")) > MAX_JSON_BYTES:
        raise PersistenceValueError(f"{label} exceeds {MAX_JSON_BYTES} bytes")
    return sanitized


def _state_dict(state_data: dict[str, Any] | BaseModel) -> dict[str, Any]:
    if isinstance(state_data, BaseModel):
        state_data = state_data.model_dump(mode="json")
    if not isinstance(state_data, dict):
        raise PersistenceValueError(
            "state_data must be a dict or Pydantic BaseModel"
        )
    result = _bounded_json(state_data, label="flow state")
    if not isinstance(result, dict):
        raise PersistenceValueError("flow state must serialize to an object")
    return result


def _identifier(value: Any, *, label: str, limit: int = 128) -> str:
    rendered = str(value).strip()
    if not rendered or len(rendered) > limit:
        raise ValueError(f"{label} must contain 1-{limit} characters")
    return rendered


def _enum_value(value: Any) -> str:
    return str(value.value if isinstance(value, Enum) else value)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: Any, *, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise PersistenceValueError(f"{label} must be an ISO timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# Public names for `builder/store.py`, which writes `builder_documents` and
# `builder_document_versions` on this module's engine and must bound and
# sanitise its JSON exactly the way every other writer here does. Aliases
# rather than a second implementation: a store that redacted differently, or
# bounded strings at a different length, would be a second answer to a question
# this module already answers - and the one that got it wrong would be the one
# nobody re-read.
bounded_json = _bounded_json
identifier = _identifier
utcnow = _utcnow


def _engine_for(database: str | Engine, engine_options: Mapping[str, Any]) -> tuple[Engine, bool]:
    if isinstance(database, Engine):
        if engine_options:
            raise ValueError("engine_options cannot be used with an existing Engine")
        return database, False
    if not isinstance(database, str) or not database.strip():
        raise ValueError("database must be a SQLAlchemy URL or Engine")

    options = dict(engine_options)
    options.setdefault("pool_pre_ping", True)
    if database.startswith("sqlite") and ":memory:" in database:
        connect_args = dict(options.pop("connect_args", {}))
        connect_args.setdefault("check_same_thread", False)
        options["connect_args"] = connect_args
        options.setdefault("poolclass", StaticPool)
        options["pool_pre_ping"] = False
    return create_engine(database, **options), True


def _shares_one_connection(engine: Engine) -> bool:
    """True when every checkout returns the same DBAPI connection.

    That is the in-memory SQLite case: the database only exists for as long as
    its one connection does, so StaticPool hands the same connection to every
    thread with no mutual exclusion. Two threads in ``begin()`` at once then
    share one transaction, and one thread's COMMIT silently ends the other's
    unit of work. PostgreSQL and file-backed SQLite pool per checkout instead,
    so neither pays for the guard below.
    """
    return isinstance(engine.pool, StaticPool)


class PostgresFlowPersistence(FlowPersistence):
    """Postgres production store with SQLite-compatible tests and local use."""

    persistence_type: str = Field(default="PostgresFlowPersistence")
    _engine: Engine = PrivateAttr()
    _owns_engine: bool = PrivateAttr(default=False)
    _access_lock: Any = PrivateAttr(default=None)

    def __init__(
        self,
        database: str | Engine,
        /,
        *,
        initialize: bool = True,
        engine_options: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._engine, self._owns_engine = _engine_for(
            database, engine_options or {}
        )
        # Re-entrant, because a few methods read through a helper after their
        # own transaction has already committed - and one thread must never
        # block on a lock it already holds.
        self._access_lock = RLock() if _shares_one_connection(self._engine) else None
        if initialize:
            self.init_db()

    @contextmanager
    def _begin(self) -> Iterator[Any]:
        """A write transaction, serialized only on a shared-connection engine."""
        with self._guard():
            with self._engine.begin() as connection:
                yield connection

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        """A read connection, serialized only on a shared-connection engine."""
        with self._guard():
            with self._engine.connect() as connection:
                yield connection

    def _guard(self) -> Any:
        return nullcontext() if self._access_lock is None else self._access_lock

    @contextmanager
    def begin(self) -> Iterator[Any]:
        """A guarded write transaction, for a sibling store on this engine.

        `builder/store.py` writes two of the tables above and must not open its
        own engine to do it: on in-memory SQLite the database only exists for
        as long as its one connection does, and `_access_lock` is what stops
        two threads sharing that single connection's transaction. A second
        store reaching for `engine.begin()` directly would bypass the guard and
        commit somebody else's half-finished unit of work.

        Public rather than a `_begin` a sibling reaches into, because that is
        what it is: one module in this package is expected to write through it.
        """
        with self._begin() as connection:
            yield connection

    @contextmanager
    def connect(self) -> Iterator[Any]:
        """A guarded read connection, for a sibling store on this engine."""
        with self._connect() as connection:
            yield connection

    @property
    def engine(self) -> Engine:
        """Return the SQLAlchemy engine without exposing its URL in model data."""
        return self._engine

    def init_db(self) -> None:
        """Create the flow and service persistence schema if it is absent."""
        metadata.create_all(self._engine)
        self._add_missing_columns()

    # Columns added to a table that already SHIPPED, as (table, column, DDL type).
    #
    # `metadata.create_all()` is create-if-absent, per TABLE. It does nothing at
    # all to a table that already exists, so a column added to a Table()
    # definition above appears on a fresh database and is silently missing on
    # every deployed one - and the failure is not at startup but at the first
    # INSERT, which names the new column and gets "no such column" from a
    # production database mid-request.
    #
    # This repo has no Alembic, and adding it for one nullable column would be a
    # large dependency for a small need. What it does have is an invariant worth
    # keeping: additive, nullable columns only. Anything that needs a backfill, a
    # NOT NULL, a rename or a drop does NOT belong here - that is the point at
    # which a real migration tool has become cheaper than this list.
    _ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
        ("runs", "user_id", "VARCHAR(128)"),
        # C7 run mode, .agent/plans/15-persistence.md D6. VARCHAR(16), NULL = `run`.
        ("runs", "mode", "VARCHAR(16)"),
    )

    def _add_missing_columns(self) -> None:
        """Bring an already-deployed schema up to the table definitions above.

        Idempotent: it inspects first and issues DDL only for what is genuinely
        absent, so it is safe on every startup, on a fresh database, and on one
        that is already current.
        """
        from sqlalchemy import inspect as sqlalchemy_inspect
        from sqlalchemy import text

        inspector = sqlalchemy_inspect(self._engine)
        existing_tables = set(inspector.get_table_names())

        for table_name, column_name, column_type in self._ADDITIVE_COLUMNS:
            if table_name not in existing_tables:
                continue  # create_all just made it, with the column already on it
            present = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            if column_name in present:
                continue
            # The identifiers are literals in _ADDITIVE_COLUMNS, never user
            # input, so there is nothing here to parameterise - DDL cannot take
            # bound parameters for identifiers in any case.
            with self._begin() as connection:
                connection.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )
            logger.info("added missing column %s.%s", table_name, column_name)

        # Indexes are created by create_all only alongside their own table, so an
        # index on a newly added column has to be asked for separately.
        for index in runs.indexes:
            try:
                index.create(bind=self._engine, checkfirst=True)
            except Exception as exc:  # noqa: BLE001
                # A missing index costs a slow query, never a wrong answer. It
                # must not be the reason a service fails to start.
                logger.warning("could not ensure index %s: %s", index.name, exc)

    def close(self) -> None:
        """Dispose an engine created by this repository."""
        if self._owns_engine:
            self._engine.dispose()

    def health_status(self) -> dict[str, str]:
        """Probe storage without exposing a connection URL or exception text."""
        backend = self._engine.dialect.name
        try:
            with self._connect() as connection:
                connection.execute(select(1)).scalar_one()
        except Exception:
            return {"status": "error", "backend": backend}
        return {"status": "ok", "backend": backend}

    def save_state(
        self,
        flow_uuid: str,
        method_name: str,
        state_data: dict[str, Any] | BaseModel,
    ) -> None:
        flow_uuid = _identifier(flow_uuid, label="flow_uuid")
        method_name = _identifier(method_name, label="method_name", limit=255)
        state = _state_dict(state_data)
        with self._begin() as connection:
            self._insert_flow_state(
                connection, flow_uuid=flow_uuid, method_name=method_name, state=state
            )

    def load_state(self, flow_uuid: str) -> dict[str, Any] | None:
        flow_uuid = _identifier(flow_uuid, label="flow_uuid")
        statement = (
            select(flow_states.c.state)
            .where(flow_states.c.flow_uuid == flow_uuid)
            .order_by(flow_states.c.id.desc())
            .limit(1)
        )
        with self._connect() as connection:
            state = connection.execute(statement).scalar_one_or_none()
        return dict(state) if isinstance(state, Mapping) else None

    def save_pending_feedback(
        self,
        flow_uuid: str,
        context: PendingFeedbackContext,
        state_data: dict[str, Any] | BaseModel,
    ) -> bool:
        """Anchor a paused flow. True when this call's context is what is stored.

        UPDATE-then-INSERT rather than an upsert, because the two dialects this
        runs on spell upsert differently and the row is keyed by
        ``flow_uuid`` alone. That shape has one race, and it is the one
        ``tests/pg/test_two_writers.py`` drives: two processes raising
        ``HumanFeedbackPending`` for one flow both read ``rowcount == 0`` from
        the UPDATE, both INSERT, and the primary key decides. The loser's
        transaction - the ``flow_states`` row included - is rolled back by the
        raise, so nothing half-written remains, and it returns ``False``
        rather than propagating ``IntegrityError``: the flow IS pending, which
        is what the caller asked for, and the winner's context is the one
        anchor a resume may read. Two processes pausing the same flow at once
        means two processes are executing it, and the second anchor is the one
        thing that must not overwrite the first.
        """
        flow_uuid = _identifier(flow_uuid, label="flow_uuid")
        if _identifier(context.flow_id, label="context.flow_id") != flow_uuid:
            raise ValueError("pending feedback flow_id must match flow_uuid")
        state = _state_dict(state_data)
        context_data = _bounded_json(context.to_dict(), label="pending feedback")
        now = _utcnow()

        try:
            with self._begin() as connection:
                self._insert_flow_state(
                    connection,
                    flow_uuid=flow_uuid,
                    method_name=context.method_name,
                    state=state,
                    created_at=now,
                )
                result = connection.execute(
                    update(pending_feedback)
                    .where(pending_feedback.c.flow_uuid == flow_uuid)
                    .values(context=context_data, state=state, updated_at=now)
                )
                if result.rowcount == 0:
                    connection.execute(
                        insert(pending_feedback).values(
                            flow_uuid=flow_uuid,
                            context=context_data,
                            state=state,
                            created_at=now,
                            updated_at=now,
                        )
                    )
        except IntegrityError:
            with self._connect() as connection:
                existing = connection.execute(
                    select(pending_feedback.c.flow_uuid).where(
                        pending_feedback.c.flow_uuid == flow_uuid
                    )
                ).scalar_one_or_none()
            if existing is None:
                # Not the race: the constraint that fired was some other one,
                # and hiding it behind "already pending" would be a lie.
                raise
            logger.warning(
                "pending feedback for flow %s was written by another process "
                "first; this context was not stored",
                flow_uuid,
            )
            return False
        return True

    def load_pending_feedback(
        self, flow_uuid: str
    ) -> tuple[dict[str, Any], PendingFeedbackContext] | None:
        from crewai.flow.async_feedback.types import PendingFeedbackContext

        flow_uuid = _identifier(flow_uuid, label="flow_uuid")
        with self._connect() as connection:
            row = connection.execute(
                select(pending_feedback.c.state, pending_feedback.c.context).where(
                    pending_feedback.c.flow_uuid == flow_uuid
                )
            ).mappings().one_or_none()
        if row is None:
            return None
        state = dict(row["state"])
        context = PendingFeedbackContext.from_dict(dict(row["context"]))
        return state, context

    def clear_pending_feedback(self, flow_uuid: str) -> None:
        flow_uuid = _identifier(flow_uuid, label="flow_uuid")
        with self._begin() as connection:
            connection.execute(
                delete(pending_feedback).where(
                    pending_feedback.c.flow_uuid == flow_uuid
                )
            )

    def create_run(
        self,
        *,
        session_id: str,
        workflow_id: str,
        graph_version: str,
        inputs: Mapping[str, Any] | None = None,
        run_id: str | None = None,
        flow_id: str | None = None,
        user_id: str | None = None,
        status: Any = "queued",
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        run_id = _identifier(run_id or uuid.uuid4(), label="run_id")
        session_id = _identifier(session_id, label="session_id")
        # Bounded like every other identifier that reaches a column. The value
        # originates in a VERIFIED token claim, not in the request body, so this
        # is a width check rather than a trust boundary - but the column is
        # VARCHAR(128) and an over-long id must fail here, with a name, rather
        # than as a driver-level truncation error deep in an insert.
        owner = _identifier(user_id, label="user_id") if user_id else None
        workflow_id = _identifier(workflow_id, label="workflow_id")
        graph_version = _identifier(graph_version, label="graph_version")
        flow_id = _identifier(flow_id, label="flow_id") if flow_id is not None else None
        status_value = _identifier(_enum_value(status), label="status", limit=32)
        safe_inputs = _bounded_json(dict(inputs or {}), label="run inputs")
        now = _as_utc(created_at) or _utcnow()

        with self._begin() as connection:
            connection.execute(
                insert(runs).values(
                    id=run_id,
                    session_id=session_id,
                    user_id=owner,
                    workflow_id=workflow_id,
                    flow_id=flow_id,
                    graph_version=graph_version,
                    status=status_value,
                    inputs=safe_inputs,
                    usage={},
                    captured_frames=0,
                    dropped_frames=0,
                    frame_gaps=0,
                    emit_errors=0,
                    subscriber_dropped=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        created = self.get_run(run_id)
        if created is None:
            raise RuntimeError(f"run {run_id} was not persisted")
        return created

    def update_run_status(
        self,
        run_id: str,
        status: Any,
        *,
        started_at: datetime | None | object = _UNSET,
        completed_at: datetime | None | object = _UNSET,
        result: Any = _UNSET,
        error: str | None | object = _UNSET,
        usage: Mapping[str, Any] | object = _UNSET,
        dropped_frames: int | object = _UNSET,
        frame_gaps: int | object = _UNSET,
        emit_errors: int | object = _UNSET,
        subscriber_dropped: int | object = _UNSET,
    ) -> dict[str, Any]:
        run_id = _identifier(run_id, label="run_id")
        status_value = _identifier(_enum_value(status), label="status", limit=32)
        now = _utcnow()
        values: dict[str, Any] = {"status": status_value, "updated_at": now}

        if started_at is not _UNSET:
            values["started_at"] = _as_utc(started_at)  # type: ignore[arg-type]
        elif status_value == "running":
            values["started_at"] = func.coalesce(runs.c.started_at, now)
        if completed_at is not _UNSET:
            values["completed_at"] = _as_utc(completed_at)  # type: ignore[arg-type]
        elif status_value in _TERMINAL_RUN_STATUSES:
            values["completed_at"] = func.coalesce(runs.c.completed_at, now)
        if result is not _UNSET:
            values["result"] = _bounded_json(result, label="run result")
        if error is not _UNSET:
            values["error"] = (
                _redact_text(str(error))[:MAX_ERROR_LENGTH]
                if error is not None
                else None
            )
        if usage is not _UNSET:
            values["usage"] = _bounded_json(dict(usage), label="run usage")  # type: ignore[arg-type]

        for column_name, value in (
            ("dropped_frames", dropped_frames),
            ("frame_gaps", frame_gaps),
            ("emit_errors", emit_errors),
            ("subscriber_dropped", subscriber_dropped),
        ):
            if value is not _UNSET:
                numeric_value = int(value)  # type: ignore[arg-type]
                if numeric_value < 0:
                    raise ValueError(f"{column_name} cannot be negative")
                values[column_name] = numeric_value

        with self._begin() as connection:
            update_result = connection.execute(
                update(runs).where(runs.c.id == run_id).values(**values)
            )
            if update_result.rowcount == 0:
                raise KeyError(run_id)
        updated = self.get_run(run_id)
        if updated is None:
            raise KeyError(run_id)
        return updated

    def claim_run_status(
        self,
        run_id: str,
        status: Any,
        *,
        expected_statuses: Sequence[Any],
    ) -> bool:
        """Move a run's status only while it is still one of ``expected_statuses``.

        The compare-and-set the orphan sweep needed and did not have. Plan 15
        D8 and CLAUDE.md remaining-work item 3 both list the sweep among the
        guarded ``UPDATE ... WHERE ...; rowcount`` paths, and until this method
        it was not one: ``_fail_interrupted`` reached storage through
        ``update_run_status``, which guards on ``id`` alone, so two API
        instances sweeping one store - a deploy overlapping the instance it is
        replacing, which ``autoDeploy: yes`` makes routine - would BOTH
        reconcile one run, each writing its own terminal status and frames.
        Guarding on the status the sweeper loaded means the second writer sees
        ``rowcount == 0`` and learns the row is already terminal.

        Only the status and its timestamps move here; ``completed_at`` is set
        for a terminal target and left alone otherwise. The rest of the record
        - result, error, usage, frame counters - is written afterwards by the
        winner through ``update_run_status``, which stays unconditional and is
        right to: it now runs only in the process holding the claim. Returns
        True when this call made the change; False when the row is gone or
        already left the expected set, which the caller must treat as somebody
        else's reconciliation and not as an error.

        ``tests/pg/test_two_writers.py`` drives two processes into this
        UPDATE at once; ``tests/service/test_orphan_sweep_claim.py`` pins the
        loser's behaviour on SQLite.
        """
        run_id = _identifier(run_id, label="run_id")
        status_value = _identifier(_enum_value(status), label="status", limit=32)
        expected = tuple(
            _identifier(_enum_value(item), label="expected_status", limit=32)
            for item in expected_statuses
        )
        if not expected:
            raise ValueError("expected_statuses cannot be empty")
        now = _utcnow()
        values: dict[str, Any] = {"status": status_value, "updated_at": now}
        if status_value in _TERMINAL_RUN_STATUSES:
            values["completed_at"] = func.coalesce(runs.c.completed_at, now)
        with self._begin() as connection:
            result = connection.execute(
                update(runs)
                .where(runs.c.id == run_id, runs.c.status.in_(expected))
                .values(**values)
            )
            claimed = result.rowcount == 1
        return claimed

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run_id = _identifier(run_id, label="run_id")
        with self._connect() as connection:
            row = connection.execute(
                select(runs).where(runs.c.id == run_id)
            ).mappings().one_or_none()
            if row is None:
                return None
            frame_stats = connection.execute(
                select(
                    func.count(run_frames.c.seq).label("count"),
                    func.min(run_frames.c.seq).label("first_seq"),
                    func.max(run_frames.c.seq).label("last_seq"),
                ).where(run_frames.c.run_id == run_id)
            ).mappings().one()
            gate_row = connection.execute(
                select(run_gates)
                .where(
                    run_gates.c.run_id == run_id,
                    run_gates.c.answered_at.is_(None),
                )
                .order_by(run_gates.c.opened_at.desc())
                .limit(1)
            ).mappings().one_or_none()
        return self._run_dict(row, frame_stats, gate_row)

    def append_frames(
        self, run_id: str, frames: Sequence[FrameData | Mapping[str, Any]]
    ) -> int:
        run_id = _identifier(run_id, label="run_id")
        prepared_by_seq: dict[int, dict[str, Any]] = {}
        for frame in frames:
            data = frame.to_dict() if isinstance(frame, FrameData) else dict(frame)
            frame_run_id = _identifier(data.get("run_id", run_id), label="frame.run_id")
            if frame_run_id != run_id:
                raise ValueError("all frames in a batch must match run_id")
            seq = int(data["seq"])
            if seq < 1:
                raise ValueError("frame sequence must be positive")
            if seq in prepared_by_seq:
                raise ValueError(f"duplicate frame sequence in batch: {seq}")
            prepared_by_seq[seq] = {
                "run_id": run_id,
                "seq": seq,
                "v": int(data.get("v", 1)),
                "ts": _parse_datetime(data["ts"], label="frame.ts"),
                "kind": _identifier(_enum_value(data["kind"]), label="frame.kind", limit=32),
                "event_type": _identifier(
                    _enum_value(data["event_type"]), label="frame.event_type", limit=64
                ),
                "level": _identifier(_enum_value(data["level"]), label="frame.level", limit=16),
                "node_id": _identifier(data["node_id"], label="frame.node_id"),
                "message": str(data.get("message", ""))[:4096],
                "details": _bounded_json(data.get("details", {}), label="frame details"),
                "duration_ms": data.get("duration_ms"),
            }

        if not prepared_by_seq:
            return 0
        ordered_rows = [prepared_by_seq[seq] for seq in sorted(prepared_by_seq)]
        sequences = list(prepared_by_seq)
        with self._begin() as connection:
            if connection.execute(
                select(runs.c.id).where(runs.c.id == run_id)
            ).scalar_one_or_none() is None:
                raise KeyError(run_id)
            existing = set(
                connection.execute(
                    select(run_frames.c.seq).where(
                        run_frames.c.run_id == run_id,
                        run_frames.c.seq.in_(sequences),
                    )
                ).scalars()
            )
            new_rows = [row for row in ordered_rows if row["seq"] not in existing]
            if new_rows:
                connection.execute(insert(run_frames), new_rows)
                connection.execute(
                    update(runs)
                    .where(runs.c.id == run_id)
                    .values(
                        captured_frames=runs.c.captured_frames + len(new_rows),
                        updated_at=_utcnow(),
                    )
                )
        return len(new_rows)

    def replay_frames(
        self,
        run_id: str,
        *,
        after: int = 0,
        limit: int = MAX_FRAME_REPLAY,
        kinds: set[Any] | None = None,
    ) -> list[dict[str, Any]]:
        run_id = _identifier(run_id, label="run_id")
        if after < 0:
            raise ValueError("after cannot be negative")
        if not 1 <= limit <= MAX_FRAME_REPLAY:
            raise ValueError(f"limit must be between 1 and {MAX_FRAME_REPLAY}")
        statement = select(run_frames).where(
            run_frames.c.run_id == run_id, run_frames.c.seq > after
        )
        if kinds:
            statement = statement.where(
                run_frames.c.kind.in_({_enum_value(kind) for kind in kinds})
            )
        statement = statement.order_by(run_frames.c.seq).limit(limit)
        with self._connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._frame_dict(row) for row in rows]

    def open_gate(
        self,
        run_id: str,
        gate_id: str,
        *,
        node_id: str,
        request: Mapping[str, Any],
        opened_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        run_id = _identifier(run_id, label="run_id")
        gate_id = _identifier(gate_id, label="gate_id")
        node_id = _identifier(node_id, label="node_id")
        safe_request = _bounded_json(dict(request), label="gate request")
        now = _as_utc(opened_at) or _utcnow()
        try:
            with self._begin() as connection:
                if connection.execute(
                    select(runs.c.id).where(runs.c.id == run_id)
                ).scalar_one_or_none() is None:
                    raise KeyError(run_id)
                connection.execute(
                    insert(run_gates).values(
                        run_id=run_id,
                        gate_id=gate_id,
                        node_id=node_id,
                        status="open",
                        request=safe_request,
                        opened_at=now,
                        expires_at=_as_utc(expires_at),
                        updated_at=now,
                    )
                )
                connection.execute(
                    update(runs)
                    .where(runs.c.id == run_id)
                    .values(status="waiting", updated_at=now)
                )
        except IntegrityError:
            existing = self.get_gate(run_id, gate_id)
            if existing is None:
                raise
            return existing
        gate = self.get_gate(run_id, gate_id)
        if gate is None:
            raise RuntimeError(f"gate {gate_id} was not persisted")
        return gate

    def answer_gate(
        self,
        run_id: str,
        gate_id: str,
        response: Mapping[str, Any] | None = None,
        *,
        outcome: str | None = None,
        fields: Mapping[str, str] | None = None,
        answered_at: datetime | None = None,
    ) -> GateAnswerResult:
        run_id = _identifier(run_id, label="run_id")
        gate_id = _identifier(gate_id, label="gate_id")
        if response is not None and (outcome is not None or fields is not None):
            raise ValueError("pass response or outcome/fields, not both")
        reply = dict(response or {})
        if response is None:
            if outcome is None:
                raise ValueError("gate response requires an outcome")
            reply["outcome"] = outcome
            if fields is not None:
                reply["fields"] = dict(fields)
        safe_response = _bounded_json(reply, label="gate response")
        now = _as_utc(answered_at) or _utcnow()

        with self._begin() as connection:
            current = connection.execute(
                select(run_gates).where(
                    run_gates.c.run_id == run_id,
                    run_gates.c.gate_id == gate_id,
                )
            ).mappings().one_or_none()
            if current is None:
                raise KeyError((run_id, gate_id))
            accepted = False
            if current["answered_at"] is None:
                result = connection.execute(
                    update(run_gates)
                    .where(
                        run_gates.c.run_id == run_id,
                        run_gates.c.gate_id == gate_id,
                        run_gates.c.answered_at.is_(None),
                    )
                    .values(
                        status="answered",
                        response=safe_response,
                        answered_at=now,
                        updated_at=now,
                    )
                )
                accepted = result.rowcount == 1
                if accepted:
                    connection.execute(
                        update(runs)
                        .where(runs.c.id == run_id)
                        .values(status="running", updated_at=now)
                    )
            stored = connection.execute(
                select(run_gates).where(
                    run_gates.c.run_id == run_id,
                    run_gates.c.gate_id == gate_id,
                )
            ).mappings().one()
        return GateAnswerResult(
            accepted=accepted,
            conflict=not accepted,
            gate=self._gate_dict(stored),
        )

    def reopen_gate(
        self,
        run_id: str,
        gate_id: str,
        *,
        status: str = "open",
    ) -> dict[str, Any]:
        """Undo an accepted answer whose resume never started.

        ``answer_gate`` is a durable compare-and-set, so once it accepts, the
        run is committed to resuming and every later reply is a 409. If the
        resume then fails to start, that commitment is a lie: the gate is
        answered, no work is queued, and the operator has no lever left. This
        is the compensating write - it clears ``answered_at`` and the stored
        response and puts the run back to ``waiting``, so the same reply can be
        sent again.

        Compare-and-set in the other direction, for the same reason: it only
        rewinds a gate that is *currently* answered, so it can never race a
        legitimate answer into being un-answered twice. ``status`` restores the
        F03 watch state the answer overwrote, so a gate that was already
        expired or alerted does not come back looking fresh.
        """
        run_id = _identifier(run_id, label="run_id")
        gate_id = _identifier(gate_id, label="gate_id")
        if status != "open" and status not in _GATE_WATCH_STATUSES:
            raise ValueError(
                "gate reopen status must be open or one of "
                f"{sorted(_GATE_WATCH_STATUSES)}"
            )
        now = _utcnow()
        with self._begin() as connection:
            result = connection.execute(
                update(run_gates)
                .where(
                    run_gates.c.run_id == run_id,
                    run_gates.c.gate_id == gate_id,
                    run_gates.c.answered_at.is_not(None),
                )
                .values(
                    status=status,
                    response=None,
                    answered_at=None,
                    updated_at=now,
                )
            )
            if result.rowcount == 0:
                exists = connection.execute(
                    select(run_gates.c.gate_id).where(
                        run_gates.c.run_id == run_id,
                        run_gates.c.gate_id == gate_id,
                    )
                ).scalar_one_or_none()
                if exists is None:
                    raise KeyError((run_id, gate_id))
            else:
                connection.execute(
                    update(runs)
                    .where(runs.c.id == run_id)
                    .values(status="waiting", updated_at=now)
                )
        gate = self.get_gate(run_id, gate_id)
        if gate is None:
            raise KeyError((run_id, gate_id))
        return gate

    def expire_gate(
        self,
        run_id: str,
        gate_id: str,
        *,
        status: str = "expired",
    ) -> dict[str, Any]:
        """Advance an unanswered gate along the F03 watch ladder.

        ``expired`` and ``alerted`` are advisory: ``answered_at`` stays NULL, so
        ``get_pending_gate`` keeps returning the gate and ``answer_gate`` still
        accepts a late reply. The run row is untouched - the run stays waiting.
        """
        run_id = _identifier(run_id, label="run_id")
        gate_id = _identifier(gate_id, label="gate_id")
        if status not in _GATE_WATCH_STATUSES:
            raise ValueError(
                f"gate watch status must be one of {sorted(_GATE_WATCH_STATUSES)}"
            )
        with self._begin() as connection:
            result = connection.execute(
                update(run_gates)
                .where(
                    run_gates.c.run_id == run_id,
                    run_gates.c.gate_id == gate_id,
                    run_gates.c.answered_at.is_(None),
                )
                .values(status=status, updated_at=_utcnow())
            )
            if result.rowcount == 0:
                exists = connection.execute(
                    select(run_gates.c.gate_id).where(
                        run_gates.c.run_id == run_id,
                        run_gates.c.gate_id == gate_id,
                    )
                ).scalar_one_or_none()
                if exists is None:
                    raise KeyError((run_id, gate_id))
        gate = self.get_gate(run_id, gate_id)
        if gate is None:
            raise KeyError((run_id, gate_id))
        return gate

    def get_gate(self, run_id: str, gate_id: str) -> dict[str, Any] | None:
        run_id = _identifier(run_id, label="run_id")
        gate_id = _identifier(gate_id, label="gate_id")
        with self._connect() as connection:
            row = connection.execute(
                select(run_gates).where(
                    run_gates.c.run_id == run_id,
                    run_gates.c.gate_id == gate_id,
                )
            ).mappings().one_or_none()
        return self._gate_dict(row) if row is not None else None

    def list_open_gates(
        self,
        *,
        due_by: datetime | None = None,
        limit: int = MAX_OPEN_GATE_SCAN,
    ) -> list[dict[str, Any]]:
        """Unanswered gates, oldest first - the F03 sweeper's durable input.

        ``due_by`` keeps only gates whose ``expires_at`` has already passed, so a
        gate that expired while the process was down is found on the next sweep
        even before any client asks for its run.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        statement = select(run_gates).where(run_gates.c.answered_at.is_(None))
        if due_by is not None:
            statement = statement.where(
                run_gates.c.expires_at.is_not(None),
                run_gates.c.expires_at <= _as_utc(due_by),
            )
        statement = statement.order_by(run_gates.c.opened_at).limit(limit)
        with self._connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._gate_dict(row) for row in rows]

    def list_runs_for_user(
        self,
        user_id: str,
        *,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """One person's runs, newest first - the history list's only query.

        Deliberately NOT ``get_run`` in a loop. ``get_run`` pays two subqueries
        per row (frame statistics and the open gate) to answer questions a list
        does not ask, so a 25-row history would cost 50 extra queries to render
        a verdict and a timestamp.

        The ``user_id`` filter is applied in SQL rather than by fetching and
        filtering in Python. That is not only faster - it means a bug in the
        service layer cannot leak another person's row into a response, because
        the row was never selected. ``ix_runs_user_created`` covers exactly this
        predicate and ordering.

        An empty or missing ``user_id`` returns nothing rather than everything.
        The dangerous reading of "no user" is "no filter", and a caller that
        arrives here with None is a caller whose authentication did not happen.
        """
        if not user_id:
            return []
        if limit < 1:
            raise ValueError("limit must be positive")
        owner = _identifier(user_id, label="user_id")
        statement = (
            select(
                runs.c.id,
                runs.c.workflow_id,
                runs.c.status,
                runs.c.inputs,
                runs.c.created_at,
                runs.c.completed_at,
                runs.c.usage,
            )
            .where(runs.c.user_id == owner)
            .order_by(runs.c.created_at.desc())
            .limit(limit)
        )
        with self._connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [dict(row) for row in rows]

    def list_stale_runs(
        self,
        *,
        updated_before: datetime | None = None,
        statuses: Sequence[str] = _LIVE_RUN_STATUSES,
        limit: int = MAX_STALE_RUN_SCAN,
    ) -> list[dict[str, Any]]:
        """Rows that still claim live work, oldest first - the orphan sweeper's input.

        A run interrupted by a process restart leaves no anchor behind: the
        future died with the process and the row keeps saying ``running``. This
        is how the next process finds those rows without waiting for someone to
        ask about one.

        ``updated_before`` is the liveness cut. ``updated_at`` is bumped by
        every persisted frame batch and every status write, so it is a real
        heartbeat rather than a creation timestamp, and filtering on it keeps a
        run that is genuinely executing right now out of the result.

        Deliberately NOT ``get_run``: this scan runs on a maintenance tick and
        must not pay ``get_run``'s per-run frame-statistics and open-gate
        subqueries for every live row. The caller rehydrates the few rows it
        actually acts on.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        wanted = tuple(
            _identifier(_enum_value(status), label="status", limit=32)
            for status in statuses
        )
        if not wanted:
            return []
        statement = select(
            runs.c.id,
            runs.c.status,
            runs.c.flow_id,
            runs.c.session_id,
            runs.c.workflow_id,
            runs.c.created_at,
            runs.c.started_at,
            runs.c.updated_at,
        ).where(runs.c.status.in_(wanted))
        if updated_before is not None:
            statement = statement.where(runs.c.updated_at <= _as_utc(updated_before))
        # created_at, not updated_at: ix_runs_status_created already covers
        # (status, created_at), and the sweeper does not care about the order
        # beyond "oldest interruption first".
        statement = statement.order_by(runs.c.created_at).limit(limit)
        with self._connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            {
                "run_id": row["id"],
                "status": row["status"],
                "flow_id": row["flow_id"],
                "session_id": row["session_id"],
                "workflow_id": row["workflow_id"],
                "created_at": _as_utc(row["created_at"]),
                "started_at": _as_utc(row["started_at"]),
                "updated_at": _as_utc(row["updated_at"]),
            }
            for row in rows
        ]

    def purge_expired_runs(
        self,
        *,
        retention_days: int,
        now: datetime | None = None,
        limit: int = MAX_STALE_RUN_SCAN,
        on_purged: Callable[[str], None] | None = None,
    ) -> int:
        """Delete terminal runs that finished more than ``retention_days`` ago.

        Plan 15 D7. The in-memory eviction (``RunRegistry.evict_stale_runs``)
        never touched a row, so completed runs, their frames, their node
        metrics and their gates accumulated forever - CLAUDE.md closed item 32
        names it. This is the durable half, and it is the only thing in this
        module that deletes a run.

        What it will not delete, each for a reason:

        * anything but ``completed`` / ``failed`` / ``cancelled``. ``waiting``
          above all: a gate answered late is deliberate behaviour, and a run
          parked at a gate is never old enough. ``queued`` / ``running`` /
          ``cancelling`` belong to the orphan sweep, which decides what they
          are before anything decides how old they are.
        * a terminal run that still has an UNANSWERED gate row. That shape
          should not exist - ``_close_interrupted_gate`` answers it - but a
          purge that could take a run out from under an open gate would be the
          exact hazard the plan names, so the predicate refuses it outright
          rather than trusting the sweep that ran before it.
        * ``retention_days == 0``: never, which is the default and the
          deployed behaviour today (PLANS.md decision 23).

        Age is ``completed_at``, falling back to ``updated_at`` for a row that
        reached a terminal status without one. The children go first and by
        name - ``run_frames``, ``run_node_metrics``, ``run_gates`` - for the
        reason ``BuilderDocumentStore.delete`` gives: they carry ``ON DELETE
        CASCADE`` and PostgreSQL honours it, but SQLite only does with a pragma
        this service never sets, so the cascade is done explicitly rather than
        hopefully. Documents, versions, credentials, skills and tools are not
        runs and are never touched.

        Bounded by ``limit`` per call, like every other sweep here, so one
        tick after a long retention change cannot hold a transaction over the
        whole table. ``on_purged`` is told each deleted id after the commit, so
        a caller holding an in-memory copy can let it go.
        """
        days = int(retention_days)
        if days < 0:
            raise ValueError("retention_days cannot be negative")
        if days == 0:
            return 0
        if limit < 1:
            raise ValueError("limit must be positive")
        moment = _as_utc(now) or _utcnow()
        cutoff = moment - timedelta(days=days)
        finished_at = func.coalesce(runs.c.completed_at, runs.c.updated_at)
        open_gate = (
            select(run_gates.c.gate_id)
            .where(
                run_gates.c.run_id == runs.c.id,
                run_gates.c.answered_at.is_(None),
            )
            .exists()
        )
        expired = and_(
            runs.c.status.in_(sorted(_TERMINAL_RUN_STATUSES)),
            finished_at < cutoff,
            ~open_gate,
        )
        purged: list[str] = []
        with self._begin() as connection:
            candidates = connection.execute(
                select(runs.c.id).where(expired).order_by(finished_at).limit(limit)
            ).scalars().all()
            for run_id in candidates:
                # The predicate is repeated on the DELETE, so a row that changed
                # between the SELECT and here - answered, reopened, anything -
                # is left alone by the write rather than by the read.
                result = connection.execute(
                    delete(runs).where(runs.c.id == run_id, expired)
                )
                if result.rowcount != 1:
                    continue
                for child in (run_frames, run_node_metrics, run_gates):
                    connection.execute(delete(child).where(child.c.run_id == run_id))
                purged.append(str(run_id))
        if on_purged is not None:
            for run_id in purged:
                on_purged(run_id)
        if purged:
            logger.info(
                "purged %d terminal run(s) that finished more than %d day(s) ago, "
                "with their frames, node metrics and gates",
                len(purged),
                days,
            )
        return len(purged)

    def get_pending_gate(self, run_id: str) -> dict[str, Any] | None:
        run_id = _identifier(run_id, label="run_id")
        with self._connect() as connection:
            row = connection.execute(
                select(run_gates)
                .where(
                    run_gates.c.run_id == run_id,
                    run_gates.c.answered_at.is_(None),
                )
                .order_by(run_gates.c.opened_at.desc())
                .limit(1)
            ).mappings().one_or_none()
        return self._gate_dict(row) if row is not None else None

    def save_node_metrics(
        self,
        run_id: str,
        node_id: str,
        *,
        model: str = "",
        successful_requests: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        call_count: int = 0,
        elapsed_ms: int = 0,
        cost_usd: Decimal | str | float = Decimal("0"),
    ) -> dict[str, Any]:
        run_id = _identifier(run_id, label="run_id")
        node_id = _identifier(node_id, label="node_id")
        model = str(model)[:255]
        numeric_values = {
            "successful_requests": int(successful_requests),
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "total_tokens": int(total_tokens),
            "call_count": int(call_count),
            "elapsed_ms": int(elapsed_ms),
        }
        if any(value < 0 for value in numeric_values.values()):
            raise ValueError("node metrics cannot be negative")
        values: dict[str, Any] = {
            **numeric_values,
            "cost_usd": Decimal(str(cost_usd)),
            "updated_at": _utcnow(),
        }
        with self._begin() as connection:
            result = connection.execute(
                update(run_node_metrics)
                .where(
                    run_node_metrics.c.run_id == run_id,
                    run_node_metrics.c.node_id == node_id,
                    run_node_metrics.c.model == model,
                )
                .values(**values)
            )
            if result.rowcount == 0:
                connection.execute(
                    insert(run_node_metrics).values(
                        run_id=run_id, node_id=node_id, model=model, **values
                    )
                )
        return {"run_id": run_id, "node_id": node_id, "model": model, **values}

    def get_node_metrics(self, run_id: str) -> list[dict[str, Any]]:
        run_id = _identifier(run_id, label="run_id")
        with self._connect() as connection:
            rows = connection.execute(
                select(run_node_metrics)
                .where(run_node_metrics.c.run_id == run_id)
                .order_by(run_node_metrics.c.node_id, run_node_metrics.c.model)
            ).mappings().all()
        return [
            {
                **dict(row),
                "updated_at": _as_utc(row["updated_at"]),
            }
            for row in rows
        ]

    def _insert_flow_state(
        self,
        connection: Any,
        *,
        flow_uuid: str,
        method_name: str,
        state: dict[str, Any],
        created_at: datetime | None = None,
    ) -> None:
        connection.execute(
            insert(flow_states).values(
                flow_uuid=flow_uuid,
                method_name=method_name,
                created_at=created_at or _utcnow(),
                state=state,
            )
        )

    @classmethod
    def _run_dict(
        cls,
        row: RowMapping,
        frame_stats: RowMapping,
        gate_row: RowMapping | None,
    ) -> dict[str, Any]:
        return {
            "run_id": row["id"],
            "session_id": row["session_id"],
            "workflow_id": row["workflow_id"],
            "flow_id": row["flow_id"],
            "graph_version": row["graph_version"],
            "status": row["status"],
            "inputs": dict(row["inputs"] or {}),
            "created_at": _as_utc(row["created_at"]),
            "started_at": _as_utc(row["started_at"]),
            "completed_at": _as_utc(row["completed_at"]),
            "pending_gate": cls._gate_dict(gate_row) if gate_row is not None else None,
            "frames": {
                "count": int(frame_stats["count"] or 0),
                "captured": int(row["captured_frames"] or 0),
                "dropped": int(row["dropped_frames"] or 0),
                "gaps": int(row["frame_gaps"] or 0),
                "emit_errors": int(row["emit_errors"] or 0),
                "subscriber_dropped": int(row["subscriber_dropped"] or 0),
                "first_seq": frame_stats["first_seq"],
                "last_seq": frame_stats["last_seq"],
            },
            "usage": dict(row["usage"] or {}),
            "result": row["result"],
            "error": row["error"],
        }

    @staticmethod
    def _gate_dict(row: RowMapping) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "gate_id": row["gate_id"],
            "node_id": row["node_id"],
            "status": row["status"],
            "request": dict(row["request"] or {}),
            "response": dict(row["response"]) if row["response"] is not None else None,
            "opened_at": _as_utc(row["opened_at"]),
            "expires_at": _as_utc(row["expires_at"]),
            "answered_at": _as_utc(row["answered_at"]),
        }

    @staticmethod
    def _frame_dict(row: RowMapping) -> dict[str, Any]:
        timestamp = _as_utc(row["ts"])
        rendered_timestamp = timestamp.isoformat(timespec="milliseconds")
        if rendered_timestamp.endswith("+00:00"):
            rendered_timestamp = f"{rendered_timestamp[:-6]}Z"
        result: dict[str, Any] = {
            "v": row["v"],
            "seq": row["seq"],
            "run_id": row["run_id"],
            "ts": rendered_timestamp,
            "kind": row["kind"],
            "event_type": row["event_type"],
            "level": row["level"],
            "node_id": row["node_id"],
            "message": row["message"],
            "details": dict(row["details"] or {}),
        }
        if row["duration_ms"] is not None:
            result["duration_ms"] = row["duration_ms"]
        return result


__all__ = [
    "GateAnswerResult",
    "PersistenceValueError",
    "PostgresFlowPersistence",
    "flow_states",
    "metadata",
    "pending_feedback",
    "run_frames",
    "run_gates",
    "run_node_metrics",
    "runs",
]