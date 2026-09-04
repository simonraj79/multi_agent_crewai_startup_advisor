import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { App } from 'vue'
import WorkflowNode from '../src/components/WorkflowNode.vue'
import { useValidatorRun, type StudioNodeData } from '../src/composables/useValidatorRun'
import { FakeStudioApi, flush, frameFactory, withSetup, zeroUsage } from './helpers'

type ValidatorRun = ReturnType<typeof useValidatorRun>

/**
 * "Is this thing working, or has it hung?"
 *
 * A real operator abandoned a healthy run as stuck after six minutes. Nothing
 * was wrong: Firecrawl was scraping and the backend was streaming the whole
 * time. The console simply had no way to say so - every animation on a running
 * node is an infinite CSS loop, identical at second 5 and at minute 6, so it
 * proves an animation is playing and never that work is progressing.
 *
 * The backend had been putting the literal query string on the `before` tool
 * frame all along, for exactly this purpose, and NOTHING in `frontend/src`
 * read the field. These tests pin that it now does, and that the two ways the
 * indicator could lie - never appearing, and never going away - are both
 * closed.
 */
describe('node liveness', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App
  let build: ReturnType<typeof frameFactory>

  const toolBefore = (nodeId: string, tool: string, query?: string) =>
    build('tool', {
      event_type: 'TOOL_CALL',
      node_id: nodeId,
      message: `${tool} started`,
      details: { stage: 'before', tool, ...(query === undefined ? {} : { query }) },
    })

  const toolAfter = (nodeId: string, tool: string) =>
    build('tool', {
      event_type: 'TOOL_CALL',
      node_id: nodeId,
      message: `${tool} completed`,
      details: { stage: 'after', tool, tool_status: 'ok', result_count: 3 },
    })

  beforeEach(async () => {
    localStorage.clear()
    api = new FakeStudioApi()
    build = frameFactory()
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
  })

  afterEach(() => {
    app.unmount()
  })

  it('records the tool and its query while a call is in flight', async () => {
    api.emit(toolBefore('research_market', 'research_market_landscape', 'figma to react'))
    await flush()

    const call = run.nodeActiveCall.research_market
    expect(call).not.toBeNull()
    expect(call?.label).toBe('research_market_landscape')
    expect(call?.query).toBe('figma to react')
    expect(call?.kind).toBe('tool')
  })

  it('clears it when the call completes', async () => {
    api.emit(toolBefore('research_market', 'research_market_landscape', 'q'))
    await flush()
    expect(run.nodeActiveCall.research_market).not.toBeNull()

    api.emit(toolAfter('research_market', 'research_market_landscape'))
    await flush()
    expect(run.nodeActiveCall.research_market).toBeNull()
  })

  it('clears it when the node ends, even without a completion frame', async () => {
    // Belt and braces. A dropped or out-of-order `after` frame would otherwise
    // leave a timer counting up forever on a finished node - a worse lie than
    // showing nothing at all.
    api.emit(toolBefore('research_market', 'research_market_landscape', 'q'))
    await flush()
    api.emit(build('node_state', { event_type: 'NODE_END', node_id: 'research_market' }))
    await flush()
    expect(run.nodeActiveCall.research_market).toBeNull()
  })

  it('clears it when the node errors', async () => {
    api.emit(toolBefore('research_market', 'research_market_landscape', 'q'))
    await flush()
    api.emit(
      build('node_state', {
        event_type: 'NODE_END',
        node_id: 'research_market',
        level: 'ERROR',
      }),
    )
    await flush()
    expect(run.nodeActiveCall.research_market).toBeNull()
  })

  it('tracks each branch independently', async () => {
    // The three branches are concurrent, so one finishing must not silence the
    // others - the fan-out is exactly when an operator most needs to know which
    // branch is still pulling.
    api.emit(toolBefore('research_market', 'research_market_landscape', 'market q'))
    api.emit(toolBefore('research_sentiment', 'analyze_community_sentiment', 'hn q'))
    await flush()
    api.emit(toolAfter('research_sentiment', 'analyze_community_sentiment'))
    await flush()

    expect(run.nodeActiveCall.research_sentiment).toBeNull()
    expect(run.nodeActiveCall.research_market?.query).toBe('market q')
  })

  it('survives a call with no query rather than showing an empty one', async () => {
    api.emit(toolBefore('research_market', 'research_market_landscape'))
    await flush()
    expect(run.nodeActiveCall.research_market).not.toBeNull()
    expect(run.nodeActiveCall.research_market?.query).toBeUndefined()
  })

  it('is cleared by a relaunch, so a stale panel cannot survive into a new run', async () => {
    // The run has to END first: `launch()` opens with `if (!canLaunch) return`,
    // so relaunching mid-run is a no-op and would prove nothing. The failure
    // this guards is a branch that errored while a call was in flight leaving
    // its "in flight" panel on screen, ticking, over the next run.
    api.emit(toolBefore('research_market', 'research_market_landscape', 'q'))
    await flush()
    expect(run.nodeActiveCall.research_market).not.toBeNull()

    api.emit(
      build('run_state', {
        event_type: 'WORKFLOW_END',
        node_id: 'workflow',
        details: { status: 'completed', result: {} },
      }),
    )
    await flush()

    await run.launch()
    await flush()
    expect(run.nodeActiveCall.research_market).toBeNull()
  })
})

describe('node card liveness rendering', () => {
  function nodeData(overrides: Partial<StudioNodeData> = {}): StudioNodeData {
    return {
      label: 'Market Analyst',
      eyebrow: '02A - MARKET',
      description: 'Run the market branch.',
      kind: 'agent',
      state: 'running',
      usage: zeroUsage(),
      frameCount: 0,
      visits: 1,
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
    mount(WorkflowNode, { props: { data }, global: { stubs: { Handle: true } } })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows nothing when no call is in flight', () => {
    const wrapper = mountNode(nodeData())
    expect(wrapper.find('[data-testid="node-active-call"]').exists()).toBe(false)
  })

  it('shows the tool and the query when one is', () => {
    const wrapper = mountNode(
      nodeData({
        activeCall: {
          label: 'research_market_landscape',
          kind: 'tool',
          query: 'figma to react code generation market',
          startedAt: Date.now(),
        },
      }),
    )
    const panel = wrapper.find('[data-testid="node-active-call"]')
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain('research_market_landscape')
    expect(panel.text()).toContain('figma to react code generation market')
  })

  it('counts elapsed seconds upward', async () => {
    // The load-bearing assertion in this file. A changing digit is the only
    // honest progress an agent can show - there is no denominator for a bar,
    // because the agent does not know how far through it is either.
    vi.useFakeTimers()
    const startedAt = Date.now()
    const wrapper = mountNode(
      nodeData({ activeCall: { label: 'tool', kind: 'tool', startedAt } }),
    )
    const read = () => wrapper.find('[data-testid="node-active-elapsed"]').text()
    const first = read()

    await vi.advanceTimersByTimeAsync(3_000)
    await wrapper.vm.$nextTick()
    expect(read()).not.toBe(first)
  })

  it('withholds the duration hint until the wait is actually long', async () => {
    // Saying "this can take a while" about something that finishes in four
    // seconds is noise, and noise is how a hint stops being read.
    vi.useFakeTimers()
    const wrapper = mountNode(
      nodeData({ activeCall: { label: 'tool', kind: 'tool', startedAt: Date.now() } }),
    )
    expect(wrapper.find('[data-testid="node-active-hint"]').exists()).toBe(false)

    await vi.advanceTimersByTimeAsync(16_000)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="node-active-hint"]').exists()).toBe(true)
  })

  it('stops its interval when the call ends', async () => {
    vi.useFakeTimers()
    const clearSpy = vi.spyOn(globalThis, 'clearInterval')
    const wrapper = mountNode(
      nodeData({ activeCall: { label: 'tool', kind: 'tool', startedAt: Date.now() } }),
    )
    await wrapper.setProps({ data: nodeData({ activeCall: null }) })
    expect(clearSpy).toHaveBeenCalled()
    expect(wrapper.find('[data-testid="node-active-call"]').exists()).toBe(false)
  })
})
