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
import { BUILDER_HOVERED_NODE } from '../../composables/useBuilderCanvas'

const props = defineProps<EdgeProps<BuilderEdgeData>>()

const emit = defineEmits<{
  /** The port chip was activated: select the router that owns this branch. */
  (event: 'select-branch', payload: { nodeId: string; port: string }): void
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
    :class="[
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
    <path class="builder-edge-hit" :d="path" />
    <BaseEdge :id="id" :path="path" :marker-end="markerEnd" class="builder-edge-path" />
    <path v-if="data?.active" :d="path" class="builder-edge-traversal" />
    <path v-if="data?.joinTarget" :d="bracket" class="builder-edge-bracket" />

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
