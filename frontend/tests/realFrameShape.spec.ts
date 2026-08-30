import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { App } from 'vue'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import type { FrameData } from '../src/types/studio'
import { FakeStudioApi, RUN_ID, flush, withSetup } from './helpers'
import backendRunStateFrames from './fixtures/backendRunStateFrames.json'

type ValidatorRun = ReturnType<typeof useValidatorRun>

/**
 * The frames below are not written here. `tests/events/test_run_state_status.py`
 * builds them by pushing real `FlowStartedEvent` / `FlowFinishedEvent` /
 * `FlowFailedEvent` objects through the real `FieldBoundedSerializer`, writes
 * the result to the fixture, and fails if the serializer's output ever stops
 * matching the committed file. So this suite is driven by what the backend
 * actually emits, and the two sides cannot drift apart in silence.
 *
 * They drifted apart badly once: the serializer's `WORKFLOW_END` frame carried
 * `{result}` and no `status`, `applyRunState` read only `details.status`, and a
 * real run left the console reading "queued" forever while its graph filled in.
 * Every spec in this directory passed, because every spec hand-wrote its own
 * frames with a `status` the server never sent.
 */
const FRAMES = backendRunStateFrames as unknown as FrameData[]
const [STARTED, FINISHED, FAILED] = FRAMES

describe('the frame shape the backend really emits', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App

  beforeEach(async () => {
    localStorage.clear()
    api = new FakeStudioApi()
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
    // The launch response is the only thing that has set a status so far. This
    // is the state the console was stuck in for a whole live run.
    expect(run.status.value).toBe('queued')
  })

  afterEach(() => {
    app.unmount()
  })

  it('is addressed to the run under test', () => {
    // The composable drops any frame belonging to another run, so a fixture
    // built under a different id would prove nothing while still passing.
    expect(FRAMES.map((frame) => frame.run_id)).toEqual([RUN_ID, RUN_ID, RUN_ID])
    expect(FRAMES.map((frame) => frame.seq)).toEqual([1, 2, 3])
  })

  it('starts the run on the real WORKFLOW_START frame', async () => {
    api.emit(STARTED)
    await flush()

    expect(STARTED.kind).toBe('run_state')
    expect(STARTED.event_type).toBe('WORKFLOW_START')
    expect(run.status.value).toBe('running')
  })

  it('completes the run on the real WORKFLOW_END frame', async () => {
    api.emit(STARTED)
    api.emit(FINISHED)
    await flush()

    expect(FINISHED.kind).toBe('run_state')
    expect(FINISHED.event_type).toBe('WORKFLOW_END')
    // The fix on the backend side: the frame now says what it means.
    expect(FINISHED.details.status).toBe('completed')
    expect(run.status.value).toBe('completed')
  })

  /**
   * Defence in depth for the same failure. A server that predates the
   * serializer fix - or any future frame that forgets the key - still ends the
   * run, because `run_state` + `WORKFLOW_END` cannot mean anything but a
   * completion: a failed flow arrives as `FrameKind.ERROR` instead, which
   * `test_a_failed_flow_is_an_error_frame_not_a_run_state` pins in Python and
   * the last case below exercises here.
   */
  it('completes the run even when the frame carries no status at all', async () => {
    const statusless: FrameData = { ...FINISHED, details: { result: FINISHED.details.result } }
    expect(statusless.details.status).toBeUndefined()

    api.emit(STARTED)
    api.emit(statusless)
    await flush()

    expect(run.status.value).toBe('completed')
  })

  it('still prefers an explicit status over the event type', async () => {
    api.emit(STARTED)
    api.emit({ ...FINISHED, details: { ...FINISHED.details, status: 'cancelled' } })
    await flush()

    expect(run.status.value).toBe('cancelled')
  })

  it('fails the run on the real error frame, which is not a run_state', async () => {
    expect(FAILED.kind).toBe('error')
    expect(FAILED.event_type).toBe('WORKFLOW_END')
    expect(FAILED.details.status).toBeUndefined()

    api.emit(STARTED)
    // Repositioned to seq 2 so the completion frame can be left out without
    // opening a sequence gap; the body is the serializer's own output.
    api.emit({ ...FAILED, seq: 2 })
    await flush()

    expect(run.status.value).toBe('error')
    expect(run.lastError.value).toBe(FAILED.message)
  })
})
