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
   * The regression test for the single-`activeEdgeId` defect: `route_scope`
   * emits one `scope_approved` event that releases all three branches at once,
   * and the graph has to show all three moving, not just the most recent one.
   */
  it('animates all three research branches simultaneously', async () => {
    api.emit(edgeFrame(build, 'route_scope', 'research_market'))
    api.emit(edgeFrame(build, 'route_scope', 'research_sentiment'))
    api.emit(edgeFrame(build, 'route_scope', 'research_feasibility'))
    await flush()

    expect(activeEdges(run)).toEqual([
      'route_scope->research_feasibility:scope_approved',
      'route_scope->research_market:scope_approved',
      'route_scope->research_sentiment:scope_approved',
    ])
  })

  it('gives every edge its own lifetime when the branches start apart', async () => {
    api.emit(edgeFrame(build, 'route_scope', 'research_market'))
    await flush()
    vi.advanceTimersByTime(900)
    api.emit(edgeFrame(build, 'route_scope', 'research_sentiment'))
    await flush()
    vi.advanceTimersByTime(900)
    api.emit(edgeFrame(build, 'route_scope', 'research_feasibility'))
    await flush()

    expect(activeEdges(run)).toHaveLength(3)

    // The market edge started 1800 ms before the feasibility edge, so it must
    // expire on its own without taking its siblings with it.
    vi.advanceTimersByTime(EDGE_ACTIVE_MS - 1800 + 10)
    await flush()
    expect(activeEdges(run)).toEqual([
      'route_scope->research_feasibility:scope_approved',
      'route_scope->research_sentiment:scope_approved',
    ])

    vi.advanceTimersByTime(EDGE_ACTIVE_MS)
    await flush()
    expect(activeEdges(run)).toEqual([])
  })

  it('stops animating an edge as soon as its branch completes', async () => {
    api.emit(edgeFrame(build, 'route_scope', 'research_market'))
    api.emit(edgeFrame(build, 'route_scope', 'research_sentiment'))
    api.emit(edgeFrame(build, 'route_scope', 'research_feasibility'))
    await flush()

    api.emit(build('node_state', { event_type: 'NODE_END', node_id: 'research_market' }))
    await flush()

    expect(activeEdges(run)).toEqual([
      'route_scope->research_feasibility:scope_approved',
      'route_scope->research_sentiment:scope_approved',
    ])
    expect(run.graphNodes.value.find((node) => node.id === 'research_market')?.data?.state).toBe('completed')
  })

  it('stops animating an edge when its branch errors', async () => {
    api.emit(edgeFrame(build, 'route_scope', 'research_sentiment'))
    await flush()
    api.emit(build('node_state', { event_type: 'NODE_ERROR', level: 'ERROR', node_id: 'research_sentiment' }))
    await flush()

    expect(activeEdges(run)).toEqual([])
  })

  it('keeps a re-taken edge alive for a fresh interval', async () => {
    api.emit(edgeFrame(build, 'research_market', 'synthesize'))
    await flush()
    vi.advanceTimersByTime(3000)
    api.emit(edgeFrame(build, 'research_sentiment', 'synthesize'))
    await flush()

    // The first edge is nearly expired, the second has just started.
    vi.advanceTimersByTime(400)
    await flush()
    expect(activeEdges(run)).toEqual(['research_sentiment->synthesize:'])
  })

  it('clears every traversal when the run reaches a terminal state', async () => {
    const baseline = settledTimerCount()
    api.emit(edgeFrame(build, 'route_scope', 'research_market'))
    api.emit(edgeFrame(build, 'route_scope', 'research_sentiment'))
    await flush()
    expect(activeEdges(run)).toHaveLength(2)

    api.emit(build('run_state', { event_type: 'RUN_COMPLETED', details: { status: 'completed' } }))
    await flush()

    expect(activeEdges(run)).toEqual([])
    expect(settledTimerCount()).toBe(baseline)
  })

  it('carries no edge state or timer across a relaunch', async () => {
    const baseline = settledTimerCount()
    api.emit(edgeFrame(build, 'route_scope', 'research_market'))
    api.emit(edgeFrame(build, 'route_scope', 'research_sentiment'))
    api.emit(edgeFrame(build, 'route_scope', 'research_feasibility'))
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
    api.emit(edgeFrame(next, 'scope_idea', 'confirm_scope'))
    await flush()
    expect(activeEdges(run)).toEqual(['scope_idea->confirm_scope:'])
  })

  it('leaks no edge timers on unmount', async () => {
    const baseline = settledTimerCount()
    api.emit(edgeFrame(build, 'route_scope', 'research_market'))
    api.emit(edgeFrame(build, 'route_scope', 'research_feasibility'))
    await flush()
    expect(settledTimerCount()).toBe(baseline + 2)

    app.unmount()
    unmounted = true

    expect(settledTimerCount()).toBe(baseline)
    expect(api.unsubscribeCount).toBeGreaterThan(0)
  })
})
