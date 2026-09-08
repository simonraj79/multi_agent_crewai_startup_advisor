import { readFileSync } from 'node:fs'
import path from 'node:path'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LangfuseLink from '../src/components/admin/LangfuseLink.vue'
import AdminDrawer from '../src/components/admin/AdminDrawer.vue'
import RunHistory from '../src/components/RunHistory.vue'
import { studioApi } from '../src/services/studioApi'
import { resetAdminGate, sessionUrlFor } from '../src/services/adminApi'
import type { AdminLinks, AdminRunRow } from '../src/services/adminApi'
import fixture from './fixtures/adminApi.json'

/**
 * "Open in Langfuse" — or nothing at all.
 *
 * `.agent/plans/17-admin-console.md` criterion 27, and the second half is the
 * whole of it: the link is **hidden when `links.langfuse.configured` is false,
 * rather than rendering a broken URL.** An href to
 * `undefined/project//traces/` is worse than an absent one - it looks like a
 * feature, it is clicked, and what it teaches is that this console lies.
 *
 * A DEPARTURE, RECORDED HERE RATHER THAN HIDDEN. On a `RunHistory` row the
 * link is the **session** only. A trace URL is `trace_id_for(run_id)` - the
 * UUID hex, else the SDK's seeded id, else a sha256 prefix - and criterion 20
 * puts that rule in `observability/backend.py` and forbids a second spelling
 * of it; `GET /api/runs`, which is what that list reads, carries no Langfuse
 * block to take a server-built one from. A session gathers every trace of the
 * run, so the reader still lands on the run's own page. **Both** halves appear
 * on the drawer's run header, where the server supplies each.
 */

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))

const LINKS = fixture['GET /api/admin/links'] as AdminLinks
const RUN = (fixture['GET /api/admin/runs'] as { rows: AdminRunRow[] }).rows[0]

describe('the link is drawn only when Langfuse is configured', () => {
  it('renders an anchor to the server’s own URL', () => {
    const wrapper = mount(LangfuseLink, {
      props: { href: RUN.langfuse?.trace_url, configured: true, kind: 'trace' },
    })
    const anchor = wrapper.get('a')
    expect(anchor.attributes('href')).toBe(RUN.langfuse?.trace_url)
    expect(anchor.text()).toContain('Open trace in Langfuse')
    // A new tab, and no referrer or opener handed to a third party.
    expect(anchor.attributes('target')).toBe('_blank')
    expect(anchor.attributes('rel')).toBe('noreferrer noopener')
  })

  it('renders NOTHING when Langfuse is not configured', () => {
    const wrapper = mount(LangfuseLink, {
      props: { href: RUN.langfuse?.trace_url, configured: false, kind: 'trace' },
    })
    expect(wrapper.find('a').exists()).toBe(false)
    expect(wrapper.html()).toBe('<!--v-if-->')
  })

  it('renders nothing when the server built no URL, even if it is configured', () => {
    // `langfuse.user_url` is null in the fixture: a person has no Langfuse
    // page of their own. An anchor with `href="null"` would be a link to a
    // 404 dressed as a feature.
    const wrapper = mount(LangfuseLink, { props: { href: null, configured: true, kind: 'user' } })
    expect(wrapper.find('a').exists()).toBe(false)
  })

  it('keeps its accessible name when the words do not fit', () => {
    // In a table cell the label is `sr-only` and the icon is the control. The
    // NAME never disappears with the text.
    const wrapper = mount(LangfuseLink, {
      props: { href: 'https://example.test/x', configured: true, kind: 'session', compact: true },
    })
    const anchor = wrapper.get('a')
    expect(anchor.classes()).toContain('is-compact')
    expect(anchor.get('span').classes()).toContain('sr-only')
    expect(anchor.text()).toContain('Open session in Langfuse')
    expect(anchor.attributes('title')).toBe('Open session in Langfuse')
  })
})

describe('sessionUrlFor builds a URL and derives no rule', () => {
  it('is the host, the project and the run id, verbatim', () => {
    // `sessionId` IS the app's own `run_id` (§3, and observability row A1
    // measured it), so nothing here is derived - it is a template over two
    // server-supplied constants and an id the caller already holds.
    expect(sessionUrlFor(LINKS, RUN.run_id)).toBe(
      `${LINKS.langfuse.base_url}/project/${LINKS.langfuse.project_id}/sessions/${RUN.run_id}`,
    )
  })

  it('agrees with the URL the server built for the same run', () => {
    // The one assertion that would catch a drift between the two spellings.
    expect(sessionUrlFor(LINKS, RUN.run_id)).toBe(RUN.langfuse?.session_url)
  })

  it('answers null rather than a broken URL', () => {
    expect(sessionUrlFor(null, RUN.run_id)).toBeNull()
    expect(
      sessionUrlFor({ ...LINKS, langfuse: { ...LINKS.langfuse, configured: false } }, RUN.run_id),
    ).toBeNull()
    expect(
      sessionUrlFor({ ...LINKS, langfuse: { ...LINKS.langfuse, project_id: '' } }, RUN.run_id),
    ).toBeNull()
    expect(sessionUrlFor(LINKS, '')).toBeNull()
  })

  it('tolerates a trailing slash on the host without doubling it', () => {
    const trailing = { ...LINKS, langfuse: { ...LINKS.langfuse, base_url: 'https://lf.test/' } }
    expect(sessionUrlFor(trailing, 'r1')).toBe(
      `https://lf.test/project/${LINKS.langfuse.project_id}/sessions/r1`,
    )
  })

  it('does NOT build a trace URL, which is criterion 20', () => {
    // The guard that has to be a SOURCE scan rather than a behaviour: if this
    // client ever grows a `traceUrlFor`, it has acquired a second spelling of
    // `observability/backend.py::trace_id_for`, and the two will disagree the
    // first time a run id is not a UUID - at which point every trace link on
    // the screen opens a trace that does not exist. Every trace URL here is
    // one the server put in its own response.
    const client = readFileSync(
      path.join(HERE, '..', 'src/services/adminApi.ts'),
      'utf8',
    ).replace(/\/\*[\s\S]*?\*\//g, '')
    expect(client).not.toMatch(/traceUrlFor|\/traces\//)
    expect(client).not.toMatch(/replace\(\/-\/g/)
  })
})

describe('the run header carries both halves (criterion 27)', () => {
  it('shows session AND trace, from the server’s own response', () => {
    const wrapper = mount(AdminDrawer, {
      props: { run: RUN, decisions: null, person: null, links: LINKS, loading: false, problem: '' },
    })
    expect(wrapper.get('[data-testid="langfuse-session"]').attributes('href')).toBe(
      RUN.langfuse?.session_url,
    )
    expect(wrapper.get('[data-testid="langfuse-trace"]').attributes('href')).toBe(
      RUN.langfuse?.trace_url,
    )
  })

  it('shows neither when Langfuse is not configured', () => {
    const off: AdminLinks = { ...LINKS, langfuse: { ...LINKS.langfuse, configured: false } }
    const wrapper = mount(AdminDrawer, {
      props: { run: RUN, decisions: null, person: null, links: off, loading: false, problem: '' },
    })
    expect(wrapper.find('[data-testid="langfuse-session"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="langfuse-trace"]').exists()).toBe(false)
  })
})

/* ── the console's own history rows ───────────────────────────────────────── */

const RUNS = [
  {
    run_id: '073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba',
    label: 'a clinic scheduler',
    status: 'completed',
    created_at: '2026-09-08T11:38:02Z',
    cost_usd: 0.06,
  },
]

let whoamiStatus = 200
let linksConfigured = true

function stubFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/admin/whoami')) {
        return new Response(JSON.stringify(fixture['GET /api/admin/whoami']), {
          status: whoamiStatus,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/api/admin/links')) {
        return new Response(
          JSON.stringify({
            ...LINKS,
            langfuse: { ...LINKS.langfuse, configured: linksConfigured },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      return new Response(JSON.stringify({ runs: RUNS }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

async function settle(rounds = 8): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

beforeEach(() => {
  whoamiStatus = 200
  linksConfigured = true
  resetAdminGate()
  // `listRuns` answers `[]` unless the transport has already been PROVED live
  // - a failure rendered as a confident negative is the defect that comment
  // exists to prevent - so the singleton is put where a console that has
  // probed would be, rather than left holding another file's decision.
  studioApi.mode = 'live'
  stubFetch()
})

afterEach(() => {
  resetAdminGate()
  studioApi.mode = 'probing'
  vi.unstubAllGlobals()
})

describe('each run-history row offers the run’s Langfuse session', () => {
  it('links the row to the session the run id names', async () => {
    const wrapper = mount(RunHistory, { props: { reloadKey: 'k', enabled: true } })
    await settle()
    const link = wrapper.get('.run-history-item [data-testid="langfuse-session"]')
    expect(link.attributes('href')).toBe(
      `${LINKS.langfuse.base_url}/project/${LINKS.langfuse.project_id}/sessions/${RUNS[0].run_id}`,
    )
  })

  it('draws no link when Langfuse is not configured', async () => {
    linksConfigured = false
    const wrapper = mount(RunHistory, { props: { reloadKey: 'k', enabled: true } })
    await settle()
    expect(wrapper.find('[data-testid="langfuse-session"]').exists()).toBe(false)
    // The row itself is untouched: an admin extra that cannot load must not
    // take an operator's own history with it.
    expect(wrapper.get('.run-history-item').text()).toContain('a clinic scheduler')
  })

  it('leaves a non-admin’s history exactly as it was', async () => {
    whoamiStatus = 404
    const wrapper = mount(RunHistory, { props: { reloadKey: 'k', enabled: true } })
    await settle()
    expect(wrapper.find('[data-testid="langfuse-session"]').exists()).toBe(false)
    expect(wrapper.get('.run-history-item').text()).toContain('a clinic scheduler')
  })

  it('never asks for the admin links when whoami said no', async () => {
    whoamiStatus = 404
    const asked: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        asked.push(url)
        if (url.includes('/api/admin/whoami')) {
          return new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 })
        }
        return new Response(JSON.stringify({ runs: RUNS }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
    const wrapper = mount(RunHistory, { props: { reloadKey: 'k', enabled: true } })
    await settle()
    // `/api/admin/links` is behind `require_admin` and would answer 404 - a
    // request whose only possible outcome is a console error the suite does
    // not tolerate.
    expect(asked.filter((url) => url.includes('/api/admin/links'))).toHaveLength(0)
    expect(wrapper.find('[data-testid="langfuse-session"]').exists()).toBe(false)
  })
})
