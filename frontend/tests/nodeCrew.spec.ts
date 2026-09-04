import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkflowNode from '../src/components/WorkflowNode.vue'
import type { StudioNodeData } from '../src/composables/useValidatorRun'
import { zeroUsage } from './helpers'

/**
 * The crew on the card, and the lap on the card.
 *
 * The progress strip answers "which STAGE", but a stage is three nodes at the
 * fan-out, and the operator still has to carry a word from the top of the
 * screen back to a card on the canvas. ChatDev stands the agent's character on
 * the active node instead; this is that idea, and these tests pin the two
 * properties that make it worth having - it appears on exactly the running
 * node, and the lap survives without any animation at all.
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
    index: 0,
    landing: false,
    nodeId: 'node',
    rerunnable: false,
    ...overrides,
  }
}

const mountNode = (data: StudioNodeData) =>
  mount(WorkflowNode, {
    props: { data },
    global: { stubs: { Handle: true } },
  })

describe('the crew boards the running node', () => {
  it('appears on a running node', () => {
    const wrapper = mountNode(nodeData({ state: 'running' }))
    expect(wrapper.find('[data-testid="node-crew"]').exists()).toBe(true)
  })

  it('stays off every other state', () => {
    // A marker on every card is furniture, and furniture is exactly what the
    // 5px state chip already was.
    for (const state of ['idle', 'waiting', 'completed', 'error'] as const) {
      const wrapper = mountNode(nodeData({ state }))
      expect(wrapper.find('[data-testid="node-crew"]').exists()).toBe(false)
    }
  })

  it('never boards the quarantine node', () => {
    // Quarantine is instrumentation. Nothing rows there.
    const wrapper = mountNode(nodeData({ kind: 'quarantine', state: 'running' }))
    expect(wrapper.find('[data-testid="node-crew"]').exists()).toBe(false)
  })

  it('boards a running router, because a router is still where the run IS', () => {
    const wrapper = mountNode(nodeData({ kind: 'router', state: 'running' }))
    expect(wrapper.find('[data-testid="node-crew"]').exists()).toBe(true)
  })

  it('draws two rowers, not the strip\'s three', () => {
    // The strip's three ARE the three research branches. Repeating that count
    // on one card would claim a fan-out the node does not have.
    const wrapper = mountNode(nodeData({ state: 'running' }))
    expect(wrapper.findAll('.node-crew-rower')).toHaveLength(2)
    expect(wrapper.findAll('.node-crew-oar')).toHaveLength(2)
  })

  it('is hidden from a screen reader, which already hears "Running"', () => {
    const wrapper = mountNode(nodeData({ state: 'running' }))
    expect(wrapper.find('[data-testid="node-crew"]').attributes('aria-hidden')).toBe('true')
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
    expect(wrapper.find('[data-testid="node-crew"]').exists()).toBe(true)
  })
})
