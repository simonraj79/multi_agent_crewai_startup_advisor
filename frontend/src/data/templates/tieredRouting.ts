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
 * Three tiers, and the first one answers without a model at all.
 *
 * A support inbox. Most of what arrives is not a hard question: it is "reset my
 * password" and "where is my order", asked a hundred different ways. Those
 * should never reach a model, let alone the dear one. What is left gets one
 * very small call whose only job is to say how hard it is, and only what
 * survives both tiers reaches the model that can think.
 *
 * THIS IS THE LARGEST COST LEVER IN THE WHOLE GALLERY, and it is the one that
 * costs nothing to pull. Google measured a first pass of exactly this kind
 * handling more than forty per cent of incoming messages before a real model
 * call happened, and their instruction is to look at your own traffic before
 * assuming you need a bigger model. Everything else here is a way of spending
 * less on the traffic that is left.
 *
 * FOUR THINGS IT TEACHES:
 *
 * 1. **Tier 1 is a router and a `format` transform, and neither bills.**
 *    `triage` is a compiled comparison, not an agent - `route_branch` costs no
 *    model call - and a `format` transform is string substitution. The two
 *    self-serve replies below are free, for ever, at any volume.
 * 2. **`contains` is a substring test and NOT a regex.** `str(value) in
 *    ticket`, case-sensitive, one value per branch. There is no expression
 *    surface here and there will not be one, so a rule tier is a list of
 *    phrases you can read rather than a pattern you have to parse. It is worth
 *    knowing what that costs you: "PASSWORD" in capitals falls through to the
 *    classifier, which is the safe direction to be wrong in.
 * 3. **Tier 2 buys a decision, not an answer.** `classify` runs on the
 *    roster's least expensive model with `max_iter: 1` and an
 *    `output_schema`, so what comes back is one word a router can compare.
 * 4. **Four is the ceiling on a router.** `MAX_FANOUT_WIDTH` caps branch count
 *    as well as out-degree, `otherwise` included. Three phrases and a fallback
 *    is the most a single tier can hold; a fifth phrase needs a second router
 *    below the first.
 *
 * WHY THE RULE TIER IS TWO BRANCHES AND NOT ONE. A single canned answer would
 * make the tier look like a special case. Two different phrases reaching two
 * different replies is what shows it is a TABLE, and adding a third is one
 * branch, one transform and two edges with no model anywhere in the change.
 *
 * WHY `joins: 'any'` AT THE GATHER, and why that is safe here. Exactly one of
 * the four paths ever runs, because every one of them descends from a router
 * where exactly one branch fires. Declared `'all'` the gather would wait for
 * three arrivals that were never going to happen, and there would be no error,
 * because waiting is not failing. `'any'` compiles to alternatives; the other
 * three were never started, so there is nothing to cancel.
 *
 * WHAT TO MODIFY FIRST: the phrases on the two rule branches. They are the
 * whole of tier 1, and reading your own inbox for the two commonest asks is
 * the exercise this template exists for.
 *
 * Measured on this build, against `validate_document` and `estimate_budget`
 * over the dumped document: zero problems, 3 billable nodes, 1 escalation,
 * 0 cycles, 24 modelled calls, floor $0.3020, static $0.3921, which is $0.4901
 * with the 1.25x margin against the $10.00 ceiling. That is the WORST case,
 * priced as though every ticket reached tier 3; the self-serve paths cost none
 * of it, because they reach the output past no billable node at all.
 */

const NODES = [
  inputNode(
    'ticket',
    'Ticket',
    'Paste the message that arrived.',
    { x: 340, y: 0 },
  ),
  gateNode(
    'confirm',
    'Confirm the ticket',
    'This message is about to be sorted. Most tickets are answered here without a model at all. Approve it, or send it back.',
    { x: 340, y: 160 },
  ),
  routerNode(
    'triage',
    'Tier 1: can we answer this for free?',
    [
      // `contains` is `str(value) in ticket`. One phrase per branch, tested in
      // the order written, and the first match wins.
      branch('password', 'contains', nodeId('ticket'), 'password'),
      branch('tracking', 'contains', nodeId('ticket'), 'where is my order'),
      // Everything else, and it must exist: a router that matched nothing and
      // declared no otherwise RAISES, which would end a run over a phrasing
      // nobody anticipated.
      branch('unclear', 'otherwise'),
    ],
    { x: 340, y: 320 },
  ),
  transformNode(
    'reset_reply',
    'Self-serve: password',
    'format',
    {
      template:
        'You can reset your own password without waiting for us.\n\nOpen the sign-in page, choose "Forgot password", and enter the address you signed up with. The link we send is good for one hour. If it does not arrive, check the spam folder before writing back.\n\nYou asked:\n{ticket}',
      ticket: stateRef('ticket'),
    },
    { x: 40, y: 480 },
  ),
  transformNode(
    'tracking_reply',
    'Self-serve: order status',
    'format',
    {
      template:
        'Every order has a live tracking page and it is quicker than we are.\n\nOpen Orders in your account and choose the order you are asking about. The page shows the carrier, the tracking number and the last scan. Orders placed after 4pm ship the following working day.\n\nYou asked:\n{ticket}',
      ticket: stateRef('ticket'),
    },
    { x: 240, y: 480 },
  ),
  authoredAgent({
    id: 'classify',
    label: 'Tier 2: how hard is this?',
    position: { x: 620, y: 480 },
    role: 'Triage',
    goal: 'Say in one word how much thinking this ticket needs, and never more than that.',
    backstory:
      'You sort the mail nobody could sort with a list of phrases. You read for the ask rather than the tone, you are paid to be quick rather than right about the answer, and you would rather send a borderline ticket up than guess at it yourself.',
    description:
      'Read the ticket below and say how hard it is.\n\nAnswer `complex` when it needs judgement: several things going wrong at once, an account history to reconstruct, a policy question, or anything where a wrong answer costs money. Answer `ordinary` for everything else, which is most of it.\n\nTICKET:\n{ticket}',
    expected: 'An object with one key, `difficulty`, whose value is complex or ordinary.',
    model: 'cheapest',
    // One pass. The answer is one word, and a second attempt would cost as much
    // as the first for the same word.
    maxIter: 1,
    outputSchema: { difficulty: 'string' },
    promptInputs: { ticket: stateRef('ticket') },
  }),
  transformNode(
    'graded',
    'Difficulty',
    'pick',
    { source: out('classify'), key: 'difficulty' },
    { x: 620, y: 640 },
  ),
  routerNode(
    'depth',
    'Tier 3: which model answers?',
    [
      branch('deep', 'eq', outKey('graded'), 'complex'),
      // Ordinary is the otherwise branch, so a classifier that answered
      // something unexpected gets the cheaper model rather than the dearer one.
      // Being wrong in this direction costs a worse answer; being wrong the
      // other way costs money on every misread ticket.
      branch('ordinary', 'otherwise'),
    ],
    { x: 620, y: 800 },
  ),
  authoredAgent({
    id: 'specialist',
    label: 'Specialist',
    position: { x: 480, y: 960 },
    role: 'Senior Support Specialist',
    goal: 'Untangle the hard ones completely, so nobody has to write in again.',
    backstory:
      'You take what the desk could not. You reconstruct what happened from what the customer half remembers, you say what you are going to do before you do it, and you name the one thing you still need when you cannot finish.',
    description:
      'Answer this ticket. It has been marked as needing judgement, so take the time.\n\nSay what you think happened, what you are doing about it, and what happens next. If you need one more fact to finish, ask for exactly that one thing.\n\nTICKET:\n{ticket}',
    expected:
      'A reply the customer can read as-is: what happened, what has been done, what happens next, and at most one question.',
    model: 'escalation',
    markdown: true,
    promptInputs: { ticket: stateRef('ticket') },
  }),
  authoredAgent({
    id: 'standard',
    label: 'Support desk',
    position: { x: 800, y: 960 },
    role: 'Support Agent',
    goal: 'Answer an ordinary ticket properly the first time.',
    backstory:
      'You clear the queue. You answer what was asked, in the order it was asked, and you do not pad a short answer to look thorough.',
    description:
      'Answer this ticket.\n\nAnswer what was asked and say what happens next. Keep it short.\n\nTICKET:\n{ticket}',
    expected: 'A short reply the customer can read as-is, with a clear next step.',
    model: 'workhorse',
    markdown: true,
    promptInputs: { ticket: stateRef('ticket') },
  }),
  transformNode(
    'gather',
    'Whichever tier answered',
    'join_text',
    {
      password: out('reset_reply'),
      tracking: out('tracking_reply'),
      deep: out('specialist'),
      ordinary: out('standard'),
    },
    { x: 340, y: 1120 },
  ),
  outputNode('reply', 'Reply', { x: 340, y: 1280 }),
]

export const TIERED_ROUTING_DOCUMENT: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: documentId('ug_00000000'),
  name: 'Tiered routing',
  version: 1,
  input_field: nodeId('ticket'),
  nodes: NODES,
  edges: [
    flowEdge('e1', 'ticket', 'confirm'),
    flowEdge('e2', 'confirm', 'triage', 'approve'),
    flowEdge('e3', 'triage', 'reset_reply', 'password'),
    flowEdge('e4', 'triage', 'tracking_reply', 'tracking'),
    flowEdge('e5', 'triage', 'classify', 'unclear'),
    flowEdge('e6', 'classify', 'graded'),
    flowEdge('e7', 'graded', 'depth'),
    flowEdge('e8', 'depth', 'specialist', 'deep'),
    flowEdge('e9', 'depth', 'standard', 'ordinary'),
    flowEdge('e10', 'reset_reply', 'gather'),
    flowEdge('e11', 'tracking_reply', 'gather'),
    flowEdge('e12', 'specialist', 'gather'),
    flowEdge('e13', 'standard', 'gather'),
    flowEdge('e14', 'gather', 'reply'),
  ],
  // One of four paths runs, so the gather fires on the first arrival. See the
  // module note: declared `'all'` this run would wait for ever.
  joins: { gather: 'any' },
  budget: null,
}
