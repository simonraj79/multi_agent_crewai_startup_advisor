<script setup lang="ts">
import { computed } from 'vue'
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@vue-flow/core'
import HandoffToken from './HandoffToken.vue'
import type { StudioEdgeData } from '../composables/useValidatorRun'
import { humaniseCode } from '../utils/humanise'

const props = defineProps<EdgeProps<StudioEdgeData>>()

const emit = defineEmits<{
  /** The token finished its walk. Carries the edge id (plan 11 D3). */
  handoffDone: [string]
}>()

/**
 * The edge chip is the router's own event name: `service/graph.py` sets
 * `label = edge["router_event"]`, so `scope_approved` and `verdict_revise`
 * were painted on the canvas verbatim. The id stays in `data-code` - it is
 * what an E2E assertion and a bug report both want - and the reader gets
 * words.
 */
const chip = computed(() => {
  const raw = props.data?.label
  return typeof raw === 'string' && raw.trim() ? humaniseCode(raw) : ''
})

const route = computed(() => getBezierPath({
  sourceX: props.sourceX,
  sourceY: props.sourceY,
  sourcePosition: props.sourcePosition,
  targetX: props.targetX,
  targetY: props.targetY,
  targetPosition: props.targetPosition,
}))
</script>

<template>
  <g class="workflow-edge" :class="{ 'is-active': data?.active }">
    <BaseEdge :id="id" :path="route[0]" class="edge-base" />
    <path v-if="data?.active" :d="route[0]" class="edge-traversal" />
    <!--
      The message itself, when the run said one crossed here. The dashed march
      above stays: it is what a run WITHOUT `edge_traversal` frames still gets,
      and a backend one version behind must not lose its edge animation to a
      feature it does not emit.
    -->
    <HandoffToken
      v-if="data?.handoff"
      :key="data.handoff.startedAt"
      :path="route[0]"
      :handoff="data.handoff"
      :character="data.character ?? 1"
      @done="emit('handoffDone', $event)"
    />
    <EdgeLabelRenderer v-if="data?.label">
      <span
        class="edge-label"
        :data-code="data.label"
        :style="{ transform: `translate(-50%, -50%) translate(${route[1]}px, ${route[2]}px)` }"
      >
        {{ chip }}
      </span>
    </EdgeLabelRenderer>
  </g>
</template>

<style scoped>
:deep(.edge-base) {
  stroke: var(--edge-inactive);
  stroke-width: var(--edge-width);
  transition: stroke var(--motion-fast) ease, opacity var(--motion-fast) ease;
}

.workflow-edge.is-active :deep(.edge-base) { stroke: var(--accent-cyan); opacity: 1; }

.edge-traversal {
  fill: none;
  stroke: var(--accent-cyan);
  stroke-width: 2.5;
  stroke-linecap: round;
  stroke-dasharray: 7 13;
  filter: drop-shadow(0 0 5px color-mix(in srgb, var(--accent-cyan) 90%, transparent));
  pointer-events: none;
  animation: edge-march 0.75s linear infinite;
}

.edge-label {
  position: absolute;
  z-index: 4;
  padding: 3px 6px;
  color: var(--text-body);
  font: 600 var(--fs-11)/1.2 var(--font-mono);
  white-space: pre-line;
  background: var(--edge-label-bg);
  border: 1px solid var(--edge-label-brd);
  border-radius: var(--r-xs);
  pointer-events: none;
}

@keyframes edge-march { to { stroke-dashoffset: -20; } }

@media (prefers-reduced-motion: reduce) {
  .edge-traversal { animation: none; stroke-dasharray: none; }
}
</style>