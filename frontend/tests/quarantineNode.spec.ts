import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { App } from 'vue'
import WorkflowNode from '../src/components/WorkflowNode.vue'
import { QUARANTINE_NODE_ID, useValidatorRun, type StudioNodeData } from '../src/composables/useValidatorRun'
import { MOCK_GRAPH } from '../src/data/mockGraph'
import { FakeStudioApi, flush, frameFactory, withSetup, zeroUsage } from './helpers'

type ValidatorRun = ReturnType<typeof useValidatorRun>

function nodeData(overrides: Partial<StudioNodeData> = {}): StudioNodeData {
  return {
    label: 'Unattributed',
    eyebrow: 'INSTRUMENTATION',
    description: 'Events that could not be joined to a declared node.',
    kind: 'quarantine',
    state: 'idle',
    usage: zeroUsage(),
    frameCount: 0,
    ...overrides,
  }
}

function mountNode(data: StudioNodeData) {
  return mount(WorkflowNode, {
    props: { data },
    global: { stubs: { Handle: true } },
  })
}

describe('unattributed quarantine node', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App

  beforeEach(async () => {
    localStorage.clear()
    api = new FakeStudioApi()
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
  })

  afterEach(() => {
    app.unmount()
  })

  it('is part of the rendered graph, matching the backend registry', () => {
    const node = run.graphNodes.value.find((candidate) => candidate.id === QUARANTINE_NODE_ID)
    expect(node).toBeDefined()
    expect(node?.data?.kind).toBe('quarantine')
    expect(node?.data?.label).toBe('Unattributed')
    expect(node?.data?.frameCount).toBe(0)
  })

  it('has no edges, because nothing routes into quarantine by design', () => {
    const touching = MOCK_GRAPH.edges.filter(
      (edge) => edge.source === QUARANTINE_NODE_ID || edge.target === QUARANTINE_NODE_ID,
    )
    expect(touching).toEqual([])
  })

  it('counts every frame the backend could not attribute', async () => {
    const build = frameFactory()
    api.emit(build('agent', { event_type: 'AGENT_STEP', node_id: QUARANTINE_NODE_ID }))
    api.emit(build('tool', { event_type: 'TOOL_CALL_STARTED', node_id: QUARANTINE_NODE_ID, details: { stage: 'before', tool: 'mystery' } }))
    api.emit(build('node_state', { event_type: 'NODE_START', node_id: 'scope_idea' }))
    await flush()

    expect(run.quarantinedFrames.value).toBe(2)
    expect(
      run.graphNodes.value.find((node) => node.id === QUARANTINE_NODE_ID)?.data?.frameCount,
    ).toBe(2)
  })

  it('resets the quarantine count on a new run', async () => {
    const build = frameFactory()
    api.emit(build('agent', { event_type: 'AGENT_STEP', node_id: QUARANTINE_NODE_ID }))
    api.emit(build('run_state', { event_type: 'RUN_COMPLETED', details: { status: 'completed' } }))
    await flush()
    expect(run.quarantinedFrames.value).toBe(1)

    await run.launch()
    expect(run.quarantinedFrames.value).toBe(0)
  })

  it('renders quietly while it is empty', () => {
    const wrapper = mountNode(nodeData())
    const article = wrapper.get('article')

    expect(article.classes()).toContain('is-quarantine')
    expect(article.classes()).toContain('is-quiet')
    expect(article.classes()).not.toContain('is-holding')
    expect(article.attributes('aria-label')).toBe('Unattributed, No unattributed frames')
    expect(wrapper.get('[data-testid="quarantine-count"]').text()).toBe('0')
    // No stage state chip: it is a diagnostic, not a step in the pipeline.
    expect(wrapper.text()).not.toContain('Idle')
  })

  it('becomes obvious once frames land in it', () => {
    const wrapper = mountNode(nodeData({ frameCount: 4 }))
    const article = wrapper.get('article')

    expect(article.classes()).toContain('is-holding')
    expect(article.classes()).not.toContain('is-quiet')
    expect(article.attributes('aria-label')).toBe('Unattributed, 4 unattributed frames')
    expect(wrapper.get('[data-testid="quarantine-count"]').text()).toBe('4')
  })

  it('says "frame" in the singular for exactly one', () => {
    const wrapper = mountNode(nodeData({ frameCount: 1 }))
    expect(wrapper.get('article').attributes('aria-label')).toBe('Unattributed, 1 unattributed frame')
  })

  it('leaves ordinary agent nodes untouched', () => {
    const wrapper = mountNode(nodeData({ label: 'Scoper', kind: 'agent', state: 'running', frameCount: 9 }))
    const article = wrapper.get('article')

    expect(article.classes()).toContain('is-agent')
    expect(article.classes()).not.toContain('is-quiet')
    expect(article.classes()).not.toContain('is-holding')
    expect(article.attributes('aria-label')).toBe('Scoper, Running')
    expect(wrapper.find('[data-testid="quarantine-count"]').exists()).toBe(false)
  })
})
