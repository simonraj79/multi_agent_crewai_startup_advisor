import type { Component } from 'vue'
import { Bot, Cog, FileText, Inbox, ShieldCheck, Split, Users } from 'lucide-vue-next'
import { nodeId } from '../types/builder'
import type {
  AgentConfig,
  BuilderNode,
  BuilderVocabulary,
  CrewConfig,
  GateConfig,
  InputConfig,
  NodeId,
  NodeKind,
  OutputConfig,
  RouterConfig,
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
}

export interface NodeKindMeta<K extends NodeKind = NodeKind> {
  readonly kind: K
  /** Lucide, rendered `:size="17" :stroke-width="1.8"` the way the run card does. */
  readonly icon: Component
  /** The card class the design tenancy hangs `--node-gradient` off (§5.1). */
  readonly className: `is-kind-${K}`
  /** One sentence on the palette tile. What this kind DOES, not what it is called. */
  readonly blurb: string
  /**
   * Position in the canonical kind order, which is also the number hotkey:
   * `paletteOrder + 1` is the `1`-`7` key that drops this kind.
   *
   * The palette itself renders `vocabulary.node_kinds` in the server's order and
   * does not sort by this - the two agree because `_vocabulary()` lists the same
   * seven literals in the same order, and `tests/nodeKinds.spec.ts` reads that
   * list out of `service/builder_api.py` and asserts it. If they ever diverge,
   * the hotkey would drop a different kind from the tile above it.
   */
  readonly paletteOrder: number
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
  /** `document.py:accepts_incoming` - only `input` refuses an inbound edge. */
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
/** `document.py:_OUT_PORTS_BY_KIND["gate"]`, in that canvas order. */
const GATE_OUT: readonly string[] = ['approve', 'revise']
/** `document.py:_OUT_PORTS_BY_KIND["output"]` - an output node ends the run. */
const NO_OUT: readonly string[] = []

export const NODE_KINDS: { readonly [K in NodeKind]: NodeKindMeta<K> } = {
  input: {
    kind: 'input',
    icon: Inbox,
    className: 'is-kind-input',
    blurb: 'Seeds the run from one named request input.',
    paletteOrder: 0,
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
    icon: Bot,
    className: 'is-kind-agent',
    blurb: 'One allowlisted YAML agent, on one tier, with bound tools.',
    paletteOrder: 1,
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
    outPorts: () => SINGLE_OUT,
    acceptsIncoming: true,
    accent: '#99eaf9',
  },
  crew: {
    kind: 'crew',
    icon: Users,
    className: 'is-kind-crew',
    blurb: 'One registered crew, run whole, with its own tools.',
    paletteOrder: 2,
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
    outPorts: () => SINGLE_OUT,
    acceptsIncoming: true,
    accent: '#a0c4ff',
  },
  gate: {
    kind: 'gate',
    icon: ShieldCheck,
    className: 'is-kind-gate',
    blurb: 'Pauses for a person, who approves it or sends it back.',
    paletteOrder: 3,
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
    icon: Split,
    className: 'is-kind-router',
    blurb: 'A deterministic fork over one state key. No model, no expression.',
    paletteOrder: 4,
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
    icon: Cog,
    className: 'is-kind-transform',
    blurb: 'One of six fixed operations over the data between two nodes.',
    paletteOrder: 5,
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
    icon: FileText,
    className: 'is-kind-output',
    blurb: 'What the run hands back, under the one key that escapes the clip.',
    paletteOrder: 6,
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
}

/**
 * The seven kinds in canonical order - the order the hotkeys `1`-`7` follow.
 *
 * Derived from `paletteOrder` rather than written twice. The palette renders
 * `vocabulary.node_kinds` (the server's order) and this agrees with it, which is
 * asserted rather than assumed.
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
