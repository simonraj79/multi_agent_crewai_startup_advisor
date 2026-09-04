import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

/**
 * The judge's capture set for plan 14, produced by the product rather than by hand.
 *
 * Criterion 10 asks for blind captures of the gallery and of each template's
 * canvas at two viewports in two themes, under `benchmarks/ours/templates/`.
 * `benchmarks/README.md` says how they are named and why they are NOT committed
 * - they are pictures of a build, regenerated on demand, and a round's defects
 * live in the ledger rather than in its pixels.
 *
 * ONE TEST, FOUR AXES. Both viewports and both themes are driven from inside
 * the test with `setViewportSize` and `emulateMedia` rather than by adding a
 * third Playwright project, so this file needs no edit to `playwright.config.ts`
 * - a config owned by another plan - and the whole set comes out of one run.
 *
 * `emulateMedia`, not `data-theme`. `useStudioTheme` resolves
 * `prefers-color-scheme` for a reader who has not chosen, and the judge is a
 * reader who has not chosen; stamping the attribute would capture the toggle
 * rather than the default anybody actually meets.
 *
 * It asserts almost nothing on purpose. A capture spec that failed would leave
 * the judge with a partial set and no captures of the state that broke it,
 * which is exactly the round you cannot score. The one thing it does insist on
 * is that each template DREW - a screenshot of an empty canvas is not a capture
 * of a template.
 */

/** `benchmarks/ours/templates/`, relative to `frontend/`. */
const OUT = path.resolve(process.cwd(), '..', 'benchmarks', 'ours', 'templates')

const VIEWPORTS = [
  { name: '1440x900', width: 1440, height: 900 },
  { name: '390x844', width: 390, height: 844 },
] as const

const THEMES = ['dark', 'light'] as const

/** The gallery's six cards, and how many nodes each draws once opened. */
const TEMPLATES = [
  { id: 'blank', title: 'Blank canvas', nodes: 2 },
  { id: 'sequential-pipeline', title: 'Sequential pipeline', nodes: 7 },
  { id: 'conditional-router', title: 'Conditional router', nodes: 10 },
  { id: 'reflection-loop', title: 'Reflection loop', nodes: 8 },
  { id: 'hierarchical-delegation', title: 'Hierarchical delegation', nodes: 7 },
  { id: 'idea-validator', title: 'Idea validator', nodes: 16 },
] as const

/**
 * An empty saved-graph library, so the gallery is the gallery.
 *
 * Without it a capture taken after any other spec has run shows somebody else's
 * documents above the cards, and the judge scores a list nobody designed.
 */
async function stubEmptyLibrary(page: Page): Promise<void> {
  await page.route('**/api/builder/workflows', async (route, request) => {
    if (request.method() !== 'GET') return route.fallback()
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
}

test.describe('plan 14 capture set', () => {
  test('captures the gallery and every template, two viewports, two themes', async ({ page }) => {
    // Twenty-eight screenshots and six navigations per axis. Generous, because
    // a capture run that times out half way is worse than no capture run.
    test.setTimeout(300_000)
    mkdirSync(OUT, { recursive: true })
    await stubEmptyLibrary(page)

    for (const viewport of VIEWPORTS) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      for (const theme of THEMES) {
        await page.emulateMedia({ colorScheme: theme })

        // `reload` for the same reason as below: the previous iteration ended
        // with a template open at `#/build`, and a same-hash `goto` does
        // nothing at all.
        await page.goto('/#/build')
        await page.reload()
        await expect(page.locator('.template-card').first()).toBeVisible()
        // The disclosure OPEN, because the two library templates are part of
        // what a reader is offered and a capture of a shut `details` says
        // nothing about them. Set rather than CLICKED: it ships open, so a
        // click would shut it and capture the opposite of what is wanted.
        const more = page.locator('.template-more')
        if (await more.count()) {
          await more.evaluate((el) => {
            ;(el as HTMLDetailsElement).open = true
          })
        }
        await page.waitForTimeout(250)
        await page.screenshot({
          path: path.join(OUT, `14-gallery-${viewport.name}-${theme}.png`),
          fullPage: false,
        })

        for (const template of TEMPLATES) {
          // `reload`, because opening a template leaves the hash at `#/build`
          // and a same-hash `goto` does nothing - the canvas would stay open
          // and every capture after the first would be of the same graph.
          await page.goto('/#/build')
          await page.reload()
          await page.locator('.template-card', { hasText: template.title }).click()
          await expect(
            page.locator('.vue-flow__node'),
            `${template.title} drew nothing`,
          ).toHaveCount(template.nodes)
          // The fit settles over a frame or two - `BuilderCanvas`'s
          // `ResizeObserver` re-fits until the container stops moving - so a
          // capture taken immediately is a capture of the wrong zoom.
          await page.waitForTimeout(700)
          await page.screenshot({
            path: path.join(OUT, `14-${template.id}-${viewport.name}-${theme}.png`),
            fullPage: false,
          })
        }
      }
    }
  })
})
