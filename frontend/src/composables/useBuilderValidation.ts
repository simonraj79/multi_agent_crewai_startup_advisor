import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import type { ComputedRef, InjectionKey, Ref } from 'vue'
import { builderApi } from '../services/builderApi'
import type { BuilderApiLike } from '../services/builderApi'
import { fingerprint } from '../utils/builderSerialize'
import type { BuilderBudget, BuilderDocument, BuilderProblem } from '../types/builder'

/**
 * The live validation loop: what the server thinks of the document on screen,
 * and - just as important - whether that opinion is still about this document.
 *
 * This is the answer to the competition's second weakness. ChatDev computes its
 * `ConfigError` list on a save and renders it until the next one, so an author
 * editing node 2 reads a complaint about node 7 with nothing on screen saying
 * it is old news. Shipping that failure with a nicer font is the one loss that
 * would matter, so `stale` here is a RENDERED state and every response is
 * stamped with the fingerprint it answered.
 *
 * Four mechanisms, each closing a different way the list could lie:
 *
 * 1. The watch is on `fingerprint(doc)`, which OMITS `position`. A drag moves a
 *    card through dozens of commits and spends no request, because the compiler
 *    never reads a position - and, more to the point, the list never dims
 *    during a gesture that could not have changed it.
 * 2. A 400ms debounce, so a typed word is one request rather than five.
 * 3. An `AbortController` per request, aborted by its successor. The server
 *    would answer both; the point is that the slower answer never arrives to
 *    race the faster one.
 * 4. The stamp. Abort is best-effort - a response already on the wire lands
 *    anyway - so the fingerprint the request was built from is compared against
 *    the current one at the moment it resolves, and a mismatch is DROPPED.
 *    Belt and braces, and the braces are the load-bearing half.
 *
 * The client NEVER computes a problem (spec R6). Everything here is transport,
 * timing and freshness; `problems` and `budget` are whatever the server said.
 */

/** Spec sections 4.6 and 6.2. Long enough to swallow a typed word, short enough to feel live. */
export const VALIDATE_DEBOUNCE_MS = 400

/**
 * The server's latest estimate, published for the inspector's per-node cost line
 * (04 D6).
 *
 * PUBLISHED RATHER THAN THREADED, for the reason `BUILDER_PROBLEMS` already
 * gives: the LLM sub-form is four components below the rail, and a prop would
 * have to be forwarded through `<component :is>` - which erases it - and
 * through every form that does not care. The rail's own `BudgetMeter` keeps its
 * prop, because it is a sibling of the thing that owns the figure.
 *
 * `null` is a REAL STATE and every reader has to render it: nothing has been
 * validated yet, or the last attempt failed. The default of the inject is null
 * for the same reason - a form mounted in a spec that provides nothing shows no
 * cost line, rather than throwing the way `FieldProblem` deliberately does. The
 * difference is that a missing problem index hides a refusal and a missing
 * budget hides an estimate.
 */
export const BUILDER_BUDGET: InjectionKey<Ref<BuilderBudget | null>> = Symbol('builder-budget')

/**
 * Where the rendered list stands relative to the document on screen.
 *
 * - `idle` - nothing has been asked and nothing is pending. Only before the
 *   first check; the caller kicks that off with `validateNow()` when a document
 *   is opened, which is why this state is reachable at all rather than being a
 *   value no reader ever sees.
 * - `stale` - a check is pending or in flight, and what is rendered (possibly
 *   nothing) is not about the current document. Publish is blocked, and the
 *   panel dims and says so.
 * - `checking` - a check is in flight for the fingerprint that is ALREADY
 *   answered and on screen. That is a forced re-check, and it is deliberately
 *   NOT `stale`: nothing rendered is out of date, so dimming the list and
 *   blocking publish would both be lies.
 * - `fresh` - the rendered list answers this exact document.
 * - `unreachable` - the last attempt failed. Publish is blocked with the reason
 *   stated, never silently permitted.
 */
export type ValidationPhase = 'idle' | 'checking' | 'stale' | 'fresh' | 'unreachable'

/** The one method this loop needs, taken off the real client so a double cannot drift. */
export type ValidateApi = Pick<BuilderApiLike, 'validate'>

export interface BuilderValidationOptions {
  /** Defaults to the module singleton. Injected in tests, and by nothing else. */
  api?: ValidateApi
  /** Defaults to `VALIDATE_DEBOUNCE_MS`. */
  debounceMs?: number
  /**
   * True while a pointer gesture (drag, connect, marquee) is live.
   *
   * Spec section 6.2: a gesture suppresses validation entirely and coalesces to
   * its end. A drag cannot change the fingerprint at all, but a connect drag
   * can - and revalidating from under a half-drawn edge spends a request on a
   * document the author is still in the middle of describing.
   */
  suppressed?: Ref<boolean>
}

export interface BuilderValidationHandle {
  phase: Ref<ValidationPhase>
  /** The server's list, verbatim and in its order. Empty until the first answer. */
  problems: Ref<BuilderProblem[]>
  /** The server's estimate, or null until the first answer. */
  budget: Ref<BuilderBudget | null>
  /**
   * The server's own `valid` flag, NOT a count taken over `problems`.
   *
   * `false` before the first answer, because "no errors have been reported" and
   * "this document is publishable" are different statements and only the server
   * can make the second one.
   */
  valid: Ref<boolean>
  /** Why the last attempt failed, as a sentence, or `''`. */
  unreachableReason: Ref<string>
  /** Whether the phase alone blocks publish - spec section 6.5, rows 4 and 5. */
  phaseBlocksPublish: ComputedRef<boolean>
  /** The sentence to put on a blocked Publish button, or `''`. */
  phaseBlockReason: ComputedRef<string>
  /** Force a check now, cancelling any debounce. Bound to Cmd+Enter. */
  validateNow: () => void
  /** How many requests have actually been dispatched. Test instrumentation. */
  requestCount: Ref<number>
}

export function useBuilderValidation(
  doc: Ref<BuilderDocument>,
  options: BuilderValidationOptions = {},
): BuilderValidationHandle {
  const api = options.api ?? builderApi
  const debounceMs = options.debounceMs ?? VALIDATE_DEBOUNCE_MS
  const suppressed = options.suppressed

  const phase = ref<ValidationPhase>('idle')
  const problems = shallowRef<BuilderProblem[]>([])
  const budget = shallowRef<BuilderBudget | null>(null)
  const valid = ref(false)
  const unreachableReason = ref('')
  const requestCount = ref(0)

  /** What the document MEANS, position excluded. Recomputed once per doc change. */
  const stamp = computed(() => fingerprint(doc.value))

  /** The fingerprint the rendered list answers. `''` until something has. */
  const answered = ref('')

  let timer = 0
  let inFlight: AbortController | null = null
  /** A check is wanted, but the timer has not fired - or fired while suppressed. */
  let armed = false

  function clearTimer(): void {
    if (timer) window.clearTimeout(timer)
    timer = 0
  }

  function schedule(): void {
    armed = true
    if (stamp.value !== answered.value) phase.value = 'stale'
    clearTimer()
    timer = window.setTimeout(fire, debounceMs)
  }

  function fire(): void {
    timer = 0
    // Still suppressed: stay armed and say nothing. The watcher below restarts
    // the timer the moment the gesture ends, so the check is deferred rather
    // than dropped - and a dropped one would leave the panel dimmed forever,
    // which is the failure this whole module exists to avoid.
    if (suppressed?.value) return
    armed = false
    void dispatch(stamp.value)
  }

  async function dispatch(requested: string): Promise<void> {
    clearTimer()
    armed = false
    // Abort the predecessor BEFORE minting the successor, so `inFlight` never
    // names a controller that is already dead.
    inFlight?.abort()
    const mine = new AbortController()
    inFlight = mine
    requestCount.value += 1
    phase.value = requested === answered.value ? 'checking' : 'stale'

    try {
      const result = await api.validate(doc.value, mine.signal)
      // Two guards, and they are not redundant. `aborted` catches the response
      // our successor superseded; the stamp comparison catches the one that was
      // already on the wire when the author typed the next character, which no
      // abort can recall.
      if (mine.signal.aborted) return
      if (requested !== stamp.value) return
      answered.value = requested
      problems.value = result.problems ?? []
      budget.value = result.budget ?? null
      valid.value = result.valid === true
      unreachableReason.value = ''
      phase.value = 'fresh'
    } catch (error) {
      if (mine.signal.aborted) return
      if (requested !== stamp.value) return
      // Every failure lands here, and every one of them blocks publish with a
      // stated reason. A 5xx, a dropped connection and a 422 about a field the
      // author never typed are indistinguishable from where they sit, and all
      // three mean the same thing: nobody has said whether this document is
      // legal, so nothing may be published on the strength of the old answer.
      unreachableReason.value = reasonFor(error)
      phase.value = 'unreachable'
    } finally {
      if (inFlight === mine) inFlight = null
    }
  }

  /**
   * Force a check immediately, debounce and suppression both ignored.
   *
   * Suppression is ignored deliberately: it exists to stop the loop firing
   * under a gesture nobody asked about, and this is somebody asking.
   */
  function validateNow(): void {
    void dispatch(stamp.value)
  }

  watch(stamp, schedule)

  if (suppressed) {
    watch(suppressed, (busy) => {
      if (!busy && armed) schedule()
    })
  }

  onScopeDispose(() => {
    clearTimer()
    inFlight?.abort()
    inFlight = null
  })

  /**
   * `idle` blocks too, and that third member is the whole repair.
   *
   * It reads like a value nobody ever sees - the caller kicks a check when a
   * document opens - but it was reachable, and it was reachable on the first
   * screen a visitor meets. A blank canvas IS the document this loop mounted
   * with, so its fingerprint never moved, the watcher never fired, and the
   * phase sat at `idle` while the panel said `Ready to publish` and Publish
   * was enabled over a graph the server refuses with `no-input-node`. The
   * caller now kicks a check when a document is shown; this is the second
   * lock, so that any FUTURE path leaving the phase at `idle` refuses to
   * publish rather than quietly repeating the same lie.
   */
  const phaseBlocksPublish = computed(
    () => phase.value === 'idle' || phase.value === 'stale' || phase.value === 'unreachable',
  )

  const phaseBlockReason = computed(() => {
    if (phase.value === 'idle') return 'validation has not run yet'
    if (phase.value === 'unreachable') {
      return unreachableReason.value
        ? `validation is not current - ${unreachableReason.value}`
        : 'validation is not current'
    }
    return phase.value === 'stale' ? 'validation is not current' : ''
  })

  return {
    phase,
    problems,
    budget,
    valid,
    unreachableReason,
    phaseBlocksPublish,
    phaseBlockReason,
    validateNow,
    requestCount,
  }
}

/**
 * A throwable turned into something an author can read.
 *
 * `builderApi` already runs every refusal through `readErrorDetail`, so the
 * common case is a server sentence and this just unwraps it. The fallback
 * matters for the case `readErrorDetail` never sees: a network failure, where
 * `fetch` rejects with a `TypeError` whose message is a browser-specific
 * fragment - "Failed to fetch" in Chromium, "NetworkError when attempting to
 * fetch resource" in Firefox - that means nothing to the person reading it.
 */
function reasonFor(error: unknown): string {
  const message = error instanceof Error ? error.message.trim() : String(error ?? '').trim()
  if (!message || message === 'Failed to fetch') return 'the validator could not be reached'
  return message
}
