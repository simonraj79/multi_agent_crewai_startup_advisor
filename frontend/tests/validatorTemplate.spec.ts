import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import fixture from './fixtures/builderValidatorTemplate.json'
import GraphThumbnail from '../src/components/builder/GraphThumbnail.vue'
import {
  BLANK,
  BUILDER_TEMPLATES,
  FAN_OUT_JOIN,
  IDEA_VALIDATOR,
  MINIMAL_GATED_AGENT,
  documentFromTemplate,
} from '../src/data/builderTemplates'
import { IDEA_VALIDATOR_CAVEAT } from '../src/data/templates/ideaValidator'
import { NODE_ID_PATTERN, STATE_REF_PATTERN } from '../src/types/builder'
import { forValidate } from '../src/utils/builderSerialize'
import type { BuilderDocument, BuilderNode } from '../src/types/builder'

/**
 * The evaluator is a template, and the template is not a fiction.
 *
 * This closes the gap a shipped template opens and nothing else can: a document
 * written by hand into a `.ts` file is never parsed by the compiler that will
 * refuse it, so it can look right for months and be a wall of 422s the first
 * time somebody clicks the card. The mission puts this graph on the gallery's
 * flagship card, so "it validates" has to be a measurement rather than a claim.
 *
 * WHAT THE FIXTURE IS. `tests/fixtures/builderValidatorTemplate.json` is the
 * real `POST /api/builder/validate` answer, recorded against a live
 * `SYNTHETIC=1` backend, together with the exact `forValidate()` body it
 * answered and the `/api/builder/vocabulary` payload of that build. The
 * document is compared field by field against what this build produces, so the
 * recorded answer cannot drift away from the document it is offered as proof
 * of: change a prompt input here and this test fails rather than the gallery
 * shipping a graph the server has never seen.
 *
 * EVERY BOUND READS THE FIXTURE'S VOCABULARY, never a constant. `MAX_BILLABLE_NODES`
 * has already moved once - 8 to 13 - and a test asserting `8` would have failed
 * for being right. What is asserted is the RELATION: the template fits inside
 * the bounds the server publishes, with headroom named where the spec asks for
 * it.
 */

const BOUNDS = fixture.vocabulary.bounds
const BUDGET = fixture.validation.budget

/** Every scalar a document carries, flattened - configs, args, prompt inputs. */
function scalars(document: BuilderDocument): string[] {
  const found: string[] = []
  const walk = (value: unknown): void => {
    if (typeof value === 'string') found.push(value)
    else if (Array.isArray(value)) value.forEach(walk)
    else if (value && typeof value === 'object') Object.values(value).forEach(walk)
  }
  document.nodes.forEach((node) => walk(node.config))
  return found
}

describe('the idea validator ships as a document the compiler accepts', () => {
  it('is byte-for-byte the document the recorded answer answered', () => {
    // Deep equality rather than a hash, so a failure names the field that
    // moved instead of two hex strings that differ.
    expect(forValidate(IDEA_VALIDATOR.document)).toEqual(fixture.document)
  })

  it('was answered valid, with no problems at all', () => {
    expect(fixture.validation.valid).toBe(true)
    expect(fixture.validation.problems).toEqual([])
  })

  it('names no crew, because two of the six registered crews cannot be built', () => {
    // `SynthesisCrew(market, sentiment, feasibility)` and
    // `ReportCrew(verdict, tool_urls)` take typed findings a drawn document
    // cannot express, and the flagship template must not be the thing that
    // teaches an author to reach for one.
    const kinds = IDEA_VALIDATOR.document.nodes.map((node) => node.kind)
    expect(kinds).not.toContain('crew')
  })

  it('spends 8 billable nodes of the bound, 5 escalation, over 2 cycles', () => {
    expect(BUDGET.billable_nodes).toBe(8)
    expect(BUDGET.escalation_nodes).toBe(5)
    expect(BUDGET.cycles).toBe(2)
  })

  it('fits inside every bound the server publishes, with headroom', () => {
    expect(BUDGET.billable_nodes).toBeLessThanOrEqual(BOUNDS.max_billable_nodes)
    expect(BUDGET.escalation_nodes).toBeLessThanOrEqual(BOUNDS.max_escalation_nodes)
    expect(BUDGET.cycles).toBeLessThanOrEqual(BOUNDS.max_cycles)
    expect(IDEA_VALIDATOR.document.nodes.length).toBeLessThanOrEqual(BOUNDS.max_graph_nodes)
    // The one bound it sits AT rather than under. §6.4 wants the flagship to
    // fill a pip row, so an author sees a full row before they place the node
    // that would break it.
    const fanOut = new Map<string, number>()
    for (const edge of IDEA_VALIDATOR.document.edges) {
      fanOut.set(edge.source, (fanOut.get(edge.source) ?? 0) + 1)
    }
    expect(Math.max(...fanOut.values())).toBe(BOUNDS.max_fanout_width)
  })

  it('is priced under the run ceiling, and both figures are reported', () => {
    expect(BUDGET.over_ceiling).toBe(false)
    expect(BUDGET.floor_cost_usd).toBeLessThan(BUDGET.static_cost_usd)
    expect(BUDGET.static_cost_usd).toBeLessThan(BOUNDS.run_cost_ceiling_usd)
    expect(BUDGET.unpriced_models).toEqual([])
  })

  it('writes every state reference in the one resolvable shape', () => {
    // A near-miss - `${state.out__scoper.segment}` - is a PARSE refusal, not a
    // problem: it reaches the agent as that literal text with nothing saying
    // the reference did not resolve. The `${` marker catches the near-misses
    // that a positive-only match would step over.
    const referencing = scalars(IDEA_VALIDATOR.document).filter((value) => value.includes('${'))
    expect(referencing.length).toBeGreaterThan(0)
    for (const value of referencing) expect(value).toMatch(STATE_REF_PATTERN)
  })

  it('references only keys some node actually writes', () => {
    const known = new Set<string>([IDEA_VALIDATOR.document.input_field])
    for (const node of IDEA_VALIDATOR.document.nodes) {
      known.add(`out__${node.id}`)
      if (node.kind === 'gate') known.add(`turns__${node.id}`)
    }
    for (const value of scalars(IDEA_VALIDATOR.document).filter((v) => v.includes('${'))) {
      const key = value.slice('${state.'.length, -1)
      expect(known, `${value} names a key nothing writes`).toContain(key)
    }
  })

  it('closes both of its loops through a router, which is the only kind that may', () => {
    const byId = new Map(IDEA_VALIDATOR.document.nodes.map((node) => [node.id as string, node]))
    // Not a cycle detector - the fixture already reports two cycles. This
    // asserts the shape `bounds.py` demands of whatever closes them: a plain
    // listener closing a loop was measured to end the run silently.
    const routerBacks = IDEA_VALIDATOR.document.edges.filter((edge) => {
      const source = byId.get(edge.source)
      return source?.kind === 'router' && edge.target !== edge.source
    })
    expect(routerBacks.length).toBeGreaterThanOrEqual(BUDGET.cycles)
    for (const edge of routerBacks) {
      expect(['gate', 'router']).toContain(byId.get(edge.source)?.kind)
    }
  })

  it('declares exactly one join, on the node that scores three branches', () => {
    expect(IDEA_VALIDATOR.document.joins).toEqual({ score: 'all' })
    const arrivals = IDEA_VALIDATOR.document.edges.filter((edge) => edge.target === 'score')
    // A join over one edge is the same as no join at all, which the server
    // reports as a warning. This one waits for four.
    expect(arrivals.length).toBeGreaterThanOrEqual(2)
  })

  it('carries the caveat verbatim on the card', () => {
    // R14. The template ships BECAUSE it is topology rather than judgement, and
    // saying so is the difference between a starting point and a booby trap.
    expect(IDEA_VALIDATOR.caveat).toBe(IDEA_VALIDATOR_CAVEAT)
    expect(IDEA_VALIDATOR.caveat).toContain('not its judgement')
  })
})

describe('the gallery ships four templates and no half-drawn ones', () => {
  it('offers blank, minimal, fan-out and the validator, in that order', () => {
    expect(BUILDER_TEMPLATES.map((template) => template.id)).toEqual([
      'blank',
      'minimal-gated-agent',
      'fan-out-join',
      'idea-validator',
    ])
  })

  it('gives every template a legal name, input field and node ids', () => {
    for (const template of BUILDER_TEMPLATES) {
      const document = template.document
      expect(document.name.length, template.id).toBeGreaterThan(0)
      expect(document.name.length).toBeLessThanOrEqual(BOUNDS.max_name_chars)
      expect(document.input_field).toMatch(NODE_ID_PATTERN)
      for (const node of document.nodes) {
        expect(node.id, `${template.id}/${node.id}`).toMatch(NODE_ID_PATTERN)
        expect(node.label.length).toBeLessThanOrEqual(BOUNDS.max_label_chars)
        // R12: `Position` declares `int` and pydantic refuses `120.5`, so a
        // fractional coordinate written into a template is a 422 on the first
        // save with nothing on screen to explain it.
        expect(Number.isInteger(node.position.x)).toBe(true)
        expect(Number.isInteger(node.position.y)).toBe(true)
      }
    }
  })

  it('declares an input node for the field each template names', () => {
    // Every template except BLANK, which is deliberately incomplete: a draft
    // need not be valid, and its two problems name the first two things to do.
    for (const template of BUILDER_TEMPLATES.filter((entry) => entry.id !== 'blank')) {
      const inputs = template.document.nodes.filter(
        (node): node is Extract<BuilderNode, { kind: 'input' }> => node.kind === 'input',
      )
      const declaring = inputs.filter((node) => node.config.field === template.document.input_field)
      expect(declaring.length, template.id).toBe(1)
    }
  })

  it('gates every launchable template above its first billable node', () => {
    // The 403 an anonymous launch gets otherwise names this exact condition.
    // BLANK has no billable node to gate, and the validator deliberately scopes
    // first - which is why `PublishDialog` renders that refusal in full.
    for (const template of [MINIMAL_GATED_AGENT, FAN_OUT_JOIN]) {
      const first = template.document.edges.find((edge) => edge.source === 'idea')
      expect(first?.target, template.id).toBe('confirm')
    }
    // BLANK seeds the run's two ENDS and nothing between them (02-canvas.md
    // D7). It has nothing to gate because it has nothing that bills: neither an
    // input nor an output is a step, they are where the request lands and where
    // the body comes back.
    expect(BLANK.document.nodes.map((node) => node.kind)).toEqual(['input', 'output'])
    expect(BLANK.document.edges).toHaveLength(1)
  })

  it('hands out a fresh copy so two sessions cannot share one document', () => {
    const first = documentFromTemplate(MINIMAL_GATED_AGENT)
    const second = documentFromTemplate(MINIMAL_GATED_AGENT)
    expect(first).toEqual(second)
    expect(first).not.toBe(MINIMAL_GATED_AGENT.document)
    expect(first.nodes[0]).not.toBe(second.nodes[0])
  })
})

describe('the thumbnail is derived from the document it advertises', () => {
  it('draws one rect per node and one line per edge', () => {
    const wrapper = mount(GraphThumbnail, {
      props: { document: IDEA_VALIDATOR.document, label: 'Idea validator' },
    })
    expect(wrapper.findAll('rect.thumb-node')).toHaveLength(IDEA_VALIDATOR.document.nodes.length)
    expect(wrapper.findAll('path.thumb-edge')).toHaveLength(IDEA_VALIDATOR.document.edges.length)
  })

  it('places the rects from the document positions, not from array order', () => {
    // The topmost node in the document must be the topmost rect. A layout that
    // ignored `position` would still pass a count assertion and would advertise
    // a graph nobody drew.
    const wrapper = mount(GraphThumbnail, { props: { document: IDEA_VALIDATOR.document } })
    const ys = wrapper.findAll('rect.thumb-node').map((rect) => Number(rect.attributes('y')))
    const documentYs = IDEA_VALIDATOR.document.nodes.map((node) => node.position.y)
    const lowestDrawn = ys.indexOf(Math.min(...ys))
    const lowestAuthored = documentYs.indexOf(Math.min(...documentYs))
    expect(lowestDrawn).toBe(lowestAuthored)
  })

  it('survives an empty document and a single-column one', () => {
    // A one-column graph has a zero span on x, and dividing by it yields NaN
    // coordinates - which SVG renders as nothing at all, with no error
    // anywhere. Both are real documents an author can produce.
    // A genuinely node-less document, which BLANK stopped being on 2026-09-04:
    // an author still reaches this by deleting the seeded input node, and the
    // thumbnail has to survive it.
    const nothing = { ...BLANK.document, nodes: [], edges: [] }
    const empty = mount(GraphThumbnail, { props: { document: nothing } })
    expect(empty.findAll('rect.thumb-node')).toHaveLength(0)

    const column = mount(GraphThumbnail, { props: { document: MINIMAL_GATED_AGENT.document } })
    for (const rect of column.findAll('rect.thumb-node')) {
      expect(Number.isFinite(Number(rect.attributes('x')))).toBe(true)
      expect(Number.isFinite(Number(rect.attributes('y')))).toBe(true)
    }
  })

  it('is hidden from the accessibility tree when the card already names it', () => {
    const unlabelled = mount(GraphThumbnail, { props: { document: BLANK.document } })
    expect(unlabelled.attributes('aria-hidden')).toBe('true')
    const labelled = mount(GraphThumbnail, {
      props: { document: BLANK.document, label: 'Blank canvas' },
    })
    expect(labelled.attributes('role')).toBe('img')
    expect(labelled.attributes('aria-label')).toBe('Blank canvas')
  })
})
