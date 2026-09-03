import { afterEach, describe, expect, it } from 'vitest'
import type { App } from 'vue'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import { MOCK_GRAPH } from '../src/data/mockGraph'
import type { GraphDescriptor } from '../src/types/studio'
import { FakeStudioApi, withSetup } from './helpers'

/**
 * A graph the server refuses (D-01-2, CLAUDE.md remaining-work item 43).
 *
 * The scenario is Bob's console pointed at Alice's published workflow: the
 * transport probe reaches a live backend, and the graph read answers the 404
 * plan 01 D1 prescribes for somebody else's graph. Round 1 found the console
 * answering that 404 by flipping to MOCK mode - the 14-node demonstration
 * graph drawn under Alice's graph name, a "Mock Mode" chip, and an enabled
 * green Launch. A 404 can only come from a real server, so the right answer
 * is the one asserted here: live, empty, the server's sentence, no Launch.
 *
 * The fake throws what `fetchJson` throws - an `Error` whose message is the
 * server's `detail` - so the sentence on screen is the server's, verbatim.
 */
class RefusingApi extends FakeStudioApi {
  refusal: unknown = new Error('workflow not found')

  override async getGraph(): Promise<GraphDescriptor> {
    throw this.refusal
  }
}

const IDEA = 'A scheduling assistant for small veterinary clinics'
const FOREIGN = 'ug_0b94fc25'

describe('a graph the server refuses (D-01-2)', () => {
  let app: App | undefined

  afterEach(() => {
    app?.unmount()
    app = undefined
    localStorage.clear()
  })

  it('keeps the transport live and draws nothing rather than the mock graph', async () => {
    const api = new RefusingApi()
    const [run, mounted] = withSetup(() =>
      useValidatorRun(api, { workflowId: FOREIGN, inputField: 'idea' }),
    )
    app = mounted
    await run.initialize()

    expect(run.transportMode.value).toBe('live')
    expect(run.graphNodes.value).toHaveLength(0)
    expect(run.graphEdges.value).toHaveLength(0)
    // Not the demonstration graph, and not anything that could be read as one.
    expect(run.descriptor.value.version).not.toBe(MOCK_GRAPH.version)
    expect(run.descriptor.value.version).not.toMatch(/^mock-/)
    expect(run.descriptor.value.id).toBe(FOREIGN)
    // The transport banner is for "no backend"; this is not that.
    expect(run.transportProblem.value).toBe('')
  })

  it("carries the server's sentence and keeps Launch disabled", async () => {
    const api = new RefusingApi()
    const [run, mounted] = withSetup(() =>
      useValidatorRun(api, { workflowId: FOREIGN, inputField: 'idea' }),
    )
    app = mounted
    await run.initialize()

    expect(run.graphProblem.value).toBe('workflow not found')
    // A valid idea is the only other thing Launch waits for; it is not enough.
    run.idea.value = IDEA
    expect(run.canLaunch.value).toBe(false)
    await run.launch()
    expect(api.startRunCalls).toEqual([])
    expect(run.runId.value).toBe('')
    expect(run.status.value).toBe('idle')
    expect(localStorage.getItem('validator-active-run')).toBeNull()
  })

  it('does not put the sentence where launch() would erase it', async () => {
    const api = new RefusingApi()
    const [run, mounted] = withSetup(() =>
      useValidatorRun(api, { workflowId: FOREIGN, inputField: 'idea' }),
    )
    app = mounted
    await run.initialize()

    run.dismissError()
    expect(run.graphProblem.value).toBe('workflow not found')
    expect(run.canLaunch.value).toBe(false)
  })

  it("falls back to the probe's own refusal when the graph read gives no sentence", async () => {
    const api = new RefusingApi()
    api.refusal = 'not an Error instance'
    api.probeRefusal = 'sign in to use this endpoint'
    const [run, mounted] = withSetup(() =>
      useValidatorRun(api, { workflowId: FOREIGN, inputField: 'idea' }),
    )
    app = mounted
    await run.initialize()

    expect(run.transportMode.value).toBe('live')
    expect(run.graphProblem.value).toBe('sign in to use this endpoint')
  })

  it('a graph that loads clears a refusal left by an earlier initialize', async () => {
    const api = new RefusingApi()
    const [run, mounted] = withSetup(() =>
      useValidatorRun(api, { workflowId: FOREIGN, inputField: 'idea' }),
    )
    app = mounted
    await run.initialize()
    expect(run.graphProblem.value).toBe('workflow not found')

    api.getGraph = async () => structuredClone(MOCK_GRAPH)
    await run.initialize()
    expect(run.graphProblem.value).toBe('')
    expect(run.graphNodes.value).toHaveLength(MOCK_GRAPH.nodes.length)
  })

  it('still draws the demonstration graph when there is no backend at all', async () => {
    // The mock fallback exists for a MISSING backend, and that case is kept:
    // in mock mode `getGraph` never asks a server and never throws.
    const api = new FakeStudioApi()
    api.mode = 'mock'
    api.probeFailure = 'The validator API could not be reached: connection refused.'
    const [run, mounted] = withSetup(() => useValidatorRun(api))
    app = mounted
    await run.initialize()

    expect(run.transportMode.value).toBe('mock')
    expect(run.transportProblem.value).toContain('could not be reached')
    expect(run.graphProblem.value).toBe('')
    expect(run.graphNodes.value).toHaveLength(MOCK_GRAPH.nodes.length)
    run.idea.value = IDEA
    expect(run.canLaunch.value).toBe(true)
  })
})
