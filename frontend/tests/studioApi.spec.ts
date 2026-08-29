import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { StudioApi, type ConnectionStatus, type StreamHandlers } from '../src/services/studioApi'
import type { BackendFramePage, BackendRunSnapshot, FrameData } from '../src/types/studio'

type Listener = (event: unknown) => void

/** Minimal socket double: nothing here reaches the network. */
class FakeWebSocket {
  static readonly OPEN = 1
  static readonly CLOSED = 3
  static instances: FakeWebSocket[] = []

  readyState = 0
  readonly url: string
  readonly sent: string[] = []
  private readonly listeners = new Map<string, Listener[]>()

  constructor(url: URL | string) {
    this.url = String(url)
    FakeWebSocket.instances.push(this)
  }

  addEventListener(type: string, handler: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), handler])
  }

  send(payload: string): void {
    this.sent.push(payload)
  }

  close(): void {
    if (this.readyState === FakeWebSocket.CLOSED) return
    this.readyState = FakeWebSocket.CLOSED
    this.dispatch('close', {})
  }

  /* Test-side drivers. */
  accept(): void {
    this.readyState = FakeWebSocket.OPEN
    this.dispatch('open', {})
  }

  deliver(message: unknown): void {
    this.dispatch('message', { data: JSON.stringify(message) })
  }

  deliverRaw(data: string): void {
    this.dispatch('message', { data })
  }

  get lastSent(): Record<string, unknown> {
    return JSON.parse(this.sent[this.sent.length - 1]) as Record<string, unknown>
  }

  private dispatch(type: string, event: unknown): void {
    for (const handler of this.listeners.get(type) ?? []) handler(event)
  }
}

function frame(seq: number, runId = 'run-1'): FrameData {
  return {
    v: 1,
    seq,
    run_id: runId,
    ts: '2026-01-01T00:00:00.000Z',
    kind: 'node_state',
    event_type: 'NODE_START',
    level: 'INFO',
    message: `frame ${seq}`,
    details: {},
  }
}

interface Recorder {
  frames: FrameData[]
  statuses: ConnectionStatus[]
  handlers: StreamHandlers
}

function recorder(after = () => 0): Recorder {
  const frames: FrameData[] = []
  const statuses: ConnectionStatus[] = []
  return {
    frames,
    statuses,
    handlers: {
      onFrame: (value) => frames.push(value),
      onStatus: (value) => statuses.push(value),
      getAfter: after,
    },
  }
}

describe('StudioApi websocket stream', () => {
  let api: StudioApi
  let originalWebSocket: typeof globalThis.WebSocket

  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.instances = []
    originalWebSocket = globalThis.WebSocket
    globalThis.WebSocket = FakeWebSocket as unknown as typeof globalThis.WebSocket
    api = new StudioApi()
    api.mode = 'live'
  })

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket
    vi.useRealTimers()
  })

  it('opens the stream at the cursor the client has already consumed', () => {
    const stream = recorder(() => 42)
    api.subscribe('run-1', 'session-9', stream.handlers)

    const socket = FakeWebSocket.instances[0]
    const url = new URL(socket.url)
    expect(url.pathname).toBe('/ws')
    expect(url.searchParams.get('run_id')).toBe('run-1')
    expect(url.searchParams.get('session_id')).toBe('session-9')
    expect(url.searchParams.get('after')).toBe('42')
    expect(stream.statuses).toEqual(['connecting'])
  })

  it('reports connection state and forwards frames', () => {
    const stream = recorder()
    api.subscribe('run-1', 'session-9', stream.handlers)
    const socket = FakeWebSocket.instances[0]

    socket.accept()
    socket.deliver({ type: 'frame', data: frame(1) })
    socket.deliver({ type: 'frame', data: frame(2) })

    expect(stream.statuses).toEqual(['connecting', 'connected'])
    expect(stream.frames.map((value) => value.seq)).toEqual([1, 2])
  })

  it('survives a malformed or unknown message', () => {
    const stream = recorder()
    api.subscribe('run-1', 'session-9', stream.handlers)
    const socket = FakeWebSocket.instances[0]
    socket.accept()

    expect(() => socket.deliverRaw('{not json')).not.toThrow()
    expect(() => socket.deliver({ type: 'pong' })).not.toThrow()
    expect(stream.frames).toEqual([])
  })

  it('pings an idle connection', () => {
    api.subscribe('run-1', 'session-9', recorder().handlers)
    const socket = FakeWebSocket.instances[0]
    socket.accept()

    vi.advanceTimersByTime(20_000)

    expect(socket.lastSent).toEqual({ type: 'ping' })
  })

  it('reconnects after a drop and resumes from the newest cursor', () => {
    let cursor = 0
    const stream = recorder(() => cursor)
    api.subscribe('run-1', 'session-9', stream.handlers)
    const first = FakeWebSocket.instances[0]
    first.accept()
    first.deliver({ type: 'frame', data: frame(7) })
    cursor = 7

    first.close()
    expect(stream.statuses).toEqual(['connecting', 'connected', 'reconnecting'])

    vi.advanceTimersByTime(1600)

    expect(FakeWebSocket.instances).toHaveLength(2)
    expect(new URL(FakeWebSocket.instances[1].url).searchParams.get('after')).toBe('7')
  })

  it('stops reconnecting once the caller unsubscribes', () => {
    const stream = recorder()
    const unsubscribe = api.subscribe('run-1', 'session-9', stream.handlers)
    const socket = FakeWebSocket.instances[0]
    socket.accept()

    unsubscribe()
    vi.advanceTimersByTime(60_000)

    expect(socket.readyState).toBe(FakeWebSocket.CLOSED)
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(stream.statuses.at(-1)).toBe('offline')
  })

  it('answers a gate on the live socket and resolves on the ack', async () => {
    api.subscribe('run-1', 'session-9', recorder().handlers)
    const socket = FakeWebSocket.instances[0]
    socket.accept()

    const reply = api.replyGate('run-1', 'scope-confirmation', { outcome: 'scope_ok', fields: { market: 'x' } })
    const sent = socket.lastSent
    expect(sent.type).toBe('gate_reply')
    expect(sent.data).toEqual({ gate_id: 'scope-confirmation', outcome: 'scope_ok', fields: { market: 'x' } })

    socket.deliver({ type: 'gate_ack', data: { request_id: sent.request_id } })
    await expect(reply).resolves.toBeUndefined()
  })

  it('rejects a gate reply the server refuses', async () => {
    api.subscribe('run-1', 'session-9', recorder().handlers)
    const socket = FakeWebSocket.instances[0]
    socket.accept()

    const reply = api.replyGate('run-1', 'scope-confirmation', { outcome: 'scope_ok' })
    const requestId = socket.lastSent.request_id
    socket.deliver({ type: 'error', data: { request_id: requestId, message: 'This gate was already answered.' } })

    await expect(reply).rejects.toThrow('This gate was already answered.')
  })

  it('rejects an unacknowledged gate reply when the connection drops', async () => {
    api.subscribe('run-1', 'session-9', recorder().handlers)
    const socket = FakeWebSocket.instances[0]
    socket.accept()

    const reply = api.replyGate('run-1', 'scope-confirmation', { outcome: 'scope_ok' })
    socket.close()

    await expect(reply).rejects.toThrow('The connection dropped before the gate reply was acknowledged.')
  })
})

describe('StudioApi http surface', () => {
  let api: StudioApi
  let fetchMock: ReturnType<typeof vi.fn>

  const jsonResponse = (body: unknown) => ({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
    text: async () => JSON.stringify(body),
  })

  let originalFetch: typeof globalThis.fetch

  beforeEach(() => {
    api = new StudioApi()
    api.mode = 'live'
    fetchMock = vi.fn()
    originalFetch = globalThis.fetch
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('pages through frames and unwraps the envelope form', async () => {
    const firstPage: BackendFramePage = {
      run_id: 'run-1',
      after: 0,
      next_after: 500,
      count: 500,
      frames: Array.from({ length: 500 }, (_, index) => ({ type: 'frame' as const, data: frame(index + 1) })),
    }
    const secondPage: BackendFramePage = {
      run_id: 'run-1',
      after: 500,
      next_after: 502,
      count: 2,
      frames: [frame(501), frame(502)],
    }
    fetchMock.mockResolvedValueOnce(jsonResponse(firstPage)).mockResolvedValueOnce(jsonResponse(secondPage))

    const frames = await api.getFrames('run-1', 0)

    expect(frames).toHaveLength(502)
    expect(frames.at(0)?.seq).toBe(1)
    expect(frames.at(-1)?.seq).toBe(502)
    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      '/api/runs/run-1/frames?after=0&limit=500',
      '/api/runs/run-1/frames?after=500&limit=500',
    ])
  })

  it('accepts a bare array of frames from an older endpoint', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([frame(1), frame(2)]))
    await expect(api.getFrames('run-1', 0)).resolves.toHaveLength(2)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('maps a failed run to the error status and keeps the server expiry flag', async () => {
    const snapshot: BackendRunSnapshot = {
      run_id: 'run-1',
      status: 'failed',
      pending_gate: {
        gate_id: 'verdict-review',
        node_id: 'review_verdict',
        title: 'Review verdict',
        summary: 'Late but still answerable.',
        editable: false,
        expires_at: '2026-01-01T00:00:00.000Z',
        expired: true,
        options: [{ id: 'verdict_ok', label: 'Accept verdict', emphasis: 'primary' }],
        fields: null,
        verdict: 'NEEDS_WORK',
        confidence: 0.62,
      },
      frames: { count: 3, dropped: 0, first_seq: 1, last_seq: 3 },
      usage: { prompt_tokens: 10, completion_tokens: 5, cost_usd: 0.01 },
    }
    fetchMock.mockResolvedValueOnce(jsonResponse(snapshot))

    const result = await api.getRun('run-1')

    expect(result.status).toBe('error')
    expect(result.pending_gate?.expired).toBe(true)
    expect(result.pending_gate?.gateId).toBe('verdict-review')
    expect(result.usage.totalTokens).toBe(15)
    expect(result.usage.costUsd).toBeCloseTo(0.01, 6)
  })

  it('treats a missing expired flag as not expired', async () => {
    const snapshot: BackendRunSnapshot = {
      run_id: 'run-1',
      status: 'waiting',
      pending_gate: {
        gate_id: 'scope-confirmation',
        node_id: 'confirm_scope',
        title: 'Confirm scope',
        summary: 'Check the scope.',
        editable: true,
        options: [],
      },
      frames: { count: 0, dropped: 0 },
      usage: {},
    }
    fetchMock.mockResolvedValueOnce(jsonResponse(snapshot))

    const result = await api.getRun('run-1')

    expect(result.status).toBe('waiting')
    expect(result.pending_gate?.expired).toBe(false)
  })

  it('maps a cancelling run to the stopping status', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      run_id: 'run-1',
      status: 'cancelling',
      pending_gate: null,
      frames: { count: 0, dropped: 0 },
      usage: {},
    }))

    await expect(api.getRun('run-1')).resolves.toMatchObject({ status: 'stopping' })
  })

  it('raises the server detail when a request fails', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 409,
      headers: new Headers(),
      text: async () => 'This gate was already answered.',
      json: async () => ({}),
    })

    await expect(api.cancelRun('run-1')).rejects.toThrow('This gate was already answered.')
  })

  it('falls back to mock mode when the API is not reachable', async () => {
    const probe = new StudioApi()
    fetchMock.mockRejectedValueOnce(new Error('connection refused'))
    await expect(probe.initialize()).resolves.toBe('mock')
  })

  it('selects live mode for a JSON workflow listing', async () => {
    const probe = new StudioApi()
    fetchMock.mockResolvedValueOnce(jsonResponse([{ id: 'idea-validator' }]))
    await expect(probe.initialize()).resolves.toBe('live')
  })
})
