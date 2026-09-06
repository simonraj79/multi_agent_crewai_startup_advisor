import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

/**
 * One control cluster, two canvases, and the one question jsdom cannot be
 * asked: **does a drag actually move the viewport?**
 *
 * `DEFINITION-OF-DONE.md` U3. `tests/canvasTool.spec.ts` pins the state machine
 * - the resting tool per canvas, `H`/`V`, the typing guard, the space latch -
 * and stops exactly where jsdom does: it has no layout, no pointer and no d3,
 * so the `panOnDrag` value it asserts is a number nobody has watched do
 * anything. Everything below reads `.vue-flow__transformationpane`'s own
 * `transform` before and after a real left-drag, which is the library's answer
 * rather than ours.
 *
 * It is also the spec that keeps D3 honest. R2 stands: Hand is Vue Flow's
 * `panOnDrag`, not a pointer layer of ours - so if a future change did
 * implement panning by hand, the transform would still move here and nothing
 * would notice. What WOULD notice is the marquee assertion: the builder's
 * band-select is derived by the library from `selectionKeyCode === true &&
 * shouldPanOnDrag !== true`, and `useCanvasTool` deliberately does not flip
 * `selectionKeyCode` because that derivation already does it. The Hand-mode
 * test asserts no `.vue-flow__selection` appears, which is that derivation
 * measured rather than trusted.
 *
 * Free: `SYNTHETIC=1`, no Launch, no `@launch` tag. Nothing here starts a run.
 */

/** Nothing is tolerated, on the same terms as `studio.spec.ts`. */
const ALLOWED_CONSOLE_ERROR: RegExp | null = null

function watchConsole(page: Page): { unexpected: string[] } {
  const watch = { unexpected: [] as string[] }
  const record = (text: string) => {
    if (!ALLOWED_CONSOLE_ERROR?.test(text)) watch.unexpected.push(text)
  }
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text())
  })
  page.on('pageerror', (error) => record(`uncaught: ${error.message}`))
  return watch
}

/**
 * Where the run console lives, and why this is two hashes rather than one.
 *
 * W1 is moving the console from `#/` to `#/run` in parallel (D2), on a branch
 * that is not this one. Hard-coding either would make this spec fail on
 * whichever tree it is not merged into - and a red that means "the other work
 * has not landed yet" is the most expensive kind, because it looks exactly like
 * a defect in the cluster. So it tries the new route and falls back to the old,
 * and the fallback is not a hedge: after the merge the first `goto` resolves
 * and the fallback is dead code that costs one selector poll.
 */
async function openConsole(page: Page): Promise<void> {
  await page.goto('/#/run')
  const landed = await page
    .locator('.validator-flow')
    .waitFor({ state: 'visible', timeout: 5_000 })
    .then(() => true)
    .catch(() => false)
  if (landed) {
    await settle(page)
    return
  }
  await page.goto('/')
  await expect(page.locator('.validator-flow')).toBeVisible()
  await settle(page)
}

/**
 * Every document the builder half creates, deleted before and after.
 *
 * Lifted from `builder.spec.ts`, for its reason: `.template-card` collides with
 * a library row a previous run saved, and the failure is a strict-mode
 * violation rather than anything about the control cluster.
 */
async function clearLibrary(request: APIRequestContext): Promise<void> {
  const listed = await request.get('/api/builder/workflows')
  if (!listed.ok()) return
  const documents = (await listed.json()) as { id: string }[]
  for (const entry of documents) await request.delete(`/api/builder/workflows/${entry.id}`)
}

async function openBuilderDocument(page: Page): Promise<void> {
  await page.goto('/#/build')
  const card = page.locator('.template-card').filter({ hasText: 'Minimal gated agent' })
  await expect(card).toBeVisible()
  await card.click()
  // The template's own shape. Anchoring on it means a drag below lands on a
  // canvas that finished arriving rather than on one still fitting itself.
  await expect(page.locator('.vue-flow__node')).toHaveCount(4)
  await settle(page)
}

/** Let the initial `fitView` and its transition finish before reading a transform. */
async function settle(page: Page): Promise<void> {
  await expect(page.locator('.vue-flow__transformationpane')).toBeVisible()
  await page.waitForTimeout(1_200)
}

/** The library's own viewport transform - the only honest witness to a pan. */
function transformOf(page: Page): Promise<string | null> {
  return page.locator('.vue-flow__transformationpane').first().getAttribute('style')
}

interface DragResult {
  /** True if the viewport moved. */
  panned: boolean
  /** True if a band-selection rectangle existed mid-drag. */
  marqueed: boolean
}

/**
 * A left-drag on empty pane, reported as what it DID rather than as a click.
 *
 * The start point is the pane's bottom-left corner plus a margin on both
 * canvases, because that is empty on the validator graph and on every template
 * this file opens; dragging from the centre would grab a node on the builder
 * and measure node-dragging instead.
 */
async function leftDrag(page: Page, pane: Locator, options?: { space?: boolean }): Promise<DragResult> {
  const box = await pane.boundingBox()
  if (!box) throw new Error('the canvas pane has no box; the canvas did not mount')
  const startX = box.x + 90
  const startY = box.y + box.height - 90
  const before = await transformOf(page)

  if (options?.space) await page.keyboard.down(' ')
  await page.mouse.move(startX, startY)
  await page.mouse.down()
  await page.mouse.move(startX + 150, startY - 100, { steps: 12 })
  const marqueed = (await page.locator('.vue-flow__selection').count()) > 0
  await page.mouse.up()
  if (options?.space) await page.keyboard.up(' ')

  await page.waitForTimeout(250)
  return { panned: (await transformOf(page)) !== before, marqueed }
}

const NAMES = ['Zoom in', 'Zoom out', 'Fit the graph to the view', 'Select tool', 'Hand tool']

const selectButton = (page: Page) => page.getByRole('button', { name: 'Select tool' })
const handButton = (page: Page) => page.getByRole('button', { name: 'Hand tool' })

/**
 * The shared body of both halves of this row.
 *
 * One function rather than two copies, because U3's criterion is that the two
 * canvases behave the SAME, and a criterion about sameness proved by two
 * separately-written tests can pass while the thing it is about is false.
 */
function describeCanvas(
  label: string,
  open: (page: Page) => Promise<void>,
  paneSelector: string,
  expected: { restingTool: 'select' | 'hand'; marqueeInSelect: boolean },
): void {
  test.describe(`${label} canvas`, () => {
    test(`names all five buttons and shows which tool is active`, async ({ page }) => {
      const watch = watchConsole(page)
      await open(page)

      for (const name of NAMES) {
        await expect(page.getByRole('button', { name, exact: true })).toBeVisible()
      }
      // Exactly five - a sixth would mean the library's `interactive` lock came
      // back, which `:show-interactive="false"` exists to keep out.
      await expect(page.locator('.vue-flow__controls button')).toHaveCount(5)

      // Visible without hovering: the pressed button carries `aria-pressed` AND
      // ink that is not the resting ink. The row asks for both.
      const active = expected.restingTool === 'hand' ? handButton(page) : selectButton(page)
      const idle = expected.restingTool === 'hand' ? selectButton(page) : handButton(page)
      await expect(active).toHaveAttribute('aria-pressed', 'true')
      await expect(idle).toHaveAttribute('aria-pressed', 'false')
      const activeInk = await active.evaluate((el) => getComputedStyle(el).color)
      const idleInk = await idle.evaluate((el) => getComputedStyle(el).color)
      expect(activeInk).not.toBe(idleInk)

      expect(watch.unexpected).toEqual([])
    })

    test(`pans on a left-drag in Hand and does not in Select`, async ({ page }) => {
      const watch = watchConsole(page)
      await open(page)
      const pane = page.locator(paneSelector).first()

      await handButton(page).click()
      await expect(pane).toHaveCSS('cursor', 'grab')
      const hand = await leftDrag(page, pane)
      expect(hand.panned).toBe(true)
      // The marquee is OFF in Hand, and nothing switched `selectionKeyCode` to
      // make it so - Vue Flow derives it from `panOnDrag === true`.
      expect(hand.marqueed).toBe(false)

      await selectButton(page).click()
      const select = await leftDrag(page, pane)
      expect(select.panned).toBe(false)
      expect(select.marqueed).toBe(expected.marqueeInSelect)

      expect(watch.unexpected).toEqual([])
    })

    test(`flips aria-pressed on H and V`, async ({ page }) => {
      const watch = watchConsole(page)
      await open(page)

      await page.keyboard.press('h')
      await expect(handButton(page)).toHaveAttribute('aria-pressed', 'true')
      await expect(selectButton(page)).toHaveAttribute('aria-pressed', 'false')

      await page.keyboard.press('v')
      await expect(selectButton(page)).toHaveAttribute('aria-pressed', 'true')
      await expect(handButton(page)).toHaveAttribute('aria-pressed', 'false')

      expect(watch.unexpected).toEqual([])
    })

    test(`pans while space is held, without leaving Select`, async ({ page }) => {
      const watch = watchConsole(page)
      await open(page)
      const pane = page.locator(paneSelector).first()

      // By key rather than by click, so the space bar below cannot be delivered
      // to a focused button instead of to the window.
      await page.keyboard.press('v')
      await expect(selectButton(page)).toHaveAttribute('aria-pressed', 'true')

      const held = await leftDrag(page, pane, { space: true })
      expect(held.panned).toBe(true)

      // The toggle did not move: holding a key is a temporary pointer, not a
      // mode change, and `aria-pressed` is what announces a mode change.
      await expect(selectButton(page)).toHaveAttribute('aria-pressed', 'true')
      // And the left button is back where it was.
      const after = await leftDrag(page, pane)
      expect(after.panned).toBe(false)

      expect(watch.unexpected).toEqual([])
    })

    test(`zooms and fits from the same cluster`, async ({ page }) => {
      const watch = watchConsole(page)
      await open(page)

      const before = await transformOf(page)
      await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
      await page.waitForTimeout(500)
      const zoomed = await transformOf(page)
      expect(zoomed).not.toBe(before)

      await page.getByRole('button', { name: 'Fit the workflow to the view', exact: true }).click()
      await page.waitForTimeout(700)
      expect(await transformOf(page)).not.toBe(zoomed)

      expect(watch.unexpected).toEqual([])
    })
  })
}

describeCanvas('run console', openConsole, '.validator-flow .vue-flow__pane', {
  restingTool: 'hand',
  marqueeInSelect: false,
})

test.describe('builder', () => {
  test.beforeEach(async ({ request }) => {
    await clearLibrary(request)
  })
  test.afterEach(async ({ request }) => {
    await clearLibrary(request)
  })

  describeCanvas('flow builder', openBuilderDocument, '.builder-flow .vue-flow__pane', {
    restingTool: 'select',
    marqueeInSelect: true,
  })
})
