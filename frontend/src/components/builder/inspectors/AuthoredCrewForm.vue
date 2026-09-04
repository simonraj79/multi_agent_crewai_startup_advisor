<script setup lang="ts">
import { computed, inject } from 'vue'
import { ArrowUpRight, ChevronDown, ChevronUp } from 'lucide-vue-next'
import { BUILDER_PROBLEMS } from '../../../composables/useBuilderProblems'
import { nodeId as toNodeId } from '../../../types/builder'
import type {
  AuthoredCrewConfig,
  BuilderDocument,
  BuilderNode,
  BuilderVocabulary,
  LlmConfig,
  NodeId,
  RetryConfig,
  Tier,
} from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import NumberRow from '../fields/NumberRow.vue'
import SegmentedRow from '../fields/SegmentedRow.vue'
import SwitchRow from '../fields/SwitchRow.vue'
import TierRegion from '../fields/TierRegion.vue'
import LlmFields from './LlmFields.vue'
import ModelPicker from './ModelPicker.vue'
import { patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'
import { CREW_ADVANCED_FIELDS } from './authoredFields'

/**
 * The authored crew - fifteen fields, and the membership that is not one.
 *
 * THE MEMBER LIST IS READ-ONLY AND ORDERABLE, which sounds like a contradiction
 * and is not. WHO is in the crew is the set of `member` edges arriving at this
 * node, so it is drawn on the canvas and there is nothing here to pick from.
 * WHAT ORDER their tasks run in is `task_order`, a stored field the edges
 * cannot express, so it is dragged here. Offering a membership dropdown as well
 * would give one fact two spellings, and Flowise's `agentTools` array is the
 * standing example of where that goes.
 *
 * REORDERING IS BUTTONS, NOT DRAG. 04 D2 says "drag-to-reorder"; this ships
 * up/down buttons instead, and the departure is deliberate rather than a
 * shortcut. A drag handle in a 260px rail needs a pointer, and D9's requirement
 * is that every control be keyboard-reachable - so a drag implementation would
 * have needed a keyboard fallback anyway, and the fallback alone is the whole
 * feature at a fifth of the surface. The order is what matters; the gesture is
 * not.
 *
 * THE MANAGER IS ONE OR THE OTHER, ENFORCED BY THE SCHEMA. `_validate_manager`
 * RAISES when a hierarchical crew has neither and when a sequential crew has
 * either - `Crew.__init__` itself raises on the first, which on a builder graph
 * means after every upstream node has already billed. So the form makes the
 * pair a single choice rather than two independent controls that can be wrong
 * together.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'crew' }> & { config: AuthoredCrewConfig }
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{
  commit: [change: InspectorCommit]
  focusNode: [id: string]
}>()

const problems = inject(BUILDER_PROBLEMS)

const id = computed(() => props.node.id)
const config = computed(() => props.node.config)
const control = (name: string) => `insp-${id.value}-${name}`
const prefix = computed(() => `insp-${id.value}-`)
const bounds = computed(() => props.vocabulary.bounds)

function commit(patch: Partial<AuthoredCrewConfig>, label: string): void {
  emit('commit', { label, next: patchConfig(props.doc, props.node, patch) })
}

/* --- members ------------------------------------------------------------ */

/** The agent nodes wired in along a `member` edge, in canvas order. */
const memberIds = computed(() =>
  props.doc.edges
    .filter((edge) => edge.target === props.node.id && edge.target_port === 'member')
    .map((edge) => edge.source),
)

/**
 * The members in the order their tasks run: `task_order` first, then anything
 * wired in and not yet ordered.
 *
 * The second half matters. A newly drawn `member` edge is a member the moment
 * it is drawn, and `task_order` does not know about it until something writes
 * one - so a list that showed only `task_order` would leave a just-connected
 * agent invisible on the surface that exists to say who is in the crew.
 */
const orderedMembers = computed(() => {
  const wired = memberIds.value
  const declared = config.value.task_order.filter((entry) => wired.includes(entry))
  const rest = wired.filter((entry) => !declared.includes(entry))
  return [...declared, ...rest]
})

function labelOf(nodeId: string): string {
  return props.doc.nodes.find((entry) => entry.id === nodeId)?.label ?? nodeId
}

function move(index: number, delta: number): void {
  const next = [...orderedMembers.value]
  const target = index + delta
  if (target < 0 || target >= next.length) return
  const [held] = next.splice(index, 1)
  next.splice(target, 0, held)
  commit({ task_order: next as NodeId[] }, `Run ${labelOf(held)} ${delta < 0 ? 'earlier' : 'later'}`)
}

/* --- the manager pair --------------------------------------------------- */

/**
 * Which manager this crew uses, as ONE choice over three states.
 *
 * `none` is only legal while the process is sequential, and the two managers
 * are only legal while it is hierarchical. Making it one control is what stops
 * an author reaching the shape `_validate_manager` refuses; switching to
 * hierarchical therefore has to seed a manager in the same commit, or the
 * document between the two clicks is one the schema will not parse.
 */
const managerMode = computed<'none' | 'llm' | 'agent'>(() =>
  config.value.manager_agent ? 'agent' : config.value.manager_llm ? 'llm' : 'none',
)

/** The escalation preset, or the first roster model - what a fresh manager runs on. */
function seedManagerLlm(): LlmConfig {
  return {
    model: 'google/gemini-3.8-flash',
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
  }
}

/** Agents that could manage this crew: any agent node that is not a member. */
const managerCandidates = computed(() =>
  props.doc.nodes.filter(
    (entry) => entry.kind === 'agent' && !memberIds.value.includes(entry.id),
  ),
)

function commitProcess(process: string | null): void {
  if (process !== 'sequential' && process !== 'hierarchical') return
  if (process === config.value.process) return
  if (process === 'sequential') {
    // Both managers go, in the same commit. A sequential crew with either one
    // set is a shape `_validate_manager` refuses outright.
    commit(
      { process, manager_llm: null, manager_agent: null },
      'Run this crew in sequence',
    )
    return
  }
  // Hierarchical needs one. Seeding an LLM manager is the choice that needs no
  // other node to exist; picking an agent is one click away below.
  commit(
    config.value.manager_llm || config.value.manager_agent
      ? { process }
      : { process, manager_llm: seedManagerLlm() },
    'Give this crew a manager',
  )
}

function commitManagerMode(mode: string | null): void {
  if (mode === 'llm') {
    commit(
      { manager_llm: config.value.manager_llm ?? seedManagerLlm(), manager_agent: null },
      'Manage with a model',
    )
    return
  }
  if (mode === 'agent') {
    const first = managerCandidates.value[0]
    if (!first) return
    commit(
      { manager_agent: config.value.manager_agent ?? first.id, manager_llm: null },
      'Manage with an agent',
    )
  }
}

function patchManagerLlm(patch: Partial<LlmConfig>, label: string): void {
  if (!config.value.manager_llm) return
  commit({ manager_llm: { ...config.value.manager_llm, ...patch } }, label)
}

function patchPlanningLlm(patch: Partial<LlmConfig>, label: string): void {
  if (!config.value.planning_llm) return
  commit({ planning_llm: { ...config.value.planning_llm, ...patch } }, label)
}

function commitPlanning(on: boolean): void {
  // Unlike the agent's, `planning_llm` is independently nullable - CrewAI falls
  // back to the crew's own model - so turning planning on seeds nothing and
  // turning it off leaves the choice alone.
  commit({ planning: on }, on ? 'Turn planning on' : 'Turn planning off')
}

function patchRetry(patch: Partial<RetryConfig>, label: string): void {
  commit({ retry: { ...config.value.retry, ...patch } }, label)
}

function commitPreset(tier: Tier, model: string): void {
  if (!config.value.manager_llm) return
  commit({ tier, manager_llm: { ...config.value.manager_llm, model } }, `Use the ${tier} model`)
}

const advancedForced = computed(() => {
  if (!problems) return false
  return problems.problemsForNode(props.node.id).some((problem) => {
    const field = problems.fieldFor(problem)
    return field !== undefined && (CREW_ADVANCED_FIELDS as readonly string[]).includes(field)
  })
})
</script>

<template>
  <div class="inspector-form">
    <SegmentedRow
      label="Process"
      :control-id="control('process')"
      field="process"
      :node-id="id"
      :model-value="config.process"
      :options="[
        { value: 'sequential', word: 'sequential' },
        { value: 'hierarchical', word: 'hierarchical' },
      ]"
      help="Sequential runs each member's task in the order below. Hierarchical gives the crew a manager that decides who does what, and CrewAI refuses to construct one without a manager - which on a graph means after every upstream node has billed."
      @commit="commitProcess"
    />

    <FieldRow
      label="Members"
      :control-id="control('members')"
      field="members"
      :node-id="id"
      group
      :note="`${orderedMembers.length}`"
      help="Wired in along member edges on the canvas. The order is this node's task_order, and it is the order their tasks run in."
    >
      <ol v-if="orderedMembers.length" class="member-list">
        <li v-for="(member, index) in orderedMembers" :key="member">
          <span class="member-rank">{{ index + 1 }}</span>
          <span class="member-label">{{ labelOf(member) }}</span>
          <button
            type="button"
            class="member-btn"
            :disabled="index === 0"
            :aria-label="`Run ${labelOf(member)} earlier`"
            @click="move(index, -1)"
          >
            <ChevronUp :size="12" aria-hidden="true" />
          </button>
          <button
            type="button"
            class="member-btn"
            :disabled="index === orderedMembers.length - 1"
            :aria-label="`Run ${labelOf(member)} later`"
            @click="move(index, 1)"
          >
            <ChevronDown :size="12" aria-hidden="true" />
          </button>
          <button
            type="button"
            class="member-btn"
            :aria-label="`Show ${labelOf(member)} on the canvas`"
            @click="emit('focusNode', member)"
          >
            <ArrowUpRight :size="12" aria-hidden="true" />
          </button>
        </li>
      </ol>
      <p v-else class="empty-note">
        No members yet. Draw a member edge from an agent to this crew.
      </p>
    </FieldRow>

    <template v-if="config.process === 'hierarchical'">
      <SegmentedRow
        label="Managed by"
        :control-id="control('manager_mode')"
        field="manager_agent"
        :node-id="id"
        :model-value="managerMode"
        :options="[
          { value: 'llm', word: 'a model' },
          { value: 'agent', word: 'an agent' },
        ]"
        help="One or the other, never both. A model manager is a plain LLM asked to delegate; an agent manager is a node on this canvas with its own role and backstory."
        @commit="commitManagerMode"
      />

      <FieldRow
        v-if="managerMode === 'agent'"
        label="Manager"
        :control-id="control('manager_agent')"
        field="manager_agent"
        :node-id="id"
        mono
        help="Any agent on this canvas that is not itself a member of this crew."
        v-slot="row"
      >
        <select
          :id="control('manager_agent')"
          :value="config.manager_agent ?? ''"
          :aria-describedby="row.describedBy"
          :aria-invalid="row.invalid"
          @change="commit({ manager_agent: toNodeId(($event.target as HTMLSelectElement).value) }, 'Choose manager')"
        >
          <option v-for="option in managerCandidates" :key="option.id" :value="option.id">
            {{ option.label }} ({{ option.id }})
          </option>
        </select>
      </FieldRow>

      <LlmFields
        v-if="managerMode === 'llm' && config.manager_llm"
        region="essentials"
        path="manager_llm"
        :value="config.manager_llm"
        :node-id="id"
        :control-prefix="prefix"
        :tiers="vocabulary.tiers"
        :tier="config.tier"
        @patch="patchManagerLlm"
        @preset="commitPreset"
      />
    </template>

    <TierRegion
      tier="advanced"
      kind="crew"
      :count="CREW_ADVANCED_FIELDS.length"
      :force-open="advancedForced"
    >
      <SwitchRow
        label="Memory"
        :control-id="control('memory')"
        field="memory"
        :node-id="id"
        :model-value="config.memory"
        help="CrewAI's unified crew memory at 1.15.18 - one switch, not the three short/long/entity toggles older docs describe."
        @commit="commit({ memory: $event }, 'Set memory')"
      />

      <SwitchRow
        label="Cache"
        :control-id="control('cache')"
        field="cache"
        :node-id="id"
        :model-value="config.cache"
        help="Reuses a tool result any member has already fetched inside this run."
        @commit="commit({ cache: $event }, 'Set cache')"
      />

      <NumberRow
        label="Requests per minute"
        :control-id="control('max_rpm')"
        field="max_rpm"
        :node-id="id"
        :model-value="config.max_rpm"
        :min="1"
        nullable
        placeholder="unlimited"
        help="A throttle across the whole crew, which is the level that matters when three members share one rate-limited tool."
        @commit="commit({ max_rpm: $event }, 'Set requests per minute')"
      />

      <!--
        The fifteenth field (00 S9 ruling, 2026-09-04). Advanced rather than
        Essentials, and `authoredFields.ts` carries the reason.
      -->
      <SwitchRow
        label="Verbose"
        :control-id="control('verbose')"
        field="verbose"
        :node-id="id"
        :model-value="config.verbose"
        help="CrewAI's own console logging. The run console reads frames rather than stdout, so this changes the server log and nothing an author sees here."
        @commit="commit({ verbose: $event }, 'Set verbose')"
      />

      <SwitchRow
        label="Planning"
        :control-id="control('planning')"
        field="planning"
        :node-id="id"
        :model-value="config.planning"
        help="The crew drafts a plan before it runs. Crew.planning is NOT deprecated - unlike Agent.reasoning, which the agent form replaces."
        @commit="commitPlanning"
      />

      <FieldRow
        v-if="config.planning"
        label="Planner model"
        :control-id="control('planning_llm-model')"
        field="planning_llm.model"
        :node-id="id"
        group
        :note="config.planning_llm ? undefined : 'crew default'"
        help="What the planning pass runs on. Empty leaves it to the crew's own model, which is the answer that cannot surprise you on the bill."
      >
        <ModelPicker
          mode="pick"
          :model-value="config.planning_llm?.model ?? null"
          :control-id="control('planning_llm-model')"
          @update:model-value="
            config.planning_llm
              ? patchPlanningLlm({ model: $event }, 'Set planner model')
              : commit({ planning_llm: { ...seedManagerLlm(), model: $event } }, 'Set planner model')
          "
        />
      </FieldRow>

      <NumberRow
        label="Iterations"
        :control-id="control('max_iter')"
        field="max_iter"
        :node-id="id"
        :model-value="config.max_iter"
        :min="1"
        :max="bounds.max_agent_iter"
        help="Accepted by the schema and ignored at run time - run_crew runs the crew whole. It round-trips so a save does not change the document, and it is still what the budget prices this node's calls at."
        @commit="commit({ max_iter: $event ?? 1 }, 'Set iteration ceiling')"
      />

      <NumberRow
        label="Guardrail retries"
        :control-id="control('guardrail_max_retries')"
        field="guardrail_max_retries"
        :node-id="id"
        :model-value="config.guardrail_max_retries"
        :min="0"
        :max="bounds.max_guardrail_retries"
        help="Also accepted and ignored at run time. The tier is still exactly what this node is priced and counted on."
        @commit="commit({ guardrail_max_retries: $event ?? 0 }, 'Set guardrail retries')"
      />

      <NumberRow
        label="Node retries"
        :control-id="control('retry-max_retries')"
        field="retry.max_retries"
        :node-id="id"
        :model-value="config.retry.max_retries"
        :min="0"
        :max="bounds.max_retries"
        help="How many times the whole crew is re-run when its step raises. The builder's own loop, inside run_crew."
        @commit="patchRetry({ max_retries: $event ?? 0 }, 'Set node retries')"
      />

      <NumberRow
        label="Retry backoff"
        :control-id="control('retry-backoff_seconds')"
        field="retry.backoff_seconds"
        :node-id="id"
        :model-value="config.retry.backoff_seconds"
        :min="0"
        :max="60"
        note="seconds"
        @commit="patchRetry({ backoff_seconds: $event ?? 0 }, 'Set retry backoff')"
      />

      <FieldRow
        label="Fallback model"
        :control-id="control('retry-fallback_model')"
        field="retry.fallback_model"
        :node-id="id"
        group
        :note="config.retry.fallback_model ? undefined : 'none'"
        help="What the LAST attempt runs on. A refusal is never retried with it."
      >
        <ModelPicker
          mode="pick"
          :model-value="config.retry.fallback_model"
          :control-id="control('retry-fallback_model')"
          @update:model-value="patchRetry({ fallback_model: $event || null }, 'Set fallback model')"
        />
      </FieldRow>

      <SegmentedRow
        label="On error"
        :control-id="control('on_error')"
        field="on_error"
        :node-id="id"
        :model-value="config.on_error ?? 'fail'"
        :options="[
          { value: 'fail', word: 'fail the run' },
          { value: 'route', word: 'route it' },
        ]"
        help="Routing grows a second source port named error on this card."
        @commit="commit({ on_error: ($event as 'fail' | 'route') }, 'Set error policy')"
      />

      <slot name="prompt-inputs" />
    </TierRegion>
  </div>
</template>

<style scoped>
.inspector-form { display: block; }

.member-list { display: grid; gap: 3px; margin: 0; padding: 0; list-style: none; }
.member-list li { display: flex; align-items: center; gap: 6px; padding: 4px 5px; border-radius: var(--r-sm); }
.member-list li:hover { background: var(--surface-raised); }
.member-rank { display: grid; width: 18px; height: 18px; flex: 0 0 auto; place-items: center; color: var(--accent-cyan); font: 600 10px/1 var(--font-mono); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-sm); }
.member-label { min-width: 0; flex: 1 1 auto; overflow: hidden; color: var(--text-body); font: 500 var(--fs-12)/1.3 var(--font-body); text-overflow: ellipsis; white-space: nowrap; }
.member-btn { display: grid; width: 20px; height: 20px; flex: 0 0 auto; place-items: center; padding: 0; color: var(--text-40); background: transparent; border: 0; border-radius: var(--r-sm); cursor: pointer; }
.member-btn:hover:not(:disabled) { color: var(--accent-cyan); }
.member-btn:disabled { cursor: not-allowed; opacity: 0.35; }
.member-btn:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

.empty-note { margin: 0; color: var(--text-40); font-size: var(--fs-11); line-height: 1.5; }
</style>
