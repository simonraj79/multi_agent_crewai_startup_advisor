import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { App } from 'vue'
import ReportPanel from '../src/components/ReportPanel.vue'
import { parseVerdictFrame, useValidatorRun } from '../src/composables/useValidatorRun'
import { buildMockSegments } from '../src/data/mockFrames'
import type { FrameData, RunResult, VerdictSummary } from '../src/types/studio'
import { FakeStudioApi, RUN_ID, flush, frameFactory, withSetup } from './helpers'

type ValidatorRun = ReturnType<typeof useValidatorRun>

/**
 * The verdict, delivered as a frame rather than rescued from a gate.
 *
 * The deterministic `Verdict` is the deliverable this product is built around,
 * and until the `verdict` frame existed it reached the console through exactly
 * one door: the read-only `derived` block on the verdict gate card, copied into
 * `verdictSummary` by `closeGate` at the instant that card disappeared. Two
 * things followed, and both are what these tests hold shut.
 *
 * An unattended run has no such door. `gates: "auto"` never opens a verdict
 * gate, so the mode whose entire purpose is producing the score without a human
 * showed a `COMPLETE` badge and no number at all - the feature working exactly
 * as designed produced strictly less output than the one needing a babysitter.
 *
 * And a gate carries a headline, not a scorecard: no composite, no confidence
 * band, no dimension scores, and no `fatal_floors` - the floors that PRD 10.2
 * calls "the most valuable output this system produces", which were therefore
 * invisible in every mode.
 *
 * So the frame is authoritative and the gate is a fallback that must not
 * overwrite it. The gate path is kept rather than deleted because a run
 * replayed from frames older than this feature has nothing else to read.
 */

/** The frozen wire contract, exactly as `events/verdict.py` publishes it. */
const VERDICT_DETAILS = {
  verdict: 'NEEDS_WORK',
  composite_score: 4.2,
  confidence: 0.17,
  confidence_band: 'LOW',
  provisional: true,
  fatal_floors: ['FLOOR_NO_DEMAND'],
  decision_reason: 'One usable thread, and nobody in it states a problem.',
  dimensions: {
    demand: 1,
    market: 3,
    competitive_room: 2,
    feasibility: 1,
    headroom_over_free: 3,
  },
}

const GATE_DETAILS = {
  gate_id: 'verdict-review',
  title: 'Review verdict',
  summary: 'Check the scored verdict.',
  editable: false,
  verdict: 'VALIDATE',
  confidence: 0.9,
  options: [{ id: 'verdict_ok', label: 'Approve', emphasis: 'primary' }],
}

function verdictFrame(
  build: ReturnType<typeof frameFactory>,
  details: Record<string, unknown> = VERDICT_DETAILS,
): FrameData {
  return build('verdict', {
    event_type: 'VERDICT_COMPUTED',
    node_id: 'synthesize',
    message: 'Verdict computed: NEEDS_WORK',
    details,
  })
}

describe('the verdict frame', () => {
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

  it('reads the whole scorecard off the frame', async () => {
    api.emit(verdictFrame(build))
    await flush()

    expect(run.verdictSummary.value).toEqual({
      verdict: 'NEEDS_WORK',
      confidence: 0.17,
      compositeScore: 4.2,
      confidenceBand: 'LOW',
      provisional: true,
      fatalFloors: ['FLOOR_NO_DEMAND'],
      decisionReason: 'One usable thread, and nobody in it states a problem.',
      dimensions: { demand: 1, market: 3, competitive_room: 2, feasibility: 1, headroom_over_free: 3 },
      source: 'frame',
    })
  })

  it('delivers the verdict of a run that never opens a gate', async () => {
    // The reason this feature exists. Not one gate frame is emitted here, which
    // is exactly what `gates: "auto"` looks like on the wire - and before the
    // frame this run finished with `verdictSummary` still null.
    api.emit(verdictFrame(build))
    api.emit(build('run_state', {
      event_type: 'WORKFLOW_END',
      details: { status: 'completed', result: { markdown_body: '# Verdict\n\nBody.' } },
    }))
    await flush()
    await flush()

    expect(run.pendingGate.value).toBeNull()
    expect(run.status.value).toBe('completed')
    expect(run.verdictSummary.value?.verdict).toBe('NEEDS_WORK')
    expect(run.verdictSummary.value?.compositeScore).toBe(4.2)
    expect(run.verdictSummary.value?.fatalFloors).toEqual(['FLOOR_NO_DEMAND'])
  })

  it('keeps the frame when a gate closes afterwards claiming something else', async () => {
    // The precedence rule, in the order it happens live: the Flow computes and
    // publishes, then the gate opens carrying a headline. The gate must not
    // flatten the scorecard back down to two fields.
    api.emit(verdictFrame(build))
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

    expect(run.verdictSummary.value?.verdict).toBe('NEEDS_WORK')
    expect(run.verdictSummary.value?.source).toBe('frame')
    expect(run.verdictSummary.value?.compositeScore).toBe(4.2)
  })

  it('lets a frame replace a value a gate had already supplied', async () => {
    // The same rule read the other way. A server that emits the gate first, or
    // a client that reconnected mid-gate, must still end up on the frame.
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
    expect(run.verdictSummary.value?.source).toBe('gate')

    api.emit(verdictFrame(build))
    await flush()

    expect(run.verdictSummary.value?.verdict).toBe('NEEDS_WORK')
    expect(run.verdictSummary.value?.source).toBe('frame')
  })

  it('prefers the newest frame, because a revise loop rescores', async () => {
    // `revise_verdict` re-runs the same crew through the same synthesis step
    // and publishes again on the same node. The correction has to replace the
    // score it disagrees with, or the console shows the rejected one forever.
    api.emit(verdictFrame(build))
    api.emit(verdictFrame(build, {
      ...VERDICT_DETAILS,
      verdict: 'VALIDATE',
      composite_score: 8.4,
      confidence: 0.81,
      confidence_band: 'HIGH',
      provisional: false,
      fatal_floors: [],
    }))
    await flush()

    expect(run.verdictSummary.value?.verdict).toBe('VALIDATE')
    expect(run.verdictSummary.value?.compositeScore).toBe(8.4)
    expect(run.verdictSummary.value?.fatalFloors).toEqual([])
  })

  it('still takes a verdict from a run that only ever sent gate frames', async () => {
    // No regression for anything replayed from before the frame existed. Frames
    // outlive nothing else here: `getFrames` will happily return a run recorded
    // by an older server, and the headline is all it has.
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

    expect(run.verdictSummary.value?.verdict).toBe('VALIDATE')
    expect(run.verdictSummary.value?.confidence).toBe(0.9)
    expect(run.verdictSummary.value?.source).toBe('gate')
  })

  it('survives details a newer or older server might send', async () => {
    // `FrameData.details` is `Record<string, unknown>` off a socket. A throw in
    // here does not surface as a crash either - `queueFrame` catches it into
    // `lastError` - so the assertion on `lastError` is the one that matters.
    api.emit(verdictFrame(build))
    await flush()

    const malformed: Array<Record<string, unknown>> = [
      {},
      { verdict: '   ' },
      { verdict: 42, composite_score: 9 },
      {
        verdict: 'REJECT',
        composite_score: null,
        confidence: 'high',
        confidence_band: 7,
        provisional: 'yes',
        fatal_floors: 'FLOOR_NO_DEMAND',
        decision_reason: 12,
        dimensions: 'nope',
      },
    ]
    for (const details of malformed) api.emit(verdictFrame(build, details))
    // Two microtask ticks per queued frame, and there are five in flight.
    await flush(24)

    expect(run.lastError.value).toBe('')
    // A frame with a usable label still lands, with every unreadable field
    // degraded rather than guessed at.
    expect(run.verdictSummary.value).toMatchObject({
      verdict: 'REJECT',
      compositeScore: null,
      confidence: null,
      confidenceBand: null,
      provisional: null,
      fatalFloors: [],
      decisionReason: null,
      dimensions: null,
    })
  })

  it('never blanks a good verdict with an unreadable one', async () => {
    api.emit(verdictFrame(build))
    api.emit(verdictFrame(build, { composite_score: 9.9 }))
    await flush()

    expect(run.verdictSummary.value?.verdict).toBe('NEEDS_WORK')
    expect(run.verdictSummary.value?.compositeScore).toBe(4.2)
  })

  it('drops junk out of the dimension map and keeps a dimension it has never heard of', async () => {
    // Forward compatibility with a sixth ladder, and the rubric order the panel
    // renders straight through without sorting again.
    api.emit(verdictFrame(build, {
      ...VERDICT_DETAILS,
      dimensions: { novelty: 4, demand: 'two', market: 3, headroom_over_free: 5 },
    }))
    await flush()

    expect(Object.keys(run.verdictSummary.value?.dimensions ?? {})).toEqual([
      'market',
      'headroom_over_free',
      'novelty',
    ])
  })

  it('clears on relaunch', async () => {
    api.emit(verdictFrame(build))
    api.emit(build('run_state', {
      event_type: 'WORKFLOW_END',
      details: { status: 'completed', result: { markdown_body: '# Verdict' } },
    }))
    await flush()
    await flush()
    expect(run.verdictSummary.value).not.toBeNull()

    await run.launch()
    expect(run.verdictSummary.value).toBeNull()
  })
})

describe('a verdict recovered across a page reload', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App

  afterEach(() => app.unmount())

  it('comes back for a run that is still in flight', async () => {
    // Recovery replays every frame and then re-applies the tail past the
    // snapshot cursor through a SECOND dispatch, `applyPostSnapshotFrame`. The
    // two dispatches are separate lists and have to carry the verdict branch
    // independently; this covers the recovery journey end to end.
    localStorage.clear()
    localStorage.setItem(
      'validator-active-run',
      JSON.stringify({ version: 1, runId: RUN_ID, sessionId: 'session-1', workflowId: 'idea-validator' }),
    )
    api = new FakeStudioApi()
    const build = frameFactory()
    api.storedFrames = [verdictFrame(build)]
    api.snapshot = { ...api.snapshot, status: 'running', frames: { count: 1, dropped: 0, first_seq: 1, last_seq: 0 } }

    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await flush()

    expect(run.verdictSummary.value?.verdict).toBe('NEEDS_WORK')
    expect(run.verdictSummary.value?.source).toBe('frame')
  })
})

describe('the offline mock', () => {
  it('publishes the verdict frame too, not just the gate that repeats it', () => {
    // Deployment trap 2: a misconfigured `VITE_API_URL` drops the console into
    // this scripted mock silently. A mock that only ever exercised the fallback
    // carrier would render the console's most important block as blank in
    // exactly the situation nobody realises they are in.
    const frames = buildMockSegments(RUN_ID).flat().map((step) => step.frame)
    const verdicts = frames.filter((frame) => frame.kind === 'verdict')

    expect(verdicts).toHaveLength(1)
    expect(verdicts[0].node_id).toBe('synthesize')
    expect(parseVerdictFrame(verdicts[0].details)).toMatchObject({
      verdict: 'NEEDS_WORK',
      compositeScore: 5,
      confidence: 0.7,
      confidenceBand: 'HIGH',
      source: 'frame',
    })
    // The mock's own gate `derived` block claims the same five scores; a mock
    // that disagreed with itself would teach the wrong lesson twice.
    expect(Object.keys(parseVerdictFrame(verdicts[0].details)?.dimensions ?? {})).toEqual([
      'demand',
      'market',
      'competitive_room',
      'feasibility',
      'headroom_over_free',
    ])
  })
})

describe('the report panel', () => {
  const REPORT: RunResult = {
    markdown_body: '# Verdict\n\nThe scoped v1 has no demand evidence.',
    sources: [],
  }

  const FRAME_VERDICT: VerdictSummary = {
    verdict: 'REJECT',
    confidence: 0.17,
    compositeScore: 4.2,
    confidenceBand: 'LOW',
    provisional: true,
    fatalFloors: ['FLOOR_NO_DEMAND'],
    decisionReason: 'One usable thread, and nobody in it states a problem.',
    dimensions: { demand: 1, market: 3, competitive_room: 2, feasibility: 1, headroom_over_free: 3 },
    source: 'frame',
  }

  function mountPanel(verdict: VerdictSummary | null) {
    return mount(ReportPanel, { props: { report: REPORT, verdict, open: true } })
  }

  it('names the floor that forced the verdict', () => {
    // The whole reason `fatal_floors` is on the wire. A REJECT whose cause is a
    // floor is a different statement from a REJECT that merely scored low, and
    // the panel used to make them indistinguishable.
    const text = mountPanel(FRAME_VERDICT).text()

    expect(text).toContain('Fatal floor')
    expect(text).toContain('No demand')
    // The raw token stays on screen so the rubric is still greppable from it.
    expect(text).toContain('FLOOR_NO_DEMAND')
  })

  it('pluralises and humanises every floor without a lookup table', () => {
    // A floor added to `config.py` after this component was written must still
    // render as words rather than as nothing.
    const text = mountPanel({
      ...FRAME_VERDICT,
      fatalFloors: ['FLOOR_ALREADY_FREE', 'FLOOR_SOMETHING_NEW'],
    }).text()

    expect(text).toContain('Fatal floors')
    expect(text).toContain('Already free')
    expect(text).toContain('Something new')
  })

  it('shows the composite score, the band and all five ladders', () => {
    const wrapper = mountPanel(FRAME_VERDICT)
    const text = wrapper.text()

    expect(text).toContain('REJECT')
    expect(text).toContain('4.2')
    expect(text).toContain('/10')
    expect(text).toContain('17% confidence')
    expect(text).toContain('LOW')
    expect(wrapper.findAll('.score-row')).toHaveLength(5)
    expect(wrapper.findAll('.score-label').map((node) => node.text())).toEqual([
      'Demand',
      'Market',
      'Competitive room',
      'Feasibility',
      'Headroom over free',
    ])
    // 1 of 5 is a fifth of the track, not a fifth of a 0-10 composite.
    expect(wrapper.findAll('.score-fill')[0].attributes('style')).toContain('width: 20%')
  })

  it('still renders a gate-only verdict, with no scorecard invented for it', () => {
    // The fallback carrier has a headline and nothing else, and the panel must
    // not fill the gap with zeroes - a `0/5` nobody scored is a lie.
    const wrapper = mountPanel({
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

    expect(wrapper.text()).toContain('NEEDS_WORK')
    expect(wrapper.text()).toContain('62% confidence')
    expect(wrapper.find('.verdict-summary').exists()).toBe(false)
  })

  it('falls back to COMPLETE when no carrier delivered a verdict at all', () => {
    const wrapper = mountPanel(null)

    expect(wrapper.text()).toContain('COMPLETE')
    expect(wrapper.find('.verdict-summary').exists()).toBe(false)
  })

  it('flags a provisional verdict even when the report body does not', () => {
    // `ValidationReport.provisional` and the verdict's own flag are separate
    // fields on separate carriers. Dropping the warning is the only failure
    // here that costs anything, so either saying so is enough.
    const wrapper = mountPanel(FRAME_VERDICT)
    expect(wrapper.text()).toContain('PROVISIONAL')
  })
})
