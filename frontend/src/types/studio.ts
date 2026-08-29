export type NodeRunState = 'idle' | 'running' | 'waiting' | 'completed' | 'error'

export type RunStatus =
  | 'idle'
  | 'queued'
  | 'running'
  | 'waiting'
  | 'stopping'
  | 'cancelled'
  | 'completed'
  | 'error'

export type BackendRunStatus =
  | 'queued'
  | 'running'
  | 'waiting'
  | 'cancelling'
  | 'cancelled'
  | 'completed'
  | 'failed'

export type FrameKind =
  | 'run_state'
  | 'node_state'
  | 'edge_taken'
  | 'agent'
  | 'tool'
  | 'llm'
  | 'token'
  | 'gate_open'
  | 'gate_closed'
  // PRD F03. Advisory only: the gate passed its deadline, the run stays
  // WAITING, and a late reply is still accepted and still resumes it.
  | 'gate_expired'
  // PRD R-2: a gate_open with no gate_closed past timeout + grace.
  | 'gate_alert'
  | 'metrics'
  | 'error'

export type FrameLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'

export interface FrameData {
  v: 1
  seq: number
  run_id: string
  ts: string
  kind: FrameKind
  event_type: string
  level: FrameLevel
  node_id?: string
  message: string
  details: Record<string, unknown>
  duration_ms?: number
}

export interface StudioFrame {
  type: 'frame'
  data: FrameData
}

export interface GraphNodeDefinition {
  id: string
  label: string
  kind: 'agent' | 'gate' | 'output' | 'quarantine' | 'router' | 'start' | 'step'
  description: string
  eyebrow: string
  model?: string
  tool?: string
  position: { x: number; y: number }
}

export interface GraphEdgeDefinition {
  id: string
  source: string
  target: string
  label?: string | null
  condition_type?: string | null
  route?: string | null
}

export interface GraphDescriptor {
  id: string
  name: string
  version: string
  start_nodes: string[]
  nodes: GraphNodeDefinition[]
  edges: GraphEdgeDefinition[]
}

export interface GateOption {
  id: string
  label: string
  emphasis?: 'primary' | 'danger'
}

/**
 * A value the gate shows but the operator cannot change.
 *
 * The verdict gate's entire payload arrives this way: `Verdict` recomputes its
 * composite score, confidence, band, floors, provisional flag and label from
 * the five dimension scores and discards whatever it was sent, and the scored
 * inputs to that arithmetic are bound to the rubric and to tool-returned URLs
 * by guardrails that only run on the Synthesist's output. They are still the
 * whole basis for approving or revising, so they are shown in full - as read
 * detail, never as a form input the edit could not reach.
 */
export interface GateDerivedField {
  key: string
  value: string
  /** `json` values are pretty-printed and belong in a block, not a line. */
  kind: 'text' | 'json'
}

export interface PendingGate {
  gateId: string
  nodeId: string
  title: string
  summary: string
  /** Whether this gate has any editable field at all - see `fields`. */
  editable: boolean
  expiresAt?: string
  /**
   * The server's view of PRD F03 expiry, from `pending_gate.expired` and the
   * `gate_expired` frame. Informational: an expired gate still accepts a
   * reply, so nothing in the UI may key a disabled state off this.
   */
  expired: boolean
  /** PRD R-2: no reply arrived within timeout + grace. Also informational. */
  alerting?: boolean
  /** Seconds past the deadline, as reported by the server's sweep. */
  overdueSeconds?: number
  options: GateOption[]
  /** Editable fields only. The server prunes the rest into `derived`. */
  fields?: Record<string, string>
  derived?: GateDerivedField[]
  verdict?: string
  confidence?: number
}

export interface UsageMetrics {
  promptTokens: number
  completionTokens: number
  totalTokens: number
  callCount: number
  costUsd: number
  elapsedMs: number
}

export interface CallChip {
  id: string
  kind: 'llm' | 'tool'
  label: string
  startedAt: number
  durationMs?: number
  active: boolean
}

export interface ChatEntry {
  id: string
  seq: number
  nodeId?: string
  actor: string
  message: string
  timestamp: string
  variant: 'agent' | 'system' | 'warning' | 'error'
  calls: CallChip[]
}

export interface RunSnapshot {
  run_id: string
  status: RunStatus
  pending_gate: PendingGate | null
  frames: {
    count: number
    dropped: number
    first_seq?: number | null
    last_seq?: number | null
  }
  usage: UsageMetrics
}

export interface StartRunResponse {
  run_id: string
  status: 'queued'
  graph_version: string
}

export interface GateReply {
  outcome: string
  fields?: Record<string, string>
}

export interface BackendGatePrompt {
  gate_id: string
  node_id: string
  title: string
  summary: string
  editable: boolean
  expires_at?: string | null
  expired?: boolean
  options: GateOption[]
  fields?: Record<string, string> | null
  derived?: GateDerivedField[] | null
  verdict?: string | null
  confidence?: number | null
}

export interface BackendRunSnapshot {
  run_id: string
  status: BackendRunStatus
  pending_gate: BackendGatePrompt | null
  frames: {
    count: number
    dropped: number
    first_seq?: number | null
    last_seq?: number | null
  }
  usage: Record<string, number>
}

export interface BackendFramePage {
  run_id: string
  after: number
  next_after: number
  count: number
  frames: Array<StudioFrame | FrameData>
}