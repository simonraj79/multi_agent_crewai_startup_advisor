import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

/**
 * Every pattern template, from a cold sign-in to a finished run.
 *
 * Plan 14 criterion 7, and the only test that can answer the question it asks.
 * A template validating in a unit suite proves the DOCUMENT is well formed; it
 * says nothing about whether somebody who has just signed in, configured
 * nothing and clicked one card ends up with a run that produces something.
 * That is four separate things - the gallery, the store, the publish contract
 * and the runtime - and only a browser against a real backend touches all four.
 *
 * ## What "zero configuration" means here, precisely
 *
 * The context has no credentials, no MCP server and no skill: nothing is
 * seeded and nothing is stubbed but the auth origin, which
 * `vite.e2e.config.ts` answers as a signed-in E2E Operator exactly as it does
 * for every other file. Each template's own document therefore has to reach a
 * completed run on the PLATFORM key alone, which is what D8 asks for and what
 * `web_search` would have made impossible - all four of its providers need the
 * author's own key.
 *
 * ## Why the launch and the gate go through `request` and not the UI
 *
 * The builder renders no Launch control - `StudioView` keeps the Run header
 * toggle and the builder never offers one - so a button here would be markup no
 * package owns. `builder.spec.ts` made the same call for the same reason. What
 * the UI drives is the half a person drives: open the card, save, publish.
 *
 * ## Cost
 *
 * `SYNTHETIC=1` replaces the crew factories and NOTHING ELSE, so the compiled
 * definition, the engine, the gates, the routers, the joins, the cycle and the
 * persistence are all the production ones. Free, and still a real proof of
 * every part of a template except what a model would have written.
 *
 * @launch - these press the button. Excluded with `--grep-invert @launch`
 * against a paid origin.
 */

const ALLOWED_CONSOLE_ERROR: RegExp | null = null

/**
 * The four patterns, and the shape each one is expected to reach.
 *
 * `gates` is how many pauses an approve-only operator answers, and it is stated
 * rather than discovered: a template that stopped gating would otherwise pass
 * this file silently, and a gate above the first billable node is the whole
 * reason these are launchable by somebody who is not signed in.
 */
const PATTERNS = [
  { id: 'sequential-pipeline', title: 'Sequential pipeline', nodes: 7, gates: 1 },
  { id: 'conditional-router', title: 'Conditional router', nodes: 10, gates: 1 },
  { id: 'reflection-loop', title: 'Reflection loop', nodes: 8, gates: 1 },
  { id: 'hierarchical-delegation', title: 'Hierarchical delegation', nodes: 7, gates: 1 },
] as const

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

/** Delete every document, so a second run measures the same thing as the first. */
async function clearLibrary(request: APIRequestContext): Promise<void> {
  const listed = await request.get('/api/builder/workflows')
  if (!listed.ok()) return
  const documents = (await listed.json()) as { id: string }[]
  for (const entry of documents) await request.delete(`/api/builder/workflows/${entry.id}`)
}

interface RunSnapshot {
  status: string
  error?: string | null
  result?: Record<string, unknown> | null
  pending_gate?: { gate_id?: string; node_id?: string } | null
}

/**
 * Answer every gate with `approve` until the run is terminal.
 *
 * Polled rather than driven off frames, because what this file is asserting is
 * the OUTCOME - a body an operator can read - and a socket would be a second
 * mechanism to get wrong. The budget is generous on purpose: the synthetic
 * runner is fast, and a timeout here should mean the run is stuck rather than
 * that the machine was busy.
 */
async function runToCompletion(
  request: APIRequestContext,
  runId: string,
  deadlineMs: number,
): Promise<{ snapshot: RunSnapshot; gatesAnswered: number }> {
  const until = Date.now() + deadlineMs
  let gatesAnswered = 0
  let snapshot: RunSnapshot = { status: 'unknown' }
  while (Date.now() < until) {
    const response = await request.get(`/api/runs/${runId}`)
    expect(response.ok(), 'the run snapshot should be readable').toBe(true)
    snapshot = (await response.json()) as RunSnapshot
    if (['completed', 'failed', 'cancelled'].includes(snapshot.status)) break
    const gateId = snapshot.status === 'waiting' ? snapshot.pending_gate?.gate_id : undefined
    if (gateId) {
      const answered = await request.post(`/api/runs/${runId}/gates/${gateId}`, {
        data: { outcome: 'approve', fields: {} },
      })
      expect(answered.status(), 'the gate reply was refused').toBe(202)
      gatesAnswered += 1
    }
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  return { snapshot, gatesAnswered }
}

test.describe('Templates run from a cold sign-in', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test.afterEach(async ({ request }) => {
    await clearLibrary(request)
  })

  for (const pattern of PATTERNS) {
    test(`@launch ${pattern.id} opens, publishes and completes with a body`, async ({
      page,
      request,
    }) => {
      // Four minutes per template is criterion 7's own budget. The synthetic
      // runner takes seconds; the ceiling is here so a WEDGED run fails as a
      // wedged run rather than as a suite that never finishes.
      test.setTimeout(240_000)
      const watch = watchConsole(page)

      // 1. One click from landing to a graph. This is rubric dimension 1's
      //    subject and the reason the gallery leads with these six.
      await page.goto('/#/build')
      await expect(card(page, pattern.title)).toBeVisible()
      await card(page, pattern.title).click()
      await expect(nodes(page)).toHaveCount(pattern.nodes)

      // 2. It is clean on arrival, against the SERVER rather than against a
      //    fixture. A template whose first frame is a red problems dock is
      //    worse than no template at all.
      await validationSettles(page)
      await expect(headline(page)).toContainText(/ready to publish/i)

      await page.keyboard.press('Control+s')
      await expect(saveChip(page)).toContainText(/saved/i)
      const id = await documentIdFromRoute(page)

      // 3. Publish, through the dialog a person uses.
      await page.keyboard.press('Control+Shift+P')
      const publish = page.locator('[aria-labelledby="publish-title"]')
      await expect(publish).toBeVisible()
      await publish.getByRole('button', { name: /^(Publish|Republish)$/ }).click()

      // Every one of these gates above its first billable node, so the dialog
      // says the link is safe to share rather than quoting the 403 an anonymous
      // launch of a gateless graph would get.
      await expect(publish).toContainText(/anyone with the link can launch it/i)

      // 4. Launch it. `input_field` comes off the published contract rather
      //    than from this file, so a template that renamed its input node is a
      //    failure in the run and not in the test's own literal.
      const published = await request.get(`/api/builder/workflows/${id}`)
      expect(published.ok()).toBe(true)
      const inputField = ((await published.json()) as { document: { input_field: string } })
        .document.input_field

      const launched = await request.post(`/api/sessions/e2e-templates/runs`, {
        data: {
          workflow_id: id,
          inputs: { [inputField]: 'A weekly digest of what changed in our codebase.' },
        },
      })
      expect(
        launched.status(),
        'the published template was refused by the endpoint it was published for',
      ).toBe(202)
      const runId = ((await launched.json()) as { run_id: string }).run_id

      const { snapshot, gatesAnswered } = await runToCompletion(request, runId, 210_000)
      expect(snapshot.status, `${pattern.id} ended ${snapshot.status}: ${snapshot.error}`).toBe(
        'completed',
      )
      expect(gatesAnswered, 'the template did not pause for a human').toBe(pattern.gates)

      // 5. A BODY, not merely a completed run. This is the assertion the first
      //    paid run of an authored graph existed to add: that run succeeded,
      //    spent money on 896 completion tokens, and handed back
      //    `markdown_body: ""` after validating with zero problems.
      const body = (snapshot.result ?? {})['markdown_body']
      expect(typeof body, `${pattern.id} produced no markdown_body`).toBe('string')
      expect(String(body).length, `${pattern.id} produced an empty body`).toBeGreaterThan(0)

      expect(watch.unexpected).toEqual([])
    })
  }
})
