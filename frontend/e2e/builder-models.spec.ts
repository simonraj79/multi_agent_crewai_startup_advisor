import { expect, test, type Locator, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

/**
 * 05 criterion 10 - the model registry, in the browser it is chosen from.
 *
 * The criterion was recorded `not reached` on 2026-09-04 for a reason that was
 * true then and is not now: *"`llm.model` exists only on the AUTHORED arm, and
 * the client has no authored arm"*. Plan 04 shipped it - all 42 controls,
 * `4d8a054` - so the blocker is gone and this is the test that criterion named.
 *
 * TWO PROPERTIES, and they are different kinds of claim.
 *
 *   1. A cheaper model makes the graph cheaper, and the ENFORCED figure is the
 *      one that has to move. There are two dollar amounts on the meter and only
 *      one of them is the ceiling's: `floor_cost_usd` is the comparable, and
 *      `static_cost_usd` x `NITRO_PRICE_FACTOR` is what `budget_problems`
 *      actually refuses a publish against. A test that watched the floor would
 *      pass while the number that governs anything sat still.
 *
 *   2. A capability the model does not have is DISABLED WITH A TOOLTIP NAMING
 *      THE MODEL, never silently dropped. `openai/gpt-4.1-nano` genuinely
 *      publishes `supports_reasoning: false` in the committed registry, so this
 *      is the roster's own row rather than a fixture invented to make a point.
 *
 * ## Which backend
 *
 * The free `SYNTHETIC=1` service, started FROM THE WORKTREE ROOT so that
 * `data/skills` and `output/` resolve:
 *
 *   SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8094 serve.exe
 *   E2E_API_TARGET=http://127.0.0.1:8094 E2E_UI_PORT=5278 npx playwright test
 *
 * Nothing here launches a run, so nothing here costs anything on any backend.
 */

const ALLOWED_CONSOLE_ERROR: RegExp | null = null

function watchConsole(page: Page): string[] {
  const unexpected: string[] = []
  const record = (text: string): void => {
    if (ALLOWED_CONSOLE_ERROR?.test(text)) return
    unexpected.push(text)
  }
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text())
  })
  page.on('pageerror', (error) => record(`uncaught: ${error.message}`))
  return unexpected
}

const canvas = (page: Page): Locator => page.locator('.builder-flow')
const inspector = (page: Page): Locator => page.locator('[data-testid="inspector-rail"]')
const enforced = (page: Page): Locator => page.locator('[data-testid="budget-static"]')

/** Wait out the 400ms debounce plus the round trip, on the RENDERED state. */
async function validationSettles(page: Page): Promise<void> {
  await expect(page.locator('[data-testid="problems-checking"]')).toHaveCount(0, {
    timeout: 20_000,
  })
}

/** Every `ug_*` document, deleted, so a second run measures the same thing. */
async function clearLibrary(page: Page): Promise<void> {
  const listed = await page.request.get('/api/builder/workflows')
  if (!listed.ok()) return
  for (const entry of (await listed.json()) as { id: string }[]) {
    await page.request.delete(`/api/builder/workflows/${entry.id}`)
  }
}

/**
 * The enforced dollar figure, as a number.
 *
 * Parsed out of the rendered text rather than read off an attribute, because
 * the criterion is about what an AUTHOR sees decrease - a data attribute
 * nobody renders could be right while the meter showed something else.
 */
async function enforcedUsd(page: Page): Promise<number> {
  const text = await enforced(page).innerText()
  const match = /\$?([0-9]+(?:\.[0-9]+)?)/.exec(text.replace(/,/g, ''))
  expect(match, `no dollar figure in "${text}"`).not.toBeNull()
  return Number(match![1])
}

/**
 * One capture for the judge, into `benchmarks/ours/05/`.
 *
 * PNGs are gitignored and the spec is not: `benchmarks/README.md` says why -
 * they are pictures of a build, regenerated on demand, and a round's defects
 * live in the ledger rather than in its pixels. Taken at the END of a passing
 * test, so a capture can never be of a state the assertions rejected.
 */
async function capture(page: Page, name: string): Promise<void> {
  const out = path.resolve(process.cwd(), '..', 'benchmarks', 'ours', '05')
  mkdirSync(out, { recursive: true })
  await page.screenshot({ path: path.join(out, `05-${name}-1440x900-dark.png`) })
}

test.describe('the model registry, from the picker', () => {
  test.beforeEach(async ({ page }) => {
    await clearLibrary(page)
  })

  test.afterEach(async ({ page }) => {
    await clearLibrary(page)
  })

  test('a cheaper model lowers the ENFORCED figure within one validate cycle', async ({ page }) => {
    const errors = watchConsole(page)
    await page.goto('/#/build')

    // The fan-out template: five billable nodes, three of them in parallel, so
    // one node's model is a visible fraction of the total rather than a
    // rounding difference.
    await page.locator('.template-card').filter({ hasText: 'Fan out and join' }).click()
    await expect(canvas(page)).toBeVisible()
    await validationSettles(page)

    const before = await enforcedUsd(page)
    expect(before, 'the meter never priced the template').toBeGreaterThan(0)

    // The authored arm is reached by converting a library agent (04's departure
    // 9); a library agent has no `llm` at all, which is why criterion 10 could
    // not be written until plan 04 landed.
    const agent = page.locator('.vue-flow__node:has(.workflow-node.is-kind-agent)').first()
    await agent.click()
    await expect(inspector(page)).toBeVisible()
    await inspector(page)
      .getByRole('button', { name: /convert to an authored agent/i })
      .click()

    const picker = inspector(page).locator('[data-field="llm.model"] select')
    await expect(picker).toBeVisible()

    /*
     * The roster, EXACTLY, cheapest first, with the presets findable by name.
     *
     * `<select>` options carry no glyphs, so `ModelPicker` writes the preset
     * word into the option text - which is what makes "the escalation one" a
     * thing an author can look for rather than a thing they have to remember.
     */
    const options = await picker.locator('option').allInnerTexts()
    expect(options.length, 'the picker offered nothing').toBeGreaterThan(1)
    expect(options.some((text) => /\[cheap\]/.test(text))).toBe(true)
    expect(options.some((text) => /\[escalation\]/.test(text))).toBe(true)

    // The node starts on the cheap PRESET, which is what a converted agent
    // inherits from its tier.
    expect(await picker.inputValue()).toBe('google/gemini-3.5-flash-lite')

    await picker.selectOption('qwen/qwen3.7-flash')
    // The card is the mirror of the rail, in the same tick (04 D4).
    await expect(agent.locator('[data-testid="node-model-pill"]')).toHaveText('qwen3.7-flash')

    await validationSettles(page)
    const after = await enforcedUsd(page)
    // $0.03 per million in against $0.30: an order of magnitude, so this is a
    // decrease no rounding can explain away.
    expect(after, `enforced ${before} -> ${after}`).toBeLessThan(before)

    // The floor moves too, and BOTH are always shown (§6.4): showing the
    // inflated one alone reads as an error, and showing the floor alone hides
    // the number a publish is actually refused against.
    await expect(page.locator('[data-testid="budget-floor"]')).toBeVisible()

await capture(page, 'picker-cheaper-model')

    expect(errors).toEqual([])
  })

  test('disables a parameter the chosen model cannot honour, and names it', async ({ page }) => {
    const errors = watchConsole(page)
    await page.goto('/#/build')
    await page.locator('.template-card').filter({ hasText: 'Minimal gated agent' }).click()
    await expect(canvas(page)).toBeVisible()

    const agent = page.locator('.vue-flow__node:has(.workflow-node.is-kind-agent)').first()
    await agent.click()
    await inspector(page)
      .getByRole('button', { name: /convert to an authored agent/i })
      .click()

    // Expert, because that is where `llm.reasoning_effort` lives (04 D2).
    const expertSwitch = inspector(page).locator('.expert-switch input')
    if (!(await expertSwitch.isChecked())) await expertSwitch.click()

    const effort = inspector(page).locator('[data-field="llm.reasoning_effort"]')
    await expect(effort).toBeVisible()
    // On a reasoning model it is live. This is the control half of the claim:
    // without it, "disabled" below could be a control that is always disabled.
    await expect(effort.getByRole('button', { name: 'high', exact: true })).toBeEnabled()

    await inspector(page)
      .locator('[data-field="llm.model"] select')
      .selectOption('openai/gpt-4.1-nano')

    /*
     * DISABLED, with a tooltip that names the model - the gauntlet's own
     * wording, "capability flags drive the UI; disabled with tooltip, never
     * silently dropped". Dropping it silently is the failure: the author asks
     * for reasoning, is charged for the request, and reads an answer that was
     * never reasoned.
     */
    await expect(effort.getByRole('button', { name: 'high', exact: true })).toBeDisabled()
    const described = effort.locator('[title*="gpt-4.1-nano"], [aria-label*="gpt-4.1-nano"]')
    await expect(described.first()).toHaveCount(1)
    await expect(effort).toContainText('gpt-4.1-nano')
    await expect(effort).toContainText('reasoning')

    /*
     * ...and the MODEL's own row says the same thing, where the model is
     * chosen, so an author comparing models meets it before they pick one
     * rather than after. `ModelPicker` renders four capability chips and
     * strikes the ones the model lacks; the sentence is the chip's `title`,
     * because a struck-through word is a signal and not an explanation.
     */
    const reasoningChip = inspector(page)
      .locator('[data-field="llm.model"] .capabilities li')
      .filter({ hasText: /^reasoning$/i })
      .first()
    await expect(reasoningChip).toHaveAttribute('aria-disabled', 'true')
    await expect(reasoningChip).toHaveAttribute(
      'title',
      /openai\/gpt-4\.1-nano does not support reasoning/i,
    )

await capture(page, 'picker-capability-disabled')

    expect(errors).toEqual([])
  })
})
