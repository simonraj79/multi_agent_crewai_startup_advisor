import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { ref } from 'vue'
import { BUILDER_PROBLEMS, useBuilderProblems } from '../src/composables/useBuilderProblems'
import { BUILDER_SCHEMA_ID, documentId, nodeId, edgeId } from '../src/types/builder'
import type {
  AgentConfig,
  BuilderDocument,
  BuilderEdge,
  BuilderNode,
  BuilderProblem,
  BuilderVocabulary,
} from '../src/types/builder'

/** `BuilderNode` narrowed to one kind - what a typed `:node` prop wants. */
type NodeOf<K extends BuilderNode['kind']> = Extract<BuilderNode, { kind: K }>

/**
 * Shared scaffolding for the three WP-E specs.
 *
 * NOT a `.spec.ts`, deliberately: `vitest.config.ts` collects
 * `tests/**\/*.spec.ts`, so importing one spec file from another would register
 * its `describe`s twice and report every assertion in it as if it had run in
 * both. A plain module is collected by nothing and imported by both.
 *
 * `tests/helpers.ts` is WP-G's file and is not touched here.
 *
 * THE VOCABULARY BELOW IS HAND-BUILT and that is a deliberate line rather than a
 * shortcut. What these specs test is widget BEHAVIOUR - that `otherwise` clears
 * its key, that a nested reference is refused - none of which depends on the
 * real bounds being real. Whether the vocabulary's shape and the served bounds
 * agree with Python is already pinned, at run time against the source, by
 * `builderTypes.spec.ts` and `nodeKinds.spec.ts`. Restating that here would be a
 * third copy of one assertion.
 *
 * The three SENTENCES this package quotes from the compiler are a different
 * matter, and they are checked against `document.py` itself in the specs that
 * use them - a message printed verbatim to an author is exactly the kind of
 * restated constant this repo has watched drift.
 */

export function pythonSource(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8')
}

export const DOCUMENT_PY = pythonSource('../../src/brief_crew/builder/document.py')

export function vocabularyFixture(
  overrides: Partial<BuilderVocabulary> = {},
): BuilderVocabulary {
  return {
    schema_id: BUILDER_SCHEMA_ID,
    node_kinds: ['input', 'agent', 'crew', 'gate', 'router', 'transform', 'output'],
    tiers: ['cheap', 'escalation'],
    agent_ids: [
      'feasibility_analyst',
      'market_analyst',
      'reporter',
      'scoper',
      'sentiment_analyst',
      'synthesist',
    ],
    // Exactly what `_vocabulary()` serves: `sorted(BUILDABLE_BUILDER_CREW_IDS)`,
    // which is the library MINUS `synthesis` and `report`. The absence is the
    // point of one of the tests, so the fixture must not quietly re-add them.
    crew_ids: ['feasibility', 'market', 'scope', 'sentiment'],
    research_tools: ['github_feasibility', 'hn_sentiment', 'market_research'],
    transform_ops: ['default', 'format', 'join_text', 'merge', 'pick', 'to_json'],
    router_comparisons: ['contains', 'eq', 'gt', 'gte', 'lt', 'lte', 'ne'],
    router_otherwise: 'otherwise',
    result_body_keys: ['markdown_body'],
    bounds: {
      max_graph_nodes: 24,
      max_billable_nodes: 8,
      max_escalation_nodes: 5,
      max_fanout_width: 4,
      min_router_branches: 2,
      max_cycles: 2,
      max_cycle_iterations: 3,
      max_agent_iter: 8,
      max_guardrail_retries: 2,
      max_label_chars: 40,
      max_name_chars: 80,
      max_gate_message_chars: 2000,
      max_input_chars: 2000,
      max_document_bytes: 262144,
      run_cost_ceiling_usd: 10,
    },
    ...overrides,
  }
}

/* --- nodes, built by hand rather than through `newNode` -------------------
 * `newNode` reads the module-singleton vocabulary, and a spec that seeded that
 * singleton would leak into whichever file ran next. These are explicit, which
 * is also what lets a test say "a router with a broken branch" in one place. */

export function inputNode(id = 'idea', field = 'idea'): NodeOf<'input'> {
  return {
    id: nodeId(id),
    kind: 'input',
    label: 'Idea',
    position: { x: 0, y: 0 },
    config: { field: nodeId(field), label: null, max_chars: 2000, required: true },
  }
}

export function agentNode(id = 'scoper', overrides: Partial<AgentConfig> = {}): NodeOf<'agent'> {
  return {
    id: nodeId(id),
    kind: 'agent',
    label: 'Scoper',
    position: { x: 0, y: 120 },
    config: {
      tier: 'cheap',
      max_iter: 2,
      guardrail_max_retries: 2,
      prompt_inputs: {},
      agent_id: nodeId('scoper'),
      tools: [],
      ...overrides,
    },
  }
}

export function crewNode(id = 'market', crew = 'market'): NodeOf<'crew'> {
  return {
    id: nodeId(id),
    kind: 'crew',
    label: 'Market crew',
    position: { x: 0, y: 240 },
    config: {
      tier: 'escalation',
      max_iter: 2,
      guardrail_max_retries: 2,
      prompt_inputs: {},
      crew_id: nodeId(crew),
    },
  }
}

export function gateNode(id = 'confirm'): NodeOf<'gate'> {
  return {
    id: nodeId(id),
    kind: 'gate',
    label: 'Confirm scope',
    position: { x: 0, y: 360 },
    config: {
      message: 'Review this step before the run continues.',
      editable_fields: [],
      max_turns: 1,
      expiry_seconds: 1800,
    },
  }
}

export function routerNode(id = 'route'): NodeOf<'router'> {
  return {
    id: nodeId(id),
    kind: 'router',
    label: 'Route',
    position: { x: 0, y: 480 },
    config: {
      branches: [
        { label: nodeId('match'), op: 'eq', key: nodeId('decision'), value: 'yes' },
        { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
      ],
    },
  }
}

export function transformNode(
  id = 'shape',
  op: 'pick' | 'format' | 'join_text' | 'merge' | 'to_json' | 'default' = 'pick',
): NodeOf<'transform'> {
  return {
    id: nodeId(id),
    kind: 'transform',
    label: 'Shape',
    position: { x: 0, y: 600 },
    config: { op, args: {} },
  }
}

export function outputNode(id = 'result'): NodeOf<'output'> {
  return {
    id: nodeId(id),
    kind: 'output',
    label: 'Result',
    position: { x: 0, y: 720 },
    config: { body_key: 'markdown_body', source: null },
  }
}

export function edge(
  id: string,
  source: string,
  target: string,
  sourcePort = 'out',
): BuilderEdge {
  return {
    id: edgeId(id),
    source: nodeId(source),
    source_port: sourcePort,
    target: nodeId(target),
    target_port: 'in',
  }
}

export function documentFixture(
  nodes: BuilderNode[],
  edges: BuilderEdge[] = [],
  overrides: Partial<BuilderDocument> = {},
): BuilderDocument {
  return {
    schema: BUILDER_SCHEMA_ID,
    id: documentId('ug_0000beef'),
    name: 'Test graph',
    version: 1,
    input_field: nodeId('idea'),
    nodes,
    edges,
    joins: {},
    budget: null,
    ...overrides,
  }
}

export function problem(overrides: Partial<BuilderProblem> = {}): BuilderProblem {
  return {
    code: 'router-branch-count',
    severity: 'error',
    message: 'this router has 5 branches; between 2 and 4 are allowed',
    node_id: null,
    edge_id: null,
    ...overrides,
  }
}

/**
 * A `global.provide` carrying a real `BuilderProblemsIndex`.
 *
 * `FieldProblem` and `InspectorRail` both THROW when the index is absent, and
 * that is their contract rather than an oversight - a form rendered without it
 * would look clean over a document the server has refused. So every mount in
 * these specs provides one, and passing problems in is how a test says what the
 * server said.
 */
export function problemsProvide(problems: BuilderProblem[] = []): Record<symbol, unknown> {
  return { [BUILDER_PROBLEMS as symbol]: useBuilderProblems(ref(problems)) }
}
