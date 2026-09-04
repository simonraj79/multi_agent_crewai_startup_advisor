<script setup lang="ts">
import { computed, ref } from 'vue'
import { Save, Trash2 } from 'lucide-vue-next'
import type { TestInput } from '../../../types/builder'

/**
 * The one input box, the saved-input list, and the two ways to add to it (D3).
 *
 * ONE FIELD, not a form. A builder flow takes exactly one input key - its
 * document's `input_field`, and `bounds.py` refuses a document with two - so a
 * generated form over a schema would be a form with one row and a false promise
 * of more. The plan's out-of-scope list says the same thing about a chat-shaped
 * tester for the same reason.
 *
 * "USE LAST RUN'S OUTPUTS AS MOCKS" is a checkbox on the save and not a button
 * of its own, because it is a property of the row being written rather than an
 * action: the label, the value and the mocks are one row, and offering the
 * mocks separately would imply a second row could hold them.
 */

const props = defineProps<{
  inputs: TestInput[]
  selectedId: string | null
  value: string
  field: string
  /** A finished run whose outputs could seed mocks, or null. */
  lastRunId: string | null
  saving?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  (event: 'update:value', value: string): void
  (event: 'select', id: string | null): void
  (event: 'save', label: string, fromLastRun: boolean): void
  (event: 'delete', id: string): void
}>()

const label = ref('')
const withMocks = ref(false)

const canSave = computed(() => label.value.trim().length > 0 && !props.saving)

function save(): void {
  if (!canSave.value) return
  emit('save', label.value.trim(), withMocks.value && props.lastRunId !== null)
  label.value = ''
}
</script>

<template>
  <div class="test-input">
    <label class="test-input-field">
      <span class="test-input-legend">{{ field }}</span>
      <textarea
        class="test-input-box"
        data-testid="test-input-value"
        rows="2"
        :value="value"
        :disabled="disabled"
        :aria-label="`Value for ${field}`"
        @input="emit('update:value', ($event.target as HTMLTextAreaElement).value)"
      />
    </label>

    <div class="test-input-saved">
      <label class="test-input-picker">
        <span class="test-input-legend">Saved</span>
        <select
          class="test-input-select"
          data-testid="test-input-select"
          :value="selectedId ?? ''"
          aria-label="Saved test inputs"
          @change="emit('select', ($event.target as HTMLSelectElement).value || null)"
        >
          <option value="">—</option>
          <option v-for="row in inputs" :key="row.id" :value="row.id">{{ row.label }}</option>
        </select>
      </label>

      <button
        v-if="selectedId"
        type="button"
        class="test-input-delete"
        data-testid="test-input-delete"
        :aria-label="`Delete the saved input ${inputs.find((row) => row.id === selectedId)?.label ?? ''}`"
        @click="emit('delete', selectedId)"
      >
        <Trash2 :size="13" aria-hidden="true" />
      </button>
    </div>

    <form class="test-input-save" @submit.prevent="save">
      <input
        v-model="label"
        class="test-input-label"
        data-testid="test-input-label"
        type="text"
        maxlength="80"
        placeholder="Save this as…"
        aria-label="A name for this saved input"
      >
      <label v-if="lastRunId" class="test-input-mocks">
        <input v-model="withMocks" type="checkbox" data-testid="test-input-mocks">
        <span>use the last run's outputs as mocks</span>
      </label>
      <button type="submit" class="test-input-submit" data-testid="test-input-save" :disabled="!canSave">
        <Save :size="13" aria-hidden="true" />
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.test-input { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.test-input-field { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.test-input-legend {
  color: var(--text-40);
  font: 600 var(--fs-11)/1.3 var(--font-mono);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.test-input-box {
  width: 100%;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
  background: var(--surface-well);
  color: var(--text-body);
  font: 400 var(--fs-12)/1.5 var(--font-body);
  resize: vertical;
}
.test-input-box:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

.test-input-saved { display: flex; gap: 6px; align-items: flex-end; min-width: 0; }
.test-input-picker { display: flex; flex: 1 1 auto; min-width: 0; flex-direction: column; gap: 4px; }
.test-input-select,
.test-input-label {
  width: 100%;
  min-width: 0;
  padding: 5px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
  background: var(--surface-well);
  color: var(--text-body);
  font: 400 var(--fs-12)/1.4 var(--font-body);
}
.test-input-delete,
.test-input-submit {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  padding: 5px 9px;
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
  background: var(--surface-raised);
  color: var(--text-body);
  font: 500 var(--fs-11)/1.4 var(--font-body);
  cursor: pointer;
}
.test-input-delete:hover,
.test-input-submit:hover:not(:disabled) { border-color: var(--border-hover); }
.test-input-submit:disabled { opacity: 0.45; cursor: default; }

.test-input-save { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; min-width: 0; }
.test-input-label { flex: 1 1 140px; }
.test-input-mocks {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  color: var(--text-muted);
  font: 400 var(--fs-11)/1.4 var(--font-body);
}
</style>
