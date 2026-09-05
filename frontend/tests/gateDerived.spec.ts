import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { App } from 'vue'
import GateCard from '../src/components/GateCard.vue'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import { buildMockSegments } from '../src/data/mockFrames'
import { StudioApi } from '../src/services/studioApi'
import type { BackendRunSnapshot, GateDerivedField, PendingGate } from '../src/types/studio'
import { FakeStudioApi, RUN_ID, flush, frameFactory, withSetup } from './helpers'

/**
 * A gate must not invite an edit it cannot honour.
 *
 * `Verdict` recomputes its composite score, confidence, band, fatal floors,
 * provisional flag and label from the five dimension scores on every
 * validation, and discards whatever it was sent. The verdict gate used to
 * render all of that as text inputs, so an operator could set VALIDATE, submit,
 * and watch REJECT come back - the client promising something the server would
 * never honour, in the one place where the operator's judgement is supposed to
 * be real.
 *
 * The server now sends two halves: `fields`, which an edit reaches, and
 * `derived`, which it does not. These tests hold the client to that: read every
 * derived value, type into none of them, and send back only what was offered.
 */

const VERDICT_DERIVED: GateDerivedField[] = [
  { key: 'demand', kind: 'json', value: '{\n  "score": 2,\n  "evidence_thin": true\n}' },
  { key: 'composite_score', kind: 'text', value: '5.0' },
  { key: 'confidence', kind: 'text', value: '0.7' },
  { key: 'confidence_band', kind: 'text', value: 'HIGH' },
  { key: 'fatal_floors', kind: 'json', value: '[]' },
  { key: 'verdict', kind: 'text', value: 'NEEDS_WORK' },
  { key: 'provisional', kind: 'text', value: 'false' },
]

function verdictGate(overrides: Partial<PendingGate> = {}): PendingGate {
  return {
    gateId: 'verdict-review',
    nodeId: 'review_verdict',
    title: 'Review verdict',
    summary: 'Offer a paid pilot to three teams already paying for a codegen tool.',
    editable: true,
    expiresAt: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
    expired: false,
    options: [
      { id: 'approve', label: 'Approve', emphasis: 'primary' },
      { id: 'revise', label: 'Revise' },
    ],
    fields: { feedback: '' },
    derived: VERDICT_DERIVED,
    verdict: 'NEEDS_WORK',
    confidence: 0.7,
    ...overrides,
  }
}

function mountGate(gate: PendingGate) {
  return mount(GateCard, { props: { gate, submitting: false } })
}

describe('GateCard separates what an edit reaches from what it does not', () => {
  it('offers one control for the verdict gate, and it is the note', () => {
    const wrapper = mountGate(verdictGate())

    // Not "few inputs" - exactly the editable ones, and nothing else.
    expect(wrapper.findAll('input')).toHaveLength(0)
    expect(wrapper.findAll('textarea')).toHaveLength(1)
    expect(wrapper.findAll('.gate-field')).toHaveLength(1)
    expect(wrapper.get('.gate-field span').text()).toBe('Feedback')
  })

  it('shows every derived value, and none of them inside a form control', () => {
    const wrapper = mountGate(verdictGate())
    const block = wrapper.get('.gate-derived')

    // Every key is still named, now in words rather than as a shouted Python
    // field: `MEDIAN MARKET SOURCE AGE MONTHS` read as a constant name even
    // after the underscores came out.
    expect(block.findAll('dt').map((node) => node.attributes('data-key'))).toEqual(
      VERDICT_DERIVED.map((item) => item.key),
    )
    expect(block.text()).toContain('Composite score')
    expect(block.text()).toContain('Confidence band')

    // The whole basis for the decision is legible - and legible now means
    // English. `NEEDS_WORK` reached an operator at the moment they were asked
    // to approve or revise it.
    expect(block.text()).toContain('Needs work')
    expect(block.text()).not.toContain('NEEDS_WORK')
    expect(block.text()).toContain('High')
    expect(block.text()).toContain('5.0')
    // ...and none of it is typeable.
    expect(block.findAll('input, textarea, select')).toHaveLength(0)
    // Product-neutral: this card renders a gate from ANY flow, and a
    // user-authored graph has no validator, no scores and no evidence.
    expect(block.text()).toContain('Computed by the run')
    expect(block.text()).toContain('edit the inputs above and it is recomputed')
    expect(block.text()).not.toMatch(/validator|rubric|dimension score/i)
  })

  it('decodes a json value into labelled rows rather than dumping it', () => {
    // WAS: two `<pre>` blocks, one of them the literal `[]`. A `<pre>` is what
    // this card used to do with every structured value, and it is what put
    // `FATAL FLOORS / []` in front of the operator.
    const wrapper = mountGate(verdictGate())

    expect(wrapper.findAll('.gate-derived pre')).toHaveLength(0)
    const demand = wrapper.get('.gate-derived dd')
    expect(demand.text()).toContain('Score')
    expect(demand.text()).toContain('2')
    // `evidence_thin: true` is a yes/no question, and now reads as one.
    expect(demand.text()).toContain('Evidence thin')
    expect(demand.text()).toContain('yes')
  })

  it('says none for an empty list and an em dash for a null', () => {
    const wrapper = mountGate(
      verdictGate({
        derived: [
          { key: 'fatal_floors', kind: 'json', value: '[]' },
          { key: 'decision_reason', kind: 'text', value: 'null' },
          { key: 'provisional', kind: 'text', value: 'false' },
        ],
      }),
    )
    const values = wrapper.findAll('.gate-derived dd').map((node) => node.text())

    expect(values).toEqual(['none', '—', 'no'])
  })

  it('puts a value it will not flatten behind a collapsed disclosure', () => {
    // One level of key: value is a scorecard; two is a structure, and a
    // structure belongs where a developer can still reach it and an operator
    // is not made to read it.
    const wrapper = mountGate(
      verdictGate({
        derived: [
          {
            key: 'branch_detail',
            kind: 'json',
            value: '{\n  "market": {"sources": 3},\n  "ok": true\n}',
          },
        ],
      }),
    )
    const details = wrapper.get('.gate-derived details')

    expect(details.attributes('open')).toBeUndefined()
    expect(details.text()).toContain('"sources": 3')
    expect(wrapper.get('.derived-pairs').text()).toContain('Ok')
  })

  it('sends back only the fields it was offered', async () => {
    const wrapper = mountGate(verdictGate())
    await wrapper.get('textarea').setValue('Rescore demand against the paying segment.')
    await wrapper.findAll('.gate-actions button')[1].trigger('click')

    expect(wrapper.emitted('submit')).toEqual([
      ['revise', { feedback: 'Rescore demand against the paying segment.' }],
    ])
  })

  it('keeps every scope field editable, because every one is honoured', () => {
    const wrapper = mountGate(
      verdictGate({
        gateId: 'scope-confirmation',
        nodeId: 'confirm_scope',
        title: 'Confirm scope',
        fields: { category: 'Clinic scheduling', target_user: 'Clinic ops', feedback: '' },
        derived: [],
        verdict: undefined,
        confidence: undefined,
      }),
    )

    expect(wrapper.find('.gate-derived').exists()).toBe(false)
    expect(wrapper.findAll('input')).toHaveLength(2)
    expect(wrapper.findAll('textarea')).toHaveLength(1)
    // Every underscore, not just the first: `target_user`, not `target user_`.
    expect(wrapper.findAll('.gate-field span').map((node) => node.text())).toEqual([
      'Category',
      'Target user',
      'Feedback',
    ])
  })

  it('renders nothing derived when an older backend sends none', () => {
    const wrapper = mountGate(verdictGate({ derived: undefined }))

    expect(wrapper.find('.gate-derived').exists()).toBe(false)
    expect(wrapper.findAll('textarea')).toHaveLength(1)
  })

  it('still submits a derived-heavy gate after its deadline passed', async () => {
    // PRD F03 has to keep working through the read-only block: expiry is
    // informational, and a gate with nothing editable but the note is still
    // answerable when it is late.
    const wrapper = mountGate(verdictGate({ expired: true, overdueSeconds: 300 }))

    for (const button of wrapper.findAll('.gate-actions button')) {
      expect(button.attributes('disabled')).toBeUndefined()
    }
    await wrapper.findAll('.gate-actions button')[0].trigger('click')
    expect(wrapper.emitted('submit')).toEqual([['approve', { feedback: '' }]])
  })
})

describe('the split survives every path a gate reaches the client by', () => {
  let app: App

  afterEach(() => app?.unmount())

  it('carries derived values off the live frame stream', async () => {
    const api = new FakeStudioApi()
    let run: ReturnType<typeof useValidatorRun>
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
    await flush()

    const build = frameFactory(RUN_ID)
    api.emit(
      build('gate_open', {
        event_type: 'HUMAN_INTERACTION',
        node_id: 'review_verdict',
        details: {
          gate_id: 'verdict-review',
          title: 'Review verdict',
          summary: 'Read the score.',
          editable: true,
          fields: { feedback: '' },
          derived: VERDICT_DERIVED,
          options: [{ id: 'approve', label: 'Approve', emphasis: 'primary' }],
        },
      }),
    )
    await flush()

    expect(run.pendingGate.value?.fields).toEqual({ feedback: '' })
    expect(run.pendingGate.value?.derived?.map((item) => item.key)).toEqual(
      VERDICT_DERIVED.map((item) => item.key),
    )
  })

  it('carries them off the refresh-recovery snapshot too', async () => {
    const fetchMock = vi.fn()
    const originalFetch = globalThis.fetch
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch
    const snapshot: BackendRunSnapshot = {
      run_id: 'run-1',
      status: 'waiting',
      pending_gate: {
        gate_id: 'verdict-review',
        node_id: 'review_verdict',
        title: 'Review verdict',
        summary: 'Read the score.',
        editable: true,
        options: [{ id: 'approve', label: 'Approve', emphasis: 'primary' }],
        fields: { feedback: '' },
        derived: VERDICT_DERIVED,
        verdict: 'NEEDS_WORK',
        confidence: 0.7,
      },
      frames: { count: 1, dropped: 0, first_seq: 1, last_seq: 1 },
      usage: {},
    }
    fetchMock.mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => snapshot,
    })

    const api = new StudioApi()
    api.mode = 'live'
    try {
      const result = await api.getRun('run-1')
      expect(result.pending_gate?.fields).toEqual({ feedback: '' })
      expect(result.pending_gate?.derived).toEqual(VERDICT_DERIVED)
    } finally {
      globalThis.fetch = originalFetch
    }
  })
})

describe('the offline mock rehearses the real gate payload', () => {
  /**
   * The mock is generated from the live descriptor and the live prompt builder
   * on purpose: it is how this defect became visible in the first place, when
   * the verdict prompt turned out to be nineteen editable inputs. If the mock
   * quietly tidied the payload instead, nothing offline would ever show it.
   */
  const gateOpen = (nodeId: string) =>
    buildMockSegments('mock-run')
      .flat()
      .map((step) => step.frame)
      .find((frame) => frame.kind === 'gate_open' && frame.node_id === nodeId)!

  it('offers only the note at the verdict gate', () => {
    const details = gateOpen('review_verdict').details as Record<string, unknown>

    expect(Object.keys(details.fields as Record<string, string>)).toEqual(['feedback'])
  })

  it('shows every recomputed field as read-only detail instead', () => {
    const details = gateOpen('review_verdict').details as Record<string, unknown>
    const derived = details.derived as GateDerivedField[]
    const byKey = new Map(derived.map((item) => [item.key, item.value]))

    for (const key of [
      'composite_score',
      'confidence',
      'confidence_band',
      'verdict',
      'decision_reason',
      'fatal_floors',
      'provisional',
    ]) {
      expect(byKey.has(key)).toBe(true)
    }
    // Generated from a real `Verdict`, so the arithmetic is the rubric's own.
    expect(byKey.get('composite_score')).toBe('5.0')
    expect(byKey.get('confidence')).toBe('0.7')
    expect(byKey.get('verdict')).toBe('NEEDS_WORK')
  })

  it('keeps the scope gate fully editable with nothing derived', () => {
    const details = gateOpen('confirm_scope').details as Record<string, unknown>

    expect(details.derived).toEqual([])
    expect(Object.keys(details.fields as Record<string, string>)).toContain('category')
    expect(Object.keys(details.fields as Record<string, string>)).toContain('feedback')
  })
})

describe('the mock run answers its gates through the real composable', () => {
  let app: App
  let originalFetch: typeof globalThis.fetch

  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    originalFetch = globalThis.fetch
    globalThis.fetch = vi.fn(async () => {
      throw new Error('connection refused')
    }) as unknown as typeof globalThis.fetch
  })

  afterEach(() => {
    app?.unmount()
    globalThis.fetch = originalFetch
    vi.useRealTimers()
  })

  it('reaches the verdict gate with one editable field and a full read-only block', async () => {
    const api = new StudioApi()
    let run: ReturnType<typeof useValidatorRun>
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
    await flush()

    const tick = async (ms: number) => {
      for (let elapsed = 0; elapsed < ms; elapsed += 40) {
        vi.advanceTimersByTime(40)
        await flush(3)
      }
    }

    await tick(5_000)
    expect(run.pendingGate.value?.nodeId).toBe('confirm_scope')
    await run.submitGate('approve', run.pendingGate.value?.fields)
    await flush()
    await tick(22_000)

    expect(run.pendingGate.value?.nodeId).toBe('review_verdict')
    expect(Object.keys(run.pendingGate.value?.fields ?? {})).toEqual(['feedback'])
    expect(
      run.pendingGate.value?.derived?.map((item) => item.key),
    ).toContain('composite_score')
  })
})
