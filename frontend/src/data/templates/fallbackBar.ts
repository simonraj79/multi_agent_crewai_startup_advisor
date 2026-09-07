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
  retryWithFallback,
  routerNode,
  stateRef,
  transformNode,
} from './authoring'

/**
 * A second model stands in when the first one is down, and clears the same bar.
 *
 * A customer writes in and the reply has to go out today. The model that
 * normally writes it starts returning 503s under load. The answerer waits,
 * tries again, and on its last attempt runs on a different model entirely -
 * and whatever comes back, from either model, goes to the same checker before
 * anything reaches the customer.
 *
 * THE BAR IS THE POINT, NOT THE FALLBACK. Google's own framing: "There's a
 * single validate function that both the Pro path and the Flash path are
 * forced to call before either result can leave the agent... That's what
 * actually prevents a fallback from quietly lowering your bar: not remembering
 * to apply the same standard twice, but making it structurally impossible to
 * apply it only once." Here it is structural twice over. The retry runs THE
 * SAME node spec with one field swapped - `replace(spec, llm={**spec.llm,
 * "model": fallback})` - so the same task, the same expected output and the
 * same guardrail budget apply to the fallback attempt by construction. And
 * `check` sits downstream of the answerer, so it reads whatever the answerer
 * produced without knowing or caring which model produced it. There is one
 * check because there is one place to put it.
 *
 * FOUR THINGS IT TEACHES, and the first three are corrections to what the
 * shape looks like it does:
 *
 * 1. **The fallback fires on TRANSPORT failure and never on a bad answer.**
 *    `_RETRYABLE_ERROR_NAMES` is a closed list of sixteen exceptions plus the
 *    statuses 408, 425, 429, 500, 502, 503 and 504. A refusal, a malformed
 *    structured output and a failed guardrail are excluded on purpose: "a
 *    refusal is a decision rather than an error, and retrying one with a
 *    fallback model is asking a second judge until one agrees." If you want a
 *    second model to try because the first wrote something poor, that is the
 *    loop below, not the retry above.
 * 2. **`max_retries` under 1 makes the fallback inert.** The fallback is
 *    offered to the last attempt and only when there was an earlier one, so a
 *    node with a fallback model and no retries never reaches it. It would look
 *    configured on the canvas and do nothing at all, which is why the helper
 *    that writes this asks for both numbers in one call.
 * 3. **Retries are priced, every one of them.** The estimate prices each
 *    attempt as a whole node re-run, so two retries triples what this node
 *    contributes. That is the honest cost of the shape and it is the reason
 *    this is the DEAREST card in the gallery.
 * 4. **Only a router may close the loop.** `bar -> answer` leaves a router
 *    port, because a plain listener closing a loop suppresses the second
 *    arrival and the run ends having produced nothing, with no exception, no
 *    warning and no frame.
 *
 * WHY THE CHECK IS A BOOLEAN AND THE LOOP EXITS ON `otherwise`. The router
 * tests `cleared == false` first, so a checker whose answer could not be read
 * scores null, fails that comparison and falls to `done` with the reply it
 * has. Written the obvious way round - test `cleared == true`, loop otherwise
 * - the same unreadable answer would go round until the compiler's backstop
 * raised, and the run would fail having paid for four replies. A loop should
 * fail towards stopping.
 *
 * WHAT IS DELIBERATELY NOT HERE: `on_error: 'route'` and the `error` port it
 * grows. The server supports it and the compiler emits a paired error router,
 * but the canvas cannot draw one - `nodeKinds.ts` writes the key in no default
 * config - so a template shipping it would render a port an author could not
 * create for themselves. Recorded as a follow-up rather than built.
 *
 * WHAT TO MODIFY FIRST: `max_retries` on the answerer. Set it to 0 and the
 * fallback model below it stops meaning anything, which is the fastest way to
 * see lesson 2 rather than read it.
 *
 * Measured on this build, against `validate_document` and `estimate_budget`
 * over the dumped document: zero problems, 2 billable nodes, ZERO escalation
 * nodes, 1 cycle, 132 modelled calls, floor $1.2309, static $2.2014, which is
 * $2.7517 with the 1.25x margin against the $10.00 ceiling. The dearest card
 * in the gallery, and the count of escalation nodes is worth reading twice:
 * the answerer DECLARES the cheap tier, because that is the tier it normally
 * runs on, and `MAX_ESCALATION_NODES` counts declarations. The dearer model is
 * reached only through `retry.fallback_model`, which the price does account
 * for and the count does not.
 */

const NODES = [
  inputNode(
    'enquiry',
    'Enquiry',
    'What has the customer asked?',
    { x: 340, y: 0 },
  ),
  gateNode(
    'confirm',
    'Confirm the enquiry',
    'A reply is about to be written and checked, and rewritten if it does not pass. Approve the enquiry, or send it back.',
    { x: 340, y: 160 },
  ),
  authoredAgent({
    id: 'answer',
    label: 'Write the reply',
    position: { x: 340, y: 320 },
    role: 'Customer Reply Writer',
    goal: 'Write the reply that goes out, and rewrite it when the checker says why.',
    backstory:
      'You write the replies a company signs its name to. You answer the question that was asked before anything else, you never promise a date you were not given, and you take a correction without arguing with it.',
    description:
      'Write the reply to the enquiry below. If NOTES are present, your previous reply did not pass the check: rewrite it so every point in the notes is addressed.\n\nAnswer what was asked, say what happens next, and commit to nothing that is not in the enquiry.\n\nENQUIRY:\n{enquiry}\n\nNOTES:\n{notes}',
    expected:
      'The reply itself, ready to send, with a greeting and a sign-off. Nothing about the reply and no notes to the reader.',
    model: 'workhorse',
    markdown: true,
    // THE WHOLE TEMPLATE. Two retries with a doubling backoff, and the LAST
    // attempt runs on the escalation model. The fallback is a role like every
    // other model here, so it resolves against the roster rather than naming a
    // slug that would be stale the first time the catalogue moved.
    retry: retryWithFallback(2, 2, 'escalation'),
    // `out__notes` is null on the first pass and the compiler pre-seeds it, so
    // this renders empty rather than failing the method.
    promptInputs: { enquiry: stateRef('enquiry'), notes: out('notes') },
  }),
  authoredAgent({
    id: 'check',
    label: 'Check it against the bar',
    position: { x: 340, y: 480 },
    role: 'Reply Checker',
    goal: 'Say whether this reply may be sent, and if not, exactly what is wrong.',
    backstory:
      'You are the last read before a reply leaves. You have a written list and you apply it the same way every time, whoever wrote the draft and whatever model wrote it.',
    description:
      'Check the reply below against every one of these, and do not add a rule of your own:\n\n1. It answers the question that was actually asked.\n2. It promises no date, price or outcome that the enquiry did not already state.\n3. It names no other customer.\n4. It is signed off and ready to send as written.\n\nENQUIRY:\n{enquiry}\n\nREPLY:\n{reply}',
    expected:
      'An object with two keys: `cleared`, true only when all four rules pass, and `notes`, one line per failed rule, or an empty string when it cleared.',
    model: 'cheapest',
    maxIter: 1,
    // The whole reason the router downstream can compare anything, and the bar
    // both the primary model and the fallback are read against.
    outputSchema: { cleared: 'boolean', notes: 'string' },
    promptInputs: { enquiry: stateRef('enquiry'), reply: out('answer') },
  }),
  transformNode(
    'cleared',
    'Cleared',
    'pick',
    { source: out('check'), key: 'cleared' },
    { x: 140, y: 640 },
  ),
  transformNode(
    'notes',
    'Notes',
    'pick',
    { source: out('check'), key: 'notes' },
    { x: 540, y: 640 },
  ),
  routerNode(
    'bar',
    'Did it clear the bar?',
    [
      // Tested first, and it is the LOOPING branch. See the module note on why
      // this is the opposite of the obvious spelling.
      branch('again', 'eq', outKey('cleared'), false),
      branch('done', 'otherwise'),
    ],
    { x: 340, y: 800 },
  ),
  // Names its source, for `reflection-loop`'s reason: an unset source follows
  // the incoming edge, which here comes from a router, and a router records
  // what flowed THROUGH it - the flag it compared rather than the reply it was
  // deciding about.
  outputNode('reply', 'Reply', { x: 340, y: 960 }, out('answer')),
]

export const FALLBACK_BAR_DOCUMENT: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: documentId('ug_00000000'),
  name: 'Fallback that clears the bar',
  version: 1,
  input_field: nodeId('enquiry'),
  nodes: NODES,
  edges: [
    flowEdge('e1', 'enquiry', 'confirm'),
    flowEdge('e2', 'confirm', 'answer', 'approve'),
    flowEdge('e3', 'answer', 'check'),
    flowEdge('e4', 'check', 'cleared'),
    flowEdge('e5', 'check', 'notes'),
    flowEdge('e6', 'cleared', 'bar'),
    flowEdge('e7', 'notes', 'bar'),
    flowEdge('e8', 'bar', 'reply', 'done'),
    // The back edge, and it leaves a ROUTER port because that is the only kind
    // of port a loop may be closed from.
    flowEdge('e9', 'bar', 'answer', 'again'),
  ],
  // `bar` needs BOTH picks. Undeclared, two arrivals whose ancestors include a
  // gate compile to alternatives, and the router would run on whichever
  // finished first with the other half of its answer missing.
  joins: { bar: 'all' },
  budget: null,
}

/**
 * What the card must say, word for word (R14).
 *
 * Three facts, and every one of them is a correction to what the picture
 * promises. A reader who takes "fallback" at face value will believe the
 * second model catches a bad answer, that setting one is enough to arm it, and
 * that a retry is free. All three are wrong, all three are measured, and none
 * of them is visible on the canvas.
 */
export const FALLBACK_BAR_CAVEAT =
  'The fallback fires on a transport failure only: a 429, a timeout, a 5xx. A '
  + 'poor answer is not a failure, so the second model never sees one; the '
  + 'checker and the loop are what catch that. Set max_retries below 1 and the '
  + 'fallback can never be reached, though it will still look configured. And '
  + 'every retry is priced as a whole node run, which is why this card costs '
  + 'what it does.'
