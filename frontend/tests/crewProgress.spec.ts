import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import CrewProgress from '../src/components/CrewProgress.vue'
import { MOCK_GRAPH } from '../src/data/mockGraph'
import type { GraphDescriptor, NodeRunState } from '../src/types/studio'

/**
 * The boat, as a component.
 *
 * `crewStages.spec.ts` and `crewLoop.spec.ts` pin the pure functions; nothing
 * pinned that the component actually renders any of it. That is the same gap
 * that let the report panel ship invisible and the RUN_STATE status ship
 * missing - the arithmetic was right and the picture was absent - so the strip
 * gets its own mount test rather than inheriting confidence from the data layer.
 */

const idle = (): Record<string, NodeRunState> =>
  Object.fromEntries(MOCK_GRAPH.nodes.map((n) => [n.id, 'idle' as NodeRunState]))

function mountCrew(options: {
  states?: Record<string, NodeRunState>
  visits?: Record<string, number>
  descriptor?: GraphDescriptor
  active?: boolean
} = {}) {
  return mount(CrewProgress, {
    props: {
      nodeStates: options.states ?? idle(),
      nodeVisits: options.visits ?? {},
      descriptor: options.descriptor ?? MOCK_GRAPH,
      active: options.active ?? true,
    },
  })
}

/** Re-props an already mounted strip, so watchers see a real transition. */
async function advance(
  wrapper: VueWrapper,
  states: Record<string, NodeRunState>,
  visits: Record<string, number> = {},
) {
  await wrapper.setProps({ nodeStates: states, nodeVisits: visits })
  await nextTick()
}

describe('the crew is drawn at all', () => {
  it('renders the boat and three rowers on an active run', () => {
    const wrapper = mountCrew()
    expect(wrapper.find('.crew-progress').exists()).toBe(true)
    expect(wrapper.findAll('.crew-rower')).toHaveLength(3)
    expect(wrapper.findAll('.crew-oar')).toHaveLength(3)
  })

  it('draws one stage marker per declared stage', () => {
    const wrapper = mountCrew()
    expect(wrapper.findAll('.crew-stage')).toHaveLength(7)
  })

  it('stays away from a topology it cannot narrate', () => {
    // The composable is workflow-generic and could be showing brief-flow, whose
    // seven nodes share not one id with the stages. No crew is the honest
    // answer there; a strip reading "0/7" over a running graph is not.
    const foreign: GraphDescriptor = {
      ...MOCK_GRAPH,
      nodes: [{ ...MOCK_GRAPH.nodes[0], id: 'some_other_flow_node' }],
    }
    expect(mountCrew({ descriptor: foreign }).find('.crew-progress').exists()).toBe(false)
  })
})

describe('the oars name their branches', () => {
  const fanOut = (over: Record<string, NodeRunState> = {}) => {
    const states = idle()
    states.scope_idea = 'completed'
    states.confirm_scope = 'completed'
    states.research_market = 'running'
    states.research_sentiment = 'running'
    states.research_feasibility = 'running'
    return { ...states, ...over }
  }

  it('captions the three rowers only at the fan-out', () => {
    const wrapper = mountCrew({ states: fanOut() })
    const names = wrapper.find('[data-testid="crew-oar-names"]')
    expect(names.exists()).toBe(true)
    // Per-span, not the concatenated text: the caption must map name to branch
    // in order, and `.text()` would pass on three names in any arrangement.
    expect(names.findAll('span').map((s) => [s.attributes('data-branch'), s.text()])).toEqual([
      ['research_market', 'Market'],
      ['research_sentiment', 'Signal'],
      ['research_feasibility', 'Build'],
    ])
  })

  it('draws no captions off the fan-out, where the crew pulls one task', () => {
    const states = idle()
    states.scope_idea = 'running'
    const wrapper = mountCrew({ states })
    expect(wrapper.find('[data-testid="crew-oar-names"]').exists()).toBe(false)
  })

  it('rests the oar of a branch that is home while its siblings pull', () => {
    const wrapper = mountCrew({
      states: fanOut({ research_sentiment: 'completed' }),
    })
    const pulling = wrapper.findAll('.crew-oar').map((o) => o.classes('is-pulling'))
    expect(pulling).toEqual([true, false, true])
  })

  it('names the branches still pulling in the headline', () => {
    const wrapper = mountCrew({
      states: fanOut({ research_market: 'completed', research_feasibility: 'completed' }),
    })
    expect(wrapper.find('.crew-headline').text()).toBe('Research - Signal still pulling')
  })

  it('falls back to a count once every branch is pulling', () => {
    // With nothing home yet, naming all three is noise: the count is shorter
    // and says the same thing.
    const wrapper = mountCrew({ states: fanOut() })
    expect(wrapper.find('.crew-headline').text()).toBe('Research - 0 of 3 branches home')
  })

  it('lights each pip from its own branch, not from a running total', () => {
    const wrapper = mountCrew({
      states: fanOut({ research_feasibility: 'completed' }),
    })
    const pips = wrapper.find('[data-testid="crew-branch-pips"]').findAll('i')
    expect(pips.map((p) => p.attributes('data-branch'))).toEqual([
      'research_market',
      'research_sentiment',
      'research_feasibility',
    ])
    expect(pips.map((p) => p.classes().find((c) => c.startsWith('is-')))).toEqual([
      'is-running',
      'is-running',
      'is-completed',
    ])
  })
})

describe('the loop is visible', () => {
  const revised = () => {
    const states = idle()
    states.scope_idea = 'completed'
    states.confirm_scope = 'completed'
    states.revise_scope = 'running'
    return states
  }

  it('says nothing about laps on a straight run', () => {
    const states = idle()
    states.scope_idea = 'running'
    const wrapper = mountCrew({ states, visits: { scope_idea: 1 } })
    expect(wrapper.find('[data-testid="crew-lap"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="crew-stage-lap"]').exists()).toBe(false)
  })

  it('badges the stage that has run more than once', () => {
    const wrapper = mountCrew({
      states: revised(),
      visits: { scope_idea: 1, revise_scope: 1 },
    })
    const badge = wrapper.find('[data-testid="crew-stage-lap"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('×2')
    expect(badge.attributes('title')).toBe('Scope has run 2 times')
  })

  it('counts further revisions', () => {
    const wrapper = mountCrew({
      states: revised(),
      visits: { scope_idea: 1, revise_scope: 3 },
    })
    expect(wrapper.find('[data-testid="crew-stage-lap"]').text()).toBe('×4')
  })

  it('badges only the stage that looped', () => {
    const wrapper = mountCrew({
      states: revised(),
      visits: { scope_idea: 1, revise_scope: 1 },
    })
    expect(wrapper.findAll('[data-testid="crew-stage-lap"]')).toHaveLength(1)
  })

  it('says which pass the crew is on beside the headline', () => {
    const wrapper = mountCrew({
      states: revised(),
      visits: { scope_idea: 1, revise_scope: 1 },
    })
    expect(wrapper.find('[data-testid="crew-lap"]').text()).toContain('pass 2')
  })
})

describe('the row-back announces itself', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  const atGate = () => {
    const states = idle()
    states.scope_idea = 'completed'
    states.confirm_scope = 'waiting'
    return states
  }
  const sentBack = () => {
    const states = idle()
    states.scope_idea = 'completed'
    states.confirm_scope = 'completed'
    states.revise_scope = 'running'
    return states
  }

  it('latches a message when a stage starts a second pass', async () => {
    const wrapper = mountCrew({ states: atGate(), visits: { scope_idea: 1 } })
    expect(wrapper.find('.crew-progress').classes()).not.toContain('is-returning')

    await advance(wrapper, sentBack(), { scope_idea: 1, revise_scope: 1 })

    expect(wrapper.find('.crew-progress').classes()).toContain('is-returning')
    expect(wrapper.find('[data-testid="crew-lap"]').text()).toContain('sent back for a revision')
  })

  it('stays quiet when a stage is merely entered for the first time', async () => {
    // Lap 0 -> 1 is arrival, not a return. Announcing it would fire on every
    // stage of every run.
    const wrapper = mountCrew({ states: idle(), visits: {} })
    const running = idle()
    running.scope_idea = 'running'
    await advance(wrapper, running, { scope_idea: 1 })
    expect(wrapper.find('.crew-progress').classes()).not.toContain('is-returning')
  })

  it('does not fire when a gate answer starts that stage\'s router', async () => {
    // The bug this trigger was rewritten for. Answering a gate starts
    // `route_scope`, which shares the gate's stage; keyed on the boat's
    // position the strip announced a revision on a run that never revised.
    const wrapper = mountCrew({ states: atGate(), visits: { scope_idea: 1 } })
    const routing = idle()
    routing.scope_idea = 'completed'
    routing.confirm_scope = 'completed'
    routing.route_scope = 'running'
    await advance(wrapper, routing, { scope_idea: 1, confirm_scope: 1, route_scope: 1 })
    expect(wrapper.find('.crew-progress').classes()).not.toContain('is-returning')
    expect(wrapper.find('[data-testid="crew-lap"]').exists()).toBe(false)
  })

  it('releases the latch and falls back to the pass number', async () => {
    const wrapper = mountCrew({ states: atGate(), visits: { scope_idea: 1 } })
    await advance(wrapper, sentBack(), { scope_idea: 1, revise_scope: 1 })

    vi.advanceTimersByTime(6001)
    await nextTick()

    expect(wrapper.find('.crew-progress').classes()).not.toContain('is-returning')
    // The lap itself is durable; only the event message expires.
    expect(wrapper.find('[data-testid="crew-lap"]').text()).toContain('pass 2')
  })

  it('does not fire when the boat moves forward', async () => {
    const wrapper = mountCrew({ states: atGate(), visits: { scope_idea: 1 } })
    const forward = idle()
    forward.scope_idea = 'completed'
    forward.confirm_scope = 'completed'
    forward.research_market = 'running'
    await advance(wrapper, forward, { scope_idea: 1, research_market: 1 })
    expect(wrapper.find('.crew-progress').classes()).not.toContain('is-returning')
  })

  it('fires again on a second revision of the same stage', async () => {
    const wrapper = mountCrew({ states: atGate(), visits: { scope_idea: 1 } })
    await advance(wrapper, sentBack(), { scope_idea: 1, revise_scope: 1 })
    vi.advanceTimersByTime(6001)
    await nextTick()
    expect(wrapper.find('.crew-progress').classes()).not.toContain('is-returning')

    await advance(wrapper, sentBack(), { scope_idea: 1, revise_scope: 2 })
    expect(wrapper.find('.crew-progress').classes()).toContain('is-returning')
  })

  it('retires the message once the crew moves on', async () => {
    // A live capture showed "Review - waiting for you / SENT BACK FOR A
    // REVISION" at the verdict gate, two stages past the revision it described.
    // The durable record of the loop is the stage's own badge; this line is the
    // event, and an event stops being news.
    const wrapper = mountCrew({ states: atGate(), visits: { scope_idea: 1 } })
    await advance(wrapper, sentBack(), { scope_idea: 1, revise_scope: 1 })
    expect(wrapper.find('.crew-progress').classes()).toContain('is-returning')

    const onward = idle()
    onward.scope_idea = 'completed'
    onward.confirm_scope = 'completed'
    onward.revise_scope = 'completed'
    onward.research_market = 'running'
    await advance(wrapper, onward, {
      scope_idea: 1,
      revise_scope: 1,
      confirm_scope: 2,
      research_market: 1,
    })

    expect(wrapper.find('.crew-progress').classes()).not.toContain('is-returning')
    // The lap survives; only the event message goes.
    expect(wrapper.findAll('[data-testid="crew-stage-lap"]').length).toBeGreaterThan(0)
  })

  it('does not inherit a row-back into the next run', async () => {
    const wrapper = mountCrew({ states: atGate(), visits: { scope_idea: 1 } })
    await advance(wrapper, sentBack(), { scope_idea: 1, revise_scope: 1 })
    expect(wrapper.find('.crew-progress').classes()).toContain('is-returning')

    await wrapper.setProps({ active: false })
    await nextTick()

    expect(wrapper.find('.crew-progress').classes()).not.toContain('is-returning')
  })
})

describe('the strip narrates itself to a screen reader', () => {
  it('carries the stage, the position and the count', () => {
    const states = idle()
    states.scope_idea = 'running'
    const label = mountCrew({ states }).find('.crew-progress').attributes('aria-label')
    expect(label).toContain('Scope')
    expect(label).toContain('Stage 1 of 7')
    expect(label).toContain('0 complete')
  })

  it('carries the lap, which is the one thing a listener cannot see', () => {
    const states = idle()
    states.scope_idea = 'completed'
    states.revise_scope = 'running'
    const label = mountCrew({ states, visits: { scope_idea: 1, revise_scope: 1 } })
      .find('.crew-progress')
      .attributes('aria-label')
    expect(label).toContain('pass 2')
  })

  it('says a gate is waiting for a human', () => {
    const states = idle()
    states.scope_idea = 'completed'
    states.confirm_scope = 'waiting'
    const wrapper = mountCrew({ states })
    expect(wrapper.find('.crew-headline').text()).toBe('Confirm - waiting for you')
    expect(wrapper.find('.crew-progress').classes()).toContain('is-stalled')
  })

  it('says a stage failed, and an error outranks a running sibling', () => {
    const states = idle()
    states.research_market = 'running'
    states.research_sentiment = 'error'
    const wrapper = mountCrew({ states })
    expect(wrapper.find('.crew-headline').text()).toBe('Research - failed')
    expect(wrapper.find('.crew-progress').classes()).toContain('is-foundered')
  })
})
