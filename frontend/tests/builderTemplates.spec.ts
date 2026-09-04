import { describe, expect, it } from 'vitest'
import { BLANK, BUILDER_TEMPLATES, documentFromTemplate } from '../src/data/builderTemplates'
import { PROBLEM_CODES } from '../src/types/builder'
import type { BuilderDocument, InputConfig } from '../src/types/builder'

/**
 * A new graph opens ready to build on, not already wrong.
 *
 * 02-canvas.md D7 and criterion 10. `BLANK` opened with nothing drawn and two
 * errors against it until 2026-09-04 - `no-input-node` and
 * `input-field-undeclared` - which meant the very first thing a new author saw
 * was a red problems dock about a graph they had not touched. Flowise seeds a
 * Start node at `{x:100, y:100}` for the same reason (`Canvas.jsx:656-677`).
 *
 * ZERO PROBLEMS IS ASSERTED STRUCTURALLY, and the distinction matters enough to
 * state: `bounds.py` owns every problem and no vitest can run it, so what is
 * checked here is that the three CONDITIONS the input-shaped codes fire on are
 * each absent, and that the codes named are codes that really exist. The
 * server's own answer for this document is asserted in a browser, where the
 * problems dock is empty on a fresh canvas.
 */

/** Every problem code this file reasons about, checked against the real union. */
const INPUT_CODES = ['no-input-node', 'input-field-undeclared', 'input-field-ambiguous'] as const

function inputNodes(document: BuilderDocument) {
  return document.nodes.filter((node) => node.kind === 'input')
}

describe('a new document opens with one input node and nothing against it', () => {
  it('names three codes that the problem union really contains', () => {
    // Otherwise the reasoning below is about codes nobody emits, and the whole
    // file would pass while asserting nothing.
    for (const code of INPUT_CODES) {
      expect(PROBLEM_CODES, code).toContain(code)
    }
  })

  it('seeds exactly one node, and it is an input at (100, 100)', () => {
    const document = documentFromTemplate(BLANK)
    expect(document.nodes).toHaveLength(1)
    const [seed] = document.nodes
    expect(seed.kind).toBe('input')
    expect(seed.position).toEqual({ x: 100, y: 100 })
    expect(document.edges).toEqual([])
  })

  it('cannot fire `no-input-node`, because there is one', () => {
    expect(inputNodes(documentFromTemplate(BLANK))).toHaveLength(1)
  })

  it('cannot fire `input-field-undeclared`, because input_field names the seed', () => {
    // The pair is consistent ON ARRIVAL rather than once somebody presses a
    // button. `input_field` is a FIELD name and not a node id, which is the
    // distinction the old blank document got wrong by declaring `idea` with no
    // node anywhere that offered it.
    const document = documentFromTemplate(BLANK)
    const fields = inputNodes(document).map((node) => (node.config as InputConfig).field)
    expect(fields).toContain(document.input_field)
  })

  it('cannot fire `input-field-ambiguous`, because there is only one candidate', () => {
    // A SECOND input node stays perfectly legal and stays flagged - that is the
    // problem that means something, two candidates and no statement of which
    // one the run reads. What is gone is the flag on a graph of one node.
    expect(inputNodes(documentFromTemplate(BLANK))).toHaveLength(1)
  })

  it('carries no billable node, so nothing about price or gating can be wrong', () => {
    const kinds = documentFromTemplate(BLANK).nodes.map((node) => node.kind)
    expect(kinds).not.toContain('agent')
    expect(kinds).not.toContain('crew')
  })

  it('hands out a fresh copy, so two sessions cannot edit one seed', () => {
    const first = documentFromTemplate(BLANK)
    const second = documentFromTemplate(BLANK)
    expect(first).toEqual(second)
    expect(first).not.toBe(BLANK.document)
    expect(first.nodes[0]).not.toBe(BLANK.document.nodes[0])
  })

  it('is still the gallery card an author reaches in one click', () => {
    // Landing -> first node placed is ONE click, and the click is this card.
    // If BLANK ever left the gallery the criterion would be met by a document
    // nobody can open.
    expect(BUILDER_TEMPLATES.map((template) => template.id)).toContain('blank')
    expect(BLANK.blurb).toContain('input node')
  })
})
