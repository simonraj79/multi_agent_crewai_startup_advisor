import {
  documentId,
  edgeId,
  nodeId,
  BUILDER_SCHEMA_ID,
} from '../../types/builder'
import type {
  BuilderDocument,
  BuilderEdge,
  BuilderNode,
  NodeId,
  NodePosition,
} from '../../types/builder'

/**
 * The six-agent startup-idea evaluator, drawn as an ordinary builder document.
 *
 * This is the mission stated as data: the evaluator that has its own Python
 * flow, its own YAML and its own console becomes ONE TEMPLATE INSIDE THE
 * BUILDER, not a special case beside it. Nothing in `TemplateGallery`,
 * `useBuilderDocument` or the inspectors knows this file exists - it is seeded
 * into the store as an unsaved draft exactly the way `BLANK` is, and every
 * command, every undo and every problem behaves identically over it.
 *
 * IT IS NOT `validator_flow.py`. The Python flow carries typed pydantic
 * findings between its methods, a rubric, guardrails, a cache and a verdict
 * schema that recomputes its own arithmetic. A builder graph carries strings on
 * a flat state map. What transfers is the TOPOLOGY - who runs, in what order,
 * where a human stops it, what loops - and the `caveat` on the gallery card
 * says exactly that in the author's own reading order, verbatim (R14).
 *
 * VERIFIED, NOT ASSERTED. This document was POSTed to a live
 * `/api/builder/validate` on 2026-09-02 and came back `valid: true` with zero
 * problems, priced at `static_cost_usd $1.5137` / `floor_cost_usd $1.2159` over
 * 60 modelled calls, at 8 billable / 5 escalation / 2 cycles. It was then
 * created, published (`graph_version 3345109819d3e09f`) and its 403 measured.
 * `tests/validatorTemplate.spec.ts` pins the counts against the LIVE
 * `vocabulary.bounds` rather than against those numbers, so a server bounds
 * change fails a test instead of the gallery.
 *
 * WHY THE PROMPT INPUTS LOOK LIKE THAT. Every `agent_id` here names a real YAML
 * task, and `library_problems` refuses a node that does not supply every
 * placeholder that task interpolates - `scoped_idea_json`, `human_override`,
 * `cached_evidence_block` and the rest are not decoration, they are the task's
 * own `{braces}`. `cached_evidence_block` is deliberately the empty string: the
 * warm Pinecone cache is wired into `validator_flow.py`, not into a drawn
 * graph, and passing an empty block is the honest way to say "there is no
 * cached evidence on this path" rather than inventing a reference that would
 * render as eight characters of punctuation inside the prompt.
 */

/** Where the document lands before a server has assigned it an id.
 *
 * `BuilderDocument.id` is a branded `DocumentId` and `documentId()` refuses
 * anything that is not `ug_` plus eight hex digits, so a template cannot simply
 * leave it blank. `POST /api/builder/workflows` overwrites whatever it is sent
 * - measured: a document posted carrying this exact value came back as
 * `ug_38cecd0b` - and `forValidate` deletes the key outright, so this string is
 * never the id of anything. All-zeroes rather than a plausible-looking id, so
 * that a value which somehow escaped to a log reads as the placeholder it is.
 */
const UNSAVED = documentId('ug_00000000')

/** The run request's input key, and the field the one input node asks for. */
const INPUT_FIELD = nodeId('idea')

/** `${state.<key>}` for a node's recorded output. Mirrors `STATE_OUTPUT_PREFIX`. */
const out = (id: string): string => `\${state.out__${id}}`

/** `${state.turns__<gate>}` - the revise turns a gate has already spent.
 *
 * Seeded by `compiler.state_default()` for every gate node and incremented by
 * `route_gate` each time it honours a revise, which is what makes it the one
 * key a router can compare against to decide whether to go round again. It is
 * a real state key, not a convention: a router reading a key nothing writes
 * would take its `otherwise` branch forever and look like it was working.
 */
const turns = (gateId: string): NodeId => nodeId(`turns__${gateId}`)

const at = (x: number, y: number): NodePosition => ({ x, y })

/**
 * One edge, minted through the guard.
 *
 * `target_port` is not a parameter because `'in'` is the only legal value in
 * the schema - `_OUT_PORTS_BY_KIND` gives every kind exactly one inbound port -
 * and a parameter for a constant is an invitation to pass the other thing.
 */
function edge(id: string, source: string, port: string, target: string): BuilderEdge {
  return {
    id: edgeId(id),
    source: nodeId(source),
    source_port: port,
    target: nodeId(target),
    target_port: 'in',
  }
}

const NODES: BuilderNode[] = [
  {
    id: nodeId('idea'),
    kind: 'input',
    label: 'Startup idea',
    position: at(0, 190),
    config: {
      field: INPUT_FIELD,
      // The operator's prompt, deliberately not the canvas label. The node is
      // called "Startup idea" on the graph; the person launching a run is asked
      // for something they can actually type.
      label: 'Describe the idea in a sentence or two',
      max_chars: 2000,
      required: true,
    },
  },
  {
    id: nodeId('scoper'),
    kind: 'agent',
    label: 'Scope the idea',
    position: at(300, 190),
    config: {
      tier: 'escalation',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('scoper'),
      tools: [],
      prompt_inputs: {
        idea: `\${state.${INPUT_FIELD}}`,
        // Empty on the FIRST pass, which is the whole difference between this
        // node and `revise_scope` below. The scoping task interpolates
        // `{human_override}` unconditionally, so the key has to be present; on
        // this path there is no operator instruction yet to put in it.
        human_override: '',
      },
    },
  },
  {
    id: nodeId('confirm_scope'),
    kind: 'gate',
    label: 'Confirm scope',
    position: at(600, 190),
    config: {
      message: 'Read the scope below. Approve it, or send it back with what to change.',
      // Seeds these two keys into the gate payload so the operator gets input
      // boxes for them rather than a wall of JSON. R9's honest sentence
      // applies: the compiler seeds them, and the service does not currently
      // render the rest of the payload read-only.
      editable_fields: [nodeId('segment'), nodeId('job')],
      // Two revise turns. Under `MAX_CYCLE_ITERATIONS` (3), so no
      // `cycle-iterations` problem, and above 1 so the loop below is worth
      // drawing at all.
      max_turns: 2,
      expiry_seconds: 1800,
    },
  },
  {
    id: nodeId('revise_scope'),
    kind: 'agent',
    label: 'Revise scope',
    position: at(600, 0),
    config: {
      tier: 'escalation',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('scoper'),
      tools: [],
      prompt_inputs: {
        idea: `\${state.${INPUT_FIELD}}`,
        // `route_gate` records the operator's reply MINUS the decision under
        // the gate's own output key, so this is the note they typed. That is
        // the entire reason a gate has an output at all.
        human_override: out('confirm_scope'),
      },
    },
  },
  {
    id: nodeId('route_scope'),
    kind: 'router',
    label: 'Scope again?',
    position: at(900, 0),
    config: {
      branches: [
        // The back edge leaves HERE, and it has to: `bounds.py` refuses a
        // loop-closing edge from any kind that is not a gate or a router,
        // because a plain listener closing a loop was measured to end the run
        // silently - the join fires once, the second arrival is suppressed, no
        // exception, no warning.
        { label: nodeId('again'), op: 'lt', key: turns('confirm_scope'), value: 2 },
        { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
      ],
    },
  },
  {
    id: nodeId('scope_brief'),
    kind: 'transform',
    label: 'Agreed scope',
    position: at(900, 190),
    config: {
      // `default` and not `pick`, because the question this node answers is
      // "which scope is current" - the revised one if a revision happened, the
      // original otherwise. Only `null` and `""` count as absent, which is what
      // makes it safe: on the first pass `out__revise_scope` is the `null` the
      // compiler seeded, so the original wins by arithmetic rather than by
      // luck.
      op: 'default',
      args: { value: out('revise_scope'), default: out('scoper') },
    },
  },
  {
    id: nodeId('market_analyst'),
    kind: 'agent',
    label: 'Market',
    position: at(1200, 0),
    config: {
      tier: 'cheap',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('market_analyst'),
      tools: ['research_market_landscape'],
      prompt_inputs: {
        scoped_idea_json: out('scope_brief'),
        market_query: out('scope_brief'),
        cached_evidence_block: '',
      },
    },
  },
  {
    id: nodeId('sentiment_analyst'),
    kind: 'agent',
    label: 'Signal',
    position: at(1200, 190),
    config: {
      tier: 'cheap',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('sentiment_analyst'),
      tools: ['analyze_community_sentiment'],
      prompt_inputs: {
        scoped_idea_json: out('scope_brief'),
        community_queries_block: out('scope_brief'),
      },
    },
  },
  {
    id: nodeId('feasibility_analyst'),
    kind: 'agent',
    label: 'Build',
    position: at(1200, 380),
    config: {
      tier: 'cheap',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('feasibility_analyst'),
      tools: ['assess_technical_feasibility'],
      prompt_inputs: {
        scoped_idea_json: out('scope_brief'),
        tech_queries_block: out('scope_brief'),
        cached_evidence_block: '',
      },
    },
  },
  {
    id: nodeId('score'),
    kind: 'agent',
    label: 'Score the evidence',
    position: at(1500, 190),
    config: {
      tier: 'escalation',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('synthesist'),
      tools: [],
      prompt_inputs: {
        scoped_idea_json: out('scope_brief'),
        market_findings_json: out('market_analyst'),
        sentiment_findings_json: out('sentiment_analyst'),
        feasibility_findings_json: out('feasibility_analyst'),
        human_override: '',
      },
    },
  },
  {
    id: nodeId('review_verdict'),
    kind: 'gate',
    label: 'Review verdict',
    position: at(300, 700),
    config: {
      message: 'Read the scored verdict. Approve it, or send it back with what to reconsider.',
      editable_fields: [],
      max_turns: 2,
      expiry_seconds: 1800,
    },
  },
  {
    id: nodeId('revise_verdict'),
    kind: 'agent',
    label: 'Rescore',
    position: at(300, 890),
    config: {
      tier: 'escalation',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('synthesist'),
      tools: [],
      prompt_inputs: {
        scoped_idea_json: out('scope_brief'),
        market_findings_json: out('market_analyst'),
        sentiment_findings_json: out('sentiment_analyst'),
        feasibility_findings_json: out('feasibility_analyst'),
        human_override: out('review_verdict'),
      },
    },
  },
  {
    id: nodeId('route_verdict'),
    kind: 'router',
    label: 'Score again?',
    position: at(600, 890),
    config: {
      branches: [
        { label: nodeId('again'), op: 'lt', key: turns('review_verdict'), value: 2 },
        { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
      ],
    },
  },
  {
    id: nodeId('verdict_brief'),
    kind: 'transform',
    label: 'Standing verdict',
    position: at(600, 700),
    config: {
      op: 'default',
      args: { value: out('revise_verdict'), default: out('score') },
    },
  },
  {
    id: nodeId('reporter'),
    kind: 'agent',
    label: 'Write the report',
    position: at(900, 700),
    config: {
      tier: 'escalation',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('reporter'),
      tools: [],
      prompt_inputs: {
        scoped_idea_json: out('scope_brief'),
        market_findings_json: out('market_analyst'),
        sentiment_findings_json: out('sentiment_analyst'),
        feasibility_findings_json: out('feasibility_analyst'),
        verdict_json: out('verdict_brief'),
      },
    },
  },
  {
    id: nodeId('brief'),
    kind: 'output',
    label: 'Validation report',
    position: at(1200, 700),
    config: {
      // `RUN_RESULT_BODY_KEYS[0]`. A body written under any other key comes
      // back clipped by the STREAMING frame serialiser instead of getting
      // `MAX_RUN_RESULT_BODY_CHARS`, which is exactly how the first paid run's
      // report was lost at 4096 characters.
      body_key: 'markdown_body',
      source: out('reporter'),
    },
  },
]

const EDGES: BuilderEdge[] = [
  edge('e1', 'idea', 'out', 'scoper'),
  edge('e2', 'scoper', 'out', 'confirm_scope'),
  edge('e3', 'confirm_scope', 'approve', 'scope_brief'),
  edge('e4', 'confirm_scope', 'revise', 'revise_scope'),
  edge('e5', 'revise_scope', 'out', 'route_scope'),
  // BACK EDGE 1 of 2. Re-opens the gate with the revised scope.
  edge('e6', 'route_scope', 'again', 'confirm_scope'),
  edge('e7', 'route_scope', 'otherwise', 'scope_brief'),
  // The four-wide fan-out. `max_fanout_width` is 4, so this sits exactly at the
  // bound - which is the point of the BudgetMeter pip row: an author must SEE a
  // full row before placing the node that would break it.
  edge('e8', 'scope_brief', 'out', 'market_analyst'),
  edge('e9', 'scope_brief', 'out', 'sentiment_analyst'),
  edge('e10', 'scope_brief', 'out', 'feasibility_analyst'),
  edge('e11', 'scope_brief', 'out', 'score'),
  edge('e12', 'market_analyst', 'out', 'score'),
  edge('e13', 'sentiment_analyst', 'out', 'score'),
  edge('e14', 'feasibility_analyst', 'out', 'score'),
  edge('e15', 'score', 'out', 'review_verdict'),
  edge('e16', 'review_verdict', 'approve', 'verdict_brief'),
  edge('e17', 'review_verdict', 'revise', 'revise_verdict'),
  edge('e18', 'revise_verdict', 'out', 'route_verdict'),
  // BACK EDGE 2 of 2.
  edge('e19', 'route_verdict', 'again', 'review_verdict'),
  edge('e20', 'route_verdict', 'otherwise', 'verdict_brief'),
  edge('e21', 'verdict_brief', 'out', 'reporter'),
  edge('e22', 'reporter', 'out', 'brief'),
]

/**
 * What the gallery card must say, word for word (R14).
 *
 * It ships because it is TOPOLOGY, and saying so is the difference between a
 * template and a booby trap: an author who starts here gets the right shape and
 * has to supply the judgement themselves. The alternative - shipping it with no
 * caveat - is a graph that looks like the validator, is named like the
 * validator, and scores nothing the way the validator does.
 */
export const IDEA_VALIDATOR_CAVEAT =
  'This is the evaluator’s shape, not its judgement. The six agents, the two '
  + 'human gates and both revise loops are the real ones — but the rubric, the '
  + 'confidence arithmetic, the guardrails and the warm evidence cache live in '
  + 'Python, and a drawn graph carries plain text between its nodes. Treat what '
  + 'it produces as a draft an analyst wrote, not as a score.'

/**
 * The evaluator as a document: 16 nodes, 22 edges, two loops, one join.
 *
 * ON THE NODE COUNT. The spec's manifest describes this file as "17 nodes, 22
 * edges", and both figures are right about something different. The GRAPH
 * DESCRIPTOR the server derives from this document has 17 nodes - the sixteenth
 * drawn node plus the `unattributed` quarantine node the event spine always
 * adds - and 22 edges, measured against a live `POST /api/builder/workflows`
 * (`ug_e9afa950`: `17 nodes, 22 edges`). The DOCUMENT has 16. A seventeenth
 * drawn node is not reachable without a twenty-third edge, and the only shape
 * that spends one - a `merge` node gathering the three branches - needs its own
 * `joins` entry, which contradicts the manifest's own `joins: {score: 'all'}`.
 */
export const IDEA_VALIDATOR_DOCUMENT: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: UNSAVED,
  name: 'Idea validator',
  version: 1,
  input_field: INPUT_FIELD,
  nodes: NODES,
  edges: EDGES,
  // The ONE join, and the only place in the document where fan-in semantics
  // are stated rather than defaulted. `score` waits for all four arrivals - the
  // agreed scope and the three research branches - because an OR here would
  // score the idea off whichever analyst answered first. Every other multi-
  // inbound node in this graph wants exactly the opposite: `confirm_scope`,
  // `scope_brief` and `verdict_brief` each have two predecessors of which only
  // one ever fires, and an AND there would deadlock the run.
  joins: { score: 'all' },
  // Written by the compiler onto the document it priced, never by an author.
  budget: null,
}
