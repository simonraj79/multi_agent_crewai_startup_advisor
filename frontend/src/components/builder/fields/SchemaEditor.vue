<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ClipboardPaste, Plus, X } from 'lucide-vue-next'
import { NODE_ID_PATTERN } from '../../../types/builder'
import type { ScalarType } from '../../../types/builder'
import FieldRow from './FieldRow.vue'

/**
 * `task.output_schema` - the shape a task promises to answer in. 04 D2's
 * `SchemaEditor`, and Flowise's `ToolDialog.jsx` grid without its two dead
 * columns.
 *
 * FOUR TYPES, NOT SIX, AND TWO COLUMNS, NOT FOUR. 04 D2 asks for a grid of
 * property / type ∈ string|number|boolean|array|object / description /
 * required, with "Paste JSON". The schema disagrees and the schema wins
 * (MISSION §9's rule, and 00's own instruction for FD5):
 * `TaskConfig.output_schema` is `dict[NodeId, ScalarType] | None` - a FLAT map
 * of name to one of `string | number | integer | boolean`. There is nowhere to
 * put a description, nowhere to put `required`, and no `array` or `object` to
 * offer. The compiler builds a pydantic class out of this map with
 * `create_model`, and a nested schema would be a second document format inside
 * the document. Rendering the four missing controls would be rendering four
 * controls whose values are dropped on save, which is the exact competitor
 * behaviour the gauntlet names.
 *
 * "PASTE JSON" SURVIVES, and it is the half that earns its keep: an author with
 * a JSON Schema in their hand pastes it and gets the properties out, rather
 * than retyping eleven names. What it accepts is deliberately generous - a bare
 * `{name: "string"}` map, or a real JSON Schema with `properties` - and what it
 * does with a type it cannot express is state it rather than swallow it. An
 * `array` property silently dropped is how an author ships a task that answers
 * the wrong shape.
 *
 * NAMES ARE `NodeId`s. The map's keys are `NodeId`-annotated in `document.py`,
 * so `Total Cost` is a 422 and `total_cost` is not. The widget refuses the
 * former at the keyboard - a §6.1 Tier-1 parse rule, the only class of refusal
 * a widget is allowed to make - and says which rule, rather than sending it.
 */
const props = defineProps<{
  label: string
  controlId: string
  field: string
  nodeId?: string
  modelValue: Record<string, ScalarType> | null
  help?: string
}>()

const emit = defineEmits<{ commit: [value: Record<string, ScalarType> | null] }>()

/** `document.py:ScalarType`, in the order an author meets them. */
const TYPES: readonly ScalarType[] = ['string', 'number', 'integer', 'boolean']

const rows = computed(() => Object.entries(props.modelValue ?? {}))

/** The name being edited, and to what. One at a time - only one has focus. */
const nameDraft = ref<{ from: string; to: string } | null>(null)
watch(
  () => props.modelValue,
  () => {
    nameDraft.value = null
  },
)

const nameHint = computed(() => {
  const draft = nameDraft.value
  if (!draft || draft.to === draft.from) return undefined
  if (!draft.to.trim()) return 'A property needs a name.'
  if (!NODE_ID_PATTERN.test(draft.to)) {
    return `"${draft.to}" is not a legal property name: lower-case, starting with a letter, letters digits and underscores, at most 40 characters.`
  }
  if (draft.to in (props.modelValue ?? {})) return `This schema already declares ${draft.to}.`
  return undefined
})

/** A fresh name no existing row holds, so adding twice does not overwrite once. */
function freeName(): string {
  const held = props.modelValue ?? {}
  let index = 1
  while (`field_${index}` in held) index += 1
  return `field_${index}`
}

function write(next: Record<string, ScalarType>): void {
  // An empty schema is `null`, not `{}`. `output_schema: {}` and its absence
  // both compile to "no declared shape", and only one of them round-trips
  // through a fingerprint identically to the document that never had one.
  emit('commit', Object.keys(next).length ? next : null)
}

function addRow(): void {
  write({ ...(props.modelValue ?? {}), [freeName()]: 'string' })
}

function removeRow(name: string): void {
  const next: Record<string, ScalarType> = {}
  for (const [key, type] of Object.entries(props.modelValue ?? {})) {
    if (key !== name) next[key] = type
  }
  write(next)
}

/** Renaming rebuilds the map in place, so a rename does not move the row. */
function commitName(): void {
  const draft = nameDraft.value
  nameDraft.value = null
  if (!draft || draft.to === draft.from || nameHint.value) return
  const next: Record<string, ScalarType> = {}
  for (const [key, type] of Object.entries(props.modelValue ?? {})) {
    next[key === draft.from ? draft.to : key] = type
  }
  write(next)
}

function commitType(name: string, event: Event): void {
  const type = (event.target as HTMLSelectElement).value as ScalarType
  write({ ...(props.modelValue ?? {}), [name]: type })
}

/* --- paste ------------------------------------------------------------- */

const pasting = ref(false)
const pasteText = ref('')
const pasteProblem = ref('')

function openPaste(): void {
  pasting.value = true
  pasteText.value = ''
  pasteProblem.value = ''
}

/**
 * Turn pasted JSON into the flat map, or say exactly why it could not.
 *
 * Two shapes are accepted because both are what people actually have: the map
 * this widget itself writes, and a JSON Schema `{"properties": {...}}` copied
 * out of an API doc. Anything else, and anything whose property type this
 * document cannot express, is REPORTED - never partially applied. A paste that
 * silently kept nine of eleven properties would be the worst of the three
 * possible behaviours.
 */
function applyPaste(): void {
  let parsed: unknown
  try {
    parsed = JSON.parse(pasteText.value)
  } catch (error) {
    pasteProblem.value = `That is not JSON: ${(error as Error).message}`
    return
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    pasteProblem.value = 'A schema is a JSON object of property names.'
    return
  }
  const source = parsed as Record<string, unknown>
  const properties =
    source.properties && typeof source.properties === 'object' && !Array.isArray(source.properties)
      ? (source.properties as Record<string, unknown>)
      : source

  const next: Record<string, ScalarType> = {}
  const badNames: string[] = []
  const badTypes: string[] = []
  for (const [name, value] of Object.entries(properties)) {
    if (!NODE_ID_PATTERN.test(name)) {
      badNames.push(name)
      continue
    }
    // `"total": "number"` and `"total": {"type": "number"}` are the same
    // statement written two ways, and both arrive here.
    const declared =
      typeof value === 'string'
        ? value
        : value && typeof value === 'object'
          ? String((value as Record<string, unknown>).type ?? '')
          : ''
    if (!(TYPES as readonly string[]).includes(declared)) {
      badTypes.push(`${name} (${declared || 'no type'})`)
      continue
    }
    next[name] = declared as ScalarType
  }

  const refusals: string[] = []
  if (badNames.length) {
    refusals.push(
      `${badNames.join(', ')} ${badNames.length === 1 ? 'is not a legal property name' : 'are not legal property names'}`,
    )
  }
  if (badTypes.length) {
    refusals.push(
      `${badTypes.join(', ')} - this document carries only ${TYPES.join(', ')}, because the compiler builds a flat pydantic class from it`,
    )
  }
  if (refusals.length) {
    pasteProblem.value = `Nothing was changed. ${refusals.join('; ')}.`
    return
  }
  if (!Object.keys(next).length) {
    pasteProblem.value = 'That schema declares no properties.'
    return
  }
  pasting.value = false
  write(next)
}
</script>

<template>
  <FieldRow
    :label="label"
    :control-id="controlId"
    :field="field"
    :node-id="nodeId"
    group
    :hint="nameHint"
    :note="rows.length ? `${rows.length} ${rows.length === 1 ? 'property' : 'properties'}` : undefined"
    :help="help"
  >
    <div class="schema-rows">
      <div v-for="[name, type] in rows" :key="name" class="schema-row">
        <input
          type="text"
          class="schema-name"
          spellcheck="false"
          autocomplete="off"
          :value="nameDraft && nameDraft.from === name ? nameDraft.to : name"
          :aria-label="`Name of property ${name}`"
          @input="nameDraft = { from: name, to: ($event.target as HTMLInputElement).value }"
          @keydown.enter.prevent="commitName"
          @blur="commitName"
        />
        <select
          class="schema-type"
          :value="type"
          :aria-label="`Type of property ${name}`"
          @change="commitType(name, $event)"
        >
          <option v-for="option in TYPES" :key="option" :value="option">{{ option }}</option>
        </select>
        <button
          type="button"
          class="row-remove"
          :aria-label="`Remove property ${name}`"
          @click="removeRow(name)"
        >
          <X :size="12" aria-hidden="true" />
        </button>
      </div>

      <p v-if="!rows.length" class="empty-note">
        No declared shape. The task answers prose, and a downstream transform has
        nothing named to pick from.
      </p>

      <div class="schema-actions">
        <button type="button" class="row-add" @click="addRow">
          <Plus :size="12" aria-hidden="true" />
          Add property
        </button>
        <button type="button" class="row-add" @click="openPaste">
          <ClipboardPaste :size="12" aria-hidden="true" />
          Paste JSON
        </button>
      </div>

      <!--
        Docked, not a dialog. R15 cuts every modal from the editing path, and a
        paste box is exactly the kind of thing that gets one by default.
      -->
      <div v-if="pasting" class="schema-paste">
        <label :for="`${controlId}-paste`" class="paste-label">
          A property map, or a JSON Schema with <code>properties</code>
        </label>
        <textarea
          :id="`${controlId}-paste`"
          v-model="pasteText"
          rows="5"
          spellcheck="false"
          placeholder='{ "verdict": "string", "score": "number" }'
        />
        <p v-if="pasteProblem" class="paste-problem" role="alert">{{ pasteProblem }}</p>
        <div class="paste-actions">
          <button type="button" class="row-add" @click="applyPaste">Replace schema</button>
          <button type="button" class="row-add" @click="pasting = false">Cancel</button>
        </div>
      </div>
    </div>
  </FieldRow>
</template>

<style scoped>
.schema-rows { display: grid; gap: 7px; }
.schema-row { display: grid; grid-template-columns: minmax(0, 1fr) 96px 22px; align-items: center; gap: 6px; }
.schema-name { font-family: var(--font-mono) !important; }
.schema-type { font-size: var(--fs-12) !important; }

.schema-actions { display: flex; gap: 7px; }
.schema-actions .row-add { flex: 1 1 auto; }

.row-remove { display: grid; width: 22px; height: 22px; flex: 0 0 auto; place-items: center; padding: 0; color: var(--text-40); background: transparent; border: 0; border-radius: var(--r-sm); cursor: pointer; }
.row-remove:hover { color: var(--err-text); background: var(--err-bg); }
.row-remove:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.row-add { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 30px; padding: 0 9px; color: var(--text-muted); font: 600 var(--fs-11)/1 var(--font-body); background: transparent; border: 1px dashed var(--border-default); border-radius: var(--r-md); cursor: pointer; transition: color var(--motion-fast) ease, border-color var(--motion-fast) ease; }
.row-add:hover { color: var(--text-title); border-color: var(--border-hover); }
.row-add:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

.schema-paste { display: grid; gap: 7px; padding: 9px 10px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.paste-label { color: var(--text-40); font: 600 var(--fs-11)/1.4 var(--font-body); }
.paste-label code { font-family: var(--font-mono); }
.paste-problem { margin: 0; color: var(--err-text); font-size: var(--fs-11); line-height: 1.5; }
.paste-actions { display: flex; gap: 7px; }
.paste-actions .row-add { flex: 1 1 auto; }
.empty-note { margin: 0; color: var(--text-40); font-size: var(--fs-11); line-height: 1.5; }
</style>
