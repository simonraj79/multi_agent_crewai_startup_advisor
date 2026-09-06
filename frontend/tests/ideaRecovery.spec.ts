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
  /** What an authored graph's own input field carries (item 56). */
  const SUBJECT = 'What the vector-database vendors shipped in September'
  const DEFAULT_IDEA = 'An AI tool that turns Figma files into production React'

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

  /**
   * THE SAME RELOAD FOR A GRAPH SOMEBODY DREW (item 56, ROUND-2 R2).
   *
   * `recoverIdea` read `inputs.idea` by literal, so a run launched under
   * `inputs.subject` recovered nothing and the box kept the Figma default -
   * with Relaunch pointed at it. The key comes off the run's own stored
   * context now, which is the value the POST used.
   */
  it('restores the input of a graph somebody drew, read by its own key', async () => {
    localStorage.setItem(
      ACTIVE_RUN_KEY,
      JSON.stringify({
        version: 1,
        runId: RUN_ID,
        sessionId: 'session-abc',
        workflowId: 'ug_a96d869d',
        inputField: 'subject',
      }),
    )
    const build = frameFactory()
    api.storedFrames = [
      build('run_state', {
        event_type: 'WORKFLOW_START',
        node_id: 'workflow',
        details: { status: 'running', inputs: { subject: SUBJECT } },
      }),
    ]

    const [run, mounted] = withSetup(() => useValidatorRun(api))
    app = mounted
    await run.initialize()
    await flush(24)

    expect(run.idea.value).toBe(SUBJECT)
    expect(run.inputField.value).toBe('subject')
  })

  /**
   * And it does NOT take a key the graph does not read. A builder document may
   * carry its own `idea` state key; putting that in a box labelled `SUBJECT`
   * would be a worse lie than recovering nothing.
   */
  it('ignores an `idea` key on a graph whose input is `subject`', async () => {
    localStorage.setItem(
      ACTIVE_RUN_KEY,
      JSON.stringify({
        version: 1,
        runId: RUN_ID,
        sessionId: 'session-abc',
        workflowId: 'ug_a96d869d',
        inputField: 'subject',
      }),
    )
    const build = frameFactory()
    api.storedFrames = [
      build('run_state', {
        event_type: 'WORKFLOW_START',
        node_id: 'workflow',
        details: { status: 'running', inputs: { idea: 'not this one' } },
      }),
    ]

    const [run, mounted] = withSetup(() => useValidatorRun(api))
    app = mounted
    await run.initialize()
    await flush(24)

    expect(run.idea.value).toBe(DEFAULT_IDEA)
  })
})
