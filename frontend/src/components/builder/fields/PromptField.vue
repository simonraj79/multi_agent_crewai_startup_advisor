<script setup lang="ts">
import { ref, watch } from 'vue'
import FieldRow from './FieldRow.vue'

/**
 * One free-text prompt an author wrote - a role, a goal, a backstory, a task
 * description, a template. 04 D2's `PromptField`.
 *
 * THE BOUND COMES FROM THE SERVER, NOT FROM HERE. `max` is
 * `vocabulary.bounds.max_prompt_chars`, which is `BUILDER_MAX_PROMPT_CHARS`
 * served rather than duplicated (R6). A constant in this file would be a second
 * opinion that silently disagrees with `document.py`'s `Prompt` annotation the
 * first time the constant moves, and the way an author would find out is a 422
 * about a box they were told was fine.
 *
 * THE COUNTER RAISES ITS VOICE INSIDE THE LAST 200. `maxlength` is a hard stop
 * that discards keystrokes with NO feedback at all, so a counter that read the
 * same at 3,800 and at 4,000 would be the only warning anybody got - which is
 * the reasoning `serverLimits.ts` already wrote for the idea box, applied to
 * the field an author spends the most time in.
 *
 * IT COMMITS ON BLUR, NOT ON EVERY KEYSTROKE, and it carries a `coalesceKey` so
 * the commits it does make collapse into one undo step. A prompt is the one
 * control in this rail somebody types a paragraph into; a commit per character
 * would be a hundred entries in a ring sized for decisions.
 *
 * `required` is what tells an empty box from an absent one. `role`, `goal` and
 * `backstory` are `min_length=1` in the schema, so clearing one is a 422 rather
 * than a null; `system_template` and its two siblings are genuinely nullable,
 * and clearing one is how an author says "use CrewAI's own". The two shapes
 * cannot share a commit path, so they do not.
 */
const props = withDefaults(
  defineProps<{
    label: string
    controlId: string
    /** As `FIELD_CODES` and C8's `field` spell it: `role`, `task.description`. */
    field: string
    nodeId?: string
    /** The stored value. `null` only where the schema admits one. */
    modelValue: string | null
    /** `vocabulary.bounds.max_prompt_chars`. Never a local constant. */
    max: number
    help?: string
    /**
     * Whether the schema refuses an empty string. When true, clearing the box
     * puts the stored value back rather than sending a 422 - the same repair
     * `InspectorRail` already makes for an emptied node label.
     */
    required?: boolean
    rows?: number
    placeholder?: string
    disabled?: boolean
  }>(),
  { required: false, rows: 3, disabled: false },
)

const emit = defineEmits<{ commit: [value: string | null] }>()

/**
 * A draft, so a paragraph is typed locally and committed once.
 *
 * Re-seeded whenever the stored value changes UNDER the field - an undo, a
 * version restore, another browser's save arriving. Without the watch a form
 * that had been typed into would go on showing the old text over a document
 * that had moved.
 */
const draft = ref(props.modelValue ?? '')
watch(
  () => props.modelValue,
  (value) => {
    draft.value = value ?? ''
  },
)

function commit(): void {
  const next = draft.value
  if (props.required && !next.trim()) {
    // `min_length=1` - an empty role is a 422, so the stored one goes back
    // rather than a save failing on a box the author cleared.
    draft.value = props.modelValue ?? ''
    return
  }
  // Empty means ABSENT on a nullable field. `''` and `null` round-trip
  // differently through the schema and only one of them parses.
  const value = next === '' ? null : next
  if (value === (props.modelValue ?? null)) return
  emit('commit', value)
}
</script>

<template>
  <FieldRow
    :label="label"
    :control-id="controlId"
    :field="field"
    :node-id="nodeId"
    :used="draft.length"
    :max="max"
    :warn-at="200"
    :help="help"
    v-slot="row"
  >
    <textarea
      :id="controlId"
      v-model="draft"
      :rows="rows"
      :maxlength="max"
      :placeholder="placeholder"
      :disabled="disabled"
      :aria-describedby="row.describedBy"
      :aria-invalid="row.invalid"
      spellcheck="true"
      @blur="commit"
    />
  </FieldRow>
</template>
