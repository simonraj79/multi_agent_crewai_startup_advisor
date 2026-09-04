import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

/**
 * The four-minute journey, timed - 13 criterion 10 and D7.
 *
 * The gauntlet's "done means" sentence, expressed as the only thing that can
 * check it: a stopwatch around a person's whole first session. Sign in, open a
 * template, change the model on one agent, drop a tool onto another, open the
 * test panel, run it, watch the canvas, read a result. Seven steps, one wall
 * clock, and an assertion that the whole thing fits inside **240 seconds**.
 *
 * ## Why `performance.now()` and not `page.clock`
 *
 * D7 says so, and the reason is that a virtual clock would measure the test's
 * own patience rather than the product's speed. `page.clock` lets a test skip
 * the waiting; what this test is FOR is the waiting.
 *
 * ## What the number does and does not prove
 *
 * `SYNTHETIC_BRANCH_DELAY_SECONDS=5` and the synthetic crew factories mean the
 * MODEL is not in this measurement. What is in it is every part a person waits
 * on that is ours: the route, the gallery, the store, the validation loop, the
 * publish contract, the compiler, the registry, the socket and the render. A
 * paid journey would be this plus whatever the models take, and 240 s is the
 * gauntlet's budget for the whole thing rather than for this half - so a pass
 * here is necessary and not sufficient, and the plan's Status says so.
 *
 * ## Zero console errors
 *
 * `ALLOWED_CONSOLE_ERROR` is null and stays null, the rule `studio.spec.ts`
 * set when it retired its last exemption.
 *
 * @launch - this presses Run. Excluded with `--grep-invert @launch` against any
 * origin that spends money.
 */

const ALLOWED_CONSOLE_ERROR: RegExp | null = null

/** D7 and the gauntlet's own sentence. Milliseconds, so the failure reads in them. */
const JOURNEY_BUDGET_MS = 240_000

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
const saveChip = (page: Page): Locator => page.locator('[data-testid="save-chip"]')
const headline = (page: Page): Locator => page.locator('[data-testid="problems-headline"]')

/** Every tool node's id, in render order. */
async function toolIds(page: Page): Promise<string[]> {
  const ids = await page
    .locator('.vue-flow__node:has(.workflow-node.is-kind-tool)')
    .evaluateAll((list) => (list as HTMLElement[]).map((node) => node.dataset.id ?? ''))
  return ids.filter(Boolean)
}

async function validationSettles(page: Page): Promise<void> {
  await expect(page.locator('[data-testid="problems-checking"]')).toHaveCount(0, {
    timeout: 30_000,
  })
}

async function clearLibrary(request: APIRequestContext): Promise<void> {
  const listed = await request.get('/api/builder/workflows')
  if (!listed.ok()) return
  for (const entry of (await listed.json()) as { id: string }[]) {
    await request.post(`/api/builder/workflows/${entry.id}/unpublish`)
    await request.delete(`/api/builder/workflows/${entry.id}`)
  }
}

test.describe('The four-minute journey', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test.afterEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test(
    'a cold sign-in reaches a visible result in under four minutes',
    { tag: '@launch' },
    async ({ page, request }) => {
      // The ceiling is the assertion's own budget plus room to REPORT a failure:
      // a journey that overruns must fail as an overrun with a number, not as a
      // Playwright timeout with none.
      test.setTimeout(JOURNEY_BUDGET_MS + 60_000)
      const watch = watchConsole(page)

      const started = await page.evaluate(() => performance.now())

      // 1. Signed in. `vite.e2e.config.ts` stubs the auth origin as the E2E
      //    Operator, which is what a cold sign-in reaches; the header chip is
      //    the page's own proof it happened rather than this file's assumption.
      await page.goto('/#/build')
      await expect(page.locator('[data-testid="account-chip"]')).toBeVisible()

      // 2. One click to a graph.
      await expect(card(page, 'Sequential pipeline')).toBeVisible()
      await card(page, 'Sequential pipeline').click()
      await expect(nodes(page)).toHaveCount(7)
      await validationSettles(page)
      await expect(headline(page)).toContainText(/ready to publish/i)

      // 3. Change the writer's model in the inspector. This is the edit the
      //    template's own card tells a first-time author to make first, and it
      //    is the one that proves the inspector reaches the document.
      const writer = page.locator('.vue-flow__node[data-id="write"] .builder-node')
      await writer.click()
      const rail = page.locator('[data-testid="inspector-rail"]')
      await expect(rail).toBeVisible()
      const model = rail.locator('select').filter({ hasText: /gemini|flash/i }).first()
      const before = await model.inputValue()
      const options = await model.locator('option').evaluateAll((list) =>
        (list as HTMLOptionElement[]).map((option) => option.value).filter(Boolean),
      )
      const swapped = options.find((option) => option !== before)
      expect(swapped, 'the registry offered only one model, so nothing could be swapped').toBeTruthy()
      await model.selectOption(swapped!)
      await expect(model).toHaveValue(swapped!)

      // 4. Drop a tool onto the researcher, and wire it. `t` is the palette's
      //    letter for a tool (decision 18: digits already select flow kinds).
      const edgesBefore = await page.locator('.vue-flow__edge').count()
      const toolsBefore = await toolIds(page)

      /*
       * A KEYLESS tool, read off the served catalogue rather than named here.
       *
       * `credential_kind` is the catalogue's own answer to "does this need the
       * author's key", and a tool that does raises `tool-credential-required` -
       * a correct refusal about a graph this journey has no credential for.
       * Measured: choosing a Firecrawl tool raised it and Publish stayed
       * disabled. This journey is about somebody with nothing configured, so the
       * tool has to be one such a person can use.
       */
      const keyless = (
        (await (await request.get('/api/builder/vocabulary')).json()) as {
          tools: { tool_id: string; label: string; credential_kind: string | null }[]
        }
      ).tools.find((tool) => tool.credential_kind === null)
      expect(keyless, 'the catalogue offers no keyless tool').toBeTruthy()

      /*
       * DRAGGED FROM THE PALETTE'S TOOL DRAWER ONTO THE CARD, which is the
       * product's own gesture for this (`NodePalette` D7 + `dropKind`'s
       * attach-by-drop, D8): one drag gives a NAMED tool and its `attach` edge
       * in a single commit.
       *
       * Two other routes were tried first and neither works, which is worth
       * recording because both look like they should:
       *
       * - the palette HOTKEY (`t`) drops at the VIEWPORT CENTRE
       *   (`BuilderView.placeKind` → `canvas.viewportCentre()`), so it never
       *   hit-tests a card and the tool lands unattached wherever the middle is.
       * - dragging the tool's `attach` PORT onto the agent's `attach` port
       *   paints the handle green and then writes `target_port: 'in'`, because
       *   `useBuilderDocument.addEdge` hardcodes it - a comment there still says
       *   "there is no other", which was true before the attachment ports
       *   existed. The server then refuses the saved document with
       *   `attach-target-not-agent`. Measured on this backend, twice.
       *
       * Both are outside this plan's files and are reported as follow-ups.
       */
      await page.getByRole('button', { name: /named tools?$/ }).click()
      const toolRow = page.locator(`[data-testid="tool-row"][data-tool-id="${keyless!.tool_id}"]`)
      await expect(toolRow).toBeVisible()
      await toolRow.dragTo(page.locator('.vue-flow__node[data-id="research"] .builder-node'))

      await expect(nodes(page)).toHaveCount(8)
      await expect(page.locator('.vue-flow__edge')).toHaveCount(edgesBefore + 1)
      // The NEW tool, by difference. This template already ships one attached to
      // the researcher, so `.last()` would be a coin toss between the two.
      const placed = (await toolIds(page)).find((id) => !toolsBefore.includes(id))
      expect(placed, 'the drag placed no tool').toBeTruthy()

      /*
       * NAME the tool in the inspector, which the drag should not have needed.
       *
       * `NodePalette` sets `BUILDER_TOOL_ID_MIME` on a tool row's `dragstart`
       * (D7's whole point: reach a NAMED tool in one gesture) and
       * `BuilderCanvas.onDrop` reads only `BUILDER_DND_MIME` - so the id is put
       * on the wire and thrown away, and the drop lands the default
       * `tool_id: 'tool'`. Measured here as a single `tool-unknown` blocking
       * Publish. Outside this plan's files; reported as a follow-up, and this
       * step is what a person would do next anyway.
       */
      await page.locator(`.vue-flow__node[data-id="${placed}"] .builder-node`).click()
      // `insp-<node id>-tool_id` - `ToolForm.vue`'s own `control()`, so this
      // names the one control rather than the first select in the rail.
      const toolSelect = page.locator(
        `[data-testid="inspector-rail"] select#insp-${placed}-tool_id`,
      )
      await expect(toolSelect).toBeVisible()
      await toolSelect.selectOption(keyless!.tool_id)

      await validationSettles(page)
      await expect(headline(page)).toContainText(/ready to publish/i)

      // 5. Save and publish. Publishing is what makes a graph runnable at all -
      //    C7 resolves every run mode against `BUILDER_WORKFLOWS`, which only a
      //    publish writes - so it is part of the journey rather than beside it.
      await page.keyboard.press('Control+s')
      await expect(saveChip(page)).toContainText(/saved/i)
      await page.keyboard.press('Control+Shift+P')
      const publish = page.locator('[aria-labelledby="publish-title"]')
      await expect(publish).toBeVisible()
      await publish.getByRole('button', { name: /^(Publish|Republish)$/ }).click()
      await expect(publish).toContainText(/anyone with the link can launch it/i)
      // The dialog's own Close, not Escape: Escape is handled inside the dialog
      // and depends on where focus went after the publish resolved, which is one
      // more thing for this test to be flaky about.
      await publish.getByRole('button', { name: 'Close' }).click()
      await expect(publish).toHaveCount(0)

      // 6. Open the panel and run, with the template's own committed sample. No
      //    configuration: the box already holds a prompt (criterion 11).
      await page.locator('[data-testid="test-tab-run"]').click()
      await expect(page.locator('[data-testid="test-panel"]')).toHaveAttribute('data-open', 'true')
      await expect(page.locator('[data-testid="test-input-value"]')).not.toHaveValue('')
      await page.locator('[data-testid="test-run"]').click()

      // 7. Watch it. The canvas hands over to run tenancy, the gate asks, the
      //    log fills, and a body appears.
      await expect(canvasFrame(page)).toHaveAttribute('data-mode', 'run', { timeout: 60_000 })
      const gate = page.locator('[data-testid="test-gate-approve"]')
      await expect(gate).toBeVisible({ timeout: 120_000 })
      await gate.click()

      await expect(page.locator('[data-testid="run-log-group"]').first()).toBeVisible({
        timeout: 120_000,
      })
      const result = page.locator('[data-testid="test-run-result"]')
      await expect(result).toBeVisible({ timeout: 180_000 })
      await expect(result).not.toBeEmpty()
      await expect(page.locator('.builder-node.is-completed').first()).toBeVisible()

      const elapsed = (await page.evaluate(() => performance.now())) - started
      // Recorded in the plan's Status as a measurement, not as a pass mark: the
      // budget is the gauntlet's and the number is this machine's.
      console.log(`journey: ${(elapsed / 1000).toFixed(1)}s of a ${JOURNEY_BUDGET_MS / 1000}s budget`)
      expect(
        elapsed,
        `the journey took ${(elapsed / 1000).toFixed(1)}s, over the ${JOURNEY_BUDGET_MS / 1000}s budget`,
      ).toBeLessThan(JOURNEY_BUDGET_MS)

      expect(watch.unexpected).toEqual([])
    },
  )
})
