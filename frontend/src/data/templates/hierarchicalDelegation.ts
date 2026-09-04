import { BUILDER_SCHEMA_ID, documentId, nodeId } from '../../types/builder'
import type { BuilderDocument } from '../../types/builder'
import {
  authoredAgent,
  authoredCrew,
  flowEdge,
  gateNode,
  inputNode,
  memberEdge,
  out,
  outputNode,
  stateRef,
} from './authoring'

/**
 * A manager and three specialists, inside one crew node.
 *
 * The other three templates put every agent on the canvas as a step. This one
 * puts three of them INSIDE something, and the difference is the whole lesson:
 * a `crew` node is a real `Crew`, its members are `Agent`s the crew owns, and
 * the crew — not the graph — decides what runs when.
 *
 * THREE THINGS IT TEACHES:
 *
 * 1. **A member edge is not a flow edge.** `market -> team` arrives at the
 *    `member` port, and a member agent may carry NO flow edges at all - 03's
 *    `member-agent-has-flow-edges` refuses one that does, because a node that
 *    was both would run twice and nothing downstream could say which output it
 *    was reading. The three specialists are wired to the crew and to nothing
 *    else, and that looks wrong until you understand it, which is why they are
 *    drawn in a row underneath rather than in the flow's column.
 * 2. **`hierarchical` without a manager is refused, twice.** CrewAI raises at
 *    `Crew.__init__` (`crew.py:729`) and `AuthoredCrewConfig._validate_manager`
 *    raises before the document can even be saved. Clearing `manager_llm` here
 *    is the fastest way to see a rule enforced before it can cost anything.
 * 3. **The manager is a real cost.** It runs on the escalation model and it
 *    calls once per member plus once to assemble - which is why the crew node
 *    declares `tier: 'escalation'` while every member declares `cheap`.
 *
 * WHAT TO MODIFY FIRST: `process`. Flip it to `sequential` and watch the
 * manager disappear from the inspector and from the price - `_validate_manager`
 * refuses a sequential crew that still names one, so the two changes are one
 * change.
 */

const NODES = [
  inputNode(
    'brief',
    'Brief',
    'Describe the deliverable.',
    { x: 340, y: 0 },
  ),
  gateNode(
    'confirm',
    'Confirm the brief',
    'A manager and three specialists are about to work from this brief. Approve it, or send it back.',
    { x: 340, y: 160 },
  ),
  authoredCrew({
    id: 'team',
    label: 'Delivery team',
    position: { x: 340, y: 320 },
    process: 'hierarchical',
    // The order the members' tasks run in. It names the three `member` edges
    // rather than declaring them: `bounds.py` checks this list against the
    // edges actually drawn, because only that module knows both.
    taskOrder: ['market', 'product', 'risk'],
    managerRole: 'escalation',
    // The escalation-most tier anything inside this node runs on. Declared
    // rather than derived, because the document is priced before a single
    // `Agent` is constructed.
    tier: 'escalation',
    promptInputs: { brief: out('confirm') },
  }),
  authoredAgent({
    id: 'market',
    label: 'Market',
    position: { x: 40, y: 500 },
    role: 'Market Specialist',
    goal: 'Say who would pay for this and roughly how many of them there are.',
    backstory:
      'You have sized enough markets to distrust a number with no buyer attached to it. You would rather name one segment you can describe than three you cannot.',
    description: 'Size the market for {brief} and name the buyer.',
    expected:
      'Two short paragraphs: the buyer, described specifically enough to find one, and the size with the reasoning that produced it.',
    model: 'workhorse',
    promptInputs: { brief: stateRef('brief') },
  }),
  authoredAgent({
    id: 'product',
    label: 'Product',
    position: { x: 340, y: 500 },
    role: 'Product Specialist',
    goal: 'Draw the smallest first version that is still worth shipping.',
    backstory:
      'You have watched more products die of scope than of competition. Everything you cut, you cut on purpose and can say why.',
    description: 'Define the v1 scope for {brief} in five bullets.',
    expected: 'Exactly five bullets, each one shippable on its own, ordered by what to build first.',
    model: 'workhorse',
    promptInputs: { brief: stateRef('brief') },
  }),
  authoredAgent({
    id: 'risk',
    label: 'Risk',
    position: { x: 640, y: 500 },
    role: 'Risk Specialist',
    goal: 'Name the ways this fails while there is still time to notice.',
    backstory:
      'You write the pre-mortem nobody asks for. A risk with no early signal attached is, to you, just an opinion.',
    description: 'List the three ways {brief} fails, and the early signal for each.',
    expected:
      'Three numbered failures. Each is one sentence for the failure and one for the signal that would show it first.',
    model: 'workhorse',
    promptInputs: { brief: stateRef('brief') },
  }),
  outputNode('plan', 'Plan', { x: 340, y: 680 }),
]

export const HIERARCHICAL_DELEGATION_DOCUMENT: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: documentId('ug_00000000'),
  name: 'Hierarchical delegation',
  version: 1,
  input_field: nodeId('brief'),
  nodes: NODES,
  edges: [
    flowEdge('e1', 'brief', 'confirm'),
    flowEdge('e2', 'confirm', 'team', 'approve'),
    flowEdge('e3', 'team', 'plan'),
    memberEdge('e4', 'market', 'team'),
    memberEdge('e5', 'product', 'team'),
    memberEdge('e6', 'risk', 'team'),
  ],
  // The fan-out is INSIDE the crew, so the flow has nothing to wait for. That
  // is the difference between this template and `fan-out-join`, and it is worth
  // opening both to see.
  joins: {},
  budget: null,
}
