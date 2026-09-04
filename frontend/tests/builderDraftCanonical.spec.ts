import { effectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { BUILDER_SCHEMA_ID, documentId, nodeId } from '../src/types/builder'
import type {
  AgentConfig,
  BuilderBudget,
  BuilderDocument,
  BuilderDocumentModel,
  BuilderDocumentSummary,
  BuilderNode,
  BuilderPublish,
  BuilderValidation,
  DocumentId,
  InputConfig,
} from '../src/types/builder'
import type { BuilderApiLike } from '../src/services/builderApi'
import { useBuilderDocument } from '../src/composables/useBuilderDocument'
import { useBuilderPersistence } from '../src/composables/useBuilderPersistence'
import { resetVocabulary } from '../src/data/builderVocabulary'

/**
 * The draft written after a clean save is the STORED document, not the local one.
 *
 * Found at integration on 2026-09-03 by `e2e/builder.spec.ts` ("recovers
 * without offering a stale draft") and by nothing in the unit suite. Plan 01
 * gave `AgentConfig` an optional `credential_id`, and the server has stored it
 * as `null` on every agent node since. A document built from a template that
 * never carried the key therefore no longer round-trips byte-identical: the
 * local copy has no key, the stored copy has `credential_id: null`, and a
 * draft written from the local copy after a save fingerprinted differently
 * from the document the reload then fetched - so the restore bar offered the
 * author the very version they were looking at, which is the one thing
 * `considerDraft` exists to prevent.
 *
 * The property is general, not about that field. A server is entitled to add
 * defaulted keys on the way in; the client cannot know them all. So when the
 * author changed nothing during the round trip, the draft is written from the
 * response - the canonical form of exactly what is on screen - and a reload
 * compares like with like. When they did keep typing, the local copy is still
 * the only one that has their work and is still what gets written.
 */

const INPUT: InputConfig = { field: nodeId('idea'), label: null, max_chars: 2000, required: true }
const DOC_ID = documentId('ug_0a1b2c3d')

/** An agent node exactly as a template literal spells it: no `credential_id` key at all. */
const AGENT_FROM_TEMPLATE = {
  tier: 'cheap',
  max_iter: 2,
  guardrail_max_retries: 2,
  prompt_inputs: {},
  agent_id: nodeId('scoper'),
  tools: [],
} as unknown as AgentConfig

function nodes(): BuilderNode[] {
  return [
    { id: nodeId('idea'), kind: 'input', label: 'Idea', position: { x: 0, y: 0 }, config: INPUT },
    { id: nodeId('scoper'), kind: 'agent', label: 'Scoper', position: { x: 200, y: 0 }, config: AGENT_FROM_TEMPLATE },
  ]
}

function local(): BuilderDocument {
  return {
    schema: BUILDER_SCHEMA_ID,
    id: DOC_ID,
    name: 'Template-born',
    version: 1,
    input_field: nodeId('idea'),
    nodes: nodes(),
    edges: [],
    joins: {},
    budget: null,
  }
}

/** What the server stores and echoes: the same document with the schema default filled in. */
function canonical(document: BuilderDocument, version: number): BuilderDocument {
  return {
    ...document,
    version,
    nodes: document.nodes.map((node) =>
      node.kind === 'agent' ? { ...node, config: { ...node.config, credential_id: null } } : node,
    ),
  }
}

const BUDGET: BuilderBudget = {
  static_cost_usd: 0,
  floor_cost_usd: 0,
  modelled_calls: 0,
  billable_nodes: 1,
  escalation_nodes: 0,
  cycles: 0,
  unpriced_models: [],
  over_ceiling: false,
  ceiling_usd: 10,
}

function model(document: BuilderDocument, version: number): BuilderDocumentModel {
  return {
    id: DOC_ID,
    document: canonical(document, version),
    status: 'draft',
    version,
    head_version: version,
    created_at: '2026-09-03T00:00:00Z',
    updated_at: '2026-09-03T00:00:00Z',
    problems: [],
    budget: BUDGET,
    graph: { id: DOC_ID, name: 'Template-born', version: 'abc', start_nodes: [], nodes: [], edges: [] },
    published: false,
    live_version: null,
  }
}

/** A server that fills in defaults, which is what `BuilderDocument.model_validate` does. */
class DefaultingApi implements BuilderApiLike {
  head = 1
  stored: BuilderDocument = canonical(local(), 1)

  async list(): Promise<BuilderDocumentSummary[]> {
    return []
  }
  async create(document: BuilderDocument): Promise<BuilderDocumentModel> {
    this.head = 1
    this.stored = canonical(document, 1)
    return model(document, 1)
  }
  async get(_id: string, version?: number): Promise<BuilderDocumentModel> {
    return model(this.stored, version ?? this.head)
  }
  async save(_id: string, document: BuilderDocument, expectedVersion: number): Promise<BuilderDocumentModel> {
    this.head = expectedVersion + 1
    this.stored = canonical(document, this.head)
    return model(document, this.head)
  }
  async remove(): Promise<void> {}
  async validate(): Promise<BuilderValidation> {
    return { valid: true, problems: [], budget: BUDGET }
  }
  async publish(): Promise<BuilderPublish> {
    return {
      workflow_id: DOC_ID,
      graph_version: 'abc',
      version: this.head,
      input_field: 'idea',
      static_cost_usd: 0,
      gated_before_spend: true,
      reserved_input_keys: [],
    }
  }
}

const stops: Array<() => void> = []

function session(api: DefaultingApi, initial: BuilderDocument) {
  const scope = effectScope()
  let built!: { document: ReturnType<typeof useBuilderDocument>; persistence: ReturnType<typeof useBuilderPersistence> }
  scope.run(() => {
    const document = useBuilderDocument(initial)
    built = { document, persistence: useBuilderPersistence(document, api) }
  })
  stops.push(() => scope.stop())
  return built
}

beforeEach(() => {
  window.localStorage.clear()
  resetVocabulary()
})

afterEach(() => {
  while (stops.length) stops.pop()?.()
  window.localStorage.clear()
  resetVocabulary()
})

describe('the draft written after a clean save', () => {
  it('is the stored document, defaults included, not the local copy', async () => {
    const api = new DefaultingApi()
    const first = session(api, local())
    first.document.commit('Rename', { ...first.document.doc.value, name: 'Renamed' })
    await first.persistence.save()

    const raw = window.localStorage.getItem(`builder-draft:${DOC_ID}`)
    expect(raw).not.toBeNull()
    const draft = JSON.parse(raw as string)
    const agent = draft.document.nodes.find((node: BuilderNode) => node.kind === 'agent')
    expect(agent.config).toHaveProperty('credential_id', null)
    expect(draft.document.name).toBe('Renamed')
  })

  it('so a reload straight after the save offers no restore', async () => {
    const api = new DefaultingApi()
    const first = session(api, local())
    first.document.commit('Rename', { ...first.document.doc.value, name: 'Renamed' })
    await first.persistence.save()

    const second = session(api, local())
    await second.persistence.open(DOC_ID as DocumentId)
    expect(second.persistence.restoreOffer.value).toBeNull()
  })

  it('still keeps the local copy when the author typed during the round trip', async () => {
    const api = new DefaultingApi()
    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const slowSave = api.save.bind(api)
    api.save = async (id, document, expected) => {
      await gate
      return slowSave(id, document, expected)
    }

    const first = session(api, local())
    first.document.commit('Rename', { ...first.document.doc.value, name: 'Renamed' })
    const saving = first.persistence.save()
    first.document.commit('Keep typing', { ...first.document.doc.value, name: 'Renamed again' })
    release()
    await saving

    const draft = JSON.parse(window.localStorage.getItem(`builder-draft:${DOC_ID}`) as string)
    expect(draft.document.name).toBe('Renamed again')
    expect(first.document.dirty.value).toBe(true)
  })
})
