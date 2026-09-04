import { BUILDER_SCHEMA_ID, documentId, edgeId, nodeId } from '../types/builder'
import type { BuilderDocument, BuilderEdge, BuilderNode } from '../types/builder'
import { IDEA_VALIDATOR_CAVEAT, IDEA_VALIDATOR_DOCUMENT } from './templates/ideaValidator'

/**
 * The four graphs the gallery opens with, as code.
 *
 * Template AUTHORING is cut (cut list item 12): there is no "save as template",
 * no template store and no server route, and these four are literals a
 * contributor edits. That is the honest shape for four, and the reason it stays
 * honest is that a template is not a special kind of document - `TemplateGallery`
 * hands one to the store as an ordinary unsaved draft and every command, undo
 * and problem behaves over it exactly as over a graph drawn by hand.
 *
 * WHAT IS HARDCODED HERE, AND WHY THAT IS NOT CUT LIST ITEM 17. These documents
 * name `scoper`, `market_analyst`, `markdown_body` and the three research tools
 * as literals. Item 17 forbids a hardcoded FALLBACK for the vocabulary - a
 * substitute enum the palette would draw from when `/vocabulary` fails, which is
 * how a client starts offering kinds the compiler rejects. This is the opposite
 * direction: authored content that names things, exactly as a document drawn by
 * hand does. If the server drops an agent id, this template stops validating and
 * says so in `ProblemsPanel` with the server's own sentence, which is the same
 * answer any other document would get.
 *
 * EVERY ONE VALIDATES. All four were POSTed to a live `/api/builder/validate` on
 * 2026-09-02; `MINIMAL_GATED_AGENT`, `FAN_OUT_JOIN` and `IDEA_VALIDATOR` each
 * came back `valid: true` with zero problems. `BLANK` deliberately does not -
 * see its own note.
 */

/** One edge. `'in'` is the only legal target port, so it is not a parameter. */
function edge(id: string, source: string, port: string, target: string): BuilderEdge {
  return {
    id: edgeId(id),
    source: nodeId(source),
    source_port: port,
    target: nodeId(target),
    target_port: 'in',
  }
}

/**
 * The id every template carries until a server assigns a real one.
 *
 * `POST /api/builder/workflows` overwrites it - measured - and `forValidate`
 * deletes the key outright, so this value is never the id of anything.
 */
const UNSAVED = documentId('ug_00000000')

const MINIMAL_NODES: BuilderNode[] = [
  {
    id: nodeId('idea'),
    kind: 'input',
    label: 'Request',
    position: { x: 300, y: 0 },
    config: {
      field: nodeId('idea'),
      label: 'What should this run work from?',
      max_chars: 2000,
      required: true,
    },
  },
  {
    id: nodeId('confirm'),
    kind: 'gate',
    label: 'Confirm the request',
    position: { x: 300, y: 180 },
    config: {
      message: 'Check the request before this run spends anything. Approve it, or send it back.',
      editable_fields: [],
      max_turns: 1,
      expiry_seconds: 1800,
    },
  },
  {
    id: nodeId('draft'),
    kind: 'agent',
    label: 'Draft',
    position: { x: 300, y: 360 },
    config: {
      tier: 'cheap',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('scoper'),
      tools: [],
      // The scoping task interpolates exactly these two placeholders, which is
      // what makes `scoper` the cheapest agent to put in a minimal template: any
      // other one would need three to five prompt inputs before it validates.
      prompt_inputs: { idea: '${state.idea}', human_override: '${state.out__confirm}' },
    },
  },
  {
    id: nodeId('report'),
    kind: 'output',
    label: 'Result',
    position: { x: 300, y: 540 },
    config: { body_key: 'markdown_body', source: '${state.out__draft}' },
  },
]

const FAN_OUT_NODES: BuilderNode[] = [
  {
    id: nodeId('idea'),
    kind: 'input',
    label: 'Request',
    position: { x: 340, y: 0 },
    config: {
      field: nodeId('idea'),
      label: 'What should the three branches research?',
      max_chars: 2000,
      required: true,
    },
  },
  {
    id: nodeId('confirm'),
    kind: 'gate',
    label: 'Confirm the request',
    position: { x: 340, y: 180 },
    config: {
      message:
        'Three research branches are about to run in parallel. Approve the request, or send it back.',
      editable_fields: [],
      max_turns: 1,
      expiry_seconds: 1800,
    },
  },
  {
    id: nodeId('brief'),
    kind: 'transform',
    label: 'Shared brief',
    position: { x: 340, y: 360 },
    config: {
      // One reference the three branches share, so a change of mind at the gate
      // reaches all three rather than one of them.
      op: 'default',
      args: { value: '${state.out__confirm}', default: '${state.idea}' },
    },
  },
  {
    id: nodeId('market'),
    kind: 'agent',
    label: 'Market',
    position: { x: 60, y: 540 },
    config: {
      tier: 'cheap',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('market_analyst'),
      tools: ['research_market_landscape'],
      prompt_inputs: {
        scoped_idea_json: '${state.out__brief}',
        market_query: '${state.out__brief}',
        cached_evidence_block: '',
      },
    },
  },
  {
    id: nodeId('signal'),
    kind: 'agent',
    label: 'Signal',
    position: { x: 340, y: 540 },
    config: {
      tier: 'cheap',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('sentiment_analyst'),
      tools: ['analyze_community_sentiment'],
      prompt_inputs: {
        scoped_idea_json: '${state.out__brief}',
        community_queries_block: '${state.out__brief}',
      },
    },
  },
  {
    id: nodeId('build'),
    kind: 'agent',
    label: 'Build',
    position: { x: 620, y: 540 },
    config: {
      tier: 'cheap',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('feasibility_analyst'),
      tools: ['assess_technical_feasibility'],
      prompt_inputs: {
        scoped_idea_json: '${state.out__brief}',
        tech_queries_block: '${state.out__brief}',
        cached_evidence_block: '',
      },
    },
  },
  {
    id: nodeId('score'),
    kind: 'agent',
    label: 'Score the evidence',
    position: { x: 340, y: 720 },
    config: {
      tier: 'escalation',
      max_iter: 2,
      guardrail_max_retries: 2,
      agent_id: nodeId('synthesist'),
      tools: [],
      prompt_inputs: {
        scoped_idea_json: '${state.out__brief}',
        market_findings_json: '${state.out__market}',
        sentiment_findings_json: '${state.out__signal}',
        feasibility_findings_json: '${state.out__build}',
        human_override: '',
      },
    },
  },
  {
    id: nodeId('report'),
    kind: 'output',
    label: 'Result',
    position: { x: 340, y: 900 },
    config: { body_key: 'markdown_body', source: '${state.out__score}' },
  },
]

/** One template card, and the document behind it. */
export interface BuilderTemplate {
  /** Stable across renames; the gallery keys its cards and its tests on it. */
  readonly id: string
  readonly title: string
  /** One sentence on the card. What you get, not what it is called. */
  readonly blurb: string
  /**
   * A truth about this template that its picture cannot carry.
   *
   * Rendered VERBATIM on the card when present (R14). Only `IDEA_VALIDATOR` has
   * one, and it earns it: the graph is the evaluator's topology without the
   * evaluator's judgement, and a template that looks like the real thing while
   * scoring nothing like it is a booby trap rather than a starting point.
   */
  readonly caveat?: string
  readonly document: BuilderDocument
}

/**
 * One input node at (100, 100), and ZERO problems (02-canvas.md D7).
 *
 * It opened with nothing drawn and two errors against it until 2026-09-04 -
 * `no-input-node` and `input-field-undeclared` - on the argument that a draft
 * need not be valid and that the two problems name the first two things an
 * author has to do. That argument is wrong in one specific way, and the way is
 * the whole of rubric 1: the FIRST thing a new author sees is a red problems
 * dock about a graph they have not touched. It reads as "you have already made
 * a mistake", and it is the one screen where nothing has happened yet.
 *
 * The counter-argument that seeding an input node "invents a decision" does not
 * survive contact with what the node actually says. Every flow this product can
 * compile starts at an input - `document.py` gives `input` no target port at
 * all, because it is where the run begins - so the node is not a guess about
 * the author's graph, it is the one thing every graph has. Flowise v2 reached
 * the same conclusion and seeds a Start node at the same `{x:100, y:100}`
 * (`Canvas.jsx:656-677`).
 *
 * `input_field` names the node's own `field`, so the pair is consistent on
 * arrival rather than consistent once somebody presses a button. A SECOND input
 * node is still perfectly legal and is still flagged `input-field-ambiguous`,
 * which is the problem that means something: two candidates and no statement of
 * which one the run reads.
 *
 * Landing to first node placed is now ONE click - the template card.
 */
const BLANK_INPUT_FIELD = nodeId('idea')

export const BLANK: BuilderTemplate = {
  id: 'blank',
  title: 'Blank canvas',
  blurb: 'One input node, ready to build on. Drag a kind from the palette, or press 1–7.',
  document: {
    schema: BUILDER_SCHEMA_ID,
    id: UNSAVED,
    name: 'Untitled graph',
    version: 1,
    input_field: BLANK_INPUT_FIELD,
    nodes: [
      {
        id: nodeId('idea'),
        label: 'Idea',
        // Flowise's own seed position, and it is a sensible one for the reason
        // it is sensible there: far enough from the origin that a fit-view has
        // something to centre, close enough that the first node an author adds
        // below it is still on screen.
        position: { x: 100, y: 100 },
        kind: 'input',
        config: {
          field: BLANK_INPUT_FIELD,
          // Null rather than the label, exactly as `nodeKinds.ts` argues: a node
          // called "Idea" may reasonably ask the operator for something longer,
          // and inventing the prompt from the canvas label puts words in the
          // author's mouth that an operator then reads.
          label: null,
          max_chars: 2000,
          required: true,
        },
      },
    ],
    edges: [],
    joins: {},
    budget: null,
  },
}

/**
 * The smallest graph a signed-out visitor may launch.
 *
 * "Smallest" is a policy statement, not an aesthetic one. `POST /runs` answers
 * **403** - `workflow … reaches a billable node before any human gate; sign in,
 * or add a gate above the first agent` - for any published graph whose first
 * billable node sits on an ungated path, because while nobody is signed in
 * human inaction IS the spend cap. Four nodes in this order is the smallest
 * shape that keeps that brake, and it is why the gate is above the agent rather
 * than below it.
 *
 * Measured on 2026-09-02: `valid: true`, `gated_before_spend: true`, one
 * billable node, `static_cost_usd $0.0607`, and an anonymous
 * `POST /api/sessions/{id}/runs` answered **202** and paused at `confirm`.
 */
export const MINIMAL_GATED_AGENT: BuilderTemplate = {
  id: 'minimal-gated-agent',
  title: 'Minimal gated agent',
  blurb: 'Input, a human gate, one agent, one result — the smallest graph anyone can launch.',
  document: {
    schema: BUILDER_SCHEMA_ID,
    id: UNSAVED,
    name: 'Minimal gated agent',
    version: 1,
    input_field: nodeId('idea'),
    nodes: MINIMAL_NODES,
    edges: [
      edge('e1', 'idea', 'out', 'confirm'),
      edge('e2', 'confirm', 'approve', 'draft'),
      edge('e3', 'draft', 'out', 'report'),
    ],
    joins: {},
    budget: null,
  },
}

/**
 * Three branches at once, and the one line that decides whether they are waited for.
 *
 * The shape exists to make `joins` legible. `score` has three predecessors, and
 * without `joins.score` it fires on whichever branch answers FIRST - a run that
 * completes, produces a body, and scored one third of the evidence with nothing
 * on screen to say so. With it, the run waits. That single key is the whole
 * lesson, which is why this is a template rather than a paragraph.
 *
 * Measured: `valid: true`, 4 billable / 1 escalation / 0 cycles,
 * `static_cost_usd $0.6078`.
 */
export const FAN_OUT_JOIN: BuilderTemplate = {
  id: 'fan-out-join',
  title: 'Fan out and join',
  blurb: 'Three branches run in parallel and one node waits for all of them.',
  document: {
    schema: BUILDER_SCHEMA_ID,
    id: UNSAVED,
    name: 'Fan out and join',
    version: 1,
    input_field: nodeId('idea'),
    nodes: FAN_OUT_NODES,
    edges: [
      edge('e1', 'idea', 'out', 'confirm'),
      edge('e2', 'confirm', 'approve', 'brief'),
      edge('e3', 'brief', 'out', 'market'),
      edge('e4', 'brief', 'out', 'signal'),
      edge('e5', 'brief', 'out', 'build'),
      edge('e6', 'market', 'out', 'score'),
      edge('e7', 'signal', 'out', 'score'),
      edge('e8', 'build', 'out', 'score'),
      edge('e9', 'score', 'out', 'report'),
    ],
    // The point of the template. `'all'` waits; deleting the key is OR.
    joins: { score: 'all' },
    budget: null,
  },
}

export const IDEA_VALIDATOR: BuilderTemplate = {
  id: 'idea-validator',
  title: 'Idea validator',
  blurb: 'Six agents, two human gates, two revise loops — the evaluator, drawn.',
  caveat: IDEA_VALIDATOR_CAVEAT,
  document: IDEA_VALIDATOR_DOCUMENT,
}

/**
 * The gallery's four cards, in the order they are shown.
 *
 * Ordered by how much a reader has to understand before the card helps them:
 * nothing, one rule, one hard rule, then the whole product. Not by size, and
 * not alphabetically - the flagship last is deliberate, because a gallery that
 * opens on the biggest graph teaches an author that the builder is for
 * transcribing something rather than for drawing.
 */
export const BUILDER_TEMPLATES: readonly BuilderTemplate[] = [
  BLANK,
  MINIMAL_GATED_AGENT,
  FAN_OUT_JOIN,
  IDEA_VALIDATOR,
]

/**
 * A fresh, unshared copy of a template's document.
 *
 * `structuredClone`, and it is load-bearing rather than defensive. These four
 * documents are module singletons: seeding one into the store by reference
 * would put the SAME object behind the editor twice in one session, so a graph
 * the author edited, undid and abandoned would still be what the gallery hands
 * the next person who clicks the card. `commit` replaces rather than mutates,
 * which makes that safe most of the time - and "most of the time" is not a
 * property worth relying on for the thing every session starts from.
 */
export function documentFromTemplate(template: BuilderTemplate): BuilderDocument {
  return structuredClone(template.document)
}
