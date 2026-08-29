<script setup lang="ts">
import { computed } from 'vue'
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@vue-flow/core'
import type { StudioEdgeData } from '../composables/useValidatorRun'

const props = defineProps<EdgeProps<StudioEdgeData>>()

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
    <EdgeLabelRenderer v-if="data?.label">
      <span
        class="edge-label"
        :style="{ transform: `translate(-50%, -50%) translate(${route[1]}px, ${route[2]}px)` }"
      >
        {{ data.label }}
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
  filter: drop-shadow(0 0 5px rgba(153, 234, 249, 0.9));
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