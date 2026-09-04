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
   * The defect: nothing ever removed the pointer, so a finished run was
   * restored on every later page load and the operator opened the console to
   * a stale result.
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
  ])('clears the saved run when the run ends as %s', async (status, eventType) => {
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
    expect(storedRun()).not.toBeNull()

    const build = frameFactory()
    api.emit(build('run_state', { event_type: eventType, details: { status } }))
    await flush()

    expect(storedRun()).toBeNull()
    expect(['completed', 'cancelled', 'error']).toContain(run.status.value)
  })

  it('clears the saved run when an error frame ends it', async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()

    const build = frameFactory()
    api.emit(build('error', { event_type: 'WORKFLOW_END', level: 'ERROR', message: 'boom' }))
    await flush()

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

  it('drops a saved run that already finished instead of re-opening it', async () => {
    seedStoredRun()
    api.snapshot = emptySnapshot(RUN_ID, 'completed')

    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await flush()

    expect(storedRun()).toBeNull()
    expect(run.runId.value).toBe('')
    expect(run.status.value).toBe('idle')
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
