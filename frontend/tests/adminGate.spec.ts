import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import HomeView from '../src/views/HomeView.vue'
import { MOCK_GRAPH } from '../src/data/mockGraph'
import { studioApi } from '../src/services/studioApi'
import { resetAdminGate } from '../src/services/adminApi'
import fixture from './fixtures/adminApi.json'

/**
 * The Admin entry exists only when the SERVER says it does (plan 17,
 * criterion 24).
 *
 * `GET /api/admin/whoami` is the whole gate: it answers 404 - FastAPI's own
 * `"Not Found"` body, byte for byte - for an anonymous caller, for a signed-in
 * non-admin and for a deployment with `ADMIN_EMAILS` unset, so a refused reader
 * cannot tell the route from one that was never built (§9 row 9). Anything on
 * this side that could tell those apart would be advertising the surface the
 * 404 exists to hide, which is why the three refusal shapes below are asserted
 * to produce **the same header** rather than three different ones.
 *
 * WHY IT MOUNTS `HomeView` AND NOT `App`. The entry is drawn by the home's
 * header, and the criterion is about that markup. `App.vue`'s half - a refused
 * `#/admin` landing on the home with one sentence - is asserted through the
 * `notice` prop the router hands down, which is the contract between them.
 */

const WHOAMI = fixture['GET /api/admin/whoami']

/** What `/api/admin/whoami` will answer, per test. */
let whoamiStatus = 200
/** Every URL the page asked for, so a test can assert what it did NOT ask. */
let asked: string[] = []
/** Set when the whoami leg should reject outright, as a dead network does. */
let whoamiThrows = false

function stubFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      asked.push(url)
      if (url.includes('/api/admin/whoami')) {
        if (whoamiThrows) throw new TypeError('Failed to fetch')
        return new Response(
          whoamiStatus === 200 ? JSON.stringify(WHOAMI) : JSON.stringify({ detail: 'Not Found' }),
          { status: whoamiStatus, headers: { 'Content-Type': 'application/json' } },
        )
      }
      let body: unknown = []
      if (url.includes('/api/builder/workflows')) body = []
      else if (url.includes('/graph')) body = MOCK_GRAPH
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

/** `home.spec.ts`'s settle: the transport probe races a real `setTimeout`. */
async function settle(rounds = 8): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

function mountHome(notice = '') {
  return mount(HomeView, { props: { user: null, resumeOnLoad: false, notice } })
}

/**
 * Rendered markup with the HTML comments blanked out.
 *
 * A comment is prose, and prose ABOUT the rule is not a violation of it -
 * `designTokens.spec.ts` strips comments before its own scan for exactly this
 * reason, and `contrast-audit.mjs` does the same. It matters here because Vue's
 * dev compiler keeps template comments in the DOM (a production build drops
 * them), so the paragraph in `HomeView.vue` explaining WHY the entry is absent
 * would otherwise be the thing that failed the assertion that it is absent.
 */
function visible(html: string): string {
  return html.replace(/<!--[\s\S]*?-->/g, '')
}

beforeEach(() => {
  asked = []
  whoamiStatus = 200
  whoamiThrows = false
  // The gate memoises one answer per page load, which is the point of it - so
  // each test starts from "never asked" rather than inheriting the last one's.
  resetAdminGate()
  window.localStorage.clear()
  window.sessionStorage.clear()
  studioApi.mode = 'probing'
  stubFetch()
})

afterEach(() => {
  resetAdminGate()
  window.localStorage.clear()
  window.sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('the Admin entry is drawn only when whoami answers 200', () => {
  it('draws it for an account the server calls an admin', async () => {
    const wrapper = mountHome()
    await settle()
    const entry = wrapper.find('[data-testid="home-admin"]')
    expect(entry.exists()).toBe(true)
    expect(entry.text()).toContain('Admin')
  })

  it('draws nothing at all on a 404', async () => {
    whoamiStatus = 404
    const wrapper = mountHome()
    await settle()
    expect(wrapper.find('[data-testid="home-admin"]').exists()).toBe(false)
  })

  it('leaves the header byte-identical across every way of being refused', async () => {
    // The criterion says "byte-identical to today's header". The three shapes
    // below are every way this app can fail to be an admin - a 404 from
    // `require_admin`, a 401 from an unauthenticated caller, and a dead
    // network - and the assertion is that they produce ONE header. A build
    // that could tell them apart would be leaking the existence of the route.
    const headers: string[] = []
    for (const arm of [
      () => {
        whoamiStatus = 404
      },
      () => {
        whoamiStatus = 401
      },
      () => {
        whoamiThrows = true
      },
    ]) {
      resetAdminGate()
      whoamiStatus = 200
      whoamiThrows = false
      arm()
      const wrapper = mountHome()
      await settle()
      headers.push(visible(wrapper.get('.app-header').html()))
      wrapper.unmount()
    }
    expect(new Set(headers).size, headers.join('\n\n---\n\n')).toBe(1)
    expect(headers[0]).not.toMatch(/admin/i)
  })

  it('says nothing about admin anywhere on the page when refused', async () => {
    whoamiStatus = 404
    const wrapper = mountHome()
    await settle()
    // Not only the entry: no tooltip, no disabled control, no aria label. A
    // disabled control is still a control, and a reader who can see one has
    // been told the route exists.
    expect(visible(wrapper.html())).not.toMatch(/admin/i)
  })

  it('asks the server exactly once, however many things want the answer', async () => {
    const wrapper = mountHome()
    await settle()
    // `App.vue`, this header and `RunHistory` all want it. The memo is what
    // keeps that one request rather than three, and a page that probed per
    // component would make the gate a load generator.
    expect(asked.filter((url) => url.includes('/api/admin/whoami'))).toHaveLength(1)
    expect(wrapper.find('[data-testid="home-admin"]').exists()).toBe(true)
  })

  it('emits `admin` when the entry is pressed, and nothing else', async () => {
    const wrapper = mountHome()
    await settle()
    await wrapper.get('[data-testid="home-admin"]').trigger('click')
    expect(wrapper.emitted('admin')).toHaveLength(1)
    expect(wrapper.emitted('run')).toBeUndefined()
    expect(wrapper.emitted('build')).toBeUndefined()
  })
})

describe('a refused #/admin lands on the home with one sentence', () => {
  it('renders the notice the router hands it, and never a fabricated screen', async () => {
    whoamiStatus = 404
    const wrapper = mountHome('That address is not available on this account.')
    await settle()
    const notice = wrapper.get('[data-testid="home-notice"]')
    expect(notice.text()).toContain('not available on this account')
    // ONE sentence, and it is a status rather than an alert: nothing failed,
    // they landed here instead.
    expect(notice.attributes('role')).toBe('status')
    // And the home is still the home - the list it always was, not an admin
    // console with the numbers blanked out.
    expect(wrapper.find('[data-testid="home-validator"]').exists()).toBe(true)
    expect(wrapper.find('.admin-panel').exists()).toBe(false)
  })

  it('says nothing when there is nothing to say', async () => {
    const wrapper = mountHome()
    await settle()
    expect(wrapper.find('[data-testid="home-notice"]').exists()).toBe(false)
  })

  it('never says whether the route exists', async () => {
    whoamiStatus = 404
    const wrapper = mountHome('That address is not available on this account.')
    await settle()
    const said = wrapper.get('[data-testid="home-notice"]').text().toLowerCase()
    // The same discretion the server's 404 keeps: no "forbidden", no "admin
    // only", nothing that distinguishes a refusal from an absent route.
    for (const word of ['forbidden', 'permission', 'not an admin', '403', 'unauthorised']) {
      expect(said).not.toContain(word)
    }
  })
})
