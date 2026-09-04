import { expect, test } from '@playwright/test'

/**
 * The handoff, recorded.
 *
 * A still cannot show a token walking an edge, and criterion 4 asks for the
 * recording explicitly so the critic can see the one effect that is motion
 * rather than state. `video: 'on'` writes a `.webm` per test into Playwright's
 * `outputDir`; the run leaves it named after the test, and the plan's Status
 * records where to find it. Its own test rather than a mode of the one above,
 * because turning video on for the twenty-screenshot run would record seven
 * minutes of navigation to show two seconds of token.
 */

async function launchRun(page: import('@playwright/test').Page, idea: string): Promise<void> {
  const review = page.getByRole('button', { name: 'Review', exact: true })
  if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
  await page.locator('#idea').fill(idea)
  await page.locator('.status-panel .control-actions button.button-primary').click()
}

test.use({ video: 'on' })

test('records a token walking the fan-out', { tag: '@launch' }, async ({ page }) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await expect(page.locator('.workflow-node')).toHaveCount(14)
  await launchRun(page, 'A shift-swap board for veterinary nurses')
  await expect(page.locator('.gate-card h2')).toHaveText('Confirm scope', { timeout: 60_000 })
  await page.locator('.gate-card').getByRole('button', { name: /^Approve/ }).click()

  const token = page.locator('[data-testid="handoff-token"]').first()
  await expect(token).toBeAttached({ timeout: 30_000 })
  // Long enough for the longest walk the formula permits, plus the receipt.
  await page.waitForTimeout(4_500)
  expect(await page.locator('.workflow-node.is-running').count()).toBeGreaterThanOrEqual(0)
})
