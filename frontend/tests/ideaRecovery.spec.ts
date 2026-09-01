import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { App } from 'vue'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import { FakeStudioApi, RUN_ID, flush, frameFactory, withSetup } from './helpers'

type ValidatorRun = ReturnType<typeof useValidatorRun>

const ACTIVE_RUN_KEY = 'validator-active-run'
const SESSION_KEY = 'validator-session-id'

/**
 * The idea comes back after a reload.
 *
 * Second half of remaining-work item 11. `idea` was a plain ref seeded with a
 * hardcoded default and assigned nowhere, so a refresh mid-run restored the
 * graph, the gates and the report correctly above a textarea that had silently
 * reverted to "An AI tool that turns Figma files into production React". The
 * next Relaunch would then have spent money on something the operator never
 * typed - which is why this is worth more than its size suggests.
 *
 * The recovery needs no new persistence and no new API field: the run's own
 * opening `RUN_STATE` frame records what it was launched with, and
 * `restoreRun` replays every frame.
 */
describe('idea recovery', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App
  let build: ReturnType<typeof frameFactory>

  const LAUNCHED = 'A triage inbox for single-vet veterinary practices'
  const DEFAULT_IDEA = 'An AI tool that turns Figma files into production React'

  const startFrame = (idea: string) =>
    build('run_state', {
      event_type: 'WORKFLOW_START',
      node_id: 'workflow',
      details: { status: 'running', inputs: { idea } },
    })

  beforeEach(async () => {
    localStorage.clear()
    api = new FakeStudioApi()
    build = frameFactory()
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
  })

  afterEach(() => {
    app?.unmount()
  })

  it('takes the idea off the run\'s opening frame', async () => {
    api.emit(startFrame(LAUNCHED))
    await flush()
    expect(run.idea.value).toBe(LAUNCHED)
  })

  it('replaces the hardcoded default, which is the actual bug', async () => {
    expect(run.idea.value).toBe(DEFAULT_IDEA)
    api.emit(startFrame(LAUNCHED))
    await flush()
    expect(run.idea.value).not.toBe(DEFAULT_IDEA)
  })

  it('ignores a frame carrying no inputs at all', async () => {
    // The TERMINAL frame carries `result`, not `inputs`. It must not blank the
    // box at the moment the operator is deciding whether to relaunch.
    api.emit(startFrame(LAUNCHED))
    await flush()
    api.emit(
      build('run_state', {
        event_type: 'WORKFLOW_END',
        node_id: 'workflow',
        details: { status: 'completed', result: { markdown_body: '# done' } },
      }),
    )
    await flush()
    expect(run.idea.value).toBe(LAUNCHED)
  })

  it('ignores an empty or whitespace idea', async () => {
    api.emit(startFrame(LAUNCHED))
    await flush()
    api.emit(startFrame('   '))
    await flush()
    expect(run.idea.value).toBe(LAUNCHED)
  })

  it('ignores a non-string idea without throwing', async () => {
    api.emit(
      build('run_state', {
        event_type: 'WORKFLOW_START',
        node_id: 'workflow',
        details: { status: 'running', inputs: { idea: 42 } },
      }),
    )
    await flush()
    expect(run.idea.value).toBe(DEFAULT_IDEA)
  })

  it('ignores inputs that are not an object', async () => {
    api.emit(
      build('run_state', {
        event_type: 'WORKFLOW_START',
        node_id: 'workflow',
        details: { status: 'running', inputs: 'not an object' },
      }),
    )
    await flush()
    expect(run.idea.value).toBe(DEFAULT_IDEA)
  })

  it('does not read a NESTED flow\'s inputs', async () => {
    // `applyRunState` returns early on a nested frame, and it must keep doing
    // so: a sub-flow's inputs are not the run's idea.
    api.emit(
      build('run_state', {
        event_type: 'WORKFLOW_START',
        node_id: 'workflow',
        details: { status: 'running', nested: true, inputs: { idea: 'a nested thing' } },
      }),
    )
    await flush()
    expect(run.idea.value).toBe(DEFAULT_IDEA)
  })
})

describe('idea recovery across a reload', () => {
  let api: FakeStudioApi
  let app: App

  const LAUNCHED = 'A scheduling assistant for small veterinary clinics'

  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem(
      ACTIVE_RUN_KEY,
      JSON.stringify({
        version: 1,
        runId: RUN_ID,
        sessionId: 'session-abc',
        workflowId: 'idea-validator',
      }),
    )
    localStorage.setItem(SESSION_KEY, 'session-abc')
    api = new FakeStudioApi()
  })

  afterEach(() => {
    app?.unmount()
  })

  it('restores the launched idea, not the default, on a fresh page load', async () => {
    // The whole scenario in one test: a new composable (a reload), a stored run
    // pointer, and the idea recovered from replayed frames.
    const build = frameFactory()
    api.storedFrames = [
      build('run_state', {
        event_type: 'WORKFLOW_START',
        node_id: 'workflow',
        details: { status: 'running', inputs: { idea: LAUNCHED } },
      }),
      build('node_state', { event_type: 'NODE_START', node_id: 'scope_idea' }),
    ]

    const [run, mounted] = withSetup(() => useValidatorRun(api))
    app = mounted
    await run.initialize()
    await flush(24)

    expect(run.idea.value).toBe(LAUNCHED)
    expect(run.runId.value).toBe(RUN_ID)
  })
})
