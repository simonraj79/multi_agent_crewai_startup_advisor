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
  // The scored `Verdict`, published the moment the Flow computes it. Emitted in
  // BOTH gate modes, which is the whole reason it exists: `gates=auto` never
  // opens a verdict gate, so before this frame the deterministic label this
  // product is built to produce reached an unattended run's UI through nothing
  // at all.
  | 'verdict'
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

/**
 * The validator's finished report, as `GET /api/runs/{id}` returns it under
 * `result` and the terminal `WORKFLOW_END` frame carries under
 * `details.result`. Mirrors `schemas/validator.py::ValidationReport`.
 *
 * `markdown_body` is exempted from the frame serializer's 4096-character clip
 * by `RUN_RESULT_BODY_KEYS` and re-read from the source at
 * `MAX_RUN_RESULT_BODY_CHARS` (64 KiB), so the snapshot copy is the whole
 * report while the frame copy may be truncated. Prefer the snapshot.
 */
export interface RunResult {
  markdown_body?: string | null
  provisional?: boolean | null
  thin_dimensions?: string[] | null
  sources?: Array<{ url?: string | null; title?: string | null }> | null
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
  result?: RunResult | null
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
  result?: RunResult | null
}

export interface BackendFramePage {
  run_id: string
  after: number
  next_after: number
  count: number
  frames: Array<StudioFrame | FrameData>
}

/**
 * The five rubric ladders, as `schemas/validator.py::Verdict` scores them.
 *
 * Every key is optional and the index signature is deliberate. This is parsed
 * out of `FrameData.details`, which is `Record<string, unknown>`: a server that
 * scores a sixth dimension, or one that drops a field, must not be able to make
 * the client throw on the one frame carrying the run's conclusion.
 */
export interface VerdictDimensionScores {
  demand?: number
  market?: number
  competitive_room?: number
  feasibility?: number
  headroom_over_free?: number
  [dimension: string]: number | undefined
}

/**
 * The wire shape of a `kind: "verdict"` frame's `details`, exactly as the Flow
 * publishes it on the `synthesize` node. Documentation of a frozen contract -
 * nothing casts to it, because a frame is untrusted input; `parseVerdictFrame`
 * in `useValidatorRun.ts` reads it field by field instead.
 */
export interface VerdictFrameDetails {
  verdict: string
  composite_score: number
  confidence: number
  confidence_band: string
  provisional: boolean
  /** Empty when nothing tripped. A non-empty list overrides the arithmetic. */
  fatal_floors: string[]
  decision_reason: string | null
  dimensions: VerdictDimensionScores
}

/**
 * The run's conclusion as the console holds it, from whichever carrier supplied
 * it. `source` is not decoration: it is what makes the precedence rule in
 * `useValidatorRun.ts::applyVerdict` / `closeGate` checkable, because the two
 * carriers are not equal. The frame is computed deterministically inside the
 * Flow and published in both gate modes; the verdict gate is optional, carries
 * only the headline, and does not exist at all under `gates=auto`.
 */
export interface VerdictSummary {
  verdict: string
  confidence: number | null
  /** 0-10. `2 * (0.30D + 0.20M + 0.20C + 0.15F + 0.15X)`, recomputed server-side. */
  compositeScore: number | null
  confidenceBand: string | null
  provisional: boolean | null
  fatalFloors: string[]
  decisionReason: string | null
  dimensions: VerdictDimensionScores | null
  source: 'frame' | 'gate'
}

/**
 * One row of "your runs", as `GET /api/runs` returns it.
 *
 * Mirrors `RunHistoryEntry` in `src/brief_crew/service/models.py`, which is
 * deliberately NOT a `RunSnapshot`: no frames, no node usage, no result body.
 * Note the absent `session_id` - it is a capability, not a label, and a list of
 * historical runs must not hand out live-stream credentials for all of them.
 */
export interface RunHistoryEntry {
  run_id: string
  workflow_id: string
  status: string
  created_at: string
  completed_at: string | null
  label: string
  total_tokens: number
  cost_usd: number
}
