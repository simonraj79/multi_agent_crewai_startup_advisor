<script setup lang="ts">
import { computed } from 'vue'
import { NODE_ID_PATTERN } from '../../../types/builder'
import { MAX_NODE_ID_CHARS } from '../../../data/builderDefaults'
import FieldRow from './FieldRow.vue'

/**
 * An identifier the compiler will accept, and a count of what changing it moves.
 *
 * Three different things in this document are `BUILDER_ID_PATTERN` identifiers
 * and all three are edited here: a node's `id`, an input node's `config.field`,
 * and a router branch's `label` - which IS the out-port name an edge leaves by.
 * The pattern is a server PARSE refusal rather than a Problem, so a value that
 * misses it comes back as a 422 naming a pydantic location instead of a node,
 * which is why §6.1 puts it in Tier 1: the widget refuses it and it is never
 * sent.
 *
 * THE REFERENCE COUNT IS THE POINT. A node id is not only an identity; the
 * compiler DERIVES state keys from it, and an author writes those keys by hand
 * inside values the schema is happy to accept as plain strings. Renaming a node
 * and missing one leaves text that is still perfectly valid - and the two halves
 * fail in opposite directions. A dangling `out__` is refused at publish naming
 * the id no node has. A dangling `turns__` is not caught at all: the existence
 * check only looks at `out__` (compiler.py:732), so the document compiles clean,
 * validates clean, and then `route_branch` reads a key nothing ever seeded, never
 * matches, and falls to `otherwise` on every pass for the life of the workflow.
 * `renameCascade` moves all of it in one commit; this field's job is to say how
 * much that is BEFORE the author commits, so the number is a fact they saw
 * rather than one they discover.
 *
 * The count itself is computed by the caller, from `renameCascade` run against
 * the draft, because only the caller has the document. See
 * `InspectorRail.referencesMoved`.
 */
const props = withDefaults(
  defineProps<{
    /** The draft, `v-model`-bound so the caller can cost it per keystroke. */
    modelValue: string
    /** What is stored right now. A draft equal to this is not a change. */
    committed: string
    /** Identifiers this value may not become. Never includes `committed`. */
    taken: readonly string[]
    label: string
    controlId: string
    field: string
    nodeId?: string
    help?: string
    /**
     * How many other places in the document move with this rename. Null when the
     * caller has nothing to count - a router branch label, an input field name -
     * so nothing is claimed rather than a confident zero.
     */
    references?: number | null
    /** What a taken value is called in the refusal sentence. */
    subject?: string
  }>(),
  { references: null, subject: 'node' },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  /** A legal, free, genuinely different identifier. Emitted on Enter and on blur. */
  commit: [value: string]
}>()

const draft = computed({
  get: () => props.modelValue,
  set: (value: string) => emit('update:modelValue', value),
})

const changed = computed(() => draft.value !== props.committed)
const wellFormed = computed(() => NODE_ID_PATTERN.test(draft.value))
const collides = computed(() => props.taken.includes(draft.value))

/**
 * The widget's refusal, in the terms the pattern is actually written in.
 *
 * Spelling out the rule rather than showing the regex: an author who typed
 * "Market Analyst" needs to be told it must start with a lowercase letter, not
 * shown `^[a-z][a-z0-9_]{0,39}$`.
 */
const hint = computed(() => {
  if (!changed.value) return undefined
  if (!draft.value) return 'An identifier cannot be empty.'
  if (!wellFormed.value) {
    return (
      `Start with a lowercase letter, then use lowercase letters, digits and ` +
      `underscores - up to ${MAX_NODE_ID_CHARS} characters in all.`
    )
  }
  if (collides.value) return `Another ${props.subject} is already called ${draft.value}.`
  return undefined
})

const acceptable = computed(() => changed.value && wellFormed.value && !collides.value)

/**
 * What the rename moves, stated before it happens.
 *
 * Only when the value is actually acceptable, because a count next to a refused
 * draft describes a rename that is not going to occur.
 */
const consequence = computed(() => {
  if (!acceptable.value || props.references == null) return undefined
  if (props.references === 0) return 'Nothing else in this graph names it.'
  return props.references === 1
    ? 'This rename updates 1 reference elsewhere in the graph.'
    : `This rename updates ${props.references} references elsewhere in the graph.`
})

function tryCommit(): void {
  if (acceptable.value) emit('commit', draft.value)
}

/**
 * Leaving the field with something the compiler would refuse puts the stored
 * value back.
 *
 * The alternative is a box holding an illegal identifier indefinitely, next to a
 * graph that still uses the old one - two answers to what this node is called,
 * with only one of them real.
 */
function onBlur(): void {
  if (acceptable.value) emit('commit', draft.value)
  else if (changed.value) draft.value = props.committed
}
</script>

<template>
  <FieldRow
    :label="label"
    :control-id="controlId"
    :field="field"
    :node-id="nodeId"
    :hint="hint"
    :help="consequence ?? help"
    mono
    v-slot="row"
  >
    <input
      :id="controlId"
      v-model="draft"
      type="text"
      spellcheck="false"
      autocomplete="off"
      autocapitalize="off"
      :maxlength="MAX_NODE_ID_CHARS"
      :aria-describedby="row.describedBy"
      :aria-invalid="row.invalid"
      @keydown.enter.prevent="tryCommit"
      @blur="onBlur"
    />
  </FieldRow>
</template>
