/**
 * Three design findings, pinned so they cannot come back.
 *
 * Each of these was measured in a real browser and was invisible to 988 green
 * unit tests, because every one of them is about what a rendered surface LOOKS
 * like rather than about what it contains. These assertions are the cheapest
 * true statement about each: the crew slot is empty, the summary does not
 * ellipsise its last fact away, and the empty canvas says what to do next.
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BuilderNode, {
  summariseConfig,
  summaryLines,
} from '../src/components/builder/BuilderNode.vue'
import type { BuilderNodeData } from '../src/components/builder/BuilderNode.vue'
import { targetPortsOf } from '../src/composables/useBuilderCanvas'
import { NODE_KINDS, outPortsOf } from '../src/data/nodeKinds'
import { nodeId } from '../src/types/builder'
import type { BuilderNode as DocumentNode } from '../src/types/builder'

const AGENT: DocumentNode = {
  id: nodeId('market_analyst'),
  kind: 'agent',
  label: 'Market analyst',
  position: { x: 0, y: 0 },
  config: {
    tier: 'escalation',
    max_iter: 2,
    guardrail_max_retries: 2,
    prompt_inputs: {},
    agent_id: nodeId('market_analyst'),
    tools: [],
  },
}

const OUTPUT: DocumentNode = {
  id: nodeId('report'),
  kind: 'output',
  label: 'Report',
  position: { x: 0, y: 0 },
  config: { body_key: 'markdown_body', source: null },
}

function nodeData(node: DocumentNode): BuilderNodeData {
  return {
    node,
    index: 3,
    ports: outPortsOf(node),
    acceptsIncoming: NODE_KINDS[node.kind].acceptsIncoming,
    targetPorts: targetPortsOf(node.kind),
    problems: [],
    severity: null,
    joined: false,
    anchor: false,
    loopTarget: false,
    loopIllegal: false,
    connectable: false,
    linkIndex: null,
    linkCurrent: false,
    flashing: false,
    inbound: 0,
    landing: false,
    refused: false,
  }
}

function mountCard(node: DocumentNode) {
  return mount(BuilderNode, {
    props: { id: node.id, data: nodeData(node) },
    global: { stubs: { Handle: true } },
  })
}

describe('the crew slot is reserved and EMPTY (section 5.7)', () => {
  it('renders the 34px seam and nothing inside it', () => {
    const wrapper = mountCard(AGENT)
    const slot = wrapper.find('.node-crew-slot')
    expect(slot.exists()).toBe(true)
    expect(slot.element.children.length).toBe(0)
    expect(slot.attributes('aria-hidden')).toBe('true')
  })

  it('paints no character art at all', () => {
    // Twelve ChatDev sprites stood here until the walk cycle turned out to be
    // unreachable - nothing writes `runState` - and section 5.7 had reserved
    // this slot with "an idle canvas that rows is the ChatDev disco". Only R4
    // was lifted above the spec; this row is what says so.
    const wrapper = mountCard(AGENT)
    expect(wrapper.findAll('img')).toHaveLength(0)
    expect(wrapper.html()).not.toContain('/sprites/')
  })

  it('holds an idle card completely still', () => {
    // No timer, no interval, nothing to clear. The design canvas is STILL.
    const wrapper = mountCard(AGENT)
    expect(wrapper.html()).not.toContain('is-running')
    expect(wrapper.get('article').classes()).toContain('is-idle')
  })
})

describe('the config summary keeps its last fact at 240px', () => {
  it('splits an agent into identity and budget, and leaves every other kind alone', () => {
    // Measured on the shipped validator template at zoom 1.0: five of ten
    // visible cards lost their last token to the ellipsis -
    // `escalation - scoper - 2 iter - no too...`. A truncated fact invites the
    // modal R15 bans, which is the one thing the summary line exists to avoid.
    expect(summaryLines(AGENT)).toEqual(['escalation · market_analyst', '2 iter · no tools'])
    expect(summaryLines(OUTPUT)).toEqual(['markdown_body'])
  })

  it('changes no CONTENT: the whole sentence is still what title carries', () => {
    // Section 5.2 enumerates the summary per kind and this does not re-litigate
    // it. `summariseConfig` is untouched, `builderNode.spec` still asserts every
    // one of the seven strings, and the card's `title` is the full sentence.
    expect(summaryLines(AGENT).join(' · ')).toBe(summariseConfig(AGENT))
    const wrapper = mountCard(AGENT)
    expect(wrapper.get('.builder-summary').attributes('title')).toBe(summariseConfig(AGENT))
  })

  it('renders one span per line, each free to ellipsise on its own', () => {
    expect(mountCard(AGENT).findAll('.builder-summary-line')).toHaveLength(2)
    expect(mountCard(OUTPUT).findAll('.builder-summary-line')).toHaveLength(1)
  })
})
