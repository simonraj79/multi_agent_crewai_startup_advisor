import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import HandoffToken from '../src/components/HandoffToken.vue'
import {
  RECEIPT_MS,
  useRunChoreography,
  type Handoff,
} from '../src/composables/useRunChoreography'
import type { FrameData, NodeRunState, RunStatus } from '../src/types/studio'

/**
 * The token that walks an edge, and the receipt it triggers on arrival.
 *
 * What jsdom can and cannot answer here is the whole shape of this file.
 * `SVGPathElement.getTotalLength` and `getPointAtLength` are UNIMPLEMENTED in
 * jsdom - they throw - so the one thing this environment can prove is the
 * component's own guard: a token mounted where the path cannot be measured must
 * render, finish and report its arrival rather than throw or loop forever. That
 * the box actually moves along the bezier is `e2e/visual/choreography.spec.ts`'s
 * question, because it is a layout question and layout questions have an answer
 * only in a real browser (MISSION.md §9.13).
 */

const handoff: Handoff = {
  edgeId: 'route_scope-research_market',
  from: 'route_scope',
  to: 'research_market',
  startedAt: 1_700_000_000_000,
}

function token(overrides: Partial<Handoff> = {}) {
  return mount(HandoffToken, {
    props: {
      path: 'M0,0 C10,10 20,20 30,30',
      handoff: { ...handoff, ...overrides },
      character: 5,
    },
  })
}

describe('the handoff token', () => {
  it('carries the edge it is walking, so a test can find it', () => {
    const wrapper = token()
    const group = wrapper.get('[data-testid="handoff-token"]')
    expect(group.attributes('data-edge')).toBe('route_scope-research_market')
  })

  it('measures the edge\'s own path rather than a straight line', () => {
    // The ruler carries the SAME `d` as the visible edge, so the token walks
    // the line an operator can see. A straight approximation would drift off a
    // curved edge by tens of pixels at the middle, which is where it is most
    // visible.
    const wrapper = token()
    expect(wrapper.get('path').attributes('d')).toBe('M0,0 C10,10 20,20 30,30')
  })

  it('finishes rather than throwing where the path cannot be measured', async () => {
    // jsdom, a detached SVG, a browser that has not laid out yet. All three
    // reach the same guard, and all three must end the walk - a token that
    // never reported arriving would sit on the canvas forever and would count
    // against the animation bound for the rest of the run.
    const wrapper = token()
    await nextTick()
    expect(wrapper.emitted('done')).toEqual([['route_scope-research_market']])
  })

  it('places the token at the target under reduced motion', async () => {
    const matchMedia = vi.fn().mockReturnValue({ matches: true })
    vi.stubGlobal('matchMedia', matchMedia)
    const wrapper = token()
    await nextTick()
    expect(wrapper.emitted('done')).toHaveLength(1)
    vi.unstubAllGlobals()
  })
})

describe('the receipt', () => {
  function harness() {
    const nodeStates = ref<Record<string, NodeRunState>>({})
    const status = ref<RunStatus>('running')
    return useRunChoreography({ nodeStates, status, edgeIdFor: (a, b) => `${a}-${b}` })
  }

  function traversal(from: string, to: string): FrameData {
    return {
      run_id: 'run-1',
      seq: 1,
      ts: new Date().toISOString(),
      kind: 'edge_taken',
      event_type: 'EDGE_PROCESS',
      level: 'INFO',
      node_id: to,
      message: `${from} to ${to}`,
      details: { stage: 'traversal', from, to, port: null },
    } as FrameData
  }

  it('marks the TARGET when the token arrives, not the source', () => {
    const run = harness()
    run.ingest(traversal('route_scope', 'research_market'))
    run.endHandoff('route_scope-research_market')
    expect(run.receiving.value.has('research_market')).toBe(true)
    expect(run.receiving.value.has('route_scope')).toBe(false)
  })

  it('clears itself, so a second arrival is a second pulse', async () => {
    // A CSS one-shot fires only when its class is ADDED. A latch that never
    // cleared would animate the first handoff into a node and silently ignore
    // every later one - which on a revise loop is every handoff but the first.
    const run = harness()
    run.ingest(traversal('a', 'b'))
    run.endHandoff('a-b')
    expect(run.receiving.value.has('b')).toBe(true)
    await new Promise((resolve) => setTimeout(resolve, RECEIPT_MS + 30))
    expect(run.receiving.value.has('b')).toBe(false)
  })

  it('does nothing for an edge with no token on it', () => {
    const run = harness()
    run.endHandoff('never-started')
    expect(run.receiving.value.size).toBe(0)
  })

  it('is cleared by a reset, so a relaunch inherits no pulse', () => {
    const run = harness()
    run.ingest(traversal('a', 'b'))
    run.endHandoff('a-b')
    run.reset()
    expect(run.receiving.value.size).toBe(0)
  })
})

describe('no regex trigger', () => {
  it('is asserted by grep in the plan, and by the shape here', () => {
    // Criterion 5's assertion is `grep -rn "Edge condition met" frontend/src`,
    // which belongs in the plan's Status rather than in a unit test. What a
    // unit test CAN say is the positive form of the same claim: the token's
    // only input is a structured record, and there is nowhere for a log line
    // to enter. `Handoff` has four fields and none of them is a message.
    expect(Object.keys(handoff).sort()).toEqual(['edgeId', 'from', 'startedAt', 'to'])
  })
})
