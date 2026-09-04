import { computed, ref } from 'vue'
import type { StorageIdentity } from '../data/identityStorage'
import { templateTestInputFor } from '../data/templates/testInputs'
import {
  BuilderPublishRefusedError,
  TestRunTransport,
  builderApi,
  type BuilderTestApiLike,
} from '../services/builderApi'
import type { StudioApiLike } from '../services/studioApi'
import { useValidatorRun } from './useValidatorRun'
import { isAttachmentKind } from '../types/builder'
import type {
  BuilderDocument,
  BuilderProblem,
  CompiledPreview,
  DryRunResult,
  RunStateResult,
  TestInput,
} from '../types/builder'

/**
 * The docked test panel's state - .agent/plans/13-flow-testing.md.
 *
 * Five tabs over ONE pipeline (D2). A test run and a real run are the same run:
 * `runs.mode` is the only difference (C7), so this composable does not own a
 * second frame reader, a second socket or a second node-state map. It owns the
 * panel's own state - which tab, how tall, which saved input - and drives
 * `useValidatorRun` through a transport that attaches the mode.
 *
 * WHAT IT DOES NOT OWN, and the boundary is worth stating because the reuse
 * looks like ownership from outside: node states, chat entries, usage, the
 * report and the socket lifecycle are all `useValidatorRun`'s, exposed here
 * unchanged so the panel and the console cannot render two different answers
 * about one run.
 *
 * ─────────────────────────────────────────────────────────────────────────
 * THE CONSTRAINT THE PLAN DID NOT KNOW, recorded here because every tab but
 * one is shaped by it.
 *
 * 13's Problem section says the panel means an author "cannot try a change
 * without publishing it" is no longer true. It is still true. C7 as BUILT
 * resolves every run mode - `dry_run` included - against `BUILDER_WORKFLOWS`
 * (`app.py::dry_run_payload`, `create_run`), and only a publish writes that
 * map. So Run, Node and Dry run need a published graph and say so; only Code,
 * which reads the document store, works on a draft. Contradiction recorded
 * against 13's Problem section and C7; not improvised around.
 * ─────────────────────────────────────────────────────────────────────────
 */

/** The five tabs, in render order. */
export const TEST_TABS = ['run', 'node', 'dry', 'code', 'state'] as const
export type TestTab = (typeof TEST_TABS)[number]

/** The collapsed tab strip's height, and the drag handle's two stops (D1). */
export const PANEL_COLLAPSED_PX = 36
export const PANEL_MIN_PX = 160
/** A fraction of the graph pane, not a pixel count: 60% of a laptop and of a wall. */
export const PANEL_MAX_FRACTION = 0.6
export const PANEL_DEFAULT_PX = 260

/**
 * The four reserved state namespaces, in the order the State tab groups them.
 *
 * `out__` and `err__` are `config.BUILDER_STATE_OUTPUT_PREFIX` and
 * `BUILDER_STATE_ERROR_PREFIX`; `turns__` is the per-gate revise counter and
 * `__builder__` the compiled graph's own metadata. Restated rather than
 * fetched, the way `data/serverLimits.ts` restates a bound - and, like that
 * one, the prefixes are what the SERVER strips and this only groups, so a
 * prefix that moved would show as an ungrouped key rather than as a wrong
 * answer.
 */
export const RESERVED_STATE_PREFIXES = ['out__', 'err__', 'turns__', '__builder__'] as const

/**
 * The session id a dry run is posted under.
 *
 * A literal, and it is not a shortcut. A dry run creates no run row, takes no
 * admission slot and is answered before the rate limiter (10 D8), so the
 * session in its path is a path segment and nothing else - minting a real one
 * would suggest this call joins the browser's run history, which is exactly
 * what D5 says it must not do.
 */
export const DRY_RUN_SESSION = 'builder-dry-run'

export interface StateGroup {
  /** The prefix, or `''` for the author's own keys. */
  prefix: string
  label: string
  entries: Array<{ key: string; label: string; value: unknown }>
}

export interface FlowTestOptions {
  /** The live document, read at every access so a rename is never stale. */
  document: () => BuilderDocument
  /** The saved document's id, or null while it has never been saved. */
  documentId: () => string | null
  /** Whether ANY version of this document is registered on the service. */
  published: () => boolean
  api?: BuilderTestApiLike
  /** The console's transport, wrapped. A double in tests, `studioApi` in the app. */
  transport?: StudioApiLike
  userId?: () => StorageIdentity
}

export function useFlowTest(options: FlowTestOptions) {
  const api = options.api ?? builderApi
  const transport = new TestRunTransport(options.transport)
  const run = useValidatorRun(transport, { userId: options.userId })

  const open = ref(false)
  const tab = ref<TestTab>('run')
  const height = ref(PANEL_DEFAULT_PX)
  /** The graph pane's height, for the 60% stop. Written by the shell's observer. */
  const paneHeight = ref(0)

  const testInputs = ref<TestInput[]>([])
  const selectedInputId = ref<string | null>(null)
  const inputValue = ref('')
  const savingInput = ref(false)

  const nodeUnderTest = ref<string | null>(null)

  const dryRunResult = ref<DryRunResult | null>(null)
  const dryRunPending = ref(false)

  const compiled = ref<CompiledPreview | null>(null)
  const compiledPending = ref(false)
  const compiledProblems = ref<BuilderProblem[]>([])

  const stateStep = ref(0)
  const stateResult = ref<RunStateResult | null>(null)
  const statePending = ref(false)

  /** The one place a refusal from any tab lands, so two tabs cannot disagree. */
  const problem = ref('')

  /* ── the panel itself (D1) ───────────────────────────────────────────── */

  const maxHeight = computed(() =>
    Math.max(PANEL_MIN_PX, Math.round((paneHeight.value || 0) * PANEL_MAX_FRACTION)),
  )

  /**
   * The rendered height: the collapsed strip, or the dragged height clamped.
   *
   * Clamped on READ rather than on write, because the ceiling is a fraction of
   * a pane that resizes: a height stored when the window was tall must come
   * back inside the bound when it is short, and a value clamped only at the
   * drag would not.
   */
  const panelHeight = computed(() => {
    if (!open.value) return PANEL_COLLAPSED_PX
    return Math.min(Math.max(height.value, PANEL_MIN_PX), maxHeight.value)
  })

  function setHeight(next: number): void {
    height.value = Math.min(Math.max(Math.round(next), PANEL_MIN_PX), maxHeight.value)
  }

  function toggle(next = !open.value): void {
    open.value = next
  }

  function selectTab(next: TestTab): void {
    tab.value = next
    open.value = true
    if (next === 'code') void loadCompiled()
  }

  /* ── what a run needs, and whether it has it ─────────────────────────── */

  const inputField = computed(() => String(options.document().input_field))

  /**
   * The nodes the Node tab may offer: flow kinds only (D4).
   *
   * An attachment cannot be tested alone because it has no output - a tool is
   * something an agent HAS, not something the flow does - so offering one would
   * be offering a run that cannot produce the thing the tab renders.
   */
  const testableNodes = computed(() =>
    options
      .document()
      .nodes.filter((node) => !isAttachmentKind(node.kind))
      .map((node) => ({ id: String(node.id), kind: node.kind, label: node.label })),
  )

  const selectedInput = computed<TestInput | null>(
    () => testInputs.value.find((row) => row.id === selectedInputId.value) ?? null,
  )

  /**
   * The `out__*` keys a single-node test must be able to replay, and has not
   * got (D4).
   *
   * Every node with an edge INTO the node under test, transitively - a mock is
   * needed for each ancestor, because the derived plan compiles every one of
   * them to `runtime:replay_output`. Reported here rather than left to the
   * server's 422 so the author is told before a run row exists, which is what
   * the criterion asks for; the server's refusal is still the one that binds.
   */
  const missingMocks = computed<string[]>(() => {
    const node = nodeUnderTest.value
    if (!node) return []
    const mocks = selectedInput.value?.node_mocks ?? {}
    return ancestorsOf(options.document(), node).filter((id) => !(id in mocks))
  })

  const canRunNode = computed(
    () =>
      Boolean(nodeUnderTest.value)
      && selectedInput.value !== null
      && missingMocks.value.length === 0
      && options.published(),
  )

  /** Why Run is unavailable, in a sentence, or `''` when it is available. */
  const runBlockedReason = computed(() => {
    if (!options.documentId()) return 'Save this graph before testing it.'
    if (!options.published()) {
      return 'Publish this graph to test it — a run resolves the workflow the service has registered.'
    }
    if (!inputValue.value.trim()) return `Type a value for ${inputField.value}.`
    return ''
  })

  const canRun = computed(() => runBlockedReason.value === '' && !run.isActive.value)

  /* ── saved inputs (D3) ───────────────────────────────────────────────── */

  /**
   * Load this document's saved inputs, and seed the box from the template's own.
   *
   * Criterion 11: a template a cold sign-in cannot run without first inventing
   * a prompt is a template nobody runs. `templateTestInputFor` answers the
   * committed sample for this graph's `input_field`, which is the one thing a
   * template's document carries that says which template it came from.
   */
  async function loadTestInputs(): Promise<void> {
    const id = options.documentId()
    seedFromTemplate()
    if (!id) {
      testInputs.value = []
      return
    }
    try {
      testInputs.value = await api.listTestInputs(id)
      if (selectedInputId.value && !selectedInput.value) selectedInputId.value = null
      if (!selectedInputId.value && testInputs.value.length) select(testInputs.value[0].id)
      problem.value = ''
    } catch (error) {
      testInputs.value = []
      problem.value = messageOf(error, 'the saved test inputs could not be read.')
    }
  }

  function seedFromTemplate(): void {
    if (inputValue.value.trim()) return
    const sample = templateTestInputFor(inputField.value)
    if (sample) inputValue.value = sample.value
  }

  function select(id: string | null): void {
    selectedInputId.value = id
    const row = testInputs.value.find((entry) => entry.id === id)
    if (!row) return
    const value = row.inputs[inputField.value]
    if (typeof value === 'string') inputValue.value = value
  }

  /**
   * Save what is in the box, optionally taking the last run's outputs as mocks.
   *
   * `from_run_id` is sent rather than mocks assembled here: a run's state is
   * readable only by its owner and no route hands the browser every node's
   * output at once, so the copy can only be the server's.
   */
  async function saveTestInput(label: string, { fromLastRun = false } = {}): Promise<void> {
    const id = options.documentId()
    if (!id) {
      problem.value = 'Save this graph before saving a test input for it.'
      return
    }
    savingInput.value = true
    try {
      const created = await api.createTestInput(id, {
        label,
        inputs: { [inputField.value]: inputValue.value },
        from_run_id: fromLastRun ? (run.runId.value ?? undefined) : undefined,
      })
      testInputs.value = [created, ...testInputs.value]
      selectedInputId.value = created.id
      problem.value = ''
    } catch (error) {
      problem.value = messageOf(error, 'that test input could not be saved.')
    } finally {
      savingInput.value = false
    }
  }

  async function removeTestInput(testInputId: string): Promise<void> {
    const id = options.documentId()
    if (!id) return
    try {
      await api.deleteTestInput(id, testInputId)
      testInputs.value = testInputs.value.filter((row) => row.id !== testInputId)
      if (selectedInputId.value === testInputId) selectedInputId.value = null
      problem.value = ''
    } catch (error) {
      problem.value = messageOf(error, 'that test input could not be deleted.')
    }
  }

  /* ── the three run modes ─────────────────────────────────────────────── */

  /**
   * Point the console's composable at THIS graph, then launch.
   *
   * The descriptor is fetched and assigned before `launch`, because `resetRun`
   * seeds `nodeStates` and `nodeUsage` from `descriptor.value.nodes` - so a
   * launch against a stale descriptor renders a run whose per-node usage lands
   * nowhere. A builder descriptor's node ids ARE the author's own canvas ids
   * (`builder_graph_descriptor`: one descriptor node per drawn node), which is
   * what lets the same map drive the builder canvas with no translation.
   *
   * `gates: 'human'` and not the console's `auto`. `create_run` refuses `auto`
   * for an ANONYMOUS caller unless `VALIDATOR_ALLOW_AUTO_GATES` is set, and the
   * free backend the E2E suite is allowed to use has no auth server - so `auto`
   * is a 403 there. A graph with no gate behaves identically either way; one
   * with a gate parks, which is honest.
   */
  async function launch(mode: 'test' | 'node_test'): Promise<void> {
    const workflowId = options.documentId()
    if (!workflowId) return
    problem.value = ''
    transport.runMode = mode
    transport.nodeId = mode === 'node_test' ? nodeUnderTest.value : null
    transport.testInputId = mode === 'node_test' ? selectedInputId.value : null
    run.workflowId.value = workflowId
    run.inputField.value = inputField.value
    run.idea.value = inputValue.value
    run.gatesMode.value = 'human'
    try {
      run.descriptor.value = await transport.getGraph(workflowId)
    } catch {
      // A descriptor this client cannot read costs the per-node usage table and
      // nothing else: node STATES come off the frames, which name their own
      // node. Losing the run over it would be the wrong trade.
    }
    await run.launch()
    if (run.lastError.value) problem.value = run.lastError.value
    stateResult.value = null
    stateStep.value = 0
  }

  const startRun = (): Promise<void> => launch('test')
  const startNodeTest = (): Promise<void> => launch('node_test')

  /** D5: parse, bound, price and compile. No run row, no token, no charge. */
  async function runDryRun(): Promise<void> {
    const workflowId = options.documentId()
    if (!workflowId) {
      problem.value = 'Save this graph before a dry run.'
      return
    }
    dryRunPending.value = true
    try {
      dryRunResult.value = await api.dryRun(DRY_RUN_SESSION, workflowId)
      problem.value = ''
    } catch (error) {
      dryRunResult.value = null
      problem.value = messageOf(error, 'the dry run could not be made.')
    } finally {
      dryRunPending.value = false
    }
  }

  /* ── the Code tab ────────────────────────────────────────────────────── */

  async function loadCompiled(): Promise<void> {
    const id = options.documentId()
    if (!id) {
      compiled.value = null
      compiledProblems.value = []
      return
    }
    compiledPending.value = true
    try {
      compiled.value = await api.compiled(id)
      compiledProblems.value = []
      problem.value = ''
    } catch (error) {
      compiled.value = null
      // A document that no longer compiles answers 422 with the compiler's own
      // problem list, which is the useful half - a preview that showed the last
      // version that worked would be the most misleading thing on the page.
      compiledProblems.value =
        error instanceof BuilderPublishRefusedError ? error.problems : []
      problem.value = messageOf(error, 'this graph could not be compiled.')
    } finally {
      compiledPending.value = false
    }
  }

  /* ── the State tab ───────────────────────────────────────────────────── */

  /**
   * The highest frame this run has emitted, which is the slider's ceiling.
   *
   * Frame sequences are allocated gapless per run, so every integer from 1 to
   * here names a real frame and the server's "no frame N" 404 is unreachable
   * from the slider. That is a property of the allocator, not an assumption
   * about it: `events/` says so, and a gap would show as a 404 the tab renders
   * rather than as a wrong state.
   */
  const maxStep = computed(() => run.lastSequence.value)

  async function loadState(step: number): Promise<void> {
    const id = run.runId.value
    if (!id) return
    stateStep.value = step
    statePending.value = true
    try {
      stateResult.value = await api.runState(id, step > 0 ? step : undefined)
      problem.value = ''
    } catch (error) {
      stateResult.value = null
      problem.value = messageOf(error, 'the state at that step could not be read.')
    } finally {
      statePending.value = false
    }
  }

  /**
   * The state, grouped: the author's own keys first, then the four reserved
   * namespaces in a fixed order.
   *
   * The author's keys first because they are the ones that answer "what is this
   * run doing"; the reserved ones kept rather than hidden because
   * `__builder__` and the `turns__` counters are the interesting half of "why
   * did this run take the branch it took" - which is the reason the server does
   * not strip them either.
   */
  const stateGroups = computed<StateGroup[]>(() => {
    const state = stateResult.value?.state ?? {}
    const groups: StateGroup[] = [
      { prefix: '', label: 'This graph', entries: [] },
      { prefix: 'out__', label: 'Node outputs', entries: [] },
      { prefix: 'err__', label: 'Node errors', entries: [] },
      { prefix: 'turns__', label: 'Gate turns', entries: [] },
      { prefix: '__builder__', label: 'Graph metadata', entries: [] },
    ]
    for (const key of Object.keys(state).sort()) {
      const prefix = RESERVED_STATE_PREFIXES.find((candidate) => key.startsWith(candidate)) ?? ''
      const group = groups.find((entry) => entry.prefix === prefix)
      group?.entries.push({ key, label: key.slice(prefix.length) || key, value: state[key] })
    }
    return groups.filter((group) => group.entries.length > 0)
  })

  return {
    // the panel
    open,
    tab,
    height,
    paneHeight,
    panelHeight,
    maxHeight,
    setHeight,
    toggle,
    selectTab,
    // saved inputs
    testInputs,
    selectedInputId,
    selectedInput,
    inputValue,
    inputField,
    savingInput,
    loadTestInputs,
    select,
    saveTestInput,
    removeTestInput,
    // running
    run,
    transport,
    canRun,
    runBlockedReason,
    startRun,
    startNodeTest,
    // node test
    nodeUnderTest,
    testableNodes,
    missingMocks,
    canRunNode,
    // dry run
    dryRunResult,
    dryRunPending,
    runDryRun,
    // code
    compiled,
    compiledPending,
    compiledProblems,
    loadCompiled,
    // state
    stateStep,
    stateResult,
    statePending,
    maxStep,
    stateGroups,
    loadState,
    // shared
    problem,
  }
}

export type FlowTest = ReturnType<typeof useFlowTest>

/**
 * Every node upstream of `nodeId`, transitively, by the document's own edges.
 *
 * Attachment edges are skipped: an attachment is a possession rather than a
 * step, so it writes no `out__` slot and a mock for one would be a key the
 * replay never reads. A cycle is walked once - `seen` guards it - because a
 * builder graph may close a loop through a router and an ancestor walk that
 * did not would not return.
 */
export function ancestorsOf(document: BuilderDocument, nodeId: string): string[] {
  const kinds = new Map(document.nodes.map((node) => [String(node.id), node.kind]))
  const incoming = new Map<string, string[]>()
  for (const edge of document.edges) {
    const source = String(edge.source)
    if (isAttachmentKind(kinds.get(source) ?? 'agent')) continue
    const target = String(edge.target)
    incoming.set(target, [...(incoming.get(target) ?? []), source])
  }
  const seen = new Set<string>()
  const queue = [...(incoming.get(nodeId) ?? [])]
  while (queue.length) {
    const next = queue.shift() as string
    if (next === nodeId || seen.has(next)) continue
    seen.add(next)
    queue.push(...(incoming.get(next) ?? []))
  }
  return [...seen].sort()
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}
