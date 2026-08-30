import { describe, expect, it } from 'vitest'
import { MOCK_GRAPH } from '../src/data/mockGraph'
import {
  CREW_STAGES,
  activeStageIndex,
  assertStageCoverage,
  stageProgress,
} from '../src/data/crewStages'
import type { NodeRunState } from '../src/types/studio'

const idle = (): Record<string, NodeRunState> =>
  Object.fromEntries(MOCK_GRAPH.nodes.map((n) => [n.id, 'idle' as NodeRunState]))

describe('stage coverage', () => {
  it('accounts for every node in the live topology', () => {
    // The whole point of the assertion: adding a node to the flow without
    // staging it must fail here, not silently make the boat skip it.
    expect(assertStageCoverage(MOCK_GRAPH)).toEqual([])
  })

  it('reports a node that belongs to no stage', () => {
    const graph = structuredClone(MOCK_GRAPH)
    graph.nodes.push({ ...graph.nodes[0], id: 'brand_new_step' })
    expect(assertStageCoverage(graph)).toContain('brand_new_step belongs to no stage')
  })

  it('reports a staged node that the graph does not have', () => {
    const graph = structuredClone(MOCK_GRAPH)
    graph.nodes = graph.nodes.filter((n) => n.id !== 'persist')
    expect(assertStageCoverage(graph)).toContain('persist is staged but absent from the graph')
  })

  it('covers the three research branches as one parallel stage', () => {
    const research = CREW_STAGES.find((s) => s.id === 'research')
    expect(research?.parallel).toBe(true)
    expect(research?.coreIds).toEqual([
      'research_market',
      'research_sentiment',
      'research_feasibility',
    ])
  })
})

describe('stageProgress', () => {
  it('is idle across the board before anything runs', () => {
    const progress = stageProgress(idle())
    expect(progress.every((p) => p.state === 'idle')).toBe(true)
    expect(activeStageIndex(progress)).toBe(-1)
  })

  it('marks a stage running when any of its nodes runs', () => {
    const states = { ...idle(), scope_idea: 'running' as NodeRunState }
    const progress = stageProgress(states)
    expect(progress[0].state).toBe('running')
    expect(activeStageIndex(progress)).toBe(0)
  })

  it('lets waiting outrank running, because a gate needs the human', () => {
    const states = {
      ...idle(),
      scope_idea: 'completed' as NodeRunState,
      confirm_scope: 'waiting' as NodeRunState,
      research_market: 'running' as NodeRunState,
    }
    const progress = stageProgress(states)
    expect(progress[1].state).toBe('waiting')
    expect(activeStageIndex(progress)).toBe(1)
  })

  it('lets error outrank everything', () => {
    const states = {
      ...idle(),
      research_market: 'running' as NodeRunState,
      research_sentiment: 'error' as NodeRunState,
    }
    const progress = stageProgress(states)
    expect(progress[2].state).toBe('error')
    expect(activeStageIndex(progress)).toBe(2)
  })

  it('counts the fan-out draining, one branch at a time', () => {
    const partial = stageProgress({
      ...idle(),
      research_market: 'completed' as NodeRunState,
      research_sentiment: 'running' as NodeRunState,
      research_feasibility: 'running' as NodeRunState,
    })
    expect(partial[2]).toMatchObject({ state: 'running', done: 1, total: 3 })
  })

  it('only completes the fan-out when all three branches are home', () => {
    const two = stageProgress({
      ...idle(),
      research_market: 'completed' as NodeRunState,
      research_sentiment: 'completed' as NodeRunState,
    })
    expect(two[2].state).not.toBe('completed')

    const all = stageProgress({
      ...idle(),
      research_market: 'completed' as NodeRunState,
      research_sentiment: 'completed' as NodeRunState,
      research_feasibility: 'completed' as NodeRunState,
    })
    expect(all[2].state).toBe('completed')
  })

  it('does not require the revise nodes, which only run on a revise loop', () => {
    // `revise_scope` never runs in the common case, so treating it as required
    // would leave the Scope stage permanently unfinished.
    const progress = stageProgress({ ...idle(), scope_idea: 'completed' as NodeRunState })
    expect(progress[0].state).toBe('completed')
  })

  it('rests the boat just past the last finished stage', () => {
    const progress = stageProgress({
      ...idle(),
      scope_idea: 'completed' as NodeRunState,
      confirm_scope: 'completed' as NodeRunState,
    })
    expect(activeStageIndex(progress)).toBe(2)
  })

  it('clamps the boat to the final stage on a finished run', () => {
    const states = idle()
    for (const stage of CREW_STAGES) {
      for (const id of stage.coreIds) states[id] = 'completed'
    }
    const progress = stageProgress(states)
    expect(activeStageIndex(progress)).toBe(CREW_STAGES.length - 1)
    expect(progress.every((p) => p.state === 'completed')).toBe(true)
  })
})
