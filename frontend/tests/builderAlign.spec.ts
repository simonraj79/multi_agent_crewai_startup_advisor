/**
 * Section 4.3's align / distribute toolbar, and the two projection fields that
 * were declared and written by nothing.
 *
 * All four subjects here shipped as spec sentences with no implementation
 * behind them, and all four were invisible to a green suite for the same
 * reason: a jsdom mount asserts that markup exists, and none of these is
 * markup. `SelectionToolbar` did not exist at all; `is-landing` was a keyframe,
 * a rule and a reduced-motion exemption over a class no file wrote; `inbound`
 * was an optional the canvas never supplied, so the fan-in glyph could only
 * ever be switched OFF.
 */
import { shallowRef } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SelectionToolbar from '../src/components/builder/SelectionToolbar.vue'
import { ALIGN_MODES, useBuilderCanvas } from '../src/composables/useBuilderCanvas'
import type {
  CanvasDocumentStore,
  CanvasViewportBridge,
  EdgeOrigin,
  NodeMove,
} from '../src/composables/useBuilderCanvas'
import { edgeId, nodeId } from '../src/types/builder'
import type { BuilderDocument, BuilderEdge, BuilderNode, EdgeId, NodeId } from '../src/types/builder'

function agentNode(id: string, x: number, y: number): BuilderNode {
  return {
    id: nodeId(id),
    kind: 'agent',
    label: id,
    position: { x, y },
    config: {
      tier: 'cheap',
      max_iter: 2,
      guardrail_max_retries: 2,
      prompt_inputs: {},
      agent_id: nodeId('scoper'),
      tools: [],
    },
  }
}

function edge(id: string, source: string, target: string): BuilderEdge {
  return {
    id: edgeId(id),
    source: nodeId(source),
    source_port: 'out',
    target: nodeId(target),
    target_port: 'in',
  }
}

function document(nodes: BuilderNode[], edges: BuilderEdge[] = []): BuilderDocument {
  return {
    schema: 'builder.flow/v1',
    id: 'ug_0000abcd' as BuilderDocument['id'],
    name: 'under test',
    version: 3,
    input_field: nodeId('idea'),
    nodes,
    edges,
    joins: {},
    budget: null,
  }
}

/** Records commits, so "ONE commit each" is an assertion rather than a hope. */
class RecordingStore implements CanvasDocumentStore {
  readonly doc = shallowRef<BuilderDocument>(document([]))
  readonly commits: string[] = []
  readonly moves: NodeMove[][] = []

  addNode(): void {
    this.commits.push('addNode')
  }

  addEdge(_origin: EdgeOrigin, _target: NodeId): void {
    this.commits.push('addEdge')
  }

  moveNodes(moves: readonly NodeMove[]): void {
    this.commits.push('moveNodes')
    this.moves.push([...moves])
    // Applied, so distribute's idempotence is measured against a document that
    // actually moved rather than asserted about one that never did.
    const byId = new Map(moves.map((move) => [move.id as string, move.position]))
    this.doc.value = {
      ...this.doc.value,
      nodes: this.doc.value.nodes.map((node) =>
        byId.has(node.id) ? { ...node, position: byId.get(node.id)! } : node,
      ),
    }
  }

  deleteSelection(_nodes: readonly NodeId[], _edges: readonly EdgeId[]): void {
    this.commits.push('deleteSelection')
  }

  setEdgePort(): void {
    this.commits.push('setEdgePort')
  }

  retargetEdge(): void {
    this.commits.push('retargetEdge')
  }

  setJoin(): void {
    this.commits.push('setJoin')
  }
}

function bridge(
  sizes: Record<string, { width: number; height: number }> = {},
): CanvasViewportBridge {
  return {
    screenToFlowCoordinate: (point) => point,
    fitView: () => undefined,
    setCenter: () => undefined,
    zoomTo: () => undefined,
    getViewport: () => ({ x: 0, y: 0, zoom: 1 }),
    getPaneSize: () => ({ width: 800, height: 600 }),
    getNodeSize: (id) => sizes[id] ?? { width: 240, height: 100 },
  }
}

function canvasOver(
  doc: BuilderDocument,
  sizes?: Record<string, { width: number; height: number }>,
) {
  const store = new RecordingStore()
  store.doc.value = doc
  const canvas = useBuilderCanvas({ document: store })
  canvas.attachViewport(bridge(sizes))
  return { canvas, store }
}

/** Where each node ended up, keyed by id, from the last recorded move. */
function landedAt(store: RecordingStore): Record<string, { x: number; y: number }> {
  const last = store.moves[store.moves.length - 1] ?? []
  return Object.fromEntries(last.map((move) => [move.id as string, move.position]))
}

describe('align moves a selection onto the anchor line, in one commit', () => {
  it('aligns left to the ANCHOR rather than to the leftmost node', () => {
    // The whole reason `anchorId` exists. "Align left" over three nodes has
    // three defensible answers, and a control that picks one silently is one an
    // author cannot predict; the anchor ring is drawn at full strength against
    // the members' .6, so the winner is visible before the press.
    const { canvas, store } = canvasOver(
      document([agentNode('a', 100, 0), agentNode('b', 20, 200), agentNode('c', 300, 400)]),
    )
    canvas.setSelection([nodeId('a'), nodeId('b'), nodeId('c')])
    canvas.anchorId.value = nodeId('a')

    canvas.alignSelection('left')

    expect(store.commits).toEqual(['moveNodes'])
    const at = landedAt(store)
    expect(at.a.x).toBe(100)
    expect(at.b.x).toBe(100)
    expect(at.c.x).toBe(100)
    // The other axis is untouched: align left is not "move to a point".
    expect([at.a.y, at.b.y, at.c.y]).toEqual([0, 200, 400])
  })

  it('falls back to the extreme edge when a marquee selected without an anchor', () => {
    const { canvas, store } = canvasOver(document([agentNode('a', 100, 0), agentNode('b', 20, 200)]))
    canvas.setSelection([nodeId('a'), nodeId('b')])
    canvas.anchorId.value = null
    canvas.alignSelection('left')
    expect(landedAt(store).a.x).toBe(20)
  })

  it('aligns bottom against each card MEASURED height, not an assumed one', () => {
    // The reason `getNodeSize` was added to the bridge. A gate reserves a
    // labelled port footer and an agent now carries a second summary line, so
    // one assumed height makes align-bottom align-bottom-ish.
    const { canvas, store } = canvasOver(
      document([agentNode('tall', 0, 0), agentNode('short', 400, 0)]),
      { tall: { width: 240, height: 160 }, short: { width: 240, height: 80 } },
    )
    canvas.setSelection([nodeId('tall'), nodeId('short')])
    canvas.anchorId.value = nodeId('tall')
    canvas.alignSelection('bottom')
    const at = landedAt(store)
    // Bottom edges agree: 0 + 160 === 80 + 80.
    expect(at.tall.y + 160).toBe(at.short.y + 80)
    expect(at.short.y).toBe(80)
  })

  it('writes integers only, because position.x is int server-side (R12)', () => {
    const { canvas, store } = canvasOver(
      document([agentNode('a', 0, 0), agentNode('b', 101, 0), agentNode('c', 202, 0)]),
    )
    canvas.setSelection([nodeId('a'), nodeId('b'), nodeId('c')])
    canvas.anchorId.value = null
    canvas.alignSelection('centerX')
    for (const move of store.moves[0]) {
      expect(Number.isInteger(move.position.x)).toBe(true)
      expect(Number.isInteger(move.position.y)).toBe(true)
    }
  })

  it('declines a selection of one, so the toolbar can never commit a no-op', () => {
    const { canvas, store } = canvasOver(document([agentNode('a', 0, 0)]))
    canvas.setSelection([nodeId('a')])
    for (const mode of ALIGN_MODES) canvas.alignSelection(mode)
    expect(store.commits).toEqual([])
  })
})

describe('distribute equalises the GAPS, once', () => {
  it('spreads three cards evenly and leaves the two extremes alone', () => {
    const { canvas, store } = canvasOver(
      document([agentNode('a', 0, 0), agentNode('b', 260, 0), agentNode('c', 1000, 0)]),
    )
    canvas.setSelection([nodeId('a'), nodeId('b'), nodeId('c')])
    canvas.distributeSelection('horizontal')
    const at = landedAt(store)
    expect(at.a.x).toBe(0)
    expect(at.c.x).toBe(1000)
    // Span 1240 over three 240-wide cards, so each gap is (1240 - 720) / 2.
    expect(at.b.x).toBe(500)
  })

  it('is idempotent - pressing it twice is not a slow drift', () => {
    const { canvas, store } = canvasOver(
      document([agentNode('a', 0, 0), agentNode('b', 260, 0), agentNode('c', 1000, 0)]),
    )
    canvas.setSelection([nodeId('a'), nodeId('b'), nodeId('c')])
    canvas.distributeSelection('horizontal')
    const first = landedAt(store)
    canvas.distributeSelection('horizontal')
    expect(landedAt(store)).toEqual(first)
  })

  it('needs three: two nodes already have exactly one gap between them', () => {
    const { canvas, store } = canvasOver(document([agentNode('a', 0, 0), agentNode('b', 500, 0)]))
    canvas.setSelection([nodeId('a'), nodeId('b')])
    canvas.distributeSelection('horizontal')
    canvas.distributeSelection('vertical')
    expect(store.commits).toEqual([])
  })

  it('declines rather than shuffling when the cards already overlap', () => {
    // A negative gap is arithmetically fine and visually a shuffle. Doing
    // something the author did not ask for is worse than doing nothing.
    const { canvas, store } = canvasOver(
      document([agentNode('a', 0, 0), agentNode('b', 10, 0), agentNode('c', 20, 0)]),
    )
    canvas.setSelection([nodeId('a'), nodeId('b'), nodeId('c')])
    canvas.distributeSelection('horizontal')
    expect(store.commits).toEqual([])
  })
})

describe('the toolbar is eight buttons and a position, and computes nothing', () => {
  const rect = { x: 400, y: 300, width: 200, height: 120 }

  it('renders all six aligns and both distributes, each with a real name', () => {
    const wrapper = mount(SelectionToolbar, { props: { rect, count: 3 } })
    const names = wrapper.findAll('button').map((button) => button.attributes('aria-label'))
    expect(names).toEqual([
      'Align left',
      'Align centres horizontally',
      'Align right',
      'Align top',
      'Align centres vertically',
      'Align bottom',
      'Distribute horizontally',
      'Distribute vertically',
    ])
  })

  it('emits the mode and lets the composable own the geometry', async () => {
    const wrapper = mount(SelectionToolbar, { props: { rect, count: 3 } })
    await wrapper.findAll('button')[2].trigger('click')
    await wrapper.findAll('button')[7].trigger('click')
    expect(wrapper.emitted('align')).toEqual([['right']])
    expect(wrapper.emitted('distribute')).toEqual([['vertical']])
  })

  it('disables distribute below three with the reason in the title', () => {
    const wrapper = mount(SelectionToolbar, { props: { rect, count: 2 } })
    const distribute = wrapper.findAll('button')[6]
    expect(distribute.attributes('disabled')).toBeDefined()
    expect(distribute.attributes('title')).toContain('needs three or more nodes')
    // Aligns stay live: two nodes is exactly when align is most useful.
    expect(wrapper.findAll('button')[0].attributes('disabled')).toBeUndefined()
  })

  it('clamps into the pane rather than floating off the top of it', () => {
    // A marquee across a tall graph leaves the selection top edge above the
    // viewport, which is the common case rather than the corner one.
    const wrapper = mount(SelectionToolbar, {
      props: { rect: { x: 100, y: -900, width: 200, height: 120 }, count: 3 },
    })
    expect(wrapper.attributes('style')).toContain('top: 8px')
  })
})

describe('the two projection fields that were written by nothing', () => {
  it('counts inbound edges, so the join glyph is offerable and not just revocable', () => {
    const { canvas } = canvasOver(
      document(
        [agentNode('a', 0, 0), agentNode('b', 0, 200), agentNode('join', 0, 400)],
        [edge('e1', 'a', 'join'), edge('e2', 'b', 'join')],
      ),
    )
    const byId = new Map(canvas.nodes.value.map((node) => [node.id, node.data]))
    expect(byId.get('join')!.inbound).toBe(2)
    expect(byId.get('a')!.inbound).toBe(0)
  })

  it('flags an arriving node as landing, and only the arriving one', async () => {
    vi.useFakeTimers()
    const store = new RecordingStore()
    store.doc.value = document([agentNode('a', 0, 0)])
    const canvas = useBuilderCanvas({ document: store })
    // The first document is not an arrival: a sixteen-node template should
    // settle onto the canvas, not stage sixteen entrances at once.
    expect(canvas.nodes.value[0].data.landing).toBe(false)

    store.doc.value = document([agentNode('a', 0, 0), agentNode('b', 300, 0)])
    await Promise.resolve()
    const byId = new Map(canvas.nodes.value.map((node) => [node.id, node.data.landing]))
    expect(byId.get('b')).toBe(true)
    expect(byId.get('a')).toBe(false)

    vi.advanceTimersByTime(400)
    await Promise.resolve()
    expect(canvas.nodes.value.every((node) => node.data.landing === false)).toBe(true)
    vi.useRealTimers()
  })

  it('does not flag a MOVE as an arrival', async () => {
    vi.useFakeTimers()
    const store = new RecordingStore()
    store.doc.value = document([agentNode('a', 0, 0)])
    const canvas = useBuilderCanvas({ document: store })
    store.doc.value = document([agentNode('a', 500, 500)])
    await Promise.resolve()
    expect(canvas.nodes.value[0].data.landing).toBe(false)
    vi.useRealTimers()
  })
})
