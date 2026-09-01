import { describe, expect, it } from 'vitest'
import { MOCK_GRAPH } from '../src/data/mockGraph'
import {
  CREW_STAGES,
  activeStageIndex,
  assertStageCoverage,
  stageProgress,
} from '../src/data/crewStages'
import type { NodeRunState } from '../src/types/studio'

/**
 * The revise loop, from the strip's point of view.
 *
 * This file exists because the loop was structurally invisible: `revise_scope`
 * sat inside the `scope` stage as a non-core node, so a revision re-ran the
 * stage and the boat slid backwards with nothing on screen to say why. A lap is
 * not recoverable from `nodeStates` either - a node that ran four times and one
 * that ran once are both `completed` - so the count comes from a separate
 * visits map, and these tests pin the arithmetic that reads it.
 */

const idle = (): Record<string, NodeRunState> =>
  Object.fromEntries(MOCK_GRAPH.nodes.map((n) => [n.id, 'idle' as NodeRunState]))

const stageById = (id: string) => {
  const stage = CREW_STAGES.find((s) => s.id === id)
  if (!stage) throw new Error(`no stage ${id}`)
  return stage
}

const progressFor = (
  states: Record<string, NodeRunState>,
  visits: Record<string, number> = {},
) => {
  const rows = stageProgress(states, CREW_STAGES, visits)
  return (id: string) => {
    const row = rows.find((r) => r.stage.id === id)
    if (!row) throw new Error(`no progress row ${id}`)
    return row
  }
}

describe('the loop is declared, not guessed', () => {
  it('names the revise node for each stage that can be re-entered', () => {
    expect(stageById('scope').reviseIds).toEqual(['revise_scope'])
    expect(stageById('score').reviseIds).toEqual(['revise_verdict'])
  })

  it('leaves the straight-through stages with no revise node', () => {
    // Research is re-entered through its cores after a scope revision, not
    // through a revise node of its own. Declaring one here would double-count.
    for (const id of ['gate-scope', 'research', 'gate-verdict', 'report', 'brief']) {
      expect(stageById(id).reviseIds).toBeUndefined()
    }
  })

  it('never lets a revise node also be a core node', () => {
    // A revise node that was core would make the stage un-completable: `done`
    // counts completed cores, and on a run that never loops the revise node
    // stays idle forever.
    for (const stage of CREW_STAGES) {
      for (const reviseId of stage.reviseIds ?? []) {
        expect(stage.coreIds).not.toContain(reviseId)
      }
    }
  })

  it('reports a revise node declared outside its own nodeIds', () => {
    const broken = CREW_STAGES.map((s) =>
      s.id === 'scope' ? { ...s, reviseIds: ['not_in_node_ids'] } : s,
    )
    expect(assertStageCoverage(MOCK_GRAPH, broken)).toContain(
      'scope lists revise node not_in_node_ids outside its nodeIds',
    )
  })

  it('reports a node declared as both core and revise', () => {
    const broken = CREW_STAGES.map((s) =>
      s.id === 'scope' ? { ...s, reviseIds: ['scope_idea'] } : s,
    )
    expect(assertStageCoverage(MOCK_GRAPH, broken)).toContain(
      'scope lists scope_idea as both core and revise',
    )
  })
})

describe('lap arithmetic', () => {
  it('is 0 for a stage nothing has touched', () => {
    const at = progressFor(idle())
    expect(at('scope').lap).toBe(0)
    expect(at('report').lap).toBe(0)
  })

  it('is 1 on a straight pass', () => {
    const states = idle()
    states.scope_idea = 'completed'
    const at = progressFor(states, { scope_idea: 1 })
    expect(at('scope').lap).toBe(1)
  })

  it('counts a revise node as a further pass over the same stage', () => {
    const states = idle()
    states.scope_idea = 'completed'
    states.revise_scope = 'running'
    const at = progressFor(states, { scope_idea: 1, revise_scope: 1 })
    expect(at('scope').lap).toBe(2)
  })

  it('keeps counting across repeated revisions', () => {
    const states = idle()
    states.scope_idea = 'completed'
    states.revise_scope = 'completed'
    const at = progressFor(states, { scope_idea: 1, revise_scope: 3 })
    expect(at('scope').lap).toBe(4)
  })

  it('counts a stage re-entered through its own cores', () => {
    // Approve after a scope revision and all three branches run again. There is
    // no revise node here - the cores carry the lap themselves, which is why
    // the formula takes the max of both and not just the revise count.
    const states = idle()
    states.research_market = 'running'
    const at = progressFor(states, {
      research_market: 2,
      research_sentiment: 2,
      research_feasibility: 2,
    })
    expect(at('research').lap).toBe(2)
  })

  it('reports lap 1 for a running stage when no visits map is supplied', () => {
    // The optional argument must degrade to an honest under-report, never to 0
    // on a stage that is visibly working.
    const states = idle()
    states.synthesize = 'running'
    const at = progressFor(states)
    expect(at('score').lap).toBe(1)
  })

  it('does not let one stage\'s lap leak into another', () => {
    const states = idle()
    states.scope_idea = 'completed'
    states.revise_scope = 'completed'
    states.synthesize = 'running'
    const at = progressFor(states, { scope_idea: 1, revise_scope: 2, synthesize: 1 })
    expect(at('scope').lap).toBe(3)
    expect(at('score').lap).toBe(1)
  })
})

describe('named branches', () => {
  it('gives every core node of the fan-out a short name', () => {
    const research = stageById('research')
    expect(research.branchLabels).toEqual(['Market', 'Signal', 'Build'])
    expect(research.branchLabels?.length).toBe(research.coreIds.length)
  })

  it('pairs each label with its own node id, in order', () => {
    const at = progressFor(idle())
    expect(at('research').branches.map((b) => [b.id, b.label])).toEqual([
      ['research_market', 'Market'],
      ['research_sentiment', 'Signal'],
      ['research_feasibility', 'Build'],
    ])
  })

  it('carries each branch its OWN state, not a running total', () => {
    // The old pip row lit left-to-right by count, so a fast Feasibility drew
    // the same picture as a fast Market. This is the fix, asserted.
    const states = idle()
    states.research_market = 'running'
    states.research_sentiment = 'running'
    states.research_feasibility = 'completed'
    const at = progressFor(states)
    expect(at('research').branches.map((b) => b.state)).toEqual([
      'running',
      'running',
      'completed',
    ])
    expect(at('research').done).toBe(1)
  })

  it('falls back to the node id when a stage declares no labels', () => {
    const at = progressFor(idle())
    expect(at('scope').branches).toEqual([
      { id: 'scope_idea', label: 'scope_idea', state: 'idle' },
    ])
  })

  it('rejects a label list that does not match the core count', () => {
    // An oar caption row silently one short is worse than none: it renames the
    // branches by shifting them, so the strip reports the wrong agent.
    const broken = CREW_STAGES.map((s) =>
      s.id === 'research' ? { ...s, branchLabels: ['Market', 'Signal'] } : s,
    )
    expect(assertStageCoverage(MOCK_GRAPH, broken)).toContain(
      'research has 2 branch labels for 3 core nodes',
    )
  })
})

describe('a finished stage is not re-opened by its own router', () => {
  /*
   * The bug this section exists for, caught by watching a real synthetic run
   * rather than by any test: answering a gate makes the backend start that
   * stage's ROUTER, and a router shares the stage with the gate it reads.
   * Ranking every `running` above "all cores done" flipped the stage
   * completed -> running -> completed, so the boat bounced back a column and
   * forward again on every single gate answer.
   */
  const afterGateAnswer = () => {
    const states = idle()
    states.scope_idea = 'completed'
    states.confirm_scope = 'completed'
    states.route_scope = 'running'
    return states
  }

  it('keeps the gate stage completed while its router runs', () => {
    const at = progressFor(afterGateAnswer(), { scope_idea: 1, confirm_scope: 1, route_scope: 1 })
    expect(at('gate-scope').state).toBe('completed')
  })

  it('lets the boat move ON rather than bouncing back', () => {
    const index = activeStageIndex(
      stageProgress(afterGateAnswer(), CREW_STAGES, { route_scope: 1 }),
    )
    // Past both finished stages, not back onto the one just left.
    expect(index).toBe(2)
  })

  it('does the same at the verdict gate', () => {
    const states = idle()
    states.synthesize = 'completed'
    states.review_verdict = 'completed'
    states.route_verdict = 'running'
    const at = progressFor(states, { synthesize: 1, review_verdict: 1, route_verdict: 1 })
    expect(at('gate-verdict').state).toBe('completed')
    expect(activeStageIndex(stageProgress(states, CREW_STAGES))).toBe(5)
  })

  it('still shows the gate stage running BEFORE its core is done', () => {
    // The carve-out is only for a stage whose real work has finished. A router
    // running while the gate itself has not settled is genuinely this stage.
    const states = idle()
    states.scope_idea = 'completed'
    states.route_scope = 'running'
    const at = progressFor(states)
    expect(at('gate-scope').state).toBe('running')
  })

  it('still re-opens the stage for a declared revise node', () => {
    // The one running node that IS a return must still win.
    const states = idle()
    states.scope_idea = 'completed'
    states.revise_scope = 'running'
    const at = progressFor(states, { scope_idea: 1, revise_scope: 1 })
    expect(at('scope').state).toBe('running')
  })

  it('still lets a waiting gate outrank everything', () => {
    const states = idle()
    states.scope_idea = 'completed'
    states.confirm_scope = 'waiting'
    states.route_scope = 'running'
    const at = progressFor(states)
    expect(at('gate-scope').state).toBe('waiting')
  })

  it('still lets an error outrank a completed stage', () => {
    const states = idle()
    states.confirm_scope = 'completed'
    states.route_scope = 'error'
    const at = progressFor(states)
    expect(at('gate-scope').state).toBe('error')
  })
})

describe('the boat moves backwards on a revision', () => {
  it('leaves the scope gate for the scope stage when revise_scope runs', () => {
    const before = idle()
    before.scope_idea = 'completed'
    before.confirm_scope = 'waiting'
    const atGate = activeStageIndex(stageProgress(before, CREW_STAGES, { scope_idea: 1 }))

    const after = idle()
    after.scope_idea = 'completed'
    after.confirm_scope = 'completed'
    after.revise_scope = 'running'
    const backOnScope = activeStageIndex(
      stageProgress(after, CREW_STAGES, { scope_idea: 1, revise_scope: 1 }),
    )

    expect(atGate).toBe(1)
    expect(backOnScope).toBe(0)
    expect(backOnScope).toBeLessThan(atGate)
  })

  it('leaves the verdict gate for the score stage when revise_verdict runs', () => {
    const before = idle()
    before.synthesize = 'completed'
    before.review_verdict = 'waiting'
    const atGate = activeStageIndex(stageProgress(before, CREW_STAGES, { synthesize: 1 }))

    const after = idle()
    after.synthesize = 'completed'
    after.review_verdict = 'completed'
    after.revise_verdict = 'running'
    const backOnScore = activeStageIndex(
      stageProgress(after, CREW_STAGES, { synthesize: 1, revise_verdict: 1 }),
    )

    expect(atGate).toBe(4)
    expect(backOnScore).toBe(3)
    expect(backOnScore).toBeLessThan(atGate)
  })
})
