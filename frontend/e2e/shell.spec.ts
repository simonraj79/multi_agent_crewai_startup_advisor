import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { DEFAULT_SYNTHETIC_USER, storageKeyFor } from './syntheticUser'

/**
 * One home, one breadcrumb, one vocabulary - in a real browser.
 *
 * `docs/ux-shell/DEFINITION-OF-DONE.md` rows U1, U2 and U4. What only a browser
 * can answer here is not layout: it is that the ROUTES resolve, that the
 * breadcrumb link actually reaches the home from both canvases, and that
 * `document.title` follows the route - three things a jsdom mount can assert
 * about a component and never about the address bar.
 *
 * NO `@launch` TAG ANYWHERE IN THIS FILE, and that is deliberate rather than
 * incidental: nothing here presses Launch, so the whole file is free against a
 * deployed origin as well as against `SYNTHETIC=1`.
 *
 * ## Helpers restated rather than imported
 *
 * `builder.spec.ts` owns `clearLibrary` and the console-error watch and the
 * reasoning behind each; they are spec files rather than modules, so importing
 * one would register its tests here a second time. The two this file needs are
 * restated with a pointer back, exactly as `isolation.spec.ts` does.
 */

/** Every template `data/builderTemplates.ts` exports, both gallery rows. */
const TEMPLATE_TITLES = [
  'Blank canvas',
  'Sequential pipeline',
  'News to social post',
  'Conditional router',
  'Reflection loop',
  'Hierarchical delegation',
  'Idea validator',
  'Minimal gated agent',
  'Fan out and join',
] as const

const SAVED_GRAPH_NAME = 'A graph the home should list'

/**
 * `builder.spec.ts`'s watch, restated: this suite tolerates zero console
 * errors, with one forgiveness list and one caller that uses it.
 *
 * `isolation.spec.ts` carries the same escape hatch for the same reason - a
 * test that PROVOKES a refusal on purpose must be able to say so, and the
 * alternative is either a suite that tolerates every 404 or one that cannot
 * test a refusal at all.
 */
function watchConsole(page: Page, ...allowed: RegExp[]): { unexpected: string[] } {
  const watch = { unexpected: [] as string[] }
  const record = (text: string) => {
    if (!allowed.some((pattern) => pattern.test(text))) watch.unexpected.push(text)
  }
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text())
  })
  page.on('pageerror', (error) => record(String(error)))
  return watch
}

/** `builder.spec.ts`'s cleaner, restated. The synthetic store is shared. */
async function clearLibrary(request: APIRequestContext): Promise<void> {
  const listed = await request.get('/api/builder/workflows')
  if (!listed.ok()) return
  const documents = (await listed.json()) as { id: string }[]
  for (const entry of documents) await request.delete(`/api/builder/workflows/${entry.id}`)
}

/**
 * A saved document, through the API rather than through the canvas.
 *
 * The authoring journey is `builder.spec.ts`'s subject and takes a minute; this
 * file's subject is whether the home LISTS what the account has, and the
 * cheapest honest way to give the account something is the same POST the
 * builder makes on its first save.
 */
async function createDocument(request: APIRequestContext, name: string): Promise<string> {
  const created = await request.post('/api/builder/workflows', {
    data: {
      document: {
        schema: 'builder.flow/v1',
        name,
        version: 1,
        input_field: 'idea',
        nodes: [
          {
            id: 'idea',
            kind: 'input',
            label: 'Idea',
            position: { x: 0, y: 0 },
            config: { field: 'idea', label: null, max_chars: 2000, required: true },
          },
        ],
        edges: [],
        joins: {},
      },
      expected_version: null,
    },
  })
  expect(created.status(), await created.text()).toBe(201)
  return (await created.json()).id as string
}

/** Home, with nothing left over from a previous test to redirect it away. */
async function openHome(page: Page): Promise<void> {
  await page.goto('/#/run')
  await page.evaluate(() => {
    window.localStorage.clear()
    window.sessionStorage.clear()
  })
  await page.goto('/#/')
  await expect(page.locator('.home-page')).toBeVisible()
}

test.describe('the unified shell', () => {
  test.beforeEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test.afterEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test('lists the built-in workflow, a saved document and all nine templates', async ({
    page,
    request,
  }) => {
    const watch = watchConsole(page)
    await createDocument(request, SAVED_GRAPH_NAME)
    await openHome(page)

    // The built-in one, named by the graph the API serves rather than by a
    // string this file invented.
    const validator = page.locator('[data-testid="home-validator"]')
    await expect(validator).toBeVisible()
    await expect(validator).toContainText('Idea Validator')
    await expect(validator).toContainText(/run only/i)

    /*
     * The saved one, with its status and a picture derived from the document -
     * asserted about THIS ROW rather than about the whole library, and that is
     * a measurement rather than caution. `clearLibrary` cannot delete a
     * PUBLISHED document (409 by design, decision 24), so a full-suite run
     * arrives here with whatever `builder.spec.ts` published still in the
     * store: this file passed alone and failed in the suite on
     * `toHaveCount(1)` reading 3 (CLAUDE.md item 44's leak, from the other
     * side). What the row count would prove is the store's tidiness; what this
     * page has to get right is that a saved workflow appears, named, with its
     * status and a picture.
     */
    const row = page.locator('[data-testid="home-library"] > li', {
      hasText: SAVED_GRAPH_NAME,
    })
    await expect(row).toHaveCount(1)
    await expect(row).toContainText('draft')
    await expect(row.locator('svg.graph-thumbnail')).toHaveCount(1)

    // All nine, both of the gallery's rows flattened into one list - the
    // gallery collapses two of them, and a list that hides two of nine is not
    // a list.
    await expect(page.locator('[data-testid="home-templates"] > li')).toHaveCount(9)
    for (const title of TEMPLATE_TITLES) {
      await expect(page.locator('[data-testid="home-templates"]'), title).toContainText(title)
    }

    expect(watch.unexpected).toEqual([])
  })

  test('opens the built-in workflow on the console, and a saved one on the builder', async ({
    page,
    request,
  }) => {
    const watch = watchConsole(page)
    const id = await createDocument(request, SAVED_GRAPH_NAME)
    await openHome(page)

    await page.locator('[data-testid="home-validator"]').click()
    await expect.poll(() => new URL(page.url()).hash).toBe('#/run')
    await expect(page.locator('.vue-flow__node').first()).toBeVisible()

    await page.goto('/#/')
    await page.locator(`[data-testid="home-document-${id}"]`).click()
    await expect.poll(() => new URL(page.url()).hash).toBe(`#/build/${id}`)
    await expect(page.locator('.builder-flow')).toBeVisible()

    expect(watch.unexpected).toEqual([])
  })

  test('opens a template on the builder canvas as an unsaved draft', async ({ page }) => {
    const watch = watchConsole(page)
    await openHome(page)

    await page.locator('[data-testid="home-template-news-to-social"]').click()
    // `#/build`, with no id: a template is a draft until it is saved, which is
    // exactly what the gallery's own cards do. The id in the address would be a
    // promise the server has not made yet.
    await expect.poll(() => new URL(page.url()).hash).toBe('#/build')
    await expect(page.locator('.builder-flow')).toBeVisible()
    await expect(page.locator('.document-name')).toContainText(/news to social/i)

    // And a reload of that address is the gallery again, which is what makes
    // the prop the right carrier rather than a query parameter.
    await page.reload()
    await expect(page.locator('.template-card').first()).toBeVisible()

    expect(watch.unexpected).toEqual([])
  })

  test('a builder run handoff at #/ lands on the console', async ({ page, request }) => {
    /*
     * ONE FORGIVEN 404, and it is the proof rather than a nuisance: the handoff
     * names a document this test created and never PUBLISHED, so the console
     * asks `GET /api/workflows/{id}/graph` for a workflow no registry holds and
     * is answered 404 - which is the console reporting an unpublished graph
     * correctly, and is also end-to-end evidence that the handoff really
     * reached it. Publishing one here would need a graph that validates, which
     * is `builder.spec.ts`'s subject and a minute of authoring; the subject
     * here is the route.
     */
    const watch = watchConsole(page, /status of 404/)
    const id = await createDocument(request, SAVED_GRAPH_NAME)

    await page.goto('/#/run')
    await page.evaluate(
      ({ key, workflowId, name }) => {
        window.localStorage.clear()
        window.sessionStorage.setItem(
          key,
          JSON.stringify({ workflowId, inputField: 'idea', name }),
        )
      },
      {
        // The record is keyed to whoever is signed in (D-01-5), and the
        // cookieless context is the E2E Operator at the API and on the page.
        key: storageKeyFor(DEFAULT_SYNTHETIC_USER, 'builder-run-handoff'),
        workflowId: id,
        name: SAVED_GRAPH_NAME,
      },
    )

    /*
     * A RELOAD at `#/`, which is the shape of the thing being tested. A
     * `goto` between two hashes of one URL is a same-document navigation - the
     * app instance never restarts - so it exercises the in-session case, which
     * is the one the hand-over deliberately does NOT fire for: pressing
     * `Workflows` from a live console is leaving, not recovering. The reload is
     * what a person does when a page has gone wrong, and it is the case the
     * home must not make one click worse than `#/` was when it WAS the console.
     * `isolation.spec.ts` reaches the same state the same way.
     */
    await page.goto('/#/')
    await page.reload()
    await expect.poll(() => new URL(page.url()).hash, { timeout: 15_000 }).toBe('#/run')
    await expect(page.locator('.handoff-banner')).toContainText(SAVED_GRAPH_NAME)

    expect(watch.unexpected).toEqual([])
  })

  test('the breadcrumb reads Workflows / <name> on the console and reaches the home', async ({
    page,
  }) => {
    const watch = watchConsole(page)
    await openHome(page)
    await page.locator('[data-testid="home-validator"]').click()

    const crumbs = page.locator('.app-header .breadcrumb')
    await expect(crumbs).toContainText('Workflows')
    await expect(crumbs).toContainText('Idea Validator')

    await crumbs.getByRole('link', { name: 'Workflows' }).click()
    await expect.poll(() => new URL(page.url()).hash).toBe('#/')
    await expect(page.locator('.home-page')).toBeVisible()

    // And it does NOT bounce back. The run pointer is not the question - a
    // reader who pressed `Workflows` is leaving, not recovering - and a
    // predicate asked on every mount would make this link read as broken.
    await page.waitForTimeout(1500)
    expect(new URL(page.url()).hash).toBe('#/')

    expect(watch.unexpected).toEqual([])
  })

  test('the breadcrumb reads Workflows / <name> on a builder document and reaches the home', async ({
    page,
    request,
  }) => {
    const watch = watchConsole(page)
    const id = await createDocument(request, SAVED_GRAPH_NAME)
    await page.goto(`/#/build/${id}`)
    await expect(page.locator('.builder-flow')).toBeVisible()

    const crumbs = page.locator('.app-header .breadcrumb')
    await expect(crumbs).toContainText('Workflows')
    await expect(crumbs).toContainText(SAVED_GRAPH_NAME)

    await crumbs.getByTestId('breadcrumb-home').click()
    await expect.poll(() => new URL(page.url()).hash).toBe('#/')
    await expect(page.locator('.home-page')).toBeVisible()

    expect(watch.unexpected).toEqual([])
  })

  test('the tab is named after the workflow on a canvas and after the product on the home', async ({
    page,
    request,
  }) => {
    const watch = watchConsole(page)
    const id = await createDocument(request, SAVED_GRAPH_NAME)

    await openHome(page)
    expect(await page.title()).toBe('Crew Studio')

    await page.goto('/#/run')
    await expect(page.locator('.vue-flow__node').first()).toBeVisible()
    await expect.poll(() => page.title()).toBe('Idea Validator · Crew Studio')

    await page.goto(`/#/build/${id}`)
    await expect(page.locator('.builder-flow')).toBeVisible()
    await expect.poll(() => page.title()).toBe(`${SAVED_GRAPH_NAME} · Crew Studio`)

    expect(watch.unexpected).toEqual([])
  })

  test('the vocabulary on the console is Run, and no graph is called fixed or published', async ({
    page,
  }) => {
    const watch = watchConsole(page)
    await page.goto('/#/run')
    await expect(page.locator('.vue-flow__node').first()).toBeVisible()

    const kicker = page.locator('.canvas-kicker')
    await expect(kicker).toHaveText(/^RUN/)
    await expect(kicker).not.toHaveText(/FIXED|PUBLISHED GRAPH/)

    // Build and Run are the modes of the workflow the breadcrumb names, and
    // they are the same pair in the same place on both canvases.
    const modes = page.locator('.app-header .workspace-switch')
    await expect(modes.getByRole('button', { name: 'Build' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    await expect(modes.getByRole('button', { name: 'Run' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )

    expect(watch.unexpected).toEqual([])
  })
})
