import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { App } from 'vue'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import type { FrameData, FrameKind } from '../src/types/studio'
import { FakeStudioApi, RUN_ID, flush, frameFactory, withSetup } from './helpers'

type ValidatorRun = ReturnType<typeof useValidatorRun>

const GATE_DETAILS = {
  gate_id: 'scope-confirmation',
  title: 'Confirm scope',
  summary: 'Check the parsed scope.',
  editable: true,
  expires_at: '2026-01-01T00:10:00.000Z',
  fields: { market: 'Design tooling' },
  options: [
    { id: 'scope_revise', label: 'Revise', emphasis: 'danger' },
    { id: 'scope_ok', label: 'Approve scope', emphasis: 'primary' },
  ],
}

describe('frame handling', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App
  let build: ReturnType<typeof frameFactory>

  beforeEach(async () => {
    localStorage.clear()
    api = new FakeStudioApi()
    build = frameFactory()
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
  })

  afterEach(() => {
    app.unmount()
  })

  it('opens a gate and moves the run to waiting', async () => {
    api.emit(build('gate_open', { event_type: 'HUMAN_INTERACTION', node_id: 'confirm_scope', level: 'WARNING', details: GATE_DETAILS }))
    await flush()

    expect(run.status.value).toBe('waiting')
    expect(run.pendingGate.value).toMatchObject({
      gateId: 'scope-confirmation',
      nodeId: 'confirm_scope',
      title: 'Confirm scope',
      editable: true,
      expired: false,
    })
    expect(run.pendingGate.value?.options.map((option) => option.id)).toEqual(['scope_revise', 'scope_ok'])
  })

  /**
   * PRD Scenario C. `gate_expired` annotates the open gate and nothing else:
   * the gate stays open, the run stays WAITING and the reply path stays live.
   */
  it('marks an open gate expired without closing it or failing the run', async () => {
    api.emit(build('gate_open', { event_type: 'HUMAN_INTERACTION', node_id: 'confirm_scope', details: GATE_DETAILS }))
    api.emit(build('gate_expired', {
      event_type: 'HUMAN_INTERACTION',
      node_id: 'confirm_scope',
      level: 'WARNING',
      details: { gate_id: 'scope-confirmation', overdue_seconds: 95 },
    }))
    await flush()

    expect(run.pendingGate.value).not.toBeNull()
    expect(run.pendingGate.value?.expired).toBe(true)
    expect(run.pendingGate.value?.alerting).toBeFalsy()
    expect(run.pendingGate.value?.overdueSeconds).toBe(95)
    expect(run.status.value).toBe('waiting')
  })

  it('raises the alert flag on gate_alert and keeps the gate answerable', async () => {
    api.emit(build('gate_open', { event_type: 'HUMAN_INTERACTION', node_id: 'confirm_scope', details: GATE_DETAILS }))
    api.emit(build('gate_alert', {
      event_type: 'HUMAN_INTERACTION',
      node_id: 'confirm_scope',
      level: 'WARNING',
      details: { gate_id: 'scope-confirmation', overdue_seconds: 600 },
    }))
    await flush()

    expect(run.pendingGate.value?.alerting).toBe(true)
    expect(run.pendingGate.value?.expired).toBe(true)
    expect(run.status.value).toBe('waiting')

    await run.submitGate('scope_ok', { market: 'Design tooling' })
    expect(api.gateReplies).toEqual([
      { runId: RUN_ID, gateId: 'scope-confirmation', reply: { outcome: 'scope_ok', fields: { market: 'Design tooling' } } },
    ])
  })

  it('ignores an expiry notice aimed at a different gate', async () => {
    api.emit(build('gate_open', { event_type: 'HUMAN_INTERACTION', node_id: 'confirm_scope', details: GATE_DETAILS }))
    api.emit(build('gate_expired', {
      event_type: 'HUMAN_INTERACTION',
      details: { gate_id: 'verdict-review', overdue_seconds: 12 },
    }))
    await flush()

    expect(run.pendingGate.value?.expired).toBe(false)
  })

  it('closes the gate and resumes the run on gate_closed', async () => {
    api.emit(build('gate_open', { event_type: 'HUMAN_INTERACTION', node_id: 'confirm_scope', details: GATE_DETAILS }))
    await flush()
    api.emit(build('gate_closed', {
      event_type: 'HUMAN_INTERACTION',
      node_id: 'confirm_scope',
      details: { gate_id: 'scope-confirmation', outcome: 'scope_ok' },
    }))
    await flush()

    expect(run.pendingGate.value).toBeNull()
    expect(run.gateSubmitting.value).toBe(false)
    expect(run.status.value).toBe('running')
    expect(run.graphNodes.value.find((node) => node.id === 'confirm_scope')?.data?.state).toBe('completed')
  })

  it('walks a node through running, waiting, completed and error', async () => {
    const stateOf = (id: string) => run.graphNodes.value.find((node) => node.id === id)?.data?.state

    api.emit(build('node_state', { event_type: 'NODE_START', node_id: 'scope_idea' }))
    await flush()
    expect(stateOf('scope_idea')).toBe('running')

    // A real `gate_open`, not the fabricated `NODE_WAITING` this used to send.
    // The comment that stood here justified the fake event on the grounds that
    // "nothing in the live stream ever puts a gate node into waiting" - true
    // when it was written, and untrue since `applyGate` started setting the
    // node. The `applyNodeState` branch it existed to cover was unreachable
    // against any real backend (no `UIEventType` member contains WAITING) and
    // has now been deleted, so this asserts the path the server actually
    // drives.
    api.emit(build('gate_open', { event_type: 'HUMAN_INTERACTION', node_id: 'confirm_scope', details: GATE_DETAILS }))
    await flush()
    expect(stateOf('confirm_scope')).toBe('waiting')
    expect(run.status.value).toBe('waiting')

    api.emit(build('node_state', { event_type: 'NODE_END', node_id: 'scope_idea' }))
    await flush()
    expect(stateOf('scope_idea')).toBe('completed')

    api.emit(build('node_state', { event_type: 'NODE_END', level: 'ERROR', node_id: 'research_market' }))
    await flush()
    expect(stateOf('research_market')).toBe('error')
  })

  it('does not throw on an unknown frame kind and still logs it', async () => {
    const before = run.chatEntries.value.length
    api.emit(build('telemetry_beacon' as unknown as FrameKind, { event_type: 'SOMETHING_NEW', message: 'from a newer server' }))
    await flush()

    expect(run.lastError.value).toBe('')
    expect(run.chatEntries.value).toHaveLength(before + 1)
    expect(run.chatEntries.value.at(-1)?.message).toBe('from a newer server')
  })

  it('records a run error frame and surfaces the message', async () => {
    api.emit(build('error', { event_type: 'WORKFLOW_END', level: 'ERROR', message: 'Firecrawl rate limit exhausted.' }))
    await flush()

    expect(run.status.value).toBe('error')
    expect(run.lastError.value).toBe('Firecrawl rate limit exhausted.')
  })

  it('deduplicates a frame that arrives twice', async () => {
    const frame = build('node_state', { event_type: 'NODE_START', node_id: 'scope_idea' })
    api.emit(frame)
    api.emit(frame)
    await flush()

    expect(run.chatEntries.value.filter((entry) => entry.seq === frame.seq)).toHaveLength(1)
    expect(run.lastSequence.value).toBe(frame.seq)
  })

  it('replays a sequence gap from the frame API instead of dropping it', async () => {
    const missed: FrameData[] = [
      build('node_state', { event_type: 'NODE_START', node_id: 'scope_idea' }),
      build('node_state', { event_type: 'NODE_END', node_id: 'scope_idea' }),
    ]
    api.storedFrames = missed
    const next = build('node_state', { event_type: 'NODE_START', node_id: 'confirm_scope' })

    api.emit(next)
    await flush()

    expect(run.lastSequence.value).toBe(next.seq)
    expect(run.droppedFrames.value).toBe(0)
    expect(run.graphNodes.value.find((node) => node.id === 'scope_idea')?.data?.state).toBe('completed')
  })

  it('counts frames the server could not replay as dropped', async () => {
    api.storedFrames = []
    const next = build('run_state', { event_type: 'WORKFLOW_START', details: { status: 'running' } })
    next.seq = 5

    api.emit(next)
    await flush()

    expect(run.droppedFrames.value).toBe(4)
    expect(run.lastSequence.value).toBe(5)
  })

  it('ignores frames belonging to another run', async () => {
    const foreign = build('node_state', { event_type: 'NODE_START', node_id: 'scope_idea', run_id: 'someone-elses-run' })
    api.emit(foreign)
    await flush()

    expect(run.graphNodes.value.find((node) => node.id === 'scope_idea')?.data?.state).toBe('idle')
  })

  it('accumulates run and per-node token usage', async () => {
    api.emit(build('token', {
      event_type: 'MODEL_CALL',
      node_id: 'scope_idea',
      details: { usage: { prompt_tokens: 100, completion_tokens: 40, total_tokens: 140, cost_usd: 0.002 } },
    }))
    await flush()

    expect(run.usage.totalTokens).toBe(140)
    expect(run.usage.costUsd).toBeCloseTo(0.002, 6)
    expect(run.nodeUsage.scope_idea.totalTokens).toBe(140)
  })
})
