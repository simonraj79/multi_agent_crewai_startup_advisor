<script setup lang="ts">
import { computed, inject } from 'vue'
import { ArrowUpRight } from 'lucide-vue-next'
import { BUILDER_PROBLEMS } from '../../../composables/useBuilderProblems'
import { NODE_KINDS } from '../../../data/nodeKinds'
import type {
  AuthoredAgentConfig,
  BuilderDocument,
  BuilderNode,
  BuilderVocabulary,
  LlmConfig,
  PlanningConfig,
  RetryConfig,
  TaskConfig,
  Tier,
  ToolFailurePolicy,
} from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import NumberRow from '../fields/NumberRow.vue'
import PromptField from '../fields/PromptField.vue'
import SchemaEditor from '../fields/SchemaEditor.vue'
import SegmentedRow from '../fields/SegmentedRow.vue'
import SwitchRow from '../fields/SwitchRow.vue'
import TierRegion from '../fields/TierRegion.vue'
import LlmFields from './LlmFields.vue'
import ModelPicker from './ModelPicker.vue'
import { coalesceKeyFor, patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'
import { ADVANCED_FIELDS, EXPERT_FIELDS } from './authoredFields'

/**
 * The authored agent - every FD5 leaf the S9 deprecation ruling leaves standing,
 * across D1's three regions.
 *
 * THE ARITHMETIC, because the plan and the package disagreed and the package
 * won. FD5's table is 41 leaf controls. Four of them are deprecated at CrewAI
 * 1.15.18 and are CUT or REPLACED by the 00 S9 ruling, and the replacement is
 * five controls rather than two:
 *
 *     41  FD5 leaves
 *      −2  `multimodal`, `function_calling_llm`            CUT: deprecated,
 *                                                          `multimodal` goes at v2.0
 *      −2  `reasoning`, `max_reasoning_attempts`           REPLACED
 *      +5  `planning` + `planning_config`'s four           the replacement
 *     ═══
 *      42  leaf controls this form renders
 *
 * plus the attachments read-out, which is not a field: tools, MCP servers and
 * skills arrive along `attach` edges and are shown here read-only, with a jump
 * to the node. **A dropdown of tools would be the Flowise `agentTools`
 * anti-pattern**, and the reason it is an anti-pattern is not taste: a list
 * inside a form cannot show you that two agents share one tool, and the canvas
 * can.
 *
 * WHY `planning_config` IS FOUR AND NOT ELEVEN. CrewAI's `PlanningConfig`
 * carries eleven fields. `system_prompt`, `plan_prompt` and `refine_prompt` are
 * excluded because prompts live in YAML for this repository's crews and in the
 * document for an authored agent, and a third place would be a third place.
 * `llm` is excluded because it would put the planner on a different model from
 * the one the node names - a cost surprise with no visible cause, on the one
 * surface whose whole argument is that it tells you what things cost. The other
 * three are not cut on principle; nobody has a reason to expose them, and an
 * unused control is a control an author has to decide about.
 *
 * COMMITS ARE COMPOSITE-AWARE. `patchConfig` merges one level, so a change to
 * `llm.temperature` has to spread `llm` itself or the other ten leaves are
 * dropped. That is what `patchTask`, `patchLlm`, `patchRetry` and
 * `patchPlanning` are for, and it is the one thing in this file that would fail
 * silently if it were got wrong - the document would still parse, having lost
 * ten fields.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'agent' }> & { config: AuthoredAgentConfig }
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{
  commit: [change: InspectorCommit]
  /** "Jump to node" on an attachment - the same channel `ProblemsPanel` uses. */
  focusNode: [id: string]
}>()

const problems = inject(BUILDER_PROBLEMS)

const id = computed(() => props.node.id)
const config = computed(() => props.node.config)
const control = (name: string) => `insp-${id.value}-${name}`
const prefix = computed(() => `insp-${id.value}-`)

const bounds = computed(() => props.vocabulary.bounds)

/* --- commits ------------------------------------------------------------ */

function commit(patch: Partial<AuthoredAgentConfig>, label: string, coalesceKey?: string): void {
  emit('commit', { label, next: patchConfig(props.doc, props.node, patch), coalesceKey })
}

/** A prompt is typed, so its commits coalesce into one undo step. */
function commitPrompt(
  field: 'role' | 'goal' | 'backstory',
  value: string | null,
  label: string,
): void {
  if (value === null) return
  commit({ [field]: value } as Partial<AuthoredAgentConfig>, label, coalesceKeyFor(id.value, field))
}

function patchTask(patch: Partial<TaskConfig>, label: string, coalesceKey?: string): void {
  commit({ task: { ...config.value.task, ...patch } }, label, coalesceKey)
}

function patchLlm(patch: Partial<LlmConfig>, label: string): void {
  commit({ llm: { ...config.value.llm, ...patch } }, label)
}

function patchRetry(patch: Partial<RetryConfig>, label: string): void {
  commit({ retry: { ...config.value.retry, ...patch } }, label)
}

/**
 * A tier chip: the model AND the tier, in one commit.
 *
 * Two fields because they answer to two layers. `llm.model` is what the run
 * calls; `tier` is what `bounds.py` counts against `MAX_ESCALATION_NODES` and
 * what `budget.py` prices, on that word alone. Writing one without the other
 * gives a graph admitted at one price and run at another, which is the shape of
 * the defect that reported 128,069 real tokens at $0.00.
 */
function commitPreset(tier: Tier, model: string): void {
  commit({ tier, llm: { ...config.value.llm, model } }, `Use the ${tier} model`)
}

/**
 * `planning_config` exists only while `planning` is on.
 *
 * `AuthoredAgentConfig._validate_planning` RAISES on the other shape - four
 * numbers under a switch that is off configure nothing - so turning the switch
 * off drops the object rather than leaving it stranded, and turning it on
 * seeds the schema's own defaults. The inspector never writes the shape the
 * schema refuses.
 */
const PLANNING_DEFAULTS: PlanningConfig = {
  reasoning_effort: 'medium',
  max_attempts: null,
  max_steps: 20,
  max_replans: 3,
}

function commitPlanning(on: boolean): void {
  commit(
    on
      ? { planning: true, planning_config: { ...PLANNING_DEFAULTS } }
      : { planning: false, planning_config: null },
    on ? 'Turn planning on' : 'Turn planning off',
  )
}

function patchPlanning(patch: Partial<PlanningConfig>, label: string): void {
  const held = config.value.planning_config ?? PLANNING_DEFAULTS
  commit({ planning_config: { ...held, ...patch } }, label)
}

/* --- attachments, read-only -------------------------------------------- */

/**
 * What is wired to this node along an `attach` edge, in canvas order.
 *
 * READ-ONLY BY CONSTRUCTION, and that is D2's ruling rather than a limitation:
 * an attachment is an edge, so the place to add or remove one is the canvas,
 * and a dropdown here would be a second way to express a thing that already has
 * a truthful one. Flowise v2's `agentTools` array is the counter-example and it
 * is the reason the rule is written down.
 */
const attachments = computed(() =>
  props.doc.edges
    .filter((edge) => edge.target === props.node.id && edge.target_port === 'attach')
    .map((edge) => props.doc.nodes.find((entry) => entry.id === edge.source))
    .filter((entry): entry is BuilderNode => Boolean(entry)),
)

/* --- which regions a problem forces open -------------------------------- */

/**
 * Whether any control in a region carries a server problem.
 *
 * D1: a field carrying a problem forces its region open. An error behind a
 * closed disclosure is the modal-stack failure R15 exists to prevent, in
 * miniature - the author is told the document is invalid and shown a form that
 * looks clean.
 *
 * It reads the SAME anchor the field rows read (`fieldFor`, which prefers C8's
 * `field` over `FIELD_CODES`), so a region can never open for a problem no
 * control inside it will render, and a control can never render one whose
 * region stayed shut.
 */
function regionHasProblem(fields: readonly string[]): boolean {
  if (!problems) return false
  return problems
    .problemsForNode(props.node.id)
    .some((problem) => {
      const field = problems.fieldFor(problem)
      return field !== undefined && fields.includes(field)
    })
}

const advancedForced = computed(() => regionHasProblem(ADVANCED_FIELDS))
const expertForced = computed(() => regionHasProblem(EXPERT_FIELDS))

/**
 * How many Expert controls the switch is hiding - the `N` in "N expert settings
 * hidden".
 *
 * COUNTED, not written down, because `planning_config`'s four are rendered only
 * while `planning` is on and a fixed number would be wrong half the time. A
 * count an author can check against what appears when they press "show" is the
 * only kind worth printing.
 */
const expertCount = computed(
  () => EXPERT_FIELDS.length - (config.value.planning ? 0 : 4),
)

const advancedCount = ADVANCED_FIELDS.length
</script>

<template>
  <div class="inspector-form">
    <!-- ================= ESSENTIALS - always open ================= -->
    <PromptField
      label="Role"
      :control-id="control('role')"
      field="role"
      :node-id="id"
      :model-value="config.role"
      :max="bounds.max_prompt_chars"
      required
      :rows="2"
      help="Who this agent is, in a phrase. CrewAI puts it at the top of every prompt this node sends."
      @commit="commitPrompt('role', $event, 'Set role')"
    />

    <PromptField
      label="Goal"
      :control-id="control('goal')"
      field="goal"
      :node-id="id"
      :model-value="config.goal"
      :max="bounds.max_prompt_chars"
      required
      :rows="3"
      help="What it is trying to achieve, which is not the same as what this one task asks for."
      @commit="commitPrompt('goal', $event, 'Set goal')"
    />

    <PromptField
      label="Backstory"
      :control-id="control('backstory')"
      field="backstory"
      :node-id="id"
      :model-value="config.backstory"
      :max="bounds.max_prompt_chars"
      required
      :rows="4"
      help="The experience it reasons from. This is where an agent stops being a job title."
      @commit="commitPrompt('backstory', $event, 'Set backstory')"
    />

    <PromptField
      label="Task"
      :control-id="control('task-description')"
      field="task.description"
      :node-id="id"
      :model-value="config.task.description"
      :max="bounds.max_prompt_chars"
      required
      :rows="4"
      help="The one instruction this node runs. Reference upstream results with ${state.out__node_id}."
      @commit="patchTask({ description: $event ?? '' }, 'Set task', coalesceKeyFor(id, 'task.description'))"
    />

    <PromptField
      label="Expected output"
      :control-id="control('task-expected_output')"
      field="task.expected_output"
      :node-id="id"
      :model-value="config.task.expected_output"
      :max="bounds.max_prompt_chars"
      required
      :rows="3"
      help="What a finished answer looks like. CrewAI shows this to the agent, and a vague one is the commonest reason a task loops."
      @commit="patchTask({ expected_output: $event ?? '' }, 'Set expected output', coalesceKeyFor(id, 'task.expected_output'))"
    />

    <LlmFields
      region="essentials"
      path="llm"
      :value="config.llm"
      :node-id="id"
      :control-prefix="prefix"
      :tiers="vocabulary.tiers"
      :tier="config.tier"
      show-cost
      @patch="patchLlm"
      @preset="commitPreset"
    />

    <!--
      Attachments. A read-out, not a picker - see the docblock. The row still
      carries `data-field="attachments"` so an `attachment-unattached` or an
      `attachments-over-max` anchored here lands on it rather than on the strip.
    -->
    <FieldRow
      label="Attached"
      :control-id="control('attachments')"
      field="attachments"
      :node-id="id"
      group
      :note="`${attachments.length}`"
      help="Tools, MCP servers and skills reach this agent along attach edges. Add or remove one on the canvas - a dropdown here would hide the fact that two agents can share one."
    >
      <ul v-if="attachments.length" class="attach-list">
        <li v-for="entry in attachments" :key="entry.id">
          <span class="attach-icon" :style="{ color: NODE_KINDS[entry.kind].accent }" aria-hidden="true">
            <component :is="NODE_KINDS[entry.kind].icon" :size="12" :stroke-width="1.8" />
          </span>
          <span class="attach-label">{{ entry.label }}</span>
          <button
            type="button"
            class="attach-jump"
            :aria-label="`Show ${entry.label} on the canvas`"
            @click="emit('focusNode', entry.id)"
          >
            <ArrowUpRight :size="12" aria-hidden="true" />
          </button>
        </li>
      </ul>
      <p v-else class="empty-note">
        Nothing attached. This agent can reason and cannot look anything up.
      </p>
    </FieldRow>

    <!-- ================= ADVANCED ================= -->
    <TierRegion tier="advanced" kind="agent" :count="advancedCount" :force-open="advancedForced">
      <SchemaEditor
        label="Output schema"
        :control-id="control('task-output_schema')"
        field="task.output_schema"
        :node-id="id"
        :model-value="config.task.output_schema"
        help="Names and types the task promises to answer with. The compiler builds a pydantic class from this, which is what lets a downstream transform pick a field by name instead of parsing prose."
        @commit="patchTask({ output_schema: $event }, 'Set output schema')"
      />

      <SwitchRow
        label="Markdown"
        :control-id="control('task-markdown')"
        field="task.markdown"
        :node-id="id"
        :model-value="config.task.markdown"
        help="Asks for Markdown in the answer. Worth having off when an output schema is declared - the two ask for different things."
        @commit="patchTask({ markdown: $event }, 'Set markdown')"
      />

      <SwitchRow
        label="Async execution"
        :control-id="control('task-async_execution')"
        field="task.async_execution"
        :node-id="id"
        :model-value="config.task.async_execution"
        help="Lets CrewAI run this task without waiting for it. The graph's own fan-out already runs branches at once, so this is for the case inside one node."
        @commit="patchTask({ async_execution: $event }, 'Set async execution')"
      />

      <LlmFields
        region="advanced"
        path="llm"
        :value="config.llm"
        :node-id="id"
        :control-prefix="prefix"
        :tiers="vocabulary.tiers"
        :tier="config.tier"
        @patch="patchLlm"
        @preset="commitPreset"
      />

      <NumberRow
        label="Iterations"
        :control-id="control('max_iter')"
        field="max_iter"
        :node-id="id"
        :model-value="config.max_iter"
        :min="1"
        :max="bounds.max_agent_iter"
        :help="`How many reasoning passes one call may take, up to ${bounds.max_agent_iter}. It multiplies this node's modelled calls, so it is one of the two terms the budget meter actually moves on.`"
        @commit="commit({ max_iter: $event ?? 1 }, 'Set iteration ceiling')"
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
        help="A throttle on this agent's own calls. GitHub's 10 requests a minute per IP is the reason this exists on a tool-using node."
        @commit="commit({ max_rpm: $event }, 'Set requests per minute')"
      />

      <NumberRow
        label="Execution time"
        :control-id="control('max_execution_time')"
        field="max_execution_time"
        :node-id="id"
        :model-value="config.max_execution_time"
        :min="1"
        nullable
        placeholder="no limit"
        note="seconds"
        help="How long the whole node may take, across every iteration and retry."
        @commit="commit({ max_execution_time: $event }, 'Set execution time')"
      />

      <SwitchRow
        label="Allow delegation"
        :control-id="control('allow_delegation')"
        field="allow_delegation"
        :node-id="id"
        :model-value="config.allow_delegation"
        help="Lets this agent hand work to a crewmate. It does nothing outside a crew, and inside one it is what turns a list of agents into a team."
        @commit="commit({ allow_delegation: $event }, 'Set delegation')"
      />

      <SwitchRow
        label="Memory"
        :control-id="control('memory')"
        field="memory"
        :node-id="id"
        :model-value="config.memory"
        help="CrewAI's unified memory at 1.15.18 - one switch, not the three short/long/entity toggles older docs describe. Anything richer is a memory backend, which is not a thing drawn on a canvas."
        @commit="commit({ memory: $event }, 'Set memory')"
      />

      <SwitchRow
        label="Cache"
        :control-id="control('cache')"
        field="cache"
        :node-id="id"
        :model-value="config.cache"
        help="Reuses a tool result this agent has already fetched inside one run. On by default, and turning it off is how a node that must see live data says so."
        @commit="commit({ cache: $event }, 'Set cache')"
      />

      <SwitchRow
        label="Respect context window"
        :control-id="control('respect_context_window')"
        field="respect_context_window"
        :node-id="id"
        :model-value="config.respect_context_window"
        help="Summarises rather than overflowing. Off means a long conversation fails at the provider instead of degrading."
        @commit="commit({ respect_context_window: $event }, 'Set context handling')"
      />

      <NumberRow
        label="Guardrail retries"
        :control-id="control('guardrail_max_retries')"
        field="guardrail_max_retries"
        :node-id="id"
        :model-value="config.guardrail_max_retries"
        :min="0"
        :max="bounds.max_guardrail_retries"
        help="Counted PER GUARDRAIL by CrewAI, so this is where one node multiplies rather than adds. This is the field that means what CrewAI's max_retries used to; the node retry below is the builder's own and is a different thing."
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
        help="How many times the WHOLE node is re-run when its step raises. The builder's own loop, inside run_agent - not CrewAI's guardrail counter above."
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
        help="The pause between those attempts. A rate limit needs one; a malformed answer does not."
        @commit="patchRetry({ backoff_seconds: $event ?? 0 }, 'Set retry backoff')"
      />

      <FieldRow
        label="Fallback model"
        :control-id="control('retry-fallback_model')"
        field="retry.fallback_model"
        :node-id="id"
        group
        :note="config.retry.fallback_model ? undefined : 'none'"
        help="What the LAST attempt runs on. A REFUSAL is never retried with it: a refusal is a decision, and asking a second model until one agrees is not a retry."
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
        help="Routing grows a second source port named error on this card, so the recovery path is something you draw rather than something you lose the run to."
        @commit="commit({ on_error: ($event as 'fail' | 'route') }, 'Set error policy')"
      />

      <slot name="prompt-inputs" />
    </TierRegion>

    <!-- ================= EXPERT ================= -->
    <TierRegion tier="expert" kind="agent" :count="expertCount" :force-open="expertForced">
      <LlmFields
        region="expert"
        path="llm"
        :value="config.llm"
        :node-id="id"
        :control-prefix="prefix"
        :tiers="vocabulary.tiers"
        :tier="config.tier"
        @patch="patchLlm"
        @preset="commitPreset"
      />

      <SwitchRow
        label="Planning"
        :control-id="control('planning')"
        field="planning"
        :node-id="id"
        :model-value="config.planning"
        help="CrewAI's replacement for the deprecated reasoning switch: the agent drafts a plan before it acts. Turning it on seeds the four settings below; turning it off drops them, because a planning config under a switch that is off configures nothing and the schema refuses that shape."
        @commit="commitPlanning"
      />

      <template v-if="config.planning && config.planning_config">
        <SegmentedRow
          label="Planning effort"
          :control-id="control('planning_config-reasoning_effort')"
          field="planning_config.reasoning_effort"
          :node-id="id"
          :model-value="config.planning_config.reasoning_effort"
          :options="[
            { value: 'low', word: 'low' },
            { value: 'medium', word: 'medium' },
            { value: 'high', word: 'high' },
          ]"
          help="How hard the planner thinks. Distinct from the model's own reasoning effort above - this one CrewAI applies itself."
          @commit="patchPlanning({ reasoning_effort: $event as PlanningConfig['reasoning_effort'] }, 'Set planning effort')"
        />

        <NumberRow
          label="Planning attempts"
          :control-id="control('planning_config-max_attempts')"
          field="planning_config.max_attempts"
          :node-id="id"
          :model-value="config.planning_config.max_attempts"
          :min="1"
          :max="bounds.max_retries"
          nullable
          placeholder="CrewAI default"
          help="What `max_reasoning_attempts` became. The deprecated field folded into this one, with a warning, at 1.15.18."
          @commit="patchPlanning({ max_attempts: $event }, 'Set planning attempts')"
        />

        <NumberRow
          label="Planning steps"
          :control-id="control('planning_config-max_steps')"
          field="planning_config.max_steps"
          :node-id="id"
          :model-value="config.planning_config.max_steps"
          :min="1"
          :max="20"
          help="How long a plan may be. Every step is work the agent will try to do."
          @commit="patchPlanning({ max_steps: $event ?? 1 }, 'Set planning steps')"
        />

        <NumberRow
          label="Replans"
          :control-id="control('planning_config-max_replans')"
          field="planning_config.max_replans"
          :node-id="id"
          :model-value="config.planning_config.max_replans"
          :min="0"
          :max="bounds.max_retries"
          help="How many times it may throw the plan away and start again. Each one is a fresh planning pass at this node's own price."
          @commit="patchPlanning({ max_replans: $event ?? 0 }, 'Set replans')"
        />
      </template>

      <PromptField
        label="System template"
        :control-id="control('system_template')"
        field="system_template"
        :node-id="id"
        :model-value="config.system_template"
        :max="bounds.max_prompt_chars"
        :rows="3"
        placeholder="CrewAI's own"
        help="Replaces CrewAI's system prompt wholesale. Empty means use theirs, which is almost always the right answer."
        @commit="commit({ system_template: $event }, 'Set system template')"
      />

      <PromptField
        label="Prompt template"
        :control-id="control('prompt_template')"
        field="prompt_template"
        :node-id="id"
        :model-value="config.prompt_template"
        :max="bounds.max_prompt_chars"
        :rows="3"
        placeholder="CrewAI's own"
        @commit="commit({ prompt_template: $event }, 'Set prompt template')"
      />

      <PromptField
        label="Response template"
        :control-id="control('response_template')"
        field="response_template"
        :node-id="id"
        :model-value="config.response_template"
        :max="bounds.max_prompt_chars"
        :rows="3"
        placeholder="CrewAI's own"
        @commit="commit({ response_template: $event }, 'Set response template')"
      />

      <SegmentedRow
        label="Tool failure"
        :control-id="control('tool_failure_policy')"
        field="tool_failure_policy"
        :node-id="id"
        :model-value="config.tool_failure_policy"
        :options="[
          { value: null, word: 'default' },
          { value: 'ignore', word: 'ignore' },
          { value: 'warn', word: 'warn' },
          { value: 'raise', word: 'raise' },
        ]"
        help="What happens when an attached tool throws. CrewAI's own default is warn; raise is what turns a broken tool into a failed node you can route."
        @commit="commit({ tool_failure_policy: $event as ToolFailurePolicy | null }, 'Set tool failure policy')"
      />
    </TierRegion>
  </div>
</template>

<style scoped>
.inspector-form { display: block; }

.attach-list { display: grid; gap: 3px; margin: 0; padding: 0; list-style: none; }
.attach-list li { display: flex; align-items: center; gap: 7px; padding: 4px 5px; border-radius: var(--r-sm); }
.attach-list li:hover { background: var(--surface-raised); }
.attach-icon { display: grid; width: 20px; height: 20px; flex: 0 0 auto; place-items: center; background: color-mix(in srgb, currentColor 12%, transparent); border: 1px solid color-mix(in srgb, currentColor 30%, transparent); border-radius: var(--r-sm); }
.attach-label { min-width: 0; overflow: hidden; color: var(--text-body); font: 500 var(--fs-12)/1.3 var(--font-body); text-overflow: ellipsis; white-space: nowrap; }
.attach-jump { display: grid; width: 20px; height: 20px; flex: 0 0 auto; margin-left: auto; place-items: center; padding: 0; color: var(--text-40); background: transparent; border: 0; border-radius: var(--r-sm); cursor: pointer; }
.attach-jump:hover { color: var(--accent-cyan); }
.attach-jump:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

.empty-note { margin: 0; color: var(--text-40); font-size: var(--fs-11); line-height: 1.5; }
</style>
