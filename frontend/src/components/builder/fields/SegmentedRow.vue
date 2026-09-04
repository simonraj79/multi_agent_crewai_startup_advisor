<script setup lang="ts">
import FieldRow from './FieldRow.vue'

/**
 * A closed set of two to four words, as the rail's own segmented control.
 *
 * Seven authored fields are a `Literal` of three or fewer members -
 * `response_format`, `reasoning_effort`, `tool_failure_policy`, `on_error`,
 * `process` - and a `<select>` for three visible options hides two of them
 * behind a click for no gain. The segmented pair already exists in the rail
 * (`FieldRow`'s `:deep(.segmented)` owns its look), so this is that control
 * with the nullable case and the capability gate added, not a new one.
 *
 * `aria-pressed` rather than `role="radiogroup"`. The buttons are what the rail
 * already uses at four other sites, the row is a labelled `group`, and a
 * radiogroup would bring arrow-key roving focus that none of the existing four
 * has - which would make two visually identical controls behave differently.
 *
 * NULL IS AN OPTION WHEN THE SCHEMA SAYS SO. `response_format`,
 * `reasoning_effort` and `tool_failure_policy` are all `… | None`, and the
 * absence means "CrewAI's default", which is a real choice rather than an
 * unset field. It is rendered as its own segment with its own word, so
 * clearing is one click and not a mystery.
 */
withDefaults(
  defineProps<{
    label: string
    controlId: string
    field: string
    nodeId?: string
    modelValue: string | null
    /** `{value, word}` in the order they should read. `value: null` is legal. */
    options: readonly { value: string | null; word: string }[]
    help?: string
    note?: string
    noteWarn?: boolean
    disabled?: boolean
    reason?: string
  }>(),
  { disabled: false, noteWarn: false },
)

const emit = defineEmits<{ commit: [value: string | null] }>()
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
    group
  >
    <div class="segmented" :title="disabled ? reason : undefined">
      <button
        v-for="option in options"
        :key="option.value ?? '__null__'"
        type="button"
        :aria-pressed="modelValue === option.value"
        :disabled="disabled"
        :aria-disabled="disabled ? 'true' : undefined"
        @click="option.value === modelValue ? undefined : emit('commit', option.value)"
      >
        {{ option.word }}
      </button>
    </div>
  </FieldRow>
</template>
