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
* **404, never 403.** `require_admin` raises FastAPI's own unknown-route body
  byte for byte, so an admin route and a route that does not exist are
  indistinguishable to anybody who is not an admin. A 403 would advertise the
  surface; see plan 17 section 9, risk 9.
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

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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
    "langfuse_links",
]

#: Under `/api`, so the CORS middleware, the body limit and the client's own
#: `authedFetch` all reach it the way they reach every other route.
ADMIN_API_PREFIX = "/api/admin"

#: The reserved key a run with no owner is grouped under. A literal rather
#: than `None` because it has to survive JSON, a dictionary key and a URL path
#: segment (`GET /users/__unowned__`), and because a client that saw `null`
#: would have to decide for itself whether that meant "nobody" or "unknown".
UNOWNED = "__unowned__"

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
    """The ONLY route the client may call to decide whether to draw the link.

    It is also the only one with no SQL: an anonymous caller and a signed-in
    non-admin both get the 404, so a 200 here is the whole answer.
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
