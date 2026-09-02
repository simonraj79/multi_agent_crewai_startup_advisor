import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import type { Edge, Node } from '@vue-flow/core'
import { MOCK_GRAPH } from '../data/mockGraph'
import { studioApi, type ConnectionStatus, type GatesMode, type LogFormat, type StudioApiLike, type TransportMode } from '../services/studioApi'
import type {
  RunResult,
  CallChip,
  ChatEntry,
  FrameData,
  GraphDescriptor,
  NodeRunState,
  PendingGate,
  RunStatus,
  UsageMetrics,
  VerdictDimensionScores,
  VerdictSummary,
} from '../types/studio'

/**
 * How a node is drawn. `router` and `step` are deliberately distinct from
 * `agent`: both are deterministic, both call zero models, and drawing them as
 * agent cards would put the cost and latency of the run in the wrong places.
 */
export type StudioNodeKind = 'agent' | 'gate' | 'output' | 'quarantine' | 'router' | 'step'

export interface StudioNodeData extends Record<string, unknown> {
  label: string
  eyebrow: string
  description: string
  kind: StudioNodeKind
  state: NodeRunState
  model?: string
  tool?: string
  usage: UsageMetrics
  /** Frames the stream attributed to this node. Drives the quarantine badge. */
  frameCount: number
  /**
   * How many times this node has STARTED in this run. 0 before it first runs,
   * 1 on a straight pass, 2+ once a revise loop has sent the crew back.
   *
   * This cannot be recovered from `state`: a node that ran four times and a
   * node that ran once are both `completed` afterwards, and the map holds no
   * history. Counting the transition into `running` is the only honest source,
   * which is why it is done where frames arrive rather than derived in a view.
   */
  visits: number
  /**
   * The tool or model call in flight on this node right now, or null.
   *
   * This exists because a 60-second branch and a 6-second branch looked
   * IDENTICAL. Every animation on a running node is an infinite loop with no
   * state, so it says "an animation is playing", never "work is progressing" -
   * and an operator watching one for six minutes reasonably concluded the app
   * had hung. It had not: Firecrawl was scraping, and the backend was putting
   * the literal query string on the wire the whole time.
   *
   * `query` is the point. `events/serializer.py` lifts it onto BOTH the
   * `before` and `after` tool frames precisely so a client can show what a
   * branch is asking for while it asks - and until now nothing in
   * `frontend/src` read the field at all.
   *
   * `startedAt` drives the only honest progress signal an agent can offer:
   * elapsed wall clock. There is no denominator to put in a progress bar - the
   * agent does not know how far through it is either - but a number that
   * changes every second refutes "it is stuck" in a way no spinner can.
   */
  activeCall: ActiveCall | null
}

export interface ActiveCall {
  /** `research_market_landscape`, or a model id for an llm call. */
  label: string
  kind: 'tool' | 'llm'
  /** The literal query the tool was handed, when it reported one. */
  query?: string
  /** Epoch ms, for the elapsed timer. */
  startedAt: number
}

export interface StudioEdgeData extends Record<string, unknown> {
  label?: string
  active: boolean
}

const initialUsage = (): UsageMetrics => ({
  promptTokens: 0,
  completionTokens: 0,
  totalTokens: 0,
  callCount: 0,
  costUsd: 0,
  elapsedMs: 0,
})

const DEFAULT_WORKFLOW_ID = 'idea-validator'
/** What both built-in workflows call their request input. `BUILTIN_WORKFLOW_INPUT_FIELDS`. */
const DEFAULT_INPUT_FIELD = 'idea'
const SESSION_STORAGE_KEY = 'validator-session-id'
const ACTIVE_RUN_STORAGE_KEY = 'validator-active-run'

/**
 * Mirrors `QUARANTINE_NODE_ID` in `src/brief_crew/events/registry.py`. Frames the
 * backend could not join to a declared node are attributed here on purpose, so
 * the loss is visible in the graph instead of silently disappearing.
 */
export const QUARANTINE_NODE_ID = 'unattributed'

/**
 * How long a traversal keeps marching after its `edge_taken` frame. Every edge
 * gets its own timer: the three research branches leave the scope gate at
 * slightly different moments and must all animate at once, so a single shared
 * deadline cannot be used to expire them.
 */
const EDGE_ACTIVE_MS = 3200

/** A run in one of these states is history: nothing more will stream for it. */
const TERMINAL_STATUSES: readonly RunStatus[] = ['completed', 'cancelled', 'error']

interface StoredRunContext {
  version: 1
  runId: string
  sessionId: string
  workflowId: string
  /**
   * The `inputs` key this run was launched under.
   *
   * Optional, and read with a fallback, because contexts written before builder
   * graphs existed do not carry it - bumping `version` would have discarded
   * every in-flight run on the deploy that shipped this, which is the opposite
   * of what refresh recovery is for. Absent means `idea`, which is what both
   * built-in workflows declare and what every such context was launched with.
   */
  inputField?: string
}

/**
 * Every storage access is guarded. A private window, blocked site data or a
 * full quota throws on read and on write, and the console must still render.
 */
function readStorage(key: string): string | null {
  try {
    return globalThis.localStorage?.getItem(key) ?? null
  } catch {
    return null
  }
}

function writeStorage(key: string, value: string): void {
  try {
    globalThis.localStorage?.setItem(key, value)
  } catch {
    // Storage is unavailable; refresh recovery is lost but the app still runs.
  }
}

function removeStorage(key: string): void {
  try {
    globalThis.localStorage?.removeItem(key)
  } catch {
    // Same as above: never let storage failure reach the render path.
  }
}

function readStoredRun(): StoredRunContext | null {
  const value = readStorage(ACTIVE_RUN_STORAGE_KEY)
  if (!value) return null
  try {
    const parsed = JSON.parse(value) as Partial<StoredRunContext>
    if (parsed.version !== 1 || !parsed.runId || !parsed.sessionId || !parsed.workflowId) return null
    return parsed as StoredRunContext
  } catch {
    return null
  }
}

function persistRun(context: StoredRunContext): void {
  writeStorage(ACTIVE_RUN_STORAGE_KEY, JSON.stringify(context))
  writeStorage(SESSION_STORAGE_KEY, context.sessionId)
}

function clearStoredRun(): void {
  removeStorage(ACTIVE_RUN_STORAGE_KEY)
}

function newSessionId(): string {
  return (
    globalThis.crypto?.randomUUID?.()
    ?? `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  )
}

/** Which workflow this console drives, when it is not the built-in validator. */
export interface ValidatorRunOptions {
  /**
   * A published workflow id. Defaults to `idea-validator`.
   *
   * A run already in flight still wins: `initialize` overwrites this from the
   * stored run context, because that run is the operator's money and the
   * console must show the graph it is actually streaming. The requested
   * workflow therefore applies on any load with nothing in flight, which is
   * every load after a publish.
   */
  workflowId?: string
  /**
   * The key inside `inputs` that this workflow's run request must carry - a
   * builder graph's own `input_field`. Defaults to `idea`.
   */
  inputField?: string
}

export function useValidatorRun(
  api: StudioApiLike = studioApi,
  options: ValidatorRunOptions = {},
) {
  const storedAtLoad = readStoredRun()
  const sessionId = storedAtLoad?.sessionId ?? readStorage(SESSION_STORAGE_KEY) ?? newSessionId()
  writeStorage(SESSION_STORAGE_KEY, sessionId)

  const descriptor = ref<GraphDescriptor>(structuredClone(MOCK_GRAPH))
  const workflowId = ref(storedAtLoad?.workflowId ?? options.workflowId ?? DEFAULT_WORKFLOW_ID)
  const inputField = ref(storedAtLoad?.inputField ?? options.inputField ?? DEFAULT_INPUT_FIELD)
  const idea = ref('An AI tool that turns Figma files into production React')
  /**
   * Who answers the two gates. `human` pauses at both; `auto` runs the whole
   * pipeline unattended.
   *
   * `auto` by owner decision, and the API now agrees with it.
   *
   * This flipped to `human` earlier on 2026-09-01 because the deployed API
   * answered **403** for `auto` - `VALIDATOR_ALLOW_AUTO_GATES` is unset in
   * `render.yaml`. That was the right read of the server at the time and the
   * wrong read of the design: the flag exists to stop ANONYMOUS unattended
   * runs, and `create_run` now permits `auto` for any authenticated caller
   * (`service/app.py`). Sign-in is what the console requires anyway, so the
   * 403 is no longer reachable from here.
   *
   * The spend argument that justified `human` does not survive authentication
   * either. Human inaction was the cap only while nobody could be identified;
   * a signed-in run is owned, rate-limited per user, and bounded by
   * `MAX_RUN_COST_USD` ($10 by default) enforced at the step boundary. Review
   * remains one click away for anyone who wants to inspect the scope before
   * three branches go and spend money on it.
   */
  const gatesMode = ref<GatesMode>('auto')
  const status = ref<RunStatus>('idle')
  const transportMode = ref<TransportMode>('probing')
  const connection = ref<ConnectionStatus>('offline')
  const runId = ref('')
  const pendingGate = ref<PendingGate | null>(null)
  const gateSubmitting = ref(false)
  const launching = ref(false)
  const downloadStatus = ref<'idle' | 'pending' | 'success' | 'error'>('idle')
  const downloadMessage = ref('')
  const lastError = ref('')
  /**
   * Why the console is not talking to a real backend, or '' when it is.
   *
   * Kept SEPARATE from `lastError` on purpose. `launch()` clears `lastError` on
   * every attempt, so a transport diagnosis routed through it would erase
   * itself the instant the operator pressed the button that cannot work - and
   * pressing that button is exactly what someone does when the page looks
   * fine. This one is written only by `initialize()` and survives until the
   * next probe.
   */
  const transportProblem = ref('')
  /**
   * The finished validation report. The backend has always delivered this -
   * `GET /api/runs/{id}` returns it as `result` and the terminal frame carries
   * `details.result` - and the client discarded it at three separate layers,
   * so a completed run showed strictly LESS than a mid-flight one.
   */
  const report = ref<RunResult | null>(null)
  /**
   * The run's conclusion, from whichever carrier supplied it.
   *
   * TWO carriers, and the precedence between them is the point.
   *
   * 1. The `verdict` FRAME, published by the Flow the moment the `Verdict` is
   *    computed. Authoritative: it is deterministic output, it carries the
   *    whole scorecard rather than a headline, and it is emitted in BOTH gate
   *    modes. `applyVerdict` writes it and the newest frame always wins - a
   *    revise loop rescores, and the later frame is the later computation.
   * 2. The verdict GATE, rescued by `closeGate` as `gate_closed` nulls
   *    `pendingGate`. A fallback, kept for two cases that are not hypothetical:
   *    a `gates=human` run replayed from frames PREDATING this feature has only
   *    the gate, and so does any server not yet emitting the frame.
   *
   * So a gate-sourced value never overwrites a frame-sourced one, while a frame
   * overwrites anything. `source` records which happened, so the rule is
   * testable rather than merely commented. Under `gates=auto` there is no
   * verdict gate at all, which is why carrier 2 alone left the mode whose whole
   * purpose is producing this number showing a `COMPLETE` badge instead.
   */
  const verdictSummary = ref<VerdictSummary | null>(null)
  const lastSequence = ref(0)
  const droppedFrames = ref(0)
  const activeEdgeIds = ref(new Set<string>())
  const chatEntries = ref<ChatEntry[]>([])
  const usage = reactive<UsageMetrics>(initialUsage())
  const nodeStates = reactive<Record<string, NodeRunState>>({})
  const nodeUsage = reactive<Record<string, UsageMetrics>>({})
  const nodeFrames = reactive<Record<string, number>>({})
  /** Node id -> how many times it has entered `running`. See `visits`. */
  const nodeVisits = reactive<Record<string, number>>({})
  /** Node id -> the call currently in flight on it. See `ActiveCall`. */
  const nodeActiveCall = reactive<Record<string, ActiveCall | null>>({})
  /**
   * The elapsed CLOCK deliberately lives in `WorkflowNode.vue`, not here.
   *
   * A ticker in this composable would have to be read by `graphNodes` to reach
   * a node card, and `graphNodes` is a computed over all 14 nodes - so every
   * second would rebuild all 14 node objects and hand Vue Flow a fresh array to
   * diff, to animate at most three of them. The component owns an interval that
   * exists only while `activeCall` is non-null instead.
   */
  function setActiveCall(nodeId: string | null | undefined, call: ActiveCall | null): void {
    if (!nodeId) return
    nodeActiveCall[nodeId] = call
  }
  const seenFrames = new Set<string>()
  const pendingCallEntries = new Map<string, string[]>()
  /** Active edge id -> the node it feeds, so a finished branch can end it. */
  const edgeTargets = new Map<string, string>()
  const edgeTimers = new Map<string, number>()
  let unsubscribe: (() => void) | undefined
  let receiveQueue = Promise.resolve()
  let downloadTimer = 0

  const resetNodes = () => {
    for (const key of Object.keys(nodeStates)) delete nodeStates[key]
    for (const key of Object.keys(nodeUsage)) delete nodeUsage[key]
    for (const key of Object.keys(nodeFrames)) delete nodeFrames[key]
    for (const key of Object.keys(nodeVisits)) delete nodeVisits[key]
    for (const key of Object.keys(nodeActiveCall)) delete nodeActiveCall[key]
    for (const node of descriptor.value.nodes) {
      nodeStates[node.id] = 'idle'
      nodeUsage[node.id] = initialUsage()
      nodeFrames[node.id] = 0
      nodeVisits[node.id] = 0
      nodeActiveCall[node.id] = null
    }
    nodeFrames[QUARANTINE_NODE_ID] ??= 0
  }
  resetNodes()

  const graphNodes = computed<Node<StudioNodeData>[]>(() =>
    descriptor.value.nodes.map((node) => ({
      id: node.id,
      type: 'workflow',
      position: node.position,
      draggable: false,
      selectable: false,
      connectable: false,
      data: {
        label: node.label,
        eyebrow: node.eyebrow,
        description: node.description,
        kind: nodeKind(node.kind),
        state: nodeStates[node.id] ?? 'idle',
        model: node.model,
        tool: node.tool,
        usage: nodeUsage[node.id] ?? initialUsage(),
        frameCount: nodeFrames[node.id] ?? 0,
        visits: nodeVisits[node.id] ?? 0,
        activeCall: nodeActiveCall[node.id] ?? null,
      },
    })),
  )

  const graphEdges = computed<Edge<StudioEdgeData>[]>(() =>
    descriptor.value.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'workflow',
      data: { label: edge.label ?? undefined, active: activeEdgeIds.value.has(edge.id) },
    })),
  )

  const quarantinedFrames = computed(() => nodeFrames[QUARANTINE_NODE_ID] ?? 0)
  const isActive = computed(() => ['queued', 'running', 'waiting', 'stopping'].includes(status.value))
  const canLaunch = computed(() => idea.value.trim().length >= 12 && !isActive.value && !launching.value)
  const primaryLabel = computed(() =>
    launching.value
      ? 'Launching…'
      : status.value === 'completed' || status.value === 'cancelled' || status.value === 'error'
      ? 'Relaunch'
      : status.value === 'running' || status.value === 'waiting'
        ? 'Send'
        : 'Launch',
  )

  /**
   * The single place a run status is written. A run that has reached a terminal
   * state must not be restored again on the next page load, so the saved
   * pointer is dropped the moment it lands there.
   */
  function setStatus(next: RunStatus): void {
    const wasTerminal = TERMINAL_STATUSES.includes(status.value)
    status.value = next
    if (!TERMINAL_STATUSES.includes(next)) return
    clearStoredRun()
    // Nothing further will stream, so no traversal should still be marching.
    clearEdgeAnimations()
    // The frame's copy of the report is clipped at 4096 characters; the
    // snapshot's is not. Collect the full one exactly once per run.
    if (!wasTerminal && next === 'completed') void fetchFullReport()
  }

  async function initialize(): Promise<void> {
    transportMode.value = await api.initialize()
    transportProblem.value = api.probeFailure ?? ''
    const storedRun = readStoredRun()
    if (storedRun) {
      // Both together or neither. Taking the workflow id from the stored run
      // while leaving `inputField` at whatever the caller asked for would
      // launch the restored workflow under another graph's input key, which is
      // a 422 the operator never typed anything to cause.
      workflowId.value = storedRun.workflowId
      inputField.value = storedRun.inputField ?? DEFAULT_INPUT_FIELD
    }
    try {
      descriptor.value = await api.getGraph(workflowId.value)
      resetNodes()
    } catch (error) {
      transportMode.value = 'mock'
      descriptor.value = structuredClone(MOCK_GRAPH)
      resetNodes()
      lastError.value = error instanceof Error ? error.message : 'Graph could not be loaded.'
    }

    if (!storedRun) return
    await restoreRun(storedRun)
  }

  async function launch(): Promise<void> {
    if (!canLaunch.value) return
    const previousStatus = status.value
    launching.value = true
    lastError.value = ''
    try {
      const response = await api.startRun(
        sessionId,
        idea.value.trim(),
        workflowId.value,
        gatesMode.value,
        inputField.value,
      )
      transportMode.value = api.mode
      /*
       * The banner must be refreshed with the mode, never left behind.
       *
       * `startRun` re-probes whenever the transport is mocked, so this is the
       * RECOVERY path: a cold Render service failed the page-load probe, the
       * operator clicked Launch rather than reloading, and the second probe
       * succeeded. Updating `transportMode` alone left the non-dismissible
       * "Demonstration mode - no agent is running" alert sitting over a real
       * run that was spending real money - the exact inverse of the defect
       * this banner exists to prevent, and it contradicted the header chip two
       * panels away.
       */
      transportProblem.value = api.probeFailure ?? ''
      resetRun()
      runId.value = response.run_id
      setStatus(response.status)
      persistRun({
        version: 1,
        runId: response.run_id,
        sessionId,
        workflowId: workflowId.value,
        inputField: inputField.value,
      })
      connectStream()
    } catch (error) {
      setStatus(runId.value ? previousStatus : 'error')
      lastError.value = error instanceof Error ? error.message : 'The run could not be started.'
    } finally {
      launching.value = false
    }
  }

  async function restoreRun(context: StoredRunContext): Promise<void> {
    resetRun()
    runId.value = context.runId
    try {
      const snapshot = await api.getRun(context.runId)
      if (TERMINAL_STATUSES.includes(snapshot.status)) {
        // Refresh recovery exists for a run that is still in flight. A finished
        // one is history: drop the pointer so the next load starts clean rather
        // than re-opening the same stale result forever.
        //
        // The report is the exception. It is what the operator came back for,
        // and the already-cleared pointer bounds how long it can linger - this
        // shows the conclusion once, not forever.
        clearStoredRun()
        resetRun()
        runId.value = context.runId
        // Replay the frames, do not merely take the result.
        //
        // The body alone restores a report with no verdict badge, no
        // confidence and an entirely idle graph, because BOTH of those come
        // from frames: `applyGate` puts the score on `pendingGate`, `closeGate`
        // rescues it into `verdictSummary` as the gate closes, and node state
        // is per-frame. `ValidationReport` carries no verdict field
        // (`schemas/validator.py:547-551`), so there is nowhere else to get it.
        //
        // Ordering matters. The frames are replayed first so the terminal
        // RUN_STATE inside them lands while `runId` is set, then the snapshot's
        // result is applied last - it is the unclipped copy, and
        // `captureResult` keeps the longer body either way.
        try {
          const frames = await api.getFrames(context.runId, 0)
          frames.sort((left, right) => left.seq - right.seq).forEach(applyFrame)
        } catch {
          // Frames expire before results do. A report with no verdict badge is
          // still the thing the operator came back for.
        }
        captureResult(snapshot.result)
        // Re-open ONLY if there is something to show. A finished run whose
        // report has aged out leaves a dead graph under a "completed" badge and
        // nothing to read, which is worse than the clean console the operator
        // would otherwise get - so in that case the original contract stands
        // and the run is dropped as history.
        if (!report.value) {
          resetRun()
          return
        }
        Object.assign(usage, snapshot.usage)
        setStatus(snapshot.status)
        return
      }
      const frames = await api.getFrames(context.runId, 0)
      frames.sort((left, right) => left.seq - right.seq).forEach(applyFrame)
      const snapshotSequence = snapshot.frames.last_seq ?? lastSequence.value
      setStatus(snapshot.status)
      pendingGate.value = snapshot.pending_gate
      droppedFrames.value = snapshot.frames.dropped
      Object.assign(usage, snapshot.usage)
      captureResult(snapshot.result)
      frames.filter((frame) => frame.seq > snapshotSequence).forEach(applyPostSnapshotFrame)
      if (['queued', 'running', 'waiting', 'stopping'].includes(status.value)) connectStream()
    } catch (error) {
      // The saved run is unreachable (expired, purged, or a different server).
      // Keeping the pointer would reproduce this error on every future load.
      clearStoredRun()
      setStatus('error')
      lastError.value = error instanceof Error ? error.message : 'The saved run could not be restored.'
    }
  }

  function connectStream(): void {
    unsubscribe?.()
    unsubscribe = api.subscribe(runId.value, sessionId, {
      onFrame: queueFrame,
      onStatus: (value) => { connection.value = value },
      getAfter: () => lastSequence.value,
    })
  }

  function applyPostSnapshotFrame(frame: FrameData): void {
    if (frame.kind === 'run_state') applyRunState(frame)
    if (frame.kind === 'verdict') applyVerdict(frame)
    if (frame.kind === 'gate_open') applyGate(frame)
    if (frame.kind === 'gate_expired' || frame.kind === 'gate_alert') applyGateWatch(frame)
    if (frame.kind === 'gate_closed') {
      closeGate()
      setStatus('running')
    }
    if (frame.kind === 'token') applyTokenUsage(frame)
    if (frame.kind === 'metrics') applyMetrics(frame)
    if (frame.kind === 'error') {
      setStatus('error')
      lastError.value = frame.message
    }
  }

  function queueFrame(frame: FrameData): void {
    receiveQueue = receiveQueue.then(() => ingestFrame(frame)).catch((error: unknown) => {
      lastError.value = error instanceof Error ? error.message : 'A frame could not be processed.'
    })
  }

  async function ingestFrame(frame: FrameData): Promise<void> {
    const key = `${frame.run_id}:${frame.seq}`
    if (seenFrames.has(key) || frame.run_id !== runId.value) return

    if (frame.seq > lastSequence.value + 1) {
      const replay = await api.getFrames(frame.run_id, lastSequence.value)
      const missing = replay
        .filter((candidate) => candidate.seq < frame.seq)
        .sort((left, right) => left.seq - right.seq)
      if (missing.length !== frame.seq - lastSequence.value - 1) {
        droppedFrames.value += frame.seq - lastSequence.value - 1 - missing.length
      }
      missing.forEach(applyFrame)
    }
    applyFrame(frame)
  }

  function applyFrame(frame: FrameData): void {
    const key = `${frame.run_id}:${frame.seq}`
    if (seenFrames.has(key)) return
    seenFrames.add(key)
    lastSequence.value = Math.max(lastSequence.value, frame.seq)
    if (frame.node_id) nodeFrames[frame.node_id] = (nodeFrames[frame.node_id] ?? 0) + 1

    if (frame.kind === 'run_state') applyRunState(frame)
    if (frame.kind === 'node_state' && frame.node_id) applyNodeState(frame)
    if (frame.kind === 'edge_taken') applyEdge(frame)
    if (frame.kind === 'verdict') applyVerdict(frame)
    if (frame.kind === 'gate_open') applyGate(frame)
    if (frame.kind === 'gate_expired' || frame.kind === 'gate_alert') applyGateWatch(frame)
    if (frame.kind === 'gate_closed') {
      closeGate()
      if (frame.node_id) setNodeState(frame.node_id, 'completed')
      setStatus('running')
    }
    if (frame.kind === 'token') applyTokenUsage(frame)
    if (frame.kind === 'metrics') applyMetrics(frame)
    if (frame.kind === 'error') {
      setStatus('error')
      lastError.value = frame.message
    }
    if (!['token', 'metrics'].includes(frame.kind)) appendChat(frame)
  }

  /**
   * `details.status` is the frame's own statement about the run and always
   * wins. The `event_type` fallback below exists because that key has not
   * always been there: the real serializer emitted `WORKFLOW_END` carrying only
   * `{result}`, this function read `details.status`, found nothing, and the
   * console sat on "queued" through an entire finished run. Every double in the
   * suite happened to send a status, so nothing failed.
   *
   * A `run_state` frame carrying `WORKFLOW_END` and no status can only be a
   * completion. A flow that failed is emitted as `FrameKind.ERROR`
   * (`events/serializer.py`, `FlowFailedEvent`) and reaches `error` through
   * `applyFrame` without passing here, and a cancellation is emitted by
   * `service/registry.py` with an explicit `status: "cancelled"` that the
   * branch above catches first.
   *
   * `details.nested` is the second lock on that fallback. CrewAI fires flow
   * lifecycle events for the flows it runs *inside* a run - its own
   * `AgentExecutor` is a Flow - and the server used to forward them as
   * `WORKFLOW_END` on the `workflow` node, so a live run reported completing
   * when its first agent finished. The server now marks them and never sends
   * them as `run_state` (`events/serializer.py::FlowScope`), but this end reads
   * the same marker anyway, because the cost of believing one is asymmetric:
   * `completed` is terminal, and `setStatus` then drops the stored run pointer,
   * permanently destroying refresh recovery for a run still in flight.
   */
  /**
   * Keep the score before the gate card that carried it disappears. Only the
   * verdict gate supplies these, so a scope gate closing leaves the value
   * untouched rather than blanking it.
   *
   * The fallback half of the precedence rule: a gate carries the headline only,
   * and never overwrites what the frame computed. It still matters, because a
   * run replayed from frames older than the verdict frame has nothing else.
   */
  function closeGate(): void {
    const gate = pendingGate.value
    if (gate?.verdict && verdictSummary.value?.source !== 'frame') {
      verdictSummary.value = {
        verdict: gate.verdict,
        confidence: gate.confidence ?? null,
        compositeScore: null,
        confidenceBand: null,
        provisional: null,
        fatalFloors: [],
        decisionReason: null,
        dimensions: null,
        source: 'gate',
      }
    }
    pendingGate.value = null
    gateSubmitting.value = false
  }

  /**
   * The authoritative carrier. See `verdictSummary` for the precedence rule:
   * the newest frame always wins, including over an earlier frame, because a
   * revise loop sends the Synthesist back to rescore and the second frame is
   * the second computation.
   *
   * A frame the parser cannot make sense of is dropped rather than allowed to
   * blank a verdict already on screen - `details` is `Record<string, unknown>`
   * and this is the one frame the whole product exists to deliver.
   */
  function applyVerdict(frame: FrameData): void {
    const parsed = parseVerdictFrame(frame.details)
    if (parsed) verdictSummary.value = parsed
  }

  /**
   * Accept a report from either carrier, keeping whichever body is LONGER.
   *
   * The two carriers are not equivalent and the difference is not cosmetic.
   * The terminal `RUN_STATE` frame goes through `FieldBoundedSerializer.clip`,
   * which cuts every string at `SerializerLimits.max_string` = 4096 with no
   * marker (`events/serializer.py:214,241,309`). Only the SNAPSHOT copy is
   * exempted, by `registry.py::_clip_run_result` re-reading the body at
   * `MAX_RUN_RESULT_BODY_CHARS` (64 KiB).
   *
   * So the frame arrives first and is usually truncated mid-sentence, and a
   * naive first-wins rule showed the operator a quarter of their report with
   * no ellipsis and no warning. Longest-wins makes the two carriers safe to
   * apply in either order, which matters because the snapshot fetch below is
   * asynchronous and races the frame.
   */
  function captureResult(value: unknown): void {
    if (!isRecord(value)) return
    const body = value.markdown_body
    if (typeof body !== 'string' || !body.trim()) return
    const existing = report.value?.markdown_body
    if (typeof existing === 'string' && existing.length >= body.length) return
    report.value = value as RunResult
  }

  /**
   * Fetch the unclipped report once the run is over.
   *
   * Nothing else on the live path ever calls `getRun` - `restoreRun` is its
   * only other caller, and that runs on page load - so without this the
   * complete body is fetched by nobody and the 64 KiB exemption the server
   * goes to trouble to provide is never collected.
   *
   * Failures are swallowed deliberately: the clipped frame body is already on
   * screen, and replacing a partial report with an error banner would be a
   * downgrade. The run is finished either way.
   */
  async function fetchFullReport(): Promise<void> {
    const id = runId.value
    if (!id) return
    try {
      const snapshot = await api.getRun(id)
      captureResult(snapshot.result)
    } catch {
      /* keep whatever the frame delivered */
    }
  }

  function applyRunState(frame: FrameData): void {
    if (frame.details.nested === true) return
    captureResult(frame.details.result)
    recoverIdea(frame)
    const next = frame.details.status
    if (next === 'failed') {
      setStatus('error')
    } else if (next === 'cancelling') {
      setStatus('stopping')
    } else if (typeof next === 'string' && ['queued', 'running', 'waiting', 'cancelled', 'completed', 'error'].includes(next)) {
      setStatus(next as RunStatus)
    } else if (frame.event_type === 'WORKFLOW_END') {
      setStatus('completed')
    } else if (frame.event_type === 'WORKFLOW_START') {
      setStatus('running')
    }
  }

  /**
   * Put the run's own idea back in the box after a reload.
   *
   * `idea` was a plain ref seeded with a hardcoded default and assigned
   * nowhere, so refreshing mid-run restored the graph, the gates and the report
   * correctly above a textarea that had silently reverted to "An AI tool that
   * turns Figma files into production React". The operator's next Relaunch
   * would then have run something they never typed.
   *
   * The fix needs no new persistence and no new API field: the run already
   * records what it was launched with, on its own opening `RUN_STATE` frame,
   * and `restoreRun` replays every frame. Reading it back from there means the
   * box shows what the run is actually about rather than what a stale default
   * happened to say.
   *
   * Only the opening frame carries `inputs` - the terminal one carries
   * `result` - and only a non-empty string is taken, so a malformed frame
   * leaves whatever the operator has typed alone.
   */
  function recoverIdea(frame: FrameData): void {
    const inputs = frame.details.inputs
    if (typeof inputs !== 'object' || inputs === null) return
    const recovered = (inputs as Record<string, unknown>).idea
    if (typeof recovered !== 'string' || !recovered.trim()) return
    idea.value = recovered
  }

  function applyNodeState(frame: FrameData): void {
    const nodeId = frame.node_id as string
    // Only START and END are real. `UIEventType` has twelve members and not one
    // contains WAITING, COMPLETED or ERROR, so the three tests that used to sit
    // here could never fire against this backend - they matched only the mock
    // transport's invented `NODE_WAITING`, which is how they survived. The
    // waiting state is set by `applyGate`, which is the only thing that knows a
    // human is being asked; the error state comes off the frame's own level.
    if (frame.event_type.includes('START')) setNodeState(nodeId, 'running')
    if (frame.event_type.includes('END')) setNodeState(nodeId, 'completed')
    if (frame.level === 'ERROR') setNodeState(nodeId, 'error')
    // A node that has settled cannot still have a call in flight. Belt and
    // braces behind `completeCallEntry`: a dropped or out-of-order `after`
    // frame would otherwise leave a timer counting up forever on a finished
    // node, which is a worse lie than showing nothing.
    if (frame.event_type.includes('END') || frame.level === 'ERROR') {
      setActiveCall(nodeId, null)
    }
  }

  /**
   * A node reaching a settled state ends every traversal feeding it. Without
   * this an edge would keep marching for the rest of its timer after the branch
   * it points at has already finished.
   */
  function setNodeState(nodeId: string, state: NodeRunState): void {
    // A visit is an EDGE into an active state, not the state itself. CrewAI
    // re-emits NODE_START on retries and the stream replays on reconnect, so
    // counting every assignment would inflate the number on a page refresh -
    // the one moment an operator is most likely to be reading it.
    //
    // `waiting` counts as well as `running`, because a gate node never becomes
    // `running`: `applyGate` is the only thing that touches it and it sets
    // `waiting`. Without this a gate that asked the operator three times
    // reported no passes at all, which is precisely backwards - the gate is
    // the node an operator revisits most, and the count is the only record
    // that they did.
    const active = state === 'running' || state === 'waiting'
    if (active && nodeStates[nodeId] !== state) {
      nodeVisits[nodeId] = (nodeVisits[nodeId] ?? 0) + 1
    }
    nodeStates[nodeId] = state
    if (state === 'completed' || state === 'error') deactivateEdgesInto(nodeId)
  }

  /**
   * The fan-out releases Market, Sentiment and Feasibility as siblings, so
   * several edges are live at the same time with independent start moments.
   * Each one is tracked and expired on its own.
   */
  function applyEdge(frame: FrameData): void {
    const from = typeof frame.details.from === 'string' ? frame.details.from : ''
    const to = typeof frame.details.to === 'string' ? frame.details.to : ''
    const edgeId = descriptor.value.edges.find(
      (edge) => edge.source === from && edge.target === to,
    )?.id ?? `${from}-${to}`
    activateEdge(edgeId, to)
  }

  function activateEdge(edgeId: string, target: string): void {
    if (!edgeId) return
    const existing = edgeTimers.get(edgeId)
    if (existing) window.clearTimeout(existing)
    activeEdgeIds.value.add(edgeId)
    edgeTargets.set(edgeId, target)
    edgeTimers.set(edgeId, window.setTimeout(() => deactivateEdge(edgeId), EDGE_ACTIVE_MS))
  }

  function deactivateEdge(edgeId: string): void {
    const timer = edgeTimers.get(edgeId)
    if (timer) window.clearTimeout(timer)
    edgeTimers.delete(edgeId)
    edgeTargets.delete(edgeId)
    activeEdgeIds.value.delete(edgeId)
  }

  function deactivateEdgesInto(nodeId: string): void {
    for (const [edgeId, target] of [...edgeTargets]) {
      if (target === nodeId) deactivateEdge(edgeId)
    }
  }

  function clearEdgeAnimations(): void {
    for (const timer of edgeTimers.values()) window.clearTimeout(timer)
    edgeTimers.clear()
    edgeTargets.clear()
    activeEdgeIds.value.clear()
  }

  function applyGate(frame: FrameData): void {
    const details = frame.details
    const options = Array.isArray(details.options) ? details.options : []
    const fields = typeof details.fields === 'object' && details.fields ? details.fields as Record<string, string> : undefined
    // The server already pruned `fields` to what an edit can reach; everything
    // else arrives here to be read, not typed into.
    const derived = Array.isArray(details.derived)
      ? (details.derived as PendingGate['derived'])
      : undefined
    pendingGate.value = {
      gateId: String(details.gate_id ?? `gate-${frame.seq}`),
      nodeId: frame.node_id ?? '',
      title: String(details.title ?? 'Operator review'),
      summary: String(details.summary ?? frame.message),
      editable: Boolean(details.editable),
      expiresAt: typeof details.expires_at === 'string' ? details.expires_at : undefined,
      expired: details.expired === true,
      options: options.map((option) => option as PendingGate['options'][number]),
      fields,
      derived,
      verdict: typeof details.verdict === 'string' ? details.verdict : undefined,
      confidence: typeof details.confidence === 'number' ? details.confidence : undefined,
    }
    // The node the run is parked on must say so. `applyNodeState` looks for a
    // WAITING event_type, but no member of `UIEventType` contains that word - a
    // gate arrives as GATE_OPEN / HUMAN_INTERACTION - so that branch never fires
    // and the paused node stayed `idle`, drawn identically to a node that has
    // never run. The live graph is the whole premise of this console, and at the
    // one moment it is asking the operator for something it was pointing at
    // nothing. `gate_closed` already sets the same node to `completed`, so this
    // is the missing half of that pair, not a new concept.
    if (frame.node_id) setNodeState(frame.node_id, 'waiting')
    setStatus('waiting')
  }

  /**
   * PRD F03/R-2. `gate_expired` and `gate_alert` are the server telling the
   * operator the deadline slipped - nothing more. The run stays WAITING, the
   * gate stays open, and the reply path stays available, so this only ever
   * annotates the gate the operator is already looking at.
   */
  function applyGateWatch(frame: FrameData): void {
    const gate = pendingGate.value
    const gateId = typeof frame.details.gate_id === 'string' ? frame.details.gate_id : ''
    if (!gate || (gateId && gate.gateId !== gateId)) return
    const overdue = Number(frame.details.overdue_seconds)
    pendingGate.value = {
      ...gate,
      expired: true,
      alerting: gate.alerting || frame.kind === 'gate_alert',
      overdueSeconds: Number.isFinite(overdue) ? overdue : gate.overdueSeconds,
    }
  }

  function applyTokenUsage(frame: FrameData): void {
    const frameUsage = usageFromDetails(frame.details)
    addUsage(usage, frameUsage)
    if (frame.node_id && nodeUsage[frame.node_id]) addUsage(nodeUsage[frame.node_id], frameUsage)
  }

  function applyMetrics(frame: FrameData): void {
    const metrics = usageFromDetails(frame.details, 0)
    usage.elapsedMs = metrics.elapsedMs || usage.elapsedMs
    usage.callCount = Math.max(usage.callCount, metrics.callCount)
  }

  function appendChat(frame: FrameData): void {
    const stage = String(frame.details.stage ?? '')
    if ((frame.kind === 'llm' || frame.kind === 'tool') && stage === 'chunk') return
    if ((frame.kind === 'llm' || frame.kind === 'tool') && stage !== 'before' && completeCallEntry(frame)) return

    const call = toCallChip(frame)
    if (call?.active && (frame.kind === 'tool' || frame.kind === 'llm')) {
      // `query` has been on this frame all along and nothing read it.
      const query = frame.details.query
      setActiveCall(frame.node_id, {
        label: call.label,
        kind: frame.kind,
        query: typeof query === 'string' && query.trim() ? query : undefined,
        startedAt: call.startedAt,
      })
    }
    const entry: ChatEntry = {
      id: `${frame.run_id}-${frame.seq}`,
      seq: frame.seq,
      nodeId: frame.node_id,
      actor: actorFor(frame),
      message: frame.message,
      timestamp: new Date(frame.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      variant: frame.level === 'ERROR' ? 'error' : frame.level === 'WARNING' ? 'warning' : frame.node_id ? 'agent' : 'system',
      calls: call ? [call] : [],
    }
    chatEntries.value.push(entry)
    if (call?.active) {
      const key = callKey(frame)
      pendingCallEntries.set(key, [...(pendingCallEntries.get(key) ?? []), entry.id])
    }
  }

  function toCallChip(frame: FrameData): CallChip | null {
    if (frame.kind !== 'llm' && frame.kind !== 'tool') return null
    const stage = String(frame.details.stage ?? '')
    return {
      id: String(frame.details.call_id ?? `call-${frame.seq}`),
      kind: frame.kind,
      label: String(frame.details.tool ?? frame.details.model ?? frame.kind),
      startedAt: Number.isNaN(Date.parse(frame.ts)) ? Date.now() : Date.parse(frame.ts),
      durationMs: frame.duration_ms,
      active: stage === 'before',
    }
  }

  function callKey(frame: FrameData): string {
    const callId = frame.details.call_id
    if (typeof callId === 'string' && callId) return `${frame.kind}:${callId}`
    const name = String(frame.details.tool ?? frame.details.model ?? frame.kind)
    return `${frame.node_id ?? QUARANTINE_NODE_ID}:${frame.kind}:${name}`
  }

  function completeCallEntry(frame: FrameData): boolean {
    const key = callKey(frame)
    const entryIds = pendingCallEntries.get(key)
    const entryId = entryIds?.shift()
    if (!entryId) return false
    if (entryIds?.length) pendingCallEntries.set(key, entryIds)
    else pendingCallEntries.delete(key)

    const index = chatEntries.value.findIndex((entry) => entry.id === entryId)
    if (index < 0) return false
    const entry = chatEntries.value[index]
    const completedAt = Date.parse(frame.ts)
    const calls = entry.calls.map((call) => ({
      ...call,
      active: false,
      durationMs: frame.duration_ms ?? Math.max(0, (Number.isNaN(completedAt) ? Date.now() : completedAt) - call.startedAt),
    }))
    chatEntries.value[index] = {
      ...entry,
      message: frame.message,
      variant: frame.level === 'ERROR' ? 'error' : frame.level === 'WARNING' ? 'warning' : entry.variant,
      calls,
    }
    if (frame.node_id && nodeUsage[frame.node_id]) {
      nodeUsage[frame.node_id].elapsedMs += calls[0]?.durationMs ?? 0
    }
    // The call is done: stop the node reporting it as in flight, and let the
    // shared ticker retire once nothing anywhere is running.
    setActiveCall(frame.node_id, null)
    return true
  }

  function actorFor(frame: FrameData): string {
    if (!frame.node_id) return frame.kind === 'run_state' ? 'Run control' : 'System'
    return descriptor.value.nodes.find((node) => node.id === frame.node_id)?.label ?? frame.node_id
  }

  async function submitGate(outcome: string, fields?: Record<string, string>): Promise<void> {
    // PRD F03: an expired gate is advisory. The server keeps the run WAITING,
    // accepts a late reply and records it as late, so the client must never
    // refuse to send one - that lockout was the whole bug.
    if (!pendingGate.value || gateSubmitting.value) return
    gateSubmitting.value = true
    try {
      await api.replyGate(runId.value, pendingGate.value.gateId, { outcome, fields })
    } catch (error) {
      gateSubmitting.value = false
      lastError.value = error instanceof Error ? error.message : 'The gate response was not accepted.'
    }
  }

  async function cancel(): Promise<void> {
    if (!runId.value || !isActive.value || status.value === 'stopping') return
    setStatus('stopping')
    try {
      await api.cancelRun(runId.value)
    } catch (error) {
      setStatus('running')
      lastError.value = error instanceof Error ? error.message : 'Cancellation could not be requested.'
    }
  }

  async function downloadLogs(format: LogFormat = 'ndjson'): Promise<void> {
    if (!runId.value || downloadStatus.value === 'pending') return
    window.clearTimeout(downloadTimer)
    downloadStatus.value = 'pending'
    downloadMessage.value = 'Preparing log download…'
    try {
      await api.downloadLogs(runId.value, format)
      downloadStatus.value = 'success'
      downloadMessage.value = 'Logs downloaded successfully.'
    } catch (error) {
      downloadStatus.value = 'error'
      downloadMessage.value = error instanceof Error ? error.message : 'Logs could not be downloaded.'
    } finally {
      downloadTimer = window.setTimeout(() => {
        downloadStatus.value = 'idle'
        downloadMessage.value = ''
      }, 5000)
    }
  }

  function dismissError(): void {
    lastError.value = ''
  }

  function resetRun(): void {
    unsubscribe?.()
    unsubscribe = undefined
    seenFrames.clear()
    pendingCallEntries.clear()
    clearEdgeAnimations()
    resetNodes()
    Object.assign(usage, initialUsage())
    status.value = 'idle'
    connection.value = 'offline'
    runId.value = ''
    pendingGate.value = null
    gateSubmitting.value = false
    lastError.value = ''
    report.value = null
    verdictSummary.value = null
    lastSequence.value = 0
    droppedFrames.value = 0
    chatEntries.value = []
    downloadStatus.value = 'idle'
    downloadMessage.value = ''
  }

  function teardown(): void {
    unsubscribe?.()
    unsubscribe = undefined
    clearEdgeAnimations()
    window.clearTimeout(downloadTimer)
  }

  onBeforeUnmount(teardown)

  return {
    descriptor,
    workflowId,
    inputField,
    idea,
    gatesMode,
    status,
    transportMode,
    connection,
    runId,
    pendingGate,
    gateSubmitting,
    launching,
    downloadStatus,
    downloadMessage,
    lastError,
    transportProblem,
    report,
    verdictSummary,
    lastSequence,
    droppedFrames,
    chatEntries,
    usage,
    nodeStates,
    nodeVisits,
    nodeActiveCall,
    nodeUsage,
    graphNodes,
    graphEdges,
    quarantinedFrames,
    isActive,
    canLaunch,
    primaryLabel,
    initialize,
    launch,
    submitGate,
    cancel,
    downloadLogs,
    dismissError,
  }
}

/**
 * The descriptor's `kind` comes from the service overlay, which falls back to
 * CrewAI's own classification (`router` / `start` / `step`) for any node it does
 * not name. Everything here is a straight pass-through except `start`, which is
 * a plain deterministic step as far as the canvas is concerned.
 *
 * This used to collapse `router`, `start` and `step` into `agent`, which drew
 * `route_scope` and `route_verdict` as six-agent-style cards. They are
 * deterministic routers with zero LLM calls (PRD §7.0); an operator reading the
 * graph for where cost and latency live was being misled by the drawing.
 */
function nodeKind(kind: GraphDescriptor['nodes'][number]['kind']): StudioNodeKind {
  if (kind === 'gate') return 'gate'
  if (kind === 'output') return 'output'
  if (kind === 'quarantine') return 'quarantine'
  if (kind === 'router') return 'router'
  if (kind === 'step' || kind === 'start') return 'step'
  return 'agent'
}

function usageFromDetails(details: Record<string, unknown>, defaultCalls = 1): UsageMetrics {
  const nested = isRecord(details.usage) ? details.usage : details
  const promptTokens = numericValue(nested, 'prompt_tokens', 'promptTokens')
  const completionTokens = numericValue(nested, 'completion_tokens', 'completionTokens')
  return {
    promptTokens,
    completionTokens,
    totalTokens: numericValue(nested, 'total_tokens', 'totalTokens', promptTokens + completionTokens),
    callCount: numericValue(
      nested,
      'call_count',
      'callCount',
      numericValue(nested, 'successful_requests', 'successfulRequests', defaultCalls),
    ),
    costUsd: numericValue(
      nested,
      'cost_usd',
      'costUsd',
      numericValue(nested, 'cost_usd_upper_bound', 'costUsdUpperBound'),
    ),
    elapsedMs: numericValue(nested, 'elapsed_ms', 'elapsedMs'),
  }
}

function numericValue(
  value: Record<string, unknown>,
  snakeCase: string,
  camelCase: string,
  fallback = 0,
): number {
  const candidate = value[snakeCase] ?? value[camelCase]
  return candidate == null ? fallback : Number(candidate) || 0
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** The five ladders, in the order PRD §10.2 weights them. */
const VERDICT_DIMENSION_KEYS = [
  'demand',
  'market',
  'competitive_room',
  'feasibility',
  'headroom_over_free',
] as const

/**
 * Read a `verdict` frame's `details` field by field.
 *
 * Nothing here casts. `details` is `Record<string, unknown>` off a socket, so
 * every field is checked and every unusable one degrades to `null` or `[]`
 * rather than throwing: a server one version ahead - a sixth dimension, a floor
 * token nobody has seen, a field turned nullable - must still render a verdict.
 *
 * The label is the one hard requirement. Without it there is no headline to
 * show, and a scorecard under a blank badge is worse than the `COMPLETE`
 * fallback `ReportPanel` already has, so such a frame is refused outright.
 */
export function parseVerdictFrame(details: Record<string, unknown>): VerdictSummary | null {
  if (!isRecord(details)) return null
  const verdict = typeof details.verdict === 'string' ? details.verdict.trim() : ''
  if (!verdict) return null
  return {
    verdict,
    confidence: finiteOrNull(details.confidence),
    compositeScore: finiteOrNull(details.composite_score),
    confidenceBand: nonEmptyStringOrNull(details.confidence_band),
    provisional: typeof details.provisional === 'boolean' ? details.provisional : null,
    fatalFloors: stringList(details.fatal_floors),
    decisionReason: nonEmptyStringOrNull(details.decision_reason),
    dimensions: dimensionScores(details.dimensions),
    source: 'frame',
  }
}

function finiteOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function nonEmptyStringOrNull(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
}

/**
 * Keeps the five known ladders in rubric order, then any dimension a newer
 * server has added, so an unrecognised score is displayed rather than dropped.
 * Returns `null` when nothing numeric survived, which is what lets the panel
 * skip the scorecard instead of drawing an empty grid.
 */
function dimensionScores(value: unknown): VerdictDimensionScores | null {
  if (!isRecord(value)) return null
  const scores: VerdictDimensionScores = {}
  const extras = Object.keys(value)
    .filter((key) => !VERDICT_DIMENSION_KEYS.includes(key as (typeof VERDICT_DIMENSION_KEYS)[number]))
    .sort()
  for (const key of [...VERDICT_DIMENSION_KEYS, ...extras]) {
    const score = finiteOrNull(value[key])
    if (score !== null) scores[key] = score
  }
  return Object.keys(scores).length ? scores : null
}

function addUsage(target: UsageMetrics, addition: UsageMetrics): void {
  target.promptTokens += addition.promptTokens
  target.completionTokens += addition.completionTokens
  target.totalTokens += addition.totalTokens
  target.callCount += addition.callCount
  target.costUsd += addition.costUsd
  target.elapsedMs += addition.elapsedMs
}
