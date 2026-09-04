import { BUILDER_SCHEMA_ID, documentId, nodeId } from '../../types/builder'
import type { BuilderDocument } from '../../types/builder'
import {
  attachEdge,
  authoredAgent,
  flowEdge,
  gateNode,
  inputNode,
  out,
  outputNode,
  stateRef,
  toolNode,
} from './authoring'

/**
 * Research, then analyse, then write. The hello world of this builder.
 *
 * Three agents in a line, one tool hung off the first, one gate above all of
 * them. Nothing here is clever and that is the point: it is the template that
 * has to be legible to somebody who has never seen a flow, and everything it
 * does is a thing they will do again on their own graph within the hour.
 *
 * THREE LESSONS, one per piece of syntax:
 *
 * 1. **An edge is a `@listen`.** `research -> analyse` compiles to a listener
 *    on `research`'s completion, and drawing it is the whole of saying "after".
 * 2. **`${state.out__x}` is how the previous step's text reaches the next
 *    prompt.** It is spelled out in `analyse` and `write` rather than generated,
 *    because it is the one string an author has to type into the inspector and
 *    a template that hid it would teach nothing.
 * 3. **A tool is something you drop ONTO an agent.** `search` is a node with one
 *    port, and the port is a SOURCE - the tool reaches toward the agent. Nothing
 *    flows into a possession, which is why an attachment has no inbound port at
 *    all and why Flowise's `agentTools` array is the shape this avoids.
 *
 * WHY THE TOOL IS HACKER NEWS AND NOT `web_search`. Every one of `web_search`'s
 * four providers needs the author's own key - `credential_kind_by_param` maps
 * `serper`, `tavily`, `exa` and `brave` each to a credential kind - and there is
 * no platform key behind any of them (PLANS.md decision 9 is provisional and
 * off). A template that shipped it would open with a
 * `tool-credential-required` error on a graph nobody had touched, and could not
 * be launched from a cold sign-in at all, which is what criterion 15 is about.
 * `analyze_community_sentiment` is keyless, is a real search rather than a
 * stand-in, and returns URLs the writer can cite. Swapping it for `web_search`
 * once a key exists is one field in the inspector.
 *
 * WHAT TO MODIFY FIRST: the writer's `expected_output`. It is the field that
 * decides what comes back, it needs no other change to be safe, and watching
 * one sentence there change the whole deliverable is the fastest way to
 * understand that these prompts are the product.
 */

const NODES = [
  inputNode(
    'topic',
    'Topic',
    'What should the team write about?',
    { x: 340, y: 0 },
  ),
  gateNode(
    'confirm',
    'Confirm the topic',
    'Three agents are about to research and write about this. Approve the topic, or send it back.',
    { x: 340, y: 160 },
  ),
  authoredAgent({
    id: 'research',
    label: 'Research',
    position: { x: 340, y: 320 },
    role: 'Research Analyst',
    goal: 'Find what is actually known about a topic, and where each claim came from.',
    backstory:
      'You have spent a decade checking claims for a newsroom. You would rather report four things you can source than ten you cannot, and you never present a summary as if it were evidence.',
    description:
      'Search the discussion for {topic} and report the five most load-bearing things practitioners say about it — the ones a reader would be wrong without — with the URL each came from.',
    expected:
      'Five numbered findings. Each is one sentence, followed by the URL it came from on its own line. No preamble.',
    model: 'workhorse',
    // Three passes rather than the default two: this is the one node in the
    // graph that calls a tool, and a search that comes back thin is worth
    // asking a second differently-worded question about.
    maxIter: 3,
    promptInputs: { topic: stateRef('topic') },
  }),
  // Keyless, deliberately - see the module note. `params: {}` takes the
  // catalogue's own defaults rather than restating them, so a default that
  // moves in `tools.py` moves here too.
  toolNode('search', 'Search the discussion', 'analyze_community_sentiment', { x: 40, y: 320 }),
  authoredAgent({
    id: 'analyse',
    label: 'Analyse',
    position: { x: 340, y: 480 },
    role: 'Analyst',
    goal: 'Turn a pile of facts into the two or three tensions that actually decide the question.',
    backstory:
      'You read research the way an editor reads a draft: looking for the places where two true things pull in opposite directions, because that is where the reader learns something.',
    description:
      'From the research below, name the three tensions a reader must understand, and give the evidence for each.\n\nRESEARCH:\n{research}',
    expected:
      'Three headed sections. Each names one tension in a short phrase, explains it in two or three sentences, and cites the facts on both sides.',
    model: 'workhorse',
    promptInputs: { research: out('research') },
  }),
  authoredAgent({
    id: 'write',
    label: 'Write',
    position: { x: 340, y: 640 },
    role: 'Writer',
    goal: 'Write something a busy reader finishes and can act on.',
    backstory:
      'You write briefs for people who will read them once, on a phone, between meetings. You put the answer first and you never pad.',
    description:
      'Write a 600-word brief from the analysis below. Headline, three sections, and a sources list at the end.\n\nANALYSIS:\n{analysis}',
    expected:
      'Markdown. An H1 headline, three H2 sections of roughly 200 words each, and a final "Sources" list of the URLs the research carried.',
    model: 'escalation',
    markdown: true,
    promptInputs: { analysis: out('analyse') },
  }),
  outputNode('brief', 'Brief', { x: 340, y: 800 }),
]

export const SEQUENTIAL_PIPELINE_DOCUMENT: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: documentId('ug_00000000'),
  name: 'Sequential pipeline',
  version: 1,
  input_field: nodeId('topic'),
  nodes: NODES,
  edges: [
    flowEdge('e1', 'topic', 'confirm'),
    flowEdge('e2', 'confirm', 'research', 'approve'),
    flowEdge('e3', 'research', 'analyse'),
    flowEdge('e4', 'analyse', 'write'),
    flowEdge('e5', 'write', 'brief'),
    attachEdge('e6', 'search', 'research'),
  ],
  // Nothing waits for anything here: every node has exactly one predecessor,
  // which is what makes this the template to read first.
  joins: {},
  budget: null,
}
