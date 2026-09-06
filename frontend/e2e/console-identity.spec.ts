import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

/**
 * The console says whose workflow it is running - however you got there.
 *
 * ROUND-2 rows R1-R4, CLAUDE.md items 55-58. Every one of these was on `main`
 * and every one of them is invisible to a unit test for the same reason: the
 * defect is that four surfaces rendered by three components agree with each
 * other about the WRONG workflow, and the only instrument that can see that is
 * a browser with a real published graph in it.
 *
 * ## What was measured before any of it was changed
 *
 * A published `News to social post` (input field `subject`), run and finished,
 * then reached without the publish dialog's handoff:
 *
 *   kicker      RUN - BUILT IN            (its own workflow is not built in)
 *   heading     Evidence pipeline         (the validator's second line)
 *   breadcrumb  Idea Validator            (a different workflow entirely)
 *   WORKFLOW    Idea Validator            (over the button that spends money)
 *   input       IDEA TO VALIDATE          (the field is `subject`)
 *   textarea    "An AI tool that turns Figma files into production React"
 *   pointer     null                      (the finished run was unreachable)
 *
 * The cause was one record: `builder-run-handoff`, which ONLY the publish
 * dialog's "Run it" writes. Everything now reads the run's own descriptor.
 *
 * ## Cost
 *
 * `SYNTHETIC=1` replaces the crew factories and nothing else - the publish, the
 * compile, the engine, the gates and the frames are all the production ones. It
 * is free, and it is still a real proof of the identity, because identity comes
 * off the descriptor the real service builds.
 */

const TEMPLATE = { title: 'News to social post', field: 'subject', inputLabel: 'SUBJECT' }
const IDEA = 'What the vector-database vendors shipped in September'

const kicker = (page: Page): Locator => page.locator('.canvas-kicker')
const crumb = (page: Page): Locator => page.locator('.breadcrumb-name')
const well = (page: Page): Locator => page.locator('.status-panel .workflow-title')
const inputLabel = (page: Page): Locator => page.locator('label[for="idea"]')
const runSwitch = (page: Page): Locator => page.locator('[data-testid="run-switch"]')

async function clearLibrary(request: APIRequestContext): Promise<void> {
  const listed = await request.get('/api/builder/workflows')
  if (!listed.ok()) return
  const documents = (await listed.json()) as { id: string }[]
  for (const entry of documents) {
    await request.post(`/api/builder/workflows/${entry.id}/unpublish`).catch(() => undefined)
    await request.delete(`/api/builder/workflows/${entry.id}`)
  }
}

/** Open the template on the canvas and save it. Returns the document id. */
async function saveTemplate(page: Page): Promise<string> {
  await page.goto('/#/build')
  await page.reload()
  const card = page.locator('.template-card', { hasText: TEMPLATE.title })
  await expect(card).toBeVisible()
  await card.click()
  await expect(page.locator('[data-testid="problems-checking"]')).toHaveCount(0, {
    timeout: 20_000,
  })
  await page.keyboard.press('Control+s')
  await expect
    .poll(() => new URL(page.url()).hash, { timeout: 20_000 })
    .toMatch(/#\/build\/ug_[0-9a-f]{8}$/)
  return /ug_[0-9a-f]{8}/.exec(new URL(page.url()).hash)![0]
}

/**
 * Publish the open document through its own dialog, and leave the dialog open.
 *
 * `News to social post` is gateless by design, so the dialog's closing sentence
 * is the 403 explanation rather than the "anyone with the link" one - which is
 * why this waits on the SUCCESS HEADING instead. Getting that wrong costs 15
 * seconds and reads like a publish failure, so it is stated.
 *
 * The heading is `Your workflow is live` since ROUND-2 ruling 10 - it was
 * `This graph is live`, which is the string this line waited on until the
 * merge, and neither branch could see the other half.
 */
async function publishOpenDocument(page: Page): Promise<void> {
  await page.keyboard.press('Control+Shift+P')
  const dialog = page.locator('[aria-labelledby="publish-title"]')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: /^(Publish|Republish)$/ }).click()
  await expect(dialog).toContainText(/Your workflow is live/i, { timeout: 30_000 })
}

/**
 * Launch whatever the console is pointed at, and wait for it to end.
 *
 * REVIEW FIRST, and it is not optional here. The console defaults to
 * unattended gates, and `create_run` answers **422 - workflow ug_... has no
 * gates to skip** for a graph that declares none; `News to social post` is
 * gateless by design (its own module note explains the trade). Measured: the
 * launch was refused, no run id was issued, and the console read `Failed`
 * within a second - which looks exactly like a run that started and died.
 */
async function launchAndFinish(page: Page, text: string): Promise<void> {
  const review = page.getByRole('button', { name: 'Review', exact: true })
  if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
  await page.locator('textarea#idea').fill(text)
  await page.locator('.status-panel .control-actions button.button-primary').click()
  await expect
    .poll(async () => page.locator('.canvas-meta span').first().textContent(), { timeout: 120_000 })
    .toMatch(/Finished|Failed|Cancelled/i)
}

/** Every identity surface at once, so a failure names all of them. */
async function identityOf(page: Page): Promise<Record<string, string | null>> {
  return {
    kicker: (await kicker(page).textContent())?.trim() ?? null,
    heading: (await page.locator('#graph-title').textContent())?.trim() ?? null,
    crumb: (await crumb(page).textContent())?.trim() ?? null,
    well: (await well(page).textContent())?.trim() ?? null,
    inputLabel: (await inputLabel(page).textContent())?.trim() ?? null,
    title: await page.title(),
  }
}

test.describe('the console names the workflow it is running', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test.afterEach(async ({ request }) => {
    await clearLibrary(request)
  })

  /**
   * R1, arm 1 of 3: the publish dialog's own "Run it". This arm PASSED before
   * the change, because it is the one path that writes a handoff - it is here
   * as the control, so a regression that broke the descriptor path could not
   * hide behind it.
   */
  test('names it when the publish dialog hands it over', { tag: '@launch' }, async ({ page }) => {
    test.setTimeout(240_000)
    await saveTemplate(page)
    await publishOpenDocument(page)
    await page.getByRole('button', { name: 'Run it' }).click()

    await expect(page.locator('.handoff-banner')).toBeVisible({ timeout: 20_000 })
    expect(await identityOf(page)).toEqual({
      kicker: 'RUN — YOUR WORKFLOW',
      heading: TEMPLATE.title,
      crumb: TEMPLATE.title,
      well: TEMPLATE.title,
      inputLabel: TEMPLATE.inputLabel,
      title: `${TEMPLATE.title} · Crew Studio`,
    })
    await page.screenshot({ path: 'test-results/R1-runit.png' })
  })

  /**
   * R1, arm 2 of 3, and R3: the workspace switch. Item 57 is why this arm
   * exists at all - the switch used to be a bare navigation, so it landed on a
   * console showing the BUILT-IN validator over a breadcrumb that had just
   * named the author's workflow.
   */
  test('names it when the Run switch carries it', { tag: '@launch' }, async ({ page }) => {
    test.setTimeout(240_000)
    const id = await saveTemplate(page)
    await publishOpenDocument(page)
    await page.getByRole('button', { name: 'Close' }).click()

    // The switch, not the dialog. A fresh load first, so nothing survives from
    // the publish: this is an author coming back to a graph they published.
    await page.goto(`/#/build/${id}`)
    await page.reload()
    await expect(page.locator('.vue-flow__node').first()).toBeVisible({ timeout: 30_000 })
    // The ACCESSIBLE name, not `textContent`: the control carries both labels
    // so its width cannot change (D-15-14), and the spare one is
    // `visibility: hidden` - out of the accessibility tree, still in the text.
    await expect(runSwitch(page)).toHaveAttribute('data-run-state', 'ready')
    await expect(runSwitch(page)).toHaveAccessibleName(/^Run$/)
    await runSwitch(page).click()

    await expect.poll(() => new URL(page.url()).hash).toBe('#/run')
    await expect(crumb(page)).toHaveText(TEMPLATE.title, { timeout: 30_000 })
    expect(await identityOf(page)).toEqual({
      kicker: 'RUN — YOUR WORKFLOW',
      heading: TEMPLATE.title,
      crumb: TEMPLATE.title,
      well: TEMPLATE.title,
      inputLabel: TEMPLATE.inputLabel,
      title: `${TEMPLATE.title} · Crew Studio`,
    })
    await page.screenshot({ path: 'test-results/R3-run-switch.png' })
  })

  /**
   * R1 arm 3, R2 and R4 in one journey, because they are one journey: launch a
   * run, let it finish, throw the handoff away, reload. Everything on screen
   * afterwards has to come from the run's own descriptor and the run's own
   * frames, which is exactly what item 55 and item 56 say it did not.
   *
   * The report is the R4 half: before this, the pointer was gone within ~40 ms
   * of the terminal frame and the report, the verdict and the trace with it.
   */
  test('names it, recovers the input and REOPENS it after a reload', { tag: '@launch' }, async ({
    page,
  }) => {
    test.setTimeout(240_000)
    await saveTemplate(page)
    await publishOpenDocument(page)
    await page.getByRole('button', { name: 'Run it' }).click()
    await expect(page.locator('.handoff-banner')).toBeVisible({ timeout: 20_000 })
    await launchAndFinish(page, IDEA)

    // The pointer SURVIVES the terminal frame now (item 58). It used to be
    // null here, which is what made a finished run unreachable.
    const pointer = await page.evaluate(() => {
      for (let i = 0; i < window.localStorage.length; i += 1) {
        const key = window.localStorage.key(i)
        if (key?.endsWith('validator-active-run')) return window.localStorage.getItem(key)
      }
      return null
    })
    expect(pointer, 'the run pointer was dropped at the terminal frame').not.toBeNull()
    const stored = JSON.parse(pointer as string) as { workflowId: string; inputField: string }
    expect(stored.inputField).toBe(TEMPLATE.field)

    // Throw away the ONE record the old code read its identity from, and
    // reload. This is the test panel's state, the Run switch's state and a
    // fresh tab's state, all at once.
    await page.evaluate(() => window.sessionStorage.clear())
    await page.reload()
    await expect(crumb(page)).toHaveText(TEMPLATE.title, { timeout: 30_000 })

    expect(await identityOf(page)).toEqual({
      kicker: 'RUN — YOUR WORKFLOW',
      heading: TEMPLATE.title,
      crumb: TEMPLATE.title,
      well: TEMPLATE.title,
      inputLabel: TEMPLATE.inputLabel,
      title: `${TEMPLATE.title} · Crew Studio`,
    })
    // R2: the box holds what the run was launched with, read by the graph's own
    // key. It used to hold the hardcoded Figma default, with Relaunch on it.
    await expect(page.locator('textarea#idea')).toHaveValue(IDEA)
    // R4: and the run itself came back, not just its labels.
    await expect(page.locator('.status-panel .run-id')).not.toBeEmpty()
    await page.screenshot({ path: 'test-results/R1-restored.png' })
  })

  /**
   * R3's refusal arm. A run resolves a REGISTERED version, so an unpublished
   * document has nothing to carry and navigating would land on a console that
   * answers 404 for this graph. The switch says so in the control, not only in
   * a tooltip, and the tooltip names the button that lifts it.
   */
  test('refuses to carry an unpublished workflow, and says how to fix it', async ({ page }) => {
    test.setTimeout(120_000)
    await saveTemplate(page)

    const run = runSwitch(page)
    await expect(run).toHaveAttribute('data-run-state', 'blocked')
    await expect(run).toHaveAccessibleName(/^Publish to run$/)
    await expect(run).toBeDisabled()
    await expect(run).toHaveAttribute('title', /Publish button/)
    await page.screenshot({ path: 'test-results/R3-unpublished.png' })

    // The gallery keeps the plain navigation: there is no workflow open to
    // carry, and the console's own built-in is a legitimate destination.
    await page.goto('/#/build')
    await page.reload()
    // The ACCESSIBLE name, not `textContent`: the control carries both labels
    // so its width cannot change (D-15-14), and the spare one is
    // `visibility: hidden` - out of the accessibility tree, still in the text.
    await expect(runSwitch(page)).toHaveAttribute('data-run-state', 'ready')
    await expect(runSwitch(page)).toHaveAccessibleName(/^Run$/)
    await expect(runSwitch(page)).toBeEnabled()
  })

  /**
   * R3's Build-back arm. The console's Build half used to emit no payload, so
   * `App.vue` sent it to the gallery - the mode switch of one workflow losing
   * the workflow on the way back.
   */
  test('sends Build back to the workflow it is running', { tag: '@launch' }, async ({ page }) => {
    test.setTimeout(240_000)
    const id = await saveTemplate(page)
    await publishOpenDocument(page)
    await page.getByRole('button', { name: 'Run it' }).click()
    await expect(page.locator('.handoff-banner')).toBeVisible({ timeout: 20_000 })

    await page.locator('.workspace-switch').getByRole('button', { name: 'Build' }).click()
    await expect.poll(() => new URL(page.url()).hash).toBe(`#/build/${id}`)
    await expect(page.locator('.breadcrumb-name')).toHaveText(TEMPLATE.title, { timeout: 30_000 })
  })

  /** And the built-in workflow keeps every one of its own words. */
  test('leaves the built-in validator saying exactly what it always said', async ({ page }) => {
    await page.goto('/#/run')
    await expect(page.locator('.workflow-node').first()).toBeVisible({ timeout: 30_000 })
    expect(await identityOf(page)).toEqual({
      kicker: 'RUN — BUILT IN',
      heading: 'Evidence pipeline',
      crumb: 'Idea Validator',
      well: 'Idea Validator',
      inputLabel: 'IDEA TO VALIDATE',
      title: 'Idea Validator · Crew Studio',
    })
    // Build from the built-in goes to the gallery: it has no document behind it.
    await page.locator('.workspace-switch').getByRole('button', { name: 'Build' }).click()
    await expect.poll(() => new URL(page.url()).hash).toBe('#/build')
  })
})

/**
 * R4's other half: the home offers the finished run rather than imposing it.
 *
 * D2 already built the card; what it could never show is a run, because the
 * pointer was dropped before the reader could reach the home. This is the
 * journey the card exists for - finish a run, go home, click Open it.
 */
test.describe('the home reopens the last run', () => {
  test.describe.configure({ mode: 'serial' })

  test('offers a finished run and restores it on the console', { tag: '@launch' }, async ({
    page,
  }) => {
    test.setTimeout(240_000)
    await page.goto('/#/run')
    await expect(page.locator('.workflow-node').first()).toBeVisible({ timeout: 30_000 })
    const review = page.getByRole('button', { name: 'Review', exact: true })
    if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
    await page.locator('textarea#idea').fill('A rota planner for community pharmacy locums')
    await page.locator('.status-panel .control-actions button.button-primary').click()

    // Answer both gates so the run really ends.
    for (const gate of ['Confirm scope', 'Review verdict']) {
      const card = page.locator('.gate-card')
      await expect(card.locator('h2')).toHaveText(gate, { timeout: 120_000 })
      await card.getByRole('button', { name: /^Approve/ }).click()
    }
    await expect
      .poll(async () => page.locator('.canvas-meta span').first().textContent(), {
        timeout: 120_000,
      })
      .toMatch(/Finished|Failed/i)
    const runId = (await page.locator('.status-panel .run-id').textContent())?.trim()

    // The home, which must NOT hand straight back over - a terminal pointer is
    // history and gets a card (D2).
    await page.goto('/#/')
    await page.reload()
    const card = page.locator('.home-last-run')
    await expect(card, 'the home showed no Last run card').toBeVisible({ timeout: 30_000 })
    await expect.poll(() => new URL(page.url()).hash).toBe('#/')
    await page.screenshot({ path: 'test-results/R4-home-last-run.png' })

    await card.getByRole('button', { name: 'Open it' }).click()
    await expect.poll(() => new URL(page.url()).hash).toBe('#/run')
    await expect(page.locator('.status-panel .run-id')).toHaveText(runId as string, {
      timeout: 30_000,
    })
    // Restored, not merely navigated to: the report is what the reader came
    // back for, and it is the thing the dropped pointer used to destroy.
    await expect(page.locator('.report-panel')).toBeVisible({ timeout: 30_000 })
    await page.screenshot({ path: 'test-results/R4-restored.png' })
  })
})
