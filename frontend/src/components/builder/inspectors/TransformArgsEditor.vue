<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronDown, ChevronUp, Plus, X } from 'lucide-vue-next'
import type { BuilderDocument, JsonScalar, NodeId, TransformOp } from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import ScalarInput from '../fields/ScalarInput.vue'

/**
 * The arguments a transform actually reads - which is a different set per op.
 *
 * THIS EDITOR CHANGES SHAPE, and it does so because the runtime does.
 * `TransformConfig.args` is one untyped `dict[str, JsonScalar]` to the schema:
 * "arg NAMES are not validated per op". Which names each op reads is
 * `runtime.py::transform`'s business, and it reads a genuinely different set
 * every time. A single free key/value table would therefore be a form that
 * accepts `sources` for `pick` and produces `None` at run time with nothing
 * anywhere saying why.
 *
 * Every shape and every caveat below was read out of `runtime.py:848-910`
 * rather than inferred from the op's name, because three of the six do
 * something the name does not suggest:
 *
 *   - `join_text` joins the args mapping's VALUES, not the elements of a list.
 *     It also pops `separator` first, so that name is the separator and never
 *     one of the joined pieces, and it skips values that are None.
 *   - `format` is NOT `str.format`. `_format` substitutes only `{name}` for
 *     names the node declares and leaves every other brace as literal text -
 *     `str.format` on an author-supplied template is an attribute-read
 *     primitive that walks straight out of the data. `{template}` is
 *     explicitly excluded, so it can never substitute itself.
 *   - `default` counts only `None` and `""` as absent, so a legitimate `0` or
 *     `false` survives. That is the same defect that once priced a
 *     128,069-token run at nothing, fixed here by construction.
 *
 * An op this build has no shape for degrades to the free table rather than to
 * an empty pane - `builderVocabulary` deliberately does not refuse an unknown
 * `transform_op` for exactly this reason.
 */

/** `runtime.py:_PLACEHOLDER`, verbatim - and `g` so a template can be scanned. */
const PLACEHOLDER = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g
/** `_format` skips this name, so `{template}` is never a placeholder. */
const TEMPLATE_ARG = 'template'

/** Named args each op reads, in the order the runtime reads them. */
const FIXED_ARGS: Partial<Record<TransformOp, readonly { name: string; help: string }[]>> = {
  pick: [
    {
      name: 'source',
      help: 'The mapping to read. A JSON string is parsed first; anything that is not a mapping yields null.',
    },
    { name: 'key', help: 'The key to take out of it.' },
  ],
  default: [
    { name: 'value', help: 'What to use when it is there.' },
    {
      name: 'default',
      help: 'What to use when it is not. Only null and the empty string count as absent, so a legitimate 0 or false survives.',
    },
  ],
}

const props = defineProps<{
  doc: BuilderDocument
  nodeId: NodeId
  op: TransformOp
  args: Record<string, JsonScalar>
}>()

const emit = defineEmits<{ commit: [args: Record<string, JsonScalar>, label: string] }>()

const control = (name: string) => `insp-${props.nodeId}-arg-${name}`

const fixed = computed(() => FIXED_ARGS[props.op] ?? null)
const isFormat = computed(() => props.op === 'format')
const isJoin = computed(() => props.op === 'join_text')
const isToJson = computed(() => props.op === 'to_json')

/** The rows the free table shows: everything the fixed shape does not own. */
const reservedNames = computed(() => {
  if (fixed.value) return new Set(fixed.value.map((entry) => entry.name))
  if (isFormat.value) return new Set([TEMPLATE_ARG])
  if (isJoin.value) return new Set(['separator'])
  return new Set<string>()
})

const freeRows = computed(() =>
  Object.entries(props.args).filter(([name]) => !reservedNames.value.has(name)),
)

const template = computed(() => String(props.args[TEMPLATE_ARG] ?? ''))
const separator = computed(() =>
  'separator' in props.args ? String(props.args.separator ?? '') : '\n\n',
)

/* --- the two-way cross-check for `format` -------------------------------- */

const placeholders = computed(() => {
  const found = new Set<string>()
  for (const match of template.value.matchAll(PLACEHOLDER)) {
    if (match[1] !== TEMPLATE_ARG) found.add(match[1])
  }
  return found
})

/**
 * Both directions, because both are silent at run time and neither is a
 * server-side Problem.
 *
 * A `{name}` with no arg comes out of `_format` as the literal text `{name}` in
 * the middle of a prompt. An arg with no `{name}` is carried, priced and never
 * read. Nothing raises for either one, so if this table does not say so nothing
 * ever does.
 */
const unfilled = computed(() =>
  [...placeholders.value].filter((name) => !(name in props.args)),
)
const unused = computed(() => freeRows.value.map(([name]) => name).filter((name) => !placeholders.value.has(name)))

const formatHint = computed(() => {
  if (!isFormat.value) return undefined
  const parts: string[] = []
  if (unfilled.value.length) {
    parts.push(
      `${unfilled.value.map((name) => `{${name}}`).join(', ')} ${unfilled.value.length === 1 ? 'has' : 'have'} no argument, so ${unfilled.value.length === 1 ? 'it stays' : 'they stay'} in the text as written.`,
    )
  }
  if (unused.value.length) {
    parts.push(
      `${unused.value.join(', ')} ${unused.value.length === 1 ? 'is' : 'are'} never referenced by the template.`,
    )
  }
  return parts.length ? parts.join(' ') : undefined
})

/* --- writes ------------------------------------------------------------- */

function write(next: Record<string, JsonScalar>, label: string): void {
  emit('commit', next, label)
}

function setArg(name: string, value: JsonScalar): void {
  write({ ...props.args, [name]: value }, `Set ${name}`)
}

function removeArg(name: string): void {
  const next: Record<string, JsonScalar> = {}
  for (const [key, value] of Object.entries(props.args)) {
    if (key !== name) next[key] = value
  }
  write(next, `Remove ${name}`)
}

function freeName(): string {
  let index = 1
  while (`arg_${index}` in props.args) index += 1
  return `arg_${index}`
}

function addArg(): void {
  write({ ...props.args, [freeName()]: '' }, 'Add argument')
}

/** Order is visible for `join_text`, so a rename must not move the row. */
const keyDraft = ref<{ from: string; to: string } | null>(null)
watch(
  () => props.args,
  () => {
    keyDraft.value = null
  },
)

const keyHint = computed(() => {
  const draft = keyDraft.value
  if (!draft || draft.to === draft.from) return undefined
  if (!draft.to.trim()) return 'An argument needs a name.'
  if (draft.to in props.args) return `This transform already has an argument called ${draft.to}.`
  if (reservedNames.value.has(draft.to)) {
    return `${draft.to} is what the ${props.op} operation calls one of its own arguments.`
  }
  return undefined
})

function commitKey(): void {
  const draft = keyDraft.value
  keyDraft.value = null
  if (!draft || draft.to === draft.from || keyHint.value) return
  const next: Record<string, JsonScalar> = {}
  for (const [name, value] of Object.entries(props.args)) {
    next[name === draft.from ? draft.to : name] = value
  }
  write(next, `Rename argument to ${draft.to}`)
}

function moveArg(name: string, delta: number): void {
  const names = Object.keys(props.args)
  const at = names.indexOf(name)
  const to = at + delta
  if (at === -1 || to < 0 || to >= names.length) return
  names.splice(to, 0, ...names.splice(at, 1))
  const next: Record<string, JsonScalar> = {}
  for (const key of names) next[key] = props.args[key]
  write(next, `Reorder ${name}`)
}
</script>

<template>
  <div class="args">
    <!-- pick / default: two named boxes, because those are the two keys the
         runtime reads and nothing else in `args` is looked at. -->
    <template v-if="fixed">
      <ScalarInput
        v-for="entry in fixed"
        :key="entry.name"
        :model-value="args[entry.name] ?? null"
        :doc="doc"
        :label="entry.name"
        :control-id="control(entry.name)"
        :field="`args.${entry.name}`"
        :node-id="nodeId"
        :where="`args['${entry.name}']`"
        :help="entry.help"
        @commit="setArg(entry.name, $event)"
      />
    </template>

    <!-- format: the template, then the names it may substitute. -->
    <template v-if="isFormat">
      <FieldRow
        label="Template"
        :control-id="control('template')"
        field="args.template"
        :node-id="nodeId"
        mono
        help="`{name}` is replaced by the argument called name. This is NOT str.format - every other brace stays as the literal text you typed, and `{template}` never substitutes itself."
        v-slot="row"
      >
        <textarea
          :id="control('template')"
          rows="3"
          :value="template"
          :aria-describedby="row.describedBy"
          @change="setArg(TEMPLATE_ARG, ($event.target as HTMLTextAreaElement).value)"
        />
      </FieldRow>
    </template>

    <!-- join_text: the separator is popped before the join, so it is its own
         control and never one of the joined pieces. -->
    <FieldRow
      v-if="isJoin"
      label="Separator"
      :control-id="control('separator')"
      field="args.separator"
      :node-id="nodeId"
      mono
      help="Placed between the values below. Defaults to a blank line when the argument is absent."
      v-slot="row"
    >
      <input
        :id="control('separator')"
        type="text"
        :value="separator"
        :aria-describedby="row.describedBy"
        @change="setArg('separator', ($event.target as HTMLInputElement).value)"
      />
    </FieldRow>

    <FieldRow
      v-if="!fixed"
      :label="isJoin ? 'Values, in order' : 'Arguments'"
      :control-id="control('table')"
      field="args"
      :node-id="nodeId"
      group
      :hint="formatHint"
      :help="
        isJoin
          ? 'Joined in this order. join_text joins these VALUES, not the elements of a list, and it skips any that are null.'
          : isToJson
            ? 'Serialised as one JSON object. Name a single argument `value` and that value alone is serialised instead.'
            : isFormat
              ? 'Each name here may appear as {name} in the template above.'
              : 'Folded together by name. A value that is a JSON object is merged by its own keys instead.'
      "
    >
      <div class="arg-rows">
        <div v-for="[name, value] in freeRows" :key="name" class="arg-row">
          <div class="arg-key">
            <input
              type="text"
              class="key-box"
              spellcheck="false"
              autocomplete="off"
              :value="keyDraft && keyDraft.from === name ? keyDraft.to : name"
              :aria-label="`Name of argument ${name}`"
              @input="keyDraft = { from: name, to: ($event.target as HTMLInputElement).value }"
              @keydown.enter.prevent="commitKey"
              @blur="commitKey"
            />
            <template v-if="isJoin">
              <button
                type="button"
                class="row-action"
                :aria-label="`Move ${name} earlier`"
                @click="moveArg(name, -1)"
              >
                <ChevronUp :size="12" aria-hidden="true" />
              </button>
              <button
                type="button"
                class="row-action"
                :aria-label="`Move ${name} later`"
                @click="moveArg(name, 1)"
              >
                <ChevronDown :size="12" aria-hidden="true" />
              </button>
            </template>
            <button
              type="button"
              class="row-action is-remove"
              :aria-label="`Remove argument ${name}`"
              @click="removeArg(name)"
            >
              <X :size="12" aria-hidden="true" />
            </button>
          </div>
          <ScalarInput
            :model-value="value"
            :doc="doc"
            :label="`${name} value`"
            :control-id="control(name)"
            :field="`args.${name}`"
            :node-id="nodeId"
            :where="`args['${name}']`"
            @commit="setArg(name, $event)"
          />
        </div>
        <p v-if="!freeRows.length" class="empty-note">
          No arguments yet, so this transform reads nothing.
        </p>
        <button type="button" class="row-add" @click="addArg">
          <Plus :size="12" aria-hidden="true" />
          Add argument
        </button>
        <p v-if="keyHint" class="arg-hint">{{ keyHint }}</p>
      </div>
    </FieldRow>
  </div>
</template>

<style scoped>
.args { display: block; }
.arg-rows { display: grid; gap: 10px; }
.arg-row { padding: 9px 10px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.arg-key { display: flex; align-items: center; gap: 4px; margin-bottom: 9px; }
.key-box { flex: 1 1 auto; min-width: 0; padding: 5px 7px; color: var(--accent-cyan); font: 600 var(--fs-12)/1.3 var(--font-mono); background: transparent; border: 1px solid transparent; border-radius: var(--r-sm); outline: 0; }
.key-box:hover { border-color: var(--border-default); }
.key-box:focus-visible { color: var(--text-title); border-color: var(--accent-cyan); box-shadow: var(--glow-input); }
.row-action { display: grid; width: 22px; height: 22px; flex: 0 0 auto; place-items: center; padding: 0; color: var(--text-40); background: transparent; border: 0; border-radius: var(--r-sm); cursor: pointer; }
.row-action:hover { color: var(--text-title); background: var(--surface-raised); }
.row-action.is-remove:hover { color: var(--err-text); background: var(--err-bg); }
.row-action:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.row-add { display: inline-flex; width: 100%; min-height: 30px; align-items: center; justify-content: center; gap: 6px; color: var(--text-muted); font: 600 var(--fs-11)/1 var(--font-body); background: transparent; border: 1px dashed var(--border-default); border-radius: var(--r-md); cursor: pointer; transition: color var(--motion-fast) ease, border-color var(--motion-fast) ease; }
.row-add:hover { color: var(--text-title); border-color: var(--border-hover); }
.row-add:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.empty-note { margin: 0; color: var(--text-40); font-size: var(--fs-11); line-height: 1.5; }
.arg-hint { margin: 0; color: var(--err-text); font-size: var(--fs-11); line-height: 1.5; }
</style>
