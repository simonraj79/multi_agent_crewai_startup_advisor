import { expect, test, type Locator, type Page } from '@playwright/test'

/**
 * End-to-end coverage of the Validator Studio console.
 *
 * These tests drive a real browser against a real FastAPI service over a real
 * WebSocket. They assert the operator's journey - launch, two durable human
 * gates, completion - and the one product guarantee that is invisible from the
 * outside: at the verdict gate the server *prunes* the editable fields, so
 * every `Verdict` key must reach the operator as read-only text.
 *
 * ## Which backend these run against
 *
 * `vite.config.ts` proxies `/api` and `/ws` to `127.0.0.1:8000`, which is this
 * project's *paid* service - real OpenRouter, Firecrawl, GitHub and Pinecone
 * keys, real money on every Launch. The suite therefore never uses that config.
 * `e2e/vite.e2e.config.ts` starts a second dev server pointed at the no-cost
 * `SYNTHETIC=1` service instead, and `playwright.config.ts` is what starts it.
 *
 * Tests that press Launch are tagged `@launch`. Against a deployed origin that
 * is backed by paid runners, run only the read-only ones:
 *
 *   E2E_BASE_URL=https://example.onrender.com npx playwright test --grep-invert @launch
 *
 * ## What the synthetic double does and does not model
 *
 * `SyntheticValidatorRunner` emits `run_state` and `node_state` frames and two
 * `HumanFeedbackPending` rounds. It emits no `edge_taken` frames - those come
 * from CrewAI's router events through `events/serializer.py` - so edges never
 * animate here and nothing below asserts that they do.
 *
 * It DOES model revise branching. It did not until the double learned to read
 * `decision`, and while it did not, a `revise` reply advanced exactly as an
 * `approve` did - so `route_scope -> revise_scope -> confirm_scope` was a dead
 * edge on the free path and the revise test could only assert that the reply
 * was accepted. It now loops back to the same gate, bounded per gate the way
 * `claim_revise_turn` bounds the real Flow.
 */

const EXPECTED_NODES = 14
const EXPECTED_EDGES = 16

/**
 * Nothing is tolerated any more.
 *
 * This used to forgive `/favicon.ico`: `index.html` declared no
 * `<link rel="icon">`, so every page load asked for one and the server answered
 * 404 - while `public/favicon.svg` had existed, referenced by nothing, since
 * the first commit. The link is declared now (remaining-work item 7), the
 * request is gone, and all seven tests pass with this set to `null`, which is
 * what retired the exemption rather than an assumption that it would.
 *
 * Kept as a nullable pattern rather than deleted outright, so the next
 * genuinely unavoidable error has an obvious place to be declared WITH its
 * reason. An exemption that outlives its cause is worse than none: it widens
 * silently, and this one had already outlived a fix that was one line away.
 */
const ALLOWED_CONSOLE_ERROR: RegExp | null = null

interface ConsoleWatch {
  /** Console errors and uncaught exceptions that are not the favicon 404. */
  unexpected: string[]
}

function watchConsole(page: Page): ConsoleWatch {
  const watch: ConsoleWatch = { unexpected: [] }
  const record = (text: string) => {
    if (!ALLOWED_CONSOLE_ERROR?.test(text)) watch.unexpected.push(text)
  }
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text())
  })
  page.on('pageerror', (error) => record(`uncaught: ${error.message}`))
  return watch
}

/** The run-control panel's own primary button, never the gate card's. */
function launchButton(page: Page): Locator {
  return page.locator('.status-panel .control-actions button.button-primary')
}

function downloadButton(page: Page): Locator {
  return page.locator('.status-panel .control-actions button', { hasText: 'Download logs' })
}

function statusBadge(page: Page): Locator {
  return page.locator('.status-panel .status-badge')
}

function gateCard(page: Page): Locator {
  return page.locator('.gate-card')
}

/** `seq N` from the stream line - the client's high-water mark of frames. */
async function readSequence(page: Page): Promise<number> {
  const text = await page.locator('.status-panel .stream-line').innerText()
  return Number(/seq\s+(\d+)/.exec(text)?.[1] ?? -1)
}

async function openStudio(page: Page): Promise<void> {
  await page.goto('/')
  await expect(page.locator('.vue-flow__node').first()).toBeVisible()
}

async function launchRun(page: Page, idea: string): Promise<void> {
  /*
   * The gates mode is DECLARED here rather than inherited from the console's
   * default, and that is not defensive tidying - inheriting it broke every
   * @launch test in this file, in two different ways at once.
   *
   * `useValidatorRun` defaults `gatesMode` to `'auto'`. Against a backend with
   * VALIDATOR_ALLOW_AUTO_GATES set, the run then completes unattended and no
   * gate card ever appears; against one without it, `create_run` answers 403
   * and no run starts at all. Neither is a bug in the console - unattended is a
   * deliberate default - but both make a test whose entire subject is the
   * operator's journey THROUGH the gates depend on an environment variable it
   * never mentions.
   *
   * Clicking Review states the requirement. `aria-pressed` is checked first so
   * a future change of default does not turn this into a click that switches
   * the mode off again.
   */
  const review = page.getByRole('button', { name: 'Review', exact: true })
  if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
  await expect(review).toHaveAttribute('aria-pressed', 'true')

  await page.locator('#idea').fill(idea)
  await expect(launchButton(page)).toBeEnabled()
  await launchButton(page).click()
}

/** Wait for a specific operator gate to be the one on screen. */
async function waitForGate(page: Page, title: string): Promise<void> {
  await expect(gateCard(page).locator('h2')).toHaveText(title, { timeout: 60_000 })
}

async function approveGate(page: Page): Promise<void> {
  await gateCard(page).getByRole('button', { name: /^Approve/ }).click()
}

test.describe('Validator Studio', () => {
  test('renders the fixed validator topology', async ({ page }) => {
    const watch = watchConsole(page)
    await openStudio(page)

    await expect(page).toHaveTitle('M2 Validator Studio')
    await expect(page.getByRole('heading', { name: 'Validator Studio', level: 1 })).toBeVisible()

    // The graph is fixed by contract: `service/graph.py` derives it from the
    // CrewAI Flow topology and the frontend renders exactly what it is served.
    // A change in either count is a change to the product, not to the test.
    await expect(page.locator('.vue-flow__node')).toHaveCount(EXPECTED_NODES)
    await expect(page.locator('.vue-flow__edge')).toHaveCount(EXPECTED_EDGES)

    // Spot-check the shape rather than every label: the six agents, both
    // gates, both routers, the output, and the visible quarantine node.
    for (const label of [
      'Scoper',
      'Market Analyst',
      'Sentiment Analyst',
      'Feasibility Analyst',
      'Synthesist',
      'Reporter',
      'Confirm scope',
      'Review verdict',
      'Route scope',
      'Route verdict',
      'Validation brief',
      'Unattributed',
    ]) {
      await expect(page.locator(`.workflow-node[aria-label^="${label},"]`)).toHaveCount(1)
    }

    // Routers are drawn as deterministic plumbing, not as agent cards.
    await expect(page.locator('[data-testid="deterministic-tag"]')).toHaveCount(2)

    expect(watch.unexpected).toEqual([])
  })

  test('reports the live backend instead of falling back to the mock transport', async ({ page }) => {
    await openStudio(page)

    // `MOCK_GRAPH.version` is deliberately prefixed `mock-of-`, so the graph
    // version on the canvas is an unambiguous statement of which transport
    // served this page. The mock fallback exists for a missing backend; it
    // silently masking a broken one is the failure this pins.
    await expect(page.locator('.canvas-meta code')).not.toHaveText(/^mock-/)
    await expect(page.locator('.live-status')).not.toHaveText(/mock/i)
    await expect(page.locator('.status-panel .stream-line')).not.toContainText('Mock stream')
    await expect(page.locator('.status-panel .read-only-well')).toContainText('Idea Validator')

    // Before a run exists there is no WebSocket. The header used to read
    // "Offline" here even though the API had just answered - the badge binds
    // the socket's state, so "backend down" and "no run yet" were the same
    // word on the first thing a visitor reads. It now reports the probed
    // transport while nothing is streaming, and hands back to the socket once
    // a run is in flight (asserted as "connected" in the journey test).
    await expect(page.locator('.live-status')).toHaveText(/ready/i)
    await expect(page.locator('.live-status')).not.toHaveText(/offline/i)
    await expect(statusBadge(page)).toHaveText(/idle/i)
  })

  test(
    'runs the full operator journey through both gates to completion',
    { tag: '@launch' },
    async ({ page }) => {
      const watch = watchConsole(page)
      await openStudio(page)

      await launchRun(page, 'A scheduling assistant for small veterinary clinics')

      // ---- Scope gate ---------------------------------------------------
      await waitForGate(page, 'Confirm scope')
      await expect(statusBadge(page)).toHaveText(/waiting/i)
      // Now that a run is streaming, the header must say so.
      await expect(page.locator('.live-status')).toHaveText(/connected/i)
      await expect(page.locator('.status-panel .run-id')).toBeVisible()

      // The scope gate is fully editable - revising the scope is its point -
      // so `ScopedIdea` arrives as inputs, not as read-only text.
      const scopeFields = gateCard(page).locator('form .gate-field')
      await expect(scopeFields).toHaveCount(5)
      await expect(scopeFields.locator('span')).toHaveText(
        ['startup idea', 'category', 'target user', 'market query', 'feedback'],
        { useInnerText: false },
      )
      for (const name of ['startup idea', 'category', 'target user', 'market query']) {
        const input = gateCard(page).locator('.gate-field', { hasText: name }).locator('input')
        await expect(input).toBeEditable()
      }
      await expect(page.locator('.workflow-node[aria-label="Scoper, Completed"]')).toHaveCount(1)
      // The gate node is NOT asserted to read "Waiting" here, because it does
      // not - see the `test.fail()` case below, which pins that as a bug rather
      // than letting this journey quietly assert the wrong thing. What is true
      // is that the gate has not been answered yet.
      await expect(page.locator('.workflow-node[aria-label="Confirm scope, Completed"]')).toHaveCount(0)

      await approveGate(page)

      // ---- Three research branches, then the verdict gate ----------------
      await waitForGate(page, 'Review verdict')
      for (const branch of ['Market Analyst', 'Sentiment Analyst', 'Feasibility Analyst']) {
        await expect(page.locator(`.workflow-node[aria-label="${branch}, Completed"]`)).toHaveCount(1)
      }
      await expect(page.locator('.workflow-node[aria-label="Synthesist, Completed"]')).toHaveCount(1)
      await expect(
        page.locator('.workflow-node[aria-label="Route scope, deterministic router, no model call, Completed"]'),
      ).toHaveCount(1)

      await approveGate(page)

      // ---- Completion -----------------------------------------------------
      await expect(statusBadge(page)).toHaveText(/completed/i, { timeout: 60_000 })
      await expect(gateCard(page)).toHaveCount(0)
      await expect(downloadButton(page)).toBeEnabled()

      // A dropped frame means the console's picture of the run has a hole in
      // it. Zero is the contract, and the panel flags any other number.
      await expect(page.locator('.status-panel .stream-line')).toContainText('0 dropped')
      await expect(page.locator('.status-panel .stream-line .has-drops')).toHaveCount(0)

      // Frames the backend could not attribute to a declared node are parked
      // on a visible quarantine node rather than dropped silently.
      await expect(page.locator('[data-testid="quarantine-count"]')).toHaveText('0')

      await expect(page.locator('.workflow-node[aria-label="Reporter, Completed"]')).toHaveCount(1)
      await expect(page.locator('.workflow-node[aria-label="Validation brief, Completed"]')).toHaveCount(1)
      await expect(page.locator('.error-banner')).toHaveCount(0)
      // The primary button turns into a relaunch once the run is history.
      await expect(launchButton(page)).toHaveText(/relaunch/i)

      expect(watch.unexpected).toEqual([])
    },
  )

  /**
   * A pinned defect, not a passing feature.
   *
   * `WorkflowNode` documents five node states and styles all five, and
   * `NodeRunState` in `types/studio.ts` declares `waiting` alongside the rest.
   * The only place a node can *reach* it is `useValidatorRun.applyNodeState`:
   *
   *     if (frame.event_type.includes('WAITING')) { setNodeState(nodeId, 'waiting') ... }
   *
   * No member of `UIEventType` (`events/models.py`) contains the substring
   * `WAITING`. A gate arrives as `FrameKind.GATE_OPEN` /
   * `UIEventType.HUMAN_INTERACTION`, which `applyFrame` routes to `applyGate` -
   * and `applyGate` sets the *run* status to waiting and never touches the node.
   * So the branch above is unreachable against this backend, and the gate node
   * on the canvas goes idle -> completed, skipping the one state that says a
   * human is being asked.
   *
   * The operator effect: while the run is paused on "Confirm scope", that node
   * is drawn grey and idle - indistinguishable from `revise_scope`, which has
   * never run. The live graph is the product, and at the two moments it most
   * needs to point at something, it points at nothing.
   *
   * FIXED. `applyGate` now sets the gate node to `waiting`, which is the
   * missing half of the pair `gate_closed` already had (it sets the same node
   * to `completed`). This test is the regression guard: it fails again the day
   * the paused node stops saying so.
   */
  test(
    'marks the paused gate node Waiting while a human is being asked',
    { tag: '@launch' },
    async ({ page }) => {
      await openStudio(page)
      await launchRun(page, 'A dosage-check assistant for community pharmacists')

      await waitForGate(page, 'Confirm scope')
      await expect(statusBadge(page)).toHaveText(/waiting/i)

      // What the canvas *should* say while a human is being asked. The short
      // timeout is deliberate: the gate is already open by the time we get
      // here, so there is nothing left to wait for, and a full-length wait
      // would just add fifteen idle seconds to every suite run.
      await expect(page.locator('.workflow-node[aria-label="Confirm scope, Waiting"]')).toHaveCount(
        1,
        { timeout: 2_000 },
      )
    },
  )

  test(
    'presents every verdict value as read-only and leaves only feedback editable',
    { tag: '@launch' },
    async ({ page }) => {
      await openStudio(page)
      await launchRun(page, 'A compliance copilot for independent pharmacies')

      await waitForGate(page, 'Confirm scope')
      await approveGate(page)
      await waitForGate(page, 'Review verdict')

      const card = gateCard(page)
      const derived = card.locator('.gate-derived')
      await expect(derived).toHaveCount(1)

      // Every key of the `Verdict` the server sent must arrive as a read-only
      // value. `service/registry.py::_gate_derived_keys` returns *all* keys at
      // `review_verdict`, and `_split_gate_fields` prunes them out of `fields`
      // so a stale client cannot go on offering an edit the server discards.
      const derivedKeys = (await derived.locator('dt').allTextContents()).map((text) => text.trim())
      expect(derivedKeys).toEqual(
        expect.arrayContaining(['verdict', 'confidence', 'cheapest next test']),
      )

      // Read-only means read-only in the DOM, not merely by convention: the
      // derived block must contain no control an operator could type into.
      await expect(
        derived.locator('input, textarea, select, button, [contenteditable="true"]'),
      ).toHaveCount(0)
      await expect(derived.locator('h3')).toContainText('Computed by the validator')

      // ...and the form must offer exactly one lever: the feedback note.
      const fields = card.locator('form .gate-field')
      await expect(fields).toHaveCount(1)
      await expect(fields.locator('span')).toHaveText('feedback', { useInnerText: false })
      await expect(card.locator('form input')).toHaveCount(0)
      const feedback = card.locator('form textarea')
      await expect(feedback).toHaveCount(1)
      await expect(feedback).toBeEditable()

      // No derived key may reappear as an editable field name.
      const fieldNames = (await fields.locator('span').allTextContents()).map((text) => text.trim())
      for (const key of derivedKeys) expect(fieldNames).not.toContain(key)

      // The headline verdict badge and the derived block are the same value,
      // so the operator cannot be shown two different answers.
      const headline = (await card.locator('.verdict-row strong').textContent())?.trim()
      const derivedVerdict = (
        await derived.locator('dt', { hasText: /^verdict$/ }).locator('+ dd').textContent()
      )?.trim()
      expect(derivedVerdict).toBe(headline)
      expect((derivedVerdict ?? '').length).toBeGreaterThan(0)

      // Both decisions are offered; Revise is the lever for disagreeing.
      await expect(card.getByRole('button', { name: /^Approve/ })).toBeEnabled()
      await expect(card.getByRole('button', { name: /^Revise/ })).toBeEnabled()
    },
  )

  test(
    'accepts a Revise reply at the scope gate and keeps the run going',
    { tag: '@launch' },
    async ({ page }) => {
      const watch = watchConsole(page)
      await openStudio(page)
      await launchRun(page, 'A triage inbox for small-practice veterinary clinics')

      await waitForGate(page, 'Confirm scope')
      const feedback = gateCard(page)
        .locator('.gate-field', { hasText: 'feedback' })
        .locator('textarea')
      await feedback.fill('Narrow the target user to single-vet practices before scoring.')

      const sequenceBefore = await readSequence(page)
      await gateCard(page).getByRole('button', { name: /^Revise/ }).click()

      await expect
        .poll(() => readSequence(page), {
          timeout: 60_000,
          message: 'the run should stream more frames after a Revise reply',
        })
        .toBeGreaterThan(sequenceBefore)

      // The loop itself, which this test could not assert while the double
      // treated revise as approve. The run comes back to the SAME gate...
      await waitForGate(page, 'Confirm scope')
      await expect(
        page.locator('.workflow-node[aria-label^="Revise scope, Completed"]'),
      ).toHaveCount(1)

      // ...and the console says so, rather than leaving the operator to notice
      // that a gate they already answered is open again. This is the whole
      // point of the lap counters: a second pass that looks identical to the
      // first is indistinguishable from a stuck run.
      await expect(page.locator('[data-testid="crew-lap"]')).toContainText(
        /sent back for a revision|pass 2/i,
      )
      await expect(page.locator('[data-testid="crew-stage-lap"]').first()).toHaveText('\u00d72')
      await expect(
        page.locator('.workflow-node[aria-label="Confirm scope, Waiting, pass 2"]'),
      ).toHaveCount(1)

      await expect(page.locator('.error-banner')).toHaveCount(0)
      await expect(statusBadge(page)).not.toHaveText(/error/i)
      await expect(page.locator('.status-panel .stream-line')).toContainText('0 dropped')
      expect(watch.unexpected).toEqual([])
    },
  )

  test(
    'recovers an in-flight run across a page reload',
    { tag: '@launch' },
    async ({ page }) => {
      const watch = watchConsole(page)
      await openStudio(page)
      await launchRun(page, 'A rota planner for community pharmacy locums')

      await waitForGate(page, 'Confirm scope')
      const runIdBefore = (await page.locator('.status-panel .run-id').textContent())?.trim()
      expect(runIdBefore).toBeTruthy()

      // The pointer the recovery reads is a localStorage record, not a cookie
      // and not server-side session state.
      const stored = await page.evaluate(() => window.localStorage.getItem('validator-active-run'))
      expect(stored).toBeTruthy()
      const parsed = JSON.parse(stored as string) as {
        version: number
        runId: string
        workflowId: string
      }
      expect(parsed.version).toBe(1)
      expect(parsed.workflowId).toBe('idea-validator')
      expect(parsed.runId.startsWith(runIdBefore as string)).toBe(true)

      await page.reload()
      await expect(page.locator('.vue-flow__node').first()).toBeVisible()

      // `GET /api/runs/{id}` plus a frame replay must put the console back
      // where it was: same run, same open gate, socket reattached, no gap.
      await waitForGate(page, 'Confirm scope')
      await expect(page.locator('.status-panel .run-id')).toHaveText(runIdBefore as string)
      await expect(statusBadge(page)).toHaveText(/waiting/i)
      await expect(page.locator('.live-status')).toHaveText(/connected/i)
      await expect(page.locator('.status-panel .stream-line')).toContainText('0 dropped')
      await expect(page.locator('.workflow-node[aria-label="Scoper, Completed"]')).toHaveCount(1)
      await expect(page.locator('.error-banner')).toHaveCount(0)

      // The restored gate is live, not a screenshot: it still accepts a reply.
      await approveGate(page)
      await waitForGate(page, 'Review verdict')
      expect(watch.unexpected).toEqual([])
    },
  )
})
