import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { App } from 'vue'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import { FakeStudioApi, edgeFrame, flush, frameFactory, withSetup } from './helpers'

type ValidatorRun = ReturnType<typeof useValidatorRun>

const EDGE_ACTIVE_MS = 3200

function activeEdges(run: ValidatorRun): string[] {
  return run.graphEdges.value.filter((edge) => edge.data?.active).map((edge) => edge.id).sort()
}

/**
 * jsdom's localStorage schedules a 0 ms task on every write, so those are
 * drained first and what remains is the composable's own pending work.
 */
function settledTimerCount(): number {
  vi.advanceTimersByTime(0)
  return vi.getTimerCount()
}

describe('parallel fan-out edge animation', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App
  let build: ReturnType<typeof frameFactory>
  let unmounted = false

  beforeEach(async () => {
    vi.useFakeTimers()
    localStorage.clear()
    unmounted = false
    api = new FakeStudioApi()
    build = frameFactory()
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
  })

  afterEach(() => {
    if (!unmounted) app.unmount()
    vi.useRealTimers()
  })

  /**
   * The regression test for the single-`activeEdgeId` defect: three sibling
   * branches leave the scope gate together and the graph has to show all three
   * moving, not just the most recent one.
   */
  it('animates all three research branches simultaneously', async () => {
    api.emit(edgeFrame(build, 'scope_gate', 'market_analyst'))
    api.emit(edgeFrame(build, 'scope_gate', 'sentiment_analyst'))
    api.emit(edgeFrame(build, 'scope_gate', 'feasibility_analyst'))
    await flush()

    expect(activeEdges(run)).toEqual([
      'scope_gate-feasibility_analyst',
      'scope_gate-market_analyst',
      'scope_gate-sentiment_analyst',
    ])
  })

  it('gives every edge its own lifetime when the branches start apart', async () => {
    api.emit(edgeFrame(build, 'scope_gate', 'market_analyst'))
    await flush()
    vi.advanceTimersByTime(900)
    api.emit(edgeFrame(build, 'scope_gate', 'sentiment_analyst'))
    await flush()
    vi.advanceTimersByTime(900)
    api.emit(edgeFrame(build, 'scope_gate', 'feasibility_analyst'))
    await flush()

    expect(activeEdges(run)).toHaveLength(3)

    // The market edge started 1800 ms before the feasibility edge, so it must
    // expire on its own without taking its siblings with it.
    vi.advanceTimersByTime(EDGE_ACTIVE_MS - 1800 + 10)
    await flush()
    expect(activeEdges(run)).toEqual([
      'scope_gate-feasibility_analyst',
      'scope_gate-sentiment_analyst',
    ])

    vi.advanceTimersByTime(EDGE_ACTIVE_MS)
    await flush()
    expect(activeEdges(run)).toEqual([])
  })

  it('stops animating an edge as soon as its branch completes', async () => {
    api.emit(edgeFrame(build, 'scope_gate', 'market_analyst'))
    api.emit(edgeFrame(build, 'scope_gate', 'sentiment_analyst'))
    api.emit(edgeFrame(build, 'scope_gate', 'feasibility_analyst'))
    await flush()

    api.emit(build('node_state', { event_type: 'NODE_END', node_id: 'market_analyst' }))
    await flush()

    expect(activeEdges(run)).toEqual([
      'scope_gate-feasibility_analyst',
      'scope_gate-sentiment_analyst',
    ])
    expect(run.graphNodes.value.find((node) => node.id === 'market_analyst')?.data?.state).toBe('completed')
  })

  it('stops animating an edge when its branch errors', async () => {
    api.emit(edgeFrame(build, 'scope_gate', 'sentiment_analyst'))
    await flush()
    api.emit(build('node_state', { event_type: 'NODE_ERROR', level: 'ERROR', node_id: 'sentiment_analyst' }))
    await flush()

    expect(activeEdges(run)).toEqual([])
  })

  it('keeps a re-taken edge alive for a fresh interval', async () => {
    api.emit(edgeFrame(build, 'market_analyst', 'synthesist'))
    await flush()
    vi.advanceTimersByTime(3000)
    api.emit(edgeFrame(build, 'sentiment_analyst', 'synthesist'))
    await flush()

    // The first edge is nearly expired, the second has just started.
    vi.advanceTimersByTime(400)
    await flush()
    expect(activeEdges(run)).toEqual(['sentiment_analyst-synthesist'])
  })

  it('clears every traversal when the run reaches a terminal state', async () => {
    const baseline = settledTimerCount()
    api.emit(edgeFrame(build, 'scope_gate', 'market_analyst'))
    api.emit(edgeFrame(build, 'scope_gate', 'sentiment_analyst'))
    await flush()
    expect(activeEdges(run)).toHaveLength(2)

    api.emit(build('run_state', { event_type: 'RUN_COMPLETED', details: { status: 'completed' } }))
    await flush()

    expect(activeEdges(run)).toEqual([])
    expect(settledTimerCount()).toBe(baseline)
  })

  it('carries no edge state or timer across a relaunch', async () => {
    const baseline = settledTimerCount()
    api.emit(edgeFrame(build, 'scope_gate', 'market_analyst'))
    api.emit(edgeFrame(build, 'scope_gate', 'sentiment_analyst'))
    api.emit(edgeFrame(build, 'scope_gate', 'feasibility_analyst'))
    await flush()
    expect(settledTimerCount()).toBe(baseline + 3)

    api.emit(build('run_state', { event_type: 'RUN_COMPLETED', details: { status: 'completed' } }))
    await flush()
    await run.launch()

    expect(run.status.value).toBe('queued')
    expect(activeEdges(run)).toEqual([])
    expect(settledTimerCount()).toBe(baseline)

    // The fresh run still animates: cleanup did not disable the mechanism.
    const next = frameFactory()
    api.emit(edgeFrame(next, 'scoper', 'scope_gate'))
    await flush()
    expect(activeEdges(run)).toEqual(['scoper-scope_gate'])
  })

  it('leaks no edge timers on unmount', async () => {
    const baseline = settledTimerCount()
    api.emit(edgeFrame(build, 'scope_gate', 'market_analyst'))
    api.emit(edgeFrame(build, 'scope_gate', 'feasibility_analyst'))
    await flush()
    expect(settledTimerCount()).toBe(baseline + 2)

    app.unmount()
    unmounted = true

    expect(settledTimerCount()).toBe(baseline)
    expect(api.unsubscribeCount).toBeGreaterThan(0)
  })
})
