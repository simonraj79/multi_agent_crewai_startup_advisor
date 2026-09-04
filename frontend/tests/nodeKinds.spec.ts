import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { NODE_KINDS, NODE_KIND_ORDER, outPortsOf } from '../src/data/nodeKinds'
import { ATTACHMENT_KINDS, nodeId } from '../src/types/builder'
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
const TOKENS_CSS = pythonSource('../src/assets/styles/tokens.css')
const TYPES_TS = pythonSource('../src/types/builder.ts')

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

/**
 * `document.py:NodeKind` - the CLOSED union, in the order the Python declares
 * it, which is also the order this client's palette numbers.
 *
 * This is the contract. It moved here from `_vocabulary()`'s `node_kinds`
 * literal when the union grew to ten, and the move is a correction rather than
 * a convenience: `NodeKind` is what `BuilderNode` discriminates on and what the
 * compiler will accept, while the vocabulary list is what one endpoint happens
 * to be serving today. Those two are allowed to differ during a build - this
 * one serves the v1 seven while the union is already ten - and when they do, it
 * is the union the client's records must be total over.
 */
function pythonNodeKinds(): string[] {
  const block = /^NodeKind = Literal\[([\s\S]*?)\n\]/m.exec(DOCUMENT_PY)
  expect(block, 'the NodeKind Literal moved or changed shape').not.toBeNull()
  return [...(block as RegExpExecArray)[1].matchAll(/"([a-z]+)"/g)].map((kind) => kind[1])
}

/** The `node_kinds` list `_vocabulary()` serves, in the order it serves them. */
function servedNodeKinds(): string[] {
  const row = /node_kinds=\[([^\]]*)\]/.exec(BUILDER_API_PY)
  expect(row, 'the node_kinds literal moved in _vocabulary()').not.toBeNull()
  return [...(row as RegExpExecArray)[1].matchAll(/"([a-z]+)"/g)].map((kind) => kind[1])
}

/** The string members of a `NAME: frozenset[str] = frozenset({...})` in `document.py`. */
function pythonFrozenset(name: string): string[] {
  const block = new RegExp(`^${name}[^=]*= frozenset\\(([\\s\\S]*?)\\n?\\)`, 'm').exec(DOCUMENT_PY)
  expect(block, `document.py declares no readable ${name}`).not.toBeNull()
  return [...(block as RegExpExecArray)[1].matchAll(/"([a-z]+)"/g)].map((entry) => entry[1])
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
    case 'tool':
      return { ...base, kind, config: { tool_id: nodeId('firecrawl_scrape'), params: {}, credential_id: null } }
    case 'mcp':
      return { ...base, kind, config: { server_id: nodeId('sandbox'), tool_names: [], credential_id: null } }
    case 'skill':
      return { ...base, kind, config: { skill_id: nodeId('house_style') } }
  }
}

/** An agent or a crew that routes its failures rather than ending the run. */
function routing(kind: 'agent' | 'crew'): BuilderNode {
  const node = nodeOf(kind)
  return { ...node, config: { ...node.config, on_error: 'route' } } as BuilderNode
}

describe('every kind the server compiles has exactly one record', () => {
  it('covers the TEN kinds document.py declares, in the Python order', () => {
    // Criterion 1's client half. `NodeKind` is a closed union on both sides of
    // the wire, and this reads the Python's own `Literal[...]` rather than a
    // transcription of it - a transcription would prove only that two copies of
    // one mistake agree, which is the failure this repo's counts hit five times.
    expect(pythonNodeKinds()).toHaveLength(10)
    expect(NODE_KIND_ORDER).toEqual(pythonNodeKinds())
  })

  it('splits them into the two families document.py partitions them into', () => {
    // `ATTACHMENT_KINDS` and `FLOW_KINDS` are frozensets over there and the
    // `family` field over here. An eleventh kind added to one set and not the
    // other is exactly the defect the partition exists to prevent, so both
    // directions are read out of the Python.
    const attachments = pythonFrozenset('ATTACHMENT_KINDS')
    const flow = pythonFrozenset('FLOW_KINDS')
    expect([...attachments].sort()).toEqual([...ATTACHMENT_KINDS].sort())
    expect([...attachments, ...flow].sort()).toEqual([...pythonNodeKinds()].sort())

    for (const kind of NODE_KIND_ORDER) {
      const expected = attachments.includes(kind) ? 'attachment' : 'flow'
      expect(NODE_KINDS[kind].family, `${kind} is in the wrong family`).toBe(expected)
    }
  })

  it('knows every kind the vocabulary actually serves, in that relative order', () => {
    /*
     * The weaker, TRUE assertion - and the weakening is deliberate and is worth
     * naming rather than hiding. This build's `_vocabulary()` still serves the
     * v1 seven while `NodeKind` is already ten (C2 v2 is criterion 5, the Python
     * half of this plan), so an equality here would fail on the plan's own
     * sequencing rather than on a defect.
     *
     * What still matters is asserted: the palette renders `node_kinds` in the
     * SERVER's order and reads `NODE_KINDS[kind]` for each, so every served kind
     * must have a record, and the relative order must agree or a tile and the
     * key printed on it would be about different kinds.
     */
    const served = servedNodeKinds()
    for (const kind of served) expect(NODE_KIND_ORDER).toContain(kind)
    expect(NODE_KIND_ORDER.filter((kind) => served.includes(kind))).toEqual(served)
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

  it('keeps the three attachment accents in step with their tokens.css values', () => {
    /*
     * The three new accents live in TWO places, and this is the guard that makes
     * that defensible. `tokens.css` owns them because they are new colours and a
     * new colour is a token; `nodeKinds.ts` restates each because a minimap dot
     * is an SVG `fill` ATTRIBUTE and cannot read a custom property from a
     * stylesheet. A drift between the two is a canvas whose pills and whose dots
     * are different colours, which is silent - so it is a failing test instead.
     */
    for (const kind of ATTACHMENT_KINDS) {
      const declared = new RegExp(`--kind-${kind}: (#[0-9a-f]{6});`).exec(TOKENS_CSS)
      expect(declared, `tokens.css declares no --kind-${kind}`).not.toBeNull()
      expect(NODE_KINDS[kind].accent).toBe((declared as RegExpExecArray)[1])
    }
  })

  it('numbers the palette 0..9 with no gaps, flow first and attachments last', () => {
    const orders = NODE_KIND_ORDER.map((kind) => NODE_KINDS[kind].paletteOrder)
    expect(orders).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    expect(NODE_KIND_ORDER.slice(7)).toEqual([...ATTACHMENT_KINDS])
  })

  it('keys the seven flow kinds by digit and the three attachments by letter', () => {
    /*
     * Owner's decision 18, 2026-09-04. The attachments are `T`, `M`, `K` and NOT
     * `8`, `9`, `0`: the digits `1`-`7` already select a kind on the same
     * surface, so a second digit row is a collision an author discovers by
     * pressing one, and `0` reads as "none".
     *
     * The flow half is still `paletteOrder + 1`, asserted rather than assumed,
     * because that is what stops a renumbering from moving a key off its tile.
     */
    const keys = NODE_KIND_ORDER.map((kind) => NODE_KINDS[kind].hotkey)
    expect(keys).toEqual(['1', '2', '3', '4', '5', '6', '7', 'T', 'M', 'K'])
    for (const kind of NODE_KIND_ORDER) {
      const meta = NODE_KINDS[kind]
      if (meta.family === 'flow') expect(meta.hotkey).toBe(String(meta.paletteOrder + 1))
    }
    // Every key is distinct, which is the whole reason the decision was made.
    expect(new Set(keys).size).toBe(keys.length)
  })
})

describe('the three target ports are the three the server accepts', () => {
  it('mirrors TARGET_PORTS, the one field an edge class is a function of', () => {
    /*
     * `in` is the flow itself; `attach` hangs a possession off an agent or a
     * crew; `member` puts an agent inside a crew. This is the ONLY input to an
     * edge's class on either side of the wire, which is what lets the canvas's
     * stroke rules and `bounds.py`'s edge rules agree about one string rather
     * than each deciding independently what the source happened to be - so a
     * fourth value appearing on one side and not the other is the exact drift
     * worth a test.
     *
     * Read as source text on this side because `TargetPort` is a TYPE and does
     * not survive to run time; a runtime tuple beside it would be a third copy.
     */
    expect(pythonFrozenset('TARGET_PORTS')).toEqual(['in', 'attach', 'member'])
    expect(TYPES_TS).toContain("export type TargetPort = 'in' | 'attach' | 'member'")
    expect(DOCUMENT_PY).toContain('target_port: Literal["in", "attach", "member"] = "in"')
  })
})

describe('the ports the canvas draws are the ports bounds.py accepts', () => {
  const declared = pythonOutPorts()

  it('reads nine kinds out of the python, and not the tenth', () => {
    // If this fails the regex above stopped matching and every assertion below
    // is passing over an empty object - which is how a mirror rots quietly.
    // `router` is the one absentee: its ports ARE its branch labels, so
    // `BuilderNode.out_ports` computes them and the dict cannot carry them.
    expect(Object.keys(declared).sort()).toEqual([
      'agent',
      'crew',
      'gate',
      'input',
      'mcp',
      'output',
      'skill',
      'tool',
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

  it('gives each attachment one port, and it is a SOURCE named attach', () => {
    /*
     * The asymmetry that pays for itself. An attachment reaches TOWARD the agent
     * rather than the agent reaching down for it, and the obvious alternative -
     * an `attach` INPUT on the agent - costs more than it looks: with the arrow
     * this way round, an edge's class is a pure function of `target_port` and of
     * nothing else, so the canvas's stroke rules and `bounds.py`'s edge rules
     * agree about one string instead of each deciding independently what the
     * source happened to be.
     */
    for (const kind of ATTACHMENT_KINDS) {
      expect(outPortsOf(nodeOf(kind)), `${kind}`).toEqual(['attach'])
    }
  })

  it('grows an error port on a billable node ONLY when on_error is route', () => {
    /*
     * D1's one conditional row. `on_error` is optional and absent by default -
     * `_BillableConfig` has no such field yet and `BuilderModel` is
     * `extra="forbid"`, so a document that carried the key would be a 422 - and
     * absent must therefore read as `fail`, which is what keeps every existing
     * document's edges legal.
     */
    for (const kind of ['agent', 'crew'] as const) {
      expect(outPortsOf(nodeOf(kind)), `${kind} default`).toEqual(['out'])
      expect(outPortsOf(routing(kind)), `${kind} routing`).toEqual(['out', 'error'])
    }
  })

  it('does not grow an error port on anything that is not billable', () => {
    // `on_error` is not a field on the other eight configs at all, so this is a
    // statement about the OTHER direction: nothing else reads it, and a stray
    // key on a gate cannot conjure a port. Written as a loop rather than as one
    // example, because "only agent and crew" is the claim.
    for (const kind of NODE_KIND_ORDER) {
      if (kind === 'agent' || kind === 'crew') continue
      expect(outPortsOf(nodeOf(kind))).not.toContain('error')
    }
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

describe('four kinds refuse an inbound edge, for two different reasons', () => {
  it('mirrors accepts_incoming: not input, and not a possession', () => {
    /*
     * `input` refuses because it is where the run starts. The three ATTACHMENT
     * kinds refuse because nothing flows INTO a possession - an author who could
     * draw an edge into a tool would be describing a step, and a tool is not a
     * step. Two reasons, one predicate, read out of the Python rather than
     * restated.
     */
    expect(DOCUMENT_PY).toContain(
      'return self.kind != "input" and self.kind not in ATTACHMENT_KINDS',
    )
    const attachments = pythonFrozenset('ATTACHMENT_KINDS')
    const refusing: NodeKind[] = []
    for (const kind of NODE_KIND_ORDER) {
      const accepts = kind !== 'input' && !attachments.includes(kind)
      expect(NODE_KINDS[kind].acceptsIncoming, kind).toBe(accepts)
      if (!accepts) refusing.push(kind)
    }
    expect(refusing).toEqual(['input', 'tool', 'mcp', 'skill'])
  })
})
