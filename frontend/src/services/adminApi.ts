import { ref } from 'vue'
import { authedFetch, fetchJson } from './httpCore'

/**
 * Everything `/api/admin/*` answers, and the one call that decides whether the
 * console exists at all.
 *
 * A third client beside `StudioApi` and `builderApi`, sharing `httpCore` and
 * nothing else, for the reason `admin_api.py` is a third router: nothing here
 * runs a flow or edits a document, and the run surface's transport probe and
 * mock fallback would be actively wrong on a screen whose whole subject is what
 * the database really holds. **There is deliberately no mock transport.** A
 * fabricated admin console is the silent-mock defect (gotchas 2) pointed at the
 * one screen somebody would take a spending decision from.
 *
 * THE SHAPES ARE `.agent/plans/17-admin-console.md` §3's, and the fixture
 * `frontend/tests/fixtures/adminApi.json` is the contract that keeps them
 * honest: W-API's criterion 21 drives every real handler against a seeded
 * database and asserts its keys equal that file's, so these interfaces cannot
 * quietly become a second, quieter contract (R7, section 14 defect 2).
 *
 * Optional fields are optional because §3 abridges its own examples, not
 * because the server is unreliable: a reader must never be shown `undefined`
 * where a number belongs, so every consumer supplies its own floor.
 */

/** The router prefix. `ADMIN_API_PREFIX` - `src/brief_crew/service/admin_api.py`. */
export const ADMIN_API_PREFIX = '/api/admin'

/**
 * The reserved key `runs.user_id IS NULL` collapses to, everywhere (§3).
 *
 * Never dropped and never merged with a real account: runs written before
 * authentication existed are somebody's, and pretending they are nobody's would
 * quietly take them out of every total on this screen.
 */
export const UNOWNED_USER_KEY = '__unowned__'

/* ── the shapes ───────────────────────────────────────────────────────────── */

export interface AdminWhoami {
  admin: boolean
  user_id: string
  email: string | null
}

export interface AdminRunCounts {
  completed: number
  failed: number
  cancelled: number
  /** Asked to stop and not yet stopped. A seventh state, and it is its own:
   *  folding it into `cancelled` would report a run as over while it runs. */
  cancelling: number
  waiting: number
  running: number
  queued: number
}

export interface AdminSpendDay {
  day: string
  usd: number
  runs: number
}

export interface AdminAccountRow {
  user_id: string
  email: string | null
  spent_usd: number
  committed_usd: number
  cap_usd: number | null
  exempt: boolean
}

/**
 * One row of `attention`, and the panel treats `kind` as an open set.
 *
 * A code this client has never heard of is rendered as sentence-case English
 * with whatever fields it carries, never dropped and never given an invented
 * meaning - the rule `data/verdictDisplay.ts` already follows for an unknown
 * `decision_reason`. A dropped row on the one tile headed "needs a decision"
 * would be the worst possible silence.
 */
export interface AdminAttentionRow {
  kind: string
  run_id?: string | null
  user_id?: string | null
  email?: string | null
  hours?: number | null
  detail?: string | null
}

export interface AdminSummary {
  spend_usd_estimate: number
  estimate: boolean
  error_note?: string | null
  runs: AdminRunCounts
  people_active: number
  people_total: number
  people_new: number
  refusals: { account_cap: number; run_ceiling: number }
  spend_by_day: AdminSpendDay[]
  top_accounts: AdminAccountRow[]
  attention: AdminAttentionRow[]
  truncated: boolean
}

export type AdminSpendAxis = 'user' | 'day' | 'workflow' | 'model' | 'node'

export interface AdminSpendRow {
  key: string
  label?: string | null
  cost_usd: number
  total_tokens?: number
  prompt_tokens?: number
  completion_tokens?: number
  call_count?: number
  runs?: number
}

export interface AdminSpend {
  group_by: AdminSpendAxis
  estimate: boolean
  error_note?: string | null
  rows: AdminSpendRow[]
  total_usd: number
  truncated: boolean
}

export interface AdminUserRow {
  user_id: string
  email: string | null
  name?: string | null
  created_at?: string | null
  last_run_at?: string | null
  last_session_at?: string | null
  runs: number
  spent_usd: number
  committed_usd: number
  /** `registry.account_spend` is memory-only and lost on restart (§9 risk 5). */
  committed_is_volatile?: boolean
  cap_usd: number | null
  exempt: boolean
  documents?: number
  published?: number
  credentials?: number
  skills?: number
  tools?: number
  mcp_servers?: number
  firecrawl_today?: number
}

export interface AdminUserDetail extends AdminUserRow {
  gates: { answered: number; expired: number; median_seconds: number | null }
  recent_runs: AdminRunRow[]
  langfuse: { user_url: string | null }
}

export interface AdminUsersPage {
  rows: AdminUserRow[]
  next: string | null
}

export interface AdminLangfuseLinks {
  session_url: string | null
  trace_url: string | null
}

export interface AdminRunRow {
  run_id: string
  user_id: string | null
  email: string | null
  workflow_id: string
  mode?: string | null
  status: string
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  duration_ms?: number | null
  cost_usd: number
  ceiling_kind?: string | null
  max_cost_usd?: number | null
  account_cap_usd?: number | null
  stop_reason?: string | null
  error?: string | null
  verdict?: string | null
  integrity?: { captured: number; dropped: number; gaps: number }
  langfuse?: AdminLangfuseLinks
}

export interface AdminRunsPage {
  rows: AdminRunRow[]
  next: string | null
}

export interface AdminGateRow {
  gate_id: string
  node_id?: string | null
  status: string
  opened_at?: string | null
  answered_at?: string | null
  seconds?: number | null
  outcome?: string | null
  /** The operator's own words, verbatim. The one view Langfuse cannot give. */
  response?: Record<string, unknown> | null
}

export interface AdminGuardrailRow {
  guardrail: string
  guardrail_type?: string | null
  retry_count: number
  node_id?: string | null
}

export interface AdminFallbackRow {
  node_id: string
  fallback_model: string
  attempt?: number | null
}

export interface AdminDecisions {
  run_id?: string
  gates: AdminGateRow[]
  guardrails: AdminGuardrailRow[]
  fallback_models: AdminFallbackRow[]
  verdict?: Record<string, unknown> | null
  langfuse?: AdminLangfuseLinks
}

export interface AdminGateStats {
  approve: number
  revise: number
  expired: number
  unanswered: number
  median_seconds: number | null
  by_gate: { gate_id: string; count: number; median_seconds: number | null; expired: number }[]
  truncated?: boolean
}

export interface AdminVerdicts {
  /** False whenever `VALIDATOR_RUN_RETENTION_DAYS > 0` (§9 risk 3). */
  complete: boolean
  rows: { verdict: string; count: number }[]
  note?: string | null
  truncated?: boolean
}

export interface AdminHealth {
  readyz: Record<string, unknown>
  integrity: {
    captured: number
    dropped: number
    gaps: number
    emit_errors: number
    subscriber_dropped: number
    runs_with_drop: number
  }
  orphans: number
  retention_days: number
  ceilings: {
    run_usd: number | null
    account_usd: number | null
    margin: number | null
    firecrawl_daily: number | null
  }
  /**
   * What this console cannot see, in the SERVER's own words (§9 row 14).
   *
   * Rendered verbatim rather than restated on this side. The list is a fact
   * about the deployment - which instruments exist - and a client copy would
   * be the thing that goes stale the day one of them is built.
   */
  blind_to?: string[]
}

export interface AdminLinks {
  langfuse: { base_url: string; project_id: string; configured: boolean }
  openrouter_activity_url: string
  openrouter_credits_url: string
  firecrawl_dashboard_url: string
}

/** A probe that could not answer. HTTP 200 with a sentence, never a 500 (§3). */
export interface ProbeUnavailable {
  available: false
  reason: string
}

export interface OpenRouterProbe {
  available: true
  /** Present and null on the healthy arm: one model, two states (§3). */
  reason?: string | null
  is_free_tier?: boolean | null
  label?: string | null
  /** `credits` with a management key, `key` with the ordinary one (§4A). */
  source: 'credits' | 'key'
  total_credits?: number | null
  total_usage?: number | null
  remaining_usd: number | null
  usage?: number | null
  limit?: number | null
  limit_remaining?: number | null
  checked_at?: string | null
  age_seconds?: number | null
}

export interface FirecrawlProbe {
  available: true
  reason?: string | null
  remaining_credits: number | null
  plan_credits: number | null
  billing_period_start?: string | null
  billing_period_end?: string | null
  checked_at?: string | null
  age_seconds?: number | null
}

export interface LangfuseProbe {
  available: true
  reason?: string | null
  exporter: string
  environment?: string | null
  project_configured: boolean
}

export interface AdminProviders {
  openrouter: OpenRouterProbe | ProbeUnavailable
  firecrawl: FirecrawlProbe | ProbeUnavailable
  langfuse: LangfuseProbe | ProbeUnavailable
}

export interface AdminBilled {
  available: true
  reason?: string | null
  run_id: string
  generations: number
  billed_usd: number
  estimate_usd: number
  delta_pct: number | null
  cost_source_counts: Record<string, number>
  session_url?: string | null
  trace_url?: string | null
  fetched_at?: string | null
}

/**
 * The Langfuse SESSION url for a run, or null.
 *
 * The one link this client is allowed to build, and the reason it is allowed
 * is that nothing is derived: `sessionId` **is** the app's own `run_id`
 * verbatim (§3, and the observability programme's row A1 measured it), so this
 * is a URL template over two server-supplied constants and an id the caller
 * already holds. `{host}/project/{projectId}/sessions/{sessionId}` is the shape
 * confirmed against Langfuse's own doc examples (§4B).
 *
 * THE TRACE URL IS NOT BUILT HERE, and that asymmetry is criterion 20. A trace
 * id is `trace_id_for(run_id)` - the UUID hex, else the SDK's seeded id, else a
 * sha256 prefix - and that rule lives in `observability/backend.py`. A second
 * spelling of it on this side would disagree with the exporter the first time a
 * run id is not a UUID, and the link would open a trace that does not exist.
 * Every trace URL on this screen is one the server put in its own response.
 */
export function sessionUrlFor(links: AdminLinks | null, runId: string): string | null {
  if (!links?.langfuse.configured) return null
  const base = links.langfuse.base_url.replace(/\/$/, '')
  const project = links.langfuse.project_id
  if (!base || !project || !runId) return null
  return `${base}/project/${encodeURIComponent(project)}/sessions/${encodeURIComponent(runId)}`
}

/** Narrowing helper, so no panel has to spell `'available' in probe` twice. */
export function probeAvailable<T extends { available: true }>(
  probe: T | ProbeUnavailable | null | undefined,
): probe is T {
  return probe?.available === true
}

/* ── the window ───────────────────────────────────────────────────────────── */

/**
 * `?from=&to=` as the API spells it, or nothing for the server's own default.
 *
 * The client never invents a default window. `ADMIN_DEFAULT_WINDOW_DAYS` is a
 * server constant, and a second copy of it here would be a second answer to
 * "what does this screen mean by recently" - the drift `data/serverLimits.ts`
 * exists to make a failing test rather than a wrong number.
 */
export interface AdminWindow {
  from?: string
  to?: string
}

function windowQuery(window: AdminWindow | undefined, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams()
  if (window?.from) params.set('from', window.from)
  if (window?.to) params.set('to', window.to)
  for (const [key, value] of Object.entries(extra)) {
    if (value !== '') params.set(key, value)
  }
  const query = params.toString()
  return query ? `?${query}` : ''
}

/* ── the gate ─────────────────────────────────────────────────────────────── */

/**
 * Who the server says you are here, or null for "not an admin, or no such
 * route". Read once per page load.
 *
 * `null` DELIBERATELY CONFLATES THREE THINGS - a 404 from `require_admin`, a
 * 404 from a build with no admin router at all, and a network failure - and
 * that conflation is the feature rather than a shortcut. §9 row 9: the surface
 * has to be invisible, so a client that could tell "refused" from "absent"
 * would be advertising the route it is hiding. Every one of the three means the
 * same thing to this app: draw no Admin entry, and send `#/admin` home.
 */
export const adminWhoami = ref<AdminWhoami | null>(null)

/** Whether the probe has been answered at all, so the header can wait rather
 *  than flashing an entry in and out on every load. */
export const adminProbed = ref(false)

let inflight: Promise<AdminWhoami | null> | null = null

/**
 * Ask once. Never throws, never retries, and never logs.
 *
 * NO CONSOLE OUTPUT ON THE REFUSAL PATH, and that is a criterion rather than
 * tidiness: `e2e/admin.spec.ts` tolerates zero console errors on the arm where
 * `ADMIN_EMAILS` is unset, and a `console.error` for an expected 404 would fail
 * a suite over the control working correctly. `authedFetch` is used directly
 * instead of `fetchJson` for the same reason - `fetchJson` throws on a 404, and
 * an exception is not what "you are not an admin" means.
 */
export async function probeAdmin(force = false): Promise<AdminWhoami | null> {
  if (!force && adminProbed.value) return adminWhoami.value
  if (inflight) return inflight
  inflight = (async () => {
    try {
      const response = await authedFetch(`${ADMIN_API_PREFIX}/whoami`)
      if (!response.ok) return null
      const body = (await response.json()) as AdminWhoami
      return body?.admin === true ? body : null
    } catch {
      return null
    }
  })()
  try {
    const answer = await inflight
    adminWhoami.value = answer
    adminProbed.value = true
    return answer
  } finally {
    inflight = null
  }
}

/** Put the gate back to "never asked". Exported for the suites, and for a
 *  sign-out: the next person on this browser is not this one. */
export function resetAdminGate(): void {
  adminWhoami.value = null
  adminProbed.value = false
  inflight = null
}

/* ── the reads ────────────────────────────────────────────────────────────── */

export interface AdminApiLike {
  whoami(): Promise<AdminWhoami>
  summary(window?: AdminWindow): Promise<AdminSummary>
  spend(groupBy: AdminSpendAxis, window?: AdminWindow): Promise<AdminSpend>
  users(sort?: 'spend' | 'recent' | 'joined', limit?: number, cursor?: string): Promise<AdminUsersPage>
  user(userId: string): Promise<AdminUserDetail>
  runs(filters?: AdminRunFilters): Promise<AdminRunsPage>
  decisions(runId: string): Promise<AdminDecisions>
  gates(window?: AdminWindow): Promise<AdminGateStats>
  verdicts(window?: AdminWindow): Promise<AdminVerdicts>
  health(): Promise<AdminHealth>
  links(): Promise<AdminLinks>
  providers(): Promise<AdminProviders>
  billed(runId: string): Promise<AdminBilled | ProbeUnavailable>
  cancelRun(runId: string): Promise<void>
  unpublish(documentId: string): Promise<void>
}

export interface AdminRunFilters extends AdminWindow {
  status?: string
  mode?: string
  user_id?: string
  workflow_id?: string
  limit?: number
  cursor?: string
}

const path = (rest: string) => `${ADMIN_API_PREFIX}${rest}`

export const adminApi: AdminApiLike = {
  whoami: () => fetchJson<AdminWhoami>(path('/whoami')),

  summary: (window) => fetchJson<AdminSummary>(path(`/summary${windowQuery(window)}`)),

  spend: (groupBy, window) =>
    fetchJson<AdminSpend>(path(`/spend${windowQuery(window, { group_by: groupBy })}`)),

  users: (sort = 'spend', limit = 50, cursor = '') =>
    fetchJson<AdminUsersPage>(
      path(`/users${windowQuery(undefined, { sort, limit: String(limit), cursor })}`),
    ),

  user: (userId) => fetchJson<AdminUserDetail>(path(`/users/${encodeURIComponent(userId)}`)),

  runs: (filters = {}) => {
    const { from, to, limit, cursor, ...rest } = filters
    const extra: Record<string, string> = {}
    for (const [key, value] of Object.entries(rest)) {
      if (typeof value === 'string' && value !== '') extra[key] = value
    }
    if (limit !== undefined) extra.limit = String(limit)
    if (cursor) extra.cursor = cursor
    return fetchJson<AdminRunsPage>(path(`/runs${windowQuery({ from, to }, extra)}`))
  },

  decisions: (runId) =>
    fetchJson<AdminDecisions>(path(`/runs/${encodeURIComponent(runId)}/decisions`)),

  gates: (window) => fetchJson<AdminGateStats>(path(`/gates${windowQuery(window)}`)),

  verdicts: (window) => fetchJson<AdminVerdicts>(path(`/verdicts${windowQuery(window)}`)),

  health: () => fetchJson<AdminHealth>(path('/health')),

  links: () => fetchJson<AdminLinks>(path('/links')),

  providers: () => fetchJson<AdminProviders>(path('/providers')),

  /**
   * The billed figure, ON AN EXPLICIT CLICK AND NEVER ON PAGE LOAD (criterion
   * 26). It is an outbound call to Langfuse on the server's thread, and a
   * dashboard that made one per run per refresh would be a load generator
   * pointed at a third party.
   */
  billed: (runId) =>
    fetchJson<AdminBilled | ProbeUnavailable>(path(`/runs/${encodeURIComponent(runId)}/billed`)),

  cancelRun: async (runId) => {
    await fetchJson(path(`/runs/${encodeURIComponent(runId)}/cancel`), { method: 'POST' })
  },

  unpublish: async (documentId) => {
    await fetchJson(path(`/workflows/${encodeURIComponent(documentId)}/unpublish`), {
      method: 'POST',
    })
  },
}
