import { computed, shallowRef, ref } from 'vue'
import { API_BASE_URL } from '../services/httpCore'
import { BUILDER_SCHEMA_ID, NODE_ID_PATTERN } from '../types/builder'
import type { BuilderBounds, BuilderVocabulary, NodeKind, Tier } from '../types/builder'
import { NODE_KIND_ORDER } from './nodeKinds'

/**
 * Everything the palette and the inspector are allowed to offer, fetched once
 * per session from `GET /api/builder/vocabulary`.
 *
 * Served rather than duplicated, for the reason `serverLimits.ts` already
 * records about `MAX_RUN_INPUT_CHARS`: a canvas offering a transform op the
 * compiler does not have is a 422 the author cannot act on, and a canvas missing
 * one is a feature nobody can reach. Both failures are silent on this side.
 *
 * THERE IS NO FALLBACK LIST, and that is cut list item 17 rather than an
 * omission. A hardcoded enum is how a client starts drawing graphs the compiler
 * rejects: it works right up until the server's allowlist moves, and then it
 * produces documents that validate on the canvas and 422 on save. When the fetch
 * fails the palette disables and states the reason, which is the one honest
 * answer available.
 *
 * NO AUTH, deliberately. `get_vocabulary` carries no `Depends(current_user)` -
 * it describes this build, not anybody's data - and this has to resolve before
 * the three-phase auth gate does, or the palette would be disabled for the whole
 * of a sign-in.
 */

/** `service/builder_api.py:BUILDER_API_PREFIX` + the handler's own path. */
export const VOCABULARY_PATH = '/api/builder/vocabulary'

/**
 * `sessionStorage`, not `localStorage`.
 *
 * The vocabulary describes ONE BUILD of the server - its bounds, its agent
 * library, its transform ops - and both Render services carry `autoDeploy: yes`,
 * so a build can change under an open browser. A session-scoped cache survives a
 * reload (which is what it is for: a reload should not re-disable the palette
 * while a request is in flight) and dies with the tab.
 */
const SESSION_KEY = 'builder-vocabulary'

/**
 * The loaded vocabulary, or null while it has not loaded.
 *
 * `shallowRef` because nothing mutates the payload - it is replaced whole or not
 * at all - and a deep reactive proxy over ten arrays would be paid for on every
 * palette render for no reader.
 */
export const vocabulary = shallowRef<BuilderVocabulary | null>(null)

/**
 * Why the vocabulary is unusable, as a sentence, or `''` when it is fine.
 *
 * One writable fact with two readers. The palette needs a boolean to disable and
 * a `role="alert"` needs a string, and holding those as two refs is holding one
 * fact twice - the failure mode being a disabled palette that says nothing, or a
 * stated reason above a palette that still works.
 */
export const vocabularyProblem = ref('')

/** True once a load has been attempted and failed. Never true merely because nothing has loaded yet. */
export const vocabularyUnavailable = computed(() => vocabularyProblem.value !== '')

/** The single in-flight request, so N palettes mounting at once make one fetch. */
let inFlight: Promise<BuilderVocabulary | null> | null = null

/**
 * The vocabulary, fetching it at most once per session.
 *
 * Resolves to `null` on failure rather than rejecting, because every caller is a
 * component mounting: a rejected promise here would be an unhandled rejection in
 * a `setup()` and the palette would still need to read `vocabularyProblem` to
 * know what to say. The reason is the return value that matters.
 */
export function loadVocabulary(): Promise<BuilderVocabulary | null> {
  if (vocabulary.value) return Promise.resolve(vocabulary.value)
  if (inFlight) return inFlight

  const cached = readSession()
  if (cached) {
    vocabulary.value = cached
    vocabularyProblem.value = ''
    return Promise.resolve(cached)
  }

  inFlight = fetchVocabulary().finally(() => {
    inFlight = null
  })
  return inFlight
}

/**
 * Drop everything loaded and let the next `loadVocabulary()` start again.
 *
 * Exported for tests, and honest about it: a module singleton outlives one spec
 * file's expectations, and a cache that cannot be cleared makes the second test
 * in a file depend on the first. It also clears the session copy, so a test that
 * seeds one is not read by the next.
 */
export function resetVocabulary(): void {
  vocabulary.value = null
  vocabularyProblem.value = ''
  inFlight = null
  try {
    window.sessionStorage.removeItem(SESSION_KEY)
  } catch {
    /* Same reasoning as the write below: a browser that refuses storage is not
     * a reason to fail. */
  }
}

async function fetchVocabulary(): Promise<BuilderVocabulary | null> {
  let payload: unknown
  try {
    /*
     * `API_BASE_URL` is imported from `httpCore`, and the plain `fetch` beside
     * it is the point of this line.
     *
     * This file used to restate that expression - one more
     * `import.meta.env.VITE_API_URL?.replace(/\/$/, '') ?? ''` - on the
     * argument that `httpCore` is the AUTHENTICATED path and this endpoint must
     * not wait on a bearer mint. That reason does not survive contact with what
     * was actually copied: `API_BASE_URL` is a const, not a credential, and
     * importing it neither mints a token nor attaches one. The thing that keeps
     * this request unauthenticated is calling `fetch` rather than `authedFetch`,
     * which is visible right here.
     *
     * What was left behind by the copy was two answers to "where is the API",
     * differing only in that one is evaluated per call and one at module load -
     * a difference with no reader, since `import.meta.env` is substituted at
     * build time. Both encode deployment trap 2: an unset `VITE_API_URL`
     * resolves every `/api` call against the SPA's own origin, where the
     * history fallback answers 200 text/html for anything, which is the
     * `SyntaxError` diagnosed below.
     */
    const response = await fetch(`${API_BASE_URL}${VOCABULARY_PATH}`, {
      headers: { Accept: 'application/json' },
    })
    if (!response.ok) {
      return refuse(
        `The builder vocabulary could not be loaded: the API answered ${response.status} ${response.statusText}.`,
      )
    }
    payload = await response.json()
  } catch (error) {
    /*
     * One catch for two diagnoses, and they are told apart by the message rather
     * than collapsed: a `TypeError` from `fetch` is an unreachable API, a
     * `SyntaxError` from `json()` is an API that answered something that is not
     * JSON - which in this codebase overwhelmingly means `VITE_API_URL` was
     * unset and the SPA's own history fallback answered 200 text/html.
     */
    return refuse(
      `The builder vocabulary could not be loaded: ${(error as Error)?.message ?? 'network error'}.`,
    )
  }

  const parsed = normalise(payload)
  if (typeof parsed === 'string') return refuse(parsed)

  vocabulary.value = parsed
  vocabularyProblem.value = ''
  writeSession(parsed)
  return parsed
}

/** Record the reason, leave the vocabulary null, and hand back null. */
function refuse(reason: string): null {
  vocabulary.value = null
  vocabularyProblem.value = reason
  return null
}

/**
 * A payload turned into a `BuilderVocabulary`, or the sentence saying why not.
 *
 * Every field is read out by name rather than spread, the same discipline
 * `toWire` applies in the other direction: what this build knows how to offer is
 * visible in one place, and a key the server grows arrives as a key nothing
 * renders rather than as an untyped passenger.
 *
 * The checks are not defensive noise. Each one is a state in which the palette
 * would otherwise offer something unusable, and would offer it silently: an
 * empty `agent_ids` makes every `agent` node unsaveable, a non-identifier id
 * fails `BUILDER_ID_PATTERN` at parse time, and a `schema_id` this build does
 * not write means every save is a 422 about a field the author never typed.
 */
function normalise(payload: unknown): BuilderVocabulary | string {
  if (!payload || typeof payload !== 'object') {
    return 'The builder vocabulary could not be loaded: the API answered something that is not an object.'
  }
  const raw = payload as Record<string, unknown>

  if (raw.schema_id !== BUILDER_SCHEMA_ID) {
    return (
      `This console writes ${BUILDER_SCHEMA_ID} documents and the API compiles ` +
      `${String(raw.schema_id)}, so nothing drawn here could be saved.`
    )
  }

  const lists: Array<[string, unknown]> = [
    ['node_kinds', raw.node_kinds],
    ['tiers', raw.tiers],
    ['agent_ids', raw.agent_ids],
    ['crew_ids', raw.crew_ids],
    ['research_tools', raw.research_tools],
    ['transform_ops', raw.transform_ops],
    ['router_comparisons', raw.router_comparisons],
    ['result_body_keys', raw.result_body_keys],
  ]
  for (const [name, value] of lists) {
    if (!Array.isArray(value) || value.some((entry) => typeof entry !== 'string')) {
      return `The builder vocabulary is unusable: ${name} is not a list of strings.`
    }
    // `research_tools` is legitimately empty on a build with no tools registered;
    // every other list names something a node kind REQUIRES, so an empty one is
    // a kind that cannot be created at all.
    if (value.length === 0 && name !== 'research_tools') {
      return `The builder vocabulary is unusable: ${name} is empty, so some node kinds could never be saved.`
    }
  }

  for (const name of ['agent_ids', 'crew_ids'] as const) {
    const offending = (raw[name] as string[]).find((id) => !NODE_ID_PATTERN.test(id))
    if (offending !== undefined) {
      return `The builder vocabulary is unusable: ${name} offers "${offending}", which is not a legal node identifier.`
    }
  }

  /*
   * `node_kinds` and `tiers` are the two lists this build DISCRIMINATES on, and
   * an entry outside either is not a missing feature, it is a document shape
   * this console cannot round-trip. `BuilderNode` is a union with seven members;
   * an eighth kind has no record in `nodeKinds.ts`, so it has no icon, no
   * default config and no ports - and worse, opening a saved document that
   * contains one would hand the author a node no inspector can edit and then
   * write it back. Refusing here is the earliest honest stop.
   *
   * `transform_ops` and `router_comparisons` are deliberately NOT checked this
   * way. Those are select options: an op this build has no argument shape for
   * degrades to the free named-args table that `merge` and `to_json` already
   * use, which is a real behaviour rather than a hole.
   */
  const unknownKind = (raw.node_kinds as string[]).find(
    (kind) => !NODE_KIND_ORDER.includes(kind as NodeKind),
  )
  if (unknownKind !== undefined) {
    return (
      `The API offers a "${unknownKind}" node and this console cannot draw one, ` +
      'so a graph using it could not be opened or saved here.'
    )
  }
  const knownTiers: readonly string[] = ['cheap', 'escalation']
  const unknownTier = (raw.tiers as string[]).find((tier) => !knownTiers.includes(tier))
  if (unknownTier !== undefined) {
    return `The API offers a "${unknownTier}" tier and this console prices and renders only ${knownTiers.join(' and ')}.`
  }

  const bounds = readBounds(raw.bounds)
  if (typeof bounds === 'string') return bounds

  return {
    schema_id: BUILDER_SCHEMA_ID,
    node_kinds: raw.node_kinds as NodeKind[],
    /*
     * C2 v2's tool catalogue, passed through only when the server sends one.
     * `undefined` is the honest answer for a v1 envelope - the palette's tool
     * sub-list is then absent rather than empty, and a client-side fallback
     * catalogue is cut-list item 17 for the same reason a fallback kind list is.
     */
    tools: Array.isArray(raw.tools)
      ? (raw.tools as BuilderVocabulary['tools'])
      : undefined,
    tiers: raw.tiers as Tier[],
    agent_ids: raw.agent_ids as string[],
    crew_ids: raw.crew_ids as string[],
    research_tools: raw.research_tools as string[],
    transform_ops: raw.transform_ops as BuilderVocabulary['transform_ops'],
    router_comparisons: raw.router_comparisons as string[],
    router_otherwise: String(raw.router_otherwise ?? ''),
    result_body_keys: raw.result_body_keys as string[],
    bounds,
  }
}

/** The count bounds, truncated; the one dollar bound, not. */
function readBounds(raw: unknown): BuilderBounds | string {
  if (!raw || typeof raw !== 'object') {
    return 'The builder vocabulary is unusable: it carries no bounds.'
  }
  const source = raw as Record<string, unknown>

  /*
   * `BuilderVocabularyModel.bounds` is `dict[str, float]`, so every value is
   * serialised as a JSON float - `24.0`, not `24`.
   *
   * Worth being exact about what that does and does not cost, because the spec
   * overstates it: `JSON.parse('24.0')` is the number 24 and renders "24", so
   * the float suffix alone is invisible on this side. What `Math.trunc` actually
   * guards is a bound that is genuinely fractional - an operator who sets one
   * from a float, or any future bound derived by arithmetic - where a pip row
   * would read "8 of 8.5" and `maxlength` would be the string "2000.5". It is
   * one call and it makes every count an integer by construction, which is what
   * every one of these fifteen is.
   */
  const count = (key: keyof BuilderBounds): number => Math.trunc(Number(source[key]))

  const bounds: BuilderBounds = {
    max_graph_nodes: count('max_graph_nodes'),
    max_billable_nodes: count('max_billable_nodes'),
    max_escalation_nodes: count('max_escalation_nodes'),
    max_fanout_width: count('max_fanout_width'),
    min_router_branches: count('min_router_branches'),
    max_cycles: count('max_cycles'),
    max_cycle_iterations: count('max_cycle_iterations'),
    max_agent_iter: count('max_agent_iter'),
    max_guardrail_retries: count('max_guardrail_retries'),
    max_label_chars: count('max_label_chars'),
    max_name_chars: count('max_name_chars'),
    max_gate_message_chars: count('max_gate_message_chars'),
    max_input_chars: count('max_input_chars'),
    max_document_bytes: count('max_document_bytes'),
    /*
     * NOT truncated, and this is the one exception §2's "Math.trunc every bounds
     * value" has to carry: `MAX_RUN_COST_USD` is dollars. Truncating it turns a
     * deliberate `MAX_RUN_COST_USD=2.50` into a $2.00 ceiling the operator never
     * set, and a ceiling below the true one refuses graphs that are affordable.
     * `types/builder.ts` records the same exception on the field itself.
     */
    run_cost_ceiling_usd: Number(source.run_cost_ceiling_usd),
  }

  const missing = (Object.keys(bounds) as Array<keyof BuilderBounds>).find(
    (key) => !Number.isFinite(bounds[key]),
  )
  if (missing) {
    return `The builder vocabulary is unusable: the bound ${missing} is missing or not a number.`
  }
  return bounds
}

function readSession(): BuilderVocabulary | null {
  let stored: string | null = null
  try {
    stored = window.sessionStorage.getItem(SESSION_KEY)
  } catch {
    // Private mode, or a browser configured to refuse site data. The cache is a
    // convenience; the fetch below is the source of truth.
    return null
  }
  if (!stored) return null
  try {
    const parsed = normalise(JSON.parse(stored))
    return typeof parsed === 'string' ? null : parsed
  } catch {
    // A half-written or older-shaped entry is discarded rather than repaired.
    return null
  }
}

function writeSession(value: BuilderVocabulary): void {
  try {
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(value))
  } catch {
    // Quota, private mode, or storage disabled. Losing the cache costs one
    // request per reload and nothing else, so it must never break a load.
  }
}
