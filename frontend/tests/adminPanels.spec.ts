import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminView from '../src/views/AdminView.vue'
import AdminDrawer from '../src/components/admin/AdminDrawer.vue'
import AdminRuns from '../src/components/admin/AdminRuns.vue'
import { personLabel } from '../src/components/admin/adminFormat'
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
  // Before `/api/admin/runs`, or a `PUT …/rating` would be handed a page of
  // runs where it asked for one run's rating - the same ordering hazard the
  // decisions line below is written for.
  if (url.includes('/rating')) {
    return { run_id: '073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba', rating: 'good', note: null,
      rated_by: 'admin@example.test', rated_at: '2026-09-18T12:03:11Z' }
  }
  if (url.includes('/billed')) return F['GET /api/admin/runs/{run_id}/billed']
  if (url.includes('/decisions')) return F['GET /api/admin/runs/{run_id}/decisions']
  if (url.includes('/api/admin/summary')) return F['GET /api/admin/summary']
  // The fixture carries this endpoint since plan 20 (criterion L8, which
  // closed the audit's gap); it used to be hand-typed here, which made the one
  // panel nobody could check against the server the one panel served by a
  // shape this file invented.
  if (url.includes('/api/admin/insights')) return F['GET /api/admin/insights']
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

describe('seven docked panels behind a tab rail', () => {
  it('renders exactly seven tabs, in their navigation order', async () => {
    const wrapper = mountAdmin()
    await settle()
    const tabs = wrapper.findAll('[role="tab"]')
    // `Improve` sits between Insights and Health (plan 21, R7): Insights says
    // what went wrong on its own, Improve is where somebody does something
    // about it, and Health stays last because it is the only tab about the
    // service rather than about the work.
    expect(tabs.map((tab) => tab.text())).toEqual([
      'Overview',
      'Money',
      'People',
      'Runs & decisions',
      'Insights',
      'Improve',
      'Health',
    ])
  })

  it('renders seven panels, with exactly one of them showing', async () => {
    const wrapper = mountAdmin()
    await settle()
    const panels = wrapper.findAll('[role="tabpanel"]')
    expect(panels).toHaveLength(7)
    // `hidden` rather than unmounted: every panel is in the document, so a
    // reader tabbing by structure finds seven, and only the chosen one paints.
    const shown = panels.filter((panel) => panel.attributes('hidden') === undefined)
    expect(shown).toHaveLength(1)
    expect(shown[0].attributes('id')).toBe('admin-panel-overview')
  })

  it('opens each panel when its tab is pressed, and marks it selected', async () => {
    const wrapper = mountAdmin()
    await settle()
    for (const id of ['money', 'people', 'runs', 'insights', 'improve', 'health', 'overview']) {
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

  /*
   * ── was this run good? (plan 20, criterion L11) ────────────────────────
   *
   * Three assertions, one per surface, and each of them is about the thing
   * that would be wrong in a way nobody notices: a chip that reports a rating
   * for a run that has none, a filter that narrows the page on screen instead
   * of asking the server, and an admin control writing through the owner's
   * door, where it would 404 on everybody else's run.
   */
  it('shows a chip only on a rated row, and asks the server to filter', async () => {
    const page = {
      rows: [
        { ...RUN, rating: 'good' as const, rated_by: 'admin@example.test' },
        { ...RUN, run_id: '9a2f0000-0000-4000-8000-000000000002', rating: null },
      ],
      next: null,
    }
    const wrapper = mount(AdminRuns, {
      props: {
        runs: page, gates: null, verdicts: null, links: null,
        selectedRunId: null, rating: '' as const, loading: false, problem: '',
      },
    })
    expect(wrapper.get(`[data-testid="admin-run-rating-${RUN.run_id}"]`).text()).toBe('Good')
    // Nothing at all on an unrated row: an empty cell already reads as "not
    // rated", and a chip saying so would be a second word for silence in every
    // row of the table.
    expect(
      wrapper.find('[data-testid="admin-run-rating-9a2f0000-0000-4000-8000-000000000002"]').exists(),
    ).toBe(false)

    const filter = wrapper.get('[data-testid="admin-runs-rating-filter"]')
    expect(filter.findAll('option').map((option) => option.text())).toEqual([
      'All', 'Good', 'Bad', 'Not sure', 'Not rated',
    ])
    await filter.setValue('unrated')
    expect(wrapper.emitted('selectRating')?.[0]).toEqual(['unrated'])
    wrapper.unmount()
  })

  it('sends the chosen rating as a query and re-asks the server for it', async () => {
    const wrapper = mountAdmin()
    await settle()
    await wrapper.get('[data-testid="admin-tab-runs"]').trigger('click')
    await settle()
    // Nothing until somebody chooses: the server decides what an absent filter
    // means, and a client spelling of "any" would be a second answer to it.
    expect(asked.filter((url) => url.includes('/api/admin/runs?')).join('')).not.toContain('rating=')

    await wrapper.get('[data-testid="admin-runs-rating-filter"]').setValue('bad')
    await settle()
    const runLists = asked.filter((url) => url.includes('/api/admin/runs?'))
    expect(runLists[runLists.length - 1]).toContain('rating=bad')
  })

  it('rates a run from the drawer through the ADMIN door, and re-reads it after', async () => {
    const wrapper = mountAdmin()
    await settle()
    await wrapper.get('[data-testid="admin-tab-runs"]').trigger('click')
    await settle()
    await wrapper.get(`[data-testid="admin-run-${RUN.run_id}"]`).trigger('click')
    await settle()

    const drawer = wrapper.get('[data-testid="admin-drawer"]')
    expect(drawer.text()).toContain('Was this run good?')
    // Read off the fixture's OWN `rating` object, note included - which is the
    // whole point of reading it through `readRunRating`: the server answers
    // `rating_note` where §2.2 says `note`, and a drawer that read only one of
    // the two spellings would drop the sentence somebody typed and say nothing.
    const current = drawer.get('[data-testid="admin-rating-current"]').text()
    expect(current).toContain('Good')
    // D9: the console's own `personLabel`, so a long account id is elided the
    // way it is in every other cell rather than printed raw in this one. When
    // the rater IS the run's owner the drawer already holds their e-mail, and
    // production's first rating read "gkHdcQ0SRs…" two lines under it.
    expect(current).toContain(personLabel('user_owner', 'owner@example.test'))
    expect(current).not.toContain('user_owner')
    expect(current).toContain('the segment was right and every claim was cited')
    expect(drawer.get('[data-testid="rating-good"]').attributes('aria-pressed')).toBe('true')
    // A raw account id is what this used to print. `personLabel` elides one
    // that does not fit, so the long form must NOT appear whole.
    const long = mount(AdminDrawer, {
      props: {
        run: RUN, person: null, links: null, loading: false, problem: '',
        decisions: { gates: [], guardrails: [], fallback_models: [],
          rating: { run_id: RUN.run_id, rating: 'bad', rating_note: null,
            rated_by: 'user_a_very_long_account_identifier', rated_at: null } },
      },
    })
    const line = long.get('[data-testid="admin-rating-current"]').text()
    expect(line).not.toContain('user_a_very_long_account_identifier')
    expect(line).toContain(personLabel('user_a_very_long_account_identifier', null))
    long.unmount()

    await drawer.get('[data-testid="rating-bad"]').trigger('click')
    await settle()
    const writes = asked.filter((url) => url.includes('/rating'))
    expect(writes).toHaveLength(1)
    // `/api/admin/runs/{id}/rating`, never `/api/runs/{id}/rating`:
    // `require_own_run` would answer 404 for somebody else's run, which is
    // every run an admin opens this drawer on.
    expect(writes[0]).toContain(`/api/admin/runs/${RUN.run_id}/rating`)
    // The server is the truth on this screen, so a save re-reads the row and
    // the drawer rather than patching either of them.
    expect(asked.filter((url) => url.includes('/decisions')).length).toBeGreaterThan(1)
  })

  it('reads the labels strip and the rated_bad card off the SERVER own insights shape', async () => {
    // Against `GET /api/admin/insights` as W-API generates it, not a payload
    // this file typed: the strip's four counts and the finding a person's
    // judgement produced both have to survive the real response.
    const wrapper = mountAdmin()
    await settle()
    await wrapper.get('[data-testid="admin-tab-insights"]').trigger('click')
    await settle()
    // The fixture's own coverage is bounded, so the strip states a LOWER BOUND
    // in the same words this panel already uses for its finding rates (D10) -
    // "People rated 9 runs good" would be a claim about the whole window that
    // nobody measured.
    const strip = wrapper.get('[data-testid="admin-insights-labels"]').text()
    expect(strip).toContain('at least 9 good')
    expect(strip).toContain('4 bad')
    expect(strip).toContain('At least 10 not rated yet')
    const findings = wrapper.get('[data-testid="admin-insight-findings"]').text()
    expect(findings).toContain('Scope: whole workflow')
    expect(findings).not.toContain('Node (run)')
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
