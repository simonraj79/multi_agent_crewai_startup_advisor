import { readFileSync } from 'node:fs'
import path from 'node:path'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminView from '../src/views/AdminView.vue'
import { resetAdminGate } from '../src/services/adminApi'
import { clearAccessToken, setSessionActive } from '../src/services/authClient'
import adminFixture from './fixtures/adminApi.json'

/**
 * The seventh panel - `.agent/plans/21-test-a-change.md`, criteria T6 and T7.
 *
 * Driven by `frontend/tests/fixtures/improveApi.json` the moment W-API
 * generates it, and by the stand-in below until then. That switch is the whole
 * reason this file reads the fixture off disk rather than importing it: an
 * `import` of a file that does not exist yet is a type error in `vue-tsc`, and
 * the two builders are working in one tree at the same time. When the generated
 * file lands it simply wins - `WIRE` prefers it whole and never merges, because
 * a merge would let this suite pass over a key the server had stopped sending,
 * which is precisely the mirror the fixture exists to refuse.
 *
 * ASSERTIONS ARE DERIVED FROM THE PAYLOAD WHEREVER THEY CAN BE. A test that
 * hard-codes `$0.24` is a test about one illustrative number; a test that reads
 * the agent's own `node_label` out of the response and then looks for it on
 * screen is a test about the rendering, and it survives the fixture being
 * regenerated with different values. Where a specific STATE is needed - an
 * underpowered arm, a review over its ceiling, a workflow with no versions -
 * the server's own object is PATCHED rather than replaced, so the shape stays
 * the server's and only the one field under test is this file's.
 *
 * WHAT THIS FILE CANNOT ANSWER. Nothing here knows how tall anything ended up,
 * whether the Download button is reachable at 1180, or whether the four
 * sections overlap - a jsdom mount asserts structure and never asks how wide
 * anything ended up, which is this repository's most expensive lesson.
 */

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))

/**
 * The stand-in, and it is a stand-in rather than a contract.
 *
 * These are the shapes plan 21 §2 describes and the values are illustrative.
 * The moment `fixtures/improveApi.json` exists this object is not read at all.
 */
const FALLBACK: Record<string, unknown> = {
  'GET /api/admin/improve/hotspots': {
    window: { start: '2026-08-20T00:00:00Z', end: '2026-09-19T00:00:00Z', days: 30 },
    workflow_id: 'ug_4d2b81ac',
    runs: 9,
    document_version: 4,
    min_runs: 5,
    agents: [
      {
        agent_role: 'Market evidence analyst',
        node_id: 'market_research',
        node_label: 'Market research',
        runs: 9,
        executions: 11,
        failures: 1,
        error_classes: ['BadRequestError'],
        guardrail_retries: 4,
        llm_calls: 96,
        calls_per_execution: 8.7,
        mean_ms: 21403,
        cost_usd: 0.3184,
        cost_share: 0.54,
        cheap_tier_cost_usd: 0.2412,
        truncated_outputs: 3,
      },
    ],
    tools: [
      {
        tool: 'market_research',
        agent_role: 'Market evidence analyst',
        node_id: 'market_research',
        calls: 18,
        empty: 9,
        empty_rate: 0.5,
        failed: 2,
        failed_rate: 0.111,
        from_cache: 1,
        queries_sample: ['clinic scheduling software'],
      },
    ],
    errors: [
      { error_class: 'BadRequestError', count: 3, nodes: ['market_research'], agent_roles: [] },
    ],
    gates: [
      {
        gate_id: 'scope-confirmation',
        node_id: 'confirm_scope',
        opened: 9,
        answered: 8,
        revise: 4,
        revise_rate: 0.5,
        expired: 1,
        median_seconds: 412,
        edited_fields: { segment: 3 },
      },
    ],
    routes: [
      {
        node_id: 'route_scope',
        node_label: 'Scope decision',
        decisions: 8,
        routes: { scope_approved: 8 },
        unique_routes: 1,
      },
    ],
    outcomes: {
      by_verdict: [{ verdict: 'NEEDS_WORK', runs: 5, mean_confidence: 0.38, cost_per_run: 0.0631 }],
      by_rating: [{ rating: 'good', runs: 3, cost_usd: 0.19 }],
      by_status: { completed: 8, failed: 1 },
    },
    tasks: [
      {
        task_name: 'market_task',
        node_id: 'market_research',
        node_label: 'Market research',
        completions: 9,
        tool_failures: 4,
        truncated_outputs: 3,
      },
    ],
    node_models: [
      {
        node_id: 'market_research',
        label: 'Market research',
        models: ['openrouter/a/cheap', 'openrouter/b/dear'],
        runs: 9,
      },
    ],
    task_completions: 9,
    task_tool_failures: 4,
    rated: 5,
    rating_mix: { good: 3, bad: 1, unsure: 1, unrated: 4 },
    verdicts: 8,
    low_confidence: 2,
    mean_confidence: 0.44,
    sample_run_ids: ['073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba'],
    estimate: true,
    error_note: 'measured -14.5% to +9.95% against billed',
    truncated: false,
  },
  'GET /api/admin/improve/compare': {
    window: { start: '2026-08-20T00:00:00Z', end: '2026-09-19T00:00:00Z', days: 30 },
    workflow_id: 'ug_4d2b81ac',
    axis: 'version',
    node_id: null,
    min_runs: 5,
    arms: [
      {
        key: '1',
        n: 6,
        underpowered: false,
        status_mix: { completed: 5, failed: 1 },
        verdict_mix: { NEEDS_WORK: 4, VALIDATE: 1 },
        mean_confidence: 0.38,
        rating_mix: { good: 1, bad: 2, unrated: 3 },
        gate_revise_rate: 0.5,
        median_duration_ms: 61402,
        cost_per_run_usd: 0.0631,
      },
      {
        key: '2',
        n: 3,
        underpowered: true,
        status_mix: { completed: 3 },
        verdict_mix: { VALIDATE: 2, NEEDS_WORK: 1 },
        mean_confidence: 0.62,
        rating_mix: { good: 2, unrated: 1 },
        gate_revise_rate: 0,
        median_duration_ms: 58110,
        cost_per_run_usd: 0.0588,
      },
    ],
    estimate: true,
    error_note: 'measured -14.5% to +9.95% against billed',
    truncated: false,
  },
  'GET /api/admin/improve/digests': {
    workflow_id: 'ug_4d2b81ac',
    enabled: false,
    total_cost_usd: 0.0121,
    total_count: 1,
    model: 'openrouter/google/gemini-3.5-flash-lite:nitro',
    max_cost_usd: 0.05,
    max_sample_runs: 12,
    max_sample_frames: 400,
    max_input_chars: 40000,
    max_output_tokens: 1200,
    rows: [
      {
        id: 'dg_2f7a91c4',
        workflow_id: 'ug_4d2b81ac',
        created_by: 'user_admin',
        window: { start: '2026-08-20T00:00:00Z', end: '2026-09-19T00:00:00Z', days: 30 },
        sample_runs: 9,
        sample_frames: 312,
        truncated_sample: false,
        model: 'openrouter/google/gemini-3.5-flash-lite:nitro',
        prompt_tokens: 8214,
        completion_tokens: 734,
        cost_usd: 0.0043,
        max_cost_usd: 0.05,
        over_cap: false,
        body: '## What went well\n\nThe first step is approved first time in 4 of 8 runs.\n',
        created_at: '2026-09-18T12:41:07Z',
      },
    ],
  },
  'POST /api/admin/improve/digests': {
    id: 'dg_9911aabb',
    workflow_id: 'ug_4d2b81ac',
    created_by: 'user_admin',
    window: { start: '2026-08-20T00:00:00Z', end: '2026-09-19T00:00:00Z', days: 30 },
    sample_runs: 9,
    sample_frames: 312,
    truncated_sample: false,
    model: 'openrouter/google/gemini-3.5-flash-lite:nitro',
    prompt_tokens: 8100,
    completion_tokens: 700,
    cost_usd: 0.0041,
    max_cost_usd: 0.05,
    over_cap: false,
    body: 'The market step is the one to change first.',
    created_at: '2026-09-19T08:00:00Z',
  },
}

/** The generated file when it exists, and the stand-in until it does. */
function generated(): Record<string, unknown> | null {
  try {
    const raw = readFileSync(path.join(HERE, 'fixtures', 'improveApi.json'), 'utf8')
    return JSON.parse(raw) as Record<string, unknown>
  } catch {
    return null
  }
}

const WIRE = generated() ?? FALLBACK
const A = adminFixture as unknown as Record<string, unknown>

/**
 * Read one endpoint out of the payload, and SAY SO when it is not there.
 *
 * This is the whole cost of the first version of this file in one function.
 * The generated fixture spells the two review endpoints in the PLURAL
 * (`/improve/digests`), the stand-in spelled them singular, and an absent key
 * came out of `bodyFor` as `undefined` - which `JSON.stringify` turns into an
 * empty body, which reaches the panel as `Unexpected end of JSON input`
 * RENDERED ON SCREEN. Six tests failed and not one of them named the cause.
 * A missing key now fails at module load with the key in the message.
 */
function endpoint(name: string): Record<string, unknown> {
  const body = WIRE[name]
  if (!body || typeof body !== 'object') {
    throw new Error(
      `improveApi.json has no \`${name}\`. The keys it does have: ${Object.keys(WIRE)
        .filter((key) => !key.startsWith('_'))
        .join(', ')}`,
    )
  }
  return body as Record<string, unknown>
}

const HOTSPOTS = endpoint('GET /api/admin/improve/hotspots')
const COMPARE = endpoint('GET /api/admin/improve/compare')
const DIGEST = endpoint('GET /api/admin/improve/digests')
const DIGEST_POST = endpoint('POST /api/admin/improve/digests')

/**
 * The helper entries W-API puts in the fixture for exactly this purpose.
 *
 * `_unknown_arm` / `_mixed_arm` are the two arm keys that are neither a
 * version nor a model, and `_evalset_ratings` is the set the export route
 * accepts. Read rather than typed, so the day one of them changes this suite
 * moves with it instead of testing a remembered spelling.
 */
const UNKNOWN_ARM = String(WIRE._unknown_arm ?? 'unknown')
const MIXED_ARM = String(WIRE._mixed_arm ?? 'mixed')
const EVALSET_RATINGS = (WIRE._evalset_ratings as string[] | undefined) ?? [
  'good',
  'bad',
  'unsure',
  'any',
]
const COMPARE_AXES = Object.keys((WIRE._compare_axes ?? {}) as Record<string, unknown>).filter(
  (key) => !key.startsWith('_'),
)

const WORKFLOW_ID = String(HOTSPOTS?.workflow_id ?? 'ug_4d2b81ac')

/** The steps that can be compared: two models or more. R4's rule, read. */
type NodeModels = { node_id: string; label?: string; models: string[] }
const NODE_MODELS = (HOTSPOTS.node_models ?? []) as NodeModels[]
const COMPARABLE = NODE_MODELS.filter((node) => (node.models ?? []).length >= 2)

/** Every request the console made, with its method, so a test can assert what
 *  it did NOT ask - which on this panel is the criterion that matters most. */
let asked: Array<{ url: string; method: string; headers: Headers }> = []

/** Per-URL overrides a single test installs, checked before the fixture. */
let overrides: Array<{ match: string; body: unknown }> = []

function bodyFor(url: string): unknown {
  for (const entry of overrides) {
    if (url.includes(entry.match)) return entry.body
  }
  // The improve arms first: `/api/admin/runs` is a prefix of
  // `/api/admin/runs/{id}/decisions`, so the plan-17 arms keep their own order
  // underneath and nothing here can steal one of them.
  if (url.includes('/api/admin/improve/hotspots')) return HOTSPOTS
  if (url.includes('/api/admin/improve/compare')) return COMPARE
  if (url.includes("/api/admin/improve/digests")) return DIGEST
  if (url.includes('/api/auth/token')) return { token: 'header.payload.signature' }
  if (url.includes('/api/admin/whoami')) return A['GET /api/admin/whoami']
  if (url.includes('/billed')) return A['GET /api/admin/runs/{run_id}/billed']
  if (url.includes('/decisions')) return A['GET /api/admin/runs/{run_id}/decisions']
  if (url.includes('/api/admin/summary')) return A['GET /api/admin/summary']
  if (url.includes('/api/admin/insights')) return A['GET /api/admin/insights']
  if (url.includes('/api/admin/spend')) return A['GET /api/admin/spend']
  if (url.includes('/api/admin/users')) return A['GET /api/admin/users']
  if (url.includes('/api/admin/runs')) return A['GET /api/admin/runs']
  if (url.includes('/api/admin/gates')) return A['GET /api/admin/gates']
  if (url.includes('/api/admin/verdicts')) return A['GET /api/admin/verdicts']
  if (url.includes('/api/admin/health')) return A['GET /api/admin/health']
  if (url.includes('/api/admin/links')) return A['GET /api/admin/links']
  if (url.includes('/api/admin/providers')) return A['GET /api/admin/providers']
  return {}
}

function stubFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = String(init?.method ?? 'GET').toUpperCase()
      asked.push({ url, method, headers: new Headers(init?.headers) })
      if (method === 'POST' && url.includes("/api/admin/improve/digests")) {
        return new Response(JSON.stringify(DIGEST_POST), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/api/admin/export/evalset')) {
        return new Response(new Blob(['{"_header":true}\n'], { type: 'application/x-ndjson' }), {
          status: 200,
          headers: { 'Content-Type': 'application/x-ndjson' },
        })
      }
      return new Response(JSON.stringify(bodyFor(url)), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

/** Replace one endpoint's body for the rest of this test, keeping every other
 *  arm intact - so the shape under test is still the server's. */
function serve(match: string, body: unknown): void {
  overrides = [{ match, body }, ...overrides]
}

async function settle(rounds = 10): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

/** Open the console and press Improve. Everything below starts here. */
async function openImprove() {
  const wrapper = mount(AdminView, { props: { user: null } })
  await settle()
  await wrapper.get('[data-testid="admin-tab-improve"]').trigger('click')
  await settle()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof openImprove>>

/**
 * Choose the workflow the payload is about.
 *
 * The picker is filled from `spend(group_by=workflow)`, whose rows come from
 * the plan-17 fixture and need not name this workflow - so the option is added
 * here rather than assumed. What is under test is what the panel does with a
 * chosen workflow, not which ones a different endpoint happens to list.
 */
async function chooseWorkflow(wrapper: Wrapper): Promise<void> {
  const select = wrapper.get('[data-testid="improve-workflow"]')
  const element = select.element as HTMLSelectElement
  const option = window.document.createElement('option')
  option.value = WORKFLOW_ID
  element.append(option)
  element.value = WORKFLOW_ID
  await select.trigger('change')
  await settle()
}

async function runCompare(wrapper: Wrapper, a: string, b: string): Promise<void> {
  await wrapper.get('[data-testid="improve-compare-a"]').setValue(a)
  await wrapper.get('[data-testid="improve-compare-b"]').setValue(b)
  await wrapper.get('[data-testid="improve-compare-run"]').trigger('click')
  await settle()
}

beforeEach(() => {
  asked = []
  overrides = []
  resetAdminGate()
  // A signed-in admin, so every request this panel makes carries a bearer
  // token: the export's whole point is that it goes through `authedFetch`, and
  // a suite with no session could not tell that from a bare `fetch`.
  clearAccessToken()
  setSessionActive(true)
  stubFetch()
})

afterEach(() => {
  resetAdminGate()
  setSessionActive(false)
  clearAccessToken()
  vi.unstubAllGlobals()
})

/* ── T6: a seventh tab, four docked sections ─────────────────────────────── */

describe('a seventh tab, four docked sections, and no modal', () => {
  it('is the sixth tab, reads `Improve`, and sits between Insights and Health', async () => {
    const wrapper = await openImprove()
    const tabs = wrapper.findAll('[role="tab"]')
    expect(tabs).toHaveLength(7)
    expect(tabs.map((tab) => tab.text())).toEqual([
      'Overview',
      'Money',
      'People',
      'Runs & decisions',
      'Insights',
      'Improve',
      'Health',
    ])
    expect(tabs[5].attributes('aria-selected')).toBe('true')
    wrapper.unmount()
  })

  it('renders the four sections in R7 order, with R7 wording', async () => {
    const wrapper = await openImprove()
    const panel = wrapper.get('#admin-panel-improve')
    const headings = panel.findAll('.admin-block-head h3').map((node) => node.text())
    expect(headings).toEqual([
      'Where runs go wrong',
      'Compare two versions',
      'Export rated runs',
      'Ask a model to review',
    ])
    wrapper.unmount()
  })

  it('is docked: no dialog, no aria-modal, nowhere on the panel', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    expect(wrapper.findAll('[role="dialog"], [aria-modal], dialog')).toHaveLength(0)
    wrapper.unmount()
  })

  it('asks for the workflow list only, and nothing about one graph yet', async () => {
    const wrapper = await openImprove()
    const urls = asked.map((entry) => entry.url)
    expect(urls.some((url) => url.includes('group_by=workflow'))).toBe(true)
    expect(urls.some((url) => url.includes('/improve/hotspots'))).toBe(false)
    expect(wrapper.get('[data-testid="improve-wrong-none"]').text()).toContain(
      'Nothing is fetched until you do',
    )
    wrapper.unmount()
  })

  it('reads the two per-workflow endpoints once a workflow is chosen', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const urls = asked.map((entry) => entry.url)
    for (const route of ['/api/admin/improve/hotspots', '/api/admin/improve/digests']) {
      expect(urls.some((url) => url.includes(route)), route).toBe(true)
    }
    expect(
      urls.filter((url) => url.includes(`workflow_id=${encodeURIComponent(WORKFLOW_ID)}`)).length,
    ).toBeGreaterThan(0)
    wrapper.unmount()
  })

  it('sends the bearer token on every read it makes', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const improve = asked.filter((entry) => entry.url.includes('/api/admin/improve/'))
    expect(improve.length).toBeGreaterThan(0)
    for (const entry of improve) {
      expect(entry.headers.get('Authorization'), entry.url).toBe('Bearer header.payload.signature')
    }
    wrapper.unmount()
  })
})

/* ── Where runs go wrong ─────────────────────────────────────────────────── */

describe('Where runs go wrong names the step, not the mechanism', () => {
  it('draws one row per agent node, named as the payload names it', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const agents = (HOTSPOTS.agents ?? []) as Array<Record<string, string>>
    const rows = wrapper.get('[data-testid="improve-agent-rows"]')
    for (const agent of agents) {
      const name = agent.agent_role || agent.node_label || agent.node_id
      expect(rows.text(), name).toContain(name)
    }
    wrapper.unmount()
  })

  it('writes one sentence per decision point, and warns on exactly the stuck ones', async () => {
    // The warn count is COMPUTED from the payload rather than typed: the rule
    // is "a router that decided something and never varied", and a fixture
    // regenerated with different routers must still be judged by the rule.
    const routes = (HOTSPOTS.routes ?? []) as Array<{ decisions: number; unique_routes: number }>
    const stuck = routes.filter((row) => row.unique_routes <= 1 && row.decisions > 0).length
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const rows = wrapper.get('[data-testid="improve-route-rows"]')
    expect(rows.findAll('.improve-sentence')).toHaveLength(routes.length)
    expect(rows.findAll('.improve-sentence.is-warn')).toHaveLength(stuck)
    if (stuck > 0) expect(rows.text()).toContain('took the same branch')
    // The finding is a binary; a bar's length would be a second channel
    // encoding traffic, which is not what the reader is here for.
    expect(rows.findAll('[role="progressbar"]')).toHaveLength(0)
    wrapper.unmount()
  })

  it('says an empty task list is an absent instrument, not a zero', async () => {
    serve('/improve/hotspots', {
      ...HOTSPOTS,
      tasks: [],
      task_completions: 0,
      task_tool_failures: 0,
    })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    expect(wrapper.get('[data-testid="improve-tasks-empty"]').text()).toBe(
      'No run recorded after the update has finished a task yet.',
    )
    expect(wrapper.find('[data-testid="improve-task-rows"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('reads what people said about these runs, and offers no way to change it', async () => {
    serve('/improve/hotspots', {
      ...HOTSPOTS,
      runs: 9,
      rated: 5,
      rating_mix: { good: 3, bad: 1, unsure: 1, unrated: 4 },
    })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const line = wrapper.get('[data-testid="improve-rating-line"]').text()
    expect(line).toContain('3 good')
    expect(line).toContain('1 bad')
    expect(line).toContain('1 not sure')
    // Plan 20's control in the run drawer is the only place a rating is SET.
    expect(wrapper.find('[data-testid="improve-rating-line"] button').exists()).toBe(false)
    wrapper.unmount()
  })

  it('offers the sample run ids as copyable text and never as a link', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const ids = (HOTSPOTS.sample_run_ids ?? []) as string[]
    if (ids.length === 0) {
      expect(wrapper.find('[data-testid="improve-sample-runs"]').exists()).toBe(false)
      wrapper.unmount()
      return
    }
    const sample = wrapper.get('[data-testid="improve-sample-runs"]')
    expect(sample.text()).toContain(ids[0])
    expect(sample.findAll('a')).toHaveLength(0)
    expect(wrapper.get(`[data-testid="improve-copy-run-${ids[0]}"]`).attributes('aria-label')).toContain(
      'Copy run id',
    )
    wrapper.unmount()
  })
})

/* ── T6: compare, the two flags, and the required step ───────────────────── */

describe('Compare prints two sides and subtracts nothing', () => {
  it('fetches only on an explicit press, and then shows six measures per side', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    expect(asked.some((entry) => entry.url.includes('/improve/compare'))).toBe(false)
    expect(wrapper.get('[data-testid="improve-compare-empty"]').text()).toContain(
      'Nothing is fetched until you do',
    )

    await runCompare(wrapper, '1', '2')

    const table = wrapper.get('[data-testid="improve-compare-table"]')
    expect(table.findAll('tbody tr')).toHaveLength(6)
    // No delta anywhere: a difference implies a significance nobody has
    // established, and this data cannot establish it.
    expect(table.text()).not.toMatch(/[+-]\d+(\.\d+)?%\s*(better|worse)/i)
    wrapper.unmount()
  })

  it('flags a thin side TWICE: in its own column header and above the table', async () => {
    const arms = (COMPARE.arms ?? []) as Array<Record<string, unknown>>
    serve('/improve/compare', {
      ...COMPARE,
      axis: 'version',
      min_runs: 5,
      arms: [
        { ...arms[0], key: '1', n: 6, underpowered: false },
        { ...(arms[1] ?? arms[0]), key: '2', n: 3, underpowered: true },
      ],
    })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await runCompare(wrapper, '1', '2')

    const headers = wrapper.findAll('[data-testid="improve-compare-table"] thead th')
    expect(headers[2].text()).toContain('n = 3')
    expect(headers[2].text()).toContain('too few runs to tell')
    expect(headers[2].text()).toContain('needs 5')
    // The untouched side carries its `n` and no flag.
    expect(headers[1].text()).toContain('n = 6')
    expect(headers[1].text()).not.toContain('too few runs to tell')

    const over = wrapper.get('[data-testid="improve-compare-thin"]')
    expect(over.attributes('role')).toBe('status')
    expect(over.text()).toContain('too few runs to tell')
    expect(over.text()).toContain('needs 5')
    wrapper.unmount()
  })

  it('shows a side by its key even when the server sends a spare name for it', async () => {
    const arms = (COMPARE.arms ?? []) as Array<Record<string, unknown>>
    serve('/improve/compare', {
      ...COMPARE,
      arms: [{ ...arms[0], key: '7', label: 'a name nothing should read' }],
    })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await runCompare(wrapper, '7', '8')
    const headers = wrapper.findAll('[data-testid="improve-compare-table"] thead th')
    expect(headers[1].text()).toContain('7')
    expect(headers[1].text()).not.toContain('a name nothing should read')
    wrapper.unmount()
  })

  it('says a built-in workflow has no versions, and points at the other axis', async () => {
    const arms = (COMPARE.arms ?? []) as Array<Record<string, unknown>>
    serve('/improve/compare', {
      ...COMPARE,
      axis: 'version',
      arms: [{ ...arms[0], key: 'unknown', underpowered: false }],
    })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await runCompare(wrapper, '1', '2')
    const said = wrapper.get('[data-testid="improve-compare-no-versions"]')
    expect(said.attributes('role')).toBe('status')
    expect(said.text()).toContain('no saved versions to compare')
    expect(said.text()).toContain('Model')
    wrapper.unmount()
  })

  /* ── R4: the model axis needs a step, and the panel enforces it ─────────── */

  /**
   * A hotspots payload with the steps and models this test needs.
   *
   * PATCHED onto the server's own object rather than built: `node_models` is a
   * real key with a real shape, and the only thing under test is what the
   * pickers do with it.
   */
  function withNodeModels(nodeModels: NodeModels[]): void {
    serve('/api/admin/improve/hotspots', { ...HOTSPOTS, node_models: nodeModels })
  }

  const TWO_MODELS: NodeModels[] = [
    { node_id: 'market_research', label: 'Market research', models: ['cheap/a', 'dear/b'] },
    { node_id: 'scope', label: 'Scope', models: ['cheap/a'] },
  ]

  it('offers only the steps that ran on two models or more', async () => {
    withNodeModels(TWO_MODELS)
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await wrapper.get('[data-testid="improve-axis-model"]').trigger('click')
    await settle()
    const values = wrapper
      .get('[data-testid="improve-compare-node"]')
      .findAll('option')
      .map((option) => option.attributes('value'))
    expect(values).toContain('market_research')
    // One model is one arm, and one arm is the same runs printed twice.
    expect(values).not.toContain('scope')
    wrapper.unmount()
  })

  /**
   * The SHIPPED payload, judged by the same rule.
   *
   * The test above patches `node_models` so the rule can be exercised in both
   * directions; this one asks what the committed fixture actually offers, so
   * the day W-API regenerates it with real steps this suite is already reading
   * them rather than only its own invention. A payload with no such key offers
   * nothing and says why, which is the honest answer and is asserted too.
   */
  it('filters the shipped payload by the same two-model rule', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await wrapper.get('[data-testid="improve-axis-model"]').trigger('click')
    await settle()
    const offered = wrapper
      .get('[data-testid="improve-compare-node"]')
      .findAll('option')
      .map((option) => option.attributes('value'))
      .filter((value) => value !== '')
    expect(offered).toEqual(COMPARABLE.map((node) => node.node_id))
    if (COMPARABLE.length === 0) {
      expect(wrapper.get('[data-testid="improve-compare-no-nodes"]').text()).toContain(
        'more than one model',
      )
    }
    expect(NODE_MODELS.length).toBeGreaterThanOrEqual(COMPARABLE.length)
    wrapper.unmount()
  })

  it('offers, for the chosen step, only the models that step actually ran', async () => {
    withNodeModels(TWO_MODELS)
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await wrapper.get('[data-testid="improve-axis-model"]').trigger('click')
    await settle()
    // Before a step is chosen there is nothing to offer, so both boxes are off.
    expect(wrapper.get('[data-testid="improve-compare-a"]').attributes('disabled')).toBeDefined()

    await wrapper.get('[data-testid="improve-compare-node"]').setValue('market_research')
    await settle()
    const offered = wrapper
      .get('[data-testid="improve-compare-a"]')
      .findAll('option')
      .map((option) => option.attributes('value'))
      .filter(Boolean)
    expect(offered).toEqual(['cheap/a', 'dear/b'])
    wrapper.unmount()
  })

  it('says so, and offers nothing, when no step ran on a second model', async () => {
    withNodeModels([{ node_id: 'scope', label: 'Scope', models: ['cheap/a'] }])
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await wrapper.get('[data-testid="improve-axis-model"]').trigger('click')
    await settle()
    expect(wrapper.get('[data-testid="improve-compare-no-nodes"]').text()).toContain(
      'more than one model',
    )
    const pickable = wrapper
      .get('[data-testid="improve-compare-node"]')
      .findAll('option')
      .filter((option) => option.attributes('value') !== '')
    expect(pickable).toHaveLength(0)
    expect(wrapper.get('[data-testid="improve-compare-run"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('will not call the server on the model axis without a step, and says why', async () => {
    withNodeModels(TWO_MODELS)
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await wrapper.get('[data-testid="improve-axis-model"]').trigger('click')
    await settle()

    const button = wrapper.get('[data-testid="improve-compare-run"]')
    expect(button.attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="improve-compare-blocked"]').text()).toContain(
      'Choose a step first',
    )
    await button.trigger('click')
    await settle()
    // R4 from the client side: the server answers 422 without a step, and a
    // refusal the panel could have avoided is a refusal a reader has to read
    // as something the server would not do.
    expect(asked.some((entry) => entry.url.includes('/improve/compare'))).toBe(false)
    wrapper.unmount()
  })

  it('sends axis, both models and the step once a step is chosen', async () => {
    withNodeModels(TWO_MODELS)
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await wrapper.get('[data-testid="improve-axis-model"]').trigger('click')
    await settle()

    await wrapper.get('[data-testid="improve-compare-node"]').setValue('market_research')
    await wrapper.get('[data-testid="improve-compare-a"]').setValue('cheap/a')
    await wrapper.get('[data-testid="improve-compare-b"]').setValue('dear/b')
    await wrapper.get('[data-testid="improve-compare-run"]').trigger('click')
    await settle()

    const call = asked.find((entry) => entry.url.includes('/improve/compare'))
    expect(call).toBeDefined()
    expect(call?.url).toContain('axis=model')
    expect(call?.url).toContain(`node_id=${encodeURIComponent('market_research')}`)
    expect(call?.url).toContain(`a=${encodeURIComponent('cheap/a')}`)
    expect(call?.url).toContain(`b=${encodeURIComponent('dear/b')}`)
    wrapper.unmount()
  })

  /* -- the two arm keys that are neither a version nor a model ------------- */

  it('gives the mixed and unknown arms a sentence each, not a bare word', async () => {
    const arms = (COMPARE.arms ?? []) as Array<Record<string, unknown>>
    serve('/api/admin/improve/compare', {
      ...COMPARE,
      axis: 'model',
      node_id: 'market_research',
      arms: [
        { ...arms[0], key: 'cheap/a', underpowered: false },
        { ...(arms[1] ?? arms[0]), key: MIXED_ARM, underpowered: false },
        { ...(arms[1] ?? arms[0]), key: UNKNOWN_ARM, underpowered: false },
      ],
    })
    withNodeModels(TWO_MODELS)
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await wrapper.get('[data-testid="improve-axis-model"]').trigger('click')
    await settle()
    await wrapper.get('[data-testid="improve-compare-node"]').setValue('market_research')
    await wrapper.get('[data-testid="improve-compare-a"]').setValue('cheap/a')
    await wrapper.get('[data-testid="improve-compare-b"]').setValue('dear/b')
    await wrapper.get('[data-testid="improve-compare-run"]').trigger('click')
    await settle()

    expect(wrapper.get(`[data-testid="improve-arm-note-${MIXED_ARM}"]`).text()).toBe(
      'Runs where this step used more than one model',
    )
    expect(wrapper.get(`[data-testid="improve-arm-note-${UNKNOWN_ARM}"]`).text()).toBe(
      'Runs whose version could not be worked out',
    )
    // A real arm gets no sentence: it is named by the thing it is.
    expect(wrapper.find('[data-testid="improve-arm-note-cheap/a"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('offers exactly the axes the server declares', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    for (const axis of COMPARE_AXES) {
      expect(wrapper.find(`[data-testid="improve-axis-${axis}"]`).exists(), axis).toBe(true)
    }
    wrapper.unmount()
  })

  it('sends no step on the version axis, where one would mean nothing', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await runCompare(wrapper, '1', '2')
    const call = asked.find((entry) => entry.url.includes('/improve/compare'))
    expect(call?.url).toContain('axis=version')
    expect(call?.url).not.toContain('node_id=')
    wrapper.unmount()
  })

  it('clears both sides when the axis changes, so no control lies about what it will send', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await runCompare(wrapper, '1', '2')
    expect(wrapper.find('[data-testid="improve-compare-table"]').exists()).toBe(true)

    await wrapper.get('[data-testid="improve-axis-model"]').trigger('click')
    await settle()
    expect(
      (wrapper.get('[data-testid="improve-compare-a"]').element as HTMLSelectElement).value,
    ).toBe('')
    expect(wrapper.find('[data-testid="improve-compare-table"]').exists()).toBe(false)
    wrapper.unmount()
  })
})

/* ── T6: the export, its four sets, and the authenticated download ───────── */

describe('Export rated runs says what is in the file, and fetches it with the token', () => {
  /**
   * ONE BUTTON PER VALUE THE ROUTE ACCEPTS, and the list is the fixture's own
   * `_evalset_ratings` rather than four strings typed here. The route answers
   * 422 for anything outside it, so a button this panel offered and the server
   * refused would be a control that cannot work; and a value the server accepts
   * with no button is a set nobody can reach.
   */
  it('offers one set per rating the server accepts, and says which is which', async () => {
    const wrapper = await openImprove()
    const buttons = wrapper.findAll('[data-testid^="improve-export-"]')
    const offered = buttons
      .map((button) => button.attributes('data-testid')?.replace('improve-export-', ''))
      .filter((id) => id !== 'run' && id !== 'warning' && id !== 'problem' && id !== 'window' && id !== 'blocked')
    expect(offered.sort()).toEqual([...EVALSET_RATINGS].sort())
    for (const id of EVALSET_RATINGS) {
      const button = wrapper.get(`[data-testid="improve-export-${id}"]`)
      expect(button.text().length, id).toBeGreaterThan(0)
      expect(button.attributes('title'), id).toBeTruthy()
    }
    // Plain words, not the wire values: `unsure` is `Not sure` on screen.
    expect(wrapper.get('[data-testid="improve-export-unsure"]').text()).toBe('Not sure')
    wrapper.unmount()
  })

  it('names the redaction rule on the control itself', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const warning = wrapper.get('[data-testid="improve-export-warning"]').text()
    expect(warning).toContain('NAMED like secrets')
    expect(warning).toContain('pasted into the text of an idea')
    // What the file holds, in the words plan 21 R3 uses.
    expect(warning).toContain('what a person typed')
    expect(warning).toContain('approval')
    wrapper.unmount()
  })

  it('downloads through an authenticated fetch and names the file for the set', async () => {
    const clicks: Array<{ download: string; href: string }> = []
    const clickSpy = vi
      .spyOn(HTMLElement.prototype, 'click')
      .mockImplementation(function record(this: HTMLAnchorElement) {
        clicks.push({ download: this.download, href: this.href })
      })
    try {
      const wrapper = await openImprove()
      await chooseWorkflow(wrapper)
      await wrapper.get('[data-testid="improve-export-bad"]').trigger('click')
      await wrapper.get('[data-testid="improve-export-run"]').trigger('click')
      await settle()

      const call = asked.find((entry) => entry.url.includes('/api/admin/export/evalset'))
      expect(call).toBeDefined()
      // A plain `<a href>` carries no bearer token and would collect a 404 that
      // reads as "there is nothing here" on a file that exists.
      expect(call?.headers.get('Authorization')).toBe('Bearer header.payload.signature')
      expect(call?.url).toContain(`workflow_id=${encodeURIComponent(WORKFLOW_ID)}`)
      expect(call?.url).toContain('rating=bad')

      expect(clicks).toHaveLength(1)
      expect(clicks[0].download).toBe(`${WORKFLOW_ID}-bad-runs.ndjson`)
      expect(clicks[0].href.startsWith('blob:')).toBe(true)
      wrapper.unmount()
    } finally {
      clickSpy.mockRestore()
    }
  })

  it('cannot be pressed before a workflow is chosen, and says so', async () => {
    const wrapper = await openImprove()
    expect(wrapper.get('[data-testid="improve-export-run"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="improve-export-blocked"]').text()).toContain(
      'Pick a workflow first',
    )
    wrapper.unmount()
  })

  it("shows the server's own sentence when the download is refused", async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/auth/token')) {
          return new Response(JSON.stringify({ token: 'header.payload.signature' }), { status: 200 })
        }
        if (url.includes('/export/evalset')) {
          return new Response(JSON.stringify({ detail: 'that window holds no rated runs' }), {
            status: 422,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        return new Response(JSON.stringify(bodyFor(url)), { status: 200 })
      }),
    )
    await wrapper.get('[data-testid="improve-export-run"]').trigger('click')
    await settle()
    expect(wrapper.get('[data-testid="improve-export-problem"]').text()).toContain(
      'that window holds no rated runs',
    )
    wrapper.unmount()
  })
})

/* ── T6: the review, priced before the press ─────────────────────────────── */

describe('Ask a model to review prices itself before the press', () => {
  it('shows the ceiling, the tier, both bounds and whether it is on', async () => {
    serve('/api/admin/improve/digests', {
      ...DIGEST,
      enabled: false,
      model: 'openrouter/google/gemini-3.5-flash-lite:nitro',
      max_cost_usd: 0.05,
      max_sample_runs: 12,
      max_sample_frames: 400,
      max_input_chars: 40000,
      max_output_tokens: 1200,
    })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const quote = wrapper.get('[data-testid="improve-review-quote"]').text()
    expect(quote).toContain('up to $0.05')
    expect(quote).toContain('gemini-3.5-flash-lite')
    expect(quote).toContain('the cheap tier')
    expect(quote).toContain('12 newest runs')
    expect(quote).toContain('400 frames')
    expect(quote).toContain('40,000 characters in')
    expect(quote).toContain('1,200 tokens back')
    expect(wrapper.get('[data-testid="improve-review-price"]').text()).toContain(
      'This spends real money: at most $0.05 per review',
    )
    wrapper.unmount()
  })

  it('is disabled while the flag is off, and says so in the plain sentence', async () => {
    serve('/api/admin/improve/digests', { ...DIGEST, enabled: false })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const button = wrapper.get('[data-testid="improve-review-run"]')
    expect(button.text()).toContain('Ask a model to review')
    expect(button.attributes('disabled')).toBeDefined()
    const blocked = wrapper.get('[data-testid="improve-review-blocked"]')
    expect(blocked.attributes('role')).toBe('status')
    expect(blocked.text()).toContain('Turned off on this server')
    wrapper.unmount()
  })

  it('posts nothing on mount, on opening the tab, or on choosing a workflow', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    expect(asked.filter((entry) => entry.method === 'POST')).toEqual([])
    wrapper.unmount()
  })

  it('posts exactly once on the press, and puts the new review at the top', async () => {
    serve('/api/admin/improve/digests', { ...DIGEST, enabled: true })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const button = wrapper.get('[data-testid="improve-review-run"]')
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click')
    await settle()

    const posts = asked.filter((entry) => entry.method === 'POST')
    expect(posts).toHaveLength(1)
    // THE PATH AND THE SHAPE, pinned. The route is `/improve/digests` and its
    // `workflow_id` is a QUERY parameter: a JSON body against it is a 422 for
    // a missing parameter, which on the one control that spends money would
    // read as "the server refused" rather than "the client asked wrongly".
    expect(posts[0].url).toContain('/api/admin/improve/digests')
    expect(posts[0].url).toContain(`workflow_id=${encodeURIComponent(WORKFLOW_ID)}`)
    // One more row than the page carried, holding what the POST answered.
    // `.trim()`, because `text()` trims and the stored body ends in a newline -
    // ordering is proved on its own, with explicit dates, further down.
    const rows = wrapper.findAll('[data-testid="improve-review-rows"] .improve-review-row')
    expect(rows).toHaveLength((DIGEST.rows as unknown[]).length + 1)
    expect(rows[0].text()).toContain(String(DIGEST_POST.body).trim())
    wrapper.unmount()
  })

  it('renders the review as text, never as markup', async () => {
    serve('/api/admin/improve/digests', {
      ...DIGEST,
      rows: [
        {
          ...((DIGEST.rows as Array<Record<string, unknown>>)[0] ?? {}),
          id: 'dg_text',
          body: '# Not a heading <script>alert(1)</script>',
        },
      ],
    })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const body = wrapper.get('[data-testid="improve-review-rows"] .improve-review-body')
    expect(body.text()).toContain('# Not a heading <script>alert(1)</script>')
    expect(body.html()).not.toContain('<script')
    expect(body.findAll('h1')).toHaveLength(0)
    wrapper.unmount()
  })

  it('shows a review that came out over its ceiling, rather than hiding it', async () => {
    serve('/api/admin/improve/digests', {
      ...DIGEST,
      rows: [
        {
          ...((DIGEST.rows as Array<Record<string, unknown>>)[0] ?? {}),
          id: 'dg_over',
          cost_usd: 0.07,
          max_cost_usd: 0.05,
          over_cap: true,
        },
      ],
    })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const warning = wrapper.get('[data-testid="improve-review-over-cap-dg_over"]')
    expect(warning.attributes('role')).toBe('status')
    expect(warning.text()).toContain('above the ceiling')
    wrapper.unmount()
  })

  it('says how many reviews there have been and what they cost', async () => {
    serve('/api/admin/improve/digests', { ...DIGEST, total_cost_usd: 0.0121, total_count: 4 })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const total = wrapper.get('[data-testid="improve-review-total"]').text()
    expect(total).toContain('Reviews so far: 4')
    expect(total).toContain('$0.01')
    expect(total).toContain('spent')
    wrapper.unmount()
  })

  /*
   * THE PRODUCTION PATH, and the test above it is the forward-compatible one.
   * `ImproveDigestsModel` carries no `total_count`, so the count on screen is
   * the page's own length - a floor rather than a wrong number - and that is
   * what a real deployment shows. Pinned separately so nobody reads the
   * `total_count` test as evidence the server sends one.
   */
  it('counts the page it was given when the server sends no total', async () => {
    const first = (DIGEST.rows as Array<Record<string, unknown>>)[0] ?? {}
    const page = { ...DIGEST, total_cost_usd: 0.0121, rows: [first, { ...first, id: 'dg_two' }] }
    delete (page as Record<string, unknown>).total_count
    serve('/api/admin/improve/digests', page)
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    expect(wrapper.get('[data-testid="improve-review-total"]').text()).toContain(
      'Reviews so far: 2',
    )
    wrapper.unmount()
  })

  it('lists stored reviews newest first, whatever order they arrived in', async () => {
    const first = (DIGEST.rows as Array<Record<string, unknown>>)[0] ?? {}
    serve('/api/admin/improve/digests', {
      ...DIGEST,
      rows: [
        { ...first, id: 'dg_old', body: 'the older one', created_at: '2026-09-01T00:00:00Z' },
        { ...first, id: 'dg_new', body: 'the newer one', created_at: '2026-09-18T00:00:00Z' },
      ],
    })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const rows = wrapper.findAll('[data-testid="improve-review-rows"] .improve-review-row')
    expect(rows[0].text()).toContain('the newer one')
    expect(rows[1].text()).toContain('the older one')
    wrapper.unmount()
  })
})

/* ── T7: the words on screen ─────────────────────────────────────────────── */

describe('the panel says none of the words R7 bans', () => {
  /*
   * A GREP OVER THE RENDERED TEXT, not over the source. R7's list is the
   * owner's: an engineering noun on this screen is a screen named after its
   * implementation, and the reader is the person who drew the workflow.
   */
  const BANNED = [/hotspot/i, /\bmining\b/i, /\bmine\b/i, /digest/i, /\beval\b/i, /evalset/i, /\blabel/i]

  it('renders none of them anywhere in the Improve tab', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const text = wrapper.get('#admin-panel-improve').text()
    for (const pattern of BANNED) {
      expect(text, String(pattern)).not.toMatch(pattern)
    }
    wrapper.unmount()
  })

  it('says none of them once a comparison and a review are on screen either', async () => {
    serve('/api/admin/improve/digests', { ...DIGEST, enabled: true })
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    await runCompare(wrapper, '1', '2')
    await wrapper.get('[data-testid="improve-review-run"]').trigger('click')
    await settle()
    const text = wrapper.get('#admin-panel-improve').text()
    for (const pattern of BANNED) {
      expect(text, String(pattern)).not.toMatch(pattern)
    }
    wrapper.unmount()
  })

  it('names no environment variable to the reader', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    const text = wrapper.get('#admin-panel-improve').text()
    expect(text).not.toContain('IMPROVE_DIGEST_ENABLED')
    expect(text).not.toContain('IMPROVE_MIN_COMPARE_RUNS')
    expect(text).not.toMatch(/[A-Z][A-Z0-9]*_[A-Z0-9_]+/)
    wrapper.unmount()
  })

  it('writes no em dash into its own prose', async () => {
    const wrapper = await openImprove()
    await chooseWorkflow(wrapper)
    // The one long dash this console uses is `—` as the MISSING-VALUE glyph,
    // which `adminFormat.money` and `count` return and which is never prose.
    // Anything with a letter on both sides of it is a sentence using one.
    const text = wrapper.get('#admin-panel-improve').text()
    expect(text).not.toMatch(/\w\s*—\s*\w/)
    wrapper.unmount()
  })
})
