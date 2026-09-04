<script setup lang="ts">
import { computed } from 'vue'
import type { BuilderDocument, BuilderNode, BuilderVocabulary, NodeId } from '../../../types/builder'
import { nodeId as toNodeId } from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import { patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * The `mcp` node: one MCP server, and WHICH of its tools this node exposes.
 *
 * Same boundary as `ToolForm`, for the same reason: 03 owns the kind, its port
 * and its identity on the canvas; **07 owns discovery** - which servers a
 * deployment may reach, what transports are allowed, and what tools a given
 * server actually offers. Nothing here can therefore offer a tool LIST, because
 * nothing here has contacted a server. What it can do is show the two fields
 * the document carries and refuse to invent either.
 *
 * The empty `tool_names` is the state worth being loud about. `McpConfig`
 * deliberately does not require it to be non-empty at parse time -
 * `document.py` raises where `bounds.py` reports - so an author who has added a
 * server and not yet chosen its tools has an incomplete graph rather than a
 * save that fails. This form says so in a sentence; the dock says so as a
 * problem; neither pretends the node is finished.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'mcp' }>
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{ commit: [change: InspectorCommit] }>()

const config = computed(() => props.node.config)
const control = (name: string) => `insp-${props.node.id}-${name}`
const selected = computed(() => config.value.tool_names)

function commitServerId(value: string): void {
  if (value === config.value.server_id) return
  emit('commit', {
    label: 'Set MCP server',
    next: patchConfig(props.doc, props.node, { server_id: toNodeId(value) as NodeId }),
  })
}
</script>

<template>
  <div class="inspector-form">
    <FieldRow
      label="Server"
      :control-id="control('server_id')"
      field="server_id"
      :node-id="node.id"
      mono
      help="Which MCP server this node speaks to, by id. Discovery, transports and which servers this deployment may reach at all are the MCP client's business, not this document's."
      v-slot="row"
    >
      <input
        :id="control('server_id')"
        type="text"
        :value="config.server_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitServerId(($event.target as HTMLInputElement).value)"
      />
    </FieldRow>

    <!--
      Read only, and named rather than picked. A picker over a server's tools
      needs a server that has been contacted, which is 07's work; listing what
      the document holds is what this plan can say truthfully.
    -->
    <p class="mcp-tools" :class="{ 'is-empty': selected.length === 0 }" data-testid="mcp-tools">
      <template v-if="selected.length">
        Exposes <code>{{ selected.join(', ') }}</code>
      </template>
      <template v-else>
        No tools selected yet, so this server exposes nothing to the agent it attaches to.
      </template>
    </p>
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
.mcp-tools {
  margin: 6px 0 0;
  color: var(--text-40);
  font: 400 var(--fs-11)/1.5 var(--font-body);
}
.mcp-tools.is-empty { color: var(--warn-text); }
.mcp-tools code { font-family: var(--font-mono); }
</style>
