import { buildMockSegments, type MockScriptStep } from '../data/mockFrames'
import { MOCK_GRAPH } from '../data/mockGraph'
import type {
  BackendFramePage,
  BackendGatePrompt,
  BackendRunSnapshot,
  FrameData,
  GateReply,
  GraphDescriptor,
  RunSnapshot,
  StartRunResponse,
  StudioFrame,
  UsageMetrics,
} from '../types/studio'

export type TransportMode = 'probing' | 'live' | 'mock'
export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'offline'

interface StreamHandlers {
  onFrame: (frame: FrameData) => void
  onStatus: (status: ConnectionStatus) => void
  getAfter: () => number
}

interface MockRun {
  segments: MockScriptStep[][]
  segmentIndex: number
  timers: number[]
  emitted: FrameData[]
  handlers?: StreamHandlers
}

const emptyUsage = (): UsageMetrics => ({
  promptTokens: 0,
  completionTokens: 0,
  totalTokens: 0,
  callCount: 0,
  costUsd: 0,
  elapsedMs: 0,
})

function runId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `mock-${Date.now().toString(36)}`
}

export class StudioApi {
  mode: TransportMode = 'probing'
  private readonly baseUrl = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''
  private readonly mockRuns = new Map<string, MockRun>()

  async initialize(force = false): Promise<TransportMode> {
    if (!force && this.mode !== 'probing') return this.mode

    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 900)
    try {
      const response = await fetch(`${this.baseUrl}/api/workflows`, {
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      })
      const contentType = response.headers.get('content-type') ?? ''
      this.mode = response.ok && contentType.includes('application/json') ? 'live' : 'mock'
    } catch {
      this.mode = 'mock'
    } finally {
      window.clearTimeout(timeout)
    }
    return this.mode
  }

  async getGraph(workflowId = 'idea-validator'): Promise<GraphDescriptor> {
    if (this.mode === 'live') {
      return this.fetchJson<GraphDescriptor>(`/api/workflows/${encodeURIComponent(workflowId)}/graph`)
    }
    return structuredClone(MOCK_GRAPH)
  }

  async startRun(sessionId: string, idea: string, workflowId = 'idea-validator'): Promise<StartRunResponse> {
    await this.initialize(this.mode === 'mock')
    if (this.mode === 'live') {
      return this.fetchJson<StartRunResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow_id: workflowId, inputs: { idea } }),
      })
    }

    const id = runId()
    this.mockRuns.set(id, {
      segments: buildMockSegments(id),
      segmentIndex: 0,
      timers: [],
      emitted: [],
    })
    return { run_id: id, status: 'queued', graph_version: MOCK_GRAPH.version }
  }

  async getRun(id: string): Promise<RunSnapshot> {
    if (this.mode === 'live') {
      const snapshot = await this.fetchJson<BackendRunSnapshot>(`/api/runs/${encodeURIComponent(id)}`)
      return {
        run_id: snapshot.run_id,
        status: normalizeRunStatus(snapshot.status),
        pending_gate: snapshot.pending_gate ? normalizeGate(snapshot.pending_gate) : null,
        frames: snapshot.frames,
        usage: normalizeUsage(snapshot.usage),
      }
    }
    const run = this.mockRuns.get(id)
    if (!run) throw new Error('This mock run is no longer available after refresh.')
    return {
      run_id: id,
      status: 'running',
      pending_gate: null,
      frames: {
        count: run.emitted.length,
        dropped: 0,
        first_seq: run.emitted.at(0)?.seq ?? null,
        last_seq: run.emitted.at(-1)?.seq ?? null,
      },
      usage: emptyUsage(),
    }
  }

  async getFrames(id: string, after: number): Promise<FrameData[]> {
    if (this.mode === 'live') {
      const frames: FrameData[] = []
      let cursor = after
      while (true) {
        const payload = await this.fetchJson<FrameData[] | BackendFramePage>(
          `/api/runs/${encodeURIComponent(id)}/frames?after=${cursor}&limit=500`,
        )
        const page = Array.isArray(payload) ? payload : payload.frames
        const batch = page.map((frame) => isStudioFrame(frame) ? frame.data : frame)
        frames.push(...batch)
        if (Array.isArray(payload) || payload.count < 500 || payload.next_after <= cursor) break
        cursor = payload.next_after
      }
      return frames
    }
    return this.mockRuns.get(id)?.emitted.filter((frame) => frame.seq > after) ?? []
  }

  subscribe(runIdValue: string, sessionId: string, handlers: StreamHandlers): () => void {
    if (this.mode === 'mock') return this.subscribeMock(runIdValue, handlers)

    let socket: WebSocket | null = null
    let reconnectTimer = 0
    let pingTimer = 0
    let attempts = 0
    let closed = false

    const connect = () => {
      handlers.onStatus(attempts === 0 ? 'connecting' : 'reconnecting')
      const base = new URL(this.baseUrl || window.location.origin, window.location.origin)
      base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:'
      base.pathname = '/ws'
      base.search = new URLSearchParams({
        session_id: sessionId,
        run_id: runIdValue,
        after: String(handlers.getAfter()),
      }).toString()
      socket = new WebSocket(base)

      socket.addEventListener('open', () => {
        attempts = 0
        handlers.onStatus('connected')
        pingTimer = window.setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'ping' }))
        }, 20_000)
      })
      socket.addEventListener('message', (event) => {
        try {
          const message = JSON.parse(String(event.data)) as StudioFrame | { type: string }
          if (message.type === 'frame' && 'data' in message) handlers.onFrame(message.data)
        } catch {
          // A malformed server frame is ignored; the sequence gap triggers replay.
        }
      })
      socket.addEventListener('close', () => {
        window.clearInterval(pingTimer)
        if (closed) return
        attempts += 1
        handlers.onStatus('reconnecting')
        reconnectTimer = window.setTimeout(connect, Math.min(800 * 2 ** attempts, 10_000))
      })
      socket.addEventListener('error', () => socket?.close())
    }

    connect()
    return () => {
      closed = true
      window.clearTimeout(reconnectTimer)
      window.clearInterval(pingTimer)
      socket?.close()
      handlers.onStatus('offline')
    }
  }

  async replyGate(runIdValue: string, gateId: string, reply: GateReply): Promise<void> {
    if (this.mode === 'live') {
      await this.fetchJson(`/api/runs/${encodeURIComponent(runIdValue)}/gates/${encodeURIComponent(gateId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(reply),
      })
      return
    }

    const run = this.mockRuns.get(runIdValue)
    if (!run || !run.handlers) return
    run.segmentIndex += 1
    this.playMockSegment(run)
  }

  async cancelRun(runIdValue: string): Promise<void> {
    if (this.mode === 'live') {
      await this.fetchJson(`/api/runs/${encodeURIComponent(runIdValue)}/cancel`, { method: 'POST' })
      return
    }

    const run = this.mockRuns.get(runIdValue)
    if (!run || !run.handlers) return
    run.timers.forEach(window.clearTimeout)
    const seq = (run.emitted.at(-1)?.seq ?? 0) + 1
    const frame: FrameData = {
      v: 1,
      seq,
      run_id: runIdValue,
      ts: new Date().toISOString(),
      kind: 'run_state',
      event_type: 'RUN_CANCELLED',
      level: 'WARNING',
      message: 'Run cancelled by operator.',
      details: { status: 'cancelled' },
    }
    run.emitted.push(frame)
    window.setTimeout(() => run.handlers?.onFrame(frame), 380)
  }

  async downloadLogs(runIdValue: string): Promise<void> {
    let blob: Blob
    if (this.mode === 'live') {
      const response = await fetch(`${this.baseUrl}/api/runs/${encodeURIComponent(runIdValue)}/logs?format=ndjson`)
      if (!response.ok) throw new Error(`Log download failed (${response.status})`)
      blob = await response.blob()
    } else {
      const content = (this.mockRuns.get(runIdValue)?.emitted ?? [])
        .map((frame) => JSON.stringify({ type: 'frame', data: frame }))
        .join('\n')
      blob = new Blob([content], { type: 'application/x-ndjson' })
    }

    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = `validator-${runIdValue.slice(0, 8)}.ndjson`
    anchor.click()
    URL.revokeObjectURL(href)
  }

  private subscribeMock(runIdValue: string, handlers: StreamHandlers): () => void {
    const run = this.mockRuns.get(runIdValue)
    if (!run) return () => undefined
    run.handlers = handlers
    handlers.onStatus('connected')
    this.playMockSegment(run)
    return () => {
      run.timers.forEach(window.clearTimeout)
      run.handlers = undefined
      handlers.onStatus('offline')
    }
  }

  private playMockSegment(run: MockRun): void {
    const segment = run.segments[run.segmentIndex]
    if (!segment || !run.handlers) return
    run.timers.forEach(window.clearTimeout)
    run.timers = []
    let elapsed = 0
    for (const step of segment) {
      elapsed += step.delayMs
      const timer = window.setTimeout(() => {
        run.emitted.push(step.frame)
        run.handlers?.onFrame(step.frame)
      }, elapsed)
      run.timers.push(timer)
    }
  }

  private async fetchJson<T = unknown>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, init)
    if (!response.ok) {
      const detail = await response.text().catch(() => '')
      throw new Error(detail || `Request failed (${response.status})`)
    }
    return response.json() as Promise<T>
  }
}

function normalizeGate(gate: BackendGatePrompt) {
  return {
    gateId: gate.gate_id,
    nodeId: gate.node_id,
    title: gate.title,
    summary: gate.summary,
    editable: gate.editable,
    expiresAt: gate.expires_at ?? undefined,
    options: gate.options,
    fields: gate.fields ?? undefined,
    verdict: gate.verdict ?? undefined,
    confidence: gate.confidence ?? undefined,
  }
}

function isStudioFrame(frame: StudioFrame | FrameData): frame is StudioFrame {
  return 'type' in frame && frame.type === 'frame' && 'data' in frame
}

function normalizeRunStatus(status: BackendRunSnapshot['status']): RunSnapshot['status'] {
  if (status === 'failed') return 'error'
  if (status === 'cancelling') return 'stopping'
  return status
}

function normalizeUsage(value: Record<string, number>): UsageMetrics {
  const promptTokens = Number(value.prompt_tokens ?? value.promptTokens ?? 0)
  const completionTokens = Number(value.completion_tokens ?? value.completionTokens ?? 0)
  return {
    promptTokens,
    completionTokens,
    totalTokens: Number(value.total_tokens ?? value.totalTokens ?? promptTokens + completionTokens),
    callCount: Number(
      value.call_count
      ?? value.callCount
      ?? value.successful_requests
      ?? value.successfulRequests
      ?? 0,
    ),
    costUsd: Number(value.cost_usd ?? value.costUsd ?? value.cost_usd_upper_bound ?? 0),
    elapsedMs: Number(value.elapsed_ms ?? value.elapsedMs ?? 0),
  }
}

export const studioApi = new StudioApi()