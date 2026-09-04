/**
 * The design-time canvas surfaces: the card, its ports, the edge, the palette
 * and the port menu.
 *
 * The gap these close is the one `flow-builder-spec.md` §6.1 names as the most
 * expensive kind available here - a port that is DRAWN and a port that is
 * ACCEPTED disagreeing. The disagreement is silent in both directions: a drawn
 * port the compiler does not know produces `edge-unknown-port` on an edge the
 * author was invited to draw, and a port not drawn is a branch that cannot be
 * reached from the canvas at all. Everything below asserts against rendered
 * structure rather than against a snapshot, so a change to the card's wording
 * does not fail a test about its ports.
 *
 * The second gap is cheaper to describe and just as easy to reintroduce: the
 * problem tenancy of `--node-gradient` OUTRANKS the kind tenancy only because
 * `builder.css` writes it second (§5.1). Nothing in the CSS says so; the class
 * binding here is what a test can hold.
 */
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import BuilderNode, { summariseConfig, type BuilderNodeData } from '../src/components/builder/BuilderNode.vue'
import BuilderEdge, { type BuilderEdgeData } from '../src/components/builder/BuilderEdge.vue'
import NodePalette, { BUILDER_KIND_MIME, isBillableKind } from '../src/components/builder/NodePalette.vue'
import PortMenu, { titleiseId, type PortMenuCreation } from '../src/components/builder/PortMenu.vue'
import { resetVocabulary, vocabulary } from '../src/data/builderVocabulary'
import { isAuthoredAgent } from '../src/types/builder'
import { edgeClassOf, targetPortsOf } from '../src/composables/useBuilderCanvas'
import type { NodeAttachment } from '../src/composables/useBuilderCanvas'
import { authoredAgentNode, authoredCrewNode } from './builderInspectorFixtures'
import { NODE_KINDS, outPortsOf } from '../src/data/nodeKinds'
import {
  nodeId,
  type BuilderNode as DocumentNode,
  type BuilderProblem,
  type BuilderVocabulary,
  type LlmConfig,
  type NodeKind,
} from '../src/types/builder'

/* ─── fixtures ───────────────────────────────────────────────────────────── */

const VOCABULARY: BuilderVocabulary = {
  schema_id: 'builder.flow/v1',
  node_kinds: ['input', 'agent', 'crew', 'gate', 'router', 'transform', 'output'],
  tiers: ['cheap', 'escalation'],
  agent_ids: ['market_analyst', 'scoper'],
  crew_ids: ['brief'],
  research_tools: ['github_feasibility', 'market_research'],
  transform_ops: ['default', 'format', 'join_text', 'merge', 'pick', 'to_json'],
  router_comparisons: ['contains', 'eq', 'gt', 'gte', 'lt', 'lte', 'ne'],
  router_otherwise: 'otherwise',
  result_body_keys: ['markdown_body'],
  bounds: {
    max_graph_nodes: 24,
    max_billable_nodes: 8,
    max_escalation_nodes: 5,
    max_fanout_width: 4,
    min_router_branches: 2,
    max_cycles: 2,
    max_cycle_iterations: 3,
    max_agent_iter: 8,
    max_guardrail_retries: 2,
    max_label_chars: 40,
    max_name_chars: 80,
    max_gate_message_chars: 2000,
    max_input_chars: 2000,
    max_document_bytes: 262144,
    run_cost_ceiling_usd: 10,
    // C2 v2\'s two authored-node bounds: BUILDER_MAX_PROMPT_CHARS and
    // BUILDER_MAX_NODE_RETRIES, served since plan 04 and read by every
    // PromptField and node-retry stepper rather than restated as a constant.
    max_prompt_chars: 4000,
    max_retries: 3,
  },
}

function seedVocabulary(): void {
  vocabulary.value = VOCABULARY
}

/*
 * Every wrapper is unmounted when its test ends.
 *
 * This file mounts about forty components, and a wrapper that is never
 * unmounted stays live for the rest of the FILE: its watchers keep running, its
 * scheduler jobs stay queued, and anything it holds open outlives the test that
 * created it. Vitest reuses one worker across files, so a job queued here and
 * flushed later is reported against whichever file happened to be running -
 * which is precisely how it presents, and precisely why it is nearly
 * un-bisectable. Nothing in this suite depends on a wrapper surviving its own
 * test, so the cheap fix is also the correct one.
 */
enableAutoUnmount(afterEach)

afterEach(() => {
  resetVocabulary()
})

const NODES: { [K in NodeKind]: DocumentNode } = {
  input: {
    id: nodeId('idea'),
    kind: 'input',
    label: 'Idea',
    position: { x: 0, y: 0 },
    config: { field: nodeId('idea'), label: null, max_chars: 2000, required: true },
  },
  agent: {
    id: nodeId('scoper'),
    kind: 'agent',
    label: 'Scoper',
    position: { x: 0, y: 0 },
    config: {
      tier: 'escalation',
      max_iter: 2,
      guardrail_max_retries: 2,
      prompt_inputs: {},
      agent_id: nodeId('scoper'),
      tools: [],
    },
  },
  crew: {
    id: nodeId('brief'),
    kind: 'crew',
    label: 'Brief crew',
    position: { x: 0, y: 0 },
    config: {
      tier: 'escalation',
      max_iter: 2,
      guardrail_max_retries: 2,
      prompt_inputs: {},
      crew_id: nodeId('brief'),
    },
  },
  gate: {
    id: nodeId('confirm'),
    kind: 'gate',
    label: 'Confirm scope',
    position: { x: 0, y: 0 },
    config: {
      message: 'Review this step.',
      editable_fields: [nodeId('idea'), nodeId('scope')],
      max_turns: 1,
      expiry_seconds: 1800,
    },
  },
  router: {
    id: nodeId('route'),
    kind: 'router',
    label: 'Route scope',
    position: { x: 0, y: 0 },
    config: {
      branches: [
        { label: nodeId('approve'), op: 'eq', key: nodeId('decision'), value: 'approve' },
        { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
      ],
    },
  },
  transform: {
    id: nodeId('shape'),
    kind: 'transform',
    label: 'Shape it',
    position: { x: 0, y: 0 },
    config: { op: 'pick', args: { source: '${state.out__scoper}', key: 'summary' } },
  },
  output: {
    id: nodeId('report'),
    kind: 'output',
    label: 'Report',
    position: { x: 0, y: 0 },
    config: { body_key: 'markdown_body', source: null },
  },
  tool: {
    id: nodeId('scrape'),
    kind: 'tool',
    label: 'Scrape',
    position: { x: 0, y: 0 },
    config: { tool_id: nodeId('firecrawl_scrape'), params: {}, credential_id: null },
  },
  mcp: {
    id: nodeId('sandbox'),
    kind: 'mcp',
    label: 'Sandbox',
    position: { x: 0, y: 0 },
    config: { server_id: nodeId('sandbox'), tool_names: ['run', 'read'], credential_id: null },
  },
  skill: {
    id: nodeId('house_style'),
    kind: 'skill',
    label: 'House style',
    position: { x: 0, y: 0 },
    config: { skill_id: nodeId('house_style') },
  },
}

/**
 * A projection of one node, shaped exactly as `useBuilderCanvas` shapes it.
 *
 * `ports`, `acceptsIncoming` and `severity` are DERIVED here rather than
 * defaulted, because the canvas derives them too - a fixture that let a caller
 * hand the card a `gate` with one port would be testing a state the projection
 * cannot produce, and passing.
 */
function nodeData(node: DocumentNode, overrides: Partial<BuilderNodeData> = {}): BuilderNodeData {
  const problems = overrides.problems ?? []
  return {
    node,
    index: 3,
    ports: outPortsOf(node),
    acceptsIncoming: NODE_KINDS[node.kind].acceptsIncoming,
    targetPorts: targetPortsOf(node.kind),
    problems,
    severity: problems.some((entry) => entry.severity === 'error')
      ? 'error'
      : problems.length > 0
        ? 'warning'
        : null,
    joined: false,
    anchor: false,
    loopTarget: false,
    loopIllegal: false,
    connectable: false,
    flashing: false,
    runState: 'idle',
    inbound: 0,
    landing: false,
    refused: false,
    ...overrides,
  }
}

function problem(overrides: Partial<BuilderProblem> = {}): BuilderProblem {
  return {
    code: 'node-unreachable',
    severity: 'error',
    message: 'Node "scoper" is not reachable from the input node.',
    node_id: 'scoper',
    edge_id: null,
    ...overrides,
  }
}

function mountNode(data: BuilderNodeData, selected = false) {
  return mount(BuilderNode, {
    props: { id: data.node.id, data, selected },
    global: { stubs: { Handle: true } },
  })
}

/** Every stubbed `<Handle>`, in render order. */
function handles(wrapper: ReturnType<typeof mountNode>) {
  return wrapper.findAll('handle-stub')
}

/* ─── the card ───────────────────────────────────────────────────────────── */

describe('the design-time card is the run card, re-tenanted', () => {
  it('keeps the run console card class so one stylesheet dresses both', () => {
    const wrapper = mountNode(nodeData(NODES.agent))
    const article = wrapper.get('article')
    // `.workflow-node` is what `node-card.css` hangs the double-clip gradient
    // border, the radius, the fill and the shadow off. Dropping it is how the
    // two canvases quietly become two products.
    expect(article.classes()).toContain('workflow-node')
    expect(article.classes()).toContain('builder-node')
    expect(article.classes()).toContain('is-kind-agent')
  })

  it('renders no crew SVG and no lap chip - both are run-console chrome', () => {
    const wrapper = mountNode(nodeData(NODES.agent, { runState: 'running' }))
    expect(wrapper.find('.node-crew').exists()).toBe(false)
    expect(wrapper.find('[data-testid="node-lap"]').exists()).toBe(false)
  })

  it('marks a problem above the kind, and an error above a warning', () => {
    const clean = mountNode(nodeData(NODES.agent))
    expect(clean.get('article').classes()).not.toContain('has-error')
    expect(clean.get('article').classes()).not.toContain('has-warning')

    const warned = mountNode(
      nodeData(NODES.agent, { problems: [problem({ severity: 'warning' })] }),
    )
    expect(warned.get('article').classes()).toContain('has-warning')
    expect(warned.get('article').classes()).not.toContain('has-error')

    // One error under any number of warnings is still a document that will not
    // publish, so severity wins outright rather than by count.
    const mixed = mountNode(
      nodeData(NODES.agent, {
        problems: [problem({ severity: 'warning' }), problem({ severity: 'error' })],
      }),
    )
    expect(mixed.get('article').classes()).toContain('has-error')
    expect(mixed.get('article').classes()).not.toContain('has-warning')
    // The kind class survives, because the two are independent channels and the
    // cascade - not the template - is what decides which colour wins.
    expect(mixed.get('article').classes()).toContain('is-kind-agent')
  })

  it('prints the server sentence verbatim, never a paraphrase', () => {
    const sentence = 'Router "route" declares 5 branches; max_router_branches is 4.'
    const wrapper = mountNode(
      nodeData(NODES.router, { problems: [problem({ message: sentence })] }),
    )
    expect(wrapper.get('.builder-problem-pop').text()).toContain(sentence)
    expect(wrapper.get('.builder-badge-problem').attributes('aria-label')).toContain(sentence)
  })

  it('rings only the escalation tier, and only on the two kinds that have one', () => {
    expect(mountNode(nodeData(NODES.agent)).get('article').classes()).toContain('is-tier-escalation')

    const cheap: DocumentNode = {
      ...NODES.agent,
      config: { ...NODES.agent.config, tier: 'cheap' },
    } as DocumentNode
    expect(mountNode(nodeData(cheap)).get('article').classes()).not.toContain('is-tier-escalation')

    // A gate has no `tier` at all - `_BillableConfig` is the base only
    // `AgentConfig` and `CrewConfig` extend - so it can never carry the ring.
    expect(mountNode(nodeData(NODES.gate)).get('article').classes()).not.toContain(
      'is-tier-escalation',
    )
    expect(mountNode(nodeData(NODES.gate)).find('.builder-badge-escalation').exists()).toBe(false)
  })

  it('numbers the eyebrow from document order, zero-padded', () => {
    const wrapper = mountNode(nodeData(NODES.agent, { index: 3 }))
    expect(wrapper.get('.builder-eyebrow').text()).toBe('03 · AGENT')
  })

  it('shows the join glyph on a fan-in and reports which way it is set', async () => {
    const single = mountNode(nodeData(NODES.agent, { inbound: 1 }))
    expect(single.find('.builder-badge-join').exists()).toBe(false)

    const fanIn = mountNode(nodeData(NODES.agent, { inbound: 3, joined: true }))
    const glyph = fanIn.get('.builder-badge-join')
    expect(glyph.attributes('aria-pressed')).toBe('true')

    // The toggle is a request, never a mutation: `commit()` is the only write
    // path in the whole editor (§1.1 invariant 1).
    await glyph.trigger('click')
    expect(fanIn.emitted('toggle-join')).toEqual([[{ id: 'scoper', joined: false }]])
  })

  it('says everything the card shows to a screen reader', () => {
    const wrapper = mountNode(
      nodeData(NODES.gate, { problems: [problem({ severity: 'warning' })], joined: true }),
    )
    const label = wrapper.get('article').attributes('aria-label')
    expect(label).toContain('Confirm scope')
    expect(label).toContain('gate')
    expect(label).toContain('1 turn · 2 editable')
    expect(label).toContain('1 warning')
    expect(label).toContain('waits for every inbound branch')
  })
})

describe('the config summary answers "what is this set to" without a click', () => {
  it('reads each kind the way §5.2 enumerates it', () => {
    expect(summariseConfig(NODES.input)).toBe('idea · 2000 chars · required')
    expect(summariseConfig(NODES.agent)).toBe('escalation · scoper · 2 iter · no tools')
    expect(summariseConfig(NODES.crew)).toBe('escalation · brief')
    expect(summariseConfig(NODES.gate)).toBe('1 turn · 2 editable')
    expect(summariseConfig(NODES.router)).toBe('2 branches')
    expect(summariseConfig(NODES.transform)).toBe('pick · source, key')
    expect(summariseConfig(NODES.output)).toBe('markdown_body')
  })

  it('answers "which one is this" for each of the three attachments', () => {
    // The only question a 160px pill can be asked without opening it. An author
    // looking at a canvas of eight tools needs to tell them apart, not to read
    // their parameters.
    expect(summariseConfig(NODES.tool)).toBe('firecrawl_scrape')
    expect(summariseConfig(NODES.mcp)).toBe('sandbox · 2 tools')
    expect(summariseConfig(NODES.skill)).toBe('house_style')
  })

  it('says an MCP node with nothing selected exposes nothing', () => {
    // Nought is worth saying out loud. `McpConfig` does not require `tool_names`
    // to be non-empty at parse time - `document.py` raises where `bounds.py`
    // reports - so this is a node an author can really have, and the card must
    // not read like one that is finished.
    const empty: DocumentNode = {
      ...NODES.mcp,
      config: { ...NODES.mcp.config, tool_names: [] },
    } as DocumentNode
    expect(summariseConfig(empty)).toBe('sandbox · 0 tools')
  })

  it('counts tools rather than listing them, so the line never wraps', () => {
    const armed: DocumentNode = {
      ...NODES.agent,
      config: { ...NODES.agent.config, tools: ['market_research'] },
    } as DocumentNode
    expect(summariseConfig(armed)).toBe('escalation · scoper · 2 iter · 1 tool')
  })
})

/* ─── D6: what an AUTHORED node is made of (criterion 8) ─────────────────── */

/**
 * The card's second job, which the summary line cannot do.
 *
 * `summariseConfig` answers "what is this set to". These chips answer "what is
 * this made of" - the model, the crew's process and manager, and the hands. The
 * two are separate elements rather than one longer sentence because D6 asks for
 * three different behaviours out of the model fact alone: it is the loudest
 * token on the card, it carries the full slug in a `title`, and 04 D4 wants it
 * to move in the same tick the picker writes `llm.model`. A slice of a
 * `·`-joined string can do none of the three.
 *
 * The avatars are DRAWN ON THE HOST while the pills stay on the canvas, which
 * is deliberate duplication (D6): the pill is where an attachment is
 * configured, the avatar is where you see whose hands it is. A dropdown inside
 * the form - Flowise's `agentTools` - cannot show that two agents share one
 * tool, and the canvas can.
 */
describe("an authored card shows what it is MADE of, not only what it is set to", () => {
  /** One `LlmConfig`, so the manager pill's fixture is a real one. */
  const MANAGER_LLM: LlmConfig = {
    model: 'google/gemini-3.8-flash',
    temperature: null,
    top_p: null,
    max_tokens: null,
    timeout: null,
    response_format: null,
    frequency_penalty: null,
    presence_penalty: null,
    stop: [],
    seed: null,
    reasoning_effort: null,
  }

  const TOOL = (id: string, label: string): NodeAttachment => ({
    id: nodeId(id),
    kind: 'tool',
    label,
  })

  it('renders a model pill and one avatar per attachment', () => {
    const wrapper = mountNode(
      nodeData(authoredAgentNode('writer'), {
        attachments: [TOOL('scrape', 'Scrape'), TOOL('search', 'Search'), TOOL('repo', 'Repos')],
      }),
    )

    const pill = wrapper.get('[data-testid="node-model-pill"]')
    // The half after the slash, because `google/gemini-3.5-flash-lite` clips at
    // this type size and the provider is the roster's business, not the canvas's.
    expect(pill.text()).toBe('gemini-3.5-flash-lite')
    expect(pill.attributes('title')).toBe('google/gemini-3.5-flash-lite')

    expect(wrapper.findAll('.builder-attach-avatar')).toHaveLength(3)
    expect(wrapper.find('[data-testid="node-attachments-more"]').exists()).toBe(false)
  })

  it('draws four avatars and a +1 when a fifth is attached', () => {
    /*
     * FOUR, per D6, and the fifth becomes a count rather than a fifth disc:
     * `NODE_W` is 240px and five 20px avatars plus the model pill do not fit
     * beside each other. `+1` rather than `4 of 5` because the question an
     * author answers at a glance is "is there more than I can see".
     */
    const wrapper = mountNode(
      nodeData(authoredAgentNode('writer'), {
        attachments: [
          TOOL('a', 'A'),
          TOOL('b', 'B'),
          { id: nodeId('c'), kind: 'mcp', label: 'Sandbox' },
          { id: nodeId('d'), kind: 'skill', label: 'House style' },
          TOOL('e', 'E'),
        ],
      }),
    )

    expect(wrapper.findAll('.builder-attach-avatar')).toHaveLength(4)
    expect(wrapper.get('[data-testid="node-attachments-more"]').text()).toBe('+1')
  })

  it('gives each avatar its own kind, glyph and accent rather than one badge', () => {
    // Three attachments that all looked alike would answer "there are three"
    // and never "which three", which is the whole difference between an avatar
    // and a counter.
    const wrapper = mountNode(
      nodeData(authoredAgentNode('writer'), {
        attachments: [
          TOOL('a', 'Scrape'),
          { id: nodeId('b'), kind: 'mcp', label: 'Sandbox' },
          { id: nodeId('c'), kind: 'skill', label: 'House style' },
        ],
      }),
    )
    const avatars = wrapper.findAll('.builder-attach-avatar')
    expect(avatars.map((node) => node.attributes('data-attachment-kind'))).toEqual([
      'tool',
      'mcp',
      'skill',
    ])
    // The accent is `nodeKinds.ts`'s, passed as the same custom property the
    // kind squircle and the minimap dot read, so one string dresses all three.
    expect(avatars[1].attributes('style')).toContain(NODE_KINDS.mcp.accent)
    expect(avatars.map((node) => node.attributes('title'))).toEqual([
      'Scrape',
      'Sandbox',
      'House style',
    ])
  })

  it('shows nothing of the sort on a LIBRARY agent, whose model it did not choose', () => {
    // Its identity is `agent_id` and its model is the tier's. A pill naming a
    // model the author never picked would invite an edit with no control behind
    // it.
    const wrapper = mountNode(nodeData(NODES.agent))
    expect(wrapper.find('[data-testid="node-model-pill"]').exists()).toBe(false)
    expect(wrapper.find('.builder-node-chips').exists()).toBe(false)
  })

  it('marks a hierarchical crew `hier` and names its manager model', () => {
    const wrapper = mountNode(
      nodeData(
        authoredCrewNode('team', {
          process: 'hierarchical',
          manager_llm: { ...MANAGER_LLM, model: 'google/gemini-3.8-flash' },
        }),
      ),
    )
    expect(wrapper.get('[data-testid="node-process-chip"]').text()).toBe('hier')
    const manager = wrapper.get('[data-testid="node-manager-pill"]')
    expect(manager.text()).toBe('gemini-3.8-flash')
    expect(manager.attributes('title')).toBe('Manager · google/gemini-3.8-flash')
  })

  it('marks a sequential crew `seq` and shows no manager, because it has none', () => {
    // `Crew.__init__` refuses a manager on a sequential crew, so an empty slot
    // here would be a slot that can never fill.
    const wrapper = mountNode(nodeData(authoredCrewNode('team')))
    expect(wrapper.get('[data-testid="node-process-chip"]').text()).toBe('seq')
    expect(wrapper.find('[data-testid="node-manager-pill"]').exists()).toBe(false)
  })

  it('says nothing about a LIBRARY crew, which has no process to name', () => {
    expect(mountNode(nodeData(NODES.crew)).find('.builder-node-chips').exists()).toBe(false)
  })
})

/* ─── identity: silhouette, squircle, accent (D5) ────────────────────────── */

describe('a node says what it is three ways before a word of it is read', () => {
  it('draws a flow node as a card and an attachment as a pill', () => {
    /*
     * D5's third channel, and the one that survives the zoom the other two do
     * not: at 0.5 an 11px eyebrow is 5.5px and two violets eight points of
     * lightness apart are one colour, while a 160px pill beside a 240px card is
     * still unmistakably a different sort of object. A pill can never be
     * mistaken for a step.
     *
     * `is-card` is asserted as a POSITIVE class rather than as the absence of
     * `is-pill`, because a stylesheet and a capture both need something to name.
     */
    for (const kind of Object.keys(NODES) as NodeKind[]) {
      const wrapper = mountNode(nodeData(NODES[kind]))
      const attachment = NODE_KINDS[kind].family === 'attachment'
      expect(wrapper.classes(), kind).toContain(attachment ? 'is-pill' : 'is-card')
      expect(wrapper.classes(), kind).not.toContain(attachment ? 'is-card' : 'is-pill')
    }
  })

  it('puts every kind icon in a squircle filled with that kind accent', () => {
    // Criterion 7 captures this in a real browser; this is the structural half.
    // The fill is passed as `--kind-accent` rather than as a `background`, so
    // the radius, the size and the one contrast decision stay in the stylesheet
    // and the COLOUR provably comes from `nodeKinds.ts` - the same value the
    // minimap dot and the inspector kicker read.
    for (const kind of Object.keys(NODES) as NodeKind[]) {
      const wrapper = mountNode(nodeData(NODES[kind]))
      const squircle = wrapper.find('.builder-kind-squircle')
      expect(squircle.exists(), `${kind} has no squircle`).toBe(true)
      expect(squircle.attributes('style')).toContain(`--kind-accent: ${NODE_KINDS[kind].accent}`)
    }
  })

  it('gives every kind its own eyebrow word, and the same index either way', () => {
    // The pill keeps the card's eyebrow CONTENT - only the type scale shrinks -
    // because an author walking the problems dock needs the same number on both
    // silhouettes.
    const words = (Object.keys(NODES) as NodeKind[]).map((kind) =>
      mountNode(nodeData(NODES[kind])).find('.builder-eyebrow').text(),
    )
    expect(words).toEqual([
      '03 · INPUT',
      '03 · AGENT',
      '03 · CREW',
      '03 · GATE',
      '03 · ROUTER',
      '03 · TRANSFORM',
      '03 · OUTPUT',
      '03 · TOOL',
      '03 · MCP',
      '03 · SKILL',
    ])
    expect(new Set(words).size).toBe(words.length)
  })

  it('renders an attachment config as chips and a flow config as the mono line', () => {
    // D6. A 160px pill ellipsises a comma-separated sentence to nothing, and a
    // truncated fact is worse than a shorter one because it invites the click
    // into a modal R15 bans.
    const pill = mountNode(nodeData(NODES.mcp))
    expect(pill.find('.builder-summary').exists()).toBe(false)
    expect(pill.findAll('.builder-chip').map((chip) => chip.text())).toEqual([
      'sandbox',
      '2 tools',
    ])

    const card = mountNode(nodeData(NODES.agent))
    expect(card.findAll('.builder-chip')).toHaveLength(0)
    expect(card.find('.builder-summary').exists()).toBe(true)
  })

  it('flags a tool that carries a key, and only when it carries one', () => {
    // Whether a tool needs a key is a yes/no an author scans a canvas for.
    // WHICH key is an inspector question, so the chip says "key" and never the
    // credential's id - the id is the one thing on the card that would be worth
    // nothing to read and something to leak.
    expect(mountNode(nodeData(NODES.tool)).findAll('.builder-chip.is-key')).toHaveLength(0)

    const keyed: DocumentNode = {
      ...NODES.tool,
      config: { ...NODES.tool.config, credential_id: 'cr_0123abcd' },
    } as DocumentNode
    const chips = mountNode(nodeData(keyed)).findAll('.builder-chip.is-key')
    expect(chips).toHaveLength(1)
    expect(chips[0].text()).toBe('key')
    expect(chips[0].text()).not.toContain('cr_')
  })

  it('shows a tool the catalogue LABEL once the server serves one, and the id until then', () => {
    // An author picked "Firecrawl scrape" from a list and should see that, not
    // `firecrawl_scrape`. The fallback is the id and never a guess: this build's
    // `/vocabulary` does not serve `tools` yet, so today every pill reads its id
    // and that is honest rather than a placeholder.
    expect(mountNode(nodeData(NODES.tool)).find('.builder-chip').text()).toBe('firecrawl_scrape')

    vocabulary.value = {
      ...VOCABULARY,
      tools: [
        {
          tool_id: 'firecrawl_scrape',
          label: 'Firecrawl scrape',
          category: 'web',
          description: 'Fetch one page as markdown.',
          credential_kind: 'firecrawl',
          attaches_to: ['agent'],
          params: [],
        },
      ],
    }
    expect(mountNode(nodeData(NODES.tool)).find('.builder-chip').text()).toBe('Firecrawl scrape')
  })
})

/* ─── ports ──────────────────────────────────────────────────────────────── */

describe('a drawn port cannot disagree with an accepted port', () => {
  it('gives an input node no target handle at all, not an inert one', () => {
    const wrapper = mountNode(nodeData(NODES.input))
    const targets = handles(wrapper).filter((handle) => handle.attributes('type') === 'target')
    // `accepts_incoming` is false only here, and an edge that arrives is
    // `edge-target-refuses-incoming`. A port drawn and then refused teaches an
    // author that the canvas lies.
    expect(targets).toHaveLength(0)
  })

  it('gives an output node no source handle at all', () => {
    const wrapper = mountNode(nodeData(NODES.output))
    const sources = handles(wrapper).filter((handle) => handle.attributes('type') === 'source')
    expect(sources).toHaveLength(0)
    expect(wrapper.findAll('handle-stub')).toHaveLength(1)
  })

  it('draws a gate as exactly approve then revise, both permanently labelled', () => {
    const wrapper = mountNode(nodeData(NODES.gate))
    const sources = handles(wrapper).filter((handle) => handle.attributes('type') === 'source')
    expect(sources.map((handle) => handle.attributes('id'))).toEqual(['approve', 'revise'])
    // Never hover-only. Which exit an edge leaves by is the fact the canvas
    // exists to show, and ChatDev puts the equivalent three modals deep.
    expect(wrapper.findAll('.builder-port-label').map((span) => span.text())).toEqual([
      'approve',
      'revise',
    ])
    // 30/70 rather than the general `((i + .5) / n) * 100`, so a labelled pair
    // reads as a fork instead of two adjacent ports (§5.3).
    expect(sources[0].attributes('style')).toContain('left: 30%')
    expect(sources[1].attributes('style')).toContain('left: 70%')
  })

  it('tracks a router branch label reactively, so a new branch grows a port', async () => {
    const data = nodeData(NODES.router)
    const wrapper = mountNode(data)
    expect(
      handles(wrapper)
        .filter((handle) => handle.attributes('type') === 'source')
        .map((handle) => handle.attributes('id')),
    ).toEqual(['approve', 'otherwise'])

    await wrapper.setProps({
      data: nodeData({
        ...NODES.router,
        config: {
          branches: [
            { label: nodeId('approve'), op: 'eq', key: nodeId('decision'), value: 'approve' },
            { label: nodeId('revise'), op: 'eq', key: nodeId('decision'), value: 'revise' },
            { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
          ],
        },
      } as DocumentNode),
    })

    expect(
      handles(wrapper)
        .filter((handle) => handle.attributes('type') === 'source')
        .map((handle) => handle.attributes('id')),
    ).toEqual(['approve', 'revise', 'otherwise'])
  })

  it('marks the otherwise port as the fallback it is', () => {
    const wrapper = mountNode(nodeData(NODES.router))
    const labels = wrapper.findAll('.builder-port-label')
    expect(labels[1].classes()).toContain('is-otherwise')
    expect(labels[0].classes()).toContain('is-branch')
  })

  it('agrees with nodeKinds.outPorts for all ten kinds', () => {
    for (const kind of Object.keys(NODES) as NodeKind[]) {
      const wrapper = mountNode(nodeData(NODES[kind]))
      const drawn = handles(wrapper)
        .filter((handle) => handle.attributes('type') === 'source')
        .map((handle) => handle.attributes('id'))
      // The single source of truth, which `tests/nodeKinds.spec.ts` in turn
      // reads out of `document.py`. Three files, one answer.
      expect(drawn).toEqual([...NODE_KINDS[kind].outPorts(NODES[kind])])
    }
  })
})

/* ─── the inline rename ──────────────────────────────────────────────────── */

describe('renaming a card asks for a commit rather than taking one', () => {
  it('emits the trimmed label on Enter', async () => {
    const wrapper = mountNode(nodeData(NODES.agent))
    const title = wrapper.get('.builder-title')
    await title.trigger('dblclick')
    title.element.textContent = '  Deep   scoper  '
    await title.trigger('keydown.enter')
    expect(wrapper.emitted('rename')).toEqual([[{ id: 'scoper', label: 'Deep scoper' }]])
  })

  it('emits nothing at all on Escape, and nothing for an emptied box', async () => {
    const wrapper = mountNode(nodeData(NODES.agent))
    const title = wrapper.get('.builder-title')

    await title.trigger('dblclick')
    title.element.textContent = 'discarded'
    await title.trigger('keydown.esc')
    expect(wrapper.emitted('rename')).toBeUndefined()

    // An empty label is a hard 422 and a nameless card is unreadable, so the
    // box reverts. There is nothing to undo yet, so undo cannot be the
    // confirmation here the way it is everywhere else.
    await title.trigger('dblclick')
    title.element.textContent = '   '
    await title.trigger('keydown.enter')
    expect(wrapper.emitted('rename')).toBeUndefined()
  })
})

/* ─── edges ──────────────────────────────────────────────────────────────── */

function edgeData(overrides: Partial<BuilderEdgeData> = {}): BuilderEdgeData {
  const problems = overrides.problems ?? []
  return {
    edge: {
      id: 'e1' as BuilderEdgeData['edge']['id'],
      source: nodeId('confirm'),
      source_port: 'approve',
      target: nodeId('scoper'),
      target_port: 'in',
    },
    problems,
    severity: problems.some((entry) => entry.severity === 'error')
      ? 'error'
      : problems.length > 0
        ? 'warning'
        : null,
    backEdge: false,
    portLabel: null,
    portRole: null,
    joinTarget: false,
    // Derived from the fixture's own edge rather than defaulted, so an override
    // that moves `target_port` cannot leave the class saying something else.
    edgeClass: edgeClassOf(overrides.edge ?? { source_port: 'approve', target_port: 'in' }),
    sourceAccent: NODE_KINDS.gate.accent,
    targetAccent: NODE_KINDS.agent.accent,
    active: false,
    ...overrides,
  }
}

function mountEdge(data: BuilderEdgeData, selected = false) {
  return mount(BuilderEdge, {
    props: {
      id: 'e1',
      source: 'confirm',
      target: 'scoper',
      sourceX: 0,
      sourceY: 0,
      targetX: 100,
      targetY: 100,
      sourcePosition: 'bottom',
      targetPosition: 'top',
      data,
      selected,
    } as never,
    global: { stubs: { BaseEdge: true, EdgeLabelRenderer: { template: '<div><slot /></div>' } } },
  })
}

describe('an edge says which port it left by', () => {
  it('renders no chip for the six kinds with one unnamed out-port', () => {
    const wrapper = mountEdge(edgeData())
    // Printing `out` on every line in the graph is noise that trains the eye
    // past the two labels that carry a decision.
    expect(wrapper.find('.builder-edge-chip').exists()).toBe(false)
  })

  it('renders the port name, colour-coded, when the source forks', () => {
    const wrapper = mountEdge(edgeData({ portLabel: 'approve', portRole: 'approve' }))
    const chip = wrapper.get('.builder-edge-chip')
    expect(chip.text()).toBe('approve')
    expect(chip.classes()).toContain('is-approve')
  })

  it('prefixes a back edge so the cycle count is read rather than inferred', () => {
    const wrapper = mountEdge(edgeData({ portLabel: 'revise', portRole: 'revise', backEdge: true }))
    expect(wrapper.get('.builder-edge-chip').text()).toBe('↺ revise')
    expect(wrapper.get('g').classes()).toContain('is-back-edge')
  })

  it('makes a router branch chip clickable and a gate chip inert', async () => {
    const gate = mountEdge(edgeData({ portLabel: 'approve', portRole: 'approve' }))
    // A control that does nothing is a lie the second time somebody clicks it.
    expect(gate.get('.builder-edge-chip').element.tagName).toBe('SPAN')

    const branch = mountEdge(edgeData({ portLabel: 'match', portRole: 'branch' }))
    const chip = branch.get('.builder-edge-chip')
    expect(chip.element.tagName).toBe('BUTTON')
    await chip.trigger('click')
    expect(branch.emitted('select-branch')).toEqual([[{ nodeId: 'confirm', port: 'match' }]])
  })

  it('carries the server problem as a stroke class, computing none itself', () => {
    const errored = mountEdge(edgeData({ problems: [problem({ severity: 'error' })] }))
    expect(errored.get('g').classes()).toContain('has-error')
    const warned = mountEdge(edgeData({ problems: [problem({ severity: 'warning' })] }))
    expect(warned.get('g').classes()).toContain('has-warning')
  })

  it('draws the AND bracket only where the branches actually meet', () => {
    expect(mountEdge(edgeData()).find('.builder-edge-bracket').exists()).toBe(false)
    expect(mountEdge(edgeData({ joinTarget: true })).find('.builder-edge-bracket').exists()).toBe(true)
  })

  it('keeps a 16px grab lane under the 1.2px line', () => {
    // §4.2 needs each end draggable for a re-route, and a 1.2px pointer target
    // is one nobody hits first time - which teaches that edges cannot be
    // re-routed at all.
    expect(mountEdge(edgeData()).find('.builder-edge-hit').exists()).toBe(true)
  })
})

/* ─── the palette ────────────────────────────────────────────────────────── */

function mountPalette(props: Record<string, unknown> = {}) {
  return mount(NodePalette, { props })
}

describe('the palette renders the server vocabulary and nothing else', () => {
  it('has no fallback list when the vocabulary is unavailable', async () => {
    // Cut list item 17. A palette that keeps drawing kinds after `/vocabulary`
    // failed is a palette drawing graphs the compiler will refuse, and the
    // author finds out at publish.
    const wrapper = mountPalette()
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.builder-tile')).toHaveLength(0)
  })

  it('renders the seven kinds in the SERVER order, unsorted', async () => {
    seedVocabulary()
    const wrapper = mountPalette()
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.builder-tile-name').map((span) => span.text().split(' ')[0])).toEqual([
      'Input',
      'Agent',
      'Crew',
      'Gate',
      'Router',
      'Transform',
      'Output',
    ])
  })

  it('prints the number key each tile answers to', async () => {
    seedVocabulary()
    const wrapper = mountPalette()
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.builder-tile-key').map((kbd) => kbd.text())).toEqual([
      '1',
      '2',
      '3',
      '4',
      '5',
      '6',
      '7',
    ])
  })

  it('counts billable kinds from the SERVER budget, never by counting nodes', async () => {
    seedVocabulary()
    const wrapper = mountPalette({
      budget: { billable_nodes: 7, escalation_nodes: 5 },
    })
    await wrapper.vm.$nextTick()
    const counts = wrapper.findAll('.builder-tile-count').map((span) => span.text())
    expect(counts).toContain('billable 7/8')
    expect(counts).toContain('escalation 5/5')
    // Amber lands AT the bound and not past it: past it the server has already
    // reported a problem, and this is the warning that precedes one.
    const escalation = wrapper.findAll('.builder-tile-count.is-escalation')
    expect(escalation[0].classes()).toContain('is-at-bound')
  })

  it('disables at the billable ceiling and names the bound', async () => {
    seedVocabulary()
    const wrapper = mountPalette({ budget: { billable_nodes: 8, escalation_nodes: 2 } })
    await wrapper.vm.$nextTick()
    const tiles = wrapper.findAll('.builder-tile')
    const agent = tiles[1]
    expect(agent.attributes('disabled')).toBeDefined()
    expect(agent.attributes('title')).toContain('max_billable_nodes is 8')
    // Only the two billable kinds. `input` cannot cost anything and disabling
    // it would be a control refusing an action for a reason untrue of it.
    expect(tiles[0].attributes('disabled')).toBeUndefined()
    await agent.trigger('click')
    expect(wrapper.emitted('place')).toBeUndefined()
  })

  it('never disables on the escalation count, because a new node is born cheap', async () => {
    seedVocabulary()
    const wrapper = mountPalette({ budget: { billable_nodes: 1, escalation_nodes: 5 } })
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.builder-tile')[1].attributes('disabled')).toBeUndefined()
  })

  it('sets a private MIME on the drag so a dropped URL is not mistaken for a kind', async () => {
    seedVocabulary()
    const wrapper = mountPalette()
    await wrapper.vm.$nextTick()
    const written: Array<[string, string]> = []
    await wrapper.findAll('.builder-tile')[1].trigger('dragstart', {
      dataTransfer: { setData: (type: string, value: string) => written.push([type, value]) },
    })
    expect(written).toEqual([
      [BUILDER_KIND_MIME, 'agent'],
      ['text/plain', 'agent'],
    ])
  })

  it('derives the billable kinds from the type layer rather than a list', () => {
    // `Extract<BuilderNode, { config: { tier: Tier } }>` is the client shadow of
    // Python's `_BillableConfig`, so a third billable kind is a compile error
    // here rather than a silent hole in the counter.
    expect(isBillableKind('agent')).toBe(true)
    expect(isBillableKind('crew')).toBe(true)
    expect(isBillableKind('gate')).toBe(false)
  })

  it('lists saved graphs with their status and marks the open one', async () => {
    seedVocabulary()
    const wrapper = mountPalette({
      library: [
        { id: 'ug_00000001', name: 'Pricing check', version: 4, status: 'published', live_version: 4, created_at: '', updated_at: '' },
        { id: 'ug_00000002', name: 'Scratch', version: 1, status: 'draft', live_version: null, created_at: '', updated_at: '' },
      ],
      openDocumentId: 'ug_00000002',
    })
    await wrapper.vm.$nextTick()
    const rows = wrapper.findAll('.builder-library-row')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('Pricing check')
    expect(rows[1].attributes('aria-current')).toBe('true')
    await rows[0].trigger('click')
    expect(wrapper.emitted('open')).toEqual([['ug_00000001']])
  })
})

/* ─── the port menu ──────────────────────────────────────────────────────── */

function mountPortMenu(props: Record<string, unknown> = {}) {
  return mount(PortMenu, {
    props: {
      open: true,
      origin: { direction: 'source', node: nodeId('confirm'), port: 'approve' },
      at: { x: 120, y: 90 },
      position: { x: 240, y: 160 },
      takenIds: new Set(['confirm']),
      ...props,
    },
  })
}

describe('the port menu creates a node and its edge as one act', () => {
  it('hands over both halves in a single payload, so one undo removes both', async () => {
    seedVocabulary()
    const wrapper = mountPortMenu()
    await wrapper.vm.$nextTick()

    const rows = wrapper.findAll('.builder-portmenu-row')
    const marketAnalyst = rows.find((row) => row.text().includes('Market analyst'))
    expect(marketAnalyst).toBeDefined()
    await marketAnalyst!.trigger('click')

    const created = wrapper.emitted('create') as [PortMenuCreation][]
    expect(created).toHaveLength(1)
    const payload = created[0][0]
    // Two commits taken in quick succession are two undo steps forever, and the
    // second Ctrl+Z would leave a node dangling where none had been asked for.
    expect(payload.source).toBe('confirm')
    expect(payload.sourcePort).toBe('approve')
    expect(payload.target).toBe(payload.node.id)
    expect(payload.label).toBe('Add market analyst')
    expect(payload.node.kind).toBe('agent')
    expect(payload.node.label).toBe('Market analyst')
    expect(payload.node.id).toBe('market_analyst')
    expect(
      payload.node.kind === 'agent' &&
        !isAuthoredAgent(payload.node.config) &&
        payload.node.config.agent_id,
    ).toBe('market_analyst')
    // Grid-snapped by the caller, and rounded again by `newNode` (R12): an
    // unrounded `position.x` is a hard 422 on a save long after the gesture.
    expect(payload.node.position).toEqual({ x: 240, y: 160 })
  })

  it('emits ZERO commits on Escape', async () => {
    seedVocabulary()
    const wrapper = mountPortMenu()
    await wrapper.vm.$nextTick()
    await wrapper.get('.builder-portmenu').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('create')).toBeUndefined()
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('walks the list with the arrows and creates with Enter, keyboard only', async () => {
    seedVocabulary()
    const wrapper = mountPortMenu()
    await wrapper.vm.$nextTick()
    const menu = wrapper.get('.builder-portmenu')
    await menu.trigger('keydown', { key: 'ArrowDown' })
    await menu.trigger('keydown', { key: 'Enter' })
    const created = wrapper.emitted('create') as [PortMenuCreation][]
    // The second row: the seven kinds come first, in canonical order, and
    // `input` is absent because the new node would be the TARGET.
    expect(created[0][0].node.kind).toBe('crew')
  })

  it('offers no input node when the new node would be the target', async () => {
    seedVocabulary()
    const wrapper = mountPortMenu()
    await wrapper.vm.$nextTick()
    const titles = wrapper.findAll('.builder-portmenu-title').map((span) => span.text())
    // `accepts_incoming` is false only for `input`. A row that cannot produce a
    // legal edge is not offered, so Enter on any visible row always works.
    expect(titles).not.toContain('Input')
    expect(titles.slice(0, 6)).toEqual(['Agent', 'Crew', 'Gate', 'Router', 'Transform', 'Output'])
  })

  it('offers no output node when the new node would be the source', async () => {
    seedVocabulary()
    const wrapper = mountPortMenu({
      origin: { direction: 'target', node: nodeId('report'), port: 'out' },
    })
    await wrapper.vm.$nextTick()
    const titles = wrapper.findAll('.builder-portmenu-title').map((span) => span.text())
    expect(titles).not.toContain('Output')
    expect(titles).toContain('Input')
  })

  it('points the edge the other way when the fixed end is the target', async () => {
    seedVocabulary()
    const wrapper = mountPortMenu({
      origin: { direction: 'target', node: nodeId('report'), port: 'out' },
    })
    await wrapper.vm.$nextTick()
    const gate = wrapper.findAll('.builder-portmenu-row').find((row) => row.text().includes('Gate'))
    await gate!.trigger('click')
    const payload = (wrapper.emitted('create') as [PortMenuCreation][])[0][0]
    expect(payload.target).toBe('report')
    expect(payload.source).toBe(payload.node.id)
    // The FIRST declared out-port, read from `nodeKinds`, so the port the edge
    // uses is the port drawn on the new card.
    expect(payload.sourcePort).toBe('approve')
  })

  it('filters on what was typed', async () => {
    seedVocabulary()
    const wrapper = mountPortMenu()
    await wrapper.vm.$nextTick()
    await wrapper.get('.builder-portmenu-input').setValue('rout')
    expect(wrapper.findAll('.builder-portmenu-title').map((span) => span.text())).toEqual(['Router'])
  })

  it('says so rather than showing an empty box when nothing matches', async () => {
    seedVocabulary()
    const wrapper = mountPortMenu()
    await wrapper.vm.$nextTick()
    await wrapper.get('.builder-portmenu-input').setValue('zzzz')
    expect(wrapper.get('.builder-portmenu-none').text()).toContain('zzzz')
  })

  it('renders nothing at all while it is closed', () => {
    seedVocabulary()
    const wrapper = mountPortMenu({ open: false })
    expect(wrapper.find('.builder-portmenu').exists()).toBe(false)
  })

  it('sentence-cases an id without asserting a proper noun', () => {
    expect(titleiseId('market_analyst')).toBe('Market analyst')
    expect(titleiseId('to_json')).toBe('To json')
  })
})

/* A guard for the one thing a spec cannot see: that nothing here reached for a
   timer or a network call. `restoreMocks`/`clearMocks` are on in the runner, so
   a stray `setInterval` would leak into the next file rather than fail here. */
afterEach(() => {
  vi.useRealTimers()
})
