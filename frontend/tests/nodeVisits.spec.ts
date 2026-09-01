import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { App } from 'vue'
import { useValidatorRun } from '../src/composables/useValidatorRun'
import { FakeStudioApi, RUN_ID, flush, frameFactory, withSetup } from './helpers'

type ValidatorRun = ReturnType<typeof useValidatorRun>

/**
 * Lap counting, at the frame layer.
 *
 * `nodeStates` cannot answer "how many times has this run?" - a node that ran
 * four times and one that ran once are both `completed` afterwards, and the map
 * holds no history. So the count is taken where the frames arrive, and the two
 * ways it could lie are both pinned here: over-counting a replayed stream, and
 * under-counting a genuine second pass.
 */
describe('node visits', () => {
  let api: FakeStudioApi
  let run: ValidatorRun
  let app: App
  let build: ReturnType<typeof frameFactory>

  const start = (nodeId: string) =>
    build('node_state', { event_type: 'NODE_START', node_id: nodeId })
  const end = (nodeId: string) =>
    build('node_state', { event_type: 'NODE_END', node_id: nodeId })

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

  it('starts every node in the topology at zero', () => {
    expect(run.nodeVisits.scope_idea).toBe(0)
    expect(run.nodeVisits.revise_scope).toBe(0)
  })

  it('counts one visit for a node that runs once', async () => {
    api.emit(start('scope_idea'))
    await flush()
    expect(run.nodeVisits.scope_idea).toBe(1)
  })

  it('does not count finishing as a further visit', async () => {
    api.emit(start('scope_idea'))
    api.emit(end('scope_idea'))
    await flush()
    expect(run.nodeVisits.scope_idea).toBe(1)
    expect(run.nodeStates.scope_idea).toBe('completed')
  })

  it('does not inflate on a repeated START while already running', async () => {
    // CrewAI re-emits NODE_START on a retry and the stream replays on
    // reconnect. Counting every assignment to `running` would bump the lap on a
    // page refresh - the one moment an operator is most likely to be reading it.
    api.emit(start('scope_idea'))
    api.emit(start('scope_idea'))
    api.emit(start('scope_idea'))
    await flush()
    expect(run.nodeVisits.scope_idea).toBe(1)
  })

  it('counts a genuine second pass after the node has settled', async () => {
    api.emit(start('research_market'))
    api.emit(end('research_market'))
    api.emit(start('research_market'))
    await flush()
    expect(run.nodeVisits.research_market).toBe(2)
  })

  it('counts each revise node separately', async () => {
    api.emit(start('revise_scope'))
    api.emit(end('revise_scope'))
    api.emit(start('revise_scope'))
    api.emit(end('revise_scope'))
    api.emit(start('revise_verdict'))
    await flush(32)
    expect(run.nodeVisits.revise_scope).toBe(2)
    expect(run.nodeVisits.revise_verdict).toBe(1)
    expect(run.nodeVisits.scope_idea).toBe(0)
  })

  it('counts a gate node each time it opens', async () => {
    // A gate never becomes `running` - `applyGate` sets `waiting` - so keying
    // the count on `running` alone reported no passes for the one node an
    // operator revisits most.
    const gate = (seq: number) =>
      build('gate_open', {
        event_type: 'HUMAN_INTERACTION',
        node_id: 'confirm_scope',
        details: { gate_id: `g${seq}`, title: 'Confirm scope', options: [] },
      })
    api.emit(gate(1))
    api.emit(build('gate_closed', { event_type: 'HUMAN_INTERACTION', node_id: 'confirm_scope', details: { gate_id: 'g1' } }))
    api.emit(gate(2))
    await flush(24)
    expect(run.nodeVisits.confirm_scope).toBe(2)
  })

  it('does not count a gate that is merely annotated as expired', async () => {
    api.emit(build('gate_open', {
      event_type: 'HUMAN_INTERACTION',
      node_id: 'confirm_scope',
      details: { gate_id: 'g1', title: 'Confirm scope', options: [] },
    }))
    api.emit(build('gate_expired', {
      event_type: 'HUMAN_INTERACTION',
      node_id: 'confirm_scope',
      details: { gate_id: 'g1', overdue_seconds: 90 },
    }))
    await flush(24)
    expect(run.nodeVisits.confirm_scope).toBe(1)
  })

  it('does not count a node that only ever errors without starting', async () => {
    api.emit(build('node_state', { event_type: 'NODE_FAIL', node_id: 'research_sentiment', level: 'ERROR' }))
    await flush()
    expect(run.nodeStates.research_sentiment).toBe('error')
    expect(run.nodeVisits.research_sentiment).toBe(0)
  })

  it('clears every count on relaunch', async () => {
    api.emit(start('scope_idea'))
    api.emit(end('scope_idea'))
    api.emit(start('revise_scope'))
    await flush()
    expect(run.nodeVisits.revise_scope).toBe(1)

    // A relaunch is only reachable from a settled run - `canLaunch` refuses
    // while one is active - so the run has to finish before the reset is real.
    api.emit(build('run_state', { event_type: 'FLOW_FINISHED', details: { status: 'completed' } }))
    await flush()
    await run.launch()
    await flush()

    expect(run.nodeVisits.scope_idea).toBe(0)
    expect(run.nodeVisits.revise_scope).toBe(0)
  })

  it('reaches the graph node data, so the card can show it', async () => {
    api.emit(start('scope_idea'))
    api.emit(end('scope_idea'))
    api.emit(start('revise_scope'))
    await flush()

    const scope = run.graphNodes.value.find((n) => n.id === 'scope_idea')
    const revise = run.graphNodes.value.find((n) => n.id === 'revise_scope')
    expect(scope?.data?.visits).toBe(1)
    expect(revise?.data?.visits).toBe(1)
  })

  it('leaves the run id alone', () => {
    expect(run.runId.value).toBe(RUN_ID)
  })
})
