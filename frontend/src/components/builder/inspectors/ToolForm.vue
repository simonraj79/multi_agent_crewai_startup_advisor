<script setup lang="ts">
import { computed } from 'vue'
import type {
  BuilderDocument,
  BuilderNode,
  BuilderVocabulary,
  NodeId,
} from '../../../types/builder'
import { nodeId as toNodeId } from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import { patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * The `tool` node: one catalogue tool, hung off an agent or a crew.
 *
 * WHAT THIS FORM IS AND IS NOT, because the boundary is a plan boundary and not
 * a judgement about effort. 03 owns the ten-kind vocabulary, the ports, the
 * palette and the node's identity on the canvas; **inspector forms are 04's**
 * and the tool CATALOGUE is 06's. So this renders the one field the document
 * actually carries today - the opaque `tool_id` - and stops there. Its `params`
 * table needs to know what a given tool accepts, which is exactly the thing
 * `/api/builder/vocabulary` does not serve yet.
 *
 * It exists now rather than later because `InspectorRail`'s
 * `Record<NodeKind, Component>` is total: a kind with no form does not compile.
 * That totality is the point (criterion 11), and satisfying it with a component
 * that renders the field the schema has is honest, where satisfying it with an
 * empty stub would be a blank pane wearing a component's name.
 *
 * `tool_id` is a SELECT when the server has served a catalogue and a text box
 * when it has not. Never a hardcoded list: a client-side catalogue is cut-list
 * item 17, and it would offer tools the compiler has never heard of.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'tool' }>
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{ commit: [change: InspectorCommit] }>()

const config = computed(() => props.node.config)
const control = (name: string) => `insp-${props.node.id}-${name}`

/** The served catalogue, or null while this build's `/vocabulary` is still v1. */
const catalogue = computed(() => props.vocabulary.tools ?? null)

/**
 * The options, with the node's own id folded in when the catalogue does not
 * carry it.
 *
 * A select whose value is not among its options renders BLANK, which would show
 * an author an empty control over a document that says something - so a stored
 * id from an older catalogue is offered as itself rather than silently dropped.
 * The server answers `library-unknown-id` for it, which is the honest message.
 */
const options = computed(() => {
  const rows = catalogue.value ?? []
  const known = rows.some((row) => row.tool_id === config.value.tool_id)
  return known ? rows : [...rows, { tool_id: config.value.tool_id as string, label: config.value.tool_id as string }]
})

const paramNames = computed(() => Object.keys(config.value.params))

function commitToolId(value: string): void {
  if (value === config.value.tool_id) return
  emit('commit', {
    label: 'Set tool',
    // `tool_id` is a `NodeId` on the wire, and every value in the catalogue is
    // one by construction. Minting rather than casting keeps the guard in the
    // one place the whole document mints ids.
    next: patchConfig(props.doc, props.node, { tool_id: toNodeId(value) as NodeId }),
  })
}
</script>

<template>
  <div class="inspector-form">
    <FieldRow
      label="Tool"
      :control-id="control('tool_id')"
      field="tool_id"
      :node-id="node.id"
      mono
      help="Which catalogue tool this node attaches. An opaque id the server looks up in a closed set - never a module path, which is why a document cannot execute code."
      v-slot="row"
    >
      <select
        v-if="catalogue"
        :id="control('tool_id')"
        :value="config.tool_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitToolId(($event.target as HTMLSelectElement).value)"
      >
        <option v-for="option in options" :key="option.tool_id" :value="option.tool_id">
          {{ option.label }}
        </option>
      </select>
      <input
        v-else
        :id="control('tool_id')"
        type="text"
        :value="config.tool_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitToolId(($event.target as HTMLInputElement).value)"
      />
    </FieldRow>

    <!--
      The parameters this node carries, READ ONLY here and named rather than
      edited. Which arguments a given `tool_id` accepts is 06's catalogue and
      04's form; listing what the document holds is the honest amount this plan
      can say, and it beats a surface that silently loses a stored value.
    -->
    <p class="tool-params" data-testid="tool-params">
      <template v-if="paramNames.length">
        Parameters: <code>{{ paramNames.join(', ') }}</code>
      </template>
      <template v-else>No parameters set.</template>
    </p>
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
.tool-params {
  margin: 6px 0 0;
  color: var(--text-40);
  font: 400 var(--fs-11)/1.5 var(--font-body);
}
.tool-params code { font-family: var(--font-mono); }
</style>
