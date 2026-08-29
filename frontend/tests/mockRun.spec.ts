import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { App } from 'vue'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import { StudioApi } from '../src/services/studioApi'
import { flush, withSetup } from './helpers'

type ValidatorRun = ReturnType<typeof useValidatorRun>

/**
 * Drives the real mock transport - `StudioApi` in `mock` mode, playing
 * `buildMockSegments` on real timers - through the real composable. Nothing is
 * faked but the clock and the network probe, so this is the offline demo as an
 * operator sees it: if the mock stops animating, or animates against nodes the
 * graph does not have, this fails.
 */
describe('the offline mock run, end to end', () => {
  let api: StudioApi
  let run: ValidatorRun
  let app: App
  let originalFetch: typeof globalThis.fetch

  /** Advances the mock stream and drains the composable's frame queue with it. */
  async function tick(ms: number): Promise<void> {
    for (let elapsed = 0; elapsed < ms; elapsed += 40) {
      vi.advanceTimersByTime(40)
      await flush(3)
    }
  }

  const stateOf = (id: string) => run.graphNodes.value.find((graphNode) => graphNode.id === id)?.data?.state
  const activeEdges = () =>
    run.graphEdges.value.filter((edge) => edge.data?.active).map((edge) => edge.id).sort()

  beforeEach(async () => {
    vi.useFakeTimers()
    localStorage.clear()
    originalFetch = globalThis.fetch
    // No backend: the probe fails and the transport falls back to the mock,
    // which is the only situation the mock exists for.
    globalThis.fetch = vi.fn(async () => {
      throw new Error('connection refused')
    }) as unknown as typeof globalThis.fetch
    api = new StudioApi()
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
  })

  afterEach(() => {
    app.unmount()
    globalThis.fetch = originalFetch
    vi.useRealTimers()
  })

  it('falls back to the mock graph and renders the live topology', () => {
    expect(run.transportMode.value).toBe('mock')
    expect(run.descriptor.value.nodes.map((graphNode) => graphNode.id)).toContain('route_scope')
    expect(stateOf('scope_idea')).toBe('idle')
  })

  it('plays scope, both gates and the three-way fan-out through to a finished run', async () => {
    await run.launch()
    await flush()
    expect(run.status.value).toBe('queued')

    // Segment one: the Scoper runs and the first gate opens.
    await tick(5_000)
    expect(stateOf('scope_idea')).toBe('completed')
    expect(stateOf('confirm_scope')).toBe('waiting')
    expect(run.status.value).toBe('waiting')
    expect(run.pendingGate.value?.nodeId).toBe('confirm_scope')
    expect(run.pendingGate.value?.options.map((option) => option.id)).toEqual(['approve', 'revise'])

    // Answering releases segment two through the deterministic router.
    await run.submitGate('approve', run.pendingGate.value?.fields)
    await flush()
    await tick(1_800)
    expect(stateOf('confirm_scope')).toBe('completed')
    expect(stateOf('route_scope')).toBe('completed')

    // The fan-out: one router event, three branches marching at once. This is
    // the property the mock previously could not rehearse at all.
    await tick(700)
    expect(activeEdges()).toEqual([
      'route_scope->research_feasibility:scope_approved',
      'route_scope->research_market:scope_approved',
      'route_scope->research_sentiment:scope_approved',
    ])
    expect(stateOf('research_market')).toBe('running')
    expect(stateOf('research_sentiment')).toBe('running')
    expect(stateOf('research_feasibility')).toBe('running')

    // Branches converge, synthesis scores, the second gate opens.
    await tick(20_000)
    expect(stateOf('research_market')).toBe('completed')
    expect(stateOf('research_sentiment')).toBe('completed')
    expect(stateOf('research_feasibility')).toBe('completed')
    expect(stateOf('synthesize')).toBe('completed')
    expect(stateOf('review_verdict')).toBe('waiting')
    expect(run.pendingGate.value?.nodeId).toBe('review_verdict')
    expect(run.pendingGate.value?.verdict).toBe('NEEDS_WORK')

    await run.submitGate('approve')
    await flush()
    await tick(10_000)

    expect(stateOf('route_verdict')).toBe('completed')
    expect(stateOf('write_report')).toBe('completed')
    expect(stateOf('persist')).toBe('completed')
    expect(run.status.value).toBe('completed')
    // A finished run leaves nothing marching and nothing quarantined.
    expect(activeEdges()).toEqual([])
    expect(run.quarantinedFrames.value).toBe(0)
    expect(run.usage.totalTokens).toBeGreaterThan(0)
    expect(run.lastError.value).toBe('')
  })

  it('never routes a frame to a node the graph does not declare', async () => {
    const declared = new Set(run.descriptor.value.nodes.map((graphNode) => graphNode.id))
    await run.launch()
    await tick(5_000)
    await run.submitGate('approve')
    await flush()
    await tick(22_000)
    await run.submitGate('approve')
    await flush()
    await tick(10_000)

    const attributed = run.chatEntries.value.map((entry) => entry.nodeId).filter(Boolean) as string[]
    expect(attributed.length).toBeGreaterThan(0)
    for (const id of attributed) expect(declared.has(id)).toBe(true)
  })
})
