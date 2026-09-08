<script setup lang="ts">
/**
 * One row of a bar chart: a label, a track, a figure.
 *
 * `.agent/plans/17-admin-console.md` criterion 25 in full - `role="progressbar"`,
 * a tone CLASS rather than a colour, and a computed width. It is
 * `BudgetMeter.vue`'s track lifted whole, and lifting it rather than reaching
 * for a chart library is the point: **`frontend/package.json` does not move**
 * (D6, and the plan repeats it), so every picture on this screen is markup this
 * repository already knows how to theme, print and read aloud.
 *
 * ONE HUE PER CHART, and the hue is the chart's subject rather than the row's
 * value: `--accent-cyan` is money, `--accent-mint` is people, `--warn-*` and
 * `--err-*` are refusals and errors. A bar that changed colour with its own
 * size would be a fifth signal nobody asked for, and `docs/design.md` §7's
 * distinction is the reason - an accent as a FILL is identity, not a verdict.
 *
 * A zero total renders no fill at all rather than a full bar or an empty one:
 * `shareOf` answers null, `aria-valuenow` is omitted, and the row still carries
 * its label and its figure. A percentage of nothing is undefined, not zero.
 */
import { computed } from 'vue'
import { shareOf } from './adminFormat'

const props = withDefaults(
  defineProps<{
    label: string
    /** The row's own quantity, in whatever unit the chart is about. */
    value: number
    /** What the whole chart adds up to, for the width. */
    total: number
    /** The figure to print at the end of the row, already formatted. */
    display?: string
    tone?: 'money' | 'people' | 'warn' | 'err'
    /** A second line under the label - a model's call count, a workflow's runs. */
    hint?: string | null
  }>(),
  { tone: 'money', display: '', hint: null },
)

const share = computed(() => shareOf(props.value, props.total))
const width = computed(() => (share.value === null ? 0 : share.value))
</script>

<template>
  <li class="admin-bar" :class="`is-${tone}`">
    <span class="admin-bar-label" :title="label">
      {{ label }}
      <span v-if="hint" class="admin-bar-hint">{{ hint }}</span>
    </span>
    <span
      class="admin-bar-track"
      role="progressbar"
      :aria-label="label"
      :aria-valuemin="0"
      :aria-valuemax="100"
      :aria-valuenow="share === null ? undefined : Math.round(share)"
      :aria-valuetext="`${label}: ${display || value}`"
    >
      <span class="admin-bar-fill" :style="{ width: `${width}%` }" />
    </span>
    <span class="admin-bar-value">
      <slot name="value">{{ display || value }}</slot>
    </span>
  </li>
</template>
