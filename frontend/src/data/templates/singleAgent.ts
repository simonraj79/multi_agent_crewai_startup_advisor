import { BUILDER_SCHEMA_ID, documentId, nodeId } from '../../types/builder'
import type { BuilderDocument } from '../../types/builder'
import {
  attachEdge,
  authoredAgent,
  flowEdge,
  gateNode,
  inputNode,
  outputNode,
  stateRef,
  toolNode,
} from './authoring'

/**
 * One agent, one tool, one answer. The smallest thing in the gallery that works.
 *
 * A help desk gets a question about a product and answers it from what people
 * are actually saying about that product this week, with the pages it read
 * named underneath. One worker does the whole job: it decides what to search
 * for, reads what comes back, decides whether that was enough, and writes the
 * reply.
 *
 * WHY THIS CARD EXISTS AT ALL, given that four other templates are bigger and
 * more interesting. Both pattern sources open with the same instruction and
 * neither hedges it. Anthropic: "we suggest teams begin with single-purpose
 * agents that do one thing well, then gradually develop them into more
 * sophisticated systems as your requirements evolve" (p. 10), and again at the
 * decision table, "Don't over-engineer. If the work involves straightforward,
 * repeatable tasks, a single well-designed agent is likely sufficient"
 * (p. 23). Google: "If you're early in your agent development, we recommend
 * that you start with a single agent... you can focus on refining the core
 * logic, prompt, and tool definitions of your agent before adding more complex
 * architectural components." A gallery whose first working card is a chain of
 * three teaches the opposite of what both sources say to do first.
 *
 * THREE THINGS IT TEACHES:
 *
 * 1. **An agent is not a prompt.** The task text below asks for a search and
 *    then for a judgement about what the search returned. `max_iter: 6` is what
 *    permits the second look; at `max_iter: 1` this node is a single call that
 *    can only use whatever the first query happened to find.
 * 2. **A tool is a possession, not a step.** `search` has one port and it is a
 *    SOURCE, so the edge reads tool-to-agent. Nothing flows into it and nothing
 *    comes out of it into the run; it is something the agent HAS.
 * 3. **The gate above the agent is what makes this launchable by a stranger.**
 *    Four nodes plus the tool, in this order, is the smallest authored shape
 *    that keeps that brake.
 *
 * WHY THE PRICE ON THIS CARD IS THE LEAST PREDICTABLE IN THE GALLERY, and the
 * card says so. Every other template's picture is a good guide to its bill,
 * because each box is one or two calls. This one box hides a loop: the agent
 * may search, read, search differently and read again, up to `max_iter` times,
 * and the estimate prices all six because it has to price the worst case. The
 * measured spread is the widest of the thirteen relative to its size, and the
 * lesson is the honest one - a tool loop is where a small graph becomes an
 * expensive one, and it is invisible on the canvas.
 *
 * WHY THE TOOL IS HACKER NEWS. It is the only search in the catalogue that
 * needs no key at all: `web_search` maps each of its four providers to a
 * credential kind, and the three Firecrawl entries are
 * `credential_optional=False`, so a template naming either opens with a
 * `tool-credential-required` error on a document nobody has touched and cannot
 * be launched from a cold sign-in. Swapping it for a web search once a key
 * exists is one field in the inspector and the prompt does not change: it
 * cites whatever URLs the tool returned.
 *
 * WHAT TO MODIFY FIRST: the agent's backstory. It is the field that decides
 * what "answer the question" means here, it needs no other edit to stay safe,
 * and rewriting it into your own product's voice is the fastest way to see
 * that these prompts are the whole of what an agent is.
 *
 * Measured on this build, against `validate_document` and `estimate_budget`
 * over the dumped document: zero problems, 1 billable node, 0 escalation,
 * 0 cycles, 21 modelled calls, floor $0.2359, static $0.4246, which is $0.5307
 * with the 1.25x margin against the $10.00 ceiling. One box, and it is dearer
 * than the four-agent vote template two sections down, which is the tool
 * loop's price and the whole of the note above.
 */

const NODES = [
  inputNode(
    'question',
    'Question',
    'What has somebody asked?',
    { x: 340, y: 0 },
  ),
  gateNode(
    'confirm',
    'Confirm the question',
    'One agent is about to search and answer this. Approve the question, or send it back.',
    { x: 340, y: 160 },
  ),
  authoredAgent({
    id: 'answer',
    label: 'Answer the question',
    position: { x: 340, y: 320 },
    role: 'Support Agent',
    goal: 'Answer the question in front of you, and show where the answer came from.',
    backstory:
      'You staff a help desk for a technical product. You would rather look something up than remember it, you say plainly when the search found nothing useful, and you have never once invented a version number.',
    description:
      'Answer the question below for the person who asked it.\n\nSearch for what practitioners have said about it. Read what comes back. If the first search was too narrow or returned nothing on point, search again with different words before you answer.\n\nThen write the reply: the answer first, in two or three sentences, and under it the pages you used, one URL per line. Cite only URLs the search returned to you. If nothing useful came back, say that in one line and answer from the question alone rather than filling the gap.\n\nQUESTION:\n{question}',
    expected:
      'A short answer in plain sentences, then a line reading "Sources" with one URL per line under it. Every URL is one the search returned. No preamble and no note about how you searched.',
    model: 'workhorse',
    markdown: true,
    // Six, and the same measurement as `news-to-social`: this is the only node
    // in the document that calls a tool, and a first query that comes back thin
    // is worth asking a second, differently worded time. It is also the number
    // the card's price note is about.
    maxIter: 6,
    promptInputs: { question: stateRef('question') },
  }),
  // Keyless, deliberately. `params: {}` takes the catalogue's own defaults, so
  // a default that moves in `tools.py` moves here too.
  toolNode('search', 'Search the discussion', 'analyze_community_sentiment', { x: 40, y: 320 }),
  outputNode('reply', 'Reply', { x: 340, y: 480 }),
]

export const SINGLE_AGENT_DOCUMENT: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: documentId('ug_00000000'),
  name: 'Single agent',
  version: 1,
  input_field: nodeId('question'),
  nodes: NODES,
  edges: [
    flowEdge('e1', 'question', 'confirm'),
    flowEdge('e2', 'confirm', 'answer', 'approve'),
    flowEdge('e3', 'answer', 'reply'),
    attachEdge('e4', 'search', 'answer'),
  ],
  // Nothing waits for anything: one step, with one possession hung off it.
  joins: {},
  budget: null,
}
