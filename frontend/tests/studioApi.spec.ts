import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { StudioApi, type ConnectionStatus, type StreamHandlers } from '../src/services/studioApi'
import { clearAccessToken, setSessionActive } from '../src/services/authClient'
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

/**
 * Wait for `subscribe()` to actually open its socket.
 *
 * `subscribe` is still synchronous and still returns its unsubscribe function
 * immediately, but the socket behind it is now opened on a microtask: the
 * bearer token has to be fetched before the /ws URL can be built, and the
 * browser WebSocket API has no way to send it as a header. So the FakeWebSocket
 * does not exist on the line after `subscribe`.
 *
 * Polling microtasks rather than awaiting a fixed number of them, because the
 * count is an implementation detail of how many `await`s `connect` happens to
 * contain, and a test that encodes it breaks on any refactor that adds one.
 */
async function socketOpened(index = 0): Promise<FakeWebSocket> {
  for (let tick = 0; tick < 25 && !FakeWebSocket.instances[index]; tick += 1) {
    await Promise.resolve()
  }
  const socket = FakeWebSocket.instances[index]
  if (!socket) throw new Error(`no websocket opened at index ${index}`)
  return socket
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

  it('opens the stream at the cursor the client has already consumed', async () => {
    const stream = recorder(() => 42)
    api.subscribe('run-1', 'session-9', stream.handlers)

    const socket = await socketOpened()
    const url = new URL(socket.url)
    expect(url.pathname).toBe('/ws')
    expect(url.searchParams.get('run_id')).toBe('run-1')
    expect(url.searchParams.get('session_id')).toBe('session-9')
    expect(url.searchParams.get('after')).toBe('42')
    expect(stream.statuses).toEqual(['connecting'])
  })

  it('reports connection state and forwards frames', async () => {
    const stream = recorder()
    api.subscribe('run-1', 'session-9', stream.handlers)
    const socket = await socketOpened()

    socket.accept()
    socket.deliver({ type: 'frame', data: frame(1) })
    socket.deliver({ type: 'frame', data: frame(2) })

    expect(stream.statuses).toEqual(['connecting', 'connected'])
    expect(stream.frames.map((value) => value.seq)).toEqual([1, 2])
  })

  it('survives a malformed or unknown message', async () => {
    const stream = recorder()
    api.subscribe('run-1', 'session-9', stream.handlers)
    const socket = await socketOpened()
    socket.accept()

    expect(() => socket.deliverRaw('{not json')).not.toThrow()
    expect(() => socket.deliver({ type: 'pong' })).not.toThrow()
    expect(stream.frames).toEqual([])
  })

  it('pings an idle connection', async () => {
    api.subscribe('run-1', 'session-9', recorder().handlers)
    const socket = await socketOpened()
    socket.accept()

    vi.advanceTimersByTime(20_000)

    expect(socket.lastSent).toEqual({ type: 'ping' })
  })

  it('reconnects after a drop and resumes from the newest cursor', async () => {
    let cursor = 0
    const stream = recorder(() => cursor)
    api.subscribe('run-1', 'session-9', stream.handlers)
    const first = await socketOpened()
    first.accept()
    first.deliver({ type: 'frame', data: frame(7) })
    cursor = 7

    first.close()
    expect(stream.statuses).toEqual(['connecting', 'connected', 'reconnecting'])

    vi.advanceTimersByTime(1600)
    const second = await socketOpened(1)

    expect(FakeWebSocket.instances).toHaveLength(2)
    expect(new URL(second.url).searchParams.get('after')).toBe('7')
  })

  it('stops reconnecting once the caller unsubscribes', async () => {
    const stream = recorder()
    const unsubscribe = api.subscribe('run-1', 'session-9', stream.handlers)
    const socket = await socketOpened()
    socket.accept()

    unsubscribe()
    vi.advanceTimersByTime(60_000)

    expect(socket.readyState).toBe(FakeWebSocket.CLOSED)
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(stream.statuses.at(-1)).toBe('offline')
  })

  it('answers a gate on the live socket and resolves on the ack', async () => {
    api.subscribe('run-1', 'session-9', recorder().handlers)
    const socket = await socketOpened()
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
    const socket = await socketOpened()
    socket.accept()

    const reply = api.replyGate('run-1', 'scope-confirmation', { outcome: 'scope_ok' })
    const requestId = socket.lastSent.request_id
    socket.deliver({ type: 'error', data: { request_id: requestId, message: 'This gate was already answered.' } })

    await expect(reply).rejects.toThrow('This gate was already answered.')
  })

  it('rejects an unacknowledged gate reply when the connection drops', async () => {
    api.subscribe('run-1', 'session-9', recorder().handlers)
    const socket = await socketOpened()
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

  /*
   * The probe fabricated a complete run for a real operator on 2026-09-01. It
   * allowed 900ms - a budget that had to cover a token mint to the auth origin,
   * a CORS preflight and the API GET, against a Render starter service in
   * Singapore - then swallowed the abort in a bare `catch {}` and served a
   * scripted validation with a NEEDS_WORK verdict and a dollar cost.
   */
  describe('the transport probe', () => {
    it('records why it failed instead of silently fabricating', async () => {
      const probe = new StudioApi()
      const abort = new Error('The operation was aborted.')
      abort.name = 'AbortError'
      fetchMock.mockRejectedValueOnce(abort)

      await expect(probe.initialize()).resolves.toBe('mock')

      expect(probe.probeFailure).toBeTruthy()
      expect(probe.probeFailure).toContain('did not respond')
      // The operator is told what to do, not merely that something broke.
      expect(probe.probeFailure).toContain('starting up')
    })

    it('names a network failure differently from a timeout', async () => {
      const probe = new StudioApi()
      fetchMock.mockRejectedValueOnce(new Error('connection refused'))

      await expect(probe.initialize()).resolves.toBe('mock')

      expect(probe.probeFailure).toContain('could not be reached')
      expect(probe.probeFailure).toContain('connection refused')
    })

    it('waits longer than a warm cross-region round trip', async () => {
      const probe = new StudioApi()
      // 1.2s would have been a timeout under the old 900ms budget. It is a
      // perfectly ordinary response time to Singapore.
      fetchMock.mockImplementationOnce(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve(jsonResponse([{ id: 'idea-validator' }])), 1_200),
          ),
      )

      await expect(probe.initialize()).resolves.toBe('live')
      expect(probe.probeFailure).toBeNull()
    })

    it('treats a 200 text/html as a misconfiguration, not as offline', async () => {
      const probe = new StudioApi()
      // What the studio's own SPA history fallback answers for any unmatched
      // path - which is where `/api/workflows` lands when VITE_API_URL is unset.
      fetchMock.mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: new Headers({ 'content-type': 'text/html' }),
        text: async () => '<!doctype html>',
        json: async () => ({}),
      })

      await expect(probe.initialize()).resolves.toBe('mock')

      expect(probe.probeFailure).toContain('misconfigured')
      expect(probe.probeFailure).toContain('VITE_API_URL')
    })

    it('does not mint the token a second time inside its own timed window', async () => {
      /*
       * The probe passes `allowRetry = false`, and `authedFetch` used to derive
       * its force-a-fresh-token flag as `!allowRetry` - so "do not retry" also
       * meant "bypass the cache and mint again". That put a second round trip
       * to a sleeping free-plan auth service back inside the window the probe
       * is timing, which is the defect this whole repair exists to remove.
       *
       * Measured 2026-09-01: that mint is 2.12s warm and 40s cold.
       */
      const probe = new StudioApi()
      const tokenCalls: string[] = []
      fetchMock.mockImplementation((input: unknown) => {
        const url = String(input)
        if (url.includes('/api/auth/token')) {
          tokenCalls.push(url)
          return Promise.resolve(jsonResponse({ token: 'not-a-real-token' }))
        }
        return Promise.resolve(jsonResponse([{ id: 'idea-validator' }]))
      })

      // The session MUST be activated, or this test is vacuous: `getAccessToken`
      // returns null without one (`authClient.ts:139`), zero token requests are
      // made, and `expect(0).toBe(1)`-style assertions pass with the defect
      // fully present. That is the state this test shipped in for one commit.
      setSessionActive(true)
      clearAccessToken()
      try {
        await expect(probe.initialize()).resolves.toBe('live')
      } finally {
        setSessionActive(false)
      }

      // Exactly one. Two means the probe re-minted inside its own timed window.
      expect(tokenCalls).toHaveLength(1)
    })

    it('still reads a 401 as live, and does not retry onto its own aborted signal', async () => {
      const probe = new StudioApi()
      fetchMock.mockResolvedValueOnce({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        headers: new Headers({ 'content-type': 'application/json' }),
        text: async () => '{"detail":"sign in to use this endpoint"}',
        json: async () => ({ detail: 'sign in to use this endpoint' }),
      })

      await expect(probe.initialize()).resolves.toBe('live')
      expect(probe.probeFailure).toBeNull()
      // Exactly one request: the retry would recurse with the same (aborted)
      // signal, which is how a late 401 used to be reclassified as offline.
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
  })
})

/**
 * A failed request must never be reported as an empty result.
 *
 * `listRuns` swallowed every failure into `[]`, and `RunHistory.vue` renders an
 * empty list as "Nothing yet. Launch a validation and it will appear here."
 * Observed in production on 2026-09-01: a run that had genuinely completed, and
 * that `GET /api/runs` returned when asked directly, showed as no runs at all.
 * The likely trigger is the first paint racing the token mint - one 401, and
 * the emptiness becomes indistinguishable from the truth.
 *
 * Same defect class as the transport probe this session repaired: a failure
 * rendered as a confident negative claim.
 */
describe('StudioApi.listRuns', () => {
  let api: StudioApi
  let fetchMock: ReturnType<typeof vi.fn>
  let originalFetch: typeof globalThis.fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
    fetchMock = vi.fn()
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch
    api = new StudioApi()
    api.mode = 'live'
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('returns the runs the server sent', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ runs: [{ run_id: 'r-1', workflow_id: 'idea-validator', status: 'completed' }] }),
      text: async () => '',
    })

    await expect(api.listRuns()).resolves.toHaveLength(1)
  })

  it('reports an empty list as empty', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ runs: [] }),
      text: async () => '',
    })

    await expect(api.listRuns()).resolves.toEqual([])
  })

  it('THROWS on a 401 rather than claiming the operator has no runs', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      headers: new Headers({ 'content-type': 'application/json' }),
      text: async () => '{"detail":"sign in to use this endpoint"}',
      json: async () => ({ detail: 'sign in to use this endpoint' }),
    })

    await expect(api.listRuns()).rejects.toThrow()
  })

  it('THROWS on a network failure', async () => {
    fetchMock.mockRejectedValueOnce(new Error('connection refused'))

    await expect(api.listRuns()).rejects.toThrow('connection refused')
  })
})
