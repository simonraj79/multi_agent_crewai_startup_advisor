import { effectScope, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BUILDER_SCHEMA_ID, documentId, nodeId } from '../src/types/builder'
import type {
  BuilderBounds,
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
import { BuilderConflictError } from '../src/services/builderApi'
import { useBuilderDocument } from '../src/composables/useBuilderDocument'
import { useBuilderPersistence } from '../src/composables/useBuilderPersistence'
import { resetVocabulary, vocabulary } from '../src/data/builderVocabulary'
import ConflictDialog from '../src/components/builder/ConflictDialog.vue'
import SaveChip from '../src/components/builder/SaveChip.vue'

/**
 * Getting the author's work stored, and never claiming it is stored when it is
 * not.
 *
 * Five gaps, each of which is a way an author loses work while a green chip
 * tells them otherwise:
 *
 * 1. **`expected_version` read off the document.** The server overwrites both
 *    `id` and `version` on every write, so `doc.version` is whatever the
 *    document was last parsed against - and on a `/validate` round trip that is
 *    not the stored version at all. A PUT carrying it would compare against a
 *    number nobody stored, which is either a spurious 409 or, worse, a lost
 *    update that succeeds. Spec §1.1 invariant 5; the test tampers with
 *    `doc.version` and reads the request.
 * 2. **A save marked clean over work it did not include.** The author keeps
 *    typing during the round trip; the response is about the document that went
 *    out, not the one on screen.
 * 3. **A 409 that reloads.** The author's only copy is the one in the tab, and
 *    an automatic reload destroys it with no undo. Both resolutions go through
 *    `commit`, so whichever version is displaced stays one Ctrl+Z away.
 * 4. **A draft restored across somebody else's save.** A draft edited from v4
 *    while v5 was stored describes a document that no longer exists; offering
 *    it silently discards their work, and merging the two is the one thing spec
 *    §4.6 forbids outright.
 * 5. **A storage failure reaching the edit path.** A private window throws on
 *    `setItem`. A commit that failed because of it would make the canvas
 *    unusable in order to protect a convenience.
 */

/* --- fixtures ------------------------------------------------------------ */

const INPUT: InputConfig = {
  field: nodeId('idea'),
  label: null,
  max_chars: 2000,
  required: true,
}

const DOC_ID = documentId('ug_0a1b2c3d')

function inputNode(id = 'idea'): BuilderNode {
  return { id: nodeId(id), kind: 'input', label: 'Idea', position: { x: 0, y: 0 }, config: INPUT }
}

function sample(overrides: Partial<BuilderDocument> = {}): BuilderDocument {
  return {
    schema: BUILDER_SCHEMA_ID,
    id: DOC_ID,
    name: 'Sample',
    version: 4,
    input_field: nodeId('idea'),
    nodes: [inputNode()],
    edges: [],
    joins: {},
    budget: null,
    ...overrides,
  }
}

const BUDGET: BuilderBudget = {
  static_cost_usd: 0,
  floor_cost_usd: 0,
  modelled_calls: 0,
  billable_nodes: 0,
  escalation_nodes: 0,
  cycles: 0,
  unpriced_models: [],
  over_ceiling: false,
  ceiling_usd: 10,
}

function model(document: BuilderDocument, version: number, head = version): BuilderDocumentModel {
  return {
    id: DOC_ID,
    document: { ...document, version },
    status: 'draft',
    version,
    head_version: head,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:00:00Z',
    problems: [],
    budget: BUDGET,
    graph: { id: DOC_ID, name: 'Sample', version: 'abc', start_nodes: [], nodes: [], edges: [] },
    published: false,
    live_version: null,
  }
}

/**
 * The transport, implementing its subject's own structural type.
 *
 * `implements BuilderApiLike` is the load-bearing word. This repo has twice
 * shipped a double that quietly diverged from the thing it stood in for and
 * certified nothing either time (closed items 20 and 33); the compiler refusing
 * this class the moment `BuilderApi` grows a method is the mechanism that stops
 * a third.
 */
class FakeBuilderApi implements BuilderApiLike {
  saves: Array<{ id: string; expectedVersion: number; document: BuilderDocument }> = []
  creates: BuilderDocument[] = []
  gets: Array<{ id: string; version?: number }> = []
  /** Thrown by the NEXT save, then cleared. One failure at a time keeps a test readable. */
  nextSaveFailure: Error | null = null
  head = 4
  headDocument: BuilderDocument = sample()

  async list(): Promise<BuilderDocumentSummary[]> {
    return []
  }

  async create(document: BuilderDocument): Promise<BuilderDocumentModel> {
    this.creates.push(document)
    const failure = this.nextSaveFailure
    this.nextSaveFailure = null
    if (failure) throw failure
    this.head = 1
    return model(document, 1)
  }

  async get(id: string, version?: number): Promise<BuilderDocumentModel> {
    this.gets.push({ id, version })
    return model(this.headDocument, version ?? this.head, this.head)
  }

  async save(
    id: string,
    document: BuilderDocument,
    expectedVersion: number,
  ): Promise<BuilderDocumentModel> {
    this.saves.push({ id, expectedVersion, document })
    const failure = this.nextSaveFailure
    this.nextSaveFailure = null
    if (failure) throw failure
    this.head = expectedVersion + 1
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

/**
 * Run the two composables inside an effect scope, so `onScopeDispose` fires.
 *
 * A scope rather than a mounted component: nothing here renders, and mounting
 * one only to reach a lifecycle hook makes every failure a component failure.
 */
function withScope<T>(build: () => T): [T, () => void] {
  const scope = effectScope()
  let result!: T
  scope.run(() => {
    result = build()
  })
  return [result, () => scope.stop()]
}

/**
 * Every scope this file opens, stopped in `afterEach` whatever happened.
 *
 * Not tidiness. `useBuilderPersistence` registers a `beforeunload` listener on
 * the shared `window`, so a session left running by a test that failed before
 * its own `stop()` keeps answering that event for every later test in the file
 * - and the unload assertion below then reads a dirty document three tests
 * away. A leaked listener is a test that passes or fails on which test ran
 * first.
 */
const openScopes: Array<() => void> = []

function session(initial = sample()) {
  const api = new FakeBuilderApi()
  const [pair, stop] = withScope(() => {
    const document = useBuilderDocument(initial)
    return { document, persistence: useBuilderPersistence(document, api) }
  })
  openScopes.push(stop)
  return { api, ...pair, stop }
}

const BOUNDS: BuilderBounds = {
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
  // C2 v2\'s two authored-node bounds: BUILDER_MAX_PROMPT_CHARS and
  // BUILDER_MAX_NODE_RETRIES, served since plan 04 and read by every
  // PromptField and node-retry stepper rather than restated as a constant.
  max_prompt_chars: 4000,
  max_retries: 3,
}

function serveBounds(overrides: Partial<BuilderBounds> = {}): void {
  vocabulary.value = {
    schema_id: BUILDER_SCHEMA_ID,
    node_kinds: ['input', 'agent', 'crew', 'gate', 'router', 'transform', 'output'],
    tiers: ['cheap', 'escalation'],
    agent_ids: ['scoper'],
    crew_ids: [],
    research_tools: [],
    transform_ops: ['pick'],
    router_comparisons: ['eq'],
    router_otherwise: 'otherwise',
    result_body_keys: ['markdown_body'],
    bounds: { ...BOUNDS, ...overrides },
  }
}

beforeEach(() => {
  window.localStorage.clear()
  resetVocabulary()
})

afterEach(() => {
  while (openScopes.length) openScopes.pop()?.()
  vi.useRealTimers()
  resetVocabulary()
  window.localStorage.clear()
})

/* --- expected_version ---------------------------------------------------- */

describe('expected_version comes only from a server response', () => {
  it('sends the adopted version, not the one written on the document', async () => {
    const { api, document, persistence, stop } = session()
    persistence.adopt(model(sample(), 4))
    // Tamper the document's own copy the way a `/validate` round trip could.
    document.commit('tamper', { ...document.doc.value, version: 999 })

    await persistence.save()
    expect(api.saves).toHaveLength(1)
    expect(api.saves[0].expectedVersion).toBe(4)
    stop()
  })

  it('takes the next expected version from the response, so a second save follows on', async () => {
    const { api, document, persistence, stop } = session()
    persistence.adopt(model(sample(), 4))

    document.setName('One')
    await persistence.save()
    document.setName('Two')
    await persistence.save()

    expect(api.saves.map((each) => each.expectedVersion)).toEqual([4, 5])
    expect(persistence.version.value).toBe(6)
    stop()
  })

  it('creates rather than saves while nothing has been stored', async () => {
    const { api, persistence, stop } = session()
    await persistence.save()
    expect(api.creates).toHaveLength(1)
    expect(api.saves).toHaveLength(0)
    expect(persistence.documentId.value).toBe(DOC_ID)
    stop()
  })
})

/* --- the chip is never silent -------------------------------------------- */

describe('saveState', () => {
  it('walks clean, dirty, then clean again across a save', async () => {
    const { document, persistence, stop } = session()
    persistence.adopt(model(sample(), 4))
    expect(persistence.saveState.value).toBe('clean')

    document.setName('Edited')
    expect(persistence.saveState.value).toBe('dirty')

    await persistence.save()
    expect(persistence.saveState.value).toBe('clean')
    stop()
  })

  it('stays dirty when the author edited during the round trip', async () => {
    const { document, persistence, stop } = session()
    persistence.adopt(model(sample(), 4))
    document.setName('First')

    const inFlight = persistence.save()
    document.setName('Typed while saving')
    await inFlight

    expect(persistence.saveState.value).toBe('dirty')
    expect(persistence.version.value).toBe(5)
    stop()
  })

  it('reports a refusal with the server sentence rather than the offline wording', async () => {
    const { document, persistence, api, stop } = session()
    persistence.adopt(model(sample(), 4))
    api.nextSaveFailure = new Error('the request body is limited to 65536 bytes')
    document.setName('Edited')

    await persistence.save()
    expect(persistence.saveState.value).toBe('offline')
    expect(persistence.error.value).toBe('the request body is limited to 65536 bytes')
    stop()
  })
})

/* --- autosave ------------------------------------------------------------ */

describe('the idle autosave', () => {
  beforeEach(() => vi.useFakeTimers())

  it('fires 2.5s after the last commit', async () => {
    const { api, document, persistence, stop } = session()
    persistence.adopt(model(sample(), 4))
    document.setName('Edited')

    await vi.advanceTimersByTimeAsync(2400)
    expect(api.saves).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(200)
    expect(api.saves).toHaveLength(1)
    stop()
  })

  it('restarts the clock on every commit, so a typing run is one save', async () => {
    const { api, document, persistence, stop } = session()
    persistence.adopt(model(sample(), 4))

    for (let index = 0; index < 5; index += 1) {
      document.commit(`Step ${index}`, { ...document.doc.value, name: `Name ${index}` })
      await vi.advanceTimersByTimeAsync(1000)
    }
    expect(api.saves).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(2500)
    expect(api.saves).toHaveLength(1)
    stop()
  })

  it('never fires before anything is stored, because a create is the author to decide', async () => {
    const { api, document, stop } = session()
    document.setName('A template being edited')
    await vi.advanceTimersByTimeAsync(5000)
    expect(api.creates).toHaveLength(0)
    stop()
  })

  it('is frozen entirely while a conflict is unresolved', async () => {
    const { api, document, persistence, stop } = session()
    persistence.adopt(model(sample(), 4))
    api.nextSaveFailure = new BuilderConflictError(
      'document ug_0a1b2c3d is at version 8, not 4; reload it before saving again',
      8,
    )
    document.setName('Edited')
    await persistence.save()
    expect(persistence.saveState.value).toBe('conflict')

    const before = api.saves.length
    document.setName('Edited again')
    await vi.advanceTimersByTimeAsync(10_000)
    expect(api.saves).toHaveLength(before)
    stop()
  })
})

/* --- the conflict --------------------------------------------------------- */

describe('a 409', () => {
  function conflicted() {
    const built = session()
    built.persistence.adopt(model(sample(), 4))
    built.document.setName('Mine')
    built.api.nextSaveFailure = new BuilderConflictError(
      'document ug_0a1b2c3d is at version 8, not 4; reload it before saving again',
      8,
    )
    return built
  }

  it('does not touch the document', async () => {
    const { document, persistence, stop } = conflicted()
    const mine = document.doc.value
    await persistence.save()
    expect(document.doc.value).toBe(mine)
    expect(persistence.conflict.value?.storedVersion).toBe(8)
    stop()
  })

  it('leaves the author version one undo away when they take the server one', async () => {
    const { api, document, persistence, stop } = conflicted()
    await persistence.save()

    api.headDocument = sample({ name: 'Theirs' })
    api.head = 8
    const head = await persistence.loadHead()
    persistence.discardMine(head)

    expect(document.doc.value.name).toBe('Theirs')
    expect(persistence.saveState.value).toBe('clean')
    expect(persistence.version.value).toBe(8)

    document.undo()
    expect(document.doc.value.name).toBe('Mine')
    stop()
  })

  it('leaves the server version one undo away when they keep their own, and re-PUTs at head', async () => {
    const { api, document, persistence, stop } = conflicted()
    await persistence.save()

    api.headDocument = sample({ name: 'Theirs' })
    api.head = 8
    const head = await persistence.loadHead()
    await persistence.keepMine(head)

    expect(document.doc.value.name).toBe('Mine')
    // The re-PUT compares against HEAD's version, which is what makes the
    // second attempt succeed rather than 409 again.
    expect(api.saves.map((each) => each.expectedVersion)).toEqual([4, 8])
    expect(persistence.conflict.value).toBeNull()

    document.undo()
    expect(document.doc.value.name).toBe('Theirs')
    stop()
  })
})

/* --- the local draft ------------------------------------------------------ */

describe('the localStorage draft', () => {
  /*
   * The write is batched to the next tick rather than run inside `commit`.
   * Vue's default `flush: 'pre'` collapses a burst of commits into ONE
   * `JSON.stringify` of a document capped at 256 KiB, which is the difference
   * between a keystroke costing a serialisation and a paste of twenty nodes
   * costing twenty. Nothing is at risk in that window: `beforeunload` is a task
   * and every microtask has already run by the time it fires.
   */
  it('is written on every commit under builder-draft:<id>', async () => {
    serveBounds()
    const { document, persistence } = session()
    persistence.adopt(model(sample(), 4))
    document.setName('Edited')
    await nextTick()

    const raw = window.localStorage.getItem(`builder-draft:${DOC_ID}`)
    expect(raw).not.toBeNull()
    const draft = JSON.parse(raw as string) as { baseVersion: number; document: { name: string } }
    expect(draft.baseVersion).toBe(4)
    expect(draft.document.name).toBe('Edited')
  })

  it('does not break a commit when storage throws', async () => {
    serveBounds()
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError')
    })

    const { document, persistence } = session()
    persistence.adopt(model(sample(), 4))
    expect(() => document.setName('Edited')).not.toThrow()
    await nextTick()

    expect(document.doc.value.name).toBe('Edited')
    expect(persistence.draftDropped.value).toBe(true)
    setItem.mockRestore()
  })

  it('drops a draft over max_document_bytes and sets the chip, rather than keeping a stale one', async () => {
    serveBounds()
    const { document, persistence } = session()
    persistence.adopt(model(sample(), 4))
    document.setName('Small enough')
    await nextTick()
    expect(window.localStorage.getItem(`builder-draft:${DOC_ID}`)).not.toBeNull()

    // The bound moves under the document rather than the document growing past
    // it, because the assertion is about the guard and not about how many nodes
    // fit in 256 KiB.
    serveBounds({ max_document_bytes: 32 })
    document.setName('Now too large to keep locally')
    await nextTick()

    expect(persistence.draftDropped.value).toBe(true)
    expect(window.localStorage.getItem(`builder-draft:${DOC_ID}`)).toBeNull()
  })

  /** A session that edited and left a draft behind, exactly as a closed tab does. */
  async function leaveDraft(name: string): Promise<void> {
    const first = session()
    first.persistence.adopt(model(sample(), 4))
    first.document.setName(name)
    await nextTick()
    first.stop()
  }

  it('offers a restore only when the draft baseVersion still equals head', async () => {
    serveBounds()
    await leaveDraft('Work in progress')

    const second = session()
    await second.persistence.open(DOC_ID as DocumentId)
    expect(second.persistence.restoreOffer.value).not.toBeNull()
    expect(second.persistence.restoreOffer.value?.baseVersion).toBe(4)
  })

  it('discards a draft whose head has moved on, and never merges it', async () => {
    serveBounds()
    await leaveDraft('Work in progress')

    const second = session()
    second.api.head = 8
    second.api.headDocument = sample({ name: 'Somebody else saved this' })
    await second.persistence.open(DOC_ID as DocumentId)

    expect(second.persistence.restoreOffer.value).toBeNull()
    expect(second.document.doc.value.name).toBe('Somebody else saved this')
    // Removed before the load's own draft write, so what remains describes head
    // rather than the discarded work - and no bar is offered for it.
    await nextTick()
    const kept = window.localStorage.getItem(`builder-draft:${DOC_ID}`)
    expect(JSON.parse(kept as string).document.name).toBe('Somebody else saved this')
  })

  it('offers nothing when the draft says the same thing as head', async () => {
    serveBounds()
    await leaveDraft('Sample')

    const second = session()
    await second.persistence.open(DOC_ID as DocumentId)
    expect(second.persistence.restoreOffer.value).toBeNull()
  })

  it('restores the draft the bar offered, not whatever the load then wrote over it', async () => {
    serveBounds()
    await leaveDraft('Work in progress')

    const second = session()
    await second.persistence.open(DOC_ID as DocumentId)
    // The load's own draft write lands here, on the tick between the offer and
    // the click. Re-reading storage on accept would find head, not the work.
    await nextTick()
    second.persistence.acceptRestore()

    expect(second.document.doc.value.name).toBe('Work in progress')
    expect(second.persistence.saveState.value).toBe('dirty')
    expect(second.persistence.restoreOffer.value).toBeNull()
  })

  it('takes the draft out of the browser when it is dismissed', async () => {
    serveBounds()
    await leaveDraft('Work in progress')

    const second = session()
    await second.persistence.open(DOC_ID as DocumentId)
    second.persistence.dismissRestore()
    expect(window.localStorage.getItem(`builder-draft:${DOC_ID}`)).toBeNull()
  })
})

/* --- the unload guard ----------------------------------------------------- */

describe('the beforeunload guard', () => {
  it('asks only while there is unsaved work, and stops asking once the scope is gone', async () => {
    const { document, persistence, stop } = session()
    persistence.adopt(model(sample(), 4))

    const clean = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(clean)
    expect(clean.defaultPrevented).toBe(false)

    document.setName('Edited')
    const dirty = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(dirty)
    expect(dirty.defaultPrevented).toBe(true)

    stop()
    const afterStop = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(afterStop)
    expect(afterStop.defaultPrevented).toBe(false)
  })
})

/* --- starting over -------------------------------------------------------- */

describe('startNew', () => {
  it('forgets the stored id, so the next save cannot PUT a template over it', async () => {
    const { api, document, persistence, stop } = session()
    persistence.adopt(model(sample(), 4))

    persistence.startNew()
    document.applyTemplate(sample({ name: 'From a template' }))
    await persistence.save()

    expect(api.saves).toHaveLength(0)
    expect(api.creates).toHaveLength(1)
    stop()
  })
})

/* --- what the author reads ------------------------------------------------ */

describe('SaveChip', () => {
  function chip(props: Record<string, unknown>) {
    return mount(SaveChip, {
      props: { state: 'clean', version: 7, headVersion: 7, ...props },
    })
  }

  it('names every state, because silence is never one of them', () => {
    expect(chip({ state: 'clean' }).text()).toContain('saved · v7')
    expect(chip({ state: 'saving' }).text()).toContain('saving…')
    expect(chip({ state: 'dirty' }).text()).toContain('unsaved changes')
    expect(chip({ state: 'conflict', headVersion: 8 }).text()).toContain('conflict — head is v8')
    expect(chip({ state: 'offline' }).text()).toContain('offline — kept in this browser')
  })

  it('is a polite status region, not an assertive one that interrupts every 2.5s', () => {
    expect(chip({}).get('[data-testid="save-chip"]').attributes('role')).toBe('status')
  })

  /*
   * `saveState` has five values and none of them is "refused". A 413 over
   * `max_document_bytes` is not a network failure, and rendering the offline
   * wording over it would be the chip's one job done wrongly.
   */
  it('prints the server sentence when a save was refused rather than lost', () => {
    const wrapper = chip({ state: 'offline', error: 'the request body is limited to 65536 bytes' })
    expect(wrapper.text()).toContain('the request body is limited to 65536 bytes')
    expect(wrapper.text()).not.toContain('offline — kept in this browser')
  })

  it('reports a dropped local backup ALONGSIDE the save state, not instead of it', () => {
    const wrapper = chip({ state: 'dirty', draftDropped: true })
    expect(wrapper.text()).toContain('unsaved changes')
    expect(wrapper.text()).toContain('too large for a local backup')
  })
})

describe('ConflictDialog', () => {
  function mine(): BuilderDocument {
    return sample({
      name: 'Mine',
      nodes: [inputNode(), { ...inputNode('only_mine'), label: 'Only mine' } as BuilderNode],
    })
  }

  function theirs(): BuilderDocumentModel {
    const head = model(
      sample({
        name: 'Theirs',
        nodes: [{ ...inputNode(), label: 'Renamed by them' } as BuilderNode],
      }),
      8,
    )
    return head
  }

  async function open(loadHead = () => Promise.resolve(theirs())) {
    const wrapper = mount(ConflictDialog, {
      props: {
        conflict: {
          detail: 'document ug_0a1b2c3d is at version 8, not 4; reload it before saving again',
          storedVersion: 8,
        },
        mine: mine(),
        documentId: DOC_ID,
        loadHead,
      },
    })
    await flushPromises()
    return wrapper
  }

  it('prints the server sentence verbatim, because it names both versions', async () => {
    const wrapper = await open()
    expect(wrapper.get('[data-testid="conflict-detail"]').text()).toBe(
      'document ug_0a1b2c3d is at version 8, not 4; reload it before saving again',
    )
  })

  it('shows what differs rather than asking the author to guess', async () => {
    const text = (await open()).get('[data-testid="conflict-diff"]').text()
    expect(text).toContain('Only in yours')
    expect(text).toContain('only_mine')
    expect(text).toContain('Different in both')
    expect(text).toContain('Renamed by them')
    expect(text).toContain('Graph settings')
  })

  it('hands the fetched head back with whichever resolution was chosen', async () => {
    const wrapper = await open()
    await wrapper.get('[data-testid="conflict-keep"]').trigger('click')
    await wrapper.get('[data-testid="conflict-discard"]').trigger('click')

    expect(wrapper.emitted('keep')?.[0]?.[0]).toMatchObject({ version: 8 })
    expect(wrapper.emitted('discard')?.[0]?.[0]).toMatchObject({ version: 8 })
  })

  /*
   * There is no Cancel and there must not be one. The document cannot save
   * until this is answered, so a dismissed dialog leaves an author editing a
   * graph that silently stopped being stored.
   */
  it('offers no way out that leaves the conflict unresolved', async () => {
    const wrapper = await open()
    const labels = wrapper.findAll('button').map((button) => button.text())
    expect(labels).toHaveLength(3)
    expect(labels.join(' ')).not.toMatch(/cancel|dismiss|close|later/i)
  })

  it('offers a retry rather than a dead dialog when head cannot be read', async () => {
    const wrapper = await open(() => Promise.reject(new Error('Request failed (503)')))
    expect(wrapper.text()).toContain('Request failed (503)')
    expect(wrapper.find('[data-testid="conflict-diff"]').exists()).toBe(false)
    // The two resolutions need head; neither is offered while it is missing.
    expect(wrapper.get('[data-testid="conflict-keep"]').attributes('disabled')).toBeDefined()
  })

  it('is a modal dialog and takes focus, so the keyboard cannot wander behind it', async () => {
    const wrapper = await open()
    const panel = wrapper.get('[role="dialog"]')
    expect(panel.attributes('aria-modal')).toBe('true')
    expect(panel.attributes('aria-labelledby')).toBe('conflict-title')
  })
})

/* --- the draft belongs to the signed-in user (D-01-5) ---------------------- */

/*
 * The draft holds the whole document - nodes, prompt inputs and
 * `config.credential_id` - and it is written on every successful load, not
 * only for unsaved work. Under a key with no identity in it, the next person
 * on the same browser could read it, and a sign-out did not remove it. The key
 * now carries the user's id, so a different signed-in user never finds it even
 * when the previous person just closed the tab.
 */
describe('the draft belongs to the signed-in user (D-01-5)', () => {
  /** A session as somebody, in the same scope discipline as `session()`. */
  function sessionAs(userId: string | null, initial = sample()) {
    const api = new FakeBuilderApi()
    const [pair, stop] = withScope(() => {
      const document = useBuilderDocument(initial)
      return {
        document,
        persistence: useBuilderPersistence(document, api, { userId: () => userId }),
      }
    })
    openScopes.push(stop)
    return { api, ...pair, stop }
  }

  it("is written under the user's own key and never under the anonymous one", async () => {
    serveBounds()
    const alice = sessionAs('alice')
    alice.persistence.adopt(model(sample(), 4))
    alice.document.setName('Edited by Alice')
    await nextTick()

    const raw = window.localStorage.getItem(`u:alice:builder-draft:${DOC_ID}`)
    expect(raw).not.toBeNull()
    const draft = JSON.parse(raw as string) as { baseVersion: number; document: { name: string } }
    expect(draft.baseVersion).toBe(4)
    expect(draft.document.name).toBe('Edited by Alice')
    expect(window.localStorage.getItem(`builder-draft:${DOC_ID}`)).toBeNull()
  })

  it('is never offered to a different user on the same browser, even without a sign-out', async () => {
    serveBounds()
    const alice = sessionAs('alice')
    alice.persistence.adopt(model(sample(), 4))
    alice.document.setName('Work in progress')
    await nextTick()
    alice.stop()
    // Alice closed the tab. Her draft is still there, and its base is head.
    expect(window.localStorage.getItem(`u:alice:builder-draft:${DOC_ID}`)).not.toBeNull()

    const bob = sessionAs('bob')
    await bob.persistence.open(DOC_ID as DocumentId)
    expect(bob.persistence.restoreOffer.value).toBeNull()
    expect(bob.document.doc.value.name).toBe('Sample')
    // Bob's own load writes Bob's own draft; Alice's is untouched.
    await nextTick()
    expect(window.localStorage.getItem(`u:bob:builder-draft:${DOC_ID}`)).not.toBeNull()
    const kept = window.localStorage.getItem(`u:alice:builder-draft:${DOC_ID}`)
    expect(JSON.parse(kept as string).document.name).toBe('Work in progress')
  })

  it('is offered back to the same user, exactly as before', async () => {
    serveBounds()
    const first = sessionAs('alice')
    first.persistence.adopt(model(sample(), 4))
    first.document.setName('Work in progress')
    await nextTick()
    first.stop()

    const again = sessionAs('alice')
    await again.persistence.open(DOC_ID as DocumentId)
    expect(again.persistence.restoreOffer.value?.baseVersion).toBe(4)
  })

  it('keeps the anonymous shape when nobody is signed in', async () => {
    serveBounds()
    const nobody = sessionAs(null)
    nobody.persistence.adopt(model(sample(), 4))
    nobody.document.setName('Edited')
    await nextTick()
    expect(window.localStorage.getItem(`builder-draft:${DOC_ID}`)).not.toBeNull()
  })
})

/* --- which version is LIVE (critic round product-1, P-05) ----------------- */

describe('the session knows which version is live, not merely whether this one is', () => {
  /**
   * `adoptIdentity` read `status` alone: a head that had returned to `draft`
   * nulled `publishedVersion`, so `DocumentBar`'s `v1 is live` chip vanished the
   * instant the author saved v2 - at exactly the moment it starts mattering,
   * because v1 goes on answering launches while they edit. The bar's own
   * rendering was always right; it was being handed the wrong fact.
   */
  it('keeps the live version when head is saved past it', () => {
    const { persistence } = session()
    persistence.adopt({ ...model(sample(), 1), status: 'published', published: true, live_version: 1 })
    expect(persistence.publishedVersion.value).toBe(1)

    // The save that reproduces P-05: head is v2 and a draft again, and v1 is
    // still the registered workflow.
    persistence.adopt({ ...model(sample(), 2), status: 'draft', published: false, live_version: 1 })
    expect(persistence.publishedVersion.value).toBe(1)
    expect(persistence.publishedHere.value).toBe(false)
    expect(persistence.version.value).toBe(2)
  })

  it('clears it when nothing of the document is registered', () => {
    const { persistence } = session()
    persistence.adopt({ ...model(sample(), 1), status: 'published', published: true, live_version: 1 })
    persistence.adopt({ ...model(sample(), 2), status: 'draft', published: false, live_version: null })
    expect(persistence.publishedVersion.value).toBeNull()
  })

  /**
   * The other direction, and the branch that was unreachable before: a restart
   * clears the process registration maps while the row still says `published`.
   * With no `else` on the old assignment nothing was written at all, so
   * `liveNote`'s "published but not registered here" sentence could never
   * render from a fresh load.
   */
  it('falls back to the published head when this process registered nothing', () => {
    const { persistence } = session()
    persistence.adopt({
      ...model(sample(), 3, 3),
      status: 'published',
      published: false,
      live_version: null,
    })
    expect(persistence.publishedVersion.value).toBe(3)
    expect(persistence.publishedHere.value).toBe(false)
  })
})
