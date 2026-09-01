import { buildMockSegments, type MockScriptStep } from '../data/mockFrames'
import { MOCK_GRAPH } from '../data/mockGraph'
import { readErrorDetail, retryAfterSentence } from '../data/serverLimits'
import { getAccessToken } from './authClient'
import type {
  BackendFramePage,
  BackendGatePrompt,
  BackendRunSnapshot,
  BackendRunStatus,
  FrameData,
  GateReply,
  GraphDescriptor,
  RunHistoryEntry,
  RunResult,
  RunSnapshot,
  StartRunResponse,
  StudioFrame,
  UsageMetrics,
} from '../types/studio'

export type GatesMode = 'human' | 'auto'

export type TransportMode = 'probing' | 'live' | 'mock'
export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'offline'

/** The two shapes `GET /api/runs/{run_id}/logs?format=` will serve. */
export type LogFormat = 'ndjson' | 'zip'

const LOG_FORMATS: Record<LogFormat, { extension: string; mimeType: string }> = {
  ndjson: { extension: 'ndjson', mimeType: 'application/x-ndjson' },
  zip: { extension: 'zip', mimeType: 'application/zip' },
}

/**
 * How long a gate reply sent over the socket waits for its `gate_ack` or
 * `error` before the operator is told to try again. The server applies the
 * reply on a worker thread and answers as soon as it lands, so this only ever
 * fires if the connection died mid-flight.
 */
const GATE_REPLY_ACK_TIMEOUT_MS = 15_000

interface PendingGateReply {
  resolve: () => void
  reject: (error: Error) => void
  timer: number
}

export interface StreamHandlers {
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

/*
 * How long the transport probe waits for the API before giving up.
 *
 * This was 900ms from the first commit, and it silently fabricated a whole run
 * for a real operator on 2026-09-01. The API is a Render *starter* service in
 * *singapore*; the probe has to cover a TLS handshake, and the service may be
 * cold. 900ms is not a timeout on that path, it is a coin flip - and losing the
 * flip did not surface an error, it produced a complete scripted validation
 * with a fabricated NEEDS_WORK verdict and a fabricated dollar cost.
 *
 * Eight seconds is chosen to be longer than a warm round trip to Singapore by a
 * wide margin while still bounded, because a page that hangs forever is its own
 * failure. A cold start can exceed even this - which is why timing out now
 * reports itself rather than fabricating.
 */
const PROBE_TIMEOUT_MS = 8000

/**
 * How long the probe waits for a bearer token before probing without one.
 *
 * `requestToken` has no timeout of its own, and the auth origin it calls is the
 * studio's own Node service on Render's FREE plan - which sleeps. Measured
 * 2026-09-01: `/api/auth/token` took **40s** on a cold hit and **2.12s** warm.
 * The page load normally wakes that service before any script runs, so warm is
 * the realistic case, but "normally" is not a guarantee worth hanging on.
 *
 * Probing WITHOUT a token is safe and is the right fallback: the API answers
 * 401, and `initialize` reads a 401 as `live`. The operator is told to sign in
 * rather than shown a fabricated run - which is the whole point.
 */
const TOKEN_MINT_TIMEOUT_MS = 4000

/**
 * `getAccessToken`, but it cannot hang the first paint. Never rejects.
 *
 * Returns the token so the caller can HAND it to `authedFetch` rather than
 * letting it mint again. That is not a convenience: `getAccessToken` shares a
 * single in-flight promise (`authClient.ts:141`, `if (inflight) return
 * inflight`), so after this races the mint and loses, a second call returns
 * that SAME still-pending promise and awaits it. The probe's `AbortController`
 * aborts a `fetch`; it does nothing to an await on an unrelated promise - so
 * the timeout here would have bounded only this function's own wall clock
 * while the probe went on to block for the full cold-start anyway.
 */
async function tokenOrNothing(): Promise<string | null> {
  let timer = 0
  return Promise.race([
    getAccessToken().catch(() => null),
    new Promise<null>((resolve) => {
      timer = window.setTimeout(() => resolve(null), TOKEN_MINT_TIMEOUT_MS)
    }),
  ]).finally(() => window.clearTimeout(timer))
}

export class StudioApi {
  mode: TransportMode = 'probing'
  /**
   * Why the last probe did not reach a live backend, or null when it did.
   *
   * Deliberately NOT routed through `lastError`: `launch()` clears that on
   * every attempt, so a transport problem would erase itself the moment the
   * operator tried the button that cannot work.
   */
  probeFailure: string | null = null
  private readonly baseUrl = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''
  private readonly mockRuns = new Map<string, MockRun>()
  private readonly liveSockets = new Map<string, WebSocket>()
  private readonly pendingGateReplies = new Map<string, PendingGateReply>()
  private gateReplyCounter = 0

  async initialize(force = false): Promise<TransportMode> {
    if (!force && this.mode !== 'probing') return this.mode

    this.probeFailure = null
    /*
     * The token is minted BEFORE the clock starts. `authedFetch` opens with
     * `await getAccessToken(...)`, which is itself a network request to the
     * Node auth origin - so arming the timer first made the budget cover two
     * sequential round trips to two different Render services plus a CORS
     * preflight (`Authorization` is not a safelisted header, so the API GET is
     * really two requests). The probe was timing the wrong thing.
     */
    const token = await tokenOrNothing()
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS)
    try {
      /*
       * `allowRetry = false`, and that is load-bearing rather than tidy.
       * `authedFetch`'s 401 retry recurses with the SAME `init`, hence the same
       * `signal` - so a 401 arriving near the deadline was retried on an
       * already-aborted controller, throwing, and landing in the `catch` below
       * as "offline". That defeated the "a 401 means LIVE" invariant this
       * function documents at length. The probe reads the status itself; it
       * does not need a retry to do that.
       */
      const response = await this.authedFetch(
        '/api/workflows',
        { headers: { Accept: 'application/json' }, signal: controller.signal },
        false,
        // Do NOT force a fresh mint. `tokenOrNothing()` just cached one; a
        // forced re-mint here is a second round trip to a sleeping auth
        // service INSIDE the timed window - the exact defect being repaired.
        false,
        // And do not mint AT ALL: use what the bounded race returned, even if
        // that is null. Asking again would await the shared in-flight promise
        // that the race just timed out on, defeating the bound entirely.
        token,
      )
      const contentType = response.headers.get('content-type') ?? ''
      /*
       * A 401 means LIVE, not mock, and getting this wrong is the worst bug
       * this file can have.
       *
       * The old test was `response.ok`, so once the API started requiring
       * authentication, a signed-out visitor - or one whose token had not been
       * minted yet on first paint - probed, got 401, and was dropped into the
       * silent scripted mock: a complete, entirely fabricated run with nothing
       * on screen to say so. That is Deployment trap 2 reached by a new route.
       *
       * The distinction is sound because a 401 can only come from a real
       * server. There is nothing to fall back TO when the backend is
       * demonstrably answering; the right response is to sign in.
       */
      if (response.status === 401) {
        this.mode = 'live'
      } else if (response.ok && contentType.includes('application/json')) {
        this.mode = 'live'
      } else if (response.ok) {
        /*
         * 200, but not JSON. This is a MISCONFIGURATION, never an outage, and
         * it has one overwhelmingly likely cause: `VITE_API_URL` is empty or
         * wrong, so `/api/workflows` resolved against the studio's own origin
         * and hit the SPA history fallback, which answers 200 text/html for
         * any unmatched path. `render.yaml` declares that variable `sync:
         * false`, so an apply into a fresh service leaves it unset - and it is
         * baked in at BUILD time, so nothing at runtime can correct it.
         *
         * Falling back to mock here was the worst possible response: the one
         * case where the operator is looking at the wrong server entirely is
         * the case where a convincing fabricated run is most misleading.
         */
        this.mode = 'mock'
        this.probeFailure =
          `The validator API is misconfigured: ${this.baseUrl || window.location.origin}` +
          `/api/workflows answered ${response.status} ${contentType || 'with no content type'}` +
          ' instead of JSON. This usually means VITE_API_URL was not set when the site was built.'
      } else {
        this.mode = 'mock'
        this.probeFailure =
          `The validator API answered ${response.status} ${response.statusText}.`
      }
    } catch (error) {
      /*
       * An abort and a genuine network failure are DIFFERENT diagnoses and used
       * to collapse into a bare `catch {}` that recorded nothing at all. A
       * timeout against a cold Render service means "wait and reload"; a
       * network error means "the service is unreachable". Neither means "here
       * is a validation report".
       */
      this.mode = 'mock'
      this.probeFailure =
        (error as Error)?.name === 'AbortError'
          ? `The validator API did not respond within ${PROBE_TIMEOUT_MS / 1000}s.` +
            ' It may be starting up - reload in a moment.'
          : `The validator API could not be reached: ${(error as Error)?.message ?? 'network error'}.`
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

  /**
   * `gates` names who answers the scope and verdict gates. It is sent as a
   * declared request field and never as an entry in `inputs`: the server
   * refuses the reserved key `no_gates` there with a 422, because that
   * undeclared path used to reach the flow's state directly and start an
   * unattended run with no policy attached to it.
   */
  async startRun(
    sessionId: string,
    idea: string,
    workflowId = 'idea-validator',
    gates: GatesMode = 'human',
  ): Promise<StartRunResponse> {
    await this.initialize(this.mode === 'mock')
    if (this.mode === 'live') {
      return this.fetchJson<StartRunResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow_id: workflowId, inputs: { idea }, gates }),
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
        // The finished report. Dropping this here is what made a completed run
        // show less than a mid-flight one: the body arrives on every snapshot
        // and had no field to land in.
        result: snapshot.result ?? null,
      }
    }
    const run = this.mockRuns.get(id)
    if (!run) throw new Error('This mock run is no longer available after refresh.')
    /*
     * Read the status and the result off the frames actually emitted, rather
     * than hardcoding `status: 'running'` as this branch did until 2026-09-01.
     * A finished demonstration reported itself as still running, and carried no
     * `result` key at all while the live branch two lines up carefully
     * preserves one - so the mock diverged from its subject in exactly the way
     * that makes a double certify nothing.
     */
    // A reverse scan rather than `Array.findLast`, which needs lib es2023 -
    // raising the lib target for one call would change what compiles across
    // five tsconfig projects.
    let terminal: FrameData | undefined
    for (let index = run.emitted.length - 1; index >= 0; index -= 1) {
      if (run.emitted[index].kind === 'run_state') {
        terminal = run.emitted[index]
        break
      }
    }
    const details = (terminal?.details ?? {}) as {
      status?: BackendRunStatus
      result?: RunResult
    }
    return {
      run_id: id,
      status: normalizeRunStatus(details.status ?? 'running'),
      pending_gate: null,
      frames: {
        count: run.emitted.length,
        dropped: 0,
        first_seq: run.emitted.at(0)?.seq ?? null,
        last_seq: run.emitted.at(-1)?.seq ?? null,
      },
      usage: emptyUsage(),
      result: details.result ?? null,
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

    /*
     * Async, because the token has to be fetched before the URL can be built.
     *
     * Two consequences are handled below and neither is optional. The `closed`
     * flag is re-checked AFTER the await: an unsubscribe that lands while the
     * token is in flight would otherwise open a socket nobody is listening to,
     * which then reconnects forever. And every caller is fire-and-forget, so
     * this must never reject - `getAccessToken` already swallows its own
     * failures and returns null, and a null token simply produces the
     * unauthenticated URL the server will refuse with 4401.
     */
    const connect = async () => {
      handlers.onStatus(attempts === 0 ? 'connecting' : 'reconnecting')
      const token = await getAccessToken()
      if (closed) return
      const base = new URL(this.baseUrl || window.location.origin, window.location.origin)
      base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:'
      base.pathname = '/ws'
      /*
       * The credential rides in the query string because the browser
       * WebSocket API cannot set request headers on a handshake - there is no
       * `Authorization` option to pass. The server documents the same
       * trade-off from its side (`service/app.py::stream_frames`): a URL is
       * logged where a header is not, which is survivable only because this is
       * the 15-minute JWT and never the session cookie.
       */
      const query: Record<string, string> = {
        session_id: sessionId,
        run_id: runIdValue,
        after: String(handlers.getAfter()),
      }
      if (token) query.access_token = token
      base.search = new URLSearchParams(query).toString()
      socket = new WebSocket(base)

      socket.addEventListener('open', () => {
        attempts = 0
        if (socket) this.liveSockets.set(runIdValue, socket)
        handlers.onStatus('connected')
        pingTimer = window.setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'ping' }))
        }, 20_000)
      })
      socket.addEventListener('message', (event) => {
        try {
          const message = JSON.parse(String(event.data)) as StudioFrame | { type: string; data?: unknown }
          if (message.type === 'frame' && 'data' in message) {
            handlers.onFrame((message as StudioFrame).data)
            return
          }
          // gate_ack / error carry the request_id of the reply they answer.
          if (message.type === 'gate_ack' || message.type === 'error') this.settleGateReply(message)
        } catch {
          // A malformed server frame is ignored; the sequence gap triggers replay.
        }
      })
      socket.addEventListener('close', () => {
        window.clearInterval(pingTimer)
        if (this.liveSockets.get(runIdValue) === socket) this.liveSockets.delete(runIdValue)
        this.failPendingGateReplies('The connection dropped before the gate reply was acknowledged.')
        if (closed) return
        attempts += 1
        handlers.onStatus('reconnecting')
        reconnectTimer = window.setTimeout(connect, Math.min(800 * 2 ** attempts, 10_000))
      })
      socket.addEventListener('error', () => socket?.close())
    }

    // Floating on purpose: `connect` is async now but never rejects, and the
    // caller wants the unsubscribe function back immediately, not a socket.
    void connect()
    return () => {
      closed = true
      window.clearTimeout(reconnectTimer)
      window.clearInterval(pingTimer)
      if (this.liveSockets.get(runIdValue) === socket) this.liveSockets.delete(runIdValue)
      socket?.close()
      handlers.onStatus('offline')
    }
  }

  async replyGate(runIdValue: string, gateId: string, reply: GateReply): Promise<void> {
    if (this.mode === 'live') {
      // PRD F27/F37: answer on the connection that is already streaming the
      // run. HTTP stays the fallback for a reply made while the socket is
      // down - both land on one server-side code path, so the outcome, the
      // duplicate refusal and the late-reply handling are identical.
      const socket = this.liveSockets.get(runIdValue)
      if (socket?.readyState === WebSocket.OPEN) {
        await this.replyGateOverSocket(socket, gateId, reply)
        return
      }
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

  private replyGateOverSocket(socket: WebSocket, gateId: string, reply: GateReply): Promise<void> {
    this.gateReplyCounter += 1
    const requestId = `gate-${this.gateReplyCounter}-${Date.now().toString(36)}`
    return new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pendingGateReplies.delete(requestId)
        reject(new Error('The gate reply was not acknowledged. Check the activity stream and try again.'))
      }, GATE_REPLY_ACK_TIMEOUT_MS)
      this.pendingGateReplies.set(requestId, { resolve, reject, timer })
      try {
        socket.send(
          JSON.stringify({
            type: 'gate_reply',
            request_id: requestId,
            data: { gate_id: gateId, outcome: reply.outcome, fields: reply.fields ?? {} },
          }),
        )
      } catch (error) {
        window.clearTimeout(timer)
        this.pendingGateReplies.delete(requestId)
        reject(error instanceof Error ? error : new Error('The gate reply could not be sent.'))
      }
    })
  }

  private settleGateReply(message: { type: string; data?: unknown }): void {
    const data = isRecord(message.data) ? message.data : {}
    const requestId = typeof data.request_id === 'string' ? data.request_id : ''
    const pending = this.pendingGateReplies.get(requestId)
    if (!pending) return
    window.clearTimeout(pending.timer)
    this.pendingGateReplies.delete(requestId)
    if (message.type === 'gate_ack') {
      pending.resolve()
      return
    }
    const detail = typeof data.message === 'string' ? data.message : 'The gate response was not accepted.'
    pending.reject(new Error(detail))
  }

  private failPendingGateReplies(reason: string): void {
    for (const [requestId, pending] of this.pendingGateReplies) {
      window.clearTimeout(pending.timer)
      this.pendingGateReplies.delete(requestId)
      pending.reject(new Error(reason))
    }
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

  /**
   * The signed-in caller's own runs, newest first.
   *
   * Returns an empty list rather than throwing when the transport is mocked or
   * the server refuses: a history sidebar failing to load must never be the
   * thing that stops someone launching a run. The API applies the ownership
   * filter in SQL, so there is nothing to filter here.
   */
  /**
   * The caller's runs, newest first.
   *
   * THROWS on failure rather than returning `[]`, and that is the whole point.
   * A `catch { return [] }` here converted every 401, 5xx, CORS refusal and
   * network drop into the positive claim "you have no runs" - which the panel
   * renders as "Nothing yet. Launch a validation and it will appear here."
   *
   * Observed in production on 2026-09-01: a run that had genuinely completed,
   * and that `GET /api/runs` returned when asked directly, showed as an empty
   * history. The likely trigger is the first paint racing the token mint, so
   * the request 401s once and the emptiness is then indistinguishable from the
   * truth. It is the same defect class as the transport probe: a failure
   * rendered as a confident negative.
   *
   * An empty ARRAY still means empty. Only an error means "could not load".
   */
  async listRuns(limit = 25): Promise<RunHistoryEntry[]> {
    if (this.mode !== 'live') return []
    const page = await this.fetchJson<{ runs: RunHistoryEntry[] }>(
      `/api/runs?limit=${encodeURIComponent(String(limit))}`,
    )
    return page.runs ?? []
  }

  async downloadLogs(runIdValue: string, format: LogFormat = 'ndjson'): Promise<void> {
    if (this.mode === 'live') {
      const response = await this.authedFetch(
        `/api/runs/${encodeURIComponent(runIdValue)}/logs?format=${encodeURIComponent(format)}`,
      )
      if (!response.ok) throw new Error(`Log download failed (${response.status})`)
      // The blob is only created once the response is known good, so a failed
      // request never reaches `saveBlob` and never mints an object URL.
      saveBlob(await response.blob(), this.logFilename(runIdValue, LOG_FORMATS[format].extension))
      return
    }

    // The mock transport has no server to archive anything, so it always hands
    // back the NDJSON it holds in memory - and names the file for what it is
    // rather than for what was asked.
    const content = (this.mockRuns.get(runIdValue)?.emitted ?? [])
      .map((frame) => JSON.stringify({ type: 'frame', data: frame }))
      .join('\n')
    const blob = new Blob([content], { type: LOG_FORMATS.ndjson.mimeType })
    saveBlob(blob, this.logFilename(runIdValue, LOG_FORMATS.ndjson.extension))
  }

  /**
   * A demonstration export is named as one.
   *
   * This was `validator-${id8}.${extension}` for both transports, so the file
   * a scripted run hands you is byte-indistinguishable *by name* from a real
   * archive - and its contents are plausible NDJSON frames. An operator
   * downloaded one on 2026-09-01, could not tell what it was, and reasonably
   * concluded the backend had failed to produce a report.
   */
  private logFilename(runIdValue: string, extension: string): string {
    const prefix = this.mode === 'live' ? 'validator' : 'validator-DEMO-not-a-real-run'
    return `${prefix}-${runIdValue.slice(0, 8)}.${extension}`
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

  /**
   * `fetch` with the bearer token attached, and one retry on 401.
   *
   * The retry matters because the client's idea of freshness is only a guess.
   * `getAccessToken` decides from the token's own `exp`, but the API is the
   * authority: a session revoked server-side, or a key rotated on the auth
   * service, leaves a token here that still looks perfectly valid. Rather than
   * showing the operator "your session has expired" for a session that has not,
   * a 401 forces one fresh mint and one retry. Exactly one - a second 401 is
   * the real answer, and looping would turn an expired login into a hot loop
   * against the auth service.
   */
  private async authedFetch(
    path: string,
    init?: RequestInit,
    allowRetry = true,
    /*
     * Whether to bypass the token cache. SEPARATE from `allowRetry`, because
     * conflating them is a trap: the retry leg passed `allowRetry = false` and
     * the force flag was derived from it as `!allowRetry`, so ANY caller asking
     * merely "do not retry" also silently demanded a fresh network mint.
     *
     * `initialize` is exactly such a caller - and a forced mint there is a
     * second round trip to a sleeping free-plan auth service, inside the very
     * window the probe is timing. That is the defect the probe repair exists to
     * remove, so deriving it would have reintroduced it one line later.
     *
     * The retry leg still forces, which is the whole point of retrying: a
     * server-side revocation leaves a cached token that still looks valid.
     */
    forceToken = !allowRetry,
    /*
     * A token the caller already holds. `undefined` means "mint one";
     * anything else (a string OR null) is used as-is with no mint at all.
     *
     * `initialize` needs this because `getAccessToken` shares one in-flight
     * promise, so asking again after a timed-out race just awaits the same
     * pending mint - outside the AbortController's reach.
     */
    presetToken?: string | null,
  ): Promise<Response> {
    const token =
      presetToken === undefined ? await getAccessToken(forceToken) : presetToken
    const headers = new Headers(init?.headers)
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers })
    if (response.status === 401 && allowRetry && token) {
      return this.authedFetch(path, init, false)
    }
    return response
  }

  private async fetchJson<T = unknown>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.authedFetch(path, init)
    if (!response.ok) {
      /*
       * What the operator is shown when the server refuses.
       *
       * This used to be `new Error(await response.text())`, so a 2001-character
       * idea surfaced in the UI as the literal string
       *   {"detail":"inputs.idea is limited to 2000 characters; this one is 2001"}
       * - braces, quotes, key and all. The server's message was already good;
       * the client was showing the envelope around it.
       *
       * The 429 is the sharper case. The server computes `Retry-After`, and
       * `CORS_EXPOSE_HEADERS` names it precisely so a cross-origin client can
       * read it - a deliberate decision made for a reader that did not exist.
       * Now it does.
       */
      const body = await response.text().catch(() => '')
      let message = readErrorDetail(body, response.status)
      if (response.status === 429) {
        message += retryAfterSentence(response.headers.get('Retry-After'))
      }
      throw new Error(message)
    }
    return response.json() as Promise<T>
  }
}

/**
 * Hands a blob to the browser's download machinery.
 *
 * An object URL is a document-lifetime entry in the blob URL store: nothing
 * reclaims it, so every one that is minted has to be revoked or the blob stays
 * resident until the tab closes. The revoke is in `finally` because `click()`
 * can throw - a blocked popup, a detached document during teardown - and a
 * throw on the happy path was the one way this could leak.
 *
 * The revoke is synchronous, immediately after the click. Chromium and Firefox
 * both resolve the blob URL while the click is still being dispatched, so the
 * download is already underway by then. WebKit has historically been less
 * forgiving; if a Safari download ever comes back empty, this is the line, and
 * the fix is to defer the revoke rather than to drop it.
 */
function saveBlob(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = filename
  anchor.rel = 'noopener'
  anchor.style.display = 'none'
  document.body.append(anchor)
  try {
    anchor.click()
  } finally {
    anchor.remove()
    URL.revokeObjectURL(href)
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
    // The server resolves PRD F03 expiry at read time; the client renders it
    // rather than deciding it. An older backend without the field reads as
    // not-expired, which is the permissive direction.
    expired: gate.expired === true,
    options: gate.options,
    fields: gate.fields ?? undefined,
    // Read-only values. An older backend sends none, which reads as "nothing
    // derived" - the permissive direction for display, and safe for editing
    // because `fields` is what the form is built from either way.
    derived: gate.derived ?? undefined,
    verdict: gate.verdict ?? undefined,
    confidence: gate.confidence ?? undefined,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
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

/**
 * The transport surface `useValidatorRun` depends on. Declaring it lets the
 * composable be driven by a deterministic double in tests without touching a
 * socket, exactly as the Python crews take injected factories.
 */
export type StudioApiLike = Pick<
  StudioApi,
  | 'mode'
  | 'probeFailure'
  | 'initialize'
  | 'getGraph'
  | 'startRun'
  | 'getRun'
  | 'getFrames'
  | 'subscribe'
  | 'replyGate'
  | 'cancelRun'
  | 'downloadLogs'
  | 'listRuns'
>

export const studioApi = new StudioApi()