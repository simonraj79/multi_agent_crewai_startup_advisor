import { BUILDER_SCHEMA_ID, documentId, edgeId, nodeId } from '../types/builder'
import type { BuilderDocument, BuilderEdge, BuilderNode } from '../types/builder'
import { IDEA_VALIDATOR_CAVEAT, IDEA_VALIDATOR_DOCUMENT } from './templates/ideaValidator'
import { NEWS_TO_SOCIAL_CAVEAT, NEWS_TO_SOCIAL_DOCUMENT } from './templates/newsToSocial'
import { CONDITIONAL_ROUTER_DOCUMENT } from './templates/conditionalRouter'
import { HIERARCHICAL_DELEGATION_DOCUMENT } from './templates/hierarchicalDelegation'
import { REFLECTION_LOOP_DOCUMENT } from './templates/reflectionLoop'
import { SEQUENTIAL_PIPELINE_DOCUMENT } from './templates/sequentialPipeline'
import { resolveModelRoles } from './templates/modelRoles'

/**
 * The graphs the gallery opens with, as code.
 *
 * Template AUTHORING is cut (cut list item 12): there is no "save as template",
 * no template store and no server route, and these are literals a contributor
 * edits. That is the honest shape at this size, and the reason it stays honest
 * is that a template is not a special kind of document - `TemplateGallery`
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
 * A MODEL ID IS THE ONE THING THEY DO NOT NAME. The four pattern templates say
 * `{{workhorse}}` and `{{cheapest}}` and `{{escalation}}`, resolved against the
 * served roster at the moment a card is clicked - see `templates/modelRoles.ts`
 * for why a slug written here would be wrong, silently, the first time
 * `scripts/refresh_models.py` runs.
 *
 * EVERY ONE VALIDATES, and that is a measurement rather than a claim: each
 * template carries a Python-generated fixture under
 * `frontend/tests/fixtures/templates/`, regenerated and byte-compared by
 * `tests/builder/test_client_fixtures.py`, and `frontend/tests/templates.spec.ts`
 * asserts each document is the one the recorded answer answered. `BLANK`
 * deliberately has no billable node - see its own note.
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
   * What opening this teaches, in one sentence, rendered on the card.
   *
   * Required rather than optional, and that is the whole point of the field: a
   * gallery of graphs is a gallery of pictures, and a picture of a flow does
   * not say why one would draw it. An author choosing between six cards is
   * choosing between six ideas, not six shapes.
   */
  readonly teaches: string
  /**
   * The one edit to make first, rendered on the card.
   *
   * The gauntlet's first rubric dimension is clicks and confusion from landing
   * to a first node placed, and the honest answer for a template is that the
   * first thing you do is not place a node - it is change one field on a graph
   * that already runs. Naming which field is the difference between a starting
   * point and something to read.
   */
  readonly modifyFirst: string
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
 * The run's beginning and its end, wired, and ZERO problems (02-canvas.md D7).
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
 * WHY TWO NODES AND NOT ONE. D7 and criterion 10 each say "one `input` node"
 * AND "zero problems", and only one shape satisfies both - which is why the
 * reading here is "exactly one node OF KIND input", not "exactly one node".
 * Measured against this build's own `/api/builder/validate` on 2026-09-04:
 *
 *   one input alone                -> 1 problem, `no-output-node` (warning)
 *   input + output + the edge      -> 0 problems
 *
 * `no-output-node` is the server saying a completed run would hand back no
 * body, and it is right: a graph that ends nowhere produces nothing an operator
 * can read. Seeding the output is not inventing a decision any more than
 * seeding the input was - every graph this product compiles has both ends, and
 * `document.py` gives `input` no target port and `output` no source port
 * precisely because they ARE the ends.
 *
 * Landing to first node placed is now ONE click - the template card.
 */
const BLANK_INPUT_FIELD = nodeId('idea')

export const BLANK: BuilderTemplate = {
  id: 'blank',
  title: 'Blank canvas',
  blurb: 'An input and an output, wired and clean. Drag a kind from the palette, or press 1–7.',
  teaches:
    'Where a run begins and where its body comes back, and that both ends already exist.',
  modifyFirst: 'Drop an agent between the two nodes and connect it. Nothing else is needed.',
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
      {
        id: nodeId('result'),
        label: 'Result',
        // Directly below the input, on the 20 grid, so the first kind an author
        // drops between them has somewhere obvious to land.
        position: { x: 100, y: 300 },
        kind: 'output',
        config: {
          // `RUN_RESULT_BODY_KEYS[0]`. A body written under any other key comes
          // back clipped by the streaming frame serializer rather than by
          // `MAX_RUN_RESULT_BODY_CHARS`, which is how the first paid run's
          // report was lost mid-link.
          body_key: 'markdown_body',
          source: null,
        },
      },
    ],
    edges: [
      {
        id: edgeId('e1'),
        source: nodeId('idea'),
        source_port: 'out',
        target: nodeId('result'),
        target_port: 'in',
      },
    ],
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
  teaches:
    'Why a gate sits above the first agent: while nobody is signed in, human inaction is the spend cap.',
  modifyFirst: "The agent's prompt inputs, which are what the scoping task interpolates.",
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
  teaches:
    'That one line — joins — decides whether a node waits for its branches or runs on the first home.',
  modifyFirst: "Delete the joins key and watch the score node fire on one branch out of three.",
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
  teaches:
    'What a real pipeline looks like at full size: six agents, two gates and two revise loops.',
  modifyFirst: 'The scope gate’s editable fields, which are what an operator may change mid-run.',
  caveat: IDEA_VALIDATOR_CAVEAT,
  document: IDEA_VALIDATOR_DOCUMENT,
}

/**
 * The five PATTERN templates - agents this repository does not own the prompts
 * for, models named by role, and one lesson each.
 *
 * The two older templates above are built out of LIBRARY agents, whose role,
 * goal and task are fixed in `crews/validator_crew/config/*.yaml`. That makes
 * them excellent proofs that the compiler works and poor teachers: a new author
 * opening one sees six dropdown choices rather than a team they could have
 * written. These five are authored end to end, so every prompt on the canvas is
 * a prompt the author may edit, which is what the builder is for.
 */
export const SEQUENTIAL_PIPELINE: BuilderTemplate = {
  id: 'sequential-pipeline',
  title: 'Sequential pipeline',
  blurb: 'Research, analyse, write — three agents in a line with a keyless search attached.',
  teaches:
    'That an edge is a listener, ${state.out__x} is how one step reaches the next, and a tool is dropped onto an agent.',
  modifyFirst: "The writer's expected output. One sentence there changes the whole deliverable.",
  document: SEQUENTIAL_PIPELINE_DOCUMENT,
}

/**
 * The smallest graph in the gallery that still does a whole job.
 *
 * It sits after `sequential-pipeline` rather than before it because the line of
 * three is what teaches the syntax, and this is what an author does with the
 * syntax an hour later. It is the only pattern template with NO gate, which is
 * a decision its caveat states rather than a shape it inherited - see
 * `templates/newsToSocial.ts`.
 */
export const NEWS_TO_SOCIAL: BuilderTemplate = {
  id: 'news-to-social',
  title: 'News to social post',
  blurb: 'Search this week’s discussion of a topic and write the post about it.',
  teaches:
    'That two agents and one tool are a whole product, and that a graph with no gate runs unattended for whoever is signed in.',
  modifyFirst: 'The subject. One box, everything downstream changes, nothing else has to.',
  caveat: NEWS_TO_SOCIAL_CAVEAT,
  document: NEWS_TO_SOCIAL_DOCUMENT,
}

export const CONDITIONAL_ROUTER: BuilderTemplate = {
  id: 'conditional-router',
  title: 'Conditional router',
  blurb: 'Classify a message, send it to one of three desks, and converge again.',
  teaches:
    'That a router is arithmetic rather than a model, and that the cheap tier belongs where the decision is small.',
  modifyFirst:
    "The classifier's model. Swap it for the escalation one and watch the meter move for one word.",
  document: CONDITIONAL_ROUTER_DOCUMENT,
}

export const REFLECTION_LOOP: BuilderTemplate = {
  id: 'reflection-loop',
  title: 'Reflection loop',
  blurb: 'A drafter and a critic go round until the score clears 8, or four drafts in.',
  teaches:
    'That only a router may close a loop, and that output_schema is what turns prose into a number one can compare.',
  modifyFirst: 'The threshold 8. It is the only thing deciding how long this runs.',
  document: REFLECTION_LOOP_DOCUMENT,
}

export const HIERARCHICAL_DELEGATION: BuilderTemplate = {
  id: 'hierarchical-delegation',
  title: 'Hierarchical delegation',
  blurb: 'A manager and three specialists, inside one crew node.',
  teaches:
    'That a crew node is a real Crew whose members are agents it owns, wired by member edges rather than flow edges.',
  modifyFirst:
    'The process. Flip it to sequential and the manager leaves the inspector and the price together.',
  document: HIERARCHICAL_DELEGATION_DOCUMENT,
}

/**
 * The gallery's seven cards, in the order they are shown.
 *
 * Ordered by how much a reader has to understand before the card helps them:
 * nothing, one line, one line put to work, one fork, one loop, one team, then
 * the whole product. Not by size and not alphabetically - the flagship last is
 * deliberate, because a gallery that opens on the biggest graph teaches an
 * author that the builder is for transcribing something rather than for
 * drawing.
 *
 * `news-to-social` is SMALLER than `sequential-pipeline` and still sits after
 * it, which is the ordering rule doing its job rather than an exception to it:
 * the line of three is where the syntax is explained, and the news graph is
 * what somebody builds once they have it. It also carries one idea neither of
 * its neighbours does - a graph with no gate - and that is a thing to meet
 * second rather than first.
 */
export const BUILDER_TEMPLATES: readonly BuilderTemplate[] = [
  BLANK,
  SEQUENTIAL_PIPELINE,
  NEWS_TO_SOCIAL,
  CONDITIONAL_ROUTER,
  REFLECTION_LOOP,
  HIERARCHICAL_DELEGATION,
  IDEA_VALIDATOR,
]

/**
 * The two library-agent templates, kept and demoted rather than deleted.
 *
 * Owner's decision 21, and the reason is not sentiment: `e2e/builder.spec.ts`
 * drives `MINIMAL_GATED_AGENT` through the whole authoring journey, so deleting
 * it would turn a template change into a suite change and lose the only E2E
 * proof that a LIBRARY-agent graph still publishes. They sit in a second row
 * because what they teach - that the compiler works - is not what a first-time
 * author needs from a gallery.
 */
export const MORE_BUILDER_TEMPLATES: readonly BuilderTemplate[] = [
  MINIMAL_GATED_AGENT,
  FAN_OUT_JOIN,
]

/** Every card the gallery renders, both rows, in render order. */
export const ALL_BUILDER_TEMPLATES: readonly BuilderTemplate[] = [
  ...BUILDER_TEMPLATES,
  ...MORE_BUILDER_TEMPLATES,
]

/**
 * A fresh, unshared copy of a template's document, with its model roles resolved.
 *
 * `structuredClone`, and it is load-bearing rather than defensive. These
 * documents are module singletons: seeding one into the store by reference
 * would put the SAME object behind the editor twice in one session, so a graph
 * the author edited, undid and abandoned would still be what the gallery hands
 * the next person who clicks the card. `commit` replaces rather than mutates,
 * which makes that safe most of the time - and "most of the time" is not a
 * property worth relying on for the thing every session starts from.
 *
 * THE CLONE IS ALSO WHAT MAKES ROLE RESOLUTION SAFE. `resolveModelRoles`
 * rewrites `{{workhorse}}` into the id the roster names today, in place - so it
 * must never see the singleton, or the second caller would get a document whose
 * models were resolved against a roster that has since been refreshed. Cloning
 * first means every seeded copy is resolved exactly once, against the roster as
 * it stands at the moment the author clicked.
 *
 * A role the roster cannot answer is LEFT AS ITS TOKEN rather than substituted,
 * which is `data/models.ts`'s rule rather than a new one: the server answers
 * `model-unknown` naming the token, in the problems dock, beside the roster
 * failure the gallery is already showing.
 */
export function documentFromTemplate(template: BuilderTemplate): BuilderDocument {
  return resolveModelRoles(structuredClone(template.document))
}
