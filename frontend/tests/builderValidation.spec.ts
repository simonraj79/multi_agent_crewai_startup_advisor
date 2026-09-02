import { ref } from 'vue'
import type { Ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useBuilderValidation } from '../src/composables/useBuilderValidation'
import type { ValidateApi } from '../src/composables/useBuilderValidation'
import { BUILDER_SCHEMA_ID, documentId, nodeId } from '../src/types/builder'
import type {
  BuilderBudget,
  BuilderDocument,
  BuilderNode,
  BuilderProblem,
  BuilderValidation,
} from '../src/types/builder'
import { flush, withSetup } from './helpers'

/**
 * The problem list is never allowed to be about a document you are no longer
 * looking at.
 *
 * That single sentence is the competition's second weakness and the reason this
 * composable exists. ChatDev computes its errors on a save and renders them
 * until the next save, so an author editing node 2 reads a complaint about node
 * 7 with nothing on screen admitting the list is old. Four mechanisms here stop
 * that, and each of them fails silently if it breaks - a dropped debounce is a
 * request storm nobody sees, a missing abort is a race that only shows up on a
 * slow connection, and a missing stamp check is exactly ChatDev's bug wearing
 * this repo's fonts. So each one is asserted separately.
 *
 * Everything is driven through an injected `ValidateApi` typed off the real
 * client, so the double cannot drift from its subject (closed items 15 and 33).
 * Nothing here touches a socket, a server or a real clock.
 */

/** A promise this test resolves by hand, so response ORDER is a variable. */
interface Deferred {
  document: BuilderDocument
  signal: AbortSignal | undefined
  resolve: (value: BuilderValidation) => void
  reject: (error: unknown) => void
}

class FakeValidateApi implements ValidateApi {
  readonly calls: Deferred[] = []

  validate(document: BuilderDocument, signal?: AbortSignal): Promise<BuilderValidation> {
    return new Promise<BuilderValidation>((resolve, reject) => {
      this.calls.push({ document, signal, resolve, reject })
    })
  }

  get last(): Deferred {
    const call = this.calls[this.calls.length - 1]
    expect(call, 'no validate request has been dispatched').toBeDefined()
    return call
  }
}

const budget = (overrides: Partial<BuilderBudget> = {}): BuilderBudget => ({
  static_cost_usd: 1.2,
  floor_cost_usd: 0.7,
  modelled_calls: 12,
  billable_nodes: 2,
  escalation_nodes: 1,
  cycles: 0,
  unpriced_models: [],
  over_ceiling: false,
  ceiling_usd: 10,
  ...overrides,
})

const answer = (problems: BuilderProblem[] = []): BuilderValidation => ({
  valid: problems.every((problem) => problem.severity !== 'error'),
  problems,
  budget: budget(),
})

const problem = (code: string, overrides: Partial<BuilderProblem> = {}): BuilderProblem => ({
  code,
  severity: 'error',
  message: `${code} happened`,
  node_id: null,
  edge_id: null,
  ...overrides,
})

function inputNode(label = 'Idea', x = 0, y = 0): BuilderNode {
  return {
    id: nodeId('idea_in'),
    label,
    position: { x, y },
    kind: 'input',
    config: { field: nodeId('idea'), label: null, max_chars: 2000, required: true },
  }
}

function document(nodes: BuilderNode[] = [inputNode()]): BuilderDocument {
  return {
    schema: BUILDER_SCHEMA_ID,
    id: documentId('ug_0a1b2c3d'),
    name: 'Test graph',
    version: 1,
    input_field: nodeId('idea'),
    nodes,
    edges: [],
    joins: {},
    budget: null,
  }
}

function harness(options: { suppressed?: Ref<boolean> } = {}) {
  const api = new FakeValidateApi()
  const doc = ref<BuilderDocument>(document())
  const [validation, app] = withSetup(() =>
    useBuilderValidation(doc, { api, suppressed: options.suppressed }),
  )
  return { api, doc, validation, app }
}

/**
 * Let the watcher run, cross the 400ms debounce, then drain the promise chain
 * the dispatch sits on.
 *
 * The leading `flush` is load-bearing and easy to leave out: Vue watchers are
 * `flush: 'pre'`, so `schedule()` runs on a microtask AFTER the assignment to
 * `doc.value`. Advancing the fake clock first would advance it past a timer
 * that had not been armed yet, and every request in this file would silently
 * fail to go out.
 */
async function tick(ms = 400): Promise<void> {
  await flush()
  vi.advanceTimersByTime(ms)
  await flush()
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('the validation loop only spends a request on a change the compiler would notice', () => {
  it('issues nothing at all for a position-only edit', async () => {
    const { api, doc, validation, app } = harness()

    doc.value = document([inputNode('Idea', 480, 260)])
    await tick()

    // `fingerprint` omits `position`, so the watcher never fires. This is not
    // an optimisation: a drag is dozens of commits, and dimming the problem
    // list through every one of them would make the panel unreadable during the
    // gesture an author performs most.
    expect(api.calls).toHaveLength(0)
    expect(validation.requestCount.value).toBe(0)
    expect(validation.phase.value).toBe('idle')
    app.unmount()
  })

  it('collapses a burst of edits into one request', async () => {
    const { api, doc, validation, app } = harness()

    doc.value = document([inputNode('I')])
    await tick(120)
    doc.value = document([inputNode('Id')])
    await tick(120)
    doc.value = document([inputNode('Ide')])
    await tick()

    expect(api.calls).toHaveLength(1)
    expect(validation.requestCount.value).toBe(1)
    app.unmount()
  })

  it('aborts the request in flight when a newer one goes out', async () => {
    const { api, doc, app } = harness()

    doc.value = document([inputNode('First')])
    await tick()
    doc.value = document([inputNode('Second')])
    await tick()

    expect(api.calls).toHaveLength(2)
    expect(api.calls[0].signal?.aborted).toBe(true)
    expect(api.calls[1].signal?.aborted).toBe(false)
    app.unmount()
  })

  it('sends the current document, not a copy captured at setup', async () => {
    const { api, doc, app } = harness()

    doc.value = document([inputNode('Renamed')])
    await tick()

    // `dispatch` reads `doc.value` at send time rather than closing over the
    // document the watcher fired on. The two are the same here; they would not
    // be if a suppressed check were deferred across further edits, which is the
    // case that makes reading late the right choice.
    expect(api.last.document.nodes[0].label).toBe('Renamed')
    app.unmount()
  })
})

describe('a response is dropped unless it answers the document on screen', () => {
  it('drops an answer whose fingerprint the author has already edited past', async () => {
    const { api, doc, validation, app } = harness()

    doc.value = document([inputNode('First')])
    await tick()
    expect(api.calls).toHaveLength(1)

    // Edited again while the first request is still in flight, but inside the
    // debounce window - so nothing has aborted it. This is the case an
    // AbortController cannot cover: the response is already on the wire.
    doc.value = document([inputNode('Second')])
    await flush()
    expect(api.calls[0].signal?.aborted).toBe(false)

    api.calls[0].resolve(answer([problem('no-output-node', { severity: 'warning' })]))
    await flush()

    expect(validation.problems.value).toEqual([])
    expect(validation.phase.value).toBe('stale')

    await tick()
    api.last.resolve(answer([problem('node-count')]))
    await flush()

    expect(validation.problems.value.map((entry) => entry.code)).toEqual(['node-count'])
    expect(validation.phase.value).toBe('fresh')
    app.unmount()
  })

  it('keeps the answer when the document has changed back to what was asked about', async () => {
    const { api, doc, validation, app } = harness()

    const first = document([inputNode('First')])
    doc.value = first
    await tick()
    doc.value = document([inputNode('Second')])
    await flush()
    // Undo, in effect: the same meaning, a different object. The stamp is a
    // fingerprint of MEANING, so this response is still current and dropping it
    // would cost a round trip for nothing.
    doc.value = document([inputNode('First')])
    await flush()

    api.calls[0].resolve(answer([problem('node-count')]))
    await flush()

    expect(validation.problems.value.map((entry) => entry.code)).toEqual(['node-count'])
    expect(validation.phase.value).toBe('fresh')
    app.unmount()
  })
})

describe('the phase is a rendered fact, and it never claims a list is current', () => {
  it('walks idle, then stale while the check is out, then fresh', async () => {
    const { api, doc, validation, app } = harness()
    const seen: string[] = [validation.phase.value]

    doc.value = document([inputNode('Edited')])
    // Recorded AFTER the watcher has run, not after the assignment: the phase
    // between those two points is a scheduler artifact nothing renders.
    await flush()
    seen.push(validation.phase.value)
    await tick()
    seen.push(validation.phase.value)
    api.last.resolve(answer())
    await flush()
    seen.push(validation.phase.value)

    // The debounce window and the flight are one state, deliberately. From
    // where the author sits they are the same fact: what is on screen is not
    // about this document.
    expect(seen).toEqual(['idle', 'stale', 'stale', 'fresh'])
    app.unmount()
  })

  it('reads checking, not stale, for a forced re-check of an unchanged document', async () => {
    const { api, doc, validation, app } = harness()

    doc.value = document([inputNode('Edited')])
    await tick()
    api.last.resolve(answer())
    await flush()
    expect(validation.phase.value).toBe('fresh')

    validation.validateNow()
    await flush()

    // Nothing on screen is out of date, so dimming the list and blocking
    // publish would both be false statements. `checking` exists for exactly
    // this, and it is the only state that separates "re-asking" from "stale".
    expect(validation.phase.value).toBe('checking')
    expect(validation.phaseBlocksPublish.value).toBe(false)
    app.unmount()
  })

  it('blocks publish while a check is pending after an edit', async () => {
    const { doc, validation, app } = harness()

    doc.value = document([inputNode('Edited')])
    await flush()

    expect(validation.phase.value).toBe('stale')
    expect(validation.phaseBlocksPublish.value).toBe(true)
    expect(validation.phaseBlockReason.value).toBe('validation is not current')
    app.unmount()
  })
})

describe('a validator that cannot be reached never quietly permits a publish', () => {
  it('lands a 500 in unreachable, carrying the server sentence', async () => {
    const { api, doc, validation, app } = harness()

    doc.value = document([inputNode('Edited')])
    await tick()
    api.last.reject(new Error('Request failed (500)'))
    await flush()

    expect(validation.phase.value).toBe('unreachable')
    expect(validation.unreachableReason.value).toBe('Request failed (500)')
    expect(validation.phaseBlocksPublish.value).toBe(true)
    expect(validation.phaseBlockReason.value).toContain('Request failed (500)')
    app.unmount()
  })

  it('lands a network failure in unreachable with a sentence an author can read', async () => {
    const { api, doc, validation, app } = harness()

    doc.value = document([inputNode('Edited')])
    await tick()
    // What `fetch` actually rejects with when the API is down. The raw message
    // is browser-specific and means nothing to the person reading it.
    api.last.reject(new TypeError('Failed to fetch'))
    await flush()

    expect(validation.phase.value).toBe('unreachable')
    expect(validation.unreachableReason.value).toBe('the validator could not be reached')
    expect(validation.phaseBlocksPublish.value).toBe(true)
    app.unmount()
  })

  it('recovers to fresh on the next successful check', async () => {
    const { api, doc, validation, app } = harness()

    doc.value = document([inputNode('Edited')])
    await tick()
    api.last.reject(new Error('Request failed (500)'))
    await flush()
    expect(validation.phase.value).toBe('unreachable')

    doc.value = document([inputNode('Edited again')])
    await tick()
    api.last.resolve(answer())
    await flush()

    expect(validation.phase.value).toBe('fresh')
    expect(validation.unreachableReason.value).toBe('')
    expect(validation.phaseBlocksPublish.value).toBe(false)
    app.unmount()
  })

  it('ignores the rejection of a request its successor aborted', async () => {
    const { api, doc, validation, app } = harness()

    doc.value = document([inputNode('First')])
    await tick()
    doc.value = document([inputNode('Second')])
    await tick()

    api.calls[0].reject(new Error('aborted'))
    await flush()

    // An abort is not a failure to reach the validator, and reporting it as one
    // would make every second keystroke look like an outage.
    expect(validation.phase.value).not.toBe('unreachable')
    app.unmount()
  })
})

describe('valid is the server answer, never a count taken over the list', () => {
  it('is false before anything has answered', () => {
    const { validation, app } = harness()
    expect(validation.valid.value).toBe(false)
    app.unmount()
  })

  it('stays true through the three warnings and false on any error', async () => {
    const { api, doc, validation, app } = harness()

    doc.value = document([inputNode('One')])
    await tick()
    api.last.resolve({
      valid: true,
      problems: [
        problem('router-branch-unconnected', { severity: 'warning', node_id: 'route' }),
        problem('no-output-node', { severity: 'warning' }),
        problem('join-single-predecessor', { severity: 'warning', node_id: 'score' }),
      ],
      budget: budget(),
    })
    await flush()
    expect(validation.valid.value).toBe(true)
    expect(validation.phaseBlocksPublish.value).toBe(false)

    doc.value = document([inputNode('Two')])
    await tick()
    api.last.resolve({ valid: false, problems: [problem('billable-count')], budget: budget() })
    await flush()
    expect(validation.valid.value).toBe(false)
    app.unmount()
  })
})

describe('a live pointer gesture defers the check rather than dropping it', () => {
  it('holds the request until the gesture ends, then sends exactly one', async () => {
    const suppressed = ref(true)
    const { api, doc, validation, app } = harness({ suppressed })

    doc.value = document([inputNode('Mid-drag')])
    await tick()
    expect(api.calls).toHaveLength(0)
    expect(validation.phase.value).toBe('stale')

    suppressed.value = false
    await tick()

    // Deferred, not dropped. A dropped check leaves the panel dimmed with no
    // request outstanding to undim it - a permanently stale list, which is the
    // exact failure this module exists to prevent.
    expect(api.calls).toHaveLength(1)
    app.unmount()
  })

  it('still sends immediately when the author forces a check mid-gesture', async () => {
    const suppressed = ref(true)
    const { api, doc, validation, app } = harness({ suppressed })

    doc.value = document([inputNode('Mid-drag')])
    await flush()
    expect(api.calls).toHaveLength(0)

    // Cmd+Enter. Suppression exists to stop the loop firing under a gesture
    // nobody asked about; this is somebody asking, so it wins.
    validation.validateNow()
    await flush()

    expect(api.calls).toHaveLength(1)
    app.unmount()
  })
})
