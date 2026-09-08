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
 * `GET /api/admin/whoami` is the whole gate, and it is the ONE route on that
 * router that answers a non-admin (amended 2026-09-08): **200 with
 * `admin: false`**, while every other `/api/admin/*` route still answers
 * FastAPI's own 404. The amendment is not a relaxation of §9 row 9 - the
 * SURFACE is still invisible - it is the removal of a failed request from
 * every ordinary page load, which had cost 113 of 145 non-`@launch` E2E tests
 * in the default `ADMIN_EMAILS`-unset configuration.
 *
 * FIVE REFUSAL SHAPES, ONE HEADER. `admin: false`, an anonymous caller, a 404
 * from `require_admin` on an older build, a 401, and a dead network all have
 * to draw the same markup: anything on this side that could tell them apart
 * would be advertising the surface, and the 404 arms have to keep working
 * because `autoDeploy: yes` on two services means this bundle can ship a
 * minute before the API it was built against.
 *
 * WHY IT MOUNTS `HomeView` AND NOT `App`. The entry is drawn by the home's
 * header, and the criterion is about that markup. `App.vue`'s half - a refused
 * `#/admin` landing on the home with one sentence - is asserted through the
 * `notice` prop the router hands down, which is the contract between them.
 */

const WHOAMI = fixture['GET /api/admin/whoami']

/**
 * What `admin: false` looks like on the wire - the FIXTURE's own examples.
 *
 * `_whoami_non_admin` and `_whoami_anonymous` are W-API's, added with the
 * amendment, and they are read rather than reconstructed here for the reason
 * R7 gives about every mirror in this repository: a shape this file typed out
 * for itself would agree with itself at whatever the server stopped sending.
 * The anonymous one carries `user_id: null`, and that has to be legal.
 */
const NOT_AN_ADMIN = fixture._whoami_non_admin
const ANONYMOUS = fixture._whoami_anonymous

/** How `/api/admin/whoami` will answer, per test. */
type WhoamiArm = 'admin' | 'not-admin' | 'anonymous' | 'notFound' | 'unauthorised' | 'dead'
let arm: WhoamiArm = 'admin'
/** Every URL the page asked for, so a test can assert what it did NOT ask. */
let asked: string[] = []

function whoamiResponse(): Response {
  const json = (body: unknown, status: number) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  if (arm === 'admin') return json(WHOAMI, 200)
  // THE AMENDED SHAPE: 200, so the browser logs nothing at all.
  if (arm === 'not-admin') return json(NOT_AN_ADMIN, 200)
  if (arm === 'anonymous') return json(ANONYMOUS, 200)
  return json({ detail: 'Not Found' }, arm === 'unauthorised' ? 401 : 404)
}

function stubFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      asked.push(url)
      if (url.includes('/api/admin/whoami')) {
        if (arm === 'dead') throw new TypeError('Failed to fetch')
        return whoamiResponse()
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
  arm = 'admin'
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

  it('draws nothing for a 200 that says admin: false', async () => {
    // The ordinary case for everybody who is not the owner, and the one the
    // amendment introduced. A 200 body is not a claim that you are an admin.
    arm = 'not-admin'
    const wrapper = mountHome()
    await settle()
    expect(wrapper.find('[data-testid="home-admin"]').exists()).toBe(false)
  })

  it('draws nothing for an anonymous caller, whose user_id is null', async () => {
    arm = 'anonymous'
    const wrapper = mountHome()
    await settle()
    expect(wrapper.find('[data-testid="home-admin"]').exists()).toBe(false)
  })

  it('still draws nothing on the 404 an older backend answers', async () => {
    // KEPT, not replaced. `autoDeploy: yes` on two services means this bundle
    // can reach production a minute before the API it was built against, and a
    // console that threw on the old shape would be a blank screen for that
    // minute.
    arm = 'notFound'
    const wrapper = mountHome()
    await settle()
    expect(wrapper.find('[data-testid="home-admin"]').exists()).toBe(false)
  })

  it('leaves the header byte-identical across every way of being refused', async () => {
    // The criterion says "byte-identical to today's header". The five shapes
    // below are every way this app can fail to be an admin - the amended
    // `admin: false`, an anonymous caller, a 404 from an older
    // `require_admin`, a 401, and a dead network - and the assertion is that
    // they produce ONE header. A build that could tell them apart would be
    // leaking the existence of the route.
    const headers: string[] = []
    for (const shape of ['not-admin', 'anonymous', 'notFound', 'unauthorised', 'dead'] as const) {
      resetAdminGate()
      arm = shape
      const wrapper = mountHome()
      await settle()
      headers.push(visible(wrapper.get('.app-header').html()))
      wrapper.unmount()
    }
    expect(new Set(headers).size, headers.join('\n\n---\n\n')).toBe(1)
    expect(headers[0]).not.toMatch(/admin/i)
  })

  it('says nothing about admin anywhere on the page when refused', async () => {
    arm = 'not-admin'
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
    arm = 'not-admin'
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
    arm = 'not-admin'
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
