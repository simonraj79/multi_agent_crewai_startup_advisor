<script setup lang="ts">
import { computed } from 'vue'
import { PenLine } from 'lucide-vue-next'
import { isAuthoredAgent, isAuthoredCrew, nodeId } from '../../../types/builder'
import type {
  AgentConfig,
  AuthoredAgentConfig,
  AuthoredCrewConfig,
  BuilderDocument,
  BuilderNode,
  BuilderVocabulary,
  CrewConfig,
  JsonScalar,
  LibraryAgentConfig,
  LibraryCrewConfig,
  Tier,
} from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import NumberRow from '../fields/NumberRow.vue'
import CredentialPicker from '../CredentialPicker.vue'
import ModelPicker from './ModelPicker.vue'
import AuthoredAgentForm from './AuthoredAgentForm.vue'
import AuthoredCrewForm from './AuthoredCrewForm.vue'
import PromptInputsField from './PromptInputsField.vue'
import { patchConfig, replaceNode } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * `agent` AND `crew`, LIBRARY arm and AUTHORED arm - four shapes, one entry.
 *
 * `InspectorRail`'s dispatch is `Record<NodeKind, Component>` and there are two
 * billable kinds, so this is the one component both land on. What changed with
 * plan 04 is that each kind now has TWO arms in `document.py`, discriminated by
 * presence rather than by a tag: "I named one of yours" (`agent_id` / `crew_id`)
 * and "I wrote my own". They are not two things an author picks in a dropdown,
 * which is why there is no tag - and they share almost nothing, which is why
 * the authored halves are their own components rather than fifty `v-if`s in
 * this file.
 *
 * WHAT STAYS HERE is the library arm, unchanged from before plan 04 except that
 * `prompt_inputs` moved to its own component (all four arms carry it) and the
 * two count fields moved to `NumberRow` (all four clamp the same way). The
 * three honest notes it has always carried are still true and still rendered:
 *
 *   - a crew's `max_iter` and `guardrail_max_retries` are accepted by the
 *     schema and IGNORED at run time, because `run_crew` runs the crew whole;
 *   - a crew's `tier` is still exactly what it is priced and counted on, on
 *     that word alone;
 *   - a crew has no `tools` control at all, because `BuilderModel` is
 *     `extra="forbid"` and the key is a 422 rather than a dropped field.
 *
 * The first and second were to be REMOVED by 04 D2, on the grounds that plan 09
 * makes the factory honour `tier` and `max_iter`. **Plan 09 has not landed**, so
 * removing them now would replace a true sentence with a false one. They come
 * out in the same commit that makes them false.
 *
 * CONVERT TO AUTHORED is D2's own escape hatch and the only way to reach the
 * authored arm from this console today: it copies the chosen YAML agent's id
 * into a role, goal and backstory the author then edits. One commit, so one
 * undo - because it is a change an author will want to take back after seeing
 * what it costs them (the library agent's real prompts live in YAML and the
 * document never had them, so what it can copy is a starting point rather than
 * the agent).
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'agent' | 'crew' }>
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{
  commit: [change: InspectorCommit]
  focusNode: [id: string]
}>()

const id = computed(() => props.node.id)
const config = computed(() => props.node.config)
const control = (name: string) => `insp-${id.value}-${name}`

/**
 * The four arms, narrowed once so no template has to re-ask.
 *
 * `isAuthoredAgent` and `isAuthoredCrew` are presence tests over the union
 * arms, exactly as `_one_of` discriminates them in `document.py`. Narrowing the
 * NODE rather than the config is what lets the authored components take a typed
 * `:node` prop instead of a config and an id.
 */
const libraryAgent = computed(() =>
  props.node.kind === 'agent' && !isAuthoredAgent(props.node.config)
    ? (props.node as Extract<BuilderNode, { kind: 'agent' }> & { config: LibraryAgentConfig })
    : null,
)
const authoredAgent = computed(() =>
  props.node.kind === 'agent' && isAuthoredAgent(props.node.config)
    ? (props.node as Extract<BuilderNode, { kind: 'agent' }> & { config: AuthoredAgentConfig })
    : null,
)
const libraryCrew = computed(() =>
  props.node.kind === 'crew' && !isAuthoredCrew(props.node.config)
    ? (props.node as Extract<BuilderNode, { kind: 'crew' }> & { config: LibraryCrewConfig })
    : null,
)
const authoredCrew = computed(() =>
  props.node.kind === 'crew' && isAuthoredCrew(props.node.config)
    ? (props.node as Extract<BuilderNode, { kind: 'crew' }> & { config: AuthoredCrewConfig })
    : null,
)

/** The library arm, either kind - what every control below is bound to. */
const library = computed<LibraryAgentConfig | LibraryCrewConfig | null>(
  () => libraryAgent.value?.config ?? libraryCrew.value?.config ?? null,
)

/**
 * `credential_id` is on THREE of the four arms and not on `LibraryCrewConfig`.
 *
 * Not an oversight in the schema: a library crew builds its own agents' LLMs
 * from `config.py`'s constants inside the `@CrewBase`, so there is no call for
 * a BYO key to attach to. The picker is therefore agent-only, and the row is
 * absent for a crew rather than disabled - there is nothing this node could do
 * with the answer.
 */
const keyed = computed(() => libraryAgent.value)

/* --- tier -------------------------------------------------------------- */

/**
 * How many escalation nodes this graph declares, against the bound the server
 * serves.
 *
 * ADVISORY ONLY, and it never disables anything. `escalation-count` is Tier 2:
 * the server counts and the client renders, and R6 is explicit that a
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
 * `sorted(BUILDABLE_BUILDER_CREW_IDS)` - the library MINUS the two crews whose
 * `__init__` takes typed findings a drawn document cannot express - so those
 * are already absent from every picker without this client holding a copy of
 * that list. A local skip-list would be cut list item 17 wearing a different
 * hat.
 *
 * But a document hand-edited past the widget, or written under an older build,
 * can still NAME one. Dropping it from the select would silently rewrite the
 * author's document to the first legal option the moment they touched anything
 * else; showing it, marked, leaves the document alone and lets the compiler's
 * own error say why.
 */
const servedIds = computed(() =>
  props.node.kind === 'agent' ? props.vocabulary.agent_ids : props.vocabulary.crew_ids,
)
const currentLibraryId = computed(() =>
  libraryAgent.value?.config.agent_id ?? libraryCrew.value?.config.crew_id ?? '',
)

const libraryIds = computed(() =>
  servedIds.value.includes(currentLibraryId.value)
    ? servedIds.value
    : [...servedIds.value, currentLibraryId.value],
)

const libraryUnknown = computed(
  () => !!library.value && !servedIds.value.includes(currentLibraryId.value),
)

function commitLibraryId(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  const patch =
    props.node.kind === 'agent' ? { agent_id: nodeId(value) } : { crew_id: nodeId(value) }
  emit('commit', {
    label: props.node.kind === 'agent' ? 'Choose agent' : 'Choose crew',
    next: patchConfig(props.doc, props.node, patch as Partial<AgentConfig & CrewConfig>),
  })
}

/* --- tools (library agent only) ----------------------------------------- */

/**
 * A checklist, so a duplicate is impossible by construction rather than refused
 * after the fact. `LibraryAgentConfig` refuses a repeat with "the same tool is
 * bound twice; list each tool once", and a checkbox cannot produce one.
 *
 * The AUTHORED arm has no such field: its tools are `attach` edges on the
 * canvas, which is why its form shows them read-only with a jump instead.
 */
function toggleTool(tool: string, on: boolean): void {
  const held = libraryAgent.value?.config.tools ?? []
  const tools = on ? [...held, tool] : held.filter((name) => name !== tool)
  emit('commit', {
    label: on ? `Bind ${tool}` : `Unbind ${tool}`,
    next: patchConfig(props.doc, props.node, { tools } as Partial<AgentConfig & CrewConfig>),
  })
}

/* --- BYO OpenRouter key ------------------------------------------------- */

/**
 * The document carries the credential's ID and nothing else. `null` rather than
 * deleting the key: the server field is `str | None` and an explicit null is
 * the one spelling that reads the same in a fingerprint, a saved draft and a
 * diff.
 */
function commitCredential(credentialId: string | null): void {
  if ((keyed.value?.config.credential_id ?? null) === credentialId) return
  emit('commit', {
    label: credentialId ? 'Use your own OpenRouter key' : 'Use the platform OpenRouter key',
    next: patchConfig(props.doc, props.node, {
      credential_id: credentialId,
    } as Partial<AgentConfig & CrewConfig>),
  })
}

/* --- counts and prompt inputs ------------------------------------------- */

function commitCount(field: 'max_iter' | 'guardrail_max_retries', value: number | null): void {
  if (value === null || value === config.value[field]) return
  emit('commit', {
    label: field === 'max_iter' ? 'Set iteration ceiling' : 'Set guardrail retries',
    next: patchConfig(props.doc, props.node, {
      [field]: value,
    } as Partial<AgentConfig & CrewConfig>),
  })
}

function commitInputs(
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

/* --- convert to authored ------------------------------------------------ */

/**
 * Turn a library agent into an authored one, in one commit.
 *
 * WHAT IT CAN AND CANNOT COPY, said out loud because the difference is the
 * whole honesty of the feature. The library agent's real role, goal and
 * backstory live in `config/agents.yaml` on the server - a document names an id
 * and never carries a prompt, which is the platform rule - so this client has
 * no access to them. What it writes is a STARTING POINT that names the agent it
 * came from, and the help text says so rather than letting an author believe
 * they now hold the Scoper's prompts.
 *
 * `tools` is dropped rather than carried, and that is not a loss: the authored
 * arm's tools are `attach` edges, so the honest translation of "this agent had
 * two tools bound" is "draw two tool nodes and wire them", which the canvas can
 * say and a config key cannot. The conversion notice says which tools were
 * bound so nobody has to remember.
 */
const convertible = computed(() => libraryAgent.value !== null)

function convertToAuthored(): void {
  const node = libraryAgent.value
  if (!node) return
  const from = node.config
  const authored: AuthoredAgentConfig = {
    tier: from.tier,
    on_error: from.on_error,
    max_iter: from.max_iter,
    guardrail_max_retries: from.guardrail_max_retries,
    prompt_inputs: { ...from.prompt_inputs },
    role: node.label,
    goal: `What ${node.label} is for. Copied from the ${from.agent_id} library agent, whose own prompts live in YAML on the server - edit this to say what you actually want.`,
    backstory: `The experience ${node.label} reasons from. Started from the ${from.agent_id} library agent; nothing here is that agent's real backstory, because a document never carries one.`,
    task: {
      description: `What ${node.label} should do with what reaches it.`,
      expected_output: 'What a finished answer looks like.',
      output_schema: null,
      markdown: false,
      async_execution: false,
    },
    llm: {
      // The tier's own preset, resolved by the picker on mount. Naming the
      // escalation default here would hardcode a model id in a component; the
      // tier chips are one click and the budget meter reprices either way.
      model: props.vocabulary.tiers.includes('escalation') && from.tier === 'escalation'
        ? 'google/gemini-3.8-flash'
        : 'google/gemini-3.5-flash-lite',
      temperature: null,
      top_p: null,
      max_tokens: null,
      timeout: null,
      response_format: null,
      frequency_penalty: null,
      presence_penalty: null,
      stop: [],
      seed: null,
      reasoning_effort: null,
    },
    max_rpm: null,
    max_execution_time: null,
    allow_delegation: false,
    memory: false,
    cache: true,
    respect_context_window: true,
    retry: { max_retries: 0, backoff_seconds: 0, fallback_model: null },
    system_template: null,
    prompt_template: null,
    response_template: null,
    tool_failure_policy: null,
    planning: false,
    planning_config: null,
    credential_id: from.credential_id,
  }
  emit('commit', {
    label: `Convert ${node.label} to an authored agent`,
    // `replaceNode` rather than a hand-rolled map: `patchConfig` merges one
    // level and this REPLACES the config wholesale, so the library arm's
    // `agent_id` and `tools` have to go rather than be spread over. The cast is
    // the same one `commit.ts` documents - the union is discriminated on `kind`,
    // a sibling key neither the spread nor the checker correlates.
    next: replaceNode(props.doc, { ...node, config: authored } as BuilderNode),
  })
}
</script>

<template>
  <!-- The authored arms. Each is its own component: they share the billable
       base and nothing else, and a single form over both would be a switch
       wearing a component's name. -->
  <AuthoredAgentForm
    v-if="authoredAgent"
    :doc="doc"
    :node="authoredAgent"
    :vocabulary="vocabulary"
    @commit="emit('commit', $event)"
    @focus-node="emit('focusNode', $event)"
  >
    <template #prompt-inputs>
      <PromptInputsField
        :doc="doc"
        :node-id="id"
        :value="config.prompt_inputs"
        @commit="commitInputs"
      />
    </template>
  </AuthoredAgentForm>

  <AuthoredCrewForm
    v-else-if="authoredCrew"
    :doc="doc"
    :node="authoredCrew"
    :vocabulary="vocabulary"
    @commit="emit('commit', $event)"
    @focus-node="emit('focusNode', $event)"
  >
    <template #prompt-inputs>
      <PromptInputsField
        :doc="doc"
        :node-id="id"
        :value="config.prompt_inputs"
        @commit="commitInputs"
      />
    </template>
  </AuthoredCrewForm>

  <!-- The library arm. -->
  <div v-else class="inspector-form">
    <FieldRow
      label="Tier"
      :control-id="control('tier')"
      field="tier"
      :node-id="id"
      group
      :note="escalationNote"
      :note-warn="escalationUsed >= escalationBound"
      help="Which OpenRouter tier this node's calls run on. A library node never names a model - its LLMs are built inside the YAML crew from the tier constants."
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

      <!-- Inside the tier row rather than beside it: it describes the button
           that was just pressed, and a separate row would read as a second
           control the author has to decide about. -->
      <ModelPicker mode="preset" :tier="config.tier" :control-id="control('tier-model')" />
    </FieldRow>

    <FieldRow
      v-if="libraryAgent"
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
        :value="libraryAgent.config.agent_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitLibraryId"
      >
        <option v-for="option in libraryIds" :key="option" :value="option">{{ option }}</option>
      </select>
    </FieldRow>

    <FieldRow
      v-if="libraryCrew"
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
        :value="libraryCrew.config.crew_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitLibraryId"
      >
        <option v-for="option in libraryIds" :key="option" :value="option">{{ option }}</option>
      </select>
    </FieldRow>

    <!--
      D2's escape hatch, and the only route to the authored arm this console
      has. Docked in the form, one commit, one undo.
    -->
    <FieldRow
      v-if="convertible"
      label="Write your own"
      :control-id="control('convert')"
      field="convert"
      :node-id="id"
      group
      help="Starts an authored agent from this node, keeping its tier, ceilings and prompt inputs. It cannot copy the library agent's prompts - those live in YAML on the server and a document never carries one - so what you get is a starting point that says where it came from."
    >
      <button type="button" class="convert-button" @click="convertToAuthored">
        <PenLine :size="12" aria-hidden="true" />
        Convert to an authored agent
      </button>
    </FieldRow>

    <FieldRow
      v-if="libraryAgent"
      label="Tools"
      :control-id="control('tools')"
      field="tools"
      :node-id="id"
      group
      :note="`${libraryAgent.config.tools.length} of ${vocabulary.research_tools.length}`"
      help="Bound at compile time. An analyst with no tool bound can still reason, but it cannot look anything up."
    >
      <ul v-if="vocabulary.research_tools.length" class="tool-list">
        <li v-for="tool in vocabulary.research_tools" :key="tool">
          <label>
            <input
              type="checkbox"
              :checked="libraryAgent.config.tools.includes(tool)"
              @change="toggleTool(tool, ($event.target as HTMLInputElement).checked)"
            />
            <span>{{ tool }}</span>
          </label>
        </li>
      </ul>
      <p v-else class="empty-note">This build registers no research tools.</p>
    </FieldRow>

    <FieldRow
      v-if="keyed"
      label="OpenRouter key"
      :control-id="control('credential_id')"
      field="credential_id"
      :node-id="id"
      :note="keyed.config.credential_id ? 'your key' : 'platform key'"
      help="Bring your own OpenRouter key and this node's calls are billed to it. The document keeps only the key's id; the secret stays in the vault and is resolved inside the run."
      v-slot="row"
    >
      <CredentialPicker
        kind="openrouter"
        :model-value="keyed.config.credential_id ?? null"
        :control-id="control('credential_id')"
        :described-by="row.describedBy"
        :invalid="row.invalid"
        @update:model-value="commitCredential"
      />
    </FieldRow>

    <NumberRow
      label="Iterations"
      :control-id="control('max_iter')"
      field="max_iter"
      :node-id="id"
      :model-value="config.max_iter"
      :min="1"
      :max="vocabulary.bounds.max_agent_iter"
      :help="
        libraryCrew
          ? 'Accepted by the schema and ignored at run time - a crew runs whole. It round-trips so a save does not change the document.'
          : `How many reasoning passes one call may take, up to ${vocabulary.bounds.max_agent_iter}.`
      "
      @commit="commitCount('max_iter', $event)"
    />

    <NumberRow
      label="Guardrail retries"
      :control-id="control('guardrail_max_retries')"
      field="guardrail_max_retries"
      :node-id="id"
      :model-value="config.guardrail_max_retries"
      :min="0"
      :max="vocabulary.bounds.max_guardrail_retries"
      :help="
        libraryCrew
          ? 'Also accepted and ignored at run time. The tier above is still exactly what this node is priced and counted on.'
          : 'Counted PER GUARDRAIL by CrewAI, so this is where one node multiplies rather than adds.'
      "
      @commit="commitCount('guardrail_max_retries', $event)"
    />

    <PromptInputsField
      :doc="doc"
      :node-id="id"
      :value="config.prompt_inputs"
      @commit="commitInputs"
    />
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

.convert-button { display: inline-flex; width: 100%; min-height: 32px; align-items: center; justify-content: center; gap: 6px; color: var(--text-muted); font: 600 var(--fs-12)/1 var(--font-body); background: transparent; border: 1px dashed var(--border-default); border-radius: var(--r-md); cursor: pointer; transition: color var(--motion-fast) ease, border-color var(--motion-fast) ease; }
.convert-button:hover { color: var(--text-title); border-color: var(--accent-cyan); }
.convert-button:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

.empty-note { margin: 0; color: var(--text-40); font-size: var(--fs-11); line-height: 1.5; }
</style>
