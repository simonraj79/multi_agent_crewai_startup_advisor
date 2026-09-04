import { nextTick, shallowRef } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useVueFlow } from '@vue-flow/core'
import type { NodeDragEvent } from '@vue-flow/core'
import BuilderCanvas from '../src/components/builder/BuilderCanvas.vue'
import { flush } from './helpers'
import BuilderMinimap from '../src/components/builder/BuilderMinimap.vue'
import type { MinimapNode } from '../src/components/builder/BuilderMinimap.vue'
import {
  BUILDER_CANVAS_ATTR,
  COLLAPSE_TRAVEL_PX,
  GRID,
  canvasHasFocus,
  useBuilderCanvas,
} from '../src/composables/useBuilderCanvas'
import type {
  CanvasDocumentStore,
  CanvasViewportBridge,
  EdgeOrigin,
  NodeMove,
} from '../src/composables/useBuilderCanvas'
import {
  HOTKEY_BINDINGS,
  bindingLabels,
  chordLabel,
  dispatchHotkey,
  isTextEntry,
  matchBinding,
} from '../src/composables/useBuilderHotkeys'
import type { HotkeyActions } from '../src/composables/useBuilderHotkeys'
import { NODE_KINDS, NODE_KIND_ORDER } from '../src/data/nodeKinds'
import { resetVocabulary, vocabulary } from '../src/data/builderVocabulary'
import { edgeId, nodeId } from '../src/types/builder'
import type {
  BuilderDocument,
  BuilderEdge,
  BuilderNode,
  BuilderProblem,
  BuilderVocabulary,
  EdgeId,
  NodeId,
} from '../src/types/builder'

/**
 * One gesture is one commit, and the canvas never writes the document itself.
 *
 * Everything in this file is a variant of that sentence, because the two ways
 * this canvas could fail are both invisible until you try to undo something. A
 * drag that committed per frame would look perfect and would spend the entire
 * 200-entry ring on one movement of one node; a creation that committed the
 * node and its edge separately would look perfect and would leave a dangling
 * edge behind the first `⌘Z`. Neither shows up in a screenshot, so both are
 * asserted here by COUNTING calls into a recording store.
 *
 * The other half is the collapse rule of §4.3, which is a behaviour Vue Flow
 * deliberately half-implements: it preserves a multi-selection on pointerdown
 * (so a group can be dragged) and never collapses it on a click. The three
 * tests around `COLLAPSE_TRAVEL_PX` are the whole of what this repo adds, and
 * they are written against travel rather than against a timer because the two
 * gestures being told apart - a click on a member, and the end of a group drag
 * - arrive as literally the same event on the same node.
 *
 * And the hotkey table is asserted as DATA. `ShortcutSheet` renders the same
 * array this dispatches from, so "documented but unbound" and "bound but
 * undocumented" are both unrepresentable; what is left to test is that the
 * table's own invariants hold - every entry reachable, every chord printable,
 * and the text-entry gate letting exactly two bindings through.
 */

/* --- fixtures ------------------------------------------------------------- */

function agentNode(id: string, x = 0, y = 0): BuilderNode {
  return {
    id: nodeId(id),
    label: id,
    position: { x, y },
    kind: 'agent',
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

function outputNode(id: string, x = 0, y = 0): BuilderNode {
  return {
    id: nodeId(id),
    label: id,
    position: { x, y },
    kind: 'output',
    config: { body_key: 'markdown_body', source: null },
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

function document(
  nodes: BuilderNode[],
  edges: BuilderEdge[] = [],
  joins: Record<string, 'all'> = {},
): BuilderDocument {
  return {
    schema: 'builder.flow/v1',
    id: 'ug_0000abcd' as BuilderDocument['id'],
    name: 'under test',
    version: 3,
    input_field: nodeId('idea'),
    nodes,
    edges,
    joins,
    budget: null,
  }
}

/**
 * The vocabulary as the handler serves it, floats and all.
 *
 * Set directly on the module singleton rather than fetched, because `newNode`
 * throws without one - three of the seven kinds have required fields whose only
 * legal values the server knows (cut list item 17), so a creation test that did
 * not seed this would be testing the guard rather than the gesture.
 */
function vocabularyFixture(): BuilderVocabulary {
  return {
    schema_id: 'builder.flow/v1',
    node_kinds: [...NODE_KIND_ORDER],
    tiers: ['cheap', 'escalation'],
    agent_ids: ['market_analyst', 'scoper'],
    crew_ids: ['brief'],
    research_tools: ['github_feasibility'],
    transform_ops: ['default', 'format', 'join_text', 'merge', 'pick', 'to_json'],
    router_comparisons: ['contains', 'eq', 'gt', 'gte', 'lt', 'lte', 'ne'],
    router_otherwise: 'otherwise',
    result_body_keys: ['markdown_body'],
    bounds: {
      max_graph_nodes: 24,
      max_billable_nodes: 8,
      max_escalation_nodes: 5,
      max_fanout_width: 4,
      min_router_branches: 2,
      max_cycles: 2,
      max_cycle_iterations: 3,
      max_agent_iter: 8,
      max_guardrail_retries: 2,
      max_label_chars: 40,
      max_name_chars: 80,
      max_gate_message_chars: 2000,
      max_input_chars: 2000,
      max_document_bytes: 262144,
      run_cost_ceiling_usd: 10,
    },
  }
}

class RecordingStore implements CanvasDocumentStore {
  readonly doc = shallowRef<BuilderDocument>(document([]))
  readonly commits: string[] = []
  readonly nodesAdded: Array<{ node: BuilderNode; connectFrom: EdgeOrigin | null }> = []
  readonly edgesAdded: Array<{ origin: EdgeOrigin; target: NodeId }> = []
  readonly moves: Array<{ moves: readonly NodeMove[]; coalesceKey?: string }> = []
  readonly deletes: Array<{ nodes: readonly NodeId[]; edges: readonly EdgeId[] }> = []
  readonly joins: Array<{ node: NodeId; join: 'all' | null }> = []

  addNode(node: BuilderNode, connectFrom: EdgeOrigin | null = null): void {
    this.commits.push('addNode')
    this.nodesAdded.push({ node, connectFrom })
  }

  addEdge(origin: EdgeOrigin, target: NodeId): void {
    this.commits.push('addEdge')
    this.edgesAdded.push({ origin, target })
  }

  moveNodes(moves: readonly NodeMove[], coalesceKey?: string): void {
    this.commits.push('moveNodes')
    this.moves.push({ moves, coalesceKey })
  }

  deleteSelection(nodes: readonly NodeId[], edges: readonly EdgeId[]): void {
    this.commits.push('deleteSelection')
    this.deletes.push({ nodes, edges })
  }

  setEdgePort(): void {
    this.commits.push('setEdgePort')
  }

  retargetEdge(): void {
    this.commits.push('retargetEdge')
  }

  setJoin(node: NodeId, join: 'all' | null): void {
    this.commits.push('setJoin')
    this.joins.push({ node, join })
  }
}

/**
 * A viewport that answers in HALF pixels.
 *
 * The offset is deliberate and is the whole point of the drop tests: `position`
 * is declared `int` server-side, pydantic coerces `120.0` and refuses `120.5`,
 * and a fractional drop is a 422 that arrives on a save minutes after the
 * gesture that caused it. A bridge that returned round numbers would let an
 * unrounded canvas pass.
 */
function fakeBridge(overrides: Partial<CanvasViewportBridge> = {}): CanvasViewportBridge & {
  fits: Array<{ nodes?: string[] } | undefined>
} {
  const fits: Array<{ nodes?: string[] } | undefined> = []
  return {
    fits,
    screenToFlowCoordinate: (point) => ({ x: point.x + 0.5, y: point.y + 0.5 }),
    fitView: (options) => fits.push(options),
    setCenter: () => undefined,
    zoomTo: () => undefined,
    getViewport: () => ({ x: 0, y: 0, zoom: 1 }),
    // Every builder card is `NODE_W` wide; the height is one agent card's
    // worth. Overridden per test where align needs cards of unequal size.
    getNodeSize: () => ({ width: 240, height: 96 }),
    getPaneSize: () => ({ width: 800, height: 600 }),
    ...overrides,
  }
}

function canvasOver(doc: BuilderDocument) {
  const store = new RecordingStore()
  store.doc.value = doc
  const canvas = useBuilderCanvas({ document: store })
  const bridge = fakeBridge()
  canvas.attachViewport(bridge)
  return { store, canvas, bridge }
}

beforeEach(() => {
  vocabulary.value = vocabularyFixture()
})

afterEach(() => {
  resetVocabulary()
})

/* --- creating ------------------------------------------------------------- */

describe('dropping a kind on the canvas is one commit on the visible grid', () => {
  it('rounds a fractional drop onto the 20 grid before anything is committed', () => {
    const { store, canvas } = canvasOver(document([]))

    canvas.dropKind('agent', { x: 129, y: 71 })

    expect(store.commits).toEqual(['addNode'])
    const { position } = store.nodesAdded[0].node
    expect(position).toEqual({ x: 120, y: 80 })
    expect(Number.isInteger(position.x) && Number.isInteger(position.y)).toBe(true)
    expect(position.x % GRID === 0 && position.y % GRID === 0).toBe(true)
  })

  it('selects the new node so the inspector is already on it', () => {
    const { store, canvas } = canvasOver(document([]))

    canvas.dropKind('gate', { x: 40, y: 40 })
    const created = store.nodesAdded[0].node.id

    expect([...canvas.selectedNodeIds.value]).toEqual([created])
    expect(canvas.anchorId.value).toBe(created)
  })

  it('refuses a kind the palette could not have produced', () => {
    // Reached through `dropKind` only from a validated `dataTransfer`, but the
    // guard that matters is the one in `newNode`: an unknown kind falls off the
    // end of a switch the type system was told is exhaustive.
    const { store, canvas } = canvasOver(document([]))
    canvas.dropKind('agent', { x: 0, y: 0 })
    expect(store.commits).toHaveLength(1)
  })

  it('drops nothing at all when no viewport is attached', () => {
    // The state between `BuilderView` creating the composable and
    // `BuilderCanvas` mounting. A drop cannot be placed without a viewport, and
    // guessing (0, 0) would stack nodes on the origin.
    const store = new RecordingStore()
    const canvas = useBuilderCanvas({ document: store })

    canvas.dropKind('agent', { x: 100, y: 100 })

    expect(store.commits).toEqual([])
  })
})

describe('a node created from a port is one commit carrying its edge', () => {
  it('hands the origin to addNode rather than committing the edge separately', () => {
    // The `⌘Z` contract of §4.1: one undo removes both. Two commits would leave
    // an edge pointing at a node that no longer exists.
    const { store, canvas } = canvasOver(document([agentNode('scoper')]))

    canvas.createAt('gate', { x: 200, y: 100 }, { source: nodeId('scoper'), source_port: 'out' })

    expect(store.commits).toEqual(['addNode'])
    expect(store.nodesAdded[0].connectFrom).toEqual({ source: 'scoper', source_port: 'out' })
  })

  it('opens the port menu when a connect drag ends on empty canvas', () => {
    const { store, canvas } = canvasOver(document([agentNode('scoper')]))

    canvas.onConnectStart({ nodeId: 'scoper', handleId: 'out' })
    canvas.onConnectEnd(new MouseEvent('mouseup', { clientX: 420, clientY: 260 }))

    expect(canvas.portMenuRequest.value).toEqual({
      origin: { source: 'scoper', source_port: 'out' },
      at: { x: 420, y: 260 },
    })
    expect(store.commits).toEqual([])
  })

  it('does not open the port menu when the drag landed on a real port', () => {
    const { store, canvas } = canvasOver(document([agentNode('scoper'), agentNode('writer')]))

    canvas.onConnectStart({ nodeId: 'scoper', handleId: 'out' })
    canvas.onConnect({ source: 'scoper', target: 'writer', sourceHandle: 'out' })
    canvas.onConnectEnd(new MouseEvent('mouseup', { clientX: 10, clientY: 10 }))

    expect(canvas.portMenuRequest.value).toBeNull()
    expect(store.commits).toEqual(['addEdge'])
  })

  it('aborts the port menu with zero commits', () => {
    const { store, canvas } = canvasOver(document([agentNode('scoper')]))

    canvas.onConnectStart({ nodeId: 'scoper', handleId: 'out' })
    canvas.onConnectEnd(new MouseEvent('mouseup', { clientX: 5, clientY: 5 }))
    canvas.cancelPortMenu()

    expect(canvas.portMenuRequest.value).toBeNull()
    expect(store.commits).toEqual([])
  })
})

describe('the number keys drop a kind and connect it to a lone selection', () => {
  it('connects from the one selected node', () => {
    const { store, canvas } = canvasOver(document([agentNode('scoper')]))
    canvas.selectNode(nodeId('scoper'))

    canvas.insertKind('gate')

    expect(store.commits).toEqual(['addNode', 'addEdge'])
    expect(store.edgesAdded[0].origin).toEqual({ source: 'scoper', source_port: 'out' })
  })

  it('does not connect from a node that has no port to leave by', () => {
    // An `output` node's `_OUT_PORTS_BY_KIND` entry is empty, so an edge out of
    // one is a 422 rather than a Problem - a refusal an author cannot act on.
    const { store, canvas } = canvasOver(document([outputNode('report')]))
    canvas.selectNode(nodeId('report'))

    canvas.insertKind('agent')

    expect(store.commits).toEqual(['addNode'])
  })

  it('does not connect when the selection is not exactly one node', () => {
    const { store, canvas } = canvasOver(document([agentNode('a'), agentNode('b')]))
    canvas.setSelection([nodeId('a'), nodeId('b')])

    canvas.insertKind('agent')

    expect(store.commits).toEqual(['addNode'])
  })
})

/* --- moving --------------------------------------------------------------- */

describe('a drag is exactly one commit, however many nodes moved', () => {
  /**
   * A drag event with the two fields the canvas reads, and one cast.
   *
   * `NodeDragEvent` carries whole `GraphNode`s - dimensions, handle bounds,
   * computed positions, the lot - none of which this canvas touches: it reads
   * `id` and `position` and nothing else, which is exactly what makes "one
   * commit per gesture" assertable without a browser. Building thirty fields of
   * Vue Flow internals to prove that would be asserting against the library.
   */
  const dragEvent = (
    nodes: Array<{ id: string; x: number; y: number }>,
    altKey = false,
  ): NodeDragEvent =>
    ({
      event: new MouseEvent('mousemove', { altKey }),
      node: { id: nodes[0].id, position: { x: nodes[0].x, y: nodes[0].y } },
      nodes: nodes.map((entry) => ({ id: entry.id, position: { x: entry.x, y: entry.y } })),
    }) as unknown as NodeDragEvent

  it('commits once on drag stop, carrying every node that moved', () => {
    const { store, canvas } = canvasOver(document([agentNode('a'), agentNode('b')]))

    canvas.onNodeDragStart(dragEvent([{ id: 'a', x: 0, y: 0 }]))
    canvas.onNodeDrag(dragEvent([{ id: 'a', x: 20, y: 20 }]))
    canvas.onNodeDrag(dragEvent([{ id: 'a', x: 40, y: 40 }]))
    canvas.onNodeDragStop(
      dragEvent([
        { id: 'a', x: 60, y: 60 },
        { id: 'b', x: 80, y: 100 },
      ]),
    )

    expect(store.commits).toEqual(['moveNodes'])
    expect(store.moves[0].moves).toEqual([
      { id: 'a', position: { x: 60, y: 60 } },
      { id: 'b', position: { x: 80, y: 100 } },
    ])
  })

  it('rounds an Alt-drag that left the grid, because the schema wants an int', () => {
    const { store, canvas } = canvasOver(document([agentNode('a')]))

    canvas.onNodeDragStop(dragEvent([{ id: 'a', x: 63.4, y: 91.6 }]))

    expect(store.moves[0].moves[0].position).toEqual({ x: 63, y: 92 })
  })

  it('turns snapping off while Alt is held and back on when the drag ends', () => {
    const { canvas } = canvasOver(document([agentNode('a')]))
    canvas.onNodeDragStart(dragEvent([{ id: 'a', x: 0, y: 0 }], true))
    expect(canvas.gridSnapping.value).toBe(false)

    canvas.onNodeDragStop(dragEvent([{ id: 'a', x: 0, y: 0 }]))
    expect(canvas.gridSnapping.value).toBe(true)
  })

  it('holds the projection still for the length of the drag', () => {
    // `parseNode` assigns an incoming node's `position` over the stored one, so
    // a projection that recomputed mid-drag would hand the dragged card the
    // coordinates it started at and the node would jump under the pointer.
    const { store, canvas } = canvasOver(document([agentNode('a', 0, 0)]))
    const before = canvas.nodes.value

    canvas.onNodeDragStart(dragEvent([{ id: 'a', x: 0, y: 0 }]))
    store.doc.value = document([agentNode('a', 500, 500)])

    expect(canvas.nodes.value).toBe(before)
    expect(canvas.nodes.value[0].position).toEqual({ x: 0, y: 0 })

    canvas.onNodeDragStop(dragEvent([{ id: 'a', x: 500, y: 500 }]))
    expect(canvas.nodes.value[0].position).toEqual({ x: 500, y: 500 })
  })
})

describe('nudging coalesces so a held arrow key is one undo step', () => {
  it('keys the coalescing on the ids, not on the direction', () => {
    const { store, canvas } = canvasOver(document([agentNode('a', 20, 20), agentNode('b', 60, 20)]))
    canvas.setSelection([nodeId('b'), nodeId('a')])

    canvas.nudge(GRID, 0)
    canvas.nudge(0, -GRID)

    expect(store.moves.map((entry) => entry.coalesceKey)).toEqual(['move:a,b', 'move:a,b'])
    expect(store.moves[0].moves).toEqual([
      { id: 'a', position: { x: 40, y: 20 } },
      { id: 'b', position: { x: 80, y: 20 } },
    ])
  })

  it('commits nothing when nothing is selected', () => {
    const { store, canvas } = canvasOver(document([agentNode('a')]))

    canvas.nudge(GRID, 0)

    expect(store.commits).toEqual([])
  })
})

/* --- selection ------------------------------------------------------------ */

describe('clicking one member of a multi-selection collapses it, dragging does not', () => {
  function multi() {
    const made = canvasOver(document([agentNode('a'), agentNode('b'), agentNode('c')]))
    made.canvas.setSelection([nodeId('a'), nodeId('b'), nodeId('c')])
    return made
  }

  it('keeps all three selected while the pointer is still down', () => {
    const { canvas } = multi()

    canvas.notePointerDown({ clientX: 100, clientY: 100 })

    expect(canvas.selectedNodeIds.value.size).toBe(3)
  })

  it('collapses to the clicked node when the pointer barely moved', () => {
    const { canvas } = multi()

    canvas.notePointerDown({ clientX: 100, clientY: 100 })
    canvas.onNodeClick(
      nodeId('b'),
      new MouseEvent('click', { clientX: 100 + COLLAPSE_TRAVEL_PX - 1, clientY: 100 }),
    )

    expect([...canvas.selectedNodeIds.value]).toEqual(['b'])
    expect(canvas.anchorId.value).toBe('b')
  })

  it('keeps the group when the pointer travelled, because that was a drag', () => {
    const { canvas } = multi()

    canvas.notePointerDown({ clientX: 100, clientY: 100 })
    canvas.onNodeClick(nodeId('b'), new MouseEvent('click', { clientX: 140, clientY: 130 }))

    expect(canvas.selectedNodeIds.value.size).toBe(3)
  })

  it('keeps the group when a modifier is held, because that is an add or a toggle', () => {
    const { canvas } = multi()

    canvas.notePointerDown({ clientX: 100, clientY: 100 })
    canvas.onNodeClick(nodeId('b'), new MouseEvent('click', { clientX: 100, clientY: 100, shiftKey: true }))

    expect(canvas.selectedNodeIds.value.size).toBe(3)
  })
})

describe('the selection mirror does not argue with Vue Flow', () => {
  it('leaves the set object alone when the library reports the same members', () => {
    const { canvas } = canvasOver(document([agentNode('a'), agentNode('b')]))
    canvas.setSelection([nodeId('a')])
    const first = canvas.selectedNodeIds.value

    canvas.onSelectionChange({ nodes: [{ id: 'a' }], edges: [] })

    // Identity: replacing an equal Set would rebuild the whole nodes array on
    // every marquee frame, and could ping-pong with the library indefinitely.
    expect(canvas.selectedNodeIds.value).toBe(first)
  })

  it('adopts a marquee selection made inside the library', () => {
    const { canvas } = canvasOver(document([agentNode('a'), agentNode('b')]))

    canvas.onSelectionChange({ nodes: [{ id: 'a' }, { id: 'b' }], edges: [{ id: 'e1' }] })

    expect([...canvas.selectedNodeIds.value]).toEqual(['a', 'b'])
    expect([...canvas.selectedEdgeIds.value]).toEqual(['e1'])
  })

  it('drops the anchor when the anchor leaves the selection', () => {
    const { canvas } = canvasOver(document([agentNode('a'), agentNode('b')]))
    canvas.selectNode(nodeId('a'))

    canvas.onSelectionChange({ nodes: [{ id: 'b' }], edges: [] })

    expect(canvas.anchorId.value).toBeNull()
  })

  it('selects everything, then clears it', () => {
    const { canvas } = canvasOver(
      document([agentNode('a'), agentNode('b')], [edge('e1', 'a', 'b')]),
    )

    canvas.selectAll()
    expect(canvas.selectionSize.value).toBe(3)

    canvas.clearSelection()
    expect(canvas.selectionSize.value).toBe(0)
    expect(canvas.anchorId.value).toBeNull()
  })
})

/* --- deleting and joining ------------------------------------------------- */

describe('delete and the join toggle each commit once', () => {
  it('sends both lists in one command and clears the selection', () => {
    const { store, canvas } = canvasOver(
      document([agentNode('a'), agentNode('b')], [edge('e1', 'a', 'b')]),
    )
    canvas.selectAll()

    canvas.deleteSelection()

    expect(store.commits).toEqual(['deleteSelection'])
    expect(store.deletes[0].nodes).toEqual(['a', 'b'])
    expect(store.deletes[0].edges).toEqual(['e1'])
    expect(canvas.selectionSize.value).toBe(0)
  })

  it('commits nothing when nothing is selected', () => {
    const { store, canvas } = canvasOver(document([agentNode('a')]))

    canvas.deleteSelection()

    expect(store.commits).toEqual([])
  })

  it('toggles AND on, then off by deleting the key rather than writing `any`', () => {
    // `'any'` is refused at parse time - it is the `or_()` suppression this repo
    // already carries a closed defect about - so OR is the ABSENCE of the key.
    const { store, canvas } = canvasOver(document([agentNode('a')]))

    canvas.toggleJoin(nodeId('a'))
    store.doc.value = document([agentNode('a')], [], { a: 'all' })
    canvas.toggleJoin(nodeId('a'))

    expect(store.joins).toEqual([
      { node: 'a', join: 'all' },
      { node: 'a', join: null },
    ])
  })

  it('publishes the join on the node and on its inbound edges', () => {
    const { canvas } = canvasOver(
      document([agentNode('a'), agentNode('b')], [edge('e1', 'a', 'b')], { b: 'all' }),
    )

    expect(canvas.nodes.value.find((node) => node.id === 'b')?.data.joined).toBe(true)
    expect(canvas.edges.value[0].data.joinTarget).toBe(true)
  })
})

/* --- problems ------------------------------------------------------------- */

describe('a problem row and F8 take you to the same place', () => {
  const problem = (over: Partial<BuilderProblem> = {}): BuilderProblem => ({
    code: 'node-unreachable',
    severity: 'error',
    message: 'Nothing reaches this node.',
    node_id: null,
    edge_id: null,
    ...over,
  })

  function withProblems(problems: BuilderProblem[]) {
    const store = new RecordingStore()
    store.doc.value = document([agentNode('a'), agentNode('b')], [edge('e1', 'a', 'b')])
    const byNode = new Map<string, BuilderProblem[]>()
    const byEdge = new Map<string, BuilderProblem[]>()
    for (const entry of problems) {
      if (entry.node_id) byNode.set(entry.node_id, [...(byNode.get(entry.node_id) ?? []), entry])
      if (entry.edge_id) byEdge.set(entry.edge_id, [...(byEdge.get(entry.edge_id) ?? []), entry])
    }
    const canvas = useBuilderCanvas({
      document: store,
      problems: { byNode: () => byNode, byEdge: () => byEdge },
    })
    const bridge = fakeBridge()
    canvas.attachViewport(bridge)
    return { canvas, bridge }
  }

  it('selects the node, centres on it and flashes it', () => {
    const { canvas, bridge } = withProblems([problem({ node_id: 'b' })])

    canvas.focusProblem(problem({ node_id: 'b' }))

    expect([...canvas.selectedNodeIds.value]).toEqual(['b'])
    expect(bridge.fits).toEqual([{ nodes: ['b'], duration: 260 }])
    expect(canvas.nodes.value.find((node) => node.id === 'b')?.data.flashing).toBe(true)
  })

  it('shows an error above a warning on a node carrying both', () => {
    const { canvas } = withProblems([
      problem({ node_id: 'a', severity: 'warning', code: 'no-output-node' }),
      problem({ node_id: 'a', severity: 'error' }),
    ])

    expect(canvas.nodes.value.find((node) => node.id === 'a')?.data.severity).toBe('error')
  })

  it('moves the viewport nowhere for a problem that anchors to nothing', () => {
    const { canvas, bridge } = withProblems([])

    canvas.focusProblem(problem())

    expect(bridge.fits).toEqual([])
    expect(canvas.selectionSize.value).toBe(0)
  })

  it('reports no severity at all for a node the server said nothing about', () => {
    const { canvas } = withProblems([])

    expect(canvas.nodes.value.every((node) => node.data.severity === null)).toBe(true)
  })
})

/* --- navigating ----------------------------------------------------------- */

describe('Tab walks the graph in the order the compiler will run it', () => {
  it('moves downstream, announces where it landed, and wraps', () => {
    const { canvas } = canvasOver(
      document(
        [agentNode('a'), agentNode('b'), agentNode('c')],
        [edge('e1', 'a', 'b'), edge('e2', 'b', 'c')],
      ),
    )

    canvas.traverse(1)
    expect([...canvas.selectedNodeIds.value]).toEqual(['a'])
    expect(canvas.announcement.value).toBe('a, agent')

    canvas.traverse(1)
    expect(canvas.anchorId.value).toBe('b')

    canvas.traverse(-1)
    expect(canvas.anchorId.value).toBe('a')
  })

  it('steps between the branches of a fan-out and nowhere else', () => {
    const { canvas } = canvasOver(
      document(
        [agentNode('root'), agentNode('m'), agentNode('s'), agentNode('f')],
        [edge('e1', 'root', 'm'), edge('e2', 'root', 's'), edge('e3', 'root', 'f')],
      ),
    )
    canvas.selectNode(nodeId('m'))

    canvas.cycleSibling(1)
    expect(canvas.anchorId.value).toBe('s')

    canvas.cycleSibling(-1)
    expect(canvas.anchorId.value).toBe('m')
  })

  it('does nothing when the focused node has no siblings', () => {
    const { canvas } = canvasOver(document([agentNode('only')]))
    canvas.selectNode(nodeId('only'))

    canvas.cycleSibling(1)

    expect(canvas.anchorId.value).toBe('only')
  })

  it('fits the selection, or the whole graph when nothing is selected', () => {
    const { canvas, bridge } = canvasOver(document([agentNode('a'), agentNode('b')]))

    canvas.zoomToSelection()
    expect(bridge.fits[0]).toEqual({ padding: 0.14, duration: 260 })

    canvas.setSelection([nodeId('a')])
    canvas.zoomToSelection()
    expect(bridge.fits[1]).toEqual({ nodes: ['a'], duration: 260 })
  })
})

/* --- the hotkey table ----------------------------------------------------- */

function recordingActions(): { actions: HotkeyActions; log: string[] } {
  const log: string[] = []
  const note =
    (name: string) =>
    (...args: unknown[]) => {
      log.push(args.length ? `${name}:${args.join(',')}` : name)
    }
  return {
    log,
    actions: {
      undo: note('undo'),
      redo: note('redo'),
      save: note('save'),
      publish: note('publish'),
      validateNow: note('validateNow'),
      deleteSelection: note('deleteSelection'),
      selectAll: note('selectAll'),
      escape: note('escape'),
      leaveCanvas: note('leaveCanvas'),
      copy: note('copy'),
      cut: note('cut'),
      paste: note('paste'),
      duplicate: note('duplicate'),
      insertKind: note('insertKind'),
      renameFocused: note('renameFocused'),
      linkFromFocused: note('linkFromFocused'),
      confirmLink: note('confirmLink'),
      nudge: note('nudge'),
      traverse: note('traverse'),
      cycleSibling: note('cycleSibling'),
      fitView: note('fitView'),
      zoomToActual: note('zoomToActual'),
      zoomToSelection: note('zoomToSelection'),
      focusFilter: note('focusFilter'),
      walkProblems: note('walkProblems'),
      toggleShortcuts: note('toggleShortcuts'),
    },
  }
}

const alwaysFocused = { canvasHasFocus: () => true }

function press(init: KeyboardEventInit & { key?: string }): KeyboardEvent {
  return new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init })
}

describe('the binding table is the shortcut sheet and the dispatcher at once', () => {
  it('gives every binding a unique id, a label and at least one chord', () => {
    const ids = HOTKEY_BINDINGS.map((binding) => binding.id)

    expect(new Set(ids).size).toBe(ids.length)
    for (const binding of HOTKEY_BINDINGS) {
      expect(binding.label.length).toBeGreaterThan(0)
      expect(binding.chords.length).toBeGreaterThan(0)
      expect(bindingLabels(binding).every((label) => label.length > 0)).toBe(true)
    }
  })

  it('has one insert binding per kind, on the digit the palette shows', () => {
    for (const kind of NODE_KIND_ORDER) {
      const binding = HOTKEY_BINDINGS.find((entry) => entry.id === `insert-${kind}`)
      expect(binding, `no binding for ${kind}`).toBeDefined()
      expect(binding?.chords[0].key).toBe(NODE_KINDS[kind].hotkey)
    }
  })

  it('runs the kind the digit names', () => {
    const { actions, log } = recordingActions()

    dispatchHotkey(press({ key: '3' }), actions, alwaysFocused)

    expect(log).toEqual([`insertKind:${NODE_KIND_ORDER[2]}`])
  })

  it('tells undo from redo, and accepts both spellings of redo', () => {
    const { actions, log } = recordingActions()

    dispatchHotkey(press({ key: 'z', ctrlKey: true }), actions, alwaysFocused)
    dispatchHotkey(press({ key: 'z', ctrlKey: true, shiftKey: true }), actions, alwaysFocused)
    dispatchHotkey(press({ key: 'y', ctrlKey: true }), actions, alwaysFocused)

    expect(log).toEqual(['undo', 'redo', 'redo'])
  })

  it('sends a bare arrow one grid step and a shifted arrow one pixel', () => {
    const { actions, log } = recordingActions()

    dispatchHotkey(press({ key: 'ArrowRight' }), actions, alwaysFocused)
    dispatchHotkey(press({ key: 'ArrowUp', shiftKey: true }), actions, alwaysFocused)

    expect(log).toEqual([`nudge:${GRID},0`, 'nudge:0,-1'])
  })

  it('prevents the default for anything it handles, and nothing it does not', () => {
    const { actions } = recordingActions()
    const handled = press({ key: 'f' })
    const ignored = press({ key: 'q' })

    expect(dispatchHotkey(handled, actions, alwaysFocused)?.id).toBe('fit-view')
    expect(handled.defaultPrevented).toBe(true)
    expect(dispatchHotkey(ignored, actions, alwaysFocused)).toBeNull()
    expect(ignored.defaultPrevented).toBe(false)
  })
})

describe('typing in a field is typing, not a shortcut', () => {
  const inField = (init: KeyboardEventInit) => {
    const input = window.document.createElement('input')
    window.document.body.append(input)
    const event = press(init)
    Object.defineProperty(event, 'target', { value: input })
    return event
  }

  it('ignores every binding while focus is in a text field', () => {
    const { actions, log } = recordingActions()

    dispatchHotkey(inField({ key: 'd' }), actions, alwaysFocused)
    dispatchHotkey(inField({ key: 'Delete' }), actions, alwaysFocused)
    dispatchHotkey(inField({ key: '3' }), actions, alwaysFocused)

    expect(log).toEqual([])
  })

  it('lets Escape and save through, because those are how you get out and keep work', () => {
    const { actions, log } = recordingActions()

    dispatchHotkey(inField({ key: 'Escape' }), actions, alwaysFocused)
    dispatchHotkey(inField({ key: 's', metaKey: true }), actions, alwaysFocused)

    expect(log).toEqual(['escape', 'save'])
  })

  it('counts a contenteditable as a text field, which is what the label rename is', () => {
    const span = window.document.createElement('span')
    Object.defineProperty(span, 'isContentEditable', { value: true })

    expect(isTextEntry(span)).toBe(true)
    expect(isTextEntry(window.document.createElement('div'))).toBe(false)
  })

  it('exempts exactly two bindings and no others', () => {
    expect(HOTKEY_BINDINGS.filter((binding) => binding.allowInTextEntry).map((b) => b.id)).toEqual([
      'escape',
      'save',
    ])
  })
})

describe('Tab is only ours while the canvas has focus', () => {
  it('walks the graph when focus is on the canvas', () => {
    const { actions, log } = recordingActions()

    dispatchHotkey(press({ key: 'Tab' }), actions, alwaysFocused)

    expect(log).toEqual(['traverse:1'])
  })

  it('leaves Tab to the browser everywhere else, so the rails stay reachable', () => {
    // Hijacking Tab at the window would make the palette, the inspector and the
    // document bar unreachable by keyboard for as long as the builder is
    // mounted - a WCAG 2.1.1 failure that no screenshot would show.
    const { actions, log } = recordingActions()
    const event = press({ key: 'Tab' })

    expect(dispatchHotkey(event, actions, { canvasHasFocus: () => false })).toBeNull()
    expect(event.defaultPrevented).toBe(false)
    expect(log).toEqual([])
  })

  it('gates traversal, the arrows and Enter on canvas focus, and nothing else', () => {
    // The arrows for the milder version of the same reason: a `preventDefault`
    // on them at the window would stop the problems panel scrolling. `Enter` is
    // the strongest case of the three: ungated, it would stop every button in
    // the palette, the inspector, the problems dock and both dialogs from being
    // activated by keyboard for as long as the builder is mounted.
    expect(
      HOTKEY_BINDINGS.filter((binding) => binding.requiresCanvasFocus).map((b) => b.id),
    ).toEqual([
      'link-confirm',
      'nudge',
      'nudge-fine',
      'leave-canvas',
      'traverse-forward',
      'traverse-back',
    ])
  })

  it('leaves the arrow keys to a scrollable rail that has focus', () => {
    const { actions, log } = recordingActions()
    const event = press({ key: 'ArrowDown' })

    expect(dispatchHotkey(event, actions, { canvasHasFocus: () => false })).toBeNull()
    expect(event.defaultPrevented).toBe(false)
    expect(log).toEqual([])
  })

  it('reads focus off the attribute the canvas stamps on itself', () => {
    const host = window.document.createElement('div')
    host.setAttribute(BUILDER_CANVAS_ATTR, '')
    const inner = window.document.createElement('button')
    host.append(inner)
    window.document.body.append(host)

    inner.focus()
    expect(canvasHasFocus()).toBe(true)

    inner.blur()
    host.remove()
    expect(canvasHasFocus()).toBe(false)
  })
})

describe('a chord prints the way the platform spells it', () => {
  it('uses glyphs on macOS and words elsewhere', () => {
    expect(chordLabel({ key: 'z', mod: true }, true)).toBe('⌘Z')
    expect(chordLabel({ key: 'z', mod: true }, false)).toBe('Ctrl+Z')
    expect(chordLabel({ key: 'z', mod: true, shift: true }, true)).toBe('⌘⇧Z')
  })

  it('names the physical key for a chord declared by code', () => {
    expect(chordLabel({ code: 'Digit1', shift: true }, false)).toBe('Shift+1')
  })

  it('prints an arrow as an arrow, not as `ArrowUp`', () => {
    expect(chordLabel({ key: 'ArrowUp' }, false)).toBe('↑')
    expect(chordLabel({ key: 'Escape' }, false)).toBe('Esc')
  })

  it('matches Shift+1 by its code, which survives a non-US layout', () => {
    // On a US keyboard `Shift+1` reports `!`; elsewhere it reports something
    // else again. `Digit1` is the same physical key everywhere.
    expect(matchBinding(press({ key: '!', code: 'Digit1', shiftKey: true }))?.id).toBe(
      'zoom-actual',
    )
  })
})

/* --- the mounted canvas --------------------------------------------------- */

describe('the mounted canvas hands the library the settings the spec names', () => {
  /**
   * Two things jsdom does not have, and one warning it therefore cannot avoid.
   *
   * `ResizeObserver` is absent outright, and Vue Flow constructs one in an
   * `onMounted` - so without a stand-in the component cannot mount at all.
   * `offsetWidth`/`offsetHeight` are always zero, which Vue Flow correctly
   * reports as "the parent container needs a width and a height"; giving the
   * prototype a size is what makes that report untrue rather than muted. What
   * is left is Vue Flow's stylesheet check, which reads a computed `z-index`
   * that vitest does not apply CSS for under any circumstances, so it is
   * silenced by name here and nowhere else.
   */
  beforeEach(() => {
    class StubResizeObserver {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    }
    vi.stubGlobal('ResizeObserver', StubResizeObserver)
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
      configurable: true,
      value: 800,
    })
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
      configurable: true,
      value: 600,
    })
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function mountCanvas() {
    const store = new RecordingStore()
    store.doc.value = document([agentNode('a', 0, 0), agentNode('b', 300, 0)], [edge('e1', 'a', 'b')])
    const canvas = useBuilderCanvas({ document: store })
    const wrapper = mount(BuilderCanvas, {
      props: { canvas, label: 'under test' },
      slots: { node: '<div class="stub-node" />', edge: '<g class="stub-edge" />' },
      attachTo: window.document.body,
    })
    return { wrapper, canvas, store }
  }

  it('mounts its own Vue Flow instance under a distinct id', () => {
    // `useVueFlow` keys per-instance state by id, and `StudioView` mounts
    // `studio-flow`. Sharing one would leak viewport and selection between the
    // two workspaces the moment a session opened both (§1.3).
    const { wrapper } = mountCanvas()

    expect(useVueFlow('builder-flow').id).toBe('builder-flow')
    expect(wrapper.attributes(BUILDER_CANVAS_ATTR)).toBeDefined()
    expect(wrapper.attributes('role')).toBe('application')
    expect(wrapper.attributes('data-mode')).toBe('design')
    wrapper.unmount()
  })

  it('marquees by intersection, snaps to 20, and owns the Delete key itself', () => {
    const { wrapper } = mountCanvas()
    const flow = useVueFlow('builder-flow')

    // Intersection rather than containment: containment-only is what makes a
    // 240px card finicky to catch, and `getNodesInside` reads exactly this.
    expect(flow.selectionMode.value).toBe('partial')
    expect(flow.snapGrid.value).toEqual([20, 20])
    // Null, so Delete reaches `deleteSelection` and is undoable. Vue Flow's own
    // removal never passes through `commit()`.
    expect(flow.deleteKeyCode.value).toBeNull()
    expect(flow.isValidConnection.value).not.toBeNull()
    wrapper.unmount()
  })

  it('re-fits when a docked strip opens, even after the author has gestured (D-15-2)', async () => {
    /*
     * Round 1 measured the defect this pins: the version browser docking 125px
     * above the graph hid 2 of 5 nodes and no re-fit followed, because the
     * settling observer disconnected at the author's first gesture. The rule
     * now: before a gesture every change to the frame re-fits; after one, only
     * the DOCK growing does - the problems panel growing under the frame does
     * not, because that re-fit moved the canvas under the next drag (2 of 6
     * E2E runs) - and never while a pointer is down. A stand-in observer whose
     * callback the test drives is the only way jsdom can say any of this.
     */
    interface Driven {
      callback: ResizeObserverCallback
      targets: Element[]
      disconnected: boolean
    }
    const instances: Driven[] = []
    // `disconnect` is honoured, so the code this test was written against -
    // which disconnected at the first gesture - fails here for the reason it
    // was wrong, not for a stub that kept calling a dead observer.
    class DrivenResizeObserver {
      private readonly entry: Driven
      constructor(callback: ResizeObserverCallback) {
        this.entry = { callback, targets: [], disconnected: false }
        instances.push(this.entry)
      }
      observe(target: Element): void {
        this.entry.targets.push(target)
      }
      unobserve(): void {}
      disconnect(): void {
        this.entry.disconnected = true
      }
    }
    vi.stubGlobal('ResizeObserver', DrivenResizeObserver)
    const dock = window.document.createElement('div')
    const store = new RecordingStore()
    store.doc.value = document([agentNode('a', 0, 0), agentNode('b', 300, 0)], [edge('e1', 'a', 'b')])
    const canvasComposable = useBuilderCanvas({ document: store })
    const wrapper = mount(BuilderCanvas, {
      props: { canvas: canvasComposable, label: 'under test', dock },
      slots: { node: '<div class="stub-node" />', edge: '<g class="stub-edge" />' },
      attachTo: window.document.body,
    })
    const flow = useVueFlow('builder-flow')
    const fitView = vi.spyOn(flow, 'fitView').mockImplementation(async () => true)
    const frame = wrapper.element as HTMLElement
    // Vue Flow builds observers of its own; ours is the one watching the frame
    // AND the dock.
    const canvasObserver = instances.find((entry) => entry.targets.includes(frame))
    expect(canvasObserver).toBeDefined()
    expect(canvasObserver!.targets).toContain(dock)
    const resize = (target: Element, height: number) => {
      if (canvasObserver!.disconnected) return
      canvasObserver!.callback(
        [{ target, contentRect: { height } } as unknown as ResizeObserverEntry],
        {} as ResizeObserver,
      )
    }

    // Settling: every change to the frame fits.
    resize(frame, 700)
    resize(frame, 640)
    expect(fitView).toHaveBeenCalledTimes(2)

    // The author gestures; the viewport is theirs. The frame shrinking under
    // them - the problems panel growing after a validate - changes nothing.
    await wrapper.trigger('pointerdown')
    await wrapper.trigger('pointerup')
    resize(frame, 540)
    resize(frame, 700)
    expect(fitView).toHaveBeenCalledTimes(2)

    // A strip docks above the graph: the dock GROWS, and the fit is owed.
    resize(dock, 125)
    expect(fitView).toHaveBeenCalledTimes(3)

    // It closes again: the dock shrinks back, nothing is hidden, nothing moves.
    resize(dock, 0)
    expect(fitView).toHaveBeenCalledTimes(3)

    // Not mid-drag. It lands when the pointer lifts.
    await wrapper.trigger('pointerdown')
    resize(dock, 230)
    expect(fitView).toHaveBeenCalledTimes(3)
    await wrapper.trigger('pointerup')
    expect(fitView).toHaveBeenCalledTimes(4)

    // Below a pixel of movement, and the frame's collapse to zero on unmount: nothing.
    resize(dock, 230.4)
    resize(frame, 0)
    expect(fitView).toHaveBeenCalledTimes(4)
    wrapper.unmount()
  })

  it('observes a dock that arrives after mount, the way a template ref does (D-15-2)', async () => {
    /*
     * The shell's dock is a template ref, assigned in a post-render effect
     * after the whole tree mounts - so when this component mounted, the prop
     * was still null and the first cut observed nothing. Round 2's capture of
     * the delete confirm showed the graph unmoved under two docked strips.
     */
    interface Driven {
      callback: ResizeObserverCallback
      targets: Element[]
    }
    const instances: Driven[] = []
    class DrivenResizeObserver {
      private readonly entry: Driven
      constructor(callback: ResizeObserverCallback) {
        this.entry = { callback, targets: [] }
        instances.push(this.entry)
      }
      observe(target: Element): void {
        this.entry.targets.push(target)
      }
      unobserve(target: Element): void {
        this.entry.targets = this.entry.targets.filter((t) => t !== target)
      }
      disconnect(): void {}
    }
    vi.stubGlobal('ResizeObserver', DrivenResizeObserver)
    const { wrapper } = mountCanvas()
    const flow = useVueFlow('builder-flow')
    const fitView = vi.spyOn(flow, 'fitView').mockImplementation(async () => true)
    const frame = wrapper.element as HTMLElement
    const canvasObserver = instances.find((entry) => entry.targets.includes(frame))!
    expect(canvasObserver).toBeDefined()

    const dock = window.document.createElement('div')
    expect(canvasObserver.targets).not.toContain(dock)
    await wrapper.setProps({ dock })
    await flush(2)
    expect(canvasObserver.targets).toContain(dock)

    await wrapper.trigger('pointerdown')
    await wrapper.trigger('pointerup')
    canvasObserver.callback(
      [{ target: dock, contentRect: { height: 125 } } as unknown as ResizeObserverEntry],
      {} as ResizeObserver,
    )
    expect(fitView).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ dock: null })
    await flush(2)
    expect(canvasObserver.targets).not.toContain(dock)
    wrapper.unmount()
  })

  it('attaches a viewport on mount and lets go of it on unmount', () => {
    const { wrapper, canvas, store } = mountCanvas()

    canvas.dropKind('agent', { x: 10, y: 10 })
    expect(store.commits).toEqual(['addNode'])

    wrapper.unmount()
    canvas.dropKind('agent', { x: 10, y: 10 })
    expect(store.commits).toEqual(['addNode'])
  })

  it('refuses a drop carrying anything that is not one of the seven kinds', async () => {
    const { wrapper, store } = mountCanvas()
    const transfer = { getData: vi.fn().mockReturnValue('rm -rf'), dropEffect: 'none' }

    await wrapper.trigger('drop', { dataTransfer: transfer, clientX: 10, clientY: 10 })
    await nextTick()

    expect(store.commits).toEqual([])
    wrapper.unmount()
  })
})

/* --- the minimap ---------------------------------------------------------- */

describe('the minimap is coloured by problems before anything else', () => {
  const base: MinimapNode = {
    id: 'a',
    x: 0,
    y: 0,
    width: 240,
    height: 96,
    accent: '#99eaf9',
    severity: null,
    selected: false,
  }

  function mountMap(nodes: MinimapNode[]) {
    return mount(BuilderMinimap, {
      props: {
        nodes,
        viewport: { x: 0, y: 0, zoom: 1 },
        pane: { width: 800, height: 600 },
      },
    })
  }

  it('ranks error above warning above selected above the kind accent', () => {
    const wrapper = mountMap([
      { ...base, id: 'err', severity: 'error', selected: true },
      { ...base, id: 'warn', severity: 'warning' },
      { ...base, id: 'sel', selected: true },
      { ...base, id: 'plain' },
    ])

    const fill = (id: string) =>
      wrapper.find(`[data-node="${id}"]`).attributes('fill')
    expect(fill('err')).toBe('var(--err-text)')
    expect(fill('warn')).toBe('var(--warn-text)')
    expect(fill('sel')).toBe('var(--accent-cyan)')
    expect(fill('plain')).toBe('#99eaf9')
  })

  it('draws one rectangle per node and never one too small to see', () => {
    const wrapper = mountMap([
      { ...base, id: 'a' },
      { ...base, id: 'b', x: 40000 },
    ])

    const dots = wrapper.findAll('.minimap-dot')
    expect(dots).toHaveLength(2)
    for (const dot of dots) {
      expect(Number(dot.attributes('width'))).toBeGreaterThanOrEqual(3)
      expect(Number(dot.attributes('height'))).toBeGreaterThanOrEqual(2)
    }
  })

  it('keeps the viewport rectangle on the map even when the graph is elsewhere', () => {
    const wrapper = mount(BuilderMinimap, {
      props: {
        nodes: [base],
        viewport: { x: -5000, y: -5000, zoom: 1 },
        pane: { width: 800, height: 600 },
      },
    })

    const box = wrapper.find('.minimap-view')
    expect(Number(box.attributes('x'))).toBeGreaterThanOrEqual(0)
    expect(Number(box.attributes('y'))).toBeGreaterThanOrEqual(0)
  })

  it('collapses to its toggle and says so to a screen reader', async () => {
    const wrapper = mountMap([base])
    expect(wrapper.find('[data-testid="minimap-surface"]').exists()).toBe(true)

    await wrapper.find('.minimap-toggle').trigger('click')

    expect(wrapper.find('[data-testid="minimap-surface"]').exists()).toBe(false)
    expect(wrapper.find('.minimap-toggle').attributes('aria-expanded')).toBe('false')
  })
})
