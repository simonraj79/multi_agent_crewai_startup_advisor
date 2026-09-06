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
 * ONE `@launch` TEST, AND EXACTLY ONE. Everything else here is free against a
 * deployed origin as well as against `SYNTHETIC=1`, and that was the whole file
 * until RV4 follow-up 1: the defect is that the home hands back to the console
 * after a run REACHED FROM BUILD AND FINISHED, and there is no way to reach that
 * state without finishing a run. It carries the tag, so
 * `--grep-invert @launch` against a paid origin still presses nothing.
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
  for (const entry of documents) {
    // UNPUBLISH FIRST, which `builder.spec.ts`'s original could not do and
    // CLAUDE.md item 44 is the record of: `DELETE` answers 409 while any
    // version is registered, so a file that publishes anything leaves one
    // behind on every run and a long-lived backend accumulates them. This file
    // publishes one workflow now (the Build-launched arm), so it cleans one up.
    await request.post(`/api/builder/workflows/${entry.id}/unpublish`).catch(() => undefined)
    await request.delete(`/api/builder/workflows/${entry.id}`)
  }
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

/**
 * A gateless `idea -> agent -> report` workflow, saved AND published, through
 * the API.
 *
 * `createDocument` above is deliberately one input node, because the tests it
 * serves only need the home to LIST something. The Build-launched arm needs a
 * workflow that really runs, and a run resolves a REGISTERED version - so this
 * is the smallest document that both validates and publishes. The shape is
 * `failure-modes.spec.ts`'s, restated for the same reason every other helper in
 * this file is: a spec file cannot be imported without registering its tests
 * here a second time.
 */
async function publishRunnable(request: APIRequestContext, name: string): Promise<string> {
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
          {
            id: 'writer',
            kind: 'agent',
            label: 'Writer',
            position: { x: 260, y: 0 },
            config: {
              role: 'note taker',
              goal: 'write the note',
              backstory: 'years of it',
              task: {
                description: 'work from ${state.out__idea}',
                expected_output: 'a paragraph',
              },
              // The same constant `failure-modes.spec.ts` and `cast.spec.ts`
              // author with, and it is never called: `SYNTHETIC=1` replaces the
              // crew factories, so this names a model rather than spending one.
              llm: { model: 'google/gemini-3.8-flash' },
              tier: 'cheap',
              on_error: 'fail',
            },
          },
          {
            id: 'report',
            kind: 'output',
            label: 'Report',
            position: { x: 520, y: 0 },
            config: { body_key: 'markdown_body', source: '${state.out__writer}' },
          },
        ],
        edges: [
          { id: 'e1', source: 'idea', source_port: 'out', target: 'writer', target_port: 'in' },
          { id: 'e2', source: 'writer', source_port: 'out', target: 'report', target_port: 'in' },
        ],
        joins: {},
      },
      expected_version: null,
    },
  })
  expect(created.status(), await created.text()).toBe(201)
  const id = (await created.json()).id as string
  const published = await request.post(`/api/builder/workflows/${id}/publish`)
  expect(published.status(), await published.text()).toBe(200)
  return id
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

    // The home's own lockup is STATIC: there is nowhere to go back to from
    // here, so an anchor to `#/` would point at the page it is on.
    await expect(page.locator('a.brand-lockup')).toHaveCount(0)
    await expect(page.locator('.brand-lockup h1')).toHaveText('Crew Studio')

    // All nine, both of the gallery's rows flattened into one list - the
    // gallery collapses two of them, and a list that hides two of nine is not
    // a list.
    await expect(page.locator('[data-testid="home-templates"] > li')).toHaveCount(9)
    for (const title of TEMPLATE_TITLES) {
      await expect(page.locator('[data-testid="home-templates"]'), title).toContainText(title)
    }

    expect(watch.unexpected).toEqual([])
  })


  /*
   * EVERY CARD NAMES ITS ACTION, AND THERE IS A WAY BACK TO A RUN - item 3,
   * ROUND-2 X2, AUDIT-R2 H2. Presses nothing, so no `@launch` and no money.
   */
  test('names the action on every card, and offers Run on a published one', async ({
    page,
    request,
  }) => {
    const watch = watchConsole(page)
    const draft = await createDocument(request, SAVED_GRAPH_NAME)
    const live = await createDocument(request, `${SAVED_GRAPH_NAME} (live)`)
    const published = await request.post(`/api/builder/workflows/${live}/publish`)
    expect(published.status(), await published.text()).toBe(200)
    await openHome(page)

    // Built in: one action, and it is the mode's word.
    await expect(
      page.locator('[data-testid="home-validator"] .home-card-action'),
    ).toHaveText(/Run/)

    // Saved: the card's own action, plus Run only where a version is
    // registered. A run resolves a REGISTERED version, so a Run on the draft
    // would answer 404 for a graph the author can do nothing about from there.
    await expect(
      page.locator(`[data-testid="home-document-${draft}"] .home-card-action`),
    ).toHaveText(/Open in Build/)
    await expect(page.locator(`[data-testid="home-run-${draft}"]`)).toHaveCount(0)
    await expect(page.locator(`[data-testid="home-run-${live}"]`)).toBeVisible()

    // Templates: WC1's row, asserted here because this is the page that has to
    // agree with the builder gallery word for word.
    await expect(
      page.locator('[data-testid="home-template-news-to-social"] .home-card-action'),
    ).toHaveText(/Use this template/)

    expect(watch.unexpected).toEqual([])
  })

  test('the home Run history link opens the console with the list in view', async ({ page }) => {
    const watch = watchConsole(page)
    await openHome(page)

    await page.locator('[data-testid="home-run-history"]').click()
    await expect.poll(() => new URL(page.url()).hash).toBe('#/run')

    /*
     * IN VIEW, which is the whole of the ask and the one thing jsdom cannot
     * answer. The list has always been rendered - it is the last block of the
     * control rail - so what the home lacked was a route to it and what the
     * console lacked was any reason to show it. Measured against the rail's own
     * scroller rather than the window: the rail scrolls, the page does not.
     */
    const history = page.locator('#run-history')
    await expect(history).toBeVisible({ timeout: 20_000 })
    const inView = await page.evaluate(() => {
      const el = document.querySelector('#run-history')
      const scroller = document.querySelector('.control-scroll')
      if (!el || !scroller) return null
      const a = el.getBoundingClientRect()
      const b = scroller.getBoundingClientRect()
      return a.top < b.bottom && a.bottom > b.top
    })
    expect(inView, 'the console rendered no history section inside its rail').not.toBeNull()
    expect(inView, 'Run history landed on a console that was not showing the list').toBe(true)

    // ONE SHOT: a reload must not scroll a reader away from a run they are
    // watching, so the note is removed as it is read.
    expect(
      await page.evaluate(() => window.sessionStorage.getItem('console-reveal-history')),
    ).toBeNull()

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

  /**
   * THE ARM THE SUITE WAS BLIND TO (RV4 follow-up 1).
   *
   * The test above proves an UN-launched handoff still hands over, which is
   * D2's rule and is right. What nothing covered is the state a real author is
   * in one minute later: they pressed Run, the run finished, and they went back
   * to `#/` looking for it. The handoff was still in `sessionStorage`, so the
   * home read it as "resume" and bounced them into a finished console with R4's
   * Last-run card unreachable - the card that whole row exists to provide.
   *
   * `console-identity.spec.ts`'s home arm cannot see this because it launches
   * from `#/run`, so it never has a handoff at all; R1's arm clears
   * `sessionStorage` outright. The blindness was structural, which is why this
   * arm sets the handoff the way the builder does and then really launches.
   *
   * `@launch` and free: `SYNTHETIC=1` replaces the crew factories and nothing
   * else, so the publish, the compile, the engine and the frames are the
   * production ones and no model is called.
   */
  test(
    'a Build-launched run that has finished leaves the home on the home',
    { tag: '@launch' },
    async ({ page, request }) => {
      const watch = watchConsole(page)
      const id = await publishRunnable(request, 'A workflow the home should remember')

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
          key: storageKeyFor(DEFAULT_SYNTHETIC_USER, 'builder-run-handoff'),
          workflowId: id,
          name: 'A workflow the home should remember',
        },
      )
      await page.reload()
      await expect(page.locator('.handoff-banner')).toBeVisible()

      // Review, not unattended: this graph declares no gate, and `create_run`
      // answers 422 for `gates=auto` on a gateless workflow.
      const review = page.getByRole('button', { name: 'Review', exact: true })
      if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
      await page.locator('textarea#idea').fill('Everything the home has to remember about this')
      await page.locator('.status-panel .control-actions button.button-primary').click()
      await expect
        .poll(async () => page.locator('.canvas-meta span').first().textContent(), {
          timeout: 120_000,
        })
        .toMatch(/Finished|Failed|Cancelled/i)

      // The record went with the launch; the run pointer did not.
      expect(
        await page.evaluate(
          (key) => window.sessionStorage.getItem(key),
          storageKeyFor(DEFAULT_SYNTHETIC_USER, 'builder-run-handoff'),
        ),
      ).toBeNull()

      await page.goto('/#/')
      await page.reload()
      await expect(page.locator('.home-page')).toBeVisible()
      expect(new URL(page.url()).hash).toBe('#/')
      const card = page.locator('.home-last-run')
      await expect(card).toBeVisible()
      await expect(card).toContainText('A workflow the home should remember')

      expect(watch.unexpected).toEqual([])
    },
  )

  test('the breadcrumb reads Workflows / <name> on the console and reaches the home', async ({
    page,
  }) => {
    const watch = watchConsole(page)
    await openHome(page)
    await page.locator('[data-testid="home-validator"]').click()

    const crumbs = page.locator('.app-header .breadcrumb')
    await expect(crumbs).toContainText('Workflows')
    await expect(crumbs).toContainText('Idea Validator')

    // The lockup is the OTHER way home (U2, and W3's `BrandLockup as="link"`).
    // Two affordances, one destination: this asserts the selector that
    // component's own docblock names, so a change to either lands here.
    const lockup = page.locator('a.brand-lockup[href="#/"]')
    await expect(lockup).toHaveCount(1)
    await expect(lockup).toContainText('Idea Validator')

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

    const lockup = page.locator('a.brand-lockup[href="#/"]')
    await expect(lockup).toHaveCount(1)
    await expect(lockup).toContainText(SAVED_GRAPH_NAME)

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

  test('keeps the workflow named at 390, truncated rather than hidden', async ({
    page,
    request,
  }) => {
    /*
     * U2's ≤640 ruling, and it is the second answer this width has had. The
     * header used to hide the workflow's name outright at 390, on the
     * measurement that it wrapped inside a 52px bar and was stated again in the
     * run console's WORKFLOW well. Two things broke that: the well belongs to
     * the console, so on the builder the name was stated nowhere, and the
     * lockup's `<h1>` that carried it here is `sr-only` now. So it truncates.
     *
     * THE ELLIPSIS IS ASSERTED AS A CHARACTER, not as a width. It lives on an
     * inner span because `text-overflow` does nothing on the `inline-flex`
     * crumb that holds the icon beside it - written on the crumb, a long name
     * clipped hard with no "…" at all, which reads as a rendering fault rather
     * than as a name that continues. jsdom cannot answer this: it has no layout
     * and every width it reports is zero.
     */
    const watch = watchConsole(page)
    const long = 'A workflow with a deliberately very long name indeed'
    const id = await createDocument(request, long)
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`/#/build/${id}`)
    await expect(page.locator('.builder-flow')).toBeVisible()

    const name = page.locator('.breadcrumb-name')
    await expect(name).toBeVisible()
    await expect(name).toHaveText(long)

    const rendered = await name.evaluate((el) => ({
      // The box is capped and the text overflows it, which together are what
      // `text-overflow` needs before it can draw anything.
      capped: el.getBoundingClientRect().width <= Math.ceil(0.42 * window.innerWidth) + 1,
      overflowing: el.scrollWidth > el.clientWidth,
      ellipsis: window.getComputedStyle(el).textOverflow,
      wrap: window.getComputedStyle(el).whiteSpace,
    }))
    expect(rendered).toEqual({
      capped: true,
      overflowing: true,
      ellipsis: 'ellipsis',
      wrap: 'nowrap',
    })

    // And the header still fits: one 52px row, nothing wrapped, no sideways
    // scroll on the body.
    const page390 = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
      headerH: Math.round(
        (document.querySelector('.app-header') as HTMLElement).getBoundingClientRect().height,
      ),
    }))
    expect(page390).toEqual({ scrollW: 390, clientW: 390, headerH: 52 })

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

  /* == ROUND-2 X1 and X2: the one vocabulary, in a real browser ============
   *
   * These read what a PERSON reads. The unit specs assert the same strings
   * against a mounted component and cannot answer the question the audit's
   * cold read asked - what does somebody scanning this page actually see -
   * because a component mount has no page to scan.
   *
   * The negative half is the one that matters and it is why these are browser
   * tests: `not.toContainText(/graph/i)` over a whole rendered surface catches
   * a word arriving from a template, a stylesheet's generated content, an
   * `aria-label` a screen reader would speak, or a component nobody thought to
   * check - which is exactly how the five nouns of N1 accumulated.
   */

  test('the home says what the product is, and calls a workflow a workflow', async ({
    page,
    request,
  }) => {
    const watch = watchConsole(page)
    await createDocument(request, SAVED_GRAPH_NAME)
    await openHome(page)

    // AUDIT-R2 H1: the sign-in wall's sentence, on the page a signed-in person
    // actually lands on. It was the only screen answering "what is this", and
    // it was the screen you stop seeing once you have an account.
    await expect(page.locator('[data-testid="product-sentence"]')).toHaveText(
      /^Draw a workflow on a canvas in Build, then Run it as a real CrewAI flow/,
    )

    // Ruling 4, the same three strings the gallery uses.
    await expect(page.locator('.home-page')).toContainText('TEMPLATES')
    await expect(page.locator('.home-page')).toContainText('Start from a working example')
    await expect(page.locator('.home-page')).toContainText(
      'Click one to copy it onto the canvas as a new workflow.',
    )
    await expect(page.locator('[data-testid="home-template-news-to-social"]')).toContainText(
      'Use this template',
    )

    expect(watch.unexpected).toEqual([])
  })

  test('no visible word on the builder calls a workflow a graph', async ({ page, request }) => {
    const watch = watchConsole(page)
    const id = await createDocument(request, SAVED_GRAPH_NAME)
    await page.goto(`/#/build/${id}`)
    await expect(page.locator('.builder-flow')).toBeVisible()
    await expect(page.locator('[data-testid="problems-checking"]')).toHaveCount(0, {
      timeout: 30_000,
    })

    // The four the audit's census named on this surface, now one word.
    const palette = page.locator('.builder-palette')
    await expect(palette).toContainText('YOUR WORKFLOWS')
    await expect(palette).toContainText('Saved here')
    await expect(page.locator('.rail-kicker').first()).toHaveText('WORKFLOW')

    /*
     * The whole rendered page, case-insensitively, and it is a stronger claim
     * than the three above: `graph` is gone from what a person can SEE. It says
     * nothing about the DOM - `GraphThumbnail`, `.graph-workspace` and
     * `builder.flow/v1` are all still there and all still correct - because
     * `innerText` is what a reader gets and class names are not.
     *
     * TWO THINGS ARE SUBTRACTED, and each is a decision rather than a
     * convenience.
     *
     * The document's own NAME, because `SAVED_GRAPH_NAME` is a fixture this
     * file chose and a fixture that fails a scan of its own page is a test
     * about itself. `split().join('')` and not `replace`, because the name is
     * on screen four times and `replace` takes the first.
     *
     * `.problem-message`, because those sentences are the SERVER'S. `bounds.py`
     * writes "this graph has no output node, so a completed run hands back no
     * body" and the dock renders it verbatim, which is the right thing to do
     * with a refusal - the client must not paraphrase a reason it did not
     * decide. WC1's brief is explicit that a server sentence is reported and
     * not rewritten, so this is the boundary of the client-side rename and the
     * assertion below states it rather than hiding it: if the server's
     * vocabulary is to move, it moves in `src/brief_crew/builder/bounds.py`,
     * which is nobody's file on this branch.
     */
    const seen = await page.locator('.studio-shell').innerText()
    const serverSentences = await page.locator('.problem-message').allInnerTexts()
    let visible = seen.split(SAVED_GRAPH_NAME).join('')
    for (const sentence of serverSentences) visible = visible.split(sentence).join('')

    expect(visible, 'a visible `graph` survives in what the client itself wrote').not.toMatch(
      /\bgraphs?\b/i,
    )

    expect(watch.unexpected).toEqual([])
  })

  test('the gallery names what it holds and what a click will do', async ({ page }) => {
    const watch = watchConsole(page)
    await page.goto('/#/build')
    await expect(page.locator('.template-gallery')).toBeVisible({ timeout: 30_000 })

    const gallery = page.locator('.template-gallery')
    await expect(gallery).toContainText('TEMPLATES')
    await expect(gallery).toContainText('Start from a working example')
    await expect(gallery.locator('.gallery-lede')).toHaveText(
      'Click one to copy it onto the canvas as a new workflow.',
    )
    // The action on every card, not on one. Nine cards, two rows, and the
    // second row is inside an open `details` - which is why this counts rather
    // than checks the first.
    await expect(gallery.locator('.template-action')).toHaveCount(TEMPLATE_TITLES.length)
    await expect(gallery.locator('.template-action').first()).toHaveText(/Use this template/)

    // The words it replaced, gone from the whole page.
    await expect(gallery).not.toContainText('YOUR GRAPHS')
    await expect(gallery).not.toContainText('A shape that already works')

    expect(watch.unexpected).toEqual([])
  })
})
