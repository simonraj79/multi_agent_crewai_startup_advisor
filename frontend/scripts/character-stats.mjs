/* ---------------------------------------------------------------------------
 * character-stats.mjs - the measured figures quoted in docs/run-shell/CHARACTERS.md.
 *
 *   cd frontend
 *   node scripts/character-stats.mjs
 *
 * Every number in that document's "Measured" section is this script's output,
 * pasted. Nothing there is reasoned about and nothing is carried over from the
 * design proposal: this repository has a long written record of what happens
 * to a figure that is quoted rather than regenerated, and the rule it arrived
 * at is that the command is the contract and the number never is.
 *
 * It imports `src/characters/pip.ts` directly - the shipping file - so a
 * figure here cannot describe a generator that is no longer the one in the
 * component.
 * --------------------------------------------------------------------------- */
import {
  BODY_COUNT,
  BODY_NAMES,
  CREST_COUNT,
  CREST_NAMES,
  EYE_COUNT,
  EYE_NAMES,
  MOUTH_COUNT,
  MOUTH_NAMES,
  PIP_COLOURS,
  PIP_COMBINATIONS,
  characterSeed,
  identityFor,
  pipParts,
  pipSvg,
} from '../src/characters/pip.ts'

const AXES = [
  ['body', BODY_COUNT, BODY_NAMES],
  ['eyes', EYE_COUNT, EYE_NAMES],
  ['mouth', MOUTH_COUNT, MOUTH_NAMES],
  ['crest', CREST_COUNT, CREST_NAMES],
  ['colour', PIP_COLOURS, Array.from({ length: PIP_COLOURS }, (_, i) => `c${i + 1}`)],
]

/** Deterministic, deliberately unnatural keys - the wide sample. */
function syntheticKey(index) {
  return `role ${index} agent ${index * 7919}`
}

/**
 * A natural-language-shaped corpus, which is the sample that matters: the
 * hash's weakness, if it has one, is on roles that rhyme, and synthetic keys
 * do not rhyme.
 */
const HEADS = [
  'senior', 'junior', 'lead', 'principal', 'staff', 'chief', 'associate', 'deputy',
  'market', 'sentiment', 'content', 'tone', 'pricing', 'fact', 'risk', 'growth',
  'data', 'legal', 'brand', 'field', 'client', 'partner', 'release', 'quality',
]
const TAILS = [
  'analyst', 'researcher', 'writer', 'editor', 'reporter', 'coach', 'checker',
  'strategist', 'scoper', 'synthesist', 'reviewer', 'planner', 'specialist',
  'lead', 'architect', 'operator', 'curator', 'auditor',
]
function naturalCorpus() {
  const roles = []
  for (const head of HEADS) for (const tail of TAILS) roles.push(`${head} ${tail}`)
  for (const tail of TAILS) roles.push(tail)
  return roles
}

function distribution(keys) {
  const counts = AXES.map(([, size]) => Array(size).fill(0))
  for (const key of keys) {
    const parts = pipParts(key)
    counts[0][parts.body] += 1
    counts[1][parts.eyes] += 1
    counts[2][parts.mouth] += 1
    counts[3][parts.crest] += 1
    counts[4][parts.colour - 1] += 1
  }
  return counts
}

const WIDE = 200_000
const wideKeys = Array.from({ length: WIDE }, (_, index) => syntheticKey(index))

console.log(`distribution over ${WIDE.toLocaleString('en-GB')} synthetic keys, % per bucket`)
const wide = distribution(wideKeys)
AXES.forEach(([name], axis) => {
  const line = wide[axis].map((count) => ((count / WIDE) * 100).toFixed(2)).join(' ')
  console.log(`  ${name.padEnd(6)} ${line}`)
})

const natural = naturalCorpus()
console.log(`\ndistribution over a ${natural.length}-role natural-language corpus, count per bucket`)
const nat = distribution(natural)
AXES.forEach(([name, , names], axis) => {
  console.log(`  ${name.padEnd(6)} ${nat[axis].map((c, i) => `${names[i]}=${c}`).join(' ')}`)
})

/* Reachability. */
const seen = new Set()
let reachedAt = 0
for (let index = 0; index < 500_000; index += 1) {
  const p = pipParts(syntheticKey(index))
  seen.add(`${p.body}.${p.eyes}.${p.mouth}.${p.crest}.${p.colour}`)
  if (seen.size === PIP_COMBINATIONS && reachedAt === 0) {
    reachedAt = index + 1
    break
  }
}
console.log(`\ndistinct characters reachable            ${seen.size} of ${PIP_COMBINATIONS}`)
console.log(`keys needed to hit all of them            ${reachedAt.toLocaleString('en-GB')}`)

/* Collisions between unrelated roles. */
const PAIRS = 400_000
let collisions = 0
for (let index = 0; index < PAIRS; index += 1) {
  const a = pipParts(syntheticKey(index * 2))
  const b = pipParts(syntheticKey(index * 2 + 1))
  if (
    a.body === b.body &&
    a.eyes === b.eyes &&
    a.mouth === b.mouth &&
    a.crest === b.crest &&
    a.colour === b.colour
  ) {
    collisions += 1
  }
}
console.log(
  `\nunrelated-pair full collision, ${PAIRS.toLocaleString('en-GB')} pairs  ` +
    `${(collisions / PAIRS).toFixed(5)}   (1/${PIP_COMBINATIONS} = ${(1 / PIP_COMBINATIONS).toFixed(5)})`,
)

/* Collisions inside the natural corpus - the sample that matters. */
const natTuples = natural.map((role) => JSON.stringify(pipParts(role)))
console.log(
  `natural corpus: ${natural.length} roles -> ${new Set(natTuples).size} distinct characters`,
)
const natColours = natural.map((role) => pipParts(role).colour)
console.log(`natural corpus colours used              ${new Set(natColours).size} of ${PIP_COLOURS}`)

/* One word apart, and one letter apart. */
console.log('\naxes that differ, one word apart')
const WORD_PAIRS = [
  ['Analyst', 'Senior Analyst'],
  ['Writer', 'Technical Writer'],
  ['Researcher', 'Senior Researcher'],
  ['Editor', 'Copy Editor'],
  ['Coach', 'Tone Coach'],
  ['Checker', 'Fact Checker'],
  ['Reporter', 'Reporters'],
]
for (const [left, right] of WORD_PAIRS) {
  const a = pipParts(left)
  const b = pipParts(right)
  const differ = ['body', 'eyes', 'mouth', 'crest', 'colour'].filter((axis) => a[axis] !== b[axis])
  console.log(`  ${(left + ' / ' + right).padEnd(38)} ${differ.length} of 5  (${differ.join(', ')})`)
}

let sameColour = 0
let identical = 0
const EDITS = 100_000
for (let index = 0; index < EDITS; index += 1) {
  const base = syntheticKey(index)
  const edited = base.slice(0, -1) + (base.endsWith('9') ? '8' : '9')
  const a = pipParts(base)
  const b = pipParts(edited)
  if (a.colour === b.colour) sameColour += 1
  if (JSON.stringify(a) === JSON.stringify(b)) identical += 1
}
console.log(
  `\nlast-character edit -> same colour        ${(sameColour / EDITS).toFixed(5)} over ${EDITS.toLocaleString('en-GB')}`,
)
console.log(`last-character edit -> same character     ${(identical / EDITS).toFixed(5)}`)

/* Stability of the normaliser, and the size of what ships. */
const spellings = ['Tone Coach', '  TONE   COACH ', 'tone-coach', 'Tone_Coach!', 'Tone  coach']
console.log(
  `\nfive spellings of one name -> ${new Set(spellings.map(characterSeed)).size} character`,
)
console.log(
  `empty role -> node id                     ${JSON.stringify(identityFor('', 'n7_second_pass'))}`,
)
console.log(
  `\nmarkup size at 32px (no detail tier)      ${pipSvg('Tone Coach', { size: 32 }).length} bytes`,
)
console.log(
  `markup size at 96px (detail tier on)      ${pipSvg('Tone Coach', { size: 96 }).length} bytes`,
)
