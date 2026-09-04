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
  /**
   * Nodes whose running means the crew has been sent BACK to this stage.
   *
   * These are already in `nodeIds` - the extra declaration is what lets the
   * strip distinguish "still on stage 1" from "back on stage 1 for a second
   * pass", which are the same picture without it. A revise node is deliberately
   * never a `coreId`: the stage is done when its core work is done, and a
   * revision is another lap of that same work, not a further requirement.
   */
  reviseIds?: string[]
  /**
   * Short names for the `coreIds`, in that order. Only meaningful on a parallel
   * stage, where they name the oars.
   *
   * Declared rather than read from the descriptor's node labels because the oar
   * caption has about eight characters of room at this size - "Market" fits,
   * "Market research" does not - and because a label the graph is free to
   * reword should not silently change what the boat says.
   */
  branchLabels?: string[]
}

export const CREW_STAGES: readonly CrewStage[] = [
  {
    id: 'scope',
    label: 'Scope',
    nodeIds: ['scope_idea', 'revise_scope'],
    coreIds: ['scope_idea'],
    reviseIds: ['revise_scope'],
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
    branchLabels: ['Market', 'Signal', 'Build'],
    kind: 'work',
    parallel: true,
  },
  {
    id: 'score',
    label: 'Score',
    nodeIds: ['synthesize', 'revise_verdict'],
    coreIds: ['synthesize'],
    reviseIds: ['revise_verdict'],
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
export function assertStageCoverage(
  descriptor: GraphDescriptor,
  stages: readonly CrewStage[] = CREW_STAGES,
): string[] {
  const problems: string[] = []
  const seen = new Map<string, string>()
  for (const stage of stages) {
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
    for (const reviseId of stage.reviseIds ?? []) {
      if (!stage.nodeIds.includes(reviseId)) {
        problems.push(`${stage.id} lists revise node ${reviseId} outside its nodeIds`)
      }
      // A revise node that is also core would make the stage un-completable:
      // `done` counts completed cores, and the revise node is idle on a run
      // that never loops, so the stage would never reach `completed`.
      if (stage.coreIds.includes(reviseId)) {
        problems.push(`${stage.id} lists ${reviseId} as both core and revise`)
      }
    }
    if (stage.branchLabels && stage.branchLabels.length !== stage.coreIds.length) {
      problems.push(
        `${stage.id} has ${stage.branchLabels.length} branch labels for ${stage.coreIds.length} core nodes`,
      )
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

/** One oar. Named, so the strip can say WHICH branch is still pulling. */
export interface BranchProgress {
  id: string
  label: string
  state: NodeRunState
}

export interface StageProgress {
  stage: CrewStage
  state: StageState
  /** How many of the stage's core nodes have finished - drives the oar count. */
  done: number
  total: number
  /**
   * Which pass over this stage the crew is on. 0 before the stage is entered,
   * 1 on a straight run, 2+ once a revise has sent it back.
   */
  lap: number
  /** One entry per core node, in `coreIds` order. Named for the oars. */
  branches: BranchProgress[]
}

/** Highest visit count over a set of nodes. Absent counts read as never-run. */
function maxVisits(ids: readonly string[], visits: Record<string, number>): number {
  return ids.reduce((most, id) => Math.max(most, visits[id] ?? 0), 0)
}

/**
 * Collapse per-node state into per-stage state. Severity order matters: an
 * errored node must not be hidden by a sibling that is merely running, and a
 * gate WAITING for a human is the single most important thing on screen.
 *
 * `visits` is optional so every existing caller keeps working; without it every
 * entered stage simply reports lap 1, which is the truth for a run that never
 * revises and an honest under-report for one that does.
 */
export function stageProgress(
  nodeStates: Record<string, NodeRunState>,
  stages: readonly CrewStage[] = CREW_STAGES,
  visits: Record<string, number> = {},
): StageProgress[] {
  return stages.map((stage) => {
    const states = stage.nodeIds.map((id) => nodeStates[id] ?? 'idle')
    const done = stage.coreIds.filter((id) => nodeStates[id] === 'completed').length
    const coresDone = done === stage.coreIds.length && done > 0

    /*
     * Which running node can drag a finished stage back to `running`.
     *
     * Answering a gate makes the backend start that stage's ROUTER, and a
     * router shares the stage with the gate it reads. Ranking any `running`
     * above `coresDone` therefore flipped the stage completed -> running ->
     * completed on every gate answer, and the boat visibly bounced back a
     * column and forward again. It had done so since the strip shipped; only
     * adding a row-back announcement made anyone look.
     *
     * A deterministic router firing on the way OUT of a stage is forward
     * progress, not a return to it - the same judgement `WorkflowNode.vue`
     * already makes when it draws routers as plumbing rather than as a stage.
     * So once the cores are done, only a declared revise node re-opens the
     * stage, which is exactly the case that IS a return.
     */
    const reopeners = coresDone ? (stage.reviseIds ?? []) : stage.nodeIds
    const running = reopeners.some((id) => (nodeStates[id] ?? 'idle') === 'running')

    let state: StageState = 'idle'
    if (coresDone) state = 'completed'
    if (running) state = 'running'
    if (states.includes('waiting')) state = 'waiting'
    if (states.includes('error')) state = 'error'

    // Two shapes of loop reach this stage and both must count.
    //
    // A revise node re-runs the stage's work from a sibling node, so its own
    // visit count IS the number of extra passes (`scope_idea` runs once; every
    // later pass is `revise_scope`). But an upstream revise re-enters this
    // stage through its core nodes instead - approve after a scope revision and
    // all three research branches run a second time - so the cores carry the
    // lap themselves. Taking both and combining is what makes one formula
    // cover the fan-out and the two revise nodes alike.
    const coreLaps = maxVisits(stage.coreIds, visits)
    const reviseLaps = maxVisits(stage.reviseIds ?? [], visits)
    const entered = coreLaps > 0 || reviseLaps > 0 || state !== 'idle'
    const lap = entered ? Math.max(coreLaps, 1) + reviseLaps : 0

    const branches: BranchProgress[] = stage.coreIds.map((id, index) => ({
      id,
      label: stage.branchLabels?.[index] ?? id,
      state: nodeStates[id] ?? 'idle',
    }))

    return { stage, state, done, total: stage.coreIds.length, lap, branches }
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

/**
 * The server's own plan, as stages this strip can row.
 *
 * `CREW_STAGES` above describes the validator specifically, and
 * `assertStageCoverage` is what stops it narrating a graph it does not know -
 * correctly, because there is no sequence there it understands. The cost was
 * that a published builder graph got NO strip at all: `CrewProgress` hides
 * itself when coverage fails, so the one surface answering "how far along is
 * this" was absent from every graph anybody drew.
 *
 * The server already knows the answer. `builder_runner._emit_plan` emits one
 * C6 `stage` frame per topological layer, all at kickoff, so the lane can be
 * painted before the first node runs rather than discovered a node at a time.
 * This turns those frames into the shape the strip already renders.
 *
 * THREE JUDGEMENTS, each of which the frame does not make for us:
 *
 * - Every node in a layer is a CORE node. A layer is by construction the set
 *   of nodes that can run at once, so the stage is done when all of them are,
 *   and there is no equivalent of the validator's revise nodes - a builder
 *   graph's loop closes through a router, which is a node in a layer like any
 *   other.
 * - A layer with more than one node is PARALLEL, which is what gives it per-
 *   branch pips. That is the same judgement `CREW_STAGES` makes by hand about
 *   the three research branches, made here from the topology instead.
 * - The label the frame carries is every node's label joined with commas,
 *   which is right for a log line and far too long for a chip with about eight
 *   characters of room. The chip takes the first; the rest become the branch
 *   names, so nothing is lost and the pips are named rather than numbered.
 */
export function stagesFromFrames(
  frames: readonly { index: number; label: string; nodeIds: string[]; of?: number }[],
): CrewStage[] {
  return [...frames]
    .sort((left, right) => left.index - right.index)
    .filter((frame) => frame.nodeIds.length > 0)
    .map((frame) => {
      const parts = frame.label
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
      const labels = parts.length === frame.nodeIds.length ? parts : frame.nodeIds
      return {
        id: `stage-${frame.index}`,
        label: labels[0] ?? `Stage ${frame.index}`,
        nodeIds: [...frame.nodeIds],
        coreIds: [...frame.nodeIds],
        kind: 'work' as StageKind,
        parallel: frame.nodeIds.length > 1,
        branchLabels: frame.nodeIds.length > 1 ? labels : undefined,
      }
    })
}
