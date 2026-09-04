<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Plus, X } from 'lucide-vue-next'
import type { BuilderDocument, JsonScalar, NodeId } from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import ScalarInput from '../fields/ScalarInput.vue'
import { coalesceKeyFor } from '../commit'

/**
 * `prompt_inputs` - the named values interpolated into a node's prompts.
 *
 * LIFTED OUT OF `BillableForm` UNCHANGED when plan 04 split the billable form
 * into a library arm and an authored one. All four billable forms carry this
 * field (`_BillableConfig` is where it lives), and a copy in each would be four
 * copies of the rename-in-place rule below - which is the sort of thing that
 * gets fixed in one copy.
 *
 * RENAMING REBUILDS THE MAP IN PLACE rather than deleting and re-adding. Order
 * is visible - these rows are drawn in insertion order and CrewAI's
 * interpolation reads them by name - so a rename that moved the row to the
 * bottom would look to the author like they had lost it.
 */
const props = defineProps<{
  doc: BuilderDocument
  /** Branded, because `ScalarInput` anchors problems by it and asks for the brand. */
  nodeId: NodeId
  value: Record<string, JsonScalar>
}>()

const emit = defineEmits<{
  commit: [inputs: Record<string, JsonScalar>, label: string, coalesceKey?: string]
}>()

const control = (name: string) => `insp-${props.nodeId}-${name}`

const rows = computed(() => Object.entries(props.value))

/** The key being renamed, and to what. One at a time - only one has focus. */
const keyDraft = ref<{ from: string; to: string } | null>(null)
watch(
  () => props.value,
  () => {
    keyDraft.value = null
  },
)

const keyHint = computed(() => {
  const draft = keyDraft.value
  if (!draft || draft.to === draft.from) return undefined
  if (!draft.to.trim()) return 'A prompt input needs a name.'
  if (draft.to in props.value) return `This node already supplies ${draft.to}.`
  return undefined
})

/** A fresh name no existing row holds, so adding twice does not overwrite once. */
function freeKey(): string {
  let index = 1
  while (`input_${index}` in props.value) index += 1
  return `input_${index}`
}

function addInput(): void {
  emit('commit', { ...props.value, [freeKey()]: '' }, 'Add prompt input')
}

function removeInput(key: string): void {
  const next: Record<string, JsonScalar> = {}
  for (const [name, value] of Object.entries(props.value)) {
    if (name !== key) next[name] = value
  }
  emit('commit', next, `Remove prompt input ${key}`)
}

function commitKey(): void {
  const draft = keyDraft.value
  keyDraft.value = null
  if (!draft || draft.to === draft.from || keyHint.value) return
  const next: Record<string, JsonScalar> = {}
  for (const [name, value] of Object.entries(props.value)) {
    next[name === draft.from ? draft.to : name] = value
  }
  emit('commit', next, `Rename prompt input to ${draft.to}`)
}

function commitValue(key: string, value: JsonScalar): void {
  emit(
    'commit',
    { ...props.value, [key]: value },
    `Set prompt input ${key}`,
    coalesceKeyFor(props.nodeId, `prompt_inputs.${key}`),
  )
}
</script>

<template>
  <FieldRow
    label="Prompt inputs"
    :control-id="control('prompt_inputs')"
    field="prompt_inputs"
    :node-id="nodeId"
    group
    :hint="keyHint"
    help="Interpolated into the task's own placeholders at kickoff. A value may be one resolvable state reference."
  >
    <div class="input-rows">
      <div v-for="[key, value] in rows" :key="key" class="input-row">
        <div class="input-key">
          <input
            type="text"
            class="key-box"
            spellcheck="false"
            autocomplete="off"
            :value="keyDraft && keyDraft.from === key ? keyDraft.to : key"
            :aria-label="`Name of prompt input ${key}`"
            @input="keyDraft = { from: key, to: ($event.target as HTMLInputElement).value }"
            @keydown.enter.prevent="commitKey"
            @blur="commitKey"
          />
          <button
            type="button"
            class="row-remove"
            :aria-label="`Remove prompt input ${key}`"
            @click="removeInput(key)"
          >
            <X :size="12" aria-hidden="true" />
          </button>
        </div>
        <ScalarInput
          :model-value="value"
          :doc="doc"
          :label="`${key} value`"
          :control-id="control(`prompt_inputs-${key}`)"
          :field="`prompt_inputs.${key}`"
          :node-id="nodeId"
          :where="`prompt_inputs['${key}']`"
          @commit="commitValue(key, $event)"
        />
      </div>
      <p v-if="!rows.length" class="empty-note">
        Nothing supplied yet. The task's placeholders arrive unfilled.
      </p>
      <button type="button" class="row-add" @click="addInput">
        <Plus :size="12" aria-hidden="true" />
        Add prompt input
      </button>
    </div>
  </FieldRow>
</template>

<style scoped>
.input-rows { display: grid; gap: 10px; }
/* A well per row, because a prompt input is a name AND a typed value and the
   two have to read as one thing - four unbounded controls in a column read as
   four fields. */
.input-row { padding: 9px 10px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.input-key { display: flex; align-items: center; gap: 6px; margin-bottom: 9px; }
.key-box { flex: 1 1 auto; min-width: 0; padding: 5px 7px; color: var(--accent-cyan); font: 600 var(--fs-12)/1.3 var(--font-mono); background: transparent; border: 1px solid transparent; border-radius: var(--r-sm); outline: 0; }
.key-box:hover { border-color: var(--border-default); }
.key-box:focus-visible { color: var(--text-title); border-color: var(--accent-cyan); box-shadow: var(--glow-input); }
.row-remove { display: grid; width: 22px; height: 22px; flex: 0 0 auto; place-items: center; padding: 0; color: var(--text-40); background: transparent; border: 0; border-radius: var(--r-sm); cursor: pointer; }
.row-remove:hover { color: var(--err-text); background: var(--err-bg); }
.row-remove:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.row-add { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 30px; color: var(--text-muted); font: 600 var(--fs-11)/1 var(--font-body); background: transparent; border: 1px dashed var(--border-default); border-radius: var(--r-md); cursor: pointer; transition: color var(--motion-fast) ease, border-color var(--motion-fast) ease; }
.row-add:hover { color: var(--text-title); border-color: var(--border-hover); }
.row-add:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.empty-note { margin: 0; color: var(--text-40); font-size: var(--fs-11); line-height: 1.5; }
</style>
