/* ---------------------------------------------------------------------------
 * character-snapshots.mjs - regenerates `tests/fixtures/characterSnapshots.json`.
 *
 *   cd frontend
 *   node scripts/character-snapshots.mjs
 *
 * WHY THIS IS A SEPARATE PROCESS AND NOT A `toMatchSnapshot()`.
 *
 * G3 is "the same role string yields byte-identical character markup ACROSS
 * PROCESSES". A snapshot a test framework writes and then reads back inside
 * the same runner proves that the runner is consistent with itself, which is
 * not the claim. This file is plain Node importing the shipping `pip.ts`
 * directly - no Vite, no Vue, no jsdom, no transform pipeline - and
 * `characterDeterminism.spec.ts` is Vitest under jsdom with Vite's transform
 * in front of it. Two processes, two toolchains, one set of hashes.
 *
 * A FAILURE OF THAT SPEC IS NOT A BROKEN TEST. It means a character changed,
 * and every existing run, screenshot and reload changed with it. Regenerate
 * this file only when the change was intended, and say so in the commit.
 * --------------------------------------------------------------------------- */
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  BODY_NAMES,
  CREST_NAMES,
  EYE_NAMES,
  MOUTH_NAMES,
  identityFor,
  pipParts,
  pipSvg,
} from '../src/characters/pip.ts'

const here = path.dirname(fileURLToPath(import.meta.url))
const frontend = path.resolve(here, '..')
const out = path.join(frontend, 'tests', 'fixtures', 'characterSnapshots.json')

/**
 * Twenty roles.
 *
 * Thirteen are the cast on the evidence sheets: the six of the flow this
 * console shipped with, the three of the original pipeline, and four from a
 * flow invented for the sheets. The other seven are the awkward cases - odd
 * whitespace, shouting, punctuation, an accent, a bare node id with no role at
 * all, and a one-letter edit of a role already in the list. Between them they
 * pin the normaliser as well as the geometry, which is the point: a
 * determinism fixture that only ever sees tidy input cannot notice the
 * normaliser moving.
 */
const ROLES = [
  'Scoper',
  'Market Analyst',
  'Sentiment Analyst',
  'Feasibility Analyst',
  'Synthesist',
  'Reporter',
  'Researcher',
  'Analyst',
  'Writer',
  'Tone Coach',
  'Fact Checker',
  'Localisation Lead',
  'Pricing Strategist',
  '  MARKET   ANALYST ',
  'market-analyst',
  'Sentiment Analysts',
  'Résumé Writer',
  'Resume Writer',
  'Senior Analyst',
  '',
]

/** The one role with no name at all falls back to this node id. */
const FALLBACK_NODE_ID = 'n7_second_pass'

const snapshots = {}
const diagnostics = {}
for (const role of ROLES) {
  const identity = identityFor(role, role ? '' : FALLBACK_NODE_ID)
  const markup = pipSvg(identity.key, { size: 32, state: 'idle' })
  const parts = pipParts(identity.key)
  snapshots[role] = createHash('sha256').update(markup, 'utf8').digest('hex')
  diagnostics[role] = {
    seed: identity.key,
    named: identity.named,
    parts: [
      BODY_NAMES[parts.body],
      EYE_NAMES[parts.eyes],
      MOUTH_NAMES[parts.mouth],
      CREST_NAMES[parts.crest],
      `c${parts.colour}`,
    ].join('/'),
    bytes: markup.length,
  }
}

const fixture = {
  command: 'cd frontend && node scripts/character-snapshots.mjs',
  generatedBy: 'scripts/character-snapshots.mjs, plain Node, importing src/characters/pip.ts',
  assertedBy: 'tests/characterDeterminism.spec.ts, Vitest under jsdom through Vite',
  hashOf: "sha256(pipSvg(identityFor(role).key, { size: 32, state: 'idle' })), utf8",
  fallbackNodeId: FALLBACK_NODE_ID,
  note:
    'A mismatch is not a broken test. It means a character changed, and every ' +
    'screenshot, reload and running node changed with it. Regenerate only on ' +
    'purpose, and say so in the commit.',
  snapshots,
  diagnostics,
}

fs.mkdirSync(path.dirname(out), { recursive: true })
fs.writeFileSync(out, JSON.stringify(fixture, null, 2) + '\n', 'utf8')
console.log(`wrote ${path.relative(frontend, out)} - ${ROLES.length} roles`)
