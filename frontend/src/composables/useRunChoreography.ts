import { computed, ref, shallowRef, type Ref } from 'vue'
import { characterSeed, type PipState } from '../characters/pip'
import { humaniseErrorText } from '../trace/interpret'
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

/**
 * How long the target medallion carries its receipt class.
 *
 * Longer than the 120ms pulse it triggers, so the animation is never cut off,
 * and short enough that two arrivals a quarter second apart are two pulses.
 */
export const RECEIPT_MS = 200

/**
 * Milliseconds of NEGATIVE animation delay per node index, for the landing
 * settle (D6.2).
 *
 * Negative, which is the whole trick: a negative delay starts an animation
 * already part-way through, so a sixteen-node graph reads as already in motion
 * on the first paint rather than popping in one card at a time. It is the
 * reference's own landing-page technique (`HomeView.vue:11-22`, eighty cubes at
 * `-0…60s`) applied ONCE rather than forever - a canvas that staggered on every
 * repaint would be the ChatDev disco the spec rules out.
 */
export const LANDING_STAGGER_MS = 40

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

/**
 * Whether a declared `agent_role` reads as a ROLE somebody wrote or as an id.
 *
 * The descriptor's `agent_role` is rung two of the identity ladder, and for a
 * builder graph it has carried the node's own id (`n3_market`) rather than a
 * role. Seeding a character from that is not wrong-looking on its own - it is
 * wrong LATER, at the node's first `agent_role`-bearing frame, when the
 * character would change in front of the operator. So a value with neither a
 * space nor a capital in it is treated as an identifier and skipped, and the
 * ladder falls through to the node's label, which is prose either way.
 *
 * Deliberately generous rather than clever: `Scoper` passes on the capital and
 * `market research analyst` passes on the spaces. What it rejects is the one
 * shape ids actually take here - a lowercase snake or kebab token.
 */
export function readsAsRole(value: string | undefined): boolean {
  const trimmed = (value ?? '').trim()
  if (!trimmed) return false
  return /\s/.test(trimmed) || /[A-Z]/.test(trimmed)
}

/**
 * Who is standing on a node, and what they are doing - the pair every surface
 * that draws a character binds to.
 *
 * Declared HERE rather than on the card, and handed out as a CACHED object
 * rather than built at each call site, and the second half is a measured
 * decision. `<WorkflowNode :cast="...">` is a prop: a fresh object literal is
 * never `props`-equal, so building one in a template re-renders the card on
 * every frame no matter how carefully its `data` was memoised. Counted in a
 * mounted benchmark over 262 frames, that alone kept all fourteen cards
 * re-rendering - 2,912 renders - with the `data` fix already in place.
 */
export interface CastMark {
  identity: string
  state: PipState
}

/** One token walking one edge. */
export interface Handoff {
  /** Descriptor edge id, or `${from}-${to}` when the graph draws no such edge. */
  edgeId: string
  from: string
  to: string
  startedAt: number
  /**
   * The SOURCE node's identity seed, resolved at the moment the token was
   * created (T2.6).
   *
   * Stamped ON THE HANDOFF rather than looked up by the component, because the
   * token is rendered by `WorkflowEdge`, which knows about edges and nothing
   * about agents. Resolving it here is also what makes the token provably the
   * same character as the card it left: one call, one store, one answer -
   * rather than two call sites that agree today.
   */
  fromIdentity: string
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
  /**
   * Node id -> the role the SERVER declared on the graph descriptor
   * (`GraphNodeDefinition.agent_role`), rung two of the identity ladder.
   *
   * Optional, and a caller that does not supply it degrades to the label
   * rather than breaking - which is exactly what the synthetic path needs,
   * since a synthetic run emits no `agent` frame and the descriptor is the
   * only identity it has.
   */
  declaredRoleFor?: (nodeId: string) => string | undefined
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
  const declaredRoleFor = options.declaredRoleFor ?? (() => undefined)
  const edgeIdFor = options.edgeIdFor ?? ((from: string, to: string) => `${from}-${to}`)

  const handoffs = ref<Handoff[]>([])
  /**
   * What the agents said. `shallowRef`, not `ref` (T2.8).
   *
   * Every write in this file replaces the array - `replaceAt`, a spread, a
   * `map` - and never mutates an entry in place, which is the obligation a
   * shallow ref imposes and which the reveal already met for its own reasons.
   * What it buys is that an entry is a plain object rather than a proxy: the
   * rail reads eight properties off each one per render, and the reveal step
   * runs sixty times a second, so a deep ref was registering thousands of
   * dependencies a second for text that had finished arriving minutes ago.
   */
  const dialogue = shallowRef<DialogueEntry[]>([])
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
  /** Nodes a token has just arrived at, for the one-shot receipt pulse. */
  const receiving = ref(new Set<string>())
  const receiptTimers = new Map<string, ReturnType<typeof setTimeout>>()

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

  /* ------------------------------------------------------------ the cast */

  /**
   * Node id -> the FIRST `agent_role` any frame carried for it, ever.
   *
   * First and not latest, and that is the whole of the rule: a character that
   * changes halfway through a run is a different agent as far as the eye is
   * concerned, and the one thing the cast exists to do is let somebody follow
   * one worker across the canvas, the rail and the edges. CrewAI stamps
   * `agent_role` on the agent, task, tool and LLM events of a paid run and the
   * synthetic backend stamps it on `node_state`, so the first frame a node
   * produces usually carries it; a node that never gets one falls through the
   * ladder in `identityFor` and stays there for the run.
   *
   * Reactive rather than a plain Map, because the node card, both rails and
   * the walking token all read it and all of them re-render on frames.
   */
  const frameRoles = ref<Record<string, string>>({})

  /**
   * Node id -> the life the FRAMES say it is in.
   *
   * This mirrors `useValidatorRun.applyNodeState` / `applyGate` / the
   * `gate_closed` branch exactly - START is running, END is completed, an
   * ERROR-level `node_state` is error, a gate opening is waiting and a gate
   * closing is completed - and it exists because `castState` has to be
   * answerable over a bare frame log with no host wired up (T2.5's evidence is
   * a replay of two NDJSON fixtures). Where the host DOES supply
   * `options.nodeStates`, that answer wins: it is the same derivation over the
   * same frames, and one authority beats two agreeing ones.
   */
  const frameLife = ref<Record<string, NodeRunState>>({})

  /**
   * Nodes whose Pip is mid-sentence.
   *
   * EVENT-BOUNDED, not reveal-bounded. It opens on an `llm` `utterance` or
   * `chunk` frame and closes on the next frame for that node that is neither -
   * another model or tool call, an agent boundary, a guardrail, a node end.
   * Keying it on the rail's reveal instead would tie the canvas to a typing
   * animation, so a node that streamed 4,000 characters would still be
   * "speaking" thirty seconds after the model stopped.
   *
   * `token` and `metrics` frames do NOT close it: they are bookkeeping the
   * server emits beside a call, not the agent doing something else, and a
   * usage frame landing between an utterance and its agent boundary would
   * otherwise make every sentence flicker.
   */
  const speaking = ref(new Set<string>())

  /** Gate node id -> the node the last `edge_taken` into it came from. */
  const feeders = ref<Record<string, string>>({})

  /**
   * The last `{identity, state}` handed out per node, so an unchanged node is
   * handed the SAME object again and its card can be skipped.
   *
   * A plain Map and not a `computed`: this is asked for one node at a time
   * from a render function, and a per-node computed would be fourteen effects
   * to create, invalidate and garbage-collect for a value that is two strings.
   */
  const castMarks = new Map<string, CastMark>()

  /** The last node a START frame named, as the feeder of last resort. */
  const lastStarted = ref('')

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

  /**
   * WHO this node is, as one string, for everything that draws a character.
   *
   * The ladder is the run's own, most specific first:
   *
   *   1. the first `agent_role` a frame carried for this node in this run
   *   2. the descriptor's declared `agent_role`, when it reads as a role at
   *      all rather than as an id (`readsAsRole`)
   *   3. the node's label - prose somebody wrote, and the only identity a
   *      hand-drawn node has
   *   4. the node id, so this is total and never returns ''
   *
   * ONE store, deliberately. The node card, the dialogue rail, the trace rail
   * and the walking token every one of them ask this function, so a character
   * cannot be one creature on the canvas and another in the transcript - which
   * is the defect the reference product has and which T2.6 measures.
   */
  function identityFor(nodeId: string): string {
    if (!nodeId) return ''
    const stamped = frameRoles.value[nodeId]
    if (stamped) return stamped
    const declared = declaredRoleFor(nodeId)
    if (readsAsRole(declared)) return (declared as string).trim()
    return labelFor(nodeId) || nodeId
  }

  /** Every node the run has mentioned, mapped through `identityFor`. */
  const identities = computed<Record<string, string>>(() => {
    const seen = new Set<string>([
      ...Object.keys(frameRoles.value),
      ...Object.keys(frameLife.value),
      ...Object.keys(read(options.nodeStates)),
    ])
    const map: Record<string, string> = {}
    for (const nodeId of seen) map[nodeId] = identityFor(nodeId)
    return map
  })

  /** The seed a character is hashed from - `identityFor`, normalised. */
  function characterSeedFor(nodeId: string): string {
    return characterSeed(identityFor(nodeId))
  }

  /** What the host says this node's life is, or what the frames say. */
  function lifeOf(nodeId: string): NodeRunState {
    const hosted = read(options.nodeStates)[nodeId]
    if (hosted && hosted !== 'idle') return hosted
    return frameLife.value[nodeId] ?? 'idle'
  }

  /**
   * The node whose work a waiting gate is holding up.
   *
   * A gate node gets no character - a human is not an agent - so without this
   * the one moment the run is actually stopped has nothing on the canvas
   * wearing the blocked pose. The feeder is the `from` of the last traversal
   * INTO the gate, which is exactly the agent whose output is on the card the
   * operator is being asked about; a run replayed from frames that name no
   * such edge falls back to the last node that started, which on a linear
   * flow is the same node.
   */
  function feederOf(nodeId: string): string {
    const viaEdge = feeders.value[nodeId]
    if (viaEdge && viaEdge !== nodeId) return viaEdge
    return lastStarted.value && lastStarted.value !== nodeId ? lastStarted.value : ''
  }

  /**
   * One node's character state (T2.5), from run events and nothing else.
   *
   * NO CLOCK IS READ HERE and none may be: `evidence/T2/no-timers.txt` greps
   * this file for one. Every input is a frame that has already been applied,
   * so the same log replayed twice produces the same states in the same order
   * and a page reload mid-run puts the cast back exactly where it was.
   *
   * Precedence is worst-news-first, and each step is a decision:
   *   error   beats everything, because a failed node that also has a stale
   *           "speaking" flag must not read as chatting
   *   blocked beats done, because the feeder of an open gate really is stopped
   *           even though its own work finished - that is what the gate means
   *   done    beats speaking, which the event bound already closes at node end
   */
  function castState(nodeId: string): PipState {
    if (!nodeId) return 'idle'
    const life = lifeOf(nodeId)
    if (life === 'error' || nodeErrors.value[nodeId]) return 'blocked-error'
    if (life === 'waiting') return 'blocked'
    if (blockedFeeders.value.has(nodeId)) return 'blocked'
    if (life === 'completed') return 'done'
    if (life === 'running') return speaking.value.has(nodeId) ? 'speaking' : 'working'
    return 'idle'
  }

  /** Nodes that are blocked because a gate they fed is waiting on a human. */
  const blockedFeeders = computed(() => {
    const held = new Set<string>()
    // Every node EITHER source knows about, resolved through `lifeOf` one at a
    // time. A merge of the two records was the first draft and it was wrong in
    // a way worth recording: `nodeStates` seeds every descriptor node to
    // `idle`, so spreading it over the frame-derived map replaced a real
    // `waiting` with a placeholder and no gate ever blocked anybody.
    const nodeIds = new Set([
      ...Object.keys(frameLife.value),
      ...Object.keys(read(options.nodeStates)),
    ])
    for (const nodeId of nodeIds) {
      if (lifeOf(nodeId) !== 'waiting') continue
      const feeder = feederOf(nodeId)
      if (feeder) held.add(feeder)
    }
    return held
  })

  /**
   * One node's cast mark, stable while it says the same thing.
   *
   * The identity is read first and the state second, so a node that has
   * neither still gets an object rather than two lookups and a literal.
   */
  function castFor(nodeId: string): CastMark {
    const identity = identityFor(nodeId)
    const state = castState(nodeId)
    const cached = castMarks.get(nodeId)
    if (cached && cached.identity === identity && cached.state === state) return cached
    const mark: CastMark = { identity, state }
    castMarks.set(nodeId, mark)
    return mark
  }

  /** Node id -> `PipState`, for everything that binds `<AgentCharacter :state>`. */
  const castStates = computed<Record<string, PipState>>(() => {
    const seen = new Set<string>([
      ...Object.keys(frameLife.value),
      ...Object.keys(read(options.nodeStates)),
      ...Object.keys(nodeErrors.value),
      ...speaking.value,
    ])
    const map: Record<string, PipState> = {}
    for (const nodeId of seen) map[nodeId] = castState(nodeId)
    return map
  })

  /**
   * Nodes whose Pip is running an INFINITE loop right now.
   *
   * Only `working` (`pip-bob`) and `speaking` (`pip-speak`) loop;
   * `character.css` makes idle and done completely still and gives blocked a
   * one-shot settle rather than a pulse, so those cost nothing and are not
   * counted. Measured rather than assumed - see `liveAnimationCount`.
   */
  const loopingCharacters = computed(
    () => new Set(
      Object.entries(castStates.value)
        .filter(([, state]) => state === 'working' || state === 'speaking')
        .map(([nodeId]) => nodeId),
    ),
  )

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
    // A CARD and the character standing on it are ONE moving thing, for the
    // same reason the glow and the elapsed clock already were: they are the
    // same card moving for the same reason, and counting both would turn a
    // bound into arithmetic about presentation. So the character loops are
    // UNIONED with the running cards rather than added to them - which also
    // means a Pip on a card that is not itself animating (there is one: the
    // feeder of an open gate) does get counted, because that one really is a
    // new thing in motion. Measured on the fan-out fixture: the union adds
    // nothing there, because every looping Pip stands on a running card.
    const moving = new Set<string>()
    for (const [nodeId, state] of Object.entries(states)) {
      if (state === 'running' || state === 'waiting') moving.add(nodeId)
    }
    for (const nodeId of loopingCharacters.value) moving.add(nodeId)
    const edges = options.activeEdgeIds ? read(options.activeEdgeIds).size : 0
    return moving.size + edges + handoffs.value.length + (pending.value.length ? 1 : 0) + (armed.value ? 1 : 0)
  })

  /** Called by `launch()`. The glow burns until the run's first frame lands. */
  function arm(): void {
    armed.value = true
    landed.value = false
  }

  function reset(): void {
    stopReveal()
    for (const timer of receiptTimers.values()) clearTimeout(timer)
    receiptTimers.clear()
    receiving.value = new Set()
    handoffs.value = []
    dialogue.value = []
    stages.value = []
    nodeErrors.value = {}
    replayed.value = new Set()
    speakers.clear()
    streamed.clear()
    // The cast is per RUN. A relaunch is a new run with the same topology, and
    // a role remembered across it would pin the previous run's identity onto a
    // node whose author has since renamed it.
    frameRoles.value = {}
    frameLife.value = {}
    castMarks.clear()
    speaking.value = new Set()
    feeders.value = {}
    lastStarted.value = ''
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

    // The cast reads EVERY frame, before the branches below start returning
    // early: an identity, a life and a sentence boundary can each arrive on a
    // kind this function otherwise ignores (`agent_role` is on `node_state` in
    // a synthetic run and on `tool` frames in a paid one), and a store that
    // only saw the four kinds the dialogue needs would miss most of them.
    noteIdentity(frame, details)
    noteLife(frame, stage)
    noteSpeaking(frame, stage)

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
    // `agent` frames are entirely `noteIdentity`'s business now; the branch
    // that used to sit here only ever called `rememberSpeaker`.
    if (frame.kind === 'error' && frame.node_id && stage === 'error') {
      /*
       * HUMANISED HERE, at the one place a card's error text is written.
       *
       * T1.3 is "no raw internal code reaches the run shell's DOM", and a
       * verification capture caught the node card still reading
       * `SYNTHETIC_FAILURE: fm_cast_refusal …` while the trace row beside it
       * had already been cleaned up - the trace went through
       * `interpret.ts::errorSentence` and the card went through nothing.
       *
       * The write rather than the render, because `nodeErrors` has exactly one
       * writer and the card reads it three times: the visible sentence, the
       * `title` a hover gets and the aria label a screen reader hears. Cleaning
       * it at the render would have fixed one of the three and left a code in
       * the two nobody screenshots.
       *
       * `humaniseErrorText` and not `errorSentence`: the latter also cuts to
       * one sentence and clips to the TRACE's budget, and the card's own budget
       * is `MAX_NODE_CARD_ERROR_CHARS` with the full text promised to its
       * `title`. Same words, each surface's own length. The raw payload is
       * untouched in the trace row's disclosure.
       */
      nodeErrors.value = {
        ...nodeErrors.value,
        [frame.node_id]: humaniseErrorText(detailString(details, 'message') || frame.message),
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
    // Which agent this hop came FROM, remembered for the gate's blocked pose.
    // Written even when the target draws no token, because the fact wanted is
    // "who fed this node", not "who is walking an edge right now".
    feeders.value = { ...feeders.value, [to]: from }
    const edgeId = edgeIdFor(from, to)
    handoffs.value = [
      ...handoffs.value.filter((entry) => entry.edgeId !== edgeId),
      { edgeId, from, to, startedAt: now(), fromIdentity: identityFor(from) },
    ]
  }

  /**
   * The first `agent_role` this node ever showed, plus the task beside it.
   *
   * `details.agent_role` is the field, and it replaces the regex that used to
   * strip "started"/"completed" off the message. That regex was reading a
   * SENTENCE the serializer happens to compose (`f"{role} started"`), which is
   * copy rather than data - it breaks the moment the wording changes and it
   * cannot work at all for the frames that carry a role but no such message.
   * It is kept underneath for exactly one case: a log written before
   * `agent_role` was on the wire, where the sentence is genuinely all there is.
   */
  function noteIdentity(frame: FrameData, details: Record<string, unknown>): void {
    const nodeId = frame.node_id ?? ''
    if (!nodeId) return
    const stamped = detailString(details, 'agent_role').trim()
    const legacy =
      frame.kind === 'agent'
        ? frame.message.replace(/\s+(started|completed|failed)$/i, '').trim()
        : ''
    const role = stamped || legacy
    // FIRST wins. A character that changes mid-run is a different agent as far
    // as the eye is concerned, and following one worker is the whole point.
    if (role && !frameRoles.value[nodeId]) {
      frameRoles.value = { ...frameRoles.value, [nodeId]: role }
    }
    const task = detailString(details, 'task') || detailString(details, 'task_name')
    const previous = speakers.get(nodeId)
    if (role || task || previous) {
      speakers.set(nodeId, {
        role: previous?.role || role || '',
        task: task || previous?.task || '',
      })
    }
  }

  /**
   * The frame-derived life of a node - the same four rules
   * `useValidatorRun.applyNodeState` applies, in the same order.
   *
   * The ORDER is load-bearing and is copied rather than improved: an
   * ERROR-level `NODE_END` sets `completed` and then `error`, so the error is
   * what survives. A `tool` frame at ERROR level does NOT fail the node - only
   * a `node_state` frame does - which is why the kind is checked first.
   */
  function noteLife(frame: FrameData, stage: string): void {
    const nodeId = frame.node_id ?? ''
    if (!nodeId) return
    let next: NodeRunState | '' = ''
    if (frame.kind === 'node_state') {
      if (frame.event_type.includes('START')) next = 'running'
      if (frame.event_type.includes('END')) next = 'completed'
      if (frame.level === 'ERROR' || stage === 'error') next = 'error'
      if (frame.event_type.includes('START')) lastStarted.value = nodeId
    }
    // A gate is the one thing that puts a node into `waiting`: no member of
    // `UIEventType` contains the word, so it arrives as GATE_OPEN and nothing
    // else. `gate_closed` settles the same node, which is the missing half of
    // that pair rather than a new concept.
    if (frame.kind === 'gate_open') next = 'waiting'
    if (frame.kind === 'gate_closed') next = 'completed'
    if (!next) return
    frameLife.value = { ...frameLife.value, [nodeId]: next }
  }

  /** Opens on an utterance or a chunk; closes on the node's next other frame. */
  function noteSpeaking(frame: FrameData, stage: string): void {
    const nodeId = frame.node_id ?? ''
    if (!nodeId) return
    const opens = frame.kind === 'llm' && (stage === 'utterance' || stage === 'chunk')
    // Bookkeeping the server emits alongside a call, not the agent doing
    // something else. Closing on one would make every sentence flicker.
    const neutral = frame.kind === 'token' || frame.kind === 'metrics'
    if (opens) {
      if (speaking.value.has(nodeId)) return
      speaking.value = new Set(speaking.value).add(nodeId)
      return
    }
    if (neutral || !speaking.value.has(nodeId)) return
    const next = new Set(speaking.value)
    next.delete(nodeId)
    speaking.value = next
  }

  /**
   * The token arrived (or was cancelled). Called by `HandoffToken.vue`.
   *
   * Arrival is also when the TARGET's medallion pulses once, and that pulse is
   * latched for `RECEIPT_MS` rather than derived from the node's state. Two
   * reasons, and the second is the one that decides it: a node's state is a
   * proxy for arrival and proxies drift (this repository has the scar - the
   * crew strip's row-back announcement keyed on the boat's position and fired
   * on a run that never revised); and a CSS one-shot only fires when its class
   * is ADDED, so a flag that never cleared would animate the first handoff into
   * a node and silently ignore every later one.
   */
  function endHandoff(edgeId: string): void {
    const arriving = handoffs.value.find((entry) => entry.edgeId === edgeId)
    handoffs.value = handoffs.value.filter((entry) => entry.edgeId !== edgeId)
    if (!arriving) return
    const target = arriving.to
    receiving.value = new Set(receiving.value).add(target)
    const timer = receiptTimers.get(target)
    if (timer) clearTimeout(timer)
    receiptTimers.set(
      target,
      setTimeout(() => {
        receiptTimers.delete(target)
        const next = new Set(receiving.value)
        next.delete(target)
        receiving.value = next
      }, RECEIPT_MS),
    )
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
    let changed = false
    const next = dialogue.value.map((entry) => {
      if (entry.revealed >= entry.text.length) return entry
      const revealed = Math.min(entry.text.length, entry.revealed + grow)
      if (revealed < entry.text.length) moving = true
      if (revealed === entry.revealed) return entry
      changed = true
      return { ...entry, revealed }
    })
    // The ARRAY is replaced only when an entry actually moved (T2.8). This runs
    // from `requestAnimationFrame`, so a step that reassigns regardless -
    // which the first version did - invalidates every consumer sixty times a
    // second for a rail in which nothing changed. It happens: `grow` is
    // fractional, and two steps a quarter of a millisecond apart can leave a
    // reveal on the same character.
    if (changed) dialogue.value = next
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
    receiving,
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
    identities,
    identityFor,
    characterSeedFor,
    castStates,
    castState,
    castFor,
    loopingCharacters,
    speaking,
    frameRoles,
    frameLife,
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
