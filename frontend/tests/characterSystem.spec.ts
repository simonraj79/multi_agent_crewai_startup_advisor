import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import AgentCharacter from '../src/components/AgentCharacter.vue'
import {
  BODIES,
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
  PIP_STATES,
  SMALL_CREST_SCALE,
  SMALL_LIFT,
  characterSeed,
  crestShape,
  eyeShape,
  fnv1a,
  identityFor,
  normaliseIdentity,
  pipParts,
  pipPartsLabel,
  pipStateWord,
  pipSvg,
  type PipState,
} from '../src/characters/pip'
import { characterIndex } from '../src/composables/useRunChoreography'

/**
 * A source file, read at test time.
 *
 * The relative path goes through a variable deliberately. Vite rewrites
 * `new URL('<literal>', import.meta.url)` into an ASSET url at transform time,
 * so a literal here resolves to an http scheme and `fileURLToPath` refuses it;
 * a variable is opaque to that transform and the expression stays what it
 * reads as. `clientMirrors.spec.ts` carries the same note for the same reason.
 */
function source(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8')
}

const CHARACTER_CSS = source('../src/assets/styles/character.css')

/** A large, deterministic, deliberately unnatural key set. */
function syntheticKeys(count: number): string[] {
  const keys: string[] = []
  for (let index = 0; index < count; index += 1) keys.push(`role ${index} agent ${index * 7919}`)
  return keys
}

describe('the identity a Pip is built from', () => {
  it('normalises spelling, case and punctuation to one agent', () => {
    const spellings = ['Tone Coach', 'tone-coach', '  TONE   COACH ', 'Tone_Coach!', 'tone  coach']
    const seeds = new Set(spellings.map((spelling) => characterSeed(spelling)))
    expect(seeds).toEqual(new Set(['tone coach']))
  })

  it('keeps two genuinely different roles apart', () => {
    expect(characterSeed('Senior Editor')).not.toBe(characterSeed('Editor'))
  })

  it('folds an accent to its base letter rather than splitting the word', () => {
    /* The bug this test was written for: NFKD alone leaves a combining mark
       INSIDE the word, and `[^a-z0-9]+` then turns it into a space - so the
       accented spelling became three tokens and a different creature from the
       unaccented one. */
    const accented = 'R' + 'é' + 'sum' + 'é' + ' Writer'
    expect(characterSeed(accented)).toBe('resume writer')
    expect(pipParts(accented)).toEqual(pipParts('Resume Writer'))
  })

  it('is idempotent, so a seed read back off the DOM re-seeds to itself', () => {
    const once = characterSeed('  Pricing   Strategist  ')
    expect(characterSeed(once)).toBe(once)
  })

  it('falls back role -> nodeId -> task -> agent, and says when it had no name', () => {
    expect(identityFor('Tone Coach', 'n3_tone', 'polish the draft')).toEqual({
      key: 'tone coach',
      named: true,
    })
    expect(identityFor('', 'n3_tone', 'polish the draft')).toEqual({ key: 'n3 tone', named: false })
    expect(identityFor('', '', 'polish the draft')).toEqual({ key: 'polish the draft', named: false })
    expect(identityFor()).toEqual({ key: 'agent', named: false })
    expect(identityFor('   ', '   ', '   ')).toEqual({ key: 'agent', named: false })
  })

  it('renders every part for an agent that fell back to its node id', () => {
    const fallback = identityFor('', 'n7_second_pass')
    expect(fallback.named).toBe(false)
    const parts = pipParts(fallback.key)
    expect(parts.body).toBeGreaterThanOrEqual(0)
    expect(parts.colour).toBeGreaterThanOrEqual(1)
    /* An ordinary Pip, not a placeholder: same four marks, same crest, same
       colour token as any named agent. `named: false` changes the caption
       beside it and nothing inside it. */
    const markup = pipSvg(fallback.key, { size: 96 })
    expect(markup).toContain('class="pip-body"')
    expect(markup).toContain('pip-eyes-open')
    expect(markup).toContain('pip-mouth--rest')
    expect(markup).toContain('pip-crest-hinge')
    expect(markup).toContain('pip-detail')
    expect(markup).toMatch(/var\(--character-([1-9]|1[0-2])\)/)
  })
})

describe('the hash', () => {
  it('gives the same key the same parts and the same markup, every time', () => {
    for (const role of ['Tone Coach', 'Fact Checker', 'n4_gate', 'agent']) {
      expect(pipParts(role)).toEqual(pipParts(role))
      expect(pipSvg(role, { size: 32 })).toBe(pipSvg(role, { size: 32 }))
    }
  })

  it('agrees with the console medallion for one and the same string', () => {
    /* The whole reason the colour skips the finaliser. A Pip must be the
       colour its own node's medallion and handoff token already are, and
       `characterIndex` has no finaliser, so neither may this. */
    for (const key of ['tone coach', 'n4 gate', 'agent', 'market research', 'writer']) {
      expect(pipParts(key).colour).toBe(characterIndex(key))
    }
  })

  it('gives two roles one word apart at least one different part', () => {
    const pairs: Array<[string, string]> = [
      ['Analyst', 'Senior Analyst'],
      ['Writer', 'Technical Writer'],
      ['Researcher', 'Senior Researcher'],
      ['Editor', 'Copy Editor'],
      ['Coach', 'Tone Coach'],
      ['Checker', 'Fact Checker'],
      ['Strategist', 'Pricing Strategist'],
    ]
    for (const [left, right] of pairs) {
      const a = pipParts(left)
      const b = pipParts(right)
      const differing = (['body', 'eyes', 'mouth', 'crest', 'colour'] as const).filter(
        (axis) => a[axis] !== b[axis],
      )
      expect(differing.length, `${left} vs ${right}`).toBeGreaterThanOrEqual(1)
    }
  })

  it('separates a family of roles that rhyme - which raw FNV-1a would not', () => {
    /* The measured argument for `mix32`. These three share a suffix on
       purpose; without the finaliser the low bits that `% 4` and `% 6` read
       are a shallow function of the shared tail and they collapse together. */
    const rhyming = ['Tone Coach', 'Life Coach', 'Voice Coach']
    const tuples = new Set(rhyming.map((role) => JSON.stringify(pipParts(role))))
    expect(tuples.size).toBe(rhyming.length)
  })

  it('reaches every one of the declared combinations', () => {
    const seen = new Set<string>()
    for (const key of syntheticKeys(300_000)) {
      const p = pipParts(key)
      seen.add(`${p.body}.${p.eyes}.${p.mouth}.${p.crest}.${p.colour}`)
      if (seen.size === PIP_COMBINATIONS) break
    }
    expect(PIP_COMBINATIONS).toBe(BODY_COUNT * EYE_COUNT * MOUTH_COUNT * CREST_COUNT * PIP_COLOURS)
    expect(seen.size).toBe(PIP_COMBINATIONS)
  })

  it('spreads every axis close to uniform over 50,000 keys', () => {
    const axes = { body: BODY_COUNT, eyes: EYE_COUNT, mouth: MOUTH_COUNT, crest: CREST_COUNT } as const
    const counts: Record<string, number[]> = {
      body: Array(BODY_COUNT).fill(0),
      eyes: Array(EYE_COUNT).fill(0),
      mouth: Array(MOUTH_COUNT).fill(0),
      crest: Array(CREST_COUNT).fill(0),
      colour: Array(PIP_COLOURS).fill(0),
    }
    const keys = syntheticKeys(50_000)
    for (const key of keys) {
      const p = pipParts(key)
      counts.body[p.body] += 1
      counts.eyes[p.eyes] += 1
      counts.mouth[p.mouth] += 1
      counts.crest[p.crest] += 1
      counts.colour[p.colour - 1] += 1
    }
    /* +/- 15% of the expected share on every bucket. Loose on purpose: this
       asserts "no bucket is starved or hogging", which is the property the
       cast needs, and not a distributional claim a hash of this size could
       not honestly make. `% 3` and `% 6` over a byte carry a bias under 0.4%
       by construction. */
    for (const [axis, size] of Object.entries({ ...axes, colour: PIP_COLOURS })) {
      const expected = keys.length / size
      for (const count of counts[axis]) {
        expect(count, `${axis} bucket`).toBeGreaterThan(expected * 0.85)
        expect(count, `${axis} bucket`).toBeLessThan(expected * 1.15)
      }
    }
  })

  it('is 32-bit and unsigned, so nothing downstream sees a negative index', () => {
    for (const key of syntheticKeys(2_000)) {
      const raw = fnv1a(key)
      expect(Number.isInteger(raw)).toBe(true)
      expect(raw).toBeGreaterThanOrEqual(0)
      expect(raw).toBeLessThanOrEqual(0xffffffff)
    }
  })
})

describe('the geometry', () => {
  /**
   * The minimum y any drawn point of one crest reaches, in its own units,
   * with half its stroke width added.
   *
   * Bezier control points are used verbatim, which OVERSTATES the reach - a
   * curve stays inside the hull of its controls - so this check is stricter
   * than the picture. That is the right direction to be wrong in.
   */
  function crestTopReach(markup: string, halfStroke = 0.85): number {
    let top = Infinity
    const tagRe = /<(path|circle|ellipse)\b([^>]*)>/g
    let match: RegExpExecArray | null
    while ((match = tagRe.exec(markup)) !== null) {
      const [, tag, attrs] = match
      const pad = /pip-stroke/.test(attrs) ? halfStroke : 0
      if (tag === 'path') {
        const d = /d="([^"]+)"/.exec(attrs)?.[1] ?? ''
        const numbers = (d.match(/-?\d*\.?\d+/g) ?? []).map(Number)
        for (let index = 1; index < numbers.length; index += 2) {
          top = Math.min(top, numbers[index] - pad)
        }
      } else {
        const attr = (name: string): number => {
          const hit = new RegExp(`${name}="(-?\\d*\\.?\\d+)"`).exec(attrs)
          return hit ? Number(hit[1]) : 0
        }
        top = Math.min(top, attr('cy') - (tag === 'circle' ? attr('r') : attr('ry')) - pad)
      }
    }
    return top
  }

  it('keeps every body x crest pair inside the 32-unit viewBox, at BOTH size tiers', () => {
    /* The 32px raster found four pairs poking out of the top of the box - the
       bean wearing a ring was worst, at -0.72 units - and `.pip-svg` sets
       `overflow: visible`, so in the DOM they spilled out of the figure's own
       box instead of being cut. On a 32px node slot that is the same defect
       in a different coat.

       BOTH TIERS, because the small tier grows the crown 1.3x, which is
       exactly the change most likely to reintroduce the defect. Its 2-unit
       drop is what buys the headroom back, and the two numbers only mean
       anything together. The stroke allowance differs per tier too: the crown
       is drawn at 1.7 normally and at 2 under `.pip--sm`. */
    const tiers = [
      { label: 'large', boost: 1, lift: 0, stroke: 1.7 },
      { label: 'small', boost: SMALL_CREST_SCALE, lift: SMALL_LIFT, stroke: 2 },
    ]
    for (const tier of tiers) {
      for (const body of BODIES) {
        const scale = body.crestScale * tier.boost
        for (let crest = 0; crest < CREST_COUNT; crest += 1) {
          const reach = crestTopReach(crestShape(crest), tier.stroke / 2)
          const top = body.crownY + scale * reach + tier.lift
          expect(top, `${tier.label}: ${body.id} + ${CREST_NAMES[crest]}`).toBeGreaterThan(0.25)
        }
      }
      /* And the floor must stay in the box too - the drop is only free while
         there is space under the feet. */
      expect(28 + tier.lift, `${tier.label} floor`).toBeLessThanOrEqual(32)
    }
  })

  it('grows the crown below 48px, and only below 48px', () => {
    const big = pipSvg('Tone Coach', { size: 96 })
    const small = pipSvg('Tone Coach', { size: 32 })
    const scaleOf = (markup: string): number =>
      Number(/scale\((-?\d*\.?\d+)\)/.exec(markup)?.[1] ?? 0)
    expect(scaleOf(small) / scaleOf(big)).toBeCloseTo(SMALL_CREST_SCALE, 5)
    expect(small).toContain(`translate(0 ${SMALL_LIFT})`)
    expect(big).toContain('translate(0 0)')
    /* The boost rides the SVG transform attribute and the lift rides a group
       with no CSS transform of its own, because `.pip-crest-hinge` already
       owns `transform` for the blocked wilt and `.pip-figure` owns it for the
       pose. Put either in CSS and the state would silently drop it. */
    expect(CHARACTER_CSS).not.toMatch(/\.pip--sm[^{]*\.pip-crest-hinge\s*\{[^}]*transform:/)
    expect(CHARACTER_CSS).not.toMatch(/\.pip-frame\s*\{[^}]*transform:/)
  })

  it('keeps the four eye shapes measurably different at the size they are read', () => {
    /* The cold reader's second finding was that two same-coloured agents were
       hard to separate at a true 32px, which put the question to the eyes as
       well as to the crown. Measured on the emitted markup rather than judged:
       the four variants differ in shape AND in width, so `lens` cannot quietly
       become `oval` after an edit. The raster sheet is what confirms it to a
       human; this is what fails the build. */
    const widths = new Set<number>()
    const shapes = new Set<string>()
    for (let variant = 0; variant < EYE_COUNT; variant += 1) {
      const markup = eyeShape(variant, 16, 16)
      shapes.add(markup.replace(/[-\d.]+/g, ''))
      const numbers = (markup.match(/-?\d*\.?\d+/g) ?? []).map(Number)
      widths.add(Math.max(...numbers) - Math.min(...numbers))
    }
    expect(shapes.size, 'four eye variants, four different constructions').toBe(EYE_COUNT)
    expect(widths.size, 'four eye variants, four different widths').toBeGreaterThanOrEqual(3)
    /* `lens` is the only one with a hole, and the hole is what carries it at
       32px. Its inner radius must stay a real fraction of the outer one. */
    const lens = eyeShape(3, 16, 16)
    expect(lens).toContain('fill-rule="evenodd"')
    expect(lens).toMatch(/1\.35 1\.35/)
  })

  it('stands every body on the same floor, so a row of Pips lines up', () => {
    for (const body of BODIES) {
      const numbers = (body.d.match(/-?\d*\.?\d+/g) ?? []).map(Number)
      const ys = numbers.filter((_, index) => index % 2 === 1)
      expect(Math.max(...ys), body.id).toBeGreaterThanOrEqual(26.5)
      expect(Math.max(...ys), body.id).toBeLessThanOrEqual(32)
      expect(Math.min(...ys), body.id).toBeGreaterThan(0)
    }
  })

  it('keeps both eyes fully inside every body it can land on', () => {
    /* The defect the raster caught first: an eye pair 12.8 units across in a
       body 15 units wide read at 32px as a damaged blob with its eyes cut
       into the outline. */
    for (const body of BODIES) {
      const outerEdge = 16 + body.eyeDx + 3.2
      expect(outerEdge, body.id).toBeLessThan(28)
      expect(32 - outerEdge, body.id).toBeGreaterThan(4)
    }
  })
})

describe('the markup', () => {
  it('never lets the identity string reach the output', () => {
    const hostile = '<script>alert(1)</script>'
    const markup = pipSvg(hostile, { size: 32 })
    expect(markup).not.toContain('<script')
    expect(markup).not.toContain('alert')
    expect(markup).not.toContain('&lt;script')
    /* Not "it was escaped" - it is not there at all. The identity is consumed
       by the hash and every character of the result comes from a literal in
       `pip.ts`. That is what makes `v-html` safe by construction. */
    expect(markup).toBe(pipSvg(characterSeed(hostile), { size: 32 }))
  })

  it('gives every state its own class and its own picture', () => {
    const markups = PIP_STATES.map((state) => pipSvg('Tone Coach', { size: 32, state }))
    expect(new Set(markups).size).toBe(PIP_STATES.length)
    for (const [index, state] of PIP_STATES.entries()) {
      expect(markups[index]).toContain(`pip--${state}`)
    }
  })

  it('carries all three eye layers, so a state is a class and never a re-render', () => {
    const markup = pipSvg('Tone Coach', { size: 32, state: 'idle' })
    expect(markup).toContain('pip-eyes-open')
    expect(markup).toContain('pip-eyes-arc')
    expect(markup).toContain('pip-eyes-cross')
  })

  it('names every state in words, never a code', () => {
    for (const state of PIP_STATES) {
      const word = pipStateWord(state)
      expect(word).not.toMatch(/[A-Z_]{2,}/)
      expect(word.length).toBeGreaterThan(3)
    }
    expect(new Set(PIP_STATES.map(pipStateWord)).size).toBe(PIP_STATES.length)
  })

  it('drops to the small tier below 48px and keeps the detail above it', () => {
    expect(pipSvg('Tone Coach', { size: 32 })).toContain('pip--sm')
    expect(pipSvg('Tone Coach', { size: 47 })).toContain('pip--sm')
    expect(pipSvg('Tone Coach', { size: 48 })).not.toContain('pip--sm')
    expect(pipSvg('Tone Coach', { size: 32 })).not.toContain('pip-detail')
    expect(pipSvg('Tone Coach', { size: 96 })).toContain('pip-detail')
    /* And the caller may override it in either direction. */
    expect(pipSvg('Tone Coach', { size: 32, detail: true })).toContain('pip-detail')
    expect(pipSvg('Tone Coach', { size: 96, detail: false })).not.toContain('pip-detail')
  })

  it('shows four marks: body, eye, eye, mouth - and hides the rest', () => {
    const markup = pipSvg('Tone Coach', { size: 32, state: 'working' })
    /* All five mouths and both eye layers are in the markup; CSS shows one of
       each. The count that matters is what is DISPLAYED, and that is asserted
       by the stylesheet rules below rather than by counting tags here. */
    expect((markup.match(/class="pip-mouth pip-mouth--/g) ?? []).length).toBe(5)
    expect(markup).toContain('pip-eyes-open')
    expect(markup).toContain('pip-eyes-arc')
  })

  it('carries the size it was asked for and nothing else', () => {
    const markup = pipSvg('Tone Coach', { size: 64 })
    expect(markup).toContain('width="64" height="64"')
    expect(markup).toContain('viewBox="0 0 32 32"')
  })

  it('hides the figure from the accessibility tree, because the wrapper names it', () => {
    const markup = pipSvg('Tone Coach', { size: 32 })
    expect(markup).toContain('aria-hidden="true"')
    expect(markup).toContain('focusable="false"')
    expect(markup).not.toContain('aria-label')
  })

  it('labels its parts the way the component publishes them', () => {
    const parts = pipParts('Tone Coach')
    expect(pipPartsLabel('Tone Coach')).toBe(
      `${BODY_NAMES[parts.body]}/${EYE_NAMES[parts.eyes]}/${MOUTH_NAMES[parts.mouth]}/${CREST_NAMES[parts.crest]}/c${parts.colour}`,
    )
    expect(pipPartsLabel('  TONE COACH ')).toBe(pipPartsLabel('Tone Coach'))
  })
})

describe('character.css', () => {
  it('introduces no colour of its own', () => {
    const declarations = CHARACTER_CSS.replace(/\/\*[\s\S]*?\*\//g, '')
    expect(declarations).not.toMatch(/#[0-9a-f]{3,8}\b/i)
    expect(declarations).not.toMatch(/\b(rgba?|hsla?|color-mix|oklch)\s*\(/i)
  })

  it('puts every animation it declares into the reduced-motion block', () => {
    /* Asserted by parsing the sheet rather than by keeping a list in a
       comment, because a list in a comment is exactly the thing that goes
       stale the first time somebody adds a keyframe. */
    const reduceAt = CHARACTER_CSS.indexOf('@media (prefers-reduced-motion: reduce)')
    expect(reduceAt).toBeGreaterThan(0)
    const before = CHARACTER_CSS.slice(0, reduceAt)
    const reduceBlock = CHARACTER_CSS.slice(reduceAt)

    const animated = new Set<string>()
    const ruleRe = /([^{}]+)\{([^}]*)\}/g
    let rule: RegExpExecArray | null
    while ((rule = ruleRe.exec(before)) !== null) {
      const [, selector, body] = rule
      if (!/\banimation\s*:/.test(body)) continue
      if (/animation\s*:\s*none/.test(body)) continue
      for (const one of selector.split(',')) {
        const leaf = one.trim().split(/\s+/).pop() ?? ''
        if (leaf.startsWith('.')) animated.add(leaf)
      }
    }
    expect(animated.size).toBeGreaterThan(0)
    expect(reduceBlock).toMatch(/animation:\s*none/)
    for (const leaf of animated) {
      expect(reduceBlock, `${leaf} is animated and not cancelled under reduced motion`).toContain(
        leaf,
      )
    }
  })

  it('pauses rather than clears an offscreen animation', () => {
    expect(CHARACTER_CSS).toMatch(/\.pip--paused[^{]*\{[^}]*animation-play-state:\s*paused/)
  })

  it('gives every state a rule', () => {
    for (const state of PIP_STATES) expect(CHARACTER_CSS).toContain(`.pip--${state} `)
  })

  it('never lets colour be the only thing separating two states', () => {
    /* THE COLD READER'S FIRST FINDING, turned into a check. `blocked` and
       `blocked-error` shared a pose and differed only in the hue of the
       outline, so a colour-blind viewer saw one state where the product means
       two. The general rule is that colour must never be the sole carrier of a
       distinction, and this asserts it structurally: whatever `blocked-error`
       does that `blocked` does not must include at least one property that is
       not a colour. */
    const COLOUR_PROPERTIES = ['stroke', 'fill', 'color', 'background', 'border-color']

    function declarationsFor(state: string): Set<string> {
      /* `.pip--blocked` must not match `.pip--blocked-error`, so the class
         token needs a boundary. */
      const token = new RegExp(`\\.pip--${state}(?![\\w-])`)
      const found = new Set<string>()
      const ruleRe = /([^{}]+)\{([^}]*)\}/g
      let rule: RegExpExecArray | null
      while ((rule = ruleRe.exec(CHARACTER_CSS)) !== null) {
        const [, selectorList, body] = rule
        for (const selector of selectorList.split(',')) {
          if (!token.test(selector)) continue
          const target = selector.trim().split(/\s+/).slice(1).join(' ') || ':self'
          for (const declaration of body.split(';')) {
            const property = declaration.split(':')[0]?.trim()
            if (property) found.add(`${target} { ${property} }`)
          }
        }
      }
      return found
    }

    const blocked = declarationsFor('blocked')
    const error = declarationsFor('blocked-error')
    expect(blocked.size).toBeGreaterThan(0)

    const onlyError = [...error].filter((entry) => !blocked.has(entry))
    expect(onlyError.length, 'blocked-error does nothing blocked does not').toBeGreaterThan(0)

    const nonColour = onlyError.filter(
      (entry) => !COLOUR_PROPERTIES.some((property) => entry.endsWith(`{ ${property} }`)),
    )
    expect(
      nonColour,
      `blocked-error differs from blocked only by colour: ${onlyError.join(', ')}`,
    ).not.toHaveLength(0)

    /* And name the shape cue, so a future edit that removes it fails with a
       sentence rather than with an arithmetic surprise. */
    expect(error).toContain('.pip-eyes-cross { display }')
    expect(error).toContain('.pip-eyes-open { display }')
    expect(blocked).not.toContain('.pip-eyes-cross { display }')
  })

  it('thickens the crown and the crosses at the small tier only', () => {
    expect(CHARACTER_CSS).toMatch(/\.pip--sm \.pip-crest-hinge \.pip-stroke\s*\{[^}]*stroke-width/)
    expect(CHARACTER_CSS).toMatch(/\.pip--sm \.pip-eyes-cross \.pip-stroke\s*\{[^}]*stroke-width/)
  })
})

describe('AgentCharacter', () => {
  function mountPip(props: Record<string, unknown>) {
    return mount(AgentCharacter, { props: { identity: 'Tone Coach', ...props } })
  }

  it('publishes the seed, the state and the parts on its root', () => {
    const wrapper = mountPip({ state: 'working', size: 32 })
    expect(wrapper.attributes('data-character')).toBe('tone coach')
    expect(wrapper.attributes('data-state')).toBe('working')
    expect(wrapper.attributes('data-parts')).toBe(pipPartsLabel('Tone Coach'))
    expect(wrapper.classes()).toContain('pip')
    expect(wrapper.classes()).toContain('pip--working')
    expect(wrapper.classes()).toContain('pip--sm')
  })

  it('drops the small class above the detail threshold', () => {
    expect(mountPip({ size: 96 }).classes()).not.toContain('pip--sm')
  })

  it('is an image with a spoken name that ends in the state, in words', () => {
    const wrapper = mountPip({ state: 'blocked' })
    expect(wrapper.attributes('role')).toBe('img')
    expect(wrapper.attributes('aria-label')).toBe('Tone Coach, blocked, needs you')
  })

  it('prefers an explicit label over the raw identity', () => {
    const wrapper = mountPip({ identity: 'n4_second_pass', label: 'Second pass', state: 'done' })
    expect(wrapper.attributes('aria-label')).toBe('Second pass, finished')
    expect(wrapper.attributes('data-character')).toBe('n4 second pass')
  })

  it('renders the generated figure inline, with no script surviving a hostile identity', () => {
    const wrapper = mountPip({ identity: '<script>alert(1)</script>' })
    /* `v-html` is the only place markup is parsed, and the identity is not in
       it: the figure is assembled from literals and the seed is 'script alert
       1 script'. So there is no element to find and nothing was executed. */
    expect(wrapper.element.querySelector('script')).toBeNull()
    expect(wrapper.find('svg').exists()).toBe(true)
    expect(wrapper.find('svg').html()).not.toContain('alert')
    expect(wrapper.attributes('data-character')).toBe('script alert 1 script')
    /* The label DOES carry the caller's string, and that is correct: it is an
       attribute value written through the DOM by Vue, never parsed as markup.
       An HTML serialiser does not escape `<` inside a quoted attribute value
       because it does not have to, so `wrapper.html()` shows the angle
       brackets - which is what makes a naive "the HTML must not contain
       <script" assertion here a false alarm rather than a finding. */
    expect(wrapper.attributes('aria-label')).toBe('<script>alert(1)</script>, waiting to start')
  })

  it('re-draws when the state changes and keeps the same character', async () => {
    const wrapper = mountPip({ state: 'idle' })
    const seed = wrapper.attributes('data-character')
    const parts = wrapper.attributes('data-parts')
    await wrapper.setProps({ state: 'speaking' })
    expect(wrapper.attributes('data-state')).toBe('speaking')
    expect(wrapper.attributes('data-character')).toBe(seed)
    expect(wrapper.attributes('data-parts')).toBe(parts)
    expect(wrapper.classes()).toContain('pip--speaking')
    expect(wrapper.classes()).not.toContain('pip--idle')
  })

  it('mounts where there is no IntersectionObserver, and is not paused there', () => {
    /* jsdom has none. The pause is an enhancement, so its absence must be a
       character that animates rather than a suite that throws. */
    expect(typeof IntersectionObserver).toBe('undefined')
    expect(mountPip({}).classes()).not.toContain('pip--paused')
  })

  it('observes while mounted, pauses offscreen, and disconnects on unmount', async () => {
    const observe = vi.fn()
    const disconnect = vi.fn()
    /*
     * Entries carry a `target`, because the real ones do and because the
     * component now routes by it: ONE `IntersectionObserver` serves every
     * character on the page rather than one per character. A long run mounts a
     * character on every graph node, every trace row and every spoken line -
     * hundreds - and a scroll of the trace used to wake hundreds of observers
     * with a single entry apiece. The observer is reference-counted, so the
     * last character to unmount still disconnects it, which is what the name of
     * this test claims and what the assertion below checks.
     */
    type Entries = Array<{ isIntersecting: boolean; target: Element }>
    /* A holder object rather than a `let`: TypeScript's control-flow analysis
       cannot see that the constructor below runs, so a plain binding stays
       narrowed to `null` and calling it is a compile error. */
    const captured: { notify: ((entries: Entries) => void) | null } = { notify: null }
    let constructed = 0
    class FakeObserver {
      constructor(callback: (entries: Entries) => void) {
        constructed += 1
        captured.notify = callback
      }
      observe = observe
      unobserve = vi.fn()
      disconnect = disconnect
      takeRecords = vi.fn()
      root = null
      rootMargin = ''
      thresholds: number[] = []
    }
    vi.stubGlobal('IntersectionObserver', FakeObserver)
    try {
      const wrapper = mountPip({ state: 'working' })
      expect(observe).toHaveBeenCalledTimes(1)
      expect(observe.mock.calls[0][0]).toBe(wrapper.element)

      captured.notify?.([{ isIntersecting: false, target: wrapper.element }])
      await wrapper.vm.$nextTick()
      expect(wrapper.classes()).toContain('pip--paused')

      captured.notify?.([{ isIntersecting: true, target: wrapper.element }])
      await wrapper.vm.$nextTick()
      expect(wrapper.classes()).not.toContain('pip--paused')

      // A second character joins the SAME observer rather than building one.
      const second = mountPip({ identity: 'Second Agent' })
      expect(constructed).toBe(1)
      expect(observe).toHaveBeenCalledTimes(2)

      // And a notification about one does not touch the other.
      captured.notify?.([{ isIntersecting: false, target: second.element }])
      await second.vm.$nextTick()
      expect(second.classes()).toContain('pip--paused')
      expect(wrapper.classes()).not.toContain('pip--paused')

      // The observer outlives the first unmount and dies with the last.
      wrapper.unmount()
      expect(disconnect).toHaveBeenCalledTimes(0)
      second.unmount()
      expect(disconnect).toHaveBeenCalledTimes(1)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('never renders a raw identity code as a visible label', () => {
    const wrapper = mountPip({ identity: 'MARKET_RESEARCH_NODE' })
    expect(wrapper.text()).toBe('')
    expect(wrapper.attributes('data-character')).toBe('market research node')
  })
})

describe('the state vocabulary is the component contract, and nothing more', () => {
  it('exposes exactly six states', () => {
    const declared: PipState[] = ['idle', 'working', 'speaking', 'blocked', 'blocked-error', 'done']
    expect([...PIP_STATES]).toEqual(declared)
  })

  it('normalises a state-shaped identity without confusing it for a state', () => {
    expect(normaliseIdentity('Blocked-Error')).toBe('blocked error')
    expect(pipParts('blocked error')).not.toEqual(pipParts('blocked'))
  })
})
