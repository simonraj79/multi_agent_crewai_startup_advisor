import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { App } from 'vue'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import { FakeStudioApi, flush, frameFactory, withSetup } from './helpers'

type ValidatorRun = ReturnType<typeof useValidatorRun>

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

  it('defaults to human gates', () => {
    expect(run.gatesMode.value).toBe('human')
  })

  it('sends human gates on a default launch', async () => {
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
      gates: 'human',
    })
  })
})
