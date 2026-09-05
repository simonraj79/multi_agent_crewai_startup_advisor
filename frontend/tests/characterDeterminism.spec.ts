import { createHash } from 'node:crypto'

import { describe, expect, it } from 'vitest'

import fixture from './fixtures/characterSnapshots.json'
import {
  BODY_NAMES,
  CREST_NAMES,
  EYE_NAMES,
  MOUTH_NAMES,
  identityFor,
  pipParts,
  pipSvg,
} from '../src/characters/pip'

/**
 * G3, the determinism half.
 *
 * `tests/fixtures/characterSnapshots.json` was written by
 * `scripts/character-snapshots.mjs` - plain Node, importing `src/characters/pip.ts`
 * directly, no Vite, no Vue, no jsdom. This file re-derives the same hashes
 * inside Vitest, under jsdom, through Vite's transform. Two processes, two
 * toolchains, one set of bytes. A `toMatchSnapshot()` written and read by one
 * runner would prove that the runner agrees with itself, which is not the
 * claim being made.
 *
 * The claim being made is that an agent's character is a property of its NAME
 * and of nothing else - not of the session, not of the graph's layout, not of
 * the order frames arrived in, not of which machine rendered it. That is what
 * lets a character survive a reload, agree between the node and the trace, and
 * be screenshotted as evidence at all.
 *
 * IF THIS FAILS, A CHARACTER CHANGED. It is not a stale fixture until somebody
 * has checked which one and why: every screenshot of that agent, every reload,
 * and the medallion beside it moved with it. Regenerate on purpose, in a
 * commit that says so.
 */

function sha256(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex')
}

function markupFor(role: string): string {
  const identity = identityFor(role, role ? '' : fixture.fallbackNodeId)
  return pipSvg(identity.key, { size: 32, state: 'idle' })
}

const ROLES = Object.keys(fixture.snapshots)
const SNAPSHOTS = fixture.snapshots as Record<string, string>
const DIAGNOSTICS = fixture.diagnostics as Record<
  string,
  { seed: string; named: boolean; parts: string; bytes: number }
>

describe('the fixture itself', () => {
  it('records the command that regenerates it', () => {
    expect(fixture.command).toBe('cd frontend && node scripts/character-snapshots.mjs')
    expect(fixture.generatedBy).toContain('scripts/character-snapshots.mjs')
    expect(fixture.assertedBy).toContain('characterDeterminism.spec.ts')
    expect(fixture.hashOf).toContain('pipSvg')
  })

  it('covers twenty roles, including the awkward ones', () => {
    expect(ROLES).toHaveLength(20)
    expect(ROLES).toContain('')
    expect(ROLES.some((role) => /\s{2,}/.test(role))).toBe(true)
    expect(ROLES.some((role) => role === role.toUpperCase() && role.trim().length > 0)).toBe(true)
    expect(ROLES.some((role) => role.includes('-'))).toBe(true)
    expect(ROLES.some((role) => role.normalize('NFKD') !== role)).toBe(true)
  })

  it('carries a sha256 for every role and a diagnostic beside it', () => {
    for (const role of ROLES) {
      expect(SNAPSHOTS[role], role).toMatch(/^[0-9a-f]{64}$/)
      expect(DIAGNOSTICS[role], role).toBeDefined()
    }
  })
})

describe('the markup is byte-identical across processes', () => {
  it.each(ROLES)('reproduces the recorded hash for %j', (role) => {
    const markup = markupFor(role)
    const actual = sha256(markup)
    if (actual !== SNAPSHOTS[role]) {
      /* A bare hash mismatch says nothing useful, and this failure is the one
         most likely to be met by a reader who did not write the generator. */
      const parts = pipParts(identityFor(role, role ? '' : fixture.fallbackNodeId).key)
      throw new Error(
        `the character for ${JSON.stringify(role)} changed.\n` +
          `  recorded: ${SNAPSHOTS[role]}  ${DIAGNOSTICS[role].parts}  ${DIAGNOSTICS[role].bytes} bytes\n` +
          `  now:      ${actual}  ` +
          `${BODY_NAMES[parts.body]}/${EYE_NAMES[parts.eyes]}/${MOUTH_NAMES[parts.mouth]}/` +
          `${CREST_NAMES[parts.crest]}/c${parts.colour}  ${markup.length} bytes\n` +
          `  If that was intended, re-run: ${fixture.command}`,
      )
    }
    expect(actual).toBe(SNAPSHOTS[role])
  })

  it('reproduces the recorded seed and parts, so a failure names what moved', () => {
    for (const role of ROLES) {
      const identity = identityFor(role, role ? '' : fixture.fallbackNodeId)
      const parts = pipParts(identity.key)
      expect(identity.key, role).toBe(DIAGNOSTICS[role].seed)
      expect(identity.named, role).toBe(DIAGNOSTICS[role].named)
      expect(
        `${BODY_NAMES[parts.body]}/${EYE_NAMES[parts.eyes]}/${MOUTH_NAMES[parts.mouth]}/${CREST_NAMES[parts.crest]}/c${parts.colour}`,
        role,
      ).toBe(DIAGNOSTICS[role].parts)
    }
  })

  it('is stable when the same role is asked for twice in a row', () => {
    for (const role of ROLES) expect(markupFor(role)).toBe(markupFor(role))
  })
})

describe('what the recorded hashes prove about the normaliser', () => {
  it('gives three spellings of one name one character', () => {
    const spellings = ['Market Analyst', '  MARKET   ANALYST ', 'market-analyst']
    const hashes = new Set(spellings.map((spelling) => SNAPSHOTS[spelling]))
    expect(hashes.size).toBe(1)
  })

  it('gives an accented name and its plain spelling one character', () => {
    expect(SNAPSHOTS['Résumé Writer']).toBe(SNAPSHOTS['Resume Writer'])
  })

  it('keeps a one-letter edit and an added word apart', () => {
    expect(SNAPSHOTS['Sentiment Analysts']).not.toBe(SNAPSHOTS['Sentiment Analyst'])
    expect(SNAPSHOTS['Senior Analyst']).not.toBe(SNAPSHOTS.Analyst)
  })

  it('gives the nameless agent a character of its own, from its node id', () => {
    expect(DIAGNOSTICS[''].named).toBe(false)
    expect(DIAGNOSTICS[''].seed).toBe('n7 second pass')
    expect(new Set(Object.values(SNAPSHOTS)).has(SNAPSHOTS[''])).toBe(true)
    expect(DIAGNOSTICS[''].parts).toMatch(/^[a-z]+\/[a-z]+\/[a-z-]+\/[a-z]+\/c\d{1,2}$/)
  })

  it('draws seventeen distinct characters from twenty roles, and says why not twenty', () => {
    /* Not "all twenty differ", and the arithmetic is the assertion: three of
       the twenty are three spellings of ONE agent (-2) and two more are one
       accented pair (-1), so seventeen names remain. A round number here
       would pass for the wrong reason the first time the normaliser moved. */
    const distinctSeeds = new Set(Object.values(DIAGNOSTICS).map((one) => one.seed))
    expect(ROLES.length - distinctSeeds.size).toBe(3)
    expect(distinctSeeds.size).toBe(17)
    /* And seventeen names give seventeen pictures: no two DIFFERENT agents in
       this set collided on all five axes. */
    expect(new Set(Object.values(SNAPSHOTS)).size).toBe(17)
  })
})
