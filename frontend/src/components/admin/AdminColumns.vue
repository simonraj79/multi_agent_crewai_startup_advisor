<script setup lang="ts">
/**
 * Spend per day, as inline SVG columns.
 *
 * The one chart on this screen that is genuinely two-dimensional - a series
 * over time - and criterion 25 says how it is drawn: **inline SVG**, no
 * dependency, `role="progressbar"` on each mark, a tone class, a computed
 * width. Every column is `fill="currentColor"` and the hue comes from the
 * chart's own class, so the whole picture is one token and the light theme
 * reaches it like anything else.
 *
 * `preserveAspectRatio="none"` with a 100x40 user-space box: the columns
 * stretch to whatever width the panel gives them and the height is CSS's. That
 * is what lets the chart be responsive with no measurement, no
 * `ResizeObserver` and no second render - the trap `BuilderCanvas.vue` paid for
 * once by fitting a viewport that had not settled.
 *
 * EACH COLUMN IS A `progressbar`, not the chart. A reader tabbing a screen
 * reader through this gets seven readings with a day and a figure each; a
 * single `img` with an alt string would give them one sentence somebody wrote.
 */
import { computed } from 'vue'

export interface ColumnPoint {
  key: string
  label: string
  value: number
  /** The already-formatted figure, so this component never spells money. */
  display: string
}

const props = withDefaults(
  defineProps<{
    points: ColumnPoint[]
    tone?: 'money' | 'people' | 'warn' | 'err'
    /** The axis label printed above the plot, e.g. `USD`. */
    unit?: string
  }>(),
  { tone: 'money', unit: '' },
)

/** The tallest column, or 0 when every day is empty. */
const peak = computed(() => props.points.reduce((high, point) => Math.max(high, point.value), 0))

const BOX_WIDTH = 100
const BOX_HEIGHT = 40
/** A hairline for an empty day, so a gap in the series is visibly a zero and
 *  not a missing bucket. */
const FLOOR = 0.6

const columns = computed(() => {
  const n = props.points.length
  if (n === 0) return []
  const slot = BOX_WIDTH / n
  const barWidth = Math.max(slot * 0.62, 0.5)
  return props.points.map((point, index) => {
    const share = peak.value > 0 ? point.value / peak.value : 0
    const height = Math.max(FLOOR, share * BOX_HEIGHT)
    return {
      ...point,
      x: index * slot + (slot - barWidth) / 2,
      y: BOX_HEIGHT - height,
      width: barWidth,
      height,
      percent: Math.round(share * 100),
    }
  })
})
</script>

<template>
  <figure class="admin-columns" :class="`is-${tone}`">
    <span v-if="unit" class="admin-columns-unit">{{ unit }}</span>
    <svg
      class="admin-columns-plot"
      :viewBox="`0 0 ${BOX_WIDTH} ${BOX_HEIGHT}`"
      preserveAspectRatio="none"
      role="group"
      aria-label="Spend per day"
    >
      <rect
        v-for="column in columns"
        :key="column.key"
        class="admin-column"
        :x="column.x"
        :y="column.y"
        :width="column.width"
        :height="column.height"
        fill="currentColor"
        role="progressbar"
        :aria-label="column.label"
        :aria-valuemin="0"
        :aria-valuemax="100"
        :aria-valuenow="column.percent"
        :aria-valuetext="`${column.label}: ${column.display}`"
      />
    </svg>
    <figcaption class="admin-columns-axis">
      <span v-for="column in columns" :key="column.key" class="admin-columns-tick">
        {{ column.label }}
      </span>
    </figcaption>
    <p v-if="points.length === 0" class="admin-columns-empty">
      Nothing in this window. That is a measured zero, not a missing figure.
    </p>
  </figure>
</template>
