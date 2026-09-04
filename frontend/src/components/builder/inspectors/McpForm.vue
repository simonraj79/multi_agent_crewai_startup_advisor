<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ShieldAlert } from 'lucide-vue-next'
import type { BuilderDocument, BuilderNode, BuilderVocabulary, NodeId } from '../../../types/builder'
import type { McpServerRow } from '../../../types/builder'
import { nodeId as toNodeId } from '../../../types/builder'
import { attachmentsApi } from '../../../services/attachmentsApi'
import type { AttachmentsApiLike } from '../../../services/attachmentsApi'
import FieldRow from '../fields/FieldRow.vue'
import { patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * The `mcp` node: one MCP server, and WHICH of its tools this node exposes.
 *
 * The tool list comes from the server's LAST DISCOVERY, stored on the row, so
 * this renders without contacting anything. That is the whole reason discovery
 * writes its result to the database rather than returning it and forgetting:
 * an inspector that needed a live server would be blank whenever the server was
 * asleep, and an author would not be able to tell that from a server with no
 * tools.
 *
 * **A checked tool gets a read-only parameter preview** - property names, types
 * and required marks off its own `input_schema` - so the author sees what the
 * agent will be able to pass. The agent supplies the arguments at run time,
 * which is how MCP tools are meant to be called; a pinned-argument form is a v2
 * contract request and is recorded as one.
 *
 * **A suspicious tool is checkable** (PLANS.md decision 8, provisional). The
 * matched pattern is shown beside it and selecting it produces a WARNING rather
 * than an error, because the thirteen patterns have false positives by design.
 *
 * **A stale server offers "re-discover" rather than a silently old list.** A
 * server that renamed a tool between discovery and run simply fails to match
 * `tool_filter` and the agent runs without it - so an old list is not merely
 * untidy, it is a graph that will quietly do less than it says.
 */
const props = withDefaults(
  defineProps<{
    doc: BuilderDocument
    node: Extract<BuilderNode, { kind: 'mcp' }>
    vocabulary: BuilderVocabulary
    api?: AttachmentsApiLike
  }>(),
  { api: () => attachmentsApi },
)

const emit = defineEmits<{ commit: [change: InspectorCommit] }>()

const config = computed(() => props.node.config)
const control = (name: string) => `insp-${props.node.id}-${name}`
const selected = computed(() => config.value.tool_names)

const servers = ref<McpServerRow[]>([])
const loadProblem = ref('')
const discovering = ref(false)

/** This node's server, or null - absent, deleted, or not loaded yet. */
const server = computed(
  () => servers.value.find((row) => row.id === config.value.server_id) ?? null,
)

async function load(): Promise<void> {
  loadProblem.value = ''
  try {
    servers.value = await props.api.listMcpServers()
  } catch (error) {
    loadProblem.value = error instanceof Error ? error.message : String(error)
  }
}

onMounted(load)

async function rediscover(): Promise<void> {
  const row = server.value
  if (!row || discovering.value) return
  discovering.value = true
  try {
    const result = await props.api.discoverMcpServer(row.id)
    servers.value = servers.value.map((current) =>
      current.id === row.id
        ? {
            ...current,
            status: result.status,
            tools: result.tools,
            discovered_at: result.discovered_at,
            last_error: result.error,
            stale: result.status !== 'authorized',
          }
        : current,
    )
  } catch (error) {
    loadProblem.value = error instanceof Error ? error.message : String(error)
  } finally {
    discovering.value = false
  }
}

function commitServerId(value: string): void {
  if (value === config.value.server_id) return
  emit('commit', {
    label: 'Set MCP server',
    // Changing the server CLEARS the tool names. They are that server's names,
    // and carrying them to another one would produce `mcp-tool-unknown` for
    // every single one - a document wrong in as many places as it has ticks.
    next: patchConfig(props.doc, props.node, {
      server_id: toNodeId(value) as NodeId,
      tool_names: [],
    }),
  })
}

function toggleTool(name: string, on: boolean): void {
  const next = on
    ? [...selected.value, name]
    : selected.value.filter((entry) => entry !== name)
  emit('commit', {
    label: on ? `Expose ${name}` : `Hide ${name}`,
    next: patchConfig(props.doc, props.node, { tool_names: next }),
  })
}

/** Property names, types and required marks - read only, from the tool's schema. */
function parameters(
  schema: Record<string, unknown>,
): { name: string; type: string; required: boolean }[] {
  const properties = (schema?.properties ?? {}) as Record<string, { type?: unknown }>
  const required = new Set((schema?.required as string[]) ?? [])
  return Object.entries(properties).map(([name, spec]) => ({
    name,
    type: typeof spec?.type === 'string' ? spec.type : 'any',
    required: required.has(name),
  }))
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
      help="Which MCP server this node speaks to. The list is your own servers; add one in the MCP panel. Its URL is masked everywhere it is shown, because a hosted server's path can carry a token."
      v-slot="row"
    >
      <select
        v-if="servers.length"
        :id="control('server_id')"
        :value="config.server_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitServerId(($event.target as HTMLSelectElement).value)"
      >
        <option v-if="!server" :value="config.server_id">{{ config.server_id }}</option>
        <option v-for="option in servers" :key="option.id" :value="option.id">
          {{ option.label }}
        </option>
      </select>
      <input
        v-else
        :id="control('server_id')"
        type="text"
        :value="config.server_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitServerId(($event.target as HTMLInputElement).value)"
      />
    </FieldRow>

    <p v-if="loadProblem" class="mcp-note is-error" data-testid="mcp-form-problem">
      {{ loadProblem }}
    </p>

    <div v-if="server" class="mcp-server" data-testid="mcp-server-summary">
      <span class="mcp-chip">{{ server.transport }}</span>
      <span class="mcp-chip" :class="{ 'is-warn': server.stale }">{{ server.status }}</span>
      <span class="mcp-count" data-testid="mcp-count">
        {{ selected.length }} of {{ server.tools.length }} tools
      </span>
      <button
        v-if="server.stale || server.tools.length === 0"
        type="button"
        class="is-quiet"
        data-testid="mcp-rediscover"
        :disabled="discovering"
        @click="rediscover"
      >
        Re-discover
      </button>
    </div>

    <p v-if="server?.last_error" class="mcp-note is-error" data-testid="mcp-form-error">
      {{ server.last_error }}
    </p>

    <!-- Flowise's sentinel row, rather than a toast that is gone when looked for. -->
    <p
      v-if="server && server.tools.length === 0"
      class="mcp-note"
      data-testid="mcp-form-no-tools"
    >
      No tools available — check the server and re-discover.
    </p>

    <ul v-if="server && server.tools.length" class="mcp-tool-list">
      <li v-for="tool in server.tools" :key="tool.name" class="mcp-tool" data-testid="mcp-form-tool">
        <label class="mcp-tool-head">
          <input
            type="checkbox"
            :checked="selected.includes(tool.name)"
            :data-tool="tool.name"
            @change="toggleTool(tool.name, ($event.target as HTMLInputElement).checked)"
          />
          <span class="mcp-tool-name">{{ tool.name }}</span>
          <span
            v-if="tool.suspicious"
            class="mcp-chip is-warn"
            data-testid="mcp-form-suspicious"
            :title="`This description matches ${tool.matched_pattern}. Often innocent, and it reaches the agent's prompt - read it before you ship.`"
          >
            <ShieldAlert :size="10" aria-hidden="true" /> check wording
          </span>
        </label>
        <p class="mcp-tool-desc">{{ tool.description }}</p>
        <p
          v-if="selected.includes(tool.name) && parameters(tool.input_schema).length"
          class="mcp-params"
          data-testid="mcp-form-params"
        >
          <span v-for="param in parameters(tool.input_schema)" :key="param.name" class="mcp-param">
            <code>{{ param.name }}</code
            >: {{ param.type }}<template v-if="param.required">*</template>
          </span>
        </p>
      </li>
    </ul>

    <!--
      The empty selection, said loudly. `McpConfig` deliberately does not require
      `tool_names` to be non-empty at parse time - `document.py` raises where
      `bounds.py` reports - so an author who has added a server and not yet
      chosen its tools has an incomplete graph rather than a save that fails.
    -->
    <p v-if="selected.length === 0" class="mcp-note is-error" data-testid="mcp-tools">
      No tools selected yet, so this server exposes nothing to the agent it attaches to.
    </p>
    <p v-else class="mcp-note" data-testid="mcp-tools">
      Exposes <code>{{ selected.join(', ') }}</code>
    </p>
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
.mcp-note { margin: 6px 0 0; color: var(--text-40); font: 400 var(--fs-11)/1.5 var(--font-body); }
.mcp-note.is-error { color: var(--warn-text); }
.mcp-note code { font-family: var(--font-mono); }
.mcp-server { display: flex; align-items: center; gap: 6px; margin: 6px 0 0; flex-wrap: wrap; }
.mcp-chip { display: inline-flex; align-items: center; gap: 3px; padding: 1px 5px; border-radius: 3px; background: var(--surface-well); color: var(--text-40); font: 500 10px/1.4 var(--font-mono); }
.mcp-chip.is-warn { background: var(--warn-bg); color: var(--warn-text); }
.mcp-count { color: var(--text-40); font: 400 var(--fs-11)/1.3 var(--font-body); }
.mcp-tool-list { margin: 6px 0 0; padding: 0; list-style: none; display: grid; gap: 6px; }
.mcp-tool-head { display: flex; align-items: center; gap: 5px; }
.mcp-tool-name { color: var(--text-body); font: 500 var(--fs-11)/1.3 var(--font-mono); }
.mcp-tool-desc { margin: 2px 0 0 18px; color: var(--text-40); font: 400 var(--fs-11)/1.4 var(--font-body); }
.mcp-params { margin: 2px 0 0 18px; display: flex; flex-wrap: wrap; gap: 8px; color: var(--text-40); font: 400 10px/1.4 var(--font-mono); }
</style>
