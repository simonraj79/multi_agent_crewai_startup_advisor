<script setup lang="ts">
import { computed } from 'vue'
import type {
  BuilderDocument,
  BuilderNode,
  BuilderVocabulary,
  JsonScalar,
  NodeId,
} from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import ScalarInput from '../fields/ScalarInput.vue'
import { descendantsOf } from '../../../utils/builderGraph'
import { patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * The `output` node: what the run hands back, under the one key that escapes
 * the clip.
 *
 * `body_key` is a select over one option today, and it is a select anyway.
 * `RUN_RESULT_BODY_KEYS` is not a formality: those are the keys `mark_completed`
 * gives `MAX_RUN_RESULT_BODY_CHARS` instead of the streaming serializer's 4 KiB
 * frame clip, and a body written under any other key comes back truncated
 * mid-sentence - which is exactly how the first paid run's report was lost. A
 * hardcoded literal would be a client that could not follow the server when a
 * second key is registered; a select over the served list follows it for free.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'output' }>
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{ commit: [change: InspectorCommit] }>()

const config = computed(() => props.node.config)
const control = (name: string) => `insp-${props.node.id}-${name}`

const bodyKeys = computed(() => {
  const served = props.vocabulary.result_body_keys
  return served.includes(config.value.body_key) ? served : [...served, config.value.body_key]
})

function commitBodyKey(event: Event): void {
  const body_key = (event.target as HTMLSelectElement).value
  if (body_key === config.value.body_key) return
  emit('commit', {
    label: 'Set result key',
    next: patchConfig(props.doc, props.node, { body_key }),
  })
}

function commitSource(source: JsonScalar): void {
  emit('commit', {
    label: 'Set result source',
    next: patchConfig(props.doc, props.node, { source }),
  })
}

/**
 * The node this output almost certainly means, stated rather than written in.
 *
 * An output node with exactly one thing upstream of it has one plausible source,
 * and saying so is cheaper than an author reading the whole key list to find it.
 * It is a SENTENCE and not a default: seeding `config.source` on mount would be
 * a write nobody asked for, arriving through a path that is not `commit()`.
 */
const soleUpstream = computed(() => {
  const feeding = props.doc.nodes.filter(
    (node) =>
      node.id !== props.node.id && descendantsOf(props.doc, node.id).has(props.node.id as NodeId),
  )
  return feeding.length === 1 ? feeding[0] : null
})

const sourceHelp = computed(() =>
  soleUpstream.value
    ? `The text handed back. Only ${soleUpstream.value.label} reaches this node, so its output is very likely what you want here.`
    : 'The text handed back. A state reference resolves to what that node produced; a literal is used as written.',
)
</script>

<template>
  <div class="inspector-form">
    <FieldRow
      label="Result key"
      :control-id="control('body_key')"
      field="body_key"
      :node-id="node.id"
      mono
      help="The key the run's result carries the body under. These are the keys the service gives the full result budget; a body written anywhere else comes back truncated mid-sentence."
      v-slot="row"
    >
      <select
        :id="control('body_key')"
        :value="config.body_key"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitBodyKey"
      >
        <option v-for="option in bodyKeys" :key="option" :value="option">{{ option }}</option>
      </select>
    </FieldRow>

    <ScalarInput
      :model-value="config.source"
      :doc="doc"
      label="Source"
      :control-id="control('source')"
      field="source"
      :node-id="node.id"
      where="source"
      :help="sourceHelp"
      @commit="commitSource"
    />
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
</style>
