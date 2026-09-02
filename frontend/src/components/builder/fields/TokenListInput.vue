<script setup lang="ts">
import { computed, ref } from 'vue'
import { X } from 'lucide-vue-next'
import FieldRow from './FieldRow.vue'

/**
 * A list of short identifiers, entered as chips.
 *
 * The shape exists because the alternative for `editable_fields` is a
 * comma-separated text box, and a comma-separated text box has no answer to the
 * two things that go wrong with it: a trailing separator produces an empty
 * entry the schema refuses, and a name typed twice is a 422 the author only
 * meets on save. A chip is committed or it is not, and a duplicate is refused
 * at the moment it is typed - which is §6.1's Tier-1 rule "impossible by
 * construction" made literal.
 *
 * `duplicateMessage` is the SERVER's own sentence, passed in by the caller and
 * printed verbatim, so the widget's refusal and the compiler's refusal are the
 * same words rather than two paraphrases of one rule.
 */
const props = withDefaults(
  defineProps<{
    modelValue: readonly string[]
    label: string
    controlId: string
    field: string
    nodeId?: string
    help?: string
    /** What the schema calls one of these, for the pattern refusal sentence. */
    subject?: string
    /** The pattern every chip must match. Tier-1: a miss is a 422, never a Problem. */
    pattern?: RegExp
    /** The server's exact wording for a repeat, so both refusals read alike. */
    duplicateMessage: string
    placeholder?: string
  }>(),
  { subject: 'entry', pattern: () => /^[a-z][a-z0-9_]{0,39}$/, placeholder: 'Type and press Enter' },
)

const emit = defineEmits<{ commit: [value: string[]] }>()

const draft = ref('')

const hint = computed(() => {
  const value = draft.value.trim()
  if (!value) return undefined
  if (props.modelValue.includes(value)) return props.duplicateMessage
  if (!props.pattern.test(value)) {
    return `A ${props.subject} must start with a lowercase letter and use only lowercase letters, digits and underscores.`
  }
  return undefined
})

const addable = computed(() => Boolean(draft.value.trim()) && !hint.value)

function add(): void {
  if (!addable.value) return
  emit('commit', [...props.modelValue, draft.value.trim()])
  draft.value = ''
}

function removeAt(index: number): void {
  emit('commit', props.modelValue.filter((_, position) => position !== index))
}

/**
 * Backspace in an empty box takes the last chip back.
 *
 * Guarded on the box being empty, not on the caret being at position zero: a
 * caret at the start of "market" belongs to that word, and eating a chip there
 * would delete something the author is not looking at.
 */
function onBackspace(): void {
  if (draft.value === '' && props.modelValue.length) removeAt(props.modelValue.length - 1)
}
</script>

<template>
  <FieldRow
    :label="label"
    :control-id="controlId"
    :field="field"
    :node-id="nodeId"
    :help="help"
    :hint="hint"
    mono
    group
    v-slot="row"
  >
    <div class="token-list">
      <ul v-if="modelValue.length" class="tokens">
        <li v-for="(token, index) in modelValue" :key="token" class="token">
          <span>{{ token }}</span>
          <button
            type="button"
            class="token-remove"
            :aria-label="`Remove ${token}`"
            @click="removeAt(index)"
          >
            <X :size="11" aria-hidden="true" />
          </button>
        </li>
      </ul>
      <input
        :id="controlId"
        v-model="draft"
        type="text"
        spellcheck="false"
        autocomplete="off"
        autocapitalize="off"
        :placeholder="placeholder"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @keydown.enter.prevent="add"
        @keydown.backspace="onBackspace"
        @blur="add"
      />
    </div>
  </FieldRow>
</template>

<style scoped>
.token-list { display: block; }
.tokens { display: flex; flex-wrap: wrap; gap: 5px; margin: 0 0 7px; padding: 0; list-style: none; }
.token { display: inline-flex; align-items: center; gap: 4px; padding: 3px 4px 3px 7px; color: var(--accent-cyan); font: 500 10px/1.4 var(--font-mono); background: color-mix(in srgb, var(--accent-cyan) 12%, transparent); border: 1px solid color-mix(in srgb, var(--accent-cyan) 34%, transparent); border-radius: var(--r-pill); }
.token-remove { display: inline-grid; width: 15px; height: 15px; place-items: center; padding: 0; color: inherit; background: transparent; border: 0; border-radius: var(--r-full); cursor: pointer; transition: color var(--motion-fast) ease, background var(--motion-fast) ease; }
.token-remove:hover { color: var(--err-text); background: var(--err-bg); }
.token-remove:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
</style>
