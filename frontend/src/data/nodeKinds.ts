import type { Component } from 'vue'
import {
  BookOpen,
  BookUser,
  Flag,
  GitFork,
  Hand,
  PlugZap,
  TextCursorInput,
  UsersRound,
  Wand2,
  Wrench,
} from 'lucide-vue-next'
import { nodeId } from '../types/builder'
import type {
  AgentConfig,
  BuilderNode,
  BuilderVocabulary,
  CrewConfig,
  GateConfig,
  InputConfig,
  McpConfig,
  NodeId,
  NodeKind,
  OutputConfig,
  RouterConfig,
  SkillConfig,
  ToolConfig,
  TransformConfig,
} from '../types/builder'

/**
 * One record per node kind, and the single source of truth for kind.
 *
 * The palette tile, the card, the port footer, the number hotkeys, the port
 * menu and the minimap dot all read this file, and that is the whole point: a
 * DRAWN port can never disagree with an ACCEPTED port. Ports are the place this
 * matters most, because the disagreement is silent in both directions - a port
 * drawn that the server does not know produces `edge-unknown-port` on an edge
 * the author was invited to draw, and a port NOT drawn is a branch that simply
 * cannot be reached from the canvas at all.
 *
 * `outPorts` is therefore a line-for-line mirror of `_OUT_PORTS_BY_KIND` and
 * `BuilderNode.out_ports` in `src/brief_crew/builder/document.py:388-458`, and
 * `tests/nodeKinds.spec.ts` reads that dict out of the Python at run time and
 * compares, rather than trusting this comment. Transcribing it into the test
 * would only prove that two copies of one mistake agree.
 *
 * WHAT IS NOT HERE. No count, no bound, no problem. `bounds.py` owns every
 * count and the client renders what it returns (R6); the four presentational
 * advisories §6.1 allows - the loop rim, the dashed back edge, the palette's
 * disable-at-ceiling, the budget pips - all read `vocabulary.bounds` at the
 * point of use and none of them gates an action.
 */

/** Which config shape belongs to which kind, so a record can be typed per kind. */
interface ConfigForKind {
  input: InputConfig
  agent: AgentConfig
  crew: CrewConfig
  gate: GateConfig
  router: RouterConfig
  transform: TransformConfig
  output: OutputConfig
  tool: ToolConfig
  mcp: McpConfig
  skill: SkillConfig
}

export interface NodeKindMeta<K extends NodeKind = NodeKind> {
  readonly kind: K
  /**
   * Which of `document.py`'s two families this kind is in (03 D1).
   *
   * The ONE fact the silhouette reads: a flow node is a card, an attachment is
   * a pill. That is D5's third identity channel and it is the one that survives
   * the zoom the other two do not - at 50% the 11px eyebrow is 5.5px and the
   * accent is a smear, while a 160px pill beside a 240px card is still two
   * different objects. A pill can never be mistaken for a step.
   */
  readonly family: 'flow' | 'attachment'
  /** Lucide, rendered `:size="17" :stroke-width="1.8"` the way the run card does. */
  readonly icon: Component
  /** The card class the design tenancy hangs `--node-gradient` off (§5.1). */
  readonly className: `is-kind-${K}`
  /** One sentence on the palette tile. What this kind DOES, not what it is called. */
  readonly blurb: string
  /**
   * Position in the canonical kind order: `0`-`6` for the flow kinds, `7`-`9`
   * for the three attachments. It is NOT the hotkey any more - `hotkey` is,
   * below - because decision 18 gave the attachments letters and a derived
   * `paletteOrder + 1` would have printed `8`, `9` and `10` on those tiles.
   *
   * The palette itself renders `vocabulary.node_kinds` in the server's order and
   * does not sort by this; `tests/nodeKinds.spec.ts` reads the Python's own
   * `NodeKind` union and asserts this order against it. If the two ever diverge,
   * a tile and the key printed on it would be about different kinds.
   */
  readonly paletteOrder: number
  /**
   * The key that inserts this kind, as the palette prints it and as
   * `useBuilderHotkeys` binds it.
   *
   * `paletteOrder + 1` for the seven FLOW kinds, which is where `1`-`7` comes
   * from - and for the three attachments it is a LETTER: `T`, `M`, `K` (owner's
   * decision 18, 2026-09-04). Not `8`/`9`/`0`, because digits `1`-`7` already
   * select a kind on this same surface and a second digit row is a collision an
   * author discovers by pressing one; `0` also reads as "none".
   *
   * Written here rather than derived, because it is now two rules and a derived
   * value would have to encode the family split anyway - and the palette, the
   * shortcut sheet and the binding table must all print the same character.
   */
  readonly hotkey: string
  /** The label a fresh node is born with, before its `1`-based suffix. */
  readonly defaultLabel: string
  /**
   * The config a fresh node of this kind is born with.
   *
   * A function rather than a value, and taking two arguments, because two of the
   * seven defaults are not knowable from this file: `agent_id`, `crew_id` and
   * `body_key` are REQUIRED fields whose legal values are served by
   * `/api/builder/vocabulary` (a hardcoded fallback list is cut list item 17),
   * and an `input` node's `field` defaults to the node's own id so that two
   * input nodes can never collide into `input-field-ambiguous` on arrival.
   */
  readonly defaultConfig: (vocabulary: BuilderVocabulary, id: NodeId) => ConfigForKind[K]
  /**
   * The ports an edge may leave by, in the order the canvas draws them.
   *
   * Mirrors `document.py:BuilderNode.out_ports`. `router` is computed from the
   * node because its ports ARE its declared branch labels - which is why this is
   * a function of the node rather than a constant per kind, and why adding a
   * branch grows a port on the same tick.
   */
  readonly outPorts: (node: BuilderNode) => readonly string[]
  /**
   * `document.py:accepts_incoming` - FOUR kinds refuse an inbound edge, for two
   * different reasons. `input` refuses because it is where the run starts. The
   * three ATTACHMENT kinds refuse because nothing flows INTO a possession: an
   * author who could draw an edge into a tool would be describing a step, and a
   * tool is not a step.
   */
  readonly acceptsIncoming: boolean
  /**
   * The one colour that identifies this kind away from the card - the minimap
   * dot, a palette tile's well.
   *
   * Each is a stop of that kind's `--node-gradient` in §5.1, and where two kinds
   * share a stop the OTHER one is taken: `input` and `output` both start
   * `#aaffcd`, `router` and `transform` are both grey at one end. A minimap
   * whose router and transform dots are the same colour tells the author
   * nothing, which is the entire job of a minimap dot.
   */
  readonly accent: string
}

/** `document.py:_OUT_PORTS_BY_KIND` - every single-output kind, verbatim. */
const SINGLE_OUT: readonly string[] = ['out']
/** The same kind, once `on_error` is `'route'` - see `billableOut`. */
const SINGLE_OUT_ROUTED: readonly string[] = ['out', 'error']
/** `document.py:_OUT_PORTS_BY_KIND["gate"]`, in that canvas order. */
const GATE_OUT: readonly string[] = ['approve', 'revise']
/** `document.py:_OUT_PORTS_BY_KIND["output"]` - an output node ends the run. */
const NO_OUT: readonly string[] = []
/**
 * `document.py:_OUT_PORTS_BY_KIND["tool"|"mcp"|"skill"]` - all three, verbatim.
 *
 * ONE port, and it is a SOURCE. The tool reaches toward the agent, never the
 * reverse, and giving the agent an `attach` INPUT instead would have cost more
 * than it looks: with the arrow this way round the edge's class is a pure
 * function of `target_port` and of nothing else, so this file's stroke rules and
 * `bounds.py`'s edge rules agree about one string rather than each deciding
 * independently what the source happened to be.
 */
const ATTACH_OUT: readonly string[] = ['attach']

/**
 * The source ports of a billable node: `out`, and `error` when it routes.
 *
 * D1's one conditional row in the port table, and the only place in this file
 * where a port depends on a CONFIG field rather than on the kind. `on_error` is
 * optional and absent by default (see `NodeErrorPolicy`), so a node that has
 * never been told otherwise has exactly the one port it has always had - which
 * is what keeps every existing document's edges legal.
 */
function billableOut(node: BuilderNode): readonly string[] {
  if (node.kind !== 'agent' && node.kind !== 'crew') return SINGLE_OUT
  return node.config.on_error === 'route' ? SINGLE_OUT_ROUTED : SINGLE_OUT
}

export const NODE_KINDS: { readonly [K in NodeKind]: NodeKindMeta<K> } = {
  input: {
    kind: 'input',
    family: 'flow',
    icon: TextCursorInput,
    className: 'is-kind-input',
    blurb: 'Seeds the run from one named request input.',
    paletteOrder: 0,
    hotkey: '1',
    defaultLabel: 'Input',
    defaultConfig: (_vocabulary, id) => ({
      /*
       * The node's own id, which is unique by construction.
       *
       * Any fixed word would make the SECOND input node an
       * `input-field-ambiguous` error the moment the author drops it - a
       * problem about a collision they did not cause, on a field they have not
       * looked at yet. `InputForm`'s "make this the run input" button is what
       * points `document.input_field` at whichever one they meant.
       */
      field: id,
      // Null, not the label. `document.py` keeps the two apart deliberately: a
      // node called "Idea" may reasonably ask for "Describe the product in a
      // sentence or two", and inventing the prompt from the canvas label would
      // put words in the author's mouth that the operator then reads.
      label: null,
      // `MAX_RUN_INPUT_CHARS`. The schema's own default is the same ceiling, so
      // a fresh input asks for as much as the run endpoint will accept.
      max_chars: 2000,
      required: true,
    }),
    outPorts: () => SINGLE_OUT,
    acceptsIncoming: false,
    accent: '#aaffcd',
  },
  agent: {
    kind: 'agent',
    family: 'flow',
    /*
     * D5 names two glyphs for this kind - `user-round` for an AUTHORED agent
     * and `book-user` for a LIBRARY one - and only one of those two shapes
     * exists in this build. `AgentConfig` carries `agent_id`, which keys the
     * YAML registry, so every agent a document can express today IS a library
     * agent; `book-user` is therefore the truthful icon for all of them, and
     * `user-round` arrives with D3's `AuthoredAgentConfig` on the Python side.
     * Picking the icon per NODE rather than per kind is that change's work.
     */
    icon: BookUser,
    className: 'is-kind-agent',
    blurb: 'One allowlisted YAML agent, on one tier, with bound tools.',
    paletteOrder: 1,
    hotkey: '2',
    defaultLabel: 'Agent',
    defaultConfig: (vocabulary, _id) => ({
      /*
       * `tier` has NO default in `_BillableConfig` - it is required, and that is
       * the point: an author names the tier. The client has to put SOMETHING in
       * the box, and the cheap tier is the only defensible answer, because the
       * escalation tier is the scarce one (`MAX_ESCALATION_NODES` is 5 of 8) and
       * spending more should be a deliberate act rather than what happens when
       * you drag a tile.
       */
      tier: 'cheap',
      // `VALIDATOR_BRANCH_MAX_ITER` - the schema default, and what this repo's
      // own research branches actually run at.
      max_iter: 2,
      // `BUILDER_MAX_GUARDRAIL_RETRIES`, which is both the default and the
      // ceiling. CrewAI counts retries PER GUARDRAIL, so the unset library
      // default of 3 permits eight full regenerations of a two-guardrail task.
      guardrail_max_retries: 2,
      prompt_inputs: {},
      // The first id the server offers. `agent_ids` is `sorted(...)` server-side
      // so this is stable, and the select in `BillableForm` opens on the same
      // entry - a default that is not the first option is a default nobody can
      // find their way back to.
      agent_id: nodeId(vocabulary.agent_ids[0]),
      tools: [],
      // No key by default: the platform key is used until the author picks one
      // of their own vault rows (plan 01 D7; the picker is 04's).
      credential_id: null,
    }),
    outPorts: billableOut,
    acceptsIncoming: true,
    accent: '#99eaf9',
  },
  crew: {
    kind: 'crew',
    family: 'flow',
    icon: UsersRound,
    className: 'is-kind-crew',
    blurb: 'One registered crew, run whole, with its own tools.',
    paletteOrder: 2,
    hotkey: '3',
    defaultLabel: 'Crew',
    defaultConfig: (vocabulary, _id) => ({
      tier: 'cheap',
      // Accepted by the schema and IGNORED at runtime - `run_crew` runs the crew
      // whole. Carried at the schema's defaults so a round trip does not change
      // the document, never presented as a control that does something.
      max_iter: 2,
      guardrail_max_retries: 2,
      prompt_inputs: {},
      /*
       * The first id the server offers, exactly as `agent` above.
       *
       * There is deliberately no local skip-list in front of this, and there
       * WAS one until 2026-09-02. Two of the six registered crews cannot be
       * built from a document - `SynthesisCrew(market, sentiment, feasibility)`
       * and `ReportCrew(verdict, tool_urls)` take typed findings the validator
       * flow hands over in Python - so this file carried its own hardcoded map
       * of the pair and stepped over it. That was cut list item 17 wearing a
       * different hat: a client-side copy of a server allowlist, which is
       * unreachable while it agrees and wrong the moment it does not.
       *
       * `_vocabulary()` serves `sorted(BUILDABLE_BUILDER_CREW_IDS)` -
       * `BUILDER_CREW_LIBRARY` minus `UNBUILDABLE_BUILDER_CREWS`
       * (`builder/runtime.py`) - so neither id ever reaches a picker and the
       * first one is safe by construction. The backstop for a document
       * hand-edited past the widget is the compiler's `library-unbuildable-crew`
       * error, which fires at validate, before anything bills.
       */
      crew_id: nodeId(vocabulary.crew_ids[0]),
    }),
    outPorts: billableOut,
    acceptsIncoming: true,
    accent: '#a0c4ff',
  },
  gate: {
    kind: 'gate',
    family: 'flow',
    icon: Hand,
    className: 'is-kind-gate',
    blurb: 'Pauses for a person, who approves it or sends it back.',
    paletteOrder: 3,
    hotkey: '4',
    defaultLabel: 'Gate',
    defaultConfig: () => ({
      /*
       * `message` is required with `min_length=1` and no default, and it is the
       * one string in the whole document an OPERATOR reads rather than an
       * author. An empty box would be a 422 on the first save; a placeholder
       * that survives to production is worse, so the default is a real sentence
       * that is true of every gate whatever the author does next.
       */
      message: 'Review this step before the run continues.',
      editable_fields: [],
      max_turns: 1,
      // `VALIDATOR_GATE_TIMEOUT_SECONDS`, which is both the schema default and
      // its ceiling. Round-trips at whatever is stored and has no control (R8):
      // the field is authored, range-validated and read by nothing in `src/`.
      expiry_seconds: 1800,
    }),
    outPorts: () => GATE_OUT,
    acceptsIncoming: true,
    accent: '#ffe082',
  },
  router: {
    kind: 'router',
    family: 'flow',
    icon: GitFork,
    className: 'is-kind-router',
    blurb: 'A deterministic fork over one state key. No model, no expression.',
    paletteOrder: 4,
    hotkey: '5',
    defaultLabel: 'Router',
    defaultConfig: () => ({
      /*
       * Two branches, one comparison and one `otherwise`, so a fresh router
       * satisfies `router-branch-count` (2..4) and `router-otherwise` (exactly
       * one) the instant it lands. A router born empty is born with two errors
       * against it, which teaches an author that dragging a tile is a mistake.
       *
       * `key` is a word rather than a resolvable-looking `out__something`, and
       * that asymmetry is deliberate: nothing here knows what is upstream, so
       * the honest default is one that obviously has to be pointed somewhere.
       * `StateRefInput` warns when a key resolves to nothing.
       */
      branches: [
        { label: nodeId('match'), op: 'eq', key: nodeId('decision'), value: null },
        // The otherwise branch takes no key and no value - it is what happens
        // when every declared comparison missed. `RouterBranch._validate_shape`
        // refuses either being present, so this is a 422 if it is ever filled.
        { label: nodeId('otherwise'), op: 'otherwise', key: null, value: null },
      ],
    }),
    outPorts: (node) =>
      // The guard is the type system's, not a runtime doubt: `NODE_KINDS[kind]`
      // can only hand this entry a router. It is written this way because the
      // record is keyed by kind while `outPorts` takes the whole node, which is
      // exactly what lets every caller write `NODE_KINDS[n.kind].outPorts(n)`.
      node.kind === 'router' ? node.config.branches.map((branch) => branch.label) : NO_OUT,
    acceptsIncoming: true,
    accent: '#7dc6ff',
  },
  transform: {
    kind: 'transform',
    family: 'flow',
    icon: Wand2,
    className: 'is-kind-transform',
    blurb: 'One of six fixed operations over the data between two nodes.',
    paletteOrder: 5,
    hotkey: '6',
    defaultLabel: 'Transform',
    defaultConfig: () => ({
      /*
       * `op` is required with no default. `pick` is chosen rather than
       * `transform_ops[0]`, which would be `default` - the server sorts that
       * list, and "default" as the default op reads as an accident. `pick` is
       * the operation with the smallest true argument shape (`source`, `key`),
       * so the args editor opens on two boxes rather than a free table.
       *
       * `tests/builderDefaults.spec.ts` asserts `pick` is in
       * `BUILDER_TRANSFORM_OPS`, read out of `config.py`.
       */
      op: 'pick',
      args: {},
    }),
    outPorts: () => SINGLE_OUT,
    acceptsIncoming: true,
    accent: '#b3b3b3',
  },
  output: {
    kind: 'output',
    family: 'flow',
    icon: Flag,
    className: 'is-kind-output',
    blurb: 'What the run hands back, under the one key that escapes the clip.',
    paletteOrder: 6,
    hotkey: '7',
    defaultLabel: 'Output',
    defaultConfig: (vocabulary) => ({
      /*
       * `RUN_RESULT_BODY_KEYS[0]`, served rather than written here. Those keys
       * are the ones that get `MAX_RUN_RESULT_BODY_CHARS` instead of the
       * streaming frame's clip, so a body written under any other key comes back
       * truncated mid-sentence - which is exactly how the first paid run's
       * report was lost.
       */
      body_key: vocabulary.result_body_keys[0],
      source: null,
    }),
    // No source handle at all, not an inert one (§5.3). `_OUT_PORTS_BY_KIND`
    // gives `output` an empty tuple, so every port an edge could leave by is
    // one `bounds.py` would refuse.
    outPorts: () => NO_OUT,
    acceptsIncoming: true,
    accent: '#7bdff2',
  },

  /* --- the three attachments ---------------------------------------------
   * Not steps. An agent or a crew HAS one, and it reaches them along an
   * `attach` edge - so all three share one port, refuse every inbound edge,
   * and are drawn as pills rather than as cards.
   *
   * Their three accents share a hue and differ only in lightness, which is
   * deliberate and is the opposite of the rule the seven flow kinds follow:
   * there, every accent must be distinguishable, because a minimap dot whose
   * router and transform are one colour tells an author nothing. Here the
   * first question is "is that an attachment?" and the second is "which one",
   * so reading as a family beats reading as three strangers. `mcp` also
   * carries its own plug glyph, which answers the second question without
   * relying on 8% of lightness.
   *
   * The DEFAULTS below are the one place these differ from the seven above:
   * `tool_id`, `server_id` and `skill_id` are required ids into catalogues
   * that 06, 07 and 08 own and that `/vocabulary` does not serve yet. A
   * placeholder is NOT a hardcoded fallback list (cut-list 17) - it is one
   * obviously-unset value that the author replaces in the inspector, and the
   * server answers `library-unknown-id` for it until they do, which is the
   * honest state of a node that has been placed and not configured.
   */
  tool: {
    kind: 'tool',
    family: 'attachment',
    icon: Wrench,
    className: 'is-kind-tool',
    blurb: 'One catalogue tool, hung off an agent or a crew.',
    paletteOrder: 7,
    hotkey: 'T',
    defaultLabel: 'Tool',
    defaultConfig: () => ({
      // A placeholder id, legal against `BUILDER_ID_PATTERN` so the node is
      // parseable the moment it lands, and obviously unset so the inspector's
      // first control is the one that matters.
      tool_id: nodeId('tool'),
      params: {},
      // The platform key until the author picks one of their own (plan 01 D7).
      credential_id: null,
    }),
    outPorts: () => ATTACH_OUT,
    acceptsIncoming: false,
    accent: '#c3a6ff',
  },
  mcp: {
    kind: 'mcp',
    family: 'attachment',
    icon: PlugZap,
    className: 'is-kind-mcp',
    blurb: 'One MCP server, and which of its tools this node exposes.',
    paletteOrder: 8,
    hotkey: 'M',
    defaultLabel: 'MCP',
    defaultConfig: () => ({
      server_id: nodeId('server'),
      /*
       * Empty, and that is a PROBLEM rather than an invalid document.
       * `McpConfig` deliberately does not require this to be non-empty at parse
       * time: an author who has added a server and not yet chosen its tools has
       * made an incomplete graph, and `document.py` raises where `bounds.py`
       * reports. Seeding a tool name here would invent a selection they never
       * made, from a server nobody has contacted.
       */
      tool_names: [],
      credential_id: null,
      // `document.py::McpConfig` carries this so an EXPORTED graph parses;
      // a fresh node has no hint because it has a real `server_id`.
      server_hint: null,
    }),
    outPorts: () => ATTACH_OUT,
    acceptsIncoming: false,
    accent: '#d5b8ff',
  },
  skill: {
    kind: 'skill',
    family: 'attachment',
    icon: BookOpen,
    className: 'is-kind-skill',
    blurb: 'Knowledge an agent carries, loaded only when a task matches it.',
    paletteOrder: 9,
    hotkey: 'K',
    defaultLabel: 'Skill',
    defaultConfig: () => ({ skill_id: nodeId('skill'),
      // Survives an export where `skill_id` cannot, and is what an importing
      // author's own library resolves against.
      skill_name: null,
    }),
    outPorts: () => ATTACH_OUT,
    acceptsIncoming: false,
    accent: '#e0ccff',
  },
}

/**
 * The TEN kinds in canonical order - flow first, attachments last.
 *
 * Derived from `paletteOrder` rather than written twice, and the order is
 * `document.py:NodeKind`'s own: the seven flow kinds in the order the digits
 * `1`-`7` follow, then `tool`, `mcp`, `skill` on `T`, `M`, `K`.
 *
 * The palette renders `vocabulary.node_kinds` (the SERVER's order) rather than
 * this, and `tests/nodeKinds.spec.ts` reads the Python union at run time and
 * asserts the two agree. What that test can no longer assert is that the served
 * vocabulary lists all ten: this build's `_vocabulary()` still serves the v1
 * seven, so the palette draws seven tiles until C2 v2 lands (criterion 5, the
 * Python half). It asserts the weaker true thing instead - that everything
 * served is known here, in this relative order - which holds on both sides of
 * that change.
 */
export const NODE_KIND_ORDER: readonly NodeKind[] = (
  Object.values(NODE_KINDS) as NodeKindMeta[]
)
  .slice()
  .sort((left, right) => left.paletteOrder - right.paletteOrder)
  .map((meta) => meta.kind)

/**
 * The ports an edge may leave this node by, in canvas order.
 *
 * The one call every other package should use. Going through the record by hand
 * is the same thing; this exists so that `isValidConnection`, the card's port
 * footer and `PortMenu` are provably reading one function.
 */
export function outPortsOf(node: BuilderNode): readonly string[] {
  return NODE_KINDS[node.kind].outPorts(node)
}
