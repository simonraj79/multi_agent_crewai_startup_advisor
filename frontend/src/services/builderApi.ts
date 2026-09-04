import { readErrorDetail, retryAfterSentence } from '../data/serverLimits'
import type {
  BuilderDocument,
  BuilderDocumentModel,
  BuilderDocumentSummary,
  BuilderExportEnvelope,
  BuilderImportResult,
  BuilderProblem,
  BuilderPublish,
  BuilderValidation,
  BuilderVersionRow,
  CompiledPreview,
  DryRunResult,
  RunMode,
  RunStateResult,
  SaveSource,
  TestInput,
  TestInputDraft,
  CredentialDraft,
  CredentialProbe,
  CredentialSummary,
} from '../types/builder'
import type {
  FrameData,
  GateReply,
  GraphDescriptor,
  RunHistoryEntry,
  RunSnapshot,
  StartRunResponse,
} from '../types/studio'
import type {
  GatesMode,
  LogFormat,
  StreamHandlers,
  StudioApiLike,
  TransportMode,
} from './studioApi'
import { studioApi } from './studioApi'
import { forValidate, toWire } from '../utils/builderSerialize'
import { authedFetch, fetchJson } from './httpCore'

/**
 * Every call `/api/builder/*` accepts, and the three refusals peculiar to it.
 *
 * A separate client from `StudioApi` rather than more methods on it, for the
 * reason `builder_api.py` gives for being a separate router: nothing here runs
 * a flow, and the run surface's transport probe, mock fallback and socket
 * lifecycle have no meaning for a document. The two share `httpCore`, which is
 * where the bearer token and the 401 retry live, and nothing else.
 *
 * There is deliberately NO mock transport here. `StudioApi` has one because a
 * visitor with no backend should still see what a run looks like; a builder
 * with a fabricated document would be an author editing a graph that cannot be
 * saved - the silent-mock defect (gotchas 2) pointed at the one surface where
 * the author's own work is what gets lost.
 */

/**
 * The router prefix. `BUILDER_API_PREFIX` - `src/brief_crew/service/builder_api.py`.
 *
 * Restated here the way `data/serverLimits.ts` restates `MAX_RUN_INPUT_CHARS`,
 * and for the same reason: duplicated constants drift, so
 * `tests/builderApi.spec.ts` reads the Python and asserts the two agree rather
 * than trusting this comment.
 */
export const BUILDER_API_PREFIX = '/api/builder'

/**
 * The stored version was not the one the author was editing.
 *
 * Typed rather than a bare `Error` because a 409 is the one refusal on this
 * router with a *resolution* attached: `ConflictDialog` re-GETs the version
 * named here and shows the author what changed. A message string cannot be
 * re-fetched.
 *
 * `storedVersion` is parsed out of the server's own sentence -
 * `document ug_0a1b2c3d is at version 8, not 7; reload it before saving again`
 * (`builder/store.py::DocumentVersionConflict`) - because the transport sends
 * `str(exc)` and there is no structured field to read. It is `null` when the
 * sentence does not match, and the caller must handle that: re-GETting head
 * with no version at all answers the same question, so a parse failure costs
 * one extra request rather than reaching a dead end.
 */
/** How a save came about, for the version browser (D-15-3). */
export interface SaveOptions {
  source?: SaveSource
  /** With `source: 'restore'`: the version that was put back. */
  restoredFrom?: number
}

export class BuilderConflictError extends Error {
  readonly name = 'BuilderConflictError'
  /** The version the server actually holds, or null when unparseable. */
  readonly storedVersion: number | null
  /** The server's sentence, verbatim, for rendering. */
  readonly detail: string

  constructor(detail: string, storedVersion: number | null) {
    super(detail)
    this.detail = detail
    this.storedVersion = storedVersion
  }
}

/**
 * The compiler refused to publish, and said why in the canvas's own vocabulary.
 *
 * `publish`'s 422 is the ONE error on this router whose `detail` is an object
 * rather than a string: `BuilderCompileError` carries the same `Problem` list
 * `validate` returns, so `PublishDialog` merges these into `ProblemsPanel` and
 * every one of them stays clickable back to the node that caused it.
 *
 * Flattening that to a sentence is not a hypothetical loss. This repo has
 * already shipped the mirror-image defect once - `fetchJson` threw
 * `new Error(await response.text())` and an author was shown a raw JSON
 * envelope, braces and all (remaining-work item 11). An object detail sent
 * through the string path renders as the whole envelope, and the problem list
 * inside it is thrown away.
 */
export class BuilderPublishRefusedError extends Error {
  readonly name = 'BuilderPublishRefusedError'
  readonly problems: BuilderProblem[]

  constructor(message: string, problems: BuilderProblem[]) {
    super(message)
    this.problems = problems
  }
}

/**
 * Unwrap publish's object-shaped 422, or answer null for every other body.
 *
 * Keyed on the SHAPE rather than on which method called it. The transport is
 * the same `HTTPException` machinery for every route, so "this is the compile
 * refusal" is a fact about `{detail: {message, problems}}` and not about the
 * URL - and it means `publish`'s OTHER 422s, the ones `_guarded` raises from
 * the store with a plain string detail, still go through `readErrorDetail`
 * where they belong.
 *
 * `problems` must be an array and `message` a string. A partial match is far
 * more likely to be some other error envelope than a compile refusal, and
 * guessing wrong means an author reads a mangled object where a sentence
 * belongs.
 */
export function readPublishRefusal(
  body: string,
): { message: string; problems: BuilderProblem[] } | null {
  if (!body.trim().startsWith('{')) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(body)
  } catch {
    return null
  }
  const detail = (parsed as { detail?: unknown })?.detail
  if (typeof detail !== 'object' || detail === null || Array.isArray(detail)) return null
  const { message, problems } = detail as { message?: unknown; problems?: unknown }
  if (typeof message !== 'string' || !Array.isArray(problems)) return null
  return { message, problems: problems as BuilderProblem[] }
}

/**
 * The version the server says it holds, read out of a conflict sentence.
 *
 * Anchored on `is at version` rather than on the first number in the string,
 * because the sentence names two versions - the stored one and the one that was
 * expected - and taking the wrong one sends `ConflictDialog` to re-fetch the
 * author's own stale version, where it would find nothing changed.
 */
function storedVersionOf(detail: string): number | null {
  const match = /is at version (\d+)/.exec(detail)
  if (!match) return null
  const version = Number(match[1])
  return Number.isFinite(version) ? version : null
}

export class BuilderApi {
  /*
   * THERE IS NO `vocabulary()` HERE, and its absence is the decision.
   *
   * `GET /api/builder/vocabulary` is the one builder route this class does not
   * own: `data/builderVocabulary.ts` owns it, and owns it whole - the session
   * cache, the single in-flight request, and `normalise()`, which is the check
   * that refuses a payload naming an eighth node kind or an empty `agent_ids`
   * rather than handing the palette something it cannot draw.
   *
   * A method here returned that payload cast to `BuilderVocabulary` with none
   * of that applied, which is two answers to one question where the cheaper
   * answer is the unsafe one. It had no caller outside its own test. The route
   * is still reached, and `tests/builderApi.spec.ts` still proves every
   * declared route is - it now reads `VOCABULARY_PATH` for that leg, from the
   * module that actually asks for it.
   */

  /** The caller's own documents, newest first. */
  async list(limit?: number): Promise<BuilderDocumentSummary[]> {
    const query = limit === undefined ? '' : `?limit=${encodeURIComponent(String(limit))}`
    return this.json<BuilderDocumentSummary[]>(`${BUILDER_API_PREFIX}/workflows${query}`)
  }

  /**
   * Save a brand new graph as a draft, and read its id off the BODY.
   *
   * The 201 also carries `Location: /api/builder/workflows/{id}`, and reading
   * that would be the conventional thing to do. It is unreadable here.
   * `Location` is not a CORS-safelisted response header and
   * `CORS_EXPOSE_HEADERS` names only `ETag` and `Retry-After`
   * (`config.py:2109`), so cross-origin - which is the deployed shape, the SPA
   * and the API being separate origins - `headers.get('Location')` answers null
   * with no error raised anywhere. It would work behind the Vite dev proxy and
   * fail in production, which is the worst failure mode available.
   *
   * `BuilderDocumentModel.id` is the same id, always present, and reads the
   * same either way.
   *
   * A draft need not be valid. The server says so explicitly and the canvas
   * depends on it: a graph is incomplete for most of the session it is drawn
   * in, and a save that refused it would be unusable exactly when it is most
   * useful. The refusals live on publish.
   */
  async create(doc: BuilderDocument): Promise<BuilderDocumentModel> {
    return this.json<BuilderDocumentModel>(`${BUILDER_API_PREFIX}/workflows`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // `expected_version` is ignored on a create, and is sent as an explicit
      // null rather than omitted so every request body on this router has one
      // shape. The server's model is `extra="forbid"`, so the key must be one
      // it declares - and it is.
      body: JSON.stringify({ document: toWire(doc), expected_version: null }),
    })
  }

  /** One document, at head or at a named version. */
  async get(id: string, version?: number): Promise<BuilderDocumentModel> {
    const query = version === undefined ? '' : `?version=${encodeURIComponent(String(version))}`
    return this.json<BuilderDocumentModel>(
      `${BUILDER_API_PREFIX}/workflows/${encodeURIComponent(id)}${query}`,
    )
  }

  /**
   * Write the next version, if nobody else wrote one first.
   *
   * `expectedVersion` is a required parameter rather than an optional one with
   * a default, mirroring the server's own refusal: it answers 422 when the
   * field is absent, because a save with no version to compare against is a
   * lost update waiting to happen and a default of "whatever is stored" would
   * make the conflict unreachable rather than rare.
   *
   * The value must come from a server RESPONSE and never from `doc.version`.
   * The server assigns both the id and the version on every write, so the
   * document's own copy is whatever it was last parsed against - which on a
   * `validate` round trip is not the stored version at all.
   *
   * A 409 is a `BuilderConflictError`, not a message. See its docblock.
   *
   * `options` says how the save came about (round 2, D-15-3) - `save`,
   * `autosave`, or `restore` with the version it put back - and the server
   * composes the version browser's `source` from it. Omitted, the server
   * writes `saved`; the three doubles that implement `BuilderApiLike` with the
   * three-parameter shape keep compiling, because a caller may pass more.
   */
  async save(
    id: string,
    doc: BuilderDocument,
    expectedVersion: number,
    options: SaveOptions = {},
  ): Promise<BuilderDocumentModel> {
    return this.json<BuilderDocumentModel>(
      `${BUILDER_API_PREFIX}/workflows/${encodeURIComponent(id)}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          document: toWire(doc),
          expected_version: expectedVersion,
          ...(options.source ? { source: options.source } : {}),
          ...(options.restoredFrom ? { restored_from: options.restoredFrom } : {}),
        }),
      },
    )
  }

  /**
   * Delete a graph, unregistering it first if it was published.
   *
   * Answers 204 with no body, so nothing is parsed. `.json()` on an empty body
   * throws, which would turn a delete that fully succeeded into an error the
   * author would reasonably retry - against a document that is already gone.
   */
  async remove(id: string): Promise<void> {
    const response = await authedFetch(
      `${BUILDER_API_PREFIX}/workflows/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    )
    if (!response.ok) throw await this.refusal(response)
  }

  /**
   * Every problem with a document nobody has saved.
   *
   * Sends `forValidate(doc)`, which omits `id` and guarantees `version` is a
   * number, because this handler reads both off the RAW body before any schema
   * sees it - it is the only endpoint that does, `save` having a typed
   * `expected_version` and `publish` a `Query(ge=1)`.
   *
   * `_requested_version` refuses a non-number by hand with `version must be a
   * whole number; this document carries 'v7'`, and
   * `str(request.document.get("id") or new_document_id())` feeds a malformed id
   * straight into `BUILDER_DOCUMENT_ID_PATTERN`. Both are 422s about fields the
   * author never typed and cannot see. The version half used to be worse: a
   * bare `int(...)` raised `ValueError` and answered **500**, which the canvas
   * reads as `unreachable` - a document that mysteriously would not validate,
   * blaming the network. That was repaired server-side on 2026-09-02; sending a
   * number means neither refusal can fire either way, which is why this side
   * did not change with it.
   *
   * `signal` is not optional decoration. The canvas revalidates on a 400ms
   * debounce, so a slow answer about a document the author has already edited
   * past must be cancelled rather than raced - a stale problem list presented
   * as current is the single failure this loop exists to avoid.
   */
  async validate(doc: BuilderDocument, signal?: AbortSignal): Promise<BuilderValidation> {
    return this.json<BuilderValidation>(`${BUILDER_API_PREFIX}/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ document: forValidate(doc), expected_version: null }),
      signal,
    })
  }

  /**
   * Compile a stored version and register it as a launchable workflow.
   *
   * It publishes what is STORED, not what is on the canvas - there is no
   * document in this request at all - which is why the publish path insists the
   * save state is clean first. A 422 here is the compiler's refusal and arrives
   * as `BuilderPublishRefusedError` carrying the problem list.
   */
  async publish(id: string, version?: number): Promise<BuilderPublish> {
    const query = version === undefined ? '' : `?version=${encodeURIComponent(String(version))}`
    return this.json<BuilderPublish>(
      `${BUILDER_API_PREFIX}/workflows/${encodeURIComponent(id)}/publish${query}`,
      { method: 'POST' },
    )
  }

  /* --- plan 15: export, import, duplicate, versions --------------------- */

  /**
   * The document as a file: secrets stripped, identity dropped.
   *
   * Answers the JSON envelope rather than a blob; the file is written on this
   * side from it (`utils/builderExport.ts`). The response also carries
   * `Content-Disposition: attachment; filename="<name>.builder.json"`, and it is
   * unreadable here for the reason `create` gives about `Location`: not a
   * CORS-safelisted header, not named by `CORS_EXPOSE_HEADERS`, so cross-origin
   * - the deployed shape - `headers.get()` answers null with nothing raised.
   * The envelope's own `name` is the same string, always present.
   *
   * `version` names a stored version; omitted, the server exports head.
   * 404 for a document that is not the caller's, the way every read on this
   * router answers - a 403 would confirm the document exists.
   */
  async exportWorkflow(id: string, version?: number): Promise<BuilderExportEnvelope> {
    const query = version === undefined ? '' : `?version=${encodeURIComponent(String(version))}`
    return this.json<BuilderExportEnvelope>(
      `${BUILDER_API_PREFIX}/workflows/${encodeURIComponent(id)}/export${query}`,
    )
  }

  /**
   * A file becomes a NEW draft owned by the caller.
   *
   * Never an overwrite: the envelope carries no id, and the server mints one
   * regardless of anything the file says. The client has already checked the
   * envelope's SHAPE (`readExportFile`), so a 422 here is about the document
   * inside it, in the server's words - and it goes through the plain string
   * path like every refusal but publish's.
   *
   * The 201 is the create model plus `needs_credentials`, read off the BODY:
   * `Location` is unreadable cross-origin (see `create`).
   */
  async importWorkflow(envelope: BuilderExportEnvelope): Promise<BuilderImportResult> {
    return this.json<BuilderImportResult>(`${BUILDER_API_PREFIX}/workflows/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(envelope),
    })
  }

  /**
   * `<name> copy`, version 1, `draft`, owner = caller, as a 201 whose body is
   * the create model. `version` copies a stored version rather than head.
   * 404 for a document that is not the caller's.
   */
  async duplicateWorkflow(id: string, version?: number): Promise<BuilderDocumentModel> {
    const query = version === undefined ? '' : `?version=${encodeURIComponent(String(version))}`
    return this.json<BuilderDocumentModel>(
      `${BUILDER_API_PREFIX}/workflows/${encodeURIComponent(id)}/duplicate${query}`,
      { method: 'POST' },
    )
  }

  /**
   * Take a published graph out of service and return its head to draft.
   *
   * The remedy the delete 409 names (plan 15 D3; PLANS.md decision 24, round 2
   * D-15-10): "a published graph cannot be deleted; unpublish it first" is only
   * a rule an author can act on if this route exists. Answers the document
   * model with `published: false` and `status: 'draft'`; idempotent, so a graph
   * that was never published answers 200 with nothing changed.
   */
  async unpublish(id: string): Promise<BuilderDocumentModel> {
    return this.json<BuilderDocumentModel>(
      `${BUILDER_API_PREFIX}/workflows/${encodeURIComponent(id)}/unpublish`,
      { method: 'POST' },
    )
  }

  /** Every stored version of a document, newest first. Same visibility as `get`. */
  async listVersions(id: string): Promise<BuilderVersionRow[]> {
    return this.json<BuilderVersionRow[]>(
      `${BUILDER_API_PREFIX}/workflows/${encodeURIComponent(id)}/versions`,
    )
  }

  /* ---------------------------------------------------------------------- *
   *  The docked test panel - .agent/plans/13-flow-testing.md, contract C7    *
   * ---------------------------------------------------------------------- */

  /** This author's saved test inputs for one document, newest first. */
  async listTestInputs(documentId: string): Promise<TestInput[]> {
    return this.json<TestInput[]>(
      `${BUILDER_API_PREFIX}/workflows/${encodeURIComponent(documentId)}/test-inputs`,
    )
  }

  /**
   * Save one input set against a document.
   *
   * `from_run_id` is sent rather than the mocks it would produce, because the
   * server is the only side that can read a run's whole state: `/runs/{id}/state`
   * answers one moment at a time and redacts as it goes, and no route hands the
   * browser every node's output at once.
   */
  async createTestInput(documentId: string, draft: TestInputDraft): Promise<TestInput> {
    return this.json<TestInput>(
      `${BUILDER_API_PREFIX}/workflows/${encodeURIComponent(documentId)}/test-inputs`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          label: draft.label,
          inputs: draft.inputs,
          node_mocks: draft.node_mocks ?? {},
          from_run_id: draft.from_run_id ?? null,
        }),
      },
    )
  }

  async deleteTestInput(documentId: string, testInputId: string): Promise<void> {
    const path =
      `${BUILDER_API_PREFIX}/workflows/${encodeURIComponent(documentId)}` +
      `/test-inputs/${encodeURIComponent(testInputId)}`
    const response = await authedFetch(path, { method: 'DELETE' })
    if (!response.ok) throw await this.refusal(response)
  }

  /**
   * What this canvas compiled to - the YAML, the Python and the definition.
   *
   * Works on any SAVED document, published or not, which is what makes the Code
   * tab the one tab an unpublished draft can use. A document that no longer
   * compiles answers 422 carrying the compiler's own problem list, and
   * `refusal` unwraps it into a `BuilderPublishRefusedError` the same way
   * publish's does - the shape is what identifies it, not the URL.
   */
  async compiled(documentId: string, version?: number): Promise<CompiledPreview> {
    const query = version === undefined ? '' : `?version=${encodeURIComponent(String(version))}`
    return this.json<CompiledPreview>(
      `${BUILDER_API_PREFIX}/workflows/${encodeURIComponent(documentId)}/compiled${query}`,
    )
  }

  /**
   * `mode: dry_run` - parse, bound, price and compile, spending nothing.
   *
   * On the RUN endpoint rather than under `/api/builder`, because that is where
   * C7 put it: a dry run is the launch path stopped one step before it spends,
   * and answering it from a different router would be a second code path that
   * could disagree with the one that runs. It is answered BEFORE the rate
   * limiter (10 D8), so a preview the canvas fires on every edit never competes
   * with Launch for a launch allowance.
   *
   * It needs a PUBLISHED graph, and that is C7 as built rather than a choice
   * made here: `dry_run_payload` resolves `workflow_id` against
   * `BUILDER_WORKFLOWS`, which only a publish writes.
   */
  async dryRun(sessionId: string, workflowId: string): Promise<DryRunResult> {
    return fetchJson<DryRunResult>(`/api/sessions/${encodeURIComponent(sessionId)}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workflow_id: workflowId, inputs: {}, mode: 'dry_run' }),
    })
  }

  /**
   * The flow state as of one frame - C7's `GET /api/runs/{id}/state?step=`.
   *
   * `step` is a frame `seq` and not a state row id, because a frame seq is the
   * only cursor a client already has: it is what `/frames` pages on and what
   * the socket replays from. Omitting it answers the latest state.
   */
  async runState(runId: string, step?: number): Promise<RunStateResult> {
    const query = step === undefined ? '' : `?step=${encodeURIComponent(String(step))}`
    return fetchJson<RunStateResult>(`/api/runs/${encodeURIComponent(runId)}/state${query}`)
  }

  private async json<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await authedFetch(path, init)
    if (!response.ok) throw await this.refusal(response)
    return response.json() as Promise<T>
  }

  /**
   * The one place a builder refusal becomes an Error, so two callers cannot
   * classify the same status differently.
   *
   * The object detail is checked FIRST, before anything reads the status.
   * `readErrorDetail` returns its own fallback for a `detail` that is not a
   * string, and for a compile refusal that fallback is the raw envelope - the
   * exact defect item 11 repaired for the run endpoint, reintroduced on the one
   * error that carries the most structure.
   *
   * A string `detail` is passed through UNMODIFIED, and that is the design
   * rather than an omission: the server writes these sentences and this client
   * must not paraphrase them. D-15-29 landed here because one of those
   * sentences was `nodes.3.skill_id: Field required` - an array index for a
   * node the canvas calls Skill - and it is fixed where the sentence is
   * written, in `service/builder_api.py::_first_schema_error`, which has the
   * document and can therefore name the mcp node by its label. Rewriting it here
   * would mean re-deriving which node an index means from a file this client
   * does not hold.
   */
  private async refusal(response: Response): Promise<Error> {
    const body = await response.text().catch(() => '')
    const refusal = readPublishRefusal(body)
    if (refusal) return new BuilderPublishRefusedError(refusal.message, refusal.problems)

    let message = readErrorDetail(body, response.status)
    if (response.status === 409) return new BuilderConflictError(message, storedVersionOf(message))
    if (response.status === 429) {
      message += retryAfterSentence(response.headers.get('Retry-After'))
    }
    return new Error(message)
  }
}

/**
 * The surface the builder composables depend on.
 *
 * Declared as a `Pick` of the class rather than as a free-standing interface,
 * so a test double is compiler-forced to match its subject - the same reasoning
 * as `StudioApiLike`, and the same lesson this repo has now learned twice: a
 * double that diverges from the thing it stands in for certifies nothing
 * (closed items 20 and 33).
 */
export type BuilderApiLike = Pick<
  BuilderApi,
  | 'list'
  | 'create'
  | 'get'
  | 'save'
  | 'remove'
  | 'validate'
  | 'publish'
>

/**
 * The five routes plan 15 added, as their own surface.
 *
 * NOT folded into `BuilderApiLike`, and the reason is that plan's criterion 11:
 * `tests/builderPersistence.spec.ts` (33) must pass unchanged, and both it and
 * `tests/helpers.ts` carry a double declared `implements BuilderApiLike`.
 * Widening that Pick would stop the persistence suite's double compiling -
 * which is what the Pick is FOR, except that nothing in the save loop calls any
 * of these, so the divergence would be a cost with no defect behind it. A
 * surface that DOES call them asks for this type, and the compiler still forces
 * its double to match its subject.
 */
export type BuilderLifecycleApiLike = Pick<
  BuilderApi,
  'exportWorkflow' | 'importWorkflow' | 'duplicateWorkflow' | 'listVersions' | 'unpublish'
>

export const builderApi = new BuilderApi()

/**
 * The five calls the docked test panel makes, as their own surface.
 *
 * NOT folded into `BuilderApiLike`, for `BuilderLifecycleApiLike`'s reason: two
 * suites carry doubles declared `implements BuilderApiLike`, and widening that
 * `Pick` would stop them compiling over methods no save loop calls. A surface
 * that DOES call these asks for this type, and the compiler still forces its
 * double to match its subject.
 */
export type BuilderTestApiLike = Pick<
  BuilderApi,
  'listTestInputs' | 'createTestInput' | 'deleteTestInput' | 'compiled' | 'dryRun' | 'runState'
>

/**
 * `studioApi` with a run MODE attached - the whole of the test panel's reuse of
 * the run console.
 *
 * 13 D2 asks for `useValidatorRun` to drive the panel: a test run and a real run
 * are the same run, `runs.mode` is the only difference (C7), and one frame
 * pipeline with two tenants is what `node-card.css` already does for two cards.
 * The composable takes its transport as an argument for exactly this - "the
 * composable can be driven by a deterministic double" - so a wrapper is the
 * seam that already existed.
 *
 * IT IS A WRAPPER AND NOT AN EDIT because `StudioApi.startRun` cannot carry a
 * mode: its signature is `(sessionId, idea, workflowId, gates, inputField)` and
 * plan 11 owns that file this wave. The change this wants is one optional
 * options bag on `startRun`; until it exists, every other method here delegates
 * unchanged, so there is exactly one behaviour that differs from the console's
 * and it is the one the panel is for.
 *
 * `mode` and `probeFailure` are getters over the wrapped client rather than
 * copies. A copy is a second answer to "is there a backend", and the console
 * has already shipped the defect where two of those disagreed on screen.
 */
export class TestRunTransport implements StudioApiLike {
  /** What the next `startRun` posts. Set by the panel immediately before it. */
  runMode: RunMode = 'test'
  /** `node_test` only: which node runs for real, and what the rest replay from. */
  nodeId: string | null = null
  testInputId: string | null = null

  private readonly inner: StudioApiLike

  constructor(inner: StudioApiLike = studioApi) {
    this.inner = inner
  }

  get mode(): TransportMode {
    return this.inner.mode
  }

  get probeFailure(): string | null {
    return this.inner.probeFailure
  }

  get probeRefusal(): string | null {
    return this.inner.probeRefusal
  }

  initialize(force?: boolean): Promise<TransportMode> {
    return this.inner.initialize(force)
  }

  getGraph(workflowId?: string): Promise<GraphDescriptor> {
    return this.inner.getGraph(workflowId)
  }

  /**
   * The one method that differs, and the one refusal that is this class's own.
   *
   * A MOCKED transport is refused rather than delegated. `StudioApi`'s mock
   * fabricates a fourteen-node validator run; drawn on a builder canvas it
   * would be a scripted demonstration of a graph the author did not write,
   * under a Run button they pressed on purpose. That is the silent-mock defect
   * (gotchas 2) aimed at the one surface where the author's own work is what
   * gets misrepresented, and `builderApi` already refuses a mock for the same
   * reason.
   */
  async startRun(
    sessionId: string,
    idea: string,
    workflowId = 'idea-validator',
    gates: GatesMode = 'human',
    inputField = 'idea',
  ): Promise<StartRunResponse> {
    const transport = await this.inner.initialize(this.inner.mode === 'mock')
    if (transport !== 'live') {
      throw new Error(
        'the test panel needs a live backend, and this page is in demonstration '
        + 'mode. A test run has to be a real one.',
      )
    }
    return fetchJson<StartRunResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workflow_id: workflowId,
        inputs: { [inputField]: idea },
        gates,
        mode: this.runMode,
        node_id: this.nodeId,
        test_input_id: this.testInputId,
      }),
    })
  }

  /**
   * Re-run from a failed node, as a TEST run.
   *
   * Plan 11's `StudioApiLike.resumeRun` (Re-run from here) and plan 13's
   * transport met on the merge, and the two disagree on one thing only: what a
   * resumed run's `mode` is. Delegating to the console's method would post no
   * mode, and the server's default is a REAL run - so a button pressed inside
   * the test panel would silently create the one kind of run the panel exists
   * not to. The body mirrors the console's exactly and adds `mode: 'test'`;
   * `test` rather than `this.runMode` because a node test's replay set is the
   * saved input's mocks, and a resume replays the failed run's own state (10
   * D5) - the two are different plans, and only the first is what a re-run is.
   */
  async resumeRun(
    sessionId: string,
    sourceRunId: string,
    nodeId: string,
    workflowId: string,
    inputs: Record<string, unknown>,
    gates: GatesMode = 'human',
  ): Promise<StartRunResponse> {
    const transport = await this.inner.initialize(this.inner.mode === 'mock')
    if (transport !== 'live') {
      throw new Error('Re-running from a node needs the live backend.')
    }
    return fetchJson<StartRunResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workflow_id: workflowId,
        inputs,
        gates,
        resume_from: { run_id: sourceRunId, node_id: nodeId },
        mode: 'test',
      }),
    })
  }

  getRun(id: string): Promise<RunSnapshot> {
    return this.inner.getRun(id)
  }

  getFrames(id: string, after: number): Promise<FrameData[]> {
    return this.inner.getFrames(id, after)
  }

  subscribe(runId: string, sessionId: string, handlers: StreamHandlers): () => void {
    return this.inner.subscribe(runId, sessionId, handlers)
  }

  replyGate(runId: string, gateId: string, reply: GateReply): Promise<void> {
    return this.inner.replyGate(runId, gateId, reply)
  }

  cancelRun(runId: string): Promise<void> {
    return this.inner.cancelRun(runId)
  }

  downloadLogs(runId: string, format?: LogFormat): Promise<void> {
    return this.inner.downloadLogs(runId, format)
  }

  listRuns(limit?: number): Promise<RunHistoryEntry[]> {
    return this.inner.listRuns(limit)
  }
}


/* ======================================================================== *
 *  Credentials - plan 01, contract C4                                      *
 * ======================================================================== */

/**
 * `BUILDER_API_PREFIX` + the credential router's own path. Every one of the
 * four calls below is `require_user` on the server: 401 with
 * `WWW-Authenticate: Bearer` for nobody, 503 `credential vault is not
 * configured` when the deployment has no `CREDENTIALS_MASTER_KEY`.
 */
export const CREDENTIALS_PATH = `${BUILDER_API_PREFIX}/credentials`

/**
 * Free functions rather than methods on `BuilderApi`, and the reason is the
 * `Pick` above. `BuilderApiLike` is what every document double in the test
 * suite is compiler-forced to match, and a credential is not a document: a
 * `FakeBuilderApi` that had to grow four vault methods to keep compiling would
 * be modelling a surface none of its callers reach. The picker takes its own
 * narrower `CredentialApiLike`, so its double is checked against exactly what
 * it stands in for and nothing else.
 *
 * They ride `httpCore` - bearer token, one 401 retry, the server's sentence
 * rather than the envelope - for the reason that file gives: a second copy of
 * a 401 retry is how one of them quietly stops retrying.
 */

/** The caller's own credentials, never a field value among them. */
export async function listCredentials(): Promise<CredentialSummary[]> {
  return fetchJson<CredentialSummary[]>(CREDENTIALS_PATH)
}

/**
 * Store one. The fields leave in THIS body and nowhere else: the 201 answers
 * with the same row shape the list uses, and a 422 names the kind or the
 * missing field, a 413 the `MAX_CREDENTIAL_BYTES` (4 KiB) ceiling.
 */
export async function createCredential(draft: CredentialDraft): Promise<CredentialSummary> {
  return fetchJson<CredentialSummary>(CREDENTIALS_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(draft),
  })
}

/**
 * Answers 204 with no body, so nothing is parsed - `.json()` on an empty
 * body throws, and that would turn a delete that fully succeeded into an
 * error the author would retry against a row that is already gone. The same
 * shape as `BuilderApi.remove`. A 404 is absent-or-not-yours, collapsed on the
 * server so a stranger's probe learns nothing.
 */
export async function deleteCredential(id: string): Promise<void> {
  const response = await authedFetch(`${CREDENTIALS_PATH}/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (response.ok) return
  const body = await response.text().catch(() => '')
  let message = readErrorDetail(body, response.status)
  if (response.status === 429) message += retryAfterSentence(response.headers.get('Retry-After'))
  throw new Error(message)
}

/**
 * Ask the vault to try the credential against its provider. User-initiated
 * and rate-limited with the run limiter's key, so a 429 here carries the same
 * `Retry-After` sentence a launch would.
 */
export async function testCredential(id: string): Promise<CredentialProbe> {
  return fetchJson<CredentialProbe>(`${CREDENTIALS_PATH}/${encodeURIComponent(id)}/test`, {
    method: 'POST',
  })
}

/** What `CredentialPicker` depends on - the four calls, nothing else. */
export interface CredentialApiLike {
  listCredentials: typeof listCredentials
  createCredential: typeof createCredential
  deleteCredential: typeof deleteCredential
  testCredential: typeof testCredential
}

export const credentialApi: CredentialApiLike = {
  listCredentials,
  createCredential,
  deleteCredential,
  testCredential,
}
