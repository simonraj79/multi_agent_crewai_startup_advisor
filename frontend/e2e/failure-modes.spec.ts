import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

/**
 * 12 D8's six failure modes, in a real browser against a real backend.
 *
 * Criterion 5. `tests/builder/test_failure_modes.py` proves the FRAMES and the
 * recovery; this file proves the two things a Python test cannot see - that the
 * failure reaches the screen, and that the sixth mode never gets as far as a run
 * because the canvas refuses to publish it.
 *
 * ## The backend this file needs, and what happens without it
 *
 * `SYNTHETIC_FAILURE` is read by the backend PROCESS, at publish, and a browser
 * cannot set it. So the five running modes need one extra line on the free
 * backend, and it is one line for all five because the grammar is comma
 * separated with a node prefix per entry:
 *
 *   SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8097 \
 *   BUILDER_ALLOW_GATELESS_GRAPHS=1 \
 *   SYNTHETIC_FAILURE="fm_bad_key:bad_key:1,fm_tool_timeout:tool_timeout:1,\
 *   fm_refusal:refusal:1,fm_malformed:malformed_output:1,fm_rate_limit:rate_limit:1" \
 *   ./.venv/Scripts/serve.exe
 *
 * `BUILDER_ALLOW_GATELESS_GRAPHS` is the second knob and it is here because of
 * a DEFECT this file found, recorded in plan 12's Status as a follow-up against
 * plan 10 D5. A graph with a human gate above its first billable node is the
 * only shape an anonymous caller may launch - and `compile_replay_plan` cannot
 * replay a gate. Resuming past one compiles to
 * `n3_safe listens for 'e2_approve', which no method emits`, and the resume
 * fails. So the five graphs here are gateless, which needs the flag, and the
 * recovery half of criterion 5 is proved on a gateless graph rather than on a
 * gated one. That limit is real and stated rather than smoothed over.
 *
 * Three things about the failure line are deliberate:
 *
 *  - **Every entry names a NODE**, and every node it names is one only this file
 *    authors. So the same backend serves `builder.spec.ts`, `studio.spec.ts`
 *    and `templates.spec.ts` unchanged - no graph of theirs contains an `fm_*`
 *    node, so no run of theirs fails.
 *  - **Every entry ends `:1`**, so the node fails its FIRST attempt and works
 *    afterwards. That is what makes "fix it and re-run from here" testable: the
 *    repair a human does between the two runs is real, and clearing the knob
 *    would need a restart the browser cannot perform.
 *  - The counter is per FACTORY, and a factory is built per publish, so each
 *    test's own document gets a fresh attempt count.
 *
 * **Without that line the five running-mode tests SKIP and say so**, rather than
 * failing on an environment gap that would read like a product defect. That is
 * the `SYNTHETIC_BRANCH_DELAY_SECONDS` lesson (`docs/tech-stack.md` §7 quirk 6)
 * applied before it costs anybody an afternoon. The cyclic-graph test does not
 * skip: it needs no knob, because that mode never runs.
 *
 * ## Cost
 *
 * Zero. `SYNTHETIC=1` swaps the crew factories and nothing else, so the
 * compiled definition, the gates, the routers, the frames and the persistence
 * are the production ones and no model is called. Tagged `@launch` because it
 * presses the button: against a paid origin, exclude it.
 */

/**
 * ONE exemption, and it names its cause - the shape `studio.spec.ts` documents.
 *
 * These two files are the first in the repository to meet
 * `RUN_RATE_LIMIT_MAX_RUNS` (ten per sixty seconds), and a Launch that is
 * refused makes the browser log the 429 as a failed resource. That console
 * error is the LIMITER WORKING, provoked deliberately by a test that then waits
 * out the window on the server's own `Retry-After` and launches again - the
 * alternative being to raise the limit, which would turn off what makes an
 * unauthenticated Launch button survivable.
 *
 * Narrow on purpose: only 429, only the words the browser uses for it. Any
 * other status, any Vue warning and any uncaught exception still fails the
 * test. If the limiter is ever removed or these files stop launching, DELETE
 * THIS - an exemption that outlives its cause widens silently, which is what
 * the favicon one did before it was retired.
 */
const ALLOWED_CONSOLE_ERROR: RegExp | null = /429 \(Too Many Requests\)/

/** D8's five running modes, and the node each one is aimed at. */
const MODES = [
  { reason: 'bad_key', node: 'fm_bad_key', errorClass: 'auth' },
  { reason: 'tool_timeout', node: 'fm_tool_timeout', errorClass: 'tool_timeout' },
  { reason: 'refusal', node: 'fm_refusal', errorClass: 'refusal' },
  { reason: 'malformed_output', node: 'fm_malformed', errorClass: 'schema' },
  { reason: 'rate_limit', node: 'fm_rate_limit', errorClass: 'rate_limit' },
] as const

const AUTHORED_MODEL = 'google/gemini-3.8-flash'
const BODY_KEY = 'markdown_body'

interface RunSnapshot {
  status: string
  error?: string | null
  result?: Record<string, unknown> | null
  pending_gate?: { gate_id?: string } | null
}

interface FrameDetails {
  stage?: string
  error_class?: string
  attempt?: number
  will_retry?: boolean
  message?: string
  replayed?: boolean
}

function watchConsole(page: Page): { unexpected: string[] } {
  const watch = { unexpected: [] as string[] }
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

/* --- documents ----------------------------------------------------------- */

function agent(id: string, source: string) {
  return {
    id,
    kind: 'agent',
    label: id,
    position: { x: 0, y: 0 },
    config: {
      role: `${id} specialist`,
      goal: `do the ${id} work`,
      backstory: 'years of it',
      task: {
        description: 'work from ${state.out__' + source + '}',
        expected_output: 'a paragraph',
      },
      llm: { model: AUTHORED_MODEL },
      tier: 'cheap',
      on_error: 'fail',
    },
  }
}

function edge(id: string, source: string, target: string, port = 'out') {
  return { id, source, source_port: port, target, target_port: 'in' }
}

/**
 * `idea -> safe -> <failing> -> report`. Gateless, for the reason in the
 * docstring: a gate above the resume point makes `compile_replay_plan` emit a
 * flow whose next node listens for a trigger no method emits.
 *
 * `safe` is not decoration. It is the node the resume REPLAYS, and a resume
 * that replayed nothing would prove only that a run can be started twice.
 */
function failingGraph(node: string) {
  return {
    schema: 'builder.flow/v1',
    name: `failure mode ${node}`,
    version: 1,
    input_field: 'idea',
    nodes: [
      { id: 'idea', kind: 'input', label: 'idea', position: { x: 0, y: 0 }, config: { field: 'idea' } },
      agent('safe', 'idea'),
      agent(node, 'safe'),
      {
        id: 'report',
        kind: 'output',
        label: 'report',
        position: { x: 0, y: 0 },
        config: { body_key: BODY_KEY, source: '${state.out__' + node + '}' },
      },
    ],
    edges: [edge('e1', 'idea', 'safe'), edge('e2', 'safe', node), edge('e3', node, 'report')],
    joins: {},
  }
}

/* --- the API a person's clicks reach ------------------------------------- */

async function publish(request: APIRequestContext, document: unknown): Promise<string> {
  const created = await request.post('/api/builder/workflows', { data: { document } })
  expect(created.status(), await created.text()).toBe(201)
  const id = ((await created.json()) as { document: { id: string } }).document.id
  const published = await request.post(`/api/builder/workflows/${id}/publish`)
  expect(published.status(), await published.text()).toBe(200)
  return id
}

/**
 * Launch, waiting out the admission limiter rather than tripping over it.
 *
 * Five modes at two runs each plus the probe is eleven, and
 * `RUN_RATE_LIMIT_MAX_RUNS` is ten per sixty seconds - so this file is the one
 * test in the repository that meets its own rate limit. Waiting is the correct
 * behaviour and not a workaround: `Retry-After` is computed by the server and
 * put in `CORS_EXPOSE_HEADERS` for exactly this reader, and a test that raised
 * the limit instead would be turning off the thing that keeps an
 * unauthenticated Launch button survivable.
 */
async function launch(
  request: APIRequestContext,
  workflowId: string,
  body: Record<string, unknown> = {},
): Promise<string> {
  const payload = {
    workflow_id: workflowId,
    inputs: { idea: 'A scheduling assistant for clinics.' },
    ...body,
  }
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const response = await request.post('/api/sessions/e2e-failure-modes/runs', { data: payload })
    if (response.status() === 429) {
      const after = Number(response.headers()['retry-after'] ?? 5)
      expect(Number.isFinite(after), 'a 429 with no readable Retry-After').toBe(true)
      await new Promise((resolve) => setTimeout(resolve, (after + 1) * 1000))
      continue
    }
    expect(response.status(), await response.text()).toBe(202)
    return ((await response.json()) as { run_id: string }).run_id
  }
  throw new Error('the admission limiter refused three launches in a row')
}

async function settle(request: APIRequestContext, runId: string): Promise<RunSnapshot> {
  const until = Date.now() + 60_000
  let snapshot: RunSnapshot = { status: 'unknown' }
  while (Date.now() < until) {
    const response = await request.get(`/api/runs/${runId}`)
    expect(response.ok()).toBe(true)
    snapshot = (await response.json()) as RunSnapshot
    if (['completed', 'failed', 'cancelled'].includes(snapshot.status)) return snapshot
    const gateId = snapshot.status === 'waiting' ? snapshot.pending_gate?.gate_id : undefined
    if (gateId) {
      const answered = await request.post(`/api/runs/${runId}/gates/${gateId}`, {
        data: { outcome: 'approve', fields: {} },
      })
      expect(answered.status(), await answered.text()).toBe(202)
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  return snapshot
}

/**
 * The C6 `node_error` frames, and only those.
 *
 * `stage: "error"` alone is not the discriminator: `serializer.py:455` raises
 * one for CrewAI's own `MethodExecutionFailedEvent` and three more come from a
 * tool, an llm call and a crew. `attempt` is written only by the runtime, which
 * is the same filter `useBuilderProblems.runPhaseProblems` applies.
 */
async function nodeErrors(
  request: APIRequestContext,
  runId: string,
): Promise<{ node_id: string; details: FrameDetails }[]> {
  const page = await request.get(`/api/runs/${runId}/frames?limit=500`)
  expect(page.ok()).toBe(true)
  const frames = ((await page.json()) as { frames: { data: { node_id: string; details: FrameDetails } }[] })
    .frames
  return frames
    .map((frame) => frame.data)
    .filter((data) => data.details?.stage === 'error' && typeof data.details?.attempt === 'number')
}

/** Whether the backend was started with the line in this file's docstring. */
let knobPresent: boolean | null = null

async function requireKnob(request: APIRequestContext): Promise<void> {
  if (knobPresent === null) {
    const workflowId = await publish(request, failingGraph('fm_refusal'))
    const response = await request.post('/api/sessions/e2e-failure-modes/runs', {
      data: { workflow_id: workflowId, inputs: { idea: 'probe' } },
    })
    if (response.status() !== 202) {
      // 403: gateless launches are off, so nothing below can run at all.
      knobPresent = false
    } else {
      const runId = ((await response.json()) as { run_id: string }).run_id
      knobPresent = (await settle(request, runId)).status === 'failed'
    }
  }
  test.skip(
    !knobPresent,
    'the backend was started without SYNTHETIC_FAILURE and BUILDER_ALLOW_GATELESS_GRAPHS. ' +
      'See this file\'s docstring: BUILDER_ALLOW_GATELESS_GRAPHS=1 SYNTHETIC_FAILURE=' +
      '"fm_bad_key:bad_key:1,fm_tool_timeout:tool_timeout:1,fm_refusal:refusal:1,' +
      'fm_malformed:malformed_output:1,fm_rate_limit:rate_limit:1"',
  )
}

/* --- what the screen says, FIRST ------------------------------------------
 *
 * Declared before the five, deliberately. Playwright runs a file's tests in
 * declaration order, and the five spend two launches each against a ten-per-
 * minute allowance - so a console test declared last would meet the limiter
 * on every run rather than occasionally.
 */

test.describe('the failure reaches the screen', () => {
  test('@launch the failed node turns red on the run console, message and all', async ({
    page,
    request,
  }) => {
    test.setTimeout(180_000)
    await requireKnob(request)
    const watch = watchConsole(page)

    // Published through the UI, and handed to the console by the dialog's own
    // `Run it` - which is how a person gets there. Poking the handoff record
    // into storage would test this file's idea of that record rather than the
    // one `PublishDialog` writes, and it is identity-scoped, so the two would
    // disagree the moment anybody signed in.
    const created = await request.post('/api/builder/workflows', {
      data: { document: failingGraph('fm_refusal') },
    })
    expect(created.status(), await created.text()).toBe(201)
    const id = ((await created.json()) as { document: { id: string } }).document.id

    await page.goto(`/#/build/${id}`)
    await expect(page.locator('[data-testid="problems-checking"]')).toHaveCount(0, {
      timeout: 30_000,
    })
    await page.keyboard.press('Control+Shift+P')
    const dialog = page.locator('[aria-labelledby="publish-title"]')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: /^(Publish|Republish)$/ }).click()
    await dialog.getByRole('button', { name: /run it/i }).click()
    await expect.poll(() => new URL(page.url()).hash).not.toMatch(/^#\/build/)

    // The console is drawing the AUTHOR's graph, not the fixed validator.
    const failing = page.locator('.vue-flow__node[data-id="fm_refusal"]')
    await expect(failing, 'the console is not drawing the published graph').toBeVisible({
      timeout: 30_000,
    })

    // Review rather than the console's own default, for `studio.spec.ts`'s
    // reason: `gatesMode` defaults to `auto`, and against a backend without
    // VALIDATOR_ALLOW_AUTO_GATES that is a 403 and no run at all.
    const review = page.getByRole('button', { name: 'Review', exact: true })
    if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
    await page.locator('textarea#idea').fill('A scheduling assistant for clinics.')

    /*
     * Pressing Launch, waiting out the admission limiter if it answers first.
     *
     * `RUN_RATE_LIMIT_MAX_RUNS` is ten per sixty seconds and this file is the
     * only one in the repository that reaches it, so the click is retried
     * rather than the limit raised. The console's own handling is asserted on
     * the way past: a 429 renders the server's sentence AND the computed
     * `Retry-After`, which is what `CORS_EXPOSE_HEADERS` puts that header on
     * the wire for.
     */
    const launchButton = page.getByRole('button', { name: /^Launch/ })
    const limited = page.locator('[role="alert"]').filter({ hasText: /too many runs/i })
    for (let attempt = 0; attempt < 14; attempt += 1) {
      await launchButton.click()
      // WAITED FOR, not counted. Counting immediately after the click races the
      // render, and the absence of the alert has to be a timeout rather than a
      // snapshot taken before Vue had a chance to paint it.
      try {
        await limited.waitFor({ state: 'visible', timeout: 2_000 })
      } catch {
        break
      }
      await expect(limited).toContainText(/try again in \d+s/i)
      await page.waitForTimeout(5_000)
    }
    await expect(limited).toHaveCount(0)

    // RED, on the card, without hovering anything. `.is-error` is
    // `WorkflowNode.vue`'s own state class and the run console's five states are
    // spec §5.1's; a jsdom mount can assert the class and only a browser can say
    // it was ever painted.
    await expect(failing.locator('.workflow-node.is-error')).toBeVisible({ timeout: 90_000 })

    // Plan 11's card (WorkflowNode.vue). Guarded while the two plans were built
    // on separate branches; un-guarded by the Integrator on the merge.
    await test.step('the inline message on the card (plan 11)', async () => {
      const message = failing.locator('[data-testid="node-error-message"]')
      await expect(message).toBeVisible()
      expect((await message.innerText()).length).toBeLessThanOrEqual(120)
    })

    // Plan 11's button. What it posts - `resume_from` - is proved for real by
    // the five tests above; this proves the click reaches it.
    await test.step('Re-run from here (plan 11)', async () => {
      const button = page.locator('[data-testid="rerun-from-here"]')
      await expect(button).toBeVisible()
      await button.click()
      await expect(failing.locator('.workflow-node.is-completed')).toBeVisible({
        timeout: 120_000,
      })
    })

    // The run-phase group in the problems dock is asserted in
    // `e2e/test-panel.spec.ts` ("a failed test run puts the node in the problems
    // dock"), not here: the run console has no problems dock BY DESIGN - the
    // dock is a builder surface - so the guarded step that used to sit here was
    // looking for it on the one page it can never be on.

    expect(watch.unexpected).toEqual([])
  })
})

/* --- the five that run ---------------------------------------------------- */

test.describe('the five failure modes that run', () => {
  test.describe.configure({ mode: 'serial' })

  for (const mode of MODES) {
    test(`@launch ${mode.reason} fails legibly and re-runs from the failed node`, async ({
      request,
    }) => {
      test.setTimeout(180_000)
      await requireKnob(request)

      const workflowId = await publish(request, failingGraph(mode.node))
      const failed = await launch(request, workflowId)
      const snapshot = await settle(request, failed)

      // LEGIBLE: the run ended failed, and the frame says which node, which
      // attempt and - D8's own column - what CLASS of failure it was.
      expect(snapshot.status, `${mode.reason} ended ${snapshot.status}`).toBe('failed')
      const errors = await nodeErrors(request, failed)
      expect(errors.length, `${mode.reason} produced no node_error frame`).toBeGreaterThan(0)
      const last = errors[errors.length - 1]
      expect(last.node_id).toBe(mode.node)
      expect(last.details.error_class).toBe(mode.errorClass)
      expect(last.details.attempt).toBe(1)
      expect(String(last.details.message ?? '')).not.toBe('')

      // The node BEFORE it succeeded, so the failure is about one node rather
      // than about a graph that never works.
      expect(errors.every((entry) => entry.node_id === mode.node)).toBe(true)

      // RECOVERABLE: `resume_from` is exactly what the Re-run from here button
      // posts. The `:1` in the knob is the repair a human would have made.
      const resumed = await launch(request, workflowId, {
        resume_from: { run_id: failed, node_id: mode.node },
      })
      const after = await settle(request, resumed)
      expect(after.status, `the resume ended ${after.status}: ${after.error}`).toBe('completed')
      expect(String((after.result ?? {})[BODY_KEY] ?? '')).not.toBe('')

      // And it REPLAYED rather than re-running what had already been paid for.
      const replayed = new Set<string>()
      const framesPage = await request.get(`/api/runs/${resumed}/frames?limit=500`)
      for (const frame of ((await framesPage.json()) as {
        frames: { data: { node_id: string; details: FrameDetails } }[]
      }).frames) {
        if (frame.data.details?.replayed === true) replayed.add(frame.data.node_id)
      }
      expect([...replayed].sort()).toContain('safe')
      expect(replayed.has(mode.node)).toBe(false)
    })
  }
})

/* --- what the screen says ------------------------------------------------- */

/* --- the sixth mode, which never runs ------------------------------------- */

test.describe('the cyclic graph never gets as far as a run', () => {
  test('publish is refused, the closing edge is highlighted, and the sentence says how', async ({
    page,
  }) => {
    test.setTimeout(120_000)
    const watch = watchConsole(page)

    // Authored in the browser rather than posted, because what this asserts is
    // the CANVAS's refusal - the dock, the edge and the disabled button - and
    // posting the document would prove only that the server said no.
    await page.goto('/#/build')
    await page.locator('.template-card').first().waitFor({ timeout: 30_000 })

    // A loop closed by a plain agent, dropped straight into the store. The
    // canvas reads it back from the same GET a deep link uses, so what is on
    // screen is a document the server has already validated.
    const created = await page.request.post('/api/builder/workflows', {
      data: {
        document: {
          schema: 'builder.flow/v1',
          name: 'a loop closed by an agent',
          version: 1,
          input_field: 'idea',
          nodes: [
            {
              id: 'idea',
              kind: 'input',
              label: 'idea',
              position: { x: 0, y: 0 },
              config: { field: 'idea' },
            },
            agent('first', 'idea'),
            agent('second', 'first'),
            {
              id: 'report',
              kind: 'output',
              label: 'report',
              position: { x: 0, y: 0 },
              config: { body_key: BODY_KEY, source: '${state.out__second}' },
            },
          ],
          edges: [
            edge('e1', 'idea', 'first'),
            edge('e2', 'first', 'second'),
            edge('e3', 'second', 'first'),
            edge('e4', 'second', 'report'),
          ],
          joins: {},
        },
      },
    })
    expect(created.status(), await created.text()).toBe(201)
    const id = ((await created.json()) as { document: { id: string } }).document.id

    await page.goto(`/#/build/${id}`)
    await expect(page.locator('[data-testid="problems-checking"]')).toHaveCount(0, {
      timeout: 30_000,
    })

    // 1. The dock names it, in a sentence that says what to do.
    const row = page.locator('[data-testid="problem-back-edge-not-router"]')
    await expect(row).toBeVisible({ timeout: 30_000 })
    await expect(row).toContainText(/router/i)

    // 2. The closing edge carries the error tint, so the sentence has something
    //    to point at. `has-error` is the class `useBuilderCanvas` projects from
    //    the problem's own `edge_id`.
    await expect(page.locator('.builder-edge.has-error')).toHaveCount(1)

    // 3. Publish is refused. An error blocks it; a warning never would.
    await expect(page.locator('[data-testid="problems-headline"]')).toContainText(/error/i)
    await page.keyboard.press('Control+Shift+P')
    const dialog = page.locator('[aria-labelledby="publish-title"]')
    if (await dialog.isVisible()) {
      await expect(
        dialog.getByRole('button', { name: /^(Publish|Republish)$/ }),
      ).toBeDisabled()
      await page.keyboard.press('Escape')
    }

    // 4. And the server would refuse it too, so the button is not the only lock.
    const refused = await page.request.post(`/api/builder/workflows/${id}/publish`)
    expect(refused.status()).toBe(422)
    expect(await refused.text()).toContain('back-edge-not-router')

    await page.request.delete(`/api/builder/workflows/${id}`)
    expect(watch.unexpected).toEqual([])
  })
})
