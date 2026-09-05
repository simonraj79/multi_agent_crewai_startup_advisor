import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import verdictFrames from './fixtures/backendVerdictFrames.json'
import GateCard from '../src/components/GateCard.vue'
import ReportPanel from '../src/components/ReportPanel.vue'
import { buildMockSegments } from '../src/data/mockFrames'
import type { PendingGate, RunResult, VerdictSummary } from '../src/types/studio'

/**
 * T1.3: no raw internal code reaches the run shell's DOM.
 *
 * The rule is mechanical on purpose. A reviewer reading a screenshot can miss
 * one leaked token among forty; a regex cannot, and it goes on not missing it
 * after everybody who read this has moved on. What it looks for is the shape
 * an identifier has and prose does not - a shouted word joined to another by
 * an underscore - which is exactly what `FLOOR_NO_MARKET`, `NEEDS_WORK`,
 * `INSUFFICIENT_EVIDENCE` and `HAS_PROBLEM` all are.
 *
 * The allowlist is EXPORTED rather than inlined so that it is a list somebody
 * can read and argue with, instead of a set of exceptions discovered one at a
 * time by whoever next makes this fail. Adding to it is a decision; every
 * entry says why it is not a leak.
 */

/** The shape of an internal identifier: a shout joined by an underscore. */
export const SHOUTED_CODE = /\b[A-Z][A-Z0-9]+(_[A-Z0-9]+)+\b/

/**
 * Tokens of this shape that are legitimately technical, and why.
 *
 * Nothing here is a rubric enum, a Python identifier or a flow method name. If
 * a future entry is one of those, it belongs in the humaniser, not here.
 */
export const ALLOWED_SHOUTED_TOKENS: readonly string[] = [
  // File formats the operator is choosing between on a download button.
  'NDJSON',
  'ZIP',
  // An OpenRouter model id, when one is shown: it is the name of the thing
  // billed, and renaming it would make an invoice unmatchable.
  'GPT_4O',
]

/** Every allowlisted token removed, so what is left is the real finding. */
function offendingTokens(text: string): string[] {
  const global = new RegExp(SHOUTED_CODE.source, 'g')
  return (text.match(global) ?? []).filter(
    (token) => !ALLOWED_SHOUTED_TOKENS.includes(token),
  )
}

/**
 * A report body with no codes of its own, so a failure here can only be the
 * shell's. The Reporter's markdown is the report's own content and is out of
 * scope for this rule - it is prose the model wrote, not a constant the client
 * leaked.
 */
const REPORT: RunResult = {
  markdown_body: '# Verdict\n\nThe scoped v1 has thin demand evidence.',
  provisional: true,
  thin_dimensions: ['D', 'C', 'F', 'X'],
  sources: [{ url: 'https://example.com/pricing', title: 'Pricing' }],
}

interface VerdictFrameDetails {
  verdict: string
  composite_score: number
  confidence: number
  confidence_band: string
  provisional: boolean
  fatal_floors: string[]
  decision_reason: string | null
  dimensions: Record<string, number>
}

/** The `verdict` frames the backend really emits, read off the committed fixture. */
function verdictSummaries(): VerdictSummary[] {
  const frames = verdictFrames as unknown as Array<{ details: VerdictFrameDetails }>
  return frames.map((frame) => {
    const d = frame.details
    return {
      verdict: d.verdict,
      confidence: d.confidence,
      compositeScore: d.composite_score,
      confidenceBand: d.confidence_band,
      provisional: d.provisional,
      fatalFloors: d.fatal_floors,
      decisionReason: d.decision_reason,
      dimensions: d.dimensions,
      source: 'frame' as const,
    }
  })
}

/**
 * The demonstration run's verdict gate, taken from the script the console
 * really plays rather than hand-written here - a fixture that diverges from
 * its subject certifies nothing.
 */
function verdictGateFromMock(): PendingGate {
  const step = buildMockSegments('run-under-test')
    .flat()
    .find(
      (entry) =>
        entry.frame.kind === 'gate_open' &&
        (entry.frame.details as Record<string, unknown>)?.verdict !== undefined,
    )
  expect(step).toBeDefined()
  const d = step!.frame.details as unknown as {
    gate_id: string
    node_id: string
    title: string
    summary: string
    editable: boolean
    expires_at: string
    fields: Record<string, string>
    derived: PendingGate['derived']
    options: PendingGate['options']
    verdict: string
    confidence: number
  }
  return {
    gateId: d.gate_id,
    nodeId: d.node_id,
    title: d.title,
    summary: d.summary,
    editable: d.editable,
    expiresAt: d.expires_at,
    expired: false,
    options: d.options,
    fields: d.fields,
    derived: d.derived,
    verdict: d.verdict,
    confidence: d.confidence,
  }
}

describe('no internal code reaches the shell (T1.3)', () => {
  it('finds a leaked code when there is one, so a pass means something', () => {
    // The control. Without it, a regex that never matched anything would look
    // exactly like a shell that never leaks - the failure mode this whole
    // repository has a section about.
    expect(offendingTokens('reads NEEDS_WORK because FLOOR_NO_MARKET')).toEqual([
      'NEEDS_WORK',
      'FLOOR_NO_MARKET',
    ])
    expect(offendingTokens('Download as NDJSON or ZIP')).toEqual([])
  })

  it('renders every real verdict frame without one', () => {
    for (const verdict of verdictSummaries()) {
      const wrapper = mount(ReportPanel, {
        props: { report: REPORT, verdict, open: true },
      })
      expect(offendingTokens(wrapper.text())).toEqual([])
      wrapper.unmount()
    }
  })

  it('renders the low-confidence override without one', () => {
    // The screen this work started from: `NEEDS_WORK`, `LOW`, `PROVISIONAL`,
    // `FLOOR_NO_MARKET` and a bare `INSUFFICIENT_EVIDENCE`, five codes in one
    // header.
    const wrapper = mount(ReportPanel, {
      props: {
        report: REPORT,
        verdict: {
          verdict: 'NEEDS_WORK',
          confidence: 0.34,
          compositeScore: 4.2,
          confidenceBand: 'LOW',
          provisional: true,
          fatalFloors: ['FLOOR_NO_MARKET'],
          decisionReason: 'INSUFFICIENT_EVIDENCE',
          dimensions: {
            demand: 2,
            market: 0,
            competitive_room: 3,
            feasibility: 3,
            headroom_over_free: 4,
          },
          source: 'frame',
        },
        open: true,
      },
    })
    const text = wrapper.text()

    expect(offendingTokens(text)).toEqual([])
    // And the reader is told the true cause, in words.
    expect(text).toContain('Too little evidence to judge.')
    expect(text).toContain('Thin evidence · Demand, Competitive room, Feasibility and Headroom over free')
    expect(text).toContain('Provisional · not a final answer')
    // The codes are still in the DOM where a grep and an E2E assertion can
    // reach them - as attributes, not as reading matter.
    expect(wrapper.get('.verdict-decision').attributes('data-code')).toBe('INSUFFICIENT_EVIDENCE')
  })

  it('renders a code the client has never seen without showing it', () => {
    const wrapper = mount(ReportPanel, {
      props: {
        report: REPORT,
        verdict: {
          verdict: 'HARD_REJECT',
          confidence: 0.5,
          compositeScore: 1.0,
          confidenceBand: 'UNCERTAIN_LOW',
          provisional: false,
          fatalFloors: ['FLOOR_NO_RUNWAY'],
          decisionReason: 'FLOOR_NO_RUNWAY',
          dimensions: { demand: 1, regulatory_risk: 0 },
          source: 'frame',
        },
        open: true,
      },
    })

    expect(offendingTokens(wrapper.text())).toEqual([])
    expect(wrapper.text()).toContain('Hard reject')
    expect(wrapper.text()).toContain('No runway.')
    expect(wrapper.text()).toContain('Regulatory risk')
  })

  it('renders the verdict gate without one', () => {
    // The densest concentration of raw codes anywhere in the console, and the
    // screen where the operator is asked to approve a decision: the whole
    // `derived` payload used to arrive as `NEEDS_WORK`, `HIGH`, `[]`, `null`
    // and `false` inside a `<pre>`.
    const wrapper = mount(GateCard, {
      props: { gate: verdictGateFromMock(), submitting: false },
    })
    const text = wrapper.text()

    expect(offendingTokens(text)).toEqual([])
    expect(text).toContain('Needs work')
    expect(text).toContain('none')
    expect(text).toContain('—')
  })
})
