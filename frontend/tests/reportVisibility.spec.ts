import { readFileSync } from 'node:fs'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { App } from 'vue'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import { FakeStudioApi, flush, frameFactory, withSetup } from './helpers'

type ValidatorRun = ReturnType<typeof useValidatorRun>

/**
 * The body of the rule whose selector is exactly `selector`, at the start of a
 * line.
 *
 * The anchoring is the point, and it cost two red tests to find.
 * `.control-rail {` also occurs inside
 * `.studio-main > .chat-rail, ... > .control-rail {` fifty lines earlier, so an
 * unanchored `indexOf` reads THAT rule's three-line `min-height: 0` body and
 * asserts against it. A source-level test that grabs the wrong rule passes or
 * fails for reasons that have nothing to do with its subject - which is the
 * one failure mode a source-level test must not have.
 */
function ruleFor(source: string, selector: string): string {
  const at = source.indexOf(`\n${selector} {`)
  if (at < 0) throw new Error(`no rule declared for ${selector}`)
  const body = source.slice(at + 1)
  return body.slice(0, body.indexOf('\n}'))
}

/**
 * The finished report, and the verdict that goes with it.
 *
 * These exist because the console previously discarded the report at three
 * separate layers behind a fully green suite: the transport type did not
 * declare `result`, `getRun` dropped it, and `applyRunState` never read it. A
 * feature nothing asserts on is a feature that can be deleted by accident, and
 * this one had already been deleted by accident once.
 *
 * The two carriers are not interchangeable, which is the subtlety worth
 * pinning: the terminal frame's copy is clipped at 4096 characters by
 * `FieldBoundedSerializer`, while the snapshot's is re-read at 64 KiB. Tests
 * that only ever use short bodies cannot tell them apart - which is exactly how
 * the truncation shipped.
 */

const GATE_DETAILS = {
  gate_id: 'verdict-review',
  title: 'Review verdict',
  summary: 'Check the scored verdict.',
  editable: false,
  verdict: 'NEEDS_WORK',
  confidence: 0.62,
  options: [{ id: 'verdict_ok', label: 'Approve', emphasis: 'primary' }],
}

describe('report visibility', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App
  let build: ReturnType<typeof frameFactory>

  beforeEach(async () => {
    localStorage.clear()
    api = new FakeStudioApi()
    build = frameFactory()
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
  })

  afterEach(() => app.unmount())

  it('surfaces the report body carried on the terminal frame', async () => {
    api.emit(build('run_state', {
      event_type: 'WORKFLOW_END',
      details: { status: 'completed', result: { markdown_body: '# Verdict\n\nBody.' } },
    }))
    await flush()

    expect(run.report.value?.markdown_body).toContain('# Verdict')
  })

  it('replaces a clipped frame body with the longer snapshot body', async () => {
    // The real failure, in miniature. The frame arrives first and truncated;
    // the snapshot fetch that `setStatus` triggers must win.
    const full = `# Verdict\n\n${'x'.repeat(9000)}\n\nEND-SENTINEL`
    api.snapshot = { ...api.snapshot, result: { markdown_body: full } }

    api.emit(build('run_state', {
      event_type: 'WORKFLOW_END',
      details: { status: 'completed', result: { markdown_body: full.slice(0, 4096) } },
    }))
    await flush()
    await flush()

    expect(run.report.value?.markdown_body).toHaveLength(full.length)
    expect(run.report.value?.markdown_body).toContain('END-SENTINEL')
  })

  it('never lets a shorter body overwrite a longer one, whatever the order', async () => {
    const long = 'L'.repeat(5000)
    api.snapshot = { ...api.snapshot, result: { markdown_body: long } }
    api.emit(build('run_state', {
      event_type: 'WORKFLOW_END',
      details: { status: 'completed', result: { markdown_body: long } },
    }))
    await flush()
    await flush()

    // A late, clipped duplicate must not shorten what is already on screen.
    api.emit(build('run_state', {
      event_type: 'WORKFLOW_END',
      details: { status: 'completed', result: { markdown_body: 'short' } },
    }))
    await flush()

    expect(run.report.value?.markdown_body).toHaveLength(5000)
  })

  it('keeps the verdict when the gate that carried it closes', async () => {
    // `gate_closed` nulls `pendingGate`, and that card was the only place the
    // score was ever rendered - so answering the gate used to destroy the run's
    // conclusion.
    api.emit(build('gate_open', {
      event_type: 'HUMAN_INTERACTION',
      node_id: 'review_verdict',
      details: GATE_DETAILS,
    }))
    await flush()
    expect(run.pendingGate.value?.verdict).toBe('NEEDS_WORK')

    api.emit(build('gate_closed', {
      event_type: 'HUMAN_INTERACTION',
      node_id: 'review_verdict',
      details: { gate_id: 'verdict-review', outcome: 'verdict_ok' },
    }))
    await flush()

    expect(run.pendingGate.value).toBeNull()
    // The gate is the FALLBACK carrier and says so. It has the headline and
    // nothing else - no composite, no floors, no scorecard - which is exactly
    // why the `verdict` frame exists; see `verdictFrame.spec.ts`.
    expect(run.verdictSummary.value).toEqual({
      verdict: 'NEEDS_WORK',
      confidence: 0.62,
      compositeScore: null,
      confidenceBand: null,
      provisional: null,
      fatalFloors: [],
      decisionReason: null,
      dimensions: null,
      source: 'gate',
    })
  })

  it('leaves the verdict alone when a scope gate closes', async () => {
    // Only the verdict gate carries a score. A scope gate closing must not
    // blank one that is already held.
    api.emit(build('gate_open', {
      event_type: 'HUMAN_INTERACTION',
      node_id: 'review_verdict',
      details: GATE_DETAILS,
    }))
    api.emit(build('gate_closed', {
      event_type: 'HUMAN_INTERACTION',
      node_id: 'review_verdict',
      details: { gate_id: 'verdict-review', outcome: 'verdict_ok' },
    }))
    await flush()

    api.emit(build('gate_open', {
      event_type: 'HUMAN_INTERACTION',
      node_id: 'confirm_scope',
      details: { gate_id: 'scope-confirmation', title: 'Confirm scope', options: [] },
    }))
    api.emit(build('gate_closed', {
      event_type: 'HUMAN_INTERACTION',
      node_id: 'confirm_scope',
      details: { gate_id: 'scope-confirmation', outcome: 'scope_ok' },
    }))
    await flush()

    expect(run.verdictSummary.value?.verdict).toBe('NEEDS_WORK')
  })

  it('ignores a result with no usable body', async () => {
    api.emit(build('run_state', {
      event_type: 'WORKFLOW_END',
      details: { status: 'completed', result: { markdown_body: '   ' } },
    }))
    await flush()
    expect(run.report.value).toBeNull()
  })

  it('clears the report and verdict on relaunch', async () => {
    api.emit(build('run_state', {
      event_type: 'WORKFLOW_END',
      details: { status: 'completed', result: { markdown_body: '# Done' } },
    }))
    await flush()
    expect(run.report.value).not.toBeNull()

    await run.launch()
    expect(run.report.value).toBeNull()
    expect(run.verdictSummary.value).toBeNull()
  })
})

describe('gates mode', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App

  beforeEach(async () => {
    localStorage.clear()
    api = new FakeStudioApi()
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
  })

  afterEach(() => app.unmount())

  it('defaults to UNATTENDED gates', () => {
    // Owner decision, and the server now agrees: `create_run` permits `auto`
    // for any AUTHENTICATED caller, because the flag exists to stop anonymous
    // unattended runs rather than owned ones. A signed-in run is owned,
    // rate-limited per user, and bounded by MAX_RUN_COST_USD. Review stays one
    // click away. Anyone flipping this back should be doing it on purpose.
    expect(run.gatesMode.value).toBe('auto')
  })

  it('sends auto gates on a default launch', async () => {
    await run.launch()
    expect(api.startRunCalls).toEqual([
      expect.objectContaining({ gates: 'auto' }),
    ])
  })

  it('sends human gates when Review is selected', async () => {
    // The toggle back must keep working: Review is how an operator restores
    // the pause, and with it the only brake on an unattended run's spend.
    run.gatesMode.value = 'human'
    await run.launch()
    expect(api.startRunCalls).toEqual([
      expect.objectContaining({ gates: 'human' }),
    ])
  })

  it('sends auto gates when unattended is selected', async () => {
    // This control spends money when it works. `auto` runs the whole pipeline
    // with nobody at the gates, so a silent regression is expensive in one
    // direction and useless in the other. Each case gets a fresh composable
    // because `canLaunch` is false while a run is in flight - relaunching
    // mid-run is a no-op by design.
    run.gatesMode.value = 'auto'
    await run.launch()
    expect(api.startRunCalls).toEqual([
      expect.objectContaining({ gates: 'auto' }),
    ])
  })

  it('passes the idea and workflow alongside the mode', async () => {
    run.idea.value = 'a clinic scheduler'
    await run.launch()
    expect(api.startRunCalls.at(-1)).toMatchObject({
      idea: 'a clinic scheduler',
      workflowId: 'idea-validator',
      gates: 'auto',
    })
  })
})

/**
 * The transport banner must track the transport, in BOTH directions.
 *
 * The banner exists because a scripted mock run was indistinguishable from a
 * paid one, and it is deliberately non-dismissible. That makes a stale banner
 * expensive in the opposite direction: left over a real run, it tells an
 * operator that the money they are spending is a demonstration.
 *
 * This is the recovery path, not an edge case. A cold Render service fails the
 * page-load probe; the operator clicks Launch rather than reloading; `startRun`
 * re-probes and succeeds. `launch()` refreshed `transportMode` from the api but
 * not `probeFailure`, so the alert survived onto a live run.
 */
describe('the transport banner', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App

  beforeEach(() => {
    localStorage.clear()
    api = new FakeStudioApi()
    ;[run, app] = withSetup(() => useValidatorRun(api))
  })

  afterEach(() => app.unmount())

  it('shows the probe failure recorded at page load', async () => {
    api.mode = 'mock'
    api.probeFailure = 'The validator API did not respond within 8s.'
    await run.initialize()
    await flush()

    expect(run.transportProblem.value).toContain('did not respond')
  })

  it('clears the banner when a later probe recovers', async () => {
    api.mode = 'mock'
    api.probeFailure = 'The validator API did not respond within 8s.'
    await run.initialize()
    await flush()
    expect(run.transportProblem.value).not.toBe('')

    // The re-probe inside startRun succeeds this time.
    api.mode = 'live'
    api.probeFailure = null
    await run.launch()
    await flush()

    expect(run.transportMode.value).toBe('live')
    // A live run must never carry "no agent is running" over it.
    expect(run.transportProblem.value).toBe('')
  })

  it('stays silent when the probe succeeded all along', async () => {
    api.mode = 'live'
    api.probeFailure = null
    await run.initialize()
    await flush()
    await run.launch()
    await flush()

    expect(run.transportProblem.value).toBe('')
  })
})

/**
 * THE SHEET IS ABOVE THE CANVAS, asserted from source because the alternative
 * is a picture.
 *
 * `after-1440.png` showed the graph and the stage lane reading through a report
 * that the shipped stylesheet paints in `--surface-strong` - an opaque
 * `#222426` with no alpha at all, verified in the built bundle. Two people
 * looked at that capture and read it two ways, which is exactly the argument
 * for an assertion: a ratio or a declaration can be checked, and a picture is
 * an opinion until somebody re-takes it.
 *
 * A unit test cannot compute a stacking order - jsdom lays nothing out - so
 * what these check is the three DECLARATIONS that make the order unambiguous.
 * The browser-side half is RV1's, and the exact instrument is:
 *
 *     const sheet = page.locator('.report-panel')
 *     expect(await styleOf(sheet, 'background-color')).toBe('rgb(34, 36, 38)')
 *     // light theme: rgb(243, 245, 247)
 *
 * plus a hit test on a point inside the sheet that sits over a node - if the
 * element at that point is not the sheet or one of its descendants, the sheet
 * is under the canvas and no colour assertion will say so.
 */
describe('the report sheet cannot be painted through', () => {
  // `process.cwd()` is `frontend/` under vitest, and a plain relative path is
  // what survives Windows: `import.meta.url` is not a file: URL here, so
  // `new URL(...)` throws before a single assertion runs.
  const source = readFileSync('src/components/ReportPanel.vue', 'utf8')
  const rule = ruleFor(source, '.report-panel')

  it('is positioned, so its z-index is not inert', () => {
    // A `z-index` on a `position: static` element does nothing at all, and that
    // is the failure mode this assertion exists for: the declaration would
    // still be there, the sheet would still be behind the graph, and the CSS
    // would look correct to a reader.
    expect(rule).toMatch(/position:\s*absolute/)
  })

  it('is its own stacking context whatever changes around it', () => {
    expect(rule).toMatch(/isolation:\s*isolate/)
  })

  it('outranks every sibling in the workspace', () => {
    // `--z-control` (30) against `.canvas-heading` 8, `.stream-reconnecting`
    // and `.crew-progress` 9, and the reopen FAB 11. Named rather than
    // numbered so the comparison survives a renumbering of the scale.
    expect(rule).toMatch(/z-index:\s*var\(--z-control\)/)
  })

  it('is opaque, with no alpha for a graph to show through', () => {
    // `--surface-strong` is the only surface token with no alpha channel.
    // `--surface-overlay` at 94% was tried first and is what produced the
    // capture this block is named for.
    expect(rule).toMatch(/background:\s*var\(--surface-strong\)/)
    expect(rule).not.toMatch(/background:\s*var\(--surface-overlay\)/)
  })

  it('does not escape the rails, which are a different stacking context', () => {
    // `.graph-workspace` declares `position: relative; z-index: 0`, so it IS a
    // stacking context and everything in ReportPanel.vue is trapped below
    // `--z-rail`. Without this the line above would put a report over the
    // controls, which is a worse defect than the one it fixes.
    const shell = readFileSync('src/studio.css', 'utf8')
    expect(ruleFor(shell, '.graph-workspace')).toMatch(/z-index:\s*var\(--z-base\)/)
  })
})

/**
 * The right rail is above the canvas for the same reason and by a different
 * route: it is a sibling of `.graph-workspace` rather than a child, so it is
 * compared with the workspace's own `z-index: 0` and not with anything inside
 * it. One number covers the rail whether it is a grid column (>= 1180px) or an
 * overlay (below it).
 */
describe('the control rail cannot be painted through', () => {
  const shell = readFileSync('src/studio.css', 'utf8')
  const rule = ruleFor(shell, '.control-rail')

  it('is positioned and outranks the workspace', () => {
    expect(rule).toMatch(/position:\s*relative/)
    expect(rule).toMatch(/z-index:\s*var\(--z-rail\)/)
  })

  it('is opaque, because below 1180px it overlays the graph', () => {
    // `--bg-app`, not `--surface-overlay`: at 94% with the blur gone, the
    // report panel's own Copy Markdown button ghosted through the GATES and
    // VIEW controls (`evidence/T3/after-1180.png`).
    expect(rule).toMatch(/background:\s*var\(--bg-app\)/)
  })
})
