import { computed, ref, type Ref } from 'vue'
import type { FrameData, NodeRunState, RunStatus } from '../types/studio'

/**
 * The run console's choreography: who is speaking, what walked which edge, what
 * phase the run is in, and how much of the canvas is allowed to move at once.
 *
 * This is a STORE that frames are pushed into, not a reader of the run.
 * `11-run-visualizer.md`'s Interfaces section declares
 * `useRunChoreography(run: ValidatorRun)`, and taking the run would mean
 * exposing a frame stream off `useValidatorRun` for this one consumer to
 * subscribe to - a second path through the same frames, with its own ordering
 * and its own replay semantics. There is exactly one place a frame is applied
 * (`useValidatorRun.applyFrame`) and that property is worth more than the
 * signature: `ingest` is called from there and nowhere else. The departure is
 * recorded in the plan's Status.
 *
 * It owns no timers of its own except the reveal's `requestAnimationFrame`, and
 * even that is separable: `advanceReveal(now)` is a pure step, so a spec can
 * drive the reveal at exact millisecond boundaries instead of racing a frame
 * callback. Fake timers hang a component mount in this suite (MISSION.md §9.9),
 * which is the practical reason the step is injectable rather than merely the
 * tidy one.
 */

/** The twelve entries of the character palette in `motion.css`. */
export const CHARACTER_COUNT = 12

/**
 * Characters per second a text with no stream behind it is revealed at.
 *
 * The number is a bound on how far the rail can lag the canvas, not a taste
 * decision: `MAX_UTTERANCE_CHARS` is 4,096, so the slowest possible entry
 * finishes in 34 seconds. Faster and the reveal stops reading as speech;
 * slower and a long answer is still arriving when the next node starts.
 */
export const REVEAL_CHARS_PER_SECOND = 120

/**
 * How many pending entries force a catch-up dump.
 *
 * Beyond this the rail is narrating a part of the run the canvas has left, and
 * a transcript that is three speakers behind is a transcript nobody trusts. At
 * the cap every pending entry except the newest is completed instantly, so the
 * rail is never more than two speakers behind.
 */
export const MAX_PENDING_REVEALS = 2

/** Entries older than the last this many collapse to a one-line header. */
export const EXPANDED_ENTRIES = 3

/** Characters of an entry's text shown while it is collapsed. */
export const COLLAPSED_PREVIEW_CHARS = 80

/**
 * How long a token takes to walk its edge, from the reference verbatim
 * (`LaunchView.vue:2044-2075`): `clamp(pathLength x 0.02, 2000, 4000)` ms.
 * The composable holds the bounds; `HandoffToken.vue` measures the path,
 * because only the DOM knows how long a bezier turned out to be.
 */
export const HANDOFF_MIN_MS = 2000
export const HANDOFF_MAX_MS = 4000

/** Milliseconds per pixel of path. */
export const HANDOFF_MS_PER_PX = 0.02

export function handoffDurationMs(pathLength: number): number {
  const scaled = Number.isFinite(pathLength) ? pathLength * HANDOFF_MS_PER_PX : HANDOFF_MIN_MS
  return Math.min(HANDOFF_MAX_MS, Math.max(HANDOFF_MIN_MS, scaled))
}

/**
 * Which of the twelve character colours this node wears. 1-based, to match the
 * `--character-1 … --character-12` custom properties it names.
 *
 * FNV-1a over the id, and the choice of hash matters less than the two
 * properties it buys: it is PURE, so the medallion on the card, the avatar in
 * the rail and the walking token cannot disagree; and it is stateless, so a
 * page reload mid-run does not repaint the cast. The reference assigns
 * characters randomly without replacement and its chat avatars never match its
 * graph, which is the defect this replaces rather than copies.
 *
 * Collisions are expected and are not a defect: twelve colours over sixteen
 * nodes must collide, and the alternative - assignment by position - would give
 * the same agent a different colour in two graphs.
 */
export function characterIndex(nodeId: string): number {
  let hash = 0x811c9dc5
  for (let index = 0; index < nodeId.length; index += 1) {
    hash ^= nodeId.charCodeAt(index)
    // `Math.imul` is the only 32-bit multiply in JavaScript; `*` would promote
    // to a double past 2^53 and the low bits - the ones a hash lives on -
    // would stop being exact.
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return (hash % CHARACTER_COUNT) + 1
}

/** The CSS custom property carrying that character's colour. */
export function characterVar(nodeId: string): string {
  return `var(--character-${characterIndex(nodeId)})`
}

/** One token walking one edge. */
export interface Handoff {
  /** Descriptor edge id, or `${from}-${to}` when the graph draws no such edge. */
  edgeId: string
  from: string
  to: string
  startedAt: number
}

/** One thing an agent said. */
export interface DialogueEntry {
  callId: string
  nodeId: string
  /** The agent's role, or the node's label when no agent frame named one. */
  role: string
  /** The task it was working, or '' when nothing said. */
  task: string
  text: string
  /** How many characters of `text` are on screen. Climbs; never falls. */
  revealed: number
  truncated: boolean
  tokens: { prompt: number; completion: number }
  at: number
  /** True once three newer entries exist. Collapsed entries render a header. */
  collapsed: boolean
}

/** One phase of the run, as the server planned it (C6 `stage`). */
export interface RunStage {
  index: number
  of: number
  label: string
  nodeIds: string[]
}

export interface RunChoreographyOptions {
  /** Live node states, so the recede and the animation bound read one source. */
  nodeStates: Ref<Record<string, NodeRunState>> | (() => Record<string, NodeRunState>)
  /** The run's status. The recede lifts when this goes terminal. */
  status: Ref<RunStatus> | (() => RunStatus)
  /** Edge ids currently marching, for the animation bound. */
  activeEdgeIds?: Ref<Set<string>> | (() => Set<string>)
  /** Node id -> label, for a dialogue entry whose frame named no role. */
  labelFor?: (nodeId: string) => string
  /** Resolve a descriptor edge id from a node pair. Falls back to `from-to`. */
  edgeIdFor?: (from: string, to: string) => string
  /** Injectable clock, so a spec can place events at exact milliseconds. */
  now?: () => number
}

const TERMINAL: readonly RunStatus[] = ['completed', 'cancelled', 'error']
const LIVE: readonly RunStatus[] = ['queued', 'running', 'waiting', 'stopping']

function read<T>(source: Ref<T> | (() => T)): T {
  return typeof source === 'function' ? source() : source.value
}

function detailString(details: Record<string, unknown>, key: string): string {
  const value = details[key]
  return typeof value === 'string' ? value : ''
}

function detailNumber(details: Record<string, unknown>, key: string): number {
  const value = details[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

export function useRunChoreography(options: RunChoreographyOptions) {
  const now = options.now ?? (() => Date.now())
  const labelFor = options.labelFor ?? ((nodeId: string) => nodeId)
  const edgeIdFor = options.edgeIdFor ?? ((from: string, to: string) => `${from}-${to}`)

  const handoffs = ref<Handoff[]>([])
  const dialogue = ref<DialogueEntry[]>([])
  const stages = ref<RunStage[]>([])
  /** Node id -> the last error message the run reported for it. */
  const nodeErrors = ref<Record<string, string>>({})
  /** Node ids whose output was REPLAYED rather than run (10 D5). */
  const replayed = ref(new Set<string>())
  /** The Launch control's glow: on from the press until the first frame. */
  const armed = ref(false)
  /** How many frames have been applied to this run - the reconnect strip's N. */
  const framesApplied = ref(0)
  /** True from the first frame, so the cards land once and only once. */
  const landed = ref(false)

  /**
   * Roles and tasks seen on this node's `agent` frames.
   *
   * The `utterance` frame carries neither, and it deliberately should not: the
   * real serializer writes seven keys at `stage="utterance"` and none of them
   * is a role, so a client keying on one would be reading a field production
   * never sends. CrewAI's own agent lifecycle events do carry it, and this is
   * where they are kept. A node whose agent frames never arrived falls back to
   * its label on the canvas, which is the honest second-best.
   */
  const speakers = new Map<string, { role: string; task: string }>()
  /** Text accumulated per call id from `chunk` frames before its utterance. */
  const streamed = new Map<string, string>()

  let revealHandle = 0
  /** The clock at the last reveal step, or null before the first one.
   *
   * NULL and not 0: a spec drives this from an injected clock and 0 is a
   * perfectly ordinary timestamp there, so a zero sentinel silently swallowed
   * the first step and the reveal never moved. */
  let revealLast: number | null = null

  const isLive = computed(() => LIVE.includes(read(options.status)))
  const isTerminal = computed(() => TERMINAL.includes(read(options.status)))

  /**
   * Whether this card steps back. D2.
   *
   * Only while a run is LIVE, so a finished canvas is a settled record rather
   * than fifteen dimmed cards under a completed badge. An errored card is
   * excluded here rather than in CSS, because "never recede and never glow" is
   * one decision about what an error means and splitting it across two files is
   * how half of it gets changed.
   */
  function isReceded(nodeId: string): boolean {
    if (!isLive.value) return false
    const state = read(options.nodeStates)[nodeId] ?? 'idle'
    return state !== 'running' && state !== 'waiting' && state !== 'error'
  }

  /** Entries still revealing. At most one is genuinely animating; see D5.3. */
  const pending = computed(() =>
    dialogue.value.filter((entry) => entry.revealed < entry.text.length),
  )

  /**
   * How many things on the canvas are moving right now. D7's measurable bound.
   *
   * The reading is stated because the plan's table lists seven surfaces and two
   * of them - the node glow and that node's elapsed clock - are the same card
   * moving for the same reason; counting both would double every running node
   * and turn a bound into arithmetic about presentation. So a running card
   * counts ONCE, and the four independent sources are: running cards, marching
   * edges, tokens in flight, and one reveal. The launch glow is the fifth and
   * is mutually exclusive with all of them - it is off by the first frame.
   */
  const liveAnimationCount = computed(() => {
    if (isTerminal.value) return 0
    const states = read(options.nodeStates)
    const moving = Object.values(states).filter(
      (state) => state === 'running' || state === 'waiting',
    ).length
    const edges = options.activeEdgeIds ? read(options.activeEdgeIds).size : 0
    return moving + edges + handoffs.value.length + (pending.value.length ? 1 : 0) + (armed.value ? 1 : 0)
  })

  /** Called by `launch()`. The glow burns until the run's first frame lands. */
  function arm(): void {
    armed.value = true
    landed.value = false
  }

  function reset(): void {
    stopReveal()
    handoffs.value = []
    dialogue.value = []
    stages.value = []
    nodeErrors.value = {}
    replayed.value = new Set()
    speakers.clear()
    streamed.clear()
    armed.value = false
    landed.value = false
    framesApplied.value = 0
  }

  /**
   * One frame in. Called from `useValidatorRun.applyFrame` and nowhere else.
   *
   * Every branch below is additive: a frame this function does not recognise
   * changes nothing, which is what lets a server one version ahead stream to an
   * older console without the canvas going wrong.
   */
  function ingest(frame: FrameData): void {
    framesApplied.value += 1
    armed.value = false
    landed.value = true

    const details = frame.details ?? {}
    const stage = detailString(details, 'stage')

    if (frame.kind === 'edge_taken' && stage === 'traversal') {
      pushHandoff(detailString(details, 'from'), detailString(details, 'to'))
      return
    }
    if (frame.kind === 'run_state' && stage === 'plan') {
      pushStage(details)
      return
    }
    if (frame.kind === 'llm' && stage === 'chunk') {
      pushChunk(details)
      return
    }
    if (frame.kind === 'llm' && stage === 'utterance') {
      pushUtterance(frame, details)
      return
    }
    if (frame.kind === 'agent' && frame.node_id) {
      rememberSpeaker(frame, details)
      return
    }
    if (frame.kind === 'error' && frame.node_id && stage === 'error') {
      nodeErrors.value = {
        ...nodeErrors.value,
        [frame.node_id]: detailString(details, 'message') || frame.message,
      }
      return
    }
    if (frame.kind === 'node_state' && frame.node_id && details.replayed === true) {
      const next = new Set(replayed.value)
      next.add(frame.node_id)
      replayed.value = next
    }
  }

  /**
   * D3's concurrency bound, applied where the token is created rather than
   * where it is drawn: at most ONE token per edge. A second traversal of an
   * edge whose token is still walking completes the first instantly, which is
   * what stops a tight revise loop stacking four tokens on one bezier.
   */
  function pushHandoff(from: string, to: string): void {
    if (!from || !to) return
    const edgeId = edgeIdFor(from, to)
    handoffs.value = [
      ...handoffs.value.filter((entry) => entry.edgeId !== edgeId),
      { edgeId, from, to, startedAt: now() },
    ]
  }

  /** The token arrived (or was cancelled). Called by `HandoffToken.vue`. */
  function endHandoff(edgeId: string): void {
    handoffs.value = handoffs.value.filter((entry) => entry.edgeId !== edgeId)
  }

  function pushStage(details: Record<string, unknown>): void {
    const nodeIds = Array.isArray(details.node_ids)
      ? details.node_ids.filter((id): id is string => typeof id === 'string')
      : []
    if (!nodeIds.length) return
    const index = detailNumber(details, 'index')
    const next = stages.value.filter((entry) => entry.index !== index)
    next.push({
      index,
      of: detailNumber(details, 'of') || index,
      label: detailString(details, 'label') || `Stage ${index}`,
      nodeIds,
    })
    stages.value = next.sort((left, right) => left.index - right.index)
  }

  /**
   * D5.1. Chunks are no longer dropped.
   *
   * `useValidatorRun` discarded every `stage === 'chunk'` frame outright, which
   * meant the one surface that shows a model actually producing text could not
   * exist. They accumulate per call id, and the utterance that closes the call
   * takes what was streamed as text already on screen - so a streamed answer
   * needs no artificial reveal at all and the rail matches the wire.
   */
  function pushChunk(details: Record<string, unknown>): void {
    const callId = detailString(details, 'call_id')
    if (!callId) return
    const chunk = detailString(details, 'chunk')
    streamed.set(callId, (streamed.get(callId) ?? '') + chunk)
    const index = dialogue.value.findIndex((entry) => entry.callId === callId)
    if (index < 0) return
    const entry = dialogue.value[index]
    const text = streamed.get(callId) ?? ''
    dialogue.value = replaceAt(dialogue.value, index, {
      ...entry,
      text,
      revealed: text.length,
    })
  }

  function pushUtterance(frame: FrameData, details: Record<string, unknown>): void {
    const nodeId = frame.node_id ?? ''
    const callId = detailString(details, 'call_id') || `${frame.run_id}:${frame.seq}`
    const text = detailString(details, 'text')
    if (!text) return
    const speaker = speakers.get(nodeId)
    // Whatever streamed is ALREADY on screen; only the remainder is revealed.
    // Without this a streamed call would replay itself from zero the moment it
    // completed, which is the one thing a reader would read as a bug.
    const already = (streamed.get(callId) ?? '').length
    streamed.delete(callId)
    const entry: DialogueEntry = {
      callId,
      nodeId,
      role: speaker?.role || labelFor(nodeId) || nodeId,
      task: speaker?.task ?? '',
      text,
      revealed: Math.min(already, text.length),
      truncated: details.truncated === true,
      tokens: {
        prompt: detailNumber(details, 'prompt_tokens'),
        completion: detailNumber(details, 'completion_tokens'),
      },
      at: Number.isNaN(Date.parse(frame.ts)) ? now() : Date.parse(frame.ts),
      collapsed: false,
    }
    const existing = dialogue.value.findIndex((candidate) => candidate.callId === callId)
    dialogue.value =
      existing >= 0
        ? replaceAt(dialogue.value, existing, { ...dialogue.value[existing], ...entry })
        : [...dialogue.value, entry]
    catchUp()
    recollapse()
    startReveal()
  }

  function rememberSpeaker(frame: FrameData, details: Record<string, unknown>): void {
    const nodeId = frame.node_id ?? ''
    if (!nodeId) return
    // The serializer writes `f"{role} started"` / `f"{role} completed"`, so the
    // role is the message minus its verb. Read from the message because that is
    // where it is: `details` carries the TASK and never the role.
    const role = frame.message.replace(/\s+(started|completed|failed)$/i, '').trim()
    const task = detailString(details, 'task')
    const previous = speakers.get(nodeId)
    speakers.set(nodeId, {
      role: role || previous?.role || '',
      task: task || previous?.task || '',
    })
  }

  /**
   * D5.3. More than two pending entries and every one but the newest is dumped
   * whole.
   *
   * The alternative - revealing them all at once - is what a naive rail does,
   * and it is worse than either extreme: three simultaneous 120 char/s reveals
   * are three sentences arriving letter by letter in parallel, which is not
   * legible and is not faster.
   */
  function catchUp(): void {
    const stillRevealing = dialogue.value.filter((entry) => entry.revealed < entry.text.length)
    if (stillRevealing.length <= MAX_PENDING_REVEALS) return
    const newest = stillRevealing[stillRevealing.length - 1]
    dialogue.value = dialogue.value.map((entry) =>
      entry.revealed < entry.text.length && entry.callId !== newest.callId
        ? { ...entry, revealed: entry.text.length }
        : entry,
    )
  }

  /** D5.4. Everything but the last three entries collapses to a header. */
  function recollapse(): void {
    const cutoff = dialogue.value.length - EXPANDED_ENTRIES
    dialogue.value = dialogue.value.map((entry, index) => ({
      ...entry,
      collapsed: index < cutoff,
    }))
  }

  /**
   * D5.2. One step of the reveal, at exactly `REVEAL_CHARS_PER_SECOND`.
   *
   * Exposed and pure-ish so a spec can drive it at chosen millisecond
   * boundaries; the browser drives it from `requestAnimationFrame`. Returns
   * whether anything is still revealing, which is what stops the loop.
   */
  function advanceReveal(at: number): boolean {
    const elapsed = revealLast === null ? 0 : Math.max(0, at - revealLast)
    revealLast = at
    const grow = (elapsed / 1000) * REVEAL_CHARS_PER_SECOND
    let moving = false
    dialogue.value = dialogue.value.map((entry) => {
      if (entry.revealed >= entry.text.length) return entry
      const revealed = Math.min(entry.text.length, entry.revealed + grow)
      if (revealed < entry.text.length) moving = true
      return { ...entry, revealed }
    })
    return moving
  }

  function startReveal(): void {
    if (revealHandle) return
    if (typeof requestAnimationFrame !== 'function') return
    revealLast = null
    const step = (at: number) => {
      revealHandle = 0
      if (advanceReveal(at)) startReveal()
    }
    revealHandle = requestAnimationFrame(step)
  }

  function stopReveal(): void {
    if (revealHandle && typeof cancelAnimationFrame === 'function') {
      cancelAnimationFrame(revealHandle)
    }
    revealHandle = 0
    revealLast = null
  }

  /**
   * Reduced motion, and the terminal frame, both want the same thing: whatever
   * is half-revealed, shown whole. Called by the view on the terminal status
   * and by `DialogueRail` when the media query says reduce.
   */
  function revealAll(): void {
    stopReveal()
    dialogue.value = dialogue.value.map((entry) =>
      entry.revealed >= entry.text.length ? entry : { ...entry, revealed: entry.text.length },
    )
  }

  return {
    handoffs,
    dialogue,
    stages,
    nodeErrors,
    replayed,
    armed,
    landed,
    framesApplied,
    pending,
    liveAnimationCount,
    isReceded,
    characterIndex,
    characterVar,
    arm,
    ingest,
    endHandoff,
    advanceReveal,
    revealAll,
    reset,
  }
}

export type RunChoreography = ReturnType<typeof useRunChoreography>

function replaceAt<T>(list: T[], index: number, value: T): T[] {
  const next = list.slice()
  next[index] = value
  return next
}

/** What a collapsed entry shows: the opening of what was said, and no more. */
export function collapsedPreview(text: string): string {
  const trimmed = text.trim().replace(/\s+/g, ' ')
  return trimmed.length <= COLLAPSED_PREVIEW_CHARS
    ? trimmed
    : `${trimmed.slice(0, COLLAPSED_PREVIEW_CHARS).trimEnd()}…`
}
