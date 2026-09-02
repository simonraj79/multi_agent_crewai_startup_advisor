<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { nodeId } from '../../../types/builder'
import type {
  BuilderDocument,
  BuilderJoins,
  BuilderVocabulary,
  NodeId,
} from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import { inboundCount } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * The document itself: its name, which input starts a run, and how fan-ins
 * combine.
 *
 * This is also the inspector's EMPTY STATE. Nothing selected renders these
 * rather than blank space, because a docked rail that goes empty is a rail an
 * author stops looking at - and because these three are the only facts about the
 * graph that no node owns.
 *
 * `input_field` is a PICKER over the fields the input nodes declare, never a
 * text box. `bounds.py` matches `document.input_field` against each input node's
 * `config.field`, so free text here produces `input-field-undeclared` - a
 * document that is broken by a typo in a field that looks like prose. Every
 * value this control can produce is one some node already declares.
 *
 * The joins list is deliberately not "nodes with two inbound edges". It is those
 * PLUS any node that already carries a `joins` key, because a fan-in that loses
 * an edge leaves a key behind - `join-single-predecessor`, one of the three
 * warnings - and a list that hid it would be a warning with no control that
 * could answer it.
 */
const props = defineProps<{
  doc: BuilderDocument
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{ commit: [change: InspectorCommit] }>()

/* --- name --------------------------------------------------------------- */

const nameDraft = ref(props.doc.name)
watch(
  () => props.doc.name,
  (name) => {
    nameDraft.value = name
  },
)

function commitName(): void {
  const name = nameDraft.value.trim()
  // 1..80 and stripped server-side. An empty name is a 422, so the stored one
  // goes back rather than a save failing on a field the author cleared by
  // accident.
  if (!name) {
    nameDraft.value = props.doc.name
    return
  }
  if (name === props.doc.name) return
  emit('commit', {
    label: 'Rename graph',
    next: { ...props.doc, name },
    coalesceKey: 'document:name',
  })
}

/* --- the run input ------------------------------------------------------- */

const declaredFields = computed(() => {
  const fields: string[] = []
  for (const node of props.doc.nodes) {
    if (node.kind === 'input' && !fields.includes(node.config.field)) fields.push(node.config.field)
  }
  // The stored value belongs in the list even when nothing declares it, or the
  // select would silently show a different field than the document holds.
  if (!fields.includes(props.doc.input_field)) fields.push(props.doc.input_field)
  return fields
})

const undeclared = computed(
  () =>
    !props.doc.nodes.some(
      (node) => node.kind === 'input' && node.config.field === props.doc.input_field,
    ),
)

function commitInputField(event: Event): void {
  const field = (event.target as HTMLSelectElement).value
  if (field === props.doc.input_field) return
  emit('commit', {
    label: 'Set the run input',
    next: { ...props.doc, input_field: nodeId(field) },
  })
}

/* --- joins -------------------------------------------------------------- */

interface JoinRow {
  id: NodeId
  label: string
  inbound: number
  all: boolean
}

const joinRows = computed<JoinRow[]>(() =>
  props.doc.nodes
    .map((node) => ({
      id: node.id,
      label: node.label,
      inbound: inboundCount(props.doc, node.id),
      all: props.doc.joins[node.id] === 'all',
    }))
    .filter((row) => row.inbound >= 2 || row.all),
)

/**
 * AND writes the key; OR deletes it. There is no third value.
 *
 * `'any'` is refused at PARSE time with a message rather than reported, and the
 * reason is worth carrying into the widget that would otherwise offer it: a
 * multi-event `or_()` listener is entered into `_fired_or_listeners` the first
 * time it fires and skipped forever after, so the SECOND arrival ends the run
 * normally having produced nothing. No exception, no warning, no frame. So OR
 * here means "no join declared - the first arrival runs it", which is CrewAI's
 * own default, and not a stored `'any'`.
 */
function commitJoin(id: NodeId, all: boolean): void {
  const joins: BuilderJoins = { ...props.doc.joins }
  if (all) joins[id] = 'all'
  else delete joins[id]
  emit('commit', {
    label: all ? `Wait for every branch into ${id}` : `Fire ${id} on the first branch`,
    next: { ...props.doc, joins },
  })
}
</script>

<template>
  <div class="inspector-form">
    <FieldRow
      label="Name"
      control-id="insp-doc-name"
      field="name"
      :used="nameDraft.length"
      :max="vocabulary.bounds.max_name_chars"
      :warn-at="10"
      help="What this graph is called in the library and in the run history."
      v-slot="row"
    >
      <input
        id="insp-doc-name"
        v-model="nameDraft"
        type="text"
        :maxlength="vocabulary.bounds.max_name_chars"
        :aria-describedby="row.describedBy"
        @keydown.enter.prevent="commitName"
        @blur="commitName"
      />
    </FieldRow>

    <FieldRow
      label="Run input"
      control-id="insp-doc-input-field"
      field="input_field"
      mono
      :note="undeclared ? 'declared by no node' : undefined"
      :note-warn="undeclared"
      help="The key a launch must carry inside `inputs`. Chosen from what the input nodes declare, because a value nothing declares is a graph that cannot start."
      v-slot="row"
    >
      <select
        id="insp-doc-input-field"
        :value="doc.input_field"
        :aria-describedby="row.describedBy"
        @change="commitInputField"
      >
        <option v-for="field in declaredFields" :key="field" :value="field">{{ field }}</option>
      </select>
    </FieldRow>

    <FieldRow
      label="Fan-in"
      control-id="insp-doc-joins"
      field="joins"
      group
      help="AND waits for every branch; OR fires on the first one that arrives. Two branches of the SAME router converging under AND deadlock - only one of them ever runs."
    >
      <ul v-if="joinRows.length" class="join-rows">
        <li v-for="row in joinRows" :key="row.id" class="join-row">
          <div class="join-name">
            <span class="join-label">{{ row.label }}</span>
            <span class="join-count">{{ row.inbound }} inbound</span>
          </div>
          <!-- Its own class rather than the rail's `.segmented`, which `FieldRow`
               owns through `:deep()` at the same specificity - two rules that can
               only be told apart by injection order is a coin toss, not a
               cascade. -->
          <div class="join-choice">
            <button type="button" :aria-pressed="row.all" @click="commitJoin(row.id, true)">
              AND
            </button>
            <button type="button" :aria-pressed="!row.all" @click="commitJoin(row.id, false)">
              OR
            </button>
          </div>
        </li>
      </ul>
      <p v-else class="empty-note">No node in this graph has more than one edge arriving.</p>
    </FieldRow>
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
.join-rows { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.join-row { display: grid; grid-template-columns: minmax(0, 1fr) 108px; align-items: center; gap: 9px; padding: 8px 9px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.join-name { min-width: 0; }
.join-label { display: block; overflow: hidden; color: var(--text-body); font-size: var(--fs-12); text-overflow: ellipsis; white-space: nowrap; }
.join-count { color: var(--text-40); font: 500 10px/1.5 var(--font-mono); }
/* The rows already sit in wells, so this pair reads as a control rather than as
   a second well: transparent, and only the pressed half is filled. */
.join-choice { display: grid; grid-template-columns: 1fr 1fr; gap: 2px; padding: 2px; border: 1px solid var(--border-default); border-radius: var(--r-md); }
.join-choice button { min-height: 26px; color: var(--text-40); font: 700 10px/1 var(--font-mono); background: transparent; border: 0; border-radius: var(--r-xs); cursor: pointer; transition: color var(--motion-fast) ease, background var(--motion-fast) ease; }
.join-choice button:hover { color: var(--text-body); }
.join-choice button[aria-pressed='true'] { color: var(--text-title); background: var(--surface-raised); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent-cyan) 24%, transparent); }
.join-choice button:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: -2px; }
.empty-note { margin: 0; color: var(--text-40); font-size: var(--fs-11); line-height: 1.5; }
</style>
