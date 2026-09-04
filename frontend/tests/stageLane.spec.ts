import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CrewProgress from '../src/components/CrewProgress.vue'
import { CREW_STAGES, stagesFromFrames } from '../src/data/crewStages'
import { MOCK_GRAPH } from '../src/data/mockGraph'
import type { RunStage } from '../src/composables/useRunChoreography'
import type { GraphDescriptor, NodeRunState } from '../src/types/studio'

/**
 * The phase lane, for a graph this console has never seen before.
 *
 * `CREW_STAGES` describes the validator and `assertStageCoverage` correctly
 * refuses to narrate anything else - there is no sequence there it understands.
 * The cost was that a published builder graph got no strip at all, so the one
 * surface answering "how far along is this" was missing from every graph
 * anybody drew. The server has known the answer since plan 10: one C6 `stage`
 * frame per topological layer, emitted at kickoff.
 */

/** A three-layer plan, as `builder_runner._emit_plan` would emit it. */
const PIPELINE: RunStage[] = [
  { index: 1, of: 3, label: 'Research', nodeIds: ['research'] },
  { index: 2, of: 3, label: 'Draft, Review', nodeIds: ['draft', 'review'] },
  { index: 3, of: 3, label: 'Publish', nodeIds: ['publish'] },
]

/** A descriptor `CREW_STAGES` knows nothing about - a graph somebody drew. */
function drawnGraph(): GraphDescriptor {
  return {
    id: 'ug_1234abcd',
    name: 'Sequential pipeline',
    version: 'v1',
    start_nodes: ['research'],
    nodes: ['research', 'draft', 'review', 'publish'].map((id, index) => ({
      id,
      label: id,
      eyebrow: `0${index + 1}`,
      description: '',
      kind: 'agent',
      position: { x: index * 200, y: 0 },
    })),
    edges: [],
  } as unknown as GraphDescriptor
}

function lane(
  nodeStates: Record<string, NodeRunState>,
  descriptor: GraphDescriptor,
  runStages?: RunStage[],
) {
  return mount(CrewProgress, {
    props: { nodeStates, descriptor, active: true, runStages },
  })
}

describe('stagesFromFrames', () => {
  it('turns each layer into one stage, in index order', () => {
    const stages = stagesFromFrames([...PIPELINE].reverse())
    expect(stages.map((stage) => stage.id)).toEqual(['stage-1', 'stage-2', 'stage-3'])
  })

  it('makes every node in a layer a core node', () => {
    // A layer IS the set of nodes that can run at once, so the stage is done
    // when all of them are. There is no builder equivalent of the validator's
    // revise nodes: a drawn loop closes through a router, which is a node in a
    // layer like any other.
    const stages = stagesFromFrames(PIPELINE)
    expect(stages[1].coreIds).toEqual(['draft', 'review'])
    expect(stages[1].nodeIds).toEqual(['draft', 'review'])
    expect(stages[1].reviseIds).toBeUndefined()
  })

  it('marks a multi-node layer parallel and names its branches', () => {
    const stages = stagesFromFrames(PIPELINE)
    expect(stages[1].parallel).toBe(true)
    expect(stages[1].branchLabels).toEqual(['Draft', 'Review'])
    expect(stages[0].parallel).toBe(false)
  })

  it('takes the chip label from the first name, not the whole joined line', () => {
    // `_emit_plan` joins every node's label with commas, which is right for a
    // log line and about five times too long for a chip.
    expect(stagesFromFrames(PIPELINE)[1].label).toBe('Draft')
  })

  it('falls back to node ids when the label does not decompose', () => {
    const stages = stagesFromFrames([
      { index: 1, of: 1, label: 'one label for two nodes', nodeIds: ['a', 'b'] },
    ])
    expect(stages[0].branchLabels).toEqual(['a', 'b'])
  })

  it('drops a layer naming no nodes', () => {
    expect(stagesFromFrames([{ index: 1, of: 1, label: 'x', nodeIds: [] }])).toEqual([])
  })
})

describe('the lane on a drawn graph', () => {
  it('appears, where today the strip hides itself entirely', () => {
    // The defect this closes: `assertStageCoverage` fails for a graph it does
    // not know, `CrewProgress` hides, and a published run has no progress
    // indicator of any kind.
    const withoutPlan = lane({ research: 'running' }, drawnGraph())
    expect(withoutPlan.find('.crew-progress').exists()).toBe(false)

    const withPlan = lane({ research: 'running' }, drawnGraph(), PIPELINE)
    expect(withPlan.find('.crew-progress').exists()).toBe(true)
  })

  it('shows one chip per layer, in order', () => {
    const wrapper = lane({ research: 'running' }, drawnGraph(), PIPELINE)
    const labels = wrapper.findAll('.crew-label').map((node) => node.text())
    expect(labels).toEqual(['Research', 'Draft', 'Publish'])
  })

  it('advances as the layers complete', () => {
    const first = lane({ research: 'running' }, drawnGraph(), PIPELINE)
    expect(first.get('.crew-stage.is-current .crew-label').text()).toBe('Research')

    const second = lane(
      { research: 'completed', draft: 'running', review: 'idle' },
      drawnGraph(),
      PIPELINE,
    )
    expect(second.get('.crew-stage.is-current .crew-label').text()).toBe('Draft')
  })

  it('draws medallions instead of the boat', () => {
    // The boat is the validator's, and its three oars ARE three research
    // branches. A graph somebody drew has no such fact, so three rowers on a
    // two-node layer would claim a fan-out that does not exist.
    const wrapper = lane(
      { research: 'completed', draft: 'running', review: 'running' },
      drawnGraph(),
      PIPELINE,
    )
    expect(wrapper.find('[data-testid="crew-medallions"]').exists()).toBe(true)
    expect(wrapper.find('.crew-boat').exists()).toBe(false)
    expect(wrapper.findAll('.crew-medallion')).toHaveLength(2)
  })

  it('bounds the medallions at four, which is MAX_FANOUT_WIDTH', () => {
    const wide: RunStage[] = [
      { index: 1, of: 1, label: 'a, b, c, d, e', nodeIds: ['a', 'b', 'c', 'd', 'e'] },
    ]
    const graph = drawnGraph()
    graph.nodes = ['a', 'b', 'c', 'd', 'e'].map((id) => ({
      ...graph.nodes[0],
      id,
      label: id,
    }))
    const running = Object.fromEntries(
      ['a', 'b', 'c', 'd', 'e'].map((id) => [id, 'running' as NodeRunState]),
    )
    const wrapper = lane(running, graph, wide)
    expect(wrapper.findAll('.crew-medallion')).toHaveLength(4)
  })
})

describe('the validator is unchanged', () => {
  const validatorStates: Record<string, NodeRunState> = {
    scope_idea: 'completed',
    confirm_scope: 'completed',
    route_scope: 'completed',
    research_market: 'running',
    research_sentiment: 'running',
    research_feasibility: 'running',
  }

  it('keeps the boat and the three named oars', () => {
    // Criterion 7. The precedence in `CrewProgress` runs validator-first for
    // exactly this: a topological plan would emit the three research branches
    // as one anonymous layer, which is true about the graph and a worse picture
    // of the crew.
    const wrapper = lane(validatorStates, MOCK_GRAPH)
    expect(wrapper.find('.crew-boat').exists()).toBe(true)
    expect(wrapper.find('[data-testid="crew-medallions"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="crew-oar-names"]').text()).toContain('Market')
  })

  it('keeps the boat even if a plan somehow arrives for it', () => {
    // The two readings never disagree today - `_emit_plan` lives on the builder
    // runner, so neither hand-written flow emits one - but the precedence is
    // written down because the day one does is the day it matters.
    const wrapper = lane(validatorStates, MOCK_GRAPH, PIPELINE)
    expect(wrapper.find('.crew-boat').exists()).toBe(true)
    const labels = wrapper.findAll('.crew-label').map((node) => node.text())
    expect(labels).toEqual(CREW_STAGES.map((stage) => stage.label))
  })
})
