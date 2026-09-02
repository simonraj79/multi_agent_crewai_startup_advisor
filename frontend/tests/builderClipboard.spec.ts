import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BUILDER_SCHEMA_ID, documentId, edgeId, nodeId } from '../src/types/builder'
import type {
  AgentConfig,
  BuilderDocument,
  BuilderEdge,
  BuilderNode,
  InputConfig,
  OutputConfig,
  RouterConfig,
  TransformConfig,
} from '../src/types/builder'
import { useBuilderDocument } from '../src/composables/useBuilderDocument'
import { parseEnvelope, useBuilderClipboard } from '../src/composables/useBuilderClipboard'

/**
 * Pasting a fragment whose nodes still talk to each other.
 *
 * The gap this closes is that IDS ARE ALSO DATA. A node id is not only an
 * identity - the compiler derives `out__<id>` from it, and an author writes that
 * key by hand inside values the schema is perfectly happy to take as plain
 * strings. Re-minting the ids of a pasted fragment without moving those
 * references produces nodes that talk to the ORIGINALS, or, pasted into another
 * document, to nothing at all.
 *
 * There are FOUR places one can hide and they are not alike. Three carry the
 * `${state.…}` wrapper - a `prompt_inputs` value, a `transform.args` value, an
 * `output.source` - and one does not: a router branch's `key` is written BARE,
 * because `compiler.py:565` passes it straight into the compiled `with:` block
 * as the key `route_branch` reads. A rewrite that only walked `${state.…}`
 * tokens would leave every router in the fragment pointing at the node it was
 * copied from, and nothing downstream would say a word - the branch simply
 * never matches and `otherwise` is taken for the life of the workflow.
 *
 * The second gap is the clipboard itself. `navigator.clipboard` is absent over
 * plain HTTP, absent in every headless runner, and permission-gated everywhere
 * else, so "copy silently reached nothing" is the common case rather than the
 * exotic one. A copy that says nothing is indistinguishable from one that
 * worked, and the author finds out at paste time - by which point the selection
 * they made is gone.
 */

/* --- a fragment with a reference in all four hiding places ---------------- */

const INPUT: InputConfig = {
  field: nodeId('idea'),
  label: null,
  max_chars: 2000,
  required: true,
}

const MARKET: AgentConfig = {
  tier: 'cheap',
  max_iter: 2,
  guardrail_max_retries: 2,
  prompt_inputs: {},
  agent_id: nodeId('market_analyst'),
  tools: [],
}

/** Hiding place 1: a `prompt_inputs` VALUE. */
const WRITER: AgentConfig = { ...MARKET, prompt_inputs: { brief: '${state.out__market}' } }

/** Hiding place 2: a `transform.args` VALUE. */
const SHAPE: TransformConfig = { op: 'pick', args: { source: '${state.out__market}', key: 'body' } }

/** Hiding place 3: a router branch `key`, written BARE - no `${state.…}` wrapper. */
const ROUTE: RouterConfig = {
  branches: [
    { label: nodeId('rich'), op: 'contains', key: nodeId('out__market'), value: 'segment' },
    { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
  ],
}

/** Hiding place 4: `output.source`. */
const OUT: OutputConfig = { body_key: 'markdown_body', source: '${state.out__market}' }

function node(
  id: string,
  kind: BuilderNode['kind'],
  config: BuilderNode['config'],
  label: string,
  x = 0,
  y = 0,
): BuilderNode {
  return { id: nodeId(id), kind, label, position: { x, y }, config } as BuilderNode
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

function sample(): BuilderDocument {
  return {
    schema: BUILDER_SCHEMA_ID,
    id: documentId('ug_0a1b2c3d'),
    name: 'Sample',
    version: 4,
    input_field: nodeId('idea'),
    nodes: [
      node('idea', 'input', INPUT, 'Idea', 0, 0),
      node('market', 'agent', MARKET, 'Market', 100, 100),
      node('writer', 'agent', WRITER, 'Writer', 100, 200),
      node('shape', 'transform', SHAPE, 'Shape', 100, 300),
      node('route', 'router', ROUTE, 'Route', 100, 400),
      node('out', 'output', OUT, 'Out', 100, 500),
    ],
    edges: [
      // `idea -> market` has one endpoint outside every copy below. It must not
      // travel with the fragment.
      edge('e1', 'idea', 'market'),
      edge('e2', 'market', 'writer'),
      edge('e3', 'writer', 'shape'),
      edge('e4', 'shape', 'route'),
      edge('e5', 'route', 'out'),
    ],
    joins: { writer: 'all', idea: 'all' },
    budget: null,
  }
}

const FRAGMENT = ['market', 'writer', 'shape', 'route', 'out'].map(nodeId)

/** The document store plus a clipboard over it, with no system clipboard present. */
function session() {
  const document = useBuilderDocument(sample())
  return { document, clipboard: useBuilderClipboard(document) }
}

/** Install a system clipboard whose two halves can each be made to fail. */
function stubClipboard(behaviour: { write?: () => Promise<void>; read?: () => Promise<string> }) {
  const writeText = vi.fn(behaviour.write ?? (() => Promise.resolve()))
  const readText = vi.fn(behaviour.read ?? (() => Promise.resolve('')))
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText, readText },
    configurable: true,
  })
  return { writeText, readText }
}

beforeEach(() => {
  Reflect.deleteProperty(navigator, 'clipboard')
})

afterEach(() => {
  Reflect.deleteProperty(navigator, 'clipboard')
})

/* --- the rewrite ---------------------------------------------------------- */

describe('a pasted fragment keeps talking to itself', () => {
  async function pasted() {
    const { document, clipboard } = session()
    await clipboard.copy(FRAGMENT)
    const ids = await clipboard.paste({ x: 400, y: 100 })
    const byId = new Map(document.doc.value.nodes.map((each) => [each.id as string, each]))
    return { document, clipboard, ids, byId }
  }

  it('re-mints every id rather than pasting a duplicate-node-id', async () => {
    const { ids } = await pasted()
    expect(ids).toEqual(['market_2', 'writer_2', 'shape_2', 'route_2', 'out_2'])
  })

  it('rewrites the reference inside a prompt_inputs value', async () => {
    const { byId } = await pasted()
    const config = byId.get('writer_2')?.config as AgentConfig
    expect(config.prompt_inputs.brief).toBe('${state.out__market_2}')
  })

  it('rewrites the reference inside a transform arg value', async () => {
    const { byId } = await pasted()
    const config = byId.get('shape_2')?.config as TransformConfig
    expect(config.args.source).toBe('${state.out__market_2}')
    // The arg that was never a reference is untouched.
    expect(config.args.key).toBe('body')
  })

  it('rewrites output.source', async () => {
    const { byId } = await pasted()
    expect((byId.get('out_2')?.config as OutputConfig).source).toBe('${state.out__market_2}')
  })

  it('rewrites a router branch key, which carries no ${state.…} wrapper at all', async () => {
    const { byId } = await pasted()
    const config = byId.get('route_2')?.config as RouterConfig
    expect(config.branches[0].key).toBe('out__market_2')
    expect(config.branches[1].key).toBeNull()
  })

  it('leaves the originals exactly as they were', async () => {
    const { byId } = await pasted()
    expect((byId.get('writer')?.config as AgentConfig).prompt_inputs.brief).toBe(
      '${state.out__market}',
    )
    expect((byId.get('route')?.config as RouterConfig).branches[0].key).toBe('out__market')
  })
})

describe('what travels with a fragment and what does not', () => {
  it('drops an edge with one endpoint outside the copied set', async () => {
    const { document, clipboard } = session()
    await clipboard.copy(FRAGMENT)
    await clipboard.paste({ x: 400, y: 100 })

    const added = document.doc.value.edges.filter((each) => each.source.endsWith('_2'))
    expect(added).toHaveLength(4)
    // `idea -> market` is not among them: pasting five of six nodes must not
    // hand the author an `edge-unknown-endpoint` they did not make.
    expect(document.doc.value.edges.some((each) => each.target === 'market_2')).toBe(false)
  })

  it('re-mints edge ids, so pasting back into the source document is not a duplicate-edge-id', async () => {
    const { document, clipboard } = session()
    await clipboard.copy(FRAGMENT)
    await clipboard.paste({ x: 400, y: 100 })
    const ids = document.doc.value.edges.map((each) => each.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).toContain('e6')
  })

  it('carries a joins key whose node was copied and drops one whose node was not', async () => {
    const { document, clipboard } = session()
    await clipboard.copy(FRAGMENT)
    await clipboard.paste({ x: 400, y: 100 })
    expect(document.doc.value.joins).toEqual({ idea: 'all', writer: 'all', writer_2: 'all' })
  })

  it('is ONE commit, labelled with what it did', async () => {
    const { document, clipboard } = session()
    await clipboard.copy(FRAGMENT)
    await clipboard.paste({ x: 400, y: 100 })

    expect(document.depth.value).toBe(1)
    expect(document.undoLabel.value).toBe('Paste 5 nodes')
    document.undo()
    expect(document.doc.value.nodes).toHaveLength(6)
    expect(document.doc.value.edges).toHaveLength(5)
  })
})

/* --- placement ------------------------------------------------------------ */

describe('where a fragment lands', () => {
  it('puts the fragment top-left at the position it was given, keeping the shape', async () => {
    const { document, clipboard } = session()
    await clipboard.copy(FRAGMENT)
    await clipboard.paste({ x: 400, y: 60 })

    const byId = new Map(document.doc.value.nodes.map((each) => [each.id as string, each]))
    // The fragment's own box starts at (100, 100); every node moves by the same
    // delta, so the layout the author arranged survives the paste.
    expect(byId.get('market_2')?.position).toEqual({ x: 400, y: 60 })
    expect(byId.get('out_2')?.position).toEqual({ x: 400, y: 460 })
  })

  it('rounds, because `Position` is declared int and a half pixel is a 422 minutes later', async () => {
    const { document, clipboard } = session()
    await clipboard.copy(FRAGMENT)
    await clipboard.paste({ x: 400.5, y: 60.4 })
    const market = document.doc.value.nodes.find((each) => each.id === 'market_2')
    expect(market?.position).toEqual({ x: 401, y: 60 })
  })

  it('offsets a duplicate by +24/+24 and never touches the system clipboard', () => {
    const { writeText } = stubClipboard({})
    const { document, clipboard } = session()

    clipboard.duplicate([nodeId('market')])
    const copy = document.doc.value.nodes.find((each) => each.id === 'market_2')
    expect(copy?.position).toEqual({ x: 124, y: 124 })
    expect(document.undoLabel.value).toBe('Duplicate 1 node')
    // Duplicating must not destroy whatever the author copied earlier.
    expect(writeText).not.toHaveBeenCalled()
  })
})

/* --- cut ------------------------------------------------------------------ */

describe('cut', () => {
  it('copies first, then deletes with the cascade, as one undo step', async () => {
    const { document, clipboard } = session()
    await clipboard.cut([nodeId('writer')])

    expect(document.doc.value.nodes.some((each) => each.id === 'writer')).toBe(false)
    expect(document.undoLabel.value).toBe('Cut node')
    expect(document.doc.value.joins).toEqual({ idea: 'all' })

    await clipboard.paste({ x: 500, y: 500 })
    const restored = document.doc.value.nodes.find((each) => each.id === 'writer')
    expect((restored?.config as AgentConfig).prompt_inputs.brief).toBe('${state.out__market}')
  })
})

/* --- the clipboard itself -------------------------------------------------- */

describe('a system clipboard that is absent or refused', () => {
  it('says so rather than reporting a copy that reached nothing', async () => {
    const { clipboard } = session()
    await clipboard.copy(FRAGMENT)
    expect(clipboard.notice.value).toMatch(/inside this tab only/)
  })

  it('says so when the write is rejected outright', async () => {
    stubClipboard({ write: () => Promise.reject(new Error('NotAllowedError')) })
    const { clipboard } = session()
    await clipboard.copy(FRAGMENT)
    expect(clipboard.notice.value).toMatch(/inside this tab only/)
  })

  it('still pastes, from the in-memory copy, when both halves are refused', async () => {
    stubClipboard({
      write: () => Promise.reject(new Error('NotAllowedError')),
      read: () => Promise.reject(new Error('NotAllowedError')),
    })
    const { document, clipboard } = session()
    await clipboard.copy(FRAGMENT)
    const ids = await clipboard.paste({ x: 400, y: 100 })

    expect(ids).toHaveLength(5)
    expect(document.depth.value).toBe(1)
  })

  it('says nothing was copied rather than committing an empty paste', async () => {
    const { document, clipboard } = session()
    const ids = await clipboard.paste({ x: 0, y: 0 })
    expect(ids).toEqual([])
    expect(document.depth.value).toBe(0)
    expect(clipboard.notice.value).toBe('Nothing on the clipboard to paste.')
  })

  it('prefers what is on the system clipboard over what this tab last copied', async () => {
    const { document, clipboard } = session()
    await clipboard.copy([nodeId('market')])

    // A different tab copied one node in the meantime.
    const elsewhere = {
      __builder: BUILDER_SCHEMA_ID,
      nodes: [node('foreign', 'input', INPUT, 'Foreign', 0, 0)],
      edges: [],
      joins: {},
      bbox: { x: 0, y: 0, width: 0, height: 0 },
    }
    stubClipboard({ read: () => Promise.resolve(JSON.stringify(elsewhere)) })

    await clipboard.paste({ x: 0, y: 0 })
    expect(document.doc.value.nodes.some((each) => each.id === 'foreign')).toBe(true)
    expect(document.doc.value.nodes.some((each) => each.id === 'market_2')).toBe(false)
  })
})

describe('parseEnvelope', () => {
  it('refuses anything that is not a builder fragment', () => {
    expect(parseEnvelope('')).toBeNull()
    expect(parseEnvelope('https://example.com')).toBeNull()
    expect(parseEnvelope('{ not json')).toBeNull()
    expect(parseEnvelope('{"nodes":[]}')).toBeNull()
  })

  it('refuses a fragment written under a different schema id', () => {
    const future = JSON.stringify({ __builder: 'builder.flow/v2', nodes: [{}], edges: [] })
    expect(parseEnvelope(future)).toBeNull()
  })

  it('accepts one this build wrote, and supplies a bbox it was sent without', () => {
    const envelope = JSON.stringify({
      __builder: BUILDER_SCHEMA_ID,
      nodes: [node('market', 'agent', MARKET, 'Market', 40, 80)],
      edges: [],
    })
    expect(parseEnvelope(envelope)?.bbox).toEqual({ x: 40, y: 80, width: 0, height: 0 })
  })
})
