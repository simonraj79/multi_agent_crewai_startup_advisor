import { createApp, type App } from 'vue'
import { MOCK_GRAPH } from '../src/data/mockGraph'
import type { LogFormat, StreamHandlers, StudioApiLike, TransportMode } from '../src/services/studioApi'
import type {
  FrameData,
  FrameKind,
  GateReply,
  GraphDescriptor,
  RunSnapshot,
  StartRunResponse,
  UsageMetrics,
} from '../src/types/studio'

export const RUN_ID = 'run-under-test'

/**
 * Runs a composable inside a real component instance so `onBeforeUnmount`
 * (and therefore the timer teardown path) actually fires when we unmount.
 */
export function withSetup<T>(composable: () => T): [T, App] {
  let result!: T
  const app = createApp({
    setup() {
      result = composable()
      return () => null
    },
  })
  app.mount(document.createElement('div'))
  return [result, app]
}

/** Drains the composable's promise-chained frame queue. */
export async function flush(ticks = 8): Promise<void> {
  for (let index = 0; index < ticks; index += 1) await Promise.resolve()
}

export const zeroUsage = (): UsageMetrics => ({
  promptTokens: 0,
  completionTokens: 0,
  totalTokens: 0,
  callCount: 0,
  costUsd: 0,
  elapsedMs: 0,
})

export function emptySnapshot(runId = RUN_ID, status: RunSnapshot['status'] = 'running'): RunSnapshot {
  return {
    run_id: runId,
    status,
    pending_gate: null,
    frames: { count: 0, dropped: 0, first_seq: null, last_seq: null },
    usage: zeroUsage(),
  }
}

/**
 * Deterministic stand-in for the transport. Nothing here touches a socket, a
 * server or a clock, so every composable test is no-cost and repeatable.
 */
export class FakeStudioApi implements StudioApiLike {
  mode: TransportMode = 'live'
  graph: GraphDescriptor = structuredClone(MOCK_GRAPH)
  snapshot: RunSnapshot = emptySnapshot()
  storedFrames: FrameData[] = []
  handlers: StreamHandlers | null = null
  subscribeCalls: Array<{ runId: string; after: number }> = []
  unsubscribeCount = 0
  gateReplies: Array<{ runId: string; gateId: string; reply: GateReply }> = []
  cancelled: string[] = []
  downloaded: Array<{ runId: string; format: LogFormat }> = []
  getRunError: Error | null = null
  runIdToIssue = RUN_ID

  async initialize(): Promise<TransportMode> {
    return this.mode
  }

  async getGraph(): Promise<GraphDescriptor> {
    return structuredClone(this.graph)
  }

  async startRun(): Promise<StartRunResponse> {
    return { run_id: this.runIdToIssue, status: 'queued', graph_version: this.graph.version }
  }

  async getRun(id: string): Promise<RunSnapshot> {
    if (this.getRunError) throw this.getRunError
    return { ...this.snapshot, run_id: id }
  }

  async getFrames(_id: string, after: number): Promise<FrameData[]> {
    return this.storedFrames.filter((frame) => frame.seq > after)
  }

  subscribe(runIdValue: string, _sessionId: string, handlers: StreamHandlers): () => void {
    this.handlers = handlers
    this.subscribeCalls.push({ runId: runIdValue, after: handlers.getAfter() })
    handlers.onStatus('connected')
    return () => {
      this.unsubscribeCount += 1
      if (this.handlers === handlers) this.handlers = null
      handlers.onStatus('offline')
    }
  }

  async replyGate(runIdValue: string, gateId: string, reply: GateReply): Promise<void> {
    this.gateReplies.push({ runId: runIdValue, gateId, reply })
  }

  async cancelRun(runIdValue: string): Promise<void> {
    this.cancelled.push(runIdValue)
  }

  async downloadLogs(runIdValue: string, format: LogFormat = 'ndjson'): Promise<void> {
    this.downloaded.push({ runId: runIdValue, format })
  }

  /** Pushes a frame down the same path the live socket uses. */
  emit(frame: FrameData): void {
    this.handlers?.onFrame(frame)
  }
}

/** Builds gap-free frame sequences; each factory owns its own counter. */
export function frameFactory(runId = RUN_ID) {
  let seq = 0
  return function build(kind: FrameKind, overrides: Partial<FrameData> = {}): FrameData {
    seq += 1
    const base: FrameData = {
      v: 1,
      seq,
      run_id: runId,
      ts: new Date(1_750_000_000_000 + seq * 1000).toISOString(),
      kind,
      event_type: 'EVENT',
      level: 'INFO',
      message: `${kind} frame ${seq}`,
      details: {},
    }
    return { ...base, ...overrides }
  }
}

export function edgeFrame(
  build: ReturnType<typeof frameFactory>,
  from: string,
  to: string,
): FrameData {
  return build('edge_taken', { event_type: 'EDGE_TRAVERSED', details: { from, to } })
}
