import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

/**
 * The cast, in a real browser — `docs/run-shell/DEFINITION-OF-DONE.md`
 * T2.6, T2.7, G3, T1, and the easy-to-skip states S1–S6.
 *
 * ## What this file is, and what it is NOT
 *
 * It was written by the verification worker (RV) BEFORE the builders landed,
 * against the DOM contract in the build brief rather than against the DOM as it
 * stood that morning. That is deliberate and it is the only ordering that makes
 * these assertions evidence: a spec written after the fact asserts whatever the
 * implementation happened to produce, which is the shape of test this repository
 * keeps recording as "green for the wrong reason"
 * (`docs/gotchas-and-insights.md`, the section on exactly that).
 *
 * So a failure here is a statement about one of two things, and the message on
 * each assertion says which: the product does not meet the contract, or the
 * contract moved and this file was not told. Neither is fixed by relaxing an
 * assertion.
 *
 * ## The DOM contract these assertions are written against
 *
 * Every character is one `<AgentCharacter>`:
 *
 *   - root element `.pip`, carrying `data-character="<seed>"`,
 *     `data-state="idle|working|speaking|blocked|blocked-error|done"`,
 *     `data-parts`, `role="img"` and an `aria-label`;
 *   - animated parts are DESCENDANTS of `.pip` (`.pip--working` and
 *     `.pip--speaking` loop; idle, blocked and done are static; under reduced
 *     motion every part resolves `animation-name: none`; a pip that is offscreen
 *     has its parts `animation-play-state: paused`).
 *
 * On the graph, each node card `.workflow-node` inside a Vue Flow
 * `.vue-flow__node[data-id]` that represents an AGENT mounts ONE `.pip` in its
 * crew slot. On the trace, `ChatRail` rows `.trace-entry` carry `data-node` and
 * `data-identity` and hold their character in `.trace-avatar > .pip`; the
 * dialogue rail's entries do the same in `.dialogue-avatar`.
 *
 * **A gate is characterless, and so is every other piece of plumbing.** Ruled by
 * the orchestrator on 2026-09-05: a human being asked for something is not a
 * cast member, and giving a person's turn a cartoon face would be the one place
 * in this console where the cast lied about who did the work. Gate, router,
 * output, start, step and the quarantine node therefore mount NO `.pip` — they
 * keep their per-kind icon. The consequence for the `blocked` pose is the
 * interesting half: while the run waits at a gate, the pose lands on the AGENT
 * THAT FED THAT GATE (the `from` of the last edge into it), because that is
 * whose work is actually stopped. For the validator's scope gate that is
 * `scope_idea`, labelled "Scoper".
 *
 * `.trace-entry .trace-line` is the one-sentence text and `.trace-entry details`
 * is the per-row disclosure, closed by default.
 *
 * ## Which backend, and what it costs
 *
 * The same one every other spec here uses, and never :8000. From the repository
 * root:
 *
 *   $env:SYNTHETIC="1"; $env:SYNTHETIC_BRANCH_DELAY_SECONDS="5"; $env:PORT="8099"
 *   $env:CREDENTIALS_MASTER_KEY="Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="
 *   .\.venv\Scripts\serve.exe
 *
 * `SYNTHETIC_BRANCH_DELAY_SECONDS=5` is NOT optional for the two mid-run tests.
 * Without it a research branch finishes in single-digit milliseconds and there
 * is no `working` character to photograph — the assertions that need it say so
 * in their own failure message rather than timing out anonymously, which is the
 * lesson `e2e/visual/run-canvas.spec.ts` records at length.
 *
 * Zero cost: `SYNTHETIC=1` swaps the crew factories and nothing else. Tests that
 * press Launch are tagged `@launch`, as everywhere in this suite; against a paid
 * origin run `--grep-invert @launch`.
 *
 * ## Evidence
 *
 * Screenshots and text artifacts land under `docs/run-shell/evidence/`, whose
 * PNG exception `.gitignore` already carries. The paths are the ones the
 * definition of done names, and nothing else in this file invents one.
 * `RUN_SHELL_EVIDENCE` overrides the root for a dry run.
 */

/* ------------------------------------------------------------------ evidence */

/**
 * `docs/run-shell/evidence`, resolved from the working directory Playwright was
 * invoked in — `frontend/`, the same assumption `e2e/capture-run.spec.ts`
 * already makes about `benchmarks/ours/11`.
 */
const EVIDENCE = process.env.RUN_SHELL_EVIDENCE
  ? path.resolve(process.env.RUN_SHELL_EVIDENCE)
  : path.resolve(process.cwd(), '..', 'docs', 'run-shell', 'evidence')

function evidencePath(...parts: string[]): string {
  const target = path.join(EVIDENCE, ...parts)
  mkdirSync(path.dirname(target), { recursive: true })
  return target
}

/**
 * A full-page capture at a named evidence path.
 *
 * `expect.soft` is used here and NOWHERE else in this file. The definition of
 * done says a capture must exist on disk; it does not make the capture the
 * criterion. A soft check records a missing file and lets the run go on to the
 * assertions that ARE the criterion, so one unwritable path cannot cost a
 * verifier the whole measurement.
 */
async function shot(page: Page, ...parts: string[]): Promise<void> {
  const target = evidencePath(...parts)
  await page.screenshot({ path: target, fullPage: false })
  expect.soft(existsSync(target), `capture not written: ${target}`).toBe(true)
}

async function shotOf(target: Locator, page: Page, ...parts: string[]): Promise<void> {
  const file = evidencePath(...parts)
  await target.screenshot({ path: file })
  expect.soft(existsSync(file), `capture not written: ${file}`).toBe(true)
  // `page` is taken so the signature reads the same as `shot` at every call
  // site; nothing else needs it.
  void page
}

function writeEvidence(contents: string, ...parts: string[]): void {
  const target = evidencePath(...parts)
  writeFileSync(target, contents, 'utf-8')
  expect.soft(existsSync(target), `evidence not written: ${target}`).toBe(true)
}

/* ------------------------------------------------------------- console rules */

/**
 * Nothing is tolerated, for `studio.spec.ts`'s reason: the one exemption this
 * suite ever had (a `/favicon.ico` 404) outlived its cause by months, and an
 * exemption that outlives its cause widens silently.
 */
const ALLOWED_CONSOLE_ERROR: RegExp | null = null

interface ConsoleWatch {
  unexpected: string[]
}

function watchConsole(page: Page): ConsoleWatch {
  const watch: ConsoleWatch = { unexpected: [] }
  const record = (text: string): void => {
    if (!ALLOWED_CONSOLE_ERROR?.test(text)) watch.unexpected.push(text)
  }
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text())
  })
  page.on('pageerror', (error) => record(`uncaught: ${error.message}`))
  return watch
}

/* ------------------------------------------------------------------ contract */

/** The five plus one states `AgentCharacter` declares. */
const STATES = ['idle', 'working', 'speaking', 'blocked', 'blocked-error', 'done'] as const
type PipState = (typeof STATES)[number]

/** A pip is "live" in exactly these two states; both animate, neither is terminal. */
const LIVE_STATES: PipState[] = ['working', 'speaking']

/**
 * Plan 11's bound, restated by T2.7: at most twelve character animations may be
 * running at once. It is a bound on the WHOLE cast, not per character, and it is
 * counted in CSS ANIMATIONS — each state is one animation, so twelve is twelve
 * live characters and not three characters with four moving parts each.
 */
const MAX_LIVE_ANIMATIONS = 12

/**
 * The node kinds that carry no character, by the ruling in the docblock.
 *
 * Written as KINDS rather than as the validator's node ids on purpose: G1 puts a
 * flow through this shell that did not exist when the cast was built, and a
 * hard-coded id list would pass that run by saying nothing. `WorkflowNode`
 * applies `is-${kind}` to the card, which is the same fact from the other side.
 */
const CHARACTERLESS_KINDS = ['gate', 'router', 'quarantine', 'output', 'start', 'step'] as const

/** T2.1's line budget, and T1.3's raw-code regex, both quoted from the DoD. */
const MAX_TRACE_LINE_CHARS = 140
const SNAKE_CASE = /\b[A-Z][A-Z0-9]+(_[A-Z0-9]+)+\b/g

/** S3's floor: "a run of ≥ 119 events". See `runLongToCompletion` for how. */
const S3_MIN_FRAMES = 119

/**
 * The only SNAKE_CASE the DoD admits anywhere in the run shell: the two log
 * formats named on the download control, and the model ids the trace discloses.
 * Run ids are lowercase UUIDs and cannot match the regex at all, which is why
 * they need no entry here.
 */
const SNAKE_CASE_ALLOWED = new Set(['NDJSON', 'ZIP'])

function rawCodesIn(text: string): string[] {
  return (text.match(SNAKE_CASE) ?? []).filter((token) => !SNAKE_CASE_ALLOWED.has(token))
}

/* ------------------------------------------------------------------ locators */

function launchButton(page: Page): Locator {
  return page.locator('[data-testid="launch-button"]')
}

function statusBadge(page: Page): Locator {
  return page.locator('.status-panel .status-badge')
}

function gateCard(page: Page): Locator {
  return page.locator('.gate-card')
}

function traceRail(page: Page): Locator {
  return page.locator('.chat-rail')
}

function traceRows(page: Page): Locator {
  return page.locator('.chat-rail .trace-entry')
}

function traceLines(page: Page): Locator {
  return page.locator('.chat-rail .trace-entry .trace-line')
}

/**
 * The status the shell is reporting.
 *
 * `data-status` on the chip is the contract; the visible text is the documented
 * fallback, because the chip has carried its status as prose since before this
 * work and a test that could only read the attribute would fail on the wording
 * rather than on the state.
 */
async function statusValue(page: Page): Promise<string> {
  const chip = statusBadge(page).first()
  const attribute = await chip.getAttribute('data-status')
  if (attribute) return attribute.trim().toLowerCase()
  return (await chip.innerText()).trim().toLowerCase()
}

/* -------------------------------------------------------------- the journey */

async function openStudio(page: Page): Promise<void> {
  await page.goto('/')
  await expect(page.locator('.vue-flow__node').first()).toBeVisible()
}

/**
 * Launch through Review, waiting out the admission limiter rather than tripping
 * over it.
 *
 * Two things are declared rather than inherited, and each one has cost this
 * suite a red before:
 *
 *  - `useValidatorRun` defaults `gatesMode` to `'auto'`. Against a backend with
 *    `VALIDATOR_ALLOW_AUTO_GATES` set, the run then completes unattended and no
 *    gate ever opens; against one without it, `create_run` answers 403 and no
 *    run starts. `studio.spec.ts` records both. Clicking Review states the
 *    requirement.
 *  - `RUN_RATE_LIMIT_MAX_RUNS` is ten runs per sixty seconds. This file adds
 *    eight launches to a suite that already had a dozen, so a 429 is reachable
 *    on a full run. Waiting it out is the correct behaviour — the server
 *    computes `Retry-After` and `CORS_EXPOSE_HEADERS` puts it on the wire for
 *    exactly this reader — and raising the limit would turn off what makes an
 *    unauthenticated Launch button survivable at all.
 */
async function launchRun(page: Page, idea: string): Promise<void> {
  const review = page.getByRole('button', { name: 'Review', exact: true })
  if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
  await expect(review).toHaveAttribute('aria-pressed', 'true')

  await page.locator('#idea').fill(idea)
  await expect(launchButton(page)).toBeEnabled()

  const limited = page.locator('[role="alert"]').filter({ hasText: /too many runs/i })
  for (let attempt = 0; attempt < 8; attempt += 1) {
    await launchButton(page).click()
    // WAITED FOR rather than counted: counting straight after the click races
    // the render, so the absence of the alert has to be a timeout and not a
    // snapshot taken before Vue had a chance to paint it.
    try {
      await limited.waitFor({ state: 'visible', timeout: 2_000 })
    } catch {
      return
    }
    await page.waitForTimeout(6_000)
  }
  throw new Error('the admission limiter refused eight launches in a row')
}

async function waitForGate(page: Page, title: string): Promise<void> {
  await expect(gateCard(page).locator('h2')).toHaveText(title, { timeout: 60_000 })
}

async function approveGate(page: Page): Promise<void> {
  await gateCard(page).getByRole('button', { name: /^Approve/ }).click()
}

async function waitForCompletion(page: Page): Promise<void> {
  await expect(statusBadge(page)).toHaveText(/finished/i, { timeout: 90_000 })
}

/** `seq N` off the stream line — the client's high-water mark of frames. */
async function readSequence(page: Page): Promise<number> {
  const text = await page.locator('.status-panel .stream-line').innerText()
  return Number(/seq\s+(\d+)/.exec(text)?.[1] ?? -1)
}

/**
 * Send one gate back for a revision and wait for the SAME gate to re-open.
 *
 * The wait is on the card DETACHING first, and that ordering is not tidiness.
 * `waitForGate` only asserts the heading, which never changed — so polling it
 * straight after the click would pass against the card that is still on screen
 * unanswered, and the Approve that follows would land on a gate already replied
 * to and take a 409. `pendingGate` is nulled by `gate_closed`, which unmounts
 * the card, so its absence is the one unambiguous "the reply was taken".
 *
 * The feedback note is located as `form textarea` rather than by its label: the
 * scope gate offers five fields of which feedback is the only textarea, and the
 * verdict gate prunes every field but that one. One selector, both gates, no
 * dependence on the copy.
 */
async function reviseGate(page: Page, title: string, note: string): Promise<void> {
  const before = await readSequence(page)
  await gateCard(page).locator('form textarea').first().fill(note)
  await gateCard(page).getByRole('button', { name: /^Revise/ }).click()

  await expect(gateCard(page), `the ${title} gate did not take the Revise reply`).toHaveCount(0, {
    timeout: 60_000,
  })
  await waitForGate(page, title)
  await expect
    .poll(() => readSequence(page), {
      timeout: 60_000,
      message: 'a revise turn produced no new frames',
    })
    .toBeGreaterThan(before)
  await expect(gateCard(page).getByRole('button', { name: /^Approve/ })).toBeEnabled()
}

/** Launch, approve both durable gates, and come back when the run is finished. */
async function runToCompletion(page: Page, idea: string): Promise<void> {
  await launchRun(page, idea)
  await waitForGate(page, 'Confirm scope')
  await approveGate(page)
  await waitForGate(page, 'Review verdict')
  await approveGate(page)
  await waitForCompletion(page)
}

/**
 * S3's long run: the same journey with three revise turns folded into it.
 *
 * A straight-through synthetic run is **96–97 frames**, and S3 asks for a run of
 * at least 119 events. The frames are not invented to reach that number: a
 * revise is a first-class reply the console offers on both gates, and the
 * synthetic double models it properly (`route_scope -> revise_scope ->
 * confirm_scope`, bounded at `SYNTHETIC_MAX_REVISE_TURNS = 3` per gate). Each
 * turn re-runs the node and re-opens the gate, so the run genuinely is longer
 * rather than padded.
 *
 * Two at the scope gate and one at the verdict gate, both inside the double's
 * own cap. Fixed rather than adaptive: a loop that revised "until the count is
 * high enough" would make the artifact a different length on every machine, and
 * the frame badge is one of the numbers the definition of done asks to be
 * recorded.
 */
async function runLongToCompletion(page: Page, idea: string): Promise<void> {
  await launchRun(page, idea)
  await waitForGate(page, 'Confirm scope')
  await reviseGate(page, 'Confirm scope', 'Narrow the target user to single-site teams first.')
  await reviseGate(page, 'Confirm scope', 'And say which sources would settle the demand question.')
  await approveGate(page)
  await waitForGate(page, 'Review verdict')
  await reviseGate(page, 'Review verdict', 'Re-score demand against the revised scope.')
  await approveGate(page)
  await waitForCompletion(page)
}

/* ------------------------------------------------------- reading the cast */

interface NodeCast {
  seed: string
  state: string
  label: string
}

/** Every graph node that mounts a character, by Vue Flow node id. */
async function graphCast(page: Page): Promise<Record<string, NodeCast>> {
  return page.evaluate(() => {
    const out: Record<string, { seed: string; state: string; label: string }> = {}
    for (const host of Array.from(document.querySelectorAll('.vue-flow__node[data-id]'))) {
      const id = host.getAttribute('data-id')
      const pip = host.querySelector('.workflow-node .pip')
      if (!id || !pip) continue
      out[id] = {
        seed: pip.getAttribute('data-character') ?? '',
        state: pip.getAttribute('data-state') ?? '',
        label: host.querySelector('.workflow-node')?.getAttribute('aria-label') ?? '',
      }
    }
    return out
  })
}

/**
 * Any node of a characterless kind that mounted a character anyway.
 *
 * Returns `"<node id> (<kind>)"` per offender, so the failure names the card
 * rather than reporting a count nobody can act on.
 */
async function characterlessOffenders(page: Page): Promise<string[]> {
  return page.evaluate((kinds: readonly string[]) => {
    const out: string[] = []
    for (const host of Array.from(document.querySelectorAll('.vue-flow__node[data-id]'))) {
      const card = host.querySelector('.workflow-node')
      if (!card) continue
      const kind = kinds.find((candidate) => card.classList.contains(`is-${candidate}`))
      if (kind && card.querySelector('.pip')) {
        out.push(`${host.getAttribute('data-id')} (${kind})`)
      }
    }
    return out
  }, CHARACTERLESS_KINDS)
}

interface TraceCastRow {
  node: string
  identity: string
  seed: string
  state: string
}

/** Every trace row that carries a character, oldest first. */
async function traceCast(page: Page): Promise<TraceCastRow[]> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll('.chat-rail .trace-entry[data-node]'))
      .map((row) => {
        const pip = row.querySelector('.trace-avatar .pip')
        return {
          node: row.getAttribute('data-node') ?? '',
          identity: row.getAttribute('data-identity') ?? '',
          seed: pip?.getAttribute('data-character') ?? '',
          state: pip?.getAttribute('data-state') ?? '',
          hasPip: pip !== null,
        }
      })
      .filter((row) => row.hasPip && row.node.length > 0)
      .map(({ node, identity, seed, state }) => ({ node, identity, seed, state })),
  )
}

interface LiveAnimation {
  pip: string
  name: string
  inView: boolean
  rect: { x: number; y: number; width: number; height: number }
  playState: string
}

/**
 * The animations the engine has actually STARTED inside a character, and where
 * their character sits relative to the viewport.
 *
 * `document.getAnimations()` rather than `getComputedStyle(el).animationName`,
 * for the reason `e2e/visual/run-canvas.spec.ts` sets out: the computed style
 * echoes back whatever the declaration said, whether or not a `@keyframes` of
 * that name resolved. Only `getAnimations()` distinguishes "the rule is still
 * there" from "the rule still works".
 *
 * The in-view test is applied to the enclosing `.pip`, not to the animated part.
 * A part can be an SVG `<g>` or a pseudo-element whose own box is degenerate,
 * and T2.7's subject is the CHARACTER being offscreen — one rectangle per
 * character is both the honest unit and the one that cannot produce a phantom
 * red on a zero-area group.
 */
async function liveAnimations(page: Page): Promise<LiveAnimation[]> {
  return page.evaluate(() => {
    const width = window.innerWidth
    const height = window.innerHeight
    const out: LiveAnimation[] = []
    for (const animation of document.getAnimations()) {
      const effect = animation.effect as KeyframeEffect | null
      const target = effect?.target ?? null
      if (!target) continue
      const pip = target.closest('.pip')
      if (!pip) continue
      if (animation.playState !== 'running') continue
      const box = pip.getBoundingClientRect()
      out.push({
        pip: pip.getAttribute('data-character') ?? '',
        name: (animation as CSSAnimation).animationName ?? '',
        playState: animation.playState,
        rect: { x: box.x, y: box.y, width: box.width, height: box.height },
        inView:
          box.width > 0 &&
          box.height > 0 &&
          box.right > 0 &&
          box.bottom > 0 &&
          box.left < width &&
          box.top < height,
      })
    }
    return out
  })
}

/* ========================================================================== */
/* S1 — the shell before anything has run                                     */
/* ========================================================================== */

test.describe('the cast at rest', () => {
  test('S1: every character is idle before a run, and the shell is not blank', async ({ page }) => {
    const watch = watchConsole(page)
    await openStudio(page)
    await expect(page.locator('.workflow-node').first()).toBeVisible()

    await shot(page, 'S', 'empty.png')

    const cast = await graphCast(page)
    const ids = Object.keys(cast)
    expect(
      ids.length,
      'no node on the canvas mounts a `.pip`; the cast is not wired into WorkflowNode',
    ).toBeGreaterThan(0)

    for (const [id, node] of Object.entries(cast)) {
      expect(node.state, `${id} is not idle before a run`).toBe('idle')
      expect(node.seed, `${id} has no data-character seed`).not.toBe('')
    }

    // Plumbing stays plumbing, at rest as much as mid-run.
    expect(
      await characterlessOffenders(page),
      'a gate, router, output or quarantine node mounted a character; only agents are cast',
    ).toEqual([])

    // The trace explains what will happen rather than showing an empty box.
    await expect(traceRail(page)).toBeVisible()

    expect(watch.unexpected).toEqual([])
  })
})

/* ========================================================================== */
/* S2 + the five states                                                       */
/* ========================================================================== */

test.describe('the states a character passes through', () => {
  test(
    'S2: a working character and an interpreted line inside two seconds, then blocked, then done',
    { tag: '@launch' },
    async ({ page }) => {
      test.setTimeout(240_000)
      const watch = watchConsole(page)
      await openStudio(page)

      await launchRun(page, 'A claim auditor for newsroom drafts')

      /*
       * S2's two seconds are measured from the click, and both halves are
       * asserted before the capture so a slow first paint fails HERE rather
       * than leaving a capture that looks fine and a criterion nobody checked.
       */
      const deadline = Date.now() + 2_000
      await expect
        .poll(
          async () => (await liveCharacters(page)).length,
          {
            timeout: 2_000,
            message:
              'no character reached `working` within 2s of Launch (S2). If every branch ' +
              'finished instantly, start the backend with SYNTHETIC_BRANCH_DELAY_SECONDS=5.',
          },
        )
        .toBeGreaterThan(0)
      await expect(traceRows(page).first()).toBeVisible({
        timeout: Math.max(250, deadline - Date.now()),
      })
      await shot(page, 'S', 'first-run.png')

      /*
       * ---- blocked: the gate is a person, so its FEEDER wears the wait ----
       *
       * The gate node itself is characterless by ruling (see the docblock), so
       * the assertion is in two halves and the second is the one that carries
       * the criterion. `confirm_scope` mounts nothing; `scope_idea` — the `from`
       * of the last edge into that gate, and the agent whose work is actually
       * stopped — wears `blocked`.
       *
       * The ids come from `src/data/mockGraph.ts`, which is asserted node for
       * node against the live descriptor by `frontend/tests/mockGraph.spec.ts`,
       * so they are the server's ids and not this file's guess at them.
       */
      await waitForGate(page, 'Confirm scope')
      await expect(
        page.locator('.vue-flow__node[data-id="confirm_scope"] .workflow-node .pip'),
        'the gate node mounted a character; a human being asked for something is not a cast member',
      ).toHaveCount(0)

      const feeder = page.locator('.vue-flow__node[data-id="scope_idea"] .workflow-node .pip')
      await expect(
        feeder,
        'the agent feeding the paused gate does not mount exactly one character',
      ).toHaveCount(1)
      await expect(
        feeder,
        'the agent feeding the paused gate is not `blocked` while a human is being asked',
      ).toHaveAttribute('data-state', 'blocked')

      expect(
        await characterlessOffenders(page),
        'a gate, router, output or quarantine node mounted a character mid-run',
      ).toEqual([])

      await approveGate(page)
      await waitForGate(page, 'Review verdict')
      await approveGate(page)
      await waitForCompletion(page)

      // ---- done: every agent that ran ends in the terminal pose ------------
      const cast = await graphCast(page)
      for (const label of [
        'Scoper',
        'Market Analyst',
        'Sentiment Analyst',
        'Feasibility Analyst',
        'Synthesist',
        'Reporter',
      ]) {
        const entry = Object.entries(cast).find(([, node]) => node.label.startsWith(`${label},`))
        expect(entry, `no node card carries the ${label} character after completion`).toBeTruthy()
        expect(entry![1].state, `${label} did not reach \`done\``).toBe('done')
      }

      // No character may be left mid-animation on a finished run.
      const stillLive = Object.entries(cast).filter(([, node]) =>
        LIVE_STATES.includes(node.state as PipState),
      )
      expect(
        stillLive.map(([id]) => id),
        'characters are still working or speaking after the run completed',
      ).toEqual([])

      expect(watch.unexpected).toEqual([])
    },
  )
})

/** The node ids whose character is currently working or speaking. */
async function liveCharacters(page: Page): Promise<string[]> {
  const cast = await graphCast(page)
  return Object.entries(cast)
    .filter(([, node]) => LIVE_STATES.includes(node.state as PipState))
    .map(([id]) => id)
}

/* ========================================================================== */
/* T2.6 — one cast, two views                                                 */
/* ========================================================================== */

test.describe('the graph and the trace show the same cast', () => {
  test(
    'T2.6: mid-run, every running node and its trace rows carry one seed and agree on the state',
    { tag: '@launch' },
    async ({ page }) => {
      test.setTimeout(240_000)
      const watch = watchConsole(page)
      await openStudio(page)

      await launchRun(page, 'A rota assistant for community pharmacies')
      await waitForGate(page, 'Confirm scope')
      await approveGate(page)

      /*
       * The fan-out is the moment worth photographing: three branches, one of
       * them in flight for five seconds. Waiting on "some node is live AND that
       * node already has a trace row" is what makes the comparison below
       * possible at all — a node that started a millisecond ago has a character
       * and no row yet, and asserting into that window would be a flake rather
       * than a gate.
       */
      await expect
        .poll(
          async () => {
            const live = await liveCharacters(page)
            if (live.length === 0) return 0
            const rows = await traceCast(page)
            return live.filter((id) => rows.some((row) => row.node === id)).length
          },
          {
            timeout: 60_000,
            message:
              'no node was live in both views at once. If the branches finish instantly, ' +
              'start the backend with SYNTHETIC_BRANCH_DELAY_SECONDS=5 — see this file docblock.',
          },
        )
        .toBeGreaterThan(0)

      const cast = await graphCast(page)
      const rows = await traceCast(page)
      await shot(page, 'T2', 'tie-in.png')

      const sharedNodes = Object.keys(cast).filter((id) => rows.some((row) => row.node === id))
      expect(
        sharedNodes.length,
        'no node id appears in both the graph and the trace; the tie-in cannot be checked',
      ).toBeGreaterThan(0)

      for (const id of sharedNodes) {
        const node = cast[id]
        const mine = rows.filter((row) => row.node === id)

        // ONE seed per node, across every row it ever produced. A seed that
        // drifts row to row is the failure this criterion exists to catch:
        // two pictures of one agent is worse than none.
        for (const row of mine) {
          expect(
            row.seed,
            `trace row for ${id} (identity "${row.identity}") carries a different character ` +
              `seed than the node card: ${row.seed} vs ${node.seed}`,
          ).toBe(node.seed)
        }

        if (!LIVE_STATES.includes(node.state as PipState)) continue

        /*
         * The state comparison uses the node's LATEST row.
         *
         * Earlier rows are history — the frame that produced them is minutes
         * old by the end of a run — so requiring every row to carry the live
         * state would be asserting that the trace is not a log. T2.6's words
         * are "the same state at the same moment", and the row at the bottom of
         * the rail is the one on screen at this moment.
         */
        const latest = mine[mine.length - 1]
        expect(
          latest.state,
          `${id} is "${node.state}" on the canvas but "${latest.state}" in the trace`,
        ).toBe(node.state)
        expect(LIVE_STATES).toContain(latest.state as PipState)
      }

      expect(watch.unexpected).toEqual([])
    },
  )
})

/* ========================================================================== */
/* G3 — determinism across a reload                                           */
/* ========================================================================== */

test.describe('the character on a node is deterministic', () => {
  test(
    'G3: the same node keeps the same character across a page reload',
    { tag: '@launch' },
    async ({ page }) => {
      test.setTimeout(240_000)
      const watch = watchConsole(page)
      await openStudio(page)

      await launchRun(page, 'A dosage-check assistant for community pharmacists')
      // After the first frames, so the run is real and the reload has something
      // to recover — a map read off an idle canvas would prove only that a
      // constant is constant.
      await expect(traceRows(page).first()).toBeVisible({ timeout: 60_000 })
      await waitForGate(page, 'Confirm scope')

      const before = await graphCast(page)
      const beforeSeeds = Object.fromEntries(
        Object.entries(before).map(([id, node]) => [id, node.seed]),
      )
      expect(Object.keys(beforeSeeds).length).toBeGreaterThan(0)

      await page.reload()
      await expect(page.locator('.vue-flow__node').first()).toBeVisible()
      // Recovery, exactly as `studio.spec.ts` asserts it: same run, same gate.
      await waitForGate(page, 'Confirm scope')

      const after = await graphCast(page)
      const afterSeeds = Object.fromEntries(
        Object.entries(after).map(([id, node]) => [id, node.seed]),
      )

      writeEvidence(
        `${JSON.stringify(
          {
            note:
              'G3, e2e/cast.spec.ts. Node id to character seed, read off the live canvas ' +
              'before and after a page reload of a run paused at the scope gate.',
            capturedAt: new Date().toISOString(),
            before: beforeSeeds,
            after: afterSeeds,
            identical: JSON.stringify(beforeSeeds) === JSON.stringify(afterSeeds),
          },
          null,
          2,
        )}\n`,
        'G3',
        'reload-map.json',
      )

      expect(
        afterSeeds,
        'the cast was re-rolled by a reload; the character is not a function of identity alone',
      ).toEqual(beforeSeeds)

      expect(watch.unexpected).toEqual([])
    },
  )
})

/* ========================================================================== */
/* T2.7 — motion bounds                                                       */
/* ========================================================================== */

test.describe('motion stays quiet', () => {
  test(
    'T2.7: nothing animates offscreen and no more than twelve character animations run at once',
    { tag: '@launch' },
    async ({ page }) => {
      test.setTimeout(240_000)
      const watch = watchConsole(page)
      await openStudio(page)

      await launchRun(page, 'A triage inbox for single-vet practices')
      await waitForGate(page, 'Confirm scope')
      await approveGate(page)

      await expect
        .poll(async () => (await liveCharacters(page)).length, {
          timeout: 60_000,
          message:
            'no character was live during the fan-out. Start the backend with ' +
            'SYNTHETIC_BRANCH_DELAY_SECONDS=5 — see this file docblock.',
        })
        .toBeGreaterThan(0)

      const running = await liveAnimations(page)

      const offscreen = running.filter((animation) => !animation.inView)
      expect(
        offscreen.map((a) => `${a.pip}:${a.name} at ${JSON.stringify(a.rect)}`),
        'character animations are running on characters outside the viewport',
      ).toEqual([])

      expect(
        running.length,
        `${running.length} character animations are running at once; plan 11 bounds it at ` +
          `${MAX_LIVE_ANIMATIONS}. Running: ${running.map((a) => `${a.pip}:${a.name}`).join(', ')}`,
      ).toBeLessThanOrEqual(MAX_LIVE_ANIMATIONS)

      expect(watch.unexpected).toEqual([])
    },
  )

  test(
    'T2.7/S5: reduced motion stops every part and keeps every state',
    { tag: '@launch' },
    async ({ page }) => {
      test.setTimeout(240_000)
      const watch = watchConsole(page)

      /*
       * BEFORE navigation, deliberately.
       *
       * A media change applied to a live page re-resolves the cascade but does
       * not re-run whatever a component decided at mount, so emulating after
       * `goto` measures a state production never reaches: a reader with the OS
       * preference set has it set on the first paint. This is also the only
       * ordering under which "the static pose still conveys state" is a claim
       * about what that reader sees rather than about a transition.
       */
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await openStudio(page)

      await launchRun(page, 'A locum rota planner for independent pharmacies')
      await waitForGate(page, 'Confirm scope')
      await approveGate(page)

      await expect
        .poll(async () => (await liveCharacters(page)).length, {
          timeout: 60_000,
          message:
            'no character was live under reduced motion. Start the backend with ' +
            'SYNTHETIC_BRANCH_DELAY_SECONDS=5 — see this file docblock.',
        })
        .toBeGreaterThan(0)

      await shot(page, 'T2', 'reduced-motion.png')

      const audit = await page.evaluate(() => {
        const problems: string[] = []
        const states: string[] = []
        const pips = Array.from(document.querySelectorAll('.pip'))
        for (const pip of pips) {
          const seed = pip.getAttribute('data-character') ?? '(no seed)'
          const state = pip.getAttribute('data-state') ?? ''
          if (!state) problems.push(`${seed} carries no data-state under reduced motion`)
          else states.push(state)
          for (const el of [pip, ...Array.from(pip.querySelectorAll('*'))]) {
            const name = window.getComputedStyle(el).animationName
            if (name && name !== 'none') {
              problems.push(`${seed} > ${el.nodeName.toLowerCase()} still declares ${name}`)
            }
          }
        }
        return { problems, states, pips: pips.length }
      })

      expect(audit.pips, 'no characters were on screen to audit').toBeGreaterThan(0)
      expect(
        audit.problems,
        'reduced motion did not silence every character part, or a state was dropped with it',
      ).toEqual([])
      // The pose still says something: at least one character is not idle.
      expect(
        audit.states.some((state) => state !== 'idle'),
        'every character read `idle` under reduced motion, so the pose conveys no state',
      ).toBe(true)

      // And the engine agrees with the computed style — the run-canvas lesson:
      // a declaration and a resolved animation are different measurements.
      expect(
        (await liveAnimations(page)).map((a) => `${a.pip}:${a.name}`),
        'the engine is still running character animations under reduced motion',
      ).toEqual([])

      expect(watch.unexpected).toEqual([])
    },
  )
})

/* ========================================================================== */
/* T2.1 (browser half), S3, T1 and the T3 after-captures                      */
/* ========================================================================== */

test.describe('the completed run', () => {
  test(
    'T2.1/S3/T1/T3: a 119-event run stays legible — sentences in the trace, a reason in the report, three widths on disk',
    { tag: '@launch' },
    async ({ page }) => {
      test.setTimeout(300_000)
      const watch = watchConsole(page)
      await openStudio(page)

      await runLongToCompletion(page, 'A claim auditor that checks numbers in newsroom drafts')

      /*
       * CAPTURES FIRST, ASSERTIONS SECOND, and the order is load-bearing.
       *
       * Six of the definition of done's named artifacts are produced by this one
       * run. A hygiene assertion that fires before the captures leaves the cold
       * reader with nothing to read and the verdict table with six blank rows —
       * so everything that only needs the run to have finished is written to
       * disk before anything that can fail is evaluated.
       */
      await shot(page, 'T3', 'after-1440.png')

      // S3: the newest line is the one on screen.
      await traceRail(page).locator('.rail-list').evaluate((el) => {
        el.scrollTop = el.scrollHeight
      })
      await page.waitForTimeout(250)
      await shotOf(traceRail(page), page, 'T2', 'trace-completed.png')
      await shot(page, 'S', 'long-run.png')

      // T1: the report's own header, clipped the way the before-capture was —
      // from the top of `.report-head` to the bottom of the scores.
      const report = page.locator('.report-panel')
      await expect(report, 'the completed run did not open its report').toBeVisible()
      const clip = await page.evaluate(() => {
        const head = document.querySelector('.report-panel .report-head')
        if (!head) return null
        const last =
          document.querySelector('.report-panel .verdict-summary') ??
          document.querySelector('.report-panel .report-flags') ??
          head
        const top = head.getBoundingClientRect()
        const bottom = last.getBoundingClientRect()
        return {
          x: Math.max(0, Math.floor(top.x)),
          y: Math.max(0, Math.floor(top.y)),
          width: Math.ceil(top.width),
          height: Math.ceil(bottom.bottom - top.top),
        }
      })
      expect(clip, 'the report panel has no `.report-head` to clip').not.toBeNull()
      const headerFile = evidencePath('T1', 'report-header.png')
      await page.screenshot({ path: headerFile, clip: clip! })
      expect.soft(existsSync(headerFile), `capture not written: ${headerFile}`).toBe(true)

      // T3: the other two widths and the light theme, on the same finished run
      // so the pixels stay comparable — the before set was captured the same way.
      await page.setViewportSize({ width: 1180, height: 800 })
      await page.waitForTimeout(400)
      await shot(page, 'T3', 'after-1180.png')

      await page.setViewportSize({ width: 1440, height: 900 })
      await page.waitForTimeout(400)
      /*
       * `data-theme`, not `emulateMedia`.
       *
       * The run shell never calls `useStudioTheme` — only `BuilderView` does —
       * and `tokens.css` carries the light palette under `:root[data-theme='light']`
       * with no `prefers-color-scheme` block for this view. So flipping the media
       * query alone produces DARK PIXELS UNDER A LIGHT FILENAME, which is exactly
       * what `e2e/capture-run.spec.ts` still does and what the before-capture
       * record calls out. Both are set here: the attribute is what paints, and
       * the media query keeps anything that does read it consistent.
       */
      await page.emulateMedia({ colorScheme: 'light' })
      await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'))
      await page.waitForTimeout(400)
      await shot(page, 'T3', 'after-1440-light.png')
      await page.evaluate(() => document.documentElement.removeAttribute('data-theme'))
      await page.emulateMedia({ colorScheme: 'dark' })
      await page.waitForTimeout(300)

      /* ---- now the criteria ------------------------------------------- */

      /*
       * The row count is TWO numbers, because the rail folds.
       *
       * Beyond a 200-row window `ChatRail` hides the older rows behind one
       * "N earlier lines" button, so `.trace-entry` counts what is mounted and
       * not what the run produced. Reading only the mounted count would report
       * a long run as a short one — and it is the fold itself that S3 is partly
       * about ("older rows fold"), so the button is read rather than defeated.
       */
      const visibleRows = await traceRows(page).count()
      const earlier = page.locator('[data-testid="trace-earlier"]')
      const foldedRows = (await earlier.count())
        ? Number(/^(\d+)/.exec((await earlier.innerText()).trim())?.[1] ?? 0)
        : 0
      const rowCount = visibleRows + foldedRows
      expect(rowCount, 'a completed run produced no trace rows at all').toBeGreaterThanOrEqual(1)

      const frames = await readSequence(page)
      const frameBadge = (await page.locator('.status-panel .stream-line').innerText()).trim()
      const railBadge = (await page.locator('.chat-rail .entry-count').innerText()).trim()

      /*
       * The rest of the hygiene sweep needs every row in the DOM, so the fold is
       * opened AFTER the captures — the pictures are of the folded rail, which is
       * the state S3 describes, and the audit is over all of it.
       */
      if (foldedRows > 0) {
        await earlier.click()
        await expect(earlier).toHaveCount(0)
      }

      const auditedRows = await traceRows(page).count()
      const lineCount = await traceLines(page).count()
      expect(
        lineCount,
        'trace rows carry no `.trace-line`; the one-sentence text has no stable hook (T2.1)',
      ).toBe(auditedRows)

      const lines = await traceLines(page).allInnerTexts()

      // The S3 companion is written HERE, before the hygiene verdict, for the
      // same reason the captures came first: a red on line 3 must not cost the
      // cold reader the row count that explains the picture beside it.
      const longest = lines.length ? Math.max(...lines.map((l) => l.trim().length)) : 0
      writeEvidence(
        [
          '# S3 — the long run, as the console finished it',
          '',
          'Written by `e2e/cast.spec.ts` (RV). Companion to `evidence/S/long-run.png`,',
          'captured on the same completed run with the trace rail scrolled to the bottom.',
          '',
          'The run is the ordinary operator journey with **three revise turns** folded in — two',
          'at the scope gate, one at the verdict gate, all inside the synthetic double\'s own',
          '`SYNTHETIC_MAX_REVISE_TURNS = 3` per-gate cap. A straight-through synthetic run is',
          '96–97 frames, and S3 asks for 119; a revise is a reply the console really offers and',
          'the double really models, so the run is longer rather than the number relaxed.',
          '',
          `- captured at: ${new Date().toISOString()}`,
          `- frames the run emitted (\`seq\`): **${frames}** (S3 floor: ${S3_MIN_FRAMES})`,
          `- stream line: \`${frameBadge.replace(/\s+/g, ' ')}\``,
          `- trace rows: **${rowCount}** = ${visibleRows} mounted + ${foldedRows} folded behind`,
          '  the "earlier lines" button',
          `- trace rail badge: **${railBadge}**`,
          `- rows audited after expanding the fold: **${auditedRows}**`,
          `- longest line: **${longest}** chars (budget ${MAX_TRACE_LINE_CHARS})`,
          '- disclosures open by default: **0** (asserted below)',
          '',
          "The stream line carries the run's frame high-water mark (`seq N`) and the dropped",
          'count; the rail badge counts the rows the interpretation layer chose to render, which',
          'is deliberately smaller — frames that cannot be summarised get no row (T2.1).',
          '',
        ].join('\n'),
        'S',
        'long-run.md',
      )

      expect(
        frames,
        `the run emitted ${frames} frames, below S3's ${S3_MIN_FRAMES}. Three revise turns ` +
          'should carry a 96–97 frame synthetic run past it; if the double changed, add a turn ' +
          'in `runLongToCompletion` (the cap is 3 per gate) rather than lowering this floor.',
      ).toBeGreaterThanOrEqual(S3_MIN_FRAMES)

      const problems: string[] = []
      lines.forEach((raw, index) => {
        const line = raw.trim()
        if (line.length === 0) problems.push(`row ${index}: empty line`)
        if (line.length > MAX_TRACE_LINE_CHARS) {
          problems.push(`row ${index}: ${line.length} chars > ${MAX_TRACE_LINE_CHARS} — "${line}"`)
        }
        if (line.includes('\\n')) problems.push(`row ${index}: literal \\n — "${line}"`)
        if (line.includes('{"')) problems.push(`row ${index}: raw JSON — "${line}"`)
        if (/\d+\s*in\s*·\s*\d+\s*out/.test(line)) {
          problems.push(`row ${index}: token counts in the line — "${line}"`)
        }
        const codes = rawCodesIn(line)
        if (codes.length) problems.push(`row ${index}: raw code ${codes.join(', ')} — "${line}"`)
      })
      expect(problems, 'the trace is not one short human sentence per row (T2.1)').toEqual([])

      // Every disclosure closed by default — the whole point of putting the
      // payload behind one is that nobody has to scroll past it.
      await expect(
        page.locator('.chat-rail .trace-entry details[open]'),
        'a per-row disclosure is open by default (T2.1)',
      ).toHaveCount(0)
      await expect(
        page.locator('.chat-rail .trace-entry details'),
        'no row carries a disclosure; the payload has nowhere to sit (T2.1)',
      ).not.toHaveCount(0)

      // T1.3, in the browser rather than over a fixture: no raw internal code
      // reaches the header a cold reader is asked to read.
      const headerText = await page.evaluate(() =>
        ['.report-head', '.report-flags', '.verdict-summary']
          .map((selector) => document.querySelector(`.report-panel ${selector}`))
          .filter((el): el is Element => el !== null)
          .map((el) => (el as HTMLElement).innerText)
          .join('\n'),
      )
      expect(headerText.trim().length, 'the report header rendered no text').toBeGreaterThan(0)
      expect(
        rawCodesIn(headerText),
        'raw SNAKE_CASE reached the report header (T1.3)',
      ).toEqual([])

      expect(watch.unexpected).toEqual([])
    },
  )
})

/* ========================================================================== */
/* S6 — 390x844                                                               */
/* ========================================================================== */

test.describe('the shell at 390x844', () => {
  /*
   * A viewport override rather than the `mobile` project.
   *
   * `playwright.config.ts` gives the mobile project a `testMatch` of exactly two
   * files, and widening it would pull this whole file into a second run at a
   * width six of its tests are not about. `test.use` sets the context viewport
   * before the page exists, which is the same instrument at file scope.
   */
  test.use({ viewport: { width: 390, height: 844 } })

  test(
    'S6: a run drives and finishes at 390px, and nothing overflows sideways',
    { tag: '@launch' },
    async ({ page }) => {
      test.setTimeout(300_000)
      const watch = watchConsole(page)
      await openStudio(page)

      /*
       * The control rail may start collapsed below the narrow breakpoint, which
       * is the right default for a phone and would otherwise read here as "the
       * console cannot be launched". Opening it by the control a person would
       * use keeps the failure honest: if Launch is still unreachable after
       * this, the shell genuinely is not usable at this width.
       */
      const expand = page.getByRole('button', { name: 'Expand control panel' })
      if (await expand.isVisible().catch(() => false)) await expand.click()
      await expect(
        launchButton(page),
        'the run shell cannot be launched at 390x844 (S6)',
      ).toBeVisible()

      await runToCompletion(page, 'A rota assistant for community pharmacies')

      await shot(page, 'S', 'narrow.png')
      await shot(page, 'T3', 'after-390.png')

      const overflow = await page.evaluate(() => ({
        scrollWidth: document.scrollingElement?.scrollWidth ?? 0,
        clientWidth: document.scrollingElement?.clientWidth ?? 0,
      }))
      expect(
        overflow.scrollWidth,
        `the page is ${overflow.scrollWidth}px wide in a 390px viewport, so it scrolls sideways (S6)`,
      ).toBeLessThanOrEqual(390)

      // Something to look at: the canvas, or the report that replaced it.
      const canvasVisible = await page.locator('.validator-flow').isVisible().catch(() => false)
      const reportVisible = await page.locator('.report-panel').isVisible().catch(() => false)
      expect(
        canvasVisible || reportVisible,
        'neither the canvas nor the report is visible at 390px (S6)',
      ).toBe(true)

      // And both rails are still reachable rather than stranded off-screen.
      await expect(
        page.locator('.chat-rail .rail-toggle'),
        'the activity rail toggle is not visible at 390px (S6)',
      ).toBeVisible()
      await expect(
        page.locator('.control-rail .control-toggle'),
        'the control rail toggle is not visible at 390px (S6)',
      ).toBeVisible()

      // The characters survive the width: still one per node, still terminal.
      const cast = await graphCast(page)
      expect(Object.keys(cast).length, 'the cast vanished at 390px').toBeGreaterThan(0)

      expect(watch.unexpected).toEqual([])
    },
  )
})

/* ========================================================================== */
/* S4 — a failure the backend produced                                        */
/* ========================================================================== */

/**
 * The failure route, and the backend it needs.
 *
 * The synthetic VALIDATOR has no failure knob at all — `SYNTHETIC_FAILURE`
 * belongs to the BUILDER runner — so the only honest way to put a failed node in
 * the run shell is `e2e/failure-modes.spec.ts`'s route: publish a gateless
 * builder graph containing a node the backend has been told to fail, hand it to
 * the console through the publish dialog's own "Run it", and launch.
 *
 * That needs a backend started with two extra knobs, and a browser cannot set
 * either:
 *
 *   $env:SYNTHETIC="1"; $env:SYNTHETIC_BRANCH_DELAY_SECONDS="5"; $env:PORT="8099"
 *   $env:CREDENTIALS_MASTER_KEY="Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="
 *   $env:BUILDER_ALLOW_GATELESS_GRAPHS="1"
 *   $env:SYNTHETIC_FAILURE="fm_cast_refusal:refusal:1"
 *   .\.venv\Scripts\serve.exe
 *
 * `BUILDER_ALLOW_GATELESS_GRAPHS` is not optional and its reason is recorded in
 * plan 12's Status: `compile_replay_plan` cannot replay past a human gate, so
 * the failure graphs are gateless and an anonymous caller may only launch a
 * gateless graph with the flag on.
 *
 * The node id is this file's own (`fm_cast_refusal`), so the same backend can
 * serve `failure-modes.spec.ts`, `studio.spec.ts` and `builder.spec.ts`
 * unchanged: no graph of theirs contains it, so no run of theirs fails. The
 * `:1` suffix fails the FIRST attempt only.
 *
 * WITHOUT those knobs this describe SKIPS and says so, rather than failing on an
 * environment gap that reads exactly like a product defect. That is the
 * `SYNTHETIC_BRANCH_DELAY_SECONDS` lesson applied before it costs anybody an
 * afternoon.
 */
const FAILING_NODE = 'fm_cast_refusal'
const AUTHORED_MODEL = 'google/gemini-3.8-flash'

function failingAgent(id: string, source: string) {
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

function failingGraph() {
  return {
    schema: 'builder.flow/v1',
    name: 'cast failure state',
    version: 1,
    input_field: 'idea',
    nodes: [
      { id: 'idea', kind: 'input', label: 'idea', position: { x: 0, y: 0 }, config: { field: 'idea' } },
      failingAgent('safe', 'idea'),
      failingAgent(FAILING_NODE, 'safe'),
      {
        id: 'report',
        kind: 'output',
        label: 'report',
        position: { x: 0, y: 0 },
        config: { body_key: 'markdown_body', source: '${state.out__' + FAILING_NODE + '}' },
      },
    ],
    edges: [
      { id: 'e1', source: 'idea', source_port: 'out', target: 'safe', target_port: 'in' },
      { id: 'e2', source: 'safe', source_port: 'out', target: FAILING_NODE, target_port: 'in' },
      { id: 'e3', source: FAILING_NODE, source_port: 'out', target: 'report', target_port: 'in' },
    ],
    joins: {},
  }
}

let failureKnobPresent: boolean | null = null

/** Publish one throwaway copy and see whether the backend actually fails it. */
async function requireFailureKnob(request: APIRequestContext): Promise<void> {
  if (failureKnobPresent === null) {
    failureKnobPresent = false
    const created = await request.post('/api/builder/workflows', {
      data: { document: failingGraph() },
    })
    if (created.status() === 201) {
      const id = ((await created.json()) as { document: { id: string } }).document.id
      const published = await request.post(`/api/builder/workflows/${id}/publish`)
      if (published.status() === 200) {
        const run = await request.post('/api/sessions/e2e-cast-failure/runs', {
          data: { workflow_id: id, inputs: { idea: 'probe' } },
        })
        if (run.status() === 202) {
          const runId = ((await run.json()) as { run_id: string }).run_id
          const until = Date.now() + 60_000
          while (Date.now() < until) {
            const snapshot = await request.get(`/api/runs/${runId}`)
            if (snapshot.ok()) {
              const body = (await snapshot.json()) as { status: string }
              if (['completed', 'failed', 'cancelled'].includes(body.status)) {
                failureKnobPresent = body.status === 'failed'
                break
              }
            }
            await new Promise((resolve) => setTimeout(resolve, 200))
          }
        }
      }
    }
  }
  test.skip(
    !failureKnobPresent,
    'the backend was started without BUILDER_ALLOW_GATELESS_GRAPHS=1 and ' +
      `SYNTHETIC_FAILURE="${FAILING_NODE}:refusal:1" — see the S4 docblock in e2e/cast.spec.ts`,
  )
}

test.describe('S4 — a failed run', () => {
  test(
    'S4: the failing node wears the blocked-error character and the trace says why in one sentence',
    { tag: '@launch' },
    async ({ page, request }) => {
      test.setTimeout(300_000)
      await requireFailureKnob(request)
      const watch = watchConsole(page)

      // Authored through the API and PUBLISHED through the dialog, which is how
      // a person reaches the console with their own graph. Writing the handoff
      // record into storage instead would test this file's idea of that record
      // rather than the one `PublishDialog` writes, and it is identity-scoped.
      const created = await request.post('/api/builder/workflows', {
        data: { document: failingGraph() },
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

      const failing = page.locator(`.vue-flow__node[data-id="${FAILING_NODE}"]`)
      await expect(failing, 'the console is not drawing the published graph').toBeVisible({
        timeout: 30_000,
      })

      await launchRun(page, 'A scheduling assistant for clinics.')

      // The character, first: this is S4's subject.
      const pip = failing.locator('.workflow-node .pip')
      await expect(pip, 'the failing node mounts no character').toHaveCount(1, { timeout: 90_000 })
      await expect(
        pip,
        'the failing node does not wear the `blocked-error` character (S4)',
      ).toHaveAttribute('data-state', 'blocked-error', { timeout: 90_000 })

      await expect
        .poll(async () => statusValue(page), { timeout: 60_000 })
        .toMatch(/error|failed/)

      const errorRow = page.locator('.chat-rail .trace-entry[data-tone="error"]').last()
      await expect(
        errorRow,
        'the failure produced no trace row with an error tone (S4)',
      ).toBeVisible({ timeout: 30_000 })

      await shot(page, 'S', 'failure.png')

      const line = (await errorRow.locator('.trace-line').innerText()).trim()
      expect(line.length, 'the error line is empty').toBeGreaterThan(0)
      expect(
        line.length,
        `the error line is ${line.length} chars: "${line}"`,
      ).toBeLessThanOrEqual(MAX_TRACE_LINE_CHARS)
      expect(line.includes('{"'), `raw JSON in the error line: "${line}"`).toBe(false)
      expect(rawCodesIn(line), `raw code in the error line: "${line}"`).toEqual([])
      // ONE sentence: a trailing terminator is fine, an internal one followed by
      // more prose is a paragraph wearing a line's clothes.
      const withoutTerminator = line.replace(/[.!?]+$/, '')
      expect(
        /[.!?]\s+\S/.test(withoutTerminator),
        `the error line is more than one sentence: "${line}"`,
      ).toBe(false)

      expect(watch.unexpected).toEqual([])
    },
  )
})
