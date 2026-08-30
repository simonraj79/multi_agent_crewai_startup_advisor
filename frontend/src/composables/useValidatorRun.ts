import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import type { Edge, Node } from '@vue-flow/core'
import { MOCK_GRAPH } from '../data/mockGraph'
import { studioApi, type ConnectionStatus, type LogFormat, type StudioApiLike, type TransportMode } from '../services/studioApi'
import type {
  CallChip,
  ChatEntry,
  FrameData,
  GraphDescriptor,
  NodeRunState,
  PendingGate,
  RunStatus,
  UsageMetrics,
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

export function useValidatorRun(api: StudioApiLike = studioApi) {
  const storedAtLoad = readStoredRun()
  const sessionId = storedAtLoad?.sessionId ?? readStorage(SESSION_STORAGE_KEY) ?? newSessionId()
  writeStorage(SESSION_STORAGE_KEY, sessionId)

  const descriptor = ref<GraphDescriptor>(structuredClone(MOCK_GRAPH))
  const workflowId = ref(storedAtLoad?.workflowId ?? DEFAULT_WORKFLOW_ID)
  const idea = ref('An AI tool that turns Figma files into production React')
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
  const lastSequence = ref(0)
  const droppedFrames = ref(0)
  const activeEdgeIds = ref(new Set<string>())
  const chatEntries = ref<ChatEntry[]>([])
  const usage = reactive<UsageMetrics>(initialUsage())
  const nodeStates = reactive<Record<string, NodeRunState>>({})
  const nodeUsage = reactive<Record<string, UsageMetrics>>({})
  const nodeFrames = reactive<Record<string, number>>({})
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
    for (const node of descriptor.value.nodes) {
      nodeStates[node.id] = 'idle'
      nodeUsage[node.id] = initialUsage()
      nodeFrames[node.id] = 0
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
    status.value = next
    if (!TERMINAL_STATUSES.includes(next)) return
    clearStoredRun()
    // Nothing further will stream, so no traversal should still be marching.
    clearEdgeAnimations()
  }

  async function initialize(): Promise<void> {
    transportMode.value = await api.initialize()
    const storedRun = readStoredRun()
    workflowId.value = storedRun?.workflowId ?? workflowId.value
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
      const response = await api.startRun(sessionId, idea.value.trim(), workflowId.value)
      transportMode.value = api.mode
      resetRun()
      runId.value = response.run_id
      setStatus(response.status)
      persistRun({
        version: 1,
        runId: response.run_id,
        sessionId,
        workflowId: workflowId.value,
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
        clearStoredRun()
        resetRun()
        return
      }
      const frames = await api.getFrames(context.runId, 0)
      frames.sort((left, right) => left.seq - right.seq).forEach(applyFrame)
      const snapshotSequence = snapshot.frames.last_seq ?? lastSequence.value
      setStatus(snapshot.status)
      pendingGate.value = snapshot.pending_gate
      droppedFrames.value = snapshot.frames.dropped
      Object.assign(usage, snapshot.usage)
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
    if (frame.kind === 'gate_open') applyGate(frame)
    if (frame.kind === 'gate_expired' || frame.kind === 'gate_alert') applyGateWatch(frame)
    if (frame.kind === 'gate_closed') {
      pendingGate.value = null
      gateSubmitting.value = false
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
    if (frame.kind === 'gate_open') applyGate(frame)
    if (frame.kind === 'gate_expired' || frame.kind === 'gate_alert') applyGateWatch(frame)
    if (frame.kind === 'gate_closed') {
      pendingGate.value = null
      gateSubmitting.value = false
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
   */
  function applyRunState(frame: FrameData): void {
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

  function applyNodeState(frame: FrameData): void {
    const nodeId = frame.node_id as string
    if (frame.event_type.includes('START')) setNodeState(nodeId, 'running')
    if (frame.event_type.includes('WAITING')) {
      setNodeState(nodeId, 'waiting')
      setStatus('waiting')
    }
    if (frame.event_type.includes('END') || frame.event_type.includes('COMPLETED')) setNodeState(nodeId, 'completed')
    if (frame.event_type.includes('ERROR') || frame.level === 'ERROR') setNodeState(nodeId, 'error')
  }

  /**
   * A node reaching a settled state ends every traversal feeding it. Without
   * this an edge would keep marching for the rest of its timer after the branch
   * it points at has already finished.
   */
  function setNodeState(nodeId: string, state: NodeRunState): void {
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
    idea,
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
    lastSequence,
    droppedFrames,
    chatEntries,
    usage,
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

function addUsage(target: UsageMetrics, addition: UsageMetrics): void {
  target.promptTokens += addition.promptTokens
  target.completionTokens += addition.completionTokens
  target.totalTokens += addition.totalTokens
  target.callCount += addition.callCount
  target.costUsd += addition.costUsd
  target.elapsedMs += addition.elapsedMs
}
