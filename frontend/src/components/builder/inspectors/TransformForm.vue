<script setup lang="ts">
import { computed } from 'vue'
import type {
  BuilderDocument,
  BuilderNode,
  BuilderVocabulary,
  JsonScalar,
  TransformOp,
} from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import TransformArgsEditor from './TransformArgsEditor.vue'
import { patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * The `transform` node: one of six fixed operations over the data between two
 * nodes. There is no seventh, and there is no author expression.
 *
 * The op select is small; the whole weight of this form is in
 * `TransformArgsEditor`, which changes shape underneath it. Changing the op
 * therefore changes the FORM, and this is deliberately not accompanied by any
 * clearing of `args`: `pick`'s `source` and `format`'s `template` are separate
 * names in one untyped mapping, so switching op and switching back leaves both
 * intact. Dropping them would be this widget deciding an author's `key` was
 * disposable because they looked at `merge` for a second.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'transform' }>
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{ commit: [change: InspectorCommit] }>()

const config = computed(() => props.node.config)
const control = (name: string) => `insp-${props.node.id}-${name}`

/**
 * The served ops, plus whatever this node already names.
 *
 * Same rule as the agent and crew pickers: an op this build does not offer
 * still has to be visible on a document that uses it, or opening that document
 * and touching anything else would silently rewrite it to the first option.
 */
const ops = computed(() => {
  const served = props.vocabulary.transform_ops
  return served.includes(config.value.op) ? served : [...served, config.value.op]
})

function commitOp(event: Event): void {
  const op = (event.target as HTMLSelectElement).value as TransformOp
  if (op === config.value.op) return
  emit('commit', {
    label: `Set transform to ${op}`,
    next: patchConfig(props.doc, props.node, { op }),
  })
}

function commitArgs(args: Record<string, JsonScalar>, label: string): void {
  emit('commit', {
    label,
    next: patchConfig(props.doc, props.node, { args }),
  })
}
</script>

<template>
  <div class="inspector-form">
    <FieldRow
      label="Operation"
      :control-id="control('op')"
      field="op"
      :node-id="node.id"
      mono
      help="Six closed operations. Switching between them keeps every argument you have written, because each op reads its own names out of one mapping."
      v-slot="row"
    >
      <select
        :id="control('op')"
        :value="config.op"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitOp"
      >
        <option v-for="option in ops" :key="option" :value="option">{{ option }}</option>
      </select>
    </FieldRow>

    <TransformArgsEditor
      :doc="doc"
      :node-id="node.id"
      :op="config.op"
      :args="config.args"
      @commit="commitArgs"
    />
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
</style>
