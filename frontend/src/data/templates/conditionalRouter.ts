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
 * Classify a message, send it to one of three desks, and converge again.
 *
 * The other three templates run everything they draw. This one draws four
 * agents and runs two, and the arithmetic of that is the lesson: a graph's
 * PRICE is what it could cost, and its BILL is what it did.
 *
 * THREE THINGS IT TEACHES:
 *
 * 1. **A router is deterministic and has no model.** `route` compares one state
 *    key against one value, seven comparisons and no expressions, because an
 *    expression surface is an evaluation surface. The judgement happens in
 *    `classify`, which is an agent; the branching happens in `route`, which is
 *    arithmetic.
 * 2. **`joins: 'any'` is what lets branches converge.** Exactly one desk runs,
 *    so `merge` must fire on the first arrival. Declared `'all'` it would wait
 *    forever for two branches that were never going to happen - and there would
 *    be no error, because waiting is not failing.
 * 3. **Put the cheap model where the decision is small.** `classify` emits one
 *    word and runs on the roster's least expensive row; the three desks write
 *    replies and run on the workhorse. That is the single largest lever an
 *    author has over a bill, and it is one dropdown.
 *
 * WHY THE MERGE IS `join_text` AND NOT `default`. `default` takes one value and
 * one fallback, which is two branches; there are three. `join_text` skips a
 * null - and every branch that did not run is null, because the compiler
 * pre-seeds `out__*` - so joining all three yields exactly the one that ran.
 * Adding a fourth desk needs one more argument here and nothing else.
 *
 * WHAT TO MODIFY FIRST: the classifier's model. Swap it for the escalation one
 * and watch the budget meter move for a node that only ever says one word.
 */

const NODES = [
  inputNode(
    'request',
    'Request',
    'Paste the customer message.',
    { x: 340, y: 0 },
  ),
  gateNode(
    'confirm',
    'Confirm the request',
    'This message is about to be classified and answered. Approve it, or send it back.',
    { x: 340, y: 160 },
  ),
  authoredAgent({
    id: 'classify',
    label: 'Triage',
    position: { x: 340, y: 320 },
    role: 'Triage',
    goal: 'Put a message on the right desk, in one word, and never guess twice.',
    backstory:
      'You have sorted support mail for years. You read for the ask rather than the tone, and you would rather send an ambiguous message to accounts than invent a fourth category.',
    description:
      'Classify the customer message below as exactly one of: billing, technical, account.\n\nMESSAGE:\n{request}',
    expected: 'An object with one key, `category`, whose value is billing, technical or account.',
    model: 'cheapest',
    // One pass. There is nothing to iterate on: the answer is one word and a
    // second attempt would cost as much as the first for the same word.
    maxIter: 1,
    outputSchema: { category: 'string' },
    promptInputs: { request: stateRef('request') },
  }),
  transformNode(
    'category',
    'Category',
    'pick',
    { source: out('classify'), key: 'category' },
    { x: 340, y: 480 },
  ),
  routerNode(
    'route',
    'Which desk?',
    [
      branch('billing', 'eq', outKey('category'), 'billing'),
      branch('technical', 'eq', outKey('category'), 'technical'),
      // `account` is the otherwise branch rather than a third comparison, so a
      // classifier that answered something unexpected still reaches a human
      // rather than stopping the run. A router that matched nothing and
      // declared no otherwise raises, and it should.
      branch('account', 'otherwise'),
    ],
    { x: 340, y: 640 },
  ),
  authoredAgent({
    id: 'billing',
    label: 'Billing',
    position: { x: 40, y: 800 },
    role: 'Billing Specialist',
    goal: 'Answer a money question completely enough that nobody has to write again.',
    backstory:
      'You handle invoices, refunds and plan changes. You quote the exact amounts and dates, because a billing reply that is vague is a second ticket.',
    description: 'Answer this billing message.\n\nMESSAGE:\n{request}',
    expected: 'A reply the customer can read as-is: what happened, what you did, and what happens next.',
    model: 'workhorse',
    markdown: true,
    promptInputs: { request: stateRef('request') },
  }),
  authoredAgent({
    id: 'technical',
    label: 'Technical',
    position: { x: 340, y: 800 },
    role: 'Support Engineer',
    goal: 'Get somebody unstuck in as few steps as they will actually follow.',
    backstory:
      'You debug from the far side of the screen. You ask for one thing at a time and you say what you expect to see, so a reply tells you something either way.',
    description: 'Answer this technical message.\n\nMESSAGE:\n{request}',
    expected: 'A reply with the likely cause, the steps to try in order, and what to send back if none of them work.',
    model: 'workhorse',
    markdown: true,
    promptInputs: { request: stateRef('request') },
  }),
  authoredAgent({
    id: 'account',
    label: 'Account',
    position: { x: 640, y: 800 },
    role: 'Account Manager',
    goal: 'Handle anything about the relationship, and route what is not yours.',
    backstory:
      'You own the account rather than the ticket. When a message is not about billing or the product you are the one who answers it, and you never send somebody back to the start.',
    description: 'Answer this account message.\n\nMESSAGE:\n{request}',
    expected: 'A reply that answers what was asked, or names the one thing you need to answer it.',
    model: 'workhorse',
    markdown: true,
    promptInputs: { request: stateRef('request') },
  }),
  transformNode(
    'merge',
    'Whichever answered',
    'join_text',
    {
      billing: out('billing'),
      technical: out('technical'),
      account: out('account'),
    },
    { x: 340, y: 960 },
  ),
  outputNode('reply', 'Reply', { x: 340, y: 1120 }),
]

export const CONDITIONAL_ROUTER_DOCUMENT: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: documentId('ug_00000000'),
  name: 'Conditional router',
  version: 1,
  input_field: nodeId('request'),
  nodes: NODES,
  edges: [
    flowEdge('e1', 'request', 'confirm'),
    flowEdge('e2', 'confirm', 'classify', 'approve'),
    flowEdge('e3', 'classify', 'category'),
    flowEdge('e4', 'category', 'route'),
    flowEdge('e5', 'route', 'billing', 'billing'),
    flowEdge('e6', 'route', 'technical', 'technical'),
    flowEdge('e7', 'route', 'account', 'account'),
    flowEdge('e8', 'billing', 'merge'),
    flowEdge('e9', 'technical', 'merge'),
    flowEdge('e10', 'account', 'merge'),
    flowEdge('e11', 'merge', 'reply'),
  ],
  // The one key that makes this graph terminate. See lesson 2 above.
  joins: { merge: 'any' },
  budget: null,
}
