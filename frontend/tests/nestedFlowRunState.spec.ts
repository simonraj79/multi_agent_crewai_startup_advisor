import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { App } from 'vue'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import type { FrameData } from '../src/types/studio'
import { FakeStudioApi, RUN_ID, edgeFrame, flush, frameFactory, withSetup } from './helpers'
import backendNestedFlowFrames from './fixtures/backendNestedFlowFrames.json'

type ValidatorRun = ReturnType<typeof useValidatorRun>

/** The key `clearStoredRun` removes; refresh recovery is exactly this pointer. */
const ACTIVE_RUN_STORAGE_KEY = 'validator-active-run'

/**
 * These frames are not written here. `tests/events/test_nested_flow_frames.py`
 * builds them by pushing real `FlowStartedEvent` / `FlowFinishedEvent` /
 * `FlowFailedEvent` objects for two different flows through the real
 * `FieldBoundedSerializer`, and fails if the serializer's output stops matching
 * the committed fixture.
 *
 * The sequence is the one a live run really produced: the run's own flow opens,
 * CrewAI runs a flow of its own inside it - `AgentExecutor` is a Flow, and the
 * Scoper finishing is what starts and ends one - and then the run's flow
 * closes. The middle three used to arrive as `run_state` / `WORKFLOW_START` and
 * `run_state` / `WORKFLOW_END` on the `workflow` node, and this composable
 * believed them: it flipped the console to Completed ten frames into a six
 * agent run, stopped the edge animations, and called `clearStoredRun()`. The
 * status came back on the next `gate_open`. The pointer did not, and a refresh
 * after that could no longer find a run that was still in flight.
 */
const FRAMES = backendNestedFlowFrames as unknown as FrameData[]
const [ROOT_STARTED, INNER_STARTED, INNER_FINISHED, INNER_FAILED, ROOT_FINISHED] = FRAMES
const INNER_FRAMES = [INNER_STARTED, INNER_FINISHED, INNER_FAILED]

describe('a flow nested inside the run', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App
  let removeItem: ReturnType<typeof vi.spyOn>

  beforeEach(async () => {
    localStorage.clear()
    api = new FakeStudioApi()
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
    expect(localStorage.getItem(ACTIVE_RUN_STORAGE_KEY)).toContain(RUN_ID)
    // Installed after the launch so the launch's own writes are not counted.
    removeItem = vi.spyOn(Storage.prototype, 'removeItem')
  })

  afterEach(() => {
    removeItem.mockRestore()
    app.unmount()
  })

  it('is addressed to the run under test, gap-free', () => {
    // The composable drops frames belonging to another run and refills gaps
    // from the API, so a mis-built fixture would prove nothing while passing.
    expect(FRAMES.map((frame) => frame.run_id)).toEqual(Array(5).fill(RUN_ID))
    expect(FRAMES.map((frame) => frame.seq)).toEqual([1, 2, 3, 4, 5])
  })

  it('does not arrive as anything the client can read as the run ending', () => {
    for (const frame of INNER_FRAMES) {
      expect(frame.kind, frame.message).not.toBe('run_state')
      expect(frame.kind, frame.message).not.toBe('error')
      expect(frame.details.status, frame.message).toBeUndefined()
      expect(frame.event_type, frame.message).not.toContain('WORKFLOW')
      expect(frame.details.nested, frame.message).toBe(true)
    }
  })

  it('leaves the run running, and leaves the stored run pointer alone', async () => {
    api.emit(ROOT_STARTED)
    await flush()
    expect(run.status.value).toBe('running')

    for (const frame of INNER_FRAMES) api.emit(frame)
    await flush(32)

    expect(run.status.value).toBe('running')
    // The damage that does not undo itself. `clearStoredRun` is the only caller
    // that removes this key, so both halves say the same thing two ways: it was
    // not called, and the pointer a refresh needs is still there.
    expect(removeItem).not.toHaveBeenCalledWith(ACTIVE_RUN_STORAGE_KEY)
    expect(localStorage.getItem(ACTIVE_RUN_STORAGE_KEY)).toContain(RUN_ID)
  })

  it('still lets the run itself finish, and clear its pointer', async () => {
    // The control for the case above: this suite can tell the two apart.
    api.emit(ROOT_STARTED)
    for (const frame of INNER_FRAMES) api.emit(frame)
    api.emit(ROOT_FINISHED)
    // Every frame costs the composable's promise-chained queue a few ticks.
    await flush(32)

    expect(run.status.value).toBe('completed')
    expect(removeItem).toHaveBeenCalledWith(ACTIVE_RUN_STORAGE_KEY)
    expect(localStorage.getItem(ACTIVE_RUN_STORAGE_KEY)).toBeNull()
  })

  it('does not stop the traversals still marching', async () => {
    const build = frameFactory()
    // Seq 1-3 here, so the fixture's own frames are replayed after them under
    // ids the composable has not seen; only the kinds matter to this case.
    api.emit(build('run_state', { event_type: 'WORKFLOW_START', details: { status: 'running' } }))
    api.emit(edgeFrame(build, 'route_scope', 'research_market'))
    await flush()
    expect(run.graphEdges.value.filter((edge) => edge.data?.active)).toHaveLength(1)

    for (const [index, frame] of INNER_FRAMES.entries()) api.emit({ ...frame, seq: 3 + index })
    await flush()

    expect(run.status.value).toBe('running')
    expect(run.graphEdges.value.filter((edge) => edge.data?.active)).toHaveLength(1)
  })

  it('keeps the inner flow in the log, attributed to the node it ran inside', async () => {
    api.emit(ROOT_STARTED)
    for (const frame of INNER_FRAMES) api.emit(frame)
    await flush(32)

    // Dropping the events would have fixed the status bug and lost the trace.
    const logged = run.chatEntries.value.filter((entry) => entry.nodeId === 'scope_idea')
    expect(logged.map((entry) => entry.message)).toEqual([
      'AgentExecutor started',
      'AgentExecutor completed',
      'AgentExecutor failed',
    ])
    // An agent frame is not a node_state frame: the node it names must not be
    // driven to `completed` by a flow that merely ran inside it.
    const node = run.graphNodes.value.find((candidate) => candidate.id === 'scope_idea')
    expect(node?.data?.state).toBe('idle')
    expect(run.quarantinedFrames.value).toBe(0)
  })

  /**
   * The second lock, on the client side of the same door. The server no longer
   * sends a nested lifecycle event as `run_state` at all, so this frame is one
   * no backend emits today - it is what the deployed one emitted yesterday,
   * plus the marker. A future server that decides a nested flow *should* stay a
   * `run_state` frame must not be able to end a run by doing so.
   */
  it('ignores a run_state frame that says it is nested', async () => {
    const build = frameFactory()
    api.emit(build('run_state', { event_type: 'WORKFLOW_START', details: { status: 'running' } }))
    await flush()
    expect(run.status.value).toBe('running')

    api.emit(
      build('run_state', {
        event_type: 'WORKFLOW_END',
        node_id: 'workflow',
        message: 'AgentExecutor completed',
        details: { status: 'completed', result: 'completed', nested: true },
      }),
    )
    // And the same frame with the status key missing, which is the shape the
    // `event_type` fallback in `applyRunState` exists to catch.
    api.emit(
      build('run_state', {
        event_type: 'WORKFLOW_END',
        node_id: 'workflow',
        message: 'AgentExecutor completed',
        details: { result: 'completed', nested: true },
      }),
    )
    await flush()

    expect(run.status.value).toBe('running')
    expect(removeItem).not.toHaveBeenCalledWith(ACTIVE_RUN_STORAGE_KEY)
    expect(localStorage.getItem(ACTIVE_RUN_STORAGE_KEY)).toContain(RUN_ID)
  })
})
