import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { NODE_KINDS, NODE_KIND_ORDER, outPortsOf } from '../src/data/nodeKinds'
import { nodeId } from '../src/types/builder'
import type { BuilderNode, NodeKind, RouterBranch } from '../src/types/builder'

/**
 * The drawn ports are the accepted ports.
 *
 * `nodeKinds.ts` is the only place the client decides which handles a card
 * renders, which connections `isValidConnection` permits and what `PortMenu`
 * offers - and the server decides the same thing independently, in
 * `document.py:_OUT_PORTS_BY_KIND` and `BuilderNode.out_ports`. A divergence
 * between the two is silent in both directions: a port drawn that the server
 * does not know produces `edge-unknown-port` on an edge the author was invited
 * to draw, and a port not drawn is a branch nothing on the canvas can reach.
 *
 * So this file reads the Python at run time rather than restating it. A test
 * that transcribed the dict would prove only that two copies of one mistake
 * agree, which is the failure the repo's own counts hit five times.
 */

function pythonSource(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8')
}

const DOCUMENT_PY = pythonSource('../../src/brief_crew/builder/document.py')
const BUILDER_API_PY = pythonSource('../../src/brief_crew/service/builder_api.py')

/**
 * `_OUT_PORTS_BY_KIND` as the Python declares it.
 *
 * `router` is deliberately absent from that dict - its ports ARE its branch
 * labels and so are computed per node - which is itself asserted below.
 */
function pythonOutPorts(): Record<string, string[]> {
  const block = /_OUT_PORTS_BY_KIND: dict\[str, tuple\[str, \.\.\.\]\] = \{([^}]*)\}/.exec(
    DOCUMENT_PY,
  )
  expect(block, 'the _OUT_PORTS_BY_KIND literal moved or changed shape').not.toBeNull()
  const ports: Record<string, string[]> = {}
  for (const row of (block as RegExpExecArray)[1].matchAll(/"([a-z_]+)":\s*\(([^)]*)\)/g)) {
    ports[row[1]] = [...row[2].matchAll(/"([a-z_]+)"/g)].map((port) => port[1])
  }
  return ports
}

/** The `node_kinds` list `_vocabulary()` serves, in the order it serves them. */
function pythonNodeKinds(): string[] {
  const row = /node_kinds=\[([^\]]*)\]/.exec(BUILDER_API_PY)
  expect(row, 'the node_kinds literal moved in _vocabulary()').not.toBeNull()
  return [...(row as RegExpExecArray)[1].matchAll(/"([a-z]+)"/g)].map((kind) => kind[1])
}

const at = { x: 0, y: 0 }

/**
 * A node of a kind, built by hand rather than through `newNode`.
 *
 * `outPorts` reads only `kind` and - for a router - `config.branches`, so the
 * rest is filled with whatever the union demands. Going through `newNode` would
 * make every assertion here depend on the vocabulary having loaded, which is a
 * different subject with its own file.
 */
function nodeOf(kind: NodeKind, branches: RouterBranch[] = []): BuilderNode {
  const base = { id: nodeId('n'), label: 'N', position: at }
  switch (kind) {
    case 'input':
      return { ...base, kind, config: { field: nodeId('idea'), label: null, max_chars: 2000, required: true } }
    case 'agent':
      return {
        ...base,
        kind,
        config: {
          tier: 'cheap',
          max_iter: 2,
          guardrail_max_retries: 2,
          prompt_inputs: {},
          agent_id: nodeId('scoper'),
          tools: [],
        },
      }
    case 'crew':
      return {
        ...base,
        kind,
        config: {
          tier: 'cheap',
          max_iter: 2,
          guardrail_max_retries: 2,
          prompt_inputs: {},
          crew_id: nodeId('scope'),
        },
      }
    case 'gate':
      return {
        ...base,
        kind,
        config: { message: 'Look at this', editable_fields: [], max_turns: 1, expiry_seconds: 1800 },
      }
    case 'router':
      return { ...base, kind, config: { branches } }
    case 'transform':
      return { ...base, kind, config: { op: 'pick', args: {} } }
    case 'output':
      return { ...base, kind, config: { body_key: 'markdown_body', source: null } }
  }
}

describe('every kind the server compiles has exactly one record', () => {
  it('covers the seven kinds the vocabulary serves, in the vocabulary order', () => {
    // The palette renders `vocabulary.node_kinds` in the server's order and the
    // number hotkeys read `paletteOrder`. If the two ever disagree, key `3`
    // drops a different kind from the tile above it.
    expect(NODE_KIND_ORDER).toEqual(pythonNodeKinds())
  })

  it('keys the record by the kind each entry names', () => {
    for (const kind of NODE_KIND_ORDER) {
      expect(NODE_KINDS[kind].kind).toBe(kind)
    }
  })

  it('gives each kind the card class the design tenancy hangs the gradient off', () => {
    for (const kind of NODE_KIND_ORDER) {
      expect(NODE_KINDS[kind].className).toBe(`is-kind-${kind}`)
    }
  })

  it('gives each kind a colour no other kind uses, so a minimap dot means something', () => {
    const accents = NODE_KIND_ORDER.map((kind) => NODE_KINDS[kind].accent)
    expect(new Set(accents).size).toBe(accents.length)
    // Every one is a stop of that kind's `--node-gradient` in the spec's §5.1
    // block, so a dot and the card it stands for cannot be different colours.
    for (const accent of accents) expect(accent).toMatch(/^#[0-9a-f]{6}$/)
  })

  it('numbers the palette 0..6 with no gaps, because the hotkeys are 1..7', () => {
    const orders = NODE_KIND_ORDER.map((kind) => NODE_KINDS[kind].paletteOrder)
    expect(orders).toEqual([0, 1, 2, 3, 4, 5, 6])
  })
})

describe('the ports the canvas draws are the ports bounds.py accepts', () => {
  const declared = pythonOutPorts()

  it('reads six kinds out of the python, and not the seventh', () => {
    // If this fails the regex above stopped matching and every assertion below
    // is passing over an empty object - which is how a mirror rots quietly.
    expect(Object.keys(declared).sort()).toEqual([
      'agent',
      'crew',
      'gate',
      'input',
      'output',
      'transform',
    ])
  })

  for (const [kind, ports] of Object.entries(declared)) {
    it(`gives ${kind} exactly the ports _OUT_PORTS_BY_KIND gives it`, () => {
      expect(outPortsOf(nodeOf(kind as NodeKind))).toEqual(ports)
    })
  }

  it('offers the gate approve then revise, in that canvas order', () => {
    // Order is not cosmetic here: §5.3 places `approve` at 30% and `revise` at
    // 70%, so a swap moves the mint port under the amber label.
    expect(outPortsOf(nodeOf('gate'))).toEqual(['approve', 'revise'])
  })

  it('gives an output node no source port at all, rather than an inert one', () => {
    expect(outPortsOf(nodeOf('output'))).toEqual([])
  })

  it('computes a router s ports from its branch labels, as the python property does', () => {
    // `router` is absent from the dict because `BuilderNode.out_ports` computes
    // it. Asserting the property's own text is what keeps this mirror honest
    // when the dict cannot carry the answer.
    expect(DOCUMENT_PY).toContain('return tuple(branch.label for branch in self.config.branches)')

    const branches: RouterBranch[] = [
      { label: nodeId('hot'), op: 'gt', key: nodeId('score'), value: 7 },
      { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
    ]
    expect(outPortsOf(nodeOf('router', branches))).toEqual(['hot', 'otherwise'])
  })

  it('grows a router s ports the moment a branch is added', () => {
    const two: RouterBranch[] = [
      { label: nodeId('hot'), op: 'gt', key: nodeId('score'), value: 7 },
      { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
    ]
    const three: RouterBranch[] = [
      two[0],
      { label: nodeId('cold'), op: 'lt', key: nodeId('score'), value: 3 },
      two[1],
    ]
    expect(outPortsOf(nodeOf('router', two))).toHaveLength(2)
    expect(outPortsOf(nodeOf('router', three))).toEqual(['hot', 'cold', 'otherwise'])
  })

  it('gives a router with no branches no ports, exactly as the python does', () => {
    // The empty tuple is the schema's own default. It is two problems
    // (`router-branch-count`, `router-otherwise`) and zero ports, not a crash -
    // which is why `newNode` never produces one.
    expect(outPortsOf(nodeOf('router'))).toEqual([])
  })
})

describe('only an input node refuses an inbound edge', () => {
  it('mirrors accepts_incoming, which is the kind not being input', () => {
    expect(DOCUMENT_PY).toContain('return self.kind != "input"')
    for (const kind of NODE_KIND_ORDER) {
      expect(NODE_KINDS[kind].acceptsIncoming).toBe(kind !== 'input')
    }
  })
})
