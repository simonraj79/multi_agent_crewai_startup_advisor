import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  BUILDER_SCHEMA_ID,
  FIELD_CODES,
  PROBLEM_CODES,
  WARNING_CODES,
  documentId,
  edgeId,
  isNodeId,
  nodeId,
} from '../src/types/builder'
import type {
  BuilderDocument,
  BuilderNode,
  ProblemCode,
} from '../src/types/builder'
import {
  fingerprint,
  forValidate,
  roundPositions,
  toWire,
  wireBytes,
} from '../src/utils/builderSerialize'

/**
 * The wire mirror agrees with the Python, and the serializer keeps it that way.
 *
 * This closes the gap WP-0 exists to close: every other builder package types
 * itself against `types/builder.ts`, so if that file is wrong about the wire
 * then six packages are wrong in the same direction and nothing on the client
 * disagrees with anything. The Python is the ground truth here and the tests
 * below reach for it directly wherever they can - the problem-code set is read
 * out of `bounds.py` and `budget.py` at run time rather than transcribed, which
 * is the difference between a mirror that is checked and a mirror that merely
 * looked right on the day it was written.
 *
 * `VALID_DOCUMENT` is not an invention. This exact object was written to JSON
 * and fed to `BuilderDocument.model_validate` and then to `validate_document`
 * on 2026-09-02: it parsed, and it returned ZERO problems - not one error, not
 * one warning. So it is a document the server would accept AND publish, which
 * is a stronger claim than "it type-checks" and the only one worth making about
 * a type layer whose whole job is to stop a 422.
 */

const VALID_DOCUMENT: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: documentId('ug_0a1b2c3d'),
  name: 'Clinic scheduling brief',
  version: 3,
  input_field: nodeId('idea'),
  nodes: [
    {
      id: nodeId('idea'),
      kind: 'input',
      label: 'Idea',
      position: { x: 0, y: 0 },
      config: {
        field: nodeId('idea'),
        label: 'Describe the product in a sentence',
        max_chars: 2000,
        required: true,
      },
    },
    {
      id: nodeId('confirm_scope'),
      kind: 'gate',
      label: 'Confirm scope',
      position: { x: 200, y: 0 },
      config: {
        message: 'Does this scope look right?',
        editable_fields: [nodeId('segment')],
        max_turns: 1,
        expiry_seconds: 1800,
      },
    },
    {
      id: nodeId('route_scope'),
      kind: 'router',
      label: 'Route scope',
      position: { x: 400, y: 0 },
      config: {
        branches: [
          { label: nodeId('approved'), op: 'eq', key: nodeId('decision'), value: 'approve' },
          { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
        ],
      },
    },
    {
      id: nodeId('market'),
      kind: 'agent',
      label: 'Market analyst',
      position: { x: 600, y: -80 },
      config: {
        tier: 'cheap',
        max_iter: 2,
        guardrail_max_retries: 2,
        prompt_inputs: { idea: '${state.idea}', depth: 3 },
        agent_id: nodeId('market_analyst'),
        tools: ['research_market_landscape'],
      },
    },
    {
      id: nodeId('synthesis'),
      kind: 'crew',
      label: 'Synthesis crew',
      position: { x: 600, y: 80 },
      config: {
        tier: 'escalation',
        max_iter: 2,
        guardrail_max_retries: 2,
        prompt_inputs: {},
        crew_id: nodeId('scope'),
      },
    },
    {
      id: nodeId('blend'),
      kind: 'transform',
      label: 'Blend',
      position: { x: 800, y: 0 },
      config: {
        op: 'format',
        args: {
          template: '{a} and {b}',
          a: '${state.out__market}',
          b: '${state.out__synthesis}',
        },
      },
    },
    {
      id: nodeId('report'),
      kind: 'output',
      label: 'Report',
      position: { x: 1000, y: 0 },
      config: { body_key: 'markdown_body', source: '${state.out__blend}' },
    },
  ],
  edges: [
    { id: edgeId('e1'), source: nodeId('idea'), source_port: 'out', target: nodeId('confirm_scope'), target_port: 'in' },
    { id: edgeId('e2'), source: nodeId('confirm_scope'), source_port: 'approve', target: nodeId('route_scope'), target_port: 'in' },
    { id: edgeId('e3'), source: nodeId('confirm_scope'), source_port: 'revise', target: nodeId('route_scope'), target_port: 'in' },
    { id: edgeId('e4'), source: nodeId('route_scope'), source_port: 'approved', target: nodeId('market'), target_port: 'in' },
    { id: edgeId('e5'), source: nodeId('route_scope'), source_port: 'otherwise', target: nodeId('synthesis'), target_port: 'in' },
    { id: edgeId('e6'), source: nodeId('market'), source_port: 'out', target: nodeId('blend'), target_port: 'in' },
    { id: edgeId('e7'), source: nodeId('synthesis'), source_port: 'out', target: nodeId('blend'), target_port: 'in' },
    { id: edgeId('e8'), source: nodeId('blend'), source_port: 'out', target: nodeId('report'), target_port: 'in' },
  ],
  joins: { blend: 'all' },
  budget: null,
}

/** A shallow copy with one node replaced, so no test mutates the shared fixture. */
function withNode(doc: BuilderDocument, index: number, node: BuilderNode): BuilderDocument {
  const nodes = [...doc.nodes]
  nodes[index] = node
  return { ...doc, nodes }
}

/**
 * The problem codes as the Python declares them, read at run time - from all
 * FOUR files that declare one.
 *
 * Transcribing them would make this test agree with the tuple it is checking
 * for exactly as long as both were copied from the same place, which is no
 * check at all. `bounds.py` (25), `budget.py` (2), `compiler.py` (3) and
 * `registry.py` (3) declare
 * every code as a module-level constant precisely so neither side has an inline
 * string, and the kebab-case filter is what tells a code apart from any other
 * string constant any of them might grow.
 *
 * `compiler.py` was missing from this array until 2026-09-02, and the omission
 * is worth keeping on the record because of HOW it passed. The regex below
 * already matched its three `LIBRARY_*` constants - nothing had to be taught -
 * and the count assertion below agreed at 27, because it was counting what this
 * list read rather than what the server emits. So a mirror missing three codes
 * was checked by a test that read the same three files the mirror did: green,
 * and wrong by the same amount on both sides. The independent number is the
 * defence, so the count is re-derived here whenever this array changes, by
 * walking every `Problem(...)` construction site under `builder/` rather than
 * by trusting the constants - which is also the only way to see the two codes
 * `bounds.py::_identity_problems` raises through a LOOP VARIABLE rather than a
 * literal.
 */
function pythonProblemCodes(): string[] {
  const sources = [
    '../../src/brief_crew/builder/bounds.py',
    '../../src/brief_crew/builder/budget.py',
    '../../src/brief_crew/builder/compiler.py',
    // Plans 06, 07 and 08 declare their own codes in their own modules, in the
    // module-level shape this regex can see. SEVEN files now, and the same
    // seven are named in `tests/builder/test_problem_code_declarations.py`, in
    // `scripts/emit_builder_fixtures.py` and in `_problem_code_union` - they
    // move together, or a code exists on the server that this tuple has never
    // heard of, which is section 14's defect 2.
    '../../src/brief_crew/builder/tools.py',
    '../../src/brief_crew/builder/mcp.py',
    '../../src/brief_crew/builder/skills.py',
    // The fourth, added 2026-09-04 with plan 05. `compiler.py` was missing from
    // this array for a while and twenty-seven codes passed as thirty; the same
    // omission here would hide `model-lacks-capability`, which is the most
    // frequent thing an author does wrong with a model picker.
    '../../src/brief_crew/builder/registry.py',
  ]
  const codes = new Set<string>()
  for (const relative of sources) {
    const text = readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8')
    for (const match of text.matchAll(/^[A-Z][A-Z0-9_]* = "([a-z]+(?:-[a-z]+)+)"$/gm)) {
      codes.add(match[1])
    }
  }
  return [...codes].sort()
}

describe('the type layer accepts a document the server accepts', () => {
  it('sends the nine top-level keys the python model dumps, and no others', () => {
    // `BuilderDocument.model_dump(mode="json", by_alias=True)` answers exactly
    // this set. A tenth key would meet `extra="forbid"` and come back a 422
    // naming a field the author never typed.
    expect(Object.keys(toWire(VALID_DOCUMENT)).sort()).toEqual([
      'budget',
      'edges',
      'id',
      'input_field',
      'joins',
      'name',
      'nodes',
      'schema',
      'version',
    ])
  })

  it('spells the schema key `schema`, never `documentSchema`', () => {
    // The python field is `document_schema` with `alias="schema"`, because a
    // pydantic field called `schema` shadows a BaseModel attribute. The wire
    // says `schema` in both directions and this is the only place that decides.
    const wire = toWire(VALID_DOCUMENT)
    expect(wire.schema).toBe('builder.flow/v1')
    expect(wire).not.toHaveProperty('documentSchema')
    expect(wire).not.toHaveProperty('document_schema')
  })

  it('never sends a budget block back', () => {
    // `budget.py` writes it onto the document it priced. An author's copy is at
    // best a stale estimate of an older version, and the server recomputes it
    // on every response anyway.
    const priced: BuilderDocument = {
      ...VALID_DOCUMENT,
      budget: {
        static_cost_usd: 1.5,
        billable_nodes: 2,
        escalation_nodes: 1,
        cycles: 0,
        compiled_at: '2026-09-02T00:00:00Z',
      },
    }
    expect(toWire(priced).budget).toBeNull()
  })

  it('round-trips through JSON unchanged, brands and all', () => {
    // The ids are branded only in the type system - `unique symbol` tags, not
    // properties - so `JSON.stringify` must see plain strings.
    const wire = toWire(VALID_DOCUMENT)
    expect(JSON.parse(JSON.stringify(wire))).toEqual(wire)
  })

  it('keeps the one legal target port and the gate ports the compiler emits', () => {
    expect(VALID_DOCUMENT.edges.every((edge) => edge.target_port === 'in')).toBe(true)
    const gatePorts = VALID_DOCUMENT.edges
      .filter((edge) => edge.source === 'confirm_scope')
      .map((edge) => edge.source_port)
    expect(gatePorts).toEqual(['approve', 'revise'])
  })
})

describe('the id minters refuse what the server would refuse', () => {
  // BUILDER_ID_PATTERN is `^[a-z][a-z0-9_]{0,39}$`, and the 40-character
  // ceiling is real: a node compiles to `n{index}_{node_id}` and
  // MAX_IDENTIFIER_LENGTH truncates silently rather than raising, which merges
  // two nodes into one in every frame the run emits.
  it('accepts a lowercase identifier at exactly forty characters', () => {
    const longest = `a${'b'.repeat(39)}`
    expect(longest).toHaveLength(40)
    expect(isNodeId(longest)).toBe(true)
    expect(nodeId(longest)).toBe(longest)
  })

  it.each([
    ['a leading digit', '1agent'],
    ['an uppercase letter', 'Agent'],
    ['a hyphen', 'market-analyst'],
    ['forty-one characters', `a${'b'.repeat(40)}`],
    ['nothing at all', ''],
    ['a leading underscore', '_agent'],
    ['a trailing newline', 'agent\n'],
  ])('refuses %s', (_reason, candidate) => {
    expect(isNodeId(candidate)).toBe(false)
    expect(() => nodeId(candidate)).toThrow(/not a NodeId/)
  })

  it('holds an edge id to the same pattern, because the python annotates it NodeId', () => {
    expect(edgeId('e12')).toBe('e12')
    expect(() => edgeId('E12')).toThrow(/not an EdgeId/)
  })

  it('holds a document id to the server-assigned shape alone', () => {
    // BUILDER_DOCUMENT_ID_PATTERN is `^ug_[0-9a-f]{8}$`. A client never chooses
    // one - `parse()` overwrites whatever is sent - so anything else here came
    // from a stale draft rather than from a server.
    expect(documentId('ug_0a1b2c3d')).toBe('ug_0a1b2c3d')
    expect(() => documentId('ug_0A1B2C3D')).toThrow(/not a DocumentId/)
    expect(() => documentId('ug_0a1b2c3')).toThrow(/not a DocumentId/)
    expect(() => documentId('idea-validator')).toThrow(/not a DocumentId/)
  })
})

describe('forValidate keeps the validate endpoint out of its two traps', () => {
  it('omits id entirely rather than blanking it', () => {
    // The handler reads `str(request.document.get("id") or new_document_id())`.
    // An absent key takes the mint; a MALFORMED one - carried over from an
    // older draft, say - reaches BuilderDocument and comes back 422 about a
    // field the author cannot see and did not choose.
    const wire = forValidate(VALID_DOCUMENT)
    expect('id' in wire).toBe(false)
    expect(Object.keys(wire).sort()).toEqual([
      'budget',
      'edges',
      'input_field',
      'joins',
      'name',
      'nodes',
      'schema',
      'version',
    ])
  })

  it('sends a number for version, so the handler never has to refuse it', () => {
    // `_requested_version` reads this off the raw body before any pydantic
    // model sees it, and answers 422 `version must be a whole number; this
    // document carries 'v7'`. It was a bare `int(...)` - and therefore a 500 -
    // until 2026-09-02; the reason to coerce is the same either way, because a
    // refusal about `version` names a field the author never typed.
    const stringVersioned = { ...VALID_DOCUMENT, version: '3' as unknown as number }
    const wire = forValidate(stringVersioned)
    expect(typeof wire.version).toBe('number')
    expect(wire.version).toBe(3)
  })

  it('floors at 1, because the schema declares version ge=1', () => {
    // The handler answers `max(FIRST_VERSION, int(...))`, so this mirrors it
    // rather than leaning on it. `Number(null)` is 0 - finite, and illegal.
    for (const bad of ['head', undefined, null, Number.NaN, Infinity, 0, -4]) {
      const wire = forValidate({ ...VALID_DOCUMENT, version: bad as unknown as number })
      expect(wire.version).toBe(1)
    }
  })

  it('truncates a fractional version the way python int() does', () => {
    expect(forValidate({ ...VALID_DOCUMENT, version: 2.9 }).version).toBe(2)
  })

  it('leaves the document it was handed untouched', () => {
    forValidate(VALID_DOCUMENT)
    expect(VALID_DOCUMENT.id).toBe('ug_0a1b2c3d')
    expect(VALID_DOCUMENT.version).toBe(3)
  })
})

describe('fingerprint tracks meaning, not layout', () => {
  it('does not change when a node is dragged', () => {
    // Position is never compiled and never read at runtime, so a drag must not
    // spend a validate round trip or dim the problem list while it resolves.
    const dragged = withNode(VALID_DOCUMENT, 3, {
      ...VALID_DOCUMENT.nodes[3],
      position: { x: 1234, y: -900 },
    })
    expect(fingerprint(dragged)).toBe(fingerprint(VALID_DOCUMENT))
  })

  it('changes when a config value changes', () => {
    const node = VALID_DOCUMENT.nodes[3]
    if (node.kind !== 'agent') throw new Error('fixture drift: node 3 is the agent')
    const escalated = withNode(VALID_DOCUMENT, 3, {
      ...node,
      config: { ...node.config, tier: 'escalation' },
    })
    expect(fingerprint(escalated)).not.toBe(fingerprint(VALID_DOCUMENT))
  })

  it('changes when a label, an edge or a join changes', () => {
    const base = fingerprint(VALID_DOCUMENT)
    const relabelled = withNode(VALID_DOCUMENT, 0, { ...VALID_DOCUMENT.nodes[0], label: 'Concept' })
    const rewired = { ...VALID_DOCUMENT, edges: VALID_DOCUMENT.edges.slice(0, 7) }
    const unjoined = { ...VALID_DOCUMENT, joins: {} }
    expect(fingerprint(relabelled)).not.toBe(base)
    expect(fingerprint(rewired)).not.toBe(base)
    expect(fingerprint(unjoined)).not.toBe(base)
  })

  it('is invariant under key order inside an author-keyed record', () => {
    // `prompt_inputs`, `transform.args` and `joins` are keyed by the author,
    // and rebuilding one - a rename, a paste, a round trip through the server -
    // reorders its keys without changing a thing it means.
    const node = VALID_DOCUMENT.nodes[3]
    if (node.kind !== 'agent') throw new Error('fixture drift: node 3 is the agent')
    const reordered = withNode(VALID_DOCUMENT, 3, {
      ...node,
      config: { ...node.config, prompt_inputs: { depth: 3, idea: '${state.idea}' } },
    })
    const before = Object.keys(node.config.prompt_inputs)
    const after = Object.keys((reordered.nodes[3].config as typeof node.config).prompt_inputs)
    expect(after).not.toEqual(before)
    expect([...after].sort()).toEqual([...before].sort())
    expect(fingerprint(reordered)).toBe(fingerprint(VALID_DOCUMENT))
  })

  it('is a stable string across repeated calls', () => {
    expect(fingerprint(VALID_DOCUMENT)).toBe(fingerprint(VALID_DOCUMENT))
  })
})

describe('wireBytes counts what a TextEncoder counts', () => {
  it('agrees with the encoder over a multi-byte name', () => {
    const named = { ...VALID_DOCUMENT, name: 'クリニック予約 — brief' }
    const expected = new TextEncoder().encode(JSON.stringify(toWire(named))).length
    expect(wireBytes(named)).toBe(expected)
  })

  it('counts more bytes than characters once the name leaves ASCII', () => {
    // And this is the honest gap, named where it is created: the server
    // measures `json.dumps(...)` with Python's default `ensure_ascii=True`,
    // which writes a non-ASCII character as a six-byte `\uXXXX` escape where
    // TextEncoder writes two or three real UTF-8 bytes. So this figure runs
    // SMALLER than the one the 413 quotes - a warning that fires late, never a
    // save refused unexpectedly.
    const ascii = wireBytes({ ...VALID_DOCUMENT, name: 'aaaaaa' })
    const wide = wireBytes({ ...VALID_DOCUMENT, name: 'クリニック予' })
    expect(wide).toBeGreaterThan(ascii)
    expect(wide - ascii).toBe(6 * 2)
  })
})

describe('roundPositions makes every position an integer the schema will take', () => {
  it('rounds a half-pixel drag that would otherwise be a 422', () => {
    // `Position` declares `int`, and pydantic coerces 120.0 but not 120.5 - so
    // the refusal arrives on the next save, long after the gesture that caused
    // it.
    const drifted = withNode(VALID_DOCUMENT, 0, {
      ...VALID_DOCUMENT.nodes[0],
      position: { x: 120.5, y: -0.4 },
    })
    const rounded = roundPositions(drifted)
    expect(rounded.nodes[0].position).toEqual({ x: 121, y: -0 })
    expect(Number.isInteger(rounded.nodes[0].position.x)).toBe(true)
    expect(Number.isInteger(rounded.nodes[0].position.y)).toBe(true)
  })

  it('returns the very same document when nothing needed rounding', () => {
    // A commit that changes nothing is still an undo step, and an undo that
    // visibly does nothing is worse than no undo at all.
    expect(roundPositions(VALID_DOCUMENT)).toBe(VALID_DOCUMENT)
  })
})

describe('the problem codes are the python problem codes', () => {
  it('matches bounds.py, budget.py and compiler.py exactly, read from the files', () => {
    expect([...PROBLEM_CODES].sort()).toEqual(pythonProblemCodes())
  })

  it('finds all fifty, so an empty read cannot pass as agreement', () => {
    // Without this the assertion above would be satisfied by a regex that
    // matched nothing against a tuple that had lost everything - and, as the
    // 27 that stood here until 2026-09-02 proved, by a file list missing a
    // whole module against a tuple missing the same three codes.
    //
    // 31 until 2026-09-04, when 03-node-library.md D2 landed the seven
    // edge-class codes in `bounds.py`: `attach-target-not-agent`,
    // `member-target-not-crew`, `member-agent-has-flow-edges`,
    // `attachment-unattached`, `attachments-over-max`,
    // `attachment-nodes-over-max` and `crew-members-out-of-range`. The
    // Python-side twin of this assertion is
    // `tests/builder/test_problem_code_declarations.py`, whose failure message
    // names this line and the tuple by path - which is the only mechanism that
    // makes a server-side code addition break a TypeScript test in the same
    // commit rather than three commits later.
    //
    // 38 until 2026-09-04, when plan 05 added a FOURTH declaring file -
    // `builder/registry.py` - and its three model codes: `model-unknown`,
    // `model-over-ceiling` and `model-lacks-capability`. That is exactly the
    // four-place edit the `compiler.py` paragraph above predicts, made in one
    // commit rather than discovered three commits later.
    //
    // 41 until 2026-09-04, when plans 06, 07 and 08 added three more declaring
    // files - `builder/tools.py`, `builder/mcp.py` and `builder/skills.py` -
    // and nine codes: three about a tool node's id, settings and key, five
    // about an MCP server and its tools, and one about a skill pack. That is
    // the same four-place edit again, made in one commit.
    expect(pythonProblemCodes()).toHaveLength(55)
    expect(PROBLEM_CODES).toHaveLength(55)
  })

  it('declares the five warnings, and they are codes', () => {
    // `bounds.py` writes `severity="warning"` at exactly four sites and
    // `mcp.py` at one. Every other code is an error and blocks publish. The
    // fourth is `attachment-unattached`, which is a warning because it is
    // exactly what a node looks like the moment it is dropped; the fifth is
    // `mcp-tool-description-suspicious`, which is a warning because the
    // thirteen injection patterns have false positives by design and PLANS.md
    // decision 8 rules that the author decides with eyes open.
    for (const code of WARNING_CODES) {
      expect(PROBLEM_CODES).toContain(code)
    }
    expect(WARNING_CODES).toHaveLength(7)
  })

  it('anchors every FIELD_CODES entry to a real code', () => {
    // A typo here is a problem that silently falls to the node-level strip
    // instead of the control it belongs under - no error, no missing row, just
    // a message in the wrong place.
    for (const code of Object.keys(FIELD_CODES) as ProblemCode[]) {
      expect(PROBLEM_CODES).toContain(code)
    }
  })
})
