import { expect, test, type Page } from '@playwright/test'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { gatePass, waitForGateReopen } from './gateReply'
import { DEFAULT_SYNTHETIC_USER, storageKeyFor } from './syntheticUser'

/**
 * T2.8 — "no dropped frames at 119+ events", measured rather than asserted.
 *
 * `docs/run-shell/DEFINITION-OF-DONE.md` asks for one number and one artifact:
 * a Playwright replay of at least 119 frames at live pace, sampling
 * `requestAnimationFrame` intervals, with **zero** intervals over 34 ms (two
 * missed 60 Hz frames) and a p95 at or under 20 ms, written to
 * `docs/run-shell/evidence/T2/perf.json`.
 *
 * ## Where 119 frames come from, and why there are two measurements
 *
 * A straight-through synthetic validator run is **96–97 frames** — counted, not
 * estimated, from `frontend/tests/fixtures/syntheticRun.ndjson` (97, auto-gated)
 * and `syntheticRunGated.ndjson` (96, both gate pairs), which are that stream
 * served byte-for-byte. Neither is 119. The threshold does not move; the run
 * does:
 *
 *  1. **`liveSyntheticRun`** — a real launch, driven through **three revise
 *     turns** (two at the scope gate, one at the verdict gate) before it is
 *     approved. A revise is a reply the console genuinely offers and the double
 *     genuinely models — `route_scope -> revise_scope -> confirm_scope`, capped
 *     at `SYNTHETIC_MAX_REVISE_TURNS = 3` per gate — so each turn re-runs a node
 *     and re-opens a gate, and the run really is longer. It is also the densest
 *     second this console ever has, which makes it the right stress rather than
 *     merely a convenient one. Real WebSocket, real gate round trips, real
 *     reflow.
 *  2. **`fixtureReplay`** — the deterministic one, and the headline. The two
 *     committed frame logs are replayed into the page through
 *     `page.routeWebSocket`: the same socket, the same `applyFrame`, the same
 *     rendering path, only the source of the bytes differs. 34 + 97 = **131
 *     frames**, above the 119 the criterion names, and the same 131 on every
 *     machine. `syntheticRunGated.ndjson` is deliberately NOT added — it is the
 *     same run gated, and counting one stream twice would inflate the figure
 *     without adding a frame the console has not already seen.
 *
 * The app exposes no `?mock=1` and no storage flag — mock mode is reached only
 * when the transport probe fails, and it then plays `data/mockFrames.ts`'s
 * scripted 59 frames rather than either fixture — so hijacking the socket is
 * the only route by which a committed frame log reaches the real client. That
 * is stated here because "replay through the mock path" was the first idea and
 * it does not exist.
 *
 * ## Pace
 *
 * Gaps come from the fixtures' own `ts` values, clamped to 250 ms. The clamp
 * only ever makes the replay DENSER than the run it was taken from — it
 * compresses the two five-second branch waits and nothing else — which is the
 * conservative direction for a dropped-frame measurement. The bursts, where a
 * dozen frames share a millisecond, are left exactly as the backend emitted
 * them, because the burst is the part that costs a frame.
 *
 * ## The refresh-rate caveat, which is a real one
 *
 * 34 ms is two frames at 60 Hz. Headless Chromium does not promise 60 Hz on
 * every machine, and comparing against a rate the browser is not running at
 * would be measuring the harness. So the sampler starts BEFORE navigation and
 * the median interval over the idle page is taken as this environment's refresh
 * estimate; when that estimate is slower than 50 Hz the budgets are widened to
 * twice it, the widening is recorded in `perf.json`, and the assertion message
 * says so. Nothing is silently relaxed and no threshold is invented.
 *
 * ## Backend and cost
 *
 * The free one, never :8000:
 *
 *   $env:SYNTHETIC="1"; $env:SYNTHETIC_BRANCH_DELAY_SECONDS="5"; $env:PORT="8099"
 *   $env:CREDENTIALS_MASTER_KEY="Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="
 *   .\.venv\Scripts\serve.exe
 *
 * Both tests press Launch and are tagged `@launch` accordingly; both cost
 * nothing, because `SYNTHETIC=1` swaps the crew factories. The replay test lets
 * the real POST through so nothing about the launch path is faked, then cancels
 * the run it started — the socket it would have streamed on is ours.
 */

/* ------------------------------------------------------------------ evidence */

const EVIDENCE = process.env.RUN_SHELL_EVIDENCE
  ? path.resolve(process.env.RUN_SHELL_EVIDENCE)
  : path.resolve(process.cwd(), '..', 'docs', 'run-shell', 'evidence')

const PERF_JSON = path.join(EVIDENCE, 'T2', 'perf.json')

/** `frontend/tests/fixtures`, from the directory Playwright was invoked in. */
function fixture(name: string): string {
  return path.resolve(process.cwd(), 'tests', 'fixtures', name)
}

/* ------------------------------------------------------------------ the maths */

/** Two missed frames at 60 Hz, which is what the criterion calls a drop. */
const DROP_BUDGET_MS = 34
const P95_BUDGET_MS = 20
/** Below this the harness is not running at 60 Hz and the budgets are derived. */
const SIXTY_HZ_IDLE_CEILING_MS = 20
/** The criterion's own floor. */
const MIN_REPLAY_FRAMES = 119
/** Live pace, with the idle waits compressed. See the docblock. */
const MAX_GAP_MS = 250

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(p * sorted.length) - 1))
  return sorted[index]
}

function round(value: number): number {
  return Math.round(value * 100) / 100
}

interface Measurement {
  frames: number
  p50: number
  p95: number
  max: number
  over34ms: number
  over50ms: number
  runFrames: number
  intervals: number
  min: number
  mean: number
  overBudget: number
  windowSeconds: number
}

function measure(times: number[]): Omit<Measurement, 'runFrames' | 'frames' | 'overBudget'> {
  const intervals: number[] = []
  for (let i = 1; i < times.length; i += 1) intervals.push(times[i] - times[i - 1])
  const sorted = [...intervals].sort((a, b) => a - b)
  const total = intervals.reduce((sum, value) => sum + value, 0)
  return {
    intervals: intervals.length,
    min: round(sorted[0] ?? 0),
    mean: round(intervals.length ? total / intervals.length : 0),
    p50: round(percentile(sorted, 0.5)),
    p95: round(percentile(sorted, 0.95)),
    max: round(sorted[sorted.length - 1] ?? 0),
    over34ms: intervals.filter((value) => value > 34).length,
    over50ms: intervals.filter((value) => value > 50).length,
    windowSeconds: round(total / 1000),
  }
}

/* ------------------------------------------------------------------ the report */

interface Budget {
  idleMedianMs: number
  refreshHz: number
  sixtyHz: boolean
  dropBudgetMs: number
  p95BudgetMs: number
  derivedBecause: string | null
}

const report: Record<string, unknown> = {
  criterion:
    'T2.8 — no dropped frames at 119+ events. Zero rAF intervals over the drop budget, ' +
    'p95 at or under the p95 budget, measured over the window in which frames are applied.',
  producedBy: 'frontend/e2e/cast-perf.spec.ts',
  capturedAt: null,
  note: null,
  measurements: {},
}

function flush(): void {
  mkdirSync(path.dirname(PERF_JSON), { recursive: true })
  report.capturedAt = new Date().toISOString()
  writeFileSync(PERF_JSON, `${JSON.stringify(report, null, 2)}\n`, 'utf-8')
}

function record(name: string, payload: Record<string, unknown>): void {
  ;(report.measurements as Record<string, unknown>)[name] = payload
  /*
   * The criterion-bearing numbers are ALSO mirrored at the top level, under the
   * exact key names the definition of done asks for, so a reader grepping
   * `over34ms` in `perf.json` finds the figure the verdict rests on rather than
   * two candidates and no rule for choosing. The fixture replay wins when it
   * ran, because it is the one that reaches 119 frames.
   */
  const criterionBearing =
    (report.measurements as Record<string, { frames?: number }>).fixtureReplay ??
    (report.measurements as Record<string, unknown>).liveSyntheticRun
  if (criterionBearing && typeof criterionBearing === 'object') {
    const source = criterionBearing as Record<string, unknown>
    for (const key of ['frames', 'p50', 'p95', 'max', 'over34ms', 'over50ms', 'runFrames']) {
      report[key] = source[key]
    }
    report.headlineFrom =
      (report.measurements as Record<string, unknown>).fixtureReplay !== undefined
        ? 'fixtureReplay'
        : 'liveSyntheticRun'
  }
  flush()
}

/* ------------------------------------------------------------------- the page */

/**
 * A `requestAnimationFrame` sampler, installed before any application script.
 *
 * `addInitScript` rather than an `evaluate` after load, for two reasons that
 * both matter: the idle baseline used to derive this machine's refresh estimate
 * has to exist BEFORE anything is launched, and a sampler installed after Vue
 * has mounted misses the first paint, which is the frame most likely to be long.
 */
async function installSampler(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const holder = window as unknown as { __frames?: number[] }
    holder.__frames = []
    const tick = (): void => {
      holder.__frames?.push(performance.now())
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
}

function samples(page: Page): Promise<number[]> {
  return page.evaluate(() => (window as unknown as { __frames?: number[] }).__frames ?? [])
}

function statusBadge(page: Page) {
  return page.locator('.status-panel .status-badge')
}

async function statusValue(page: Page): Promise<string> {
  const chip = statusBadge(page).first()
  const attribute = await chip.getAttribute('data-status')
  if (attribute) return attribute.trim().toLowerCase()
  return (await chip.innerText()).trim().toLowerCase()
}

const TERMINAL = ['completed', 'error', 'cancelled', 'failed']

/** The client's own high-water mark of frames accepted, off the stream line. */
async function readSequence(page: Page): Promise<number> {
  const text = await page.locator('.status-panel .stream-line').innerText()
  return Number(/seq\s+(\d+)/.exec(text)?.[1] ?? -1)
}

async function openStudio(page: Page): Promise<void> {
  await page.goto('/')
  await expect(page.locator('.vue-flow__node').first()).toBeVisible()
}

/** Review mode, then Launch, waiting out the admission limiter as elsewhere. */
async function launchRun(page: Page, idea: string): Promise<void> {
  const review = page.getByRole('button', { name: 'Review', exact: true })
  if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
  await expect(review).toHaveAttribute('aria-pressed', 'true')
  // `textarea#idea`: a published graph may name a node `idea`, and Vue Flow's
  // node id falls through to the card's DOM id, so the bare `#idea` matches two
  // elements and fails on strict mode. Measured in `cast.spec.ts`'s S4.
  await page.locator('textarea#idea').fill(idea)
  const launch = page.locator('[data-testid="launch-button"]')
  await expect(launch).toBeEnabled()

  const limited = page.locator('[role="alert"]').filter({ hasText: /too many runs/i })
  for (let attempt = 0; attempt < 8; attempt += 1) {
    await launch.click()
    try {
      await limited.waitFor({ state: 'visible', timeout: 2_000 })
    } catch {
      return
    }
    await page.waitForTimeout(6_000)
  }
  throw new Error('the admission limiter refused eight launches in a row')
}

/** The full run id, from the identity-scoped pointer the console writes. */
async function activeRunId(page: Page): Promise<string | null> {
  const raw = await page.evaluate(
    (key) => window.localStorage.getItem(key),
    storageKeyFor(DEFAULT_SYNTHETIC_USER, 'validator-active-run'),
  )
  if (!raw) return null
  try {
    return (JSON.parse(raw) as { runId?: string }).runId ?? null
  } catch {
    return null
  }
}

function budgetFrom(idleTimes: number[]): Budget {
  const idle = measure(idleTimes)
  const idleMedian = idle.p50
  const sixtyHz = idleMedian > 0 && idleMedian <= SIXTY_HZ_IDLE_CEILING_MS
  return {
    idleMedianMs: idleMedian,
    refreshHz: idleMedian > 0 ? round(1000 / idleMedian) : 0,
    sixtyHz,
    dropBudgetMs: sixtyHz ? DROP_BUDGET_MS : round(Math.max(DROP_BUDGET_MS, idleMedian * 2)),
    p95BudgetMs: sixtyHz ? P95_BUDGET_MS : round(Math.max(P95_BUDGET_MS, idleMedian * 1.25)),
    derivedBecause: sixtyHz
      ? null
      : `the idle page sampled a median rAF interval of ${idleMedian}ms ` +
        `(~${idleMedian > 0 ? round(1000 / idleMedian) : 0}Hz), so this environment is not ` +
        'running at 60Hz and the 34ms/20ms figures would be measuring the harness. The ' +
        'budgets are twice and 1.25x the measured interval instead, per the DoD note.',
  }
}

/* ========================================================================== */
/* 1. The live synthetic run                                                  */
/* ========================================================================== */

test.describe('T2.8 — frame budget', () => {
  test(
    'the console keeps its frame budget through a real synthetic run',
    { tag: '@launch' },
    async ({ page }) => {
      test.setTimeout(300_000)
      const consoleErrors: string[] = []
      const pageErrors: string[] = []
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text())
      })
      page.on('pageerror', (error) => pageErrors.push(error.message))

      await installSampler(page)
      await openStudio(page)

      // Let the first-paint storm settle, then take this machine's idle rate.
      await page.waitForTimeout(1_500)
      const idle = await samples(page)
      const budget = budgetFrom(idle)
      report.budget = budget
      flush()

      const launchIndex = idle.length

      /*
       * EVERYTHING THAT DRIVES THE RUN IS INSIDE THIS TRY, and the artifact is
       * written after it whatever happened.
       *
       * `perf.json` is the evidence T2.8 is graded on, and on the first full run
       * it arrived carrying ONE of its two arms: this test threw inside the gate
       * loop, twenty lines above `record()`, so the live measurement was taken,
       * discarded and never written. A measurement that only survives the happy
       * path is not evidence — the run that fails is exactly the one whose
       * numbers a reader wants. So a drive failure becomes a string in
       * `driveProblems`, the sampler is read either way, and the assertion that
       * the run was drivable is made BELOW `record()` with everything else.
       */
      const driveProblems: string[] = []
      await launchRun(page, 'A claim auditor for newsroom drafts').catch((error: Error) => {
        driveProblems.push(`launch: ${error.message}`)
      })

      /*
       * Gates answered as soon as they open — but the first two openings of the
       * scope gate and the first of the verdict gate are answered REVISE.
       *
       * A straight-through synthetic run is 96–97 frames and the criterion asks
       * for 119, so the frames have to come from somewhere. They come from a
       * reply the console really offers and the double really models
       * (`route_scope -> revise_scope -> confirm_scope`, capped at
       * `SYNTHETIC_MAX_REVISE_TURNS = 3` per gate): each turn re-runs the node
       * and re-opens the gate. A revise loop is also the densest thing this
       * console ever does — a gate closing, a node re-running and a gate
       * re-opening inside a second — which makes it the right stress for a
       * dropped-frame measurement rather than a convenient one.
       *
       * The poll is deliberately slow (250 ms): every tick is an `evaluate` into
       * the page, and a sampler measuring frame intervals must not be dominated
       * by the instrument reading it. The card is waited out after each reply,
       * because the heading does not change on a revise and a second click would
       * land on a gate already answered and take a 409.
       */
      const revisesLeft: Record<string, number> = { 'Confirm scope': 2, 'Review verdict': 1 }
      const card = page.locator('.gate-card')
      const until = Date.now() + 240_000
      let status = 'unknown'
      let replies = 0
      while (Date.now() < until && driveProblems.length === 0) {
        status = await statusValue(page).catch(() => 'unknown')
        if (TERMINAL.includes(status)) break
        if (await card.first().isVisible().catch(() => false)) {
          const title = (await card.locator('h2').innerText().catch(() => '')).trim()
          const revise = (revisesLeft[title] ?? 0) > 0
          const pass = revise ? await gatePass(page, title) : 0
          if (revise) {
            revisesLeft[title] -= 1
            await card
              .locator('form textarea')
              .first()
              .fill('Tighten this before scoring it.')
              .catch(() => undefined)
          }
          await card
            .getByRole('button', { name: revise ? /^Revise/ : /^Approve/ })
            .click()
            .catch(() => undefined)
          replies += 1
          /*
           * The two replies need OPPOSITE waits, and conflating them cost this
           * test a red on its first full run.
           *
           * An approve leaves a real gap — the scope gate hands off to a fifteen
           * second fan-out — so waiting for the card to detach is right. A
           * revise does not: the server emits `gate_closed` and `gate_open` back
           * to back, Vue coalesces them into one render, and `pendingGate` never
           * passes through null. Waiting for a hole that is never there timed out
           * at 60 s while the console sat there with the re-opened gate on
           * screen. `waitForGateReopen` watches the gate node's pass count, which
           * increments once per opening; `e2e/gateReply.ts` carries the full
           * reasoning.
           */
          try {
            if (revise) await waitForGateReopen(page, title, pass)
            else await expect(card).toHaveCount(0, { timeout: 60_000 })
          } catch (error) {
            driveProblems.push(`${revise ? 'revise' : 'approve'} at "${title}": ${(error as Error).message}`)
          }
        }
        await page.waitForTimeout(250)
      }

      const all = await samples(page).catch(() => [] as number[])
      const runFrames = await readSequence(page).catch(() => -1)
      const stats = measure(all.slice(launchIndex))
      const overBudget = all
        .slice(launchIndex)
        .map((value, index, list) => (index === 0 ? 0 : value - list[index - 1]))
        .filter((gap) => gap > budget.dropBudgetMs).length

      record('liveSyntheticRun', {
        what:
          'One real launch against the SYNTHETIC=1 backend, driven through three revise turns ' +
          '(two at the scope gate, one at the verdict gate) and then approved, so a 96–97 frame ' +
          "run reaches the criterion's 119 events by looping rather than by relaxing the floor. " +
          'Sampling runs from before navigation; the window measured starts at the Launch click ' +
          'and ends at the terminal status.',
        budget,
        frames: runFrames,
        runFrames,
        gateReplies: replies,
        terminalStatus: status,
        driveProblems,
        ...stats,
        overBudget,
        reachesCriterionFrameFloor: runFrames >= MIN_REPLAY_FRAMES,
        consoleErrors,
        pageErrors,
      })

      expect(
        driveProblems,
        'the run could not be driven to a terminal state; the numbers above were still recorded',
      ).toEqual([])
      expect(pageErrors, 'an uncaught exception invalidates the measurement').toEqual([])
      expect(TERMINAL, `the run never reached a terminal state (last: ${status})`).toContain(status)
      expect(
        runFrames,
        `the live run emitted ${runFrames} frames, below the criterion's ${MIN_REPLAY_FRAMES}. ` +
          'Three revise turns should carry a 96–97 frame synthetic run past it; if the double ' +
          'changed, add a turn (the cap is 3 per gate) rather than lowering the floor.',
      ).toBeGreaterThanOrEqual(MIN_REPLAY_FRAMES)
      expect(
        stats.intervals,
        'the rAF sampler recorded no intervals after Launch',
      ).toBeGreaterThan(30)
      expect(
        overBudget,
        `${overBudget} rAF intervals exceeded ${budget.dropBudgetMs}ms during a live run ` +
          `(max ${stats.max}ms, p95 ${stats.p95}ms). See ${PERF_JSON}.`,
      ).toBe(0)
      expect(
        stats.p95,
        `p95 was ${stats.p95}ms against a budget of ${budget.p95BudgetMs}ms. See ${PERF_JSON}.`,
      ).toBeLessThanOrEqual(budget.p95BudgetMs)
    },
  )

  /* ======================================================================== */
  /* 2. The 131-frame replay, which is the criterion                          */
  /* ======================================================================== */

  test(
    'the console keeps its frame budget while 131 committed frames are applied at live pace',
    { tag: '@launch' },
    async ({ page }) => {
      test.setTimeout(300_000)
      const consoleErrors: string[] = []
      const pageErrors: string[] = []
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text())
      })
      page.on('pageerror', (error) => pageErrors.push(error.message))

      /* ---- the script ---------------------------------------------------- */

      const sources = ['serializerFrames.ndjson', 'syntheticRun.ndjson']
      for (const name of sources) {
        expect(existsSync(fixture(name)), `missing fixture ${fixture(name)}`).toBe(true)
      }

      interface Step {
        frame: Record<string, unknown>
        gapMs: number
      }
      const script: Step[] = []
      const perSource: Record<string, number> = {}
      let sequence = 0
      for (const name of sources) {
        const rows = readFileSync(fixture(name), 'utf-8')
          .split(/\r?\n/)
          .filter((line) => line.trim().length > 0)
          .map((line) => JSON.parse(line) as { type?: string; data?: Record<string, unknown> })
        perSource[name] = rows.length
        let previous: number | null = null
        for (const row of rows) {
          const frame = (row.data ?? (row as unknown as Record<string, unknown>)) as Record<
            string,
            unknown
          >
          const at = Date.parse(String(frame.ts ?? ''))
          const gap =
            previous === null || Number.isNaN(at)
              ? 0
              : Math.min(Math.max(at - previous, 0), MAX_GAP_MS)
          if (!Number.isNaN(at)) previous = at
          sequence += 1
          /*
           * SEQUENCE IS RENUMBERED, and it has to be.
           *
           * Both logs start at `seq 1`, and the client deduplicates on the
           * sequence it has already seen — so a naive concatenation would have
           * the second file's 97 frames silently discarded and the "131 frames"
           * in this file's name would be a fiction. The renumbering is the only
           * edit made to a committed frame: kind, event_type, node_id, message
           * and details are the bytes the Python serializer wrote.
           */
          script.push({ frame: { ...frame, seq: sequence }, gapMs: gap })
        }
      }
      // These two, and only these two, are asserted before `record()`. They fire
      // before the page has been opened, so there is no measurement in
      // existence to write down - unlike everything below, which is asserted
      // after the artifact is on disk.
      expect(
        script.length,
        `the two committed frame logs total ${script.length} frames, below the criterion's ${MIN_REPLAY_FRAMES}`,
      ).toBeGreaterThanOrEqual(MIN_REPLAY_FRAMES)

      /* ---- the socket ---------------------------------------------------- */

      let replayStarted = false
      let sent = 0
      let resolveReplay!: () => void
      const replayFinished = new Promise<void>((resolve) => {
        resolveReplay = resolve
      })

      /*
       * `routeWebSocket` and NOT `connectToServer`: this handler owns the
       * socket, so the frames the page applies are the committed ones rather
       * than whatever the backend happens to emit. Everything downstream of the
       * socket — `applyFrame`, the node states, the trace, the report — is the
       * production path untouched, which is what makes this a measurement of the
       * console rather than of a fixture renderer.
       *
       * Installed before `goto`, because a route that arrives after the page has
       * opened its socket routes nothing.
       */
      await page.routeWebSocket(
        (url) => url.pathname === '/ws',
        (ws) => {
          // Swallow the client's 20-second keepalive; nothing answers it.
          ws.onMessage(() => undefined)
          if (replayStarted) return
          replayStarted = true
          const runId = new URL(ws.url()).searchParams.get('run_id') ?? 'replay'
          void (async () => {
            for (const step of script) {
              await new Promise((resolve) => setTimeout(resolve, step.gapMs))
              ws.send(JSON.stringify({ type: 'frame', data: { ...step.frame, run_id: runId } }))
              sent += 1
            }
            resolveReplay()
          })()
        },
      )

      await installSampler(page)
      await openStudio(page)
      await page.waitForTimeout(1_500)
      const idle = await samples(page)
      const budget = budgetFrom(idle)
      report.budget = budget
      flush()

      const launchIndex = idle.length

      /*
       * Same shape as the live arm, and for the same reason: the artifact is
       * written whatever happened. A replay that stalls half way through is a
       * far more interesting row in `perf.json` than a missing one, and the
       * timeout it would otherwise die on takes the numbers with it.
       *
       * The replay is raced against a bound rather than awaited outright, so a
       * handler that never resolves becomes a recorded `driveProblems` entry
       * instead of a test timeout with no evidence at all.
       */
      const driveProblems: string[] = []
      let runId: string | null = null
      try {
        await launchRun(page, 'A claim auditor that checks numbers in newsroom drafts')
        // The run the POST really created, kept so it can be cancelled below:
        // the socket it would have streamed on belongs to this test.
        runId = await activeRunId(page)
        const stalled = Symbol('stalled')
        const outcome = await Promise.race([
          replayFinished,
          new Promise((resolve) => setTimeout(() => resolve(stalled), 180_000)),
        ])
        if (outcome === stalled) {
          driveProblems.push(`the replay stalled after ${sent} of ${script.length} frames`)
        }
        // Let the last frames land and the console settle before the window closes.
        await page.waitForTimeout(1_000)
      } catch (error) {
        driveProblems.push((error as Error).message)
      }

      const all = await samples(page).catch(() => [] as number[])
      const applied = await readSequence(page).catch(() => -1)
      const status = await statusValue(page).catch(() => 'unknown')
      const stats = measure(all.slice(launchIndex))
      const overBudget = all
        .slice(launchIndex)
        .map((value, index, list) => (index === 0 ? 0 : value - list[index - 1]))
        .filter((gap) => gap > budget.dropBudgetMs).length

      record('fixtureReplay', {
        what:
          'The two committed frame logs replayed into the page over its own WebSocket ' +
          '(page.routeWebSocket), so the client applies them through the production path. ' +
          'Gaps are the fixtures\' own timestamps clamped to ' +
          `${MAX_GAP_MS}ms, which only compresses idle waits.`,
        budget,
        sources: perSource,
        frames: script.length,
        framesSent: sent,
        runFrames: applied,
        terminalStatus: status,
        driveProblems,
        ...stats,
        overBudget,
        consoleErrors,
        pageErrors,
      })

      if (runId) {
        // Tidy: the backend started a real synthetic run whose frames nobody
        // read. Cancelling it releases the gate it is parked on.
        await page.request.post(`/api/runs/${runId}/cancel`).catch(() => undefined)
      }

      expect(
        driveProblems,
        'the replay could not be driven to the end; the numbers above were still recorded',
      ).toEqual([])
      expect(pageErrors, 'an uncaught exception invalidates the measurement').toEqual([])
      expect(sent, 'the replay did not send every frame').toBe(script.length)
      expect(
        applied,
        `the console accepted ${applied} frames of ${script.length}; the replay did not reach ` +
          'the client, so nothing below is a measurement of applying them',
      ).toBeGreaterThanOrEqual(MIN_REPLAY_FRAMES)
      expect(
        stats.intervals,
        'the rAF sampler recorded no intervals during the replay',
      ).toBeGreaterThan(30)
      expect(
        overBudget,
        `${overBudget} rAF intervals exceeded ${budget.dropBudgetMs}ms while ${applied} frames ` +
          `were applied (max ${stats.max}ms, p95 ${stats.p95}ms). See ${PERF_JSON}.`,
      ).toBe(0)
      expect(
        stats.p95,
        `p95 was ${stats.p95}ms against a budget of ${budget.p95BudgetMs}ms over ${applied} ` +
          `frames. See ${PERF_JSON}.`,
      ).toBeLessThanOrEqual(budget.p95BudgetMs)
    },
  )

  test.afterAll(() => {
    report.note =
      'Two measurements, both above the 119-event floor. `liveSyntheticRun` is a real launch ' +
      'taken round three revise turns, because a straight-through synthetic run is 96–97 ' +
      'frames. `fixtureReplay` is the headline because it is deterministic: 131 committed ' +
      'frames applied through the production client over its own socket. The top-level frames/p50/' +
      'p95/max/over34ms/over50ms/runFrames keys mirror whichever of the two the verdict rests ' +
      'on, named in `headlineFrom`. `over34ms` is always the raw 60Hz count; `overBudget` is ' +
      'the count against `budget.dropBudgetMs`, which differs only when this environment was ' +
      'measured running below 60Hz.'
    flush()
  })
})
