<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import { NODE_ID_PATTERN, STATE_OUTPUT_PREFIX, STATE_REF_PATTERN } from '../../../types/builder'
import type { BuilderDocument, NodeId } from '../../../types/builder'
import { STATE_TURNS_PREFIX, ancestorsOf } from '../../../utils/builderGraph'
import FieldRow from './FieldRow.vue'

/**
 * A reference to something an upstream node produced - offered as a list of the
 * keys that actually resolve, rather than as a text box.
 *
 * TWO SHAPES, because the document genuinely has two. A `with:` value carries
 * the whole wrapper (`${state.out__scoper}`), while a router branch's `key` is
 * the bare key (`out__scoper`) because `route_branch` reads it straight out of
 * the state map. Spelling one as the other is a 422 in one direction and a
 * comparison that never matches in the other, so the shape is declared rather
 * than guessed.
 *
 * WHY THE NESTED REFUSAL IS IN THE WIDGET (§6.1, Tier 1). Only the single flat
 * key was ever measured resolving, so `document.py::_checked_with_value` refuses
 * any string carrying `${` that is not the blessed shape - a PARSE refusal, a
 * 422, not a Problem the panel can render. Left to the server, an author who
 * wrote `${state.out__scoper.segment}` would lose a whole save to a pydantic
 * location. Refused here, they are shown the compiler's own sentence, verbatim,
 * while they are still typing it.
 *
 * WHY BEING OUT OF SCOPE IS ONLY A WARNING. A reference to a node that is not
 * upstream is perfectly legal to the schema and compiles clean - it simply
 * resolves to nothing every time the graph runs, because `out__x` is seeded by
 * running x. That is a judgement about the graph's shape, which is the server's
 * to make and not this widget's to refuse; what a widget can honestly do is say
 * so before the run does.
 */

/** `document.py:_EXPRESSION_MARKER` - any `${` at all means a reference was intended. */
const EXPRESSION_MARKER = '${'
/** What typing opens the list, per §4.4. */
const REF_OPEN = '${state.'

const props = withDefaults(
  defineProps<{
    /** The stored text. In `bare` shape, the key alone; in `wrapped`, the whole value. */
    modelValue: string
    doc: BuilderDocument
    label: string
    controlId: string
    field: string
    /** The node this control belongs to, which is what "upstream" is measured from. */
    nodeId?: NodeId
    /** `wrapped` writes `${state.k}`; `bare` writes `k`. */
    shape?: 'wrapped' | 'bare'
    /**
     * What the compiler calls this position in its refusal - `source`,
     * `prompt_inputs['idea']`. Rendered into the server's own sentence so the
     * widget and the 422 name the same place.
     */
    where?: string
    help?: string
    placeholder?: string
    /**
     * Inert, and visibly so.
     *
     * The one caller is a router's `otherwise` branch, where `key` and `value`
     * MUST be null - `RouterBranch._validate_shape` refuses either being
     * present. A disabled control says "this field exists and does not apply
     * here"; hiding it would say "this field does not exist", and an author
     * switching the op back would then wonder where it went.
     */
    disabled?: boolean
  }>(),
  { shape: 'wrapped', placeholder: '', disabled: false },
)

const emit = defineEmits<{ commit: [value: string] }>()

const draft = ref(props.modelValue)
const open = ref(false)
const active = ref(0)

/*
 * The stored value can move without this field touching it - an undo, a
 * different node selected into the same mounted form, a paste. Re-seeding on
 * focus alone would leave the box showing the value it had before the undo,
 * which is the one moment an author is checking what the undo did.
 */
watch(
  () => props.modelValue,
  (value) => {
    draft.value = value
  },
)

/**
 * Every key that resolves at runtime: the run's own input, and one per node.
 *
 * `input_field` first because it is the only one that exists before anything has
 * run. The rest are in document order rather than topological order - the author
 * arranged the canvas, and `topoOrder` would reshuffle the list under them every
 * time an edge changed.
 */
const options = computed(() => {
  const entries: Array<{ key: string; label: string; kind: 'input' | 'output' }> = [
    { key: props.doc.input_field, label: 'the run input', kind: 'input' },
  ]
  for (const node of props.doc.nodes) {
    entries.push({
      key: `${STATE_OUTPUT_PREFIX}${node.id}`,
      label: node.label,
      kind: 'output',
    })
  }
  return entries
})

/** What the author has typed as a KEY, whatever shape the field is in. */
const typedKey = computed(() => {
  if (props.shape === 'bare') return draft.value.trim()
  const value = draft.value.trim()
  if (!value.startsWith(REF_OPEN)) return ''
  return value.slice(REF_OPEN.length).replace(/\}$/, '')
})

const matches = computed(() => {
  const needle = typedKey.value.toLowerCase()
  if (!needle) return options.value
  return options.value.filter(
    (option) =>
      option.key.toLowerCase().includes(needle) || option.label.toLowerCase().includes(needle),
  )
})

/** `wrapped` fields start as plain text and become a reference the moment `${` appears. */
const referencing = computed(
  () => props.shape === 'bare' || draft.value.trim().startsWith(EXPRESSION_MARKER),
)

/**
 * The widget's refusal, in the compiler's own words where the compiler has some.
 *
 * `_checked_with_value`'s sentence is reproduced exactly, with `where`
 * substituted the way the server substitutes it, because two paraphrases of one
 * rule is how an author ends up believing there are two rules.
 */
const hint = computed(() => {
  const value = draft.value.trim()
  if (props.shape === 'bare') {
    if (!value) return undefined
    return NODE_ID_PATTERN.test(value)
      ? undefined
      : 'A state key is one flat lowercase identifier - letters, digits and underscores, starting with a letter.'
  }
  if (!value.includes(EXPRESSION_MARKER)) return undefined
  if (STATE_REF_PATTERN.test(value)) return undefined
  return (
    `${props.where ?? props.field} looks like a state reference but is not a resolvable one: write ` +
    '${state.<key>} with a single lowercase key. Nested access such as ' +
    '${state.out__scoper.segment} does not resolve, and is refused here rather than ' +
    'passed to the agent as literal text'
  )
})

/**
 * Everything that can reach this node, computed once per draft rather than per
 * keystroke of the list.
 */
const upstream = computed(() =>
  props.nodeId ? ancestorsOf(props.doc, props.nodeId) : new Set<NodeId>(),
)

/**
 * The advisory, and only for the two prefixes whose meaning this side actually
 * knows.
 *
 * `out__x` is seeded by running x and `turns__x` by answering the gate x, so for
 * either one "is x upstream?" is a real question with a real answer. Any other
 * key is something the compiler seeds and this widget has no opinion about -
 * saying "not upstream" about one would be inventing a rule.
 */
const advisory = computed(() => {
  if (!props.nodeId || hint.value) return undefined
  const key = props.shape === 'bare' ? draft.value.trim() : typedKey.value
  if (!key || key === props.doc.input_field) return undefined
  const prefix = key.startsWith(STATE_OUTPUT_PREFIX)
    ? STATE_OUTPUT_PREFIX
    : key.startsWith(STATE_TURNS_PREFIX)
      ? STATE_TURNS_PREFIX
      : ''
  if (!prefix) return undefined
  const producer = key.slice(prefix.length)
  if (!props.doc.nodes.some((node) => node.id === producer)) {
    return `No node in this graph is called ${producer}, so this key is never written and reads as empty.`
  }
  if (!upstream.value.has(producer as NodeId)) {
    return `${producer} cannot reach this node, so this key is empty every time the graph runs.`
  }
  return undefined
})

function choose(key: string): void {
  draft.value = props.shape === 'bare' ? key : `${REF_OPEN}${key}}`
  open.value = false
  commit()
}

function commit(): void {
  if (hint.value) return
  if (draft.value !== props.modelValue) emit('commit', draft.value)
}

function onInput(): void {
  open.value = referencing.value
  active.value = 0
}

function move(step: number): void {
  if (!open.value) {
    open.value = referencing.value
    return
  }
  const count = matches.value.length
  if (!count) return
  active.value = (active.value + step + count) % count
}

function onEnter(): void {
  if (open.value && matches.value[active.value]) choose(matches.value[active.value].key)
  else commit()
}

/**
 * Escape closes the list and puts the stored value back, with nothing emitted -
 * the same contract every other abortable gesture in this builder has (§4.5).
 */
function onEscape(): void {
  if (open.value) open.value = false
  else draft.value = props.modelValue
}

function onBlur(): void {
  open.value = false
  if (hint.value) draft.value = props.modelValue
  else commit()
}

const listId = computed(() => `${props.controlId}-options`)
const activeId = computed(() =>
  open.value && matches.value[active.value] ? `${listId.value}-${active.value}` : undefined,
)
</script>

<template>
  <FieldRow
    :label="label"
    :control-id="controlId"
    :field="field"
    :node-id="nodeId"
    :hint="disabled ? undefined : hint"
    :help="advisory ?? help"
    mono
  >
    <!-- Passed straight through, so `ScalarInput` can hang its type toggle on
         this row's label line while the control below stays ours. -->
    <template #note><slot name="note" /></template>

    <template #default="row">
    <div class="ref-control">
      <input
        :id="controlId"
        v-model="draft"
        type="text"
        role="combobox"
        spellcheck="false"
        autocomplete="off"
        autocapitalize="off"
        :placeholder="placeholder"
        :disabled="disabled"
        :aria-expanded="open"
        :aria-controls="listId"
        :aria-activedescendant="activeId"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @input="onInput"
        @keydown.down.prevent="move(1)"
        @keydown.up.prevent="move(-1)"
        @keydown.enter.prevent="onEnter"
        @keydown.esc.prevent="onEscape"
        @blur="onBlur"
      />
      <button
        v-if="!disabled"
        type="button"
        class="ref-toggle"
        :aria-label="open ? 'Hide resolvable keys' : 'Show resolvable keys'"
        @mousedown.prevent
        @click="open = !open"
      >
        <ChevronDown :size="13" aria-hidden="true" />
      </button>

      <ul v-if="open && !disabled" :id="listId" class="ref-options" role="listbox" :aria-label="`Keys ${label} can read`">
        <li
          v-for="(option, index) in matches"
          :id="`${listId}-${index}`"
          :key="option.key"
          class="ref-option"
          :class="{ 'is-active': index === active }"
          role="option"
          :aria-selected="index === active"
          @mousedown.prevent="choose(option.key)"
          @mousemove="active = index"
        >
          <code>{{ option.key }}</code>
          <span>{{ option.label }}</span>
        </li>
        <!-- Never an empty box. A filter that matches nothing is a fact about
             what this graph produces, and saying it is cheaper than leaving the
             author to wonder whether the list failed to load. -->
        <li v-if="!matches.length" class="ref-empty">No key in this graph matches that.</li>
      </ul>
    </div>
    </template>
  </FieldRow>
</template>

<style scoped>
.ref-control { position: relative; }
.ref-toggle { position: absolute; top: 4px; right: 4px; display: grid; width: 26px; height: 26px; place-items: center; padding: 0; color: var(--text-40); background: transparent; border: 0; border-radius: var(--r-sm); cursor: pointer; }
.ref-toggle:hover { color: var(--text-title); background: var(--surface-raised); }
.ref-toggle:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

/* Absolutely positioned, so opening the list never reflows the form beneath it.
   An inspector that grows by 140px when a combobox opens moves every control
   below the one the author is using. */
.ref-options { position: absolute; z-index: var(--z-control); top: calc(100% + 4px); right: 0; left: 0; max-height: 184px; margin: 0; padding: 4px; overflow-y: auto; list-style: none; background: var(--surface-overlay); border: 1px solid var(--border-default); border-radius: var(--r-md); box-shadow: 0 12px 28px rgba(0, 0, 0, 0.42); }
.ref-option { display: flex; align-items: baseline; gap: 8px; padding: 5px 7px; border-radius: var(--r-sm); cursor: pointer; }
.ref-option code { color: var(--accent-cyan); font: 500 10px/1.4 var(--font-mono); }
.ref-option span { overflow: hidden; color: var(--text-muted); font-size: var(--fs-11); text-overflow: ellipsis; white-space: nowrap; }
.ref-option.is-active { background: color-mix(in srgb, var(--accent-cyan) 14%, transparent); }
.ref-empty { padding: 6px 7px; color: var(--text-40); font-size: var(--fs-11); }
</style>
