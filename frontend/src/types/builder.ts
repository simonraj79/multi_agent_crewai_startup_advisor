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
/**
 * `config.py:CREDENTIAL_ID_PATTERN` - `cr_` + 8 hex, server-minted like a
 * document id. The document carries a credential as this OPAQUE id and nothing
 * else: the parser never resolves it, the compiler never sees a field value,
 * and `resolve_credential` reads the row at run time scoped to the user the
 * run belongs to (plan 01 D5). Restated here so `credentialPicker.spec.ts` can
 * assert the two agree, the `serverLimits.ts` way.
 */
export const CREDENTIAL_ID_PATTERN = /^cr_[0-9a-f]{8}$/

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

/**
 * `document.py:NodeKind` - TEN kinds in two families, in the Python's own order.
 *
 * FLOW kinds are steps: an edge arrives, something happens, it passes on.
 * ATTACHMENT kinds are not steps at all - they are things an agent or a crew
 * HAS, and they reach it along an `attach` edge. They never run, never bill,
 * never sit in a cycle and never count toward the graph-size bound, because
 * none of that is true of a possession.
 *
 * The union is CLOSED on both sides of the wire, and closing it is what turns
 * "somebody added a kind and forgot the inspector" into a build failure rather
 * than a blank pane: `nodeKinds.ts`'s `NODE_KINDS` is a mapped type over this
 * union, `InspectorRail.vue`'s `INSPECTORS` is a `Record<NodeKind, Component>`,
 * `builderDefaults.ts::newNode` switches exhaustively over it, and
 * `BuilderNode.vue`'s `KIND_EYEBROW` and `summariseConfig` are total over it.
 * Five compile errors from one added word.
 */
export type NodeKind =
  // flow
  | 'input' | 'agent' | 'crew' | 'gate' | 'router' | 'transform' | 'output'
  // attachment
  | 'tool' | 'mcp' | 'skill'

/**
 * `document.py:ATTACHMENT_KINDS`, and the two families it partitions the union
 * into. Restated here rather than derived, because the client needs the set at
 * RUN time (a pill is not a card) and TypeScript's unions do not survive to
 * run time; `tests/nodeKinds.spec.ts` reads the frozenset out of `document.py`
 * and asserts the two agree, and that the two families partition the union.
 */
export const ATTACHMENT_KINDS = ['tool', 'mcp', 'skill'] as const
export type AttachmentKind = (typeof ATTACHMENT_KINDS)[number]
export type FlowKind = Exclude<NodeKind, AttachmentKind>
/** Which family a kind belongs to - the one fact a card-versus-pill decision reads. */
export const isAttachmentKind = (kind: NodeKind): kind is AttachmentKind =>
  (ATTACHMENT_KINDS as readonly string[]).includes(kind)

export type Tier = 'cheap' | 'escalation'
export type Severity = 'error' | 'warning'
/** `store.py:STATUS_DRAFT` / `STATUS_PUBLISHED`. */
export type DocumentStatus = 'draft' | 'published'

/**
 * `document.py:BuilderEdge.target_port` - what an edge may ARRIVE at.
 *
 * `in` is the flow itself and was the only value before the ten-kind
 * vocabulary. `attach` hangs a tool, an MCP server or a skill off an agent or a
 * crew; `member` puts an agent inside a crew. Neither is a step: `bounds.py`
 * excludes both from fan-out counting, from cycle detection and from billable
 * depth, because an agent holding three tools has not branched three ways and a
 * tool cannot be part of a loop.
 *
 * EDGE CLASS IS A PURE FUNCTION OF THIS FIELD AND OF NOTHING ELSE. That is the
 * whole reason an attachment's single port is a SOURCE - the tool reaches
 * toward the agent, never the reverse - so the canvas's stroke rules and the
 * server's bounds rules need to agree about one string rather than each
 * independently deciding what the source happened to be.
 */
export type TargetPort = 'in' | 'attach' | 'member'
export type GatePort = 'approve' | 'revise'
/** An attachment's one source port. `_OUT_PORTS_BY_KIND` gives all three `('attach',)`. */
export type AttachPort = 'attach'

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
/**
 * What a billable node does when its step raises - 03 D3's `on_error`.
 *
 * `fail` (the absence, and the only behaviour the runtime has today) ends the
 * run. `route` sends the failure out of a SECOND source port named `error`, so
 * an author can draw the recovery path instead of losing the run to it.
 *
 * OPTIONAL, and it stays optional until the Python half of D3 lands. Today's
 * `_BillableConfig` has no such field and `BuilderModel` is `extra="forbid"`,
 * so a document that carried the key would be a 422 rather than a feature -
 * which is why `nodeKinds.ts` never writes one into a fresh node and why
 * `outPortsOf` reads it as "absent means `fail`".
 */
export type NodeErrorPolicy = 'fail' | 'route'

/**
 * `document.py:ToolFailurePolicy` - `Agent.tool_failure_policy` at CrewAI
 * 1.15.18, by its enum's own VALUES rather than its member names.
 */
export type ToolFailurePolicy = 'ignore' | 'warn' | 'raise'

/**
 * `document.py:ScalarType`. FOUR, not six.
 *
 * 04 D2's prose asks a `SchemaEditor` for `string/number/boolean/array/object`.
 * The schema admits neither `array` nor `object` and adds `integer`, because
 * `task.output_schema` is a FLAT map the compiler turns into a pydantic class
 * with `create_model` - a nested schema would be a second document format
 * inside the document. The package wins; the editor offers these four.
 */
export type ScalarType = 'string' | 'number' | 'integer' | 'boolean'

/**
 * `document.py:TaskConfig` - the one `Task` an authored agent runs.
 *
 * A composite rather than five flat fields because a Task is one CrewAI
 * primitive, and it is one of the three composites whose collapse is the
 * difference between FD5's 25 and its 41.
 */
export interface TaskConfig {
  /** REQUIRED, 1..`bounds.max_prompt_chars`. */
  description: string
  /** REQUIRED, same bound. */
  expected_output: string
  /**
   * A FLAT map of property name to scalar type, or null. Compiles to
   * `Task.output_json` / `Task.response_model` via `create_model`.
   */
  output_schema: Record<string, ScalarType> | null
  markdown: boolean
  async_execution: boolean
}

/**
 * `document.py:LlmConfig` - eleven leaves, and the reason FD5 counts 41 rather
 * than 25.
 *
 * `stream` is absent on purpose: a builder run streams frames by construction,
 * so there is nothing for an author to decide. `reasoning_effort` takes the
 * eleventh slot instead, and the inspector gates it on `supports_reasoning`
 * because OpenRouter drops it for every model in this roster.
 */
export interface LlmConfig {
  /** REQUIRED. A registry model id, in any of the four spellings `baseSlug` folds. */
  model: string
  /** 0..2, or null. */
  temperature: number | null
  /** 0..1, or null. */
  top_p: number | null
  /** >= 1, or null. No ceiling - what a completion COSTS is `run_cost_ceiling_usd`'s job. */
  max_tokens: number | null
  /** Seconds, >= 1, or null. */
  timeout: number | null
  /** Gated on `supports_json_mode`. */
  response_format: 'text' | 'json_object' | null
  /** -2..2, or null. */
  frequency_penalty: number | null
  /** -2..2, or null. */
  presence_penalty: number | null
  /** At most four - the OpenAI-compatible ceiling, enforced by `LlmConfig._validate_stop`. */
  stop: string[]
  seed: number | null
  /** Gated on `supports_reasoning`. SILENTLY DROPPED for every OpenRouter model. */
  reasoning_effort: 'low' | 'medium' | 'high' | null
}

/**
 * `document.py:RetryConfig` - the builder's OWN whole-node retry loop.
 *
 * Not `Task.max_retries`, which is deprecated at CrewAI 1.15.18, counts
 * GUARDRAIL retries and is a different concept sharing a name. The field that
 * means what CrewAI's means is `guardrail_max_retries` on the shared base.
 */
export interface RetryConfig {
  /** 0..`bounds.max_retries`. */
  max_retries: number
  /** 0..`BUILDER_MAX_RETRY_BACKOFF_SECONDS` (60). */
  backoff_seconds: number
  /** The model to try on the LAST attempt. A REFUSAL is never retried with it (decision 16). */
  fallback_model: string | null
}

/**
 * `document.py:PlanningConfig` - FOUR of CrewAI's eleven.
 *
 * The 00 S9 deprecation ruling: `Agent.reasoning` and
 * `Agent.max_reasoning_attempts` are deprecated at 1.15.18 and are REPLACED by
 * `Agent.planning` plus these four. The three prompt overrides are excluded
 * because prompts live in YAML for this repository's crews and in the document
 * for an authored agent, and a third place would be a third place; `llm` is
 * excluded because it would put the planner on a different model from the one
 * the node names - a cost surprise with no visible cause.
 */
export interface PlanningConfig {
  reasoning_effort: 'low' | 'medium' | 'high'
  /** 1..`bounds.max_retries`, or null. */
  max_attempts: number | null
  /** 1..`BUILDER_MAX_PLANNING_STEPS` (20). */
  max_steps: number
  /** 0..`bounds.max_retries`. */
  max_replans: number
}

export interface LibraryAgentConfig {
  /** REQUIRED, no default. */
  tier: Tier
  /**
   * D1's conditional port. `'route'` grows an `error` source port on the card;
   * anything else, including the absence, does not. See `NodeErrorPolicy` for
   * why this is optional rather than defaulted.
   */
  on_error?: NodeErrorPolicy
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
  /**
   * A BYO OpenRouter key, as the id of one of the author's own credentials
   * (`CREDENTIAL_ID_PATTERN`), or null for the platform key. Stage 1's stand-in
   * for C1 v2's `llm.credential_id` (S1 ruling 8), which is why it is optional
   * here: a document written before the field existed carries no key at all.
   * Never a secret - the runtime resolves it inside the entrypoint, scoped to
   * the run's user, and a foreign id fails as `credential-not-yours` there.
   */
  credential_id?: string | null
}

/**
 * `document.py:AuthoredAgentConfig` - a role, a goal, a backstory and one task
 * the author wrote. FD5's canonical list as amended by the 00 S9 ruling.
 *
 * FOUR fields the older plan text names are deliberately ABSENT, and each
 * absence is a decision rather than an oversight:
 *
 *   - `multimodal` and `function_calling_llm` are CUT. Both are deprecated at
 *     CrewAI 1.15.18 and `multimodal`'s own message says it goes at v2.0, so a
 *     control for either warns today and breaks at the next major.
 *   - `reasoning` and `max_reasoning_attempts` are REPLACED by `planning` and
 *     `planning_config`. CrewAI already folds the old pair into a
 *     `PlanningConfig` and emits a `DeprecationWarning`; the switch an author
 *     sees should be the one the package keeps.
 *
 * Attachments - tools, MCP servers, skills - are NOT fields. They arrive along
 * `attach` edges and reach the constructor through the compiled `with:` block,
 * which is what keeps "what this agent has" a thing you can see on the canvas
 * rather than a list buried in a form. Flowise v2's `agentTools` array is the
 * anti-pattern this avoids.
 */
export interface AuthoredAgentConfig {
  /* --- the shared billable base, identical to the library arm ------------ */
  tier: Tier
  on_error?: NodeErrorPolicy
  max_iter: number
  guardrail_max_retries: number
  prompt_inputs: Record<string, JsonScalar>

  /* --- essentials -------------------------------------------------------- */
  role: string
  goal: string
  backstory: string
  task: TaskConfig
  llm: LlmConfig

  /* --- advanced ---------------------------------------------------------- */
  max_rpm: number | null
  max_execution_time: number | null
  allow_delegation: boolean
  /** `Agent.memory` is UNIFIED at 1.15.18 and is not three toggles. */
  memory: boolean
  cache: boolean
  respect_context_window: boolean
  retry: RetryConfig

  /* --- expert ------------------------------------------------------------ */
  system_template: string | null
  prompt_template: string | null
  response_template: string | null
  tool_failure_policy: ToolFailurePolicy | null
  planning: boolean
  /**
   * `null` unless `planning` is on: `AuthoredAgentConfig._validate_planning`
   * RAISES on a config that sets one without the other, so the inspector never
   * writes that shape.
   */
  planning_config: PlanningConfig | null
  credential_id?: string | null
}

export interface LibraryCrewConfig {
  /**
   * REQUIRED. A DECLARATION, not a derivation - the document is priced before
   * anything is constructed, so an author names the escalation-most tier the
   * crew's agents run on. It is what `MAX_ESCALATION_NODES` counts and what the
   * budget prices, on that word alone, even though `run_crew` ignores it.
   */
  tier: Tier
  /** D1's conditional port, exactly as on an agent. See `NodeErrorPolicy`. */
  on_error?: NodeErrorPolicy
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

/**
 * `document.py:AuthoredCrewConfig` - a team the author assembled.
 *
 * FIFTEEN fields, per the 00 S9 ruling that settled 04's count against its own
 * prose: **`verbose` is the fifteenth**. The gauntlet's Crew Essentials line
 * reads `process (sequential/hierarchical), verbose`; `process` is among the
 * fourteen 04's paragraph names and `verbose` is not, and `Crew.verbose` exists
 * at 1.15.18 and is not deprecated.
 *
 * The MEMBERSHIP is not a field - it is the set of `member` edges arriving
 * here - which is why the inspector renders the member list read-only and lets
 * an author drag the order that `task_order` records.
 */
export interface AuthoredCrewConfig {
  tier: Tier
  on_error?: NodeErrorPolicy
  max_iter: number
  guardrail_max_retries: number
  prompt_inputs: Record<string, JsonScalar>

  process: 'sequential' | 'hierarchical'
  /** The member node ids, in the order their tasks run. */
  task_order: NodeId[]
  /**
   * `Crew.__init__` RAISES when the process is hierarchical and neither manager
   * is set, and a sequential crew refuses both - `_validate_manager` checks the
   * pair here rather than reporting it, because it is a cross-field rule about
   * one object.
   */
  manager_llm: LlmConfig | null
  manager_agent: NodeId | null
  memory: boolean
  cache: boolean
  max_rpm: number | null
  planning: boolean
  planning_llm: LlmConfig | null
  retry: RetryConfig
  verbose: boolean
}

/**
 * The two arms per billable kind, discriminated by PRESENCE rather than a tag.
 *
 * There is no `kind` tag because the two arms are not two things an author
 * picks in a dropdown - they are "I named one of yours" and "I wrote my own",
 * and the field that says which is the field that does the work. `document.py`
 * spells the same union the same way, and `_one_of` refuses both-or-neither at
 * parse.
 */
export type AgentConfig = LibraryAgentConfig | AuthoredAgentConfig
export type CrewConfig = LibraryCrewConfig | AuthoredCrewConfig

/** Whether this agent config is the arm whose prompts the author wrote. */
export const isAuthoredAgent = (config: AgentConfig): config is AuthoredAgentConfig =>
  !('agent_id' in config)

/** Whether this crew config is the arm whose members the author assembled. */
export const isAuthoredCrew = (config: CrewConfig): config is AuthoredCrewConfig =>
  !('crew_id' in config)

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

/* --- the three attachment configs ---------------------------------------
 * `document.py:ToolConfig`, `McpConfig`, `SkillConfig`. Each carries only its
 * SHAPE: 06 owns what a `tool_id` accepts, 07 owns MCP discovery and 08 owns
 * skill storage. Every id here is an OPAQUE key into a server-owned closed set
 * - never a module path, an import or a callable name. That is the whole reason
 * a document cannot execute code, and these are no exception. */

export interface ToolConfig {
  /** REQUIRED. Keys the server-owned tool catalogue (`vocabulary.tools[].tool_id`). */
  tool_id: NodeId
  /**
   * default {}. The tool's own configuration, flat like every other
   * author-supplied mapping - each value a JsonScalar or the one resolvable
   * state ref.
   */
  params: Record<string, JsonScalar>
  /** The author's own key for tools that need one, by id. The id travels; the secret never does. */
  credential_id?: string | null
}

/**
 * What survives an export when the server reference itself cannot.
 * `document.py::ServerHint`. Every field is optional because the export nulls
 * whatever it could not safely carry, and a hint with nothing in it is still a
 * truthful hint.
 */
export interface ServerHint {
  label?: string | null
  transport?: string | null
  /** Masked by `export.mask_url` before it is written: a real MCP url can carry
   *  `user:password@` and `?token=`, so the raw one never leaves. */
  url?: string | null
}

export interface McpConfig {
  /**
   * One MCP server, by id — and OPTIONAL, which cost a production defect to
   * learn (D-15-28). `export.py` NULLS this key on the way out, because it
   * names a row in the exporting author's own server list and a different
   * author importing that file must not end up pointing at it. While it was
   * required, an exported graph could not be re-imported by anyone, its own
   * author included.
   */
  server_id?: NodeId | null
  /** What the export leaves in `server_id`'s place. Present here because the
   *  export WRITES it and the server model is `extra="forbid"`. */
  server_hint?: ServerHint | null
  /**
   * WHICH of the server's tools this node exposes. default []. Emptiness is a
   * `bounds.py` PROBLEM rather than a parse refusal, because an author who has
   * added a server and not chosen its tools has made an incomplete graph and
   * not an invalid document - the difference between a row in the dock and a
   * save that fails.
   */
  tool_names: string[]
  credential_id?: string | null
}

export interface SkillConfig {
  /**
   * One SKILL.md pack. A skill is knowledge, not hands: its name and
   * description load at run start and its body only when a task matches.
   *
   * OPTIONAL for the same reason as `McpConfig.server_id`: the export strips
   * it, leaving `skill_name` behind as the thing an importing author's own
   * library resolves against.
   */
  skill_id?: NodeId | null
  /** The human name, which survives an export where the id cannot. */
  skill_name?: string | null
}

export type BuilderNodeConfig =
  | InputConfig | AgentConfig | CrewConfig
  | GateConfig | RouterConfig | TransformConfig | OutputConfig
  | ToolConfig | McpConfig | SkillConfig

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
  | (BuilderNodeBase & { kind: 'tool';      config: ToolConfig })
  | (BuilderNodeBase & { kind: 'mcp';       config: McpConfig })
  | (BuilderNodeBase & { kind: 'skill';     config: SkillConfig })

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
   * `'in'` for a flow edge, `'attach'` for a tool/MCP/skill hanging off an
   * agent or crew, `'member'` for an agent inside a crew. Default `'in'`.
   *
   * This field ALONE decides the edge's class. Nothing may re-derive it from
   * what the source node happened to be - see `TargetPort`.
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
  'credential-missing',
  // 03-node-library.md D2's edge classes, added 2026-09-04 with the ten-kind
  // vocabulary's server half. `attach` and `member` edges say what a node HAS
  // rather than what happens next, so every one of these is about a pair the
  // author drew rather than about a count they exceeded - which is why six of
  // the seven anchor to a node AND an edge.
  'attach-target-not-agent', 'member-target-not-crew', 'member-agent-has-flow-edges',
  'attachment-unattached', 'attachments-over-max', 'attachment-nodes-over-max',
  'crew-members-out-of-range',
  // 05-model-registry.md D7's three, added 2026-09-04 with `builder/registry.py`.
  // The first two are about WHICH model - an id no roster row carries, and a row
  // whose price crossed the ceiling after the document was published. The third
  // is about a PARAMETER, and it is the one the inspector also gates: the widget
  // disables the control and the server reports it anyway, so a stale client
  // cannot smuggle in a parameter the compiler would silently drop.
  'model-unknown', 'model-over-ceiling', 'model-lacks-capability',
  // 06-tool-registry.md, added 2026-09-04 with `builder/tools.py`. A tool node
  // names a catalogue id and nothing else, so all three are about the id, its
  // settings, or the key it needs - never about a class or a path, because a
  // document cannot carry one.
  //
  // `tool-credential-required` is deliberately NOT `credential-missing`, which
  // 06 D4 reuses for both. The repairs differ - "add a key of this kind and
  // pick it" against "that id is not yours" - and `compiler.py` already states
  // the rule that a different repair earns a different code.
  'tool-unknown', 'tool-param-invalid', 'tool-credential-required',
  // 07-mcp-client.md, added 2026-09-04 with `builder/mcp.py`. The last is the
  // FIFTH warning: a discovered tool description matching one of thirteen
  // injection patterns. It warns rather than errors because the list has false
  // positives by design - `act as` is ordinary English - and PLANS.md decision
  // 8 rules that the tool stays selectable with the warning shown.
  'mcp-server-unavailable', 'mcp-tool-unknown', 'mcp-no-tools-selected',
  'mcp-transport-disallowed', 'mcp-tool-description-suspicious',
  // 08-skills.md. One code for absent, deleted and foreign; a built-in
  // validates clean for everyone, so this is not "reject what you do not own".
  // `skill-contains-scripts` is NOT here: it is an import-time refusal that
  // never lands on a node, so it is declared in `service/builder_api.py` where
  // the three greps that build this union cannot sweep it up.
  'skill-unknown',
  // 09-compiler.md, added 2026-09-04 with the authored compile path. The first
  // two are about `document.state`: the compiler owns `out__*`, `err__*`,
  // `turns__*` and the input field, and a declared key under one of those names
  // would be overwritten by a node's own output. The third is the `on_error:
  // route` port with nothing drawn from it - legal, and almost certainly not
  // what was meant. The fourth is what an IMPORTED graph looks like, because
  // `export.py` strips `server_id` and `skill_id` on purpose.
  'state-key-reserved', 'state-schema-invalid', 'error-port-unconnected',
  'attachment-reference-missing',
  // The SEVENTH warning, and decision 12 said out loud rather than by silence:
  // a registered crew builds its own LLMs in python, so the node's `tier` word
  // prices and bounds the graph and does not choose a model. The gauntlet's own
  // forbidden list names a parameter rendered in the UI that the compiler
  // ignores; this is that rule answered on the node.
  'crew-tier-not-honoured',
] as const
export type ProblemCode = (typeof PROBLEM_CODES)[number]

/**
 * The warnings; everything else is an error and blocks publish. Every one of
 * them describes a graph that is legal and probably not what was meant.
 *
 * COUNT IT, never copy it - the list has grown three times and the prose beside
 * it has been wrong twice:
 *   grep -c 'severity="warning"' src/brief_crew/builder/*.py
 *
 * `attachment-unattached` is the fourth, added with D2. It is a warning rather
 * than an error for a reason worth keeping: it is exactly what a node looks
 * like the moment it is dropped, and refusing it would mean an author cannot
 * put a tool on the canvas before deciding whose it is.
 */
export const WARNING_CODES = [
  'router-branch-unconnected', 'no-output-node', 'join-single-predecessor',
  'attachment-unattached',
  // The fifth, added 2026-09-04 with plan 07. A discovered MCP tool whose
  // description matched one of thirteen injection patterns: it warns rather
  // than errors because the list has false positives by design, and PLANS.md
  // decision 8 rules that the tool stays selectable with the warning shown.
  // Hiding it in the picker would be the quietly-divergent double this
  // repository keeps warning about.
  'mcp-tool-description-suspicious',
  // The sixth and seventh, added 2026-09-04 with plan 09. `error-port-
  // unconnected` is a graph that is legal and probably not what was meant - the
  // author asked for a recovery path and did not draw one. `crew-tier-not-
  // honoured` is a control that does real work in two places and not in the
  // third; refusing the document over it would refuse every registered crew.
  'error-port-unconnected', 'crew-tier-not-honoured',
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
  /**
   * WHICH CONTROL, when the code alone cannot say - C8's optional `field`,
   * requested by 04 D7.
   *
   * Three codes anchor to a field that varies with the document rather than
   * with the code: `model-lacks-capability` (the parameter the model cannot
   * honour), `state-schema-invalid` and `prompt-too-long`. `FIELD_CODES` holds
   * one string per code and cannot express any of them, so the server names the
   * control and `useBuilderProblems` prefers it. Absent on every problem from a
   * server that has not grown it, which is why the index falls back rather than
   * dropping the row.
   */
  field?: string | null
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
  // Plan 01 D10: a `credential_id` the caller's vault does not hold anchors to
  // the picker that chose it (`data-field="credential_id"` in the inspector).
  'credential-missing': 'credential_id',
  // 09-compiler.md's two with a fixed control. `on_error` is the switch that
  // grew the `error` port, so an unconnected one belongs beside it; `tier` is
  // decision 12's whole subject - the word that prices and bounds a registered
  // crew and does not choose its models.
  'error-port-unconnected': 'on_error',
  'crew-tier-not-honoured': 'tier',

  /*
   * 04 D7: every FD14 code with a FIXED field. The three whose field varies
   * with the document rather than with the code carry `field` on the payload
   * instead (C8) and are deliberately absent here - `model-lacks-capability`
   * blames `llm.response_format` on one node and `llm.reasoning_effort` on the
   * next, and one string cannot say both.
   *
   * `model-unknown` and `model-over-ceiling` ARE fixed: both are about the
   * model a node names, and `registry.py::_model_references` reports them for
   * `llm.model` and for `retry.fallback_model` alike - which is precisely why
   * those two ALSO carry `field`, and why the index prefers it when it is
   * there. The entry below is the honest fallback for a server that has not
   * grown the payload yet, and it points at the far commoner of the two.
   */
  'model-unknown': 'llm.model',
  'model-over-ceiling': 'llm.model',
  // 06: a tool node names a catalogue id and nothing else, so all three anchor
  // to one of its two controls.
  'tool-unknown': 'tool_id',
  'tool-credential-required': 'credential_id',
  // 07: which server, which of its tools, and whether any were picked at all.
  // `mcp-transport-disallowed` is a property of the SERVER record rather than
  // of this node's reference to it, so it anchors to the server row too.
  'mcp-server-unavailable': 'server_id',
  'mcp-transport-disallowed': 'server_id',
  'mcp-tool-unknown': 'tool_names',
  'mcp-no-tools-selected': 'tool_names',
  'mcp-tool-description-suspicious': 'tool_names',
  // 08: one code for absent, deleted and foreign, and one control to change.
  'skill-unknown': 'skill_id',
  // 03 D2's crew membership count. It is about the `member` edges, and the
  // control that shows them is the authored crew's read-only member list.
  'crew-members-out-of-range': 'members',
  /*
   * `tool-param-invalid` is deliberately absent. Its field is one of the
   * catalogue's own parameter names - `params.limit`, `params.formats` - which
   * varies per tool, so it is the fourth code that needs C8's `field` and the
   * fourth that must not be given a single wrong string here.
   */
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
  /**
   * The per-node breakdown - C5, requested by 04 D6, OWNED BY PLAN 09.
   *
   * OPTIONAL, and it is optional because plan 09 has not landed: today's
   * `budget.py::BudgetEstimate` carries the six whole-graph figures above and
   * no breakdown, so the inspector's per-node cost line renders when the key
   * arrives and is absent when it does not. That is the honest degradation -
   * computing the figure here instead would be a second estimator quietly
   * disagreeing with the one that enforces the ceiling (invariant 3), which is
   * exactly the shape of thing this repository keeps finding.
   *
   * `node_call_count` already exists server-side and is addressed by node id,
   * so the arithmetic 09 has to expose is arithmetic it already does.
   */
  per_node?: Record<string, { calls: number; usd: number }>
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
  /**
   * `BUILDER_MAX_PROMPT_CHARS` (4000) - what one authored prompt field may hold.
   *
   * Read by every `PromptField` in the authored-agent form rather than by a
   * constant here, per R6: a bound the client keeps its own copy of is a bound
   * that disagrees with the compiler after any server change, and the failure
   * mode is a 422 about a box the author was told was fine.
   */
  max_prompt_chars: number
  /** `BUILDER_MAX_NODE_RETRIES` (3) - the ceiling on `retry.max_retries`. */
  max_retries: number
}

/**
 * Everything the palette and the inspector are allowed to offer, served rather
 * than duplicated: a canvas offering a transform op the compiler does not have
 * is a 422 the author cannot act on, and a canvas missing one is a feature
 * nobody can reach.
 */
/**
 * One row of C2 v2's `tools` - 06's catalogue, verbatim, served rather than
 * duplicated.
 *
 * The palette's tool sub-list searches `label`, the pill renders it, and a
 * `credential_kind` is what tells an author this tool needs a key before it
 * will do anything. `params` is the tool's argument shape; the inspector that
 * renders it is 04's and 06's, not this plan's.
 */
export interface BuilderToolParam {
  name: string
  /**
   * The server's own words, not a mapping of them.
   *
   * `'integer'` and `'array'` were added 2026-09-04 when `builder/tools.py`
   * landed and this union was `'string' | 'number' | 'boolean' | 'json'`. The
   * catalogue declares `integer` for every bounded count and `array` for
   * `firecrawl_scrape`'s `formats`, and folding those into `number` and `json`
   * would have cost the inspector the two things it needs to draw a control -
   * that a count is whole, and that a list has a closed set of members.
   * `'number'` and `'json'` are kept because nothing has proved they are
   * unreachable.
   */
  type: 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'json'
  /**
   * Always false in today's catalogue, and that is a property rather than an
   * omission: every entry declares a default for every parameter, so there is
   * no configuration an author can leave incomplete. A parameter with no
   * sensible default would be a tool this product cannot offer with zero
   * configuration, which the idea-validator template depends on.
   */
  required: boolean
  default?: JsonScalar | JsonScalar[]
  min?: number
  max?: number
  /** For `'string'`, the values it may take; for `'array'`, its MEMBERS' set. */
  enum?: JsonScalar[]
  description?: string
}

export interface BuilderToolCatalogueEntry {
  tool_id: string
  /** What the palette's sub-list searches and what the pill shows. */
  label: string
  category: string
  description: string
  /** `config.py:CREDENTIAL_KINDS`, or null when the tool needs no key. */
  credential_kind: CredentialKind | null
  /** Which kinds this tool may hang off. */
  attaches_to: NodeKind[]
  params: BuilderToolParam[]

  /*
   * Everything below arrived with `builder/tools.py` on 2026-09-04 and is
   * OPTIONAL, so a fixture written against the earlier six fields still
   * type-checks. Each one answers a question the six could not.
   */

  /**
   * `web_search` is one tool over four providers, so which key it needs is a
   * function of a PARAMETER rather than a property of the entry. `{param, map}`,
   * and `credential_kind` is null whenever this is set.
   */
  credential_kind_by_param?: { param: string; map: Record<string, CredentialKind> } | null
  /**
   * The tool runs without a key and does better with one - GitHub
   * unauthenticated is a lower rate limit, not a refusal. The server does NOT
   * report `tool-credential-required` for these, so a card that showed the
   * amber "no key" chip on one would be inventing a problem.
   */
  credential_optional?: boolean
  /** Where the author reads about what this tool actually does. */
  docs_url?: string
  /** `builtin`, or `user` for one of the caller's own custom HTTP tools. */
  owner?: 'builtin' | 'user'
  /**
   * Whether THIS DEPLOYMENT can build it, which is not the same as whether the
   * catalogue describes it. `tavily-python` and `exa_py` ship separately and
   * neither is installed, so two of `web_search`'s four providers abort at run
   * time - and `TavilySearchTool`'s constructor asks, through `click.confirm`,
   * whether it should install itself. A picker that offered all four alike
   * would be offering two that cannot run.
   */
  available?: boolean
  /** The missing distributions, keyed by the `packages_param` value that needs them. */
  requires_packages?: Record<string, string[]>
  /** Which parameter chooses a row of `requires_packages`. Only `web_search` has one. */
  packages_param?: string | null
}

export interface BuilderVocabulary {
  schema_id: string
  /** ORDERED literals in the handler, deliberately not sorted. Render in this order. */
  node_kinds: NodeKind[]
  /**
   * C2 v2's tool catalogue, 06's to fill. OPTIONAL because this build's server
   * still serves the v1 envelope: the palette renders the sub-list when the key
   * is there and renders nothing extra when it is not, which is cut-list 17
   * applied honestly - a client-side catalogue would be a list of tools the
   * compiler has never heard of.
   */
  tools?: BuilderToolCatalogueEntry[]
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

/* --- the model registry, C3 ---------------------------------------------- */

/**
 * How fast a model answers, as a curated word rather than a measurement.
 *
 * The public catalogue publishes no throughput figure, so these three come from
 * the MCP's `sort: throughput-high-to-low` ordering and are a judgement the
 * roster's author made. A closed set so the picker can group on it without
 * inventing a fourth word.
 */
export type SpeedTier = 'fast' | 'balanced' | 'deep'

/**
 * One roster model - `data/models.json`, served by `GET /api/builder/models`.
 *
 * TWO PRICE COLUMNS, and rendering only one of them is the mistake this
 * registry exists to stop. `cost_in` is what a run is priced at: the plain
 * slug's headline, which is itself one of the endpoints serving it.
 * `cost_in_max_endpoint` is the DEAREST endpoint for the same slug, and it is
 * what says how much exposure `provider.max_price` is filtering away -
 * `google/gemini-3.8-flash` bills $0.75 on its headline and $1.35 on its two
 * `priority` endpoints. A picker that showed only the first would tell an
 * author the escalation preset costs $0.75 and never that its dearest route
 * would breach the product's own ceiling; one that showed only the second would
 * overstate every estimate on the page.
 */
export interface RegistryModel {
  /** A BASE slug: no `openrouter/` prefix and no `:variant`. */
  id: string
  /** The catalogue's own human name, e.g. `Google: Gemini 3.5 Flash Lite`. */
  name: string
  /** The slug's first segment - `google`, `openai`, `deepseek`. */
  provider: string
  context_window: number
  supports_tools: boolean
  supports_vision: boolean
  supports_json_mode: boolean
  supports_reasoning: boolean
  /** USD per MILLION prompt tokens, headline. */
  cost_in: number
  /** USD per MILLION completion tokens, headline. */
  cost_out: number
  /** USD per million prompt tokens on the dearest endpoint serving this slug. */
  cost_in_max_endpoint: number
  speed_tier: SpeedTier
  /** A closed list the picker groups on - `router`, `critic`, `default-cheap`. */
  recommended_for: string[]
}

/**
 * `GET /api/builder/models` - the roster, its ceiling and its two presets.
 *
 * `generated_at` and `source` travel with the rows because they are what a
 * stale client is diagnosed FROM. Comparing prices would only ever say that two
 * numbers differ; a date says which one is old.
 */
export interface ModelRoster {
  schema: string
  generated_at: string
  source: string
  /** USD per million input tokens. No roster model may exceed it. */
  ceiling_usd_per_m_input: number
  /**
   * Tier name to the id that tier resolves to, WITH its routing variant -
   * `google/gemini-3.5-flash-lite:nitro`. The variant is kept because it is the
   * reason the cheap preset's enforced price is above its headline: nitro
   * routes on speed, not price, so the published rate is a floor. Strip it to
   * look a row up; render it to explain the meter.
   */
  presets: Record<string, string>
  models: RegistryModel[]
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

/* --- credentials (plan 01, contract C4) ---------------------------------
 * The vault's API shape. `config.py:CREDENTIAL_FIELDS` is the ground truth for
 * the kinds and the field each one needs; `data/credentialKinds.ts` mirrors it
 * and says so. What is deliberately NOT here is any type carrying a field
 * VALUE on the way back: the server never returns one, and a client type that
 * had somewhere to put one would be the first step towards rendering it. */

/** `config.py:CREDENTIAL_KINDS`. */
export type CredentialKind =
  | 'openrouter' | 'firecrawl' | 'serper' | 'tavily' | 'exa' | 'brave'
  | 'github' | 'postgres' | 'http_header' | 'mcp_header' | 'e2b'

/**
 * One row of `GET /api/builder/credentials`, and what `POST` answers with 201.
 * Never a field - the list is what an author picks FROM, and the secret is
 * encrypted at rest and decrypted only inside a tool constructor at run time.
 */
export interface CredentialSummary {
  /** `CREDENTIAL_ID_PATTERN`. */
  id: string
  kind: CredentialKind
  /** 1..80, unique per user. What the picker shows. */
  label: string
  created_at: string
  updated_at: string
  /** Written by `resolve_credential` on every run-time use; null until then. */
  last_used_at: string | null
}

/* --- the attachment stores, C11 and C12 ---------------------------------- */

/**
 * One tool an MCP server offered, after the server sanitised it.
 *
 * `suspicious` is the one field worth pausing on. A tool description lands
 * verbatim in an agent's tool list, which is a prompt written by a third party,
 * so discovery tests every description against thirteen injection patterns and
 * marks a match. **The tool is still listed and still selectable** (PLANS.md
 * decision 8): the patterns have false positives by design - `act as` is
 * ordinary English - and a picker that quietly dropped rows would be the
 * quietly-divergent double this repository keeps warning about. The author sees
 * `matched_pattern` and decides.
 */
export interface McpDiscoveredTool {
  name: string
  description: string
  /** The tool's own JSON Schema, rendered read-only as a parameter preview. */
  input_schema: Record<string, unknown>
  suspicious: boolean
  matched_pattern: string | null
}

/**
 * One row of `GET /api/builder/mcp/servers`.
 *
 * `url` arrives MASKED - origin plus `/************` - and there is no
 * unmasked form on this side. Plenty of hosted MCP servers put a token in the
 * path, so a panel that showed the whole URL would publish a credential to
 * anybody who could see the screen. The two `has_*_credential` booleans are the
 * same principle: whether a key is attached is a fact the panel needs, and
 * which key it is belongs to the credential picker.
 */
export interface McpServerRow {
  /** `MCP_SERVER_ID_PATTERN` - `ms_` + 12 hex. */
  id: string
  label: string
  transport: 'http' | 'sse' | 'stdio'
  /** Masked. Null for a stdio server. */
  url: string | null
  command: string | null
  args: string[]
  has_header_credential: boolean
  has_env_credential: boolean
  /** `pending` until a discovery has run, then `authorized` or `error`. */
  status: 'pending' | 'authorized' | 'error'
  /** No discovery yet, or one older than `MCP_DISCOVERY_STALE_SECONDS` (a day). */
  stale: boolean
  tools: McpDiscoveredTool[]
  discovered_at: string | null
  /** One sentence. What the panel shows instead of a stack trace. */
  last_error: string | null
}

/** What `POST`/`PUT /api/builder/mcp/servers` takes. Credentials travel as ids. */
export interface McpServerDraft {
  label: string
  transport: 'http' | 'sse' | 'stdio'
  url?: string | null
  command?: string | null
  args?: string[]
  header_credential_id?: string | null
  env_credential_id?: string | null
}

/** What `POST .../discover` answers with, whether it worked or not. */
export interface McpDiscovery {
  status: 'pending' | 'authorized' | 'error'
  tools: McpDiscoveredTool[]
  discovered_at: string | null
  error: string | null
}

/**
 * One row of `GET /api/builder/skills`, WITHOUT the body.
 *
 * Thirty packs at 64 KiB each is two megabytes of JSON to draw a palette, so
 * the list carries the frontmatter and `GET /api/builder/skills/{id}` carries
 * the pack. `owner` is `builtin` for the four this repository ships - visible
 * to everybody, editable by nobody - and `me` for the caller's own.
 */
export interface SkillSummary {
  /** `SKILL_ID_PATTERN` - `sk_` + 12 hex. */
  id: string
  /** The frontmatter name, which is also the directory name. */
  name: string
  description: string
  /** `metadata.version` in the frontmatter, which is where it lives. */
  version: number
  owner: 'builtin' | 'me'
  size_bytes: number
  updated_at: string | null
}

/** A pack with its `SKILL.md` text. Rendered through the escape-first renderer. */
export interface SkillDetail extends SkillSummary {
  body: string
}

/** One typed argument of a custom HTTP tool - Flowise's grid, minus the function. */
export interface CustomToolProperty {
  name: string
  type: 'string' | 'integer' | 'number' | 'boolean'
  description: string
  required: boolean
}

/**
 * The request template that replaces Flowise's JavaScript `func`.
 *
 * A function stored per user is an evaluation surface; a template is a shape.
 * `{placeholders}` name declared properties and are URL-encoded on the way in;
 * `{credential}` is the header credential's value and never leaves the server.
 */
export interface CustomToolRequest {
  method: 'GET' | 'POST'
  url: string
  header_name: string | null
  header_template: string | null
  body_template: string | null
  timeout_seconds: number
  max_response_bytes: number
}

/** One row of the caller's own custom HTTP tools. */
export interface CustomToolRow {
  /** `CUSTOM_TOOL_ID_PATTERN` - `ut_` + 12 hex. This is the document's `tool_id`. */
  id: string
  name: string
  description: string
  properties: CustomToolProperty[]
  request: CustomToolRequest
  credential_id: string | null
  /** The catalogue row it appears as, for its owner only. */
  entry: BuilderToolCatalogueEntry
}

/**
 * The body of `POST`/`PUT /api/builder/tools/custom`. The same shape the row
 * carries, minus the server's own id and derived entry.
 */
export interface CustomToolDraft {
  name: string
  description: string
  properties: CustomToolProperty[]
  request: CustomToolRequest
  credential_id?: string | null
}

/**
 * The body of `POST /api/builder/credentials`. The ONLY place a field value
 * exists on this side is inside this object, on its way out.
 */
export interface CredentialDraft {
  kind: CredentialKind
  label: string
  fields: Record<string, string>
}

/**
 * `POST /api/builder/credentials/{id}/test`. `detail` is the provider's own
 * sentence, or the vault's when a kind has no free probe (Firecrawl has no
 * authenticated read that costs nothing, so its probe is a format check and
 * says so). Never a stack trace.
 */
export interface CredentialProbe {
  ok: boolean
  detail: string
}

/* --- export, import, versions (plan 15) ---------------------------------
 * The lifecycle the builder was missing: a document as a FILE, a file as a
 * new draft, a copy, and the list of stored versions. Every shape here is the
 * plan's contract as written on 2026-09-02, built against fakes on this side
 * and against `builder_api.py` on the other; the Integrator reconciles the two
 * the way `tests/builderApi.spec.ts` reconciles the route table. */

/**
 * The `export` values an import accepts.
 *
 * Ruling S1-4: the field carries the document's OWN `schema`, so today every
 * file says `builder.flow/v1`, and the importer already admits the v2 spelling
 * C1 will introduce because the server passes the document through
 * `upgrade_document` on the way in. Checked client-side so a file that is not
 * an export at all - a run log, a clipboard envelope, somebody's `package.json`
 * - is refused with a sentence naming the FILE, rather than sent to
 * `POST /import` for a 422 about a field the author never typed.
 */
export const EXPORT_SCHEMAS = ['builder.flow/v1', 'builder.flow/v2'] as const
export type ExportSchema = (typeof EXPORT_SCHEMAS)[number]

/** `GET /workflows/{id}/export` - plan 15 D1, `builder/export.py::strip_for_export`. */
export interface BuilderExportEnvelope {
  export: ExportSchema
  /** ISO. */
  exported_at: string
  name: string
  /** The stored version the file was taken from. */
  source_version: number
  /** Node ids whose `credential_id` was nulled on the way out. */
  needs_credentials: string[]
  /**
   * The stripped document: no `id`, `version`, `budget` or `user_id`, every
   * secret-bearing field null. Carried as the wire shape rather than as a
   * `BuilderDocument`, because the importer mints its own identity and this
   * client never parses it - the file round-trips, it is not edited here.
   */
  document: Record<string, unknown>
}

/**
 * `POST /workflows/import` - the create model, plus the nodes that arrived
 * without a credential. Ruling S1-7: that list is rendered as a client-side
 * notice, never as a C8 problem code.
 */
export interface BuilderImportResult extends BuilderDocumentModel {
  needs_credentials: string[]
}

/** One row of `GET /workflows/{id}/versions`, which answers newest first. */
export interface BuilderVersionRow {
  version: number
  status: DocumentStatus
  created_at: string
  /** The stored JSON's size, for the browser's one number about weight. */
  bytes: number
  /**
   * How the row came to be (round 2, D-15-3): `created`, `saved`, `autosaved`,
   * `restored from v3`, `imported`, `duplicated`, or `stored` for a row older
   * than the column. Composed by the server from what this client declares on
   * a save - see `SaveOptions`.
   */
  source: string
  /** The document's name at that version, read leniently off the row; null if it has none. */
  name: string | null
  /** How many nodes that version has; null when the row could not say. */
  node_count: number | null
}

/** What a save may declare about itself, for the version browser's `source`. */
export type SaveSource = 'save' | 'autosave' | 'restore'
