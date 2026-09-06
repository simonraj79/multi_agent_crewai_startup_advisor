import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import StudioView from '../src/views/StudioView.vue'
import { workflowIdentity } from '../src/composables/useValidatorRun'
import { readRunHandoff } from '../src/data/builderRunHandoff'
import { MOCK_GRAPH } from '../src/data/mockGraph'
import { flush } from './helpers'
import builderDescriptor from './fixtures/builderGraphDescriptor.json'
import type { GraphDescriptor } from '../src/types/studio'

/**
 * The console says whose workflow it is showing (item 55, ROUND-2 R1).
 *
 * The defect was not cosmetic. Every identity surface - breadcrumb, tab title,
 * canvas kicker and heading, the WORKFLOW well over the Launch button, the
 * input label and the report's kicker - keyed on the `builder-run-handoff`
 * record, and only the publish dialog's "Run it" writes one. A run reached by
 * the test panel, by the Run switch or by a restored pointer therefore drew a
 * graph somebody else wrote under the built-in validator's name, over an input
 * box labelled `IDEA TO VALIDATE`, beside a Launch button the well told them
 * was about `Idea Validator`.
 *
 * The fixture is the REAL descriptor, not a hand-written stand-in: it is
 * `GET /api/workflows/ug_a96d869d/graph` from the synthetic backend on
 * 2026-09-06, saved verbatim, for the `News to social post` template published
 * through the product's own path. That matters because both rules this function
 * applies are facts about what the SERVER puts on a descriptor, and a fixture
 * somebody typed could agree with the code and disagree with the service.
 */

const builder = builderDescriptor as unknown as GraphDescriptor
const BUILDER_ID = 'ug_a96d869d'

describe('workflowIdentity: the run names its own workflow', () => {
  it('reads the built-in validator off its own descriptor', () => {
    const identity = workflowIdentity(MOCK_GRAPH, 'idea-validator', 'idea')
    expect(identity.authored).toBe(false)
    expect(identity.name).toBe('Idea Validator')
    expect(identity.kicker).toBe('RUN — BUILT IN')
    expect(identity.title).toBe('Evidence pipeline')
    expect(identity.inputLabel).toBe('IDEA TO VALIDATE')
  })

  it('reads an authored graph off its own descriptor, with NO handoff', () => {
    const identity = workflowIdentity(builder, BUILDER_ID, 'subject')
    expect(identity.authored).toBe(true)
    expect(identity.name).toBe('News to social post')
    expect(identity.kicker).toBe('RUN — YOUR WORKFLOW')
    expect(identity.title).toBe('News to social post')
    // The author typed `Subject` on the input card; the server put it on the
    // descriptor node's `label`. Nothing here derives it from `inputs.subject`.
    expect(identity.inputLabel).toBe('SUBJECT')
  })

  /**
   * The two facts the whole function rests on, asserted against the fixture
   * rather than against the code, so a server change that moved either one
   * fails here instead of on screen.
   */
  it('rests on a document id and an input node the SERVER really sends', () => {
    expect(builder.id).toMatch(/^ug_[0-9a-f]{8}$/)
    expect(builder.start_nodes).toEqual(['subject'])
    const input = builder.nodes.find((node) => node.id === 'subject')
    expect(input?.kind).toBe('start')
    expect(input?.label).toBe('Subject')
    // And the validator carries no node of that kind at all, which is what
    // makes `kind === 'start'` a total test for "the author drew an input".
    expect(MOCK_GRAPH.nodes.some((node) => node.kind === 'start')).toBe(false)
  })

  it('never lends the validator its name to a graph whose descriptor has not arrived', () => {
    // The first tick of a restored builder run: `descriptor` is still
    // MOCK_GRAPH and `workflowId` already names the document.
    const identity = workflowIdentity(MOCK_GRAPH, BUILDER_ID, 'subject')
    expect(identity.authored).toBe(true)
    expect(identity.name).toBe('')
    expect(identity.kicker).toBe('RUN — YOUR WORKFLOW')
    // The field name is the only thing known at that moment, and it is used
    // rather than the validator's label.
    expect(identity.inputLabel).toBe('SUBJECT TO RUN')
  })

  it('uses the handoff name ONLY as the provisional one, never over the served one', () => {
    const early = workflowIdentity(MOCK_GRAPH, BUILDER_ID, 'subject', 'News to social post')
    expect(early.name).toBe('News to social post')

    // A stale handoff naming the graph something else loses to the descriptor.
    const served = workflowIdentity(builder, BUILDER_ID, 'subject', 'An older name')
    expect(served.name).toBe('News to social post')
  })

  it('says nothing about a graph the server refused, and does not fall back to the validator', () => {
    const refused: GraphDescriptor =
      { id: BUILDER_ID, name: '', version: 'unavailable', start_nodes: [], nodes: [], edges: [] }
    const identity = workflowIdentity(refused, BUILDER_ID, 'subject')
    expect(identity.authored).toBe(true)
    expect(identity.name).toBe('')
    expect(identity.inputLabel).toBe('SUBJECT TO RUN')
  })

  it('turns an underscored field into words when there is no input node to read', () => {
    const identity = workflowIdentity(MOCK_GRAPH, BUILDER_ID, 'source_material')
    expect(identity.inputLabel).toBe('SOURCE MATERIAL TO RUN')
  })

  it('does not mistake the validator\'s first agent for an input card', () => {
    // `start_nodes[0]` on the validator is `scope_idea`, an AGENT. Reading the
    // label off `start_nodes` alone would have put `SCOPER` over the box.
    expect(MOCK_GRAPH.start_nodes.length).toBeGreaterThan(0)
    expect(workflowIdentity(MOCK_GRAPH, 'idea-validator', 'idea').inputLabel).toBe('IDEA TO VALIDATE')
  })

  it('keeps the other built-in workflow out of the validator\'s subtitle', () => {
    const brief: GraphDescriptor =
      { id: 'brief-flow', name: 'Brief Flow', version: 'v1', start_nodes: [], nodes: [], edges: [] }
    const identity = workflowIdentity(brief, 'brief-flow', 'topic')
    expect(identity.authored).toBe(false)
    expect(identity.kicker).toBe('RUN — BUILT IN')
    // Not `Evidence pipeline`, which is the validator's line and nobody else's.
    expect(identity.title).toBe('Brief Flow')
  })
})

/* ────────────────────────────────────────────────────────────────────────────
 * And the same thing in the DOM, because the four surfaces R1 names are
 * rendered by three different components and a pure function proves none of
 * them. The console is mounted twice - once for a run reached WITH a handoff
 * and once for a restored builder run with NO handoff at all - and the second
 * is the arm the old code failed.
 * ────────────────────────────────────────────────────────────────────────── */

const buildRunState = (inputs: Record<string, string>) => ({
  seq: 1,
  run_id: 'run-under-test',
  ts: new Date().toISOString(),
  kind: 'run_state' as const,
  event_type: 'WORKFLOW_START',
  node_id: 'workflow',
  level: 'INFO' as const,
  message: '',
  details: { status: 'running', inputs },
})

vi.mock('../src/services/studioApi', async () => {
  const actual = await vi.importActual<typeof import('../src/services/studioApi')>(
    '../src/services/studioApi',
  )
  return {
    ...actual,
    studioApi: {
      mode: 'live',
      probeFailure: null,
      probeRefusal: null,
      initialize: async () => 'live',
      // The console asks for whichever workflow it is pointed at, and this
      // answers with the real descriptor for that id - which is the whole
      // mechanism under test.
      getGraph: async (id: string) =>
        id === BUILDER_ID ? structuredClone(builder) : structuredClone(MOCK_GRAPH),
      startRun: async () => ({ run_id: 'run-under-test', status: 'queued', graph_version: 'v' }),
      resumeRun: async () => ({ run_id: 'run-under-test', status: 'queued', graph_version: 'v' }),
      getRun: async (id: string) => ({
        run_id: id,
        session_id: 'session-abc',
        workflow_id: BUILDER_ID,
        status: 'running',
        graph_version: 'v',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        inputs: {},
        result: null,
        error: null,
        pending_gate: null,
        usage: {
          promptTokens: 0, completionTokens: 0, totalTokens: 0,
          callCount: 0, costUsd: 0, elapsedMs: 0,
        },
        frames: { count: 1, dropped: 0, first_seq: 1, last_seq: 1 },
      }),
      getFrames: async () => [buildRunState({ subject: 'Vector databases in September' })],
      subscribe: () => () => {},
      replyGate: async () => {},
      cancelRun: async () => {},
      downloadLogs: async () => {},
      listRuns: async () => [],
    },
  }
})

describe('the console renders the workflow it is actually running', () => {
  const USER = { id: 'u1', name: 'Ada', email: 'ada@example.com', image: null }

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    window.matchMedia = ((query: string) => ({
      matches: false, media: query, onchange: null,
      addListener: () => {}, removeListener: () => {},
      addEventListener: () => {}, removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia
  })

  async function mountConsole() {
    const wrapper = mount(StudioView, {
      props: { user: USER, authenticated: true },
      global: { stubs: { VueFlow: true, Background: true, CanvasControls: true } },
    })
    await flush()
    return wrapper
  }

  it('names the built-in validator on every surface when nothing was handed over', async () => {
    const wrapper = await mountConsole()
    expect(wrapper.find('.canvas-kicker').text()).toBe('RUN — BUILT IN')
    expect(wrapper.find('#graph-title').text()).toBe('Evidence pipeline')
    expect(wrapper.find('.breadcrumb-name').text()).toBe('Idea Validator')
    expect(wrapper.find('label[for="idea"]').text()).toBe('IDEA TO VALIDATE')
    expect(wrapper.find('.workflow-title').text()).toBe('Idea Validator')
    wrapper.unmount()
  })

  /**
   * THE ARM THE OLD CODE FAILED. A builder run restored from the pointer, with
   * the handoff absent - which is every run reached by the test panel, by the
   * Run switch or by a reload. Measured before the fix on 2026-09-06: kicker
   * `RUN — BUILT IN`, heading `Evidence pipeline`, crumb and well `Idea
   * Validator`, label `IDEA TO VALIDATE`.
   */
  it('names the AUTHORED workflow on every surface with no handoff at all', async () => {
    localStorage.setItem(
      'u:u1:validator-active-run',
      JSON.stringify({
        version: 1, runId: 'run-under-test', sessionId: 'session-abc',
        workflowId: BUILDER_ID, inputField: 'subject',
      }),
    )
    expect(readRunHandoff('u1')).toBeNull()

    const wrapper = await mountConsole()
    expect(wrapper.find('.canvas-kicker').text()).toBe('RUN — YOUR WORKFLOW')
    expect(wrapper.find('#graph-title').text()).toBe('News to social post')
    expect(wrapper.find('.breadcrumb-name').text()).toBe('News to social post')
    expect(wrapper.find('label[for="idea"]').text()).toBe('SUBJECT')
    expect(wrapper.find('.workflow-title').text()).toBe('News to social post')
    expect(document.title).toBe('News to social post · Crew Studio')
    wrapper.unmount()
  })
})
