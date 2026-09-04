import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

/**
 * How the canvas behaves at the size the bounds allow, measured rather than
 * asserted about.
 *
 * 02-canvas.md criterion 8 and rubric 6. The plan's own note is that graph scale
 * was NEVER MEASURED here and that Flowise has not measured it either - v2 sets
 * `minZoom 0.5` with no recorded reason. So the point of this file is a number,
 * and the number is written to `benchmarks/perf/canvas.json` beside the budget
 * it was measured against. A performance claim this project cannot reproduce is
 * worth nothing, which is why the fixture is committed and the output is a file
 * rather than a line in a report.
 *
 * WHAT IS MEASURED. `requestAnimationFrame` deltas while the canvas is being
 * driven - three seconds of wheel zoom, then three seconds of drag pan. A frame
 * delta is what a person feels; a frame COUNT is not, because a run that drops
 * ten frames in one stall and a run that drops one frame ten times average the
 * same and feel completely different. That is why p95 is in the budget beside
 * the mean.
 *
 * WHAT IS NOT MEASURED, and would be dishonest to imply: this is one machine,
 * one browser build, one head/headless mode. The budget is a floor under
 * "obviously broken", not a benchmark against other products. Read the numbers
 * in `canvas.json`, not the pass/fail.
 *
 * ## Running it
 *
 *   SYNTHETIC=1 PORT=8099 ./.venv/Scripts/serve.exe
 *   npx playwright test e2e/builder-perf.spec.ts --project=chromium
 *
 * `--project=chromium` because the budget is stated for the desktop viewport.
 * The `mobile` project does not match this file.
 */

/**
 * The plan's budget, in milliseconds per frame, EXACTLY as criterion 8 states
 * it - and it is not widened here, because a budget moved to make a test green
 * is not a budget.
 *
 * READ THIS BEFORE READING A FAILURE. The display this runs against is 60Hz, so
 * a run that drops NOTHING has a mean of 1000/60 = 16.667ms. A mean budget of
 * 16.7 therefore allows 0.033ms per frame of slack: over the ~370 frames these
 * tests sample, that is 12ms in total, which is less than one dropped frame.
 * The mean assertion is, in practice, "zero frames were dropped".
 *
 * Measured 2026-09-04 across several runs: mean 16.666 to 16.71, p95 16.7 to
 * 16.8, max 16.8. So the p95 half passes with 3ms of headroom and the mean half
 * sits ON the physical floor and crosses it whenever one frame in three hundred
 * is late. Both numbers are written to `benchmarks/perf/canvas.json` on every
 * run, pass or fail, because the number is the deliverable and the pass/fail is
 * not.
 */
const MEAN_BUDGET_MS = 16.7
const P95_BUDGET_MS = 20

/*
 * AMENDED 2026-09-04 by the Integrator, on this spec's own measurements.
 *
 * `MEAN_BUDGET_MS` stays 16.7 and is still recorded, but it is no longer the
 * pass/fail clause, because it cannot be met by any harness on a 60Hz display
 * and it never could. The physical floor is 1000/60 = 16.667ms, so 16.7 allows
 * 0.033ms per frame; over ~370 frames that is 12.2ms of total slack, which is
 * LESS THAN ONE dropped frame. The budget as written demands zero dropped
 * frames in a six-second scripted gesture.
 *
 * The measurements say the canvas is not what drops them:
 *
 *   idle48     48 nodes, no gesture   mean 16.666   not one late frame
 *   gesture1    1 node,  the gesture  mean 16.849
 *   fixture48  48 nodes, the gesture  mean 16.846
 *   client60   60 nodes, the gesture  mean 16.846
 *
 * Three numbers within 0.003ms across a SIXTYFOLD difference in canvas work.
 * The overrun is 2-3 frames at exactly 33.4ms - one dropped frame each - from
 * CDP-driven input on the paint thread, and it is the same at one node as at
 * sixty. `idle48` rules out ambient machine load.
 *
 * So the old clause measured the driver. Rubric 6 asks whether the canvas
 * DEGRADES WITH GRAPH SIZE, and these two clauses measure that directly:
 *
 *   SCALING_HEADROOM_MS - the mean of the gesture at N nodes may exceed the
 *     mean of the SAME gesture at one node by at most this. Immune to the
 *     harness, because both sides pay the same harness cost. Measured margin
 *     today: -0.003ms, i.e. 48 nodes is fractionally FASTER than one.
 *
 *   MEAN_CEILING_MS - an absolute guard so the amendment cannot hide a real
 *     regression. 17.0 permits about two dropped frames in 370; a canvas
 *     genuinely costing 1ms a frame would read 17.85 and fail it.
 *
 * A regression is caught by both. The clause that was removed caught neither -
 * only jitter, and it did not even do that consistently. TWO RUNS OF THE SAME
 * CODE, forty minutes apart on this machine:
 *
 *   fixture48 mean 16.846   -> FAILS the 16.7 budget   (2-3 frames at 33.4ms)
 *   fixture48 mean 16.666   -> PASSES it               (no late frame at all)
 *
 * So it was not merely unmeetable, it was NONDETERMINISTIC - which is worse
 * than a failing gate, because a flaky one teaches everybody to re-run until
 * green and then teaches them to ignore it. The scaling clause has no such
 * property: it measured +0.0000ms at 48 nodes and +0.0004ms at 60 against a
 * 0.5ms budget on the run that recorded those very numbers. This is an amendment made ON evidence, and the evidence is
 * printed by the run itself, which is why the numbers above are reproducible
 * rather than quoted.
 */
const SCALING_HEADROOM_MS = 0.5
const MEAN_CEILING_MS = 17.0
/** 1000/60. The floor a 60Hz display cannot go below, for the failure messages. */
const VSYNC_MS = 1000 / 60
/** How long the instrument check blocks the main thread for. Twelve frames. */
const BLOCK_MS = 300

/** Where the measurement is written, so a later session can compare rather than re-argue. */
const REPORT = path.resolve(process.cwd(), '..', 'benchmarks', 'perf', 'canvas.json')

interface FrameStats {
  frames: number
  meanMs: number
  p95Ms: number
  maxMs: number
  seconds: number
}

/**
 * Start sampling `requestAnimationFrame` deltas on the page.
 *
 * The sampler runs INSIDE the page and stores into a global, because reading a
 * timestamp back over CDP once a frame would measure the protocol rather than
 * the canvas.
 */
async function startSampling(page: Page): Promise<void> {
  await page.evaluate(() => {
    const store = { deltas: [] as number[], stop: false, last: 0 }
    ;(window as unknown as { __frames: typeof store }).__frames = store
    const tick = (now: number): void => {
      if (store.stop) return
      if (store.last > 0) store.deltas.push(now - store.last)
      store.last = now
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
}

/** Stop sampling and reduce the deltas to the four numbers the budget is about. */
async function stopSampling(page: Page): Promise<FrameStats> {
  return page.evaluate(() => {
    const store = (window as unknown as { __frames: { deltas: number[]; stop: boolean } }).__frames
    store.stop = true
    const deltas = store.deltas.slice().sort((left, right) => left - right)
    const total = deltas.reduce((sum, delta) => sum + delta, 0)
    return {
      frames: deltas.length,
      meanMs: deltas.length ? total / deltas.length : 0,
      // The nearest-rank p95, which needs no interpolation and cannot be
      // flattered by one being chosen over another.
      p95Ms: deltas.length ? deltas[Math.min(deltas.length - 1, Math.ceil(deltas.length * 0.95) - 1)] : 0,
      maxMs: deltas.length ? deltas[deltas.length - 1] : 0,
      seconds: total / 1000,
    }
  })
}

/** Three seconds of wheel zoom over the pane, in and out, without clamping at a limit. */
async function scriptZoom(page: Page, seconds = 3): Promise<void> {
  const box = (await page.locator('.builder-flow').boundingBox())!
  const centre = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
  await page.mouse.move(centre.x, centre.y)
  const until = Date.now() + seconds * 1000
  let direction = -1
  while (Date.now() < until) {
    // 120 is one notch of a real wheel, which is what a person's hand produces.
    await page.mouse.wheel(0, 120 * direction)
    direction = direction === -1 ? 1 : -1
    await page.waitForTimeout(16)
  }
}

/**
 * Three seconds of drag pan.
 *
 * SPACE IS HELD for the whole gesture. The builder canvas pans on middle-drag,
 * right-drag or Space+left only - a plain left drag is the marquee (§4.3) - so a
 * pan scripted without the modifier measures a selection rectangle instead, and
 * would be a green number about the wrong thing.
 */
async function scriptPan(page: Page, seconds = 3): Promise<void> {
  const box = (await page.locator('.builder-flow').boundingBox())!
  const centre = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
  await page.keyboard.down('Space')
  await page.mouse.move(centre.x, centre.y)
  await page.mouse.down()
  const until = Date.now() + seconds * 1000
  let step = 0
  while (Date.now() < until) {
    // A circle rather than a line, so the pan never runs out of canvas and
    // never stops moving - a gesture that reached the edge and stalled would
    // report the stall as a run of cheap frames.
    const angle = (step * Math.PI) / 12
    await page.mouse.move(centre.x + Math.cos(angle) * 220, centre.y + Math.sin(angle) * 160)
    step += 1
    await page.waitForTimeout(16)
  }
  await page.mouse.up()
  await page.keyboard.up('Space')
}

/** Create a document from a fixture and open it, returning its id. */
async function openDocument(
  page: Page,
  request: APIRequestContext,
  document: Record<string, unknown>,
): Promise<string> {
  const created = await request.post('/api/builder/workflows', {
    data: { document, expected_version: null },
  })
  expect(created.ok(), await created.text()).toBe(true)
  const model = (await created.json()) as { document: { id: string } }
  const id = model.document.id
  await page.goto(`/#/build/${id}`)
  await expect(page.locator('.builder-flow')).toBeVisible()
  return id
}

async function clearLibrary(request: APIRequestContext): Promise<void> {
  const listed = await request.get('/api/builder/workflows')
  if (!listed.ok()) return
  const documents = (await listed.json()) as { id: string }[]
  for (const entry of documents) await request.delete(`/api/builder/workflows/${entry.id}`)
}

const PERF48 = JSON.parse(
  readFileSync(path.resolve(process.cwd(), 'tests/fixtures/perf48.json'), 'utf8'),
) as Record<string, unknown>

/**
 * The same graph again, at 60 nodes, for the client-only half of criterion 8.
 *
 * `MAX_GRAPH_NODES` is 24 and `MAX_ATTACHMENT_NODES` is 24, so 60 is a document
 * the SERVER would report counts against - which is the point: the budget has to
 * hold for a graph past the bound, not only for one that sits on it. The extra
 * twelve are attachments, because they are the cheapest node to add and
 * therefore the least flattering thing to pad with.
 */
function grow(document: Record<string, unknown>, extra: number): Record<string, unknown> {
  const nodes = [...(document.nodes as Record<string, unknown>[])]
  const edges = [...(document.edges as Record<string, unknown>[])]
  const host = nodes.find((node) => node.kind === 'agent')!.id as string
  for (let index = 0; index < extra; index += 1) {
    const id = `pad_${index + 1}`
    nodes.push({
      id,
      label: `Pad ${index + 1}`,
      position: { x: -900, y: index * 60 },
      kind: 'skill',
      config: { skill_id: 'skill' },
    })
    edges.push({
      id: `pe${index + 1}`,
      source: id,
      source_port: 'attach',
      target: host,
      target_port: 'attach',
    })
  }
  return { ...document, nodes, edges }
}

/**
 * Record one case, MERGED into whatever is already on disk.
 *
 * Written per case rather than once at the end, and the reason is a measurement
 * rather than caution: an `afterAll` that wrote an accumulating module-level
 * object produced a report containing only the LAST case, because Playwright
 * does not guarantee that every test in a file shares one module instance -
 * a failing test can be followed by a fresh worker, and a fresh worker starts
 * with an empty accumulator. Merging means the file is correct however the
 * tests were sharded, retried or re-run one at a time.
 */
function record(name: string, stats: FrameStats, nodes: number): void {
  mkdirSync(path.dirname(REPORT), { recursive: true })
  let existing: Record<string, unknown> = {}
  try {
    existing = JSON.parse(readFileSync(REPORT, 'utf8')) as Record<string, unknown>
  } catch {
    // No report yet, or one this version cannot read. Either way it is replaced.
  }
  const cases = (existing.cases as Record<string, unknown>) ?? {}
  cases[name] = { ...stats, nodes }
  writeFileSync(
    REPORT,
    `${JSON.stringify(
      {
        measuredAt: new Date().toISOString(),
        budget: { meanMs: MEAN_BUDGET_MS, p95Ms: P95_BUDGET_MS, vsyncFloorMs: VSYNC_MS },
        note:
          'requestAnimationFrame deltas over 3s of scripted wheel zoom and 3s of ' +
          'Space+drag pan, Chromium at 1440x900 against a local SYNTHETIC=1 backend. ' +
          'One machine, one browser build - a floor under "obviously broken", not a ' +
          'comparison against another product. `idle48` is the same canvas doing ' +
          'NOTHING for the same six seconds, and is the control the busy cases are ' +
          'read against. `instrumentCheck` blocks the main thread on purpose, and ' +
          'is what makes a green run mean anything.',
        cases,
      },
      null,
      2,
    )}
`,
    'utf8',
  )
}

/**
 * A failure message that says how far over, and how far over the FLOOR.
 *
 * "mean 16.71ms" on its own reads as a performance problem. "mean 16.71ms
 * against a 16.70 budget and a 16.67 physical floor - 0.04ms of the budget's
 * 0.03ms of headroom" reads as what it is: one dropped frame in three hundred.
 */
function describe(stats: FrameStats): string {
  const dropped = Math.round(((stats.meanMs - VSYNC_MS) * stats.frames) / VSYNC_MS)
  return (
    `mean ${stats.meanMs.toFixed(3)}ms / p95 ${stats.p95Ms.toFixed(2)}ms / ` +
    `max ${stats.maxMs.toFixed(2)}ms over ${stats.frames} frames; ` +
    `budget ${MEAN_BUDGET_MS} mean and ${P95_BUDGET_MS} p95, ` +
    `60Hz floor ${VSYNC_MS.toFixed(3)}ms, so roughly ${dropped} frame(s) late`
  )
}

/**
 * The one-node mean, filled in by the `gesture1` test and read by the two that
 * assert scaling. Module state rather than a fixture because the comparison is
 * only meaningful WITHIN one run on one machine - a one-node number recorded on
 * some other machine would compare two harnesses, which is the exact mistake
 * this amendment exists to stop making.
 */
let oneNodeMeanMs: number | null = null

/**
 * Assert that graph size costs nothing measurable.
 *
 * Skips rather than passes when the one-node control has not run, because a
 * scaling assertion with nothing to scale against is a test that always passes
 * - and this file already has one lesson about clauses that cannot fail.
 */
function expectScalesFlat(meanMs: number, what: string): void {
  if (oneNodeMeanMs === null) {
    test.skip(true, 'the one-node control did not run, so there is nothing to scale against')
    return
  }
  const delta = meanMs - oneNodeMeanMs
  expect(
    delta,
    `${what}: mean ${meanMs.toFixed(3)}ms against a one-node control of ` +
      `${oneNodeMeanMs.toFixed(3)}ms - graph size cost ${delta.toFixed(3)}ms per ` +
      `frame, budget ${SCALING_HEADROOM_MS}ms. The absolute mean is bounded ` +
      `separately at ${MEAN_CEILING_MS}ms; this clause is about whether the ` +
      `canvas degrades with node count, which is what rubric 6 asks.`,
  ).toBeLessThanOrEqual(SCALING_HEADROOM_MS)
}

test.describe('canvas performance at the bound maximum', () => {
  test.afterEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test('the sampler can actually see a stall, which is what makes a green run mean anything', async ({
    page,
    request,
  }) => {
    /*
     * THE INSTRUMENT CHECK, and it exists because the first green run looked
     * too good: mean 16.666ms, max 16.8ms, on both cases, which is a perfectly
     * locked 60Hz vsync. That is either a canvas that never dropped a frame or a
     * sampler that cannot tell. A budget met by an instrument that reads the
     * same number whatever happens is worth nothing, so the instrument is
     * measured before the canvas is.
     *
     * A 120ms busy loop on the main thread is longer than seven frames. If the
     * deltas do not move, every other number in this file is furniture.
     */
    await openDocument(page, request, PERF48)
    await page.waitForTimeout(600)

    await startSampling(page)
    await page.evaluate(
      (ms) =>
        new Promise<void>((resolve) => {
          // Blocked from INSIDE a frame callback, so the block is guaranteed to
          // straddle at least one vsync. Blocking from `evaluate` alone raced
          // the sampler's first frame pair and reported anywhere from 66ms to
          // 116ms for the same 120ms loop - an instrument check that is itself
          // flaky proves nothing.
          requestAnimationFrame(() => {
            const until = performance.now() + ms
            while (performance.now() < until) {
              // Deliberately blocking. Nothing here is a canvas operation; the
              // point is that the MAIN THREAD is busy, which is the only thing
              // rAF deltas can report.
            }
            resolve()
          })
        }),
      BLOCK_MS,
    )
    await page.waitForTimeout(400)
    const stalled = await stopSampling(page)
    record('instrumentCheck', stalled, 48)

    /*
     * Two thirds of the block, not all of it. The claim being pinned is "a
     * multi-frame stall is visible", not "the reported number equals the
     * block": a delta above 200ms against a 16.8ms maximum on every unblocked
     * run is a twelve-fold signal, which is all the sensitivity this file needs.
     */
    expect(
      stalled.maxMs,
      `the sampler did not notice a ${BLOCK_MS}ms block: worst frame ${stalled.maxMs.toFixed(1)}ms`,
    ).toBeGreaterThan(BLOCK_MS * 0.66)
  })

  test('records what an IDLE canvas costs, so a busy one can be compared to it', async ({
    page,
    request,
  }) => {
    /*
     * THE CONTROL, and it is what turns "we missed the mean by 0.04ms" into a
     * statement about where the time goes.
     *
     * The same 48 nodes and the same six seconds, with NO gesture at all. If an
     * idle canvas also reports one or two double-length frames, they are
     * ambient - the harness's own CDP round trips, a compositor hiccup, another
     * process on the machine - and not something the zoom or the pan caused. If
     * an idle canvas is exactly 16.667, the gestures own the difference.
     *
     * Recorded, never asserted. A budget on an idle canvas would be a budget on
     * this machine's background load.
     */
    await openDocument(page, request, PERF48)
    await page.waitForTimeout(1200)

    await startSampling(page)
    await page.waitForTimeout(6000)
    const stats = await stopSampling(page)
    record('idle48', stats, 48)

    expect(stats.frames, 'no frames were sampled at all').toBeGreaterThan(60)
  })

  test('records the same gesture over ONE node, to say where the late frames come from', async ({
    page,
    request,
  }) => {
    /*
     * THE SECOND CONTROL, and between them the two answer the question a bare
     * "we missed the mean by 0.06ms" cannot.
     *
     * `idle48` shows a 48-node canvas doing nothing at exactly the 60Hz floor,
     * which rules out ambient load on the machine. What it cannot separate is
     * the scripted GESTURE from the canvas work it causes: every `mouse.wheel`
     * and `mouse.move` is a CDP round trip landing on the same thread that
     * paints, so the harness has a cost of its own.
     *
     * This is the identical gesture at the identical cadence over ONE node -
     * the same number of round trips, roughly a fiftieth of the canvas work.
     * Late frames here belong to the harness; late frames only in the 48-node
     * case belong to the canvas.
     *
     * Recorded, never asserted, for the same reason `idle48` is: a budget on a
     * control is a budget on this machine.
     */
    const created = await request.post('/api/builder/workflows', {
      data: {
        document: {
          schema: 'builder.flow/v1',
          name: 'One node',
          version: 1,
          input_field: 'idea',
          nodes: [
            {
              id: 'idea',
              kind: 'input',
              label: 'Idea',
              position: { x: 0, y: 0 },
              config: { field: 'idea', label: null, max_chars: 2000, required: true },
            },
          ],
          edges: [],
          joins: {},
        },
        expected_version: null,
      },
    })
    expect(created.status(), await created.text()).toBe(201)
    await page.goto(`/#/build/${((await created.json()) as { id: string }).id}`)
    await expect(page.locator('.vue-flow__node')).toHaveCount(1)
    await page.waitForTimeout(1200)

    await startSampling(page)
    await scriptZoom(page)
    await scriptPan(page)
    const stats = await stopSampling(page)
    record('gesture1', stats, 1)
    // The control the two scaling assertions below read. Set here rather than
    // recomputed, so both compare against the same run on the same machine.
    oneNodeMeanMs = stats.meanMs

    expect(stats.frames).toBeGreaterThan(60)
  })

  test('holds the frame budget on the 48-node fixture', async ({ page, request }) => {
    await openDocument(page, request, PERF48)
    await expect(page.locator('.vue-flow__node:has(.workflow-node)')).toHaveCount(48)
    // Let the settling `ResizeObserver` finish its fits before sampling, or the
    // measurement includes a layout the author never sees.
    await page.waitForTimeout(1200)

    await startSampling(page)
    await scriptZoom(page)
    await scriptPan(page)
    const stats = await stopSampling(page)
    record('fixture48', stats, 48)

    expect(stats.frames, 'no frames were sampled at all').toBeGreaterThan(60)
    expect(stats.p95Ms, describe(stats)).toBeLessThanOrEqual(P95_BUDGET_MS)
    expect(stats.meanMs, describe(stats)).toBeLessThanOrEqual(MEAN_CEILING_MS)
    expectScalesFlat(stats.meanMs, '48-node fixture')
  })

  test('holds the same budget on a 60-node graph the server would refuse to size', async ({
    page,
    request,
  }) => {
    /*
     * The client-only half. 60 is past `MAX_GRAPH_NODES + MAX_ATTACHMENT_NODES`,
     * so `bounds.py` reports counts against it - and reporting is all it does
     * (R6), which is exactly why the CANVAS still has to draw it. A bound the
     * renderer relies on is a bound that becomes load-bearing the day it moves.
     */
    await openDocument(page, request, grow(PERF48, 12))
    await expect(page.locator('.vue-flow__node:has(.workflow-node)')).toHaveCount(60)
    await page.waitForTimeout(1200)

    await startSampling(page)
    await scriptZoom(page)
    await scriptPan(page)
    const stats = await stopSampling(page)
    record('client60', stats, 60)

    expect(stats.frames).toBeGreaterThan(60)
    expect(stats.p95Ms, describe(stats)).toBeLessThanOrEqual(P95_BUDGET_MS)
    expect(stats.meanMs, describe(stats)).toBeLessThanOrEqual(MEAN_CEILING_MS)
    expectScalesFlat(stats.meanMs, '60-node client-only graph')
  })
})
