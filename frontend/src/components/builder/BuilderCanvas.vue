<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, provide, ref, shallowRef, watch } from 'vue'
import { Background } from '@vue-flow/background'
import { ControlButton, Controls } from '@vue-flow/controls'
import { ConnectionMode, SelectionMode, VueFlow, getBezierPath, useVueFlow } from '@vue-flow/core'
import type { Position } from '@vue-flow/core'
import type { EdgeMouseEvent, EdgeUpdateEvent, NodeDragEvent, NodeMouseEvent } from '@vue-flow/core'
import { Maximize, Minus, Plus } from 'lucide-vue-next'
import BuilderMinimap from './BuilderMinimap.vue'
import SelectionToolbar from './SelectionToolbar.vue'
import type { MinimapNode } from './BuilderMinimap.vue'
import { NODE_KINDS, NODE_KIND_ORDER } from '../../data/nodeKinds'
import {
  BUILDER_CANVAS_ATTR,
  BUILDER_DND_MIME,
  BUILDER_HOVERED_NODE,
  BUILDER_READ_ONLY,
  BUILDER_SELECTED_IDS,
  DEFAULT_NODE_HEIGHT,
  DEFAULT_NODE_WIDTH,
} from '../../composables/useBuilderCanvas'
import type { BuilderCanvas } from '../../composables/useBuilderCanvas'
import type { AlignMode, DistributeAxis } from '../../composables/useBuilderCanvas'
import type { EdgeId, NodeId, NodeKind } from '../../types/builder'

/**
 * The `<VueFlow>` host, and nothing else.
 *
 * Every gesture below is wired to `useBuilderCanvas` rather than implemented
 * here, which keeps the whole of the canvas's behaviour testable without a DOM
 * (R2 again: the library does the pointers, the composable does the meaning,
 * and this file does the wiring). What genuinely lives here is the handful of
 * things that need a mounted instance: the viewport bridge, the alignment
 * guides, and the two `provide`s that carry hover and selection to the cards
 * without rebuilding the elements arrays.
 *
 * `id="builder-flow"` is load-bearing. `useVueFlow` keys per-instance state by
 * id, and `StudioView` mounts `studio-flow`; sharing an id would let one view's
 * viewport, selection and node lookup leak into the other's the moment both
 * exist in one session (§1.3).
 *
 * THE NODE AND EDGE RENDERERS ARRIVE AS SLOTS. `BuilderNode` and `BuilderEdge`
 * belong to a different work package, and importing them here would make this
 * file uncompilable until that one landed. Forwarding Vue Flow's own
 * `#node-builder` / `#edge-builder` slots outward is the same registration by a
 * seam the shell fills, and it is what lets a spec mount this canvas against a
 * one-line stub.
 *
 * `:auto-pan-on-connect="false"` is a REFUSAL of a Vue Flow default, and it is
 * the one prop here whose absence was measured as a defect. The default is
 * `true`: hold a connection near the pane edge and the viewport accelerates
 * away, measured at ~670 px/s - 1,606 px of travel in 2.4 s, the entire graph
 * off the top of the screen while the author is still holding the button - and
 * returning the pointer to the centre does not bring it back. It also made the
 * acceptance suite's very first drag time out with "element is not stable",
 * because the target handle was drifting ~0.67 px per animation frame under a
 * hover that waits for stillness. Section 4.2 describes no auto-pan, and a
 * canvas that runs away from a gesture is worse than one that makes the author
 * pan first.
 */

const props = defineProps<{
  canvas: BuilderCanvas
  /** The document's name, for the canvas's own accessible name. */
  label?: string
  /**
   * A stored version that is not head is on screen (plan 15 D3).
   *
   * The store's `readOnly` lock already refuses every commit, so nothing here
   * is load-bearing for safety - this is what stops Vue Flow from DRAWING a
   * drag the store will then refuse: a card that follows the pointer and snaps
   * back on release reads as a broken canvas, where a card that will not lift
   * reads as a locked one. Selection stays on, because reading v3 is the
   * point of opening it.
   */
  readOnly?: boolean
  /**
   * The shell's dock row - the strips that sit above this canvas in the layout
   * (round 2, D-15-2). Observed beside the frame so a strip OPENING re-fits the
   * graph it just shrank, and nothing else after the author's first gesture
   * does. An element rather than a height, because the observer is the one
   * thing here that measures.
   */
  dock?: HTMLElement | null
  /**
   * The docked test panel BELOW this canvas (13 D1).
   *
   * A second observed element rather than a second meaning for `dock`, because
   * the two sit on opposite sides of the graph and only their effect on its
   * height is shared: opening the test panel takes 260px from the canvas
   * exactly as opening the version browser does, and the fit is owed for the
   * same reason. Everything else about the rule - never mid-gesture, only on a
   * GROW after the author's first gesture - is unchanged and is why this is a
   * prop here rather than an observer in the panel.
   */
  panel?: HTMLElement | null
  /**
   * `design` while the author is drawing, `run` while a test run streams into
   * this canvas (13 D2).
   *
   * The handover costs no JavaScript at all - one attribute, and
   * `builder.css`'s `[data-mode='run']` block outranks the seven kind
   * gradients by a single extra attribute of specificity. Those rules shipped
   * with the card and had no writer until now; §5.1 wrote them expecting
   * exactly this.
   */
  mode?: 'design' | 'run'
}>()

const flow = useVueFlow('builder-flow')
const frame = ref<HTMLElement | null>(null)

/**
 * The composable's window on the mounted instance.
 *
 * Attached on mount and detached on unmount, so a `focusNode` arriving from a
 * problem row after the view has gone is a no-op rather than a call into a
 * disposed d3 zoom behaviour.
 */
onMounted(() => {
  props.canvas.attachViewport({
    screenToFlowCoordinate: (point) => flow.screenToFlowCoordinate(point),
    fitView: (options) => flow.fitView(options),
    setCenter: (x, y, options) => flow.setCenter(x, y, options),
    zoomTo: (zoom, options) => flow.zoomTo(zoom, options),
    getViewport: () => flow.getViewport(),
    getPaneSize: () => ({ width: flow.dimensions.value.width, height: flow.dimensions.value.height }),
    // The RENDERED box, not the assumed one: align-bottom over cards of
    // different heights is only correct against what each card actually
    // measures. `findNode` answers `undefined` for a node the library has not
    // mounted yet, and the composable falls back to the §5.2 defaults.
    getNodeSize: (id) => {
      const measured = flow.findNode(id)?.dimensions
      return measured && measured.width > 0 ? { width: measured.width, height: measured.height } : null
    },
  })
})

/**
 * Re-fit while the canvas is still settling into its final height - and again
 * whenever the layout takes height AWAY from it later.
 *
 * `fit-view-on-init` and the shell's own post-load fit both compute against
 * whatever this element measures AT THAT INSTANT, and at that instant it is
 * still full-bleed: the budget meter sits in `.graph-workspace`'s `auto` row
 * and the problems dock below it, and neither has taken its height yet. So the
 * first fit is honest arithmetic about a box that stops existing one frame
 * later. Measured on the 16-node validator template, the fits chose 0.544 then
 * 0.524 while the settled container wanted 0.466 - each time leaving the last
 * two nodes under the dock, on a canvas that reported itself fitted.
 *
 * An observer rather than a longer wait, because "long enough" is a guess about
 * someone else's layout and this is the actual signal.
 *
 * WHAT THE AUTHOR'S FIRST GESTURE ENDS is the settling phase, not the
 * observer (round 2, D-15-2). It used to disconnect outright, so that a late
 * settling re-fit could never throw away a pan the author had just made - and
 * the same rule then left the canvas blind to every layout change afterwards.
 * Round 1 measured what that cost: the version browser docking 125px above
 * the graph hid 2 of 5 nodes below the canvas bottom, and the delete confirm
 * docked beneath it hid 3 of 5 - an operator confirming a delete could not see
 * most of the graph they were deleting. The rule now has two halves:
 *
 * - before the first gesture, any change to THIS frame re-fits, as before;
 * - after it, only the DOCK re-fits, and only when it GROWS - a strip the
 *   author asked for (versions, the delete confirm, the restore bar, the
 *   import notice) has just taken height from the graph, and the fit is owed.
 *   A dock closing hides nothing, so the viewport stays where they put it.
 *
 * Why the dock and not "any shrink". The first cut of this rule re-fitted on
 * every shrink of the frame, and the problems panel is under the frame too:
 * it grows 400ms after a node is placed, as the validate answer lands, and the
 * re-fit moved the canvas under the author's next drag. Measured on
 * `e2e/builder.spec.ts`'s router-branch test, six runs each: 2 of 6 failed
 * with that rule, 0 of 6 without it - the drag that should have wired the
 * router's `match` port started where the port had been a frame earlier.
 * A human would meet the same jolt on every edit that changed the problem
 * count. The dock changes only when the author opens something, which is the
 * one moment a re-fit is what they want.
 *
 * And never mid-gesture: a re-fit that lands while a pointer is down is a
 * canvas running away from a drag, which is the worse bug this observer was
 * first written not to cause. It waits for the pointer to lift.
 */
/**
 * The zoom below which a node's title stops being readable (round 3, D-15-2).
 *
 * Round 2 fixed the round-1 half of this row - a docked strip pushed nodes off
 * the bottom without re-fitting - and the fix traded hidden for unreadable:
 * the re-fit now honoured every dock, so at 1440x900 the cards went 186px, then
 * 136 with the Versions panel, 116 with the read-only banner added and 100 with
 * the delete strip beneath, and the titles with them, down to about 7px. The
 * row's subject is that the operator cannot see the graph they are about to
 * delete, and a graph rendered at 7px is not seen.
 *
 * `.builder-title` is 15px CSS and the fit scales it, so the rendered size is
 * `15 * zoom` and an 11px floor is `11 / 15`. Eleven is the smallest size this
 * repo already treats as legible - it is `--fs-11`, what the eyebrow and every
 * meta row use.
 *
 * WHAT THIS TRADES, deliberately. Below the floor the fit no longer shows
 * every node, and the ones it cannot keep are reachable by a pan - which is
 * the trade the row's ruling names. A graph too big to be both whole and
 * legible has to give up one of them, and "whole" is the one the author can
 * recover with a drag.
 *
 * Not applied to the FIT button. That is the author asking to see everything
 * at once, and answering "no, here is part of it larger" would be refusing the
 * one request the control exists to serve.
 */
const MIN_LEGIBLE_ZOOM = 11 / 15

/**
 * The initial fit's options. `minZoom` for the same reason `refit` carries it:
 * a fit on init is one nobody asked for, so it keeps the title legible and
 * leaves the rest to a pan.
 *
 * A constant rather than an inline object literal in the template, because the
 * comment explaining it cannot live inside a tag's attribute list - an HTML
 * comment there is a Vue compile error, `Duplicate attribute`, which presents
 * as the whole gallery failing to render.
 */
const initialFitOptions = { padding: 0.16, maxZoom: 1, minZoom: MIN_LEGIBLE_ZOOM }

let layoutObserver: ResizeObserver | null = null
/** The author has panned, zoomed or pressed on the canvas; the viewport is theirs. */
let settled = false
let pointerHeld = false
/** A shrink arrived while the pointer was down; owed on release. */
let refitOwed = false

function noteGesture(): void {
  settled = true
}

function refit(): void {
  if (pointerHeld) {
    refitOwed = true
    return
  }
  refitOwed = false
  flow.fitView({ padding: 0.14, minZoom: MIN_LEGIBLE_ZOOM })
}

onMounted(() => {
  if (typeof ResizeObserver === 'undefined' || !frame.value) return
  let lastFrame = 0
  let lastDock = 0
  layoutObserver = new ResizeObserver((entries) => {
    let owed = false
    for (const entry of entries) {
      const height = entry.contentRect.height
      if (entry.target === frame.value) {
        // Only a real change, and never the collapse to zero that unmounting shows.
        if (height <= 0 || Math.abs(height - lastFrame) < 1) continue
        lastFrame = height
        if (!settled) owed = true
      } else {
        // The dock. Zero is its resting state, so a change to zero is a strip
        // closing and a change from it a strip opening.
        if (Math.abs(height - lastDock) < 1) continue
        const grew = height > lastDock
        lastDock = height
        if (settled && grew) owed = true
      }
    }
    if (owed) refit()
  })
  layoutObserver.observe(frame.value)
  if (props.dock) layoutObserver.observe(props.dock)
  if (props.panel) layoutObserver.observe(props.panel)
})

/*
 * The dock usually arrives AFTER this component has mounted. It is a template
 * ref in the shell, and Vue assigns template refs in a post-render effect once
 * the whole tree is up - so at this component's own `onMounted` the prop is
 * still null, and an `observe` there alone observed nothing. Round 2's first
 * capture of the delete confirm showed exactly that: two strips docked, five
 * nodes, and the canvas sitting where it was. So the mount observes whatever
 * is there, and this watches for the element arriving, changing or going.
 * Not `immediate`: an immediate post-flush callback is queued from setup,
 * ahead of the mounted hook, and would run before the observer exists.
 */
watch(
  () => props.dock,
  (dock, previous) => {
    if (previous) layoutObserver?.unobserve(previous)
    if (dock) layoutObserver?.observe(dock)
  },
  { flush: 'post' },
)

/* The test panel arrives the same way and for the same reason - a template ref
   in the shell, assigned in a post-render effect after this component's own
   `onMounted` has already run. */
watch(
  () => props.panel,
  (panel, previous) => {
    if (previous) layoutObserver?.unobserve(previous)
    if (panel) layoutObserver?.observe(panel)
  },
  { flush: 'post' },
)

onBeforeUnmount(() => {
  layoutObserver?.disconnect()
  layoutObserver = null
  props.canvas.detachViewport()
})

/**
 * Vue Flow's selection, mirrored into the composable.
 *
 * There is no `selectionChange` hook - selection travels as `select` entries
 * inside `nodesChange`, which is the same stream position changes arrive on and
 * which invariant 4 forbids this canvas from listening to. Watching the two
 * getters reads the settled answer instead of filtering a change list, and the
 * composable's `sameMembers` guard is what stops the round trip from looping.
 */
watch(
  [flow.getSelectedNodes, flow.getSelectedEdges],
  ([nodes, edges]) => props.canvas.onSelectionChange({ nodes, edges }),
)

/* --- hover, published rather than passed ---------------------------------- */

provide(BUILDER_HOVERED_NODE, props.canvas.hoveredNodeId)
provide(BUILDER_SELECTED_IDS, computed(() => props.canvas.selectedIds.value))
provide(BUILDER_READ_ONLY, computed(() => props.readOnly === true))

function onNodeEnter({ node }: NodeMouseEvent): void {
  props.canvas.hoveredNodeId.value = node.id
}

function onNodeLeave(): void {
  props.canvas.hoveredNodeId.value = null
}

/* --- pointer bookkeeping -------------------------------------------------- */

function onPointerDown(event: PointerEvent): void {
  // The viewport is the author's from here. See `noteGesture`.
  noteGesture()
  pointerHeld = true
  props.canvas.notePointerDown(event)
}

function onPointerMove(event: PointerEvent): void {
  props.canvas.notePointerMove(event)
}

/** The gesture ended; a re-fit the layout owed during it lands now. */
function onPointerUp(): void {
  pointerHeld = false
  if (refitOwed) refit()
}

function onNodeClick({ event, node }: NodeMouseEvent): void {
  if (event instanceof MouseEvent) props.canvas.onNodeClick(node.id as NodeId, event)
}

function onEdgeClick({ event, edge }: EdgeMouseEvent): void {
  const additive = event instanceof MouseEvent && (event.shiftKey || event.metaKey || event.ctrlKey)
  props.canvas.selectEdge(edge.id as EdgeId, additive ? 'add' : 'replace')
}

/* --- the palette drop ----------------------------------------------------- */

const KINDS = new Set<string>(NODE_KIND_ORDER)

/**
 * A kind dragged off the palette.
 *
 * The read is validated against the kind list rather than trusted, because
 * `dataTransfer` is a public channel: anything on the page - or off it - can be
 * dropped here, and `newNode` on an unknown kind is a crash in a `switch` the
 * type system was told is exhaustive.
 */
function onDrop(event: DragEvent): void {
  event.preventDefault()
  const raw =
    event.dataTransfer?.getData(BUILDER_DND_MIME) || event.dataTransfer?.getData('text/plain') || ''
  if (!KINDS.has(raw)) return
  props.canvas.dropKind(raw as NodeKind, { x: event.clientX, y: event.clientY })
  // The drag started on a palette tile, so that is where focus still is - and
  // the arrow keys are gated on the canvas having it. Taking focus here is what
  // makes "drop a node, then nudge it into place" work without a click nobody
  // would think to make.
  frame.value?.focus()
}

function onDragOver(event: DragEvent): void {
  // Without a `preventDefault` on dragover the browser refuses the drop
  // outright, and the failure is silent: the tile animates back to the palette
  // and nothing anywhere reports why.
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}

/* --- alignment guides ----------------------------------------------------- */

interface Guide {
  id: string
  x1: number
  y1: number
  x2: number
  y2: number
}

const guides = shallowRef<Guide[]>([])

/**
 * Six pixels of SCREEN, converted into flow units by dividing by the zoom.
 *
 * A raw flow-unit threshold is the mistake worth naming: at 0.4 zoom - the
 * fitted view of a graph with a fan-out - six flow units is two pixels and the
 * guides never appear, while at 2x they appear for anything vaguely nearby. The
 * author's tolerance is in pixels, so the constant is too.
 */
const GUIDE_THRESHOLD_PX = 6
/** At most two per axis, so a dense graph does not draw a barcode. */
const MAX_GUIDES_PER_AXIS = 2

/**
 * The alignment guides for a drag in flight, in container-local pixels.
 *
 * Computed from Vue Flow's measured `dimensions` rather than from `NODE_W`, so
 * a router that has grown a fourth port aligns on the edges it actually has.
 * Screen conversion is done here rather than through `flowToScreenCoordinate`
 * because these lines live in an overlay that is a sibling of the transformed
 * pane, so what is wanted is the pane transform alone: `flow * zoom + pan`.
 */
function computeGuides(event: NodeDragEvent): void {
  const viewport = flow.viewport.value
  const threshold = GUIDE_THRESHOLD_PX / viewport.zoom
  const moving = new Set(event.nodes.map((node) => node.id))
  if (moving.size === 0) moving.add(event.node.id)

  const rects = flow.getNodes.value.map((node) => ({
    id: node.id,
    moving: moving.has(node.id),
    left: node.position.x,
    top: node.position.y,
    width: node.dimensions.width || DEFAULT_NODE_WIDTH,
    height: node.dimensions.height || DEFAULT_NODE_HEIGHT,
  }))
  const dragged = rects.filter((rect) => rect.moving)
  const others = rects.filter((rect) => !rect.moving)
  if (dragged.length === 0 || others.length === 0) {
    guides.value = []
    return
  }

  const found: Guide[] = []
  for (const axis of ['x', 'y'] as const) {
    const candidates: { at: number; from: number; to: number }[] = []
    for (const rect of dragged) {
      for (const other of others) {
        for (const edge of edgesOf(rect, axis)) {
          for (const target of edgesOf(other, axis)) {
            if (Math.abs(edge - target) > threshold) continue
            candidates.push({
              at: target,
              from: Math.min(span(rect, axis)[0], span(other, axis)[0]),
              to: Math.max(span(rect, axis)[1], span(other, axis)[1]),
            })
          }
        }
      }
    }
    const seen = new Set<number>()
    for (const candidate of candidates) {
      if (seen.has(candidate.at)) continue
      if (seen.size >= MAX_GUIDES_PER_AXIS) break
      seen.add(candidate.at)
      const at = candidate.at * viewport.zoom + (axis === 'x' ? viewport.x : viewport.y)
      const from = candidate.from * viewport.zoom + (axis === 'x' ? viewport.y : viewport.x)
      const to = candidate.to * viewport.zoom + (axis === 'x' ? viewport.y : viewport.x)
      found.push(
        axis === 'x'
          ? { id: `x${candidate.at}`, x1: at, y1: from, x2: at, y2: to }
          : { id: `y${candidate.at}`, x1: from, y1: at, x2: to, y2: at },
      )
    }
  }
  guides.value = found
}

/** The three alignment edges of a rect on one axis: near, centre, far. */
function edgesOf(
  rect: { left: number; top: number; width: number; height: number },
  axis: 'x' | 'y',
): number[] {
  return axis === 'x'
    ? [rect.left, rect.left + rect.width / 2, rect.left + rect.width]
    : [rect.top, rect.top + rect.height / 2, rect.top + rect.height]
}

/** How far a rect reaches along the OTHER axis, so a guide spans both cards. */
function span(
  rect: { left: number; top: number; width: number; height: number },
  axis: 'x' | 'y',
): [number, number] {
  return axis === 'x' ? [rect.top, rect.top + rect.height] : [rect.left, rect.left + rect.width]
}

/**
 * True between `@node-drag-start` and `@node-drag-stop`.
 *
 * §4.3 hides the `SelectionToolbar` "during any drag", and this is the only
 * signal for it: `guides` goes empty whenever nothing is within the snap
 * threshold, so a drag with no guide would look like no drag at all and the bar
 * would flicker back under the pointer mid-gesture.
 */
const dragging = ref(false)

function onDragStart(event: NodeDragEvent): void {
  dragging.value = true
  props.canvas.onNodeDragStart(event)
  computeGuides(event)
}

function onDrag(event: NodeDragEvent): void {
  props.canvas.onNodeDrag(event)
  computeGuides(event)
}

function onDragStop(event: NodeDragEvent): void {
  dragging.value = false
  guides.value = []
  props.canvas.onNodeDragStop(event)
}

function onEdgeUpdate(event: EdgeUpdateEvent): void {
  props.canvas.onEdgeUpdate({ edge: event.edge, connection: event.connection })
}

/* --- the minimap's input -------------------------------------------------- */

const minimapNodes = computed<MinimapNode[]>(() =>
  props.canvas.nodes.value.map((node) => {
    const measured = flow.findNode(node.id)
    return {
      id: node.id,
      x: node.position.x,
      y: node.position.y,
      width: measured?.dimensions.width || DEFAULT_NODE_WIDTH,
      height: measured?.dimensions.height || DEFAULT_NODE_HEIGHT,
      accent: NODE_KINDS[node.data.node.kind].accent,
      severity: node.data.severity,
      selected: Boolean(node.selected),
    }
  }),
)

const minimapViewport = computed(() => flow.viewport.value)
const minimapPane = computed(() => ({
  width: flow.dimensions.value.width,
  height: flow.dimensions.value.height,
}))

/* --- the align / distribute toolbar (§4.3) -------------------------------- */

/**
 * The selection's bounding box in PANE pixels, or `null` when there is nothing
 * to align.
 *
 * Computed here rather than in the composable because it is the one part of
 * align that genuinely needs the mounted instance: `dimensions` is what Vue
 * Flow measured and the viewport transform is what turns flow units into the
 * pixels the bar has to sit at. The geometry that MOVES nodes stays in
 * `useBuilderCanvas`, where a spec can drive it with no DOM at all.
 */
const selectionRect = computed(() => {
  if (dragging.value || props.canvas.connectDrag.value !== null) return null
  const selected = props.canvas.selectedNodeIds.value
  if (selected.size < 2) return null
  const { x: panX, y: panY, zoom } = flow.viewport.value
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const node of props.canvas.nodes.value) {
    if (!selected.has(node.id as NodeId)) continue
    const measured = flow.findNode(node.id)?.dimensions
    const width = measured?.width || DEFAULT_NODE_WIDTH
    const height = measured?.height || DEFAULT_NODE_HEIGHT
    minX = Math.min(minX, node.position.x)
    minY = Math.min(minY, node.position.y)
    maxX = Math.max(maxX, node.position.x + width)
    maxY = Math.max(maxY, node.position.y + height)
  }
  if (!Number.isFinite(minX)) return null
  return {
    x: minX * zoom + panX,
    y: minY * zoom + panY,
    width: (maxX - minX) * zoom,
    height: (maxY - minY) * zoom,
  }
})

function onAlign(mode: AlignMode): void {
  props.canvas.alignSelection(mode)
}

function onDistribute(axis: DistributeAxis): void {
  props.canvas.distributeSelection(axis)
}

/* --- Space-to-pan, the half Vue Flow does not finish (§4.5) --------------- */

/**
 * True while the space bar is held, and the reason `pan-on-drag` is a computed.
 *
 * §4.3 wants a plain left-drag on the empty pane to MARQUEE, which in Vue Flow
 * 1.48 means `selection-key-code="true"` plus a `pan-on-drag` that excludes
 * button 0 - and that takes the left button away from panning, which §4.5 says
 * Space is supposed to give back. Vue Flow's own `panActivationKeyCode`
 * (default `Space`) does half of it: measured, holding space correctly drops
 * `.selection` off the pane so a drag no longer marquees, and then the drag
 * does nothing at all, because the d3 filter still refuses button 0. Widening
 * `pan-on-drag` to `true` for exactly as long as the key is down is the
 * remaining half, and it is still Vue Flow doing the panning (R2) - this is one
 * boolean, not a pointer layer.
 *
 * Scoped to `keyup`/`blur` as well as `keydown`, because a key released while
 * the window is not focused never sends a `keyup` and the canvas would be stuck
 * unable to marquee for the rest of the session.
 */
const spaceHeld = ref(false)

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.isContentEditable ||
    target.tagName === 'INPUT' ||
    target.tagName === 'TEXTAREA' ||
    target.tagName === 'SELECT'
  )
}

function onSpaceDown(event: KeyboardEvent): void {
  if (event.code !== 'Space' || event.repeat || isTypingTarget(event.target)) return
  spaceHeld.value = true
}

function onSpaceUp(event: KeyboardEvent): void {
  if (event.code === 'Space') spaceHeld.value = false
}

function releaseSpace(): void {
  spaceHeld.value = false
}

onMounted(() => {
  window.addEventListener('keydown', onSpaceDown)
  window.addEventListener('keyup', onSpaceUp)
  window.addEventListener('blur', releaseSpace)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onSpaceDown)
  window.removeEventListener('keyup', onSpaceUp)
  window.removeEventListener('blur', releaseSpace)
})

/**
 * `true` (every button pans) while space is held; middle and right otherwise.
 *
 * Left is deliberately absent from the resting value: it belongs to the
 * marquee, which is what §4.3 asks for and what a plain drag did nothing at all
 * for before - measured, a corner-to-corner unmodified drag selected nothing
 * and moved the viewport instead.
 */
const panOnDrag = computed<boolean | number[]>(() => (spaceHeld.value ? true : [1, 2]))

/** §5.6: the empty document's one centred line, and only while it is empty. */
const isEmptyDocument = computed(() => props.canvas.nodes.value.length === 0)

/* --- the dangling connection line (D3) ----------------------------------- */

/** How far above the cursor the port label rides, so the pointer never covers it. */
const CONNECTION_LABEL_OFFSET_PX = 12

/**
 * The preview's classes: its edge class, and its port role when it has one.
 *
 * Both come from `useBuilderCanvas.connectPreview`, which reads the same
 * `outPortsOf` and `portRoleFor` the card and the committed edge read - so the
 * colour of the line an author is dragging is provably the colour of the edge
 * they are about to make.
 */
const connectionLineClasses = computed(() => {
  const preview = props.canvas.connectPreview.value
  if (!preview) return []
  return [`is-class-${preview.edgeClass}`, preview.role ? `is-${preview.role}` : '']
})

/** The same bezier the committed edge will draw, so the preview does not lie. */
function connectionPath(line: {
  sourceX: number
  sourceY: number
  sourcePosition: Position
  targetX: number
  targetY: number
  targetPosition: Position
}): string {
  return getBezierPath({
    sourceX: line.sourceX,
    sourceY: line.sourceY,
    sourcePosition: line.sourcePosition,
    targetX: line.targetX,
    targetY: line.targetY,
    targetPosition: line.targetPosition,
  })[0]
}

const isConnecting = computed(() => props.canvas.connectDrag.value !== null)
const isHovering = computed(() => props.canvas.hoveredNodeId.value !== null)
</script>

<template>
  <div
    ref="frame"
    class="builder-canvas"
    :class="{ 'is-connecting': isConnecting, 'is-hovering': isHovering, 'is-read-only': readOnly }"
    :[BUILDER_CANVAS_ATTR]="''"
    :data-mode="mode ?? 'design'"
    role="application"
    tabindex="0"
    :aria-label="label ? `Flow builder canvas for ${label}` : 'Flow builder canvas'"
    @pointerdown="onPointerDown"
    @pointerup="onPointerUp"
    @pointercancel="onPointerUp"
    @wheel="noteGesture"
    @pointermove="onPointerMove"
    @drop="onDrop"
    @dragover="onDragOver"
  >
    <VueFlow
      id="builder-flow"
      class="builder-flow"
      :nodes="canvas.nodes.value"
      :edges="canvas.edges.value"
      :nodes-draggable="!readOnly"
      :nodes-connectable="!readOnly"
      :elements-selectable="true"
      :edges-updatable="!readOnly"
      :snap-to-grid="canvas.gridSnapping.value"
      :snap-grid="[20, 20]"
      :selection-mode="SelectionMode.Partial"
      :selection-key-code="true"
      :auto-pan-on-connect="false"
      :pan-on-drag="panOnDrag"
      :multi-selection-key-code="['Shift', 'Control', 'Meta']"
      :connection-mode="ConnectionMode.Strict"
      :is-valid-connection="canvas.isValidConnection"
      :delete-key-code="null"
      :min-zoom="0.2"
      :max-zoom="2"
      :default-viewport="{ x: 0, y: 0, zoom: 0.8 }"
      :fit-view-on-init="true"
      :fit-view-options="initialFitOptions"
      :zoom-on-double-click="false"
      @connect-start="canvas.onConnectStart"
      @click-connect-start="canvas.onConnectStart"
      @connect="canvas.onConnect"
      @connect-end="canvas.onConnectEnd"
      @click-connect-end="canvas.onConnectEnd"
      @node-click="onNodeClick"
      @node-mouse-enter="onNodeEnter"
      @node-mouse-leave="onNodeLeave"
      @node-drag-start="onDragStart"
      @node-drag="onDrag"
      @node-drag-stop="onDragStop"
      @selection-drag-start="onDragStart"
      @selection-drag="onDrag"
      @selection-drag-stop="onDragStop"
      @edge-click="onEdgeClick"
      @edge-update="onEdgeUpdate"
      @pane-click="canvas.clearSelection"
    >
      <template #node-builder="nodeProps">
        <slot name="node" v-bind="nodeProps" />
      </template>
      <template #edge-builder="edgeProps">
        <slot name="edge" v-bind="edgeProps" />
      </template>

      <!--
        D3's dangling line: tinted by the source port's class, and carrying the
        port's own name when the source has more than one way out.

        Flowise does this (`ConnectionLine.jsx`) and its notes say why it
        matters - a drag from a two-branch node never lands on the wrong branch.
        Here it matters more, because a router can have four ports and they are
        four identical discs along one edge; without the label the author finds
        out which one they grabbed by releasing.

        `getBezierPath` rather than Vue Flow's default straight line, so the
        preview has the shape the committed edge will have. The label is an SVG
        `<text>` and not an HTML overlay: `EdgeLabelRenderer` is for mounted
        edges and this line does not exist as one yet.
      -->
      <template #connection-line="line">
        <g class="builder-connection-line" :class="connectionLineClasses">
          <path :d="connectionPath(line)" class="builder-connection-path" />
          <text
            v-if="canvas.connectPreview.value?.label"
            class="builder-connection-label"
            :x="line.targetX"
            :y="line.targetY - CONNECTION_LABEL_OFFSET_PX"
            text-anchor="middle"
          >
            {{ canvas.connectPreview.value?.label }}
          </text>
        </g>
      </template>

      <Background :gap="20" :size="1" color="#777777" pattern-color="#777777" />

      <!--
        Named, because the stock ones are not. `<Controls>` renders three
        `<button>`s each wrapping a bare `<svg>` with no title and no text, so a
        screen reader announces "button, button, button" - the only three
        unnamed interactive elements in a builder where every other icon button
        carries an `aria-label`. The `control-*` slots replace the whole button,
        which is what lets a name be attached at all; `ControlButton` keeps the
        library's own class and styling, so this is a label rather than a
        reimplementation. Inherited from `StudioView`, and fixed there too.
      -->
      <Controls position="bottom-left" :show-interactive="false">
        <template #control-zoom-in>
          <ControlButton class="vue-flow__controls-zoomin" aria-label="Zoom in" @click="flow.zoomIn()">
            <Plus :size="12" :stroke-width="2.5" aria-hidden="true" />
          </ControlButton>
        </template>
        <template #control-zoom-out>
          <ControlButton class="vue-flow__controls-zoomout" aria-label="Zoom out" @click="flow.zoomOut()">
            <Minus :size="12" :stroke-width="2.5" aria-hidden="true" />
          </ControlButton>
        </template>
        <template #control-fit-view>
          <ControlButton
            class="vue-flow__controls-fitview"
            aria-label="Fit the graph to the view"
            @click="canvas.fitView()"
          >
            <Maximize :size="12" :stroke-width="2.5" aria-hidden="true" />
          </ControlButton>
        </template>
      </Controls>
    </VueFlow>

    <!--
      Guides sit above the pane and below the chrome, and are `aria-hidden`
      because they say nothing a screen reader user can act on - the position
      they describe is announced by the node itself when the drag ends.
    -->
    <svg v-if="guides.length" class="builder-guides" aria-hidden="true">
      <line
        v-for="guide in guides"
        :key="guide.id"
        :x1="guide.x1"
        :y1="guide.y1"
        :x2="guide.x2"
        :y2="guide.y2"
      />
    </svg>

    <!--
      §5.6, "Canvas, empty document": one centred mono line, no illustration.
      It was missing entirely, so choosing "Blank canvas" opened a dot grid with
      no affordance anywhere in it and the only hint that `1`-`7` exist was the
      number badges in the palette, a rail away.
    -->
    <p v-if="isEmptyDocument" class="builder-canvas-hint">
      Drag a kind from the palette, or press <kbd>1</kbd>–<kbd>7</kbd>
    </p>

    <!--
      §4.3's floating align / distribute bar. Above a multi-selection, gone
      during a drag, and gone again the moment the selection drops below two -
      the same "appears when it has something to act on" rule the badge row on
      the card follows.
    -->
    <SelectionToolbar
      v-if="selectionRect"
      :rect="selectionRect"
      :count="canvas.selectedNodeIds.value.size"
      @align="onAlign"
      @distribute="onDistribute"
    />

    <BuilderMinimap
      :nodes="minimapNodes"
      :viewport="minimapViewport"
      :pane="minimapPane"
      @centre="canvas.centreOn"
      @fit="canvas.fitView()"
    />

    <!-- `PortMenu`, and anything else the shell wants anchored to the canvas. -->
    <slot name="overlay" />

    <!--
      Tab traversal has no visible cursor of its own - it selects a node and
      centres the viewport - so without this a screen reader user pressing Tab
      hears silence and has no way to know where they are.
    -->
    <p class="visually-hidden" role="status" aria-live="polite">{{ canvas.announcement.value }}</p>
  </div>
</template>

<style scoped>
.builder-canvas {
  position: relative;
  min-height: 0;
  overflow: hidden;
  background: var(--canvas-bg);
}

.builder-canvas:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 1px var(--accent-cyan);
}

.builder-flow { width: 100%; height: 100%; }

.builder-guides {
  position: absolute;
  inset: 0;
  z-index: var(--z-rail);
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.builder-guides line {
  stroke: var(--accent-cyan);
  stroke-width: 1;
  stroke-dasharray: 4 3;
  opacity: 0.75;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>
