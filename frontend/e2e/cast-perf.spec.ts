import { expect, test, type Page } from '@playwright/test'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { gatePass, waitForGateReopen } from './gateReply'
import { DEFAULT_SYNTHETIC_USER, storageKeyFor } from './syntheticUser'

/**
 * T2.8 — "no dropped frames at 119+ events, ATTRIBUTABLE TO THE CONSOLE".
 *
 * `docs/run-shell/DEFINITION-OF-DONE.md` asks for one artifact,
 * `docs/run-shell/evidence/T2/perf.json`, carrying a replay of at least 119
 * frames at live pace in THREE arms of one run, on one page, with one sampler:
 *
 *   1. **idle** — the page at rest, nothing replaying;
 *   2. **hidden** — the replay with the whole console `visibility: hidden`,
 *      which is the harness's own cost: the socket, the CDP driver that drives
 *      it, and applying 131 frames, with nothing of ours painting;
 *   3. **painted** — the identical replay with everything drawn.
 *
 * The console passes when arm 3 adds nothing over arm 2:
 * `over34ms(painted) <= over34ms(hidden)` and `p95(painted) <= p95(hidden) + 4ms`.
 * All three arms' absolute figures are printed, so the retired wording can still
 * be applied by a reader.
 *
 * ## Why the criterion is a comparison and not a bar
 *
 * It was a bar — zero intervals over 34 ms, p95 at or under 20 ms — and the bar
 * measured this machine rather than this product. W4's profile and bisect
 * (`evidence/T2/perf-notes.md`, round three) settled it with two numbers taken
 * on the machine the suite runs on:
 *
 *   - an **idle page** with the console doing nothing reads **p95 22.2 ms**,
 *     already over the bar before the product is involved;
 *   - the **replay harness alone**, with the whole console hidden, drops
 *     **17 frames**.
 *
 * The renderer is why: headless Chromium here rasterises in software
 * (`ANGLE … SwiftShader`), so a floor of that shape is a property of the
 * environment and no product change can move it. The same bisect found the
 * console's own share to be about 3 intervals of 77 once `backdrop-filter` was
 * accounted for — inside the run-to-run spread of the arm it was measured
 * against.
 *
 * So the question this file now asks is the one the console can answer: given
 * an identical replay, does PAINTING it cost anything? Arms 2 and 3 differ by a
 * single `visibility: hidden`, so their difference is attributable to painting
 * and to nothing else. `visibility` rather than `display: none` deliberately:
 * the box tree, the layout and every reflow an appended trace row causes are
 * held constant, and only the paint stops.
 *
 * ## The frames
 *
 * 34 + 97 = **131**, from `serializerFrames.ndjson` and `syntheticRun.ndjson` —
 * the same two committed logs in both replay arms, renumbered so the client's
 * sequence deduplication does not silently discard the second file.
 * `syntheticRunGated.ndjson` is deliberately NOT added: it is the same run
 * gated, and counting one stream twice would inflate the figure without adding
 * a frame the console has not already seen.
 *
 * The app exposes no `?mock=1` and no storage flag — mock mode is reached only
 * when the transport probe fails, and it then plays `data/mockFrames.ts`'s
 * scripted 59 frames rather than either fixture — so hijacking the socket is
 * the only route by which a committed frame log reaches the real client.
 *
 * ## Pace
 *
 * Gaps come from the fixtures' own `ts` values, clamped to 250 ms. The clamp
 * only ever makes the replay DENSER than the run it was taken from — it
 * compresses the two five-second branch waits and nothing else — which is the
 * conservative direction. The bursts, where a dozen frames share a millisecond,
 * are left exactly as the backend emitted them, because the burst is the part
 * that costs a frame.
 *
 * ## The live run
 *
 * The first test drives a real launch through three revise turns and records
 * everything it measures. It is **recorded, not graded**: a live run cannot be
 * repeated frame for frame, so it cannot carry a controlled comparison, and
 * grading it would be grading the machine again. It asserts completion and
 * nothing beyond it. Its numbers are in the artifact because the console under
 * a real stream is what a reader actually cares about.
 *
 * ## Backend and cost
 *
 * The free one, never :8000:
 *
 *   $env:SYNTHETIC="1"; $env:SYNTHETIC_BRANCH_DELAY_SECONDS="5"; $env:PORT="8099"
 *   $env:CREDENTIALS_MASTER_KEY="Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="
 *   .\.venv\Scripts\serve.exe
 *
 * Both tests press Launch and are tagged `@launch`; both cost nothing, because
 * `SYNTHETIC=1` swaps the crew factories. The replay arms let the real POST
 * through so nothing about the launch path is faked, then cancel the run they
 * started — the socket it would have streamed on belongs to this test.
 *
 * ## One run of this means nothing
 *
 * W4 measured 63, 69 and 77 dropped intervals across three runs an hour apart
 * on unchanged code, against an earlier pass that read 4. A single green here
 * is a lucky run until it is repeated, and the comparison design is what makes
 * repetition affordable: both arms move together with the machine.
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
/** How long the idle arm watches a page at rest. */
const IDLE_ARM_MS = 10_000
/**
 * How many times each replay arm is repeated, alternating H P H P H P.
 *
 * THREE, because one sample of each was inside the harness's own noise and said
 * so out loud: the third pass read hidden 4 / painted 5 on one run and 5 / 10 on
 * another, while the hidden CONTROL — the same replay, the same machine, nothing
 * of ours painting — moved between 4 and 5 by itself. A comparison whose two
 * halves are each one draw from that distribution decides on the draw.
 *
 * Alternating rather than blocked (H H H P P P) so that anything drifting across
 * the test — thermal throttling, another process waking, the backend's own
 * sqlite growing — lands on both arms equally instead of on whichever ran last.
 * Odd, so the median is a measured sample rather than a mean of two.
 */
const REPLAY_REPEATS = 3
/** The figures the retired absolute wording was read off, kept where they were. */
const MIRRORED_KEYS = [
  'frames',
  'p50',
  'p95',
  'max',
  'over34ms',
  'over50ms',
  'runFrames',
  'meetsLegacyBar',
] as const
/**
 * How much p95 the painted arm may add over the hidden one.
 *
 * Four milliseconds, from the amended criterion. It is a NOISE allowance
 * rather than a budget: W4's repeats of one arm spread 13-26 drops and p95
 * 28-34ms on an otherwise idle machine, so two arms minutes apart differ by a
 * few milliseconds for reasons that have nothing to do with painting.
 */
const P95_HEADROOM_MS = 4

/** One frame of a replay, and how long to wait before sending it. */
interface ReplayStep {
  frame: Record<string, unknown>
  gapMs: number
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(p * sorted.length) - 1))
  return sorted[index]
}

/** The middle sample. Odd counts only, which `REPLAY_REPEATS` guarantees. */
function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  return sorted[Math.floor(sorted.length / 2)] ?? 0
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

/**
 * This machine's refresh estimate, recorded rather than enforced.
 *
 * It derived the two absolute bars while there were bars to derive. They are
 * still computed and still written into the artifact — `meetsLegacyBar` on every
 * arm is read against them — but nothing asserts on them any more. What the
 * block is FOR now is the honest reading of the environment: `idleMedianMs` and
 * `refreshHz`, taken from the idle arm, which is what tells a reader whether a
 * run's numbers are comparable with another machine's at all.
 */
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
  /* ======================================================================== */
  /* 1. The live synthetic run — RECORDED, not graded                         */
  /* ======================================================================== */

  test(
    'a real synthetic run is measured end to end and its numbers are recorded',
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
       * THE WHOLE DRIVE IS INSIDE ONE TRY, and the artifact is written after it
       * whatever happened.
       *
       * This was already guarded per-await and it was not enough: W4's profiling
       * run still found the live numbers only in a failure message, because one
       * call in the loop — `gatePass` — was outside every `.catch()` and threw
       * straight past `record()`. Guarding the awaits one at a time is a list
       * that has to stay complete; guarding the block is a property. The block
       * it is now.
       *
       * `perf.json` is the evidence T2.8 is graded on, and a measurement that
       * only survives the happy path is not evidence: the run that fails is
       * exactly the one whose numbers a reader wants.
       */
      const driveProblems: string[] = []
      const revisesLeft: Record<string, number> = { 'Confirm scope': 2, 'Review verdict': 1 }
      const card = page.locator('.gate-card')
      let status = 'unknown'
      let replies = 0

      try {
        await launchRun(page, 'A claim auditor for newsroom drafts')

        /*
         * Gates answered as soon as they open — but the first two openings of
         * the scope gate and the first of the verdict gate are answered REVISE.
         *
         * A straight-through synthetic run is 96–97 frames and 119 events is the
         * length worth measuring, so the frames come from a reply the console
         * really offers and the double really models (`route_scope ->
         * revise_scope -> confirm_scope`, capped at
         * `SYNTHETIC_MAX_REVISE_TURNS = 3` per gate): each turn re-runs the node
         * and re-opens the gate. A revise loop is also the densest thing this
         * console ever does — a gate closing, a node re-running and a gate
         * re-opening inside a second.
         *
         * The poll is deliberately slow (250 ms): every tick is an `evaluate`
         * into the page, and a sampler measuring frame intervals must not be
         * dominated by the instrument reading it.
         */
        const until = Date.now() + 240_000
        while (Date.now() < until) {
          status = await statusValue(page)
          if (TERMINAL.includes(status)) break
          if (await card.first().isVisible().catch(() => false)) {
            const title = (await card.locator('h2').innerText().catch(() => '')).trim()
            const revise = (revisesLeft[title] ?? 0) > 0
            const pass = revise ? await gatePass(page, title) : 0
            if (revise) {
              revisesLeft[title] -= 1
              await card.locator('form textarea').first().fill('Tighten this before scoring it.')
            }
            await card.getByRole('button', { name: revise ? /^Revise/ : /^Approve/ }).click()
            replies += 1
            /*
             * The two replies need OPPOSITE waits, and conflating them cost this
             * test a red on its first full run.
             *
             * An approve leaves a real gap — the scope gate hands off to a
             * fifteen second fan-out — so waiting for the card to detach is
             * right. A revise does not: the server emits `gate_closed` and
             * `gate_open` back to back, Vue coalesces them into one render, and
             * `pendingGate` never passes through null. Waiting for a hole that is
             * never there timed out at 60 s with the re-opened gate on screen.
             * `waitForGateReopen` watches the gate node's pass count, which
             * increments once per opening; `e2e/gateReply.ts` has the reasoning.
             */
            if (revise) await waitForGateReopen(page, title, pass)
            else await expect(card).toHaveCount(0, { timeout: 60_000 })
          }
          await page.waitForTimeout(250)
        }
      } catch (error) {
        driveProblems.push((error as Error).message)
      }

      const all = await samples(page).catch(() => [] as number[])
      const runFrames = await readSequence(page).catch(() => -1)
      const stats = measure(all.slice(launchIndex))
      const overLegacy = stats.over34ms

      record('liveSyntheticRun', {
        what:
          'One real launch against the SYNTHETIC=1 backend, driven through three revise turns ' +
          '(two at the scope gate, one at the verdict gate) and then approved. RECORDED, NOT ' +
          'GRADED: T2.8 is decided by the three-arm fixture replay below, because a live run ' +
          'cannot be repeated frame for frame and so cannot carry a controlled comparison. ' +
          'These numbers are here because the console under a real stream is the thing a reader ' +
          'actually cares about, and because a figure nobody records is a figure nobody can ' +
          'check later.',
        graded: false,
        budget,
        frames: runFrames,
        runFrames,
        gateReplies: replies,
        terminalStatus: status,
        driveProblems,
        ...stats,
        overBudget: overLegacy,
        meetsLegacyBar: stats.over34ms === 0 && stats.p95 <= P95_BUDGET_MS,
        reachesCriterionFrameFloor: runFrames >= MIN_REPLAY_FRAMES,
        consoleErrors,
        pageErrors,
      })

      // Completion, and nothing beyond it. The budget assertions that used to
      // sit here were the absolute bar the criterion retired: they measured this
      // machine's software rasteriser, not the console.
      expect(
        driveProblems,
        'the run could not be driven to a terminal state; the numbers above were still recorded',
      ).toEqual([])
      expect(pageErrors, 'an uncaught exception invalidates the measurement').toEqual([])
      expect(TERMINAL, `the run never reached a terminal state (last: ${status})`).toContain(status)
      expect(
        stats.intervals,
        'the rAF sampler recorded no intervals after Launch',
      ).toBeGreaterThan(30)
    },
  )

  /* ======================================================================== */
  /* 2. The three-arm fixture replay, which IS the criterion                  */
  /* ======================================================================== */

  test(
    'the console adds no dropped frames of its own while 131 committed frames are applied',
    { tag: '@launch' },
    async ({ page }) => {
      /*
       * Fifteen minutes, for six replays rather than two.
       *
       * Each arm is a page load, a launch, a ~10 s replay at the 250 ms gap
       * clamp, a settle and a cancel — about 25 s — so six of them plus the
       * ten-second idle arm is roughly three minutes of work. The rest is
       * headroom for the admission limiter, which this file can meet: seven
       * launches against `RUN_RATE_LIMIT_MAX_RUNS` of ten per sixty seconds, and
       * `launchRun` waits one out rather than raising the limit.
       */
      test.setTimeout(900_000)
      const consoleErrors: string[] = []
      const pageErrors: string[] = []
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text())
      })
      page.on('pageerror', (error) => pageErrors.push(error.message))

      /* ---- the script, shared by both replay arms ------------------------ */

      const sources = ['serializerFrames.ndjson', 'syntheticRun.ndjson']
      for (const name of sources) {
        expect(existsSync(fixture(name)), `missing fixture ${fixture(name)}`).toBe(true)
      }

      const script: ReplayStep[] = []
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
           * the second file's frames silently discarded and the "131 frames" in
           * this test's name would be a fiction. The renumbering is the only
           * edit made to a committed frame: kind, event_type, node_id, message
           * and details are the bytes the Python serializer wrote.
           */
          script.push({ frame: { ...frame, seq: sequence }, gapMs: gap })
        }
      }
      // These two, and only these two, are asserted before any `record()`. They
      // fire before the page is opened, so no measurement exists to write down.
      expect(
        script.length,
        `the two committed frame logs total ${script.length} frames, below the criterion's ${MIN_REPLAY_FRAMES}`,
      ).toBeGreaterThanOrEqual(MIN_REPLAY_FRAMES)

      /* ---- the socket ---------------------------------------------------- */

      /*
       * One handler, one job at a time, and the job carries its own STARTING
       * GATE.
       *
       * The gate is what makes the two replay arms comparable. The hidden arm
       * has to press Launch while the console is still visible — a
       * `visibility: hidden` button is not clickable — so without a gate the
       * first few hundred milliseconds of frames would land painted and the two
       * arms would not be the same replay. With it, the socket opens, the
       * handler waits, the shell is hidden, the window is marked, and only then
       * does the first frame go down the wire.
       *
       * `routeWebSocket` and NOT `connectToServer`: this handler owns the
       * socket, so the frames the page applies are the committed ones rather
       * than whatever the backend happens to emit. Everything downstream of the
       * socket — `applyFrame`, the node states, the trace, the report — is the
       * production path untouched, which is what makes this a measurement of the
       * console rather than of a fixture renderer.
       */
      interface ReplayJob {
        gate: Promise<void>
        finished: () => void
        sent: number
      }
      let job: ReplayJob | null = null

      await page.routeWebSocket(
        (url) => url.pathname === '/ws',
        (ws) => {
          // Swallow the client's 20-second keepalive; nothing answers it.
          ws.onMessage(() => undefined)
          const mine = job
          if (!mine) return
          job = null
          const runId = new URL(ws.url()).searchParams.get('run_id') ?? 'replay'
          void (async () => {
            await mine.gate
            for (const step of script) {
              await new Promise((resolve) => setTimeout(resolve, step.gapMs))
              try {
                ws.send(JSON.stringify({ type: 'frame', data: { ...step.frame, run_id: runId } }))
              } catch {
                // The page navigated away mid-replay; this socket is finished.
                break
              }
              mine.sent += 1
            }
            mine.finished()
          })()
        },
      )

      await installSampler(page)
      await openStudio(page)

      const arms: Record<string, Record<string, unknown>> = {}
      const driveProblems: string[] = []

      /**
       * Take a slice of the sampler and describe it, with the legacy bar
       * evaluated beside it so a reader can still apply the retired wording.
       */
      const armOf = async (from: number, extra: Record<string, unknown>) => {
        const all = await samples(page).catch(() => [] as number[])
        const stats = measure(all.slice(from))
        return {
          ...stats,
          ...extra,
          meetsLegacyBar: stats.over34ms === 0 && stats.p95 <= P95_BUDGET_MS,
        }
      }

      /* ---- arm 1: idle, nothing replaying -------------------------------- */

      /*
       * The floor. Ten seconds of a page at rest on this machine, with the same
       * sampler reading it, so every figure below is compared against what this
       * environment does when the console is doing NOTHING. W4's profile
       * measured an idle page here at p95 22.2 ms — already over the retired
       * absolute bar of 20 ms before the product does anything at all — which is
       * the whole reason the criterion moved to a comparison.
       */
      await page.waitForTimeout(1_500)
      const idleFrom = (await samples(page)).length
      await page.waitForTimeout(IDLE_ARM_MS)
      const idleArm = await armOf(idleFrom, { what: 'the page at rest, no replay', frames: 0 })
      arms.idle = idleArm

      const budget = budgetFrom((await samples(page)).slice(idleFrom))
      report.budget = budget
      flush()

      /* ---- arms 2 and 3: the same replay, hidden and painted, three times each */

      /**
       * Drive one replay arm and return its numbers.
       *
       * Every call differs from every other by ONE line — whether the shell is
       * hidden before the starting gate opens — which is what makes the
       * difference between the two arms attributable to painting and to nothing
       * else. Same script, same fresh page, same sampler, same socket handler,
       * same backend.
       *
       * Called six times, alternating, and the median of each arm is what is
       * graded. One sample each was not enough: the hidden control moved 4-5
       * drops between runs on its own, so a single hidden-against-painted
       * comparison was deciding on the draw rather than on the console.
       */
      const replayArm = async (
        hidden: boolean,
        round_: number,
      ): Promise<Record<string, unknown>> => {
        const label = `${hidden ? 'hidden' : 'painted'}#${round_ + 1}`
        /*
         * EVERY arm starts from a fresh page, and that is part of the control.
         *
         * Without it the second arm launches on a console that is already
         * showing the first arm's completed run with its report panel open —
         * more painted surface than the arm before it, which is precisely the
         * variable being measured. A `goto` also resets the sampler array, so
         * each arm's window indexes into its own page.
         */
        await openStudio(page)
        let openGate: () => void = () => undefined
        const gate = new Promise<void>((resolve) => {
          openGate = resolve
        })
        let finish: () => void = () => undefined
        const finished = new Promise<void>((resolve) => {
          finish = resolve
        })
        const mine: ReplayJob = { gate, finished: finish, sent: 0 }
        job = mine

        let runId: string | null = null
        let from = (await samples(page)).length
        try {
          await launchRun(page, 'A claim auditor that checks numbers in newsroom drafts')
          runId = await activeRunId(page)

          if (hidden) {
            /*
             * `visibility: hidden` on the shell, not `display: none`.
             *
             * The box tree stays exactly as it is — same layout, same sizes,
             * same reflow on every appended trace row — and only the painting
             * stops. `display: none` would remove the subtree, so the arm would
             * be measuring "the console does not exist" rather than "the console
             * is not painted", and every layout cost this arm is supposed to
             * hold constant would vanish with it.
             */
            await page.evaluate(() => {
              const shell = document.querySelector('.studio-shell') as HTMLElement | null
              if (shell) shell.style.visibility = 'hidden'
              else document.body.style.visibility = 'hidden'
            })
            await page.waitForTimeout(250)
          }

          // Marked AFTER the hide, so no painted frame is inside a hidden arm's
          // window and vice versa.
          from = (await samples(page)).length
          openGate()

          const stalled = Symbol('stalled')
          const outcome = await Promise.race([
            finished,
            new Promise((resolve) => setTimeout(() => resolve(stalled), 180_000)),
          ])
          if (outcome === stalled) {
            driveProblems.push(`${label}: stalled after ${mine.sent} of ${script.length} frames`)
          }
          // Let the last frames land before the window closes.
          await page.waitForTimeout(1_000)
        } catch (error) {
          driveProblems.push(`${label}: ${(error as Error).message}`)
        }

        const applied = await readSequence(page).catch(() => -1)
        const status = await statusValue(page).catch(() => 'unknown')
        const arm = await armOf(from, {
          label,
          hidden,
          frames: script.length,
          framesSent: mine.sent,
          runFrames: applied,
          terminalStatus: status,
        })

        if (hidden) {
          await page.evaluate(() => {
            const shell = document.querySelector('.studio-shell') as HTMLElement | null
            if (shell) shell.style.visibility = ''
            else document.body.style.visibility = ''
          })
        }

        /*
         * Tidy, and then forget. The POST created a real synthetic run whose
         * frames nobody read; cancelling releases the gate it is parked on.
         * Clearing the pointer is the half that matters for correctness:
         * without it the next arm's page load restores this run and opens a
         * socket before Launch is pressed, and the next arm replays into it.
         */
        if (runId) await page.request.post(`/api/runs/${runId}/cancel`).catch(() => undefined)
        await page.evaluate(() => {
          try {
            window.localStorage.clear()
          } catch {
            /* a browser with site data blocked has nothing to forget */
          }
        })
        return arm
      }

      /*
       * H P H P H P.
       *
       * The pairing is what the median is taken over: each round contributes one
       * hidden and one painted sample minutes apart on the same page, and the
       * three rounds bracket whatever the machine was doing.
       */
      const hiddenSamples: Record<string, unknown>[] = []
      const paintedSamples: Record<string, unknown>[] = []
      for (let round_ = 0; round_ < REPLAY_REPEATS; round_ += 1) {
        hiddenSamples.push(await replayArm(true, round_))
        paintedSamples.push(await replayArm(false, round_))
      }

      /** The middle sample of every figure, plus the legacy bar read off it. */
      const medianOf = (samples: Record<string, unknown>[]): Record<string, unknown> => {
        const pick = (key: string): number[] => samples.map((s_) => Number(s_[key] ?? 0))
        const p95 = round(median(pick('p95')))
        const over34ms = median(pick('over34ms'))
        return {
          over34ms,
          over50ms: median(pick('over50ms')),
          p50: round(median(pick('p50'))),
          p95,
          max: round(median(pick('max'))),
          intervals: median(pick('intervals')),
          meetsLegacyBar: over34ms === 0 && p95 <= P95_BUDGET_MS,
        }
      }

      const hiddenMedian = medianOf(hiddenSamples)
      const paintedMedian = medianOf(paintedSamples)
      arms.hidden = {
        what:
          'the same replay with the whole console `visibility: hidden` — the harness itself: ' +
          'the socket, the CDP driver, and applying 131 frames, with nothing of ours painting',
        repeats: REPLAY_REPEATS,
        samples: hiddenSamples,
        median: hiddenMedian,
      }
      arms.painted = {
        what: 'the same replay with everything painted — the console as it ships',
        repeats: REPLAY_REPEATS,
        samples: paintedSamples,
        median: paintedMedian,
      }

      /* ---- the artifact, before any verdict ------------------------------ */

      const hidden = hiddenMedian as { over34ms: number; p95: number }
      const painted = paintedMedian as { over34ms: number; p95: number }
      const addedDrops = painted.over34ms - hidden.over34ms
      const p95Delta = round(painted.p95 - hidden.p95)
      const drops = (samples: Record<string, unknown>[]): string =>
        samples.map((s_) => String(s_.over34ms)).join(', ')
      const p95s = (samples: Record<string, unknown>[]): string =>
        samples.map((s_) => String(s_.p95)).join(', ')

      record('fixtureReplay', {
        what:
          'The two committed frame logs replayed into the page over its own WebSocket ' +
          '(page.routeWebSocket), so the client applies them through the production path. One ' +
          'page, one sampler, three arms: idle once, then the replay hidden and the replay ' +
          `painted ${REPLAY_REPEATS} times each, ALTERNATING (H P H P H P) so any drift across ` +
          "the test lands on both equally. Gaps are the fixtures' own timestamps clamped to " +
          `${MAX_GAP_MS}ms, which only compresses idle waits.`,
        graded: true,
        criterion:
          'On the MEDIAN of each arm: over34ms(painted) <= over34ms(hidden), and ' +
          `p95(painted) <= p95(hidden) + ${P95_HEADROOM_MS}ms. Medians rather than single ` +
          'samples because the hidden CONTROL itself moved 4-5 drops between runs, so a ' +
          'one-against-one comparison decides on the draw. Every sample is in ' +
          '`arms.<arm>.samples`, and every arm carries its absolute figures and a ' +
          '`meetsLegacyBar` flag so the retired absolute bar (0 over 34ms, p95 <= 20ms) can ' +
          'still be applied by a reader.',
        sources: perSource,
        budget,
        arms,
        verdict: {
          addedDrops,
          p95Delta,
          p95Headroom: P95_HEADROOM_MS,
          passes: addedDrops <= 0 && p95Delta <= P95_HEADROOM_MS,
        },
        driveProblems,
        consoleErrors,
        pageErrors,
        /*
         * The retired keys, mirrored from the painted arm's MEDIAN.
         *
         * Picked one by one rather than spread, because a spread would carry the
         * arm's own `what` up with it and overwrite this block's description
         * with one that describes an arm. The point of the mirror is that a
         * reader who knew this file's old shape still finds
         * `frames`/`p95`/`over34ms` where they were, reading the figure the
         * verdict actually rests on — which is now a median and not a sample.
         */
        ...(() => {
          const source: Record<string, unknown> = {
            ...paintedMedian,
            frames: script.length,
            runFrames: paintedSamples[paintedSamples.length - 1]?.runFrames ?? -1,
          }
          const mirrored: Record<string, unknown> = {}
          for (const key of MIRRORED_KEYS) mirrored[key] = source[key]
          return mirrored
        })(),
      })

      /* ---- the verdict --------------------------------------------------- */

      expect(
        driveProblems,
        'a replay arm could not be driven to the end; the numbers above were still recorded',
      ).toEqual([])
      expect(pageErrors, 'an uncaught exception invalidates the measurement').toEqual([])
      // Every one of the six replays has to have been the whole replay, or the
      // medians are taken over arms that are not the same measurement.
      const shortfall = [...hiddenSamples, ...paintedSamples]
        .filter((sample) => Number(sample.framesSent ?? 0) !== script.length)
        .map((sample) => `${String(sample.label)}: ${String(sample.framesSent)}`)
      expect(
        shortfall,
        `a replay arm did not send all ${script.length} frames`,
      ).toEqual([])
      expect(
        (arms.idle as { intervals: number }).intervals,
        'the idle arm recorded no rAF intervals at all',
      ).toBeGreaterThan(60)

      /*
       * THE CRITERION, and it is a comparison rather than a bar.
       *
       * The absolute wording — zero intervals over 34 ms, p95 at or under 20 ms
       * — measured this machine and not this product. W4's bisect established
       * it in two numbers: an idle page here reads p95 22.2 ms, already over the
       * bar with the console doing nothing, and the replay harness alone drops
       * 17 frames with nothing of ours painted. Headless Chromium rasterises in
       * software here (`SwiftShader`), so the floor is a property of the
       * environment.
       *
       * What the console is answerable for is what it ADDS. Arms 2 and 3 are the
       * same replay a `visibility: hidden` apart, so their difference is
       * painting and nothing else — and the criterion asks that the difference
       * be nothing.
       */
      expect(
        painted.over34ms,
        `painting the console added ${addedDrops} dropped frames at the median: ` +
          `${painted.over34ms} painted (samples ${drops(paintedSamples)}) against ` +
          `${hidden.over34ms} hidden (samples ${drops(hiddenSamples)}). Idle floor: ` +
          `${(arms.idle as { over34ms: number }).over34ms}. See ${PERF_JSON}.`,
      ).toBeLessThanOrEqual(hidden.over34ms)
      expect(
        painted.p95,
        `painting the console cost ${p95Delta}ms of p95 at the median: ${painted.p95}ms painted ` +
          `(samples ${p95s(paintedSamples)}) against ${hidden.p95}ms hidden ` +
          `(samples ${p95s(hiddenSamples)}), headroom ${P95_HEADROOM_MS}ms. Idle floor: ` +
          `${(arms.idle as { p95: number }).p95}ms. See ${PERF_JSON}.`,
      ).toBeLessThanOrEqual(hidden.p95 + P95_HEADROOM_MS)
    },
  )

  test.afterAll(() => {
    report.note =
      'Three arms, and the two that are compared are repeated. `fixtureReplay.arms` holds idle ' +
      '(the page at rest, once), hidden (the 131-frame replay with the console ' +
      '`visibility: hidden` - the socket, the CDP driver and applying the frames, with nothing ' +
      `of ours painting) and painted (the same replay drawn), the last two ${REPLAY_REPEATS} ` +
      'times each, ALTERNATING. The criterion is the comparison in `fixtureReplay.verdict`, ' +
      'taken on each arm`s MEDIAN: painting must add no dropped frames and at most ' +
      `${P95_HEADROOM_MS}ms of p95. Medians because the hidden control moved between runs by ` +
      'itself, so one sample against one was deciding on the draw; every sample is in ' +
      '`arms.<arm>.samples`. Every arm also carries its absolute figures and a `meetsLegacyBar` ' +
      'flag, so the retired wording (0 over 34ms, p95 <= 20ms) can still be applied - recorded ' +
      'as a fact about this machine rather than asserted as a fact about the console. ' +
      '`liveSyntheticRun` is a real launch through three revise turns, recorded and not graded. ' +
      'The top-level frames/p50/p95/max/over34ms/over50ms/runFrames keys mirror the PAINTED ' +
      'arm`s median, named in `headlineFrom`.'
    flush()
  })
})
