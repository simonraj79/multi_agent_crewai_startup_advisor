<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Plus, X } from 'lucide-vue-next'
import { nodeId } from '../../../types/builder'
import type {
  AgentConfig,
  BuilderDocument,
  BuilderNode,
  BuilderVocabulary,
  CrewConfig,
  JsonScalar,
  Tier,
} from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import ScalarInput from '../fields/ScalarInput.vue'
import { coalesceKeyFor, patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * `agent` AND `crew` in one component, because they are one model.
 *
 * `AgentConfig` and `CrewConfig` both extend `_BillableConfig` in
 * `document.py` - the same tier, the same two retry ceilings, the same
 * `prompt_inputs` - and differ only in which library id they name and whether
 * `tools` exists. Two forms would be two copies of the shared four fifths, and
 * the copies would drift the first time a bound moved. One form is the truthful
 * modelling of what the schema says.
 *
 * WHAT MAKES THIS SURFACE DIFFERENT FROM ChatDev's. Every one of these controls
 * is here, in the docked rail, beside the graph. Theirs opens a modal, and an
 * "advanced settings" disclosure inside it, and child modals off that - so
 * reading what an agent is configured to do means covering up the thing you are
 * configuring it inside of. `tools` in particular is behind no disclosure here:
 * it is the difference between an analyst that can search and one that cannot,
 * which is not an advanced setting.
 *
 * THREE HONEST NOTES that a prettier form would leave out, and each one is a
 * real behaviour of the runtime:
 *   - a crew's `max_iter` and `guardrail_max_retries` are accepted by the schema
 *     and IGNORED at run time, because `run_crew` runs the crew whole;
 *   - a crew's `tier` is still exactly what it is priced and counted on, on that
 *     word alone;
 *   - a crew has no `tools` control at all, because `BuilderModel` is
 *     `extra="forbid"` and the key is a 422 rather than a dropped field.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'agent' | 'crew' }>
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{ commit: [change: InspectorCommit] }>()

const id = computed(() => props.node.id)
const config = computed(() => props.node.config)
const control = (name: string) => `insp-${id.value}-${name}`

/** Narrowed once, so the template never re-asks which member of the union this is. */
const agent = computed(() => (props.node.kind === 'agent' ? props.node : null))
const crew = computed(() => (props.node.kind === 'crew' ? props.node : null))

/* --- tier -------------------------------------------------------------- */

/**
 * How many escalation nodes this graph declares, against the bound the server
 * serves.
 *
 * ADVISORY ONLY, and it never disables anything. `escalation-count` is Tier 2
 * (§6.1): the server counts and the client renders, and R6 is explicit that a
 * client-side bound is a second opinion that silently disagrees with the
 * compiler after any server change. What this is for is the moment BEFORE the
 * refusal - an author picking a tier can see that four of five are spent
 * without first spending the fifth.
 */
const escalationUsed = computed(
  () =>
    props.doc.nodes.filter(
      (node) =>
        (node.kind === 'agent' || node.kind === 'crew') && node.config.tier === 'escalation',
    ).length,
)
const escalationBound = computed(() => props.vocabulary.bounds.max_escalation_nodes)
const escalationNote = computed(() => `${escalationUsed.value} of ${escalationBound.value} used`)

function commitTier(tier: Tier): void {
  if (tier === config.value.tier) return
  emit('commit', {
    label: `Set tier to ${tier}`,
    next: patchConfig(props.doc, props.node, { tier } as Partial<AgentConfig & CrewConfig>),
  })
}

/* --- library id -------------------------------------------------------- */

/**
 * The ids the server says are buildable, plus whatever this node already names.
 *
 * The second half is the interesting one. `_vocabulary()` serves
 * `sorted(BUILDABLE_BUILDER_CREW_IDS)` - `BUILDER_CREW_LIBRARY` minus the two
 * crews whose `__init__` takes typed findings a drawn document cannot express -
 * so `synthesis` and `report` are already absent from every picker without this
 * client holding a copy of that list. A local skip-list would be cut list item
 * 17 wearing a different hat.
 *
 * But a document hand-edited past the widget, or written under an older build,
 * can still NAME one. Dropping it from the select would silently rewrite the
 * author's document to the first legal option the moment they touched anything
 * else; showing it, marked, leaves the document alone and lets the compiler's
 * own `library-unbuildable-crew` error - already pinned to this node - say why.
 */
const libraryIds = computed(() => {
  const served = props.node.kind === 'agent' ? props.vocabulary.agent_ids : props.vocabulary.crew_ids
  const current = props.node.kind === 'agent' ? props.node.config.agent_id : props.node.config.crew_id
  return served.includes(current) ? served : [...served, current]
})

const libraryUnknown = computed(() => {
  const served = props.node.kind === 'agent' ? props.vocabulary.agent_ids : props.vocabulary.crew_ids
  const current = props.node.kind === 'agent' ? props.node.config.agent_id : props.node.config.crew_id
  return !served.includes(current)
})

function commitLibraryId(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  const patch =
    props.node.kind === 'agent' ? { agent_id: nodeId(value) } : { crew_id: nodeId(value) }
  emit('commit', {
    label: props.node.kind === 'agent' ? 'Choose agent' : 'Choose crew',
    next: patchConfig(props.doc, props.node, patch as Partial<AgentConfig & CrewConfig>),
  })
}

/* --- tools (agent only) ------------------------------------------------- */

/**
 * A checklist, so a duplicate is impossible by construction rather than refused
 * after the fact - which is what §6.1 means by that phrase. `AgentConfig`
 * refuses a repeat with "the same tool is bound twice; list each tool once", and
 * a checkbox cannot produce one.
 */
function toggleTool(tool: string, on: boolean): void {
  const held = agent.value?.config.tools ?? []
  const tools = on ? [...held, tool] : held.filter((name) => name !== tool)
  emit('commit', {
    label: on ? `Bind ${tool}` : `Unbind ${tool}`,
    next: patchConfig(props.doc, props.node, { tools } as Partial<AgentConfig & CrewConfig>),
  })
}

/* --- retry ceilings ---------------------------------------------------- */

function commitCount(field: 'max_iter' | 'guardrail_max_retries', event: Event): void {
  const low = field === 'max_iter' ? 1 : 0
  const high =
    field === 'max_iter'
      ? props.vocabulary.bounds.max_agent_iter
      : props.vocabulary.bounds.max_guardrail_retries
  const raw = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(raw)) return
  const clamped = Math.min(Math.max(Math.round(raw), low), high)
  if (clamped === config.value[field]) return
  emit('commit', {
    label: field === 'max_iter' ? 'Set iteration ceiling' : 'Set guardrail retries',
    next: patchConfig(props.doc, props.node, {
      [field]: clamped,
    } as Partial<AgentConfig & CrewConfig>),
  })
}

/* --- prompt inputs ------------------------------------------------------ */

const promptRows = computed(() => Object.entries(config.value.prompt_inputs))

/** The key being renamed, and to what. One at a time - only one has focus. */
const keyDraft = ref<{ from: string; to: string } | null>(null)
watch(config, () => {
  keyDraft.value = null
})

const keyHint = computed(() => {
  const draft = keyDraft.value
  if (!draft || draft.to === draft.from) return undefined
  if (!draft.to.trim()) return 'A prompt input needs a name.'
  if (draft.to in config.value.prompt_inputs) {
    return `This node already supplies ${draft.to}.`
  }
  return undefined
})

/** A fresh name no existing row holds, so adding twice does not overwrite once. */
function freeKey(): string {
  const held = config.value.prompt_inputs
  let index = 1
  while (`input_${index}` in held) index += 1
  return `input_${index}`
}

function writeInputs(
  inputs: Record<string, JsonScalar>,
  label: string,
  coalesceKey?: string,
): void {
  emit('commit', {
    label,
    next: patchConfig(props.doc, props.node, {
      prompt_inputs: inputs,
    } as Partial<AgentConfig & CrewConfig>),
    coalesceKey,
  })
}

function addInput(): void {
  writeInputs({ ...config.value.prompt_inputs, [freeKey()]: '' }, 'Add prompt input')
}

function removeInput(key: string): void {
  const next: Record<string, JsonScalar> = {}
  for (const [name, value] of Object.entries(config.value.prompt_inputs)) {
    if (name !== key) next[name] = value
  }
  writeInputs(next, `Remove prompt input ${key}`)
}

/**
 * Renaming rebuilds the map in place rather than deleting and re-adding.
 *
 * Order is visible - these rows are drawn in insertion order and CrewAI's
 * interpolation reads them by name - so a rename that moved the row to the
 * bottom would look like the author had lost it.
 */
function commitKey(): void {
  const draft = keyDraft.value
  keyDraft.value = null
  if (!draft || draft.to === draft.from || keyHint.value) return
  const next: Record<string, JsonScalar> = {}
  for (const [name, value] of Object.entries(config.value.prompt_inputs)) {
    next[name === draft.from ? draft.to : name] = value
  }
  writeInputs(next, `Rename prompt input to ${draft.to}`)
}

function commitValue(key: string, value: JsonScalar): void {
  writeInputs(
    { ...config.value.prompt_inputs, [key]: value },
    `Set prompt input ${key}`,
    coalesceKeyFor(id.value, `prompt_inputs.${key}`),
  )
}
</script>

<template>
  <div class="inspector-form">
    <FieldRow
      label="Tier"
      :control-id="control('tier')"
      field="tier"
      :node-id="id"
      group
      :note="escalationNote"
      :note-warn="escalationUsed >= escalationBound"
      help="Which OpenRouter tier this node's calls run on. A node never names a model."
    >
      <div class="segmented">
        <button
          v-for="tier in vocabulary.tiers"
          :key="tier"
          type="button"
          :aria-pressed="config.tier === tier"
          @click="commitTier(tier)"
        >
          <!-- Only spend shouts. The cheap option is unmarked; escalation
               carries the same amber the card's second inset ring uses, so the
               expensive choice looks expensive in both places. -->
          <i v-if="tier === 'escalation'" class="tier-dot" aria-hidden="true" />
          {{ tier }}
        </button>
      </div>
    </FieldRow>

    <FieldRow
      v-if="agent"
      label="Agent"
      :control-id="control('agent_id')"
      field="agent_id"
      :node-id="id"
      mono
      :note="libraryUnknown ? 'not in this build' : undefined"
      :note-warn="libraryUnknown"
      help="Keys the YAML agent registry. Prompts live in YAML; a document names an id and never a role."
      v-slot="row"
    >
      <select
        :id="control('agent_id')"
        :value="agent.config.agent_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitLibraryId"
      >
        <option v-for="option in libraryIds" :key="option" :value="option">{{ option }}</option>
      </select>
    </FieldRow>

    <FieldRow
      v-if="crew"
      label="Crew"
      :control-id="control('crew_id')"
      field="crew_id"
      :node-id="id"
      mono
      :note="libraryUnknown ? 'not in this build' : undefined"
      :note-warn="libraryUnknown"
      help="One registered crew, run whole. Its tools are the crew's own, which is why there is nothing to bind here."
      v-slot="row"
    >
      <select
        :id="control('crew_id')"
        :value="crew.config.crew_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitLibraryId"
      >
        <option v-for="option in libraryIds" :key="option" :value="option">{{ option }}</option>
      </select>
    </FieldRow>

    <FieldRow
      v-if="agent"
      label="Tools"
      :control-id="control('tools')"
      field="tools"
      :node-id="id"
      group
      :note="`${agent.config.tools.length} of ${vocabulary.research_tools.length}`"
      help="Bound at compile time. An analyst with no tool bound can still reason, but it cannot look anything up."
    >
      <ul v-if="vocabulary.research_tools.length" class="tool-list">
        <li v-for="tool in vocabulary.research_tools" :key="tool">
          <label>
            <input
              type="checkbox"
              :checked="agent.config.tools.includes(tool)"
              @change="toggleTool(tool, ($event.target as HTMLInputElement).checked)"
            />
            <span>{{ tool }}</span>
          </label>
        </li>
      </ul>
      <p v-else class="empty-note">This build registers no research tools.</p>
    </FieldRow>

    <FieldRow
      label="Iterations"
      :control-id="control('max_iter')"
      field="max_iter"
      :node-id="id"
      :help="
        crew
          ? 'Accepted by the schema and ignored at run time - a crew runs whole. It round-trips so a save does not change the document.'
          : `How many reasoning passes one call may take, up to ${vocabulary.bounds.max_agent_iter}.`
      "
      v-slot="row"
    >
      <input
        :id="control('max_iter')"
        type="number"
        min="1"
        :max="vocabulary.bounds.max_agent_iter"
        step="1"
        :value="config.max_iter"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitCount('max_iter', $event)"
      />
    </FieldRow>

    <FieldRow
      label="Guardrail retries"
      :control-id="control('guardrail_max_retries')"
      field="guardrail_max_retries"
      :node-id="id"
      :help="
        crew
          ? 'Also accepted and ignored at run time. The tier above is still exactly what this node is priced and counted on.'
          : 'Counted PER GUARDRAIL by CrewAI, so this is where one node multiplies rather than adds.'
      "
      v-slot="row"
    >
      <input
        :id="control('guardrail_max_retries')"
        type="number"
        min="0"
        :max="vocabulary.bounds.max_guardrail_retries"
        step="1"
        :value="config.guardrail_max_retries"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitCount('guardrail_max_retries', $event)"
      />
    </FieldRow>

    <FieldRow
      label="Prompt inputs"
      :control-id="control('prompt_inputs')"
      field="prompt_inputs"
      :node-id="id"
      group
      :hint="keyHint"
      help="Interpolated into the task's own YAML placeholders at kickoff. A value may be one resolvable state reference."
    >
      <div class="input-rows">
        <div v-for="[key, value] in promptRows" :key="key" class="input-row">
          <div class="input-key">
            <input
              type="text"
              class="key-box"
              spellcheck="false"
              autocomplete="off"
              :value="keyDraft && keyDraft.from === key ? keyDraft.to : key"
              :aria-label="`Name of prompt input ${key}`"
              @input="keyDraft = { from: key, to: ($event.target as HTMLInputElement).value }"
              @keydown.enter.prevent="commitKey"
              @blur="commitKey"
            />
            <button
              type="button"
              class="row-remove"
              :aria-label="`Remove prompt input ${key}`"
              @click="removeInput(key)"
            >
              <X :size="12" aria-hidden="true" />
            </button>
          </div>
          <ScalarInput
            :model-value="value"
            :doc="doc"
            :label="`${key} value`"
            :control-id="control(`prompt_inputs-${key}`)"
            :field="`prompt_inputs.${key}`"
            :node-id="id"
            :where="`prompt_inputs['${key}']`"
            @commit="commitValue(key, $event)"
          />
        </div>
        <p v-if="!promptRows.length" class="empty-note">
          Nothing supplied yet. The task's placeholders arrive unfilled.
        </p>
        <button type="button" class="row-add" @click="addInput">
          <Plus :size="12" aria-hidden="true" />
          Add prompt input
        </button>
      </div>
    </FieldRow>
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
.tier-dot { width: 6px; height: 6px; background: var(--warn-text); border-radius: var(--r-full); }

.tool-list { display: grid; gap: 2px; margin: 0; padding: 0; list-style: none; }
.tool-list label { display: flex; align-items: center; gap: 8px; padding: 5px 7px; border-radius: var(--r-sm); cursor: pointer; transition: background var(--motion-fast) ease; }
.tool-list label:hover { background: var(--surface-raised); }
.tool-list span { color: var(--text-body); font: 500 var(--fs-12)/1.3 var(--font-mono); }
.tool-list input { accent-color: var(--accent-cyan); }
.tool-list input:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 2px; }

.input-rows { display: grid; gap: 10px; }
/* A well per row, because a prompt input is a name AND a typed value and the
   two have to read as one thing - four unbounded controls in a column read as
   four fields. */
.input-row { padding: 9px 10px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.input-key { display: flex; align-items: center; gap: 6px; margin-bottom: 9px; }
.key-box { flex: 1 1 auto; min-width: 0; padding: 5px 7px; color: var(--accent-cyan); font: 600 var(--fs-12)/1.3 var(--font-mono); background: transparent; border: 1px solid transparent; border-radius: var(--r-sm); outline: 0; }
.key-box:hover { border-color: var(--border-default); }
.key-box:focus-visible { color: var(--text-title); border-color: var(--accent-cyan); box-shadow: var(--glow-input); }
.row-remove { display: grid; width: 22px; height: 22px; flex: 0 0 auto; place-items: center; padding: 0; color: var(--text-40); background: transparent; border: 0; border-radius: var(--r-sm); cursor: pointer; }
.row-remove:hover { color: var(--err-text); background: var(--err-bg); }
.row-remove:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.row-add { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 30px; color: var(--text-muted); font: 600 var(--fs-11)/1 var(--font-body); background: transparent; border: 1px dashed var(--border-default); border-radius: var(--r-md); cursor: pointer; transition: color var(--motion-fast) ease, border-color var(--motion-fast) ease; }
.row-add:hover { color: var(--text-title); border-color: var(--border-hover); }
.row-add:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.empty-note { margin: 0; color: var(--text-40); font-size: var(--fs-11); line-height: 1.5; }
</style>
