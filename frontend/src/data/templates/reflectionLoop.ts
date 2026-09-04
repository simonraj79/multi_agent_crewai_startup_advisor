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
 * A drafter and a critic, going round until the score is good enough.
 *
 * The first template with a cycle in it, and the only one whose picture has an
 * edge pointing back up the page. Everything difficult about loops is here in
 * its smallest form.
 *
 * FOUR THINGS IT TEACHES:
 *
 * 1. **Only a router may close a loop.** `judge -> generate` leaves a router
 *    port, and it has to: compiled as a plain listener the join fires once, the
 *    second arrival is suppressed, and the run produces nothing with no
 *    exception, no warning and no frame. That was measured, not reasoned, and
 *    `bounds.py`'s `back-edge-not-router` refuses the shape.
 * 2. **`output_schema` turns prose into a number a router can read.** The critic
 *    declares `{score: integer, feedback: string}`, which compiles to a
 *    `Task.response_model`; without it `score` would be a sentence and `gte`
 *    would be comparing a string to 8.
 * 3. **`pick` is how one field leaves a structured answer.** Two transform
 *    nodes, no code, no expression - the six transform operations are the whole
 *    vocabulary and there is no seventh.
 * 4. **The loop is bounded by the compiler, not by the prompt.**
 *    `max_method_calls` is `(1 + MAX_CYCLE_ITERATIONS) ** cycles` = 4, so at
 *    most four drafts happen whatever the critic says.
 *
 * WHY THE ROUTER LOOPS ON `lt` AND EXITS ON `otherwise`, WHICH IS THE OPPOSITE
 * OF THE OBVIOUS SPELLING. `_compare` returns false for a null on every
 * ordering comparison, so with `done` as the tested branch a critic whose
 * answer could not be parsed would score null, fail `gte`, fall to `again`, and
 * go round until the compiler's backstop raised `RecursionError` - the run
 * failing, having paid for four drafts, because one answer came back
 * unreadable. Written this way the same null falls to `done` and the run ends
 * with the draft it has. A loop should fail towards stopping: the cost of one
 * fewer revision is a slightly worse draft, and the cost of one more is money
 * and a crash.
 *
 * WHAT TO MODIFY FIRST: the threshold `8`. It is one integer, it is the only
 * thing deciding how long this runs, and moving it to 10 is the cheapest way to
 * watch the compiler's cap do its job.
 */

const NODES = [
  inputNode(
    'ask',
    'Ask',
    'What should be drafted?',
    { x: 340, y: 0 },
  ),
  gateNode(
    'confirm',
    'Confirm the ask',
    'A drafter and a critic are about to go round on this, up to four times. Approve the ask, or send it back.',
    { x: 340, y: 160 },
  ),
  authoredAgent({
    id: 'generate',
    label: 'Draft',
    position: { x: 340, y: 320 },
    role: 'Drafter',
    goal: 'Produce a draft, and improve it whenever somebody says how.',
    backstory:
      'You write first drafts fast and you do not defend them. When a critic gives you three fixes you make all three, rather than arguing with one.',
    description:
      'Draft the piece described below. If FEEDBACK is present, revise your previous draft to address every point in it.\n\nASK:\n{ask}\n\nFEEDBACK:\n{feedback}',
    expected: 'The draft itself, in Markdown, and nothing about the draft.',
    model: 'workhorse',
    markdown: true,
    // `out__feedback` is null on the first pass and the compiler pre-seeds it,
    // so this renders empty rather than failing the method - which is exactly
    // what a loop's first time round needs.
    promptInputs: { ask: stateRef('ask'), feedback: out('feedback') },
  }),
  authoredAgent({
    id: 'critique',
    label: 'Critique',
    position: { x: 340, y: 480 },
    role: 'Critic',
    goal: 'Say how good this is, on a scale, and what would most improve it.',
    backstory:
      'You review as an editor rather than as a fan. You give a number you would defend and three fixes ordered by how much each one buys.',
    description:
      'Score the draft below out of 10 and give the three most important fixes.\n\nDRAFT:\n{draft}',
    expected:
      'An object with two keys: `score`, a whole number 0 to 10, and `feedback`, the three fixes as one string.',
    model: 'workhorse',
    // The whole reason the router downstream can compare anything.
    outputSchema: { score: 'integer', feedback: 'string' },
    promptInputs: { draft: out('generate') },
  }),
  transformNode(
    'score',
    'Score',
    'pick',
    { source: out('critique'), key: 'score' },
    { x: 140, y: 640 },
  ),
  transformNode(
    'feedback',
    'Feedback',
    'pick',
    { source: out('critique'), key: 'feedback' },
    { x: 540, y: 640 },
  ),
  routerNode(
    'judge',
    'Good enough?',
    [
      // Tested first, and it is the LOOPING branch. See the module note.
      branch('again', 'lt', outKey('score'), 8),
      branch('done', 'otherwise'),
    ],
    { x: 340, y: 800 },
  ),
  // THE ONE OUTPUT IN THE GALLERY THAT NAMES ITS SOURCE, and the exception
  // proves the rule. An unset `source` follows the node's incoming edge, which
  // here comes from `judge` - and a router records what flowed THROUGH it,
  // which at that point is the score it compared rather than the draft it was
  // deciding about. Measured against the synthetic backend before this line
  // existed: the run completed, answered `markdown_body: ""`, and reported no
  // problem at all. The deliverable is the drafter's last draft, so this says
  // so. Every other template leaves it null on purpose.
  outputNode('final', 'Final draft', { x: 340, y: 960 }, out('generate')),
]

export const REFLECTION_LOOP_DOCUMENT: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: documentId('ug_00000000'),
  name: 'Reflection loop',
  version: 1,
  input_field: nodeId('ask'),
  nodes: NODES,
  edges: [
    flowEdge('e1', 'ask', 'confirm'),
    flowEdge('e2', 'confirm', 'generate', 'approve'),
    flowEdge('e3', 'generate', 'critique'),
    flowEdge('e4', 'critique', 'score'),
    flowEdge('e5', 'critique', 'feedback'),
    flowEdge('e6', 'score', 'judge'),
    flowEdge('e7', 'feedback', 'judge'),
    flowEdge('e8', 'judge', 'final', 'done'),
    // The back edge. It leaves a ROUTER port, which is the only kind of port a
    // loop may be closed from.
    flowEdge('e9', 'judge', 'generate', 'again'),
  ],
  // `judge` needs BOTH transforms, and saying so is not optional. Undeclared,
  // two arrivals whose ancestors include a gate compile to alternatives, and
  // the router would run on whichever of the two finished first with the other
  // half of its answer missing.
  joins: { judge: 'all' },
  budget: null,
}
