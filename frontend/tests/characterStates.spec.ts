import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import AgentCharacter from '../src/components/AgentCharacter.vue'
import ChatRail from '../src/components/ChatRail.vue'
import DialogueRail from '../src/components/DialogueRail.vue'
import WorkflowNode from '../src/components/WorkflowNode.vue'
import { characterSeed, type PipState } from '../src/characters/pip'
import {
  characterIndex,
  readsAsRole,
  useRunChoreography,
  type DialogueEntry,
} from '../src/composables/useRunChoreography'
import type { ChatEntry } from '../src/types/studio'
import type { StudioNodeData } from '../src/composables/useValidatorRun'
import type { FrameData, NodeRunState, RunStatus, StudioFrame } from '../src/types/studio'
import { zeroUsage } from './helpers'

/**
 * WHO each node is, and WHAT it is doing - derived from run events and nothing
 * else. Definition of done T2.5, and the store half of T2.6.
 *
 * ## Why this is a replay and not a set of hand-made frames
 *
 * Both fixtures are logs somebody's code actually produced.
 * `syntheticRun.ndjson` is 97 frames served by the synthetic backend, byte for
 * byte; `serializerFrames.ndjson` is 34 frames from the real Python serializer
 * over CrewAI events, including the kinds a happy path never emits - a
 * reasoning frame, a tool that failed, a guardrail that rejected an output and
 * retried, a gate, and a node that ended in error. A state machine asserted
 * against frames written to satisfy it certifies nothing, which is the failure
 * this repository has now recorded from four directions
 * (`docs/gotchas-and-insights.md`, the section on tests that pass for the
 * wrong reason).
 *
 * ## The one thing the fixtures cannot show
 *
 * Neither log contains a gate on a node OTHER than the one that fed it: the
 * synthetic run's `confirm_scope` opens no gate at all in this capture, and the
 * serializer log's gate sits on `verify` itself. The feeder rule therefore has
 * one hand-built case at the bottom of this file, assembled from the same frame
 * shapes the fixtures use, and it says so where it sits.
 *
 * ## No clock
 *
 * Nothing here fakes a timer, because there is no timer to fake. If a state
 * ever needs one, this file cannot be written, which is the point of
 * `evidence/T2/no-timers.txt` being a grep rather than an assertion.
 */

const FIXTURES = ['syntheticRun.ndjson', 'serializerFrames.ndjson'] as const

/**
 * `process.cwd()` and NOT `import.meta.url` - jsdom's whatwg `URL` makes
 * `fileURLToPath` throw on a file URL that plainly is one. Vitest's cwd is this
 * package, which is the stable fact about the environment.
 */
function fixturePath(name: string): string {
  return resolve(process.cwd(), 'tests', 'fixtures', name)
}

/** NDJSON of either `StudioFrame` envelopes or bare frames; both are served. */
function loadFrames(name: string): FrameData[] {
  const path = fixturePath(name)
  if (!existsSync(path)) return []
  return readFileSync(path, 'utf8')
    .split('\n')
    .map((row) => row.trim())
    .filter(Boolean)
    .map((row) => {
      const parsed = JSON.parse(row) as StudioFrame | FrameData
      return 'data' in parsed && parsed.type === 'frame' ? parsed.data : (parsed as FrameData)
    })
}

interface Replay {
  run: ReturnType<typeof useRunChoreography>
  /** Node id -> its states in order, with consecutive repeats collapsed. */
  sequences: Record<string, PipState[]>
  /** Node id -> every identity it was ever given, in order. */
  identitiesSeen: Record<string, string[]>
  frames: FrameData[]
}

/**
 * Push a whole log through the store, recording what the cast did after EVERY
 * frame rather than at the end.
 *
 * After every frame, because the criterion is about a sequence: a node that
 * ended `done` having never been `working` would pass an end-state assertion
 * and would mean the canvas never moved.
 *
 * `nodeStates` is seeded with `idle` for every node the log mentions, which is
 * what `useValidatorRun` does from the descriptor before a run starts, and it
 * is the only way `idle` can be the first entry of a sequence. It is then left
 * alone: the host is not simulated, so what these assertions measure is the
 * FRAME derivation on its own.
 */
function replay(name: string, declaredRoleFor?: (nodeId: string) => string | undefined): Replay {
  const frames = loadFrames(name)
  const nodeStates = ref<Record<string, NodeRunState>>({})
  for (const frame of frames) if (frame.node_id) nodeStates.value[frame.node_id] = 'idle'
  const status = ref<RunStatus>('running')
  const run = useRunChoreography({
    nodeStates,
    status,
    labelFor: (nodeId) => `The ${nodeId} card`,
    declaredRoleFor,
  })

  const sequences: Record<string, PipState[]> = {}
  const identitiesSeen: Record<string, string[]> = {}
  const record = () => {
    for (const [nodeId, state] of Object.entries(run.castStates.value)) {
      const list = (sequences[nodeId] ??= [])
      if (list[list.length - 1] !== state) list.push(state)
    }
    for (const nodeId of Object.keys(run.identities.value)) {
      const list = (identitiesSeen[nodeId] ??= [])
      const identity = run.identities.value[nodeId]
      if (list[list.length - 1] !== identity) list.push(identity)
    }
  }

  record()
  for (const frame of frames) {
    run.ingest(frame)
    record()
  }
  return { run, sequences, identitiesSeen, frames }
}

const AGENT_NODES = [
  'scope_idea',
  'research_market',
  'research_sentiment',
  'research_feasibility',
  'synthesize',
  'write_report',
] as const

describe('the fixtures are present', () => {
  it.each(FIXTURES)('%s has frames to replay', (name) => {
    // A missing fixture must fail loudly. `existsSync` returning an empty list
    // would otherwise turn every assertion below into a vacuous pass over an
    // empty object - the exact shape of green-for-the-wrong-reason this file's
    // docblock is about.
    expect(loadFrames(name).length, `${name} is missing or empty`).toBeGreaterThan(0)
  })
})

describe('the state a node is in, over a real synthetic run', () => {
  it('walks idle to working to speaking and back, and ends done', () => {
    const { sequences } = replay('syntheticRun.ndjson')
    for (const nodeId of AGENT_NODES) {
      const seen = sequences[nodeId]
      expect(seen, `${nodeId} produced no states at all`).toBeDefined()
      expect(seen[0], `${nodeId} did not start idle`).toBe('idle')
      expect(seen[1], `${nodeId} did not start working at its NODE_START`).toBe('working')
      expect(seen, `${nodeId} never spoke`).toContain('speaking')
      expect(seen[seen.length - 1], `${nodeId} did not finish done`).toBe('done')
      // Speaking is EVENT-bounded, so it closes and reopens around the model's
      // own `after` frame rather than running from the first chunk to the end
      // of the node. Those returns to `working` are the property being pinned:
      // a state that only ever opened would make a finished node look mid-
      // sentence for the rest of the run.
      expect(seen.filter((state) => state === 'working').length).toBeGreaterThan(1)
      expect(seen, `${nodeId} failed or was blocked on a clean run`).not.toContain('blocked')
      expect(seen).not.toContain('blocked-error')
    }
  })

  it('leaves the gate, the routers and the writer with no speaking state', () => {
    // None of them makes a model call, so none of them can produce an `llm`
    // frame, so none of them can ever be `speaking`. Asserted rather than
    // assumed, because "it cannot happen" is how a state machine acquires a
    // branch nobody has ever seen run.
    const { sequences } = replay('syntheticRun.ndjson')
    for (const nodeId of ['confirm_scope', 'route_scope', 'route_verdict', 'persist']) {
      expect(sequences[nodeId], `${nodeId} spoke`).not.toContain('speaking')
      expect(sequences[nodeId]).toEqual(['idle', 'working', 'done'])
    }
  })

  it('has every node idle before the first frame, which is S1', () => {
    const { run } = replay('syntheticRun.ndjson')
    const fresh = useRunChoreography({
      nodeStates: ref<Record<string, NodeRunState>>({ scope_idea: 'idle' }),
      status: ref<RunStatus>('queued'),
    })
    expect(fresh.castState('scope_idea')).toBe('idle')
    // And the replayed run does not leave one behind after a reset.
    // A relaunch is a new run with the same topology, so the role a frame
    // named is forgotten and the ladder drops back to the label. Keeping it
    // would pin the previous run's identity onto a node its author may since
    // have renamed.
    run.reset()
    expect(run.castState('scope_idea')).toBe('idle')
    expect(run.identityFor('scope_idea')).toBe('The scope_idea card')
  })
})

describe('the state a node is in, over the real serializer log', () => {
  it('is blocked while the gate is open and blocked-error once it fails', () => {
    // This log ends `NODE_END` at ERROR level after a gate round trip, so it
    // exercises the two orderings that matter: `blocked` must not survive the
    // gate closing, and `error` must beat the `completed` that the same frame
    // also sets. `applyNodeState` applies END then ERROR, and this mirror does
    // the same - which is why the last state is `blocked-error` and not `done`.
    const { sequences, run } = replay('serializerFrames.ndjson')
    const seen = sequences.verify
    expect(seen[0]).toBe('idle')
    expect(seen).toContain('speaking')
    expect(seen).toContain('blocked')
    expect(seen[seen.length - 1]).toBe('blocked-error')
    expect(seen.indexOf('blocked')).toBeLessThan(seen.lastIndexOf('done'))
    expect(run.castState('verify')).toBe('blocked-error')
  })

  it('is not failed by a TOOL error, only by a node one', () => {
    // Frame 9 is a `tool` frame at ERROR level - a search that 503'd and was
    // retried. The agent recovered and went on to produce three utterances. A
    // derivation that failed the node there would have drawn a red character
    // over a node that finished its work, which is a lie the log itself
    // disproves four frames later.
    const { run, frames } = replay('serializerFrames.ndjson')
    run.reset()
    for (const frame of frames.slice(0, 9)) run.ingest(frame)
    expect(run.castState('verify')).not.toBe('blocked-error')
    expect(['working', 'speaking']).toContain(run.castState('verify'))
  })

  it('does not let a guardrail rejection or a reasoning frame end a sentence', () => {
    // Both arrive between an utterance and the next call. They are the agent
    // still working, so they close the sentence rather than being ignored -
    // the state must be `working`, not `speaking` and not something else.
    const { run, frames } = replay('serializerFrames.ndjson')
    run.reset()
    const upToGuardrail = frames.findIndex((frame) => frame.kind === 'guardrail')
    for (const frame of frames.slice(0, upToGuardrail + 1)) run.ingest(frame)
    expect(run.castState('verify')).toBe('working')
  })
})

describe('the identity a node is given', () => {
  it('is the FIRST agent_role a frame carried, and never changes after', () => {
    const { identitiesSeen } = replay('syntheticRun.ndjson')
    expect(identitiesSeen.scope_idea.filter((value) => value === 'Startup validation scoper'))
      .toHaveLength(1)
    // One transition at most: the label the ladder starts on, then the role.
    // Never a second role, because a character that changes mid-run is a
    // different agent as far as the eye is concerned.
    for (const nodeId of AGENT_NODES) {
      const seen = identitiesSeen[nodeId]
      expect(seen.length, `${nodeId} changed identity ${seen.length} times: ${seen.join(' -> ')}`)
        .toBeLessThanOrEqual(2)
      expect(seen[seen.length - 1]).not.toBe(`The ${nodeId} card`)
    }
    expect(identitiesSeen.research_market[identitiesSeen.research_market.length - 1])
      .toBe('Market evidence analyst')
  })

  it('ignores a later frame that names a different role for the same node', () => {
    // CrewAI re-emits an agent boundary per retry and a stream replays on
    // reconnect. A store that took the latest would repaint the cast on a page
    // refresh, which is the moment an operator is most likely to be looking.
    const { run } = replay('syntheticRun.ndjson')
    run.ingest({
      v: 1,
      seq: 999,
      run_id: 'run-1',
      ts: new Date().toISOString(),
      kind: 'agent',
      event_type: 'AGENT_CALL',
      level: 'INFO',
      node_id: 'scope_idea',
      message: 'Someone Else started',
      details: { stage: 'before', agent_role: 'Someone Else' },
    } as FrameData)
    expect(run.identityFor('scope_idea')).toBe('Startup validation scoper')
  })

  it('falls back to the DESCRIPTOR role for a node whose frames name none', () => {
    // The synthetic gate and routers carry no `agent_role` at all. This is the
    // rung a published graph lives on: the server declares the role on the
    // graph descriptor and the run never mentions it again.
    const declared: Record<string, string> = { confirm_scope: 'Scope Reviewer' }
    const { run } = replay('syntheticRun.ndjson', (nodeId) => declared[nodeId])
    expect(run.identityFor('confirm_scope')).toBe('Scope Reviewer')
  })

  it('falls back to the LABEL when the declared role is really an id', () => {
    // A builder descriptor has carried the node's own id in `agent_role`.
    // Seeding a character from it is not wrong-looking on its own; it is wrong
    // at the node's first real frame, when the character would change on
    // screen. A lowercase token with no space is treated as an identifier.
    const { run } = replay('syntheticRun.ndjson', () => 'n3_market')
    expect(run.identityFor('confirm_scope')).toBe('The confirm_scope card')
    expect(readsAsRole('n3_market')).toBe(false)
    expect(readsAsRole('market-analyst')).toBe(false)
    expect(readsAsRole('Scoper')).toBe(true)
    expect(readsAsRole('market research analyst')).toBe(true)
    expect(readsAsRole(undefined)).toBe(false)
  })

  it('falls back to the node id when there is no label either', () => {
    const run = useRunChoreography({
      nodeStates: ref<Record<string, NodeRunState>>({}),
      status: ref<RunStatus>('running'),
    })
    expect(run.identityFor('n7_unnamed')).toBe('n7_unnamed')
    expect(run.identityFor('')).toBe('')
  })
})

describe('one seed reaches the node, the token and the rail', () => {
  it('serves the node card and the trace the same string', () => {
    // T2.6's unit half. The E2E compares the rendered `data-character` on the
    // canvas with the one in the rail; what can be proved here is the thing
    // that makes those equal - both read ONE function, so there is no second
    // answer to disagree with.
    const { run } = replay('syntheticRun.ndjson')
    const identity = run.identityFor('research_market')
    expect(identity).toBe('Market evidence analyst')
    expect(run.identities.value.research_market).toBe(identity)

    const pip = mount(AgentCharacter, { props: { identity, state: 'working' } })
    expect(pip.attributes('data-character')).toBe(characterSeed(identity))

    const card = mount(WorkflowNode, {
      props: {
        data: nodeData({ nodeId: 'research_market', state: 'running' }),
        cast: { identity, state: run.castState('research_market') },
      },
      global: { stubs: { Handle: true } },
    })
    expect(card.get('.pip').attributes('data-character')).toBe(pip.attributes('data-character'))
    expect(card.get('.pip').attributes('data-state')).toBe('done')
  })

  it('serves the trace rail and the dialogue rail the SAME seed as the card', () => {
    // T2.6's unit half, over all three surfaces at once. The E2E compares the
    // rendered `data-character` on the canvas with the one in the rail; what a
    // mount can prove is the thing that makes them equal - the rails ask the
    // STORE, not their own row, so there is no second answer to disagree with.
    //
    // The row deliberately carries a WORSE identity than the store does: an
    // entry resolved before the node's first `agent_role` names the label. If
    // the rails read `entry.identity` the two seeds below would differ, which
    // is exactly the drift this criterion exists to catch.
    const { run } = replay('syntheticRun.ndjson')
    const identity = run.identityFor('research_market')
    const pose = run.castState('research_market')

    const card = mount(WorkflowNode, {
      props: {
        data: nodeData({ nodeId: 'research_market', state: 'completed' }),
        cast: { identity, state: pose },
      },
      global: { stubs: { Handle: true } },
    })
    const seed = card.get('.pip').attributes('data-character')

    const trace = mount(ChatRail, {
      props: {
        entries: [traceRow('research_market', 'The research_market card')],
        collapsed: false,
        identityOf: run.identityFor,
        stateOf: run.castState,
      },
    })
    expect(trace.get('.trace-avatar .pip').attributes('data-character')).toBe(seed)
    expect(trace.get('.trace-avatar .pip').attributes('data-state')).toBe(pose)
    // T2.1's line element carries the class the E2E reads it by.
    expect(trace.find('.trace-line').exists()).toBe(true)

    const spoken = mount(DialogueRail, {
      props: {
        entries: [spokenRow('research_market', 'The research_market card')],
        collapsed: false,
        characterOf: characterIndex,
        identityOf: run.identityFor,
        stateOf: run.castState,
      },
    })
    expect(spoken.get('.dialogue-avatar .pip').attributes('data-character')).toBe(seed)
    expect(spoken.get('.dialogue-avatar .pip').attributes('data-state')).toBe(pose)
  })

  it('stamps the sender identity onto every handoff it creates', () => {
    // The token walks an edge and is drawn by `WorkflowEdge`, which knows
    // nothing about agents. Resolving the seed where the handoff is CREATED is
    // what keeps the third view reading the same store as the other two.
    const { run } = replay('syntheticRun.ndjson')
    run.reset()
    const frames = loadFrames('syntheticRun.ndjson')
    for (const frame of frames.slice(0, 13)) run.ingest(frame)
    const walking = run.handoffs.value[run.handoffs.value.length - 1]
    expect(walking.from).toBe('scope_idea')
    expect(walking.fromIdentity).toBe('Startup validation scoper')
    expect(characterSeed(walking.fromIdentity)).toBe(characterSeed(run.identityFor('scope_idea')))
  })
})

describe('the gate blocks the agent that fed it', () => {
  /*
   * HAND-BUILT, and it says so: neither committed log has a gate on a node
   * other than the one that produced the work. The frames below are the shapes
   * the fixtures use - a `traversal` with `from`/`to` in `details`, a
   * `gate_open` whose `node_id` is the gate - so this is the missing case
   * rather than a different vocabulary.
   */
  function harness() {
    const nodeStates = ref<Record<string, NodeRunState>>({ scoper: 'idle', confirm: 'idle' })
    return {
      nodeStates,
      ...useRunChoreography({ nodeStates, status: ref<RunStatus>('running') }),
    }
  }

  function frame(partial: Partial<FrameData> & Pick<FrameData, 'kind'>): FrameData {
    return {
      v: 1,
      seq: 1,
      run_id: 'run-1',
      ts: new Date().toISOString(),
      event_type: 'NODE_START',
      level: 'INFO',
      message: '',
      details: {},
      ...partial,
    } as FrameData
  }

  it('marks the feeding agent blocked while a gate waits, and the gate is not a cast member', () => {
    const run = harness()
    run.ingest(frame({
      kind: 'node_state',
      node_id: 'scoper',
      event_type: 'NODE_START',
      details: { stage: 'before', agent_role: 'Startup Scoper' },
    }))
    run.ingest(frame({
      kind: 'node_state',
      node_id: 'scoper',
      event_type: 'NODE_END',
      details: { stage: 'after', agent_role: 'Startup Scoper' },
    }))
    run.ingest(frame({
      kind: 'edge_taken',
      node_id: 'confirm',
      event_type: 'EDGE_PROCESS',
      message: 'scoper to confirm',
      details: { stage: 'traversal', from: 'scoper', to: 'confirm', port: null },
    }))
    expect(run.castState('scoper')).toBe('done')

    run.ingest(frame({
      kind: 'gate_open',
      node_id: 'confirm',
      event_type: 'HUMAN_INTERACTION',
      message: 'Confirm the scope',
      details: { stage: 'before', gate_id: 'g1' },
    }))
    // The gate node itself is waiting; the agent whose output is being
    // questioned is blocked WITH it. Blocked beats done here on purpose: the
    // scoper's work really is held up, and the gate draws no character at all,
    // so without this the one moment the run is stopped has nothing on the
    // canvas saying so.
    expect(run.castState('confirm')).toBe('blocked')
    expect(run.castState('scoper')).toBe('blocked')

    run.ingest(frame({
      kind: 'gate_closed',
      node_id: 'confirm',
      event_type: 'HUMAN_INTERACTION',
      message: 'Feedback received',
      details: { stage: 'after', gate_id: 'g1' },
    }))
    expect(run.castState('confirm')).toBe('done')
    expect(run.castState('scoper')).toBe('done')
  })

  it('falls back to the last node that started when no edge fed the gate', () => {
    // A run replayed from frames that name no traversal into the gate - which
    // is every hand-written flow whose edges the server does not publish.
    const run = harness()
    run.ingest(frame({
      kind: 'node_state',
      node_id: 'scoper',
      event_type: 'NODE_START',
      details: { stage: 'before', agent_role: 'Startup Scoper' },
    }))
    run.ingest(frame({
      kind: 'gate_open',
      node_id: 'confirm',
      event_type: 'HUMAN_INTERACTION',
      details: { stage: 'before', gate_id: 'g1' },
    }))
    expect(run.castState('scoper')).toBe('blocked')
  })

  it('never blocks a node that has failed', () => {
    // Worst news first. A red character replaced by an amber one would hide
    // the failure behind the gate that is waiting on it.
    const run = harness()
    run.ingest(frame({
      kind: 'node_state',
      node_id: 'scoper',
      event_type: 'NODE_END',
      level: 'ERROR',
      details: { stage: 'error', error: 'no signing key configured' },
    }))
    run.ingest(frame({
      kind: 'gate_open',
      node_id: 'confirm',
      event_type: 'HUMAN_INTERACTION',
      details: { stage: 'before', gate_id: 'g1' },
    }))
    expect(run.castState('scoper')).toBe('blocked-error')
  })
})

describe('the motion budget, with characters in it', () => {
  it('stays inside the plan-11 bound of twelve across the whole synthetic run', () => {
    // Measured after EVERY frame rather than at the end: the bound is a
    // property of the design, not of one moment. The fan-out is where it is
    // tightest - three branches, three marching edges, three tokens.
    const { frames } = replay('syntheticRun.ndjson')
    const nodeStates = ref<Record<string, NodeRunState>>({})
    const activeEdgeIds = ref(new Set<string>())
    const run = useRunChoreography({
      nodeStates,
      status: ref<RunStatus>('running'),
      activeEdgeIds,
    })
    const observed: number[] = []
    for (const frame of frames) {
      run.ingest(frame)
      /*
       * The console's own edge lifecycle, restated: a traversal starts an edge
       * marching towards its target, and the target settling ends it -
       * `useValidatorRun.deactivateEdgesInto`, and the token's own arrival.
       * Modelling it matters, because an edge list that only ever grew would
       * measure a console nobody ships and would put this bound at 21 rather
       * than at what the design actually costs.
       */
      const nodeId = frame.node_id ?? ''
      if (frame.kind === 'edge_taken') {
        activeEdgeIds.value = new Set(activeEdgeIds.value).add(nodeId)
        nodeStates.value = { ...nodeStates.value, [nodeId]: 'running' }
      }
      if (frame.kind === 'node_state' && nodeId) {
        if (frame.event_type.includes('START')) {
          nodeStates.value = { ...nodeStates.value, [nodeId]: 'running' }
        }
        if (frame.event_type.includes('END')) {
          nodeStates.value = { ...nodeStates.value, [nodeId]: 'completed' }
          const next = new Set(activeEdgeIds.value)
          next.delete(nodeId)
          activeEdgeIds.value = next
          for (const walking of run.handoffs.value.filter((entry) => entry.to === nodeId)) {
            run.endHandoff(walking.edgeId)
          }
        }
      }
      observed.push(run.liveAnimationCount.value)
    }
    expect(Math.max(...observed)).toBeLessThanOrEqual(12)
  })

  it('counts a card and the character standing on it ONCE', () => {
    // The union rather than the sum, for the reason the glow and the elapsed
    // clock are already one: they are the same card moving for the same
    // reason. Every looping Pip on this run stands on a running card, so the
    // cast adds nothing to the count - which is the measurement, not an
    // assumption.
    const nodeStates = ref<Record<string, NodeRunState>>({ a: 'running', b: 'running' })
    const run = useRunChoreography({ nodeStates, status: ref<RunStatus>('running') })
    run.ingest({
      v: 1,
      seq: 1,
      run_id: 'r',
      ts: new Date().toISOString(),
      kind: 'node_state',
      event_type: 'NODE_START',
      level: 'INFO',
      node_id: 'a',
      message: 'a started',
      details: { stage: 'before', agent_role: 'Alpha' },
    } as FrameData)
    expect(run.castState('a')).toBe('working')
    expect(run.loopingCharacters.value.has('a')).toBe(true)
    expect(run.liveAnimationCount.value).toBe(2)
  })

  it('lets nothing loop once the run is terminal', () => {
    const nodeStates = ref<Record<string, NodeRunState>>({ a: 'completed' })
    const status = ref<RunStatus>('completed')
    const run = useRunChoreography({ nodeStates, status })
    expect(run.liveAnimationCount.value).toBe(0)
    expect(run.castState('a')).toBe('done')
  })

  it('does not loop for idle, blocked or done - only working and speaking', () => {
    // `character.css` makes idle and done completely still and gives blocked a
    // ONE-SHOT settle rather than a pulse, so those three cost nothing on a
    // sixteen-node canvas. The count has to agree with that sheet or the bound
    // is arithmetic about a design nobody shipped.
    const nodeStates = ref<Record<string, NodeRunState>>({
      idle: 'idle',
      waiting: 'waiting',
      done: 'completed',
      broken: 'error',
    })
    const run = useRunChoreography({ nodeStates, status: ref<RunStatus>('running') })
    expect([...run.loopingCharacters.value]).toEqual([])
  })
})

/** One trace row, shaped as `trace/interpret.ts` produces them. */
function traceRow(nodeId: string, identity: string): ChatEntry {
  return {
    id: `${nodeId}-1`,
    nodeId,
    identity,
    actor: identity,
    message: 'Searched the market for competitors.',
    timestamp: '10:00:00',
    variant: 'agent',
    tone: 'info',
    raw: { kind: 'tool', eventType: 'TOOL_CALL', seq: 22, message: 'x', details: '{}' },
  } as unknown as ChatEntry
}

/** One spoken line, shaped as the choreography's own `DialogueEntry`. */
function spokenRow(nodeId: string, role: string): DialogueEntry {
  return {
    callId: `${nodeId}-call`,
    nodeId,
    role,
    task: 'market_task',
    text: 'The market is larger than the scope implies.',
    revealed: 43,
    truncated: false,
    tokens: { prompt: 640, completion: 120 },
    at: 1_700_000_000_000,
    collapsed: false,
  }
}

function nodeData(overrides: Partial<StudioNodeData> = {}): StudioNodeData {
  return {
    label: 'Market Analyst',
    eyebrow: '03 - RESEARCH',
    description: 'Searches the live market for competitors and pricing.',
    kind: 'agent',
    state: 'idle',
    usage: zeroUsage(),
    frameCount: 0,
    visits: 0,
    activeCall: null,
    character: 1,
    receded: false,
    errorMessage: '',
    replayed: false,
    receiving: false,
    index: 0,
    landing: false,
    nodeId: 'node',
    rerunnable: false,
    ...overrides,
  }
}
