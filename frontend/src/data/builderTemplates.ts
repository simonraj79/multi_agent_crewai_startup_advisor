import { BUILDER_SCHEMA_ID, documentId, edgeId, nodeId } from '../types/builder'
import type { TemplateCategoryId } from './templateCategories'
import type { BuilderDocument, BuilderEdge, BuilderNode } from '../types/builder'
import { IDEA_VALIDATOR_CAVEAT, IDEA_VALIDATOR_DOCUMENT } from './templates/ideaValidator'
import { NEWS_TO_SOCIAL_CAVEAT, NEWS_TO_SOCIAL_DOCUMENT } from './templates/newsToSocial'
import {
  CONDITIONAL_ROUTER_CAVEAT,
  CONDITIONAL_ROUTER_DOCUMENT,
} from './templates/conditionalRouter'
import { FALLBACK_BAR_CAVEAT, FALLBACK_BAR_DOCUMENT } from './templates/fallbackBar'
import {
  HIERARCHICAL_DELEGATION_CAVEAT,
  HIERARCHICAL_DELEGATION_DOCUMENT,
} from './templates/hierarchicalDelegation'
import { REFLECTION_LOOP_DOCUMENT } from './templates/reflectionLoop'
import { SEQUENTIAL_PIPELINE_DOCUMENT } from './templates/sequentialPipeline'
import { SINGLE_AGENT_DOCUMENT } from './templates/singleAgent'
import { TIERED_ROUTING_DOCUMENT } from './templates/tieredRouting'
import { VOTE_REVIEW_DOCUMENT } from './templates/voteReview'
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

/**
 * Where a pattern's name comes from.
 *
 * `both` when Anthropic's whitepaper and Google's design-pattern guide name the
 * same shape (routing / tiered routing; parallelization / parallel); `none` for
 * the two scaffolds that are not patterns at all (`blank`, the gated minimum).
 * The provenance is rendered in the card's pattern line and nowhere else (D5).
 */
export type PatternSource = 'anthropic' | 'google' | 'both' | 'none'

/** The pattern a card is an instance of, named the way the literature names it. */
export interface TemplatePattern {
  /** The name the card carries: "Routing", "Evaluator-optimizer", "Single agent". */
  readonly name: string
  readonly source: PatternSource
  /** The other name the same shape goes by, when the two sources disagree ("Google calls this tiered routing"). */
  readonly aka?: string
}

/** One template card, and the document behind it. */
export interface BuilderTemplate {
  /** Stable across renames; the gallery keys its cards and its tests on it. */
  readonly id: string
  readonly title: string
  /** One sentence on the card. What you get, not what it is called. ≤ 140 characters, asserted in Python. */
  readonly blurb: string
  /**
   * The gallery section this card sits in (`data/templateCategories.ts`).
   *
   * A closed union, and the gallery derives its sections from it rather than
   * from a hand-kept list, so a card cannot be in two sections or in none.
   * `tests/builder/test_templates.py` asserts every category has a card and
   * that gallery order equals category order.
   */
  readonly category: TemplateCategoryId
  /** The pattern this card is an instance of, and who calls it that. */
  readonly pattern: TemplatePattern
  /**
   * The job, narrated: who, what arrives, what goes out. ≤ 240 characters.
   *
   * This is the field the owner asked for by name: a template tied to an
   * authentic use case rather than to a concept. It is the second thing on
   * the card after the title, because "what would I use this for" is the
   * first question a person browsing has.
   */
  readonly useCase: string
  /** When to reach for this shape, grounded in the sources' own decision rules. ≤ 170 characters. */
  readonly useWhen: string
  /** When NOT to, from the same rules. ≤ 170 characters. */
  readonly notWhen: string
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
  blurb: 'An input and an output, wired and clean. Drag a kind from the palette, or press 1 to 7.',
  category: 'start',
  // `none`, and it is the honest answer rather than a missing one: an empty
  // canvas is scaffolding. A card that claimed a pattern here would be the
  // first thing a new author read and the first thing that was not true.
  pattern: { name: 'Empty canvas', source: 'none' },
  useCase:
    'You know what you want to build and would rather draw it than start from somebody else’s. This is the two ends of a run, already connected, with nothing in between.',
  useWhen:
    'You have the shape in your head already, or you are learning what each kind of node does by putting one down.',
  notWhen:
    'You are new here. One of the working examples below is closer to what you want than an empty page is.',
  teaches:
    'Where a run begins and where its body comes back, and that both ends already exist.',
  modifyFirst: 'Drop an agent between the two nodes and connect it. Nothing else is needed.',
  document: {
    schema: BUILDER_SCHEMA_ID,
    id: UNSAVED,
    name: 'Untitled workflow',
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
  blurb: 'Input, a human gate, one agent, one result. The smallest workflow anyone can launch.',
  category: 'start',
  // Also `none`. This is a policy demonstration rather than a pattern: what it
  // exists to show is the 403 an ungated published workflow answers, which is a
  // rule of this service and not a shape either source names.
  pattern: { name: 'Smallest run', source: 'none' },
  useCase:
    'You want to prove the plumbing before you build anything on it: that a run starts, pauses for a person, spends once, and hands a body back.',
  useWhen:
    'You are checking that publishing, launching and approving work end to end, or you want the fewest moving parts to change.',
  notWhen:
    'You want something that does a real job. This one is a proof that the machinery runs, not a piece of work.',
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

/**
 * What the card must say, word for word (R14).
 *
 * Two facts, and a reader of the picture would guess wrong about both. Four is
 * a hard ceiling rather than a suggestion, and it is the one bound that
 * deliberately did NOT move when the others were raised, because it bounds
 * concurrent threads and a third-party rate limit rather than money. And the
 * branches are blind to each other by construction: each one's prompt names
 * what came before the fan-out, and there is no moment at which one could read
 * another, because they are running at the same time.
 */
export const FAN_OUT_JOIN_CAVEAT =
  'Four branches is the ceiling, and it is the one bound here that was left '
  + 'where it was on purpose: it caps concurrent work rather than spend. The '
  + 'branches also cannot see each other. Each reads what came before the fan '
  + 'out and nothing a sibling produced, because they are running at the same '
  + 'time.'

export const FAN_OUT_JOIN: BuilderTemplate = {
  id: 'fan-out-join',
  title: 'Fan out and join',
  blurb: 'Three branches run at the same time and one node waits for all of them.',
  category: 'parallel',
  pattern: { name: 'Parallelization', source: 'both', aka: 'Sectioning' },
  useCase:
    'An analyst wants three readings of one idea at once: the market, the sentiment and what it would take to build. One node waits for all three and scores what they found together.',
  useWhen:
    'The pieces of work do not need each other, and you would rather pay for three at once than wait for three in turn.',
  notWhen:
    'One branch needs another branch’s answer, or you have no rule for combining three answers that disagree.',
  teaches:
    'Parallelization by sectioning: one line, joins, decides whether a node waits for its branches or runs on the first one home.',
  modifyFirst: "Delete the joins key and watch the score node fire on one branch out of three.",
  caveat: FAN_OUT_JOIN_CAVEAT,
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
  blurb: 'Six agents, two human gates, two revise loops. The evaluator, drawn.',
  category: 'team',
  // Not orchestrator-workers, though it sits on that shelf. It is a chain, a
  // fan-out, two review loops and two human gates in one document, which is
  // the pattern Anthropic's catalogue calls a hybrid architecture and the one
  // most real pipelines turn out to be. Claiming a single pattern here would
  // be the neatest sentence and the wrong one.
  pattern: { name: 'Hybrid architecture', source: 'anthropic' },
  useCase:
    'A founder wants an idea checked. It is scoped with a person’s approval, researched three ways at once, scored against a rubric, and written up once a person has agreed the verdict.',
  useWhen:
    'You want to see what a full size pipeline looks like before drawing your own, or you want this one’s shape as a starting point.',
  notWhen:
    'You want its judgement. The scoring that makes the real validator worth reading is in code, not on this canvas.',
  teaches:
    'Hybrid architecture, at full size: a chain, a fan-out, two review loops and two human gates in one document.',
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
  blurb: 'Research, analyse, write. Three agents in a line with a keyless search attached.',
  category: 'chain',
  pattern: { name: 'Prompt chaining', source: 'both', aka: 'Sequential' },
  useCase:
    'A content team turns a topic into a briefing. One agent gathers sources, a second says what they mean together, and a third writes the piece the other two fed.',
  useWhen:
    'The work has stages and each one genuinely needs the last one’s result. Splitting it makes every call an easier call.',
  notWhen:
    'The steps do not depend on each other. A line of independent steps is a slower way to do them side by side.',
  teaches:
    'Prompt chaining, in this builder’s own syntax: an edge is a listener, ${state.out__x} is how one step reaches the next, and a tool is dropped onto an agent.',
  modifyFirst: "The writer's expected output. One sentence there changes the whole deliverable.",
  document: SEQUENTIAL_PIPELINE_DOCUMENT,
}

/**
 * One worker, one tool, one answer, and it is the card both sources say to
 * read first.
 *
 * It sits second rather than first because `blank` is the empty state, and
 * before `sequential-pipeline` because a line of three is what somebody draws
 * once one box has stopped being enough. `templates/singleAgent.ts` carries
 * the reasoning and the measured price.
 */
export const SINGLE_AGENT: BuilderTemplate = {
  id: 'single-agent',
  title: 'Single agent',
  blurb: 'One agent with one search tool answers a question and shows where the answer came from.',
  category: 'start',
  pattern: { name: 'Single agent', source: 'both', aka: 'Single-agent system' },
  useCase:
    'A help desk gets a product question. One agent decides what to search for, reads what comes back, decides whether that was enough, and writes a reply with the pages it used.',
  useWhen:
    'The job is one job and it needs a tool to do it. Start here, and add structure only when one worker has stopped being enough.',
  notWhen:
    'One model call with no tool would do it, or this worker has quietly grown several unrelated responsibilities.',
  teaches:
    'Single agent, the shape to start from: one worker, one tool, and a loop inside one box that no picture can show.',
  modifyFirst:
    'The backstory. It is the whole of what this agent is, and rewriting it in your own voice changes every answer.',
  document: SINGLE_AGENT_DOCUMENT,
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
  category: 'chain',
  pattern: { name: 'Prompt chaining', source: 'both', aka: 'Sequential' },
  useCase:
    'A marketer needs today’s post about a subject. One agent finds what has actually been said in the last week, and a second writes the short and long versions with the links in.',
  useWhen:
    'Two steps are enough and the second needs the first. It is the smallest chain that still ships something you would send.',
  notWhen:
    'Somebody has to approve it before it runs. This one carries no gate, so only a signed-in caller may launch it at all.',
  teaches:
    'Prompt chaining at two nodes: two agents and one tool are a whole product, and a workflow with no gate runs unattended for whoever is signed in.',
  modifyFirst: 'The subject. One box, everything downstream changes, nothing else has to.',
  caveat: NEWS_TO_SOCIAL_CAVEAT,
  document: NEWS_TO_SOCIAL_DOCUMENT,
}

export const CONDITIONAL_ROUTER: BuilderTemplate = {
  id: 'conditional-router',
  title: 'Conditional router',
  blurb: 'Classify a message, send it to one of three desks, and converge again.',
  category: 'route',
  pattern: { name: 'Routing', source: 'both', aka: 'Coordinator' },
  useCase:
    'A support inbox takes anything. One cheap classifier reads the message, one of three specialists answers it, and whichever one ran is what comes back.',
  useWhen:
    'Requests fall into kinds that want different handling, and the kinds are distinct enough that a classifier can tell them apart.',
  notWhen:
    'Every request wants the same handling. A classifier that always answers the same way is a call you pay for and never use.',
  teaches:
    'Routing, and the two facts behind it: a router is arithmetic rather than a model, and the cheap tier belongs where the decision is small.',
  modifyFirst:
    "The classifier's model. Swap it for the escalation one and watch the meter move for one word.",
  caveat: CONDITIONAL_ROUTER_CAVEAT,
  document: CONDITIONAL_ROUTER_DOCUMENT,
}

/**
 * The rule tier, which is the only card in the gallery that answers anybody
 * without a model. `templates/tieredRouting.ts` carries the reasoning.
 */
export const TIERED_ROUTING: BuilderTemplate = {
  id: 'tiered-routing',
  title: 'Tiered routing',
  blurb: 'The easy tickets answered with no model at all, and the rest sorted by the cheapest one.',
  category: 'route',
  pattern: { name: 'Tiered routing', source: 'google', aka: 'Routing' },
  useCase:
    'A support team is paying top prices for password resets. A phrase list answers those for nothing, a one word classifier sizes what is left, and only the hard ones reach the model that thinks.',
  useWhen:
    'You have looked at your own traffic and the easy questions dominate it. Checking that distribution is the step before buying a bigger model.',
  notWhen:
    'You have not measured, or the traffic is uniformly hard. Then a classifier is a stage added to every request that removes none.',
  teaches:
    'Tiered routing, drawn in three: a contains match on the raw text costs nothing, a classifier costs one word, and only what survives both reaches the model that thinks. A contains match is a substring test, not a regular expression, and it is case-sensitive.',
  modifyFirst:
    'The two phrases on the rule branches. They are the whole of tier one, and they are the only edit here that saves money.',
  document: TIERED_ROUTING_DOCUMENT,
}

export const REFLECTION_LOOP: BuilderTemplate = {
  id: 'reflection-loop',
  title: 'Reflection loop',
  blurb: 'A drafter and a critic go round until the score clears 8, or four drafts in.',
  category: 'review',
  pattern: { name: 'Evaluator-optimizer', source: 'both', aka: 'Review and critique' },
  useCase:
    'A writer needs a draft that is actually good. One agent writes, another scores it out of ten and says what to fix, and the loop closes when the score is high enough.',
  useWhen:
    'You can write down what good looks like, and a second pass reliably improves the first. Clear criteria are the precondition.',
  notWhen:
    'The first attempt already meets the requirement, the criteria are a matter of taste, or the wait and the cost matter more than the polish.',
  teaches:
    'Evaluator-optimizer, closed properly: only a router may close a loop, and output_schema is what turns prose into a number one can compare.',
  modifyFirst: 'The threshold 8. It is the only thing deciding how long this runs.',
  document: REFLECTION_LOOP_DOCUMENT,
}

/**
 * A second model when the first is down, and one checker that reads both.
 * `templates/fallbackBar.ts` carries the three facts its caveat states.
 */
export const FALLBACK_BAR: BuilderTemplate = {
  id: 'fallback-bar',
  title: 'Fallback that clears the bar',
  blurb: 'A second model takes over when the first is overloaded, and the same checker reads both.',
  category: 'review',
  pattern: { name: 'Same-bar fallback', source: 'google' },
  useCase:
    'A reply has to go out today and the usual model is failing under load. The answerer waits, retries, runs its last attempt on another model, and one checker reads whatever came back.',
  useWhen:
    'Somebody will act on the output, you already have a check it must pass, and a plausible wrong answer would be worse than a slow one.',
  notWhen:
    'There is no check to share. Then this is a retry with a second model rather than a bar, and the standard quietly drops when it fires.',
  teaches:
    'Same-bar fallback, made structural: the retry re-runs the same task with one field swapped, so the checker downstream cannot tell which model wrote what it is reading.',
  modifyFirst:
    'max_retries on the answerer. Set it to 0 and the fallback below it stops meaning anything at all.',
  caveat: FALLBACK_BAR_CAVEAT,
  document: FALLBACK_BAR_DOCUMENT,
}

export const HIERARCHICAL_DELEGATION: BuilderTemplate = {
  id: 'hierarchical-delegation',
  title: 'Hierarchical delegation',
  blurb: 'A manager and three specialists, inside one crew node.',
  category: 'team',
  pattern: {
    name: 'Orchestrator-workers',
    source: 'both',
    aka: 'Hierarchical task decomposition',
  },
  useCase:
    'A brief is too broad for one worker. A manager decides who does what and in which order, three specialists do it, and the manager assembles what comes back.',
  useWhen:
    'The job is open ended enough that you cannot write the steps down in advance, and the result is worth paying a lead to reason about every hand-off.',
  notWhen:
    'You already know the sub-tasks and their order. A line or a fan-out does the same work without paying a lead to rediscover it.',
  teaches:
    'Orchestrator-workers, inside one box: a crew node is a real Crew whose members are agents it owns, wired by member edges rather than flow edges.',
  modifyFirst:
    'The process. Flip it to sequential and the manager leaves the inspector and the price together.',
  caveat: HIERARCHICAL_DELEGATION_CAVEAT,
  document: HIERARCHICAL_DELEGATION_DOCUMENT,
}

/**
 * Three reviewers on one draft, and a threshold. `templates/voteReview.ts`
 * carries the reasoning and the measured price.
 */
export const VOTE_REVIEW: BuilderTemplate = {
  id: 'vote-review',
  title: 'Vote before it ships',
  blurb: 'Three reviewers read the same draft at once, and two have to agree before it ships.',
  category: 'parallel',
  pattern: { name: 'Voting', source: 'anthropic', aka: 'Parallelization' },
  useCase:
    'A team is about to publish an announcement. Three reviewers read it side by side for accuracy, tone and policy, a fourth counts the approvals, and two out of three sends it.',
  useWhen:
    'Several perspectives raise your confidence more than one long check would, and you want a threshold you can move.',
  notWhen:
    'One reviewer is enough, or the reviewers would have to read each other to be useful. That is a chain wearing this shape.',
  teaches:
    'Voting, which is parallelization doing the same job three times: the branches are independent, and a transform cannot count, so the tally is a model call.',
  modifyFirst: 'The threshold 2. Move it to 3 and only a clean sweep publishes.',
  document: VOTE_REVIEW_DOCUMENT,
}

/**
 * The gallery's thirteen cards, in the order they are shown: D2's order, which
 * is `templateCategories.ts`'s order with the cards of each category together.
 *
 * WHAT REPLACED THE OLD ORDERING RULE, AND WHY. Plan 14 D7 ordered these by
 * how much a reader had to understand before the card helped them - nothing,
 * one line, one line put to work, one fork, one loop, one team, then the whole
 * product. That is a good order for somebody learning the BUILDER and the
 * wrong one for somebody who arrived with a job, because it indexes on the
 * shape of the drawing rather than on the question being asked. The categories
 * index on the question, and inside a category the old rule survives intact:
 * `blank` before `single-agent` before the gated minimum, the line of three
 * before the two-node chain, the classifier before the rule tier.
 *
 * TWO POSITIONS ARE STILL DECISIONS RATHER THAN CONSEQUENCES, and both are the
 * ones plan 14 fixed. `blank` is first, because the first thing a new author
 * sees should not be somebody else's finished work. `idea-validator` is last,
 * because a gallery that opens on the biggest document teaches an author that
 * the builder is for transcribing something rather than for drawing.
 * `tests/builder/test_templates.py` asserts both by name.
 *
 * THE SECOND ROW IS GONE. `MORE_BUILDER_TEMPLATES` held `minimal-gated-agent`
 * and `fan-out-join` in a demoted row, on the argument that what they teach -
 * that the compiler works over LIBRARY agents - is not what a first-time
 * author needs. Owner's decision 21's RULE was never to delete them, and that
 * stands: both are here, `e2e/builder.spec.ts` still drives
 * `minimal-gated-agent` through the whole authoring journey, and nothing has
 * been removed. What has gone is the PLACEMENT, and the reason is that
 * `fan-out-join` is the cleanest expression of parallelization in the gallery
 * and it was behind a disclosure triangle, which is not where the pattern a
 * reader came looking for should be.
 */
export const BUILDER_TEMPLATES: readonly BuilderTemplate[] = [
  // start
  BLANK,
  SINGLE_AGENT,
  MINIMAL_GATED_AGENT,
  // chain
  SEQUENTIAL_PIPELINE,
  NEWS_TO_SOCIAL,
  // route
  CONDITIONAL_ROUTER,
  TIERED_ROUTING,
  // parallel
  FAN_OUT_JOIN,
  VOTE_REVIEW,
  // review
  REFLECTION_LOOP,
  FALLBACK_BAR,
  // team
  HIERARCHICAL_DELEGATION,
  IDEA_VALIDATOR,
]

/**
 * Every card the gallery renders, in render order.
 *
 * An ALIAS since the second row was retired, and kept rather than replaced
 * because five files outside this module import it and the distinction it once
 * drew - all the cards, versus the first row's cards - is now a distinction
 * with no difference. A consumer that means "every template" should keep
 * saying so.
 */
export const ALL_BUILDER_TEMPLATES: readonly BuilderTemplate[] = BUILDER_TEMPLATES

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
