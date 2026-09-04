import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import validatorTemplate from './fixtures/builderValidatorTemplate.json'
import {
  CHARACTER_COUNT,
  MAX_PENDING_REVEALS,
  REVEAL_CHARS_PER_SECOND,
  characterIndex,
  characterVar,
  collapsedPreview,
  handoffDurationMs,
  useRunChoreography,
} from '../src/composables/useRunChoreography'
import type { FrameData, NodeRunState, RunStatus } from '../src/types/studio'

/**
 * The run console's choreography, driven by frames rather than by a backend.
 *
 * Every frame built here is the SHAPE the server actually emits, not a
 * convenient one: `stage` discriminators on the existing kinds (C6), the
 * seven-key utterance from `events/serializer.py`, the three-key coalesced
 * chunk from `events/adapter.py::_merged_chunk`, the four-key traversal. A
 * fixture that diverges from its subject certifies nothing, which this
 * repository has now had to write down four times.
 */

let seq = 0

function frame(partial: Partial<FrameData> & Pick<FrameData, 'kind'>): FrameData {
  seq += 1
  return {
    run_id: 'run-1',
    seq,
    ts: new Date(1_700_000_000_000 + seq * 1000).toISOString(),
    kind: partial.kind,
    event_type: partial.event_type ?? 'NODE_START',
    level: partial.level ?? 'INFO',
    node_id: partial.node_id ?? null,
    message: partial.message ?? '',
    details: partial.details ?? {},
    duration_ms: partial.duration_ms,
  } as FrameData
}

function utterance(nodeId: string, text: string, callId = `call-${nodeId}`): FrameData {
  return frame({
    kind: 'llm',
    event_type: 'MODEL_CALL',
    node_id: nodeId,
    message: 'gemini-3.5-flash-lite said',
    details: {
      stage: 'utterance',
      call_id: callId,
      text,
      truncated: false,
      prompt_tokens: 640,
      completion_tokens: 120,
      model: 'google/gemini-3.5-flash-lite',
    },
  })
}

function chunk(nodeId: string, text: string, callId = `call-${nodeId}`): FrameData {
  return frame({
    kind: 'llm',
    event_type: 'MODEL_CALL',
    node_id: nodeId,
    message: 'Model stream chunk',
    details: { stage: 'chunk', call_id: callId, chunk: text },
  })
}

function traversal(from: string, to: string): FrameData {
  return frame({
    kind: 'edge_taken',
    event_type: 'EDGE_PROCESS',
    node_id: to,
    message: `${from} to ${to}`,
    details: { stage: 'traversal', from, to, port: null },
  })
}

function planStage(index: number, of: number, label: string, nodeIds: string[]): FrameData {
  return frame({
    kind: 'run_state',
    event_type: 'NODE_START',
    node_id: 'workflow',
    message: `Stage ${index} of ${of}`,
    details: { stage: 'plan', index, of, label, node_ids: nodeIds },
  })
}

function harness(initial: Record<string, NodeRunState> = {}) {
  const nodeStates = ref<Record<string, NodeRunState>>({ ...initial })
  const status = ref<RunStatus>('running')
  const activeEdgeIds = ref(new Set<string>())
  const choreography = useRunChoreography({
    nodeStates,
    status,
    activeEdgeIds,
    labelFor: (id) => `Label for ${id}`,
    edgeIdFor: (from, to) => `${from}->${to}`,
    now: () => 1_700_000_000_000,
  })
  return { nodeStates, status, activeEdgeIds, ...choreography }
}

describe('characterIndex', () => {
  it('is pure: the same id yields the same index across a thousand calls', () => {
    // Criterion 1. The whole reason a hash was chosen over an assignment table:
    // the medallion on the card, the avatar in the rail and the walking token
    // are three call sites, and they cannot be allowed to disagree.
    const first = characterIndex('research_market')
    for (let i = 0; i < 1000; i += 1) {
      expect(characterIndex('research_market')).toBe(first)
    }
  })

  it('stays inside the twelve declared colours', () => {
    const ids = ['a', '', 'a very long node identifier with spaces', '🙂', 'route_scope']
    for (const id of ids) {
      const index = characterIndex(id)
      expect(index).toBeGreaterThanOrEqual(1)
      expect(index).toBeLessThanOrEqual(CHARACTER_COUNT)
    }
  })

  it('spreads the validator template over at least eight colours', () => {
    // Criterion 1's second half, measured against the committed template
    // fixture rather than a list typed here - the fixture is what a run
    // actually renders.
    const ids = validatorTemplate.document.nodes.map((node) => node.id)
    expect(ids).toHaveLength(16)
    const distinct = new Set(ids.map((id) => characterIndex(id)))
    expect(distinct.size).toBeGreaterThanOrEqual(8)
  })

  it('names the custom property the stylesheet declares', () => {
    expect(characterVar('scoper')).toBe(`var(--character-${characterIndex('scoper')})`)
  })
})

describe('handoff duration', () => {
  it('is the reference formula, clamped at both ends', () => {
    // clamp(pathLength x 0.02, 2000, 4000), LaunchView.vue:2044-2075.
    expect(handoffDurationMs(10)).toBe(2000)
    expect(handoffDurationMs(150_000)).toBe(3000)
    expect(handoffDurationMs(250_000)).toBe(4000)
    expect(handoffDurationMs(Number.NaN)).toBe(2000)
  })
})

describe('handoffs', () => {
  it('starts one token per traversal frame', () => {
    const run = harness()
    run.ingest(traversal('scoper', 'confirm_scope'))
    expect(run.handoffs.value).toHaveLength(1)
    expect(run.handoffs.value[0]).toMatchObject({
      edgeId: 'scoper->confirm_scope',
      from: 'scoper',
      to: 'confirm_scope',
    })
  })

  it('keeps at most one token in flight per edge', () => {
    // D3's concurrency bound. A tight revise loop traverses one edge repeatedly
    // and four tokens stacked on one bezier is not a picture of anything.
    const run = harness()
    run.ingest(traversal('route_scope', 'revise_scope'))
    run.ingest(traversal('route_scope', 'revise_scope'))
    expect(run.handoffs.value).toHaveLength(1)
  })

  it('runs the three fan-out branches at once', () => {
    const run = harness()
    for (const branch of ['research_market', 'research_sentiment', 'research_feasibility']) {
      run.ingest(traversal('route_scope', branch))
    }
    expect(run.handoffs.value).toHaveLength(3)
  })

  it('drops a token when its walk ends', () => {
    const run = harness()
    run.ingest(traversal('a', 'b'))
    run.endHandoff('a->b')
    expect(run.handoffs.value).toEqual([])
  })

  it('ignores a traversal missing an end', () => {
    const run = harness()
    run.ingest(traversal('', 'b'))
    run.ingest(traversal('a', ''))
    expect(run.handoffs.value).toEqual([])
  })
})

describe('stages', () => {
  it('collects the plan frames in index order however they arrive', () => {
    const run = harness()
    run.ingest(planStage(2, 3, 'Research', ['market', 'signal']))
    run.ingest(planStage(1, 3, 'Scope', ['scoper']))
    run.ingest(planStage(3, 3, 'Report', ['reporter']))
    expect(run.stages.value.map((stage) => stage.label)).toEqual(['Scope', 'Research', 'Report'])
  })

  it('replaces a re-sent index rather than duplicating it', () => {
    const run = harness()
    run.ingest(planStage(1, 2, 'Scope', ['scoper']))
    run.ingest(planStage(1, 2, 'Scope', ['scoper']))
    expect(run.stages.value).toHaveLength(1)
  })

  it('ignores a plan frame naming no nodes', () => {
    const run = harness()
    run.ingest(planStage(1, 1, 'Nothing', []))
    expect(run.stages.value).toEqual([])
  })
})

describe('dialogue', () => {
  it('reveals an unstreamed utterance at 120 characters a second', () => {
    // Criterion 8. Driven through `advanceReveal` at exact millisecond
    // boundaries rather than through requestAnimationFrame, because a rAF race
    // measures the runner and fake timers hang a mount in this suite.
    const run = harness()
    const text = 'x'.repeat(1200)
    run.ingest(utterance('scoper', text))
    run.advanceReveal(0)
    run.advanceReveal(1000)
    const afterOneSecond = run.dialogue.value[0].revealed
    expect(afterOneSecond).toBeGreaterThanOrEqual(REVEAL_CHARS_PER_SECOND - 10)
    expect(afterOneSecond).toBeLessThanOrEqual(REVEAL_CHARS_PER_SECOND + 10)

    run.advanceReveal(2000)
    expect(run.dialogue.value[0].revealed).toBeCloseTo(REVEAL_CHARS_PER_SECOND * 2, 5)
  })

  it('never reveals past the end of the text', () => {
    const run = harness()
    run.ingest(utterance('scoper', 'short'))
    run.advanceReveal(0)
    run.advanceReveal(60_000)
    expect(run.dialogue.value[0].revealed).toBe(5)
  })

  it('dumps every pending entry but the newest past the catch-up bound', () => {
    // Criterion 8's second half. Three simultaneous reveals is not legible and
    // is not faster; the rail is never more than two speakers behind.
    const run = harness()
    run.ingest(utterance('a', 'a'.repeat(400), 'call-a'))
    run.ingest(utterance('b', 'b'.repeat(400), 'call-b'))
    run.ingest(utterance('c', 'c'.repeat(400), 'call-c'))
    const revealed = run.dialogue.value.map((entry) => entry.revealed)
    expect(revealed[0]).toBe(400)
    expect(revealed[1]).toBe(400)
    expect(revealed[2]).toBe(0)
    expect(run.pending.value).toHaveLength(1)
    expect(MAX_PENDING_REVEALS).toBe(2)
  })

  it('concatenates five chunks for one call into one entry', () => {
    // Criterion 9. `useValidatorRun` discarded every chunk frame outright, so
    // the one surface that shows a model producing text could not exist.
    const run = harness()
    for (const part of ['Hello', ', ', 'wor', 'ld', '!']) run.ingest(chunk('scoper', part))
    run.ingest(utterance('scoper', 'Hello, world!'))
    expect(run.dialogue.value).toHaveLength(1)
    expect(run.dialogue.value[0].text).toBe('Hello, world!')
  })

  it('shows a streamed answer whole rather than replaying it', () => {
    // The trap this avoids: a call that streamed every character and then
    // completed would re-reveal itself from zero, which reads as a bug.
    const run = harness()
    run.ingest(chunk('scoper', 'Hello, world!'))
    run.ingest(utterance('scoper', 'Hello, world!'))
    expect(run.dialogue.value[0].revealed).toBe(13)
    expect(run.pending.value).toEqual([])
  })

  it('reveals only the part a partial stream did not deliver', () => {
    const run = harness()
    run.ingest(chunk('scoper', 'Hello'))
    run.ingest(utterance('scoper', 'Hello, world!'))
    expect(run.dialogue.value[0].revealed).toBe(5)
  })

  it('takes the role from the agent frame when there is one', () => {
    const run = harness()
    run.ingest(
      frame({
        kind: 'agent',
        event_type: 'AGENT_CALL',
        node_id: 'scoper',
        message: 'Startup Scoper started',
        details: { stage: 'before', task: 'scoping_task' },
      }),
    )
    run.ingest(utterance('scoper', 'text'))
    expect(run.dialogue.value[0].role).toBe('Startup Scoper')
    expect(run.dialogue.value[0].task).toBe('scoping_task')
  })

  it('falls back to the node label when no agent frame arrived', () => {
    // The utterance frame carries no role, deliberately - the real serializer
    // writes seven keys and none of them is one. This is the honest
    // second-best rather than a field production never sends.
    const run = harness()
    run.ingest(utterance('scoper', 'text'))
    expect(run.dialogue.value[0].role).toBe('Label for scoper')
  })

  it('carries the truncation flag and the token counts', () => {
    const run = harness()
    const truncated = utterance('scoper', 'text')
    truncated.details.truncated = true
    run.ingest(truncated)
    expect(run.dialogue.value[0].truncated).toBe(true)
    expect(run.dialogue.value[0].tokens).toEqual({ prompt: 640, completion: 120 })
  })

  it('collapses everything but the last three entries', () => {
    const run = harness()
    for (const id of ['a', 'b', 'c', 'd', 'e']) run.ingest(utterance(id, 'text', `call-${id}`))
    expect(run.dialogue.value.map((entry) => entry.collapsed)).toEqual([
      true,
      true,
      false,
      false,
      false,
    ])
  })

  it('ignores an utterance with no text', () => {
    const run = harness()
    run.ingest(utterance('scoper', ''))
    expect(run.dialogue.value).toEqual([])
  })

  it('reveals everything on demand', () => {
    const run = harness()
    run.ingest(utterance('scoper', 'x'.repeat(500)))
    run.revealAll()
    expect(run.dialogue.value[0].revealed).toBe(500)
  })
})

describe('collapsedPreview', () => {
  it('keeps a short line whole', () => {
    expect(collapsedPreview('  a short line ')).toBe('a short line')
  })

  it('trims a long one to eighty characters with an ellipsis', () => {
    const preview = collapsedPreview('y'.repeat(200))
    expect(preview).toHaveLength(81)
    expect(preview.endsWith('…')).toBe(true)
  })
})

describe('the idle recede', () => {
  it('recedes every card that is not the speaker while the run is live', () => {
    // Criterion 3's unit half. The reference emphasises the active node and
    // does nothing to the other fifteen; emphasis with no recession is not
    // emphasis.
    const run = harness({
      scoper: 'running',
      confirm_scope: 'idle',
      reporter: 'completed',
      broken: 'error',
      gate: 'waiting',
    })
    expect(run.isReceded('scoper')).toBe(false)
    expect(run.isReceded('gate')).toBe(false)
    expect(run.isReceded('broken')).toBe(false)
    expect(run.isReceded('confirm_scope')).toBe(true)
    expect(run.isReceded('reporter')).toBe(true)
  })

  it('lifts on a terminal run', () => {
    const run = harness({ scoper: 'completed', reporter: 'idle' })
    run.status.value = 'completed'
    expect(run.isReceded('scoper')).toBe(false)
    expect(run.isReceded('reporter')).toBe(false)
  })

  it('does not recede before a run starts', () => {
    const run = harness({ scoper: 'idle' })
    run.status.value = 'idle'
    expect(run.isReceded('scoper')).toBe(false)
  })
})

describe('the alive-not-noisy bound', () => {
  /** A thirty-frame fan-out: plan, traversals, chunks, utterances, states. */
  function fanOut(run: ReturnType<typeof harness>): void {
    run.ingest(planStage(1, 3, 'Scope', ['scoper']))
    run.ingest(planStage(2, 3, 'Research', ['market', 'signal', 'build']))
    run.ingest(planStage(3, 3, 'Report', ['reporter']))
    run.ingest(traversal('scoper', 'route'))
    run.nodeStates.value = { scoper: 'completed', route: 'running' }
    for (const branch of ['market', 'signal', 'build']) {
      run.ingest(traversal('route', branch))
      run.activeEdgeIds.value.add(`route->${branch}`)
      for (const part of ['Look', 'ing ', 'at ', 'the ', 'evidence.']) {
        run.ingest(chunk(branch, part, `call-${branch}`))
      }
      run.ingest(utterance(branch, 'Looking at the evidence.', `call-${branch}`))
    }
    run.nodeStates.value = {
      scoper: 'completed',
      route: 'completed',
      market: 'running',
      signal: 'running',
      build: 'running',
      reporter: 'idle',
    }
  }

  it('never exceeds twelve across a thirty-frame fan-out', () => {
    // Criterion 11. The bound is a property of the design, not of one moment,
    // so it is measured after every frame rather than at the end.
    const run = harness()
    const observed: number[] = []
    const record = () => observed.push(run.liveAnimationCount.value)
    run.ingest(planStage(1, 3, 'Scope', ['scoper']))
    record()
    fanOut(run)
    record()
    expect(Math.max(...observed)).toBeLessThanOrEqual(12)
    expect(observed.every((count) => count >= 0)).toBe(true)
  })

  it('is zero once the run is terminal', () => {
    const run = harness()
    fanOut(run)
    expect(run.liveAnimationCount.value).toBeGreaterThan(0)
    run.status.value = 'completed'
    expect(run.liveAnimationCount.value).toBe(0)
  })

  it('counts the launch glow, and only until the first frame', () => {
    const run = harness()
    run.status.value = 'queued'
    run.arm()
    expect(run.armed.value).toBe(true)
    expect(run.liveAnimationCount.value).toBe(1)
    run.ingest(planStage(1, 1, 'Scope', ['scoper']))
    expect(run.armed.value).toBe(false)
  })
})

describe('node errors and replay', () => {
  it('keeps the message a node_error frame carried', () => {
    // Criterion 15 / plan 12 D2's data half.
    const run = harness()
    run.ingest(
      frame({
        kind: 'error',
        event_type: 'NODE_END',
        level: 'ERROR',
        node_id: 'market',
        message: 'market failed on attempt 1',
        details: {
          stage: 'error',
          error_class: 'rate_limit',
          message: 'RateLimitError: the provider refused, 429',
          attempt: 1,
          will_retry: false,
          fallback_model: null,
          routed: false,
        },
      }),
    )
    expect(run.nodeErrors.value.market).toBe('RateLimitError: the provider refused, 429')
  })

  it('falls back to the frame message when the detail is missing', () => {
    const run = harness()
    run.ingest(
      frame({
        kind: 'error',
        event_type: 'NODE_END',
        level: 'ERROR',
        node_id: 'market',
        message: 'market failed',
        details: { stage: 'error' },
      }),
    )
    expect(run.nodeErrors.value.market).toBe('market failed')
  })

  it('marks a replayed node so the console can draw it dimmed', () => {
    // Plan 12 D6: `resume_from` replays every upstream node, and the frames say
    // so (`10-runtime.md` D5). A replayed node that looked like a run node
    // would claim work that was never done.
    const run = harness()
    run.ingest(
      frame({
        kind: 'node_state',
        event_type: 'NODE_START',
        node_id: 'scoper',
        message: 'scoper replayed from a saved run',
        details: { stage: 'before', replayed: true, source: 'run' },
      }),
    )
    expect(run.replayed.value.has('scoper')).toBe(true)
  })
})

describe('reset', () => {
  it('clears everything a relaunch must not inherit', () => {
    const run = harness()
    run.ingest(planStage(1, 1, 'Scope', ['scoper']))
    run.ingest(traversal('a', 'b'))
    run.ingest(utterance('scoper', 'text'))
    run.reset()
    expect(run.stages.value).toEqual([])
    expect(run.handoffs.value).toEqual([])
    expect(run.dialogue.value).toEqual([])
    expect(run.framesApplied.value).toBe(0)
  })

  it('counts every frame applied, which is the reconnect strip N', () => {
    const run = harness()
    run.ingest(planStage(1, 1, 'Scope', ['scoper']))
    run.ingest(traversal('a', 'b'))
    expect(run.framesApplied.value).toBe(2)
  })
})
