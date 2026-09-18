import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AdminInsights from '../src/components/admin/AdminInsights.vue'
import AdminView from '../src/views/AdminView.vue'
import type { AdminInsights as Insights } from '../src/services/adminApi'
import fixture from './fixtures/adminApi.json'

const insight: Insights = {
  workflows: [{ workflow_id: 'idea-validator', runs: 8 }],
  findings: [{
    rule_id: 'repeated_failed_runs',
    severity: 'warning',
    workflow_id: 'idea-validator',
    node_id: 'synthesis',
    gate_id: null,
    title: 'Repeated failures',
    explanation: 'The same workflow failed repeatedly.',
    suggestion: 'Review the synthesis input and its failure trace.',
    affected_runs: 3,
    total_runs: 8,
    rate: 0.375,
    samples: [{
      run_id: 'sample-1', user_id: 'user-1', cost_usd: 0.12, status: 'failed',
      created_at: '2026-09-17T10:00:00Z', seq: 42, gate_id: null,
      langfuse: { session_url: 'https://trace.test/session', trace_url: 'https://trace.test/trace' },
    }, {
      run_id: 'sample-2', user_id: 'user-2', cost_usd: 0.08, status: 'failed',
      created_at: '2026-09-17T11:00:00Z', seq: 51, gate_id: 'scope-gate',
      langfuse: { session_url: null, trace_url: null },
    }],
  }],
  insufficient: [],
  labels: { good: 4, bad: 2, unsure: 1, unrated: 1 },
  suppressed_count: 1,
  thresholds: { min_runs: 3, min_affected_runs: 2 },
  coverage: {
    runs_scanned: 8, frames_scanned: 120, gates_scanned: 4, runs_missing_frames: 0,
    runs_with_integrity_loss: 0, retention_days: 30, truncated: false, incomplete: false, warnings: [],
  },
}

function panel(data: Insights | null = insight) {
  return mount(AdminInsights, {
    props: { insights: data, workflows: insight.workflows, workflowId: '', loading: false, problem: '' },
  })
}

afterEach(() => vi.unstubAllGlobals())

describe('governance insights panel', () => {
  it('states the terminal-run denominator and passes truthful sample metadata', async () => {
    const wrapper = panel()
    expect(wrapper.text()).toContain('3 / 8')
    expect(wrapper.text()).toContain('all sampled terminal idea-validator runs')
    expect(wrapper.text()).toContain('Review the synthesis input')
    expect(wrapper.text()).toContain('estimate $0.12')
    expect(wrapper.text()).toContain('frame 42')
    expect(wrapper.get('[data-testid="admin-insights-coverage"]').text()).toContain('120 frames')
    expect(wrapper.text()).toContain('do not prove cause')
    expect(wrapper.text()).toContain('not node visits')
    await wrapper.get('[data-testid="admin-insight-run-sample-1"]').trigger('click')
    expect(wrapper.emitted('openRun')?.[0]?.[0]).toMatchObject({
      run_id: 'sample-1', user_id: 'user-1', workflow_id: 'idea-validator',
      status: 'failed', created_at: '2026-09-17T10:00:00Z', cost_usd: 0.12,
    })
    expect(wrapper.get('a[aria-label="Open sample trace in Langfuse"]').attributes('href')).toBe('https://trace.test/trace')
  })

  it('distinguishes partial, small-sample, and no-finding states', () => {
    const partial = panel({ ...insight, coverage: { ...insight.coverage, incomplete: true, runs_missing_frames: 2 } })
    expect(partial.get('[data-testid="admin-insights-partial"]').text()).toContain('Partial evidence')
    expect(partial.get('.admin-insight-rate').text()).toContain('at least 3 / 8')
    expect(partial.get('.admin-insight-rate').text()).toContain('of scanned runs')

    const small = panel({ ...insight, findings: [], suppressed_count: 0, insufficient: [{ workflow_id: 'new-flow', total_runs: 2, required_runs: 3 }] })
    expect(small.get('[data-testid="admin-insights-small-sample"]').text()).toContain('2 of 3')

    const empty = panel({ ...insight, findings: [], suppressed_count: 0 })
    expect(empty.get('[data-testid="admin-insights-empty"]').text()).toContain('No repeated governance signals')
    const boundedEmpty = panel({ ...insight, findings: [], coverage: { ...insight.coverage, incomplete: true, truncated: true } })
    expect(boundedEmpty.get('[data-testid="admin-insights-empty"]').text()).toContain('unscanned or missing evidence')
    const mixed = panel({ ...insight, insufficient: [{ workflow_id: 'new-flow', total_runs: 1, required_runs: 3 }] })
    expect(mixed.find('[data-testid="admin-insight-findings"]').exists()).toBe(true)
    expect(mixed.get('[data-testid="admin-insights-small-sample"]').text()).toContain('1 of 3')
  })

  /*
   * ── what people said, beside what the rules found (plan 20, criterion L11)
   *
   * The strip is one sentence over the SAME sample every finding below is
   * counted against. It is absent rather than zeroed when the server does not
   * send `labels`, because an API a minute older than this bundle has never
   * been asked the question - and "0 rated good" would be a measurement of
   * something that was never measured.
   */
  it('says in plain words how the scanned runs were rated', () => {
    const wrapper = panel()
    const strip = wrapper.get('[data-testid="admin-insights-labels"]').text()
    expect(strip).toContain('People rated 4 runs good')
    expect(strip).toContain('2 bad')
    expect(strip).toContain('1 not sure')
    expect(strip).toContain('1 not rated yet')
    // This programme's private vocabulary never reaches the screen.
    for (const banned of ['label', 'mining', 'hotspot']) {
      expect(strip.toLowerCase(), banned).not.toContain(banned)
    }
  })

  it('draws no strip at all when the server did not answer the question', () => {
    const older = { ...insight }
    delete (older as { labels?: unknown }).labels
    const wrapper = panel(older)
    expect(wrapper.find('[data-testid="admin-insights-labels"]').exists()).toBe(false)
    // Everything else still renders: an older API is a missing strip, not a
    // blank panel.
    expect(wrapper.text()).toContain('Repeated failures')
  })

  /*
   * A finding somebody's judgement produced, rendered exactly as a computed one
   * is - card, rate, suggestion, samples - because it IS one row of the same
   * table. The only concession is its scope line: `node_id` is the literal
   * `(run)` (§2.2), so "Node (run)" would name a node that does not exist.
   */
  it('renders a rated_bad finding like any other, and its samples open the drawer', async () => {
    const wrapper = panel({
      ...insight,
      findings: [{
        ...insight.findings[0],
        rule_id: 'rated_bad',
        severity: 'high',
        node_id: '(run)',
        title: 'People rated these runs bad',
        explanation: 'A person said the answer was not worth having. This is a judgement, not a measurement.',
        suggestion: 'Read the notes on these runs before changing the workflow.',
      }],
    })
    const text = wrapper.get('[data-testid="admin-insight-findings"]').text()
    expect(text).toContain('People rated these runs bad')
    expect(text).toContain('3 / 8')
    expect(text).toContain('Read the notes on these runs')
    expect(text).toContain('Scope: whole workflow')
    expect(text).not.toContain('Node (run)')

    await wrapper.get('[data-testid="admin-insight-run-sample-1"]').trigger('click')
    expect(wrapper.emitted('openRun')?.[0]?.[0]).toMatchObject({
      run_id: 'sample-1', workflow_id: 'idea-validator', status: 'failed',
    })
  })

  it('never displays old findings underneath loading or error feedback', async () => {
    const wrapper = panel()
    await wrapper.setProps({ loading: true, insights: null })
    expect(wrapper.text()).toContain('Reading governance signals')
    expect(wrapper.text()).not.toContain('Repeated failures')
    await wrapper.setProps({ loading: false, problem: 'scan unavailable', insights: null })
    expect(wrapper.get('[role="alert"]').text()).toContain('scan unavailable')
    expect(wrapper.text()).not.toContain('Repeated failures')
  })
})

describe('admin insight request ownership', () => {
  it('fetches lazily and ignores an older workflow response', async () => {
    const pending: Array<(value: Response) => void> = []
    const decisionPending: Array<{ url: string; resolve: (value: Response) => void }> = []
    const asked: string[] = []
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      asked.push(url)
      if (url.includes('/api/admin/insights')) {
        return new Promise<Response>((resolve) => pending.push(resolve))
      }
      if (url.includes('/decisions')) {
        return new Promise<Response>((resolve) => decisionPending.push({ url, resolve }))
      }
      const fixtures = fixture as unknown as Record<string, unknown>
      let body: unknown = {}
      if (url.includes('/api/admin/summary')) body = fixtures['GET /api/admin/summary']
      else if (url.includes('/api/admin/health')) body = fixtures['GET /api/admin/health']
      else if (url.includes('/api/admin/providers')) body = fixtures['GET /api/admin/providers']
      else if (url.includes('/api/admin/links')) body = fixtures['GET /api/admin/links']
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }))
    const wrapper = mount(AdminView, { props: { user: null } })
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(asked.some((url) => url.includes('/api/admin/insights'))).toBe(false)

    await wrapper.get('[data-testid="admin-tab-insights"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))
    pending[0](new Response(JSON.stringify(insight), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    await wrapper.get('[data-testid="admin-insights-workflow"]').setValue('idea-validator')
    await new Promise((resolve) => setTimeout(resolve, 0))
    await wrapper.get('[data-testid="admin-insights-workflow"]').setValue('')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(pending).toHaveLength(3)

    pending[2](new Response(JSON.stringify(insight), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(wrapper.text()).toContain('Repeated failures')

    const stale = { ...insight, findings: [{ ...insight.findings[0], title: 'Stale result' }] }
    pending[1](new Response(JSON.stringify(stale), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(wrapper.text()).not.toContain('Stale result')
    expect(asked.filter((url) => url.includes('/api/admin/insights'))[1]).toContain('workflow_id=idea-validator')

    // Leaving invalidates the request and clears its busy state. Its eventual
    // answer cannot paint, and returning starts a fresh read instead of
    // leaving the panel permanently loading.
    await wrapper.get('[data-testid="admin-insights-workflow"]').setValue('idea-validator')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(pending).toHaveLength(4)
    await wrapper.get('[data-testid="admin-tab-overview"]').trigger('click')
    pending[3](new Response(JSON.stringify(stale), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    await wrapper.get('[data-testid="admin-tab-insights"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(pending).toHaveLength(5)
    expect(wrapper.get('#admin-panel-insights').text()).toContain('Reading governance signals')
    expect(wrapper.text()).not.toContain('Stale result')
    pending[4](new Response(JSON.stringify(insight), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(wrapper.text()).toContain('Repeated failures')

    // A late sample A response cannot attach its decisions to sample B.
    await wrapper.get('[data-testid="admin-insight-run-sample-1"]').trigger('click')
    await wrapper.get('[data-testid="admin-insight-run-sample-2"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(decisionPending).toHaveLength(2)
    const decisions = (gate: string) => ({
      gates: [{ gate_id: gate, status: 'answered', outcome: 'revise', response: null }],
      guardrails: [], fallback_models: [],
    })
    decisionPending[1].resolve(new Response(JSON.stringify(decisions('gate-b')), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    decisionPending[0].resolve(new Response(JSON.stringify(decisions('gate-a')), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(wrapper.get('[data-testid="admin-drawer"]').text()).toContain('sample-2')
    expect(wrapper.get('[data-testid="admin-gate-trail"]').text()).toContain('gate-b')
    expect(wrapper.get('[data-testid="admin-gate-trail"]').text()).not.toContain('gate-a')

    // Closing while details load keeps the drawer closed when they arrive.
    await wrapper.get('[data-testid="admin-insight-run-sample-1"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))
    await wrapper.get('[aria-label="Close the drawer"]').trigger('click')
    decisionPending[2].resolve(new Response(JSON.stringify(decisions('gate-after-close')), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(wrapper.find('[data-testid="admin-drawer"]').exists()).toBe(false)
  })
})
