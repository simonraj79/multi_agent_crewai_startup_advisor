import { BUILDER_SCHEMA_ID, documentId, nodeId } from '../../types/builder'
import type { BuilderDocument } from '../../types/builder'
import {
  authoredAgent,
  branch,
  flowEdge,
  gateNode,
  inputNode,
  out,
  outKey,
  outputNode,
  routerNode,
  stateRef,
  transformNode,
} from './authoring'

/**
 * Three reviewers read the same draft at the same time, and two have to agree.
 *
 * A communications team is about to publish an announcement. Three reviewers
 * read it side by side, each briefed on one thing and blind to the other two:
 * is it accurate, does it sound like us, does it break a rule. A fourth counts
 * the approvals. Two out of three ships it; anything less holds it with every
 * objection attached.
 *
 * THIS IS THE OTHER HALF OF PARALLELISATION, and it is not the half
 * `fan-out-join` teaches. There, three branches do three DIFFERENT pieces of
 * work and one node assembles them. Here, three branches do the SAME work
 * under different instructions, and the disagreement is the product. Anthropic
 * calls the first sectioning and the second voting, and gives voting its own
 * rule: use it for "evaluating content appropriateness with multiple prompts
 * using different vote thresholds to balance false positives and negatives".
 * The threshold is the dial, and it is one integer on the router below.
 *
 * FOUR THINGS IT TEACHES:
 *
 * 1. **Independence is what a vote is made of.** No reviewer reads another's
 *    verdict: each one's `prompt_inputs` names the draft and nothing else.
 *    Wire one reviewer's output into another and you have a chain wearing a
 *    vote's clothes, and the second reviewer will agree with the first.
 * 2. **A `transform` cannot count, so the tally is a model call.** The six
 *    operations are `pick`, `merge`, `join_text`, `to_json`, `default` and
 *    `format`; there is no arithmetic among them and no seventh escape hatch.
 *    Counting three verdicts is therefore the cheapest possible agent, on the
 *    roster's least expensive model, with one pass and an `output_schema` -
 *    and it is honest about being a call rather than pretending to be free.
 * 3. **`joins: 'all'` is what makes it a vote at all.** Without it `votes`
 *    fires on whichever reviewer answered first and the tally counts one
 *    opinion out of three, having paid for all three, with nothing on screen
 *    to say so.
 * 4. **The threshold fails towards holding.** `approvals >= 2` is the tested
 *    branch and `hold` is `otherwise`, so a tally whose answer could not be
 *    parsed scores null, fails `gte`, and holds the draft. Written the other
 *    way round the same null would publish it.
 *
 * WHY THE TWO OUTCOMES ARE `format` TRANSFORMS AND NOT AGENTS. Nothing needs
 * writing at the end: the draft already exists and the reviewers have already
 * said what is wrong with it. A fifth and sixth model call would restate what
 * is in front of it and would put the decision back into a model's hands after
 * a router had just taken it out of them. Both outcomes are string
 * substitution, they cost nothing, and they carry the reviews forward verbatim
 * so whoever reads the result sees what the three actually said.
 *
 * WHY `joins: 'any'` AT THE OUTCOME. Exactly one of the two ever runs, because
 * both descend from a router. Declared `'all'` this would wait for ever for
 * the branch that was never going to happen, and waiting is not failing, so
 * there would be no error to see.
 *
 * WHAT TO MODIFY FIRST: the threshold `2`. Move it to 3 and the announcement
 * ships only on a clean sweep; that is the false-positive dial the pattern is
 * named for, and it is one integer.
 *
 * Measured on this build, against `validate_document` and `estimate_budget`
 * over the dumped document: zero problems, 4 billable nodes, 0 escalation,
 * 0 cycles, 24 modelled calls, floor $0.0155, static $0.0155, which is $0.0193
 * with the 1.25x margin against the $10.00 ceiling. The CHEAPEST template in
 * the gallery that does any work at all, and it makes four model calls: every
 * one of them is one pass on the roster's least expensive row, and the two
 * outcomes and the two joins are string substitution.
 */

const REVIEW_EXPECTED =
  'An object with two keys: `verdict`, which is exactly APPROVE or REJECT, and `reason`, one sentence saying why.'

const NODES = [
  inputNode(
    'draft',
    'Draft',
    'What are you about to publish?',
    { x: 380, y: 0 },
  ),
  gateNode(
    'confirm',
    'Confirm the draft',
    'Three reviewers are about to read this at the same time. Approve the draft, or send it back.',
    { x: 380, y: 160 },
  ),
  authoredAgent({
    id: 'accuracy',
    label: 'Accuracy',
    position: { x: 80, y: 320 },
    role: 'Fact Checker',
    goal: 'Find the claims that are not true, and let the rest alone.',
    backstory:
      'You check announcements against what actually shipped. You care about numbers, dates and names, you have no view on the writing, and you would rather flag one real error than five things you would have phrased differently.',
    description:
      'Review the draft below for accuracy ONLY. Ignore tone and ignore policy; two colleagues are reading for those.\n\nREJECT if any claim is wrong, unverifiable as written, or more confident than the evidence supports. APPROVE otherwise.\n\nDRAFT:\n{draft}',
    expected: REVIEW_EXPECTED,
    model: 'cheapest',
    maxIter: 1,
    outputSchema: { verdict: 'string', reason: 'string' },
    // The draft, and nothing else. See lesson 1: a reviewer who could read
    // another reviewer's verdict would agree with it.
    promptInputs: { draft: stateRef('draft') },
  }),
  authoredAgent({
    id: 'tone',
    label: 'Tone',
    position: { x: 380, y: 320 },
    role: 'Brand Editor',
    goal: 'Say whether this sounds like us, in the voice we actually publish in.',
    backstory:
      'You have read every announcement this company has sent. You know the difference between plain and blunt, and between warm and salesy, and you can name which one a sentence is.',
    description:
      'Review the draft below for TONE ONLY. Ignore accuracy and ignore policy; two colleagues are reading for those.\n\nREJECT if it oversells, hedges into meaninglessness, or reads as though somebody else wrote it. APPROVE otherwise.\n\nDRAFT:\n{draft}',
    expected: REVIEW_EXPECTED,
    model: 'cheapest',
    maxIter: 1,
    outputSchema: { verdict: 'string', reason: 'string' },
    promptInputs: { draft: stateRef('draft') },
  }),
  authoredAgent({
    id: 'policy',
    label: 'Policy',
    position: { x: 680, y: 320 },
    role: 'Compliance Reviewer',
    goal: 'Catch the sentence that will have to be retracted.',
    backstory:
      'You read for what a regulator, a customer lawyer or a competitor would do with a sentence. You are not looking for reasons to say no; you are looking for the one line that commits somebody to something.',
    description:
      'Review the draft below for POLICY ONLY. Ignore accuracy and ignore tone; two colleagues are reading for those.\n\nREJECT if it names an unannounced customer, promises a date, states a performance figure without a qualifier, or compares us to a named competitor. APPROVE otherwise.\n\nDRAFT:\n{draft}',
    expected: REVIEW_EXPECTED,
    model: 'cheapest',
    maxIter: 1,
    outputSchema: { verdict: 'string', reason: 'string' },
    promptInputs: { draft: stateRef('draft') },
  }),
  transformNode(
    'votes',
    'The three reviews',
    'join_text',
    {
      accuracy: out('accuracy'),
      tone: out('tone'),
      policy: out('policy'),
    },
    { x: 380, y: 480 },
  ),
  authoredAgent({
    id: 'tally',
    label: 'Count the approvals',
    position: { x: 380, y: 640 },
    role: 'Returning Officer',
    goal: 'Count what the reviewers said, and add nothing to it.',
    backstory:
      'You count. You have no opinion about the draft, you do not reread it, and you never break a tie yourself.',
    description:
      'Below are three independent reviews, each carrying a `verdict` of APPROVE or REJECT.\n\nCount how many say APPROVE. Do not read the draft, do not weigh the reasons and do not change a verdict. Return the count, and the reasons from every review that said REJECT.\n\nREVIEWS:\n{reviews}',
    expected:
      'An object with two keys: `approvals`, a whole number 0 to 3, and `objections`, the REJECT reasons as one string, or an empty string when there were none.',
    model: 'cheapest',
    maxIter: 1,
    // The whole reason the router downstream can compare anything.
    outputSchema: { approvals: 'number', objections: 'string' },
    promptInputs: { reviews: out('votes') },
  }),
  transformNode(
    'approvals',
    'Approvals',
    'pick',
    { source: out('tally'), key: 'approvals' },
    { x: 180, y: 800 },
  ),
  transformNode(
    'objections',
    'Objections',
    'pick',
    { source: out('tally'), key: 'objections' },
    { x: 580, y: 800 },
  ),
  routerNode(
    'threshold',
    'Two out of three?',
    [
      // Tested first, and it is the SHIPPING branch. A tally that came back
      // unreadable scores null, `gte` is false for a null on either side, and
      // the draft falls to `hold`. See lesson 4.
      branch('ship', 'gte', outKey('approvals'), 2),
      branch('hold', 'otherwise'),
    ],
    { x: 380, y: 960 },
  ),
  transformNode(
    'approved',
    'Cleared to publish',
    'format',
    {
      template:
        'CLEARED TO PUBLISH: {count} of 3 reviewers approved.\n\nAnything still noted:\n{objections}\n\n---\n\n{draft}',
      count: out('approvals'),
      objections: out('objections'),
      draft: stateRef('draft'),
    },
    { x: 180, y: 1120 },
  ),
  transformNode(
    'blocked',
    'Held',
    'format',
    {
      template:
        'HELD: only {count} of 3 reviewers approved.\n\nWhat has to change:\n{objections}\n\n---\n\n{draft}',
      count: out('approvals'),
      objections: out('objections'),
      draft: stateRef('draft'),
    },
    { x: 580, y: 1120 },
  ),
  transformNode(
    'outcome',
    'Whichever way it went',
    'join_text',
    { approved: out('approved'), blocked: out('blocked') },
    { x: 380, y: 1280 },
  ),
  outputNode('decision', 'Decision', { x: 380, y: 1440 }),
]

export const VOTE_REVIEW_DOCUMENT: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: documentId('ug_00000000'),
  name: 'Vote before it ships',
  version: 1,
  input_field: nodeId('draft'),
  nodes: NODES,
  edges: [
    flowEdge('e1', 'draft', 'confirm'),
    flowEdge('e2', 'confirm', 'accuracy', 'approve'),
    flowEdge('e3', 'confirm', 'tone', 'approve'),
    flowEdge('e4', 'confirm', 'policy', 'approve'),
    flowEdge('e5', 'accuracy', 'votes'),
    flowEdge('e6', 'tone', 'votes'),
    flowEdge('e7', 'policy', 'votes'),
    flowEdge('e8', 'votes', 'tally'),
    flowEdge('e9', 'tally', 'approvals'),
    flowEdge('e10', 'tally', 'objections'),
    flowEdge('e11', 'approvals', 'threshold'),
    flowEdge('e12', 'objections', 'threshold'),
    flowEdge('e13', 'threshold', 'approved', 'ship'),
    flowEdge('e14', 'threshold', 'blocked', 'hold'),
    flowEdge('e15', 'approved', 'outcome'),
    flowEdge('e16', 'blocked', 'outcome'),
    flowEdge('e17', 'outcome', 'decision'),
  ],
  // Two joins, and they say opposite things for opposite reasons. `votes`
  // waits for all three reviewers, because a vote counted before everyone has
  // voted is not a vote. `threshold` waits for both picks off the tally, for
  // the reason `reflection-loop` states: undeclared, two arrivals whose
  // ancestors include a gate compile to alternatives. `outcome` fires on the
  // first arrival, because exactly one of its two ever runs.
  joins: { votes: 'all', threshold: 'all', outcome: 'any' },
  budget: null,
}
