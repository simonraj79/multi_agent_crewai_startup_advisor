import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkflowNode from '../src/components/WorkflowNode.vue'
import type { StudioNodeData } from '../src/composables/useValidatorRun'
import { characterIndex } from '../src/composables/useRunChoreography'
import { MAX_NODE_CARD_ERROR_CHARS } from '../src/data/serverLimits'
import { zeroUsage } from './helpers'

/**
 * The run console's node card, for the four things plan 11 and plan 12 added to
 * it: the character medallion, the idle recede, the failure sentence and the
 * "Re-run from here" control.
 *
 * A jsdom mount asserts STRUCTURE and never asks how wide anything ended up
 * (MISSION.md §9.13), so every question here is a structural one - which
 * elements exist, what they carry, when they are absent. The layout questions
 * are `e2e/visual/choreography.spec.ts`'s, in a real browser, which is the only
 * place they have an answer.
 */

function nodeData(overrides: Partial<StudioNodeData> = {}): StudioNodeData {
  return {
    label: 'Market Analyst',
    eyebrow: '03 - RESEARCH',
    description: 'Firecrawl market research.',
    kind: 'agent',
    state: 'idle',
    usage: zeroUsage(),
    frameCount: 0,
    visits: 0,
    activeCall: null,
    character: 4,
    receded: false,
    errorMessage: '',
    replayed: false,
    receiving: false,
    index: 0,
    landing: false,
    nodeId: 'research_market',
    rerunnable: false,
    ...overrides,
  }
}

function card(overrides: Partial<StudioNodeData> = {}) {
  return mount(WorkflowNode, {
    props: { data: nodeData(overrides) },
    global: { stubs: { Handle: true } },
  })
}

describe('the character medallion', () => {
  it('names the palette entry the composable chose', () => {
    const wrapper = card({ character: 7 })
    const medallion = wrapper.get('[data-testid="node-character"]')
    expect(medallion.attributes('style')).toContain('--character-color: var(--character-7)')
    // `data-character-INDEX`, since the cast landed. `data-character` now means
    // one thing everywhere - the identity SEED, published by `AgentCharacter` -
    // and two attributes of that name meaning a number on the wrapper and a
    // string on the figure inside it is exactly the ambiguity T2.6's E2E reads
    // through (`.workflow-node .pip[data-character]`).
    expect(medallion.attributes('data-character-index')).toBe('7')
    expect(medallion.attributes('data-character')).toBeUndefined()
  })

  it('is on every card, at rest as well as running', () => {
    // Identity is not a run state. A mark that only appears while a node is
    // working cannot be what an operator tracks an agent BY.
    expect(card({ state: 'idle' }).find('[data-testid="node-character"]').exists()).toBe(true)
    expect(card({ state: 'completed' }).find('[data-testid="node-character"]').exists()).toBe(true)
  })

  it('is absent from the quarantine node', () => {
    // Instrumentation, not a cast member. Giving it a face puts it in the story.
    const wrapper = card({ kind: 'quarantine', label: 'Unattributed' })
    expect(wrapper.find('[data-testid="node-character"]').exists()).toBe(false)
  })

  it('pulses on an ARRIVAL rather than on a state', () => {
    // The distinction `endHandoff`'s docstring argues: a state is a proxy for
    // an arrival, and this repository has already shipped one announcement
    // keyed on a proxy that fired on a run that never revised.
    expect(card({ receiving: true }).get('[data-testid="node-character"]').classes())
      .toContain('is-receiving')
    expect(
      card({ receiving: false, state: 'running' }).get('[data-testid="node-character"]').classes(),
    ).not.toContain('is-receiving')
  })

  it('agrees with the pure function the rail and the token also call', () => {
    // The one property the whole design rests on: three call sites, one answer.
    expect(characterIndex('research_market')).toBe(characterIndex('research_market'))
  })
})

describe('the idle recede', () => {
  it('carries the class the composable computed', () => {
    expect(card({ receded: true }).classes()).toContain('is-receded')
    expect(card({ receded: false }).classes()).not.toContain('is-receded')
  })
})

describe('a failed node', () => {
  const failure = 'RateLimitError: the provider refused this call with 429 after three attempts'

  it('shows the message on the card', () => {
    // Criterion 15 / plan 12 D2. It was in the rail and nowhere else, which is
    // not where somebody looking at a red card is looking.
    const wrapper = card({ state: 'error', errorMessage: failure })
    expect(wrapper.get('[data-testid="node-error-message"]').text()).toBe(failure)
  })

  it('clips a long message and keeps the whole of it on hover', () => {
    const long = 'x'.repeat(400)
    const wrapper = card({ state: 'error', errorMessage: long })
    const message = wrapper.get('[data-testid="node-error-message"]')
    expect(message.text().length).toBeLessThanOrEqual(MAX_NODE_CARD_ERROR_CHARS)
    expect(message.text().endsWith('…')).toBe(true)
    expect(message.attributes('title')).toBe(long)
  })

  it('speaks the message in full, because a screen reader has no hover', () => {
    const long = 'y'.repeat(400)
    const wrapper = card({ state: 'error', errorMessage: long })
    expect(wrapper.attributes('aria-label')).toContain(long)
  })

  it('says nothing when the run reported no message', () => {
    const wrapper = card({ state: 'error', errorMessage: '' })
    expect(wrapper.find('[data-testid="node-error-message"]').exists()).toBe(false)
  })

  it('shows no message on a node that did not fail', () => {
    const wrapper = card({ state: 'running', errorMessage: failure })
    expect(wrapper.find('[data-testid="node-error-message"]').exists()).toBe(false)
  })
})

describe('re-run from here', () => {
  it('is offered on a failed node the server would accept a resume for', () => {
    const wrapper = card({ state: 'error', errorMessage: 'boom', rerunnable: true })
    expect(wrapper.find('[data-testid="rerun-from-here"]').exists()).toBe(true)
  })

  it('emits the node id the server needs', () => {
    const wrapper = card({
      state: 'error',
      errorMessage: 'boom',
      rerunnable: true,
      nodeId: 'research_market',
    })
    wrapper.get('[data-testid="rerun-from-here"]').trigger('click')
    expect(wrapper.emitted('rerun')).toEqual([['research_market']])
  })

  it('is absent when the composable said the server would refuse', () => {
    // Mid-run, somebody else's run, a mocked transport - three different
    // refusals, one answer. A control whose only outcome is an error message is
    // worse than no control.
    const wrapper = card({ state: 'error', errorMessage: 'boom', rerunnable: false })
    expect(wrapper.find('[data-testid="rerun-from-here"]').exists()).toBe(false)
  })
})

describe('a replayed node', () => {
  it('says so and dims itself', () => {
    const wrapper = card({ replayed: true, state: 'completed' })
    expect(wrapper.find('[data-testid="node-replayed"]').exists()).toBe(true)
    expect(wrapper.classes()).toContain('is-replayed')
    expect(wrapper.attributes('aria-label')).toContain('replayed from a saved run')
  })

  it('says nothing on an ordinary run', () => {
    expect(card({ replayed: false }).find('[data-testid="node-replayed"]').exists()).toBe(false)
  })
})
