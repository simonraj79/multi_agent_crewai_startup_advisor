import { computed } from 'vue'
import type { ComputedRef, InjectionKey, Ref } from 'vue'
import { FIELD_CODES } from '../types/builder'
import type { BuilderProblem, ProblemCode, Severity } from '../types/builder'

/**
 * The server's flat problem list, indexed the four ways the canvas reads it.
 *
 * Nothing here decides anything. Every judgement was made by `bounds.py` and
 * arrives already worded for the author (spec R6); this is addressing, so that
 * one sentence can appear in three places at once - the node rim, the offending
 * control, and the panel - without three surfaces each running their own filter
 * over the array and quietly disagreeing about which problems exist.
 *
 * THE INVARIANT THIS FILE OWNS: no problem is ever silently dropped. A problem
 * lands in exactly one of three sinks - `documentProblems` when it carries no
 * anchor at all, the per-field bucket when `FIELD_CODES` can place it, and the
 * node's unplaced strip otherwise - and `tests/builderProblems.spec.ts` asserts
 * that partition is total over every code in `PROBLEM_CODES`. A message the
 * server wrote and no surface renders is worse than no check at all: the author
 * cannot publish and is told nothing.
 */

/**
 * A problem is entered under EVERY anchor it carries, not under one of them.
 *
 * Three codes carry both - `edge-unknown-port`, `edge-target-refuses-incoming`
 * and `back-edge-not-router` - because each describes a relationship rather
 * than an object: an edge naming a port its source does not have is a fact
 * about both ends, and an author looking at either one has to see it.
 * `bounds.py` sets `node_id=` and `edge_id=` together at exactly those three
 * sites (lines 470-490 and 617-629), which is what makes "index under each
 * non-null anchor" the faithful rule rather than a special case per code.
 */
export interface BuilderProblemsIndex {
  /** The list as given, in the server's order. */
  problems: ComputedRef<readonly BuilderProblem[]>
  /** Errors first, then warnings; server order preserved inside each group. */
  ordered: ComputedRef<BuilderProblem[]>
  problemsByNode: ComputedRef<ReadonlyMap<string, BuilderProblem[]>>
  problemsByEdge: ComputedRef<ReadonlyMap<string, BuilderProblem[]>>
  /** Both anchors null: graph-wide facts, rendered in their own group and anchored nowhere. */
  documentProblems: ComputedRef<BuilderProblem[]>
  /** The severity that should colour each node's rim - error outranks warning. */
  worstByNode: ComputedRef<ReadonlyMap<string, Severity>>
  worstByEdge: ComputedRef<ReadonlyMap<string, Severity>>
  errorCount: ComputedRef<number>
  warningCount: ComputedRef<number>
  problemsForNode: (nodeId: string) => BuilderProblem[]
  problemsForEdge: (edgeId: string) => BuilderProblem[]
  /** The problems `FieldProblem` renders under one control. */
  problemsForField: (nodeId: string, field: string) => BuilderProblem[]
  /**
   * The problems that must be pinned at the top of this node's inspector.
   *
   * `knownFields` is the fields the open inspector actually renders. Pass it and
   * a problem whose mapped control is absent from THIS form falls to the strip
   * instead of vanishing: `library-unknown-id` maps to `agent_id`, and
   * `compiler.py` raises it for a crew's unregistered `crew_id` too, where no
   * such control exists. Omit it and only unmapped codes fall through, which is
   * the right answer for a caller that has not enumerated its own fields.
   */
  unplacedForNode: (nodeId: string, knownFields?: readonly string[]) => BuilderProblem[]
  /** Which control a code anchors to, or undefined when nothing claims it. */
  fieldForCode: (code: ProblemCode | string) => string | undefined
  /**
   * Which control ONE problem anchors to: its own `field` (C8) if it carries
   * one, else its code's. This is the answer every sink uses; `fieldForCode` is
   * kept beside it because a caller holding only a code still has a question.
   */
  fieldFor: (problem: BuilderProblem) => string | undefined
}

/**
 * How `FieldProblem` reaches the index without a prop on every control.
 *
 * An inspector form is five to fifteen controls deep and each one needs the
 * same object; threading it through as a prop would put a `:problems` binding
 * on every field in the package and make forgetting one a silent loss of a
 * message. `BuilderView` provides it once.
 */
export const BUILDER_PROBLEMS: InjectionKey<BuilderProblemsIndex> = Symbol('builder-problems')

/**
 * An unrecognised severity counts as an error.
 *
 * `BuilderProblem.severity` is typed `Severity`, but `code` deliberately admits
 * `| string` so a check this build has never heard of still renders - and a
 * server that grows a third severity would otherwise have it silently treated
 * as the harmless one. Under-reporting a blocker is the expensive direction:
 * publish would be offered, the compiler would refuse, and the panel would show
 * nothing that explained it.
 */
function isError(problem: BuilderProblem): boolean {
  return problem.severity !== 'warning'
}

export function useBuilderProblems(
  source: Ref<readonly BuilderProblem[]>,
): BuilderProblemsIndex {
  const problems = computed(() => source.value ?? [])

  const ordered = computed(() => [
    ...problems.value.filter(isError),
    ...problems.value.filter((problem) => !isError(problem)),
  ])

  const problemsByNode = computed(() => groupBy(problems.value, (problem) => problem.node_id))
  const problemsByEdge = computed(() => groupBy(problems.value, (problem) => problem.edge_id))

  const documentProblems = computed(() =>
    ordered.value.filter((problem) => !problem.node_id && !problem.edge_id),
  )

  const worstByNode = computed(() => worst(problemsByNode.value))
  const worstByEdge = computed(() => worst(problemsByEdge.value))

  const errorCount = computed(() => problems.value.filter(isError).length)
  const warningCount = computed(() => problems.value.length - errorCount.value)

  const problemsForNode = (nodeId: string): BuilderProblem[] =>
    problemsByNode.value.get(nodeId) ?? []

  const problemsForEdge = (edgeId: string): BuilderProblem[] =>
    problemsByEdge.value.get(edgeId) ?? []

  const fieldForCode = (code: ProblemCode | string): string | undefined =>
    FIELD_CODES[code as ProblemCode]

  /**
   * The control ONE problem anchors to - its own `field` first, then its code's.
   *
   * C8's optional `field` exists because three codes blame a control that
   * varies with the document rather than with the code:
   * `model-lacks-capability` is about `llm.response_format` on one node and
   * `llm.reasoning_effort` on the next, and `FIELD_CODES` holds one string per
   * code. The payload wins where it is present, because it is the more specific
   * statement and it was made by the check that found the problem; the map is
   * the fallback for every server that has not grown the key.
   */
  const fieldFor = (problem: BuilderProblem): string | undefined =>
    problem.field || fieldForCode(problem.code)

  const problemsForField = (nodeId: string, field: string): BuilderProblem[] =>
    problemsForNode(nodeId).filter((problem) => fieldFor(problem) === field)

  const unplacedForNode = (nodeId: string, knownFields?: readonly string[]): BuilderProblem[] =>
    problemsForNode(nodeId).filter((problem) => {
      const field = fieldFor(problem)
      if (field === undefined) return true
      return knownFields ? !knownFields.includes(field) : false
    })

  return {
    problems,
    ordered,
    problemsByNode,
    problemsByEdge,
    documentProblems,
    worstByNode,
    worstByEdge,
    errorCount,
    warningCount,
    problemsForNode,
    problemsForEdge,
    problemsForField,
    unplacedForNode,
    fieldForCode,
    fieldFor,
  }
}

/**
 * Bucket by one anchor, skipping the problems that do not carry it.
 *
 * Order within a bucket is the server's, not severity's: a node's own strip
 * reads better in the order the checks ran (structure, then counts, then
 * budget) than re-sorted, and the panel does its own error-then-warning pass
 * over the whole list anyway.
 */
function groupBy(
  problems: readonly BuilderProblem[],
  anchor: (problem: BuilderProblem) => string | null,
): ReadonlyMap<string, BuilderProblem[]> {
  const index = new Map<string, BuilderProblem[]>()
  for (const problem of problems) {
    const key = anchor(problem)
    if (!key) continue
    const bucket = index.get(key)
    if (bucket) bucket.push(problem)
    else index.set(key, [problem])
  }
  return index
}

/** One severity per anchor, error winning, so a rim is never softened by a sibling warning. */
function worst(index: ReadonlyMap<string, BuilderProblem[]>): ReadonlyMap<string, Severity> {
  const severities = new Map<string, Severity>()
  for (const [key, bucket] of index) {
    severities.set(key, bucket.some(isError) ? 'error' : 'warning')
  }
  return severities
}

/* --- the run phase (12 D2) ----------------------------------------------- */

/**
 * The shape a `node_error` frame arrives in, structurally.
 *
 * Declared here rather than imported from `types/studio.ts` on purpose: the
 * builder's problems index has no business depending on the run console's frame
 * union, and everything this function reads is three keys deep. A frame that
 * carries more is unaffected; a frame that carries less falls out of the filter.
 */
export interface NodeErrorFrameLike {
  node_id?: string | null
  details?: {
    stage?: string | null
    error_class?: string | null
    message?: string | null
    attempt?: number | null
    will_retry?: boolean | null
    routed?: boolean | null
  } | null
}

/**
 * C6 `node_error` frames as problems the dock can render - 12 D2.
 *
 * WHY THEY ARE PROBLEMS AT ALL. The plan's D2 asks that a failed node say so in
 * three places at once: on the node, in the log, and in the problems dock. The
 * dock is the one that makes a failure SURVEYABLE - four nodes red on a
 * sixteen-node canvas is four rows here and four hunts otherwise - and it
 * already owns "every reason this graph is not working, all at once, errors
 * first, each one one click from the thing it is about". A run failure is that
 * kind of fact.
 *
 * THE CODE IS PREFIXED, and the prefix is this module's and not the wire's. C8
 * is explicit that run-phase classes surface through `node_error.error_class`
 * and are NOT union members, so `auth` and `rate_limit` are the values the
 * server really sends. Rendered raw in the code chip they would sit beside
 * `back-edge-not-router` reading like a build-time code this build had never
 * heard of; `run-auth` says which phase it came from in the one place a reader
 * is already looking. Nothing is invented - the suffix is the wire value
 * verbatim - and the frame is untouched.
 *
 * THE LAST ATTEMPT WINS. A retried node emits one frame per attempt, and three
 * rows saying the same sentence about one node is a dock nobody reads. The one
 * kept is the last, because that is the one whose `will_retry` is false and
 * whose message describes the state the run actually ended in; the attempt
 * count is carried into the sentence so nothing about the earlier ones is lost.
 */
export function runPhaseProblems(
  frames: readonly NodeErrorFrameLike[],
): BuilderProblem[] {
  const latest = new Map<string, BuilderProblem>()
  for (const frame of frames) {
    const details = frame.details ?? null
    // `stage: 'error'` alone is not enough: `serializer.py:455` raises one for
    // CrewAI's own MethodExecutionFailedEvent, and a tool, an llm call and a
    // crew each raise another. `attempt` is the field only the runtime writes.
    if (!details || details.stage !== 'error' || typeof details.attempt !== 'number') continue
    const nodeId = frame.node_id ?? null
    if (!nodeId) continue
    const attempt = details.attempt
    const sentence = (details.message ?? '').trim() || 'the node failed'
    latest.set(nodeId, {
      code: `run-${details.error_class || 'error'}`,
      severity: 'error',
      message:
        attempt > 1
          ? `${sentence} (attempt ${attempt})`
          : sentence,
      node_id: nodeId,
      edge_id: null,
    })
  }
  return [...latest.values()]
}
