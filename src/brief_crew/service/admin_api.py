"""`/api/admin` - one screen's worth of read API, and two levers (plan 17).

Three questions an owner has, answered over rows this repository already
holds: *are we burning money faster than expected*, *who is here and what did
they do*, *what is the product deciding and is it healthy*. There is no
warehouse, no sync job and no copied table - `run_node_metrics` (PK
`(run_id, node_id, model)`, `cost_usd NUMERIC(12,6)`, joined to `runs.user_id`)
has been a complete FinOps store since the day it shipped and exactly one
`SUM` read it. So this module adds no table, no column and no migration.

FIVE RULES DECIDE ALMOST EVERY LINE BELOW
-----------------------------------------
* **404, never 403 - on every route but one.** `require_admin` raises
  FastAPI's own unknown-route body byte for byte, so an admin route and a
  route that does not exist are indistinguishable to anybody who is not an
  admin. A 403 would advertise the surface; see plan 17 section 9, risk 9.
  The one exception is `GET /whoami`, which answers 200 `admin: false`
  because the home page probes it on every load and a 404 there is a console
  error on every non-admin's every page - for a fact the JavaScript bundle
  already publishes. `AdminWhoamiModel` carries the full reasoning.
* **No JSON path is ever written in SQL.** `persistence.user_spend_usd` sums a
  `Numeric` column rather than the `usage` JSON precisely because the path is
  spelled differently on SQLite and PostgreSQL. Every JSON here -
  `run_gates.response`, a VERDICT frame's `details` - is selected as a column
  and read in Python. The day bucket obeys the same rule: `spend_by_day`
  groups by `runs.id` in SQL and buckets by UTC day in Python, rather than
  choosing between `strftime` and `date_trunc`.
* **Per-user counts are nine grouped queries merged in Python, not one join.**
  A `LEFT JOIN` of `runs` to six one-to-many tables multiplies rows and every
  `COUNT` comes out wrong. This is not a hot path.
* **`runs.user_id IS NULL` collapses to `"__unowned__"` everywhere** - never
  dropped, never merged with a real account. Pre-auth rows and every run made
  on a deployment with no identity are real spend and have to appear
  somewhere.
* **Any upstream that cannot answer is a 200 carrying
  `{"available": false, "reason": ...}`**, never a 500. A dashboard whose own
  health tile is the thing that breaks it is worse than no dashboard.

THE `"user"` TABLE
------------------
Better Auth's `user` table is in the same database and `runs.user_id` **is**
`user.id` verbatim, so the e-mail this console shows comes from a join. It is
declared on **a separate `MetaData()`** and never on `persistence.metadata`,
whose `create_all()` would then create a table Better Auth owns in another
language with another migration tool. `"user"` is a reserved word and its
columns are camelCase, so every identifier is quoted (SQLAlchemy quotes what
it is given verbatim). Presence is checked once per engine with
`inspect(engine).has_table("user")`; absent - SQLite tests, a bare checkout -
every row answers `email: null, name: null` and nothing else changes.

NO `from __future__ import annotations` here, for the reason `builder_api.py`
gives: FastAPI resolves handler annotations against module globals, and
`Depends`, `Query` and `Response` are imported inside the factory because
FastAPI is an optional dependency of this package.
"""

import base64
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
from statistics import median
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, DateTime, MetaData, String, Table, func, select

from brief_crew import config

__all__ = [
    "ADMIN_API_PREFIX",
    "UNOWNED",
    "AdminBilledModel",
    "AdminDecisionsModel",
    "AdminGatesModel",
    "AdminHealthModel",
    "AdminLinksModel",
    "AdminProvidersModel",
    "AdminRunsModel",
    "AdminSpendModel",
    "AdminSummaryModel",
    "AdminUserDetailModel",
    "AdminUsersModel",
    "AdminVerdictsModel",
    "AdminWhoamiModel",
    "LangfuseRunLinks",
    "auth_profiles",
    "auth_user",
    "create_admin_router",
    "decode_cursor",
    "encode_cursor",
    "gate_outcome",
    "langfuse_links",
]

#: Under `/api`, so the CORS middleware, the body limit and the client's own
#: `authedFetch` all reach it the way they reach every other route.
ADMIN_API_PREFIX = "/api/admin"

#: The reserved key a run with no owner is grouped under. Imported from
#: `config` and never re-typed: `service/persistence.py` groups on the same
#: value in SQL, and two spellings of it would mean the SQL grouped one way
#: and the HTTP layer read another.
UNOWNED = config.ADMIN_UNOWNED_KEY

#: What the measured reconciliation found the app's estimate to be worth, so
#: every dollar on screen can carry its own error band. Row E5 of the
#: observability programme: three of seven priced runs were out by this much
#: against OpenRouter's own billed figures.
SPEND_ERROR_NOTE = "measured -14.5% to +9.95% against billed"

#: What the verdict tile is hostage to (plan 17 risk 3).
VERDICT_NOTE = (
    "read from run frames; a raised VALIDATOR_RUN_RETENTION_DAYS deletes these"
)

#: What the console cannot see, in the words the Health panel prints. A blank
#: tile must never be read as a zero (plan 17 risk 14): none of these is
#: recorded by either server, so the console is not reporting none of them -
#: it is blind to them.
BLIND_TO = (
    "sign-ins and sign-outs: Better Auth writes a session row, not an event log",
    "page views: nothing on either origin records one",
    "request latency and uptime history: no metrics store on either server",
    "CLI runs (validate --idea): they never enter the service, so they have "
    "no run id and no row here",
    "embedding, rerank and Firecrawl DOLLARS: none of the three raises an LLM "
    "event, so no figure on this console includes them",
)


# ---------------------------------------------------------------------------
# Response models. Every one is `extra="forbid"`, so a field added to a handler
# without being added here is a failure in this process rather than a key that
# quietly appears on the wire and quietly disappears again.
# ---------------------------------------------------------------------------


class AdminModel(BaseModel):
    """The base every admin response shares."""

    model_config = ConfigDict(extra="forbid")


class AdminWhoamiModel(AdminModel):
    """The ONE route that answers everybody, and the one documented exception.

    Every other admin route answers FastAPI's own 404 to anybody who is not an
    admin. This one answers **200 with `admin: false`**, and the reason is
    measured rather than stylistic: the home page probes it on every load for
    every signed-in person, so a 404 is a `Failed to load resource: 404` in
    the browser console of every non-admin - and 113 of 145 non-`@launch` E2E
    tests tolerate zero console errors, in the DEFAULT configuration where
    `ADMIN_EMAILS` is unset.

    Nothing is hidden by refusing it. The admin surface's existence is already
    public in the JavaScript bundle that draws the link; what has to be
    invisible is the DATA - who is here, what they spent, what they typed into
    a gate - and every route carrying any of that keeps the byte-identical
    404. So the probe is public and says no, and the thirteen reads and the
    two levers behave as if they do not exist.

    It is also the only route with no SQL.
    """

    admin: bool
    user_id: str | None
    email: str | None


class RunStatusCounts(AdminModel):
    """`GROUP BY runs.status`, with every status present at zero.

    Named fields rather than a free dictionary so a status that stops being
    written - or one that starts - fails a test here instead of making a tile
    silently narrower.
    """

    queued: int = 0
    running: int = 0
    waiting: int = 0
    completed: int = 0
    failed: int = 0
    cancelling: int = 0
    cancelled: int = 0


class RefusalCounts(AdminModel):
    """Runs stopped by a spend rule, counted off the durable `error` column.

    Both prefixes are IMPORTED from `service/registry.py` rather than typed
    here; criterion 8 patches the constant and asserts the count moves, which
    is what proves no literal was copied.
    """

    account_cap: int = 0
    run_ceiling: int = 0


class SpendDay(AdminModel):
    """One UTC day, bucketed in Python - never `strftime` or `date_trunc`."""

    day: str
    usd: float
    runs: int


class TopAccount(AdminModel):
    user_id: str
    email: str | None
    spent_usd: float
    committed_usd: float
    cap_usd: float | None
    exempt: bool


class AttentionItem(AdminModel):
    """Something a person has to do, not something that is wrong."""

    kind: str
    run_id: str
    hours: float


class AdminSummaryModel(AdminModel):
    spend_usd_estimate: float
    #: Always `true`. A constant on the wire rather than a comment in a
    #: document, because the one thing that must never happen is somebody
    #: taking an irreversible decision from this figure believing it is a bill.
    estimate: bool = True
    error_note: str = SPEND_ERROR_NOTE
    runs: RunStatusCounts
    people_active: int
    people_total: int
    people_new: int
    refusals: RefusalCounts
    spend_by_day: list[SpendDay] = Field(default_factory=list)
    top_accounts: list[TopAccount] = Field(default_factory=list)
    attention: list[AttentionItem] = Field(default_factory=list)
    truncated: bool = False


class SpendRow(AdminModel):
    key: str
    label: str
    cost_usd: float
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    call_count: int
    runs: int


class AdminSpendModel(AdminModel):
    group_by: str
    estimate: bool = True
    error_note: str = SPEND_ERROR_NOTE
    rows: list[SpendRow] = Field(default_factory=list)
    total_usd: float = 0.0
    truncated: bool = False


class UserRow(AdminModel):
    """One account, assembled from nine grouped queries.

    `committed_usd` is the headroom promised to this account's live runs and
    is **memory-only** - it is lost on a restart, which is why it travels
    beside its own `committed_is_volatile` flag rather than being folded into
    a single headline figure (plan 17 risk 5).
    """

    user_id: str
    email: str | None
    name: str | None
    created_at: str | None
    last_run_at: str | None
    last_session_at: str | None
    runs: int
    spent_usd: float
    committed_usd: float
    committed_is_volatile: bool = True
    cap_usd: float | None
    exempt: bool
    documents: int
    published: int
    credentials: int
    skills: int
    tools: int
    mcp_servers: int
    firecrawl_today: int


class AdminUsersModel(AdminModel):
    rows: list[UserRow] = Field(default_factory=list)
    next: str | None = None


class GateStats(AdminModel):
    answered: int
    expired: int
    median_seconds: float | None


class LangfuseUserLink(AdminModel):
    """Deliberately always null today.

    Langfuse's metrics v2 restricts `userId` from GROUPING - it is a filter
    only - so there is no per-user view to link to and no per-user aggregate
    to take from it (plan 17 section 4B, risk 6). The key exists so the client
    does not have to grow a branch on the day there is one.
    """

    user_url: str | None = None


class RunIntegrity(AdminModel):
    captured: int
    dropped: int
    gaps: int


class LangfuseRunLinks(AdminModel):
    session_url: str | None = None
    trace_url: str | None = None


class RunRow(AdminModel):
    run_id: str
    user_id: str
    email: str | None
    workflow_id: str
    mode: str
    status: str
    created_at: str
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    cost_usd: float
    ceiling_kind: str
    max_cost_usd: float | None
    account_cap_usd: float | None
    stop_reason: str | None
    error: str | None
    verdict: str | None
    integrity: RunIntegrity
    langfuse: LangfuseRunLinks


class AdminRunsModel(AdminModel):
    rows: list[RunRow] = Field(default_factory=list)
    next: str | None = None


class AdminUserDetailModel(UserRow):
    gates: GateStats
    recent_runs: list[RunRow] = Field(default_factory=list)
    langfuse: LangfuseUserLink = Field(default_factory=LangfuseUserLink)


class GateDecision(AdminModel):
    """One gate, with the operator's reply **verbatim**.

    This is the one view Langfuse cannot give: the words a person typed and
    the fields they edited are hashed there by the content policy, on purpose.
    Here they are the point.
    """

    gate_id: str
    node_id: str
    status: str
    opened_at: str
    answered_at: str | None
    seconds: float | None
    outcome: str | None
    response: dict[str, Any] | None


class GuardrailRetry(AdminModel):
    guardrail: str
    guardrail_type: str | None
    retry_count: int
    node_id: str


class FallbackModel(AdminModel):
    node_id: str
    fallback_model: str
    attempt: int | None


class AdminDecisionsModel(AdminModel):
    run_id: str
    gates: list[GateDecision] = Field(default_factory=list)
    guardrails: list[GuardrailRetry] = Field(default_factory=list)
    fallback_models: list[FallbackModel] = Field(default_factory=list)
    verdict: dict[str, Any] | None = None
    langfuse: LangfuseRunLinks = Field(default_factory=LangfuseRunLinks)


class GateBucket(AdminModel):
    gate_id: str
    count: int
    median_seconds: float | None
    expired: int


class AdminGatesModel(AdminModel):
    approve: int = 0
    revise: int = 0
    expired: int = 0
    unanswered: int = 0
    median_seconds: float | None = None
    by_gate: list[GateBucket] = Field(default_factory=list)
    truncated: bool = False


class VerdictRow(AdminModel):
    verdict: str
    count: int


class AdminVerdictsModel(AdminModel):
    #: False whenever `VALIDATOR_RUN_RETENTION_DAYS > 0`, because a purge
    #: cascades to `run_frames` and takes these with it.
    complete: bool = True
    rows: list[VerdictRow] = Field(default_factory=list)
    note: str = VERDICT_NOTE
    truncated: bool = False


class HealthIntegrity(AdminModel):
    captured: int
    dropped: int
    gaps: int
    emit_errors: int
    subscriber_dropped: int
    runs_with_drop: int


class HealthCeilings(AdminModel):
    run_usd: float
    account_usd: float
    margin: float
    firecrawl_daily: int


class AdminHealthModel(AdminModel):
    #: `/readyz`'s own body, produced by the SAME `health_payload` and
    #: `exporter_state` calls the route makes - never a restatement of either.
    readyz: dict[str, Any]
    integrity: HealthIntegrity
    orphans: int
    retention_days: int
    ceilings: HealthCeilings
    #: What this console cannot see, in words, so a blank tile never implies
    #: zero (plan 17 risk 14).
    blind_to: list[str] = Field(default_factory=list)


class LangfuseLinkConfig(AdminModel):
    base_url: str
    project_id: str
    configured: bool


class AdminLinksModel(AdminModel):
    langfuse: LangfuseLinkConfig
    openrouter_activity_url: str
    openrouter_credits_url: str
    firecrawl_dashboard_url: str


class OpenRouterProbe(AdminModel):
    available: bool
    reason: str | None = None
    #: `credits` (a management key answered `/api/v1/credits`) or `key` (the
    #: ordinary inference key answered `/api/v1/key`). The tile SAYS which,
    #: because the two measure different things: credits is the account
    #: balance, key is one key's usage against its own limit.
    source: str | None = None
    total_credits: float | None = None
    total_usage: float | None = None
    remaining_usd: float | None = None
    usage: float | None = None
    limit: float | None = None
    limit_remaining: float | None = None
    is_free_tier: bool | None = None
    label: str | None = None
    checked_at: str | None = None
    age_seconds: float | None = None


class FirecrawlProbe(AdminModel):
    available: bool
    reason: str | None = None
    remaining_credits: int | None = None
    plan_credits: int | None = None
    billing_period_start: str | None = None
    billing_period_end: str | None = None
    checked_at: str | None = None
    age_seconds: float | None = None


class LangfuseProbe(AdminModel):
    """Local, and no outbound call: `exporter_state` plus the project id."""

    available: bool
    reason: str | None = None
    exporter: str | None = None
    environment: str | None = None
    project_configured: bool = False


class AdminProvidersModel(AdminModel):
    openrouter: OpenRouterProbe
    firecrawl: FirecrawlProbe
    langfuse: LangfuseProbe


class AdminBilledModel(AdminModel):
    """What Langfuse says one run cost, fetched **on an explicit click only**.

    Never on page load: it is one to five outbound requests per run and the
    estimate beside it is already on screen.
    """

    available: bool
    reason: str | None = None
    run_id: str
    generations: int = 0
    billed_usd: float | None = None
    estimate_usd: float = 0.0
    delta_pct: float | None = None
    cost_source_counts: dict[str, int] = Field(default_factory=dict)
    #: Generations per model, off whichever key the v2 row carries the name
    #: in - `model` is Langfuse's RESOLVED model and is null for an
    #: `openrouter/...` string, so `providers._MODEL_KEYS` reads four
    #: candidates in order. Additive: the panel may ignore it.
    model_counts: dict[str, int] = Field(default_factory=dict)
    session_url: str | None = None
    trace_url: str | None = None
    fetched_at: str | None = None


# ---------------------------------------------------------------------------
# Deep links
# ---------------------------------------------------------------------------


def langfuse_links(run_id: str) -> LangfuseRunLinks:
    """The session and trace URLs for one run, or two nulls.

    `trace_id_for` is **imported**, never re-derived. It is the exporter's own
    rule - the run id's UUID hex, else the SDK's seeded id, else a sha256
    prefix - and a second spelling of it here would be a link that resolves to
    nothing for exactly the runs whose ids are not UUIDs, which is the case
    nobody would test.

    Both are `None` unless a project id is configured, because a URL built
    without one 404s in somebody's browser and looks like the console lying.
    """

    project = config.LANGFUSE_PROJECT_ID
    if not project or not run_id:
        return LangfuseRunLinks()
    from brief_crew.observability.backend import trace_id_for

    host = (config.LANGFUSE_BASE_URL or "").rstrip("/")
    base = f"{host}/project/{project}"
    return LangfuseRunLinks(
        session_url=f"{base}/sessions/{run_id}",
        trace_url=f"{base}/traces/{trace_id_for(run_id)}",
    )


# ---------------------------------------------------------------------------
# Better Auth's `user` table, on a MetaData of its own
# ---------------------------------------------------------------------------

#: **A SEPARATE `MetaData()`, and that is the whole point of this block.**
#:
#: Declaring `user` on `persistence.metadata` would put it in the set
#: `metadata.create_all()` creates, and `init_db()` runs on every boot - so
#: this service would create, on a fresh database, a table Better Auth owns in
#: another language with another migration tool, with columns this file
#: guessed. The Node service would then migrate on top of it or fail, and
#: which of the two you got would depend on which service booted first.
#:
#: `"user"` is a reserved word in PostgreSQL and its columns are camelCase, so
#: every identifier is quoted - SQLAlchemy quotes what it is given verbatim,
#: which is why the names here are spelled exactly as Better Auth spells them
#: rather than in this repository's snake_case.
#:
#: Only the four columns this console reads are declared. A table object is a
#: description of what to SELECT, not a schema, and describing columns nobody
#: reads would be inventing facts about somebody else's table.
_AUTH_METADATA = MetaData()
auth_user = Table(
    "user",
    _AUTH_METADATA,
    Column("id", String(128), primary_key=True),
    Column("email", String(255)),
    Column("name", String(255)),
    Column("createdAt", DateTime(timezone=True)),
)
auth_session = Table(
    "session",
    _AUTH_METADATA,
    Column("id", String(128), primary_key=True),
    Column("userId", String(128)),
    Column("updatedAt", DateTime(timezone=True)),
)


def _has_table(engine: Any, name: str) -> bool:
    """Whether this database carries the table, asked once and never assumed.

    Absent is the ordinary case, not an error: SQLite in every test, a bare
    checkout, and any deployment whose Node half has not migrated yet. The
    console then answers `email: null, name: null` and nothing else changes -
    a join to a table that is not there would be a 500 on every page.
    """

    try:
        from sqlalchemy import inspect as sqla_inspect

        return bool(sqla_inspect(engine).has_table(name))
    except Exception:  # pragma: no cover - a dialect that cannot introspect
        return False


def auth_profiles(persistence: Any, user_ids: Sequence[str] | None = None) -> dict[str, dict[str, Any]]:
    """The ninth query of `/users`: e-mail, name, joined-at, last session.

    Two SELECTs and no join to anything of ours, because `runs.user_id` **is**
    `user.id` verbatim and the merge is a dictionary lookup in Python - the
    same rule the other eight obey.
    """

    engine = getattr(persistence, "engine", None)
    if engine is None or not _has_table(engine, "user"):
        return {}
    wanted = [str(user_id) for user_id in (user_ids or []) if user_id and user_id != UNOWNED]
    if user_ids is not None and not wanted:
        return {}
    statement = select(
        auth_user.c.id,
        auth_user.c.email,
        auth_user.c.name,
        auth_user.c.createdAt,
    )
    if wanted:
        statement = statement.where(auth_user.c.id.in_(wanted))
    profiles: dict[str, dict[str, Any]] = {}
    with persistence.connect() as connection:
        for row in connection.execute(statement).mappings().all():
            profiles[str(row["id"])] = {
                "email": row["email"],
                "name": row["name"],
                "created_at": _iso(row["createdAt"]),
                "last_session_at": None,
            }
        if _has_table(engine, "session"):
            sessions = select(
                auth_session.c.userId, func.max(auth_session.c.updatedAt)
            ).group_by(auth_session.c.userId)
            if wanted:
                sessions = sessions.where(auth_session.c.userId.in_(wanted))
            for user_id, last in connection.execute(sessions).all():
                if str(user_id) in profiles:
                    profiles[str(user_id)]["last_session_at"] = _iso(last)
    return profiles


def auth_people_counts(
    persistence: Any, *, start: datetime | None, end: datetime | None
) -> tuple[int, int]:
    """`(people_total, people_new)` off `"user"."createdAt"`, or `(0, 0)`.

    Zeroes when the table is absent, and the Health panel's `blind_to` list is
    what stops a reader taking that as "nobody has signed up".
    """

    engine = getattr(persistence, "engine", None)
    if engine is None or not _has_table(engine, "user"):
        return 0, 0
    with persistence.connect() as connection:
        total = int(
            connection.execute(select(func.count()).select_from(auth_user)).scalar_one() or 0
        )
        fresh = select(func.count()).select_from(auth_user)
        if start is not None:
            fresh = fresh.where(auth_user.c.createdAt >= start)
        if end is not None:
            fresh = fresh.where(auth_user.c.createdAt < end)
        new = int(connection.execute(fresh).scalar_one() or 0)
    return total, new


# ---------------------------------------------------------------------------
# Small pure helpers, all of them Python where the alternative was SQL
# ---------------------------------------------------------------------------


def _iso(moment: Any) -> str | None:
    """A datetime as the `Z`-suffixed ISO string every other frame here uses."""

    if moment is None:
        return None
    if isinstance(moment, str):
        return moment
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    text = moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    return text.replace("+00:00", "Z")


def _money(value: Any) -> float:
    """A `Numeric` column as a float, at the cent-and-beyond precision money needs.

    `Decimal` all the way through the arithmetic and `float` only at the wire,
    because JSON has no decimal type and every sum has already been taken.
    """

    if value is None:
        return 0.0
    return float(Decimal(str(value)))


def encode_cursor(created_at: Any, row_id: str) -> str:
    """The opaque keyset cursor: base64url of `"<created_at ISO>|<id>"`.

    Opaque so no client builds one, and so the shape can change; base64url so
    it survives a query string with no escaping. It is NOT a signature and
    does not need to be - the worst a tampered cursor can do is page from a
    different place in a list the caller is already allowed to read, and a
    malformed one is a 422 rather than a 500.
    """

    raw = f"{_iso(created_at)}|{row_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """The inverse, raising `ValueError` on anything that is not one."""

    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - every decode failure is equal
        raise ValueError("cursor is not valid") from exc
    moment, _, row_id = raw.partition("|")
    if not moment or not row_id:
        raise ValueError("cursor is not valid")
    try:
        parsed = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("cursor is not valid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, row_id


def gate_outcome(response: Mapping[str, Any] | None) -> str | None:
    """The operator's decision, read out of the reply **in Python**.

    `run_gates.response` is JSON and the path to a key inside it is spelled
    `->>` on PostgreSQL and `json_extract` on SQLite. Reading it here rather
    than in the SELECT is the rule this module opens with, and this is the
    place it would have been most tempting to break.
    """

    if not response:
        return None
    for key in ("decision", "outcome"):
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def median_or_none(values: Sequence[float]) -> float | None:
    """`statistics.median`, or `None` for an empty sample.

    `None` rather than `0`: a gate cohort nobody has answered has no median,
    and a zero would draw as "answered instantly" on exactly the tile that
    exists to find the ones nobody answered.
    """

    if not values:
        return None
    return round(float(median(sorted(values))), 3)


def _window(
    since: str | None, until: str | None
) -> tuple[datetime, datetime]:
    """The `?from=`/`?to=` pair, defaulted and bounded, or a `ValueError`.

    Refused above `ADMIN_MAX_WINDOW_DAYS` rather than silently clamped: a
    dashboard that answers a different question from the one asked, without
    saying so, is how a figure gets quoted for the wrong period.
    """

    now = datetime.now(timezone.utc)

    def parse(value: str, name: str) -> datetime:
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"{name} must be an ISO-8601 UTC timestamp, for example "
                "2026-09-01T00:00:00Z"
            ) from exc
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)

    end = parse(until, "to") if until else now
    start = (
        parse(since, "from")
        if since
        else end - timedelta(days=config.ADMIN_DEFAULT_WINDOW_DAYS)
    )
    if start > end:
        raise ValueError("from must not be later than to")
    span = (end - start).days
    if span > config.ADMIN_MAX_WINDOW_DAYS:
        raise ValueError(
            f"the window is limited to {config.ADMIN_MAX_WINDOW_DAYS} days; "
            f"this one is {span}"
        )
    return start, end


def _verdict_of(details: Mapping[str, Any]) -> str | None:
    """The verdict word out of a VERDICT frame's `details`, parsed in Python."""

    for key in ("verdict", "result"):
        value = details.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            inner = value.get("verdict")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return None


def _document_model(stored: Any) -> Any:
    """One stored document as `BuilderDocumentModel`, for the unpublish lever.

    It composes the SAME public builder functions `builder_api.judged` does -
    `document_problems`, `estimate_budget`, `builder_graph_descriptor`,
    `builder_workflow` - and deliberately runs NONE of the four owner-scoped
    attachment checks (credential, custom tool, MCP server, skill).

    That omission is correct rather than convenient, and it is the one place
    an admin response legitimately differs from the author's own. Those four
    ask "does THIS caller own the credential this node names", and this
    caller is an admin acting on somebody else's graph: running them here
    would report the ADMIN's missing credentials as problems with the
    AUTHOR's document. The author sees the full list on their own canvas,
    where the question means something.
    """

    from brief_crew.builder import estimate_budget
    from brief_crew.builder.compiler import document_problems
    from brief_crew.builder.descriptor import builder_graph_descriptor
    from brief_crew.service.builder_api import (
        BuilderBudgetModel,
        BuilderDocumentModel,
        BuilderProblemModel,
    )
    from brief_crew.service.graph import builder_workflow

    live = builder_workflow(stored.id)
    problems = document_problems(stored.document)
    return BuilderDocumentModel(
        id=stored.id,
        document=stored.document.model_dump(mode="json", by_alias=True),
        status=stored.status,
        version=stored.document.version,
        head_version=stored.head_version,
        created_at=stored.created_at,
        updated_at=stored.updated_at,
        problems=[BuilderProblemModel.of(problem) for problem in problems],
        budget=BuilderBudgetModel.of(estimate_budget(stored.document)),
        graph=builder_graph_descriptor(stored.document),
        published=bool(live) and live.document.version == stored.document.version,
        live_version=live.document.version if live else None,
    )


# ---------------------------------------------------------------------------
# The router
# ---------------------------------------------------------------------------


def create_admin_router(
    *,
    resolve_user: Callable[..., Any],
    registry: Any,
    persistence_factory: Callable[[], Any],
    store_factory: Callable[[], Any],
    health_payload: Callable[..., tuple[dict[str, Any], int]],
    exporter_state_for: Callable[[], dict[str, Any]],
    providers: Any = None,
) -> Any:
    """The `/api/admin` router, closed over the app's own dependencies.

    A factory rather than a module-level `APIRouter`, matching
    `create_builder_router` and `create_credentials_router`: the registry, the
    persistence and the user dependency are per-application.

    `resolve_user` is `optional_user` and NOT `current_user` - see `admin`
    below. Plan 17 section 6 names `current_user`; criterion 4 requires an
    anonymous caller to get the same 404 as everybody else, and only the
    optional resolver can deliver that.

    `health_payload` and `exporter_state_for` are INJECTED rather than
    reimplemented, which is criterion 13: `/api/admin/health` has to answer
    what `/readyz` answers, and the only way to guarantee that is for both to
    call the same two functions with the same arguments. A copy would agree on
    the day it was written.

    `providers` is the probe cache (`service/providers.py`); a test passes a
    double, and `None` builds the real one lazily on first use so an app that
    never opens the console makes no client.
    """

    from fastapi import APIRouter, Depends, HTTPException, Query
    from fastapi.concurrency import run_in_threadpool

    from brief_crew.service.auth import require_admin

    # The MODULE, and every prefix read off it at CALL time - never bound into
    # a local at import. Two reasons, and the second is the load-bearing one:
    # a name bound here is bound when the app is built, so a deployment that
    # reworded a stop sentence would keep counting the old one until a
    # restart; and criterion 8's proof is `patch.object(registry, PREFIX, ...)`
    # changing the count, which is the ONLY construction that can tell an
    # import from a re-typed literal. A copy of the string would pass a test
    # that merely seeded the current sentence.
    from brief_crew.service import registry as registry_module

    router = APIRouter(prefix=ADMIN_API_PREFIX, tags=["admin"])
    logger = logging.getLogger(__name__)

    def admin(user: Any = Depends(resolve_user)) -> Any:
        """Every route's only dependency. 404 for everybody who is not one.

        `resolve_user` is `app.py`'s **`optional_user`**, not its
        `current_user`, and the difference is criterion 4. `current_user`
        raises 401 for a caller with no credential when authentication is
        required - which happens BEFORE this function runs, so an anonymous
        caller would get "sign in to use this endpoint" from an admin route
        and `{"detail": "Not Found"}` from an unknown one. The two answers
        would be distinguishable, which is the one property this gate exists
        to deny. A token that IS offered is still verified and a bad one is
        still refused with the 401 `optional_user` writes; what changes is
        that offering nothing is not a different kind of refusal here.
        """

        return require_admin(user)

    def store() -> Any:
        persistence = persistence_factory()
        if persistence is None:
            raise HTTPException(
                status_code=503,
                detail="this service has no durable store, so there is nothing to read",
            )
        return persistence

    def probes() -> Any:
        nonlocal providers
        if providers is None:
            from brief_crew.service.providers import ProviderProbes

            providers = ProviderProbes()
        return providers

    def window(since: str | None, until: str | None) -> tuple[datetime, datetime]:
        try:
            return _window(since, until)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def page_limit(limit: int) -> int:
        return max(1, min(int(limit), config.ADMIN_PAGE_LIMIT_MAX))

    def cursor_of(cursor: str | None) -> tuple[datetime, str] | None:
        if not cursor:
            return None
        try:
            return decode_cursor(cursor)
        except ValueError as exc:
            # 422 and not 500: a tampered or stale cursor is a bad request,
            # and the remedy is to ask for the first page again.
            raise HTTPException(status_code=422, detail="cursor is not valid") from exc

    def stop_reason_of(error: Any) -> str | None:
        """IMPORTED, never re-typed - criterion 8.

        `registry._restored_stop_reason` is the one place that knows which
        prefix means which stop, and it is the same function
        `_restore_record` uses when a run comes back after a restart. A second
        copy here would be a second answer to "why did this run stop", and the
        two would disagree the first time a sentence was reworded.
        """

        return registry_module._restored_stop_reason(error)

    def run_rows(rows: Sequence[Mapping[str, Any]], *, verdicts: Mapping[str, str] | None = None) -> list[RunRow]:
        persistence = store()
        costs = persistence.admin_run_costs([row["run_id"] for row in rows])
        owners = [row["user_id"] for row in rows if row["user_id"]]
        profiles = auth_profiles(persistence, owners) if owners else {}
        built: list[RunRow] = []
        for row in rows:
            owner = row["user_id"]
            started = row["started_at"]
            finished = row["completed_at"]
            duration = (
                int((finished - started).total_seconds() * 1000)
                if started and finished
                else None
            )
            built.append(
                RunRow(
                    run_id=row["run_id"],
                    user_id=owner or UNOWNED,
                    email=(profiles.get(owner or "") or {}).get("email"),
                    workflow_id=row["workflow_id"],
                    mode=row["mode"],
                    status=row["status"],
                    created_at=_iso(row["created_at"]) or "",
                    started_at=_iso(started),
                    completed_at=_iso(finished),
                    duration_ms=duration,
                    cost_usd=_money(costs.get(row["run_id"], 0)),
                    ceiling_kind=row["ceiling_kind"],
                    max_cost_usd=(
                        _money(row["max_cost_usd"])
                        if row["max_cost_usd"] is not None
                        else None
                    ),
                    account_cap_usd=(
                        _money(row["account_cap_usd"])
                        if row["account_cap_usd"] is not None
                        else None
                    ),
                    stop_reason=stop_reason_of(row["error"]),
                    error=row["error"],
                    verdict=(verdicts or {}).get(row["run_id"]),
                    integrity=RunIntegrity(
                        captured=row["captured_frames"],
                        dropped=row["dropped_frames"],
                        gaps=row["frame_gaps"],
                    ),
                    langfuse=langfuse_links(row["run_id"]),
                )
            )
        return built

    def verdicts_for(run_ids: Sequence[str]) -> dict[str, str]:
        """The VERDICT frame of each of these runs, `details` parsed in Python.

        In retention, and it says so on the tile: a purge cascades to
        `run_frames` and takes these with it (plan 17 risk 3). The durable fix
        is a `runs.verdict` column, which is Phase 2.
        """

        if not run_ids:
            return {}
        frames, _ = store().admin_frames_by_kind(
            ["verdict"], run_ids=list(run_ids), limit=config.ADMIN_MAX_SCAN_ROWS
        )
        found: dict[str, str] = {}
        for frame in frames:
            verdict = _verdict_of(frame["details"])
            if verdict:
                found[frame["run_id"]] = verdict
        return found

    def user_rows(
        totals: Mapping[str, Mapping[str, Any]], profiles: Mapping[str, Mapping[str, Any]]
    ) -> list[UserRow]:
        built: list[UserRow] = []
        for user_id, totals_row in totals.items():
            profile = profiles.get(user_id, {})
            email = profile.get("email")
            # An unowned bucket is not an account: it has no cap, is not
            # exempt from one, and `account_spend` would answer zeroes for it.
            real = user_id != UNOWNED
            cap = config.user_spend_cap_usd(user_id, email) if real else None
            committed = (
                float(registry.account_spend(user_id).get("committed", 0.0))
                if real and hasattr(registry, "account_spend")
                else 0.0
            )
            built.append(
                UserRow(
                    user_id=user_id,
                    email=email,
                    name=profile.get("name"),
                    created_at=profile.get("created_at"),
                    last_run_at=_iso(totals_row["last_run_at"]),
                    last_session_at=profile.get("last_session_at"),
                    runs=totals_row["runs"],
                    spent_usd=_money(totals_row["spent_usd"]),
                    committed_usd=round(committed, 6),
                    committed_is_volatile=True,
                    cap_usd=cap,
                    exempt=real and cap is None,
                    documents=totals_row["documents"],
                    published=totals_row["published"],
                    credentials=totals_row["credentials"],
                    skills=totals_row["skills"],
                    tools=totals_row["tools"],
                    mcp_servers=totals_row["mcp_servers"],
                    firecrawl_today=totals_row["firecrawl_today"],
                )
            )
        return built

    # -- the routes ---------------------------------------------------------

    @router.get("/whoami", response_model=AdminWhoamiModel)
    async def whoami(user: Any = Depends(resolve_user)) -> AdminWhoamiModel:
        """The ONE documented exception to the 404 rule - see the model above.

        `Depends(resolve_user)` and NOT `Depends(admin)`: this route answers
        everybody, with `admin: false` for an anonymous caller, for a signed-in
        non-admin and for an empty `ADMIN_EMAILS` alike. The home page probes
        it on every load, and a 404 there is a console error on every
        non-admin's every page for a fact the JavaScript bundle already
        publishes. The thirteen reads and the two levers are what must be
        invisible, and they still are.

        Still no SQL, and still nothing about anybody else: the identity in
        the answer is the CALLER's own, which they already had.
        """

        return AdminWhoamiModel(
            admin=config.is_admin(
                getattr(user, "id", None), getattr(user, "email", None)
            ),
            user_id=getattr(user, "id", None),
            email=getattr(user, "email", None),
        )

    @router.get("/summary", response_model=AdminSummaryModel)
    async def summary(
        since: str | None = Query(default=None, alias="from"),
        until: str | None = Query(default=None, alias="to"),
        _: Any = Depends(admin),
    ) -> AdminSummaryModel:
        """The Overview panel: four questions off one scan of `runs`.

        The day buckets, the per-account totals, the refusal counts and the
        active head count are the same rows read four ways, which is why
        `admin_run_window` returns rows rather than four aggregates. The day
        bucket itself is Python, never `strftime` or `date_trunc`.
        """

        start, end = window(since, until)
        persistence = store()
        rows, truncated = persistence.admin_run_window(
            start=start, end=end, limit=config.ADMIN_MAX_SCAN_ROWS
        )
        counts = persistence.admin_status_counts(start=start, end=end)
        by_day: dict[str, dict[str, Any]] = {}
        by_account: dict[str, Decimal] = {}
        refusals = {"account_cap": 0, "run_ceiling": 0}
        total = Decimal("0")
        active: set[str] = set()
        for row in rows:
            total += row["cost_usd"]
            day = row["created_at"].astimezone(timezone.utc).strftime("%Y-%m-%d")
            bucket = by_day.setdefault(day, {"day": day, "usd": Decimal("0"), "runs": 0})
            bucket["usd"] += row["cost_usd"]
            bucket["runs"] += 1
            owner = row["user_id"] or UNOWNED
            by_account[owner] = by_account.get(owner, Decimal("0")) + row["cost_usd"]
            if row["user_id"]:
                active.add(row["user_id"])
            error = row["error"]
            if isinstance(error, str):
                if error.startswith(registry_module.ACCOUNT_CAP_ERROR_PREFIX):
                    refusals["account_cap"] += 1
                elif error.startswith(registry_module.COST_CEILING_ERROR_PREFIX):
                    refusals["run_ceiling"] += 1
        people_total, people_new = auth_people_counts(persistence, start=start, end=end)
        top_ids = sorted(by_account, key=lambda key: by_account[key], reverse=True)[:10]
        profiles = auth_profiles(persistence, top_ids)
        top_accounts = []
        for user_id in top_ids:
            email = (profiles.get(user_id) or {}).get("email")
            real = user_id != UNOWNED
            cap = config.user_spend_cap_usd(user_id, email) if real else None
            committed = (
                float(registry.account_spend(user_id).get("committed", 0.0))
                if real and hasattr(registry, "account_spend")
                else 0.0
            )
            top_accounts.append(
                TopAccount(
                    user_id=user_id,
                    email=email,
                    spent_usd=_money(by_account[user_id]),
                    committed_usd=round(committed, 6),
                    cap_usd=cap,
                    exempt=real and cap is None,
                )
            )
        now = datetime.now(timezone.utc)
        attention = [
            AttentionItem(
                kind="gate_open_long",
                run_id=gate["run_id"],
                hours=round((now - gate["opened_at"]).total_seconds() / 3600.0, 2),
            )
            for gate in persistence.list_open_gates()
        ]
        attention.sort(key=lambda item: item.hours, reverse=True)
        return AdminSummaryModel(
            spend_usd_estimate=_money(total),
            runs=RunStatusCounts(**{
                status: count
                for status, count in counts.items()
                if status in RunStatusCounts.model_fields
            }),
            people_active=len(active),
            people_total=people_total,
            people_new=people_new,
            refusals=RefusalCounts(**refusals),
            spend_by_day=[
                SpendDay(day=day, usd=_money(bucket["usd"]), runs=bucket["runs"])
                for day, bucket in sorted(by_day.items())
            ],
            top_accounts=top_accounts,
            attention=attention,
            truncated=truncated,
        )

    @router.get("/spend", response_model=AdminSpendModel)
    async def spend(
        group_by: str = Query(default="model"),
        since: str | None = Query(default=None, alias="from"),
        until: str | None = Query(default=None, alias="to"),
        _: Any = Depends(admin),
    ) -> AdminSpendModel:
        """The Money panel, on any of five axes.

        Four of them are one `GROUP BY` over `run_node_metrics JOIN runs`.
        The fifth, `day`, is the Python bucket over the same scan `/summary`
        makes, because `strftime` and `date_trunc` are the two spellings of
        one idea and this repository ships on both dialects.
        """

        start, end = window(since, until)
        persistence = store()
        if group_by == "day":
            rows, truncated = persistence.admin_run_window(
                start=start, end=end, limit=config.ADMIN_MAX_SCAN_ROWS
            )
            buckets: dict[str, dict[str, Any]] = {}
            for row in rows:
                day = row["created_at"].astimezone(timezone.utc).strftime("%Y-%m-%d")
                bucket = buckets.setdefault(
                    day, {"cost": Decimal("0"), "runs": 0}
                )
                bucket["cost"] += row["cost_usd"]
                bucket["runs"] += 1
            built = [
                SpendRow(
                    key=day,
                    label=day,
                    cost_usd=_money(bucket["cost"]),
                    # A day has no token or call total of its own without a
                    # second scan of `run_node_metrics`, and this axis exists
                    # to answer "when", not "on what". Zero here is the honest
                    # answer to a question this row does not carry; the four
                    # other axes carry it.
                    total_tokens=0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    call_count=0,
                    runs=bucket["runs"],
                )
                for day, bucket in sorted(buckets.items())
            ]
        else:
            try:
                raw, truncated = persistence.admin_spend_by(
                    group_by, start=start, end=end, limit=config.ADMIN_MAX_SCAN_ROWS
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            built = [
                SpendRow(
                    key=row["key"],
                    label=row["key"] or "(none)",
                    cost_usd=_money(row["cost_usd"]),
                    total_tokens=row["total_tokens"],
                    prompt_tokens=row["prompt_tokens"],
                    completion_tokens=row["completion_tokens"],
                    call_count=row["call_count"],
                    runs=row["runs"],
                )
                for row in raw
            ]
        # Summed from the rows, so the header and the table can never disagree
        # on screen. `Decimal` for the sum and `float` only at the wire.
        total = sum((Decimal(str(row.cost_usd)) for row in built), Decimal("0"))
        return AdminSpendModel(
            group_by=group_by,
            rows=built,
            total_usd=_money(total),
            truncated=truncated,
        )

    @router.get("/users", response_model=AdminUsersModel)
    async def users(
        sort: str = Query(default="spend"),
        limit: int = Query(default=50, ge=1),
        cursor: str | None = Query(default=None),
        _: Any = Depends(admin),
    ) -> AdminUsersModel:
        """The People panel: nine grouped queries merged in Python.

        Not one join, for the reason at the top of this module: a LEFT JOIN of
        `runs` to six one-to-many tables multiplies rows and every COUNT comes
        out too big.

        The page is a slice of the merged list rather than a keyset over SQL,
        because the sort keys - lifetime spend, last run, joined-at - come
        from three different tables and no index covers any of them across the
        merge. The list is bounded by the number of accounts, which is the one
        number on this console that is small by construction.
        """

        persistence = store()
        totals = persistence.admin_user_totals(utc_day=_utc_day())
        profiles = auth_profiles(persistence)
        rows = user_rows(totals, profiles)
        keys = {
            "spend": lambda row: (-row.spent_usd, row.user_id),
            "recent": lambda row: (row.last_run_at or "", row.user_id),
            "joined": lambda row: (row.created_at or "", row.user_id),
        }
        if sort not in keys:
            raise HTTPException(
                status_code=422, detail=f"sort must be one of {sorted(keys)}"
            )
        rows.sort(key=keys[sort], reverse=sort != "spend")
        size = page_limit(limit)
        offset = 0
        if cursor:
            try:
                offset = int(base64.urlsafe_b64decode(cursor + "==").decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=422, detail="cursor is not valid") from exc
        page = rows[offset : offset + size]
        following = offset + size
        return AdminUsersModel(
            rows=page,
            next=(
                base64.urlsafe_b64encode(str(following).encode("utf-8"))
                .decode("ascii")
                .rstrip("=")
                if following < len(rows)
                else None
            ),
        )

    @router.get("/users/{user_id}", response_model=AdminUserDetailModel)
    async def user_detail(user_id: str, _: Any = Depends(admin)) -> AdminUserDetailModel:
        """One account, the same nine queries scoped to one id.

        `__unowned__` is accepted and maps to `user_id IS NULL`, which is the
        whole reason the key exists: pre-auth runs and every run made on a
        deployment with no identity are real spend and have to be reachable.
        """

        persistence = store()
        totals = persistence.admin_user_totals(user_ids=[user_id], utc_day=_utc_day())
        if not totals:
            # An account with no rows anywhere is still an account if Better
            # Auth knows it; only an id nothing at all knows is a 404.
            profiles = auth_profiles(persistence, [user_id])
            if user_id not in profiles:
                raise HTTPException(status_code=404, detail="Not Found")
            totals = {
                user_id: {
                    "user_id": user_id,
                    "runs": 0,
                    "last_run_at": None,
                    "spent_usd": Decimal("0"),
                    "documents": 0,
                    "published": 0,
                    "credentials": 0,
                    "skills": 0,
                    "tools": 0,
                    "mcp_servers": 0,
                    "firecrawl_today": 0,
                }
            }
        profiles = auth_profiles(persistence, [user_id])
        base = user_rows(totals, profiles)[0]
        recent = persistence.admin_list_runs(user_id=user_id, limit=20)
        gates = persistence.admin_gates_for_user(user_id)
        answered = [gate for gate in gates if gate["answered_at"]]
        seconds = [
            (gate["answered_at"] - gate["opened_at"]).total_seconds() for gate in answered
        ]
        return AdminUserDetailModel(
            **base.model_dump(),
            gates=GateStats(
                answered=len(answered),
                expired=sum(1 for gate in gates if gate["status"] == "expired"),
                median_seconds=median_or_none(seconds),
            ),
            recent_runs=run_rows(
                recent, verdicts=verdicts_for([row["run_id"] for row in recent])
            ),
            langfuse=LangfuseUserLink(),
        )

    @router.get("/runs", response_model=AdminRunsModel)
    async def list_runs(
        status: str | None = Query(default=None),
        mode: str | None = Query(default=None),
        user_id: str | None = Query(default=None),
        workflow_id: str | None = Query(default=None),
        since: str | None = Query(default=None, alias="from"),
        until: str | None = Query(default=None, alias="to"),
        limit: int = Query(default=50, ge=1),
        cursor: str | None = Query(default=None),
        _: Any = Depends(admin),
    ) -> AdminRunsModel:
        """Every account's runs, newest first, on a row-value keyset.

        `(created_at, id) < (ts, id)` is one spelling that works on both
        dialects, and it does not drift while somebody is reading the list the
        way an OFFSET does.
        """

        start, end = window(since, until)
        persistence = store()
        size = page_limit(limit)
        # One more than the page, so "is there a next page" is an observation
        # rather than a second COUNT over the same predicate.
        rows = persistence.admin_list_runs(
            status=status,
            mode=mode,
            user_id=user_id,
            workflow_id=workflow_id,
            start=start,
            end=end,
            limit=size + 1,
            cursor=cursor_of(cursor),
        )
        more = len(rows) > size
        page = rows[:size]
        verdicts = verdicts_for([row["run_id"] for row in page])
        return AdminRunsModel(
            rows=run_rows(page, verdicts=verdicts),
            next=(
                encode_cursor(page[-1]["created_at"], page[-1]["run_id"])
                if more and page
                else None
            ),
        )

    @router.get("/runs/{run_id}/decisions", response_model=AdminDecisionsModel)
    async def decisions(run_id: str, _: Any = Depends(admin)) -> AdminDecisionsModel:
        """The one view Langfuse cannot give: what a person actually replied.

        Gate replies and edited fields are hashed in the trace by the content
        policy, on purpose. Here the reply comes back **verbatim** off
        `run_gates.response`, and every field of it is read in Python - no
        JSON path is written in any statement this route runs.
        """

        persistence = store()
        gates = persistence.list_gates(run_id)
        frames, _truncated = persistence.admin_frames_by_kind(
            ["guardrail", "verdict", "error"],
            run_ids=[run_id],
            limit=config.ADMIN_MAX_SCAN_ROWS,
        )
        guardrails: list[GuardrailRetry] = []
        fallbacks: list[FallbackModel] = []
        verdict: dict[str, Any] | None = None
        for frame in frames:
            details = frame["details"]
            if frame["kind"] == "verdict" and verdict is None:
                verdict = dict(details)
            name = details.get("guardrail")
            if isinstance(name, str) and name:
                guardrails.append(
                    GuardrailRetry(
                        guardrail=name,
                        guardrail_type=(
                            str(details["guardrail_type"])
                            if isinstance(details.get("guardrail_type"), str)
                            else None
                        ),
                        retry_count=int(details.get("retry_count") or 0),
                        node_id=frame["node_id"],
                    )
                )
            fallback = details.get("fallback_model")
            if isinstance(fallback, str) and fallback:
                fallbacks.append(
                    FallbackModel(
                        node_id=frame["node_id"],
                        fallback_model=fallback,
                        attempt=(
                            int(details["attempt"])
                            if isinstance(details.get("attempt"), int)
                            else None
                        ),
                    )
                )
        return AdminDecisionsModel(
            run_id=run_id,
            gates=[
                GateDecision(
                    gate_id=gate["gate_id"],
                    node_id=gate["node_id"],
                    status=gate["status"],
                    opened_at=_iso(gate["opened_at"]) or "",
                    answered_at=_iso(gate["answered_at"]),
                    seconds=(
                        round(
                            (gate["answered_at"] - gate["opened_at"]).total_seconds(), 3
                        )
                        if gate["answered_at"]
                        else None
                    ),
                    outcome=gate_outcome(gate["response"]),
                    response=gate["response"],
                )
                for gate in gates
            ],
            guardrails=guardrails,
            fallback_models=fallbacks,
            verdict=verdict,
            langfuse=langfuse_links(run_id),
        )

    @router.get("/gates", response_model=AdminGatesModel)
    async def gates(
        since: str | None = Query(default=None, alias="from"),
        until: str | None = Query(default=None, alias="to"),
        _: Any = Depends(admin),
    ) -> AdminGatesModel:
        """How long people take to answer, and which gate they sit on.

        Every outcome and every median is computed here in Python from the
        whole `response` column - `statistics.median`, and `None` rather than
        `0` for a cohort nobody answered, because a zero would draw as
        "instant" on the one tile that exists to find the slow ones.
        """

        start, end = window(since, until)
        rows, truncated = store().admin_gate_window(
            start=start, end=end, limit=config.ADMIN_MAX_SCAN_ROWS
        )
        approve = revise = expired = unanswered = 0
        seconds: list[float] = []
        buckets: dict[str, dict[str, Any]] = {}
        for row in rows:
            bucket = buckets.setdefault(
                row["gate_id"],
                {"count": 0, "seconds": [], "expired": 0},
            )
            bucket["count"] += 1
            if row["status"] == "expired":
                expired += 1
                bucket["expired"] += 1
            if row["answered_at"] is None:
                unanswered += 1
            else:
                elapsed = (row["answered_at"] - row["opened_at"]).total_seconds()
                seconds.append(elapsed)
                bucket["seconds"].append(elapsed)
            outcome = gate_outcome(row["response"])
            if outcome == "approve":
                approve += 1
            elif outcome == "revise":
                revise += 1
        return AdminGatesModel(
            approve=approve,
            revise=revise,
            expired=expired,
            unanswered=unanswered,
            median_seconds=median_or_none(seconds),
            by_gate=[
                GateBucket(
                    gate_id=gate_id,
                    count=bucket["count"],
                    median_seconds=median_or_none(bucket["seconds"]),
                    expired=bucket["expired"],
                )
                for gate_id, bucket in sorted(buckets.items())
            ],
            truncated=truncated,
        )

    @router.get("/verdicts", response_model=AdminVerdictsModel)
    async def verdicts(
        since: str | None = Query(default=None, alias="from"),
        until: str | None = Query(default=None, alias="to"),
        _: Any = Depends(admin),
    ) -> AdminVerdictsModel:
        """What the product decided, read from frames and labelled fragile.

        `complete` is false whenever `VALIDATOR_RUN_RETENTION_DAYS > 0`,
        because a purge cascades to `run_frames` and takes these with it. Kept
        rather than omitted: it is the product's own output, and the durable
        fix - a `runs.verdict` column - is Phase 2 (plan 17 risk 3).
        """

        start, end = window(since, until)
        frames, truncated = store().admin_frames_by_kind(
            ["verdict"], start=start, end=end, limit=config.ADMIN_MAX_SCAN_ROWS
        )
        counts: dict[str, int] = {}
        for frame in frames:
            verdict = _verdict_of(frame["details"])
            if verdict:
                counts[verdict] = counts.get(verdict, 0) + 1
        return AdminVerdictsModel(
            complete=int(config.VALIDATOR_RUN_RETENTION_DAYS) == 0,
            rows=[
                VerdictRow(verdict=verdict, count=count)
                for verdict, count in sorted(
                    counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            truncated=truncated,
        )

    @router.get("/health", response_model=AdminHealthModel)
    async def health(_: Any = Depends(admin)) -> AdminHealthModel:
        """`/readyz`'s own body, plus what only an admin should see.

        `health_payload` and `exporter_state` are CALLED, not restated - the
        two functions `/readyz` itself calls, with the same arguments. That is
        criterion 13, and it is the only construction under which the two
        answers cannot drift apart.
        """

        # Validated through `ReadyResponse` and dumped, so this block is not
        # merely built the same way as `/readyz`'s - it IS `/readyz`'s body,
        # defaults and all. Without it the two differ by the optional fields
        # the model fills in (`backend: null`, `workers: null`), and a test
        # asserting they "match" would have to be weakened to pass, which is
        # how criterion 13 would quietly stop meaning anything.
        from brief_crew.service.app import ReadyResponse

        payload, _status = health_payload(readiness=True)
        payload = dict(payload)
        payload["observability"] = exporter_state_for()
        readyz = ReadyResponse.model_validate(payload).model_dump(mode="json")
        persistence = store()
        return AdminHealthModel(
            readyz=readyz,
            integrity=HealthIntegrity(**persistence.admin_integrity_totals()),
            orphans=len(persistence.list_stale_runs()),
            retention_days=int(config.VALIDATOR_RUN_RETENTION_DAYS),
            ceilings=HealthCeilings(
                run_usd=float(config.MAX_RUN_COST_USD),
                account_usd=float(config.USER_SPEND_CAP_USD),
                margin=float(config.GRAPH_STATIC_BUDGET_MARGIN),
                firecrawl_daily=int(config.BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP),
            ),
            blind_to=list(BLIND_TO),
        )

    @router.get("/links", response_model=AdminLinksModel)
    async def links(_: Any = Depends(admin)) -> AdminLinksModel:
        """Constants only. **Never a key, never a URL with userinfo.**

        The rule `exporter_state` already follows: a URL can carry credentials
        in its userinfo, so nothing that is or contains one is ever assembled
        into a response. `LANGFUSE_BASE_URL` is a host this deployment
        configured and is published deliberately; the two Langfuse keys never
        appear anywhere in this module.
        """

        return AdminLinksModel(
            langfuse=LangfuseLinkConfig(
                base_url=(config.LANGFUSE_BASE_URL or "").rstrip("/"),
                project_id=config.LANGFUSE_PROJECT_ID,
                configured=bool(config.LANGFUSE_PROJECT_ID and config.LANGFUSE_BASE_URL),
            ),
            openrouter_activity_url=config.OPENROUTER_ACTIVITY_PAGE_URL,
            openrouter_credits_url=config.OPENROUTER_CREDITS_PAGE_URL,
            firecrawl_dashboard_url=config.FIRECRAWL_DASHBOARD_URL,
        )

    @router.get("/providers", response_model=AdminProvidersModel)
    async def provider_status(_: Any = Depends(admin)) -> AdminProvidersModel:
        """Two outbound probes behind a TTL, and one local answer.

        Every one of the three degrades to `available: false` with a sentence
        rather than raising: a 500 here would make the dashboard's own health
        tile the thing that breaks the dashboard.
        """

        cache = probes()
        openrouter = await run_in_threadpool(cache.openrouter)
        firecrawl = await run_in_threadpool(cache.firecrawl)
        state = exporter_state_for()
        return AdminProvidersModel(
            openrouter=OpenRouterProbe(**openrouter),
            firecrawl=FirecrawlProbe(**firecrawl),
            langfuse=LangfuseProbe(
                available=state.get("exporter") == "enabled",
                reason=state.get("reason"),
                exporter=state.get("exporter"),
                environment=state.get("environment"),
                project_configured=bool(config.LANGFUSE_PROJECT_ID),
            ),
        )

    @router.get("/runs/{run_id}/billed", response_model=AdminBilledModel)
    async def billed(run_id: str, _: Any = Depends(admin)) -> AdminBilledModel:
        """What Langfuse says one run cost. **On an explicit click only.**

        Never on page load: it is up to `LANGFUSE_BILLED_PAGE_LIMIT` outbound
        requests for one run, and the app's own estimate is already on screen
        beside it. `delta_pct` is what the Money banner's error band is
        measured against.
        """

        persistence = store()
        estimate = persistence.admin_run_costs([run_id]).get(run_id, Decimal("0"))
        answer = await run_in_threadpool(probes().langfuse_billed, run_id)
        links = langfuse_links(run_id)
        billed_usd = answer.get("billed_usd")
        delta = None
        if billed_usd is not None and estimate > 0:
            delta = round((float(billed_usd) - float(estimate)) / float(estimate) * 100.0, 2)
        return AdminBilledModel(
            available=bool(answer.get("available")),
            reason=answer.get("reason"),
            run_id=run_id,
            generations=int(answer.get("generations") or 0),
            billed_usd=billed_usd,
            estimate_usd=_money(estimate),
            delta_pct=delta,
            cost_source_counts=dict(answer.get("cost_source_counts") or {}),
            model_counts=dict(answer.get("model_counts") or {}),
            session_url=links.session_url,
            trace_url=links.trace_url,
            fetched_at=answer.get("fetched_at"),
        )

    # -- the two levers -----------------------------------------------------

    @router.post("/runs/{run_id}/cancel", status_code=202)
    async def cancel_run(run_id: str, user: Any = Depends(admin)) -> Any:
        """`registry.cancel` - the SAME call `/api/runs/{id}/cancel` makes.

        `require_own_run` is replaced by `require_admin` and nothing else is:
        there is no second cancellation path, no second set of statuses and no
        second sentence. PLANS.md decision 29 says yes to this and to the
        unpublish below, on the grounds that they are the only two levers that
        stop spend without a redeploy.

        Logged at WARNING with the ACTOR's e-mail and the target, because an
        admin acting on somebody else's run is exactly the event an audit
        wants and the run's own row records only that it was cancelled.
        """

        from brief_crew.service.models import CancelRunResponse

        try:
            record = registry.require(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        logger.warning(
            "admin lever: %s cancelled run %s (owner %s)",
            getattr(user, "email", None) or getattr(user, "id", "?"),
            run_id,
            getattr(record, "user_id", None) or UNOWNED,
        )
        return CancelRunResponse.model_validate(registry.cancel(run_id))

    @router.post("/workflows/{document_id}/unpublish")
    async def unpublish(document_id: str, user: Any = Depends(admin)) -> Any:
        """`mark_unpublished` + `unregister_builder_workflow`, on ANY row.

        The same two calls `builder_api.unpublish` makes, in the same order
        and for the same reason: the row moves first, then the registration,
        so a crash between them leaves a draft that is still registered until
        the next restart rather than a `published` row with no registration
        that the boot sweep would put straight back into service.

        The one difference is whose id is passed to the store: an admin passes
        **the document's own owner**, not themselves, so the store's ownership
        check still runs and still means what it says - it is not bypassed,
        it is asked the question it was written to answer about the person who
        owns the row.
        """

        from brief_crew.service.builder_api import _guarded, _unregister

        document_store = store_factory()
        if document_store is None:
            raise HTTPException(
                status_code=503,
                detail="this service has no durable store, so builder graphs cannot be saved",
            )
        exists, owner = store().admin_document_owner(document_id)
        if not exists:
            # The constant, not a sentence about documents: an admin route
            # answering "no such document" in different words from the 404
            # `require_admin` writes would be a way to tell an admin route
            # apart from an unknown path.
            raise HTTPException(status_code=404, detail="Not Found")
        stored = _guarded(
            lambda: document_store.mark_unpublished(document_id, user_id=owner)
        )
        _unregister(registry, document_id)
        logger.warning(
            "admin lever: %s unpublished workflow %s (owner %s)",
            getattr(user, "email", None) or getattr(user, "id", "?"),
            document_id,
            owner or UNOWNED,
        )
        return _document_model(stored)

    return router


def _utc_day() -> str:
    """Today, in UTC, spelled the way `platform_tool_usage.utc_day` spells it.

    The day boundary is a decision this codebase makes - UTC, always - and
    `claim_platform_quota` stores the decision rather than a timestamp so no
    reader can re-derive it in a different zone. This is the read side of the
    same decision.
    """

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
