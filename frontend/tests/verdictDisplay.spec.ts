import { describe, expect, it } from 'vitest'
import {
  DECISIONS,
  DIMENSIONS,
  confidenceChip,
  confidenceWord,
  describeDecision,
  describeValue,
  dimensionName,
  dimensionQuestion,
  thinDimensionKeys,
  thinEvidencePhrase,
  verdictLabel,
} from '../src/data/verdictDisplay'
import type { RunResult, VerdictSummary } from '../src/types/studio'

/**
 * The run's conclusion, in words.
 *
 * Criteria T1.2 and T1.4 of `docs/run-shell/DEFINITION-OF-DONE.md`: the
 * dimension and its score are named in plain language, the evidence chip names
 * dimensions in words, the band and provisional status are words - and an
 * unknown floor code, dimension key or band still renders as words rather than
 * as SNAKE_CASE.
 *
 * The load-bearing fact underneath all of it, and the reason this file exists
 * at all: `Verdict.compute_mechanical_result` computes `fatal_floors` and
 * `decision_reason` INDEPENDENTLY, and the low-confidence override is the
 * FIRST branch of the reason ladder. So a run can list `FLOOR_NO_MARKET` while
 * that floor decided nothing. The block this covers is keyed on
 * `decision_reason` for exactly that reason; the panel it replaces was keyed
 * on the floors and confidently narrated a cause that had not applied.
 */

function verdict(overrides: Partial<VerdictSummary> = {}): VerdictSummary {
  return {
    verdict: 'REJECT',
    confidence: 0.72,
    compositeScore: 3.1,
    confidenceBand: 'MODERATE',
    provisional: false,
    fatalFloors: [],
    decisionReason: null,
    dimensions: {
      demand: 2,
      market: 0,
      competitive_room: 3,
      feasibility: 3,
      headroom_over_free: 4,
    },
    source: 'frame',
    ...overrides,
  }
}

describe('what decided the run', () => {
  it('names the dimension and its score in plain language when a floor decided', () => {
    const block = describeDecision(
      verdict({
        verdict: 'REJECT',
        decisionReason: 'FLOOR_NO_MARKET',
        fatalFloors: ['FLOOR_NO_MARKET'],
      }),
    )

    expect(block).not.toBeNull()
    expect(block?.headline).toBe('Market scored 0 of 5.')
    expect(block?.meaning).toBe(
      'No buyer segment was named and no price was found. A market at 0 rejects the ' +
        'idea whatever the other scores say.',
    )
    // Red, because this idea is dead - not amber, which means "we could not
    // tell". Both are existing semantic tokens and the reader had to infer the
    // difference before.
    expect(block?.tone).toBe('floor')
    expect(block?.alsoBlocking).toEqual([])
    // Greppable from the DOM, never on screen.
    expect(block?.code).toBe('FLOOR_NO_MARKET')
    expect(block?.headline).not.toMatch(/FLOOR_/)
  })

  it('says low confidence decided it, and demotes the floor that did not', () => {
    // THE case. 34% confidence with `market == 0`: the floor is in the list,
    // and the low-confidence override pre-empted it. The old block asserted
    // the opposite in its loudest element.
    const block = describeDecision(
      verdict({
        verdict: 'NEEDS_WORK',
        confidence: 0.34,
        confidenceBand: 'LOW',
        compositeScore: 4.2,
        decisionReason: 'INSUFFICIENT_EVIDENCE',
        fatalFloors: ['FLOOR_NO_MARKET'],
      }),
    )

    expect(block?.headline).toBe('Too little evidence to judge.')
    expect(block?.meaning).toContain('Confidence came out at 34%')
    expect(block?.meaning).not.toContain('{confidence}')
    // Amber: we could not tell, rather than the idea is dead.
    expect(block?.tone).toBe('evidence')

    expect(block?.alsoBlocking).toHaveLength(1)
    expect(block?.alsoBlocking[0].code).toBe('FLOOR_NO_MARKET')
    // The tense is the whole point: it did NOT reject anything on this run.
    expect(block?.alsoBlocking[0].text).toBe(
      'Market scored 0 of 5 — no buyer segment was named and no price was found. ' +
        'On stronger evidence that alone would reject the idea.',
    )
  })

  it('drops the number rather than printing NaN% when confidence is missing', () => {
    const block = describeDecision(
      verdict({ confidence: null, decisionReason: 'INSUFFICIENT_EVIDENCE' }),
    )

    expect(block?.meaning).toContain('under the bar')
    expect(block?.meaning).not.toContain('NaN')
    expect(block?.meaning).not.toContain('{confidence}')
  })

  it('carries two floors as one headline and one demoted line, never two blocks', () => {
    const block = describeDecision(
      verdict({
        confidence: 0.72,
        decisionReason: 'FLOOR_NO_DEMAND',
        fatalFloors: ['FLOOR_NO_DEMAND', 'FLOOR_ALREADY_FREE'],
        dimensions: {
          demand: 0,
          market: 3,
          competitive_room: 2,
          feasibility: 4,
          headroom_over_free: 0,
        },
      }),
    )

    expect(block?.headline).toBe('Demand scored 0 of 5.')
    expect(block?.alsoBlocking).toHaveLength(1)
    // A floor DID decide here, so the also-ran corroborates it flatly - there
    // is no "on stronger evidence" to wait for.
    expect(block?.alsoBlocking[0].text).toBe(
      'Headroom over free scored 0 of 5 — a free substitute already covers the core job. ' +
        'That alone would also reject the idea.',
    )
    expect(block?.blockedDimensions).toEqual(['demand', 'headroom_over_free'])
  })

  it('renders no block at all when the arithmetic decided', () => {
    // No floor, no reason: the composite is the whole answer and the score row
    // already shows it. A red box here would say "nothing unusual happened".
    expect(describeDecision(verdict())).toBeNull()
    expect(describeDecision(null)).toBeNull()
  })

  it('falls back to the floor list when the server sent floors but no reason', () => {
    const block = describeDecision(verdict({ fatalFloors: ['FLOOR_NO_MARKET'] }))

    expect(block?.code).toBe('FLOOR_NO_MARKET')
    expect(block?.headline).toBe('Market scored 0 of 5.')
  })

  it('uses the stored sentence when no scorecard came with the verdict', () => {
    // A gate-sourced summary carries the headline and no dimensions; a
    // composed "scored 0 of 5" would be inventing a number nobody scored.
    const block = describeDecision(
      verdict({ dimensions: null, decisionReason: 'FLOOR_ALREADY_FREE' }),
    )

    expect(block?.headline).toBe('Something free already does the whole job.')
  })

  it('keeps the retired floor, because rows already written still parse', () => {
    // RATIFICATION C4 retired `FLOOR_NOT_BUILDABLE` and left it in `FloorCode`
    // so older runs still load. The client keeps it for exactly as long.
    expect(DECISIONS.FLOOR_NOT_BUILDABLE.meaning).toContain('withdrawn')
    const block = describeDecision(
      verdict({ decisionReason: 'FLOOR_NOT_BUILDABLE', dimensions: { feasibility: 0 } }),
    )
    expect(block?.headline).toBe('Feasibility scored 0 of 5.')
  })
})

describe('the humaniser fallback (T1.4)', () => {
  it('renders an unknown floor code as words, never as SNAKE_CASE', () => {
    const block = describeDecision(
      verdict({
        decisionReason: 'FLOOR_NO_RUNWAY',
        fatalFloors: ['FLOOR_NO_RUNWAY'],
      }),
    )

    expect(block?.headline).toBe('No runway.')
    expect(block?.headline).not.toMatch(/_/)
    // No invented explanation for a rule this file has never seen.
    expect(block?.meaning).toBeNull()
  })

  it('renders an unknown demoted floor as words too, tense intact', () => {
    const block = describeDecision(
      verdict({
        decisionReason: 'INSUFFICIENT_EVIDENCE',
        confidence: 0.2,
        fatalFloors: ['FLOOR_NO_RUNWAY'],
      }),
    )

    expect(block?.alsoBlocking[0].text).toBe(
      'No runway. On stronger evidence that alone would reject the idea.',
    )
    expect(block?.alsoBlocking[0].text).not.toMatch(/[A-Z]{2,}_/)
  })

  it('renders an unknown dimension key as words and offers no question', () => {
    expect(dimensionName('regulatory_risk')).toBe('Regulatory risk')
    expect(dimensionQuestion('regulatory_risk')).toBeNull()
    // A made-up question would be worse than none.
    expect(dimensionName('Z')).toBe('Z')
  })

  it('renders an unknown band and an unknown verdict as words', () => {
    expect(confidenceWord('VERY_HIGH')).toBe('Very high')
    expect(confidenceChip('VERY_HIGH', 0.91)?.label).toBe('Very high confidence · 91%')
    // Neutral, because an unrecognised band is unrecognised - painting it
    // amber would assert a doubt nobody measured.
    expect(confidenceChip('VERY_HIGH', 0.91)?.tone).toBe('moderate')
    expect(verdictLabel('PARTIALLY_VALIDATED')).toBe('Partially validated')
  })
})

describe('the chips', () => {
  it('states the verdict in words, so the shout can be typography', () => {
    expect(verdictLabel('NEEDS_WORK')).toBe('Needs work')
    expect(verdictLabel('VALIDATE')).toBe('Validate')
    expect(verdictLabel('REJECT')).toBe('Reject')
    expect(verdictLabel(null)).toBe('')
  })

  it('carries the band word and the number in one chip', () => {
    expect(confidenceChip('LOW', 0.34)).toEqual({ label: 'Low confidence · 34%', tone: 'low' })
    expect(confidenceChip('HIGH', 0.82)).toEqual({ label: 'High confidence · 82%', tone: 'high' })
    // `MODERATE`, not `MEDIUM` - but a flow spelling it the other way still
    // reads correctly rather than falling through to the humaniser.
    expect(confidenceChip('MEDIUM', 0.61)?.label).toBe('Moderate confidence · 61%')
    // Either half alone is still a chip; neither half is no chip.
    expect(confidenceChip(null, 0.62)?.label).toBe('Confidence 62%')
    expect(confidenceChip('LOW', null)?.label).toBe('Low confidence')
    expect(confidenceChip(null, null)).toBeNull()
  })

  it('names thin dimensions in words, from either carrier', () => {
    // `thin_dimensions` sends letters; `dimensions` sends field names; the
    // panel renders both in one sentence and must not need two lookups.
    expect(thinEvidencePhrase(['D'])).toBe('Demand')
    expect(thinEvidencePhrase(['D', 'C', 'F', 'X'])).toBe(
      'Demand, Competitive room, Feasibility and Headroom over free',
    )
    expect(thinEvidencePhrase(['demand', 'competitive_room'])).toBe('Demand and Competitive room')
    // Naming all five is longer and says less than the summary.
    expect(thinEvidencePhrase(['D', 'M', 'C', 'F', 'X'])).toBe('all five dimensions')
    expect(thinEvidencePhrase([])).toBe('')
    // An unknown letter still reads as words.
    expect(thinEvidencePhrase(['Q_RATIO'])).toBe('Q ratio')
  })

  it('resolves the report letters to canonical keys, de-duplicated', () => {
    const report: RunResult = { thin_dimensions: ['D', 'demand', 'X'] }
    expect(thinDimensionKeys(report)).toEqual(['demand', 'headroom_over_free'])
    expect(thinDimensionKeys(null)).toEqual([])
  })

  it('passes thin dimensions through onto the block', () => {
    const block = describeDecision(
      verdict({ decisionReason: 'FLOOR_NO_MARKET', fatalFloors: ['FLOOR_NO_MARKET'] }),
      { thin_dimensions: ['M', 'F'] },
    )
    expect(block?.thinDimensions).toEqual(['market', 'feasibility'])
  })

  it('keys every dimension by BOTH its letter and its field name', () => {
    // The two carriers disagree by design, and a lookup that knew only one of
    // them would render half the panel as a code.
    for (const [code, key] of [
      ['D', 'demand'],
      ['M', 'market'],
      ['C', 'competitive_room'],
      ['F', 'feasibility'],
      ['X', 'headroom_over_free'],
    ] as const) {
      expect(DIMENSIONS[code]).toBe(DIMENSIONS[key])
      expect(DIMENSIONS[code].question.length).toBeGreaterThan(0)
    }
  })
})

describe('a derived value, as the gate card renders it', () => {
  it('turns the literals a gate serialises into English', () => {
    expect(describeValue('null')).toBe('—')
    expect(describeValue('[]')).toBe('none')
    expect(describeValue('false')).toBe('no')
    expect(describeValue('true')).toBe('yes')
    expect(describeValue('NEEDS_WORK')).toBe('Needs work')
    expect(describeValue('HIGH')).toBe('High')
    expect(describeValue('FLOOR_NO_MARKET')).toBe('No market found.')
  })

  it('handles real JSON values, not only their string spellings', () => {
    expect(describeValue(null)).toBe('—')
    expect(describeValue([])).toBe('none')
    expect(describeValue(true)).toBe('yes')
    expect(describeValue(3)).toBe('3')
    expect(describeValue(['a', 'b'])).toBe('a, b')
  })

  it('leaves prose alone', () => {
    // This must never lower-case a sentence somebody wrote.
    const sentence = 'Offer a paid pilot to three teams already paying for a codegen tool.'
    expect(describeValue(sentence)).toBe(sentence)
  })

  it('humanises an enum it has never seen rather than showing the token', () => {
    expect(describeValue('RATE_LIMITED')).toBe('Rate limited')
    expect(describeValue('SOLVES_ENTIRELY')).toBe('Solves entirely')
  })
})
