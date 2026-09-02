<script setup lang="ts">
import {
  AlignCenterHorizontal,
  AlignCenterVertical,
  AlignEndHorizontal,
  AlignEndVertical,
  AlignHorizontalDistributeCenter,
  AlignStartHorizontal,
  AlignStartVertical,
  AlignVerticalDistributeCenter,
} from 'lucide-vue-next'
import { computed } from 'vue'
import { ALIGN_MODES, DISTRIBUTE_AXES } from '../../composables/useBuilderCanvas'
import type { AlignMode, DistributeAxis } from '../../composables/useBuilderCanvas'

/**
 * §4.3's floating align / distribute toolbar, above a multi-selection.
 *
 * The last thing in §4.3 that had a spec sentence, a WP-G test row and no
 * component. §9's cut list is explicit that this is IN scope - "alignment guides
 * and the align/distribute toolbar sit on top of Vue Flow's drag; they do not
 * replace it" (R2) - so it is built rather than cut; only §2's file manifest
 * omitted it.
 *
 * IT COMPUTES NOTHING. The geometry lives in `useBuilderCanvas.alignSelection`
 * and `distributeSelection`, where it is testable without a DOM and where it can
 * reach `store.moveNodes` for the ONE commit per press §4.3 requires. This file
 * is eight buttons and a position.
 *
 * Hidden during a drag (`v-if` in `BuilderCanvas`), because a toolbar that
 * chases a card the author is holding is a target that moves as you reach for
 * it - and because align while dragging is a question with no answer.
 */
const props = defineProps<{
  /** The selection's bounding box in CANVAS pixels, already viewport-projected. */
  rect: { x: number; y: number; width: number; height: number }
  /** How many nodes are selected. Distribute needs three; align needs two. */
  count: number
}>()

const emit = defineEmits<{
  (event: 'align', mode: AlignMode): void
  (event: 'distribute', axis: DistributeAxis): void
}>()

/** Icon and accessible name per mode, in `ALIGN_MODES` order. */
const ALIGN_META: Record<AlignMode, { icon: unknown; label: string }> = {
  left: { icon: AlignStartVertical, label: 'Align left' },
  centerX: { icon: AlignCenterVertical, label: 'Align centres horizontally' },
  right: { icon: AlignEndVertical, label: 'Align right' },
  top: { icon: AlignStartHorizontal, label: 'Align top' },
  centerY: { icon: AlignCenterHorizontal, label: 'Align centres vertically' },
  bottom: { icon: AlignEndHorizontal, label: 'Align bottom' },
}

const DISTRIBUTE_META: Record<DistributeAxis, { icon: unknown; label: string }> = {
  horizontal: { icon: AlignHorizontalDistributeCenter, label: 'Distribute horizontally' },
  vertical: { icon: AlignVerticalDistributeCenter, label: 'Distribute vertically' },
}

/**
 * Above the selection, and clamped into the pane rather than off the top of it.
 *
 * A selection whose top edge is above the viewport would otherwise put the
 * toolbar off-screen - which is exactly the state a marquee across a tall graph
 * leaves you in, so it is the common case rather than the corner one. 8px of
 * clearance below the pane's top edge; the bar is `translateX(-50%)` in CSS so
 * only the centre needs computing.
 */
const style = computed(() => ({
  left: `${props.rect.x + props.rect.width / 2}px`,
  top: `${Math.max(8, props.rect.y - 44)}px`,
}))

/**
 * Distribute needs three nodes to mean anything: with two, the gap between them
 * is already the only gap. Disabled with the reason in the title rather than
 * hidden, so the bar does not change width as a selection grows - a control
 * that moves under the pointer between two presses is worse than one that is
 * briefly unavailable.
 */
const canDistribute = computed(() => props.count >= 3)
</script>

<template>
  <div class="builder-selection-toolbar" :style="style" role="toolbar" aria-label="Align and distribute">
    <button
      v-for="mode in ALIGN_MODES"
      :key="mode"
      type="button"
      class="builder-selection-action"
      :aria-label="ALIGN_META[mode].label"
      :title="ALIGN_META[mode].label"
      @click="emit('align', mode)"
    >
      <component :is="ALIGN_META[mode].icon" :size="14" :stroke-width="2" aria-hidden="true" />
    </button>

    <span class="builder-selection-rule" aria-hidden="true" />

    <button
      v-for="axis in DISTRIBUTE_AXES"
      :key="axis"
      type="button"
      class="builder-selection-action"
      :disabled="!canDistribute"
      :aria-label="DISTRIBUTE_META[axis].label"
      :title="
        canDistribute
          ? DISTRIBUTE_META[axis].label
          : `${DISTRIBUTE_META[axis].label} — needs three or more nodes`
      "
      @click="emit('distribute', axis)"
    >
      <component :is="DISTRIBUTE_META[axis].icon" :size="14" :stroke-width="2" aria-hidden="true" />
    </button>

    <span class="builder-selection-count">{{ count }}</span>
  </div>
</template>
