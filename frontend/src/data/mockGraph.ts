import type { GraphDescriptor } from '../types/studio'

/**
 * A faithful copy of the live `idea-validator` descriptor, not an impression of
 * it. This is what the console renders when no backend answers `/api/workflows`,
 * so anyone demoing or developing offline has to be looking at the topology the
 * service actually runs - Flow method names, both deterministic routers, and
 * both revise paths included.
 *
 * It was generated from the backend rather than transcribed. To refresh it after
 * a `ValidatorFlow` change:
 *
 *   ./.venv/Scripts/python.exe -c "import json; from brief_crew.service.graph \
 *     import VALIDATOR_GRAPH; print(VALIDATOR_GRAPH.model_dump_json(indent=2))"
 *
 * Node ids are `ValidatorFlow` method names, edge ids are
 * `{source}->{target}:{router_event}` - both are what `build_flow_structure`
 * emits, and the frame stream attributes `node_id` with the same strings.
 *
 * `version` is deliberately NOT the live SHA. The live hash changes whenever the
 * flow changes, and a mock claiming the current hash would assert a freshness it
 * cannot have. The suffix records which live version this was cut from, so drift
 * is visible instead of silent.
 */
export const MOCK_GRAPH: GraphDescriptor = {
  id: 'idea-validator',
  name: 'Idea Validator',
  version: 'mock-of-d8be7621',
  start_nodes: ['scope_idea'],
  nodes: [
    {
      id: 'scope_idea',
      label: 'Scoper',
      kind: 'agent',
      eyebrow: '01 - DEFINE',
      description: 'Turn the idea into the shared research contract.',
      model: 'Escalation tier',
      position: { x: 430, y: 20 },
    },
    {
      id: 'revise_scope',
      label: 'Revise scope',
      kind: 'agent',
      eyebrow: '01R - REVISE',
      description: 'Regenerate scope from the operator\'s requested correction.',
      model: 'Escalation tier',
      position: { x: 825, y: 180 },
    },
    {
      id: 'confirm_scope',
      label: 'Confirm scope',
      kind: 'gate',
      eyebrow: 'GATE 01',
      description: 'Pause after scoping so the operator can approve or revise it.',
      position: { x: 430, y: 180 },
    },
    {
      id: 'route_scope',
      label: 'Route scope',
      kind: 'router',
      eyebrow: 'DECISION',
      description: 'Route the structured scope reply without an LLM call.',
      position: { x: 430, y: 340 },
    },
    {
      id: 'research_market',
      label: 'Market Analyst',
      kind: 'agent',
      eyebrow: '02A - MARKET',
      description: 'Run the market branch in a Flow-managed worker thread.',
      model: 'Cheap tier',
      tool: 'Firecrawl',
      position: { x: 35, y: 520 },
    },
    {
      id: 'research_sentiment',
      label: 'Sentiment Analyst',
      kind: 'agent',
      eyebrow: '02B - DEMAND',
      description: 'Run the sentiment branch in a Flow-managed worker thread.',
      model: 'Cheap tier',
      tool: 'HN Algolia',
      position: { x: 430, y: 520 },
    },
    {
      id: 'research_feasibility',
      label: 'Feasibility Analyst',
      kind: 'agent',
      eyebrow: '02C - BUILD',
      description: 'Run the feasibility branch in a Flow-managed worker thread.',
      model: 'Cheap tier',
      tool: 'GitHub',
      position: { x: 825, y: 520 },
    },
    {
      id: 'synthesize',
      label: 'Synthesist',
      kind: 'agent',
      eyebrow: '03 - SCORE',
      description: 'Join all three branches before applying the deterministic rubric.',
      model: 'Escalation tier',
      position: { x: 430, y: 720 },
    },
    {
      id: 'revise_verdict',
      label: 'Revise verdict',
      kind: 'agent',
      eyebrow: '03R - REVISE',
      description: 'Re-run synthesis using the operator\'s requested correction.',
      model: 'Escalation tier',
      position: { x: 825, y: 880 },
    },
    {
      id: 'review_verdict',
      label: 'Review verdict',
      kind: 'gate',
      eyebrow: 'GATE 02',
      description: 'Pause after synthesis so the operator can approve or revise it.',
      position: { x: 430, y: 880 },
    },
    {
      id: 'route_verdict',
      label: 'Route verdict',
      kind: 'router',
      eyebrow: 'DECISION',
      description: 'Route the structured verdict reply without an LLM call.',
      position: { x: 430, y: 1040 },
    },
    {
      id: 'write_report',
      label: 'Reporter',
      kind: 'agent',
      eyebrow: '04 - WRITE',
      description: 'Turn the deterministic verdict and its evidence into the final brief.',
      model: 'Escalation tier',
      position: { x: 430, y: 1200 },
    },
    {
      id: 'persist',
      label: 'Validation brief',
      kind: 'output',
      eyebrow: 'OUTPUT',
      description: 'Write only the human-readable report body to output/validation.md.',
      position: { x: 430, y: 1360 },
    },
    // Mirrors the node the service appends to every graph descriptor from
    // QUARANTINE_NODE_ID. It has no edges on purpose: frames land here only
    // when the backend could not attribute them, and that has to be visible.
    {
      id: 'unattributed',
      label: 'Unattributed',
      kind: 'quarantine',
      eyebrow: 'INSTRUMENTATION',
      description: 'Events that could not be joined to a declared node.',
      position: { x: 1130, y: 20 },
    },
  ],
  edges: [
    { id: 'scope_idea->confirm_scope:', source: 'scope_idea', target: 'confirm_scope', condition_type: 'OR' },
    { id: 'revise_scope->confirm_scope:', source: 'revise_scope', target: 'confirm_scope', condition_type: 'OR' },
    { id: 'confirm_scope->route_scope:', source: 'confirm_scope', target: 'route_scope', condition_type: 'OR' },
    { id: 'research_market->synthesize:', source: 'research_market', target: 'synthesize', condition_type: 'AND' },
    { id: 'research_sentiment->synthesize:', source: 'research_sentiment', target: 'synthesize', condition_type: 'AND' },
    { id: 'research_feasibility->synthesize:', source: 'research_feasibility', target: 'synthesize', condition_type: 'AND' },
    { id: 'synthesize->review_verdict:', source: 'synthesize', target: 'review_verdict', condition_type: 'OR' },
    { id: 'revise_verdict->review_verdict:', source: 'revise_verdict', target: 'review_verdict', condition_type: 'OR' },
    { id: 'review_verdict->route_verdict:', source: 'review_verdict', target: 'route_verdict', condition_type: 'OR' },
    { id: 'write_report->persist:', source: 'write_report', target: 'persist', condition_type: 'OR' },
    { id: 'route_scope->research_market:scope_approved', source: 'route_scope', target: 'research_market', label: 'scope_approved', route: 'scope_approved' },
    { id: 'route_scope->research_sentiment:scope_approved', source: 'route_scope', target: 'research_sentiment', label: 'scope_approved', route: 'scope_approved' },
    { id: 'route_scope->research_feasibility:scope_approved', source: 'route_scope', target: 'research_feasibility', label: 'scope_approved', route: 'scope_approved' },
    { id: 'route_scope->revise_scope:scope_revise', source: 'route_scope', target: 'revise_scope', label: 'scope_revise', route: 'scope_revise' },
    { id: 'route_verdict->write_report:verdict_approved', source: 'route_verdict', target: 'write_report', label: 'verdict_approved', route: 'verdict_approved' },
    { id: 'route_verdict->revise_verdict:verdict_revise', source: 'route_verdict', target: 'revise_verdict', label: 'verdict_revise', route: 'verdict_revise' },
  ],
}
