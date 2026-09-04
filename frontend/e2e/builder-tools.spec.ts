import { expect, test, type Locator, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

/**
 * 06 criteria 9 and 10 - the tool catalogue, in the browser.
 *
 * Plan 06's Status recorded both as *"the browser half is not reached and is
 * not approximated"*. This is that half.
 *
 * ## Which backend, and why nothing here spends
 *
 * The free `SYNTHETIC=1` service, started FROM THE WORKTREE ROOT so the
 * credential vault and `data/skills` resolve:
 *
 *   SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8094 \
 *     CREDENTIALS_MASTER_KEY=... serve.exe
 *
 * Without `CREDENTIALS_MASTER_KEY` the credential path answers 503, which reads
 * like a broken feature rather than a missing key (MISSION.md §8). Nothing here
 * launches a run and no tool is ever executed - a tool NODE is a declaration,
 * and this file only ever writes one.
 *
 * ## Two departures from the criteria's own wording, both because the shipped
 * behaviour is a documented decision rather than a gap
 *
 * 1. **A tool dropped on a `transform` is NOT refused.** Criterion 9 asks for
 *    "nothing is created and the tooltip reads *tools attach to agents*".
 *    `dropKind` deliberately creates an UNATTACHED node instead, and says why:
 *    an author may be laying out before wiring, and `bounds.py` reporting
 *    `attachment-unattached` is a sentence they can read where a refused drop
 *    is silent. That reasoning is in the composable and in 03's contract
 *    request; it is a decision, so this file asserts the decision.
 *
 * 2. **The code is `tool-credential-required`, not `credential-missing`.** Both
 *    exist in the served union; the tool path emits the first (`tools.py`), and
 *    `credential-missing` belongs to the MCP and skill paths. Criterion 10's
 *    prose predates that split.
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
const nodes = (page: Page): Locator => page.locator('.vue-flow__node:has(.workflow-node)')
const edges = (page: Page): Locator => page.locator('.vue-flow__edge')
const inspector = (page: Page): Locator => page.locator('[data-testid="inspector-rail"]')
const problemRow = (page: Page, code: string): Locator =>
  page.locator(`[data-testid="problem-${code}"]`)
const paletteTile = (page: Page, hotkey: string): Locator =>
  page.locator(`.builder-tile[aria-keyshortcuts="${hotkey}"]`)

async function validationSettles(page: Page): Promise<void> {
  await expect(page.locator('[data-testid="problems-checking"]')).toHaveCount(0, {
    timeout: 20_000,
  })
}

async function clearLibrary(page: Page): Promise<void> {
  const listed = await page.request.get('/api/builder/workflows')
  if (!listed.ok()) return
  for (const entry of (await listed.json()) as { id: string }[]) {
    await page.request.delete(`/api/builder/workflows/${entry.id}`)
  }
}

/**
 * Every key this caller owns, deleted before and after.
 *
 * The vault is durable and per-user, so a key written by the last test in this
 * file is still there for the first test in the next run - and `CredentialPicker`
 * selects the only key of a kind by itself, which is the right behaviour and
 * makes "the amber chip appears" false for a reason nothing on screen explains.
 * It passed in isolation and failed in the full suite, which is the signature.
 */
async function clearCredentials(page: Page): Promise<void> {
  const listed = await page.request.get('/api/builder/credentials')
  if (!listed.ok()) return
  for (const entry of (await listed.json()) as { id: string }[]) {
    await page.request.delete(`/api/builder/credentials/${entry.id}`)
  }
}

/** Open the smallest launchable template: input -> gate -> agent -> output. */
async function startFromMinimalTemplate(page: Page): Promise<void> {
  await page.goto('/#/build')
  await page.locator('.template-card').filter({ hasText: 'Minimal gated agent' }).click()
  await expect(canvas(page)).toBeVisible()
  await expect(nodes(page)).toHaveCount(4)
}

const agentCard = (page: Page): Locator =>
  page.locator('.vue-flow__node:has(.workflow-node.is-kind-agent)').first()

/**
 * One capture for the judge, into `benchmarks/ours/06/`.
 *
 * PNGs are gitignored and the spec is not: `benchmarks/README.md` says why -
 * they are pictures of a build, regenerated on demand, and a round's defects
 * live in the ledger rather than in its pixels. Taken at the END of a passing
 * test, so a capture can never be of a state the assertions rejected.
 */
async function capture(page: Page, name: string): Promise<void> {
  const out = path.resolve(process.cwd(), '..', 'benchmarks', 'ours', '06')
  mkdirSync(out, { recursive: true })
  await page.screenshot({ path: path.join(out, `06-${name}-1440x900-dark.png`) })
}

test.describe('the tool catalogue, on the canvas', () => {
  test.beforeEach(async ({ page }) => {
    await clearLibrary(page)
    await clearCredentials(page)
  })

  test.afterEach(async ({ page }) => {
    await clearLibrary(page)
    await clearCredentials(page)
  })

  test('names every catalogue entry in a sub-list under the tool tile', async ({ page }) => {
    /*
     * Criterion 9's first half seen from the palette rather than from the drop.
     *
     * The sub-list is the only surface where a specific tool is a thing an
     * author can point at, and it renders `vocabulary.tools` verbatim - so this
     * also proves the CATALOGUE reached the browser, which is the half a unit
     * test with a hand-built double cannot establish.
     */
    const errors = watchConsole(page)
    await startFromMinimalTemplate(page)

    await page.locator('.builder-subtoggle').click()
    const rows = page.locator('[data-testid="tool-row"]')
    await expect(rows.first()).toBeVisible()

    const served = (await (await page.request.get('/api/builder/vocabulary')).json()) as {
      tools: { tool_id: string; label: string }[]
    }
    expect(served.tools.length, 'this build serves no catalogue').toBeGreaterThan(0)
    expect(await rows.evaluateAll((els) => els.map((el) => el.getAttribute('data-tool-id')))).toEqual(
      served.tools.map((entry) => entry.tool_id),
    )

    // Named by their LABEL, never their id: an author picked "Web search" from
    // a list and should see that word again.
    await expect(rows.filter({ hasText: 'Web search' })).toHaveCount(1)

await capture(page, 'catalogue-sublist')

    expect(errors).toEqual([])
  })

  test('attaches a tool to an agent and takes both away in one undo', async ({ page }) => {
    /*
     * Criterion 9's second half. One node and one edge from one gesture, the
     * chip on the agent card, and Ctrl+Z removing both - because two commits
     * would leave an author who changed their mind holding a pill they never
     * placed, hanging off nothing.
     */
    const errors = watchConsole(page)
    await startFromMinimalTemplate(page)
    await validationSettles(page)

    const agent = agentCard(page)
    const agentId = (await agent.getAttribute('data-id'))!
    const nodesBefore = await nodes(page).count()
    const edgesBefore = await edges(page).count()

    await paletteTile(page, 'T').dragTo(agent)

    await expect(nodes(page)).toHaveCount(nodesBefore + 1)
    await expect(edges(page)).toHaveCount(edgesBefore + 1)
    // The chip on the HOST - D6's avatar, which is the only place an agent
    // admits what it has in its hands without being opened.
    await expect(
      page.locator(`.vue-flow__node[data-id="${agentId}"] .builder-attach-avatar`),
    ).toHaveCount(1)

    await page.keyboard.press('Control+z')
    await expect(nodes(page)).toHaveCount(nodesBefore)
    await expect(edges(page)).toHaveCount(edgesBefore)

    expect(errors).toEqual([])
  })

  test('leaves a tool dropped on a transform unattached, and says so in the dock', async ({
    page,
  }) => {
    /*
     * The DEPARTURE, asserted rather than glossed. Criterion 9 asks for a
     * refusal and a tooltip; what shipped creates an unattached node and
     * reports `attachment-unattached`, because `dropKind` only attaches when
     * the drop point is inside an agent or a crew and a drop anywhere else is a
     * legal placement.
     *
     * The reasoning is the composable's own: an author may be laying out before
     * wiring, and a sentence in the dock is something they can act on where a
     * gesture that silently does nothing is not.
     */
    const errors = watchConsole(page)
    await startFromMinimalTemplate(page)
    await validationSettles(page)

    // A transform, placed away from everything so the drop cannot land on an
    // agent by accident.
    const pane = (await canvas(page).boundingBox())!
    await paletteTile(page, '6').dragTo(canvas(page), {
      targetPosition: { x: pane.width * 0.7, y: pane.height * 0.25 },
    })
    const transform = page.locator('.vue-flow__node:has(.workflow-node.is-kind-transform)').first()
    await expect(transform).toBeVisible()

    const edgesBefore = await edges(page).count()
    await paletteTile(page, 'T').dragTo(transform)

    // A node, and NO edge: `attach` is refused on a transform by
    // `TARGET_PORTS_BY_KIND`, which is why the drop could not have wired it.
    await expect(page.locator('.workflow-node.is-kind-tool')).toBeVisible()
    await expect(edges(page)).toHaveCount(edgesBefore)

    await validationSettles(page)
    await expect(problemRow(page, 'attachment-unattached')).toBeVisible()
    await expect(problemRow(page, 'attachment-unattached')).toContainText('attached to nothing')

    expect(errors).toEqual([])
  })

  test('shows the amber no-key chip and the dock row until a credential is chosen', async ({
    page,
  }) => {
    /*
     * Criterion 10, both ends of it: the CARD says a key is missing where an
     * author is looking, and the DOCK says it in a sentence anchored to the
     * node. Two surfaces, one fact, and they have to clear together - a chip
     * that stayed amber after the key was chosen would be worse than no chip.
     *
     * `firecrawl_search` is the criterion's own example and it genuinely
     * requires a `firecrawl` key: `credential_optional` is false on that row in
     * the served catalogue, which is what makes this an error rather than a
     * note.
     */
    const errors = watchConsole(page)
    await startFromMinimalTemplate(page)
    await validationSettles(page)

    await paletteTile(page, 'T').dragTo(agentCard(page))
    await expect(inspector(page)).toBeVisible()
    await inspector(page).locator('[data-field="tool_id"] select').selectOption('firecrawl_search')

    // The amber chip, on the tool's own card in the inspector.
    await expect(inspector(page).locator('[data-testid="tool-no-key"]')).toBeVisible()
    await expect(inspector(page).locator('[data-testid="tool-no-key"]')).toContainText(/no key/i)

    await validationSettles(page)
    const row = problemRow(page, 'tool-credential-required')
    await expect(row).toBeVisible()
    // The server's sentence names the tool AND the kind of key, because the
    // author's next action needs both.
    await expect(row).toContainText('firecrawl')

    /*
     * Create a key from inside the inspector. DOCKED, never a dialog (R15):
     * asserted here as an absence, because "no modal" is a property a
     * screenshot cannot show and a `role=dialog` count can.
     */
    await inspector(page).locator('[data-testid="credential-new"]').click()
    await expect(inspector(page).locator('[data-testid="credential-form"]')).toBeVisible()
    expect(await page.locator('[role="dialog"]').count(), 'a dialog opened').toBe(0)

    await inspector(page).locator('[data-testid="credential-label"]').fill('E2E firecrawl')
    const fields = inspector(page).locator('[data-testid^="credential-field-"]')
    const fieldCount = await fields.count()
    expect(fieldCount, 'the form asked for no field').toBeGreaterThan(0)
    for (let index = 0; index < fieldCount; index += 1) {
      await fields.nth(index).fill('fc-not-a-real-key')
    }
    await inspector(page).locator('[data-testid="credential-save"]').click()

    // Both surfaces clear, and they clear together.
    await expect(inspector(page).locator('[data-testid="tool-key"]')).toBeVisible()
    await expect(inspector(page).locator('[data-testid="tool-no-key"]')).toHaveCount(0)
    await validationSettles(page)
    await expect(problemRow(page, 'tool-credential-required')).toHaveCount(0)

await capture(page, 'no-key-chip-cleared')

    expect(errors).toEqual([])
  })
})

/*
 * Criterion 9's other end, CLOSED by the integration closer of 2026-09-04.
 *
 * `NodePalette.onToolDragStart` had always written BOTH mime entries -
 * `application/x-builder-kind` and `application/x-builder-tool-id`, pinned by
 * `frontend/tests/nodePalette.spec.ts` - and nothing read the second one.
 * `BuilderCanvas.onDrop` read only the kind, so a tool dragged out of the
 * sub-list landed on `nodeKinds`' placeholder `tool_id`, exactly as the generic
 * tile does: the two gestures are meant to be distinguishable - the tile is "a
 * tool node", the row is "that tool" - and they were not.
 *
 * `onDrop` now reads the second entry and hands it to `dropKind`, which
 * validates it against the SERVED catalogue before applying it (`asNamedTool`
 * in `useBuilderCanvas.ts`) - `dataTransfer` is a public channel, and a
 * `tool_id` the compiler has never heard of is a node that publishes and then
 * fails. The unit half is `frontend/tests/builderCanvas.spec.ts`, *"lands THAT
 * tool, not a placeholder"*; this is the half that needs a real drag.
 */
test('drags a NAMED tool out of the sub-list and lands that tool', async ({ page }) => {
  await startFromMinimalTemplate(page)
  await page.locator('.builder-subtoggle').click()
  await page
    .locator('[data-testid="tool-row"][data-tool-id="web_search"]')
    .dragTo(agentCard(page))

  await expect(page.locator('.workflow-node.is-kind-tool')).toContainText('Web search')
  await expect(
    page.locator('[data-testid="inspector-rail"] [data-field="tool_id"] select'),
  ).toHaveValue('web_search')
})
