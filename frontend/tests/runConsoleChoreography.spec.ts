import { beforeEach, describe, expect, it } from 'vitest'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import { FakeStudioApi, flush, frameFactory, withSetup } from './helpers'

/**
 * The choreography as the run composable actually drives it.
 *
 * `runChoreography.spec.ts` drives the store directly, which is the right place
 * to assert arithmetic. This file asserts the WIRING: that a frame arriving on
 * the socket reaches the store, that the trace and the dialogue rail divide the
 * frames between them the way they are supposed to, and that the two controls
 * plan 12 added to the console call the API they claim to.
 *
 * Everything here goes through `FakeStudioApi`, so no socket, no server and no
 * clock is touched.
 */

type ValidatorRun = ReturnType<typeof useValidatorRun>

// The run pointer is durable by design, so a test that leaves one behind makes
// the NEXT test's `initialize()` take the restore path instead of the fresh
// one. Every other composable spec here clears it for the same reason.
beforeEach(() => {
  localStorage.clear()
})

async function launched(api = new FakeStudioApi()) {
  const [run, app] = withSetup<ValidatorRun>(() => useValidatorRun(api))
  await run.initialize()
  await run.launch()
  await flush()
  return { run, app, api }
}

describe('frames reach the choreography', () => {
  it('turns an utterance into a dialogue entry', async () => {
    const { run, api, app } = await launched()
    const build = frameFactory()
    api.emit(
      build('llm', {
        event_type: 'MODEL_CALL',
        node_id: 'scope_idea',
        message: 'gemini said',
        details: {
          stage: 'utterance',
          call_id: 'c1',
          text: 'A scheduling assistant for clinics.',
          truncated: false,
          prompt_tokens: 100,
          completion_tokens: 20,
          model: 'google/gemini-3.5-flash-lite',
        },
      }),
    )
    await flush()
    expect(run.dialogue.value).toHaveLength(1)
    expect(run.dialogue.value[0].role).toBe('Scoper')
    app.unmount()
  })

  it('keeps an utterance OUT of the trace', async () => {
    // The rail owns model output; the trace owns the mechanics. Carrying the
    // same 4,096 characters in both is how one copy goes stale, and in the
    // trace it is noise in the surface whose job is the kicker and the chips.
    const { run, api, app } = await launched()
    const build = frameFactory()
    const before = run.chatEntries.value.length
    api.emit(
      build('llm', {
        event_type: 'MODEL_CALL',
        node_id: 'scope_idea',
        message: 'gemini said',
        details: { stage: 'utterance', call_id: 'c1', text: 'text', truncated: false },
      }),
    )
    await flush()
    expect(run.chatEntries.value).toHaveLength(before)
    app.unmount()
  })

  it('keeps a plan frame out of the trace too', async () => {
    // Seven system messages before the run starts, otherwise. The lane owns it.
    const { run, api, app } = await launched()
    const build = frameFactory()
    const before = run.chatEntries.value.length
    api.emit(
      build('run_state', {
        event_type: 'NODE_START',
        node_id: 'workflow',
        message: 'Stage 1 of 3',
        details: { stage: 'plan', index: 1, of: 3, label: 'Scope', node_ids: ['scope_idea'] },
      }),
    )
    await flush()
    expect(run.chatEntries.value).toHaveLength(before)
    expect(run.stages.value).toHaveLength(1)
    app.unmount()
  })

  it('turns a traversal into a token on the descriptor\'s own edge', async () => {
    const { run, api, app } = await launched()
    const build = frameFactory()
    api.emit(
      build('edge_taken', {
        event_type: 'EDGE_PROCESS',
        node_id: 'confirm_scope',
        message: 'scope_idea to confirm_scope',
        details: { stage: 'traversal', from: 'scope_idea', to: 'confirm_scope', port: null },
      }),
    )
    await flush()
    expect(run.handoffs.value).toHaveLength(1)
    // The edge id is the DESCRIPTOR's, so the token can find the path Vue Flow
    // rendered rather than a name only the frame knows.
    const edge = run.descriptor.value.edges.find(
      (candidate) => candidate.source === 'scope_idea' && candidate.target === 'confirm_scope',
    )
    expect(run.handoffs.value[0].edgeId).toBe(edge?.id)
    expect(run.graphEdges.value.find((e) => e.id === edge?.id)?.data?.handoff).toBeTruthy()
    app.unmount()
  })

  it('counts every applied frame, which is the reconnect strip\'s N', async () => {
    const { run, api, app } = await launched()
    const build = frameFactory()
    api.emit(build('node_state', { event_type: 'NODE_START', node_id: 'scope_idea' }))
    api.emit(build('node_state', { event_type: 'NODE_END', node_id: 'scope_idea' }))
    await flush()
    expect(run.framesApplied.value).toBeGreaterThanOrEqual(2)
    app.unmount()
  })
})

describe('the launch glow', () => {
  it('is armed by the press and dropped by the first frame', async () => {
    const api = new FakeStudioApi()
    const [run, app] = withSetup<ValidatorRun>(() => useValidatorRun(api))
    await run.initialize()
    const launching = run.launch()
    expect(run.armed.value).toBe(true)
    await launching
    await flush()
    const build = frameFactory()
    api.emit(build('node_state', { event_type: 'NODE_START', node_id: 'scope_idea' }))
    await flush()
    expect(run.armed.value).toBe(false)
    app.unmount()
  })
})

describe('re-run from here', () => {
  async function failedRun() {
    const api = new FakeStudioApi()
    const { run, app } = await launched(api)
    const build = frameFactory()
    api.emit(
      build('node_state', {
        event_type: 'NODE_END',
        level: 'ERROR',
        node_id: 'research_market',
        message: 'research_market failed',
        details: { stage: 'error' },
      }),
    )
    api.emit(
      build('run_state', {
        event_type: 'WORKFLOW_END',
        node_id: 'workflow',
        message: 'failed',
        details: { status: 'failed' },
      }),
    )
    await flush()
    return { run, api, app }
  }

  it('offers the control on the failed node of a finished run', async () => {
    const { run, app } = await failedRun()
    const node = run.graphNodes.value.find((candidate) => candidate.id === 'research_market')
    expect(node?.data?.rerunnable).toBe(true)
    expect(
      run.graphNodes.value.find((c) => c.id === 'scope_idea')?.data?.rerunnable,
    ).toBe(false)
    app.unmount()
  })

  it('posts resume_from with the source run and the node', async () => {
    const { run, api, app } = await failedRun()
    const source = run.runId.value
    await run.resumeFrom('research_market')
    await flush()
    expect(api.resumeCalls).toHaveLength(1)
    expect(api.resumeCalls[0]).toMatchObject({ sourceRunId: source, nodeId: 'research_market' })
    expect(run.runId.value).not.toBe(source)
    app.unmount()
  })

  it('carries the idea the run was launched with, not a blank', async () => {
    const { run, api, app } = await failedRun()
    await run.resumeFrom('research_market')
    await flush()
    expect(api.resumeCalls[0].inputs).toEqual({ idea: run.idea.value.trim() })
    app.unmount()
  })

  it('surfaces the server\'s refusal instead of swallowing it', async () => {
    // The four refusals are 404 for somebody else's run, 422 for one still in
    // flight, 422 for a workflow that is not a compiled graph, and a missing
    // upstream output. Each is a sentence somebody can act on.
    const { run, api, app } = await failedRun()
    api.resumeError = new Error('the replay plan has no saved output for research_market')
    const source = run.runId.value
    await run.resumeFrom('research_market')
    await flush()
    expect(run.lastError.value).toContain('no saved output')
    expect(run.runId.value).toBe(source)
    app.unmount()
  })

  it('refuses to resume while a run is still going', async () => {
    // The server answers 422 for this; asking first is the difference between
    // a control that is honest and one whose only outcome is an error.
    const { run, api, app } = await launched()
    await run.resumeFrom('research_market')
    expect(api.resumeCalls).toHaveLength(0)
    app.unmount()
  })
})
