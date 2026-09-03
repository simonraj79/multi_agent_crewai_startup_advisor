import { expect, test, type Locator, type Page } from '@playwright/test'

/**
 * Layout regression guards for the flow builder.
 *
 * ## Why this file exists at all
 *
 * Two layout defects shipped in this deliverable and both were invisible to 988
 * green unit tests:
 *
 *   1. On the empty gallery `BuilderView` renders neither the palette nor the
 *      inspector, but `.studio-main` still declared three columns - so the
 *      gallery became the grid's first child and was placed in the 236px
 *      palette column, inside a row sized for a document bar that is not there.
 *      Measured at 2000x1150: a 236x70 box holding 1356px of content.
 *   2. The canvas fitted its viewport BEFORE the budget meter and the problems
 *      dock had taken their height, so the 16-node validator template opened
 *      with its last two nodes underneath the dock while reporting itself
 *      fitted.
 *
 * Neither is a structural defect. Every element was in the DOM, in the right
 * order, with the right props, which is all a jsdom mount can ask about - it
 * never asks how wide anything ended up. So the whole class needs a real
 * browser with real layout, and that is the only thing this file does: it makes
 * measurements and asserts numbers. Behaviour belongs in `builder.spec.ts`.
 *
 * ## Proved by breaking it
 *
 * Every assertion below was run against the pre-fix code and observed to FAIL,
 * then against the fix and observed to pass. Measured, not asserted:
 *
 *   - Reverting `studio.css`'s two `.is-gallery` rules gave `clientWidth` 236
 *     against a 900px floor, a `scrollHeight - clientHeight` of 1531, a
 *     `scrollWidth - clientWidth` of 60, and the last template card's bottom
 *     edge at 1438 inside a gallery whose own bottom edge was at 122. All four
 *     soft assertions fired in one run, which is why they are `expect.soft`:
 *     the failure names every dimension the defect touched rather than the
 *     first one alphabetically.
 *   - Deleting `BuilderCanvas`'s settling `ResizeObserver` left the worst node
 *     92px below the pane's bottom edge, and it stayed there for the entire ten
 *     seconds the poll waits - the broken code is not slow, it is wrong.
 *
 * A guard nobody has seen fail is a guard nobody should trust - the same
 * argument `docs/gotchas-and-insights.md` makes about a green suite, and the
 * same method that proved the `./e2e` tsconfig reference (remaining-work
 * item 38).
 *
 * ## Which backend
 *
 * The same one `studio.spec.ts` documents at length: `e2e/vite.e2e.config.ts`
 * proxying to the no-cost `SYNTHETIC=1` service, never the paid backend on
 * :8000. Nothing here launches a run or saves a document, so this file is free
 * in both senses - it spends no money and it leaves no rows behind.
 */

/**
 * Nothing is tolerated, for the reason `studio.spec.ts` gives: an exemption
 * that outlives its cause widens silently. All three tests below pass with
 * this `null`, which is what makes the policy a measurement rather than a hope.
 */
const ALLOWED_CONSOLE_ERROR: RegExp | null = null

interface ConsoleWatch {
  unexpected: string[]
}

function watchConsole(page: Page): ConsoleWatch {
  const watch: ConsoleWatch = { unexpected: [] }
  const record = (text: string) => {
    if (!ALLOWED_CONSOLE_ERROR?.test(text)) watch.unexpected.push(text)
  }
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text())
  })
  page.on('pageerror', (error) => record(`uncaught: ${error.message}`))
  return watch
}

/** `IDEA_VALIDATOR` in `src/data/builderTemplates.ts`. The count is the point. */
const VALIDATOR_TEMPLATE_NODES = 16

/**
 * A wide viewport for the gallery test, because the defect was a RATIO.
 *
 * At 1440px a 236px column is 16% of the window and a careless floor would
 * still pass it; at 2000px it is 11.8% and the assertion below - at least 45% -
 * has room to be unambiguous either way. This is also the width the design
 * critic captured the gallery at, so the numbers in this file and the ones in
 * `docs/comparison/ours/` describe the same frame.
 */
const WIDE = { width: 2000, height: 1200 }

/**
 * The library list is stubbed EMPTY, and only the library list.
 *
 * `GET /api/builder/workflows` reads a shared synthetic database that other
 * suites - and other people - save into, and `TemplateGallery` renders one row
 * per saved graph below the four template cards. Left live, the "content is not
 * clipped" assertion would be a measurement of how many documents happened to
 * be lying around, and would go red for a reason that has nothing to do with
 * layout. Stubbing it makes the gallery a fixed height, which is what lets the
 * overflow assertion be exact rather than generous.
 *
 * Nothing else is intercepted: the four cards are still priced by the real
 * service, so the cards still have their real content and their real height.
 */
async function stubEmptyLibrary(page: Page): Promise<void> {
  await page.route('**/api/builder/workflows*', (route) =>
    route.request().method() === 'GET'
      ? route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      : route.fallback(),
  )
}

function gallery(page: Page): Locator {
  return page.locator('.template-gallery')
}

/** A document straight into the store, so the library has rows to lay out. */
async function seedDocument(page: Page, name: string): Promise<string> {
  const listed = await page.request.get('/api/builder/vocabulary')
  expect(listed.ok()).toBe(true)
  const document = {
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
  }
  const created = await page.request.post('/api/builder/workflows', {
    data: { document, expected_version: null },
  })
  expect(created.status()).toBe(201)
  return ((await created.json()) as { id: string }).id
}

async function openValidatorTemplate(page: Page): Promise<void> {
  await page.goto('/#/build')
  await page.locator('.template-card', { hasText: 'Idea validator' }).click()
  await expect(page.locator('.vue-flow__node')).toHaveCount(VALIDATOR_TEMPLATE_NODES)
}

/**
 * Every node's worst excursion outside the pane, in CSS pixels.
 *
 * Read from `getBoundingClientRect` on both sides rather than from the viewport
 * transform, because the transform is exactly what the broken code was
 * confident about: it reported a fit, and the fit was honest arithmetic about a
 * container that stopped existing one frame later. The rectangles are the
 * arbiter, and a node drawn below the pane's bottom edge is hidden behind the
 * problems dock whatever the matrix says.
 */
async function worstNodeOverflow(page: Page): Promise<number> {
  return page.evaluate(() => {
    const frame = document.querySelector('.builder-canvas')
    if (!frame) return Number.POSITIVE_INFINITY
    const box = frame.getBoundingClientRect()
    let worst = 0
    for (const node of document.querySelectorAll('.vue-flow__node')) {
      const rect = node.getBoundingClientRect()
      worst = Math.max(
        worst,
        box.top - rect.top,
        rect.bottom - box.bottom,
        box.left - rect.left,
        rect.right - box.right,
      )
    }
    return Math.round(worst)
  })
}

test.describe('Flow builder layout', () => {
  test('gives the empty gallery the page, not the 236px palette column', async ({ page }) => {
    const watch = watchConsole(page)
    await page.setViewportSize(WIDE)
    await stubEmptyLibrary(page)
    await page.goto('/#/build')

    // The gallery is the canvas's empty state (§5.6), so it is inside
    // `#builder-canvas` - and it is the ONLY thing in there. Asserting the two
    // rails are absent first is what makes the width assertion meaningful: a
    // 236px gallery is only possible while a column that holds nothing is
    // still being reserved for it.
    await expect(gallery(page).locator('.template-card')).toHaveCount(4)
    await expect(page.locator('.builder-palette')).toHaveCount(0)
    await expect(page.locator('.builder-inspector')).toHaveCount(0)

    const box = await gallery(page).evaluate((el) => ({
      clientWidth: el.clientWidth,
      clientHeight: el.clientHeight,
      scrollWidth: el.scrollWidth,
      scrollHeight: el.scrollHeight,
    }))

    // A substantial fraction of the window, not a sliver of it. The floor is
    // 45% rather than the 54% the gallery's own `width: min(1080px, 100%)`
    // actually resolves to, so a later change to that cap is a design decision
    // rather than a test failure - while 236px (11.8%) can never squeak past.
    expect
      .soft(box.clientWidth, 'the gallery should be a page, not a column')
      .toBeGreaterThanOrEqual(Math.round(WIDE.width * 0.45))

    // ...and it must not be CLIPPED. `.template-gallery` carries
    // `max-height: 100%; overflow: auto`, so a row that collapsed to 70px
    // reports the whole 1356px of cards as scrollHeight and shows a sliver.
    // One pixel of slack for sub-pixel rounding; anything a reader would call
    // "there is more below" fails.
    expect
      .soft(box.scrollHeight - box.clientHeight, 'the gallery is clipped vertically')
      .toBeLessThanOrEqual(1)
    expect
      .soft(box.scrollWidth - box.clientWidth, 'the gallery is clipped horizontally')
      .toBeLessThanOrEqual(1)

    // The last card is fully on screen, stated as a rectangle rather than as a
    // scroll figure - this is the assertion a human would make by looking, and
    // it survives any future change to how the gallery scrolls.
    const cardBox = await gallery(page).locator('.template-card').last().boundingBox()
    const galleryBox = await gallery(page).boundingBox()
    expect(cardBox, 'the last template card should have a box').not.toBeNull()
    expect(galleryBox, 'the gallery should have a box').not.toBeNull()
    expect
      .soft(cardBox!.y + cardBox!.height, 'the last template card is below the fold')
      .toBeLessThanOrEqual(galleryBox!.y + galleryBox!.height + 1)

    expect(watch.unexpected).toEqual([])
  })

  test('lands every node of the validator template inside the canvas pane', async ({ page }) => {
    const watch = watchConsole(page)
    await stubEmptyLibrary(page)
    await openValidatorTemplate(page)

    /*
     * Polled, not sampled once, and the poll is doing two different jobs.
     *
     * The fix is a `ResizeObserver` that re-fits while the container is still
     * settling, so the correct answer can arrive a frame or two after the nodes
     * do and a single immediate read would be racing it. And because the broken
     * code never reaches zero at all, the poll's timeout IS the failure: it
     * spends its budget watching a number that does not move.
     */
    await expect
      .poll(() => worstNodeOverflow(page), {
        timeout: 10_000,
        message: 'every node must settle inside the pane the fit was computed against',
      })
      .toBe(0)

    // The mechanism, stated separately from its symptom: the pane stops where
    // the problems dock starts. A fit computed against a taller box is exactly
    // how nodes end up underneath it.
    const geometry = await page.evaluate(() => {
      const frame = document.querySelector('.builder-canvas')!.getBoundingClientRect()
      const dock = document.querySelector('.problems-panel')?.getBoundingClientRect() ?? null
      return {
        paneBottom: frame.bottom,
        paneHeight: frame.height,
        dockTop: dock ? dock.top : null,
      }
    })
    expect(geometry.dockTop, 'the problems dock should be rendered').not.toBeNull()
    expect(geometry.paneHeight).toBeGreaterThan(100)
    expect(Math.round(geometry.paneBottom)).toBeLessThanOrEqual(Math.round(geometry.dockTop!) + 1)

    expect(watch.unexpected).toEqual([])
  })

  test('keeps all three shell columns present and non-zero once a document is open', async ({
    page,
  }) => {
    const watch = watchConsole(page)
    await stubEmptyLibrary(page)
    await openValidatorTemplate(page)

    const columns = await page.evaluate(() => {
      const width = (selector: string) =>
        document.querySelector(selector)?.getBoundingClientRect().width ?? 0
      return {
        palette: width('.builder-palette'),
        workspace: width('#builder-canvas'),
        inspector: width('.builder-inspector'),
        main: width('.studio-main'),
      }
    })

    // All three exist and all three have width. The gallery defect was the
    // mirror image of this - a column that existed with nothing in it - so the
    // guard is worth stating in both directions: the editor keeps its three,
    // and the gallery (above) keeps none of them.
    expect(columns.palette).toBeGreaterThan(0)
    expect(columns.workspace).toBeGreaterThan(0)
    expect(columns.inspector).toBeGreaterThan(0)

    // The canvas is the column that must not be squeezed: it is the product.
    expect(columns.workspace).toBeGreaterThan(columns.palette)
    expect(columns.workspace).toBeGreaterThan(columns.inspector)

    // And they tile the row rather than overflowing it, which is what a grid
    // whose columns are declared but whose children are missing does NOT do.
    const total = columns.palette + columns.workspace + columns.inspector
    expect(Math.abs(total - columns.main)).toBeLessThanOrEqual(2)

    expect(watch.unexpected).toEqual([])
  })
})

test.describe('the saved-graphs library (D-15-4)', () => {
  /*
   * Round 1: the palette's library row truncated "Minimal gated agent copy" to
   * "Minimal gated age…" - losing the one word that told the copy from its
   * source - and a third row sat clipped at y≈895 with no scrollbar. Both are
   * measurements only a browser can make: how wide a name ended up, and
   * whether the last row is reachable at all.
   */
  // Prefixed so the rows are this test's own: the synthetic store is shared
  // with the other suites, and a published document the cleanup cannot
  // delete (409) is named exactly like the template.
  const NAMES = [
    'LP Minimal gated agent copy',
    'LP Minimal gated agent imported',
    'LP Minimal gated agent',
    'LP a fourth graph so the list has to earn its height',
    'LP a fifth graph, for the same reason',
    'LP a sixth graph, because the capture clipped the third',
  ]
  for (const name of NAMES) expect(name.length).toBeLessThanOrEqual(80)
  const created: string[] = []

  test.beforeEach(async ({ page }) => {
    for (const name of NAMES) created.push(await seedDocument(page, name))
  })

  test.afterEach(async ({ page }) => {
    for (const id of created.splice(0)) await page.request.delete(`/api/builder/workflows/${id}`)
  })

  test('shows every distinguishing word and keeps every row reachable', async ({ page }) => {
    const watch = watchConsole(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/#/build')
    await page.getByRole('button', { name: /minimal gated agent/i }).first().click()
    const palette = page.locator('.builder-palette')
    await expect(palette).toBeVisible()
    // Only the rows this test seeded.
    const rows = palette.locator('.builder-library-row', { hasText: /^LP / })
    await expect(rows).toHaveCount(NAMES.length)

    // No name is cut horizontally: the distinguishing word is on screen, on a
    // second line if it must be, never behind an ellipsis in the first.
    for (const name of NAMES.slice(0, 2)) {
      const label = palette.locator('.builder-library-name', { hasText: name }).first()
      await expect(label).toBeVisible()
      const box = await label.evaluate((el) => ({
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
      }))
      expect(box.scrollWidth).toBeLessThanOrEqual(box.clientWidth + 1)
      expect(box.scrollHeight).toBeLessThanOrEqual(box.clientHeight + 1)
    }

    // The palette ends inside the viewport, and the last seeded row can be
    // reached - the sixth, whose name says why it exists.
    const paletteBox = (await palette.boundingBox())!
    expect(paletteBox.y + paletteBox.height).toBeLessThanOrEqual(900 + 1)
    const last = palette.locator('.builder-library-row', { hasText: 'LP a sixth graph' })
    await last.scrollIntoViewIfNeeded()
    const lastBox = (await last.boundingBox())!
    expect(lastBox.y + lastBox.height).toBeLessThanOrEqual(paletteBox.y + paletteBox.height + 1)
    expect(lastBox.y).toBeGreaterThanOrEqual(paletteBox.y - 1)

    expect(watch.unexpected).toEqual([])
  })
})
