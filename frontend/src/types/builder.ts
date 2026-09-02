import type { GraphDescriptor } from './studio'

/**
 * The wire mirror of `builder.flow/v1` - what an author draws, before anything
 * compiles it.
 *
 * Every declaration here mirrors a Python one, and the Python is the ground
 * truth: `src/brief_crew/builder/document.py` for the document and its seven
 * per-kind configs, `builder/bounds.py` for `Problem` and the problem codes,
 * `builder/budget.py` for the estimate, `service/builder_api.py` for the
 * response envelopes and the vocabulary, and `config.py` for every pattern and
 * ceiling either side quotes. Where a value is restated rather than fetched it
 * names its source in a comment and `tests/builderTypes.spec.ts` asserts the
 * two agree - the `serverLimits.ts` idiom, for the same reason: duplicated
 * constants drift, and a drift that is a failing test is not a drift that is a
 * 422 in front of an author.
 *
 * WHAT THIS FILE DELIBERATELY DOES NOT CONTAIN. No bound is *enforced* here.
 * `bounds.py` counts nodes, branches, cycles and dollars and reports them as
 * Problems the client renders; a client-side recount is a second opinion that
 * silently disagrees with the compiler the first time the server changes. The
 * few things below that look like enforcement - the id pattern, the scalar
 * union, the literal `'in'` target port - are the server's *parse* refusals,
 * which are 422s rather than problems and so must never be sent at all.
 *
 * THE ONE WIRE-SPELLING TRAP is the document's `schema` key. Pydantic refuses a
 * field called `schema` outright because it shadows a `BaseModel` attribute, so
 * the Python field is `document_schema` with `alias="schema"`, and the server
 * dumps `by_alias=True`. Both directions on the wire therefore say `schema`,
 * and so does the interface below. `utils/builderSerialize.ts::toWire` is the
 * single place that guarantees it.
 */

/* --- branded ids ---------------------------------------------------------
 * A label can never be assigned where an id belongs - that is a compile error,
 * not a 422. Mint through the guards; never cast.
 *
 * The brands are `unique symbol` declarations rather than a string literal
 * member, so the tag exists only in the type system: at runtime a NodeId is a
 * plain string and `JSON.stringify` sees nothing extra. */
declare const NODE_ID: unique symbol
declare const EDGE_ID: unique symbol
declare const DOC_ID: unique symbol

export type NodeId = string & { readonly [NODE_ID]: true }
export type EdgeId = string & { readonly [EDGE_ID]: true }
export type DocumentId = string & { readonly [DOC_ID]: true }

/**
 * `config.py:BUILDER_ID_PATTERN` - first char a-z, then 0..39 of `[a-z0-9_]`.
 *
 * The 40-character ceiling is not cosmetic. A node compiles to the flow method
 * ident `n{index}_{node_id}`, and `MAX_IDENTIFIER_LENGTH` in `events/models.py`
 * TRUNCATES silently rather than raising - a truncation there merges two nodes
 * into one in every frame the run emits.
 */
export const NODE_ID_PATTERN = /^[a-z][a-z0-9_]{0,39}$/
/** `config.py:BUILDER_DOCUMENT_ID_PATTERN` - server-assigned, never client-chosen. */
export const DOCUMENT_ID_PATTERN = /^ug_[0-9a-f]{8}$/
/**
 * `config.py:BUILDER_STATE_REF_PATTERN` - ONE flat lowercase key. No nesting.
 *
 * Single-key by construction: `${state.a_value}` was measured resolving and
 * nested dotted access was not, so `${state.out__scoper.segment}` would reach
 * the agent as that exact text. `document.py::_checked_with_value` refuses a
 * near-miss at parse time rather than passing it through as a literal, which
 * makes this a 422 the client must never send.
 */
export const STATE_REF_PATTERN = /^\$\{state\.[a-z0-9_]{1,64}\}$/
/** `config.py:BUILDER_STATE_OUTPUT_PREFIX` - the compiler writes each node's return to `out__<id>`. */
export const STATE_OUTPUT_PREFIX = 'out__'
/** `config.py:BUILDER_DOCUMENT_SCHEMA` - the only legal value of `schema`. */
export const BUILDER_SCHEMA_ID = 'builder.flow/v1'

export const isNodeId = (v: string): v is NodeId => NODE_ID_PATTERN.test(v)
export const nodeId = (v: string): NodeId => {
  if (!isNodeId(v)) throw new Error(`not a NodeId: ${v}`)
  return v
}
/**
 * An edge id is checked against the SAME pattern, and that is the Python rather
 * than an approximation of it: `BuilderEdge.id` is annotated `NodeId`, so the
 * two namespaces share one shape while staying separate types on this side.
 */
export const edgeId = (v: string): EdgeId => {
  if (!NODE_ID_PATTERN.test(v)) throw new Error(`not an EdgeId: ${v}`)
  return v as EdgeId
}
export const documentId = (v: string): DocumentId => {
  if (!DOCUMENT_ID_PATTERN.test(v)) throw new Error(`not a DocumentId: ${v}`)
  return v as DocumentId
}

/* --- scalars -------------------------------------------------------------
 * `document.py:JsonScalar`. Arrays and objects are REFUSED by the server in
 * prompt_inputs values, transform.args values, output.source and
 * RouterBranch.value - every argument shape the ten compiler entrypoints
 * accept is flat, and a nested literal would be a place to hide something the
 * compiler never looks at. */
export type JsonScalar = string | number | boolean | null

export type NodeKind =
  | 'input' | 'agent' | 'crew' | 'gate' | 'router' | 'transform' | 'output'
export type Tier = 'cheap' | 'escalation'
export type Severity = 'error' | 'warning'
/** `store.py:STATUS_DRAFT` / `STATUS_PUBLISHED`. */
export type DocumentStatus = 'draft' | 'published'

/** `document.py:_OUT_PORTS_BY_KIND`. `in` is the ONLY target port, for every kind. */
export type TargetPort = 'in'
export type GatePort = 'approve' | 'revise'

/* --- per-kind configs -------------------------------------------------- */

export interface InputConfig {
  /** REQUIRED. The `inputs` key `POST /api/sessions/{id}/runs` must carry. */
  field: NodeId
  /**
   * 1..40 or null. What the console labels the box, distinct from the node's
   * own canvas label - a node called "Idea" may reasonably ask for "Describe
   * the product in a sentence or two".
   */
  label: string | null
  /** int, 1..`MAX_RUN_INPUT_CHARS`. default 2000. */
  max_chars: number
  /** default true. */
  required: boolean
}

/**
 * `document.py:_BillableConfig` + `AgentConfig`.
 *
 * Both ceilings bound RETRY, which is where one node's cost multiplies rather
 * than adds: CrewAI counts guardrail retries PER GUARDRAIL, so the unset
 * default of 3 permits eight full regenerations of a two-guardrail task.
 */
export interface AgentConfig {
  /** REQUIRED, no default. */
  tier: Tier
  /** int, 1..`BUILDER_MAX_AGENT_ITER` (8). default `VALIDATOR_BRANCH_MAX_ITER` = 2. */
  max_iter: number
  /** int, 0..`BUILDER_MAX_GUARDRAIL_RETRIES` (2). default 2. */
  guardrail_max_retries: number
  /** default {}. Each value a JsonScalar, or the one resolvable state ref. */
  prompt_inputs: Record<string, JsonScalar>
  /** REQUIRED. One of `vocabulary.agent_ids` - keys the YAML registry, never carries a prompt. */
  agent_id: NodeId
  /** default []. Each in `vocabulary.research_tools`. Duplicates rejected server-side. */
  tools: string[]
}

export interface CrewConfig {
  /**
   * REQUIRED. A DECLARATION, not a derivation - the document is priced before
   * anything is constructed, so an author names the escalation-most tier the
   * crew's agents run on. It is what `MAX_ESCALATION_NODES` counts and what the
   * budget prices, on that word alone, even though `run_crew` ignores it.
   */
  tier: Tier
  /** Accepted by the schema, IGNORED at runtime - `run_crew` runs the crew whole. */
  max_iter: number
  /** Accepted by the schema, IGNORED at runtime. */
  guardrail_max_retries: number
  prompt_inputs: Record<string, JsonScalar>
  /** REQUIRED. One of `vocabulary.crew_ids`. */
  crew_id: NodeId
  // NO `tools` key. A crew declares its own tools and `BuilderModel` is
  // `extra="forbid"`, so sending one is a 422 rather than a silently dropped
  // key - which is why this interface has nothing for an inspector to render.
}

export interface GateConfig {
  /** 1..`BUILDER_MAX_GATE_MESSAGE_CHARS` (2000). REQUIRED. */
  message: string
  /** default []. Duplicates rejected server-side. Seeds the rendered gate payload. */
  editable_fields: NodeId[]
  /**
   * int >= 0, default 1. There is NO schema upper bound here on purpose: above
   * `MAX_CYCLE_ITERATIONS` (3) it is a `cycle-iterations` PROBLEM naming the
   * bound and by how much, not a pydantic error the author cannot act on.
   */
  max_turns: number
  /**
   * int, 1..`VALIDATOR_GATE_TIMEOUT_SECONDS` (1800), default 1800. Capped at
   * the service's own gate timeout, because a gate claiming to stay open longer
   * than the service keeps it open is a promise nothing can keep.
   */
  expiry_seconds: number
}

/** `config.py:BUILDER_ROUTER_COMPARISONS` plus `BUILDER_ROUTER_OTHERWISE`. */
export type RouterOp =
  | 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'contains' | 'otherwise'

/**
 * One declared way out of a router: a label, and one comparison over ONE state
 * key. There is no expression here and there will not be one - an expression
 * surface is an evaluation surface, and an author who needs arithmetic writes a
 * `transform` node whose six operations are equally closed.
 */
export interface RouterBranch {
  /** REQUIRED. This IS the out-port name an edge leaves by. */
  label: NodeId
  /** REQUIRED. */
  op: RouterOp
  /** REQUIRED (non-null) for every op except `otherwise`; MUST be null when `otherwise`. */
  key: NodeId | null
  /** MUST be null when `op === 'otherwise'` - it is what happens when every comparison missed. */
  value: JsonScalar
}

export interface RouterConfig {
  /**
   * `MIN_ROUTER_BRANCHES`..`MAX_FANOUT_WIDTH` (2..4), enforced as a PROBLEM
   * rather than a 422: an author who drew five wants to be told the ceiling is
   * four. The schema's own default is an empty tuple.
   */
  branches: RouterBranch[]
}

/** `config.py:BUILDER_TRANSFORM_OPS`. Six, and there is no seventh escape hatch. */
export type TransformOp =
  | 'pick' | 'merge' | 'join_text' | 'to_json' | 'default' | 'format'

export interface TransformConfig {
  /** REQUIRED. */
  op: TransformOp
  /**
   * default {}. Arg NAMES are not validated per op by the schema - only the
   * values are, as JsonScalar-or-one-state-ref. Which names an op reads is
   * `runtime.py`'s business, and the inspector's.
   */
  args: Record<string, JsonScalar>
}

export interface OutputConfig {
  /**
   * REQUIRED. In `vocabulary.result_body_keys`; today `markdown_body` is the
   * only member. Not a formality: those keys get `MAX_RUN_RESULT_BODY_CHARS`
   * instead of the streaming frame's 4 KiB clip, and a body written under any
   * other key comes back truncated mid-sentence - exactly how the first paid
   * run's report was lost.
   */
  body_key: string
  /** default null. */
  source: JsonScalar
}

export type BuilderNodeConfig =
  | InputConfig | AgentConfig | CrewConfig
  | GateConfig | RouterConfig | TransformConfig | OutputConfig

/* --- discriminated node --------------------------------------------------
 * The union is what makes `node.config.branches` narrow only on 'router' and
 * every inspector switch exhaustiveness-checkable. A new kind becomes a
 * compile error, not a blank pane. */

/** INTEGERS. `document.py:Position` declares `int`, so `120.5` is a hard 422. */
export interface NodePosition { x: number; y: number }

interface BuilderNodeBase {
  id: NodeId
  /** 1..`BUILDER_MAX_LABEL_CHARS` (40), REQUIRED, no default. */
  label: string
  /**
   * default {x:0,y:0}. Never compiled and never read at runtime - it exists so
   * the canvas can redraw what the author arranged - but still int-typed, which
   * is why every write rounds.
   */
  position: NodePosition
}

export type BuilderNode =
  | (BuilderNodeBase & { kind: 'input';     config: InputConfig })
  | (BuilderNodeBase & { kind: 'agent';     config: AgentConfig })
  | (BuilderNodeBase & { kind: 'crew';      config: CrewConfig })
  | (BuilderNodeBase & { kind: 'gate';      config: GateConfig })
  | (BuilderNodeBase & { kind: 'router';    config: RouterConfig })
  | (BuilderNodeBase & { kind: 'transform'; config: TransformConfig })
  | (BuilderNodeBase & { kind: 'output';    config: OutputConfig })

export interface BuilderEdge {
  id: EdgeId
  source: NodeId
  /**
   * `'out'` for a single-output kind, `'approve'`/`'revise'` on a gate, or a
   * router's declared branch label. NodeId-shaped, default `'out'`, and checked
   * against the SOURCE NODE's own ports in `bounds.py` - the only place that
   * knows both.
   */
  source_port: string
  target: NodeId
  /**
   * The literal `'in'` is the ONLY legal value. A second inbound port would be
   * a join semantics this document deliberately does not have: `joins` says how
   * arrivals combine, and the answer is always "all".
   */
  target_port: TargetPort
}

/**
 * node_id -> 'all'. `'any'` is REFUSED at parse time with a message rather than
 * reported, because there is nothing to fix except deleting it: a multi-event
 * `or_()` listener is added to `_fired_or_listeners` the first time it fires and
 * skipped forever after, so the SECOND arrival ends the run normally having
 * produced nothing. No exception, no warning, no frame. Measured both ways.
 */
export type BuilderJoins = Record<string, 'all'>

/**
 * The compiler's static estimate, stored on the document it priced. Written by
 * `budget.py`, never by an author: send `null`, or round-trip it verbatim.
 */
export interface BuilderBudgetBlock {
  static_cost_usd: number
  billable_nodes: number
  escalation_nodes: number
  cycles: number
  /** ISO datetime. REQUIRED if the object exists at all. */
  compiled_at: string
}

export interface BuilderDocument {
  /**
   * WIRE KEY IS `schema`. The python field is `document_schema` with
   * `alias="schema"`, because a pydantic field named `schema` shadows a
   * `BaseModel` attribute and the model is refused outright.
   */
  schema: typeof BUILDER_SCHEMA_ID
  /** SERVER-ASSIGNED. `builder_api.parse()` overwrites whatever is sent, always. */
  id: DocumentId
  /** 1..`BUILDER_MAX_NAME_CHARS` (80), whitespace-stripped server-side. */
  name: string
  /** SERVER-ASSIGNED and monotonic; `store.save` stamps `expected_version + 1`. */
  version: number
  /** Must equal exactly one input node's `config.field`. Cross-object, so `bounds.py` checks it. */
  input_field: NodeId
  nodes: BuilderNode[]
  edges: BuilderEdge[]
  joins: BuilderJoins
  budget: BuilderBudgetBlock | null
}

/* --- problems ---------------------------------------------------------- */

/**
 * Every code the server can emit, from THREE files: the twenty-five named
 * constants at the top of `bounds.py`, `budget.py`'s two, and `compiler.py`'s
 * three. Ordered the way an author meets them - counts, identity, wiring,
 * cycles, reachability, joins, compiled idents, money, library - rather than
 * alphabetically, because this tuple is also the order a panel is free to group
 * by.
 *
 * The third file was missing until 2026-09-02, and it is the one that matters
 * most. `compiler.py::library_problems` is not a publish-only check -
 * `validate_document` calls it, so `service/builder_api.py` emits these three on
 * the GET-workflow, POST-/validate and publish paths alike. And
 * `library-missing-prompt-input` is the single most common problem in the whole
 * builder: `nodeKinds.ts` mints an agent node with `prompt_inputs: {}`, and
 * `missing_prompt_inputs` is non-empty for ALL SIX registered agent ids -
 * measured, from `scoper`'s two to `reporter`'s five - so it is on screen from
 * the moment an author drops their first agent until every input is filled. A
 * mirror that was missing exactly that code would have rendered the builder's
 * most frequent message as an unrecognised one.
 *
 * `tests/builderTypes.spec.ts` asserts this set equals the Python's, reading all
 * three files at run time, so a code added on that side becomes a failing test
 * rather than a row the panel renders without a home. Note what let the omission
 * survive: the test's regex already matched these three constants and its
 * count assertion already agreed with its own file list - it was green because
 * it and the tuple were wrong by the same three, which is the failure mode a
 * mirror is uniquely prone to. The fix was one path in an array.
 */
export const PROBLEM_CODES = [
  'node-count', 'billable-count', 'escalation-count',
  'duplicate-node-id', 'duplicate-edge-id',
  'edge-unknown-endpoint', 'edge-unknown-port', 'edge-target-refuses-incoming',
  'fanout-width',
  'router-branch-count', 'router-otherwise', 'router-duplicate-branch',
  'router-branch-unconnected',
  'cycle-count', 'back-edge-not-router', 'cycle-iterations',
  'no-input-node', 'input-field-undeclared', 'input-field-ambiguous',
  'node-unreachable', 'no-output-node',
  'join-unknown-node', 'join-single-predecessor',
  'ident-pattern', 'ident-collision',
  'budget-over-ceiling', 'budget-unpriced-model',
  'library-unknown-id', 'library-missing-prompt-input', 'library-unbuildable-crew',
] as const
export type ProblemCode = (typeof PROBLEM_CODES)[number]

/**
 * The ONLY three warnings; everything else is an error and blocks publish.
 * `bounds.py` writes `severity="warning"` at exactly three sites, and all three
 * describe a graph that is legal and probably not what was meant.
 */
export const WARNING_CODES = [
  'router-branch-unconnected', 'no-output-node', 'join-single-predecessor',
] as const

export interface BuilderProblem {
  /**
   * The `| string` fallback is deliberate. A code this build has never heard of
   * must still render its sentence - the alternative is a server that grew a
   * check and a client that silently drops it.
   */
  code: ProblemCode | string
  severity: Severity
  /** A full sentence written for the author. RENDER VERBATIM. */
  message: string
  node_id: string | null
  edge_id: string | null
}

/**
 * Which inspector control a problem anchors to.
 *
 * Anything absent falls to the node-level strip at the top of the inspector, so
 * no problem is ever silently dropped. Note that a code appearing here is a
 * statement about WHICH FIELD, not a promise that the problem carries a node at
 * all: `billable-count` and `node-count` are graph-wide and arrive with both
 * anchors null (`bounds.py::_count_problems`), so they land in the document
 * group and this entry never fires. `escalation-count` DOES carry the node that
 * crossed the line, which is why its `tier` entry is the useful one.
 */
export const FIELD_CODES: Partial<Record<ProblemCode, string>> = {
  'router-branch-count': 'branches',
  'router-otherwise': 'branches',
  'router-duplicate-branch': 'branches',
  'router-branch-unconnected': 'branches',
  'cycle-iterations': 'max_turns',
  'input-field-ambiguous': 'field',
  'escalation-count': 'tier',
  'billable-count': 'tier',
  'edge-unknown-port': 'source_port',
  // The two library codes that DO have one field to blame. An agent node whose
  // `agent_id` is unregistered anchors to that control; the prompt-input code
  // anchors to `prompt_inputs`, which an author meets on every agent they place
  // and would otherwise read as a sentence detached from the empty map causing
  // it.
  //
  // `library-unknown-id` is honestly imperfect and says so here rather than
  // silently: `compiler.py` raises it for a CREW's unregistered `crew_id` too,
  // and a crew inspector has no `agent_id` control, so on that node the anchor
  // misses and the problem falls to the node-level strip - the documented
  // fallback above, not a dropped row. One code, two fields, and this map holds
  // one string; the agent case is the far commoner one.
  //
  // `library-unbuildable-crew` is deliberately absent. It is a fact about the
  // crew as a whole - `SynthesisCrew` and `ReportCrew` take typed findings at
  // construction, so no single control is at fault - and the node-level strip is
  // where it belongs.
  'library-unknown-id': 'agent_id',
  'library-missing-prompt-input': 'prompt_inputs',
}

/* --- budget ------------------------------------------------------------ */

export interface BuilderBudget {
  /**
   * What admission ENFORCES: `NITRO_PRICE_FACTOR` (1.8) applied to every
   * cheap-tier node. Higher than any figure an invoice will show, because
   * `:nitro` routes to the fastest provider rather than the cheapest and the
   * recorded cheap price is a floor - eight endpoints serve the cheap model
   * from $0.15/$1.25 to $0.54/$4.50.
   */
  static_cost_usd: number
  /**
   * The same graph at published prices, with no nitro inflation. Shown beside
   * the enforced figure rather than instead of it: this is the number a real
   * run's `compute_cost_usd` total is comparable with, and showing the inflated
   * one alone reads as an error.
   */
  floor_cost_usd: number
  /** Model calls the worst case makes - the unit the 8-node frontier was solved in. */
  modelled_calls: number
  billable_nodes: number
  escalation_nodes: number
  cycles: number
  /**
   * Tiers whose model `PRICES` cannot price. Never empty-and-ignored: an
   * unpriced model contributes nothing to the total, so a non-empty list is a
   * `budget-unpriced-model` ERROR. It is the only thing standing between "no
   * price on file" and "this graph is free" - the exact confusion that reported
   * a 128,069-token run at $0.00.
   */
  unpriced_models: string[]
  /**
   * `static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN` (1.25) against
   * `MAX_RUN_COST_USD`. ALWAYS false when the ceiling is <= 0, which is how the
   * ceiling is disabled.
   */
  over_ceiling: boolean
  /** `MAX_RUN_COST_USD`, default 10.0. <= 0 means DISABLED. */
  ceiling_usd: number
}

/* --- vocabulary -------------------------------------------------------- */

/**
 * `BuilderVocabularyModel.bounds` is typed `dict[str, float]` in Python, so
 * EVERY value arrives as a JSON float - `24.0`, not `24`. `Math.trunc` on
 * ingest, or a headroom pip row reads "8 of 8.0".
 */
export interface BuilderBounds {
  max_graph_nodes: number
  max_billable_nodes: number
  max_escalation_nodes: number
  max_fanout_width: number
  min_router_branches: number
  max_cycles: number
  max_cycle_iterations: number
  max_agent_iter: number
  max_guardrail_retries: number
  max_label_chars: number
  max_name_chars: number
  max_gate_message_chars: number
  max_input_chars: number
  max_document_bytes: number
  /** `MAX_RUN_COST_USD`. <= 0 means DISABLED - and it is a dollar figure, so it is NOT trunc'd. */
  run_cost_ceiling_usd: number
}

/**
 * Everything the palette and the inspector are allowed to offer, served rather
 * than duplicated: a canvas offering a transform op the compiler does not have
 * is a 422 the author cannot act on, and a canvas missing one is a feature
 * nobody can reach.
 */
export interface BuilderVocabulary {
  schema_id: string
  /** ORDERED literals in the handler, deliberately not sorted. Render in this order. */
  node_kinds: NodeKind[]
  /** Ordered: cheap, then escalation. */
  tiers: Tier[]
  agent_ids: string[]
  crew_ids: string[]
  research_tools: string[]
  transform_ops: TransformOp[]
  /** Sorted, and WITHOUT `otherwise` - which is not a comparison and is named separately. */
  router_comparisons: string[]
  /** `'otherwise'`. */
  router_otherwise: string
  result_body_keys: string[]
  bounds: BuilderBounds
}

/* --- responses --------------------------------------------------------- */

export interface BuilderDocumentSummary {
  id: string
  name: string
  version: number
  status: DocumentStatus
  created_at: string
  updated_at: string
}

export interface BuilderDocumentModel {
  id: string
  /** The document exactly as stored, by its wire spelling. What goes out may be sent back. */
  document: BuilderDocument
  /** The STORED fact. */
  status: DocumentStatus
  /** The version you are looking at; `version === head_version` means you are on head. */
  version: number
  head_version: number
  created_at: string
  updated_at: string
  /** Recomputed on every response - never read off the document. */
  problems: BuilderProblem[]
  /** Recomputed on every response. NOT `document.budget`, which is the compiler's stored block. */
  budget: BuilderBudget
  /**
   * The graph as the console renders it, byte-identical to what
   * `GET /api/workflows/{id}/graph` returns. Included on a load so the canvas
   * has one request rather than two, and so a DRAFT can be drawn at all - that
   * endpoint only answers for a published graph.
   */
  graph: GraphDescriptor
  /**
   * True when this exact version is registered ON THIS PROCESS. It can be false
   * while `status` is `'published'`: a restart clears the module maps and
   * nothing re-registers them, so the stored fact and the live fact disagree
   * and both are honest.
   */
  published: boolean
}

export interface BuilderValidation {
  /** `=== problems.every(p => p.severity !== 'error')`. Warnings never block. */
  valid: boolean
  problems: BuilderProblem[]
  budget: BuilderBudget
}

export interface BuilderPublish {
  /** The document id. */
  workflow_id: string
  /** 16 lowercase hex - the graph ETag body. */
  graph_version: string
  version: number
  /** The key `POST /api/sessions/{id}/runs` must carry inside `inputs`. */
  input_field: string
  static_cost_usd: number
  /**
   * False when a billable node is reachable from the input without passing a
   * gate. An anonymous launch of such a graph is refused 403 unless
   * `BUILDER_ALLOW_GATELESS_GRAPHS` is set.
   */
  gated_before_spend: boolean
  /** Sorted. Refused inside `inputs` with a 422. */
  reserved_input_keys: string[]
}

/**
 * Publish's 422 is the ONE error on this router whose `detail` is an OBJECT
 * rather than a string - `build_builder_workflow` raises `BuilderCompileError`
 * carrying the same problem list the canvas already knows how to draw, and
 * flattening it to a sentence would throw that away.
 */
export interface BuilderCompileRefusal {
  message: string
  problems: BuilderProblem[]
}

export interface BuilderDocumentRequest {
  /**
   * `toWire(doc)`. Untyped on the server too (`dict[str, Any]`) so a bad
   * document comes back as a problem list rather than FastAPI's own 422, which
   * echoes the offending input and names pydantic locations rather than nodes.
   */
  document: unknown
  /**
   * MANDATORY on PUT - a save with no version to compare against is a lost
   * update waiting to happen. Ignored on POST and on validate.
   */
  expected_version: number | null
}
