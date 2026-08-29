"""SQLAlchemy persistence for CrewAI flow state and durable service runs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import json
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
    String,
    Table,
    Text,
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


if TYPE_CHECKING:
    from crewai.flow.async_feedback.types import PendingFeedbackContext


MAX_JSON_BYTES = 1_048_576
MAX_JSON_DEPTH = 16
MAX_CONTAINER_ITEMS = 10_000
MAX_STRING_LENGTH = 65_536
MAX_ERROR_LENGTH = 4096
MAX_FRAME_REPLAY = 500
MAX_OPEN_GATE_SCAN = 500

_UNSET = object()
_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})
# F03/R-2 watch ladder for an unanswered gate: open -> expired -> alerted.
_GATE_WATCH_STATUSES = frozenset({"expired", "alerted"})
_SECRET_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "clientsecret",
        "cookie",
        "password",
        "privatekey",
        "refreshtoken",
        "secret",
        "setcookie",
        "token",
        "accesstoken",
    }
)
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
    Column("workflow_id", String(128), nullable=False),
    Column("flow_id", String(128)),
    Column("graph_version", String(128), nullable=False),
    Column("status", String(32), nullable=False),
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


def _normalize_secret_key(key: str) -> str:
    return "".join(character for character in key.lower() if character.isalnum())


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
                sanitized[normalized_key] = "[REDACTED]"
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

    @property
    def engine(self) -> Engine:
        """Return the SQLAlchemy engine without exposing its URL in model data."""
        return self._engine

    def init_db(self) -> None:
        """Create the flow and service persistence schema if it is absent."""
        metadata.create_all(self._engine)

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
    ) -> None:
        flow_uuid = _identifier(flow_uuid, label="flow_uuid")
        if _identifier(context.flow_id, label="context.flow_id") != flow_uuid:
            raise ValueError("pending feedback flow_id must match flow_uuid")
        state = _state_dict(state_data)
        context_data = _bounded_json(context.to_dict(), label="pending feedback")
        now = _utcnow()

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
        status: Any = "queued",
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        run_id = _identifier(run_id or uuid.uuid4(), label="run_id")
        session_id = _identifier(session_id, label="session_id")
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