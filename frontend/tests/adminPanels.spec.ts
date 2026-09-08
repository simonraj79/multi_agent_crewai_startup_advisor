import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminView from '../src/views/AdminView.vue'
import AdminDrawer from '../src/components/admin/AdminDrawer.vue'
import { resetAdminGate } from '../src/services/adminApi'
import type { AdminRunRow } from '../src/services/adminApi'
import fixture from './fixtures/adminApi.json'

/**
 * Five docked panels, one docked drawer, no modal anywhere — and every dollar
 * carrying the word that says what kind of number it is.
 *
 * `.agent/plans/17-admin-console.md` criteria 23 and 26. Everything below is
 * driven by `frontend/tests/fixtures/adminApi.json`, which W-API generates from
 * its own response models and criterion 21 holds the real handlers to. That is
 * the anti-mirror rule (R7, section 14 defect 2) working in the direction that
 * matters here: this suite cannot pass against a shape the server does not
 * produce, because the shape is not written down twice.
 */

/**
 * The fixture, indexed by endpoint.
 *
 * The keys are the contract and the values are illustrative - W-API generates
 * this file from its own response models, and criterion 21 drives the real
 * handlers against it. Read as `unknown` and handed straight to `Response`,
 * because typing it here would be a THIRD spelling of a shape that already has
 * two owners.
 */
const F = fixture as unknown as Record<string, unknown>

/** Every URL the console asked for, so a test can assert what it did NOT ask. */
let asked: string[] = []

/**
 * The fixture, served by URL. The order of these tests matters: `/runs/{id}/…`
 * is checked before `/runs`, or the page would be handed a run list where it
 * asked for one run's decisions.
 */
function bodyFor(url: string): unknown {
  if (url.includes('/api/admin/whoami')) return fixture['GET /api/admin/whoami']
  if (url.includes('/billed')) return F['GET /api/admin/runs/{run_id}/billed']
  if (url.includes('/decisions')) return F['GET /api/admin/runs/{run_id}/decisions']
  if (url.includes('/api/admin/summary')) return F['GET /api/admin/summary']
  if (url.includes('/api/admin/spend')) return F['GET /api/admin/spend']
  if (url.includes('/api/admin/users/')) return F['GET /api/admin/users/{user_id}']
  if (url.includes('/api/admin/users')) return F['GET /api/admin/users']
  if (url.includes('/api/admin/runs')) return F['GET /api/admin/runs']
  if (url.includes('/api/admin/gates')) return F['GET /api/admin/gates']
  if (url.includes('/api/admin/verdicts')) return F['GET /api/admin/verdicts']
  if (url.includes('/api/admin/health')) return F['GET /api/admin/health']
  if (url.includes('/api/admin/links')) return F['GET /api/admin/links']
  if (url.includes('/api/admin/providers')) return F['GET /api/admin/providers']
  return {}
}

function stubFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      asked.push(url)
      return new Response(JSON.stringify(bodyFor(url)), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

async function settle(rounds = 10): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

function mountAdmin() {
  return mount(AdminView, { props: { user: null } })
}

beforeEach(() => {
  asked = []
  resetAdminGate()
  stubFetch()
})

afterEach(() => {
  resetAdminGate()
  vi.unstubAllGlobals()
})

describe('five docked panels behind a tab rail', () => {
  it('renders exactly five tabs, in the order the plan names them', async () => {
    const wrapper = mountAdmin()
    await settle()
    const tabs = wrapper.findAll('[role="tab"]')
    expect(tabs.map((tab) => tab.text())).toEqual([
      'Overview',
      'Money',
      'People',
      'Runs & decisions',
      'Health',
    ])
  })

  it('renders five panels, with exactly one of them showing', async () => {
    const wrapper = mountAdmin()
    await settle()
    const panels = wrapper.findAll('[role="tabpanel"]')
    expect(panels).toHaveLength(5)
    // `hidden` rather than unmounted: every panel is in the document, so a
    // reader tabbing by structure finds five, and only the chosen one paints.
    const shown = panels.filter((panel) => panel.attributes('hidden') === undefined)
    expect(shown).toHaveLength(1)
    expect(shown[0].attributes('id')).toBe('admin-panel-overview')
  })

  it('opens each panel when its tab is pressed, and marks it selected', async () => {
    const wrapper = mountAdmin()
    await settle()
    for (const id of ['money', 'people', 'runs', 'health', 'overview']) {
      await wrapper.get(`[data-testid="admin-tab-${id}"]`).trigger('click')
      await settle(4)
      const tab = wrapper.get(`[data-testid="admin-tab-${id}"]`)
      expect(tab.attributes('aria-selected'), id).toBe('true')
      const panel = wrapper.get(`#admin-panel-${id}`)
      expect(panel.attributes('hidden'), id).toBeUndefined()
      expect(panel.attributes('aria-labelledby'), id).toBe(`admin-tab-${id}`)
    }
  })

  it('puts numbers on every panel, not only the landing one', async () => {
    const wrapper = mountAdmin()
    await settle()
    // Overview: the four tiles.
    expect(wrapper.get('#admin-panel-overview').text()).toContain('28')
    await wrapper.get('[data-testid="admin-tab-money"]').trigger('click')
    await settle()
    expect(wrapper.get('[data-testid="admin-spend-rows"]').text()).toContain(
      'google/gemini-3.8-flash',
    )
    await wrapper.get('[data-testid="admin-tab-people"]').trigger('click')
    await settle()
    expect(wrapper.get('[data-testid="admin-people-table"]').text()).toContain('owner@example.test')
    await wrapper.get('[data-testid="admin-tab-runs"]').trigger('click')
    await settle()
    expect(wrapper.get('[data-testid="admin-runs-table"]').text()).toContain('idea-validator')
    await wrapper.get('[data-testid="admin-tab-health"]').trigger('click')
    await settle()
    expect(wrapper.get('[data-testid="admin-integrity"]').text()).toContain('41,208')
  })

  it('fetches a panel lazily, once, and never re-asks on a second visit', async () => {
    const wrapper = mountAdmin()
    await settle()
    // Money has not been opened, so its grouping has not been asked for.
    expect(asked.filter((url) => url.includes('/api/admin/spend'))).toHaveLength(0)
    await wrapper.get('[data-testid="admin-tab-money"]').trigger('click')
    await settle()
    await wrapper.get('[data-testid="admin-tab-overview"]').trigger('click')
    await wrapper.get('[data-testid="admin-tab-money"]').trigger('click')
    await settle()
    expect(asked.filter((url) => url.includes('/api/admin/spend'))).toHaveLength(1)
  })

  it('sends no from/to at all until a window is chosen', async () => {
    // The client never invents a default window: `ADMIN_DEFAULT_WINDOW_DAYS` is
    // a server constant, and a second copy of it here would be a second answer
    // to what this screen means by "recently".
    const wrapper = mountAdmin()
    await settle()
    const summary = asked.find((url) => url.includes('/api/admin/summary')) ?? ''
    expect(summary).not.toContain('from=')
    await wrapper.get('[data-testid="admin-window-7"]').trigger('click')
    await settle()
    const windowed = asked.filter((url) => url.includes('/api/admin/summary'))
    expect(windowed[windowed.length - 1]).toContain('from=')
  })
})

describe('nothing on this screen is a modal (R15)', () => {
  it('declares no dialog, no aria-modal and no scrim, drawer open or shut', async () => {
    const wrapper = mountAdmin()
    await settle()
    await wrapper.get('[data-testid="admin-tab-runs"]').trigger('click')
    await settle()
    await wrapper.get('[data-testid="admin-run-073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba"]').trigger('click')
    await settle()
    expect(wrapper.find('[data-testid="admin-drawer"]').exists()).toBe(true)
    for (const selector of ['[role="dialog"]', '[role="alertdialog"]', '[aria-modal]', '.scrim', 'dialog']) {
      expect(wrapper.findAll(selector), selector).toHaveLength(0)
    }
  })

  it('docks the drawer as a second column, so the panel beside it is still there', async () => {
    const wrapper = mountAdmin()
    await settle()
    await wrapper.get('[data-testid="admin-tab-runs"]').trigger('click')
    await settle()
    await wrapper.get('[data-testid="admin-run-073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba"]').trigger('click')
    await settle()
    // The table the drawer is about is not hidden, replaced or unmounted: it
    // is the sibling the grid narrows. That is the whole difference between a
    // docked drawer and an overlay.
    expect(wrapper.get('.admin-body').classes()).toContain('has-drawer')
    expect(wrapper.find('[data-testid="admin-runs-table"]').exists()).toBe(true)
    expect(wrapper.get('#admin-panel-runs').attributes('hidden')).toBeUndefined()
  })

  it('closes on its own control and leaves the panel untouched', async () => {
    const wrapper = mountAdmin()
    await settle()
    await wrapper.get('[data-testid="admin-tab-people"]').trigger('click')
    await settle()
    await wrapper.get('[data-testid="admin-person-user_owner"]').trigger('click')
    await settle()
    expect(wrapper.find('[data-testid="admin-drawer"]').exists()).toBe(true)
    await wrapper.get('.admin-drawer-close').trigger('click')
    await settle(2)
    expect(wrapper.find('[data-testid="admin-drawer"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="admin-people-table"]').exists()).toBe(true)
  })

  it('shows the operator’s own words in the gate trail', async () => {
    // The one view Langfuse cannot give: content policy hashes it there, so
    // `run_gates.response` is the only copy of what a person actually typed.
    const wrapper = mountAdmin()
    await settle()
    await wrapper.get('[data-testid="admin-tab-runs"]').trigger('click')
    await settle()
    await wrapper.get('[data-testid="admin-run-073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba"]').trigger('click')
    await settle()
    const trail = wrapper.get('[data-testid="admin-gate-trail"]')
    expect(trail.text()).toContain('scope-confirmation')
    expect(trail.text()).toContain('the segment is right, go on')
  })
})

describe('every dollar on screen says it is an estimate (criterion 26)', () => {
  it('carries the word beside every figure, on every panel', async () => {
    const wrapper = mountAdmin()
    await settle()
    for (const id of ['overview', 'money', 'people', 'runs']) {
      await wrapper.get(`[data-testid="admin-tab-${id}"]`).trigger('click')
      await settle()
      const figures = wrapper.get(`#admin-panel-${id}`).findAll('[data-testid="admin-money"]')
      expect(figures.length, `${id} shows no money at all`).toBeGreaterThan(0)
      for (const figure of figures) {
        // The tag is `sr-only` where a kicker already reads `estimate`, so the
        // eye is not told twice and the machine is never told less.
        expect(figure.text().toLowerCase(), `${id}: ${figure.html()}`).toContain('estimate')
      }
    }
  })

  it('prints the measured error band, in the server’s own sentence', async () => {
    const wrapper = mountAdmin()
    await settle()
    const band = wrapper.get('[data-testid="admin-estimate-band"]')
    expect(band.text()).toContain('estimate')
    expect(band.text()).toContain('measured -14.5% to +9.95% against billed')
  })

  it('says the band is missing rather than remembering one', async () => {
    // A range this screen invented would be a range nobody measured, which is
    // worse than none - the "a price written in prose is stale" rule.
    const drawerless = mount(AdminDrawer, {
      props: { run: null, decisions: null, person: null, links: null, loading: false, problem: '' },
    })
    expect(drawerless.html()).toBe('<!--v-if-->')
  })

  it('never rounds a real cost to $0.00', async () => {
    const wrapper = mountAdmin()
    await settle()
    await wrapper.get('[data-testid="admin-tab-runs"]').trigger('click')
    await settle()
    // `cost_usd` on the fixture run is 0.0562551 - two decimal places would
    // print `$0.06`, and a four-cent graph at two places is the shape of the
    // defect this repository shipped once (128,069 tokens at $0.00).
    const row = wrapper.get('[data-testid="admin-runs-table"]').text()
    expect(row).toContain('$0.06')
    expect(row).not.toContain('$0.00')
  })

  it('fetches the billed figure only when somebody presses for it', async () => {
    const wrapper = mountAdmin()
    await settle()
    await wrapper.get('[data-testid="admin-tab-runs"]').trigger('click')
    await settle()
    await wrapper.get('[data-testid="admin-run-073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba"]').trigger('click')
    await settle()
    // Not on page load, not on opening the drawer: it is an outbound call to
    // Langfuse on the server's own thread.
    expect(asked.filter((url) => url.includes('/billed'))).toHaveLength(0)
    await wrapper.get('[data-testid="admin-fetch-billed"]').trigger('click')
    await settle()
    expect(asked.filter((url) => url.includes('/billed'))).toHaveLength(1)
    const billed = wrapper.get('[data-testid="admin-billed"]')
    expect(billed.text()).toContain('$0.06')
    expect(billed.text()).toContain('14.5')
  })

  it('names the unowned bucket rather than dropping it or merging it', async () => {
    // `runs.user_id IS NULL` collapses to `__unowned__`: real spend by real
    // people, and a screen that omitted it would not add up.
    const wrapper = mountAdmin()
    await settle()
    expect(wrapper.get('[data-testid="admin-top-accounts"]').text()).toContain('unowned runs')
  })
})

describe('the drawer says what is fragile about what it shows', () => {
  const RUN = (fixture['GET /api/admin/runs'] as { rows: AdminRunRow[] }).rows[0]

  it('labels the verdict chart as rebuilt from frames', async () => {
    const wrapper = mountAdmin()
    await settle()
    await wrapper.get('[data-testid="admin-tab-runs"]').trigger('click')
    await settle()
    const note = wrapper.get('[data-testid="admin-verdict-fragile"]').text().toLowerCase()
    expect(note).toContain('frames')
  })

  it('warns against raising retention beside the number itself', async () => {
    const wrapper = mountAdmin()
    await settle()
    await wrapper.get('[data-testid="admin-tab-health"]').trigger('click')
    await settle()
    expect(wrapper.get('[data-testid="admin-retention"]').text()).toContain('keep everything')
    const warning = wrapper.get('[data-testid="admin-retention-warning"]').text().toLowerCase()
    expect(warning).toContain('cascades')
    expect(warning).toContain('cap')
  })

  it('renders what the console is blind to in the server’s own words', async () => {
    const wrapper = mountAdmin()
    await settle()
    await wrapper.get('[data-testid="admin-tab-health"]').trigger('click')
    await settle()
    const blind = wrapper.get('[data-testid="admin-blind"]').text()
    expect(blind).toContain('sign-ins')
    expect(blind).toContain('not that the figure is zero')
  })

  it('offers the cancel lever only while a run can still be stopped', () => {
    const finished = mount(AdminDrawer, {
      props: { run: RUN, decisions: null, person: null, links: null, loading: false, problem: '' },
    })
    expect(finished.find('[data-testid="admin-cancel-run"]').exists()).toBe(false)

    const live = mount(AdminDrawer, {
      props: {
        run: { ...RUN, status: 'running' },
        decisions: null,
        person: null,
        links: null,
        loading: false,
        problem: '',
      },
    })
    expect(live.find('[data-testid="admin-cancel-run"]').exists()).toBe(true)
  })
})
