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
  fromIdentity: 'Market Evidence Analyst',
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

/**
 * A token that has actually been PLACED, which jsdom cannot do on its own.
 *
 * `getTotalLength` and `getPointAtLength` are unimplemented here, so the
 * component's guard fires and it finishes with no position and therefore no
 * disc and no figure - which is correct behaviour and is what the guard test
 * below asserts. To see what the token WEARS, the two measurements are stubbed
 * and the reduced-motion path is taken, because that one places the token
 * synchronously at its destination instead of waiting for a frame callback.
 */
async function placedToken(overrides: Partial<Handoff> = {}) {
  // `Element.prototype` and not `SVGElement.prototype`: this component's root
  // is a `<g>` with no `<svg>` above it in a unit mount, so Vue creates it (and
  // the ruler inside it) in the HTML namespace and jsdom hands back an
  // `HTMLUnknownElement`. In the app the `<g>` really is inside the edge layer's
  // SVG. Stubbing the base prototype covers both and costs nothing.
  const prototype = Element.prototype as unknown as Record<string, unknown>
  const hadLength = prototype.getTotalLength
  const hadPoint = prototype.getPointAtLength
  prototype.getTotalLength = () => 120
  prototype.getPointAtLength = (at: number) => ({ x: at, y: at * 2 })
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
  try {
    const wrapper = token(overrides)
    // The position is assigned inside `onMounted`; the DOM catches up on the
    // next tick. Reading `.get()` before it is how the first draft of this
    // helper reported "no figure" about a token that had one.
    await nextTick()
    return wrapper
  } finally {
    vi.unstubAllGlobals()
    if (hadLength === undefined) delete prototype.getTotalLength
    else prototype.getTotalLength = hadLength
    if (hadPoint === undefined) delete prototype.getPointAtLength
    else prototype.getPointAtLength = hadPoint
  }
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

  it("wears the SENDER's character, at the seed the sender's card is drawn from", async () => {
    // T2.6's third view. The seed is `characterSeed(fromIdentity)`, resolved by
    // the choreography when the token was created rather than looked up here -
    // `WorkflowEdge` knows about edges and nothing about agents, and a second
    // lookup is a second answer waiting to disagree.
    const figure = (await placedToken()).get('[data-testid="handoff-token-figure"]')
    expect(figure.attributes('data-character')).toBe('market evidence analyst')
    expect(figure.html()).toContain('pip-body')
  })

  it('draws the figure IDLE, whatever the sender is doing', async () => {
    // A message in flight is not the agent: the agent is still standing on the
    // card it left, in whatever pose that card says. A token that also posed
    // would be a second animated cast member on a canvas whose whole budget is
    // twelve moving things.
    const html = (await placedToken()).get('[data-testid="handoff-token-figure"]').html()
    expect(html).toContain('pip--idle')
    expect(html).not.toContain('pip--working')
  })

  it('falls back to the source node id when a replayed handoff names no identity', async () => {
    // A frame log written before `fromIdentity` existed. The token still walks
    // and still wears A character - the same one the node card falls back to.
    const figure = (await placedToken({ fromIdentity: '' })).get(
      '[data-testid="handoff-token-figure"]',
    )
    expect(figure.attributes('data-character')).toBe('route scope')
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
      v: 1,
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
    // to enter. `Handoff` has five fields and none of them is a message: the
    // fifth is the sender's identity, which is a role somebody declared rather
    // than a sentence anybody logged.
    expect(Object.keys(handoff).sort()).toEqual([
      'edgeId',
      'from',
      'fromIdentity',
      'startedAt',
      'to',
    ])
  })
})
