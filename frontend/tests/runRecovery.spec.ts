import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { App } from 'vue'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import { FakeStudioApi, RUN_ID, emptySnapshot, flush, frameFactory, withSetup } from './helpers'

type ValidatorRun = ReturnType<typeof useValidatorRun>

const ACTIVE_RUN_KEY = 'validator-active-run'
const SESSION_KEY = 'validator-session-id'

function seedStoredRun(runId = RUN_ID): void {
  localStorage.setItem(
    ACTIVE_RUN_KEY,
    JSON.stringify({ version: 1, runId, sessionId: 'session-abc', workflowId: 'idea-validator' }),
  )
  localStorage.setItem(SESSION_KEY, 'session-abc')
}

function storedRun(): { runId?: string } | null {
  const raw = localStorage.getItem(ACTIVE_RUN_KEY)
  return raw ? (JSON.parse(raw) as { runId?: string }) : null
}

describe('run context persistence', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App

  beforeEach(() => {
    localStorage.clear()
    api = new FakeStudioApi()
  })

  afterEach(() => {
    app?.unmount()
  })

  it('saves the run context when a run is launched', async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()

    expect(storedRun()?.runId).toBe(RUN_ID)
    expect(localStorage.getItem(SESSION_KEY)).toBeTruthy()
  })

  /**
   * INVERTED 2026-09-06 (item 58, ROUND-2 R4), and the reasoning of BOTH
   * contracts is kept because they answer different halves of one question.
   *
   * These cases used to assert that a terminal status DROPPED the pointer.
   * That was written for a real defect - nothing ever removed it, so the
   * console reopened a stale result on every later load - and it overshot: the
   * console was the only place a run's report, verdict and trace existed, and
   * the moment a run ended they became unreachable from anywhere. A synthetic
   * builder run is over in ~115 ms and the pointer lived 30-40 ms.
   *
   * What replaced the old line is not "nothing". The home reads the pointer's
   * STATUS (D2): `live` hands over to the console, `terminal` shows a "Last
   * run" card and stays put. So a finished run is offered rather than imposed,
   * which is the outcome the original defect wanted and this one keeps.
   *
   * All three end frames carry `WORKFLOW_END`, because that is the only event
   * type the backend has for the end of a run: `FlowFinishedEvent` in
   * `events/serializer.py` and both cancellation paths in
   * `service/registry.py` emit it, and `details.status` is what tells them
   * apart. These cases used to name `RUN_COMPLETED` / `RUN_CANCELLED` /
   * `RUN_FAILED`, which are not values of `UIEventType` and never reach a
   * client. Keeping the real name here also pins the precedence the composable
   * relies on: an explicit `cancelled` or `failed` status must beat the
   * `WORKFLOW_END`-means-completed fallback.
   */
  it.each([
    ['completed', 'WORKFLOW_END'],
    ['cancelled', 'WORKFLOW_END'],
    ['failed', 'WORKFLOW_END'],
  ])('KEEPS the saved run when it ends as %s, so it can be reopened', async (status, eventType) => {
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
    expect(storedRun()).not.toBeNull()

    const build = frameFactory()
    api.emit(build('run_state', { event_type: eventType, details: { status } }))
    await flush()

    expect(storedRun()?.runId).toBe(RUN_ID)
    expect(['completed', 'cancelled', 'error']).toContain(run.status.value)
  })

  it('keeps the saved run when an error frame ends it', async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()

    const build = frameFactory()
    api.emit(build('error', { event_type: 'WORKFLOW_END', level: 'ERROR', message: 'boom' }))
    await flush()

    // A failed run is the one an operator most wants to look at again.
    expect(storedRun()?.runId).toBe(RUN_ID)
  })

  /** The pointer is REPLACED by the next launch, not accumulated. */
  it('replaces the pointer on the next launch', async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
    const build = frameFactory()
    api.emit(build('run_state', { event_type: 'WORKFLOW_END', details: { status: 'completed' } }))
    await flush()

    api.runIdToIssue = 'run-the-second'
    await run.launch()
    expect(storedRun()?.runId).toBe('run-the-second')
  })

  /**
   * And it is put down when the operator ASKS to leave, which is the one thing
   * the removed line used to do by accident. `StudioView.backToValidator`
   * reloads the page, so a surviving pointer at a builder workflow would
   * restore that run and repoint the console straight back at the graph they
   * just asked to leave.
   */
  it('forgets the run on request', async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
    expect(storedRun()).not.toBeNull()

    run.forgetRun()
    expect(storedRun()).toBeNull()
  })

  it('recovers an in-flight run after a refresh and keeps streaming it', async () => {
    seedStoredRun()
    api.snapshot = { ...emptySnapshot(RUN_ID, 'waiting'), frames: { count: 2, dropped: 1, first_seq: 1, last_seq: 2 } }
    const build = frameFactory()
    api.storedFrames = [
      build('node_state', { event_type: 'NODE_START', node_id: 'scope_idea' }),
      build('node_state', { event_type: 'NODE_END', node_id: 'scope_idea' }),
    ]

    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await flush()

    expect(run.runId.value).toBe(RUN_ID)
    expect(run.status.value).toBe('waiting')
    expect(run.lastSequence.value).toBe(2)
    expect(run.droppedFrames.value).toBe(1)
    expect(run.graphNodes.value.find((node) => node.id === 'scope_idea')?.data?.state).toBe('completed')
    // The stream is reattached from the recovered cursor, not from zero.
    expect(api.subscribeCalls).toEqual([{ runId: RUN_ID, after: 2 }])
    // Still in flight, so the pointer survives for the next refresh.
    expect(storedRun()?.runId).toBe(RUN_ID)
  })

  /**
   * INVERTED with the cases above (item 58, R4). It read "drops a saved run
   * that already finished instead of re-opening it", and re-opening it is now
   * the point: the home offers a "Last run" card and this is the screen that
   * card arrives at, so landing on a blank console would be the card lying.
   *
   * The snapshot here carries NO result, which is deliberate - the old code
   * reset in exactly that case, and a cancelled run has no report and a trace
   * worth reading.
   */
  it('re-opens a saved run that already finished, and keeps its pointer', async () => {
    seedStoredRun()
    api.snapshot = emptySnapshot(RUN_ID, 'completed')

    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await flush()

    expect(storedRun()?.runId).toBe(RUN_ID)
    expect(run.runId.value).toBe(RUN_ID)
    expect(run.status.value).toBe('completed')
    // Nothing more will stream for it, so no socket is opened.
    expect(api.subscribeCalls).toEqual([])
  })

  it('drops a saved run the server can no longer serve', async () => {
    seedStoredRun('run-that-was-purged')
    api.getRunError = new Error('Run not found (404)')

    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await flush()

    expect(storedRun()).toBeNull()
    expect(run.status.value).toBe('error')
    expect(run.lastError.value).toBe('Run not found (404)')
  })

  it('reuses the stored session id across reloads', async () => {
    seedStoredRun()
    api.snapshot = emptySnapshot(RUN_ID, 'running')
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await flush()

    expect(localStorage.getItem(SESSION_KEY)).toBe('session-abc')
  })

  it('renders and runs normally when site data is blocked', async () => {
    const denied = (): never => {
      throw new DOMException('The operation is insecure.', 'SecurityError')
    }
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(denied)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(denied)
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(denied)

    ;[run, app] = withSetup(() => useValidatorRun(api))
    await expect(run.initialize()).resolves.toBeUndefined()
    await run.launch()

    expect(run.runId.value).toBe(RUN_ID)
    expect(run.status.value).toBe('queued')
    expect(run.lastError.value).toBe('')
    expect(run.graphNodes.value.length).toBeGreaterThan(0)

    // A terminal run must not throw on the clear path either.
    const build = frameFactory()
    api.emit(build('run_state', { event_type: 'WORKFLOW_END', details: { status: 'completed' } }))
    await flush()
    expect(run.status.value).toBe('completed')
    expect(run.lastError.value).toBe('')
  })
})

/*
 * D-01-5. The pointer is written by whoever is signed in and read back only by
 * them: nobody else on the same browser profile sees it, even when the first
 * person closed the tab without signing out, which is the common case. And a
 * pointer the server refuses to restore leaves nothing of the old run on
 * screen - the run id was set before the fetch and survived its failure, so a
 * refused restore still printed it and relabelled Launch as Relaunch.
 */
describe('the run pointer belongs to the signed-in user (D-01-5)', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App

  const asAlice = { userId: () => 'alice' }
  const asBob = { userId: () => 'bob' }

  beforeEach(() => {
    localStorage.clear()
    api = new FakeStudioApi()
  })

  afterEach(() => {
    app?.unmount()
  })

  it("is written under the user's own key and never under the anonymous one", async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api, asAlice))
    await run.initialize()
    await run.launch()

    const scoped = localStorage.getItem(`u:alice:${ACTIVE_RUN_KEY}`)
    expect(scoped).toBeTruthy()
    expect((JSON.parse(scoped as string) as { runId: string }).runId).toBe(RUN_ID)
    expect(localStorage.getItem(`u:alice:${SESSION_KEY}`)).toBeTruthy()
    expect(localStorage.getItem(ACTIVE_RUN_KEY)).toBeNull()
    expect(localStorage.getItem(SESSION_KEY)).toBeNull()
  })

  it('is not restored for a different user on the same browser, even without a sign-out', async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api, asAlice))
    await run.initialize()
    await run.launch()
    app.unmount()
    // Alice closed the tab. Her pointer is still there.
    expect(localStorage.getItem(`u:alice:${ACTIVE_RUN_KEY}`)).toBeTruthy()

    const bobApi = new FakeStudioApi()
    ;[run, app] = withSetup(() => useValidatorRun(bobApi, asBob))
    await run.initialize()

    expect(run.runId.value).toBe('')
    expect(run.status.value).toBe('idle')
    expect(run.lastError.value).toBe('')
    expect(run.primaryLabel.value).toBe('Launch')
    expect(bobApi.subscribeCalls).toEqual([])
    // Nothing of Alice's was touched on the way through.
    expect(localStorage.getItem(`u:alice:${ACTIVE_RUN_KEY}`)).toBeTruthy()
    expect(localStorage.getItem(`u:bob:${ACTIVE_RUN_KEY}`)).toBeNull()
  })

  it('gives each user their own session id rather than sharing one across people', async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api, asAlice))
    await run.initialize()
    app.unmount()
    ;[run, app] = withSetup(() => useValidatorRun(api, asBob))
    await run.initialize()

    const alice = localStorage.getItem(`u:alice:${SESSION_KEY}`)
    const bob = localStorage.getItem(`u:bob:${SESSION_KEY}`)
    expect(alice).toBeTruthy()
    expect(bob).toBeTruthy()
    expect(alice).not.toBe(bob)
  })

  it('a restore the server refused leaves no run id on screen and no Relaunch', async () => {
    seedStoredRun()
    api.getRunError = new Error('run not found')

    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()

    expect(run.status.value).toBe('error')
    expect(run.lastError.value).toBe('run not found')
    expect(run.runId.value).toBe('')
    expect(run.primaryLabel.value).toBe('Launch')
    expect(storedRun()).toBeNull()
    expect(api.subscribeCalls).toEqual([])
  })
})
