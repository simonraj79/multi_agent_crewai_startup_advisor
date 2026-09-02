<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronDown, ChevronUp, X } from 'lucide-vue-next'
import { nodeId } from '../../../types/builder'
import type {
  BuilderDocument,
  BuilderNode,
  BuilderVocabulary,
  JsonScalar,
  RouterBranch,
  RouterOp,
} from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import NodeIdField from '../fields/NodeIdField.vue'
import ScalarInput from '../fields/ScalarInput.vue'
import StateRefInput from '../fields/StateRefInput.vue'

/**
 * One way out of a router, edited in place on the canvas's own rail.
 *
 * THE CROSS-FIELD RULES LIVE HERE, not in a validator that runs afterwards, and
 * both of them are §6.1 Tier-1 refusals - parse errors the server answers with a
 * 422 rather than a Problem, so they must never be sent:
 *
 *   - `otherwise` takes no key and no value. `RouterBranch._validate_shape`
 *     refuses either being present, so choosing it CLEARS both in the same
 *     commit and disables the controls rather than leaving stale text in a box
 *     that is about to be refused.
 *   - every other op MUST name a key. The same validator refuses a null one, so
 *     an empty key marks the row here instead of on save.
 *
 * Exactly-one-`otherwise` is enforced STRUCTURALLY: once another branch holds
 * it, the option is not in this select at all. An author cannot pick the second
 * one and then be told off for it, which is the difference between a rule and a
 * reprimand.
 *
 * The label IS the out-port name (`_OUT_PORTS_BY_KIND` computes a router's ports
 * from its branch labels), which is why it is a `NodeIdField` and why the count
 * it reports is the number of edges that would move with it.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'router' }>
  vocabulary: BuilderVocabulary
  branch: RouterBranch
  index: number
  /** True when a DIFFERENT branch already holds `otherwise`. */
  otherwiseTaken: boolean
  canRemove: boolean
  canMoveUp: boolean
  canMoveDown: boolean
}>()

const emit = defineEmits<{
  /** A whole replacement branch. The parent decides what that costs elsewhere. */
  update: [index: number, branch: RouterBranch]
  /** A label rename, kept separate because the parent must move the edges too. */
  rename: [index: number, label: string]
  remove: [index: number]
  move: [index: number, delta: number]
}>()

const otherwiseOp = computed(() => props.vocabulary.router_otherwise)
const isOtherwise = computed(() => props.branch.op === otherwiseOp.value)

/**
 * The comparisons, plus `otherwise` only when it is still available.
 *
 * `router_comparisons` is served WITHOUT `otherwise` - it is not a comparison -
 * and `router_otherwise` names it separately, so this list is assembled rather
 * than filtered.
 */
const ops = computed(() => {
  const comparisons = [...props.vocabulary.router_comparisons]
  if (!props.otherwiseTaken || isOtherwise.value) comparisons.push(otherwiseOp.value)
  return comparisons
})

const control = (name: string) => `insp-${props.node.id}-branch-${props.index}-${name}`

const labelDraft = ref<string>(props.branch.label)
watch(
  () => props.branch.label,
  (label) => {
    labelDraft.value = label
  },
)

/** Every OTHER branch's label - a port name is unique within one router. */
const takenLabels = computed(() =>
  props.node.config.branches
    .filter((_, position) => position !== props.index)
    .map((branch) => branch.label as string),
)

/** How many edges leave by this port today, and would therefore move with it. */
const edgesOnPort = computed(
  () =>
    props.doc.edges.filter(
      (edge) => edge.source === props.node.id && edge.source_port === props.branch.label,
    ).length,
)

function commitOp(event: Event): void {
  const op = (event.target as HTMLSelectElement).value as RouterOp
  if (op === props.branch.op) return
  emit(
    'update',
    props.index,
    op === otherwiseOp.value
      ? // Cleared in the SAME object that changes the op. Two commits would
        // leave one intermediate document that the compiler refuses outright.
        { ...props.branch, op, key: null, value: null }
      : { ...props.branch, op },
  )
}

function commitKey(key: string): void {
  emit('update', props.index, { ...props.branch, key: nodeId(key) })
}

function commitValue(value: JsonScalar): void {
  emit('update', props.index, { ...props.branch, value })
}

/** The row's own refusal: a comparison with nothing to compare. */
const keyHint = computed(() =>
  !isOtherwise.value && !props.branch.key
    ? `the ${props.branch.op} branch must name the state key it compares`
    : undefined,
)
</script>

<template>
  <li class="branch" :class="{ 'is-otherwise': isOtherwise }">
    <div class="branch-head">
      <span class="branch-index">{{ index + 1 }}</span>
      <span class="branch-port">{{ branch.label }}</span>
      <div class="branch-actions">
        <button
          type="button"
          class="branch-action"
          :disabled="!canMoveUp"
          :aria-label="`Move branch ${branch.label} earlier`"
          @click="emit('move', index, -1)"
        >
          <ChevronUp :size="12" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="branch-action"
          :disabled="!canMoveDown"
          :aria-label="`Move branch ${branch.label} later`"
          @click="emit('move', index, 1)"
        >
          <ChevronDown :size="12" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="branch-action is-remove"
          :disabled="!canRemove"
          :aria-label="`Delete branch ${branch.label}`"
          @click="emit('remove', index)"
        >
          <X :size="12" aria-hidden="true" />
        </button>
      </div>
    </div>

    <NodeIdField
      v-model="labelDraft"
      :committed="branch.label"
      :taken="takenLabels"
      label="Port"
      :control-id="control('label')"
      field="branches"
      subject="branch"
      :references="edgesOnPort"
      help="The out-port an edge leaves this router by."
      @commit="emit('rename', index, $event)"
    />

    <FieldRow
      label="Comparison"
      :control-id="control('op')"
      field="branches"
      v-slot="row"
    >
      <select
        :id="control('op')"
        :value="branch.op"
        :aria-describedby="row.describedBy"
        @change="commitOp"
      >
        <option v-for="op in ops" :key="op" :value="op">{{ op }}</option>
      </select>
    </FieldRow>

    <StateRefInput
      :model-value="branch.key ?? ''"
      :doc="doc"
      shape="bare"
      label="State key"
      :control-id="control('key')"
      field="key"
      :node-id="node.id"
      :disabled="isOtherwise"
      :placeholder="isOtherwise ? '' : 'out__scoper'"
      :help="
        isOtherwise
          ? 'Not used. Otherwise is what happens when every declared comparison missed.'
          : undefined
      "
      @commit="commitKey"
    />
    <p v-if="keyHint" class="branch-hint">{{ keyHint }}</p>

    <ScalarInput
      :model-value="branch.value"
      :doc="doc"
      label="Compared with"
      :control-id="control('value')"
      field="value"
      :node-id="node.id"
      :where="`branches[${index}].value`"
      :disabled="isOtherwise"
      @commit="commitValue"
    />
  </li>
</template>

<style scoped>
.branch { padding: 10px 11px; list-style: none; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
/* Muted and dashed, matching the port the canvas draws for it: `otherwise` is
   the branch that fires when nothing else did, and it should not look like a
   decision the author made about a value. */
.branch.is-otherwise { border-style: dashed; }
.branch-head { display: flex; align-items: center; gap: 7px; margin-bottom: 11px; }
.branch-index { display: grid; width: 18px; height: 18px; flex: 0 0 auto; place-items: center; color: var(--text-40); font: 700 10px/1 var(--font-mono); background: var(--surface-raised); border-radius: var(--r-xs); }
.branch-port { flex: 1 1 auto; overflow: hidden; color: var(--link-cyan); font: 600 var(--fs-12)/1 var(--font-mono); text-overflow: ellipsis; white-space: nowrap; }
.is-otherwise .branch-port { color: var(--text-40); }
.branch-actions { display: flex; flex: 0 0 auto; gap: 2px; }
.branch-action { display: grid; width: 22px; height: 22px; place-items: center; padding: 0; color: var(--text-40); background: transparent; border: 0; border-radius: var(--r-sm); cursor: pointer; transition: color var(--motion-fast) ease, background var(--motion-fast) ease; }
.branch-action:hover:not(:disabled) { color: var(--text-title); background: var(--surface-raised); }
.branch-action.is-remove:hover:not(:disabled) { color: var(--err-text); background: var(--err-bg); }
.branch-action:disabled { cursor: not-allowed; opacity: 0.35; }
.branch-action:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.branch-hint { margin: 7px 0 0; color: var(--err-text); font-size: var(--fs-11); line-height: 1.5; }
</style>
