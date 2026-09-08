import { expect, test, type Page } from '@playwright/test'
import { SYNTHETIC_USER_COOKIE } from './syntheticUser'

/**
 * `#/admin` in a real browser: invisible to everybody it is not for, and
 * carrying real numbers for the one person it is.
 *
 * `.agent/plans/17-admin-console.md` criterion 28, non-`@launch`: nothing here
 * presses Launch, so it is free against `SYNTHETIC=1` and free against a
 * deployed origin.
 *
 * ## What only a browser can answer
 *
 * Not layout. Three things a jsdom mount cannot reach: that the ROUTE resolves
 * from a pasted address, that a refused visitor is actually redirected by the
 * running app rather than by a component under test, and that the whole screen
 * loads with **zero console errors** - which is the assertion that catches a
 * request nobody meant to make.
 *
 * ## The two arms, and how the refused one is produced
 *
 * The present arm needs `ADMIN_EMAILS` to name the harness identity. §7 of the
 * plan measured which value that is, and it is worth restating because the
 * answer is not the one the browser sees: the stub auth origin signs the page
 * in as `e2e@example.test`, while the proxies forward
 * `X-Synthetic-User: e2e-user` and `synthetic_identity` builds
 * `AuthenticatedUser(id="e2e-user", email="e2e-user@synthetic")`. The API never
 * reads the stub's email, so **`e2e-user@synthetic`** is the value that
 * matters.
 *
 * The refused arm is a SECOND synthetic identity, not a client-side stub and
 * not a mocked response: `isolation.spec.ts`'s cookie makes the page and the
 * API agree on somebody else, that somebody is not in `ADMIN_EMAILS`, and
 * `require_admin` answers its real 404. The plan's §7 describes the refused arm
 * as the same backend restarted with the knob unset; this is the same refusal
 * from the same code path without a restart, and the file is written so that
 * running it against a backend with the knob unset ALSO passes - the present
 * arm then skips with a message naming the knob, rather than failing over a
 * configuration.
 */

/**
 * An identity the plan's `ADMIN_EMAILS` value cannot match.
 *
 * `stranger`, and NOT `not-an-admin`, which is what this was until the test
 * itself caught it: the account chip renders the synthetic id, so an id with
 * the word `admin` in it failed the very assertion that the word appears
 * nowhere in the header. The rule is about what the app SAYS, and a fixture
 * that smuggles the word in is testing the fixture.
 */
const STRANGER = 'stranger'

/**
 * `builder.spec.ts`'s watch, restated with `isolation.spec.ts`'s escape hatch.
 *
 * A spec file cannot be imported without registering its tests here a second
 * time, which is why every file in this directory restates these rather than
 * sharing them. The hatch exists for one reason and one test uses it: a suite
 * that PROVOKES a 404 on purpose must be able to say so, and the alternative is
 * either tolerating every 404 or being unable to test a refusal at all.
 */
function watchConsole(page: Page, ...allowed: RegExp[]): { unexpected: string[] } {
  const watch = { unexpected: [] as string[] }
  const record = (text: string) => {
    if (allowed.some((pattern) => pattern.test(text))) return
    watch.unexpected.push(text)
  }
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text())
  })
  page.on('pageerror', (error) => record(`uncaught: ${error.message}`))
  return watch
}

/** Home, with nothing a previous test left behind to redirect it away. */
async function openHome(page: Page): Promise<void> {
  await page.goto('/#/run')
  await page.evaluate(() => {
    window.localStorage.clear()
    window.sessionStorage.clear()
  })
  await page.goto('/#/')
  await expect(page.locator('.home-page')).toBeVisible()
}

test.describe('the admin console', () => {
  test('is invisible, and #/admin lands home, for somebody it is not for', async ({ browser }) => {
    const { baseURL, viewport } = test.info().project.use
    if (!baseURL) throw new Error('playwright.config.ts declares no baseURL')
    const context = await browser.newContext({ baseURL, viewport: viewport ?? undefined })
    await context.addCookies([{ name: SYNTHETIC_USER_COOKIE, value: STRANGER, url: baseURL }])
    const page = await context.newPage()
    // The one forgiveness, and it is the refusal this test exists to provoke:
    // `require_admin` answers 404 and Chrome logs a failed resource load for
    // it. Everything else is still an error.
    const watch = watchConsole(page, /admin\/whoami/, /Failed to load resource.*404/)

    try {
      await openHome(page)

      // NOT DRAWN, rather than drawn and disabled: a disabled control is a
      // control, and a reader who can see one has been told the route exists.
      await expect(page.locator('[data-testid="home-admin"]')).toHaveCount(0)
      const header = await page.locator('.app-header').innerText()
      expect(header.toLowerCase()).not.toContain('admin')

      // A pasted address reaches the home with ONE sentence - never a
      // fabricated console, and never a blank screen.
      await page.goto('/#/admin')
      await expect(page.locator('[data-testid="home-notice"]')).toBeVisible()
      await expect(page.locator('.admin-panel')).toHaveCount(0)
      await expect(page.locator('[role="tablist"]')).toHaveCount(0)
      await expect(page).toHaveURL(/#\/$/)

      // The sentence keeps the server's own discretion: it never says whether
      // the route exists.
      const notice = (await page.locator('[data-testid="home-notice"]').innerText()).toLowerCase()
      for (const word of ['forbidden', 'permission', 'admin only', '403']) {
        expect(notice, word).not.toContain(word)
      }

      expect(watch.unexpected, watch.unexpected.join('\n')).toEqual([])
    } finally {
      await context.close()
    }
  })

  test('draws five panels with real numbers, and nothing on the console', async ({
    page,
    request,
  }) => {
    // Measured rather than assumed: ask the API, as the harness identity, and
    // skip with a reason when this backend was started without the knob. That
    // makes this file honest on BOTH configurations instead of red on one.
    const who = await request.get('/api/admin/whoami')
    test.skip(
      who.status() !== 200,
      'this backend names no admin: start it with ADMIN_EMAILS=e2e-user@synthetic '
        + `(GET /api/admin/whoami answered ${who.status()})`,
    )

    const watch = watchConsole(page)
    await openHome(page)

    // The entry appears BECAUSE the server said so, and it is the way in.
    const entry = page.locator('[data-testid="home-admin"]')
    await expect(entry).toBeVisible()
    await entry.click()
    await expect(page).toHaveURL(/#\/admin$/)

    // Five tabs, five panels, one showing.
    const tabs = page.locator('[role="tab"]')
    await expect(tabs).toHaveCount(5)
    await expect(tabs).toHaveText([
      'Overview',
      'Money',
      'People',
      'Runs & decisions',
      'Health',
    ])
    await expect(page.locator('[role="tabpanel"]')).toHaveCount(5)

    // Every panel renders, and each carries a figure the SERVER produced. The
    // synthetic backend starts empty, so the honest assertion is that each
    // panel reaches a settled state with its own numbers - a count, a total, a
    // ceiling - rather than a spinner or a refusal.
    await expect(page.locator('#admin-panel-overview .admin-tiles li')).toHaveCount(4)
    await expect(page.locator('#admin-panel-overview [data-testid="admin-money"]').first()).toContainText('$')
    await expect(page.locator('#admin-panel-overview')).toContainText(/estimate/i)

    await page.locator('[data-testid="admin-tab-money"]').click()
    await expect(page.locator('#admin-panel-money [data-testid="admin-ceilings"]')).toBeVisible()
    await expect(page.locator('#admin-panel-money [data-testid="admin-ceilings"]')).toContainText('$')
    // The five axes are a control, not five blocks: one endpoint, five
    // questions, over one window.
    await expect(page.locator('#admin-panel-money .admin-axis-button')).toHaveCount(5)
    await page.locator('[data-testid="admin-axis-workflow"]').click()
    await expect(page.locator('[data-testid="admin-axis-workflow"]')).toHaveAttribute(
      'aria-pressed',
      'true',
    )

    await page.locator('[data-testid="admin-tab-people"]').click()
    await expect(page.locator('#admin-panel-people .admin-axis-button')).toHaveCount(3)
    await expect(page.locator('#admin-panel-people')).toContainText(/Declared absent/i)

    await page.locator('[data-testid="admin-tab-runs"]').click()
    await expect(page.locator('#admin-panel-runs [data-testid="admin-verdict-fragile"]')).toBeVisible()

    await page.locator('[data-testid="admin-tab-health"]').click()
    const readyz = page.locator('#admin-panel-health [data-testid="admin-readyz"]')
    await expect(readyz).toBeVisible()
    // `/health` calls `health_payload` rather than restating it, so a real
    // backend answers here with its own storage backend.
    await expect(readyz).toContainText(/sqlite|postgresql/i)
    await expect(page.locator('#admin-panel-health [data-testid="admin-integrity"]')).toBeVisible()
    // What the console cannot see, in words - never a blank tile implying zero.
    await expect(page.locator('[data-testid="admin-blind"]')).toContainText(
      'not that the figure is zero',
    )

    // The drawer is docked or absent; it is never a modal, on any panel.
    await expect(page.locator('[role="dialog"], [aria-modal], dialog')).toHaveCount(0)

    // The way back, and the tab name that follows the route.
    await expect(page).toHaveTitle(/Admin/)
    await page.locator('.breadcrumb-crumb', { hasText: 'Workflows' }).click()
    await expect(page.locator('.home-page')).toBeVisible()

    expect(watch.unexpected, watch.unexpected.join('\n')).toEqual([])
  })

  test('never fetches a billed cost on a page load', async ({ page, request }) => {
    const who = await request.get('/api/admin/whoami')
    test.skip(who.status() !== 200, 'this backend names no admin')

    // Criterion 26's other half, and only a browser can see it: `/billed` is an
    // outbound call to Langfuse on the server's own thread, so a console that
    // made one per run per refresh would be a load generator pointed at a third
    // party. Every request the page makes is recorded and searched.
    const asked: string[] = []
    page.on('request', (request_) => asked.push(request_.url()))

    await openHome(page)
    await page.goto('/#/admin')
    await expect(page.locator('[role="tablist"]')).toBeVisible()
    for (const id of ['money', 'people', 'runs', 'health']) {
      await page.locator(`[data-testid="admin-tab-${id}"]`).click()
      await expect(page.locator(`#admin-panel-${id}`)).toBeVisible()
    }

    expect(asked.filter((url) => url.includes('/billed'))).toEqual([])
  })
})
