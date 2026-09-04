import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MAX_NODE_ID_CHARS, mintNodeId, newNode } from '../src/data/builderDefaults'
import {
  loadVocabulary,
  resetVocabulary,
  vocabulary,
  vocabularyProblem,
  vocabularyUnavailable,
} from '../src/data/builderVocabulary'
import { NODE_KINDS, NODE_KIND_ORDER, outPortsOf } from '../src/data/nodeKinds'
import { NODE_ID_PATTERN } from '../src/types/builder'
import type { NodeKind } from '../src/types/builder'

/**
 * A node arrives schema-valid, or dragging a tile is a 422.
 *
 * `BuilderDocument.model_validate` is the only judge of a document, and it runs
 * on the next save - which is seconds after the drop and nowhere near it. So
 * every default here is checked against the pydantic model that will receive it:
 * the KEY SET against the model's own field list, and every bound against the
 * `config.py` constant the field's `ge`/`le` names. Both are read out of the
 * Python at run time, because a transcribed constant proves only that two copies
 * of one mistake agree.
 *
 * The other half of the file is the vocabulary, and the property it must have is
 * negative: when the fetch fails, nothing is fabricated. `newNode` refuses
 * rather than inventing an `agent_id`, because a client that guesses at the
 * server's allowlist draws graphs the compiler rejects (cut list 17).
 */

function pythonSource(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8')
}

const DOCUMENT_PY = pythonSource('../../src/brief_crew/builder/document.py')
const CONFIG_PY = pythonSource('../../src/brief_crew/config.py')
const RUNTIME_PY = pythonSource('../../src/brief_crew/builder/runtime.py')
const BUILDER_API_PY = pythonSource('../../src/brief_crew/service/builder_api.py')

/** The keys of a module-level `Mapping[...]` literal in runtime.py. */
function pythonMappingKeys(name: string): string[] {
  const start = RUNTIME_PY.indexOf('\n' + name + ':')
  expect(start, `${name} moved or changed shape in runtime.py`).toBeGreaterThan(-1)
  const body = RUNTIME_PY.slice(start, RUNTIME_PY.indexOf('\n}', start))
  const keys = [...body.matchAll(/^ {4}"([a-z_]+)":/gm)].map((entry) => entry[1])
  expect(keys.length, `${name} parsed as empty`).toBeGreaterThan(0)
  return keys
}

/**
 * `sorted(BUILDABLE_BUILDER_CREW_IDS)` - the list `_vocabulary()` actually
 * serves, computed from the Python rather than transcribed.
 *
 * This used to be six literal ids in the fixture below, `synthesis` and
 * `report` among them, which meant the crew-default test was fed a payload the
 * live endpoint has never sent - and the client-side skip-list it certified was
 * therefore unreachable against the real server. `BUILDABLE_BUILDER_CREW_IDS`
 * is `BUILDER_CREW_LIBRARY` minus `UNBUILDABLE_BUILDER_CREWS`, so deriving it
 * the same way here is what keeps the fixture honest when a seventh crew lands.
 */
const UNBUILDABLE_CREW_IDS = pythonMappingKeys('UNBUILDABLE_BUILDER_CREWS')
const BUILDABLE_CREW_IDS = pythonMappingKeys('BUILDER_CREW_LIBRARY')
  .filter((id) => !UNBUILDABLE_CREW_IDS.includes(id))
  .sort()

/** A module-level integer, whether it is a literal or an env-var default. */
function pythonInt(name: string): number {
  const pattern = new RegExp(`^${name}(?:: int)? = (?:_env_\\w+\\("${name}", )?(\\d+)`, 'm')
  const match = pattern.exec(CONFIG_PY)
  expect(match, `${name} moved or changed shape in config.py`).not.toBeNull()
  return Number((match as RegExpExecArray)[1])
}

/** The string members of a `frozenset({...})` or a `(...)` tuple in config.py. */
function pythonStrings(name: string, open: '{' | '(', close: '}' | ')'): string[] {
  const pattern = new RegExp(`${name}[^${open === '{' ? '{' : '('}]*\\${open}([^\\${close}]*)\\${close}`)
  const match = pattern.exec(CONFIG_PY)
  expect(match, `${name} moved or changed shape in config.py`).not.toBeNull()
  return [...(match as RegExpExecArray)[1].matchAll(/"([a-z_]+)"/g)].map((entry) => entry[1])
}

/**
 * The field names one pydantic config model declares.
 *
 * Fields sit at four spaces; continuation lines, decorators and method bodies do
 * not, which is what tells an annotation apart from everything else in the class
 * body. `AgentConfig` and `CrewConfig` extend `_BillableConfig`, so their callers
 * union the parent in - the inheritance is the reason `BillableForm` is one
 * component for both kinds.
 */
function pythonFields(className: string): string[] {
  const start = DOCUMENT_PY.indexOf(`\nclass ${className}(`)
  expect(start, `class ${className} is gone from document.py`).toBeGreaterThan(-1)
  const rest = DOCUMENT_PY.slice(start + 1)
  const end = rest.indexOf('\nclass ')
  const body = end === -1 ? rest : rest.slice(0, end)
  return [...body.matchAll(/^ {4}([a-z][a-z0-9_]*):/gm)].map((entry) => entry[1])
}

const BILLABLE_FIELDS = pythonFields('_BillableConfig')

const FIELDS_BY_KIND: Record<NodeKind, string[]> = {
  input: pythonFields('InputConfig'),
  agent: [...BILLABLE_FIELDS, ...pythonFields('AgentConfig')],
  crew: [...BILLABLE_FIELDS, ...pythonFields('CrewConfig')],
  gate: pythonFields('GateConfig'),
  router: pythonFields('RouterConfig'),
  transform: pythonFields('TransformConfig'),
  output: pythonFields('OutputConfig'),
  // The three attachments, read out of the same Python. `ToolConfig`,
  // `McpConfig` and `SkillConfig` extend `BuilderModel` directly rather than a
  // shared base - they have nothing in common but being possessions - so unlike
  // the billable pair there is no parent list to union in.
  tool: pythonFields('ToolConfig'),
  mcp: pythonFields('McpConfig'),
  skill: pythonFields('SkillConfig'),
}

/**
 * The vocabulary payload, shaped exactly as `_vocabulary()` serves it - every
 * bound a JSON float, every list sorted the way the handler sorts it.
 */
function vocabularyPayload(): Record<string, unknown> {
  return {
    schema_id: 'builder.flow/v1',
    node_kinds: ['input', 'agent', 'crew', 'gate', 'router', 'transform', 'output'],
    tiers: ['cheap', 'escalation'],
    agent_ids: [
      'feasibility_analyst',
      'market_analyst',
      'reporter',
      'scoper',
      'sentiment_analyst',
      'synthesist',
    ],
    crew_ids: BUILDABLE_CREW_IDS,
    research_tools: [
      'analyze_community_sentiment',
      'assess_technical_feasibility',
      'research_market_landscape',
    ],
    transform_ops: ['default', 'format', 'join_text', 'merge', 'pick', 'to_json'],
    router_comparisons: ['contains', 'eq', 'gt', 'gte', 'lt', 'lte', 'ne'],
    router_otherwise: 'otherwise',
    result_body_keys: ['markdown_body'],
    bounds: {
      max_graph_nodes: 24.0,
      max_billable_nodes: 8.0,
      max_escalation_nodes: 5.0,
      max_fanout_width: 4.0,
      min_router_branches: 2.0,
      max_cycles: 2.0,
      max_cycle_iterations: 3.0,
      max_agent_iter: 8.0,
      max_guardrail_retries: 2.0,
      max_label_chars: 40.0,
      max_name_chars: 80.0,
      max_gate_message_chars: 2000.0,
      max_input_chars: 2000.0,
      max_document_bytes: 262144.0,
      run_cost_ceiling_usd: 10.0,
    },
  }
}

/** A `fetch` that answers the vocabulary endpoint with `payload`. */
function servingFetch(payload: unknown, status = 200): ReturnType<typeof vi.fn> {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Service Unavailable',
    json: async () => payload,
  }))
}

function stubFetch(fetchImpl: unknown): void {
  vi.stubGlobal('fetch', fetchImpl)
}

afterEach(() => {
  vi.unstubAllGlobals()
  resetVocabulary()
})

describe('the vocabulary is fetched once and never invented', () => {
  beforeEach(() => {
    resetVocabulary()
  })

  it('truncates the count bounds and leaves the dollar ceiling alone', async () => {
    /*
     * `bounds` is `dict[str, float]`, so `24.0` is what goes on the wire - and
     * `JSON.parse` already turns that into 24, which is why this uses genuinely
     * fractional values instead. Trunc is what makes every count an integer
     * whatever the server computed; the ceiling is dollars, and truncating a
     * deliberate `MAX_RUN_COST_USD=2.50` into a $2.00 bound would refuse graphs
     * the operator can afford.
     */
    const payload = vocabularyPayload()
    Object.assign(payload.bounds as Record<string, number>, {
      max_graph_nodes: 24.7,
      run_cost_ceiling_usd: 2.5,
    })
    stubFetch(servingFetch(payload))

    const served = await loadVocabulary()
    expect(served?.bounds.max_graph_nodes).toBe(24)
    expect(served?.bounds.run_cost_ceiling_usd).toBe(2.5)
  })

  it('makes one request however many palettes ask at once', async () => {
    const fetchImpl = servingFetch(vocabularyPayload())
    stubFetch(fetchImpl)

    const [first, second] = await Promise.all([loadVocabulary(), loadVocabulary()])
    await loadVocabulary()

    expect(fetchImpl).toHaveBeenCalledTimes(1)
    expect(first).toBe(second)
  })

  it('asks the builder prefix, with no credential', async () => {
    const fetchImpl = servingFetch(vocabularyPayload())
    stubFetch(fetchImpl)
    await loadVocabulary()

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit]
    // No auth: `get_vocabulary` carries no `Depends(current_user)`, and this has
    // to resolve before the auth gate does or the palette is disabled for the
    // whole of a sign-in.
    expect(url).toBe('/api/builder/vocabulary')
    expect(init.headers).toEqual({ Accept: 'application/json' })
  })

  it('reads a session copy back without a second request', async () => {
    stubFetch(servingFetch(vocabularyPayload()))
    await loadVocabulary()
    const stored = window.sessionStorage.getItem('builder-vocabulary')
    expect(stored).toBeTruthy()

    // `resetVocabulary` clears storage too, so the cache is re-seeded by hand:
    // this is the reload case, where the module singleton is gone and the tab is
    // not.
    resetVocabulary()
    window.sessionStorage.setItem('builder-vocabulary', stored as string)
    const fetchImpl = servingFetch(vocabularyPayload())
    stubFetch(fetchImpl)

    const served = await loadVocabulary()
    expect(served?.agent_ids).toHaveLength(6)
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('still loads when the browser refuses session storage', async () => {
    const store = window.sessionStorage
    vi.spyOn(store, 'getItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })
    vi.spyOn(store, 'setItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })
    stubFetch(servingFetch(vocabularyPayload()))

    expect(await loadVocabulary()).not.toBeNull()
    expect(vocabularyUnavailable.value).toBe(false)
  })
})

describe('a vocabulary that will not load degrades and says so', () => {
  beforeEach(() => {
    resetVocabulary()
  })

  it('states an unreachable API rather than offering a list of its own', async () => {
    stubFetch(vi.fn(async () => { throw new TypeError('Failed to fetch') }))

    expect(await loadVocabulary()).toBeNull()
    expect(vocabulary.value).toBeNull()
    expect(vocabularyUnavailable.value).toBe(true)
    expect(vocabularyProblem.value).toContain('Failed to fetch')
  })

  it('names the status when the API refuses', async () => {
    stubFetch(servingFetch({}, 503))

    expect(await loadVocabulary()).toBeNull()
    expect(vocabularyProblem.value).toContain('503')
  })

  it('refuses a build that compiles a different document schema', async () => {
    const payload = { ...vocabularyPayload(), schema_id: 'builder.flow/v2' }
    stubFetch(servingFetch(payload))

    expect(await loadVocabulary()).toBeNull()
    // Every save would be a 422 about `schema`, a field the author never typed.
    expect(vocabularyProblem.value).toContain('builder.flow/v2')
  })

  it('refuses a kind this console has no card for', async () => {
    const payload = vocabularyPayload()
    payload.node_kinds = [...(payload.node_kinds as string[]), 'webhook']
    stubFetch(servingFetch(payload))

    expect(await loadVocabulary()).toBeNull()
    expect(vocabularyProblem.value).toContain('webhook')
  })

  it('refuses an empty agent library, which no agent node could be saved without', async () => {
    const payload = { ...vocabularyPayload(), agent_ids: [] }
    stubFetch(servingFetch(payload))

    expect(await loadVocabulary()).toBeNull()
    expect(vocabularyProblem.value).toContain('agent_ids')
  })

  it('refuses a bound that is missing, rather than rendering NaN in a pip row', async () => {
    const payload = vocabularyPayload()
    delete (payload.bounds as Record<string, unknown>).max_billable_nodes
    stubFetch(servingFetch(payload))

    expect(await loadVocabulary()).toBeNull()
    expect(vocabularyProblem.value).toContain('max_billable_nodes')
  })

  it('refuses to mint a node at all rather than guessing an agent id', async () => {
    stubFetch(vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    await loadVocabulary()

    expect(() => newNode('agent', { x: 0, y: 0 }, [])).toThrow(/vocabulary/)
  })
})

describe('a new node is one the server would accept', () => {
  beforeEach(async () => {
    resetVocabulary()
    stubFetch(servingFetch(vocabularyPayload()))
    await loadVocabulary()
  })

  for (const kind of NODE_KIND_ORDER) {
    it(`gives a fresh ${kind} exactly the config fields its pydantic model declares`, () => {
      const node = newNode(kind, { x: 0, y: 0 }, [])
      // `BuilderModel` is `extra="forbid"`, so a key too many is a 422 naming a
      // field the author never typed - and a key too few is a 422 too, for the
      // required ones. The set has to be exact in both directions.
      expect(Object.keys(node.config).sort()).toEqual([...FIELDS_BY_KIND[kind]].sort())
    })

    it(`gives a fresh ${kind} a legal id, label and integer position`, () => {
      const node = newNode(kind, { x: 12.4, y: -3.6 }, [])
      expect(node.id).toMatch(NODE_ID_PATTERN)
      expect(node.id).toBe(`${kind}_1`)
      expect(node.label).toBe(`${NODE_KINDS[kind].defaultLabel} 1`)
      expect(node.label.length).toBeLessThanOrEqual(pythonInt('BUILDER_MAX_LABEL_CHARS'))
      // `Position` declares `int`; pydantic coerces 120.0 and refuses 120.5.
      expect(node.position).toEqual({ x: 12, y: -4 })
    })
  }

  it('takes the first free suffix, so a delete leaves a gap to reuse', () => {
    expect(newNode('agent', { x: 0, y: 0 }, ['agent_1', 'agent_2']).id).toBe('agent_3')
    expect(newNode('agent', { x: 0, y: 0 }, ['agent_2']).id).toBe('agent_1')
    // The label follows the id, so `agent_3` is never labelled "Agent 1".
    expect(newNode('gate', { x: 0, y: 0 }, ['gate_1']).label).toBe('Gate 2')
  })

  it('gives an input node its own id as the run input key', () => {
    const first = newNode('input', { x: 0, y: 0 }, [])
    const second = newNode('input', { x: 0, y: 0 }, [first.id])
    expect(first.kind === 'input' && first.config.field).toBe(first.id)
    // Two input nodes must not collide: a shared default field would make the
    // second one an `input-field-ambiguous` error about a box nobody has opened.
    expect(second.kind === 'input' && second.config.field).toBe(second.id)
    expect(first.config).not.toEqual(second.config)
  })

  it('asks an input node for as much text as the run endpoint accepts', () => {
    const node = newNode('input', { x: 0, y: 0 }, [])
    if (node.kind !== 'input') throw new Error('unreachable')
    expect(node.config.max_chars).toBe(pythonInt('MAX_RUN_INPUT_CHARS'))
    expect(node.config.required).toBe(true)
    // Null, not the canvas label: `document.py` keeps the operator's prompt and
    // the author's label apart on purpose.
    expect(node.config.label).toBeNull()
  })

  it('starts a billable node on the cheap tier at the schema defaults', () => {
    const node = newNode('agent', { x: 0, y: 0 }, [])
    if (node.kind !== 'agent') throw new Error('unreachable')
    // The escalation tier is the scarce one (5 of 8), so spending more has to be
    // an act rather than what happens when you drag a tile.
    expect(node.config.tier).toBe('cheap')
    expect(node.config.max_iter).toBe(pythonInt('VALIDATOR_BRANCH_MAX_ITER'))
    expect(node.config.guardrail_max_retries).toBe(pythonInt('BUILDER_MAX_GUARDRAIL_RETRIES'))
    expect(node.config.max_iter).toBeLessThanOrEqual(pythonInt('BUILDER_MAX_AGENT_ITER'))
    expect(node.config.agent_id).toBe(vocabulary.value?.agent_ids[0])
    expect(node.config.tools).toEqual([])
  })

  it('never defaults a crew to one that cannot be constructed', () => {
    const node = newNode('crew', { x: 0, y: 0 }, [])
    if (node.kind !== 'crew') throw new Error('unreachable')
    /*
     * `synthesis` and `report` compile, publish, and then raise `TypeError` at
     * the first PAID run - after every upstream billable node has billed. The
     * client is safe from them not because it carries a copy of the pair but
     * because the SERVER never offers them, so that is what this asserts: the
     * endpoint's own expression, read out of the Python, and the two ids absent
     * from the list it produces.
     *
     * This is the load-bearing line. Delete `crew_ids=sorted(BUILDABLE_...)`
     * from `_vocabulary()` and a fresh crew node starts naming whichever
     * unbuildable crew sorts first, which is a `TypeError` a paid run finds.
     */
    expect(BUILDER_API_PY).toContain('crew_ids=sorted(BUILDABLE_BUILDER_CREW_IDS)')
    expect(UNBUILDABLE_CREW_IDS.sort()).toEqual(['report', 'synthesis'])
    for (const unbuildable of UNBUILDABLE_CREW_IDS) {
      expect(BUILDABLE_CREW_IDS).not.toContain(unbuildable)
    }
    // The first id the server offers, with nothing stepped over on this side.
    expect(vocabulary.value?.crew_ids).toEqual(BUILDABLE_CREW_IDS)
    expect(node.config.crew_id).toBe(BUILDABLE_CREW_IDS[0])
  })

  it('gives a gate a real sentence and the service s own expiry', () => {
    const node = newNode('gate', { x: 0, y: 0 }, [])
    if (node.kind !== 'gate') throw new Error('unreachable')
    // `min_length=1`, and it is the one string in the document an OPERATOR reads.
    expect(node.config.message.length).toBeGreaterThan(0)
    expect(node.config.message.length).toBeLessThanOrEqual(
      pythonInt('BUILDER_MAX_GATE_MESSAGE_CHARS'),
    )
    expect(node.config.max_turns).toBe(1)
    expect(node.config.expiry_seconds).toBe(pythonInt('VALIDATOR_GATE_TIMEOUT_SECONDS'))
    expect(node.config.editable_fields).toEqual([])
  })

  it('gives a fresh router the two branches its own rules require', () => {
    const node = newNode('router', { x: 0, y: 0 }, [])
    if (node.kind !== 'router') throw new Error('unreachable')
    const branches = node.config.branches

    // `router-branch-count`: 2..4, satisfied on arrival rather than after two
    // edits. A router born empty is born with two errors against it.
    expect(branches.length).toBeGreaterThanOrEqual(pythonInt('MIN_ROUTER_BRANCHES'))
    expect(branches.length).toBeLessThanOrEqual(pythonInt('MAX_FANOUT_WIDTH'))

    // `router-otherwise`: exactly one, or an unmatched value wedges the run.
    const otherwise = branches.filter((branch) => branch.op === 'otherwise')
    expect(otherwise).toHaveLength(1)
    expect(otherwise[0].key).toBeNull()
    expect(otherwise[0].value).toBeNull()
    expect(otherwise[0].op).toBe(
      /BUILDER_ROUTER_OTHERWISE = "(\w+)"/.exec(CONFIG_PY)?.[1],
    )

    // `router-duplicate-branch`: the label is the port an edge leaves by.
    expect(new Set(branches.map((branch) => branch.label)).size).toBe(branches.length)

    for (const branch of branches.filter((entry) => entry.op !== 'otherwise')) {
      // `RouterBranch._validate_shape` refuses a comparison with no key.
      expect(branch.key).not.toBeNull()
      expect(pythonStrings('BUILDER_ROUTER_COMPARISONS', '{', '}')).toContain(branch.op)
    }

    // And the ports the card draws are those labels, on the same tick.
    expect(outPortsOf(node)).toEqual(branches.map((branch) => branch.label))
  })

  it('gives a transform an op the compiler has', () => {
    const node = newNode('transform', { x: 0, y: 0 }, [])
    if (node.kind !== 'transform') throw new Error('unreachable')
    expect(pythonStrings('BUILDER_TRANSFORM_OPS', '{', '}')).toContain(node.config.op)
    expect(node.config.args).toEqual({})
  })

  it('gives an output the one body key that escapes the frame clip', () => {
    const node = newNode('output', { x: 0, y: 0 }, [])
    if (node.kind !== 'output') throw new Error('unreachable')
    // A body written under any other key comes back truncated mid-sentence,
    // which is exactly how the first paid run's report was lost.
    expect(pythonStrings('RUN_RESULT_BODY_KEYS', '(', ')')).toContain(node.config.body_key)
    expect(node.config.body_key).toBe(vocabulary.value?.result_body_keys[0])
    expect(node.config.source).toBeNull()
  })
})

describe('a minted id is legal by construction', () => {
  const none: ReadonlySet<string> = new Set()

  it('slugifies the shapes a real label actually takes', () => {
    expect(mintNodeId('Market Analyst', none)).toBe('market_analyst')
    expect(mintNodeId('Scope - v2', none)).toBe('scope_v2')
    expect(mintNodeId('  Confirm  ', none)).toBe('confirm')
  })

  it('drops a leading run the pattern refuses, because it must start a-z', () => {
    // `^[a-z]` is the part of BUILDER_ID_PATTERN a title breaks most often.
    expect(mintNodeId('2024 review', none)).toBe('review')
    expect(mintNodeId('_hidden', none)).toBe('hidden')
  })

  it('falls back to a word when a label has nothing left to slugify', () => {
    expect(mintNodeId('🙂', none)).toBe('node')
    expect(mintNodeId('2024', none)).toBe('node')
    expect(mintNodeId('', none)).toBe('node')
  })

  it('numbers around a taken id and leaves the original alone', () => {
    expect(mintNodeId('Scoper', new Set(['scoper']))).toBe('scoper_2')
    expect(mintNodeId('Scoper', new Set(['scoper', 'scoper_2']))).toBe('scoper_3')
  })

  it('never exceeds the 40 characters the compiled ident depends on', () => {
    const long = 'A'.repeat(80)
    const minted = mintNodeId(long, none)
    expect(minted).toHaveLength(MAX_NODE_ID_CHARS)
    expect(minted).toMatch(NODE_ID_PATTERN)

    // Trimming the BASE to make room for the suffix, rather than dropping the
    // suffix: a truncated id that collides again would never terminate, and a
    // 41-character id is a 422.
    const collided = mintNodeId(long, new Set([minted]))
    expect(collided.length).toBeLessThanOrEqual(MAX_NODE_ID_CHARS)
    expect(collided).toMatch(NODE_ID_PATTERN)
    expect(collided).not.toBe(minted)
  })

  it('matches the pattern the server parses with, for every case above', () => {
    const labels = ['Market Analyst', 'Scope - v2', '2024 review', '🙂', 'A'.repeat(80)]
    for (const label of labels) {
      expect(mintNodeId(label, none)).toMatch(NODE_ID_PATTERN)
    }
    // And that pattern is the Python's, not a paraphrase of it.
    expect(CONFIG_PY).toContain('BUILDER_ID_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"')
    expect(MAX_NODE_ID_CHARS).toBe(pythonInt('BUILDER_MAX_ID_CHARS'))
  })
})

describe('the kind record and the defaults agree with each other', () => {
  beforeEach(async () => {
    resetVocabulary()
    stubFetch(servingFetch(vocabularyPayload()))
    await loadVocabulary()
  })

  it('labels every kind distinctly, so two tiles are never the same word', () => {
    const labels = NODE_KIND_ORDER.map((kind: NodeKind) => NODE_KINDS[kind].defaultLabel)
    expect(new Set(labels).size).toBe(labels.length)
  })

  it('says what every kind does in one sentence', () => {
    for (const kind of NODE_KIND_ORDER) {
      expect(NODE_KINDS[kind].blurb.length).toBeGreaterThan(20)
      expect(NODE_KINDS[kind].blurb.endsWith('.')).toBe(true)
    }
  })
})
