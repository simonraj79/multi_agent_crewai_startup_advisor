import { computed, ref, shallowRef, watch } from 'vue'
import type { InjectionKey, Ref } from 'vue'
import type { Edge, Node, NodeDragEvent, XYPosition } from '@vue-flow/core'
import { newNode } from '../data/builderDefaults'
import { NODE_KINDS, outPortsOf } from '../data/nodeKinds'
import { ancestorsOf, backEdges, topoOrder } from '../utils/builderGraph'
import type {
  BuilderDocument,
  BuilderEdge,
  BuilderNode,
  BuilderProblem,
  EdgeId,
  NodeId,
  NodeKind,
  NodePosition,
  Severity,
  TargetPort,
} from '../types/builder'

/**
 * The projection of a builder document onto a Vue Flow canvas, and the whole of
 * the canvas's own state.
 *
 * The division of labour is ruling R2 and it is not negotiable: dragging,
 * marquee, pan, zoom, snapping and hit-testing are Vue Flow's, and this file
 * contains no pointer-position arithmetic for any of them. What it owns is
 * everything Vue Flow has no opinion about - which document a node came from,
 * what a port means, which connections are representationally impossible, and
 * the single commit each finished gesture becomes.
 *
 * THE ONE-WAY LOOP (§1.1). `commit()` on the document store is the only write
 * path, and every function here that changes the graph ends in exactly one call
 * to one of the store's mutators. Positions come back through
 * `@node-drag-stop`, never through `@nodes-change`: a per-frame commit would
 * spend the whole 200-entry undo ring on one drag of one node, which is
 * invariant 4 stated as a consequence rather than as a rule.
 *
 * NOTHING HERE COMPUTES A PROBLEM (invariant 3, R6). `isValidConnection`
 * refuses exactly the *parse* refusals of §6.1 - the shapes that come back as a
 * 422 rather than as a Problem, and so must never be sent. Fan-out width, cycle
 * count, back-edge legality and every other `bounds.py` count is the server's,
 * is rendered rather than enforced, and is permitted at the mouse on purpose: a
 * client-side bound is a second opinion that silently disagrees with the
 * compiler the first time either side moves.
 */

/**
 * `<Background :gap="20">` and `:snap-grid="[20,20]"` are the same number
 * (R12), which is what makes a dropped node land on a dot the author can see
 * rather than near one.
 */
export const GRID = 20

/**
 * How far the pointer may travel between `pointerdown` and `click` and still
 * count as a click for the purpose of collapsing a multi-selection (§4.3).
 *
 * Vue Flow already gets the harder half right: `handleNodeClick`
 * (`vue-flow-core.mjs`) leaves an already-selected node's selection alone, so
 * grabbing one member of a group drags the whole group. What it never does is
 * collapse - click one member of a three-node selection with no modifier and
 * you still have three selected, with no way back to one except clicking empty
 * pane first. Three pixels is the tremor in a real click; a plain `click`
 * listener with no travel test would collapse the selection at the END of every
 * group drag instead, which arrives as the same event on the same node.
 */
export const COLLAPSE_TRAVEL_PX = 3

/**
 * The card's size before Vue Flow has measured it, and only until then.
 *
 * `NODE_W` is 240 by §5.2 and the height is one card's worth of that section's
 * vertical rhythm. Every consumer prefers the measured `dimensions` and falls
 * back to this, so the pair is load-bearing for exactly one frame per node -
 * without it the minimap draws a graph of zero-area rectangles on first paint,
 * which reads as an empty document.
 */
export const DEFAULT_NODE_WIDTH = 240
export const DEFAULT_NODE_HEIGHT = 96

/**
 * The `dataTransfer` type a palette tile writes and the canvas reads.
 *
 * A custom MIME rather than bare `text/plain`, so a drag of selected text from
 * anywhere else in the page cannot land on the canvas and mint a node from
 * whatever word happened to be under the pointer. `NodePalette` sets both this
 * and `text/plain`, because Firefox refuses a drag whose `dataTransfer` carries
 * no type it recognises; the canvas prefers this one and falls back.
 */
export const BUILDER_DND_MIME = 'application/x-builder-kind'

/**
 * The attribute `BuilderCanvas` stamps on itself, and the whole of the
 * canvas-focus test.
 *
 * `Tab` is repurposed for topological traversal, which is legitimate inside
 * `role="application"` and a WCAG 2.1.1 failure anywhere else. An attribute plus
 * `closest()` answers "is focus inside the canvas" without a template ref
 * threaded through two components, and it stays correct when Vue Flow moves
 * focus onto a node element that this file never sees.
 */
export const BUILDER_CANVAS_ATTR = 'data-builder-canvas'

/** True while the focused element is the canvas or lives inside it. */
export function canvasHasFocus(): boolean {
  const active = typeof document === 'undefined' ? null : document.activeElement
  return active instanceof Element && active.closest(`[${BUILDER_CANVAS_ATTR}]`) !== null
}

/**
 * The six align modes and the two distribute axes of §4.3, in toolbar order.
 *
 * Exported so `SelectionToolbar.vue` renders the list rather than restating it -
 * the same rule the shortcut sheet obeys about its binding table. A seventh
 * mode added here appears in the toolbar with no second edit.
 */
export const ALIGN_MODES = ['left', 'centerX', 'right', 'top', 'centerY', 'bottom'] as const
export type AlignMode = (typeof ALIGN_MODES)[number]
export const DISTRIBUTE_AXES = ['horizontal', 'vertical'] as const
export type DistributeAxis = (typeof DISTRIBUTE_AXES)[number]

/** The kinds that may legally close a loop, per `bounds.py`'s `back-edge-not-router`. */
const LOOP_CLOSING_KINDS: ReadonlySet<NodeKind> = new Set<NodeKind>(['gate', 'router'])

/**
 * Which target ports each kind offers, in the order the card draws them.
 *
 * `document.py:TARGET_PORTS` is the set of THREE strings an edge may arrive at;
 * what it does not yet say is which kind offers which, because `/vocabulary`
 * does not serve `target_ports` until C2 v2 lands (02-canvas.md Interfaces).
 * So this is a client-side mirror of a server table that does not exist yet,
 * and it is written here - beside `isValidConnection`, the one function that
 * consumes it - rather than in `nodeKinds.ts`, which is plan 03's and whose
 * mirror `nodeKinds.spec.ts` proves against the Python at run time. Putting an
 * unprovable table in the provable file is how a mirror stops being a mirror.
 *
 * The three rows are not arbitrary and each one is `document.py`'s own sentence
 * read from the other end:
 *
 *   `in`      - every kind whose `accepts_incoming` is true. The flow itself.
 *   `attach`  - `agent` and `crew`, the two kinds that can HAVE a possession.
 *   `member`  - `crew` alone, because membership is of a crew.
 *
 * REPORT rather than invent when this moves: the moment `vocabulary` carries
 * `target_ports`, this constant should be deleted and read from there, and the
 * test that guards it should read the Python the way `nodeKinds.spec.ts` does.
 */
const TARGET_PORTS_BY_KIND: Readonly<Record<NodeKind, readonly TargetPort[]>> = {
  input: [],
  agent: ['in', 'attach'],
  crew: ['in', 'attach', 'member'],
  gate: ['in'],
  router: ['in'],
  transform: ['in'],
  output: ['in'],
  tool: [],
  mcp: [],
  skill: [],
}

/** The target ports a kind draws, and the ones `isValidConnection` will accept. */
export function targetPortsOf(kind: NodeKind): readonly TargetPort[] {
  return TARGET_PORTS_BY_KIND[kind]
}

/** The four ways an edge can be drawn, and the only four (02-canvas.md D4). */
export type EdgeClass = 'flow' | 'attach' | 'member' | 'error'

/**
 * Which class an edge is, from the edge's own two port fields and nothing else.
 *
 * THE RULE, and it is the reason this is four lines rather than a lookup: an
 * edge's class is decided by strings the EDGE carries, never by what kind the
 * source node happened to be. `bounds.py` decides the same question from the
 * same two fields, so there is one string for the two sides to agree about
 * instead of a table of ten kinds each side maintains separately - which is
 * exactly the shape of drift `nodeKinds.ts`'s docblock is written against.
 *
 * `target_port` answers three of the four. The fourth, `error`, is the one
 * departure from "`target_port` alone" that `types/builder.ts` states, and
 * D4's own table marks it as such: an error exit arrives at an ordinary `in`
 * port and what makes it different is that it LEFT by `error`. That is still a
 * field of the edge, so the rule the settled contract is protecting - do not
 * look at the source node - holds exactly. Assumption recorded in the plan's
 * Status.
 */
export function edgeClassOf(edge: { source_port: string; target_port: TargetPort }): EdgeClass {
  if (edge.target_port === 'attach') return 'attach'
  if (edge.target_port === 'member') return 'member'
  if (edge.source_port === 'error') return 'error'
  return 'flow'
}

/* --- what the canvas needs from the packages either side of it ------------ */

/**
 * A `.value` and nothing more.
 *
 * Declared this shape rather than as `Ref<T>` because the canvas does not care
 * whether the document arrives as a `ref`, a `shallowRef`, a `computed` or a
 * `readonly` wrapper, and each of those is a different type a plain `Ref<T>`
 * parameter would refuse. Reading `.value` on the real ref still tracks:
 * tracking is a property of the object, not of its declared type.
 */
export interface ValueOf<T> {
  readonly value: T
}

/** A move, as `@node-drag-stop` produces them: an id and where it ended up. */
export interface NodeMove {
  id: NodeId
  position: NodePosition
}

/** The fixed end of an edge that is being drawn, before it has a target. */
export interface EdgeOrigin {
  source: NodeId
  source_port: string
}

/**
 * The slice of `useBuilderDocument` (WP-B) the canvas calls.
 *
 * Structural, and deliberately the minimum: the canvas draws a document and
 * turns finished gestures into commits, so anything unreachable from a pointer
 * has no business being nameable here. WP-B's store satisfies this by having
 * the methods rather than by importing it - which is also what lets
 * `builderCanvas.spec.ts` drive the whole surface with a recording double and
 * assert the *number* of commits a gesture produced.
 *
 * `addNode` takes the origin of the edge that reaches the new node because
 * three separate gestures need the node and its edge to be ONE commit: the
 * number keys' auto-connect (§4.1), `PortMenu`'s creation ("one undo removes
 * both") and a keyboard link. Two calls would be two undo steps, and the second
 * undo would leave an edge pointing at a node that no longer exists.
 */
export interface CanvasDocumentStore {
  readonly doc: ValueOf<BuilderDocument>
  /**
   * `attachTo` is the third argument because an attachment edge points the
   * OTHER WAY: the tool is the source and the agent is the target, so
   * `connectFrom` - which names the fixed end of a flow edge that reaches the
   * new node - cannot express it. Both are optional and at most one is ever
   * passed; a drop that attaches is still ONE commit, which is what makes a
   * single Ctrl+Z remove the tool AND its wire (criterion 11).
   */
  addNode(
    node: BuilderNode,
    connectFrom?: EdgeOrigin | null,
    attachTo?: { target: NodeId; target_port: TargetPort } | null,
  ): void
  addEdge(origin: EdgeOrigin, target: NodeId): void
  moveNodes(moves: readonly NodeMove[], coalesceKey?: string): void
  deleteSelection(nodes: readonly NodeId[], edges: readonly EdgeId[]): void
  setEdgePort(edge: EdgeId, port: string): void
  retargetEdge(edge: EdgeId, endpoint: 'source' | 'target', node: NodeId, port?: string): void
  setJoin(node: NodeId, join: 'all' | null): void
}

/**
 * Where the canvas reads the server's problems from, as two getters.
 *
 * Getters rather than refs for the same reason `ValueOf` exists, one step
 * further: WP-C's `useBuilderProblems` may hold these as computeds, as reactive
 * maps or as anything else, and a getter called inside a `computed` tracks
 * whatever it touched. The canvas never asks for a problem it did not receive
 * and never derives one - it groups them by anchor for the rim, the badge and
 * the minimap dot, which is presentation over a list the server wrote.
 */
export interface CanvasProblemSource {
  byNode(): ReadonlyMap<string, readonly BuilderProblem[]>
  byEdge(): ReadonlyMap<string, readonly BuilderProblem[]>
}

/**
 * The viewport functions the canvas needs from the mounted `<VueFlow>`.
 *
 * Registered by `BuilderCanvas.vue` on mount rather than taken as a constructor
 * argument, because `useVueFlow()` only answers inside the component that hosts
 * the instance while this composable is created one level up by `BuilderView`
 * and handed down. Method syntax throughout, so Vue Flow's real functions -
 * which return promises and take wider parameter objects - are assignable
 * without a cast.
 */
export interface CanvasViewportBridge {
  screenToFlowCoordinate(point: XYPosition): XYPosition
  fitView(options?: { nodes?: string[]; duration?: number; padding?: number }): unknown
  setCenter(x: number, y: number, options?: { zoom?: number; duration?: number }): unknown
  zoomTo(zoom: number, options?: { duration?: number }): unknown
  getViewport(): { x: number; y: number; zoom: number }
  getPaneSize(): { width: number; height: number }
  /**
   * A node's RENDERED size, for align and distribute.
   *
   * `NODE_W` is fixed at 240 so the horizontal half could be done with a
   * constant, but the heights genuinely differ - a gate reserves a labelled
   * port footer, an agent now carries a second summary line, a node with a
   * problem badge grows a row - and "align bottom" computed against one assumed
   * height is align-bottom-ish, which is the one thing an alignment control may
   * not be. `null` when the node is not mounted, and every caller falls back to
   * the defaults rather than skipping the node.
   */
  getNodeSize(id: string): { width: number; height: number } | null
}

/** What `BuilderNode.vue` receives as `data`. */
export interface BuilderNodeData {
  node: BuilderNode
  /** 1-based document order, for the card's `03 · AGENT` eyebrow (§5.2). */
  index: number
  ports: readonly string[]
  acceptsIncoming: boolean
  /**
   * The target ports this card draws, in canvas order - `in`, then `attach`,
   * then `member`. Projected rather than computed on the card for the same
   * reason `ports` is: a drawn port that `isValidConnection` refuses is the
   * silent disagreement §6.1 exists to prevent.
   */
  targetPorts: readonly TargetPort[]
  problems: readonly BuilderProblem[]
  severity: Severity | null
  /** `joins[id] === 'all'` - the card's `Σ` glyph and the edges' AND bracket. */
  joined: boolean
  /** The last-clicked member of a multi-selection; align needs a defined winner. */
  anchor: boolean
  /** An edge to this node would close a loop (§4.2). Advisory; never a refusal. */
  loopTarget: boolean
  /** ...and the source is neither gate nor router, so the server will refuse it. */
  loopIllegal: boolean
  /** A connect drag is live and this node's inbound port would accept it. */
  connectable: boolean
  /**
   * 1-based position in the keyboard-link candidate list, or `null`.
   *
   * Spec section 4.1's `E` mode: candidates are NUMBERED so an author can see
   * how many there are and which one Enter would take, and Tab walks them.
   * `null` for every node whenever no keyboard link is in flight, which is
   * almost always - the badge exists for the length of one gesture.
   */
  linkIndex?: number | null
  /** This is the candidate Enter would connect to right now. */
  linkCurrent?: boolean
  /** A problem row or `F8` just pointed here; drives the finite `problem-anchor` flash. */
  flashing: boolean
  /** The node filter is active and this card matches it (section 4.5). */
  filterMatch?: boolean
  /** ...and this one does not, so it dims to .35 rather than disappearing. */
  filterDimmed?: boolean
  /**
   * `R` was pressed on this node: the card should enter inline rename.
   *
   * A projected flag rather than a DOM query, because the card OWNS the
   * contenteditable and its Escape-reverts contract. The shortcut used to run
   * `document.querySelector('[data-node-id="…"] .builder-title')?.focus()`,
   * which failed twice over - Vue Flow writes `data-id`, not `data-node-id`, so
   * the selector matched nothing anywhere in the app; and even corrected, the
   * title is `:contenteditable="editing"` and `editing` is set only by a
   * double-click handler, so focusing it could never have entered rename mode.
   * The `?.` swallowed both misses and the key read as dead.
   */
  renaming?: boolean
  /**
   * How many edges land on this node, so the card can offer the `Σ` glyph.
   *
   * §4.2 says "a node with >= 2 inbound edges shows a `Σ` glyph", and until this
   * was projected the card fell back to `data.joined`, which means the glyph
   * could only ever be switched OFF. Measured on the validator template: the
   * inspector's fan-in list named five qualifying nodes and the canvas drew one
   * badge, on the only node where AND was already on. Counted in one pass below
   * rather than through `commit.ts`'s `inboundCount` per node, which would be
   * O(N x E) on a projection that rebuilds whenever the selection moves; the
   * ANSWER is the same one `GraphSettings` shows, and `builderCanvas.spec.ts`
   * asserts the two agree so the card and the inspector cannot drift.
   */
  inbound: number
  /**
   * True for one beat after this node arrives, driving `node-land` (§4.1).
   *
   * Diffed from the document rather than set by each of the six gestures that
   * can add a node (drop, palette click, `1`-`7`, PortMenu, paste, `⌘D`),
   * because six call sites is six chances for one of them to forget and the
   * acknowledgement to go missing on exactly the path nobody tested. The very
   * first document is deliberately exempt: a template opening should not play
   * sixteen arrivals at once.
   */
  landing: boolean
  /**
   * A connect drag was just released over this card and refused (D2).
   *
   * One-shot, cleared on a timer for `--motion-medium`, and it exists because
   * the alternative is Flowise Agentflow v2's: the drop does nothing at all and
   * the author learns that the canvas is broken rather than that the edge was.
   */
  refused: boolean
}

/** What `BuilderEdge.vue` receives as `data`. */
export interface BuilderEdgeData {
  edge: BuilderEdge
  problems: readonly BuilderProblem[]
  severity: Severity | null
  /** From the mirrored `backEdges(doc)`. STYLING ONLY (R7): dashes and a `↺`. */
  backEdge: boolean
  /** The mid-point chip, or null when the source has only one way out (§5.4). */
  portLabel: string | null
  portRole: 'approve' | 'revise' | 'branch' | 'otherwise' | null
  /** `joins[target] === 'all'`, so the inbound edges draw into the AND bracket. */
  joinTarget: boolean
  /** Exactly one of the four, from `edgeClassOf`. Drives `is-class-*` and the stroke. */
  edgeClass: EdgeClass
  /**
   * The source and target KIND accents, for the flow gradient (D4).
   *
   * Resolved here rather than in the edge, because the edge is handed two node
   * ids and looking a node up from inside a renderer that mounts once per wire
   * is O(N) per edge per frame. They are `nodeKinds.ts`'s `accent` values
   * verbatim - the same string the minimap dot and the card squircle use - so a
   * gradient stop can never be a colour the node itself is not.
   */
  sourceAccent: string
  targetAccent: string
}

/**
 * `data` is required here where Vue Flow declares it optional.
 *
 * Every node on this canvas is projected by this file and every one carries a
 * `BuilderNodeData`, so the optionality is a fact about the library's generic
 * defaults rather than about anything reachable at runtime - and leaving it
 * optional would put a `?.` in front of every read in the card, the minimap and
 * the edge, each of which would then need a meaningless fallback branch.
 */
export type BuilderFlowNode = Node<BuilderNodeData> & {
  data: BuilderNodeData
  /**
   * Declared on `GraphNode` but not on `Node`, and this canvas writes it.
   *
   * `parseNode` copies every own property of an incoming node over the stored
   * one, so publishing `selected` in the projection is how a selection made
   * from a problem row or from `⌘A` reaches the library at all - the mirror in
   * the other direction is `onSelectionChange`.
   */
  selected: boolean
}
export type BuilderFlowEdge = Edge<BuilderEdgeData> & {
  data: BuilderEdgeData
  selected: boolean
}

/**
 * The hovered node and the current selection, published to every card and edge
 * without touching the nodes or edges arrays.
 *
 * §5.4's field dimming is the reason. Putting `hovered` in each edge's `data`
 * would rebuild both arrays on every `mousemove` across the canvas, and Vue
 * Flow re-parses every element when an array's identity changes - so the one
 * interaction that has to stay smooth at sixty frames would be the one doing
 * the most work. ChatDev highlights two sets against a full-strength field and
 * visibly stops working somewhere past fifteen nodes.
 */
export const BUILDER_HOVERED_NODE: InjectionKey<Ref<string | null>> = Symbol('builder-hovered-node')
/**
 * Whether the canvas is showing a stored version read-only (round 2, D-15-1).
 * Provided by `BuilderCanvas`, read by every card, so each one can wear a lock
 * without the projection carrying a flag per node.
 */
export const BUILDER_READ_ONLY: InjectionKey<Ref<boolean>> = Symbol('builder-read-only')
export const BUILDER_SELECTED_IDS: InjectionKey<Ref<ReadonlySet<string>>> =
  Symbol('builder-selected-ids')

export interface BuilderCanvasOptions {
  document: CanvasDocumentStore
  problems?: CanvasProblemSource
}

const EMPTY_PROBLEMS: ReadonlyMap<string, readonly BuilderProblem[]> = new Map()
/** The gradient stop for an endpoint that is not in the document. See the edge projection. */
const ACCENT_FALLBACK = '#777a7c'
/** `--motion-medium`, in milliseconds, for the refused-drop flash (D2). */
const REFUSED_FLASH_MS = 260
/** `.builder-node.is-pill`'s declared width, for the hit test's fallback box. */
export const ATTACHMENT_NODE_WIDTH = 160
/** Two grid steps between an attachment and the card it hangs off. */
const ATTACH_GAP = GRID * 2
/** How far down the next attachment on the same host is parked. */
const ATTACH_ROW_STEP = GRID * 3
/** The two kinds that can HAVE an attachment, per `TARGET_PORTS_BY_KIND`. */
const ATTACH_HOST_KINDS: ReadonlySet<NodeKind> = new Set<NodeKind>(['agent', 'crew'])

/** What the dangling connection line renders while a drag is in flight (D3). */
export interface ConnectPreview {
  port: string
  /** Null when the source has only one way out - the edge chip's own rule. */
  label: string | null
  role: 'approve' | 'revise' | 'branch' | 'otherwise' | null
  /** A PREVIEW from the source port alone; the target is not known yet. */
  edgeClass: EdgeClass
  accent: string
}

/** What `dropKind` reports back: the node it made, and what it hung it off. */
export interface DropResult {
  nodeId: NodeId
  attachedTo: NodeId | null
}
const NO_PROBLEMS: readonly BuilderProblem[] = []

/** Rounds to the visible grid, and to an integer. Both, always, in that order. */
export function snapToGrid(value: number): number {
  return Math.round(Math.round(value / GRID) * GRID)
}

/**
 * The worst severity in a list, or null for an empty one.
 *
 * An error outranks a warning because the rim is the first thing read and the
 * two mean categorically different things: a warning never blocks publish and
 * an error always does (§6.5). A node carrying both must read as the one that
 * stops the run.
 */
function worst(problems: readonly BuilderProblem[]): Severity | null {
  let severity: Severity | null = null
  for (const problem of problems) {
    if (problem.severity === 'error') return 'error'
    severity = 'warning'
  }
  return severity
}

/** `source|port|target`, the triple `bounds.py` treats as one edge identity. */
function tripleOf(source: string, port: string, target: string): string {
  return `${source}|${port}|${target}`
}

/** Two sets with the same members, so a mirrored selection does not re-render. */
function sameMembers(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  if (left.size !== right.size) return false
  for (const member of left) if (!right.has(member)) return false
  return true
}

interface ConnectDrag {
  source: NodeId
  port: string
  /** Every node an edge from `source` would loop back to, computed ONCE. */
  ancestors: ReadonlySet<string>
  /** True when the source kind may not close a loop, so the rim says so. */
  illegal: boolean
  /**
   * Every `source|port|target` this document already carries, built ONCE per
   * drag. `isValidConnection` runs on every pointer frame over every candidate
   * handle; rebuilding this from `doc.edges` there would be O(E) per frame for
   * an answer that cannot change while a drag is in flight.
   */
  existing: ReadonlySet<string>
}

export function useBuilderCanvas(options: BuilderCanvasOptions) {
  const store = options.document
  const problemSource = options.problems
  const doc = () => store.doc.value

  const selectedNodeIds = shallowRef<ReadonlySet<NodeId>>(new Set())
  const selectedEdgeIds = shallowRef<ReadonlySet<EdgeId>>(new Set())
  const anchorId = shallowRef<NodeId | null>(null)
  const hoveredNodeId = ref<string | null>(null)
  /**
   * What Tab traversal just landed on, for the canvas's polite live region.
   *
   * A ref here rather than a callback passed in, because the region that reads
   * it lives inside `BuilderCanvas` while this composable is created one level
   * up - handing the announcer down and the announcement back up would be a
   * cycle through two files to move one string.
   */
  const announcement = ref('')
  const flashingId = shallowRef<string | null>(null)
  /** The card a connect drag was just refused over, for `--motion-medium` (D2). */
  const refusedId = shallowRef<string | null>(null)
  let refusedTimer: ReturnType<typeof setTimeout> | null = null
  /** Which node `R` most recently asked to rename. Cleared by the card. */
  const renamingId = shallowRef<NodeId | null>(null)
  /**
   * Section 4.5's node filter, the thing `/` focuses.
   *
   * It lives here rather than in the palette because what it filters is the
   * GRAPH: matching cards highlight and the rest drop to .35, which is a fact
   * about the projection. The palette owns the text box and nothing else. An
   * empty query filters nothing at all - a filter that dimmed the whole canvas
   * when it was cleared would be worse than no filter.
   */
  const filterQuery = ref('')
  /**
   * The nodes that arrived on the last commit, for §4.1's one-shot `node-land`.
   *
   * `builder.css` has declared `@keyframes builder-node-land` and
   * `.builder-node.is-landing` since the package landed, and named `is-landing`
   * in its reduced-motion block - over a class that `grep -rn is-landing src
   * --include=*.vue --include=*.ts` found written by nothing. An animation
   * declared, documented, exempted from reduced motion, and unreachable is the
   * stub the brief forbids; this is the one ref that makes it true.
   *
   * Cleared by a timer rather than by `animationend`, for exactly the reason
   * `flash` gives: under `prefers-reduced-motion` the animation is `none`, so
   * `animationend` never fires and the class would sit on the card forever.
   */
  const landingIds = shallowRef<ReadonlySet<string>>(new Set())
  let landingTimer: ReturnType<typeof setTimeout> | null = null
  let knownNodeIds: ReadonlySet<string> | null = null
  const connectDrag = shallowRef<ConnectDrag | null>(null)
  /**
   * The keyboard half of connecting (section 4.1's `E`), and the reason
   * `cancelConnect` exists.
   *
   * `E` used to call `onConnectStart` directly and then hand the author
   * nothing: `connectDrag` was only ever cleared by `onConnectEnd`, which is
   * fired by a POINTER, so a keyboard-started connect survived Escape, every
   * click and any amount of waiting - leaving `.is-connecting` on the container
   * with two `port-ready` animations running on an idle canvas (section 5.5
   * says the design canvas is STILL) and, worse, leaving `escape()` stuck on
   * its first rung so it could never clear a selection again for the rest of
   * the session.
   *
   * So the gesture now has a state of its own with a beginning, a cycle, an
   * end and an abort, instead of borrowing half of the mouse's.
   */
  const linkMode = shallowRef<{
    source: NodeId
    port: string
    candidates: readonly NodeId[]
    index: number
  } | null>(null)
  /**
   * Where a connect drag ended on empty canvas, for `PortMenu` (§4.1).
   *
   * A ref rather than an emit, because the menu is a sibling that lives as long
   * as the canvas does and because clearing it is how Escape aborts with zero
   * commits - there is no half-created node to roll back.
   */
  const portMenuRequest = shallowRef<{ origin: EdgeOrigin; at: XYPosition } | null>(null)
  /** Alt as of the last drag frame. R12: Alt drags free of the grid. */
  const gridSnapping = ref(true)
  const pointerDownAt = shallowRef<XYPosition | null>(null)
  /** The last pointer position over the pane, for the number keys' drop point. */
  const lastPointer = shallowRef<XYPosition | null>(null)

  let bridge: CanvasViewportBridge | null = null
  let flashTimer: ReturnType<typeof setTimeout> | null = null
  /** Set by `@connect`, read and cleared by `@connect-end`. See `onConnectEnd`. */
  let landedOnPort = false

  /**
   * The projection, frozen for the duration of a drag.
   *
   * Vue Flow re-parses every node when the `nodes` array identity changes, and
   * `parseNode` assigns the incoming `position` over the existing one
   * (`Object.assign(existingNode, node, …)` in `vue-flow-core.mjs`). A drag
   * moves the node inside Vue Flow's own store while the document still holds
   * the position the node started at - so any recompute mid-drag hands the
   * dragged card its old coordinates back and the node jumps under the pointer.
   * Freezing the array makes that impossible rather than unlikely. The document
   * cannot change during a drag anyway, which is why one snapshot is enough.
   */
  const frozenNodes = shallowRef<BuilderFlowNode[] | null>(null)

  const projectedNodes = computed<BuilderFlowNode[]>(() => {
    const document = doc()
    const nodeProblems = problemSource ? problemSource.byNode() : EMPTY_PROBLEMS
    const drag = connectDrag.value
    const selected = selectedNodeIds.value
    const anchor = anchorId.value
    const flashing = flashingId.value
    const link = linkMode.value
    const linkPositions = link
      ? new Map(link.candidates.map((id, position) => [id as string, position + 1]))
      : null
    const linkCurrentId = link ? (link.candidates[link.index] as string | undefined) ?? null : null
    const renaming = renamingId.value
    const refused = refusedId.value
    // Trimmed and lower-cased once per recompute rather than once per node.
    const filter = filterQuery.value.trim().toLowerCase()
    // One pass over the edges rather than `inboundCount` per node, which would
    // be O(N*E) on a projection that rebuilds on every selection change.
    const inbound = new Map<string, number>()
    for (const edge of document.edges) inbound.set(edge.target, (inbound.get(edge.target) ?? 0) + 1)

    return document.nodes.map((node, index) => {
      const problems = nodeProblems.get(node.id) ?? NO_PROBLEMS
      const meta = NODE_KINDS[node.kind]
      const loopTarget = drag !== null && drag.ancestors.has(node.id)
      const data: BuilderNodeData = {
        node,
        index: index + 1,
        ports: outPortsOf(node),
        acceptsIncoming: meta.acceptsIncoming,
        targetPorts: targetPortsOf(node.kind),
        problems,
        severity: worst(problems),
        joined: document.joins[node.id] === 'all',
        anchor: anchor === node.id,
        loopTarget,
        loopIllegal: loopTarget && drag !== null && drag.illegal,
        connectable:
          drag !== null &&
          meta.acceptsIncoming &&
          !drag.existing.has(tripleOf(drag.source, drag.port, node.id)),
        linkIndex: linkPositions ? linkPositions.get(node.id) ?? null : null,
        linkCurrent: linkCurrentId === node.id,
        flashing: flashing === node.id,
        renaming: renaming === node.id,
        // Matched on the LABEL and the id, because those are the two names a
        // node has and an author looking for `market_analyst` may be thinking
        // of either. Nothing is hidden: a filtered-out card dims, keeps its
        // edges and stays selectable, so the shape of the graph survives.
        filterMatch:
          filter !== '' &&
          (node.label.toLowerCase().includes(filter) || node.id.toLowerCase().includes(filter)),
        filterDimmed:
          filter !== '' &&
          !(node.label.toLowerCase().includes(filter) || node.id.toLowerCase().includes(filter)),
        inbound: inbound.get(node.id) ?? 0,
        landing: landingIds.value.has(node.id),
        refused: refused === node.id,
      }
      return {
        id: node.id,
        type: 'builder',
        position: node.position,
        selected: selected.has(node.id),
        data,
      }
    })
  })

  const nodes = computed<BuilderFlowNode[]>(() => frozenNodes.value ?? projectedNodes.value)

  const edges = computed<BuilderFlowEdge[]>(() => {
    const document = doc()
    const edgeProblems = problemSource ? problemSource.byEdge() : EMPTY_PROBLEMS
    const selected = selectedEdgeIds.value
    const back = new Set(backEdges(document))
    const byId = new Map(document.nodes.map((node) => [node.id as string, node]))

    return document.edges.map((edge, index) => {
      const problems = edgeProblems.get(edge.id) ?? NO_PROBLEMS
      const source = byId.get(edge.source)
      const target = byId.get(edge.target)
      const data: BuilderEdgeData = {
        edge,
        problems,
        severity: worst(problems),
        backEdge: back.has(index),
        portLabel: portLabelFor(source, edge),
        portRole: portRoleFor(source, edge),
        joinTarget: document.joins[edge.target] === 'all',
        edgeClass: edgeClassOf(edge),
        // `--edge-inactive` for an endpoint the document does not contain: that
        // is an `edge-unknown-endpoint` the problems panel has to be able to
        // point at a DRAWN wire, so it is painted plainly rather than dropped.
        sourceAccent: source ? NODE_KINDS[source.kind].accent : ACCENT_FALLBACK,
        targetAccent: target ? NODE_KINDS[target.kind].accent : ACCENT_FALLBACK,
      }
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.source_port,
        targetHandle: edge.target_port,
        type: 'builder',
        selected: selected.has(edge.id),
        updatable: true,
        data,
      }
    })
  })

  /**
   * What the dangling connection line should say and be tinted by (D3).
   *
   * Flowise's `ConnectionLine.jsx` previews the branch label and the colour
   * while you drag, and its own notes name that as the reason a drag from a
   * human-input node never lands on the wrong branch. The equivalent here is
   * sharper, because a gate has two ports and a router has up to four: without
   * this the author is dragging an anonymous grey line out of a card with four
   * identical discs on it and finding out which one they grabbed on release.
   *
   * The label follows the same rule as the edge chip - shown only when the
   * source has more than one way out - because a line reading `out` on every
   * drag in the graph is furniture, and furniture is what stops labels being
   * read.
   *
   * `edgeClass` here is a PREVIEW and is derived from the source port alone,
   * because the target port is not known until the pointer lands. `attach` and
   * `error` are the two source ports that decide a class on their own; the
   * `member` class cannot be previewed at all, and is deliberately shown as
   * flow rather than guessed at.
   */
  const connectPreview = computed<ConnectPreview | null>(() => {
    const drag = connectDrag.value ?? linkPreviewOrigin()
    if (!drag) return null
    const source = doc().nodes.find((node) => node.id === drag.source)
    if (!source) return null
    const ports = outPortsOf(source)
    return {
      port: drag.port,
      label: ports.length > 1 ? drag.port : null,
      role: portRoleFor(source, { source_port: drag.port }),
      edgeClass:
        drag.port === 'attach' ? 'attach' : drag.port === 'error' ? 'error' : 'flow',
      accent: NODE_KINDS[source.kind].accent,
    }
  })

  /** The keyboard link's origin, in the shape a pointer drag would have had. */
  function linkPreviewOrigin(): { source: NodeId; port: string } | null {
    const link = linkMode.value
    return link ? { source: link.source, port: link.port } : null
  }

  /* --- selection --------------------------------------------------------- */

  const selectionSize = computed(() => selectedNodeIds.value.size + selectedEdgeIds.value.size)
  const selectedNodes = computed(() =>
    doc().nodes.filter((node) => selectedNodeIds.value.has(node.id)),
  )
  /** One string set for `provide`, so a card can ask without a prop. */
  const selectedIds = computed<ReadonlySet<string>>(() => {
    const all = new Set<string>(selectedNodeIds.value)
    for (const edge of selectedEdgeIds.value) all.add(edge)
    return all
  })

  function setSelection(nodeIds: Iterable<NodeId>, edgeIds: Iterable<EdgeId> = []): void {
    const nextNodes = new Set(nodeIds)
    const nextEdges = new Set(edgeIds)
    // Written only when the membership actually moved. Vue Flow mirrors its own
    // gesture selection back through `@selection-change`, which lands here
    // carrying the set we just published; assigning a fresh Set with identical
    // members would rebuild the entire nodes array on every marquee frame for
    // no visible change, and could ping-pong with the library indefinitely.
    if (!sameMembers(nextNodes, selectedNodeIds.value)) selectedNodeIds.value = nextNodes
    if (!sameMembers(nextEdges, selectedEdgeIds.value)) selectedEdgeIds.value = nextEdges
    if (anchorId.value !== null && !nextNodes.has(anchorId.value)) anchorId.value = null
  }

  function selectNode(id: NodeId, mode: 'replace' | 'add' | 'toggle' = 'replace'): void {
    const next = mode === 'replace' ? new Set<NodeId>() : new Set(selectedNodeIds.value)
    if (mode === 'toggle' && next.has(id)) next.delete(id)
    else next.add(id)
    setSelection(next, mode === 'replace' ? [] : selectedEdgeIds.value)
    anchorId.value = next.has(id) ? id : null
  }

  function selectEdge(id: EdgeId, mode: 'replace' | 'add' = 'replace'): void {
    const next = mode === 'replace' ? new Set<EdgeId>() : new Set(selectedEdgeIds.value)
    next.add(id)
    setSelection(mode === 'replace' ? [] : selectedNodeIds.value, next)
  }

  function selectAll(): void {
    setSelection(
      doc().nodes.map((node) => node.id),
      doc().edges.map((edge) => edge.id),
    )
  }

  function clearSelection(): void {
    setSelection([], [])
    anchorId.value = null
  }

  /**
   * Vue Flow's own selection, mirrored in.
   *
   * One direction only. Marquee, shift-click and ctrl-click are the library's
   * (R2) and arrive here; everything this composable initiates is written to
   * these refs and reaches Vue Flow through the `selected` flag on the
   * projection, which `parseNode` copies over its own. Two writers, one field,
   * and `sameMembers` is what stops them arguing.
   */
  function onSelectionChange(payload: {
    nodes: readonly { id: string }[]
    edges: readonly { id: string }[]
  }): void {
    setSelection(
      payload.nodes.map((node) => node.id as NodeId),
      payload.edges.map((edge) => edge.id as EdgeId),
    )
  }

  /* --- the collapse Vue Flow deliberately does not do -------------------- */

  function notePointerDown(event: { clientX: number; clientY: number }): void {
    pointerDownAt.value = { x: event.clientX, y: event.clientY }
    lastPointer.value = { x: event.clientX, y: event.clientY }
  }

  function notePointerMove(event: { clientX: number; clientY: number }): void {
    lastPointer.value = { x: event.clientX, y: event.clientY }
  }

  /**
   * A click on a node, after Vue Flow has already decided what it selects.
   *
   * The only thing done here is the collapse Vue Flow leaves undone: clicking
   * one member of a multi-selection with no modifier held means "just this
   * one". The travel test is what separates that from the end of a group drag,
   * which arrives as the same `click` event on the same node.
   */
  function onNodeClick(id: NodeId, event: MouseEvent): void {
    const start = pointerDownAt.value
    pointerDownAt.value = null
    anchorId.value = id
    if (event.shiftKey || event.metaKey || event.ctrlKey) return
    if (selectionSize.value <= 1) return
    if (!selectedNodeIds.value.has(id)) return
    if (start) {
      const travelled = Math.hypot(event.clientX - start.x, event.clientY - start.y)
      if (travelled >= COLLAPSE_TRAVEL_PX) return
    }
    setSelection([id], [])
    anchorId.value = id
  }

  /* --- connecting -------------------------------------------------------- */

  /**
   * The representational impossibilities of §6.1, and nothing else.
   *
   * A fifth outgoing edge is PERMITTED here on purpose (R6): `max_fanout_width`
   * is a `bounds.py` count, the server reports it as a Problem the author can
   * read, and refusing it at the mouse would mean the canvas and the compiler
   * disagreeing silently the first time that bound moves.
   *
   * THE `id` TEST IS NOT A NICETY. `createGraphEdges` runs EVERY edge in the
   * projection through this function on every `setEdges`, and drops - with a
   * console error - any it refuses. An edge already in the document that fails
   * one of these tests is exactly an `edge-unknown-port` or an
   * `edge-target-refuses-incoming`: a problem the panel has to be able to point
   * at a DRAWN edge. Refusing it here would erase the edge from the canvas and
   * leave a problem row anchored to nothing, which is the failure this whole
   * document is written against. A live connection attempt is a `Connection`
   * and carries no id; a re-parse is an `Edge` and does.
   */
  function isValidConnection(connection: {
    source: string
    target: string
    sourceHandle?: string | null
    targetHandle?: string | null
    id?: string
  }): boolean {
    if (connection.id !== undefined) return true

    const document = doc()
    const source = document.nodes.find((node) => node.id === connection.source)
    const target = document.nodes.find((node) => node.id === connection.target)
    if (!source || !target) return false

    // The target port has to be one the TARGET KIND offers. `input` and the
    // three attachment kinds offer none at all and render none at all, so that
    // pair is a parse refusal twice over; `attach` on a gate and `member` on an
    // agent are refusals of the same kind, a `target_port` the schema will not
    // accept for that node.
    const targetPort = (connection.targetHandle ?? 'in') as TargetPort
    if (!targetPortsOf(target.kind).includes(targetPort)) return false

    const port = connection.sourceHandle ?? 'out'
    if (!outPortsOf(source).includes(port)) return false

    /*
     * The three class rules of 03-node-library.md FD4.
     *
     * Each one is a shape the SCHEMA refuses rather than a count the server
     * reports, which is the only test for belonging in this function: a tool
     * wired into an agent's `in` port is not a step that happens to be badly
     * ordered, it is a category error the compiler has no node to build from.
     * They are stated on the SOURCE's family and kind because the target port
     * has already been established, so between them the two ends of the edge
     * are pinned by two independent facts rather than by one inference.
     */
    const sourceFamily = NODE_KINDS[source.kind].family
    // Only a tool, an MCP server or a skill may hang off something.
    if (targetPort === 'attach' && sourceFamily !== 'attachment') return false
    // Only an agent can be a member of a crew. A crew inside a crew is a
    // nesting the compiler has no shape for.
    if (targetPort === 'member' && source.kind !== 'agent') return false
    // And nothing an agent HAS is a step in the flow. This is the mirror of the
    // rule above and it is the one an author reaches by accident, because the
    // `in` port is the big obvious one at the top of every card.
    if (targetPort === 'in' && sourceFamily === 'attachment') return false

    const triple = tripleOf(source.id, port, target.id)
    const drag = connectDrag.value
    if (drag) return !drag.existing.has(triple)
    // Reached by `connectOnClick`, where no drag was ever started. O(E) once,
    // and only on the click that completes the connection.
    return !document.edges.some(
      (edge) => tripleOf(edge.source, edge.source_port, edge.target) === triple,
    )
  }

  function onConnectStart(params: { nodeId?: string; handleId: string | null }): void {
    const document = doc()
    const source = document.nodes.find((node) => node.id === params.nodeId)
    landedOnPort = false
    if (!source) return
    const port = params.handleId ?? 'out'
    const existing = new Set<string>()
    for (const edge of document.edges) {
      existing.add(tripleOf(edge.source, edge.source_port, edge.target))
    }
    // `ancestorsOf` excludes the start unless a real path leads back to it, so
    // the self-edge - the one loop that closes through no other node - is
    // unioned in here rather than folded into the graph helper, where it would
    // have claimed a node is its own ancestor on an acyclic document.
    const ancestors = new Set<string>(ancestorsOf(document, source.id))
    ancestors.add(source.id)
    connectDrag.value = {
      source: source.id,
      port,
      ancestors,
      illegal: !LOOP_CLOSING_KINDS.has(source.kind),
      existing,
    }
  }

  /**
   * The end of a connect drag, and the one gesture that opens `PortMenu`.
   *
   * A drop that landed on a handle emitted `@connect` first, which is the only
   * reliable signal available here: `@connect-end` carries the raw pointer
   * event and nothing about what it hit. Anything still unclaimed ended on
   * empty canvas (§4.1).
   */
  function onConnectEnd(event?: MouseEvent | TouchEvent): void {
    const drag = connectDrag.value
    connectDrag.value = null
    if (landedOnPort) {
      landedOnPort = false
      return
    }
    if (!drag || !event || !('clientX' in event)) return

    /*
     * A drop that landed ON A CARD and was refused is not a drop on empty
     * canvas, and opening `PortMenu` for it would be the wrong answer twice
     * over: it offers to create a NEW node when the author was pointing at an
     * existing one, and it hides the refusal behind a menu. So the card flashes
     * (D2) and the menu stays shut. Everything genuinely released over the
     * background still opens the menu, which is §4.1's gesture and is
     * unchanged.
     *
     * The hit test is the DOM's, not ours (R2): whatever the pointer was over
     * carries `data-id` on its `.vue-flow__node` ancestor, and Vue Flow put it
     * there. Recomputing it from coordinates would be a second opinion about a
     * question the browser has already answered.
     */
    const overNode = nodeIdUnder(event.target)
    if (overNode !== null) {
      flashRefused(overNode)
      return
    }
    portMenuRequest.value = {
      origin: { source: drag.source, source_port: drag.port },
      at: { x: event.clientX, y: event.clientY },
    }
  }

  /** The id of the card the pointer was over, or null for the background. */
  function nodeIdUnder(target: EventTarget | null): string | null {
    if (!(target instanceof Element)) return null
    const card = target.closest('.vue-flow__node')
    return card?.getAttribute('data-id') ?? null
  }

  /**
   * Mark a card refused for `--motion-medium`, then stop.
   *
   * A timer rather than `animationend`, for the reason `flash` already gives:
   * under `prefers-reduced-motion` the animation is `none`, so `animationend`
   * never fires and the class would sit on the card for the rest of the
   * session.
   */
  function flashRefused(id: string): void {
    if (refusedTimer) clearTimeout(refusedTimer)
    refusedId.value = id
    refusedTimer = setTimeout(() => {
      refusedId.value = null
      refusedTimer = null
    }, REFUSED_FLASH_MS)
  }

  function onConnect(connection: {
    source: string
    target: string
    sourceHandle?: string | null
  }): void {
    landedOnPort = true
    store.addEdge(
      { source: connection.source as NodeId, source_port: connection.sourceHandle ?? 'out' },
      connection.target as NodeId,
    )
  }

  /** Escape, or a `PortMenu` dismissed: no node, no edge, no commit. */
  function cancelPortMenu(): void {
    portMenuRequest.value = null
  }

  /**
   * Abort ANY connect gesture - pointer or keyboard - with zero commits.
   *
   * `cancelPortMenu` alone was what Escape called, and it clears one ref out of
   * three. The container's `.is-connecting` class and the animating ports are
   * bound to `connectDrag`, so a gesture aborted through the old path stayed
   * visually and logically live forever. Section 4.5's Escape ladder starts
   * "if a gesture is live, abort it", and this is what aborting one means.
   */
  function cancelConnect(): void {
    connectDrag.value = null
    linkMode.value = null
    landedOnPort = false
    portMenuRequest.value = null
  }

  /* --- the keyboard half of connecting (section 4.1, `E`) ------------------ */

  /**
   * Which nodes an edge from `source`'s first port could legally reach.
   *
   * The same predicate the projection already uses for `connectable`, in
   * document order, so the numbers an author reads run top-to-bottom through
   * the palette-ordered card list rather than in whatever order a Set iterated.
   * A representationally-impossible target (no inbound port, or a duplicate
   * triple) is not offered a number at all - section 6.1 tier 1 refuses those
   * at the mouse and the keyboard must not be the softer door.
   */
  function linkCandidates(source: BuilderNode, port: string): NodeId[] {
    const document = doc()
    const taken = new Set(
      document.edges.map((edge) => tripleOf(edge.source, edge.source_port, edge.target)),
    )
    return document.nodes
      .filter((node) => node.id !== source.id)
      .filter((node) => NODE_KINDS[node.kind].acceptsIncoming)
      .filter((node) => !taken.has(tripleOf(source.id, port, node.id)))
      .map((node) => node.id)
  }

  /**
   * Start a keyboard link from a node, or report why there is nothing to start.
   *
   * Returns the number of candidates, so the caller can say something true
   * rather than leaving the author pressing a key that appears dead. Zero
   * candidates enters no mode at all: a gesture with no possible ending is the
   * stuck state this whole change exists to remove.
   */
  function beginLink(nodeId: NodeId): number {
    const document = doc()
    const source = document.nodes.find((node) => node.id === nodeId)
    if (!source) return 0
    const port = outPortsOf(source)[0]
    if (!port) return 0
    const candidates = linkCandidates(source, port)
    if (candidates.length === 0) return 0
    onConnectStart({ nodeId, handleId: port })
    linkMode.value = { source: nodeId, port, candidates, index: 0 }
    return candidates.length
  }

  /** Tab / Shift+Tab inside link mode: walk the numbered candidates, wrapping. */
  function cycleLink(step: 1 | -1): void {
    const link = linkMode.value
    if (!link) return
    const size = link.candidates.length
    const index = (link.index + step + size) % size
    linkMode.value = { ...link, index }
  }

  /** Enter inside link mode: one commit, then the gesture is over. */
  function commitLink(): void {
    const link = linkMode.value
    if (!link) return
    const target = link.candidates[link.index]
    cancelConnect()
    if (!target) return
    store.addEdge({ source: link.source, source_port: link.port }, target)
    selectNode(target)
  }

  /* --- creating ---------------------------------------------------------- */

  /**
   * A kind dropped at a screen point, as one commit.
   *
   * `Math.round` runs here, again inside `newNode`, and again on every move,
   * and the repetition is the point (R12): `position.x` is declared `int` in
   * `document.py`, pydantic coerces `120.0` but refuses `120.5`, and the refusal
   * arrives as a 422 on a save minutes after the drop that caused it.
   */
  function dropKind(
    kind: NodeKind,
    at: XYPosition,
    connectFrom: EdgeOrigin | null = null,
  ): DropResult | null {
    if (!bridge) return null
    const point = bridge.screenToFlowCoordinate(at)

    /*
     * ATTACH-BY-DROP (D8). Dropping a tool, an MCP server or a skill INSIDE an
     * agent or crew card is the gesture, and it is one commit: the node and the
     * `attach` edge together, labelled `Attach tool`, so one Ctrl+Z removes
     * both. Two commits would leave an author who pressed undo once looking at
     * a pill they never placed, hanging off nothing.
     *
     * A drop on empty canvas is deliberately still legal and creates an
     * unattached node - the author may be laying out before wiring, and
     * `bounds.py` reporting `attachment-unattached` is a sentence they can read
     * where a refused drop is not. Contract request in the plan's Status.
     */
    if (NODE_KINDS[kind].family === 'attachment') {
      const host = hitTestNode(point, ATTACH_HOST_KINDS)
      if (host) return attachTo(kind, host)
    }

    const node = createAt(kind, point, connectFrom)
    return { nodeId: node.id, attachedTo: null }
  }

  /**
   * Which card contains a flow-space point, or null.
   *
   * LAST match wins, because document order is paint order: the card an author
   * sees on top of a stack is the one the drop belongs to. Sizes come from the
   * mounted instance where it has measured one, and from the §5.2 defaults
   * where it has not - the same fallback `align` and the minimap already use,
   * so a card that has not painted yet is a slightly wrong box rather than a
   * zero-area one that can never be hit.
   */
  function hitTestNode(point: NodePosition, kinds?: ReadonlySet<NodeKind>): NodeId | null {
    let found: NodeId | null = null
    for (const node of doc().nodes) {
      if (kinds && !kinds.has(node.kind)) continue
      const measured = bridge?.getNodeSize(node.id) ?? null
      const width = measured?.width || defaultWidthOf(node.kind)
      const height = measured?.height || DEFAULT_NODE_HEIGHT
      if (point.x < node.position.x || point.x > node.position.x + width) continue
      if (point.y < node.position.y || point.y > node.position.y + height) continue
      found = node.id
    }
    return found
  }

  /**
   * The new attachment, parked to the LEFT of its host, wired in one commit.
   *
   * Left, because D1 puts the host's `attach` port on its left edge and an
   * attachment's own `attach` port on its right - so the wire runs horizontally
   * and a wired agent stays readable against the vertical flow. Dropped ON the
   * card, the pill would land under the thing it is attached to and the author
   * would have to move it before they could read either.
   *
   * The vertical stagger counts the attachments the host ALREADY has, so
   * dropping three tools on one agent produces three legible rows rather than
   * three pills in one place. It is a starting position and nothing more: the
   * author drags it wherever they like and that is an ordinary move.
   */
  function attachTo(kind: NodeKind, host: NodeId): DropResult {
    const document = doc()
    const target = document.nodes.find((node) => node.id === host)
    if (!target) return { nodeId: host, attachedTo: null }
    const already = document.edges.filter(
      (edge) => edge.target === host && edge.target_port === 'attach',
    ).length
    const node = newNode(
      kind,
      {
        x: snapToGrid(target.position.x - ATTACHMENT_NODE_WIDTH - ATTACH_GAP),
        y: snapToGrid(target.position.y + already * ATTACH_ROW_STEP),
      },
      document.nodes.map((existing) => existing.id),
    )
    store.addNode(node, null, { target: host, target_port: 'attach' })
    setSelection([node.id], [])
    anchorId.value = node.id
    return { nodeId: node.id, attachedTo: host }
  }

  /** A pill is 160px wide and a card 240; the hit test needs to know which. */
  function defaultWidthOf(kind: NodeKind): number {
    return NODE_KINDS[kind].family === 'attachment'
      ? ATTACHMENT_NODE_WIDTH
      : DEFAULT_NODE_WIDTH
  }

  /** The same, at a point already in flow coordinates. */
  function createAt(
    kind: NodeKind,
    position: NodePosition,
    connectFrom: EdgeOrigin | null = null,
  ): BuilderNode {
    const document = doc()
    const node = newNode(
      kind,
      { x: snapToGrid(position.x), y: snapToGrid(position.y) },
      document.nodes.map((existing) => existing.id),
    )
    store.addNode(node, connectFrom)
    setSelection([node.id], [])
    anchorId.value = node.id
    return node
  }

  /** The centre of what the author can currently see, in flow coordinates. */
  function viewportCentre(): NodePosition {
    if (!bridge) return { x: 0, y: 0 }
    const pane = bridge.getPaneSize()
    const viewport = bridge.getViewport()
    return {
      x: (pane.width / 2 - viewport.x) / viewport.zoom,
      y: (pane.height / 2 - viewport.y) / viewport.zoom,
    }
  }

  /**
   * `1`-`7`: drop a kind at the pointer, or at the viewport centre when the
   * pointer has never been over the pane, and connect it to the selection when
   * that selection is exactly one node.
   *
   * The auto-connect is checked rather than assumed, and it is checked against
   * the KIND rather than by looking the new node up again. `soleSelectedOrigin`
   * has already established that the source declares the port, the new id is
   * fresh so no duplicate triple can exist, and what is left is whether the new
   * kind accepts an inbound edge at all - pressing `1` with an agent selected
   * would otherwise mint an edge into an `input` node, which is a 422 rather
   * than a Problem and so a refusal the author cannot act on from the canvas.
   *
   * Asking `isValidConnection` instead would mean asking about a node the
   * document does not contain until the commit lands, which makes a correct
   * answer depend on the store applying the write synchronously.
   */
  function insertKind(kind: NodeKind): void {
    const pointer = lastPointer.value
    const position =
      pointer && bridge
        ? bridge.screenToFlowCoordinate(pointer)
        : offsetFromCentre(viewportCentre())
    const origin = soleSelectedOrigin()
    const node = createAt(kind, position, null)
    if (!origin) return
    if (!NODE_KINDS[kind].acceptsIncoming) return
    store.addEdge(origin, node.id)
  }

  /** Half a card up and left, so a centre-dropped card is centred on the point. */
  function offsetFromCentre(centre: NodePosition): NodePosition {
    return { x: centre.x - DEFAULT_NODE_WIDTH / 2, y: centre.y - DEFAULT_NODE_HEIGHT / 2 }
  }

  /** The one selected node's first out-port, or null when that is not the shape. */
  function soleSelectedOrigin(): EdgeOrigin | null {
    if (selectedNodeIds.value.size !== 1) return null
    const [only] = selectedNodeIds.value
    const node = doc().nodes.find((candidate) => candidate.id === only)
    if (!node) return null
    const ports = outPortsOf(node)
    if (ports.length === 0) return null
    return { source: node.id, source_port: ports[0] }
  }

  /* --- moving ------------------------------------------------------------ */

  function onNodeDragStart(event: NodeDragEvent): void {
    frozenNodes.value = projectedNodes.value
    gridSnapping.value = !isAltHeld(event.event)
  }

  function onNodeDrag(event: NodeDragEvent): void {
    gridSnapping.value = !isAltHeld(event.event)
  }

  /**
   * ONE commit per gesture, and it is non-negotiable (invariant 4).
   *
   * Vue Flow reports every node that moved, which is what makes a group drag a
   * single undo step rather than one per member. `@nodes-change` fires per
   * frame per node and is deliberately not listened to anywhere in this file.
   */
  function onNodeDragStop(event: NodeDragEvent): void {
    const moved = event.nodes.length > 0 ? event.nodes : [event.node]
    store.moveNodes(
      moved.map((node) => ({
        id: node.id as NodeId,
        position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
      })),
    )
    frozenNodes.value = null
    gridSnapping.value = true
  }

  /**
   * Arrow-key movement, coalesced so a held key is one undo step.
   *
   * The key names the ids rather than the direction, because a run of nudges
   * that changes direction is still one intent - "put these three there" - and
   * splitting the ring on a direction change would spend four entries on one
   * adjustment.
   */
  function nudge(dx: number, dy: number): void {
    const selected = selectedNodeIds.value
    if (selected.size === 0) return
    const moves: NodeMove[] = []
    for (const node of doc().nodes) {
      if (!selected.has(node.id)) continue
      moves.push({
        id: node.id,
        position: { x: Math.round(node.position.x + dx), y: Math.round(node.position.y + dy) },
      })
    }
    store.moveNodes(moves, `move:${[...selected].sort().join(',')}`)
  }

  function isAltHeld(event: unknown): boolean {
    return typeof event === 'object' && event !== null && 'altKey' in event
      ? Boolean((event as { altKey?: boolean }).altKey)
      : false
  }

  /* --- edges ------------------------------------------------------------- */

  /**
   * An endpoint dragged onto another port.
   *
   * Three commands, because three different things happen, and dropping on a
   * different port of the SAME node is the one that matters most: it is how a
   * gate edge moves between `approve` and `revise`, and modelling it as a
   * delete-and-recreate would lose the edge's identity and its place in
   * `backEdges`' index order.
   */
  function onEdgeUpdate(payload: {
    edge: { id: string; source: string; target: string; sourceHandle?: string | null }
    connection: { source: string; target: string; sourceHandle?: string | null }
  }): void {
    const id = payload.edge.id as EdgeId
    const nextPort = payload.connection.sourceHandle ?? 'out'
    if (payload.connection.target !== payload.edge.target) {
      store.retargetEdge(id, 'target', payload.connection.target as NodeId)
      return
    }
    if (payload.connection.source !== payload.edge.source) {
      store.retargetEdge(id, 'source', payload.connection.source as NodeId, nextPort)
      return
    }
    if (nextPort !== (payload.edge.sourceHandle ?? 'out')) store.setEdgePort(id, nextPort)
  }

  /* --- deleting ---------------------------------------------------------- */

  /**
   * Delete with no confirmation, because undo IS the confirmation.
   *
   * `:delete-key-code="null"` on the canvas is what routes the key here rather
   * than into Vue Flow's own removal, which would take the elements out of the
   * library's store without ever reaching `commit()` - undoable by nothing, and
   * silently re-added the next time the projection recomputed.
   */
  function deleteSelection(): void {
    if (selectionSize.value === 0) return
    store.deleteSelection([...selectedNodeIds.value], [...selectedEdgeIds.value])
    clearSelection()
  }

  /** `Σ`: AND waits for every inbound branch, OR fires on the first. */
  function toggleJoin(id: NodeId): void {
    store.setJoin(id, doc().joins[id] === 'all' ? null : 'all')
  }

  /* --- navigating -------------------------------------------------------- */

  function attachViewport(next: CanvasViewportBridge): void {
    bridge = next
  }

  function detachViewport(): void {
    bridge = null
  }

  /**
   * `R`: ask this node's card to enter inline rename.
   *
   * Set, then cleared by the card through `noteRenameStarted` once it has the
   * caret. A latch rather than an event bus because the projection is the only
   * channel between this composable and the cards, and one that stayed set
   * would re-arm rename every time the array recomputed.
   */
  function requestRename(id: NodeId): void {
    renamingId.value = id
  }

  function noteRenameStarted(): void {
    renamingId.value = null
  }

  function focusNode(id: NodeId, select = true): void {
    if (select) {
      setSelection([id], [])
      anchorId.value = id
    }
    bridge?.fitView({ nodes: [id], duration: 260 })
  }

  /**
   * A problem row, `F8`, or a publish refusal: the same path in all three
   * (§6.3), so "take me there" cannot come to mean two different things.
   *
   * A document-level problem anchors to neither a node nor an edge and moves
   * nothing - it is already rendered in the panel's own group, and centring the
   * viewport on nothing at all would read as a broken click.
   */
  function focusProblem(problem: BuilderProblem): void {
    if (problem.node_id) {
      focusNode(problem.node_id as NodeId)
      flash(problem.node_id)
      return
    }
    if (problem.edge_id) {
      selectEdge(problem.edge_id as EdgeId)
      const edge = doc().edges.find((candidate) => candidate.id === problem.edge_id)
      if (edge) bridge?.fitView({ nodes: [edge.source, edge.target], duration: 260 })
      flash(problem.edge_id)
    }
  }

  /**
   * The finite `problem-anchor` flash (§5.5), cleared by a timer rather than by
   * an `animationend` listener: the animation is `none` under
   * `prefers-reduced-motion`, so `animationend` would never fire and the class
   * would sit on the card for the rest of the session.
   */
  function flash(id: string): void {
    if (flashTimer !== null) clearTimeout(flashTimer)
    flashingId.value = id
    flashTimer = setTimeout(() => {
      flashingId.value = null
      flashTimer = null
    }, 3300)
  }

  /** `Tab` / `Shift+Tab`: one step along the compiler's own execution order. */
  function traverse(step: 1 | -1): void {
    const order = topoOrder(doc())
    if (order.length === 0) return
    const current = anchorId.value
    const at = current === null ? -1 : order.indexOf(current)
    const next = order[(at + step + order.length * 2) % order.length]
    setSelection([next], [])
    anchorId.value = next
    focusNode(next, false)
    const node = doc().nodes.find((candidate) => candidate.id === next)
    if (node) announcement.value = `${node.label}, ${node.kind}`
  }

  /**
   * `[` / `]`: the other nodes fed by the same sources as this one.
   *
   * Siblings rather than neighbours, because the three research branches of a
   * fan-out are the set an author actually wants to step through, and they are
   * exactly the nodes that share a parent.
   */
  function cycleSibling(step: 1 | -1): void {
    const current = anchorId.value
    if (current === null) return
    const document = doc()
    const parents = new Set(
      document.edges.filter((edge) => edge.target === current).map((edge) => edge.source),
    )
    const siblings = new Set<string>()
    for (const edge of document.edges) {
      if (parents.has(edge.source)) siblings.add(edge.target)
    }
    const ordered = document.nodes.filter((node) => siblings.has(node.id)).map((node) => node.id)
    if (ordered.length < 2) return
    const at = ordered.indexOf(current)
    const next = ordered[(at + step + ordered.length) % ordered.length]
    setSelection([next], [])
    anchorId.value = next
    focusNode(next, false)
    const node = document.nodes.find((candidate) => candidate.id === next)
    if (node) announcement.value = `${node.label}, ${node.kind}`
  }

  function fitView(): void {
    bridge?.fitView({ padding: 0.14, duration: 260 })
  }

  function zoomToActual(): void {
    bridge?.zoomTo(1, { duration: 260 })
  }

  function zoomToSelection(): void {
    const ids = [...selectedNodeIds.value]
    if (ids.length === 0) {
      fitView()
      return
    }
    bridge?.fitView({ nodes: ids, duration: 260 })
  }

  /** Centre the viewport on a flow point. The minimap's only write. */
  function centreOn(point: XYPosition): void {
    bridge?.setCenter(point.x, point.y, { zoom: bridge.getViewport().zoom, duration: 0 })
  }

  /**
   * The arrival diff that drives `node-land`.
   *
   * Watched here rather than called by `BuilderView` after each of the six
   * gestures that can add a node, because six call sites is six chances for one
   * to forget and for the acknowledgement to go missing on the path nobody
   * tested. The membership DIFF is what makes this safe against the noisy
   * trigger: `nodes` gets a new array identity on every commit including a
   * drag's final position write, and a commit that added nothing produces an
   * empty `arrived` and returns before touching the ref.
   */
  watch(
    () => doc().nodes,
    (nodes) => {
      const ids: ReadonlySet<string> = new Set(nodes.map((node) => node.id))
      const previous = knownNodeIds
      knownNodeIds = ids
      // The first document is not an arrival. A sixteen-node template opening
      // should settle onto the canvas, not stage sixteen entrances at once.
      if (previous === null) return
      const arrived = new Set<string>()
      for (const id of ids) if (!previous.has(id)) arrived.add(id)
      if (arrived.size === 0) return
      if (landingTimer !== null) clearTimeout(landingTimer)
      landingIds.value = arrived
      // 320ms, comfortably past the 260ms animation. A hair longer rather than
      // exact, because a class pulled at the same instant the animation ends
      // shows a one-frame flash of the un-animated card on a slow paint.
      landingTimer = setTimeout(() => {
        landingIds.value = new Set()
        landingTimer = null
      }, 320)
    },
    { immediate: true },
  )

  /* --- align & distribute (§4.3) ----------------------------------------- */

  /** A selected node with the box it actually occupies on the canvas. */
  interface SelectionBox {
    id: NodeId
    x: number
    y: number
    width: number
    height: number
  }

  function selectionBoxes(): SelectionBox[] {
    const selected = selectedNodeIds.value
    const boxes: SelectionBox[] = []
    for (const node of doc().nodes) {
      if (!selected.has(node.id)) continue
      const size = bridge?.getNodeSize(node.id) ?? null
      boxes.push({
        id: node.id,
        x: node.position.x,
        y: node.position.y,
        width: size?.width || DEFAULT_NODE_WIDTH,
        height: size?.height || DEFAULT_NODE_HEIGHT,
      })
    }
    return boxes
  }

  /**
   * Move every selected node onto one line, as ONE commit (§4.3).
   *
   * The line is the ANCHOR's, and that is why `anchorId` exists at all: "align
   * left" over three nodes has three defensible answers, and a control that
   * picks one silently is a control an author cannot predict. `builder.css`
   * already draws the anchor's ring at full strength against the members' .6 -
   * the winner is visible before the button is pressed. With no anchor (a
   * marquee selects without clicking anything) the extreme edge of the
   * selection wins, which is the convention every other editor uses.
   *
   * `Math.round` because `position.x` is declared `int` server-side and `120.5`
   * is a hard 422 (R12). Nodes already on the line are still included in the
   * move list; `moveNodes` writes one snapshot either way, and filtering them
   * out would make the undo label lie about what it restores.
   */
  function alignSelection(mode: AlignMode): void {
    const boxes = selectionBoxes()
    if (boxes.length < 2) return
    const anchor = boxes.find((box) => box.id === anchorId.value) ?? null
    const horizontal = mode === 'left' || mode === 'centerX' || mode === 'right'

    const edgeOf = (box: SelectionBox): number => {
      switch (mode) {
        case 'left':
          return box.x
        case 'right':
          return box.x + box.width
        case 'centerX':
          return box.x + box.width / 2
        case 'top':
          return box.y
        case 'bottom':
          return box.y + box.height
        case 'centerY':
          return box.y + box.height / 2
      }
    }

    let target: number
    if (anchor) target = edgeOf(anchor)
    else if (mode === 'left' || mode === 'top') target = Math.min(...boxes.map(edgeOf))
    else if (mode === 'right' || mode === 'bottom') target = Math.max(...boxes.map(edgeOf))
    else target = boxes.reduce((sum, box) => sum + edgeOf(box), 0) / boxes.length

    store.moveNodes(
      boxes.map((box) => {
        const delta = target - edgeOf(box)
        return {
          id: box.id,
          position: {
            x: Math.round(box.x + (horizontal ? delta : 0)),
            y: Math.round(box.y + (horizontal ? 0 : delta)),
          },
        }
      }),
    )
  }

  /**
   * Equal GAPS between three or more nodes, as ONE commit (§4.3).
   *
   * Gaps rather than equal centres, which is the other reading and the wrong
   * one here: the cards differ in height, so equal centres leaves visibly
   * uneven whitespace between boxes that are the thing an author is actually
   * looking at. The two extremes never move - they define the span - so
   * distribute is idempotent and pressing it twice is not a slow drift.
   */
  function distributeSelection(axis: DistributeAxis): void {
    const boxes = selectionBoxes()
    if (boxes.length < 3) return
    const horizontal = axis === 'horizontal'
    const start = (box: SelectionBox): number => (horizontal ? box.x : box.y)
    const extent = (box: SelectionBox): number => (horizontal ? box.width : box.height)

    const ordered = [...boxes].sort((a, b) => start(a) - start(b))
    const first = ordered[0]
    const last = ordered[ordered.length - 1]
    const span = start(last) + extent(last) - start(first)
    const occupied = ordered.reduce((sum, box) => sum + extent(box), 0)
    // A negative gap means the cards overlap end to end. Spreading them by a
    // negative step is arithmetically fine and visually a shuffle, so the
    // control declines rather than doing something the author did not ask for.
    const gap = (span - occupied) / (ordered.length - 1)
    if (!Number.isFinite(gap) || gap < 0) return

    let cursor = start(first)
    store.moveNodes(
      ordered.map((box) => {
        const at = Math.round(cursor)
        cursor += extent(box) + gap
        return {
          id: box.id,
          position: horizontal ? { x: at, y: box.y } : { x: box.x, y: at },
        }
      }),
    )
  }

  function dispose(): void {
    if (flashTimer !== null) clearTimeout(flashTimer)
    flashTimer = null
    if (landingTimer !== null) clearTimeout(landingTimer)
    landingTimer = null
    bridge = null
  }

  return {
    nodes,
    edges,
    selectedNodeIds,
    selectedEdgeIds,
    selectedNodes,
    selectedIds,
    selectionSize,
    anchorId,
    hoveredNodeId,
    announcement,
    connectDrag,
    linkMode,
    filterQuery,
    portMenuRequest,
    gridSnapping,
    isValidConnection,
    onConnectStart,
    onConnectEnd,
    onConnect,
    cancelPortMenu,
    cancelConnect,
    requestRename,
    noteRenameStarted,
    beginLink,
    cycleLink,
    commitLink,
    onSelectionChange,
    notePointerDown,
    notePointerMove,
    onNodeClick,
    selectNode,
    selectEdge,
    selectAll,
    clearSelection,
    setSelection,
    dropKind,
    hitTestNode,
    connectPreview,
    createAt,
    insertKind,
    onNodeDragStart,
    onNodeDrag,
    onNodeDragStop,
    onEdgeUpdate,
    nudge,
    alignSelection,
    distributeSelection,
    deleteSelection,
    toggleJoin,
    focusNode,
    focusProblem,
    traverse,
    cycleSibling,
    fitView,
    zoomToActual,
    zoomToSelection,
    centreOn,
    viewportCentre,
    attachViewport,
    detachViewport,
    dispose,
  }
}

export type BuilderCanvas = ReturnType<typeof useBuilderCanvas>

/** The chip on an edge, drawn only where a source has more than one way out (§5.4). */
function portLabelFor(source: BuilderNode | undefined, edge: BuilderEdge): string | null {
  if (!source) return null
  if (source.kind !== 'gate' && source.kind !== 'router') return null
  return edge.source_port
}

function portRoleFor(
  source: BuilderNode | undefined,
  // `Pick`, not the whole edge, because the dangling connection line has a
  // source port and no edge at all - and the role of a port is a fact about the
  // port. Widening the parameter is what lets the preview and the committed
  // edge be provably the same answer rather than two implementations of it.
  edge: Pick<BuilderEdge, 'source_port'>,
): BuilderEdgeData['portRole'] {
  if (!source) return null
  if (source.kind === 'gate') return edge.source_port === 'revise' ? 'revise' : 'approve'
  if (source.kind !== 'router') return null
  const branch = source.config.branches.find((candidate) => candidate.label === edge.source_port)
  return branch?.op === 'otherwise' ? 'otherwise' : 'branch'
}
