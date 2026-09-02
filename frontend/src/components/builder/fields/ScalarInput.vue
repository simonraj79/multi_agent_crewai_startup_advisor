<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { BuilderDocument, JsonScalar, NodeId } from '../../../types/builder'
import FieldRow from './FieldRow.vue'
import StateRefInput from './StateRefInput.vue'

/**
 * One `JsonScalar`, with the type declared rather than inferred from the text.
 *
 * The toggle is the whole feature. Every value this control edits ends up in a
 * `prompt_inputs` entry, a `transform.args` entry, an `output.source` or a
 * `RouterBranch.value` - and a router comparing `gt` against the STRING "0.7"
 * is not the comparison the author drew. ChatDev's forms have exactly this
 * hazard: a numeric setting typed into a text box arrives as `temperature:
 * '0.7'`, which is well-formed, silently wrong, and invisible on the canvas.
 * Declaring the type makes `0` and `false` survivable values rather than things
 * a truthiness check eats.
 *
 * ARRAYS AND OBJECTS ARE NOT OFFERED, and that is the schema's decision rather
 * than a simplification: `document.py`'s `JsonScalar` is `str | int | float |
 * bool | None`, because every argument shape the ten compiler entrypoints accept
 * is flat and a nested literal would be a place to hide something the compiler
 * never looks at.
 *
 * The string case delegates to `StateRefInput`, so a value that reaches for
 * `${state.…}` gets the resolvable-key list and the nested-reference refusal
 * without this component knowing anything about either.
 */

type ScalarType = 'string' | 'number' | 'boolean' | 'null'

const TYPES: readonly { id: ScalarType; label: string }[] = [
  { id: 'string', label: 'str' },
  { id: 'number', label: 'num' },
  { id: 'boolean', label: 'bool' },
  { id: 'null', label: 'null' },
]

const props = defineProps<{
  modelValue: JsonScalar
  doc: BuilderDocument
  label: string
  controlId: string
  field: string
  nodeId?: NodeId
  /** What the compiler calls this position, for `StateRefInput`'s refusal sentence. */
  where?: string
  help?: string
  /** Inert, and visibly so - see `StateRefInput`'s note on the same prop. */
  disabled?: boolean
}>()

const emit = defineEmits<{ commit: [value: JsonScalar] }>()

/** What the stored value IS - never a guess about what the text looks like. */
function typeOf(value: JsonScalar): ScalarType {
  if (value === null) return 'null'
  if (typeof value === 'number') return 'number'
  if (typeof value === 'boolean') return 'boolean'
  return 'string'
}

const chosen = ref<ScalarType>(typeOf(props.modelValue))
const numberDraft = ref(typeof props.modelValue === 'number' ? String(props.modelValue) : '')

watch(
  () => props.modelValue,
  (value) => {
    chosen.value = typeOf(value)
    if (typeof value === 'number') numberDraft.value = String(value)
  },
)

/**
 * The value as text, carrying a number's digits across rather than dropping them.
 *
 * Switching `0.7` to `str` and back must not silently become `0`. The whole
 * point of the toggle is that the author's TYPE was wrong, not their value.
 */
const asString = computed(() =>
  typeof props.modelValue === 'string'
    ? props.modelValue
    : typeof props.modelValue === 'number'
      ? String(props.modelValue)
      : '',
)
const asBoolean = computed(() => props.modelValue === true)

/**
 * Changing type writes a value of that type immediately.
 *
 * The alternative - hold the new type locally and wait for an edit - leaves the
 * document holding a string while the control says number, and the two disagree
 * until the author happens to type. Committing an empty string, a zero, a false
 * or a null is a real value in every one of those positions.
 */
function chooseType(next: ScalarType): void {
  if (next === chosen.value) return
  chosen.value = next
  if (next === 'string') emit('commit', asString.value)
  else if (next === 'number') {
    /*
     * The STRING is the source when there is one, not the empty number draft.
     *
     * This is the whole `temperature: '0.7'` repair: an author reaching for
     * `num` has almost always already typed the number into the text box, and a
     * version of this that read only `numberDraft` turned their 0.7 into a 0 -
     * which is worse than the string they started with, because it looks
     * deliberate.
     */
    const source = numberDraft.value.trim() || asString.value.trim()
    const parsed = Number(source)
    const value = source && Number.isFinite(parsed) ? parsed : 0
    numberDraft.value = String(value)
    emit('commit', value)
  } else if (next === 'boolean') emit('commit', asBoolean.value)
  else emit('commit', null)
}

/**
 * A number box refuses what it cannot send rather than sending a NaN.
 *
 * `BuilderModel` sets `allow_inf_nan=False`, so an infinity or a NaN is a 422 -
 * and an empty box is not a zero, it is an author mid-edit.
 */
const numberHint = computed(() => {
  if (chosen.value !== 'number') return undefined
  const raw = numberDraft.value.trim()
  if (!raw) return 'Enter a number, or switch this value to null.'
  return Number.isFinite(Number(raw)) ? undefined : `${raw} is not a number the compiler accepts.`
})

function commitNumber(): void {
  if (numberHint.value) return
  const parsed = Number(numberDraft.value)
  if (parsed !== props.modelValue) emit('commit', parsed)
}
</script>

<template>
  <StateRefInput
    v-if="chosen === 'string'"
    :model-value="asString"
    :doc="doc"
    :label="label"
    :control-id="controlId"
    :field="field"
    :node-id="nodeId"
    :where="where"
    :help="help"
    :disabled="disabled"
    @commit="emit('commit', $event)"
  >
    <template #note>
      <div class="scalar-types" role="group" :aria-label="`${label} value type`">
        <button
          v-for="type in TYPES"
          :key="type.id"
          type="button"
          :aria-pressed="chosen === type.id"
          :disabled="disabled"
          @click="chooseType(type.id)"
        >
          {{ type.label }}
        </button>
      </div>
    </template>
  </StateRefInput>

  <FieldRow
    v-else
    :label="label"
    :control-id="controlId"
    :field="field"
    :node-id="nodeId"
    :help="help"
    :hint="disabled ? undefined : numberHint"
    :group="chosen !== 'number'"
    mono
  >
    <template #note>
      <div class="scalar-types" role="group" :aria-label="`${label} value type`">
        <button
          v-for="type in TYPES"
          :key="type.id"
          type="button"
          :aria-pressed="chosen === type.id"
          :disabled="disabled"
          @click="chooseType(type.id)"
        >
          {{ type.label }}
        </button>
      </div>
    </template>

    <template #default="row">
    <input
      v-if="chosen === 'number'"
      :id="controlId"
      v-model="numberDraft"
      type="number"
      step="any"
      :disabled="disabled"
      :aria-describedby="row.describedBy"
      :aria-invalid="row.invalid"
      @keydown.enter.prevent="commitNumber"
      @blur="commitNumber"
    />

    <div v-else-if="chosen === 'boolean'" class="segmented" :aria-describedby="row.describedBy">
      <button type="button" :aria-pressed="asBoolean" :disabled="disabled" @click="emit('commit', true)">true</button>
      <button type="button" :aria-pressed="!asBoolean" :disabled="disabled" @click="emit('commit', false)">false</button>
    </div>

    <!-- Not an empty space: null is a value here, and `transform`'s `default` op
         treats it as the one thing that counts as absent. Saying so is the
         difference between "this is null" and "this has not loaded". -->
    <p v-else class="scalar-null" :class="{ 'is-disabled': disabled }" :aria-disabled="disabled" :aria-describedby="row.describedBy">
      null — nothing is sent for this value.
    </p>
    </template>
  </FieldRow>
</template>

<style scoped>
.scalar-types { display: inline-flex; gap: 2px; padding: 2px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.scalar-types button { min-width: 30px; padding: 3px 5px; color: var(--text-40); font: 600 10px/1.3 var(--font-mono); background: transparent; border: 0; border-radius: var(--r-xs); cursor: pointer; transition: color var(--motion-fast) ease, background var(--motion-fast) ease; }
.scalar-types button:hover { color: var(--text-body); }
.scalar-types button[aria-pressed='true'] { color: var(--text-title); background: var(--surface-raised); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent-cyan) 24%, transparent); }
.scalar-types button:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }


.scalar-null.is-disabled { opacity: 0.55; }
.scalar-null { display: flex; min-height: 34px; align-items: center; margin: 0; padding: 7px 9px; color: var(--text-40); font: 500 var(--fs-12)/1.4 var(--font-mono); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
</style>
