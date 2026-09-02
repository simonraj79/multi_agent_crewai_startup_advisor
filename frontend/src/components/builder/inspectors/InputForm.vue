<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Target } from 'lucide-vue-next'
import { nodeId } from '../../../types/builder'
import type { BuilderDocument, BuilderNode, BuilderVocabulary, NodeId } from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import NodeIdField from '../fields/NodeIdField.vue'
import { coalesceKeyFor, patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * The `input` node: what `POST /api/sessions/{id}/runs` must carry, and how the
 * console asks for it.
 *
 * The badge at the top is the whole reason this form is not just four boxes.
 * `document.input_field` has to equal EXACTLY ONE input node's `config.field`,
 * and a graph with two input nodes is legal - so the commonest state an author
 * reaches after dropping a second one is `input-field-undeclared`, a document
 * that validates as broken because of a fact about a field they have not
 * scrolled to. The one-click fix is here, next to the field it is about, rather
 * than in graph settings where the problem's sentence would send them.
 *
 * `config.field` is NOT refused when another input node already uses it, even
 * though this widget knows. `input-field-ambiguous` is Tier 2 (§6.1): the server
 * owns every count and every cross-object judgement, and a client that refused
 * it would be a second opinion that disagrees with the compiler the first time
 * the rule moves. The pattern - and only the pattern - is refused here, because
 * that one is a 422 rather than a Problem.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'input' }>
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{ commit: [change: InspectorCommit] }>()

const id = computed(() => props.node.id)
const config = computed(() => props.node.config)
const control = (name: string) => `insp-${id.value}-${name}`

/* --- field ------------------------------------------------------------- */

const fieldDraft = ref<string>(config.value.field)
watch(config, (next) => {
  fieldDraft.value = next.field
})

function commitField(value: string): void {
  emit('commit', {
    label: 'Rename input field',
    next: patchConfig(props.doc, props.node, { field: nodeId(value) }),
  })
}

/* --- the run input ------------------------------------------------------ */

const isRunInput = computed(() => props.doc.input_field === config.value.field)

function makeRunInput(): void {
  emit('commit', {
    label: 'Set the run input',
    next: { ...props.doc, input_field: config.value.field as NodeId },
  })
}

/* --- label, bounds, required ------------------------------------------- */

const labelDraft = ref<string>(config.value.label ?? '')
watch(config, (next) => {
  labelDraft.value = next.label ?? ''
})

/**
 * An empty box means null, not the empty string.
 *
 * `InputConfig.label` is `Label | None` with `min_length=1`, so committing `''`
 * is a 422 - and null is the honest reading anyway: the author deleted the
 * prompt rather than asking for a blank one.
 */
function commitLabel(): void {
  const trimmed = labelDraft.value.trim()
  const next = trimmed === '' ? null : trimmed
  if (next === config.value.label) return
  emit('commit', {
    label: 'Set input prompt',
    next: patchConfig(props.doc, props.node, { label: next }),
    coalesceKey: coalesceKeyFor(id.value, 'label'),
  })
}

const maxChars = computed(() => props.vocabulary.bounds.max_input_chars)

function commitMaxChars(event: Event): void {
  const raw = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(raw)) return
  const clamped = Math.min(Math.max(Math.round(raw), 1), maxChars.value)
  if (clamped === config.value.max_chars) return
  emit('commit', {
    label: 'Set input length limit',
    next: patchConfig(props.doc, props.node, { max_chars: clamped }),
  })
}

function commitRequired(required: boolean): void {
  if (required === config.value.required) return
  emit('commit', {
    label: required ? 'Make the input required' : 'Make the input optional',
    next: patchConfig(props.doc, props.node, { required }),
  })
}
</script>

<template>
  <div class="inspector-form">
    <!-- Above the field it is about, because the sentence the server writes for
         `input-field-undeclared` names the document and this is the node that
         answers it. -->
    <div class="run-input" :class="{ 'is-current': isRunInput }">
      <Target :size="13" aria-hidden="true" />
      <template v-if="isRunInput">
        <span>This is the run input. A launch sends its text as <code>{{ config.field }}</code>.</span>
      </template>
      <template v-else>
        <span>The run input is <code>{{ doc.input_field }}</code>, not this node.</span>
        <button type="button" class="run-input-action" @click="makeRunInput">
          Make this the run input
        </button>
      </template>
    </div>

    <NodeIdField
      v-model="fieldDraft"
      :committed="config.field"
      :taken="[]"
      label="Request key"
      :control-id="control('field')"
      field="field"
      :node-id="id"
      subject="input"
      help="The key inside `inputs` on the launch request. Distinct from the node's canvas label."
      @commit="commitField"
    />

    <FieldRow
      label="Prompt"
      :control-id="control('label')"
      field="label"
      :node-id="id"
      :used="labelDraft.length"
      :max="vocabulary.bounds.max_label_chars"
      :warn-at="8"
      help="What the console asks for. Leave it empty and the box is labelled by the node instead."
      v-slot="row"
    >
      <input
        :id="control('label')"
        v-model="labelDraft"
        type="text"
        :maxlength="vocabulary.bounds.max_label_chars"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @keydown.enter.prevent="commitLabel"
        @blur="commitLabel"
      />
    </FieldRow>

    <FieldRow
      label="Length limit"
      :control-id="control('max_chars')"
      field="max_chars"
      :node-id="id"
      :help="`Characters accepted, up to the ${maxChars} the run endpoint itself allows.`"
      v-slot="row"
    >
      <input
        :id="control('max_chars')"
        type="number"
        min="1"
        :max="maxChars"
        step="1"
        :value="config.max_chars"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitMaxChars"
      />
    </FieldRow>

    <FieldRow
      label="Required"
      :control-id="control('required')"
      field="required"
      :node-id="id"
      group
      help="An optional input may be left empty, and every node reading it sees an empty string."
    >
      <div class="segmented">
        <button type="button" :aria-pressed="config.required" @click="commitRequired(true)">
          Required
        </button>
        <button type="button" :aria-pressed="!config.required" @click="commitRequired(false)">
          Optional
        </button>
      </div>
    </FieldRow>
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
.run-input { display: flex; align-items: flex-start; gap: 7px; margin-bottom: 16px; padding: 9px 10px; color: var(--text-muted); font-size: var(--fs-11); line-height: 1.5; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.run-input svg { flex: 0 0 auto; margin-top: 2px; }
.run-input code { color: var(--accent-cyan); font: 500 10px/1.4 var(--font-mono); }
/* Mint when it IS the run input: a statement of fact reads differently from an
   offer to change one, and the colour is the faster of the two signals. */
.run-input.is-current { color: var(--accent-mint); border-color: color-mix(in srgb, var(--accent-mint) 32%, transparent); background: color-mix(in srgb, var(--accent-mint) 8%, transparent); }
.run-input.is-current code { color: inherit; }
.run-input-action { margin-top: 6px; padding: 4px 8px; color: var(--text-title); font: 600 var(--fs-11)/1.3 var(--font-body); background: var(--surface-raised); border: 1px solid var(--border-default); border-radius: var(--r-sm); cursor: pointer; }
.run-input-action:hover { border-color: var(--border-hover); }
.run-input-action:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.run-input > span { flex: 1 1 auto; }
.run-input:not(.is-current) { display: grid; grid-template-columns: auto minmax(0, 1fr); }
.run-input:not(.is-current) .run-input-action { grid-column: 2; justify-self: start; }

</style>
