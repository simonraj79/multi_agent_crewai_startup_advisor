import { ref } from 'vue'
import { authedFetch, fetchJson } from './httpCore'
import { readErrorDetail } from '../data/serverLimits'
import { ratingToSend, readRunRating } from '../data/runRating'
import { saveBlob } from '../utils/saveBlob'
import type { RunRating, RunRatingValue, RunRatingWire } from '../types/studio'

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

/**
 * The one admin route that answers a non-admin.
 *
 * AMENDED 2026-09-08 by the orchestrator's ruling, and the amendment is the
 * whole reason this shape has an `admin` field at all. `whoami` used to be
 * 404 for everybody but an admin, like every other route on the router - and
 * that made every ordinary page load fetch a resource that 404s, which Chrome
 * logs as a console error and which failed **113 of 145 non-`@launch` E2E
 * tests** in the default `ADMIN_EMAILS`-unset configuration. The invisibility
 * §9 row 9 asks for is about the SURFACE, not about the question "am I one";
 * so `whoami` is now the single documented exception and answers 200 with
 * `admin: false` for a non-admin or an anonymous caller, while every other
 * `/api/admin/*` route still answers FastAPI's own 404.
 *
 * `user_id` is nullable because an anonymous caller has none.
 */
export interface AdminWhoami {
  admin: boolean
  user_id: string | null
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
  /**
   * What a person said about this run, when anybody did (plan 20 §2.2).
   *
   * OPTIONAL for the reason every other optional field here is: an API
   * deployed before plan 20 answers rows without these keys, and both Render
   * services carry `autoDeploy: yes`, so the console can ship a minute before
   * the API does. Absent and `null` mean the same thing - nobody has said
   * anything - and the row draws no chip for either.
   */
  rating?: RunRatingValue | null
  rated_by?: string | null
  rated_at?: string | null
}

/** The four states the admin Runs filter may ask for (plan 20 §2.2). */
export type AdminRatingFilter = '' | RunRatingValue | 'unrated'

export interface AdminRunsPage {
  rows: AdminRunRow[]
  next: string | null
}

export interface AdminInsightSample {
  run_id: string
  user_id: string | null
  cost_usd: number
  status: string
  created_at: string
  seq: number | null
  gate_id: string | null
  langfuse: AdminLangfuseLinks
}

export interface AdminInsightFinding {
  rule_id: string
  severity: string
  workflow_id: string
  node_id: string
  gate_id: string | null
  title: string
  explanation: string
  suggestion: string
  affected_runs: number
  total_runs: number
  rate: number
  samples: AdminInsightSample[]
}

/**
 * How the scanned runs were rated, over the same sample every finding counts
 * against (plan 20 §2.2).
 *
 * OPTIONAL, so a console built against plan 20 still draws an older API's
 * insights rather than a row of `undefined`. The strip is simply absent then,
 * which is honest: nobody has been asked yet.
 */
export interface AdminInsightLabels {
  good: number
  bad: number
  unsure: number
  unrated: number
}

export interface AdminInsights {
  workflows: { workflow_id: string; runs: number }[]
  labels?: AdminInsightLabels
  findings: AdminInsightFinding[]
  insufficient: { workflow_id: string; total_runs: number; required_runs: number }[]
  suppressed_count: number
  thresholds: { min_runs: number; min_affected_runs: number }
  coverage: {
    runs_scanned: number
    frames_scanned: number
    gates_scanned: number
    runs_missing_frames: number
    runs_with_integrity_loss: number
    retention_days: number
    truncated: boolean
    incomplete: boolean
    warnings: string[]
  }
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
  /**
   * The human verdict on this run, beside the machine's (plan 20 §2.2).
   *
   * Read through `readRunRating` rather than trusted as typed, because it is
   * the one field on this response whose note has two spellings in flight -
   * see `data/runRating.ts` for which and why.
   */
  rating?: RunRatingWire | null
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
 * Who the server says you are here, or null for "not an admin". Read once per
 * page load.
 *
 * `null` DELIBERATELY CONFLATES FOUR THINGS - a 200 saying `admin: false`, a
 * 404 from `require_admin` on an older build, a 404 from a build with no admin
 * router at all, and a network failure - and that conflation is the feature
 * rather than a shortcut. §9 row 9: the surface has to be invisible, so a
 * client that could tell "refused" from "absent" would be advertising the
 * route it is hiding. All four mean one thing here: draw no Admin entry, and
 * send `#/admin` home.
 *
 * The 404 arms are KEPT rather than replaced. A deployed API is not always the
 * one this bundle was built against - `autoDeploy: yes` on two services means
 * the web service can ship a minute before the API does - and a console that
 * threw on the old shape would be a blank screen for that minute.
 */
export const adminWhoami = ref<AdminWhoami | null>(null)

/** Whether the probe has been answered at all, so the header can wait rather
 *  than flashing an entry in and out on every load. */
export const adminProbed = ref(false)

let inflight: Promise<AdminWhoami | null> | null = null

/**
 * Ask once. Never throws, never retries, and never logs.
 *
 * NO OUTPUT OF ANY KIND ON THE REFUSAL PATH, and that is a criterion rather
 * than tidiness. Under the amended contract a non-admin gets a 200, so the
 * browser logs nothing at all - which is what took the E2E suite from 113
 * failures back to zero. `authedFetch` is still used instead of `fetchJson`,
 * because `fetchJson` throws on the 404 an OLDER backend still answers, and an
 * exception is not what "you are not an admin" means.
 *
 * `admin: false` and a 404 land on the same `null`, so the caller has one
 * state to handle and no way to tell a refusal from an absence.
 */
export async function probeAdmin(force = false): Promise<AdminWhoami | null> {
  if (!force && adminProbed.value) return adminWhoami.value
  if (inflight) return inflight
  inflight = (async () => {
    try {
      const response = await authedFetch(`${ADMIN_API_PREFIX}/whoami`)
      // An older backend 404s here rather than answering `admin: false`. Both
      // are "no entry"; neither is an error worth showing anybody.
      if (!response.ok) return null
      const body = (await response.json()) as AdminWhoami | null
      // `=== true` rather than truthiness: a body with no `admin` key at all -
      // a proxy's HTML error page parsed as JSON, a shape that has moved - is
      // not a claim that you are an admin.
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
  insights(window?: AdminWindow, workflowId?: string): Promise<AdminInsights>
  decisions(runId: string): Promise<AdminDecisions>
  gates(window?: AdminWindow): Promise<AdminGateStats>
  verdicts(window?: AdminWindow): Promise<AdminVerdicts>
  health(): Promise<AdminHealth>
  links(): Promise<AdminLinks>
  providers(): Promise<AdminProviders>
  billed(runId: string): Promise<AdminBilled | ProbeUnavailable>
  cancelRun(runId: string): Promise<void>
  unpublish(documentId: string): Promise<void>
  rateRun(runId: string, rating: RunRatingValue | null, note?: string): Promise<RunRating>
}

export interface AdminRunFilters extends AdminWindow {
  status?: string
  mode?: string
  user_id?: string
  workflow_id?: string
  /** `good` / `bad` / `unsure` / `unrated`, and 422 for anything else (§2.2). */
  rating?: AdminRatingFilter
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

  insights: (window, workflowId = '') =>
    fetchJson<AdminInsights>(
      path(`/insights${windowQuery(window, { workflow_id: workflowId })}`),
    ),

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

  /**
   * Rate anybody's run, through the admin door (§2.2).
   *
   * THE SECOND DOOR ONTO ONE WRITE, and the server logs the actor's e-mail
   * beside the run it touched - the same shape as this console's other two
   * levers. A rating an owner did not write has to be findable when the owner
   * asks why it is there, not only by reading the column.
   *
   * `require_admin` answers **404, never 403**, so a caller who is not an
   * admin reads "that run was not found" like any stranger. That is the
   * surface staying invisible, not a lost message.
   */
  rateRun: async (runId, rating, note = '') => {
    const body = await fetchJson<unknown>(path(`/runs/${encodeURIComponent(runId)}/rating`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating: ratingToSend(rating), note: note || null }),
    })
    return readRunRating(body, runId)
  },
}

/* ======================================================================== *
 *  Improve - plan 21, `/api/admin/improve` and the rated-run export        *
 * ======================================================================== */

/**
 * Step 4 of the loop: where runs go wrong, whether a change helped, the runs
 * worth keeping, and one optional written review.
 *
 * A SEPARATE OBJECT FROM `adminApi`, mirroring the server: `improve_api.py` is
 * its own router mounted beside the admin one precisely so no plan-17 route
 * changes behaviour, and a second surface here keeps that property visible from
 * the client too. `AdminApiLike` does not move, so nothing that stands in for
 * the console has to grow five methods it never calls.
 *
 * EVERY SHAPE BELOW IS `.agent/plans/21-test-a-change.md` §2's, and
 * `frontend/tests/fixtures/improveApi.json` is what holds it honest (T5):
 * W-API generates that file from its own response models and drives every real
 * handler against it. So these interfaces must never become a second, quieter
 * contract - section 14 defect 2 is what happens without one.
 *
 * OPTIONAL MEANS ABRIDGED, NOT UNRELIABLE. The plan prints abbreviated
 * examples, so a key it does not spell is optional here and every consumer
 * supplies its own floor. Two fields are deliberately loose - `error_classes`
 * and a gate's `edited_fields` - because the server sends them as counts in one
 * place and as names in another; `describeCounts` reads either without
 * inventing a third.
 *
 * NOT HERE, AND DELIBERATELY: there is no rating WRITE on this object. Plan
 * 20's `adminApi.rateRun` and `data/runRating.ts` are the only rating code in
 * this repository (R1), and a second spelling of a write is how two doors onto
 * one column start disagreeing.
 */

/** The router prefix. `ADMIN_API_PREFIX + "/improve"`. */
export const IMPROVE_API_PREFIX = `${ADMIN_API_PREFIX}/improve`

/** A count-or-name bag: `{"TimeoutError": 3}` or `["TimeoutError"]`. */
export type CountBag = Record<string, number> | string[] | null | undefined

/**
 * A count bag as `name x3, other` - one reading for both spellings.
 *
 * The alternative was to pick one and let the other render as `[object
 * Object]`, which is the shape of thing a dashboard shows for a week before
 * anybody notices. An empty bag answers `''` and the caller prints nothing.
 */
export function describeCounts(bag: CountBag, limit = 3): string {
  if (!bag) return ''
  const entries = Array.isArray(bag)
    ? bag.map((name) => [String(name), 0] as const)
    : Object.entries(bag).map(([name, value]) => [name, Number(value) || 0] as const)
  return entries
    .slice(0, limit)
    .map(([name, value]) => (value > 1 ? `${name} x${value}` : name))
    .join(', ')
}

/**
 * The window every improve read echoes back, in the SERVER's own spelling.
 *
 * `{start, end, days}` and not the `{from, to}` the request carries: the query
 * is what a client asks for and this is what the server decided, and the two
 * are different objects even when they agree.
 */
export interface ImproveWindow {
  start?: string | null
  end?: string | null
  days?: number | null
}

export interface ImproveRatingCounts {
  good: number
  bad: number
  unsure: number
  unrated: number
}

export interface ImproveAgentRow {
  agent_role?: string | null
  node_id: string
  node_label?: string | null
  runs: number
  executions: number
  failures: number
  error_classes?: CountBag
  guardrail_retries: number
  llm_calls: number
  calls_per_execution: number
  mean_ms?: number | null
  cost_usd: number
  cost_share?: number | null
  /**
   * What this node would cost if every one of its calls had run on the cheap
   * tier - `null` when the node already runs there, or its tokens are unknown.
   * Only ever a suggestion: Compare, axis Model, is the one thing that
   * measures it.
   */
  cheap_tier_cost_usd?: number | null
  truncated_outputs: number
}

export interface ImproveToolRow {
  tool: string
  agent_role?: string | null
  node_id?: string | null
  calls: number
  empty: number
  empty_rate: number
  failed: number
  failed_rate: number
  from_cache?: number
  queries_sample?: string[]
}

export interface ImproveErrorRow {
  error_class: string
  count: number
  nodes?: string[]
  agent_roles?: string[]
}

export interface ImproveGateRow {
  gate_id: string
  node_id?: string | null
  opened: number
  answered: number
  revise: number
  revise_rate: number
  expired: number
  median_seconds?: number | null
  edited_fields?: CountBag
}

export interface ImproveRouteRow {
  node_id: string
  node_label?: string | null
  decisions: number
  routes?: CountBag
  unique_routes: number
}

/**
 * One task's completions, and how many of them swallowed a tool failure.
 *
 * The one row in this payload that CANNOT be answered for a run recorded
 * before the serializer change: `completions` counts the task-completed frames
 * that carry the new keys, so a window of historic runs reads zero. That is
 * why the panel's empty state says "no run recorded after the update", and
 * never "no tool failed".
 *
 * `truncated_outputs` is declared because the server sends it and this type is
 * the fixture's shape; it is deliberately NOT rendered on its own. It counts
 * this repository's own frame preview bound rather than a model stopping
 * short, so a sentence built on it would be advice about the wrong thing.
 */
export interface ImproveTaskRow {
  task_name: string
  node_id: string
  node_label?: string | null
  completions: number
  tool_failures: number
  truncated_outputs?: number
}

/**
 * One step of the workflow, and every model it has actually run on.
 *
 * THE ONLY HONEST SOURCE FOR THE MODEL AXIS's three pickers. The first version
 * of this panel filled its two model boxes from `spend(group_by=model)`, which
 * answers "what billed anywhere in this window" - so it offered a model that
 * had never touched the chosen step, and a comparison of two arms that cannot
 * both exist is a question with no answer rather than a finding.
 *
 * A step with fewer than two models here has nothing to compare, and the panel
 * says so rather than offering it.
 */
export interface ImproveNodeModels {
  node_id: string
  label?: string | null
  models: string[]
  runs?: number
}

export interface ImproveOutcomes {
  by_verdict?: Array<{
    verdict: string
    runs: number
    mean_confidence?: number | null
    cost_usd?: number
    cost_per_run?: number
  }>
  by_rating?: Array<{ rating: string; runs: number; cost_usd?: number }>
  by_status?: Record<string, number>
}

/** Five ranked lists plus the outcomes, every row carrying its own counts. */
export interface ImproveHotspots {
  window?: ImproveWindow | null
  runs: number
  truncated?: boolean
  workflow_id?: string
  document_version?: number | null
  /** Every dollar here is the app's own estimate, and the band says by how much. */
  estimate?: boolean
  error_note?: string | null
  /**
   * The run floor under which every rate here is one or two events wearing a
   * percentage, when the server names one.
   *
   * OPTIONAL because no plan-21 response is documented to carry it: on the
   * branch this figure rode on the lessons payload, which R1 drops. Absent, the
   * panel simply prints no small-sample line rather than inventing a floor - a
   * client constant would be a second answer to a server question, which is the
   * drift `data/serverLimits.ts` exists to turn into a failing test.
   */
  min_runs?: number | null
  agents: ImproveAgentRow[]
  tools: ImproveToolRow[]
  errors: ImproveErrorRow[]
  gates: ImproveGateRow[]
  routes: ImproveRouteRow[]
  /**
   * Which models each step has run on, for the model axis's pickers.
   *
   * OPTIONAL because an API deployed before this key existed sends none, and
   * both Render services carry `autoDeploy: yes` - so this bundle can be a
   * minute ahead of the API. Absent, the panel offers no step and says why,
   * which is honest; it never falls back to a list of models from somewhere
   * else, because that is the defect this key exists to close.
   */
  node_models?: ImproveNodeModels[]
  outcomes?: ImproveOutcomes | null
  tasks?: ImproveTaskRow[]
  /** The sum over `tasks`. Zero for a window of runs older than the change. */
  task_completions?: number
  task_tool_failures?: number
  rated?: number
  rating_mix?: ImproveRatingCounts
  verdicts?: number
  low_confidence?: number
  mean_confidence?: number | null
  /**
   * A few run ids from this window, so "read the bad ones" has a starting
   * point. Plain ids: there is no `#/run/<run_id>` route to link them to.
   */
  sample_run_ids?: string[]
}

export type ImproveCompareAxis = 'version' | 'model'

/**
 * One arm of a comparison, with the six measures and its own `n`.
 *
 * THERE IS NO `label`. The branch declared one, nothing ever sent it, and the
 * table fell back to `key` on every row it has ever drawn - so the field was a
 * second name for a column that only ever had one (R4 removes it).
 */
export interface ImproveCompareArm {
  key: string
  n: number
  /** Under `IMPROVE_MIN_COMPARE_RUNS`. A difference over three runs is noise. */
  underpowered?: boolean
  status_mix?: Record<string, number>
  verdict_mix?: Record<string, number>
  mean_confidence?: number | null
  rating_mix?: Record<string, number>
  gate_revise_rate?: number | null
  median_duration_ms?: number | null
  cost_per_run_usd?: number | null
}

export interface ImproveCompare {
  workflow_id: string
  axis: ImproveCompareAxis
  node_id?: string | null
  arms: ImproveCompareArm[]
  min_runs?: number | null
  window?: ImproveWindow | null
  estimate?: boolean
  error_note?: string | null
  truncated?: boolean
}

export interface ImproveDigestRow {
  id: string
  workflow_id: string
  created_by?: string | null
  window?: ImproveWindow | null
  sample_runs: number
  sample_frames?: number | null
  /** The sample was clipped to fit the input bound, and says so. */
  truncated_sample?: boolean
  model: string
  prompt_tokens?: number | null
  completion_tokens?: number | null
  cost_usd?: number | null
  /** The ceiling this call was made under, as it stood at the time. */
  max_cost_usd?: number | null
  /** R5: the measured cost came out ABOVE the cap. Shown, never hidden. */
  over_cap?: boolean
  /** Model output. Rendered as TEXT, never as markup - see the panel. */
  body: string
  created_at: string
}

/**
 * The stored reviews, AND the bounds the button has to print before the click.
 *
 * The cap, the model and the sample bounds ride on this GET rather than being
 * spelled here, for the reason `AdminWindow` gives about the default window: a
 * ceiling written in the client is a second answer to "what does this cost",
 * and the copy is always the half that goes stale. When the server sends none,
 * the panel says so rather than filling one in.
 */
export interface ImproveDigestPage {
  rows: ImproveDigestRow[]
  enabled: boolean
  workflow_id?: string
  model?: string | null
  max_cost_usd?: number | null
  max_sample_runs?: number | null
  max_sample_frames?: number | null
  /** R5: the two bounds the server gained so the button could print them. */
  max_input_chars?: number | null
  max_output_tokens?: number | null
  /** Every stored row's `cost_usd` for this workflow, summed by the server. */
  total_cost_usd?: number | null
  /**
   * How many reviews exist, when the server counts them - `rows` is a page.
   *
   * Optional, and the panel falls back to `rows.length` with no ceremony: an
   * API that does not count them yet reports the page it sent, which is a
   * floor rather than a wrong number.
   */
  total_count?: number | null
}

/** Which rated runs the export should carry. `any` sends no rating filter. */
export type EvalsetRating = 'good' | 'bad' | 'unsure' | 'any'

export interface ImproveApiLike {
  hotspots(workflowId: string, window?: AdminWindow): Promise<ImproveHotspots>
  compare(
    workflowId: string,
    axis: ImproveCompareAxis,
    a: string,
    b: string,
    window?: AdminWindow,
    nodeId?: string,
  ): Promise<ImproveCompare>
  digests(workflowId: string, limit?: number): Promise<ImproveDigestPage>
  runDigest(workflowId: string, window?: AdminWindow): Promise<ImproveDigestRow>
  downloadEvalset(workflowId: string, rating: EvalsetRating, window?: AdminWindow): Promise<void>
}

const improvePath = (rest: string) => `${IMPROVE_API_PREFIX}${rest}`

/** A workflow id in a filename, with anything a file system argues about gone. */
function fileSafe(value: string): string {
  return value.replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'workflow'
}

export const improveApi: ImproveApiLike = {
  hotspots: (workflowId, window) =>
    fetchJson<ImproveHotspots>(
      improvePath(`/hotspots${windowQuery(window, { workflow_id: workflowId })}`),
    ),

  /**
   * Two arms, on an explicit press only.
   *
   * `node_id` is sent on the MODEL axis and omitted on the version axis, which
   * is R4's rule from the client side: the server answers 422 without it, the
   * arms are only disjoint once a node is named, and `cost_per_run_usd` then
   * means that node's cost rather than the whole run's. The panel will not let
   * the press happen without one; this is the second half of the same rule, so
   * a caller that skipped the panel still cannot ask a question the server
   * would have to refuse.
   */
  compare: (workflowId, axis, a, b, window, nodeId = '') =>
    fetchJson<ImproveCompare>(
      improvePath(
        `/compare${windowQuery(window, {
          workflow_id: workflowId,
          axis,
          a,
          b,
          node_id: axis === 'model' ? nodeId : '',
        })}`,
      ),
    ),

  digests: (workflowId, limit = 10) =>
    fetchJson<ImproveDigestPage>(
      improvePath(
        `/digests${windowQuery(undefined, { workflow_id: workflowId, limit: String(limit) })}`,
      ),
    ),

  /**
   * The one model call on this screen, and it happens ONLY here.
   *
   * `POST`, never a `GET`, never on mount, never on a timer. A 422 with the
   * knob off is the expected answer and reaches the panel as the server's own
   * sentence rather than as a crash.
   */
  runDigest: (workflowId, window) =>
    /*
     * QUERY PARAMETERS AND NO BODY, which is what the route declares. The
     * first version of this call sent `{workflow_id, from, to}` as JSON, and
     * against a handler whose `workflow_id` is `Query(...)` that is a 422 for
     * a missing parameter - a refusal that would have read, on the one control
     * that spends money, as "the server would not write a review" rather than
     * "the client asked wrongly".
     */
    fetchJson<ImproveDigestRow>(
      improvePath(`/digests${windowQuery(window, { workflow_id: workflowId })}`),
      { method: 'POST' },
    ),

  /**
   * The rated runs, saved to disk.
   *
   * A fetch and a blob rather than an anchor, and that is not a preference: the
   * route is behind `require_admin`, a plain `<a href>` carries no bearer
   * token, and the refusal it would collect is a 404 - so the link would read
   * as "there is nothing here" on a file that exists. `authedFetch` attaches
   * the token and `saveBlob` is the same three steps `downloadLogs` already
   * uses, imported rather than copied.
   *
   * The response is streamed NDJSON, and a truncated export ends in its own
   * sentinel LINE rather than a 500 - so a short file is still a valid file and
   * the caller is never told it failed.
   */
  async downloadEvalset(workflowId, rating, window) {
    const query = windowQuery(window, { workflow_id: workflowId, rating })
    const response = await authedFetch(`${ADMIN_API_PREFIX}/export/evalset${query}`)
    if (!response.ok) {
      const body = await response.text().catch(() => '')
      throw new Error(readErrorDetail(body, response.status))
    }
    saveBlob(await response.blob(), `${fileSafe(workflowId)}-${rating}-runs.ndjson`)
  },
}
