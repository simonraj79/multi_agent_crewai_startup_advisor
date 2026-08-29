import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { App } from 'vue'
import WorkflowNode from '../src/components/WorkflowNode.vue'
import { useValidatorRun, type StudioNodeData, type StudioNodeKind } from '../src/composables/useValidatorRun'
import type { GraphDescriptor } from '../src/types/studio'
import { FakeStudioApi, withSetup, zeroUsage } from './helpers'

type ValidatorRun = ReturnType<typeof useValidatorRun>

function nodeData(overrides: Partial<StudioNodeData> = {}): StudioNodeData {
  return {
    label: 'Route scope',
    eyebrow: 'DECISION',
    description: 'Route the structured scope reply without an LLM call.',
    kind: 'router',
    state: 'idle',
    usage: zeroUsage(),
    frameCount: 0,
    ...overrides,
  }
}

function mountNode(data: StudioNodeData) {
  return mount(WorkflowNode, { props: { data }, global: { stubs: { Handle: true } } })
}

const spentUsage = () => ({ ...zeroUsage(), callCount: 3, totalTokens: 4200, costUsd: 0.0182 })

/**
 * PRD §7.0: `route_scope` and `route_verdict` decide where the run goes by
 * reading a structured reply, with zero model calls. Drawing them the same way
 * as the six agents told an operator that cost and latency live somewhere they
 * do not - so they are drawn as plumbing, and the drawing is asserted here.
 */
describe('router nodes are not drawn as agents', () => {
  it('carries the router class and the deterministic marker', () => {
    const wrapper = mountNode(nodeData())
    const article = wrapper.get('article')

    expect(article.classes()).toContain('is-router')
    expect(article.classes()).not.toContain('is-agent')
    expect(wrapper.get('[data-testid="deterministic-tag"]').text()).toBe('0 LLM CALLS')
  })

  it('says what it is to a screen reader', () => {
    const wrapper = mountNode(nodeData({ state: 'running' }))
    expect(wrapper.get('article').attributes('aria-label')).toBe(
      'Route scope, deterministic router, no model call, Running',
    )
  })

  it('stays subordinate: no description body and no usage block', () => {
    const wrapper = mountNode(nodeData({ usage: spentUsage() }))

    expect(wrapper.find('.node-copy p').exists()).toBe(false)
    // Its purpose is still reachable, just not spending a card's worth of room.
    expect(wrapper.get('.node-copy strong').attributes('title')).toBe(
      'Route the structured scope reply without an LLM call.',
    )
    // A router that somehow accrued usage must not display a cost panel - the
    // frames would be misattributed, and the card would assert a lie.
    expect(wrapper.find('.node-usage').exists()).toBe(false)
  })

  it('still reports run state, because the run really does pass through it', () => {
    for (const state of ['running', 'completed', 'error'] as const) {
      const wrapper = mountNode(nodeData({ state }))
      expect(wrapper.get('article').classes()).toContain(`is-${state}`)
      expect(wrapper.get('.node-state').text()).not.toBe('')
    }
  })

  it('leaves agent cards exactly as they were', () => {
    const wrapper = mountNode(
      nodeData({
        label: 'Market Analyst',
        kind: 'agent',
        eyebrow: '02A - MARKET',
        description: 'Run the market branch in a Flow-managed worker thread.',
        model: 'Cheap tier',
        tool: 'Firecrawl',
        state: 'running',
        usage: spentUsage(),
      }),
    )
    const article = wrapper.get('article')

    expect(article.classes()).toContain('is-agent')
    expect(article.classes()).not.toContain('is-router')
    expect(wrapper.find('[data-testid="deterministic-tag"]').exists()).toBe(false)
    expect(wrapper.get('.node-copy p').text()).toBe('Run the market branch in a Flow-managed worker thread.')
    expect(wrapper.get('.node-usage').text()).toContain('4.2K')
    expect(article.attributes('aria-label')).toBe('Market Analyst, Running')
  })

  /** Brief Flow's `retrieve_cached` / `index_content`: real work, no model. */
  it('marks deterministic steps too, without shrinking them', () => {
    const wrapper = mountNode(
      nodeData({ label: 'Index content', kind: 'step', description: 'Write the retrieved pages to the cache.' }),
    )

    expect(wrapper.get('article').classes()).toContain('is-step')
    expect(wrapper.get('[data-testid="deterministic-tag"]').text()).toBe('0 LLM CALLS')
    expect(wrapper.get('.node-copy p').text()).toBe('Write the retrieved pages to the cache.')
  })
})

describe('descriptor kinds map onto canvas kinds', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App

  const kindOf = (id: string): StudioNodeKind | undefined =>
    run.graphNodes.value.find((node) => node.id === id)?.data?.kind

  beforeEach(() => {
    localStorage.clear()
    api = new FakeStudioApi()
  })

  afterEach(() => {
    app.unmount()
  })

  it('keeps the validator routers as routers', async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()

    expect(kindOf('route_scope')).toBe('router')
    expect(kindOf('route_verdict')).toBe('router')
    expect(kindOf('scope_idea')).toBe('agent')
    expect(kindOf('revise_scope')).toBe('agent')
    expect(kindOf('confirm_scope')).toBe('gate')
    expect(kindOf('persist')).toBe('output')
    expect(kindOf('unattributed')).toBe('quarantine')
  })

  /**
   * Brief Flow's descriptor uses CrewAI's own classifications, so the mapping
   * has to survive a graph this UI was not shaped around.
   */
  it('maps a brief-flow style descriptor without inventing agents', async () => {
    const briefGraph: GraphDescriptor = {
      id: 'brief-flow',
      name: 'Brief Flow',
      version: 'test',
      start_nodes: ['retrieve_cached'],
      nodes: [
        { id: 'retrieve_cached', label: 'Retrieve cached', kind: 'start', eyebrow: '01 - CACHE', description: '', position: { x: 0, y: 0 } },
        { id: 'check_cache', label: 'Check cache', kind: 'router', eyebrow: 'ROUTE', description: '', position: { x: 0, y: 1 } },
        { id: 'scrape_web', label: 'Research live web', kind: 'agent', eyebrow: '02 - RESEARCH', description: '', model: 'Cheap tier', position: { x: 0, y: 2 } },
        { id: 'index_content', label: 'Index content', kind: 'step', eyebrow: '03 - INDEX', description: '', position: { x: 0, y: 3 } },
      ],
      edges: [],
    }
    api.graph = briefGraph
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()

    expect(kindOf('check_cache')).toBe('router')
    expect(kindOf('retrieve_cached')).toBe('step')
    expect(kindOf('index_content')).toBe('step')
    expect(kindOf('scrape_web')).toBe('agent')
  })
})
