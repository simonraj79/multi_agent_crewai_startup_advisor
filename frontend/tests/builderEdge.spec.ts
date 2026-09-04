import { readFileSync } from 'node:fs'
import path from 'node:path'
import { mount } from '@vue/test-utils'
import { beforeAll, describe, expect, it } from 'vitest'
import BuilderEdge, { type BuilderEdgeData } from '../src/components/builder/BuilderEdge.vue'
import { edgeClassOf } from '../src/composables/useBuilderCanvas'
import type { EdgeClass } from '../src/composables/useBuilderCanvas'
import { NODE_KINDS } from '../src/data/nodeKinds'
import { edgeId, nodeId } from '../src/types/builder'
import type { TargetPort } from '../src/types/builder'

/**
 * One edge per class, and the four are mutually exclusive by construction.
 *
 * 02-canvas.md D4 gives the design-time edge four looks and criterion 5 asks
 * for exactly one `is-class-*` on every element. Two things are being pinned,
 * and they are different questions that a single test would blur:
 *
 *   1. WHICH class an edge is. That is `edgeClassOf`, and it reads two strings
 *      off the edge - `target_port`, plus `source_port` for the error exit -
 *      and never looks up what kind the source node happened to be. The whole
 *      point of the rule is that `bounds.py` decides the same question from the
 *      same two fields, so there is one string for the two sides to agree about
 *      rather than a table of ten kinds maintained twice.
 *   2. WHAT that class looks like. That is `builder.css`, and it is read here
 *      out of the real file rather than transcribed - a transcription would
 *      only prove that two copies of one mistake agree, which is the failure
 *      `nodeKinds.ts` writes its own docblock against.
 *
 * The marker half is asserted on the RENDER, because whether an arrowhead
 * exists is a fact about the SVG and not about a stylesheet: an arrow means
 * "and then this happens", and an attachment is a possession rather than a next
 * step, so pointing one at it would say the run goes there.
 */

/* --- the stylesheet, read rather than restated ---------------------------- */

let RULES: CSSStyleRule[] = []

beforeAll(() => {
  const css = readFileSync(path.resolve(process.cwd(), 'src/assets/styles/builder.css'), 'utf8')
  const style = document.createElement('style')
  style.textContent = css
  document.head.appendChild(style)
  RULES = Array.from((style.sheet as CSSStyleSheet).cssRules).filter(
    (rule): rule is CSSStyleRule => rule instanceof CSSStyleRule,
  )
})

/**
 * A selector with its runs of whitespace collapsed.
 *
 * `builder.css` pads several selectors so their declarations line up in a
 * column, and the CSSOM hands the padding straight back - so
 * `.builder-edge.has-error   .builder-edge-path` is three spaces different from
 * the same selector written normally, and a string comparison reports the
 * formatting rather than the rule.
 */
function normalise(selector: string): string {
  return selector.replace(/\s+/g, ' ').trim()
}

/** The declarations of one selector, exactly as `builder.css` writes them. */
function ruleFor(selector: string): CSSStyleDeclaration {
  const rule = RULES.find((entry) => normalise(entry.selectorText) === normalise(selector))
  expect(rule, 'builder.css has no rule for ' + selector).toBeDefined()
  return (rule as CSSStyleRule).style
}

/* --- fixtures ------------------------------------------------------------- */

type EdgeOverrides = Partial<BuilderEdgeData> & {
  source_port?: string
  target_port?: TargetPort
}

function edgeData(overrides: EdgeOverrides = {}): BuilderEdgeData {
  const sourcePort = overrides.source_port ?? 'out'
  const targetPort = overrides.target_port ?? 'in'
  const edge = {
    id: edgeId('e1'),
    source: nodeId('scoper'),
    source_port: sourcePort,
    target: nodeId('writer'),
    target_port: targetPort,
  }
  return {
    edge,
    problems: [],
    severity: null,
    backEdge: false,
    portLabel: null,
    portRole: null,
    joinTarget: false,
    edgeClass: edgeClassOf(edge),
    sourceAccent: NODE_KINDS.agent.accent,
    targetAccent: NODE_KINDS.output.accent,
    ...overrides,
  }
}

function mountEdge(data: BuilderEdgeData) {
  return mount(BuilderEdge, {
    props: {
      id: 'e1',
      source: 'scoper',
      target: 'writer',
      sourceX: 0,
      sourceY: 0,
      targetX: 120,
      targetY: 220,
      sourcePosition: 'bottom',
      targetPosition: 'top',
      data,
      selected: false,
    } as never,
  })
}

/* --- which class ---------------------------------------------------------- */

describe('an edge is classed by its own two port fields and by nothing else', () => {
  it('reads `in` as flow, `attach` as attach and `member` as member', () => {
    expect(edgeClassOf({ source_port: 'out', target_port: 'in' })).toBe('flow')
    expect(edgeClassOf({ source_port: 'attach', target_port: 'attach' })).toBe('attach')
    expect(edgeClassOf({ source_port: 'out', target_port: 'member' })).toBe('member')
  })

  it('reads a departure by the `error` port as the error class', () => {
    expect(edgeClassOf({ source_port: 'error', target_port: 'in' })).toBe('error')
  })

  it('lets the target port outrank the source port, because arrival decides', () => {
    // Not a shape the schema can produce - an attachment has no `error` port -
    // but the ORDER is the contract: three of the four classes are decided by
    // where the edge ARRIVES, and `error` is the one exception, not a rival
    // rule that can win against `attach`.
    expect(edgeClassOf({ source_port: 'error', target_port: 'attach' })).toBe('attach')
  })

  it('never returns two classes, because it returns one string', () => {
    const seen = new Set<EdgeClass>()
    for (const sourcePort of ['out', 'approve', 'error', 'attach']) {
      for (const targetPort of ['in', 'attach', 'member'] as TargetPort[]) {
        seen.add(edgeClassOf({ source_port: sourcePort, target_port: targetPort }))
      }
    }
    expect([...seen].sort()).toEqual(['attach', 'error', 'flow', 'member'])
  })
})

/* --- exactly one `is-class-*` on the element ------------------------------ */

describe('every edge element carries exactly one is-class-*', () => {
  const cases: Array<[EdgeClass, EdgeOverrides]> = [
    ['flow', {}],
    ['attach', { source_port: 'attach', target_port: 'attach' }],
    ['member', { target_port: 'member' }],
    ['error', { source_port: 'error' }],
  ]

  for (const [expected, overrides] of cases) {
    it('draws a ' + expected + ' edge as is-class-' + expected + ' and nothing else', () => {
      const wrapper = mountEdge(edgeData(overrides))
      const classes = wrapper
        .find('g.builder-edge')
        .classes()
        .filter((name) => name.startsWith('is-class-'))
      expect(classes).toEqual(['is-class-' + expected])
    })
  }
})

/* --- the D4 table, stroke by stroke --------------------------------------- */

describe('each class takes the stroke D4 gives it, read out of builder.css', () => {
  it('paints a flow edge with the per-edge gradient at the flow weight', () => {
    const style = ruleFor('.builder-edge.is-class-flow .builder-edge-path')
    // `--edge-paint` is published by the edge as `url(#edge-gradient-<id>)`; a
    // CSS file cannot write a per-element id, and an inline `stroke` would
    // outrank `has-error`, `is-lit-in` and `is-selected`.
    expect(style.stroke).toBe('var(--edge-paint, var(--edge-inactive))')
    expect(style.strokeWidth).toBe('var(--edge-width-flow)')
  })

  it('paints an attach edge violet, thin and finely dashed', () => {
    const style = ruleFor('.builder-edge.is-class-attach .builder-edge-path')
    expect(style.stroke).toBe('var(--accent-attach)')
    expect(style.strokeWidth).toBe('var(--edge-width-attach)')
    expect(style.strokeDasharray).toBe('2 3')
  })

  it('paints a member edge mint, thin, and on a longer dash than attach', () => {
    const style = ruleFor('.builder-edge.is-class-member .builder-edge-path')
    expect(style.stroke).toBe('var(--accent-mint)')
    expect(style.strokeWidth).toBe('var(--edge-width-attach)')
    expect(style.strokeDasharray).toBe('6 3')
  })

  it('paints an error edge red at the flow weight, because it is a flow', () => {
    const style = ruleFor('.builder-edge.is-class-error .builder-edge-path')
    expect(style.stroke).toBe('var(--err-text)')
    expect(style.strokeWidth).toBe('var(--edge-width-flow)')
  })

  it('adds a dash to a back edge and takes no colour away from it', () => {
    // Until 2026-09-04 this rule also forced `--link-cyan`, which overpainted
    // the gradient on exactly the edges whose direction is hardest to follow.
    const style = ruleFor('.builder-edge.is-back-edge .builder-edge-path')
    expect(style.strokeDasharray).toBe('5 4')
    expect(style.stroke).toBe('')
  })

  it('declares the class rules BEFORE the state rules, because both are (0,2,1)', () => {
    // Same specificity, so source order is the whole of the cascade here: a
    // problem, a hover or a selection has to be able to repaint a wire whatever
    // class it carries.
    const order = RULES.map((rule) => normalise(rule.selectorText))
    const lastClass = Math.max(
      ...['flow', 'attach', 'member', 'error'].map((name) =>
        order.indexOf('.builder-edge.is-class-' + name + ' .builder-edge-path'),
      ),
    )
    expect(lastClass).toBeGreaterThan(-1)
    for (const later of [
      '.builder-edge.has-warning .builder-edge-path',
      '.builder-edge.has-error .builder-edge-path',
      '.builder-edge.is-lit-in .builder-edge-path',
      '.builder-edge.is-lit-out .builder-edge-path',
    ]) {
      expect(order.indexOf(later), later).toBeGreaterThan(lastClass)
    }
  })
})

/* --- the gradient and the marker ------------------------------------------ */

describe('a flow edge is a gradient from the source kind to the target kind', () => {
  it('mints one linearGradient whose stops are the two kind accents', () => {
    const wrapper = mountEdge(
      edgeData({ sourceAccent: NODE_KINDS.gate.accent, targetAccent: NODE_KINDS.crew.accent }),
    )
    const stops = wrapper.findAll('linearGradient stop')
    expect(stops).toHaveLength(2)
    expect(stops[0].attributes('stop-color')).toBe(NODE_KINDS.gate.accent)
    expect(stops[1].attributes('stop-color')).toBe(NODE_KINDS.crew.accent)
  })

  it('runs the ramp along the real endpoints, not the bounding box', () => {
    // In the default `objectBoundingBox` units a wire running right-to-left has
    // its colours reversed, and says the opposite of what it means.
    const gradient = mountEdge(edgeData()).find('linearGradient')
    expect(gradient.attributes('id')).toBe('edge-gradient-e1')
    expect(gradient.attributes('gradientunits')).toBe('userSpaceOnUse')
    expect(gradient.attributes('x1')).toBe('0')
    expect(gradient.attributes('y1')).toBe('0')
    expect(gradient.attributes('x2')).toBe('120')
    expect(gradient.attributes('y2')).toBe('220')
  })

  it('publishes the gradient as --edge-paint so the cascade still decides', () => {
    const group = mountEdge(edgeData()).find('g.builder-edge')
    expect(group.attributes('style')).toContain('--edge-paint: url(#edge-gradient-e1)')
  })

  it('mints no gradient at all for the three flat classes', () => {
    const flat: EdgeOverrides[] = [
      { source_port: 'attach', target_port: 'attach' },
      { target_port: 'member' },
      { source_port: 'error' },
    ]
    for (const overrides of flat) {
      const wrapper = mountEdge(edgeData(overrides))
      expect(wrapper.findAll('linearGradient')).toHaveLength(0)
      expect(wrapper.find('g.builder-edge').attributes('style') ?? '').not.toContain('--edge-paint')
    }
  })
})

describe('an arrowhead means "and then this happens", so only two classes get one', () => {
  it('gives a flow edge a marker and points the path at it', () => {
    const wrapper = mountEdge(edgeData())
    expect(wrapper.findAll('marker')).toHaveLength(1)
    expect(wrapper.find('marker').attributes('id')).toBe('edge-arrow-e1')
    expect(wrapper.find('path.builder-edge-path').attributes('marker-end')).toBe(
      'url(#edge-arrow-e1)',
    )
  })

  it('tints a flow arrowhead with the TARGET accent, where the arrow actually is', () => {
    const wrapper = mountEdge(edgeData({ targetAccent: NODE_KINDS.output.accent }))
    expect(wrapper.find('marker path').attributes('fill')).toBe(NODE_KINDS.output.accent)
  })

  it('gives an error edge a red arrowhead', () => {
    const wrapper = mountEdge(edgeData({ source_port: 'error' }))
    expect(wrapper.findAll('marker')).toHaveLength(1)
    expect(wrapper.find('marker path').attributes('fill')).toBe('var(--err-text)')
  })

  it('gives an attach edge and a member edge no marker at all', () => {
    const structural: EdgeOverrides[] = [
      { source_port: 'attach', target_port: 'attach' },
      { target_port: 'member' },
    ]
    for (const overrides of structural) {
      const wrapper = mountEdge(edgeData(overrides))
      expect(wrapper.findAll('marker')).toHaveLength(0)
      expect(wrapper.find('path.builder-edge-path').attributes('marker-end')).toBeUndefined()
    }
  })
})

/* --- the hover-only delete ------------------------------------------------ */

describe('the delete affordance is hover-only in CSS and always in the DOM', () => {
  it('emits the edge id rather than acting on the selection', async () => {
    const wrapper = mountEdge(edgeData())
    await wrapper.find('button.builder-edge-delete').trigger('click')
    expect(wrapper.emitted('delete')).toEqual([[{ edgeId: 'e1' }]])
  })

  it('names the edge it deletes, so it is reachable and legible by keyboard', () => {
    const button = mountEdge(edgeData()).find('button.builder-edge-delete')
    expect(button.attributes('aria-label')).toBe('Delete edge e1')
  })

  it('is transparent at rest and shown on hover, selection or focus', () => {
    expect(ruleFor('.builder-edge-delete').opacity).toBe('0')
    const shown = RULES.find(
      (rule) =>
        rule.selectorText.includes('.builder-edge:hover .builder-edge-delete') &&
        rule.style.opacity === '1',
    )
    expect(shown?.selectorText).toContain('.builder-edge.is-selected .builder-edge-delete')
    expect(shown?.selectorText).toContain('.builder-edge-delete:focus-visible')
  })
})
