/**
 * Enum -> English, for the run's conclusion.
 *
 * The data layer is untouched and stays that way: `schemas/validator.py` goes
 * on emitting `FLOOR_NO_MARKET`, `NEEDS_WORK`, `MODERATE` and the letters
 * `D`/`M`/`C`/`F`/`X`, and every one of them is turned into words HERE and
 * nowhere else. Nothing in this file decides anything - it renames.
 *
 * ## The finding this file is shaped by
 *
 * `Verdict.compute_mechanical_result` (`src/brief_crew/schemas/validator.py`,
 * around :538-566) computes `fatal_floors` and `decision_reason`
 * INDEPENDENTLY. The floors are collected first, unconditionally; then a
 * separate ladder picks the reason, and its FIRST branch is
 * `confidence < 0.35 -> NEEDS_WORK / INSUFFICIENT_EVIDENCE`. So a run at 34%
 * confidence with `market == 0` carries `FLOOR_NO_MARKET` in `fatal_floors`
 * while that floor decided precisely nothing: the low-confidence override
 * pre-empted it.
 *
 * The panel that used to render this was keyed on `fatal_floors` and asserted,
 * in its loudest block, that the floor "not the arithmetic, is why this run
 * reads NEEDS_WORK". On that screen it was false twice over. So the block is
 * keyed on `decision_reason` - the one field that answers "why this verdict" -
 * and floors that did not decide are demoted to also-rans. Everything below
 * follows from that inversion.
 *
 * ## Why a table, and why a table with a transform under it
 *
 * A transform can only ever turn `FLOOR_NO_MARKET` into "No market", and "No
 * market" is not what an operator needs; what they need is which dimension
 * scored what, and what that means for their idea. No string manipulation
 * recovers that from a token.
 *
 * But a table alone renders a code added to `config.py` tomorrow as nothing at
 * all - which is exactly why `ReportPanel.vue` reached for a transform in the
 * first place. `humaniseCode` is the floor under every lookup here: an unknown
 * code degrades to sentence-case English, never to SNAKE_CASE, and it degrades
 * WITHOUT a meaning sentence, because inventing an explanation for a rule this
 * file has never seen is worse than omitting one.
 *
 * ## What is deliberately NOT here
 *
 * The confidence cut-offs (0.35 / 0.70) and the five dimension weights. Both
 * are `compute_mechanical_result`'s arithmetic, and restating them would make
 * this a third mirror of server truth with no generated fixture behind it -
 * the exact shape of the defect recorded in CLAUDE.md section 14 (a client
 * mirror that agreed with itself at the wrong number). The wording says "under
 * the bar" and shows the measured percentage instead, which is checkable on
 * the page.
 */

import type { RunResult, VerdictDimensionScores, VerdictSummary } from '../types/studio'
import { humaniseCode } from '../utils/humanise'

/** Every ladder in this rubric is 0-5. Stated once. */
export const DIMENSION_MAX = 5

/* ------------------------------------------------------------------------ */
/* Dimensions                                                                */
/* ------------------------------------------------------------------------ */

export interface DimensionDisplay {
  /** The rubric letter, as `ValidationReport.thin_dimensions` carries it. */
  readonly code: string
  /** The `Verdict.dimensions` field name. */
  readonly key: string
  /**
   * The name the markdown report body uses
   * (`validator_flow.py::_DIMENSION_LABELS`). Kept verbatim, jargon included:
   * the body rendered a few pixels below this panel says "Headroom over free"
   * in its own scores table, and a console that renames a dimension its own
   * report does not teaches the reader that one of the two is lying.
   */
  readonly name: string
  /**
   * The ladder's own question, verbatim from
   * `crews/validator_crew/config/tasks.yaml`. This is the only place in the
   * console where the five ladders are explained at all, and it is what makes
   * "Headroom over free" mean anything to a first-time reader.
   */
  readonly question: string
}

const DIMENSION_LIST: readonly DimensionDisplay[] = [
  {
    code: 'D',
    key: 'demand',
    name: 'Demand',
    question: 'Is anyone actively trying to solve this today?',
  },
  {
    code: 'M',
    key: 'market',
    name: 'Market',
    question: 'Is there money, and can you name whose?',
  },
  {
    code: 'C',
    key: 'competitive_room',
    name: 'Competitive room',
    question: 'Is the incumbent set beatable on a stated axis?',
  },
  {
    code: 'F',
    key: 'feasibility',
    name: 'Feasibility',
    question: 'Can two or three engineers ship a v1?',
  },
  {
    code: 'X',
    key: 'headroom_over_free',
    name: 'Headroom over free',
    question: 'Is the core already free and good?',
  },
]

/**
 * Keyed by BOTH carriers, on purpose and not by accident.
 *
 * `ValidationReport.thin_dimensions` sends the letters; `Verdict.dimensions`
 * sends the field names; this panel renders both in the same sentence and must
 * not need to know which one it is holding. Built from one list so a letter
 * and a name can never disagree about which dimension they are.
 */
export const DIMENSIONS: Readonly<Record<string, DimensionDisplay>> =
  Object.freeze(
    Object.fromEntries(
      DIMENSION_LIST.flatMap((entry) => [
        [entry.code, entry] as const,
        [entry.key, entry] as const,
      ]),
    ),
  )

/** The five field names, in rubric order. */
export const DIMENSION_KEYS: readonly string[] = DIMENSION_LIST.map((d) => d.key)

/**
 * `D` or `demand` -> the canonical field name; anything unrecognised is
 * returned unchanged, so a sixth dimension keeps a stable identity through
 * every lookup below rather than collapsing into one bucket.
 */
export function dimensionKey(keyOrCode: string): string {
  return DIMENSIONS[keyOrCode]?.key ?? keyOrCode
}

/** `D` or `demand` -> `Demand`; anything else -> humanised words. */
export function dimensionName(keyOrCode: string): string {
  const known = DIMENSIONS[keyOrCode]
  if (known) return known.name
  return humaniseCode(keyOrCode) || keyOrCode
}

/**
 * `D` or `demand` -> the ladder's question; `null` for a dimension this file
 * has never heard of, because a made-up question is worse than none.
 */
export function dimensionQuestion(keyOrCode: string): string | null {
  return DIMENSIONS[keyOrCode]?.question ?? null
}

/* ------------------------------------------------------------------------ */
/* Verdict label - `schemas/validator.py::VerdictLabel`                      */
/* ------------------------------------------------------------------------ */

/**
 * Sentence case in the data layer; the badge shouts through
 * `text-transform: uppercase` in CSS.
 *
 * The underscore is the enum tell, not the capitals - so deleting the
 * underscore and keeping the weight is the honest minimum, and it keeps a
 * verdict on screen matchable against the same verdict in a log. It also means
 * an unknown label from a newer server can never reach the screen looking like
 * a variable name.
 */
export const VERDICT_LABELS: Readonly<Record<string, string>> = {
  VALIDATE: 'Validate',
  NEEDS_WORK: 'Needs work',
  REJECT: 'Reject',
}

/** `NEEDS_WORK` -> `Needs work`; unknown -> humanised words. */
export function verdictLabel(verdict: string | null | undefined): string {
  if (typeof verdict !== 'string' || !verdict.trim()) return ''
  const known = VERDICT_LABELS[verdict.trim().toUpperCase()]
  return known ?? humaniseCode(verdict)
}

/** Which of the badge's three tints. */
export function verdictTone(verdict: string | null | undefined): 'pass' | 'warn' | 'fail' {
  const label = (verdict ?? '').toUpperCase()
  if (label.includes('VALIDATE')) return 'pass'
  if (label.includes('REJECT')) return 'fail'
  return 'warn'
}

/* ------------------------------------------------------------------------ */
/* Confidence band - `schemas/validator.py::ConfidenceBand`                  */
/* ------------------------------------------------------------------------ */

/**
 * The band supplies the word, the percentage supplies the precision, and the
 * two belong in ONE chip: `34% confidence` beside a separate shouted `LOW` was
 * two elements carrying one fact, and `LOW` on its own is ambiguous ("low
 * what?").
 *
 * `MEDIUM` is not a `ConfidenceBand` today - the enum is HIGH | MODERATE | LOW
 * - and is mapped anyway so a flow that spells it that way reads correctly
 * instead of falling through to the humaniser.
 */
export const CONFIDENCE_BANDS: Readonly<Record<string, string>> = {
  HIGH: 'High',
  MODERATE: 'Moderate',
  MEDIUM: 'Moderate',
  LOW: 'Low',
}

export type ConfidenceTone = 'high' | 'moderate' | 'low'

const CONFIDENCE_TONES: Readonly<Record<string, ConfidenceTone>> = {
  HIGH: 'high',
  MODERATE: 'moderate',
  MEDIUM: 'moderate',
  LOW: 'low',
}

/** `LOW` -> `Low`; unknown -> humanised words. */
export function confidenceWord(band: string | null | undefined): string {
  if (typeof band !== 'string' || !band.trim()) return ''
  const key = band.trim().toUpperCase()
  return CONFIDENCE_BANDS[key] ?? humaniseCode(band)
}

export interface ChipDisplay {
  label: string
  tone: ConfidenceTone
}

/**
 * `Low confidence · 34%`, or just one half of it when the other is missing.
 *
 * Returns `null` when neither half is available, so the caller renders no chip
 * rather than an empty one. `moderate` is the neutral fallback tone: an
 * unrecognised band is unrecognised, and painting it amber would assert a
 * doubt nobody measured.
 */
export function confidenceChip(
  band: string | null | undefined,
  confidence: number | null | undefined,
): ChipDisplay | null {
  const word = confidenceWord(band)
  const percent = formatPercent(confidence)
  if (!word && percent === null) return null
  const tone = CONFIDENCE_TONES[(band ?? '').toUpperCase()] ?? 'moderate'
  if (!word) return { label: `Confidence ${percent}`, tone }
  if (percent === null) return { label: `${word} confidence`, tone }
  return { label: `${word} confidence · ${percent}`, tone }
}

/** `0.34` -> `34%`. `null` for anything that is not a finite number. */
export function formatPercent(value: number | null | undefined): string | null {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${Math.round(value * 100)}%`
    : null
}

/* ------------------------------------------------------------------------ */
/* Thin evidence - `ValidationReport.thin_dimensions`                        */
/* ------------------------------------------------------------------------ */

/** The report's letters, resolved to canonical field names and de-duplicated. */
export function thinDimensionKeys(report: RunResult | null | undefined): string[] {
  const raw = report?.thin_dimensions ?? []
  const seen = new Set<string>()
  for (const entry of raw) {
    if (typeof entry !== 'string' || !entry.trim()) continue
    seen.add(dimensionKey(entry.trim()))
  }
  return [...seen]
}

/**
 * `['D','C','F','X']` -> `Demand, Competitive room, Feasibility and Headroom
 * over free`.
 *
 * All five collapse to `all five dimensions`, which is the common shape on a
 * bad run: naming every one of them is longer and says less than the summary.
 */
export function thinEvidencePhrase(codes: readonly string[]): string {
  const names = [...new Set(codes.map((code) => dimensionKey(code)))].map(dimensionName)
  if (names.length === 0) return ''
  if (names.length >= DIMENSION_LIST.length && names.every((name) =>
    DIMENSION_LIST.some((d) => d.name === name),
  )) {
    return 'all five dimensions'
  }
  if (names.length === 1) return names[0]
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/* ------------------------------------------------------------------------ */
/* What decided the run                                                      */
/* ------------------------------------------------------------------------ */

/**
 * `DecisionReason` is a superset of `FloorCode`: the four floors plus
 * `INSUFFICIENT_EVIDENCE` (`schemas/validator.py`). One table therefore serves
 * both `decision_reason` and every entry of `fatal_floors`.
 */
interface DecisionCopy {
  /**
   * The `Verdict.dimensions` field whose score tripped this, when one did.
   * Present means the headline is COMPOSED - "Market scored 0 of 5." - so a
   * rule that later fires at 1 instead of 0 renders correctly with no edit
   * here.
   */
  readonly dimension?: string
  /** Used when no score is available for `dimension`. Stands alone. */
  readonly headline: string
  /**
   * One meaning sentence, at most two short ones. `{confidence}` is the only
   * interpolation and appears only where the percentage IS the substance.
   */
  readonly meaning: string
  /** Used when `meaning` needs a percentage and none was reported. */
  readonly meaningWithoutConfidence?: string
  /**
   * The lower-case clause used when this code is an also-ran rather than the
   * decider: "{Dimension} scored 0 of 5 - {clause}. ..."
   */
  readonly clause: string
}

export const DECISIONS: Readonly<Record<string, DecisionCopy>> = {
  INSUFFICIENT_EVIDENCE: {
    headline: 'Too little evidence to judge.',
    meaning:
      'Confidence came out at {confidence}, under the bar this system needs before it ' +
      'will call anything final. The five scores below stand, but the answer does not.',
    meaningWithoutConfidence:
      'Confidence came out under the bar this system needs before it will call anything ' +
      'final. The five scores below stand, but the answer does not.',
    clause: 'there was too little evidence to judge',
  },
  FLOOR_NO_DEMAND: {
    dimension: 'demand',
    headline: 'No demand found.',
    meaning:
      'Nobody in the evidence describes having this problem. A zero on Demand rejects ' +
      'the idea whatever the other scores say.',
    clause: 'nobody in the evidence describes having this problem',
  },
  FLOOR_NO_MARKET: {
    dimension: 'market',
    headline: 'No market found.',
    meaning:
      'No buyer segment was named and no price was found. A market at 0 rejects the ' +
      'idea whatever the other scores say.',
    clause: 'no buyer segment was named and no price was found',
  },
  FLOOR_ALREADY_FREE: {
    dimension: 'headroom_over_free',
    headline: 'Something free already does the whole job.',
    meaning:
      'A free substitute already covers the core job and is usable commercially. A zero ' +
      'here rejects the idea whatever the other scores say.',
    clause: 'a free substitute already covers the core job',
  },
  // Retired 2026-09-01 (RATIFICATION C4) and kept in `FloorCode` so rows
  // already written still parse - so it is kept here for exactly as long, and
  // says so rather than pretending to be a live rule.
  FLOOR_NOT_BUILDABLE: {
    dimension: 'feasibility',
    headline: 'Nothing reusable to build on.',
    meaning:
      'Nothing in the evidence is reusable enough to build a first version on. This rule ' +
      'has since been withdrawn, so only older runs show it.',
    clause: 'nothing in the evidence is reusable enough to build on',
  },
}

/** One floor that fired without deciding anything. */
export interface AlsoBlocking {
  /** The raw code, for `data-code` and a `title` - greppable, never on screen. */
  readonly code: string
  readonly text: string
}

/**
 * The block the panel renders under "WHAT DECIDED THIS RUN".
 *
 * `null` from `describeDecision` means the block does not render at all: the
 * arithmetic decided, and the score row already says so.
 */
export interface DecisionBlock {
  /** The raw deciding code, for `data-code`. Never rendered as text. */
  readonly code: string
  /**
   * `floor` when a zero decided it (`--err-*`, this idea is dead);
   * `evidence` when low confidence did (`--warn-*`, we could not tell). The
   * reader currently has to infer that difference; the tint states it.
   */
  readonly tone: 'floor' | 'evidence'
  /** Line 1. `Market scored 0 of 5.` or `Too little evidence to judge.` */
  readonly headline: string
  /** Line 2. `null` renders nothing - never a placeholder, never a guess. */
  readonly meaning: string | null
  /** Every floor that fired and did not decide, in the server's own order. */
  readonly alsoBlocking: readonly AlsoBlocking[]
  /** Canonical keys of every dimension the decision or a floor rests on. */
  readonly blockedDimensions: readonly string[]
  /** Canonical keys the report flagged as thin, for the caller's convenience. */
  readonly thinDimensions: readonly string[]
}

function scoreOf(
  dimensions: VerdictDimensionScores | null | undefined,
  key: string | undefined,
): number | null {
  if (!key || !dimensions) return null
  const value = dimensions[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** `No market found.` -> `No market found` - so a clause can be appended. */
function withoutFullStop(text: string): string {
  return text.replace(/\.\s*$/, '')
}

/**
 * The composed headline for one code: a dimension and its score in plain
 * words whenever the score is on the wire, and the stored sentence when it is
 * not (a gate-sourced verdict carries the headline and no scorecard).
 */
function headlineFor(
  code: string,
  copy: DecisionCopy | undefined,
  dimensions: VerdictDimensionScores | null | undefined,
): string {
  const score = scoreOf(dimensions, copy?.dimension)
  if (copy && copy.dimension && score !== null) {
    return `${dimensionName(copy.dimension)} scored ${score} of ${DIMENSION_MAX}.`
  }
  if (copy) return copy.headline
  // Unknown code: words, never SNAKE_CASE, and no invented explanation.
  const words = humaniseCode(code, { stripPrefix: 'FLOOR_' })
  return words ? `${words}.` : ''
}

/**
 * One "ALSO BLOCKING" line.
 *
 * The tense is the point. When low confidence pre-empted the floors, a floor
 * did NOT reject anything and the sentence has to say "would" - that is the
 * case the old block could not express at all, and the case it got wrong.
 * When a floor did decide, the remaining floors corroborate it in the flat
 * present.
 */
function alsoBlockingText(
  code: string,
  dimensions: VerdictDimensionScores | null | undefined,
  decidedByFloor: boolean,
): string {
  const copy = DECISIONS[code]
  const tail = decidedByFloor
    ? 'That alone would also reject the idea.'
    : 'On stronger evidence that alone would reject the idea.'
  const head = withoutFullStop(headlineFor(code, copy, dimensions))
  if (!head) return tail
  if (copy?.clause) return `${head} — ${copy.clause}. ${tail}`
  return `${head}. ${tail}`
}

/**
 * The whole block, or `null` when there is nothing to override the arithmetic.
 *
 * Keyed on `decision_reason` first and `fatal_floors[0]` only as a fallback,
 * because those two fields are computed independently and only the first one
 * answers "why this verdict". A floor in the list that is not the decider is
 * an also-ran, and saying so is the correction this whole file exists for.
 *
 * `report` supplies `thin_dimensions`, which travels on a different carrier
 * from the scores and is passed through onto the block so a caller can read
 * the run's conclusion from one call.
 */
export function describeDecision(
  verdict: VerdictSummary | null | undefined,
  report?: RunResult | null,
): DecisionBlock | null {
  const thinDimensions = thinDimensionKeys(report)
  if (!verdict) return null

  const floors = (verdict.fatalFloors ?? []).filter(
    (code): code is string => typeof code === 'string' && code.trim().length > 0,
  )
  const reason =
    typeof verdict.decisionReason === 'string' && verdict.decisionReason.trim()
      ? verdict.decisionReason.trim()
      : null

  const decided = reason ?? floors[0] ?? null
  // Nothing overrode the arithmetic: the composite decided, and the score row
  // below already shows it. A block here would be a red box saying "nothing
  // unusual happened".
  if (!decided) return null

  const copy = DECISIONS[decided]
  const dimensions = verdict.dimensions
  const decidedByFloor = copy ? copy.dimension !== undefined : floors.includes(decided)

  const meaningTemplate = copy?.meaning ?? null
  const percent = formatPercent(verdict.confidence)
  let meaning: string | null = meaningTemplate
  if (meaningTemplate && meaningTemplate.includes('{confidence}')) {
    meaning =
      percent === null
        ? copy?.meaningWithoutConfidence ?? null
        : meaningTemplate.replaceAll('{confidence}', percent)
  }

  const alsoBlocking = floors
    .filter((code) => code !== decided)
    .map((code) => ({ code, text: alsoBlockingText(code, dimensions, decidedByFloor) }))

  const blocked = new Set<string>()
  if (copy?.dimension) blocked.add(copy.dimension)
  for (const code of floors) {
    const floorDimension = DECISIONS[code]?.dimension
    if (floorDimension) blocked.add(floorDimension)
  }

  return {
    code: decided,
    tone: decidedByFloor ? 'floor' : 'evidence',
    headline: headlineFor(decided, copy, dimensions),
    meaning,
    alsoBlocking,
    blockedDimensions: [...blocked],
    thinDimensions,
  }
}

/* ------------------------------------------------------------------------ */
/* Free-text values that arrive as codes (the gate card's `derived` payload)  */
/* ------------------------------------------------------------------------ */

/** An identifier-shaped string: `NEEDS_WORK`, `FLOOR_NO_MARKET`, `HIGH`. */
const ENUM_SHAPED = /^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+$/

/**
 * One derived value, rendered as words.
 *
 * The verdict gate dumps its whole read-only payload at an operator at the
 * moment they approve or reject a decision, and it used to arrive as raw JSON:
 * `NEEDS_WORK`, `HIGH`, the literal strings `"null"`, `"false"` and `"[]"`.
 * Every one of those has an English answer and none of them needed a new
 * concept to produce it.
 *
 * A value that is already prose comes back untouched - this must never
 * lower-case a sentence somebody wrote.
 */
export function describeValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '—'
  if (Array.isArray(value)) return value.length === 0 ? 'none' : value.map(describeValue).join(', ')
  if (typeof value !== 'string') return String(value)

  const raw = value.trim()
  if (!raw) return '—'
  // The gate serialises everything to a string, so these arrive spelled out.
  const lower = raw.toLowerCase()
  if (lower === 'null' || lower === 'none') return '—'
  if (lower === 'true') return 'yes'
  if (lower === 'false') return 'no'
  if (raw === '[]' || raw === '{}') return 'none'

  const upper = raw.toUpperCase()
  if (VERDICT_LABELS[upper]) return VERDICT_LABELS[upper]
  if (CONFIDENCE_BANDS[upper]) return CONFIDENCE_BANDS[upper]
  if (DECISIONS[upper]) return DECISIONS[upper].headline
  // Length-guarded: a bare `D` is far more likely to be somebody's data than
  // the Demand ladder, and guessing wrong there invents a fact.
  if (raw.length > 1 && DIMENSIONS[raw]) return DIMENSIONS[raw].name
  if (ENUM_SHAPED.test(raw)) return humaniseCode(raw, { stripPrefix: 'FLOOR_' })
  return raw
}
