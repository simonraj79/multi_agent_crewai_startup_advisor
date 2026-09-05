import { BUILDER_SCHEMA_ID, documentId, nodeId } from '../../types/builder'
import type { BuilderDocument } from '../../types/builder'
import {
  attachEdge,
  authoredAgent,
  flowEdge,
  inputNode,
  out,
  outputNode,
  stateRef,
  toolNode,
} from './authoring'

/**
 * Search what has just been said about a topic, then write the post about it.
 *
 * Two billable nodes and nothing else - the smallest graph in the gallery that
 * still does a real job end to end. `sequential-pipeline` teaches the syntax;
 * this one teaches that the syntax is enough. A researcher with a search tool
 * hands its findings to a writer on the escalation tier, and what comes back is
 * something you could paste into a feed.
 *
 * TWO NODES IS THE DESIGN, not a first draft of a bigger one. A middle
 * "analyse" step would double the price and change nothing an author could see
 * in the output, because the writer is already reading five sourced items and
 * a 280-character post is not a thing that benefits from being summarised
 * twice. The template's whole argument is that a useful agent graph can be
 * this small.
 *
 * WHY IT IS GATELESS, and what that costs. Every other pattern template puts a
 * human gate above its first billable node, which is what makes it launchable
 * by a signed-OUT visitor: `create_run` answers **403** for a published graph
 * that reaches a billable node before any human gate unless
 * `BUILDER_ALLOW_GATELESS_GRAPHS` is set, on the argument that while nobody is
 * signed in, human inaction IS the spend cap. This template is meant to be run
 * unattended by somebody who IS signed in, so it carries no gate and pays that
 * price knowingly - the card's caveat states it in the author's own terms and
 * `PublishDialog` renders the 403 sentence verbatim before anyone shares a
 * link. It is the same shape `idea-validator` already ships in, and it is the
 * only one of the two that chose it rather than inherited it.
 *
 * WHY THE TOOL IS HACKER NEWS AND NOT FIRECRAWL. `firecrawl_search` is the
 * obvious choice for a news graph and it cannot be shipped in a template today:
 * its catalogue entry is `credential_optional=False` unconditionally
 * (`builder/tools.py`), so a template naming it opens with a
 * `tool-credential-required` error on a graph nobody has touched, and could not
 * be launched from a cold sign-in at all. `BUILDER_PLATFORM_FIRECRAWL_DEFAULT`
 * does NOT reach it - the flag is read by exactly one entry,
 * `research_market_landscape`, whose factory falls back to the process
 * `FIRECRAWL_API_KEY`; `_firecrawl` raises instead. `analyze_community_sentiment`
 * is keyless, is a real search of what practitioners are actually saying this
 * week, and cites an item URL for every thread it returns. Swapping it for a
 * Firecrawl search once a key exists is one field in the inspector, and the
 * writer's prompt does not change: it cites whatever URLs the tool returned.
 *
 * WHY THE INPUT FIELD IS `subject` AND NOT `topic`. `sequential-pipeline`
 * already declares `topic`, and `data/templates/testInputs.ts` resolves a
 * template's saved sample BY ITS INPUT FIELD rather than by template id - a
 * document carries no provenance once it is cloned onto the canvas, so the
 * field is the only thing left to key on. Two templates sharing one field
 * therefore share one sample, and "AI agents" is not the sample somebody
 * opening the research pipeline should be handed. The field is the name of a
 * slot in a run request; the word an author reads is the node's label and the
 * prompt below it, and both of those say topic.
 *
 * WHAT TO MODIFY FIRST: the subject. It is the one field that changes the
 * whole output and needs no other edit to stay safe, and it is on the input
 * node rather than inside a prompt precisely so that running this a second
 * time about something else is one box and one click.
 */

const NODES = [
  inputNode('subject', 'Subject', 'What should the post be about?', { x: 340, y: 0 }),
  authoredAgent({
    id: 'research',
    label: 'Find the news',
    position: { x: 340, y: 180 },
    role: 'News Researcher',
    goal: 'Find what has actually happened lately, and the page each item was reported on.',
    backstory:
      'You are the person on the desk who reads everything so nobody else has to. You would rather file three items you can link to than eight you half remember, and you have never once written "reportedly" about something you did not read.',
    description:
      'Search for what has been said in the last 7 days about {topic}.\n\nEvery row the search returns carries a `date` and a `date_is_retrieval_time` flag. Drop every row whose `date_is_retrieval_time` is true — that date is the moment of the search, not the item. Of what is left, report the three to five most newsworthy items dated within the last 7 days. For each: what happened, the URL it came from, and its date.\n\nCite ONLY URLs the search tool returned to you. If fewer than three items fall inside the 7 days, say so in one line and then list the most recent ones you did find, each with its own date, so the reader can see how old they are. Do not fill the gap from memory.',
    expected:
      'Three to five numbered items. Each is a short title, then the source URL on its own line, then the date on its own line, then one sentence saying what happened. Every URL is one the search returned and every item carries a date. No preamble.',
    model: 'workhorse',
    // Six passes rather than the default two. This is the only node in the
    // graph that calls a tool, and "the last 7 days" is a query worth asking a
    // second, differently-worded time when the first comes back thin.
    //
    // It was THREE until 2026-09-05, and the raise is a measurement rather than
    // generosity: run `a9887442` failed at the cap, because CrewAI asks for a
    // final answer there by appending a MODEL turn and Google refuses a request
    // that ends in one. `builder/max_iter.py` makes that request legal, and this
    // makes reaching it rarer - the two are belt and braces, and the belt is the
    // one that stops it costing money. The cost of the raise is bounded and
    // small: the static estimate prices every node as if the loop ran to the
    // cap, so it is the only figure that moves, and it moves inside the ceiling.
    maxIter: 6,
    // The prompt VARIABLE and the state KEY are different things, and this is
    // the one node in the gallery where they differ visibly: `{topic}` is what
    // the task text interpolates, `${state.subject}` is where the value comes
    // from. They are two names because the field could not be `topic` - see
    // the note on the field below.
    promptInputs: { topic: stateRef('subject') },
  }),
  // Keyless, deliberately - see the module note. `params: {}` takes the
  // catalogue's own defaults rather than restating them, so a default that
  // moves in `tools.py` moves here too.
  toolNode('search', 'Search the discussion', 'analyze_community_sentiment', { x: 40, y: 180 }),
  authoredAgent({
    id: 'write',
    label: 'Write the post',
    position: { x: 340, y: 360 },
    role: 'Social Editor',
    goal: 'Turn a handful of sourced items into one post somebody stops scrolling for.',
    backstory:
      'You write the account people actually follow. You know the first line is the whole of the decision to read on, that a link is worth more than an adjective, and that a wall of hashtags reads as somebody who has nothing to say.',
    description:
      'Write a social post from the items below.\n\nGive two things:\n1. SHORT — one post of at most 280 characters, for an X or LinkedIn-style feed. It must be under 280 including any link.\n2. LONG — a two-to-three sentence variant for a feed with room.\n\nRules: cite the source URLs from the research; skip any item that carries no date; at most three hashtags and none of them generic; invent nothing that is not in the items below. If the research is thin, write the honest short post rather than padding it.\n\nReturn the two sections and nothing else. Do not introduce them, do not explain your choices and do not show your working: no "Here is", no "Okay", no counting characters out loud, no note about what you skipped.\n\nITEMS:\n{items}',
    expected:
      'Exactly two Markdown sections and nothing else: a line reading "# Short" with the post under it, then a line reading "# Long" with the long variant under it. Nothing before "# Short", nothing between the two sections but their own text, nothing after the long variant. No preamble, no commentary, no reasoning, no character counts. Short is at most 280 characters. Both carry the source URLs. At most three hashtags in total.',
    model: 'escalation',
    markdown: true,
    promptInputs: { items: out('research') },
  }),
  outputNode('post', 'Post', { x: 340, y: 540 }),
]

export const NEWS_TO_SOCIAL_DOCUMENT: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: documentId('ug_00000000'),
  name: 'News to social post',
  version: 1,
  input_field: nodeId('subject'),
  nodes: NODES,
  edges: [
    flowEdge('e1', 'subject', 'research'),
    flowEdge('e2', 'research', 'write'),
    flowEdge('e3', 'write', 'post'),
    attachEdge('e4', 'search', 'research'),
  ],
  // Nothing waits for anything: a straight line of three, with one possession
  // hung off the first.
  joins: {},
  budget: null,
}

/**
 * The two things about this graph its picture cannot carry, rendered verbatim.
 *
 * The first is a rule of the SERVICE rather than of the graph, and an author
 * who publishes this and hands the link to somebody signed out would otherwise
 * meet it as a 403 with no warning. The second is why the search is Hacker News
 * and what to change when a Firecrawl key exists.
 */
export const NEWS_TO_SOCIAL_CAVEAT =
  'No human gate, so it runs unattended — which means only a signed-in caller may launch it. '
  + 'Hand the link to somebody signed out and the service answers 403; add a gate above the '
  + 'researcher if you need that. The search is Hacker News, which needs no key; swap it for a '
  + 'Firecrawl web search in the inspector once you have added one.'
