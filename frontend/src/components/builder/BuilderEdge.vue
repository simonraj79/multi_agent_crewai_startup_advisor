<script lang="ts">
import type { BuilderEdgeData as CanvasEdgeData } from '../../composables/useBuilderCanvas'

/**
 * The design-time edge.
 *
 * Three things here that ChatDev's canvas cannot express at all, and each is a
 * consequence of its edge identity being `${from}-${to}`:
 *
 *   1. Two edges between one pair of nodes. A gate's `approve` and `revise` may
 *      both land on the same node - a perfectly ordinary "review it, then carry
 *      on either way" - and an id keyed on the endpoints has nowhere to put the
 *      second one.
 *   2. A port label on the wire. Which of a router's four branches this edge IS
 *      is the single most useful fact about it, and it is drawn on the line
 *      rather than discovered by opening the node.
 *   3. A back edge that says so. `bounds.py` allows two cycles and refuses a
 *      third; a loop drawn identically to a forward edge makes that count
 *      something you infer rather than something you read.
 *
 * Like the card, this computes nothing. `portRole`, `backEdge`, `joinTarget`
 * and `severity` are all projected by `useBuilderCanvas`; hover is the one
 * thing decided here, because it is a property of the pointer rather than of
 * the document.
 */
export interface BuilderEdgeData extends CanvasEdgeData {
  /** Run tenancy: the run is traversing this edge right now. */
  active?: boolean
}
</script>

<script setup lang="ts">
import { computed, inject } from 'vue'
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@vue-flow/core'
import { X } from 'lucide-vue-next'
import { BUILDER_HOVERED_NODE } from '../../composables/useBuilderCanvas'

/**
 * How far BELOW the midpoint the delete button sits.
 *
 * The port chip is already at the midpoint, and on a gate's `revise` edge the
 * two would land on top of each other - the one edge where the label matters
 * most. Offsetting the button rather than the chip keeps the chip where every
 * other edge draws it.
 */
const DELETE_OFFSET_PX = 16

const props = defineProps<EdgeProps<BuilderEdgeData>>()

const emit = defineEmits<{
  /** The port chip was activated: select the router that owns this branch. */
  (event: 'select-branch', payload: { nodeId: string; port: string }): void
  /** The hover-only delete button was pressed. One commit, one undo step. */
  (event: 'delete', payload: { edgeId: string }): void
}>()

const route = computed(() =>
  getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  }),
)

const path = computed(() => route.value[0])
const labelX = computed(() => route.value[1])
const labelY = computed(() => route.value[2])

/* ─── class, paint and marker (§5.4, 02-canvas.md D4) ────────────────────── */

/**
 * Exactly one of the four, decided by `edgeClassOf` and projected in `data`.
 *
 * Not recomputed here. The class is a fact about the DOCUMENT's edge - which
 * port it left by and which it arrived at - and `useBuilderCanvas` is where
 * the document is read. A second derivation in the renderer would be a second
 * opinion about a string `bounds.py` also has an opinion about, which is three
 * copies of one rule.
 */
const edgeClass = computed(() => props.data?.edgeClass ?? 'flow')

/** Only a FLOW edge is painted by a gradient; the other three are one token each. */
const isFlow = computed(() => edgeClass.value === 'flow')

/**
 * A gradient per edge, source kind accent to target kind accent.
 *
 * Flowise v2 does exactly this (`AgentFlowEdge.jsx`) and it is the single best
 * thing about its canvas: the wire says where it came FROM at the end you are
 * looking at, so following a fan-in backwards is reading rather than tracing.
 * `userSpaceOnUse` with the real endpoint coordinates rather than the default
 * bounding-box units, so the ramp follows the edge's actual direction - in
 * object-bounding-box units a wire that runs right-to-left has its colours
 * reversed and says the opposite of what it means.
 */
const gradientId = computed(() => `edge-gradient-${props.id}`)
const markerId = computed(() => `edge-arrow-${props.id}`)

/**
 * `--edge-paint`, published on the group for `builder.css` to pick up.
 *
 * An inline `stroke` would be the obvious way and is the wrong one: it outranks
 * every stylesheet rule, so `has-error`, `is-lit-in`, `is-selected` and the
 * problem tints would all stop working on exactly the edges that carry a
 * gradient. A custom property is a VALUE the stylesheet chooses to use, so the
 * cascade still decides.
 */
const paintStyle = computed(() =>
  isFlow.value ? { '--edge-paint': `url(#${gradientId.value})` } : {},
)

/**
 * Flow and error edges carry an arrowhead; attach and member do not (D4).
 *
 * Because an arrow means "and then this happens". An attachment is a
 * possession, not a next step, and pointing an arrow at it would say the run
 * goes there. The marker is minted here rather than through Vue Flow's
 * `MarkerType`, so that it can be tinted with the target's own accent - the
 * arrow sits at the target end and any other colour would be a third thing to
 * explain.
 */
const hasArrow = computed(() => edgeClass.value === 'flow' || edgeClass.value === 'error')
const markerColor = computed(() =>
  edgeClass.value === 'error' ? 'var(--err-text)' : props.data?.targetAccent ?? 'currentColor',
)
const markerUrl = computed(() => (hasArrow.value ? `url(#${markerId.value})` : undefined))

/* ─── the hovered field (§5.4) ───────────────────────────────────────────── */

/**
 * Hover dims the FIELD rather than highlighting two sets against it.
 *
 * ChatDev lights the hovered node's edges at full strength on top of every
 * other edge at full strength, which reads fine on the eight-node example in
 * its README and visibly stops working past about fifteen: the highlight has
 * nothing to be brighter *than*. Dropping everything else to .22 works at any
 * density, because the contrast is manufactured rather than borrowed.
 *
 * The hovered id arrives through `inject`, so a mousemove touches one ref
 * instead of rebuilding the edges array and making Vue Flow re-parse every
 * element. Defaults to "nothing hovered" so an edge mounted outside a canvas
 * still renders.
 */
const hovered = inject(BUILDER_HOVERED_NODE, null)

/** `'out'` when this edge leaves the hovered node, `'in'` when it arrives at it. */
const lit = computed<'in' | 'out' | null>(() => {
  const id = hovered?.value ?? null
  if (id === null) return null
  if (props.source === id) return 'out'
  if (props.target === id) return 'in'
  return null
})

/**
 * Everything that is not lit while something IS hovered.
 *
 * Computed on the edge rather than driven by the canvas's `.is-hovering` class,
 * which §5.4 sketches. Both would render identically; this one owns both halves
 * of the decision, so the dimming cannot stop happening because a container
 * elsewhere stopped setting a class.
 */
const dim = computed(() => hovered?.value != null && lit.value === null)

/* ─── the port chip ──────────────────────────────────────────────────────── */

const chipText = computed(() => {
  const label = props.data?.portLabel
  if (!label) return null
  // The `↺` prefix, so a loop is legible on the line rather than inferred from
  // the dash pattern alone at a zoom level where 5-4 dashes read as solid.
  return props.data?.backEdge ? `↺ ${label}` : label
})

/**
 * A router's chip selects the router; a gate's does not.
 *
 * `approve` and `revise` are fixed ports with nothing to edit - `GateForm`
 * carries no branch list - so a gate chip is a label. A router's branch rows
 * are the thing the author would want, and `RouterBranchEditor` is one click
 * away once the node is selected. A control that does nothing is a lie the
 * second time somebody clicks it.
 */
const selectsBranch = computed(
  () => props.data?.portRole === 'branch' || props.data?.portRole === 'otherwise',
)

function selectBranch(): void {
  if (!selectsBranch.value || !props.data?.portLabel) return
  emit('select-branch', { nodeId: props.source, port: props.data.portLabel })
}

/* ─── the AND bracket (§5.4) ─────────────────────────────────────────────── */

/**
 * A small bracket above the target port when the target is an AND fan-in.
 *
 * Every inbound edge draws the same glyph at the same coordinates, so they
 * coincide into one mark rather than stacking - which is the honest drawing,
 * because AND is a property of the TARGET and not of any one edge that feeds
 * it. It is the same fact the card's `Σ` badge carries, drawn where the branches
 * actually meet.
 */
const bracket = computed(() => {
  const x = props.targetX
  const y = props.targetY
  return `M ${x - 11} ${y - 11} q 0 -7 11 -7 q 11 0 11 7`
})
</script>

<template>
  <g
    class="workflow-edge builder-edge"
    :style="paintStyle"
    :class="[
      `is-class-${edgeClass}`,
      {
        'is-dim': dim,
        'is-lit': lit !== null,
        'is-lit-in': lit === 'in',
        'is-lit-out': lit === 'out',
        'is-selected': selected,
        'is-back-edge': data?.backEdge,
        'is-active': data?.active,
        'has-error': data?.severity === 'error',
        'has-warning': data?.severity === 'warning',
      },
    ]"
  >
    <!--
      A 16px invisible stroke under the 1.2px visible one, so a hairline is
      grabbable. §4.2 needs each end draggable for a re-route, and a 1.2px
      pointer target is a target nobody hits on the first try - which is how an
      editor teaches people that edges cannot be re-routed at all.
    -->
    <defs>
      <linearGradient
        v-if="isFlow"
        :id="gradientId"
        gradientUnits="userSpaceOnUse"
        :x1="sourceX"
        :y1="sourceY"
        :x2="targetX"
        :y2="targetY"
      >
        <stop offset="0%" :stop-color="data?.sourceAccent" />
        <stop offset="100%" :stop-color="data?.targetAccent" />
      </linearGradient>
      <marker
        v-if="hasArrow"
        :id="markerId"
        markerWidth="9"
        markerHeight="9"
        refX="8"
        refY="4.5"
        orient="auto-start-reverse"
        markerUnits="strokeWidth"
      >
        <path d="M 0 1 L 8 4.5 L 0 8 z" :fill="markerColor" />
      </marker>
    </defs>

    <path class="builder-edge-hit" :d="path" />
    <BaseEdge :id="id" :path="path" :marker-end="markerUrl" class="builder-edge-path" />
    <path v-if="data?.active" :d="path" class="builder-edge-traversal" />
    <path v-if="data?.joinTarget" :d="bracket" class="builder-edge-bracket" />

    <!--
      The hover-only delete affordance (D4). Flowise v2 shows its delete button
      only on hover for the reason that applies here too: the validator template
      has 22 edges, and 22 always-visible buttons is a canvas of buttons rather
      than a graph. Keyboard users are unaffected - select the edge and press
      Delete - and the button is focusable, so it is reachable that way as well
      rather than being a pointer-only control.
    -->
    <EdgeLabelRenderer>
      <button
        type="button"
        class="builder-edge-delete nodrag nopan"
        :aria-label="`Delete edge ${id}`"
        :style="{
          transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY + DELETE_OFFSET_PX}px)`,
        }"
        @click.stop="emit('delete', { edgeId: id })"
      >
        <X :size="11" :stroke-width="2.5" aria-hidden="true" />
      </button>
    </EdgeLabelRenderer>

    <EdgeLabelRenderer v-if="chipText">
      <component
        :is="selectsBranch ? 'button' : 'span'"
        class="builder-edge-chip nodrag nopan"
        :class="[`is-${data?.portRole}`, { 'is-clickable': selectsBranch }]"
        :type="selectsBranch ? 'button' : undefined"
        :style="{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }"
        @click.stop="selectBranch"
        >{{ chipText }}</component
      >
    </EdgeLabelRenderer>
  </g>
</template>
