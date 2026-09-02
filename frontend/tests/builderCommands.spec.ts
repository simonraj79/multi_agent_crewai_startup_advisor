import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BUILDER_SCHEMA_ID, documentId, edgeId, nodeId } from '../src/types/builder'
import type {
  AgentConfig,
  BuilderDocument,
  BuilderEdge,
  BuilderNode,
  GateConfig,
  InputConfig,
  NodeId,
  OutputConfig,
  RouterConfig,
} from '../src/types/builder'
import { useBuilderDocument } from '../src/composables/useBuilderDocument'

/**
 * The write path, the cascade and the ring.
 *
 * Four gaps, and the first three are the ones that make an undo stack either
 * trustworthy or actively dangerous:
 *
 * 1. **A delete that half-cascades produces a document the server refuses.**
 *    Deleting a node without its incident edges leaves `edge-unknown-endpoint`
 *    naming an id that is no longer anywhere on the canvas, and without its
 *    `joins` key leaves `join-unknown-node`. Cascading in a SEPARATE command
 *    would be worse than not cascading at all: one Ctrl+Z would restore the
 *    edges around a node that is still deleted.
 * 2. **A per-frame commit destroys the history in one gesture.** Vue Flow emits
 *    a change per animation frame; at 60fps a two-second drag is 120 entries in
 *    a 200-entry ring, and everything the author did before picking the node up
 *    is gone. `moveNodes` takes the END of a drag, which is why this is asserted
 *    on the count and not on the positions.
 * 3. **Coalescing that never ends is one undo step for a whole session.** The
 *    600ms window and `sealHistory()` are the two things that end a burst, and a
 *    burst that survives a blur would merge a label edit with the next
 *    unrelated one.
 * 4. **A mutated document rewrites history as well as the present.** The ring
 *    holds references, so `doc.nodes.push(...)` anywhere would edit every
 *    snapshot that shares the array. `import.meta.env.DEV` deep-freezes, and
 *    this file asserts the freeze rather than the intention.
 */

/* --- a document with a reference in every place a rename has to move ------ */

const AGENT: AgentConfig = {
  tier: 'cheap',
  max_iter: 2,
  guardrail_max_retries: 2,
  prompt_inputs: { brief: '${state.out__market}' },
  agent_id: nodeId('scoper'),
  tools: [],
}

const GATE: GateConfig = {
  message: 'Confirm the scope before anything is billed.',
  editable_fields: [],
  max_turns: 1,
  expiry_seconds: 1800,
}

const INPUT: InputConfig = {
  field: nodeId('idea'),
  label: null,
  max_chars: 2000,
  required: true,
}

const OUTPUT: OutputConfig = { body_key: 'markdown_body', source: '${state.out__writer}' }

const ROUTER: RouterConfig = {
  branches: [
    { label: nodeId('again'), op: 'lt', key: nodeId('turns__confirm'), value: 3 },
    { label: nodeId('onward'), op: 'otherwise', key: null, value: null },
  ],
}

function node(
  id: string,
  kind: BuilderNode['kind'],
  config: BuilderNode['config'],
  x = 0,
  y = 0,
): BuilderNode {
  return {
    id: nodeId(id),
    kind,
    label: id,
    position: { x, y },
    config,
  } as BuilderNode
}

function edge(id: string, source: string, target: string, port = 'out'): BuilderEdge {
  return {
    id: edgeId(id),
    source: nodeId(source),
    source_port: port,
    target: nodeId(target),
    target_port: 'in',
  }
}

/**
 * market -> writer -> out, with a gate and a router closing a loop, a `joins`
 * key on the node that has two predecessors, and a `${state.out__market}`
 * reference inside the writer's prompt inputs.
 */
function sample(): BuilderDocument {
  return {
    schema: BUILDER_SCHEMA_ID,
    id: documentId('ug_0a1b2c3d'),
    name: 'Sample',
    version: 3,
    input_field: nodeId('idea'),
    nodes: [
      node('idea', 'input', INPUT, 0, 0),
      node('confirm', 'gate', GATE, 0, 100),
      node('market', 'agent', { ...AGENT, prompt_inputs: {} }, 0, 200),
      node('writer', 'agent', AGENT, 0, 300),
      node('route', 'router', ROUTER, 0, 400),
      node('out', 'output', OUTPUT, 0, 500),
    ],
    edges: [
      edge('e1', 'idea', 'confirm'),
      edge('e2', 'confirm', 'market', 'approve'),
      edge('e3', 'market', 'writer'),
      edge('e4', 'confirm', 'writer', 'revise'),
      edge('e5', 'writer', 'route'),
      edge('e6', 'route', 'out', 'onward'),
    ],
    joins: { writer: 'all' },
    budget: null,
  }
}

describe('the document is replaced rather than mutated', () => {
  it('freezes every version, so a stray write throws instead of rewriting history', () => {
    const store = useBuilderDocument(sample())
    expect(Object.isFrozen(store.doc.value)).toBe(true)
    expect(Object.isFrozen(store.doc.value.nodes)).toBe(true)
    expect(Object.isFrozen(store.doc.value.nodes[0].config)).toBe(true)
    expect(() => {
      ;(store.doc.value as { name: string }).name = 'renamed by hand'
    }).toThrow()
  })

  it('keeps the previous version intact on the ring after a commit', () => {
    const store = useBuilderDocument(sample())
    const before = store.doc.value
    store.setName('Renamed')
    expect(store.doc.value).not.toBe(before)
    expect(before.name).toBe('Sample')
    store.undo()
    expect(store.doc.value).toBe(before)
  })

  it('records nothing when a commit would change nothing', () => {
    const store = useBuilderDocument(sample())
    store.commit('no-op', store.doc.value)
    expect(store.depth.value).toBe(0)
    expect(store.canUndo.value).toBe(false)
  })
})

describe('deleting cascades to edges and joins in one command', () => {
  it('takes every incident edge with the node', () => {
    const store = useBuilderDocument(sample())
    store.deleteSelection([nodeId('writer')])
    const ids = store.doc.value.edges.map((each) => each.id)
    expect(ids).toEqual(['e1', 'e2', 'e6'])
  })

  it('takes the orphaned joins key with it', () => {
    const store = useBuilderDocument(sample())
    store.deleteSelection([nodeId('writer')])
    expect(store.doc.value.joins).toEqual({})
  })

  it('leaves a joins key whose node survives, because the count is the server to make', () => {
    const store = useBuilderDocument(sample())
    // `market` is one of `writer`'s two predecessors. Dropping the join here
    // would be the client deciding `join-single-predecessor`, which is a
    // warning `bounds.py` owns.
    store.deleteSelection([nodeId('market')])
    expect(store.doc.value.joins).toEqual({ writer: 'all' })
  })

  it('restores nodes, edges and joins together on one undo', () => {
    const store = useBuilderDocument(sample())
    const before = store.doc.value
    store.deleteSelection([nodeId('writer')])
    expect(store.depth.value).toBe(1)
    store.undo()
    expect(store.doc.value).toBe(before)
    expect(store.doc.value.nodes).toHaveLength(6)
    expect(store.doc.value.edges).toHaveLength(6)
    expect(store.doc.value.joins).toEqual({ writer: 'all' })
  })

  it('names the cascade in the label, so the undo tooltip is not a surprise', () => {
    const store = useBuilderDocument(sample())
    store.deleteSelection([nodeId('writer')])
    expect(store.undoLabel.value).toBe('Delete 1 node and 3 edges')
  })
})

describe('a node drag is exactly one commit', () => {
  it('records one step for a three-node move', () => {
    const store = useBuilderDocument(sample())
    store.moveNodes([
      { id: nodeId('idea'), position: { x: 20, y: 40 } },
      { id: nodeId('market'), position: { x: 40, y: 60 } },
      { id: nodeId('writer'), position: { x: 60, y: 80 } },
    ])
    expect(store.depth.value).toBe(1)
    expect(store.undoLabel.value).toBe('Move 3 nodes')
  })

  it('rounds every position, because `Position` is declared int and 120.5 is a 422', () => {
    const store = useBuilderDocument(sample())
    store.moveNodes([{ id: nodeId('idea'), position: { x: 120.5, y: -3.4 } }])
    expect(store.doc.value.nodes[0].position).toEqual({ x: 121, y: -3 })
  })

  it('commits nothing when the drag ended where it started', () => {
    const store = useBuilderDocument(sample())
    store.moveNodes([{ id: nodeId('idea'), position: { x: 0, y: 0 } }])
    expect(store.depth.value).toBe(0)
  })
})

describe('coalescing', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('merges consecutive edits of one field into one undo step', () => {
    const store = useBuilderDocument(sample())
    const before = store.doc.value
    store.setLabel(nodeId('market'), 'M')
    vi.advanceTimersByTime(120)
    store.setLabel(nodeId('market'), 'Ma')
    vi.advanceTimersByTime(120)
    store.setLabel(nodeId('market'), 'Mar')

    expect(store.depth.value).toBe(1)
    store.undo()
    // Back to before the burst began, not to the penultimate keystroke.
    expect(store.doc.value).toBe(before)
  })

  it('starts a new step once the 600ms window lapses', () => {
    const store = useBuilderDocument(sample())
    store.setLabel(nodeId('market'), 'M')
    vi.advanceTimersByTime(700)
    store.setLabel(nodeId('market'), 'Ma')
    expect(store.depth.value).toBe(2)
  })

  it('refuses to merge across sealHistory(), which is what a blur calls', () => {
    const store = useBuilderDocument(sample())
    store.setLabel(nodeId('market'), 'M')
    store.sealHistory()
    store.setLabel(nodeId('market'), 'Ma')
    expect(store.depth.value).toBe(2)
  })

  it('does not merge two different fields even inside the window', () => {
    const store = useBuilderDocument(sample())
    store.setLabel(nodeId('market'), 'M')
    store.setLabel(nodeId('writer'), 'W')
    expect(store.depth.value).toBe(2)
  })

  it('coalesces consecutive nudges of the same selection', () => {
    const store = useBuilderDocument(sample())
    store.moveNodes([{ id: nodeId('idea'), position: { x: 20, y: 0 } }], { coalesce: true })
    store.moveNodes([{ id: nodeId('idea'), position: { x: 40, y: 0 } }], { coalesce: true })
    expect(store.depth.value).toBe(1)
    expect(store.doc.value.nodes[0].position.x).toBe(40)
  })
})

describe('the snapshot ring', () => {
  /**
   * `commit` directly rather than `setName`, and that is the point rather than
   * a convenience: `setName` coalesces under `doc:name`, so 250 renames inside
   * one 600ms window are ONE undo step. Filling the ring needs 250 distinct
   * steps, which is what an uncoalesced commit is.
   */
  function fill(store: ReturnType<typeof useBuilderDocument>, count: number): void {
    for (let index = 0; index < count; index += 1) {
      store.commit(`Step ${index}`, { ...store.doc.value, name: `Name ${index}` })
    }
  }

  it('bounds at 200 entries', () => {
    const store = useBuilderDocument(sample())
    fill(store, 250)
    expect(store.depth.value).toBe(200)
  })

  it('drops the oldest, so the 200 kept are the most recent', () => {
    const store = useBuilderDocument(sample())
    fill(store, 250)
    for (let index = 0; index < 200; index += 1) store.undo()
    expect(store.canUndo.value).toBe(false)
    // 250 commits, 200 undone: the floor is the state after the 50th.
    expect(store.doc.value.name).toBe('Name 49')
  })

  it('clears the redo future when a new commit arrives', () => {
    const store = useBuilderDocument(sample())
    store.setName('One')
    store.setName('Two')
    store.undo()
    expect(store.canRedo.value).toBe(true)
    store.setName('Three')
    expect(store.canRedo.value).toBe(false)
    expect(store.redoDepth.value).toBe(0)
  })

  it('replays a redo and reports the label of what it will replay', () => {
    const store = useBuilderDocument(sample())
    store.deleteSelection([nodeId('out')])
    store.undo()
    expect(store.redoLabel.value).toBe('Delete 1 node and 1 edge')
    store.redo()
    expect(store.doc.value.nodes.some((each) => each.id === 'out')).toBe(false)
  })
})

describe('rename is one step and moves every reference with it', () => {
  it('rewrites edges, joins and the state reference in one commit', () => {
    const store = useBuilderDocument(sample())
    store.renameNode(nodeId('market'), nodeId('market_landscape'))

    expect(store.depth.value).toBe(1)
    expect(store.doc.value.edges.map((each) => each.source)).toContain('market_landscape')
    const writer = store.doc.value.nodes.find((each) => each.id === 'writer')
    expect((writer?.config as AgentConfig).prompt_inputs.brief).toBe(
      '${state.out__market_landscape}',
    )
  })

  it('moves a gate turn counter, which is the half that fails silently', () => {
    const store = useBuilderDocument(sample())
    store.renameNode(nodeId('confirm'), nodeId('confirm_scope'))
    const route = store.doc.value.nodes.find((each) => each.id === 'route')
    expect((route?.config as RouterConfig).branches[0].key).toBe('turns__confirm_scope')
  })
})

describe('patchConfig', () => {
  it('refuses a key the node kind does not declare, rather than writing it', () => {
    const store = useBuilderDocument(sample())
    expect(() => store.patchConfig(nodeId('route'), { tier: 'escalation' })).toThrow(
      /a router node has no 'tier'/,
    )
    expect(store.depth.value).toBe(0)
  })

  it('coalesces a single-field patch under node:<id>:<field>', () => {
    const store = useBuilderDocument(sample())
    store.patchConfig(nodeId('market'), { max_iter: 3 })
    store.patchConfig(nodeId('market'), { max_iter: 4 })
    expect(store.depth.value).toBe(1)
    store.patchConfig(nodeId('market'), { guardrail_max_retries: 1 })
    expect(store.depth.value).toBe(2)
  })

  it('accepts an explicit null to force a distinct step', () => {
    const store = useBuilderDocument(sample())
    store.patchConfig(nodeId('market'), { max_iter: 3 }, null)
    store.patchConfig(nodeId('market'), { max_iter: 4 }, null)
    expect(store.depth.value).toBe(2)
  })
})

describe('a node and the edge that reaches it are one commit', () => {
  it('mints the edge id and one undo removes both', () => {
    const store = useBuilderDocument(sample())
    const fresh = node('market_two', 'agent', AGENT, 200, 200)
    store.addNode(fresh, {
      edge: { source: nodeId('confirm'), source_port: 'approve', target: nodeId('market_two') },
      label: 'Add market two',
    })

    expect(store.depth.value).toBe(1)
    expect(store.doc.value.edges.map((each) => each.id)).toContain('e7')
    store.undo()
    expect(store.doc.value.nodes.some((each) => each.id === 'market_two')).toBe(false)
    expect(store.doc.value.edges).toHaveLength(6)
  })

  it('mints the first FREE edge id rather than counting', () => {
    const store = useBuilderDocument(sample())
    store.deleteEdges([edgeId('e3')])
    const minted = store.addEdge({
      source: nodeId('market'),
      source_port: 'out',
      target: nodeId('writer'),
    })
    expect(minted).toBe('e3')
  })
})

describe('dirty', () => {
  it('is false on a loaded document and true after any commit', () => {
    const store = useBuilderDocument(sample())
    expect(store.dirty.value).toBe(false)
    store.setName('Edited')
    expect(store.dirty.value).toBe(true)
  })

  it('goes clean again when an undo returns to the saved version', () => {
    const store = useBuilderDocument(sample())
    store.setName('Edited')
    store.undo()
    expect(store.dirty.value).toBe(false)
  })

  it('is true for a template, which nothing has stored', () => {
    const store = useBuilderDocument(sample())
    store.applyTemplate({ ...sample(), name: 'From a template' })
    expect(store.dirty.value).toBe(true)
    expect(store.canUndo.value).toBe(false)
  })
})

describe('the joins declaration', () => {
  it('writes only `all`, and deletes the key rather than writing `any`', () => {
    const store = useBuilderDocument(sample())
    store.setJoin(nodeId('route') as NodeId, true)
    expect(store.doc.value.joins).toEqual({ writer: 'all', route: 'all' })
    store.setJoin(nodeId('writer') as NodeId, false)
    expect(store.doc.value.joins).toEqual({ route: 'all' })
  })
})
