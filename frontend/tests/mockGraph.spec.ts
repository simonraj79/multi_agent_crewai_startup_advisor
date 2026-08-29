import { describe, expect, it } from 'vitest'
import { buildMockSegments } from '../src/data/mockFrames'
import { MOCK_GRAPH } from '../src/data/mockGraph'
import { QUARANTINE_NODE_ID } from '../src/composables/useValidatorRun'

/**
 * `MOCK_GRAPH` is what the console renders when no backend answers, so it has to
 * be a rehearsal of the live topology rather than an impression of it. It used
 * to use invented ids (`scoper`, `scope_gate`, `market_analyst`) and to omit the
 * routers and the revise paths entirely - self-consistent, and a fiction.
 *
 * The ids below are `ValidatorFlow` method names, taken from
 * `build_graph_descriptor(ValidatorFlow, ...)`. Regenerate with:
 *
 *   ./.venv/Scripts/python.exe -c "from brief_crew.service.graph import \
 *     VALIDATOR_GRAPH; print(VALIDATOR_GRAPH.model_dump_json(indent=2))"
 */
const LIVE_NODE_IDS = [
  'scope_idea',
  'revise_scope',
  'confirm_scope',
  'route_scope',
  'research_market',
  'research_sentiment',
  'research_feasibility',
  'synthesize',
  'revise_verdict',
  'review_verdict',
  'route_verdict',
  'write_report',
  'persist',
  'unattributed',
]

const LIVE_EDGE_IDS = [
  'scope_idea->confirm_scope:',
  'revise_scope->confirm_scope:',
  'confirm_scope->route_scope:',
  'research_market->synthesize:',
  'research_sentiment->synthesize:',
  'research_feasibility->synthesize:',
  'synthesize->review_verdict:',
  'revise_verdict->review_verdict:',
  'review_verdict->route_verdict:',
  'write_report->persist:',
  'route_scope->research_market:scope_approved',
  'route_scope->research_sentiment:scope_approved',
  'route_scope->research_feasibility:scope_approved',
  'route_scope->revise_scope:scope_revise',
  'route_verdict->write_report:verdict_approved',
  'route_verdict->revise_verdict:verdict_revise',
]

const nodeIds = new Set(MOCK_GRAPH.nodes.map((node) => node.id))
const edgeById = new Map(MOCK_GRAPH.edges.map((edge) => [edge.id, edge]))
const node = (id: string) => MOCK_GRAPH.nodes.find((candidate) => candidate.id === id)

function targetsOf(source: string, route?: string): string[] {
  return MOCK_GRAPH.edges
    .filter((edge) => edge.source === source && (route === undefined || edge.route === route))
    .map((edge) => edge.target)
    .sort()
}

describe('mock graph mirrors the live idea-validator descriptor', () => {
  it('declares exactly the live node set, in the live order', () => {
    expect(MOCK_GRAPH.nodes.map((candidate) => candidate.id)).toEqual(LIVE_NODE_IDS)
  })

  it('declares exactly the live edge set', () => {
    expect(MOCK_GRAPH.edges.map((edge) => edge.id)).toEqual(LIVE_EDGE_IDS)
  })

  it('starts where the flow starts', () => {
    expect(MOCK_GRAPH.start_nodes).toEqual(['scope_idea'])
    expect(nodeIds.has(MOCK_GRAPH.start_nodes[0])).toBe(true)
  })

  it('keeps every edge id in the service\'s source->target:route form', () => {
    for (const edge of MOCK_GRAPH.edges) {
      expect(edge.id).toBe(`${edge.source}->${edge.target}:${edge.route ?? ''}`)
    }
  })

  it('connects only declared nodes', () => {
    for (const edge of MOCK_GRAPH.edges) {
      expect(nodeIds.has(edge.source)).toBe(true)
      expect(nodeIds.has(edge.target)).toBe(true)
    }
  })

  /** The property the whole UI is built around: one router event, three branches. */
  it('fans out to all three research branches on one scope_approved route', () => {
    expect(targetsOf('route_scope', 'scope_approved')).toEqual([
      'research_feasibility',
      'research_market',
      'research_sentiment',
    ])
    expect(targetsOf('route_scope', 'scope_revise')).toEqual(['revise_scope'])
  })

  it('joins all three branches before synthesis, as an AND', () => {
    const incoming = MOCK_GRAPH.edges.filter((edge) => edge.target === 'synthesize')
    expect(incoming.map((edge) => edge.source).sort()).toEqual([
      'research_feasibility',
      'research_market',
      'research_sentiment',
    ])
    for (const edge of incoming) expect(edge.condition_type).toBe('AND')
  })

  it('carries both revise loops back to their gates', () => {
    expect(edgeById.get('route_scope->revise_scope:scope_revise')).toBeDefined()
    expect(edgeById.get('revise_scope->confirm_scope:')).toBeDefined()
    expect(edgeById.get('route_verdict->revise_verdict:verdict_revise')).toBeDefined()
    expect(edgeById.get('revise_verdict->review_verdict:')).toBeDefined()
  })

  it('classifies the deterministic routers as routers, not agents', () => {
    for (const id of ['route_scope', 'route_verdict']) {
      expect(node(id)?.kind).toBe('router')
      // A router has no tier and no tool because it never calls anything.
      expect(node(id)?.model).toBeUndefined()
      expect(node(id)?.tool).toBeUndefined()
    }
  })

  it('keeps the revise nodes as agents, because they really do re-run a model', () => {
    for (const id of ['revise_scope', 'revise_verdict']) {
      expect(node(id)?.kind).toBe('agent')
      expect(node(id)?.model).toBe('Escalation tier')
    }
  })

  it('keeps the quarantine node present and unconnected', () => {
    expect(node(QUARANTINE_NODE_ID)?.kind).toBe('quarantine')
    expect(
      MOCK_GRAPH.edges.filter(
        (edge) => edge.source === QUARANTINE_NODE_ID || edge.target === QUARANTINE_NODE_ID,
      ),
    ).toEqual([])
  })

  it('names its version as a copy rather than claiming the live hash', () => {
    expect(MOCK_GRAPH.version).toMatch(/^mock-/)
  })
})

describe('mock frame script addresses only declared nodes and edges', () => {
  const frames = buildMockSegments('run-mock').flat().map((step) => step.frame)

  it('emits frames for nodes the graph declares', () => {
    const attributed = [...new Set(frames.map((frame) => frame.node_id).filter(Boolean))] as string[]
    expect(attributed.length).toBeGreaterThan(0)
    for (const id of attributed) expect(nodeIds.has(id)).toBe(true)
  })

  /**
   * The exact drift this file exists to stop: an `edge_taken` frame naming a
   * traversal the descriptor has no edge for still animated, because the
   * composable falls back to a synthetic `from-to` id when the lookup misses.
   * Nothing crashed, and nothing lit up either.
   */
  it('emits edge_taken frames only for edges the graph declares', () => {
    const traversals = frames
      .filter((frame) => frame.kind === 'edge_taken')
      .map((frame) => [String(frame.details.from), String(frame.details.to)] as const)

    expect(traversals.length).toBeGreaterThan(0)
    for (const [from, to] of traversals) {
      const match = MOCK_GRAPH.edges.find((edge) => edge.source === from && edge.target === to)
      expect(match, `no edge declared for ${from} -> ${to}`).toBeDefined()
    }
  })

  it('opens its gates on nodes the graph declares as gates', () => {
    const gates = frames.filter((frame) => frame.kind === 'gate_open')
    expect(gates.map((frame) => frame.node_id)).toEqual(['confirm_scope', 'review_verdict'])
    for (const frame of gates) expect(node(String(frame.node_id))?.kind).toBe('gate')
  })

  /** The service sends `approve` / `revise`; anything else is not a rehearsal. */
  it('offers the option ids the service actually sends', () => {
    for (const frame of frames.filter((candidate) => candidate.kind === 'gate_open')) {
      const options = frame.details.options as Array<{ id: string }>
      expect(options.map((option) => option.id)).toEqual(['approve', 'revise'])
    }
  })

  it('runs the routers, so the deterministic hop is visible in the stream', () => {
    const routed = frames.filter((frame) => frame.node_id === 'route_scope' || frame.node_id === 'route_verdict')
    expect(routed.map((frame) => frame.event_type)).toEqual([
      'NODE_START',
      'NODE_END',
      'NODE_START',
      'NODE_END',
    ])
    // Routers never bill: no llm or token frame may be attributed to one.
    expect(routed.filter((frame) => frame.kind === 'llm' || frame.kind === 'token')).toEqual([])
  })

  it('numbers frames gaplessly from one across the whole script', () => {
    expect(frames.map((frame) => frame.seq)).toEqual(frames.map((_, index) => index + 1))
  })
})
