import { shallowRef } from 'vue'
import { describe, expect, it } from 'vitest'
import { useBuilderCanvas } from '../src/composables/useBuilderCanvas'
import type {
  CanvasDocumentStore,
  EdgeOrigin,
  NodeMove,
} from '../src/composables/useBuilderCanvas'
import { edgeId, nodeId } from '../src/types/builder'
import type {
  BuilderDocument,
  BuilderEdge,
  BuilderNode,
  EdgeId,
  NodeId,
} from '../src/types/builder'

/**
 * A drawn port is an accepted port, and a refused connection is a 422 rather
 * than an opinion.
 *
 * `nodeKinds.spec.ts` already proves the port TABLE matches
 * `document.py:_OUT_PORTS_BY_KIND` by reading the Python. This file closes the
 * gap on the other side of that table: what the canvas does with it at the
 * mouse. Two failures are being pinned, and they fail in opposite directions.
 *
 * The first is refusing too much. `isValidConnection` may enforce only the
 * §6.1 parse refusals - the shapes that come back as a 422 and can never be
 * rendered as a Problem the author could act on. Every `bounds.py` count is the
 * server's (R6), and the fan-out case has an explicit test here because it is
 * the one a well-meaning contributor is most likely to "fix": drawing a fifth
 * edge out of a gate LOOKS wrong and is a warning the server owns.
 *
 * The second is refusing at the wrong time, and it is the sharper of the two.
 * `createGraphEdges` runs every edge of the projection through
 * `isValidConnection` on every `setEdges` and silently drops - with a console
 * error - any it refuses. An edge already in the document that fails one of
 * these tests is exactly an `edge-unknown-port`: a problem whose row has to be
 * able to point at a DRAWN edge. Erase it from the canvas and the panel names a
 * defect in something invisible, which is the ChatDev failure this whole
 * document is written against.
 */

/* --- fixtures ------------------------------------------------------------- */

function inputNode(id: string): BuilderNode {
  return {
    id: nodeId(id),
    label: id,
    position: { x: 0, y: 0 },
    kind: 'input',
    config: { field: nodeId(id), label: null, max_chars: 2000, required: true },
  }
}

function agentNode(id: string): BuilderNode {
  return {
    id: nodeId(id),
    label: id,
    position: { x: 0, y: 0 },
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

function gateNode(id: string): BuilderNode {
  return {
    id: nodeId(id),
    label: id,
    position: { x: 0, y: 0 },
    kind: 'gate',
    config: { message: 'Look at this.', editable_fields: [], max_turns: 1, expiry_seconds: 1800 },
  }
}

function routerNode(id: string, labels: string[]): BuilderNode {
  return {
    id: nodeId(id),
    label: id,
    position: { x: 0, y: 0 },
    kind: 'router',
    config: {
      branches: labels.map((label, index) =>
        index === labels.length - 1
          ? { label: nodeId(label), op: 'otherwise' as const, key: null, value: null }
          : { label: nodeId(label), op: 'eq' as const, key: nodeId('decision'), value: label },
      ),
    },
  }
}

function outputNode(id: string): BuilderNode {
  return {
    id: nodeId(id),
    label: id,
    position: { x: 0, y: 0 },
    kind: 'output',
    config: { body_key: 'markdown_body', source: null },
  }
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

function document(nodes: BuilderNode[], edges: BuilderEdge[] = []): BuilderDocument {
  return {
    schema: 'builder.flow/v1',
    id: 'ug_0000abcd' as BuilderDocument['id'],
    name: 'under test',
    version: 1,
    input_field: nodeId('idea'),
    nodes,
    edges,
    joins: {},
    budget: null,
  }
}

/**
 * A store that records rather than commits.
 *
 * `implements CanvasDocumentStore` on purpose: the canvas's contract with WP-B
 * is structural, so the compiler is what keeps this double honest when that
 * contract moves. A double that has quietly diverged from its subject certifies
 * nothing, which this repo has now recorded twice as a closed defect.
 */
class RecordingStore implements CanvasDocumentStore {
  readonly doc = shallowRef<BuilderDocument>(document([]))
  readonly commits: string[] = []
  readonly edgesAdded: Array<{ origin: EdgeOrigin; target: NodeId }> = []
  readonly nodesAdded: Array<{ node: BuilderNode; connectFrom: EdgeOrigin | null }> = []
  readonly moves: Array<{ moves: readonly NodeMove[]; coalesceKey?: string }> = []

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

  deleteSelection(): void {
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

function canvasOver(doc: BuilderDocument) {
  const store = new RecordingStore()
  store.doc.value = doc
  return { store, canvas: useBuilderCanvas({ document: store }) }
}

/* --- the parse refusals --------------------------------------------------- */

describe('the canvas refuses at the mouse only what the server refuses at parse', () => {
  it('will not draw an edge into an input node, which has no inbound port to hit', () => {
    const { canvas } = canvasOver(document([agentNode('scoper'), inputNode('idea')]))

    expect(
      canvas.isValidConnection({
        source: 'scoper',
        sourceHandle: 'out',
        target: 'idea',
        targetHandle: 'in',
      }),
    ).toBe(false)
  })

  it('will not draw an edge out of a port the source kind does not declare', () => {
    const { canvas } = canvasOver(document([agentNode('scoper'), agentNode('writer')]))

    // `approve` exists on a gate and nowhere else. Sending it would be an
    // `edge-unknown-port` at best and is a 422 at the schema.
    expect(
      canvas.isValidConnection({
        source: 'scoper',
        sourceHandle: 'approve',
        target: 'writer',
        targetHandle: 'in',
      }),
    ).toBe(false)
    expect(
      canvas.isValidConnection({
        source: 'scoper',
        sourceHandle: 'out',
        target: 'writer',
        targetHandle: 'in',
      }),
    ).toBe(true)
  })

  it('will not draw an edge out of an output node, which declares no ports at all', () => {
    const { canvas } = canvasOver(document([outputNode('report'), agentNode('writer')]))

    expect(
      canvas.isValidConnection({
        source: 'report',
        sourceHandle: 'out',
        target: 'writer',
        targetHandle: 'in',
      }),
    ).toBe(false)
  })

  it('will not accept a target handle other than `in`, the only one the schema has', () => {
    const { canvas } = canvasOver(document([agentNode('scoper'), agentNode('writer')]))

    expect(
      canvas.isValidConnection({
        source: 'scoper',
        sourceHandle: 'out',
        target: 'writer',
        targetHandle: 'approve',
      }),
    ).toBe(false)
  })

  it('will not draw a second edge on a source, port and target it already has', () => {
    const doc = document(
      [gateNode('confirm'), agentNode('writer')],
      [edge('e1', 'confirm', 'approve', 'writer')],
    )
    const { canvas } = canvasOver(doc)

    expect(
      canvas.isValidConnection({
        source: 'confirm',
        sourceHandle: 'approve',
        target: 'writer',
        targetHandle: 'in',
      }),
    ).toBe(false)
    // The SAME pair on the gate's other port is a different edge and is legal -
    // ChatDev's edge identity is `${from}-${to}`, which cannot represent this.
    expect(
      canvas.isValidConnection({
        source: 'confirm',
        sourceHandle: 'revise',
        target: 'writer',
        targetHandle: 'in',
      }),
    ).toBe(true)
  })
})

/* --- and permits everything the server merely reports --------------------- */

describe('the canvas permits every connection whose objection is a Problem', () => {
  it('draws a fifth outgoing edge, because fan-out width is a count the server owns', () => {
    // The explicit anti-regression for R6. `MAX_FANOUT_WIDTH` is 4; this is the
    // fifth, and the author is meant to be told about it by a problem row they
    // can read, not by a connection that mysteriously will not land.
    const targets = ['a', 'b', 'c', 'd', 'e'].map(agentNode)
    const doc = document(
      [gateNode('confirm'), ...targets],
      ['a', 'b', 'c', 'd'].map((target, index) =>
        edge(`e${index + 1}`, 'confirm', 'approve', target),
      ),
    )
    const { canvas } = canvasOver(doc)

    expect(
      canvas.isValidConnection({
        source: 'confirm',
        sourceHandle: 'approve',
        target: 'e',
        targetHandle: 'in',
      }),
    ).toBe(true)
  })

  it('draws a loop-closing edge out of an agent, and only marks it as doomed', () => {
    // `back-edge-not-router` is the server's. What the canvas does is rim the
    // ancestors so the author can see the loop forming, and say - in the rim,
    // not in a refusal - that this source may not close one.
    const doc = document(
      [agentNode('scoper'), agentNode('writer')],
      [edge('e1', 'scoper', 'out', 'writer')],
    )
    const { canvas } = canvasOver(doc)

    canvas.onConnectStart({ nodeId: 'writer', handleId: 'out' })
    const scoper = canvas.nodes.value.find((node) => node.id === 'scoper')
    expect(scoper?.data.loopTarget).toBe(true)
    expect(scoper?.data.loopIllegal).toBe(true)
    expect(
      canvas.isValidConnection({
        source: 'writer',
        sourceHandle: 'out',
        target: 'scoper',
        targetHandle: 'in',
      }),
    ).toBe(true)
  })

  it('rims a loop from a router without calling it illegal', () => {
    const doc = document(
      [agentNode('scoper'), routerNode('route', ['again', 'otherwise'])],
      [edge('e1', 'scoper', 'out', 'route')],
    )
    const { canvas } = canvasOver(doc)

    canvas.onConnectStart({ nodeId: 'route', handleId: 'again' })
    const scoper = canvas.nodes.value.find((node) => node.id === 'scoper')
    expect(scoper?.data.loopTarget).toBe(true)
    expect(scoper?.data.loopIllegal).toBe(false)
  })

  it('never refuses an edge Vue Flow is only re-parsing, however illegal it looks', () => {
    // `createGraphEdges` pushes the whole projection through `isValidConnection`
    // on every `setEdges`. This edge is an `edge-target-refuses-incoming` the
    // server will report; refusing it here would delete it from the canvas and
    // leave the problem row pointing at nothing.
    const doc = document(
      [agentNode('scoper'), inputNode('idea')],
      [edge('e1', 'scoper', 'out', 'idea')],
    )
    const { canvas } = canvasOver(doc)

    expect(
      canvas.isValidConnection({
        id: 'e1',
        source: 'scoper',
        sourceHandle: 'out',
        target: 'idea',
        targetHandle: 'in',
      }),
    ).toBe(true)
    expect(canvas.edges.value.map((entry) => entry.id)).toEqual(['e1'])
  })
})

/* --- the duplicate set ---------------------------------------------------- */

describe('the duplicate check is built once per drag, not once per hover', () => {
  it('reuses one Set across every candidate the pointer passes over', () => {
    const doc = document(
      [gateNode('confirm'), agentNode('a'), agentNode('b'), agentNode('c')],
      [edge('e1', 'confirm', 'approve', 'a')],
    )
    const { canvas } = canvasOver(doc)

    canvas.onConnectStart({ nodeId: 'confirm', handleId: 'approve' })
    const built = canvas.connectDrag.value?.existing
    expect(built).toEqual(new Set(['confirm|approve|a']))

    for (const target of ['a', 'b', 'c', 'a', 'b']) {
      canvas.isValidConnection({
        source: 'confirm',
        sourceHandle: 'approve',
        target,
        targetHandle: 'in',
      })
    }

    // Identity, not equality: a rebuilt Set with the same members would pass an
    // `toEqual` and would still be O(E) on every pointer frame.
    expect(canvas.connectDrag.value?.existing).toBe(built)
  })

  it('builds a fresh Set for the next drag rather than carrying the last one', () => {
    const doc = document(
      [gateNode('confirm'), agentNode('a')],
      [edge('e1', 'confirm', 'approve', 'a')],
    )
    const { canvas } = canvasOver(doc)

    canvas.onConnectStart({ nodeId: 'confirm', handleId: 'approve' })
    const first = canvas.connectDrag.value?.existing
    canvas.onConnectEnd()
    canvas.onConnectStart({ nodeId: 'confirm', handleId: 'revise' })

    expect(canvas.connectDrag.value?.existing).not.toBe(first)
    expect(canvas.connectDrag.value?.port).toBe('revise')
  })

  it('still answers correctly for a click-connect, where no drag was ever started', () => {
    // `connectOnClick` is on by default, and it reaches `isValidConnection` with
    // `connectDrag` null. The O(E) fallback is the only path that runs then.
    const doc = document(
      [gateNode('confirm'), agentNode('a')],
      [edge('e1', 'confirm', 'approve', 'a')],
    )
    const { canvas } = canvasOver(doc)

    expect(canvas.connectDrag.value).toBeNull()
    expect(
      canvas.isValidConnection({
        source: 'confirm',
        sourceHandle: 'approve',
        target: 'a',
        targetHandle: 'in',
      }),
    ).toBe(false)
  })
})

/* --- what the projection publishes ---------------------------------------- */

describe('the ports the projection publishes are the ports the card draws', () => {
  it('gives a gate exactly approve then revise, in that canvas order', () => {
    const { canvas } = canvasOver(document([gateNode('confirm')]))

    expect(canvas.nodes.value[0].data.ports).toEqual(['approve', 'revise'])
  })

  it('gives an output node no ports and an input node no inbound port', () => {
    const { canvas } = canvasOver(document([outputNode('report'), inputNode('idea')]))

    const [report, idea] = canvas.nodes.value
    expect(report.data.ports).toEqual([])
    expect(report.data.acceptsIncoming).toBe(true)
    expect(idea.data.acceptsIncoming).toBe(false)
  })

  it('grows a router port on the same tick a branch is added', () => {
    const { store, canvas } = canvasOver(document([routerNode('route', ['hot', 'otherwise'])]))
    expect(canvas.nodes.value[0].data.ports).toEqual(['hot', 'otherwise'])

    store.doc.value = document([routerNode('route', ['hot', 'cold', 'otherwise'])])

    expect(canvas.nodes.value[0].data.ports).toEqual(['hot', 'cold', 'otherwise'])
  })

  it('labels only the edges whose source has more than one way out', () => {
    const doc = document(
      [
        gateNode('confirm'),
        routerNode('route', ['again', 'otherwise']),
        agentNode('writer'),
        agentNode('second'),
      ],
      [
        edge('e1', 'confirm', 'approve', 'writer'),
        edge('e2', 'route', 'otherwise', 'writer'),
        edge('e3', 'writer', 'out', 'second'),
      ],
    )
    const { canvas } = canvasOver(doc)

    const [approve, otherwise, plain] = canvas.edges.value
    expect(approve.data.portLabel).toBe('approve')
    expect(approve.data.portRole).toBe('approve')
    expect(otherwise.data.portRole).toBe('otherwise')
    // A single-output source draws no chip: a label reading `out` on every edge
    // in the graph is furniture, and furniture is what stops labels being read.
    expect(plain.data.portLabel).toBeNull()
    expect(plain.data.portRole).toBeNull()
  })

  it('marks a node that could receive the edge being drawn, and the ones that could not', () => {
    const doc = document(
      [gateNode('confirm'), agentNode('taken'), agentNode('free'), inputNode('idea')],
      [edge('e1', 'confirm', 'approve', 'taken')],
    )
    const { canvas } = canvasOver(doc)

    canvas.onConnectStart({ nodeId: 'confirm', handleId: 'approve' })
    const byId = new Map(canvas.nodes.value.map((node) => [node.id, node.data]))

    expect(byId.get('free')?.connectable).toBe(true)
    expect(byId.get('taken')?.connectable).toBe(false)
    expect(byId.get('idea')?.connectable).toBe(false)

    canvas.onConnectEnd()
    expect(canvas.nodes.value.every((node) => !node.data.connectable)).toBe(true)
  })
})

/* --- edge endpoints ------------------------------------------------------- */

describe('dragging an edge endpoint keeps the edge rather than replacing it', () => {
  const doc = () =>
    document(
      [gateNode('confirm'), agentNode('writer'), agentNode('other')],
      [edge('e1', 'confirm', 'approve', 'writer')],
    )

  it('moves a gate edge between approve and revise as a port change', () => {
    const { store, canvas } = canvasOver(doc())

    canvas.onEdgeUpdate({
      edge: { id: 'e1', source: 'confirm', target: 'writer', sourceHandle: 'approve' },
      connection: { source: 'confirm', target: 'writer', sourceHandle: 'revise' },
    })

    expect(store.commits).toEqual(['setEdgePort'])
  })

  it('treats a new target as a retarget, not a delete and a redraw', () => {
    const { store, canvas } = canvasOver(doc())

    canvas.onEdgeUpdate({
      edge: { id: 'e1', source: 'confirm', target: 'writer', sourceHandle: 'approve' },
      connection: { source: 'confirm', target: 'other', sourceHandle: 'approve' },
    })

    expect(store.commits).toEqual(['retargetEdge'])
  })

  it('does nothing at all when the endpoint lands back where it started', () => {
    const { store, canvas } = canvasOver(doc())

    canvas.onEdgeUpdate({
      edge: { id: 'e1', source: 'confirm', target: 'writer', sourceHandle: 'approve' },
      connection: { source: 'confirm', target: 'writer', sourceHandle: 'approve' },
    })

    expect(store.commits).toEqual([])
  })
})

/* A compile-time reminder that the branded ids above are the real ones. */
const _ids: [NodeId, EdgeId] = [nodeId('scoper'), edgeId('e1')]
void _ids
