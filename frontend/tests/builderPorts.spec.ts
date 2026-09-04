import { readFileSync } from 'node:fs'
import path from 'node:path'
import { shallowRef } from 'vue'
import { beforeAll, describe, expect, it } from 'vitest'
import { targetPortsOf, useBuilderCanvas } from '../src/composables/useBuilderCanvas'
import { useBuilderDocument } from '../src/composables/useBuilderDocument'
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

function crewNode(id: string): BuilderNode {
  return {
    id: nodeId(id),
    label: id,
    position: { x: 0, y: 0 },
    kind: 'crew',
    config: {
      tier: 'cheap',
      max_iter: 2,
      guardrail_max_retries: 2,
      prompt_inputs: {},
      crew_id: nodeId('brief'),
    },
  }
}

function toolNode(id: string): BuilderNode {
  return {
    id: nodeId(id),
    label: id,
    position: { x: 0, y: 0 },
    kind: 'tool',
    config: { tool_id: nodeId('tool'), params: {}, credential_id: null },
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

/* --- the port table on the other side of the edge -------------------------- */

describe('a target port exists only on the kinds that offer it', () => {
  it('gives every flow kind `in`, and the two billable ones the structural ports', () => {
    // The mirror `TARGET_PORTS_BY_KIND` states, read back through the one
    // function `isValidConnection` and the card both call. `document.py` has
    // `TARGET_PORTS` - the three legal strings - and does not yet say which
    // kind offers which; when `/vocabulary` starts serving `target_ports` this
    // table is deleted and read from there.
    expect(targetPortsOf('agent')).toEqual(['in', 'attach'])
    expect(targetPortsOf('crew')).toEqual(['in', 'attach', 'member'])
    expect(targetPortsOf('gate')).toEqual(['in'])
  })

  it('gives an input node and all three attachments no target port at all', () => {
    // `input` because it is where the run starts; the attachments because
    // nothing flows INTO a possession. An author who could draw an edge into a
    // tool would be describing a step, and a tool is not a step.
    expect(targetPortsOf('input')).toEqual([])
    expect(targetPortsOf('tool')).toEqual([])
    expect(targetPortsOf('mcp')).toEqual([])
    expect(targetPortsOf('skill')).toEqual([])
  })

  it('publishes the same list on the projection the card draws from', () => {
    const { canvas } = canvasOver(document([crewNode('research'), toolNode('search')]))
    const byId = new Map(canvas.nodes.value.map((node) => [node.id, node.data]))
    expect(byId.get('research')?.targetPorts).toEqual(['in', 'attach', 'member'])
    expect(byId.get('search')?.targetPorts).toEqual([])
  })
})

describe('the three FD4 class rules are refusals, not counts', () => {
  it('lets a tool attach to an agent and to a crew', () => {
    const { canvas } = canvasOver(
      document([toolNode('search'), agentNode('scoper'), crewNode('research')]),
    )
    for (const target of ['scoper', 'research']) {
      expect(
        canvas.isValidConnection({
          source: 'search',
          sourceHandle: 'attach',
          target,
          targetHandle: 'attach',
        }),
      ).toBe(true)
    }
  })

  it('refuses an `attach` edge whose source is not an attachment kind', () => {
    // A gate cannot be a possession. Only a tool, an MCP server or a skill can.
    const { canvas } = canvasOver(document([gateNode('confirm'), agentNode('scoper')]))
    expect(
      canvas.isValidConnection({
        source: 'confirm',
        sourceHandle: 'approve',
        target: 'scoper',
        targetHandle: 'attach',
      }),
    ).toBe(false)
  })

  it('refuses `member` from anything but an agent, and accepts it from one', () => {
    const { canvas } = canvasOver(
      document([agentNode('scoper'), crewNode('research'), crewNode('other')]),
    )
    expect(
      canvas.isValidConnection({
        source: 'scoper',
        sourceHandle: 'out',
        target: 'research',
        targetHandle: 'member',
      }),
    ).toBe(true)
    // A crew inside a crew is a nesting the compiler has no shape for.
    expect(
      canvas.isValidConnection({
        source: 'other',
        sourceHandle: 'out',
        target: 'research',
        targetHandle: 'member',
      }),
    ).toBe(false)
  })

  it('refuses an attachment reaching an `in` port, the accident an author makes', () => {
    // `in` is the big obvious port at the top of every card, so this is the
    // wrong drop somebody really makes - and nothing an agent HAS is a step.
    const { canvas } = canvasOver(document([toolNode('search'), agentNode('scoper')]))
    expect(
      canvas.isValidConnection({
        source: 'search',
        sourceHandle: 'attach',
        target: 'scoper',
        targetHandle: 'in',
      }),
    ).toBe(false)
  })

  it('refuses `attach` and `member` on a kind that offers neither', () => {
    const { canvas } = canvasOver(document([toolNode('search'), gateNode('confirm')]))
    expect(
      canvas.isValidConnection({
        source: 'search',
        sourceHandle: 'attach',
        target: 'confirm',
        targetHandle: 'attach',
      }),
    ).toBe(false)
  })
})

/* --- a refused drop says so and commits nothing ---------------------------- */

/** A pointer event whose `target` is inside Vue Flow's own node wrapper. */
function overCard(id: string): MouseEvent {
  const card = window.document.createElement('div')
  card.className = 'vue-flow__node'
  card.setAttribute('data-id', id)
  window.document.body.appendChild(card)
  const event = new MouseEvent('mouseup', { clientX: 40, clientY: 40 })
  Object.defineProperty(event, 'target', { value: card })
  return event
}

describe('a drop released over a card that refused it flashes and does not commit', () => {
  it('leaves the undo depth exactly where it was', () => {
    // The real store, not the recording double, because the criterion is about
    // `depth` - and a double that reports its own idea of depth would certify
    // nothing. `depth` is 0 before and 0 after: no commit was made to undo.
    const store = useBuilderDocument(document([toolNode('search'), agentNode('scoper')]))
    const canvas = useBuilderCanvas({
      document: {
        doc: store.doc,
        addNode: (node, connectFrom) =>
          store.addNode(node, connectFrom ? { edge: { ...connectFrom, target: node.id } } : undefined),
        addEdge: (origin, target) => store.addEdge({ ...origin, target }),
        moveNodes: (moves) => store.moveNodes(moves),
        deleteSelection: (nodes, edges) => store.deleteSelection(nodes, edges),
        setEdgePort: (edge, port) => store.setEdgePort(edge, port),
        retargetEdge: () => undefined,
        setJoin: (node, join) => store.setJoin(node, join === 'all'),
      },
    })

    expect(store.depth.value).toBe(0)
    canvas.onConnectStart({ nodeId: 'search', handleId: 'attach' })
    canvas.onConnectEnd(overCard('scoper'))

    expect(store.depth.value).toBe(0)
    expect(store.doc.value.edges).toEqual([])
  })

  it('does not open the port menu, because the author was pointing at a node', () => {
    // `PortMenu` offers to CREATE a node. Opening it here would answer a
    // question nobody asked and hide the refusal behind a menu, which is the
    // Flowise v2 failure - its cycle rejection does nothing at all.
    const { store, canvas } = canvasOver(document([toolNode('search'), agentNode('scoper')]))
    canvas.onConnectStart({ nodeId: 'search', handleId: 'attach' })
    canvas.onConnectEnd(overCard('scoper'))

    expect(canvas.portMenuRequest.value).toBeNull()
    expect(store.commits).toEqual([])
  })

  it('marks the card refused, so the canvas says no out loud', () => {
    const { canvas } = canvasOver(document([toolNode('search'), agentNode('scoper')]))
    canvas.onConnectStart({ nodeId: 'search', handleId: 'attach' })
    canvas.onConnectEnd(overCard('scoper'))

    const scoper = canvas.nodes.value.find((node) => node.id === 'scoper')
    expect(scoper?.data.refused).toBe(true)
  })

  it('still opens the port menu when the drop really was on the background', () => {
    const { canvas } = canvasOver(document([agentNode('scoper'), agentNode('writer')]))
    canvas.onConnectStart({ nodeId: 'scoper', handleId: 'out' })
    const onPane = new MouseEvent('mouseup', { clientX: 12, clientY: 12 })
    Object.defineProperty(onPane, 'target', { value: window.document.createElement('div') })
    canvas.onConnectEnd(onPane)

    expect(canvas.portMenuRequest.value?.origin).toEqual({ source: 'scoper', source_port: 'out' })
  })
})

/* --- the port an edge LANDS on is the port it is written with (13 f/u 1) ----
 *
 * The defect this describe block pins is the sharpest kind there is: the
 * gesture validated one edge and committed a different one, and every surface
 * agreed with the wrong answer.
 *
 * `isValidConnection` has always read `targetHandle`, so dragging from a tool's
 * `attach` port onto an agent's `attach` port went GREEN. `onConnect` then
 * dropped the handle, and `useBuilderDocument.addEdge` wrote
 * `target_port: 'in'` from a literal one line below its own spread of
 * `EdgeEnds` - a field that was declared, documented and overwritten. So the
 * author drew an attachment, the document recorded a flow edge, `edgeClassOf`
 * drew it as a flow edge because it reads `target_port`, and the server came
 * back with `attach-target-not-agent` about a shape nobody had drawn.
 *
 * Attach-by-DROP was never affected - it goes through `addNode`'s third
 * argument - which is exactly why this survived a suite with attach coverage
 * in it. So these tests go through the REAL store, the whole way down.
 */

describe('a connect gesture writes the target port it was validated against', () => {
  function liveCanvasOver(doc: BuilderDocument) {
    const store = useBuilderDocument(doc)
    const canvas = useBuilderCanvas({
      document: {
        doc: store.doc,
        addNode: (node, connectFrom) =>
          store.addNode(node, connectFrom ? { edge: { ...connectFrom, target: node.id } } : undefined),
        // The adapter `BuilderView` writes, verbatim: it CARRIES the port and
        // defaults nothing, because a second spelling of the `'in'` default is
        // how the two ends came apart to begin with.
        addEdge: (origin, target, targetPort) =>
          store.addEdge({ ...origin, target, target_port: targetPort }),
        moveNodes: (moves) => store.moveNodes(moves),
        deleteSelection: (nodes, edges) => store.deleteSelection(nodes, edges),
        setEdgePort: (edge, port) => store.setEdgePort(edge, port),
        retargetEdge: () => undefined,
        setJoin: (node, join) => store.setJoin(node, join === 'all'),
      },
    })
    return { store, canvas }
  }

  it('writes `attach` when the drag lands on an attach port', () => {
    const { store, canvas } = liveCanvasOver(document([toolNode('search'), agentNode('scoper')]))

    // The same connection object Vue Flow hands `@connect`, and the same one
    // `isValidConnection` accepted a frame earlier.
    const connection = {
      source: 'search',
      sourceHandle: 'attach',
      target: 'scoper',
      targetHandle: 'attach',
    }
    expect(canvas.isValidConnection(connection)).toBe(true)
    canvas.onConnect(connection)

    expect(store.doc.value.edges).toHaveLength(1)
    expect(store.doc.value.edges[0].target_port).toBe('attach')
  })

  it('writes `member` when an agent is dragged onto a crew member port', () => {
    const { store, canvas } = liveCanvasOver(document([agentNode('scoper'), crewNode('brief')]))

    const connection = {
      source: 'scoper',
      sourceHandle: 'out',
      target: 'brief',
      targetHandle: 'member',
    }
    expect(canvas.isValidConnection(connection)).toBe(true)
    canvas.onConnect(connection)

    expect(store.doc.value.edges[0].target_port).toBe('member')
  })

  it('still writes `in` for an ordinary flow edge, and for a handle-less one', () => {
    // The default has to stay exactly `isValidConnection`'s own, or the gesture
    // validates one edge and commits another in the other direction.
    const { store, canvas } = liveCanvasOver(document([agentNode('scoper'), outputNode('done')]))

    canvas.onConnect({ source: 'scoper', sourceHandle: 'out', target: 'done', targetHandle: 'in' })
    canvas.onConnect({ source: 'scoper', sourceHandle: 'error', target: 'done' })

    expect(store.doc.value.edges.map((edge) => edge.target_port)).toEqual(['in', 'in'])
  })

  it('draws the committed edge as the CLASS its port makes it', () => {
    // `edgeClassOf` reads `target_port`, so the write being wrong made the
    // colour wrong too - an attachment painted as a step in the flow.
    const { canvas } = liveCanvasOver(document([toolNode('search'), agentNode('scoper')]))

    canvas.onConnect({
      source: 'search',
      sourceHandle: 'attach',
      target: 'scoper',
      targetHandle: 'attach',
    })

    const edge = canvas.edges.value.find((candidate) => candidate.source === 'search')
    expect(edge?.data?.edgeClass).toBe('attach')
  })
})

/* --- the pixels (criterion 1) ---------------------------------------------- */

/**
 * `builder.css`, parsed by jsdom, and read two different ways.
 *
 * The handle itself is asked through `getComputedStyle`, which is the real
 * cascade over a real element. The disc has to be read off the CSSOM rule
 * instead, because jsdom does not implement `getComputedStyle(el, '::after')`
 * at all - it logs "Not implemented" and hands back the element's own style,
 * which would silently pass. A rule read out of the real file is still the
 * single source of truth; what it is not is a layout, and MISSION.md's trap 13
 * is that a jsdom mount never asks how wide anything ended up. The BROWSER
 * answer is `e2e/builder.spec.ts`, which measures the bounding box.
 */
describe('the hit target is 24px and the disc inside it is 12px', () => {
  let sheet: CSSStyleSheet

  beforeAll(() => {
    const css = readFileSync(path.resolve(process.cwd(), 'src/assets/styles/builder.css'), 'utf8')
    const style = window.document.createElement('style')
    style.textContent = css
    window.document.head.appendChild(style)
    sheet = style.sheet as CSSStyleSheet
  })

  function ruleFor(selector: string): CSSStyleDeclaration {
    const rule = Array.from(sheet.cssRules)
      .filter((entry): entry is CSSStyleRule => entry instanceof CSSStyleRule)
      .find((entry) => entry.selectorText.replace(/\s+/g, ' ').trim() === selector)
    expect(rule, 'builder.css has no rule for ' + selector).toBeDefined()
    return (rule as CSSStyleRule).style
  }

  it('computes the handle at 24 by 24 with nothing drawn on it', () => {
    const handle = window.document.createElement('div')
    handle.className = 'builder-port vue-flow__handle is-port-out'
    window.document.body.appendChild(handle)
    const computed = window.getComputedStyle(handle)

    expect(computed.width).toBe('24px')
    expect(computed.height).toBe('24px')
    // Transparent, because the 24px box is the TARGET. A 24px block of accent
    // would read as a button rather than as a port.
    expect(computed.backgroundColor).toBe('rgba(0, 0, 0, 0)')
    expect(computed.borderTopWidth).toBe('0px')
  })

  it('draws the visible disc at 12px, centred inside that box', () => {
    const disc = ruleFor('.builder-port.vue-flow__handle::after')
    expect(disc.width).toBe('12px')
    expect(disc.height).toBe('12px')
    expect(disc.borderRadius).toBe('var(--r-full)')
    expect(disc.transform).toBe('translate(-50%, -50%)')
  })

  it('keeps twice the target it draws, which is the whole point', () => {
    const handle = ruleFor('.builder-port.vue-flow__handle')
    const disc = ruleFor('.builder-port.vue-flow__handle::after')
    expect(Number.parseFloat(handle.width)).toBe(2 * Number.parseFloat(disc.width))
    // Flowise v1 is 10px hit on a 10px visual and v2 is a 20px hit target that
    // is INVISIBLE until the node is hovered. This is large and visible at once.
    expect(Number.parseFloat(handle.width)).toBeGreaterThan(10)
    expect(Number.parseFloat(disc.width)).toBeGreaterThanOrEqual(10)
  })

  it('restates the per-side offset in all four hover transforms', () => {
    // A hover rule that writes only `scale()` drops Vue Flow's centring offset,
    // and the port jumps half its own height the moment the pointer arrives -
    // which reads as the target running away, on the one control where that is
    // fatal. All four sides, because D1 puts ports on all four.
    expect(ruleFor('.builder-node:hover .builder-port.vue-flow__handle-bottom').transform).toBe(
      'translate(-50%, 50%) scale(1.33)',
    )
    expect(ruleFor('.builder-node:hover .builder-port.vue-flow__handle-top').transform).toBe(
      'translate(-50%, -50%) scale(1.33)',
    )
    expect(ruleFor('.builder-node:hover .builder-port.vue-flow__handle-left').transform).toBe(
      'translate(-50%, -50%) scale(1.33)',
    )
    expect(ruleFor('.builder-node:hover .builder-port.vue-flow__handle-right').transform).toBe(
      'translate(50%, -50%) scale(1.33)',
    )
  })

  it('gives the two structural ports a shape rather than only a colour', () => {
    // At 50% zoom the disc is six pixels across, and six pixels of violet
    // against six of mint is not a distinction. A square still reads as a
    // square, and a diamond as a diamond, in print and under deuteranopia too.
    const attach = ruleFor('.builder-port.is-port-attach::after')
    expect(attach.borderRadius).toBe('1px')
    expect(attach.borderColor).toBe('var(--accent-attach)')

    const member = ruleFor('.builder-port.is-port-member::after')
    expect(member.borderRadius).toBe('1px')
    expect(member.transform).toBe('translate(-50%, -50%) rotate(45deg)')
  })

  it('paints the connect-drag answer on the disc, green for yes and red for no', () => {
    expect(ruleFor('.builder-port.vue-flow__handle-valid::after').background).toBe(
      'var(--accent-mint)',
    )
    expect(ruleFor('.builder-port.vue-flow__handle-valid').cursor).toBe('crosshair')
    const refused = ruleFor(
      '.builder-port.vue-flow__handle-connecting:not(.vue-flow__handle-valid)::after',
    )
    expect(refused.background).toBe('var(--err-text)')
    expect(
      ruleFor('.builder-port.vue-flow__handle-connecting:not(.vue-flow__handle-valid)').cursor,
    ).toBe('not-allowed')
  })
})

/* A compile-time reminder that the branded ids above are the real ones. */
const _ids: [NodeId, EdgeId] = [nodeId('scoper'), edgeId('e1')]
void _ids
