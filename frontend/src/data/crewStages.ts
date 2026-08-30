import type { GraphDescriptor, NodeRunState } from '../types/studio'

/**
 * The pipeline as an ORDERED list of stages.
 *
 * The graph descriptor has no ordering. Its nodes arrive as an unordered array
 * with hardcoded x/y coordinates, and the only sequence signal anywhere in the
 * UI was the `eyebrow` string ("01 - DEFINE"), rendered at 11px CSS which the
 * default fit shrinks to about 5px on screen. So the console drew a topology
 * but never answered the two questions an operator actually has: how far along
 * is this, and what is working right now.
 *
 * Grouping is declared here rather than derived, because "these three nodes are
 * one logical stage" is a judgement about the pipeline, not a fact recoverable
 * from edges - a topological sort would happily emit the three research
 * branches as three separate steps and lose the thing that makes them
 * interesting, which is that they happen at once.
 *
 * `assertStageCoverage` is the safety net: it mirrors the exact-set-match the
 * service performs between `VALIDATOR_OVERLAY` and the derived topology
 * (`service/graph.py:77-86`). Add a node to the flow without adding it here and
 * a test fails, rather than the boat silently skipping it.
 */

export type StageKind = 'work' | 'gate' | 'output'

export interface CrewStage {
  id: string
  /** Shown under the stage marker. */
  label: string
  /** Every node that can put this stage in a running/waiting/error state. */
  nodeIds: string[]
  /** The nodes that must ALL complete before the stage counts as done. */
  coreIds: string[]
  kind: StageKind
  /** True for the fan-out, which is drawn as one stage with three oars. */
  parallel?: boolean
}

export const CREW_STAGES: readonly CrewStage[] = [
  {
    id: 'scope',
    label: 'Scope',
    nodeIds: ['scope_idea', 'revise_scope'],
    coreIds: ['scope_idea'],
    kind: 'work',
  },
  {
    id: 'gate-scope',
    label: 'Confirm',
    nodeIds: ['confirm_scope', 'route_scope'],
    coreIds: ['confirm_scope'],
    kind: 'gate',
  },
  {
    id: 'research',
    label: 'Research',
    nodeIds: ['research_market', 'research_sentiment', 'research_feasibility'],
    coreIds: ['research_market', 'research_sentiment', 'research_feasibility'],
    kind: 'work',
    parallel: true,
  },
  {
    id: 'score',
    label: 'Score',
    nodeIds: ['synthesize', 'revise_verdict'],
    coreIds: ['synthesize'],
    kind: 'work',
  },
  {
    id: 'gate-verdict',
    label: 'Review',
    nodeIds: ['review_verdict', 'route_verdict'],
    coreIds: ['review_verdict'],
    kind: 'gate',
  },
  {
    id: 'report',
    label: 'Report',
    nodeIds: ['write_report'],
    coreIds: ['write_report'],
    kind: 'work',
  },
  {
    id: 'brief',
    label: 'Brief',
    nodeIds: ['persist'],
    coreIds: ['persist'],
    kind: 'output',
  },
]

/** The quarantine node is instrumentation, not a pipeline stage. */
const NOT_A_STAGE = new Set(['unattributed'])

/**
 * Every descriptor node is either in exactly one stage or explicitly excluded.
 * Returns the problems rather than throwing, so a test can name them and the
 * runtime can degrade instead of blanking the canvas.
 */
export function assertStageCoverage(descriptor: GraphDescriptor): string[] {
  const problems: string[] = []
  const seen = new Map<string, string>()
  for (const stage of CREW_STAGES) {
    for (const nodeId of stage.nodeIds) {
      const already = seen.get(nodeId)
      if (already) problems.push(`${nodeId} is claimed by both ${already} and ${stage.id}`)
      seen.set(nodeId, stage.id)
    }
    for (const coreId of stage.coreIds) {
      if (!stage.nodeIds.includes(coreId)) {
        problems.push(`${stage.id} lists core node ${coreId} outside its nodeIds`)
      }
    }
  }
  for (const node of descriptor.nodes) {
    if (NOT_A_STAGE.has(node.id)) continue
    if (!seen.has(node.id)) problems.push(`${node.id} belongs to no stage`)
  }
  for (const nodeId of seen.keys()) {
    if (!descriptor.nodes.some((node) => node.id === nodeId)) {
      problems.push(`${nodeId} is staged but absent from the graph`)
    }
  }
  return problems
}

export type StageState = 'idle' | 'running' | 'waiting' | 'completed' | 'error'

export interface StageProgress {
  stage: CrewStage
  state: StageState
  /** How many of the stage's core nodes have finished - drives the oar count. */
  done: number
  total: number
}

/**
 * Collapse per-node state into per-stage state. Severity order matters: an
 * errored node must not be hidden by a sibling that is merely running, and a
 * gate WAITING for a human is the single most important thing on screen.
 */
export function stageProgress(
  nodeStates: Record<string, NodeRunState>,
  stages: readonly CrewStage[] = CREW_STAGES,
): StageProgress[] {
  return stages.map((stage) => {
    const states = stage.nodeIds.map((id) => nodeStates[id] ?? 'idle')
    const done = stage.coreIds.filter((id) => nodeStates[id] === 'completed').length
    let state: StageState = 'idle'
    if (done === stage.coreIds.length && done > 0) state = 'completed'
    if (states.includes('running')) state = 'running'
    if (states.includes('waiting')) state = 'waiting'
    if (states.includes('error')) state = 'error'
    return { stage, state, done, total: stage.coreIds.length }
  })
}

/**
 * Where the boat sits.
 *
 * An unfinished stage that is doing something wins outright. Otherwise the boat
 * rests just past the last finished stage, which is what makes it read as
 * progress rather than as a cursor. Returns -1 before anything has happened, so
 * the caller can hide the crew entirely on an idle console.
 */
export function activeStageIndex(progress: StageProgress[]): number {
  const busy = progress.findIndex((entry) => entry.state === 'waiting' || entry.state === 'error')
  if (busy !== -1) return busy
  const running = progress.findIndex((entry) => entry.state === 'running')
  if (running !== -1) return running
  let lastDone = -1
  progress.forEach((entry, index) => {
    if (entry.state === 'completed') lastDone = index
  })
  if (lastDone === -1) return -1
  return Math.min(lastDone + 1, progress.length - 1)
}
