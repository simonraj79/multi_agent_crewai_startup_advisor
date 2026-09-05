/* ---------------------------------------------------------------------------
 * PIPS - the run console's character system.
 *
 * One agent, one Pip. A Pip is a single-piece rounded creature: no limbs, no
 * face-plate, no separate head. Its whole identity is (1) the outline it is
 * cut from, (2) two oversized eyes, (3) a small resting mouth, and (4) a
 * flourish growing out of the crown. All four, plus the body colour, are a
 * pure function of the agent's identity string, so the same agent is the same
 * creature in every run, session and reload, and an unfamiliar role is a
 * stranger rather than a placeholder.
 *
 * FOUR MARKS ON SCREEN, NEVER MORE. At any instant a Pip shows: body (the
 * crest is cut from the same fill and fuses into that one silhouette), eye,
 * eye, mouth. Cheeks and eye sparkles are a DETAIL TIER the generator switches
 * off below 48px, because at 32px they are mud rather than charm.
 *
 * COLOUR is the twelve-entry character palette in
 * `frontend/src/assets/styles/motion.css`, referenced as `var(--character-N)`
 * so the theme swaps it. The index is the SAME raw FNV-1a modulo that
 * `useRunChoreography.characterIndex` uses, so for one and the same string the
 * two agree exactly and a Pip is the colour its node's medallion already is.
 *
 * STATE is six CSS classes on one unchanged SVG. Nothing here re-renders on a
 * frame; a run event sets a class and the browser does the rest. This module
 * knows nothing about runs, frames or flows - it is given a state and it draws
 * it.
 *
 * THIS FILE IS PURE. No DOM access, no clock, no randomness, no timer and no
 * imports - a grep for any of those over this module answers nothing, which is
 * itself part of the contract (T2.5). Every export is a total function of its
 * arguments; that is what makes a character survive a reload, agree across two
 * processes, and be snapshot-testable at all (G3).
 * --------------------------------------------------------------------------- */

/**
 * Six states. `blocked` is "a human is holding this up"; `blocked-error` is a
 * node that failed.
 *
 * They share the pose, the frown and the wilted crown, and they are separated
 * by TWO signals: the outline colour (`--warn-border` against `--err-border`)
 * AND the eyes, which close into two crosses for the error. The second signal
 * exists because a cold reader given only the evidence sheets reported that
 * the outline hue was the sole difference - which means a colour-blind viewer
 * sees one state where the product means two. Colour is never allowed to be
 * the only carrier of a distinction, and a cross is four straight strokes, so
 * it is one of the few expressions that survives the 32px raster.
 */
export type PipState = 'idle' | 'working' | 'speaking' | 'blocked' | 'blocked-error' | 'done'

export const PIP_STATES: readonly PipState[] = [
  'idle',
  'working',
  'speaking',
  'blocked',
  'blocked-error',
  'done',
]

/** What `identityFor` resolved, and whether it had a name to work from. */
export interface PipIdentity {
  /** The normalised string that is hashed and rendered as `data-character`. */
  key: string
  /** False when no role was supplied and the fallback chain was used. */
  named: boolean
}

/** The five hash-selected axes. Indices into the `*_NAMES` arrays below. */
export interface PipParts {
  body: number
  eyes: number
  mouth: number
  crest: number
  /** 1..12, indexing `--character-N`. */
  colour: number
}

export interface PipOptions {
  /** Rendered edge in CSS px. Drives the detail tier at 48. */
  size?: number
  state?: PipState
  /** Force the detail tier on or off. Defaults to `size >= 48`. */
  detail?: boolean
}

/* ---------------------------------------------------------------- the hash */

const FNV_OFFSET = 0x811c9dc5
const FNV_PRIME = 0x01000193

/**
 * FNV-1a, 32-bit - byte for byte the loop in
 * `useRunChoreography.ts::characterIndex`. `Math.imul` is the only 32-bit
 * multiply JavaScript has; `*` promotes past 2^53 and the low bits stop being
 * exact, which is where a hash lives.
 */
export function fnv1a(input: string): number {
  let hash = FNV_OFFSET
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index)
    hash = Math.imul(hash, FNV_PRIME) >>> 0
  }
  return hash >>> 0
}

/**
 * The finaliser (Murmur3-style `lowbias32`), applied ONCE before the four
 * shape fields are sliced out.
 *
 * It is here because raw FNV-1a's low bits are barely mixed - its last
 * operation is a multiply, so the low bits are a shallow function of the last
 * bytes fed in, and `% 4` / `% 6` read exactly those bits. Agent roles are
 * natural language and natural language has a small set of endings, so this is
 * the common case here and not a contrived one: two ordinary role words that
 * hash to wholly different numbers were measured agreeing under `% 4`, `% 6`
 * and `% 8` alike, and came out as the same creature in all four shape axes.
 * Slicing four independent selectors out of an unavalanched word is how a
 * family of roles that rhyme ends up wearing one hat.
 *
 * The COLOUR deliberately does NOT go through it: it uses the raw FNV modulo
 * 12, which is exactly what `characterIndex` does, so for one and the same
 * string the two cannot disagree. That agreement matters more than the bias,
 * and twelve colours over a sixteen-node graph must collide anyway - which
 * `characterIndex`'s own comment already says.
 */
export function mix32(word: number): number {
  let x = word >>> 0
  x ^= x >>> 16
  x = Math.imul(x, 0x7feb352d) >>> 0
  x ^= x >>> 15
  x = Math.imul(x, 0x846ca68b) >>> 0
  x ^= x >>> 16
  return x >>> 0
}

/**
 * NFKD, drop the combining marks, lowercase, every run of non-alphanumerics
 * to one space, trimmed.
 *
 * So `"Tone Coach"`, `"tone-coach"` and `"  TONE   COACH "` are one agent, and
 * `"Senior Editor"` and `"Editor"` are two.
 *
 * DROPPING THE MARKS IS A SEPARATE STEP AND IT HAS TO BE. NFKD decomposes an
 * accented letter into a base letter FOLLOWED BY a combining mark, and the
 * mark then sits in the middle of a word - so handing it straight to
 * `[^a-z0-9]+` turns it into a space and splits the word: `"Resume Writer"`
 * with an acute became `re sume writer`, three tokens, a different hash and a
 * different creature from the same name typed without the accent. Measured;
 * the first draft of this function shipped that bug and a test caught it.
 *
 * The class is written as escapes rather than as the characters themselves,
 * because a combining mark pasted into source is invisible in every editor
 * and a diff over it is unreadable. U+0300..U+036F is the combining
 * diacritical block NFKD produces.
 */
export function normaliseIdentity(value: string): string {
  return (value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

/**
 * The exact string a Pip is hashed from and rendered as `data-character`.
 *
 * Total and idempotent: `characterSeed(characterSeed(x)) === characterSeed(x)`,
 * so a caller may hand it a raw role, a key from `identityFor`, or an already
 * normalised seed read back off the DOM, and get the same answer. Empty input
 * floors to the literal `'agent'` so the function never returns `''` and
 * nothing downstream has to check.
 */
export function characterSeed(key: string): string {
  return normaliseIdentity(key) || 'agent'
}

export const PIP_COLOURS = 12
export const BODY_COUNT = 4
export const EYE_COUNT = 4
export const MOUTH_COUNT = 3
export const CREST_COUNT = 6

/** 4 x 4 x 3 x 6 x 12. Every one of them is reachable; `characterSystem.spec.ts` measures it. */
export const PIP_COMBINATIONS = BODY_COUNT * EYE_COUNT * MOUTH_COUNT * CREST_COUNT * PIP_COLOURS

/**
 * identity -> the key that is hashed, and whether it came from a name.
 *
 * THE FALLBACK CHAIN IS role -> nodeId -> task -> 'agent', and the order of
 * the middle two is a decision rather than a convenience. A task name is
 * authored text that a router can vary between two passes of the same node, so
 * hashing it ahead of the node id would repaint the cast mid-run - the exact
 * defect `characterIndex`'s docstring says it exists to avoid. A node id is
 * fixed for the life of the graph and is on every frame. Task is kept as the
 * last resort before the literal, because a frame that carries neither a role
 * nor a node id still carries something a human wrote, and a character built
 * from it is better than every such agent sharing one.
 *
 * WHAT THE FALLBACK LOOKS LIKE IS: an ordinary Pip. There is no placeholder
 * face and no question-mark badge, because a system whose strangers look
 * broken punishes the author of every flow it has never seen. `named: false`
 * is returned so the CAPTION beside the figure can show the node id instead of
 * a role - that is the only difference, and it is outside the character.
 */
export function identityFor(role?: string, nodeId?: string, task?: string): PipIdentity {
  const fromRole = normaliseIdentity(role ?? '')
  const fromNode = normaliseIdentity(nodeId ?? '')
  const fromTask = normaliseIdentity(task ?? '')
  const key = fromRole || fromNode || fromTask || 'agent'
  return { key, named: fromRole.length > 0 }
}

/**
 * key -> parts. Pure, total, never throws.
 *
 * The key is normalised on the way in, so `pipParts('Tone Coach')` and
 * `pipParts(identityFor('Tone Coach').key)` are the same parts.
 */
export function pipParts(key: string): PipParts {
  const seed = characterSeed(key)
  const raw = fnv1a(seed)
  const mixed = mix32(raw)

  return {
    body: (mixed & 0xff) % BODY_COUNT,
    eyes: ((mixed >>> 8) & 0xff) % EYE_COUNT,
    mouth: ((mixed >>> 16) & 0xff) % MOUTH_COUNT,
    crest: ((mixed >>> 24) & 0xff) % CREST_COUNT,
    colour: (raw % PIP_COLOURS) + 1,
  }
}

/* --------------------------------------------------------------- the parts */

export interface BodyPart {
  id: string
  d: string
  /** Eye centre line, and half the distance between the two eye centres. */
  eyeY: number
  eyeDx: number
  /**
   * How far below the eye line the mouth sits. Per body, because the 32px
   * raster test caught the first draft putting the bean's mouth in its waist.
   */
  mouthDy: number
  /** Where the crest is hinged. */
  crownX: number
  crownY: number
  crestScale: number
}

/**
 * Four outlines, chosen so the SILHOUETTE alone separates them at 32px - the
 * only cue that survives that size. Squat-and-wide, tall-and-tapered,
 * two-lobed-with-a-waist, and flared-with-two-feet.
 *
 * All four stand on the same floor (y = 28) so a row of Pips lines up, and all
 * four are one closed path, so the crest can be cut from the same fill and the
 * pair reads as one creature rather than a body wearing a hat.
 */
export const BODIES: readonly BodyPart[] = [
  {
    id: 'pebble',
    d:
      'M 5 21.4 C 5 12.6 9.9 7.4 16 7.4 C 22.1 7.4 27 12.6 27 21.4 ' +
      'C 27 25.4 25.2 27.8 21.6 27.8 L 10.4 27.8 C 6.8 27.8 5 25.4 5 21.4 Z',
    eyeY: 17.9,
    eyeDx: 4.7,
    mouthDy: 5.3,
    crownX: 16,
    crownY: 7.6,
    crestScale: 1,
  },
  {
    id: 'drop',
    d:
      'M 14.5 6.8 C 15.1 5.6 16.9 5.6 17.5 6.8 C 21.1 10.7 25.5 15.1 25.5 19.9 ' +
      'C 25.5 24.8 21.2 28.0 16 28.0 C 10.8 28.0 6.5 24.8 6.5 19.9 ' +
      'C 6.5 15.1 10.9 10.7 14.5 6.8 Z',
    eyeY: 19.2,
    eyeDx: 4.5,
    mouthDy: 4.9,
    crownX: 16,
    crownY: 6.3,
    crestScale: 0.9,
  },
  {
    /* Two lobes in one outline - a big head over a smaller base, pinched at
       the waist. The first draft was a narrow leaning peanut and the 32px
       raster showed its eyes touching both edges; this one gives them 1.5
       units of body on each side, which is the whole reason it is shaped the
       way it is. */
    id: 'bean',
    d:
      'M 16 5.8 C 20.9 5.8 24.5 9.1 24.5 13.5 C 24.5 16.3 22.9 17.9 23.4 19.9 ' +
      'C 24.4 23.6 21.2 28.0 16 28.0 C 10.8 28.0 7.6 23.6 8.6 19.9 ' +
      'C 9.1 17.9 7.5 16.3 7.5 13.5 C 7.5 9.1 11.1 5.8 16 5.8 Z',
    eyeY: 13.6,
    eyeDx: 4.3,
    mouthDy: 4.4,
    crownX: 16,
    crownY: 6.0,
    crestScale: 0.86,
  },
  {
    id: 'bell',
    d:
      'M 16 6.7 C 21.4 6.7 25.3 10.7 25.5 15.9 C 25.7 20.3 25.9 23.7 26.3 26.5 ' +
      'Q 21.3 29.4 16 26.5 Q 10.7 29.4 5.7 26.5 ' +
      'C 6.1 23.7 6.3 20.3 6.5 15.9 C 6.7 10.7 10.6 6.7 16 6.7 Z',
    eyeY: 17.2,
    eyeDx: 4.8,
    mouthDy: 5.3,
    crownX: 16,
    crownY: 6.9,
    crestScale: 1,
  },
]

export const BODY_NAMES: readonly string[] = ['pebble', 'drop', 'bean', 'bell']
export const EYE_NAMES: readonly string[] = ['round', 'oval', 'square', 'lens']
export const MOUTH_NAMES: readonly string[] = ['smile', 'cat-w', 'oh']
export const CREST_NAMES: readonly string[] = ['antenna', 'sprout', 'curl', 'ring', 'fin', 'ears']

/**
 * A coordinate, rounded to three decimals and printed without a trailing zero.
 *
 * Every number in the markup goes through this, because `16 - 4.7 - 3.2` is
 * `7.999999999999999` in IEEE 754 and a figure whose path data is full of
 * fifteen-digit noise is unreadable in a diff, unreadable in a snapshot and
 * indistinguishable at a glance from a figure that has genuinely moved. The
 * arithmetic is deterministic either way - this is legibility, not
 * correctness - and 0.001 of a viewBox unit is 1/32000 of a 32px figure.
 */
function n(value: number): string {
  return String(Math.round(value * 1000) / 1000)
}

/**
 * Four eyes. NOT four expressions - expression belongs to the state, and an
 * identity that already looked like it was winking could not then be asked to
 * look worried. These are four SHAPES: a full round, a tall oval, a soft
 * rounded square, and a lens ring. Radius 3.2 puts the pair at ~58% of the
 * body's width, which is the whole kawaii proportion argument in one number.
 */
export function eyeShape(variant: number, cx: number, cy: number): string {
  switch (variant) {
    case 1:
      return `<ellipse cx="${n(cx)}" cy="${n(cy)}" rx="2.75" ry="3.55" />`
    case 2:
      return `<rect x="${n(cx - 3.1)}" y="${n(cy - 2.75)}" width="6.2" height="5.5" rx="2.3" />`
    case 3:
      return (
        `<path d="M ${n(cx - 3.2)} ${n(cy)} a 3.2 3.2 0 1 0 6.4 0 a 3.2 3.2 0 1 0 -6.4 0 ` +
        `M ${n(cx - 1.35)} ${n(cy)} a 1.35 1.35 0 1 1 2.7 0 a 1.35 1.35 0 1 1 -2.7 0 Z" fill-rule="evenodd" />`
      )
    default:
      return `<circle cx="${n(cx)}" cy="${n(cy)}" r="3.2" />`
  }
}

/** Where the sparkle sits inside each eye shape. The lens has a hole already. */
function sparkle(variant: number, cx: number, cy: number): string {
  if (variant === 3) return ''
  return `<circle cx="${n(cx + 1.05)}" cy="${n(cy - 1.15)}" r="0.95" />`
}

/**
 * Three RESTING mouths - the one an agent wears for most of a run, which is
 * why it is worth an identity axis at all. A soft smile, a cat "w", and a
 * small round "o". The other five states override it, which is exactly why
 * this axis gets three variants and not six.
 */
export const REST_MOUTHS: ReadonlyArray<(x: number, y: number) => string> = [
  (x, y) =>
    `<path d="M ${n(x - 2.7)} ${n(y - 0.6)} Q ${n(x)} ${n(y + 2.2)} ${n(x + 2.7)} ${n(y - 0.6)}" class="pip-stroke" />`,
  (x, y) =>
    `<path d="M ${n(x - 3.0)} ${n(y - 0.3)} Q ${n(x - 1.5)} ${n(y + 1.5)} ${n(x)} ${n(y - 0.3)} Q ${n(x + 1.5)} ${n(y + 1.5)} ${n(x + 3.0)} ${n(y - 0.3)}" class="pip-stroke" />`,
  (x, y) => `<ellipse cx="${n(x)}" cy="${n(y + 0.3)}" rx="1.8" ry="1.5" />`,
]

/**
 * Six crowns. Each is one group filled with `currentColor`, so it fuses with
 * the body into a single outline instead of reading as a hat. It is also the
 * part that wilts when the agent is blocked.
 *
 * THE ANTENNA AND THE RING WERE SHORTENED, AND THE BEAN'S `crestScale` CUT
 * FROM 0.94 TO 0.86, because the 32px raster found four of the twenty-four
 * (body x crest) pairs reaching above `y = 0` and being cut flat by the
 * viewBox - bean+ring worst at -0.72 units. `.pip-svg` sets `overflow:
 * visible`, so in the live DOM they were not clipped but spilled out of the
 * figure's own box instead, which is the same defect wearing a different coat
 * on a 32px node slot. Every pair now clears the top edge by at least 0.40
 * units and `characterSystem.spec.ts` measures all twenty-four rather than
 * trusting this paragraph.
 */
export function crestShape(variant: number): string {
  switch (variant) {
    case 1: // sprout
      return '<path d="M 0 0.6 C 0.5 -2.6 2.9 -4.6 5.5 -4.9 C 5.4 -2.3 3.4 -0.1 0 0.6 Z" />'
    case 2: // curl
      return '<path d="M -3.0 0.6 C -2.7 -3.8 1.4 -6.3 4.3 -4.6 C 2.1 -4.6 -0.3 -3.2 -1.0 -0.2 Z" />'
    case 3: // ring
      return '<ellipse cx="0" cy="-4.15" rx="4.2" ry="1.3" fill="none" class="pip-stroke" />'
    case 4: // fin
      return '<path d="M -4.8 0.8 C -3.6 -3.6 -1.3 -5.4 0 -5.4 C 1.3 -5.4 3.6 -3.6 4.8 0.8 Z" />'
    case 5: // ears
      return (
        '<path d="M -6.0 1.6 C -7.0 -2.6 -4.6 -5.2 -2.2 -2.0 Z ' +
        'M 6.0 1.6 C 7.0 -2.6 4.6 -5.2 2.2 -2.0 Z" />'
      )
    default: // antenna
      return (
        '<path d="M 0.3 0.8 C 0.1 -1.4 1.0 -2.7 2.2 -3.6" fill="none" class="pip-stroke" />' +
        '<circle cx="2.9" cy="-4.6" r="1.75" />'
      )
  }
}

/* --------------------------------------------------------------- the markup */

const STATE_WORDS: Record<PipState, string> = {
  idle: 'waiting to start',
  working: 'working',
  speaking: 'speaking',
  blocked: 'blocked, needs you',
  'blocked-error': 'stopped by an error',
  done: 'finished',
}

/** The state, in words, for an aria-label. Never a code. */
export function pipStateWord(state: PipState): string {
  return STATE_WORDS[state] ?? STATE_WORDS.idle
}

/** `body/eyes/mouth/crown/cN` - what the component publishes as `data-parts`. */
export function pipPartsLabel(key: string): string {
  const parts = pipParts(key)
  return [
    BODY_NAMES[parts.body],
    EYE_NAMES[parts.eyes],
    MOUTH_NAMES[parts.mouth],
    CREST_NAMES[parts.crest],
    `c${parts.colour}`,
  ].join('/')
}

/** Below this the detail tier is off: cheeks and sparkles are mud at 32px. */
export const DETAIL_MIN_SIZE = 48

/**
 * How much bigger the crown is drawn below `DETAIL_MIN_SIZE`, and how far the
 * whole figure drops to make room for it.
 *
 * A COLD READER FOUND THE DEFECT THIS FIXES. Given the sheets alone, they
 * could separate two same-coloured agents when magnified but "would not bet on
 * it in isolation" at a true 32px. The reason is measurable: at 32px the body
 * and the eyes are shared vocabulary, so the crown is doing nearly all of the
 * identifying work, and the crown was 5 or 6 units of a 32-unit box - two to
 * three actual pixels. One of the pair wore a `fin`, which at that size was
 * indistinguishable from the `bell` body's own peak.
 *
 * So below 48px the crown is drawn 1.3x and the figure is moved 2 units down
 * the box to keep every crown inside it. The DROP rather than a shrink is the
 * point: shrinking the figure to make room at the top would have taken the eyes down
 * with it, and the eyes are the other thing that has to survive 32px. The box
 * has four unused units under the floor and this spends two of them.
 */
export const SMALL_CREST_SCALE = 1.3
export const SMALL_LIFT = 2

/**
 * The whole character, as one inline SVG string. No raster, no sprite sheet,
 * no external file, no font, no network.
 *
 * THE IDENTITY STRING NEVER ENTERS THE MARKUP. It is consumed by the hash and
 * nothing else: every character in the returned string comes from a closed set
 * of literals in this file plus numbers computed from the geometry table. That
 * is what makes `v-html` on the result safe by construction rather than by
 * sanitising, and `characterSystem.spec.ts` asserts it with a `<script>` tag
 * for an identity.
 *
 * Every state is present in the markup and CSS shows exactly one, because a
 * class change is the only thing cheap enough to be driven by a run frame and
 * the only thing that survives a `prefers-reduced-motion` query without the
 * caller knowing about it.
 */
export function pipSvg(key: string, options: PipOptions = {}): string {
  const { state = 'idle', size = 32 } = options
  const seed = characterSeed(key)
  const id = pipParts(seed)
  const body = BODIES[id.body]
  const small = size < DETAIL_MIN_SIZE
  const detail = options.detail ?? !small

  const lx = 16 - body.eyeDx
  const rx = 16 + body.eyeDx
  const ey = body.eyeY
  const my = ey + body.mouthDy

  const eyesOpen =
    `<g class="pip-eyes-open pip-ink">${eyeShape(id.eyes, lx, ey)}${eyeShape(id.eyes, rx, ey)}</g>`
  const eyesArc =
    `<g class="pip-eyes-arc pip-ink">` +
    `<path class="pip-stroke" d="M ${n(lx - 3.0)} ${n(ey + 0.9)} Q ${n(lx)} ${n(ey - 2.7)} ${n(lx + 3.0)} ${n(ey + 0.9)}" />` +
    `<path class="pip-stroke" d="M ${n(rx - 3.0)} ${n(ey + 0.9)} Q ${n(rx)} ${n(ey - 2.7)} ${n(rx + 3.0)} ${n(ey + 0.9)}" />` +
    `</g>`

  /* The x_x eyes, and they exist because a cold reader caught the defect: the
     amber outline was the ONLY thing separating "a human is holding this up"
     from "this failed", so a colour-blind viewer saw one state where the
     product means two. Colour must never be the sole carrier of a distinction.
     A cross is the kawaii idiom for it, it is two straight strokes so it
     survives the 32px raster where a subtler face would not, and it is the
     largest change the eyes can make short of closing them - which `done`
     already owns. */
  const eyesCross =
    `<g class="pip-eyes-cross pip-ink">` +
    `<path class="pip-stroke" d="M ${n(lx - 2.6)} ${n(ey - 2.6)} L ${n(lx + 2.6)} ${n(ey + 2.6)} M ${n(lx + 2.6)} ${n(ey - 2.6)} L ${n(lx - 2.6)} ${n(ey + 2.6)}" />` +
    `<path class="pip-stroke" d="M ${n(rx - 2.6)} ${n(ey - 2.6)} L ${n(rx + 2.6)} ${n(ey + 2.6)} M ${n(rx + 2.6)} ${n(ey - 2.6)} L ${n(rx - 2.6)} ${n(ey + 2.6)}" />` +
    `</g>`

  const detailMarkup = detail
    ? `<g class="pip-detail">` +
      `<ellipse class="pip-cheek" cx="${n(lx - 2.7)}" cy="${n(ey + 3.6)}" rx="1.9" ry="1.25" />` +
      `<ellipse class="pip-cheek" cx="${n(rx + 2.7)}" cy="${n(ey + 3.6)}" rx="1.9" ry="1.25" />` +
      `<g class="pip-spark">${sparkle(id.eyes, lx, ey)}${sparkle(id.eyes, rx, ey)}</g>` +
      `</g>`
    : ''

  const mouths =
    `<g class="pip-ink">` +
    `<g class="pip-mouth pip-mouth--rest">${REST_MOUTHS[id.mouth](16, my)}</g>` +
    `<g class="pip-mouth pip-mouth--work"><path class="pip-stroke" d="M ${n(16 - 1.9)} ${n(my + 0.2)} L ${n(16 + 1.9)} ${n(my + 0.2)}" /></g>` +
    `<g class="pip-mouth pip-mouth--speak"><ellipse cx="16" cy="${n(my + 0.2)}" rx="2.35" ry="2.9" /></g>` +
    `<g class="pip-mouth pip-mouth--block"><path class="pip-stroke" d="M ${n(16 - 2.6)} ${n(my + 1.0)} Q 16 ${n(my - 0.9)} ${n(16 + 2.6)} ${n(my + 1.0)}" /></g>` +
    `<g class="pip-mouth pip-mouth--done"><path d="M ${n(16 - 3.3)} ${n(my - 0.9)} A 3.3 3.3 0 0 0 ${n(16 + 3.3)} ${n(my - 0.9)} Z" /></g>` +
    `</g>`

  /* The crown grows below 48px, and the figure drops to make room. Both are
     done here rather than in CSS, for one reason each. The SCALE cannot be a
     CSS transform on `.pip-crest-hinge` because the blocked wilt already owns
     that property on that element, and `transform` is one property - the wilt
     would silently drop the boost. The LIFT cannot go on `.pip-figure` for the
     same reason (the pose owns it there), so it rides an outer group with no
     CSS transform of its own. */
  const crestScale = body.crestScale * (small ? SMALL_CREST_SCALE : 1)
  const lift = small ? SMALL_LIFT : 0
  const crest =
    `<g class="pip-crest-hinge" style="transform-origin:${n(body.crownX)}px ${n(body.crownY)}px">` +
    `<g transform="translate(${n(body.crownX)} ${n(body.crownY)}) scale(${n(crestScale)})">${crestShape(id.crest)}</g>` +
    `</g>`

  /* The state and size classes ride on the SVG as well as on the component's
     wrapper. They have to: the raster proof and the design sheets render this
     string with no wrapper at all, and a state that only reads through an
     ancestor would be a second code path in exactly the artefact that exists
     to check the first one. `aria-hidden` because the wrapper carries the
     `role="img"` and the label - two accessible names for one figure is a
     screen reader saying everything twice. */
  return (
    `<svg class="pip-svg pip--${state}${small ? ' pip--sm' : ''}" viewBox="0 0 32 32" ` +
    `width="${size}" height="${size}" aria-hidden="true" focusable="false" ` +
    `style="color:var(--character-${id.colour})">` +
    `<g class="pip-frame" transform="translate(0 ${n(lift)})">` +
    `<g class="pip-figure">` +
    `<g class="pip-shell">${crest}<path class="pip-body" d="${body.d}" /></g>` +
    detailMarkup +
    eyesOpen +
    eyesArc +
    eyesCross +
    mouths +
    `</g>` +
    `</g>` +
    `</svg>`
  )
}
