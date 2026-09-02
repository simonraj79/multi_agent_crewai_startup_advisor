import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  BUILDER_SCHEMA_ID,
  STATE_OUTPUT_PREFIX,
  STATE_REF_PATTERN,
  documentId,
  edgeId,
  nodeId,
} from '../src/types/builder'
import type {
  AgentConfig,
  BuilderDocument,
  BuilderEdge,
  BuilderNode,
  EdgeId,
  GateConfig,
  NodeId,
  OutputConfig,
  RouterConfig,
  TransformConfig,
} from '../src/types/builder'
import {
  STATE_TURNS_PREFIX,
  ancestorsOf,
  backEdges,
  descendantsOf,
  remapIds,
  renameCascade,
  topoOrder,
} from '../src/utils/builderGraph'

/**
 * A rename moves every reference, and a cycle is drawn the way the server sees
 * it.
 *
 * Two gaps, and they fail in opposite directions.
 *
 * The first is `renameCascade`. A node id is not only an identity - the
 * compiler derives `out__<id>` and `turns__<id>` from it, and an author writes
 * those keys by hand inside values the schema is happy to take as plain
 * strings. Miss one and the text is still perfectly legal. `REFERENCE_DOC`
 * below is not a construction: it was written to JSON and fed to the real
 * `BuilderDocument.model_validate`, `validate_document` and `compile_document`
 * on 2026-09-02. It parses, it returns ZERO problems, and it compiles - and
 * then the two naive renames were run against the same Python, which is where
 * the two failure modes each test names came from:
 *
 *   rename `market`, leave the refs  -> COMPILE ERROR, "a node references
 *                                       ${state.out__market} and no node has
 *                                       the id 'market'"
 *   rename the gate `confirm`,
 *   leave `turns__confirm`           -> COMPILES. Zero problems. And
 *                                       `route_branch` then reads a key nothing
 *                                       seeded, never matches, and takes
 *                                       `otherwise` on every pass forever.
 *
 * That second one is why this file walks every string leaf rather than the four
 * sites the schema type-checks: nothing downstream would ever have said a word.
 *
 * The second gap is `backEdges`, the one deliberate mirror of server logic
 * (R7). Every expected index below was MEASURED by running the same document
 * through `bounds.back_edge_indices`, not derived by reading the algorithm -
 * a mirror checked against its author's understanding of the original is not
 * checked. The permanent anti-rot gate is the Python-generated fixture R7 calls
 * for, which is WP-G's to emit; this is the version of that check that can
 * exist today.
 */

/* --- the document with a reference in every legal hiding place ------------ */

const MARKET_QUERY_INPUTS: AgentConfig = {
  tier: 'cheap',
  max_iter: 2,
  guardrail_max_retries: 2,
  prompt_inputs: {
    cached_evidence_block: '',
    market_query: '${state.idea}',
    scoped_idea_json: '{}',
  },
  agent_id: nodeId('market_analyst'),
  tools: [],
}

function node(
  id: string,
  kind: BuilderNode['kind'],
  config: BuilderNode['config'],
): BuilderNode {
  return { id: nodeId(id), kind, label: id, position: { x: 0, y: 0 }, config } as BuilderNode
}

function edge(id: string, source: string, port: string, target: string): BuilderEdge {
  return {
    id: edgeId(id),
    source: nodeId(source),
    source_port: port,
    target: nodeId(target),
    target_port: 'in',
  }
}

const REFERENCE_DOC: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: documentId('ug_0a1b2c3d'),
  name: 'Reference hiding places',
  version: 1,
  input_field: nodeId('idea'),
  nodes: [
    node('idea', 'input', {
      field: nodeId('idea'),
      label: 'Idea',
      max_chars: 2000,
      required: true,
    }),
    node('market', 'agent', MARKET_QUERY_INPUTS),
    // hiding place 1: a prompt input value
    node('summarise', 'agent', {
      ...MARKET_QUERY_INPUTS,
      prompt_inputs: {
        cached_evidence_block: '${state.out__market}',
        market_query: 'again',
        scoped_idea_json: '{}',
      },
    }),
    // hiding place 2: a transform arg value
    node('blend', 'transform', {
      op: 'format',
      args: { template: '{a}', a: '${state.out__market}' },
    }),
    // hiding place 3: a gate message, EMBEDDED mid-sentence
    node('confirm', 'gate', {
      message: 'The analyst said ${state.out__market} - accept?',
      editable_fields: [],
      max_turns: 2,
      expiry_seconds: 1800,
    }),
    // hiding place 4: a router branch key, written BARE
    node('spin', 'router', {
      branches: [
        { label: nodeId('again'), op: 'eq', key: nodeId('out__market'), value: 'retry' },
        { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
      ],
    }),
    // hiding place 5: a gate's turn counter, also bare
    node('cap', 'router', {
      branches: [
        { label: nodeId('enough'), op: 'gte', key: nodeId('turns__confirm'), value: 2 },
        { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
      ],
    }),
    // hiding place 6: output.source
    node('report', 'output', { body_key: 'markdown_body', source: '${state.out__market}' }),
  ],
  edges: [
    edge('e1', 'idea', 'out', 'market'),
    edge('e2', 'market', 'out', 'summarise'),
    edge('e3', 'summarise', 'out', 'blend'),
    edge('e4', 'blend', 'out', 'confirm'),
    edge('e5', 'confirm', 'approve', 'spin'),
    edge('e6', 'confirm', 'revise', 'cap'),
    edge('e7', 'spin', 'again', 'report'),
    edge('e8', 'spin', 'otherwise', 'report'),
    edge('e9', 'cap', 'enough', 'report'),
    edge('e10', 'cap', 'otherwise', 'market'),
  ],
  joins: { report: 'all' },
  budget: null,
}

function find(doc: BuilderDocument, id: string): BuilderNode {
  const found = doc.nodes.find((entry) => entry.id === id)
  if (!found) throw new Error(`no node ${id} in the document under test`)
  return found
}

/* --- the loop document, in three edge orders ----------------------------- */

const LOOP_NODES: BuilderNode[] = [
  node('idea', 'input', { field: nodeId('idea'), label: null, max_chars: 2000, required: true }),
  node('confirm', 'gate', {
    message: 'ok?',
    editable_fields: [],
    max_turns: 1,
    expiry_seconds: 1800,
  }),
  node('revise', 'agent', MARKET_QUERY_INPUTS),
  node('market', 'agent', MARKET_QUERY_INPUTS),
  node('report', 'output', { body_key: 'markdown_body', source: null }),
]

const LOOP_EDGES: BuilderEdge[] = [
  edge('e1', 'idea', 'out', 'confirm'),
  edge('e2', 'confirm', 'approve', 'market'),
  edge('e3', 'market', 'out', 'report'),
  edge('e4', 'confirm', 'revise', 'revise'),
  edge('e5', 'revise', 'out', 'confirm'),
]

function docOf(nodes: BuilderNode[], edges: BuilderEdge[]): BuilderDocument {
  return { ...REFERENCE_DOC, nodes, edges, joins: {} }
}

const ORDERED = (positions: number[]) => positions.map((position) => LOOP_EDGES[position])

describe('renameCascade moves every reference a node id can hide in', () => {
  const renamed = renameCascade(REFERENCE_DOC, nodeId('market'), nodeId('market_analysis'))

  it('renames the node itself', () => {
    expect(renamed.nodes.map((entry) => entry.id)).toContain('market_analysis')
    expect(renamed.nodes.map((entry) => entry.id)).not.toContain('market')
  })

  it('moves both endpoints of every incident edge', () => {
    expect(renamed.edges[0]).toMatchObject({ source: 'idea', target: 'market_analysis' })
    expect(renamed.edges[1]).toMatchObject({ source: 'market_analysis', target: 'summarise' })
    expect(renamed.edges[9]).toMatchObject({ source: 'cap', target: 'market_analysis' })
  })

  it('rewrites a reference hiding in a prompt input value', () => {
    const config = find(renamed, 'summarise').config as AgentConfig
    expect(config.prompt_inputs.cached_evidence_block).toBe('${state.out__market_analysis}')
  })

  it('rewrites a reference hiding in a transform arg value', () => {
    const config = find(renamed, 'blend').config as TransformConfig
    expect(config.args.a).toBe('${state.out__market_analysis}')
    // The sibling arg is not a reference and must come through untouched, or
    // `format` starts substituting a name it was never given.
    expect(config.args.template).toBe('{a}')
  })

  it('rewrites a reference embedded mid-sentence in a gate message', () => {
    // The schema never checks this field for `${`, so it is the one hiding
    // place a site-by-site rewrite would miss - and the compiler's own scan is
    // an unanchored regex over every leaf, so it counts as a reference and a
    // dangling one refuses the publish.
    const config = find(renamed, 'confirm').config as GateConfig
    expect(config.message).toBe('The analyst said ${state.out__market_analysis} - accept?')
  })

  it('rewrites a router branch key, which is written BARE and not as a token', () => {
    const config = find(renamed, 'spin').config as RouterConfig
    expect(config.branches[0].key).toBe('out__market_analysis')
    expect(config.branches[1].key).toBeNull()
  })

  it('rewrites output.source', () => {
    const config = find(renamed, 'report').config as OutputConfig
    expect(config.source).toBe('${state.out__market_analysis}')
  })

  it('moves a joins key', () => {
    const joined = renameCascade(REFERENCE_DOC, nodeId('report'), nodeId('final_report'))
    expect(Object.keys(joined.joins)).toEqual(['final_report'])
    expect(joined.joins.final_report).toBe('all')
  })

  it('leaves every other reference alone', () => {
    const config = find(renamed, 'market_analysis').config as AgentConfig
    expect(config.prompt_inputs.market_query).toBe('${state.idea}')
    const cap = find(renamed, 'cap').config as RouterConfig
    expect(cap.branches[0].key).toBe('turns__confirm')
  })

  it('does not mutate the document it was given', () => {
    const before = find(REFERENCE_DOC, 'summarise').config as AgentConfig
    expect(before.prompt_inputs.cached_evidence_block).toBe('${state.out__market}')
    expect(REFERENCE_DOC.nodes.map((entry) => entry.id)).toContain('market')
  })
})

describe('renameCascade knows which state keys a node id actually owns', () => {
  it('moves a gate turn counter, which fails SILENTLY when it is left behind', () => {
    // Measured: the same document with `turns__confirm` left behind compiles,
    // returns zero problems, and routes on a key nothing seeded for the life of
    // the workflow. Nothing anywhere would have reported it.
    const renamed = renameCascade(REFERENCE_DOC, nodeId('confirm'), nodeId('confirm_scope'))
    const cap = find(renamed, 'cap').config as RouterConfig
    expect(cap.branches[0].key).toBe('turns__confirm_scope')
  })

  it('moves a `${state.turns__…}` token as well as the bare key', () => {
    const withToken: BuilderDocument = {
      ...REFERENCE_DOC,
      nodes: REFERENCE_DOC.nodes.map((entry) =>
        entry.id === 'blend'
          ? node('blend', 'transform', {
              op: 'format',
              args: { template: '{a}', a: '${state.turns__confirm}' },
            })
          : entry,
      ),
    }
    const renamed = renameCascade(withToken, nodeId('confirm'), nodeId('confirm_scope'))
    const config = find(renamed, 'blend').config as TransformConfig
    expect(config.args.a).toBe('${state.turns__confirm_scope}')
  })

  it('does NOT invent a turns key for a node that is not a gate', () => {
    // Only a gate has a turn counter (`compiler.py:729`). Rewriting
    // `turns__market` would be rewriting an author's own state key that merely
    // happens to be spelled like a derived one.
    const withDecoy: BuilderDocument = {
      ...REFERENCE_DOC,
      nodes: REFERENCE_DOC.nodes.map((entry) =>
        entry.id === 'cap'
          ? node('cap', 'router', {
              branches: [
                { label: nodeId('enough'), op: 'gte', key: nodeId('turns__market'), value: 2 },
                { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
              ],
            })
          : entry,
      ),
    }
    const renamed = renameCascade(withDecoy, nodeId('market'), nodeId('market_analysis'))
    const config = find(renamed, 'cap').config as RouterConfig
    expect(config.branches[0].key).toBe('turns__market')
  })

  it('cannot rewrite a longer id that merely starts with the renamed one', () => {
    const withNeighbour: BuilderDocument = {
      ...REFERENCE_DOC,
      nodes: REFERENCE_DOC.nodes.map((entry) =>
        entry.id === 'blend'
          ? node('blend', 'transform', {
              op: 'format',
              args: { template: '{a}', a: '${state.out__market_share} ${state.out__market}' },
            })
          : entry,
      ),
    }
    const renamed = renameCascade(withNeighbour, nodeId('market'), nodeId('m'))
    const config = find(renamed, 'blend').config as TransformConfig
    expect(config.args.a).toBe('${state.out__market_share} ${state.out__m}')
  })

  it('leaves input_field and the input node field alone', () => {
    // The departure from the §2 sentence, and the reason is in the function's
    // docblock: `bounds.py` matches `input_field` against `config.field`, never
    // against a node id, so moving it alone would leave it declared by no input
    // node and turn a valid document into an `input-field-undeclared` error.
    const renamed = renameCascade(REFERENCE_DOC, nodeId('idea'), nodeId('the_idea'))
    expect(renamed.input_field).toBe('idea')
    expect(find(renamed, 'the_idea').config).toMatchObject({ field: 'idea' })
  })

  it('returns the same document when the name did not change', () => {
    expect(renameCascade(REFERENCE_DOC, nodeId('market'), nodeId('market'))).toBe(REFERENCE_DOC)
  })

  it('reuses the node objects it did not have to touch', () => {
    // The document is immutable by invariant, so an identity comparison is how
    // everything downstream tells what actually changed. Reallocating every
    // config would make that comparison useless.
    const renamed = renameCascade(REFERENCE_DOC, nodeId('market'), nodeId('market_analysis'))
    expect(find(renamed, 'cap')).toBe(find(REFERENCE_DOC, 'cap'))
    expect(find(renamed, 'summarise')).not.toBe(find(REFERENCE_DOC, 'summarise'))
  })
})

/**
 * A Python source file, read at test time.
 *
 * The relative path goes through a variable deliberately. Vite rewrites
 * `new URL('<literal>', import.meta.url)` into an ASSET url at transform time,
 * so a literal here resolves to an http scheme and `fileURLToPath` refuses it;
 * a variable is opaque to that transform and the expression stays what it
 * reads as. `builderTypes.spec.ts` does the same for the same reason.
 */
function pythonSource(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8')
}

describe('the derived state prefixes agree with the python', () => {
  it('spells the gate turn counter the way the runtime does', () => {
    // The `serverLimits.ts` idiom. `turns__` is declared twice on the Python
    // side (`runtime.py` and `gates.py`) and this is the third; a drift should
    // be a failing test, not a router that quietly stops routing.
    expect(pythonSource('../../src/brief_crew/builder/runtime.py')).toContain(
      `BUILDER_STATE_TURNS_PREFIX = "${STATE_TURNS_PREFIX}"`,
    )
    expect(pythonSource('../../src/brief_crew/builder/gates.py')).toContain(
      `_TURNS_PREFIX = "${STATE_TURNS_PREFIX}"`,
    )
  })

  it('spells the node output prefix the way config.py does', () => {
    /*
     * `turns__` had this test and `out__` - its matched pair, restated in the
     * very next line of `types/builder.ts` - did not, which is the shape
     * restated-constant discipline fails in: the one that got written down is
     * checked and the one beside it is trusted.
     *
     * It is the more expensive half, too. `out__` is what every `${state.…}`
     * reference in a document resolves through, so a drift does not raise
     * anything - `stateKeysOf` would simply offer keys that resolve to nothing
     * and `StateRefInput` would warn about references that are in fact correct.
     */
    const declared = /^BUILDER_STATE_OUTPUT_PREFIX = "([^"]+)"$/m.exec(
      pythonSource('../../src/brief_crew/config.py'),
    )
    expect(declared?.[1], 'BUILDER_STATE_OUTPUT_PREFIX moved in config.py').toBe(
      STATE_OUTPUT_PREFIX,
    )
  })

  it('accepts exactly the state references config.py accepts', () => {
    /*
     * Compared as SOURCE rather than by trying a few strings past both, because
     * the two engines are not the same engine and a sample would prove only
     * that the samples agree. What makes a character-identical comparison
     * legitimate here is that the pattern uses nothing whose meaning differs
     * between Python's `re` and ECMAScript: an anchor, escaped literals, one
     * character class and one bounded quantifier.
     *
     * The failure it guards is a near-miss reference. `_checked_with_value`
     * refuses `${state.out__scoper.segment}` at parse time - dotted access was
     * measured NOT resolving - so a client whose pattern is one character wider
     * than the server's invites the author to type a 422.
     */
    const declared = /^BUILDER_STATE_REF_PATTERN = r"([^"]+)"$/m.exec(
      pythonSource('../../src/brief_crew/config.py'),
    )
    expect(declared?.[1], 'BUILDER_STATE_REF_PATTERN moved in config.py').toBe(
      STATE_REF_PATTERN.source,
    )
  })
})

describe('backEdges mirrors bounds._back_edges_with_index', () => {
  it('finds the loop-closing edge of a revise loop', () => {
    expect(backEdges(docOf(LOOP_NODES, LOOP_EDGES))).toEqual([4])
  })

  it('reports a POSITION, so the answer moves with the edge order', () => {
    // The same graph, edges written in three orders. Two parallel edges between
    // one pair are equal as values and only their position tells them apart,
    // which is why the Python answers in positions and so does this.
    expect(backEdges(docOf(LOOP_NODES, ORDERED([4, 0, 1, 2, 3])))).toEqual([0])
    expect(backEdges(docOf(LOOP_NODES, ORDERED([3, 4, 1, 0, 2])))).toEqual([1])
  })

  it('counts a cycle no input can reach', () => {
    // The Python sweeps every node as a root after the inputs, so a detached
    // cycle is still counted rather than silently free.
    const nodes = [
      node('idea', 'input', { field: nodeId('idea'), label: null, max_chars: 2000, required: true }),
      node('report', 'output', { body_key: 'markdown_body', source: null }),
      node('spin', 'router', {
        branches: [
          { label: nodeId('yes'), op: 'eq', key: nodeId('decision'), value: 'approve' },
          { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
        ],
      }),
      node('wheel', 'agent', MARKET_QUERY_INPUTS),
    ]
    const edges = [
      edge('e1', 'idea', 'out', 'report'),
      edge('e2', 'spin', 'yes', 'wheel'),
      edge('e3', 'wheel', 'out', 'spin'),
    ]
    expect(backEdges(docOf(nodes, edges))).toEqual([2])
  })

  it('counts a self edge', () => {
    const nodes = [
      node('idea', 'input', { field: nodeId('idea'), label: null, max_chars: 2000, required: true }),
      node('spin', 'router', {
        branches: [
          { label: nodeId('yes'), op: 'eq', key: nodeId('decision'), value: 'approve' },
          { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
        ],
      }),
    ]
    const edges = [edge('e1', 'idea', 'out', 'spin'), edge('e2', 'spin', 'yes', 'spin')]
    expect(backEdges(docOf(nodes, edges))).toEqual([1])
  })

  it('does not double-count two parallel edges into one node', () => {
    const nodes = [
      node('idea', 'input', { field: nodeId('idea'), label: null, max_chars: 2000, required: true }),
      node('confirm', 'gate', {
        message: 'ok?',
        editable_fields: [],
        max_turns: 1,
        expiry_seconds: 1800,
      }),
      node('market', 'agent', MARKET_QUERY_INPUTS),
    ]
    const edges = [
      edge('e1', 'idea', 'out', 'confirm'),
      edge('e2', 'confirm', 'approve', 'market'),
      edge('e3', 'confirm', 'revise', 'market'),
      edge('e4', 'market', 'out', 'confirm'),
    ]
    expect(backEdges(docOf(nodes, edges))).toEqual([3])
  })

  it('skips an edge pointing at an id no node has', () => {
    const nodes = [
      node('idea', 'input', { field: nodeId('idea'), label: null, max_chars: 2000, required: true }),
      node('report', 'output', { body_key: 'markdown_body', source: null }),
    ]
    const edges = [edge('e1', 'idea', 'out', 'ghost'), edge('e2', 'idea', 'out', 'report')]
    expect(backEdges(docOf(nodes, edges))).toEqual([])
  })

  it('agrees with the python on the reference document', () => {
    // Measured, not derived: `back_edge_indices(REFERENCE_DOC)` answered `(9,)`
    // - the `cap` router's `otherwise` branch closing the loop back to
    // `market`. The whole point of a mirror is that this number comes from the
    // original.
    expect(backEdges(REFERENCE_DOC)).toEqual([9])
  })
})

describe('topoOrder terminates on a graph with cycles', () => {
  it('puts every node after the ones that feed it', () => {
    const order = topoOrder(REFERENCE_DOC)
    const at = (id: string) => order.indexOf(id as NodeId)
    expect(at('idea')).toBeLessThan(at('market'))
    expect(at('market')).toBeLessThan(at('summarise'))
    expect(at('summarise')).toBeLessThan(at('blend'))
    expect(at('blend')).toBeLessThan(at('confirm'))
    expect(at('confirm')).toBeLessThan(at('spin'))
    expect(at('spin')).toBeLessThan(at('report'))
  })

  it('returns every node exactly once on a cyclic graph, without hanging', () => {
    const order = topoOrder(docOf(LOOP_NODES, LOOP_EDGES))
    expect(order).toHaveLength(LOOP_NODES.length)
    expect(new Set(order).size).toBe(LOOP_NODES.length)
    expect(order.indexOf(nodeId('idea'))).toBe(0)
  })

  it('keeps a detached node rather than dropping it', () => {
    const nodes = [...LOOP_NODES, node('orphan', 'transform', { op: 'to_json', args: {} })]
    expect(topoOrder(docOf(nodes, LOOP_EDGES))).toContain('orphan')
  })

  it('breaks a tie in EDGE order, not node order', () => {
    // Two clients rendering one document must not disagree about what "first"
    // means, so this mirrors the Python's FIFO queue exactly rather than
    // sorting - and the mirror is worth having because the answer is not the
    // obvious one. `left` is declared before `right` among the NODES and comes
    // out second, because the seed queue holds only the zero-indegree nodes and
    // everything after that arrives in the order the EDGES named it. Run
    // through the same Kahn pass in Python: `['idea', 'right', 'left']`.
    const nodes = [
      node('idea', 'input', { field: nodeId('idea'), label: null, max_chars: 2000, required: true }),
      node('left', 'transform', { op: 'to_json', args: {} }),
      node('right', 'transform', { op: 'to_json', args: {} }),
    ]
    const edges = [edge('e1', 'idea', 'out', 'right'), edge('e2', 'idea', 'out', 'left')]
    expect(topoOrder(docOf(nodes, edges))).toEqual(['idea', 'right', 'left'])
  })
})

describe('ancestorsOf and descendantsOf answer the loop advisory', () => {
  it('names every node an edge back to would close a loop through', () => {
    // `blend` is itself in the set, because the reference document already has
    // a loop (`cap` -> `market` -> `summarise` -> `blend` -> `confirm` ->
    // `cap`) and `blend` sits on it.
    const ancestors = ancestorsOf(REFERENCE_DOC, nodeId('blend'))
    expect([...ancestors].sort()).toEqual([
      'blend',
      'cap',
      'confirm',
      'idea',
      'market',
      'summarise',
    ])
  })

  it('excludes a node that is not on a cycle from its own sets', () => {
    expect(ancestorsOf(REFERENCE_DOC, nodeId('idea')).size).toBe(0)
    expect(descendantsOf(REFERENCE_DOC, nodeId('report')).size).toBe(0)
  })

  it('includes the node itself exactly when it sits on a cycle', () => {
    // Not an artefact of how the walk is seeded - it is the fact the rim is
    // there to show. `confirm` can be reached again from `confirm`.
    const looping = docOf(LOOP_NODES, LOOP_EDGES)
    expect(ancestorsOf(looping, nodeId('confirm')).has(nodeId('confirm'))).toBe(true)
    expect(ancestorsOf(looping, nodeId('market')).has(nodeId('market'))).toBe(false)
  })

  it('reads forward for descendants', () => {
    expect([...descendantsOf(REFERENCE_DOC, nodeId('confirm'))].sort()).toEqual([
      'blend',
      'cap',
      'confirm',
      'market',
      'report',
      'spin',
      'summarise',
    ])
  })

  it('ignores an edge with an endpoint no node has', () => {
    const nodes = [
      node('idea', 'input', { field: nodeId('idea'), label: null, max_chars: 2000, required: true }),
      node('report', 'output', { body_key: 'markdown_body', source: null }),
    ]
    const edges = [edge('e1', 'idea', 'out', 'ghost'), edge('e2', 'idea', 'out', 'report')]
    expect([...descendantsOf(docOf(nodes, edges), nodeId('idea'))]).toEqual(['report'])
  })
})

describe('remapIds re-mints a pasted fragment', () => {
  const counters = () => {
    let nodes = 0
    let edges = 0
    return {
      node: (previous: NodeId) => nodeId(`${previous}_copy${(nodes += 1)}`),
      edge: (previous: EdgeId) => edgeId(`${previous}_copy${(edges += 1)}`),
    }
  }

  it('mints a new id for every node and follows it into every reference', () => {
    const fragment = {
      nodes: [find(REFERENCE_DOC, 'market'), find(REFERENCE_DOC, 'summarise')],
      edges: [REFERENCE_DOC.edges[1]],
      joins: {},
    }
    const pasted = remapIds(fragment, counters())
    expect(pasted.nodes.map((entry) => entry.id)).toEqual(['market_copy1', 'summarise_copy2'])
    const config = pasted.nodes[1].config as AgentConfig
    expect(config.prompt_inputs.cached_evidence_block).toBe('${state.out__market_copy1}')
  })

  it('re-mints edge ids too', () => {
    // A paste back into the document it was copied from is the commonest paste
    // there is, and a kept edge id is a `duplicate-edge-id` on the first one.
    const fragment = {
      nodes: [find(REFERENCE_DOC, 'market'), find(REFERENCE_DOC, 'summarise')],
      edges: [REFERENCE_DOC.edges[1]],
      joins: {},
    }
    const pasted = remapIds(fragment, counters())
    expect(pasted.edges[0]).toMatchObject({
      id: 'e2_copy1',
      source: 'market_copy1',
      target: 'summarise_copy2',
    })
  })

  it('drops an edge whose other endpoint was not copied', () => {
    const fragment = {
      nodes: [find(REFERENCE_DOC, 'summarise')],
      edges: [REFERENCE_DOC.edges[1], REFERENCE_DOC.edges[2]],
      joins: {},
    }
    expect(remapIds(fragment, counters()).edges).toEqual([])
  })

  it('drops a joins entry whose node was not copied', () => {
    const fragment = {
      nodes: [find(REFERENCE_DOC, 'summarise')],
      edges: [],
      joins: { report: 'all' as const, summarise: 'all' as const },
    }
    expect(remapIds(fragment, counters()).joins).toEqual({ summarise_copy1: 'all' })
  })

  it('moves a gate turn counter through a paste as well', () => {
    const fragment = {
      nodes: [find(REFERENCE_DOC, 'confirm'), find(REFERENCE_DOC, 'cap')],
      edges: [REFERENCE_DOC.edges[5]],
      joins: {},
    }
    const pasted = remapIds(fragment, counters())
    const config = pasted.nodes[1].config as RouterConfig
    expect(config.branches[0].key).toBe('turns__confirm_copy1')
  })

  it('accepts a whole document as a fragment', () => {
    // A `BuilderDocument` IS a subgraph, structurally - which is what makes
    // "duplicate everything" and "paste a selection" the same code path.
    const pasted = remapIds(REFERENCE_DOC, counters())
    expect(pasted.nodes).toHaveLength(REFERENCE_DOC.nodes.length)
    expect(pasted.edges).toHaveLength(REFERENCE_DOC.edges.length)
  })
})
