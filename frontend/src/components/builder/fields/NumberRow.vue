<script setup lang="ts">
import { computed } from 'vue'
import FieldRow from './FieldRow.vue'

/**
 * A bounded number, optionally nullable, optionally with a slider beside it.
 *
 * NULLABLE IS THE INTERESTING HALF. Eleven of the authored agent's numbers are
 * `int | None` or `float | None` in `document.py`, and the null is not a
 * missing value - it is "let CrewAI decide", which is a different and usually
 * better answer than any number this form could default to. So an empty box
 * commits `null` rather than being ignored or coerced to zero, and the
 * placeholder says what the absence means rather than showing a fake figure an
 * author would then believe was in effect.
 *
 * IT CLAMPS RATHER THAN REFUSING. `min` and `max` come from
 * `vocabulary.bounds` or from the schema's own literal ranges, and a value
 * outside them is pulled to the nearest end before it is committed. The
 * alternative - send it and let the server 422 - is worse in the one case that
 * matters: `type="number"` lets a paste put `900` in a 0..2 box, and a form
 * that accepts it and then reports a failure two seconds later has spent the
 * author's attention to tell them what it already knew.
 *
 * THE SLIDER IS A SECOND VIEW OF ONE VALUE, not a second control. D2 asks for
 * "slider + number" on `temperature`, `top_p` and the two penalties, because
 * those are the four an author explores rather than knows; both inputs write
 * the same field and both read it back.
 *
 * `disabled` + `reason` are D3's capability gate, and the stored value stays
 * rendered while it bites - see `SwitchRow` for why that is the whole point.
 */
const props = withDefaults(
  defineProps<{
    label: string
    controlId: string
    field: string
    nodeId?: string
    modelValue: number | null
    min: number
    max?: number
    /** `1` for a count, `0.05` for a probability. Also what the slider steps by. */
    step?: number
    /** Whether an empty box is legal, and commits `null`. */
    nullable?: boolean
    /** What an empty box means, in the author's words: "CrewAI's default". */
    placeholder?: string
    help?: string
    note?: string
    noteWarn?: boolean
    /** Render a range input beside the number, bound to the same value. */
    slider?: boolean
    disabled?: boolean
    reason?: string
  }>(),
  { step: 1, nullable: false, slider: false, disabled: false, noteWarn: false },
)

const emit = defineEmits<{ commit: [value: number | null] }>()

/** A slider has no null, so it rests at the low end when the value is absent. */
const sliderValue = computed(() => props.modelValue ?? props.min)

function clamp(raw: number): number {
  const low = Math.max(raw, props.min)
  const bounded = props.max === undefined ? low : Math.min(low, props.max)
  // Whole steps stay whole. `0.30000000000000004` in a temperature box is the
  // float artefact every slider produces, and rounding to the step is what
  // keeps the committed document readable.
  const places = props.step < 1 ? String(props.step).split('.')[1]?.length ?? 2 : 0
  return places ? Number(bounded.toFixed(places)) : Math.round(bounded)
}

function commitRaw(text: string): void {
  const trimmed = text.trim()
  if (!trimmed) {
    if (!props.nullable) return
    if (props.modelValue === null) return
    emit('commit', null)
    return
  }
  const raw = Number(trimmed)
  if (!Number.isFinite(raw)) return
  const next = clamp(raw)
  if (next === props.modelValue) return
  emit('commit', next)
}
</script>

<template>
  <FieldRow
    :label="label"
    :control-id="controlId"
    :field="field"
    :node-id="nodeId"
    :help="help"
    :note="note"
    :note-warn="noteWarn"
    :group="slider"
    v-slot="row"
  >
    <div class="number-row" :class="{ 'has-slider': slider }" :title="disabled ? reason : undefined">
      <input
        v-if="slider"
        class="number-slider"
        type="range"
        :min="min"
        :max="max"
        :step="step"
        :value="sliderValue"
        :disabled="disabled"
        :aria-disabled="disabled ? 'true' : undefined"
        :aria-label="`${label} slider`"
        @input="commitRaw(($event.target as HTMLInputElement).value)"
      />
      <input
        :id="controlId"
        type="number"
        :min="min"
        :max="max"
        :step="step"
        :value="modelValue ?? ''"
        :placeholder="placeholder"
        :disabled="disabled"
        :aria-disabled="disabled ? 'true' : undefined"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitRaw(($event.target as HTMLInputElement).value)"
      />
    </div>
  </FieldRow>
</template>

<style scoped>
.number-row { display: block; }
/* The number box is narrow beside a slider and full-width without one: 34px of
   digits is all `0.85` needs, and stretching it would make the slider the
   afterthought rather than the control being explored. */
.number-row.has-slider { display: grid; grid-template-columns: minmax(0, 1fr) 78px; align-items: center; gap: 9px; }
.number-slider { width: 100%; accent-color: var(--accent-cyan); cursor: pointer; }
.number-slider:disabled { cursor: not-allowed; opacity: 0.55; }
.number-slider:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 3px; }
</style>
