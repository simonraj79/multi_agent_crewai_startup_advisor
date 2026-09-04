import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

/**
 * A graph somebody DREW, running in the console.
 *
 * Plan 11 criterion 6, and the reason it needs a browser and a backend
 * together: the phase lane a published graph gets is painted from C6 `stage`
 * frames that `builder_runner._emit_plan` emits at kickoff, and nothing short
 * of a real publish followed by a real launch produces one. Before this, the
 * console's answer to "how far along is this" was ABSENT for every graph
 * anybody drew - `CREW_STAGES` describes the validator and
 * `assertStageCoverage` correctly refuses to narrate anything else, so
 * `CrewProgress` hid itself entirely.
 *
 * The publish half deliberately mirrors `e2e/templates.spec.ts` step for step,
 * because that file already established this is the path a person takes:
 * open the card, save, publish. What is new here is everything after it.
 *
 * ## Cost
 *
 * `SYNTHETIC=1` replaces the crew factories and nothing else, so the compiled
 * definition, the engine, the gates, the routers and the plan emitter are all
 * the production ones. Free, and still a real proof of the lane.
 */

/** The simplest template with more than one phase, so "in order" means something. */
const TEMPLATE = { id: 'sequential-pipeline', title: 'Sequential pipeline', nodes: 7 }

async function clearLibrary(request: APIRequestContext): Promise<void> {
  const listed = await request.get('/api/builder/workflows')
  if (!listed.ok()) return
  const documents = (await listed.json()) as { id: string }[]
  for (const entry of documents) await request.delete(`/api/builder/workflows/${entry.id}`)
}

async function publishTemplate(page: Page): Promise<string> {
  await page.goto('/#/build')
  await page.reload()
  const card = page.locator('.template-card', { hasText: TEMPLATE.title })
  await expect(card).toBeVisible()
  await card.click()
  await expect(page.locator('.vue-flow__node')).toHaveCount(TEMPLATE.nodes)
  await expect(page.locator('[data-testid="problems-checking"]')).toHaveCount(0, {
    timeout: 20_000,
  })

  await page.keyboard.press('Control+s')
  await expect
    .poll(() => new URL(page.url()).hash, { timeout: 20_000 })
    .toMatch(/#\/build\/ug_[0-9a-f]{8}$/)
  const id = /ug_[0-9a-f]{8}/.exec(new URL(page.url()).hash)![0]

  await page.keyboard.press('Control+Shift+P')
  const publish = page.locator('[aria-labelledby="publish-title"]')
  await expect(publish).toBeVisible()
  await publish.getByRole('button', { name: /^(Publish|Republish)$/ }).click()
  await expect(publish).toContainText(/anyone with the link can launch it/i)
  return id
}

test.describe('a published graph in the run console', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test.afterEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test('paints a phase lane that advances in order', { tag: '@launch' }, async ({ page }) => {
    test.setTimeout(240_000)
    const id = await publishTemplate(page)

    // "Run it" is the control the dialog offers, and it is the path a person
    // takes: it writes the handoff and navigates. Taking it rather than
    // building a URL is what makes this a test of the product.
    await page.getByRole('button', { name: 'Run it' }).click()
    await expect(page.locator('.handoff-banner')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('.workflow-node')).toHaveCount(TEMPLATE.nodes)

    // The lane is ABSENT before a run, because the plan frames are what draw it
    // and nothing has emitted one yet. That is the honest state: this console
    // has never seen this graph and is not going to guess its shape.
    await expect(page.locator('.crew-progress')).toHaveCount(0)

    const review = page.getByRole('button', { name: 'Review', exact: true })
    if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
    await page.locator('textarea#idea').fill('A weekly digest of what changed in our codebase.')
    await page.locator('.status-panel .control-actions button.button-primary').click()

    // The lane paints from the plan frames, which arrive at KICKOFF - before
    // the first node runs - so it is drawn by the time anything has happened.
    const lane = page.locator('.crew-progress')
    await expect(lane, 'a published graph got no phase lane').toBeVisible({ timeout: 60_000 })

    const chips = page.locator('.crew-stage .crew-label')
    const stageCount = await chips.count()
    expect(stageCount, 'the plan named fewer than three layers').toBeGreaterThanOrEqual(3)

    // In ORDER: the current stage index only ever climbs. Sampled across the
    // run, because "advances in order" is a statement about a sequence and a
    // single reading cannot make it.
    const seen: number[] = []
    for (let i = 0; i < 8; i += 1) {
      const index = await page
        .locator('.crew-stage')
        .evaluateAll((items) => items.findIndex((el) => el.classList.contains('is-current')))
      if (index >= 0) seen.push(index)
      // Answer the one gate this template raises, whenever it appears.
      const approve = page.locator('.gate-card').getByRole('button', { name: /^Approve/ })
      if (await approve.count()) await approve.first().click()
      await page.waitForTimeout(900)
    }
    expect(seen.length, 'the lane never reported a current stage').toBeGreaterThan(0)
    for (let i = 1; i < seen.length; i += 1) {
      expect(seen[i], `stage went backwards: ${seen.join(' -> ')}`).toBeGreaterThanOrEqual(
        seen[i - 1],
      )
    }
    expect(seen.at(-1), 'the lane never left the first stage').toBeGreaterThan(seen[0])

    // Visible for the WHOLE run, which is the half of the criterion the old
    // behaviour failed outright.
    await expect(lane).toBeVisible()
    expect(id).toMatch(/^ug_[0-9a-f]{8}$/)
  })

  test('gives the lane medallions rather than the validator\'s boat', { tag: '@launch' }, async ({
    page,
  }) => {
    test.setTimeout(240_000)
    await publishTemplate(page)
    await page.getByRole('button', { name: 'Run it' }).click()
    await expect(page.locator('.handoff-banner')).toBeVisible({ timeout: 20_000 })

    const review = page.getByRole('button', { name: 'Review', exact: true })
    if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
    await page.locator('textarea#idea').fill('A weekly digest of what changed in our codebase.')
    await page.locator('.status-panel .control-actions button.button-primary').click()

    await expect(page.locator('.crew-progress')).toBeVisible({ timeout: 60_000 })
    // The boat is the validator's, and its three oars ARE three research
    // branches. A graph somebody drew has no such fact, so drawing three rowers
    // on a two-node layer would claim a fan-out that does not exist.
    await expect(page.locator('.crew-boat')).toHaveCount(0)
  })
})
