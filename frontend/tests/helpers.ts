import { createApp, type App } from 'vue'
import { MOCK_GRAPH } from '../src/data/mockGraph'
import { BuilderConflictError, type BuilderApiLike } from '../src/services/builderApi'
import type { LogFormat, StreamHandlers, StudioApiLike, TransportMode } from '../src/services/studioApi'
import {
  BUILDER_SCHEMA_ID,
  documentId,
  edgeId,
  nodeId,
  type BuilderBudget,
  type BuilderDocument,
  type BuilderDocumentModel,
  type BuilderDocumentSummary,
  type BuilderEdge,
  type BuilderNode,
  type BuilderProblem,
  type BuilderPublish,
  type BuilderValidation,
  type BuilderVocabulary,
  type DocumentId,
} from '../src/types/builder'
import type {
  FrameData,
  FrameKind,
  GateReply,
  GraphDescriptor,
  GraphNodeDefinition,
  RunSnapshot,
  StartRunResponse,
  UsageMetrics,
  RunHistoryEntry,
} from '../src/types/studio'
import problemCodeFixture from './fixtures/builderProblemCodes.json'

export const RUN_ID = 'run-under-test'

/**
 * Runs a composable inside a real component instance so `onBeforeUnmount`
 * (and therefore the timer teardown path) actually fires when we unmount.
 */
export function withSetup<T>(composable: () => T): [T, App] {
  let result!: T
  const app = createApp({
    setup() {
      result = composable()
      return () => null
    },
  })
  app.mount(document.createElement('div'))
  return [result, app]
}

/** Drains the composable's promise-chained frame queue. */
export async function flush(ticks = 8): Promise<void> {
  for (let index = 0; index < ticks; index += 1) await Promise.resolve()
}

export const zeroUsage = (): UsageMetrics => ({
  promptTokens: 0,
  completionTokens: 0,
  totalTokens: 0,
  callCount: 0,
  costUsd: 0,
  elapsedMs: 0,
})

export function emptySnapshot(runId = RUN_ID, status: RunSnapshot['status'] = 'running'): RunSnapshot {
  return {
    run_id: runId,
    status,
    pending_gate: null,
    frames: { count: 0, dropped: 0, first_seq: null, last_seq: null },
    usage: zeroUsage(),
  }
}

/**
 * Deterministic stand-in for the transport. Nothing here touches a socket, a
 * server or a clock, so every composable test is no-cost and repeatable.
 */
export class FakeStudioApi implements StudioApiLike {
  mode: TransportMode = 'live'
  /** Null means "the probe reached a real backend", which is this double's default. */
  probeFailure: string | null = null
  /** The server's sentence when a real backend refused the probe (D-01-2). */
  probeRefusal: string | null = null
  graph: GraphDescriptor = structuredClone(MOCK_GRAPH)
  snapshot: RunSnapshot = emptySnapshot()
  storedFrames: FrameData[] = []
  handlers: StreamHandlers | null = null
  subscribeCalls: Array<{ runId: string; after: number }> = []
  unsubscribeCount = 0
  gateReplies: Array<{ runId: string; gateId: string; reply: GateReply }> = []
  cancelled: string[] = []
  downloaded: Array<{ runId: string; format: LogFormat }> = []
  getRunError: Error | null = null
  runIdToIssue = RUN_ID

  async initialize(): Promise<TransportMode> {
    return this.mode
  }

  async getGraph(): Promise<GraphDescriptor> {
    return structuredClone(this.graph)
  }

  startRunCalls: Array<{ idea: string; workflowId: string; gates: string }> = []

  async startRun(
    _sessionId: string,
    idea: string,
    workflowId = 'idea-validator',
    gates = 'human',
  ): Promise<StartRunResponse> {
    this.startRunCalls.push({ idea, workflowId, gates })
    return { run_id: this.runIdToIssue, status: 'queued', graph_version: this.graph.version }
  }

  async getRun(id: string): Promise<RunSnapshot> {
    if (this.getRunError) throw this.getRunError
    return { ...this.snapshot, run_id: id }
  }

  async getFrames(_id: string, after: number): Promise<FrameData[]> {
    return this.storedFrames.filter((frame) => frame.seq > after)
  }

  /**
   * The history the double will report, and a record of who asked.
   *
   * Present because `StudioApiLike` requires it, and `StudioApiLike` requires
   * it on purpose: the real client gained `listRuns` and the compiler refused
   * this class until it did too. That is the mechanism CLAUDE.md's closed items
   * 15 and 33 both describe - a double that quietly diverges from its subject
   * certifies nothing, and here the divergence could not stay quiet.
   */
  historyRuns: RunHistoryEntry[] = []
  listRunsCalls: number[] = []

  async listRuns(limit = 25): Promise<RunHistoryEntry[]> {
    this.listRunsCalls.push(limit)
    return this.historyRuns.slice(0, limit)
  }

  subscribe(runIdValue: string, _sessionId: string, handlers: StreamHandlers): () => void {
    this.handlers = handlers
    this.subscribeCalls.push({ runId: runIdValue, after: handlers.getAfter() })
    handlers.onStatus('connected')
    return () => {
      this.unsubscribeCount += 1
      if (this.handlers === handlers) this.handlers = null
      handlers.onStatus('offline')
    }
  }

  async replyGate(runIdValue: string, gateId: string, reply: GateReply): Promise<void> {
    this.gateReplies.push({ runId: runIdValue, gateId, reply })
  }

  async cancelRun(runIdValue: string): Promise<void> {
    this.cancelled.push(runIdValue)
  }

  async downloadLogs(runIdValue: string, format: LogFormat = 'ndjson'): Promise<void> {
    this.downloaded.push({ runId: runIdValue, format })
  }

  /** Pushes a frame down the same path the live socket uses. */
  emit(frame: FrameData): void {
    this.handlers?.onFrame(frame)
  }
}

/**
 * Builds gap-free frame sequences; each factory owns its own counter.
 *
 * `event_type` defaults to a value that is deliberately *not* a `UIEventType`:
 * every test that cares about the event type overrides it with the real one,
 * and a caller that leaves the default is stating it does not care. Real-looking
 * defaults are what let this suite assert against a fiction for so long - the
 * frames here used to claim `RUN_COMPLETED` and `EDGE_TRAVERSED`, names no
 * server has ever sent.
 */
export function frameFactory(runId = RUN_ID) {
  let seq = 0
  return function build(kind: FrameKind, overrides: Partial<FrameData> = {}): FrameData {
    seq += 1
    const base: FrameData = {
      v: 1,
      seq,
      run_id: runId,
      ts: new Date(1_750_000_000_000 + seq * 1000).toISOString(),
      kind,
      event_type: 'EVENT',
      level: 'INFO',
      message: `${kind} frame ${seq}`,
      details: {},
    }
    return { ...base, ...overrides }
  }
}

export function edgeFrame(
  build: ReturnType<typeof frameFactory>,
  from: string,
  to: string,
): FrameData {
  return build('edge_taken', { event_type: 'EDGE_PROCESS', details: { from, to } })
}

/* ======================================================================== *
 *  Flow builder                                                            *
 * ======================================================================== */

/**
 * The shape `builderProblemCodes.json` is emitted in.
 *
 * Declared rather than inferred from the import, because `resolveJsonModule`
 * widens `severity` to `string` and narrows `node_id` only by accident of the
 * values that happen to be in the file today. A fixture whose every anchor was
 * non-null would silently type as `string`, and the first test to handle a
 * document-level problem would stop compiling for a reason nobody could read.
 */
export interface ProblemFixtureInstance {
  code: string
  scenario: string
  why: string
  problem: BuilderProblem
}

interface ProblemFixture {
  codes: string[]
  instances: ProblemFixtureInstance[]
  /** The wire document each scenario ran over, keyed by scenario name. */
  documents: Record<string, unknown>
}

const PROBLEM_FIXTURE = problemCodeFixture as unknown as ProblemFixture

/**
 * The vocabulary `GET /api/builder/vocabulary` serves from this build.
 *
 * Restated here rather than fetched, the way `data/serverLimits.ts` restates
 * `MAX_RUN_INPUT_CHARS` - and with the same guard, which is the only thing that
 * makes restating it defensible: `tests/clientMirrors.spec.ts` reads
 * `config.py` and `builder_api.py` and asserts every value below still agrees.
 * A bound that moves on the server is then a failing test naming the bound,
 * rather than a palette quietly offering a ninth iteration the compiler refuses.
 *
 * `bounds` values arrive from the server as JSON floats (`24.0`), and every
 * count is written here as an integer because that is what `readBounds` hands
 * back after `Math.trunc`. The one exception is `run_cost_ceiling_usd`, which
 * is dollars and is deliberately NOT truncated on either side.
 */
export function vocabularyFixture(
  overrides: Partial<BuilderVocabulary> = {},
): BuilderVocabulary {
  return {
    schema_id: BUILDER_SCHEMA_ID,
    // Handler order, NOT sorted. `builder_api.py::_vocabulary` writes these as
    // literals and the palette renders them in the order it is given, so
    // sorting here would be testing a palette nobody ships.
    node_kinds: ['input', 'agent', 'crew', 'gate', 'router', 'transform', 'output'],
    tiers: ['cheap', 'escalation'],
    agent_ids: [
      'feasibility_analyst',
      'market_analyst',
      'reporter',
      'scoper',
      'sentiment_analyst',
      'synthesist',
    ],
    // The BUILDABLE crews only. `synthesis` and `report` are registered and are
    // refused by `library_problems`, so the server does not offer them here
    // either - a picker that did would advertise a document that publishes
    // clean and then raises a bare TypeError at the first paid run.
    crew_ids: ['feasibility', 'market', 'scope', 'sentiment'],
    research_tools: [
      'analyze_community_sentiment',
      'assess_technical_feasibility',
      'research_market_landscape',
    ],
    transform_ops: ['default', 'format', 'join_text', 'merge', 'pick', 'to_json'],
    router_comparisons: ['contains', 'eq', 'gt', 'gte', 'lt', 'lte', 'ne'],
    router_otherwise: 'otherwise',
    result_body_keys: ['markdown_body'],
    bounds: {
      max_graph_nodes: 24,
      max_billable_nodes: 13,
      max_escalation_nodes: 8,
      max_fanout_width: 4,
      min_router_branches: 2,
      max_cycles: 3,
      max_cycle_iterations: 3,
      max_agent_iter: 8,
      max_guardrail_retries: 2,
      max_label_chars: 40,
      max_name_chars: 80,
      max_gate_message_chars: 2000,
      max_input_chars: 2000,
      max_document_bytes: 262144,
      run_cost_ceiling_usd: 10,
    },
    ...overrides,
  }
}

/** A budget with every field at zero - the answer for a graph with no billable node. */
export function zeroBudget(overrides: Partial<BuilderBudget> = {}): BuilderBudget {
  return {
    static_cost_usd: 0,
    floor_cost_usd: 0,
    modelled_calls: 0,
    billable_nodes: 0,
    escalation_nodes: 0,
    cycles: 0,
    unpriced_models: [],
    over_ceiling: false,
    ceiling_usd: 10,
    ...overrides,
  }
}

/**
 * A parseable, empty draft: one the server would store and refuse to publish.
 *
 * `id` is present and shaped like a server-assigned one even though nothing has
 * been saved. `BuilderDocument.id` is not nullable on the wire - the server
 * overwrites it on every write and `forValidate` deletes it before sending - so
 * a helper returning `null` here would model a document state that cannot
 * exist, and every consumer would need a cast to use it.
 */
export function emptyDocument(overrides: Partial<BuilderDocument> = {}): BuilderDocument {
  return {
    schema: BUILDER_SCHEMA_ID,
    id: documentId('ug_00000001'),
    name: 'Untitled graph',
    version: 1,
    input_field: nodeId('idea'),
    nodes: [],
    edges: [],
    joins: {},
    // Always null on the way out. The compiler writes this block; a client that
    // sent one back would be asserting a price it did not compute.
    budget: null,
    ...overrides,
  }
}

/**
 * A REAL document and the REAL problems the server found in it.
 *
 * Both halves come out of `builderProblemCodes.json`, which
 * `scripts/emit_builder_fixtures.py` generates by running
 * `compiler.document_problems` over each scenario. Nothing here is written by
 * hand, and that is the point: a problem's `message` is rendered verbatim by
 * three surfaces and its `node_id` is what `fitView` centres on, so a
 * hand-written double would let a test pass over a sentence and an anchor no
 * server has ever produced. This repository has shipped that defect twice
 * already (closed items 20 and 33).
 *
 * The default scenario is the five-branch router, chosen because it is the one
 * carrying an error and a warning against the SAME node - which is what
 * `worstByNode` exists to resolve and what a single-severity fixture cannot
 * test. Pass a code to get the scenario that produced that code instead.
 *
 * `document` is the wire shape (`schema`, not `documentSchema`) exactly as the
 * generator fed it to the compiler, cast rather than re-derived: re-deriving it
 * would be a second answer to the question of what the server actually saw.
 */
export function docWithProblems(code?: string): {
  document: BuilderDocument
  problems: BuilderProblem[]
  scenario: string
} {
  const anchor = code ?? 'router-branch-count'
  const instance = PROBLEM_FIXTURE.instances.find((entry) => entry.code === anchor)
  if (!instance) {
    throw new Error(
      `builderProblemCodes.json carries no instance of ${anchor}; the emitter ` +
        'refuses to write an incomplete fixture, so this is a misspelt code',
    )
  }
  const scenario = instance.scenario
  return {
    document: PROBLEM_FIXTURE.documents[scenario] as BuilderDocument,
    problems: PROBLEM_FIXTURE.instances
      .filter((entry) => entry.scenario === scenario)
      .map((entry) => entry.problem),
    scenario,
  }
}

/** Every problem instance in the fixture: exactly one per code the server can emit. */
export function everyProblemInstance(): ProblemFixtureInstance[] {
  return PROBLEM_FIXTURE.instances.map((entry) => ({ ...entry }))
}

/** The descriptor kind the service derives for each builder kind. */
const DESCRIPTOR_KIND: Record<string, GraphNodeDefinition['kind']> = {
  input: 'start',
  agent: 'agent',
  crew: 'agent',
  gate: 'gate',
  router: 'router',
  transform: 'step',
  output: 'output',
}

/**
 * A `GraphDescriptor` derived from the document, the way `descriptor.py` does.
 *
 * Derived rather than canned. `BuilderDocumentModel.graph` is what the console
 * draws, and a double returning a fixed descriptor would let a test save one
 * document and then assert against a topology with nothing to do with it - the
 * divergence invisible precisely because both halves are individually
 * plausible.
 */
export function descriptorFor(doc: BuilderDocument): GraphDescriptor {
  return {
    id: doc.id,
    name: doc.name,
    version: `v${doc.version}`,
    start_nodes: doc.nodes.filter((node) => node.kind === 'input').map((node) => node.id),
    nodes: doc.nodes.map((node) => ({
      id: node.id,
      label: node.label,
      kind: DESCRIPTOR_KIND[node.kind] ?? 'step',
      description: '',
      eyebrow: node.kind.toUpperCase(),
      position: { ...node.position },
    })),
    edges: doc.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.source_port === 'out' ? null : edge.source_port,
    })),
  }
}

/** A validate answer over `problems`, with `valid` derived the way the server derives it. */
export function validationFor(
  problems: BuilderProblem[] = [],
  budget: BuilderBudget = zeroBudget(),
): BuilderValidation {
  return {
    // `valid === problems.every(p => p.severity !== 'error')`, derived rather
    // than passed in, so a caller cannot hand this double a clean flag over an
    // error list and then test a state the server never produces.
    valid: problems.every((problem) => problem.severity !== 'error'),
    problems,
    budget,
  }
}

/** One row of the fake store: a document at a version, with its status. */
interface StoredDocument {
  document: BuilderDocument
  status: BuilderDocumentModel['status']
  version: number
  createdAt: string
  updatedAt: string
  published: boolean
}

/**
 * Deterministic stand-in for `BuilderApi`, with a real optimistic-concurrency
 * store behind it.
 *
 * `implements BuilderApiLike` is the load-bearing part of the declaration.
 * `BuilderApiLike` is a `Pick` of the class, so adding a method to the real
 * client makes this file stop compiling until it is added here too. That is the
 * only mechanism that has ever kept a double in this repository honest - the
 * two times it was absent, a double diverged and certified nothing (closed
 * items 20 and 33).
 *
 * The version counter is REAL rather than canned, because `expected_version` is
 * the whole of the conflict story: `save` compares, bumps and answers, and a
 * `save` that always succeeded would leave `ConflictDialog` untestable and the
 * 409 path dead on the free side - which is exactly how
 * `SyntheticValidatorRunner`'s missing revise branch left two edges unexercised
 * for a month.
 */
export class FakeBuilderApi implements BuilderApiLike {
  /** Stored documents by id. Seed it directly, or let `create` fill it. */
  readonly store = new Map<string, StoredDocument>()

  /** What `validate` answers unless a deferral is armed. */
  validation: BuilderValidation = validationFor()

  /** What `publish` answers. Overwrite for the `gated_before_spend: false` case. */
  publishResult: BuilderPublish | null = null

  /** Errors to throw instead of answering, keyed by method name. */
  readonly failWith: Partial<Record<keyof BuilderApiLike, Error>> = {}

  listCalls: Array<number | undefined> = []
  createCalls: BuilderDocument[] = []
  getCalls: Array<{ id: string; version: number | undefined }> = []
  saveCalls: Array<{ id: string; doc: BuilderDocument; expectedVersion: number }> = []
  removeCalls: string[] = []
  validateCalls: Array<{ doc: BuilderDocument; signal: AbortSignal | undefined }> = []
  publishCalls: Array<{ id: string; version: number | undefined }> = []

  /**
   * While true, `validate` returns a promise nobody has settled.
   *
   * The out-of-order case cannot be tested without it. `useBuilderValidation`
   * stamps every response with the fingerprint it answered and drops a stale
   * one, and proving that needs two requests in flight at once with the FIRST
   * settling last - which an immediately-resolving double cannot produce at any
   * ordering of awaits.
   */
  deferValidate = false

  private readonly deferred: Array<(value: BuilderValidation) => void> = []
  private nextId = 1

  /** Settle the `index`-th deferred validate. Defaults to the oldest. */
  settleValidate(value: BuilderValidation, index = 0): void {
    const resolve = this.deferred[index]
    if (!resolve) throw new Error(`no deferred validate at index ${index}`)
    this.deferred.splice(index, 1)
    resolve(value)
  }

  /** How many validate calls are still unsettled. */
  get pendingValidates(): number {
    return this.deferred.length
  }

  /**
   * Put a document in the store at a version, as though it had been saved.
   *
   * `updatedAt` is a parameter because the saved-graphs library orders by it
   * (D-15-15) and every row otherwise carries the same fixed stamp, which
   * would make an ordering assertion true by accident.
   */
  seed(
    doc: BuilderDocument,
    version = 1,
    status: BuilderDocumentModel['status'] = 'draft',
    updatedAt?: string,
  ): DocumentId {
    const stamp = new Date(1_750_000_000_000).toISOString()
    this.store.set(doc.id, {
      document: { ...doc, version },
      status,
      version,
      createdAt: stamp,
      updatedAt: updatedAt ?? stamp,
      published: status === 'published',
    })
    return doc.id
  }

  async list(limit?: number): Promise<BuilderDocumentSummary[]> {
    this.listCalls.push(limit)
    this.refuse('list')
    const rows = [...this.store.entries()].map(([id, row]) => ({
      id,
      name: row.document.name,
      version: row.version,
      status: row.status,
      created_at: row.createdAt,
      updated_at: row.updatedAt,
    }))
    return limit === undefined ? rows : rows.slice(0, limit)
  }

  async create(doc: BuilderDocument): Promise<BuilderDocumentModel> {
    this.createCalls.push(doc)
    this.refuse('create')
    // The server assigns the id and the version on every write, so this double
    // overwrites both rather than echoing what it was sent. A client that read
    // its own `doc.id` back would look correct here and be wrong in production.
    const id = documentId(`ug_${this.nextId.toString(16).padStart(8, '0')}`)
    this.nextId += 1
    this.seed({ ...doc, id, version: 1 }, 1)
    return this.model(id)
  }

  async get(id: string, version?: number): Promise<BuilderDocumentModel> {
    this.getCalls.push({ id, version })
    this.refuse('get')
    return this.model(id, version)
  }

  async save(
    id: string,
    doc: BuilderDocument,
    expectedVersion: number,
  ): Promise<BuilderDocumentModel> {
    this.saveCalls.push({ id, doc, expectedVersion })
    this.refuse('save')
    const row = this.require(id)
    if (row.version !== expectedVersion) {
      // The server's own sentence, verbatim, because `BuilderConflictError`
      // parses the stored version back OUT of it - a double with a friendlier
      // message would leave `storedVersion` null and exercise the fallback path
      // on every test instead of the one it is meant to.
      throw new BuilderConflictError(
        `document ${id} is at version ${row.version}, not ${expectedVersion}; ` +
          'reload it before saving again',
        row.version,
      )
    }
    const version = row.version + 1
    row.document = { ...doc, id: documentId(id), version }
    row.version = version
    row.updatedAt = new Date(1_750_000_000_000 + version * 1000).toISOString()
    return this.model(id)
  }

  async remove(id: string): Promise<void> {
    this.removeCalls.push(id)
    this.refuse('remove')
    this.require(id)
    this.store.delete(id)
  }

  async validate(doc: BuilderDocument, signal?: AbortSignal): Promise<BuilderValidation> {
    this.validateCalls.push({ doc, signal })
    this.refuse('validate')
    if (!this.deferValidate) return this.validation
    return new Promise<BuilderValidation>((resolve, reject) => {
      this.deferred.push(resolve)
      // The abort must REJECT, not resolve with something stale. An
      // `AbortController` is how the composable cancels a superseded request,
      // and a double that resolved an aborted promise would let a stale answer
      // reach the reducer by a route the real client cannot take.
      signal?.addEventListener('abort', () => {
        const index = this.deferred.indexOf(resolve)
        if (index >= 0) this.deferred.splice(index, 1)
        reject(new DOMException('Aborted', 'AbortError'))
      })
    })
  }

  async publish(id: string, version?: number): Promise<BuilderPublish> {
    this.publishCalls.push({ id, version })
    this.refuse('publish')
    const row = this.require(id)
    row.status = 'published'
    row.published = true
    return (
      this.publishResult ?? {
        workflow_id: id,
        graph_version: '0123456789abcdef',
        version: row.version,
        input_field: row.document.input_field,
        static_cost_usd: this.validation.budget.static_cost_usd,
        gated_before_spend: true,
        reserved_input_keys: ['no_gates', 'sequential_branches'],
      }
    )
  }

  private refuse(method: keyof BuilderApiLike): void {
    const error = this.failWith[method]
    if (error) throw error
  }

  private require(id: string): StoredDocument {
    const row = this.store.get(id)
    if (!row) throw new Error(`no document ${id}`)
    return row
  }

  private model(id: string, version?: number): BuilderDocumentModel {
    const row = this.require(id)
    const document = version === undefined ? row.document : { ...row.document, version }
    return {
      id,
      document,
      status: row.status,
      version: document.version,
      head_version: row.version,
      created_at: row.createdAt,
      updated_at: row.updatedAt,
      problems: this.validation.problems,
      budget: this.validation.budget,
      graph: descriptorFor(document),
      published: row.published,
    }
  }
}

/**
 * A node with a legal id, a legal label and the config its kind requires.
 *
 * The cast at the end rather than a per-kind switch: this is a test factory
 * whose caller states the pairing, and the seven-way switch that PROVES the
 * pairing lives in `builderDefaults.newNode`, which is the production path and
 * is tested as one.
 */
export function builderNode(
  id: string,
  kind: BuilderNode['kind'],
  config: BuilderNode['config'],
  position: { x: number; y: number } = { x: 0, y: 0 },
): BuilderNode {
  return { id: nodeId(id), kind, label: id, position, config } as BuilderNode
}

/** An edge from `source`'s `port` to `target`'s only inbound port. */
export function builderEdge(
  id: string,
  source: string,
  target: string,
  port = 'out',
): BuilderEdge {
  return {
    id: edgeId(id),
    source: nodeId(source),
    source_port: port,
    target: nodeId(target),
    target_port: 'in',
  }
}
