import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkflowNode, { type NodeCast } from '../src/components/WorkflowNode.vue'
import type { PipState } from '../src/characters/pip'
import type { StudioNodeData } from '../src/composables/useValidatorRun'
import { zeroUsage } from './helpers'

/**
 * The cast on the card, and the lap on the card.
 *
 * WHAT THESE TESTS USED TO PIN, and why they now pin something else. A
 * two-rower boat used to moor above a running card: `.node-crew-rower` x2,
 * `.node-crew-oar` x2, present on exactly the running node. It answered "is
 * this one working" and could not answer "which agent is this", because it was
 * the same two rowers on every card - and it was absent in every other state,
 * which is most of a run. T2.9 replaces it with one `AgentCharacter` in the
 * same 34px slot: a different creature per agent, present in all six poses.
 *
 * The assertions below are the STRONGER form of the old ones rather than fewer
 * of them - "on exactly the running node" becomes "on exactly the nodes that
 * have an agent in them, in every state, wearing the pose the run says", which
 * is a claim the boat could not make. The lap block underneath is untouched.
 */

function nodeData(overrides: Partial<StudioNodeData> = {}): StudioNodeData {
  return {
    label: 'Market Analyst',
    eyebrow: '03 - RESEARCH',
    description: 'Searches the live market for competitors and pricing.',
    kind: 'agent',
    state: 'idle',
    usage: zeroUsage(),
    frameCount: 0,
    visits: 0,
    activeCall: null,
    character: 1,
    receded: false,
    errorMessage: '',
    replayed: false,
    receiving: false,
    index: 0,
    landing: false,
    nodeId: 'node',
    rerunnable: false,
    ...overrides,
  }
}

const mountNode = (data: StudioNodeData, cast?: NodeCast) =>
  mount(WorkflowNode, {
    props: cast ? { data, cast } : { data },
    global: { stubs: { Handle: true } },
  })

/** The one character this card mounts, or an empty wrapper. */
const pipOf = (wrapper: ReturnType<typeof mountNode>) => wrapper.find('.pip')

describe('the cast stands on the card', () => {
  it('is on an agent card in EVERY state, not only while it runs', () => {
    // The boat's real limitation, written as a test. Identity is not a run
    // state: a mark that appears only while a node is working cannot be the
    // thing an operator tracks an agent BY, which is the whole of T2.6.
    for (const state of ['idle', 'running', 'waiting', 'completed', 'error'] as const) {
      const wrapper = mountNode(nodeData({ state }))
      expect(pipOf(wrapper).exists(), `no character on a ${state} agent`).toBe(true)
    }
  })

  it('leaves no rower, oar or hull behind - replaced, not duplicated (T2.9)', () => {
    const html = mountNode(nodeData({ state: 'running' })).html()
    for (const gone of ['node-crew', 'node-rower', 'node-oar', 'node-hull']) {
      expect(html, `${gone} survived the replacement`).not.toContain(gone)
    }
    expect(pipOf(mountNode(nodeData({ state: 'running' }))).exists()).toBe(true)
  })

  it('mounts exactly ONE character, inside the workflow node', () => {
    // T2.6's E2E selects `.vue-flow__node[data-id] .workflow-node .pip` and
    // reads one seed off it. Two would make that query ambiguous and the
    // criterion unanswerable.
    const wrapper = mountNode(nodeData({ state: 'running' }))
    expect(wrapper.findAll('.pip')).toHaveLength(1)
    expect(wrapper.find('.workflow-node .pip').exists()).toBe(true)
    expect(wrapper.find('.node-character .pip').exists()).toBe(true)
  })

  it('never boards the quarantine node', () => {
    // Quarantine is instrumentation. Giving it a face puts it in the story.
    const wrapper = mountNode(nodeData({ kind: 'quarantine', state: 'running' }))
    expect(pipOf(wrapper).exists()).toBe(false)
  })

  it('gives no character to a router, gate, output or step', () => {
    // A router makes no model call - its own card says `0 LLM CALLS` - and a
    // gate is a PERSON being asked for something. A face on either would be
    // the one place this console lied about who did the work. A `step` is what
    // an authored transform compiles to, and an `output` is a file.
    for (const kind of ['router', 'gate', 'output', 'step'] as const) {
      const wrapper = mountNode(nodeData({ kind, state: 'running' }))
      expect(pipOf(wrapper).exists(), `${kind} was given a character`).toBe(false)
      // The lucide medallion is what it keeps instead, in the same slot.
      expect(wrapper.find('[data-testid="node-character"]').exists()).toBe(true)
    }
  })

  it('wears the pose the run resolved, not the one the card could guess', () => {
    // `speaking` and the gate's `blocked` are the two states a card cannot
    // derive: one is bounded by `llm` frames and the other is imposed by a
    // gate downstream. Passing the pose in is what makes them reachable.
    const cast: NodeCast = { identity: 'Market Evidence Analyst', state: 'speaking' }
    const pip = pipOf(mountNode(nodeData({ state: 'running' }), cast))
    expect(pip.attributes('data-state')).toBe('speaking')
    expect(pip.attributes('data-character')).toBe('market evidence analyst')
  })

  it('falls back to the node label when no run has resolved an identity', () => {
    // A design-time card, a mock transport, a spec. It draws A character - the
    // same one the composable's own ladder lands on at rung three - rather
    // than a placeholder, because a system whose strangers look broken
    // punishes the author of every flow it has not seen.
    const pip = pipOf(mountNode(nodeData({ label: 'Market Analyst' })))
    expect(pip.attributes('data-character')).toBe('market analyst')
  })

  it('maps the four poses a card CAN work out for itself', () => {
    const expected: Record<string, PipState> = {
      idle: 'idle',
      running: 'working',
      waiting: 'blocked',
      completed: 'done',
      error: 'blocked-error',
    }
    for (const [state, pose] of Object.entries(expected)) {
      const pip = pipOf(mountNode(nodeData({ state: state as StudioNodeData['state'] })))
      expect(pip.attributes('data-state'), `${state} drew ${pose}`).toBe(pose)
    }
  })

  it('is hidden from a screen reader, which already hears the state in words', () => {
    // The card's own aria-label carries label and state. Two accessible names
    // for one fact is a screen reader saying everything twice.
    const wrapper = mountNode(nodeData({ state: 'running' }))
    expect(wrapper.find('[data-testid="node-character"]').attributes('aria-hidden')).toBe('true')
  })
})

describe('the lap is on the card', () => {
  it('says nothing on a first pass', () => {
    const wrapper = mountNode(nodeData({ state: 'running', visits: 1 }))
    expect(wrapper.find('[data-testid="node-lap"]').exists()).toBe(false)
  })

  it('says nothing on a node that has never run', () => {
    const wrapper = mountNode(nodeData({ visits: 0 }))
    expect(wrapper.find('[data-testid="node-lap"]').exists()).toBe(false)
  })

  it('shows the count from the second pass', () => {
    const wrapper = mountNode(nodeData({ state: 'running', visits: 2 }))
    const chip = wrapper.find('[data-testid="node-lap"]')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('×2')
    expect(chip.attributes('title')).toBe('This node has run 2 times')
  })

  it('persists after the node has finished, which is when it matters most', () => {
    // A completed node with x3 is the record of a revision loop. If the chip
    // only existed while running, the finished graph would look like a straight
    // pass and the loop would leave no trace at all.
    const wrapper = mountNode(nodeData({ state: 'completed', visits: 3 }))
    expect(wrapper.find('[data-testid="node-lap"]').text()).toContain('×3')
  })

  it('shows on a revise node, which is the whole point', () => {
    const wrapper = mountNode(
      nodeData({ label: 'Revise scope', kind: 'agent', state: 'completed', visits: 2 }),
    )
    expect(wrapper.find('[data-testid="node-lap"]').exists()).toBe(true)
  })

  it('never appears on the quarantine node', () => {
    const wrapper = mountNode(nodeData({ kind: 'quarantine', visits: 4 }))
    expect(wrapper.find('[data-testid="node-lap"]').exists()).toBe(false)
  })

  it('tells a screen reader which pass this is', () => {
    const label = mountNode(nodeData({ state: 'running', visits: 2 }))
      .find('.workflow-node')
      .attributes('aria-label')
    expect(label).toBe('Market Analyst, Running, pass 2')
  })

  it('leaves the aria label alone on a first pass', () => {
    const label = mountNode(nodeData({ state: 'running', visits: 1 }))
      .find('.workflow-node')
      .attributes('aria-label')
    expect(label).toBe('Market Analyst, Running')
  })

  it('keeps the router\'s own aria wording and adds the pass', () => {
    const label = mountNode(nodeData({ label: 'Route scope', kind: 'router', state: 'completed', visits: 2 }))
      .find('.workflow-node')
      .attributes('aria-label')
    expect(label).toBe('Route scope, deterministic router, no model call, Completed, pass 2')
  })

  it('sits in the eyebrow row, clear of the usage table', () => {
    // Bottom-right would land on the three-column usage block the moment a node
    // spends anything, which is exactly when a looped node is worth reading.
    const wrapper = mountNode(
      nodeData({
        state: 'completed',
        visits: 2,
        usage: { ...zeroUsage(), callCount: 3, totalTokens: 12_400, costUsd: 0.0182 },
      }),
    )
    expect(wrapper.find('.node-eyebrow-row [data-testid="node-lap"]').exists()).toBe(true)
    expect(wrapper.find('.node-usage').exists()).toBe(true)
  })

  it('tolerates a data object with no visits field at all', () => {
    // `visits` arrives from the composable, but the mock transport and any
    // stale cached snapshot need not carry it. Absent must read as "unknown",
    // never as a chip claiming a lap that did not happen.
    const data = nodeData({ state: 'running' })
    delete (data as Partial<StudioNodeData>).visits
    const wrapper = mountNode(data as StudioNodeData)
    expect(wrapper.find('[data-testid="node-lap"]').exists()).toBe(false)
    expect(wrapper.find('.pip').exists()).toBe(true)
  })
})
