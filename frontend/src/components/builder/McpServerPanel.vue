<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { LoaderCircle, Plus, RefreshCw, ShieldAlert, Trash2, X } from 'lucide-vue-next'
import { attachmentsApi, AttachmentPolicyError } from '../../services/attachmentsApi'
import type { AttachmentsApiLike } from '../../services/attachmentsApi'
import type { McpServerDraft, McpServerRow } from '../../types/builder'

/**
 * The author's MCP servers: add one, discover its tools, see what it offered.
 *
 * MCP is the point where a finite catalogue becomes an open surface, and this
 * panel is where an author decides to open it. Four things it does that are
 * decisions rather than layout:
 *
 * **The URL is masked and there is no unmasked form on this side.** Hosted MCP
 * servers routinely put a token in the path, so a list that showed the whole
 * URL would publish a credential to anybody who could see the screen. The
 * server sends `origin/************` and this renders exactly that.
 *
 * **A failed discovery is a SENTENCE, not a toast.** The route answers 200 with
 * `status: "error"` and one line, and it lands under the row it is about. An
 * author whose server is unreachable needs to read why beside the thing that is
 * unreachable; a dismissible banner three seconds later is a worse version of
 * the same information.
 *
 * **A suspicious tool is LISTED with its matched pattern shown** (PLANS.md
 * decision 8, provisional). The thirteen injection patterns have false
 * positives by design - `act as` is ordinary English - so hiding a row would be
 * the quietly-divergent double this repository keeps warning about. The author
 * sees the warning and decides.
 *
 * **stdio is offered only where the deployment allows it.** The transport
 * select carries it, the server refuses it with `mcp-transport-disallowed`, and
 * this shows that refusal verbatim rather than pre-filtering the option: an
 * author who wonders why they cannot run a local server deserves the sentence
 * that says the deployment is remote-only, not a select that silently has two
 * entries.
 *
 * DOCKED, NEVER MODAL (R15). The add form opens inline under the list.
 */
const props = withDefaults(
  defineProps<{ api?: AttachmentsApiLike }>(),
  { api: () => attachmentsApi },
)

const emit = defineEmits<{
  /** An author picked a server and a tool subset for the selected `mcp` node. */
  choose: [payload: { serverId: string; toolNames: string[] }]
}>()

const rows = ref<McpServerRow[]>([])
const loading = ref(false)
/** Why the list is unavailable, as the server's own sentence, or ''. */
const listProblem = ref('')
/** Which row is mid-discovery. One at a time: each holds a threadpool slot. */
const discovering = ref<string | null>(null)
/** Per-row refusals, keyed by id, so a failure lands under its own row. */
const rowProblem = ref<Record<string, string>>({})
const expanded = ref<string | null>(null)

async function load(): Promise<void> {
  loading.value = true
  listProblem.value = ''
  try {
    rows.value = await props.api.listMcpServers()
  } catch (error) {
    listProblem.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

onMounted(load)

/* --- adding one --------------------------------------------------------- */

const adding = ref(false)
const draft = ref<McpServerDraft>({ label: '', transport: 'http', url: '' })
const addProblem = ref('')
/** The code beside a policy refusal, so the panel can say more than the sentence. */
const addProblemCode = ref('')
const saving = ref(false)

function openAdd(): void {
  adding.value = true
  addProblem.value = ''
  addProblemCode.value = ''
  draft.value = { label: '', transport: 'http', url: '' }
}

const canSave = computed(() => {
  const row = draft.value
  if (!row.label.trim()) return false
  return row.transport === 'stdio' ? Boolean(row.command?.trim()) : Boolean(row.url?.trim())
})

async function save(): Promise<void> {
  if (!canSave.value || saving.value) return
  saving.value = true
  addProblem.value = ''
  addProblemCode.value = ''
  try {
    const created = await props.api.createMcpServer({
      label: draft.value.label.trim(),
      transport: draft.value.transport,
      url: draft.value.url?.trim() || null,
      command: draft.value.command?.trim() || null,
      args: draft.value.args ?? [],
    })
    rows.value = [created, ...rows.value]
    adding.value = false
  } catch (error) {
    if (error instanceof AttachmentPolicyError) addProblemCode.value = error.code
    addProblem.value = error instanceof Error ? error.message : String(error)
  } finally {
    saving.value = false
  }
}

/* --- discovery ----------------------------------------------------------- */

async function discover(row: McpServerRow): Promise<void> {
  if (discovering.value) return
  discovering.value = row.id
  rowProblem.value = { ...rowProblem.value, [row.id]: '' }
  try {
    const result = await props.api.discoverMcpServer(row.id)
    // A `status: "error"` is a RESULT and lands on the row, not a rejection.
    rows.value = rows.value.map((current) =>
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
    if (result.status === 'authorized') expanded.value = row.id
  } catch (error) {
    rowProblem.value = {
      ...rowProblem.value,
      [row.id]: error instanceof Error ? error.message : String(error),
    }
  } finally {
    discovering.value = null
  }
}

async function remove(row: McpServerRow): Promise<void> {
  try {
    await props.api.deleteMcpServer(row.id)
    rows.value = rows.value.filter((current) => current.id !== row.id)
  } catch (error) {
    rowProblem.value = {
      ...rowProblem.value,
      [row.id]: error instanceof Error ? error.message : String(error),
    }
  }
}

/* --- picking tools ------------------------------------------------------- */

const picked = ref<Record<string, string[]>>({})

function toggleTool(row: McpServerRow, name: string): void {
  const current = picked.value[row.id] ?? []
  const next = current.includes(name)
    ? current.filter((entry) => entry !== name)
    : [...current, name]
  picked.value = { ...picked.value, [row.id]: next }
}

function attach(row: McpServerRow): void {
  emit('choose', { serverId: row.id, toolNames: picked.value[row.id] ?? [] })
}

function isPicked(row: McpServerRow, name: string): boolean {
  return (picked.value[row.id] ?? []).includes(name)
}

/**
 * The read-only parameter preview - D5.
 *
 * Property names, types and required marks off the tool's own `input_schema`,
 * so the author sees what the agent will be able to pass. The AGENT supplies
 * the arguments at run time, which is how MCP tools are meant to be called; a
 * pinned-argument form is v2 and is recorded as a contract request.
 */
function parameters(schema: Record<string, unknown>): { name: string; type: string; required: boolean }[] {
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
  <section class="mcp-panel" data-testid="mcp-panel">
    <header class="mcp-head">
      <h3>MCP servers</h3>
      <button type="button" class="mcp-add" data-testid="mcp-add" @click="openAdd">
        <Plus :size="12" aria-hidden="true" /> Add
      </button>
    </header>

    <p class="mcp-blurb">Extensibility: any server's tools, on your own key.</p>

    <p v-if="loading" class="mcp-note" data-testid="mcp-loading">
      <LoaderCircle :size="12" class="spin" aria-hidden="true" /> Loading…
    </p>
    <p v-else-if="listProblem" class="mcp-note is-error" data-testid="mcp-list-problem">
      {{ listProblem }}
    </p>
    <p v-else-if="rows.length === 0" class="mcp-note" data-testid="mcp-empty">
      No servers yet. Add one by URL and discover what it offers.
    </p>

    <!-- The add form, docked under the list rather than over the graph. -->
    <form v-if="adding" class="mcp-form" data-testid="mcp-form" @submit.prevent="save">
      <label>
        Label
        <input v-model="draft.label" type="text" maxlength="80" data-testid="mcp-label" />
      </label>
      <label>
        Transport
        <select v-model="draft.transport" data-testid="mcp-transport">
          <option value="http">HTTP (streamable)</option>
          <option value="sse">SSE</option>
          <option value="stdio">stdio (local process)</option>
        </select>
      </label>
      <label v-if="draft.transport === 'stdio'">
        Command
        <input v-model="draft.command" type="text" data-testid="mcp-command" />
      </label>
      <label v-else>
        URL
        <input v-model="draft.url" type="url" placeholder="https://…" data-testid="mcp-url" />
      </label>
      <p v-if="addProblem" class="mcp-note is-error" data-testid="mcp-add-problem">
        <ShieldAlert v-if="addProblemCode" :size="12" aria-hidden="true" />
        {{ addProblem }}
      </p>
      <div class="mcp-actions">
        <button type="submit" :disabled="!canSave || saving" data-testid="mcp-save">Save</button>
        <button type="button" class="is-quiet" data-testid="mcp-cancel" @click="adding = false">
          <X :size="12" aria-hidden="true" /> Cancel
        </button>
      </div>
    </form>

    <ul class="mcp-rows">
      <li v-for="row in rows" :key="row.id" class="mcp-row" data-testid="mcp-row" :data-server-id="row.id">
        <div class="mcp-row-head">
          <span class="mcp-row-label">{{ row.label }}</span>
          <span class="mcp-chip">{{ row.transport }}</span>
          <span class="mcp-chip" :class="{ 'is-warn': row.stale }" data-testid="mcp-status">
            {{ row.status }}
          </span>
          <span v-if="row.url" class="mcp-url" data-testid="mcp-masked-url">{{ row.url }}</span>
          <span v-if="row.has_header_credential" class="mcp-chip is-key">key</span>
          <button
            type="button"
            class="is-quiet"
            data-testid="mcp-discover"
            :disabled="discovering === row.id"
            @click="discover(row)"
          >
            <LoaderCircle v-if="discovering === row.id" :size="12" class="spin" aria-hidden="true" />
            <RefreshCw v-else :size="12" aria-hidden="true" />
            {{ row.stale ? 'Discover' : 'Re-discover' }}
          </button>
          <button type="button" class="is-quiet" data-testid="mcp-delete" @click="remove(row)">
            <Trash2 :size="12" aria-hidden="true" />
            <span class="sr-only">Delete {{ row.label }}</span>
          </button>
        </div>

        <p v-if="row.last_error" class="mcp-note is-error" data-testid="mcp-row-error">
          {{ row.last_error }}
        </p>
        <p v-if="rowProblem[row.id]" class="mcp-note is-error" data-testid="mcp-row-problem">
          {{ rowProblem[row.id] }}
        </p>

        <!--
          Flowise's sentinel pattern: one row saying the list is empty, rather
          than a toast that has gone by the time the author looks.
        -->
        <p
          v-if="row.status === 'authorized' && row.tools.length === 0"
          class="mcp-note"
          data-testid="mcp-no-tools"
        >
          No tools available — check the server and re-discover.
        </p>

        <ul v-if="row.tools.length" class="mcp-tools">
          <li v-for="tool in row.tools" :key="tool.name" class="mcp-tool" data-testid="mcp-tool">
            <label class="mcp-tool-head">
              <input
                type="checkbox"
                :checked="isPicked(row, tool.name)"
                :data-tool="tool.name"
                @change="toggleTool(row, tool.name)"
              />
              <span class="mcp-tool-name">{{ tool.name }}</span>
              <span
                v-if="tool.suspicious"
                class="mcp-chip is-warn"
                data-testid="mcp-suspicious"
                :title="`This description matches ${tool.matched_pattern}. Often innocent - the pattern list has false positives - but it reaches the agent's prompt, so read it before you ship.`"
              >
                <ShieldAlert :size="10" aria-hidden="true" /> check wording
              </span>
            </label>
            <p class="mcp-tool-desc">{{ tool.description }}</p>
            <!-- Read only. The AGENT supplies the arguments at run time. -->
            <p
              v-if="isPicked(row, tool.name) && parameters(tool.input_schema).length"
              class="mcp-params"
              data-testid="mcp-params"
            >
              <span v-for="param in parameters(tool.input_schema)" :key="param.name" class="mcp-param">
                <code>{{ param.name }}</code
                >: {{ param.type }}<template v-if="param.required">*</template>
              </span>
            </p>
          </li>
        </ul>

        <button
          v-if="row.tools.length"
          type="button"
          class="mcp-attach"
          data-testid="mcp-attach"
          :disabled="(picked[row.id] ?? []).length === 0"
          @click="attach(row)"
        >
          Attach {{ (picked[row.id] ?? []).length }} of {{ row.tools.length }} tools
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.mcp-panel { display: block; }
.mcp-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.mcp-head h3 { margin: 0; color: var(--text-title); font: 600 var(--fs-12)/1.3 var(--font-body); }
.mcp-blurb { margin: 2px 0 8px; color: var(--text-40); font: 400 var(--fs-11)/1.4 var(--font-body); }
.mcp-note { margin: 4px 0; display: flex; align-items: center; gap: 4px; color: var(--text-40); font: 400 var(--fs-11)/1.5 var(--font-body); }
.mcp-note.is-error { color: var(--warn-text); }
.mcp-form { display: grid; gap: 6px; padding: 8px; background: var(--surface-well); border-radius: var(--r-sm); }
.mcp-form label { display: grid; gap: 3px; color: var(--text-40); font: 500 var(--fs-11)/1.3 var(--font-body); }
.mcp-actions { display: flex; gap: 6px; }
.mcp-rows { margin: 8px 0 0; padding: 0; list-style: none; display: grid; gap: 8px; }
.mcp-row { padding: 8px; background: var(--surface-panel); border: 1px solid var(--border-default); border-radius: var(--r-sm); }
.mcp-row-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.mcp-row-label { color: var(--text-body); font: 500 var(--fs-12)/1.3 var(--font-body); }
.mcp-url { color: var(--text-40); font: 400 10px/1.3 var(--font-mono); }
.mcp-chip { padding: 1px 5px; border-radius: 3px; background: var(--surface-well); color: var(--text-40); font: 500 10px/1.4 var(--font-mono); }
.mcp-chip.is-warn { background: var(--warn-bg); color: var(--warn-text); }
.mcp-chip.is-key { color: var(--text-body); }
.mcp-tools { margin: 6px 0 0; padding: 0; list-style: none; display: grid; gap: 6px; }
.mcp-tool-head { display: flex; align-items: center; gap: 5px; }
.mcp-tool-name { color: var(--text-body); font: 500 var(--fs-11)/1.3 var(--font-mono); }
.mcp-tool-desc { margin: 2px 0 0 18px; color: var(--text-40); font: 400 var(--fs-11)/1.4 var(--font-body); }
.mcp-params { margin: 2px 0 0 18px; display: flex; flex-wrap: wrap; gap: 8px; color: var(--text-40); font: 400 10px/1.4 var(--font-mono); }
.mcp-attach { margin-top: 6px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.spin { animation: mcp-spin 1s linear infinite; }
@keyframes mcp-spin { to { transform: rotate(360deg); } }
</style>
