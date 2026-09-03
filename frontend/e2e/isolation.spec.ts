import {
  expect,
  test,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from '@playwright/test'
import { SYNTHETIC_USER_COOKIE, storageKeyFor } from './syntheticUser'

/**
 * Per-user isolation, end to end, at no cost (plan 01 criterion 11, rubric 14).
 *
 * Two browser contexts are two people. Each one carries the synthetic-user
 * cookie (`syntheticUser.ts`); the e2e Vite server turns it into the
 * `X-Synthetic-User` header on every `/api` and `/ws` request and answers the
 * stub auth origin with a session for that id, so the header chip, the owner
 * column and the bearer path all name the same person. The free backend honours
 * the header only as `SYNTHETIC=1` with no `AUTH_BASE_URL` (plan 01 D8), which
 * is also why this file skips itself against a deployed origin: there the
 * header is ignored, both contexts would be one real account, and every
 * "Bob cannot see it" below would fail for a reason that has nothing to do with
 * isolation.
 *
 * Alice authors a graph, stores a key and publishes - through the UI, because
 * the point is that the product does this, not that the API can. Bob then
 * meets each of her artefacts by the only routes a stranger has: the gallery,
 * the picker, a deep link, and the run console pointed at her workflow id. Each
 * UI assertion is corroborated by the same question asked of the API as that
 * person, and the launch has a CONTROL - Alice's own launch answers 202 - so a
 * 404 for Bob is proved to be ownership and not a publish that never worked.
 *
 * Serial by construction: later tests read ids the first one minted, and the
 * serial mode skips the rest when the first fails rather than reporting three
 * isolation failures for one authoring failure.
 *
 * ## Helpers restated rather than imported
 *
 * `builder.spec.ts` and `studio.spec.ts` own the selectors these helpers use
 * and the reasoning behind each one. They are spec files, not modules -
 * importing one registers its tests here a second time - so the handful this
 * file needs are restated with a pointer back, and every selector is one those
 * files already fix.
 */

const ALLOWED_CONSOLE_ERROR: RegExp | null = null

/** The server's own bound on the header, and the two ids this file is. */
const ALICE = 'alice'
const BOB = 'bob'

/**
 * The secret Alice types. It must leave the page ONCE, in the POST body, and
 * never come back: every response body from the credential routes is searched
 * for it, and so is Alice's own list afterwards.
 */
const ALICE_SECRET = 'sk-or-v1-alice-not-a-real-key-DO-NOT-RENDER'
/** Unique per run, because `(user_id, label)` is unique and a leftover row would 409 the next run. */
const ALICE_KEY_LABEL = `Alice's OpenRouter key ${Date.now().toString(36)}`
const ALICE_GRAPH_NAME = "Alice's graph"

interface Person {
  readonly id: string
  readonly context: BrowserContext
  readonly page: Page
  /** Shares the context's cookies, so the proxy forwards the same identity. */
  readonly api: APIRequestContext
}

interface ConsoleWatch {
  unexpected: string[]
  /** Forgive one pattern from here on - the 404s this file exists to provoke. */
  allow(pattern: RegExp): void
}

function watchConsole(page: Page): ConsoleWatch {
  const allowed: RegExp[] = []
  const watch: ConsoleWatch = {
    unexpected: [],
    allow: (pattern: RegExp) => {
      allowed.push(pattern)
    },
  }
  const record = (text: string) => {
    if (ALLOWED_CONSOLE_ERROR?.test(text)) return
    if (allowed.some((pattern) => pattern.test(text))) return
    watch.unexpected.push(text)
  }
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text())
  })
  page.on('pageerror', (error) => record(`uncaught: ${error.message}`))
  return watch
}

/**
 * Every response body the page receives from a path, collected for a search.
 *
 * `text()` is taken eagerly because a body can only be read while the response
 * is alive; a 204 has none and resolves to ''. The count is asserted alongside
 * the search so "no body contained the secret" can never be true of no bodies.
 */
function collectBodies(page: Page, pathPart: string): () => Promise<string[]> {
  const bodies: Promise<string>[] = []
  page.on('response', (response) => {
    if (response.url().includes(pathPart)) bodies.push(response.text().catch(() => ''))
  })
  return () => Promise.all(bodies)
}

/* --- selectors, from builder.spec.ts and studio.spec.ts ------------------- */

const canvas = (page: Page): Locator => page.locator('.builder-flow')
const nodes = (page: Page): Locator => page.locator('.vue-flow__node:has(.workflow-node)')
const inspector = (page: Page): Locator => page.locator('[data-testid="inspector-rail"]')
const headline = (page: Page): Locator => page.locator('[data-testid="problems-headline"]')
const saveChip = (page: Page): Locator => page.locator('[data-testid="save-chip"]')
const accountChip = (page: Page): Locator => page.locator('[data-testid="account-chip"]')
/**
 * The same chip on the RUN console, which renders its own markup rather than
 * mounting `AccountChip` - so it carries the class and not the test id. Both
 * render `user.name || user.email`, and the stub names a synthetic account by
 * its own id, which is what makes either one proof of who this context is.
 */
const consoleChip = (page: Page): Locator => page.locator('.studio-shell .account-chip, header .account-chip')
const templateCard = (page: Page): Locator =>
  page.locator('.template-card').filter({ hasText: 'Minimal gated agent' })
const credentialRow = (page: Page): Locator => inspector(page).locator('[data-field="credential_id"]')
const launchButton = (page: Page): Locator =>
  page.locator('.status-panel .control-actions button.button-primary')
const errorBanner = (page: Page): Locator => page.locator('.status-panel .error-banner')

async function firstOfKind(page: Page, kind: string): Promise<{ id: string; card: Locator }> {
  const wrapper = page.locator(`.vue-flow__node:has(.workflow-node.is-kind-${kind})`).first()
  await expect(wrapper, `no ${kind} node on the canvas`).toBeVisible()
  const id = await wrapper.getAttribute('data-id')
  return { id: id!, card: wrapper.locator('.workflow-node') }
}

async function validationSettles(page: Page): Promise<void> {
  await expect(page.locator('[data-testid="problems-checking"]')).toHaveCount(0, { timeout: 20_000 })
}

async function documentIdFromRoute(page: Page): Promise<string> {
  await expect
    .poll(() => new URL(page.url()).hash, { timeout: 20_000 })
    .toMatch(/#\/build\/ug_[0-9a-f]{8}$/)
  return /ug_[0-9a-f]{8}/.exec(new URL(page.url()).hash)![0]
}

/* --- being somebody ---------------------------------------------------------- */

async function become(browser: Browser, id: string): Promise<Person> {
  // Read off the project rather than the fixtures: this runs in `beforeAll`,
  // where only worker-scoped fixtures exist, and a context built by hand
  // inherits nothing from `use` unless it is told to.
  const { baseURL, viewport } = test.info().project.use
  if (!baseURL) throw new Error('playwright.config.ts declares no baseURL')
  const context = await browser.newContext({ baseURL, viewport: viewport ?? undefined })
  await context.addCookies([{ name: SYNTHETIC_USER_COOKIE, value: id, url: baseURL }])
  const page = await context.newPage()
  return { id, context, page, api: context.request }
}

/**
 * Delete everything this person owns, before and after, so the suite measures
 * this run and not the last one. Best-effort on purpose: a document that is
 * published and registered may refuse deletion with 409 (PLANS.md decision
 * 24), and a leftover row breaks nothing below - every assertion is by id.
 */
async function forgetEverything(person: Person): Promise<void> {
  for (const path of ['/api/builder/workflows', '/api/builder/credentials']) {
    const listed = await person.api.get(path)
    if (!listed.ok()) continue
    for (const entry of (await listed.json()) as { id: string }[]) {
      await person.api.delete(`${path}/${entry.id}`)
    }
  }
}

async function ids(api: APIRequestContext, path: string): Promise<string[]> {
  const listed = await api.get(path)
  expect(listed.ok(), `${path} answered ${listed.status()}`).toBe(true)
  return ((await listed.json()) as { id: string }[]).map((entry) => entry.id)
}

function launchBody(workflowId: string): Record<string, unknown> {
  return { workflow_id: workflowId, inputs: { idea: 'A scheduling assistant for clinics' }, gates: 'human' }
}

/**
 * Change WHO a context is without changing anything else about it - the
 * round-2 critic's probe for D-01-5. localStorage, sessionStorage and every
 * open tab stay exactly as the previous person left them; only the cookie the
 * stub auth origin and the proxies read moves. That is the shape of the next
 * person sitting down at a shared browser after the first one closed the tab
 * without signing out.
 */
async function becomeInPlace(person: Person, id: string): Promise<void> {
  const { baseURL } = test.info().project.use
  await person.context.clearCookies()
  await person.context.addCookies([{ name: SYNTHETIC_USER_COOKIE, value: id, url: baseURL! }])
}

interface StorageSnapshot {
  local: Record<string, string>
  session: Record<string, string>
}

/** Every key and value in both storages, as the page can read them. */
async function storageSnapshot(page: Page): Promise<StorageSnapshot> {
  return page.evaluate(() => {
    const dump = (storage: Storage): Record<string, string> => {
      const out: Record<string, string> = {}
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index)
        if (key !== null) out[key] = storage.getItem(key) ?? ''
      }
      return out
    }
    return { local: dump(window.localStorage), session: dump(window.sessionStorage) }
  })
}

/** The keys a build before 2026-09-03 wrote with no identity in them. */
function unscopedResidue(key: string): boolean {
  return (
    key.startsWith('builder-draft:')
    || key === 'validator-active-run'
    || key === 'validator-session-id'
    || key === 'builder-run-handoff'
  )
}

function keysOf(snapshot: StorageSnapshot): string[] {
  return [...Object.keys(snapshot.local), ...Object.keys(snapshot.session)]
}

test.describe('Per-user isolation', () => {
  test.skip(
    Boolean(process.env.E2E_BASE_URL),
    'the synthetic identity is honoured only by a SYNTHETIC=1 backend with no AUTH_BASE_URL; a deployed origin ignores the header and both contexts would be one real user',
  )
  test.describe.configure({ mode: 'serial' })

  let alice: Person
  let bob: Person
  let aliceDocumentId = ''
  let aliceCredentialId = ''

  test.beforeAll(async ({ browser }) => {
    alice = await become(browser, ALICE)
    bob = await become(browser, BOB)
    await forgetEverything(alice)
    await forgetEverything(bob)
  })

  test.afterAll(async () => {
    for (const person of [alice, bob].filter(Boolean)) {
      await forgetEverything(person)
      await person.context.close()
    }
  })

  test('Alice authors a graph, stores a key and publishes, and every row says it is hers', async () => {
    const { page, api } = alice
    const watch = watchConsole(page)
    const credentialBodies = collectBodies(page, '/api/builder/credentials')

    await page.goto('/#/build')
    // The chip is the proof this context is who it thinks it is, before a
    // single isolation claim is made. The stub names the account by its id.
    await expect(accountChip(page)).toContainText(ALICE)
    await expect(templateCard(page)).toBeVisible()
    await templateCard(page).click()
    await expect(canvas(page)).toBeVisible()
    await expect(nodes(page)).toHaveCount(4)

    // ---- a credential, from the agent's own inspector row -------------------
    const agent = await firstOfKind(page, 'agent')
    await agent.card.click()
    await expect(inspector(page)).toBeVisible()
    const row = credentialRow(page)
    await expect(row).toBeVisible()
    const select = row.locator('[data-testid="credential-select"]')
    await expect(select).toBeEnabled()
    await expect(select).toHaveValue('')

    await row.locator('[data-testid="credential-new"]').click()
    const form = row.locator('[data-testid="credential-form"]')
    await expect(form).toBeVisible()
    // Docked, never modal (R15): the graph stays on screen under the form.
    await expect(canvas(page)).toBeVisible()
    await expect(page.locator('[role="dialog"]')).toHaveCount(0)
    await form.locator('[data-testid="credential-label"]').fill(ALICE_KEY_LABEL)
    const secretInput = form.locator('[data-testid="credential-field-api_key"]')
    await expect(secretInput).toHaveAttribute('type', 'password')
    await secretInput.fill(ALICE_SECRET)
    await form.locator('[data-testid="credential-save"]').click()

    await expect(form).toBeHidden()
    await expect(select).toHaveValue(/^cr_[0-9a-f]{8}$/)
    aliceCredentialId = await select.inputValue()
    await expect(select.locator('option:checked')).toHaveText(ALICE_KEY_LABEL)
    await expect(row).toContainText('your key')
    // Choosing a key is an edit to the document, like any other inspector change.
    await expect(saveChip(page)).toContainText(/unsaved/i)

    // ---- save, then publish -------------------------------------------------
    await validationSettles(page)
    await expect(headline(page)).toContainText(/ready to publish/i)
    // Off the inspector's inputs before the chord, so it is the shell that
    // hears it and not a text field.
    await canvas(page).click({ position: { x: 40, y: 40 } })
    await page.keyboard.press('Control+s')
    await expect(saveChip(page)).toContainText(/saved/i)
    aliceDocumentId = await documentIdFromRoute(page)

    await page.keyboard.press('Control+Shift+P')
    const publish = page.locator('[aria-labelledby="publish-title"]')
    await expect(publish).toBeVisible()
    await publish.getByRole('button', { name: /^(Publish|Republish)$/ }).click()
    await expect(publish).toContainText(/this graph is live/i)
    await page.keyboard.press('Escape')

    // ---- the rows agree, and none of them carries the secret ----------------
    expect(await ids(api, '/api/builder/workflows')).toContain(aliceDocumentId)
    const credentials = await api.get('/api/builder/credentials')
    expect(credentials.ok()).toBe(true)
    const listed = (await credentials.json()) as Record<string, unknown>[]
    expect(listed.map((entry) => entry.id)).toEqual([aliceCredentialId])
    expect(listed[0]).toMatchObject({ kind: 'openrouter', label: ALICE_KEY_LABEL })
    // C4: `{id, kind, label, created_at, updated_at, last_used_at}` and never a field.
    expect(Object.keys(listed[0]).sort()).toEqual(
      ['created_at', 'id', 'kind', 'label', 'last_used_at', 'updated_at'],
    )
    expect(await credentials.text()).not.toContain(ALICE_SECRET)

    const bodies = await credentialBodies()
    expect(bodies.length, 'no credential response reached the page').toBeGreaterThan(0)
    expect(bodies.filter((body) => body.includes(ALICE_SECRET))).toEqual([])
    // The published workflow is really hers: the console can launch it.
    expect(watch.unexpected).toEqual([])
  })

  test("Bob's gallery lists no graph of Alice's, and his picker no key of hers", async () => {
    const { page, api } = bob
    const watch = watchConsole(page)

    await page.goto('/#/build')
    await expect(accountChip(page)).toContainText(BOB)

    // "Saved here" has finished reading AND was not refused: a 401 would
    // render as an alert and count as an empty list otherwise.
    const library = page.locator('.gallery-library')
    await expect(library.locator('[role="status"]')).toHaveCount(0)
    await expect(library.locator('[role="alert"]')).toHaveCount(0)
    await expect(library.locator('.library-row')).toHaveCount(0)
    await expect(library).toContainText(/no saved graphs yet/i)
    await expect(page.locator('.library-name', { hasText: ALICE_GRAPH_NAME })).toHaveCount(0)

    // The picker on Bob's own agent node lists only the platform key.
    await templateCard(page).click()
    await expect(canvas(page)).toBeVisible()
    const agent = await firstOfKind(page, 'agent')
    await agent.card.click()
    await expect(inspector(page)).toBeVisible()
    const row = credentialRow(page)
    const select = row.locator('[data-testid="credential-select"]')
    await expect(select).toBeEnabled()
    await expect(row.locator('[role="alert"]')).toHaveCount(0)
    await expect(select.locator('option')).toHaveText(['Platform key'])
    await expect(inspector(page)).not.toContainText(ALICE_KEY_LABEL)
    await expect(inspector(page)).not.toContainText(aliceCredentialId)

    // The same two questions, asked of the API as Bob.
    expect(await ids(api, '/api/builder/workflows')).not.toContain(aliceDocumentId)
    expect(await ids(api, '/api/builder/credentials')).toEqual([])

    expect(watch.unexpected).toEqual([])
  })

  test("a deep link to Alice's document lands Bob on the empty builder", async () => {
    const { page } = bob
    const watch = watchConsole(page)
    // Chromium logs every non-2xx response; the 404 is the subject here.
    watch.allow(/Failed to load resource.*404/)

    // A fresh load, not a hash change under the canvas the previous test
    // started - `#/build/<id>` is the URL a colleague pastes into a new tab.
    await page.goto('about:blank')
    const refused = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/builder/workflows/${aliceDocumentId}`) &&
        response.request().method() === 'GET',
    )
    await page.goto(`/#/build/${aliceDocumentId}`)
    // 404, not 403: a 403 would confirm the document exists.
    expect((await refused).status()).toBe(404)

    await expect(templateCard(page)).toBeVisible()
    await expect(canvas(page)).toHaveCount(0)
    await expect(inspector(page)).toHaveCount(0)
    await expect(page.locator('.library-name', { hasText: ALICE_GRAPH_NAME })).toHaveCount(0)
    // The server's sentence, verbatim, where the shell reports a graph it could
    // not open. Asserted right after the refusal because the notice retires
    // itself after four seconds.
    await expect(page.locator('.builder-notice')).toContainText(/not found/i)
    expect(new URL(page.url()).hash).toBe(`#/build/${aliceDocumentId}`)

    expect(watch.unexpected).toEqual([])
  })

  test(
    "Bob's console pointed at Alice's workflow stays live, shows the server's sentence, and cannot launch",
    { tag: '@launch' },
    async () => {
      const { page, api } = bob
      const watch = watchConsole(page)
      watch.allow(/Failed to load resource.*404/)

      /*
       * The console is pointed at a workflow by the builder's handoff record,
       * and the only UI that writes it is the owner's own publish dialog - which
       * Bob cannot reach. So the record is written by hand: it is the shape of
       * "Alice sent Bob her workflow id", and `StudioView` reads it at setup.
       */
      await page.goto('/#/build')
      // Under Bob's own key: the record is keyed to whoever is signed in
      // (D-01-5), and this is the shape of Bob having been handed her id.
      await page.evaluate(
        ({ key, workflowId, name }) => {
          window.sessionStorage.setItem(key, JSON.stringify({ workflowId, inputField: 'idea', name }))
        },
        { key: storageKeyFor(BOB, 'builder-run-handoff'), workflowId: aliceDocumentId, name: ALICE_GRAPH_NAME },
      )
      await page.goto('/#/')
      await page.reload()

      await expect(page.locator('.handoff-banner')).toContainText(ALICE_GRAPH_NAME)
      await expect(page.locator('.live-status')).not.toHaveText(/connecting/i)

      /*
       * D-01-2. The graph read on load is refused - D1 collapses the graph
       * route to the same 404 as the launch - and a 404 can only come from a
       * real server. Round 1 found the console answering it by dropping into
       * MOCK mode: a 14-node fabricated topology drawn under Alice's graph
       * name, a 12px "Mock Mode" chip, and an enabled green Launch. The first
       * version of this test asserted only the launch's 404 sentence and never
       * what the canvas showed before it. Now: live, empty, the server's own
       * words in a banner that cannot be dismissed, and no Launch.
       */
      await expect(page.locator('.live-status')).not.toHaveText(/mock/i)
      await expect(page.locator('.canvas-meta code')).not.toHaveText(/^mock-/)
      await expect(page.locator('.vue-flow__node')).toHaveCount(0)
      await expect(page.locator('.status-panel .transport-banner')).toHaveCount(0)
      const refusal = page.locator('.status-panel .graph-banner')
      await expect(refusal).toContainText('workflow not found')

      // Human gates and a valid idea are the only other things Launch waits
      // for. It stays disabled because the graph was refused, not because the
      // form is incomplete - and it stays disabled after the dismissible
      // error banner, if any, is gone.
      const review = page.getByRole('button', { name: 'Review', exact: true })
      if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
      await expect(review).toHaveAttribute('aria-pressed', 'true')
      await page.locator('textarea#idea').fill('A scheduling assistant for small veterinary clinics')
      if ((await errorBanner(page).count()) > 0) {
        await errorBanner(page).getByRole('button', { name: 'Dismiss error' }).click()
      }
      await expect(launchButton(page)).toBeDisabled()
      await expect(refusal).toContainText('workflow not found')
      await expect(page.locator('.status-panel .run-id')).toHaveCount(0)
      await expect(page.locator('.gate-card')).toHaveCount(0)
      expect(
        await page.evaluate((key) => window.localStorage.getItem(key), storageKeyFor(BOB, 'validator-active-run')),
      ).toBeNull()

      // As Bob, the API refuses the launch itself with the same sentence, and
      // his history stays empty.
      const bobLaunch = await api.post('/api/sessions/e2e-isolation-bob/runs', {
        data: launchBody(aliceDocumentId),
      })
      expect(bobLaunch.status()).toBe(404)
      expect(((await bobLaunch.json()) as { detail: string }).detail).toBe('workflow not found')
      const history = await api.get('/api/runs?limit=25')
      expect(history.ok()).toBe(true)
      expect(((await history.json()) as { runs: unknown[] }).runs).toEqual([])

      // THE CONTROL. Alice's own launch of the same id is accepted, which is
      // what makes Bob's 404 a statement about ownership rather than about a
      // publish that never produced a runnable workflow. Cancelled at once:
      // the gate would otherwise hold a durable row open for the next test.
      const aliceLaunch = await alice.api.post('/api/sessions/e2e-isolation-alice/runs', {
        data: launchBody(aliceDocumentId),
      })
      expect(aliceLaunch.status(), 'the owner could not launch her own published graph').toBe(202)
      const run = (await aliceLaunch.json()) as { run_id: string }
      expect(run.run_id).toBeTruthy()
      await alice.api.post(`/api/runs/${run.run_id}/cancel`)

      expect(watch.unexpected).toEqual([])
    },
  )

  test(
    "the next person on the same browser inherits nothing of Alice's, and her sign-out clears what she wrote",
    { tag: '@launch' },
    async () => {
      const { page, api } = alice
      const watch = watchConsole(page)

      /*
       * D-01-5. The round-2 critic swapped the harness's synthetic-user cookie
       * under a live page - a real Google sign-out cannot run here - and the
       * console then printed Alice's run id, "Running your published graph",
       * "run not found", and a draft holding her credential id, all read back
       * from browser storage under keys with no identity in them. The same
       * probe, repeated: Alice leaves a draft, a handoff and a run at a gate
       * behind WITHOUT signing out, which is the common case; the cookie
       * becomes Bob's; the page is reloaded. Then Alice comes back and signs
       * out, and everything she wrote goes with her.
       */

      // ---- Alice leaves residue: a draft, a handoff, and a run at a gate ----
      await page.goto('/#/')
      await expect(consoleChip(page)).toContainText(ALICE)
      await expect(page.locator('.live-status')).not.toHaveText(/connecting/i)
      const review = page.getByRole('button', { name: 'Review', exact: true })
      if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
      await expect(review).toHaveAttribute('aria-pressed', 'true')
      await page.locator('textarea#idea').fill('A rota planner for community pharmacy locums')
      await expect(launchButton(page)).toBeEnabled()
      await launchButton(page).click()
      await expect(page.locator('.gate-card h2')).toHaveText('Confirm scope', { timeout: 60_000 })
      const aliceRunOnScreen = (await page.locator('.status-panel .run-id').textContent())?.trim()
      expect(aliceRunOnScreen).toBeTruthy()
      // The handoff, under her own key, the way her publish dialog writes it.
      await page.evaluate(
        ({ key, workflowId, name }) => {
          window.sessionStorage.setItem(key, JSON.stringify({ workflowId, inputField: 'idea', name }))
        },
        { key: storageKeyFor(ALICE, 'builder-run-handoff'), workflowId: aliceDocumentId, name: ALICE_GRAPH_NAME },
      )

      const alicePointerKey = storageKeyFor(ALICE, 'validator-active-run')
      const aliceDraftKey = storageKeyFor(ALICE, `builder-draft:${aliceDocumentId}`)
      const aliceHandoffKey = storageKeyFor(ALICE, 'builder-run-handoff')
      const before = await storageSnapshot(page)
      expect(before.local[alicePointerKey]).toContain(aliceRunOnScreen as string)
      const aliceRunId = (JSON.parse(before.local[alicePointerKey]) as { runId: string }).runId
      // The draft is what the critic found: the whole document, credential id
      // included. It has to exist, under her key, for this test to test anything.
      expect(before.local[aliceDraftKey]).toContain(aliceCredentialId)
      // And nothing was written under a key with no identity in it.
      expect(keysOf(before).filter(unscopedResidue)).toEqual([])

      // ---- the cookie becomes Bob's; nothing else about the browser changes --
      await becomeInPlace(alice, BOB)
      try {
        await page.reload()
        await expect(consoleChip(page)).toContainText(BOB)
        await expect(page.locator('.live-status')).not.toHaveText(/connecting/i)

        // An empty console: no run id, no "Running your published graph", no
        // "run not found", no gate, and Launch rather than Relaunch.
        await expect(page.locator('.status-panel .run-id')).toHaveCount(0)
        await expect(page.locator('.handoff-banner')).toHaveCount(0)
        await expect(errorBanner(page)).toHaveCount(0)
        await expect(page.locator('.gate-card')).toHaveCount(0)
        await expect(page.locator('.status-panel .status-badge')).not.toHaveText(/waiting|running|error/i)
        await expect(launchButton(page)).toHaveText('Launch')

        const asBob = await storageSnapshot(page)
        // Bob's console minted its own session id and nothing else is his.
        expect(keysOf(asBob).filter((key) => key.startsWith('u:bob:'))).toEqual([
          storageKeyFor(BOB, 'validator-session-id'),
        ])
        expect(keysOf(asBob).filter(unscopedResidue)).toEqual([])
        // What Bob's page can read names neither her run nor her credential.
        const readableByBob = keysOf(asBob)
          .filter((key) => !key.startsWith('u:alice:'))
          .map((key) => asBob.local[key] ?? asBob.session[key] ?? '')
          .join('\n')
        expect(readableByBob).not.toContain(aliceRunId)
        expect(readableByBob).not.toContain(aliceCredentialId)
        // THE CONTROL: Alice's residue is all still there, under her prefix,
        // which is what proves the swap happened on one browser profile.
        expect(asBob.local[alicePointerKey]).toBe(before.local[alicePointerKey])
        expect(asBob.local[aliceDraftKey]).toBe(before.local[aliceDraftKey])
        expect(asBob.session[aliceHandoffKey]).toBe(before.session[aliceHandoffKey])

        // And an empty builder: no draft of hers offered, none readable as him.
        await page.goto('/#/build')
        await expect(accountChip(page)).toContainText(BOB)
        await expect(templateCard(page)).toBeVisible()
        await expect(page.locator('[data-testid="restore-bar"]')).toHaveCount(0)
        expect(
          await page.evaluate((key) => window.localStorage.getItem(key), storageKeyFor(BOB, `builder-draft:${aliceDocumentId}`)),
        ).toBeNull()
      } finally {
        await becomeInPlace(alice, ALICE)
      }

      // ---- Alice returns and signs out; her sign-out takes her things with it --
      // The run first, so nothing durable stays open behind this test.
      await api.post(`/api/runs/${aliceRunId}/cancel`)
      // Through `about:blank`, because a `goto` to the hash already in the
      // address bar is a same-document navigation: the session would not be
      // re-read and the chip would still say Bob.
      await page.goto('about:blank')
      await page.goto('/#/build')
      await expect(accountChip(page)).toContainText(ALICE)
      expect(keysOf(await storageSnapshot(page)).filter((key) => key.startsWith('u:alice:'))).not.toEqual([])

      await accountChip(page).locator('button.account-signout').click()
      await expect
        .poll(async () => keysOf(await storageSnapshot(page)).filter((key) => key.startsWith('u:alice:')))
        .toEqual([])
      expect(keysOf(await storageSnapshot(page)).filter(unscopedResidue)).toEqual([])

      expect(watch.unexpected).toEqual([])
    },
  )
})
