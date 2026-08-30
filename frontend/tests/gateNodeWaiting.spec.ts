import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import { FakeStudioApi, flush, frameFactory, withSetup } from './helpers'

/**
 * The paused node must say it is paused.
 *
 * `applyNodeState` looks for a `WAITING` event_type, but no member of
 * `UIEventType` (`src/brief_crew/events/models.py`) contains that substring -
 * a gate arrives as `FrameKind.GATE_OPEN` / `UIEventType.HUMAN_INTERACTION`.
 * So that branch was unreachable and the gate node sat at `idle` for the whole
 * pause, drawn identically to a node that has never run. On a console whose
 * entire premise is a live graph, the two moments it most needs to point at
 * something were the two moments it pointed at nothing.
 *
 * `gate_closed` always set the same node to `completed`; this is the missing
 * open half. An end-to-end guard lives in `frontend/e2e/studio.spec.ts`, but
 * that one needs a browser and a backend - this is the cheap version that runs
 * on every `npm test`.
 */
describe('a gate node reports Waiting while the operator is being asked', () => {
  let api: FakeStudioApi
  let run: ReturnType<typeof useValidatorRun>
  let app: { unmount(): void }

  beforeEach(() => {
    api = new FakeStudioApi()
  })
  afterEach(() => {
    app?.unmount()
  })

  /** Node state as the canvas actually renders it, via the public surface. */
  const stateOf = (id: string) =>
    run.graphNodes.value.find((node) => node.id === id)?.data.state

  const openGate = (build: ReturnType<typeof frameFactory>, nodeId: string, gateId: string) =>
    build('gate_open', {
      event_type: 'HUMAN_INTERACTION',
      node_id: nodeId,
      details: {
        gate_id: gateId,
        node_id: nodeId,
        title: 'Confirm scope',
        summary: 'Check the market and the primary user.',
        editable: true,
        options: [{ id: 'approve', label: 'Approve' }],
        fields: { startup_idea: 'A scheduling assistant for clinics' },
        derived: [],
      },
    })

  it('marks the gate node waiting, not idle, when the gate opens', async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
    const build = frameFactory()

    expect(stateOf('confirm_scope')).toBe('idle')

    api.emit(openGate(build, 'confirm_scope', 'gate-1'))
    await flush()

    expect(stateOf('confirm_scope')).toBe('waiting')
    expect(run.status.value).toBe('waiting')
  })

  it('releases the node to completed when the gate is answered', async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
    const build = frameFactory()

    api.emit(openGate(build, 'confirm_scope', 'gate-1'))
    await flush()
    expect(stateOf('confirm_scope')).toBe('waiting')

    api.emit(
      build('gate_closed', {
        event_type: 'HUMAN_INTERACTION',
        node_id: 'confirm_scope',
        details: { gate_id: 'gate-1', outcome: 'approve', fields: {}, late: false },
      }),
    )
    await flush()

    // Not left stuck on `waiting` once the human has answered.
    expect(stateOf('confirm_scope')).not.toBe('waiting')
    expect(run.status.value).toBe('running')
  })

  it('does not mark any other node waiting', async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
    const build = frameFactory()

    api.emit(openGate(build, 'confirm_scope', 'gate-1'))
    await flush()

    const waiting = run.graphNodes.value
      .filter((node) => node.data.state === 'waiting')
      .map((node) => node.id)
    expect(waiting).toEqual(['confirm_scope'])
  })

  it('marks the verdict gate node too, not just the scope gate', async () => {
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
    const build = frameFactory()

    api.emit(openGate(build, 'review_verdict', 'gate-2'))
    await flush()

    expect(stateOf('review_verdict')).toBe('waiting')
  })
})
