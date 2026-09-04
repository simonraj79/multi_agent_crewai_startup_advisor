import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

/**
 * The docked test panel, in a real browser - 13 criterion 9.
 *
 * WHAT ONLY A BROWSER CAN ANSWER HERE, and it is the whole reason this file
 * exists beside `frontend/tests/testPanel.spec.ts`. That suite mounts the panel
 * in jsdom and asserts what goes on the wire; it cannot see whether the panel
 * took height from the canvas, whether the run states reached the cards, or
 * whether a result body ever appeared on screen. "A jsdom mount asserts
 * structure and never asks how wide anything ended up" is this repository's own
 * most expensive lesson - two layout defects reached a 988-green suite that way
 * - and the four tests below are the three questions that lesson names.
 *
 * ## Which backend
 *
 * The free one. `playwright.config.ts` starts `e2e/vite.e2e.config.ts`, which
 * proxies `/api` at `E2E_API_TARGET` and stubs the Better Auth origin with a
 * signed-in session:
 *
 *   SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8096 serve.exe
 *
 * `SYNTHETIC=1` replaces the crew factories and NOTHING else, so the compiled
 * definition, the gates, the frames and the persistence are the production
 * ones. Free, and still a real proof of every part of the panel except what a
 * model would have written.
 *
 * @launch - these press Run. Excluded with `--grep-invert @launch` against any
 * origin that spends money.
 */

const ALLOWED_CONSOLE_ERROR: RegExp | null = null

interface ConsoleWatch {
  unexpected: string[]
}

function watchConsole(page: Page): ConsoleWatch {
  const watch: ConsoleWatch = { unexpected: [] }
  const record = (text: string) => {
    if (ALLOWED_CONSOLE_ERROR?.test(text)) return
    watch.unexpected.push(text)
  }
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text())
  })
  page.on('pageerror', (error) => record(`uncaught: ${error.message}`))
  return watch
}

const card = (page: Page, title: string): Locator =>
  page.locator('.template-card').filter({ hasText: title })
const nodes = (page: Page): Locator => page.locator('.vue-flow__node:has(.workflow-node)')
const canvasFrame = (page: Page): Locator => page.locator('.builder-canvas')
const panel = (page: Page): Locator => page.locator('[data-testid="test-panel"]')
const saveChip = (page: Page): Locator => page.locator('[data-testid="save-chip"]')
const headline = (page: Page): Locator => page.locator('[data-testid="problems-headline"]')

async function validationSettles(page: Page): Promise<void> {
  await expect(page.locator('[data-testid="problems-checking"]')).toHaveCount(0, {
    timeout: 20_000,
  })
}

async function documentIdFromRoute(page: Page): Promise<string> {
  await expect
    .poll(() => new URL(page.url()).hash, { timeout: 20_000 })
    .toMatch(/#\/build\/ug_[0-9a-f]{8}$/)
  return /ug_[0-9a-f]{8}/.exec(new URL(page.url()).hash)![0]
}

async function clearLibrary(request: APIRequestContext): Promise<void> {
  const listed = await request.get('/api/builder/workflows')
  if (!listed.ok()) return
  const documents = (await listed.json()) as { id: string; status?: string }[]
  for (const entry of documents) {
    // A PUBLISHED document is refused (decision 24), so unpublish first. The
    // refusal is the right one and this is the cleanup that respects it.
    await request.post(`/api/builder/workflows/${entry.id}/unpublish`)
    await request.delete(`/api/builder/workflows/${entry.id}`)
  }
}

/**
 * Open the sequential pipeline, save it and publish it.
 *
 * Publishing is a PRECONDITION of the panel's three run modes and not an
 * incidental step: C7 as built resolves `mode` - `dry_run` included - against
 * `BUILDER_WORKFLOWS`, and only a publish writes that map. The panel says so on
 * screen, and the first test below asserts that it does.
 */
async function openAndPublish(page: Page): Promise<string> {
  await page.goto('/#/build')
  await expect(card(page, 'Sequential pipeline')).toBeVisible()
  await card(page, 'Sequential pipeline').click()
  await expect(nodes(page)).toHaveCount(7)
  await validationSettles(page)
  await expect(headline(page)).toContainText(/ready to publish/i)

  await page.keyboard.press('Control+s')
  await expect(saveChip(page)).toContainText(/saved/i)
  const id = await documentIdFromRoute(page)

  await page.keyboard.press('Control+Shift+P')
  const publish = page.locator('[aria-labelledby="publish-title"]')
  await expect(publish).toBeVisible()
  await publish.getByRole('button', { name: /^(Publish|Republish)$/ }).click()
  await expect(publish).toContainText(/anyone with the link can launch it/i)
  // The dialog's own Close, not Escape: Escape is handled inside the dialog and
  // depends on where focus went after the publish resolved, which is one more
  // thing for a test to be flaky about.
  await publish.getByRole('button', { name: 'Close' }).click()
  await expect(publish).toHaveCount(0)
  return id
}

/** Open the panel on one tab, the way an author does: by pressing it. */
async function openTab(page: Page, tab: string): Promise<void> {
  await page.locator(`[data-testid="test-tab-${tab}"]`).click()
  await expect(panel(page)).toHaveAttribute('data-open', 'true')
}

test.describe('The docked test panel', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test.afterEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test(
    'the Run tab completes a published graph and shows a result body inline',
    { tag: '@launch' },
    async ({ page }) => {
      test.setTimeout(240_000)
      const watch = watchConsole(page)
      await openAndPublish(page)

      // The panel starts collapsed to its tab strip - an author lands on a
      // canvas to draw, and a pane that opens itself takes 260px from the first
      // thing they came to do.
      await expect(panel(page)).toHaveAttribute('data-open', 'false')
      const canvasBefore = (await canvasFrame(page).boundingBox())!.height

      await openTab(page, 'run')

      // It took height from the CANVAS rather than covering it (R15, D1). This
      // is the assertion no unit test can make: a jsdom mount reports whatever
      // it is told, and an overlay and a grid row look identical to it.
      await expect
        .poll(async () => (await canvasFrame(page).boundingBox())!.height, { timeout: 10_000 })
        .toBeLessThan(canvasBefore)

      // Seeded from the template's committed sample, so there is nothing to
      // configure (criterion 11).
      const value = page.locator('[data-testid="test-input-value"]')
      await expect(value).not.toHaveValue('')

      await page.locator('[data-testid="test-run"]').click()

      // The canvas hands over to run tenancy with one attribute, and the
      // `[data-mode='run']` block in `builder.css` - dormant since §5.1 - is
      // what draws the cards from here on.
      await expect(canvasFrame(page)).toHaveAttribute('data-mode', 'run', { timeout: 30_000 })

      // This template gates above its first billable node, which is what makes
      // it launchable by somebody who is not signed in. The panel offers the
      // forward answer.
      const gate = page.locator('[data-testid="test-gate-approve"]')
      await expect(gate).toBeVisible({ timeout: 60_000 })
      await gate.click()

      const result = page.locator('[data-testid="test-run-result"]')
      await expect(result).toBeVisible({ timeout: 180_000 })
      await expect(result).not.toBeEmpty()
      await expect(page.locator('[data-testid="test-run-status"]')).toHaveText(/completed/i)

      // At least one card finished, drawn by the run tenancy rather than by its
      // kind. `.is-completed` is `BuilderNode`'s own class and the selector the
      // stylesheet keys on.
      await expect(page.locator('.builder-node.is-completed').first()).toBeVisible()

      expect(watch.unexpected).toEqual([])
    },
  )

  test(
    'the Node tab names the mocks it has not got, and runs one node once it has',
    { tag: '@launch' },
    async ({ page, request }) => {
      test.setTimeout(240_000)
      const watch = watchConsole(page)
      const id = await openAndPublish(page)

      await openTab(page, 'node')

      // Only flow-kind nodes are offered: an attachment has no output, so there
      // is nothing to replay and nothing to render.
      const select = page.locator('[data-testid="test-node-select"]')
      const options = await select.locator('option').allInnerTexts()
      expect(options.some((option) => option.includes('· tool'))).toBe(false)
      expect(options.some((option) => option.includes('· agent'))).toBe(true)

      // The LAST agent has ancestors, so it needs mocks and has none.
      const agents = options.filter((option) => option.includes('· agent'))
      await select.selectOption({ label: agents[agents.length - 1] })

      // Refused before a run row exists, naming the keys (D4). The server's 422
      // says the same thing and is the refusal that binds; this one costs no
      // request.
      const missing = page.locator('[data-testid="test-node-missing"]')
      await expect(missing).toBeVisible()
      await expect(missing).toContainText('out__')
      await expect(page.locator('[data-testid="test-node-run"]')).toBeDisabled()

      // Give it mocks the way D3 says is cheapest. Through `request`, because
      // "run once, then save its outputs" is the Run tab's journey and this
      // test is about the Node tab.
      const document = (await (await request.get(`/api/builder/workflows/${id}`)).json()) as {
        document: { input_field: string; nodes: { id: string; kind: string; label: string }[] }
      }
      const flowNodes = document.document.nodes.filter(
        (node) => !['tool', 'mcp', 'skill'].includes(node.kind),
      )
      const mocks = Object.fromEntries(
        flowNodes.map((node) => [node.id, 'a mocked upstream answer']),
      )
      const saved = await request.post(`/api/builder/workflows/${id}/test-inputs`, {
        data: {
          label: 'every node mocked',
          inputs: { [document.document.input_field]: 'clinic scheduling software' },
          node_mocks: mocks,
        },
      })
      expect(saved.status(), 'the saved test input was refused').toBe(201)

      // Reload so the panel reads the row, then choose it.
      await page.reload()
      await expect(nodes(page)).toHaveCount(7)
      await openTab(page, 'node')
      await page.locator('[data-testid="test-input-select"]').selectOption({
        label: 'every node mocked',
      })

      /*
       * THE NODE UNDER TEST IS THE GATE, and that is a limitation of the
       * derived plan rather than a preference. Measured against this backend on
       * 2026-09-04: a `node_test` on ANY node downstream of a gate fails before
       * a frame is emitted -
       *
       *   n3_research listens for 'e2_approve', which no method emits and no
       *   method is called. A trigger nothing produces is a node that never runs
       *
       * - because a gate compiles to TWO methods (the pause and its paired
       * router), and replacing the gate node with `runtime:replay_output`
       * removes the router that emits `<edge>_approve`. Every one of these four
       * templates gates above its first billable node, so the gate is the one
       * node here whose ancestors carry none. Recorded against 09 D7 and 10 D5;
       * not worked around, because the compiler is not this plan's to change.
       */
      const gate = flowNodes.find((node) => node.kind === 'gate')!
      await select.selectOption({ value: gate.id })
      await expect(missing).toHaveCount(0)

      await page.locator('[data-testid="test-node-run"]').click()
      // The panel's own refusal is quoted into the failure: a node test that is
      // refused says why, and a poll reporting only "error" would send the next
      // reader to the wrong layer.
      await expect
        .poll(
          async () => {
            const problem = page.locator('[data-testid="test-panel-problem"]')
            const detail = (await problem.count()) ? await problem.innerText() : ''
            const status = await page.locator('[data-testid="test-node-status"]').innerText()
            return `${status}${detail ? ` — ${detail}` : ''}`
          },
          { timeout: 90_000 },
        )
        .toMatch(/^(waiting|completed)/i)

      /*
       * ONE node ran, and the canvas says which. This is the assertion the
       * criterion asks for and the one no unit test can make.
       *
       * Stated as "the gate moved and every DESCENDANT is still idle" rather
       * than as a count of one, because the replayed ancestor moves too: an
       * ancestor compiled to `runtime:replay_output` announces itself with a
       * frame carrying `replayed: true` (C6), which is the honest thing for it
       * to do and would make a count of one an assertion about the wrong
       * property. What `node_test` promises is that nothing BELOW the node runs.
       */
      await expect(
        page.locator(`.vue-flow__node[data-id="${gate.id}"] .builder-node`),
      ).not.toHaveClass(/is-idle/)
      for (const node of flowNodes.filter((entry) => ['agent', 'output'].includes(entry.kind))) {
        await expect(
          page.locator(`.vue-flow__node[data-id="${node.id}"] .builder-node`),
          `${node.id} ran, and a single-node test must not reach it`,
        ).toHaveClass(/is-idle/)
      }

      // Every log group the tab draws is that node's - the tab filters, so a
      // frame from anywhere else would be a frame this run should not have had.
      const groups = page.locator('[data-testid="test-body-node"] [data-testid="run-log-group"]')
      for (const group of await groups.all()) {
        await expect(group).toHaveAttribute('data-node', gate.id)
      }

      expect(watch.unexpected).toEqual([])
    },
  )

  test('the Dry-run tab prices the graph and creates no run at all', async ({ page, request }) => {
    /*
     * DELIBERATELY NOT `@launch`. That is the whole claim: a dry run parses,
     * bounds, prices and compiles with no kickoff, no run row, no admission
     * slot and no rate-limit charge (D5, 10 D8). If this test could create a
     * run it would need the tag, and the run-history assertion below is what
     * makes the absence of the tag checkable rather than asserted.
     */
    const watch = watchConsole(page)
    await openAndPublish(page)

    const before = ((await (await request.get('/api/runs')).json()) as { runs?: unknown[] }).runs
    const beforeCount = (before ?? []).length

    await openTab(page, 'dry')
    await page.locator('[data-testid="test-dry-run"]').click()

    await expect(page.locator('[data-testid="test-dry-free"]')).toContainText(
      'no tokens were spent',
    )
    // BOTH figures. The floor is what a real run's total is comparable with;
    // the enforced one carries the nitro margin and deliberately is not.
    await expect(page.locator('[data-testid="test-dry-floor"]')).toContainText('$')
    await expect(page.locator('[data-testid="test-dry-static"]')).toContainText('$')
    await expect(page.locator('[data-testid="test-dry-calls"]')).not.toBeEmpty()
    await expect(page.locator('[data-testid="test-dry-plan"]')).toContainText('n0_')

    const after = ((await (await request.get('/api/runs')).json()) as { runs?: unknown[] }).runs
    expect((after ?? []).length, 'a dry run appeared in the run history').toBe(beforeCount)

    expect(watch.unexpected).toEqual([])
  })

  test('the Code tab shows what a DRAFT compiled to, without publishing it', async ({ page }) => {
    /*
     * The one tab an unpublished document can use, and the reason the panel is
     * still worth opening before a publish: `compiled` reads the document
     * store, where the three run modes read `BUILDER_WORKFLOWS`.
     */
    const watch = watchConsole(page)
    await page.goto('/#/build')
    await card(page, 'Sequential pipeline').click()
    await expect(nodes(page)).toHaveCount(7)
    await page.keyboard.press('Control+s')
    await expect(saveChip(page)).toContainText(/saved/i)

    await openTab(page, 'code')

    const yaml = page.locator('[data-testid="code-yaml"]')
    await expect(yaml).toBeVisible({ timeout: 20_000 })
    // The literal declaration `Flow.from_declaration` is handed.
    await expect(yaml).toContainText('crewai.flow/v1')
    await expect(page.locator('[data-testid="code-python"]')).toContainText('from crewai import')

    // Run is refused, and the sentence names the button that fixes it.
    await openTab(page, 'run')
    await expect(page.locator('[data-testid="test-run-blocked"]')).toContainText(/publish/i)
    await expect(page.locator('[data-testid="test-run"]')).toBeDisabled()

    expect(watch.unexpected).toEqual([])
  })
})
