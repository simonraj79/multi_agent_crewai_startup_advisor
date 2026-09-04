<script setup lang="ts">
import { computed, inject, onMounted } from 'vue'
import { loadModels, modelById, nitroMultiplier, roster } from '../../../data/models'
import { BUILDER_BUDGET } from '../../../composables/useBuilderValidation'
import type { LlmConfig, RegistryModel, Tier } from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import NumberRow from '../fields/NumberRow.vue'
import SegmentedRow from '../fields/SegmentedRow.vue'
import TokenListInput from '../fields/TokenListInput.vue'
import ModelPicker from './ModelPicker.vue'

/**
 * `LlmConfig`'s eleven leaves, the capability gate that decides which of them a
 * model can honour, and the one line that says what this node costs.
 *
 * ONE COMPONENT FOR THREE FIELDS. An authored agent carries `llm`; an authored
 * crew carries `manager_llm` and `planning_llm`, each an `LlmConfig` in its own
 * right. Three copies of eleven controls would be thirty-three chances for two
 * of them to disagree about a bound, and the crew's two would be the copies
 * nobody re-read. `path` is what makes one component serve all three: it is the
 * document path the problems anchor to (`llm.model`, `manager_llm.model`), and
 * `registry.py::_llm_fields` yields exactly these three names for exactly this
 * reason.
 *
 * D3 - DISABLED WITH A REASON, NEVER DROPPED. Two of the eleven are gated on
 * the chosen model: `response_format` on `supports_json_mode` and
 * `reasoning_effort` on `supports_reasoning`. A gated control renders
 * `disabled`, carries `aria-disabled`, shows a tooltip naming the model, and
 * **keeps its stored value on screen**. The value stays in the document too, so
 * `registry.py` reports `model-lacks-capability` against it and the author sees
 * exactly what stopped working when they switched model - they can clear it, or
 * switch back. Flowise accepts the parameter, sends it, and lets the provider
 * drop it in silence; the gauntlet names that as the win condition, and a
 * client-side-only gate is how you ship the same thing with better manners.
 *
 * THE THIRD CAPABILITY IS NOT GATED HERE. `supports_tools` is about the
 * ATTACHMENTS wired to the node, which are edges on the canvas rather than
 * controls in this form, so the server reports it and the picker's glyph row
 * shows it, and there is nothing here to disable.
 *
 * IT COMPUTES NO PRICE. The cost line reads the server's `per_node` breakdown
 * (C5, 04 D6). A second estimator here would be a number that quietly
 * disagrees with the one enforcing the ceiling - invariant 3, and the failure
 * that once reported a 128,069-token run at $0.00.
 */
const props = withDefaults(
  defineProps<{
    /**
     * WHICH TIER'S SLICE to render - D1's three regions.
     *
     * The eleven leaves do NOT all sit at one tier: `model` is Essentials, five
     * are Advanced, five are Expert. One component renders one slice at a time
     * so the tiering lives in `D2`'s table and not in three copies of it, and so
     * a crew's manager and planner get the same split without restating it.
     */
    region: 'essentials' | 'advanced' | 'expert'
    /** The document path this LLM sits at: `llm`, `manager_llm`, `planning_llm`. */
    path: string
    value: LlmConfig
    nodeId: string
    /** `insp-<id>-` - the prefix every control id in this sub-form carries. */
    controlPrefix: string
    /** Which tier chips to offer as presets, in the vocabulary's order. */
    tiers: readonly Tier[]
    /** The node's declared tier, so the preset chips can show which is pressed. */
    tier: Tier
    /**
     * Whether to render the per-node cost line. True for the node's OWN model
     * and false for a crew's manager and planner: the breakdown is per NODE, so
     * printing the same figure under three controls would say the manager costs
     * what the whole crew costs.
     */
    showCost?: boolean
  }>(),
  { showCost: false },
)

const emit = defineEmits<{
  /** One leaf changed. The parent folds it into the right composite. */
  patch: [patch: Partial<LlmConfig>, label: string]
  /** A tier chip was pressed: set the model AND the node's tier in one commit. */
  preset: [tier: Tier, model: string]
}>()

onMounted(() => {
  void loadModels()
})

const control = (name: string) => `${props.controlPrefix}${props.path}-${name}`
const field = (name: string) => `${props.path}.${name}`

/** The roster row this model names, or null - not loaded, failed, or unknown. */
const model = computed<RegistryModel | null>(() => modelById(props.value.model))

/**
 * Whether a named parameter may be offered at all.
 *
 * `true` when the roster has not loaded, deliberately. An unloaded roster is not
 * evidence that a model lacks a capability, and greying out half the form while
 * a request is in flight would read as a product that had decided something.
 */
function supports(capability: 'supports_json_mode' | 'supports_reasoning'): boolean {
  return model.value ? model.value[capability] === true : true
}

/** The tooltip on a gated control. It NAMES THE MODEL, per D3. */
function reason(capability: string): string {
  return model.value
    ? `${model.value.id} does not support ${capability}, so this would be sent and dropped.`
    : ''
}

const jsonOk = computed(() => supports('supports_json_mode'))
const reasoningOk = computed(() => supports('supports_reasoning'))

/* --- the tier presets --------------------------------------------------- */

/**
 * The two preset chips, pinned above the picker - D2's "tier preset" row.
 *
 * They SET `llm.model` rather than being a field of their own, which is exactly
 * why FD5 counts 34 leaves and not 35: `tier` is a control over another field.
 * It is still a stored field - `bounds.py` counts it against
 * `MAX_ESCALATION_NODES` on that word alone - so pressing a chip writes both,
 * in one commit, or the price the graph is admitted at and the model it runs on
 * would disagree.
 */
const presets = computed(() =>
  props.tiers.map((tier) => ({
    tier,
    /** The preset's spelling WITH its variant, which is where `:nitro` shows up. */
    spelling: roster.value?.presets[tier] ?? '',
  })),
)

/** True when the model is neither preset - D2's "shows custom when the model is neither". */
const custom = computed(() => {
  const rows = roster.value
  if (!rows) return false
  const chosen = modelById(props.value.model)
  if (!chosen) return false
  return !presets.value.some(
    (preset) => preset.spelling && modelById(preset.spelling)?.id === chosen.id,
  )
})

function pressPreset(tier: Tier, spelling: string): void {
  if (!spelling) return
  emit('preset', tier, spelling)
}

/* --- the per-node cost line, D6 ----------------------------------------- */

const budget = inject(BUILDER_BUDGET, null)

/**
 * `this node ≈ $0.12 of $1.51 (static)`, or nothing.
 *
 * NOTHING is the honest answer in three different states and they are not the
 * same: no validation has run, the run failed, or the server does not serve a
 * `per_node` breakdown yet - which is today's state, because C5 assigns that
 * key to plan 09. The line appears the moment the key does, and no arithmetic
 * here changes in between.
 *
 * It recomputes on the same 400 ms validation debounce as everything else, so
 * changing the model reprices within half a second without leaving the field.
 */
const cost = computed(() => {
  if (!props.showCost) return null
  const estimate = budget?.value
  const perNode = estimate?.per_node?.[props.nodeId]
  if (!estimate || !perNode) return null
  return {
    node: perNode.usd,
    calls: perNode.calls,
    total: estimate.static_cost_usd,
  }
})

/** Four decimals under a dime, because `$0.09` and `$0.0886` are different claims. */
function usd(value: number): string {
  return value < 0.1 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`
}

/** What a `:nitro` preset may bill above its headline. Rendered only when > 1. */
const inflation = computed(() => nitroMultiplier(props.value.model))
</script>

<template>
  <FieldRow
    v-if="region === 'essentials'"
    label="Model"
    :control-id="control('model')"
    :field="field('model')"
    :node-id="nodeId"
    group
    :note="custom ? 'custom' : undefined"
    help="What this node's calls run on. The two chips are the tiers the platform prices and counts; picking any other model is legal and makes the tier a declaration about spend rather than a name for a model."
  >
    <div class="preset-chips segmented">
      <button
        v-for="preset in presets"
        :key="preset.tier"
        type="button"
        :aria-pressed="!custom && tier === preset.tier"
        :disabled="!preset.spelling"
        @click="pressPreset(preset.tier, preset.spelling)"
      >
        <i v-if="preset.tier === 'escalation'" class="tier-dot" aria-hidden="true" />
        {{ preset.tier }}
      </button>
    </div>

    <ModelPicker
      mode="pick"
      :model-value="value.model"
      :control-id="control('model')"
      @update:model-value="emit('patch', { model: $event }, 'Choose model')"
    />

    <p v-if="cost" class="node-cost" data-testid="node-cost">
      this node ≈ <strong>{{ usd(cost.node) }}</strong> of {{ usd(cost.total) }} (static)
      <span class="node-cost-calls">· {{ cost.calls }} modelled calls</span>
    </p>
  </FieldRow>

  <template v-if="region === 'advanced'">
  <NumberRow
    label="Temperature"
    :control-id="control('temperature')"
    :field="field('temperature')"
    :node-id="nodeId"
    :model-value="value.temperature"
    :min="0"
    :max="2"
    :step="0.05"
    nullable
    slider
    placeholder="model default"
    help="Higher wanders further. Empty leaves it to the model, which is usually the better answer for a graph you want to be able to re-run."
    @commit="emit('patch', { temperature: $event }, 'Set temperature')"
  />

  <NumberRow
    label="Top-p"
    :control-id="control('top_p')"
    :field="field('top_p')"
    :node-id="nodeId"
    :model-value="value.top_p"
    :min="0"
    :max="1"
    :step="0.05"
    nullable
    slider
    placeholder="model default"
    help="Nucleus sampling. Setting this AND temperature is two knobs on one behaviour; most providers advise picking one."
    @commit="emit('patch', { top_p: $event }, 'Set top-p')"
  />

  <NumberRow
    label="Max tokens"
    :control-id="control('max_tokens')"
    :field="field('max_tokens')"
    :node-id="nodeId"
    :model-value="value.max_tokens"
    :min="1"
    nullable
    placeholder="model default"
    help="A ceiling on ONE completion. What the whole graph may cost is the run ceiling, and it is measured rather than declared."
    @commit="emit('patch', { max_tokens: $event }, 'Set max tokens')"
  />

  <NumberRow
    label="Timeout"
    :control-id="control('timeout')"
    :field="field('timeout')"
    :node-id="nodeId"
    :model-value="value.timeout"
    :min="1"
    nullable
    placeholder="no timeout"
    note="seconds"
    help="How long one call may take before it is abandoned. An abandoned call still billed for what it generated."
    @commit="emit('patch', { timeout: $event }, 'Set timeout')"
  />

  <SegmentedRow
    label="Response format"
    :control-id="control('response_format')"
    :field="field('response_format')"
    :node-id="nodeId"
    :model-value="value.response_format"
    :options="[
      { value: null, word: 'default' },
      { value: 'text', word: 'text' },
      { value: 'json_object', word: 'json' },
    ]"
    :disabled="!jsonOk"
    :reason="reason('JSON mode')"
    :note="jsonOk ? undefined : 'unsupported'"
    :note-warn="!jsonOk"
    :help="
      jsonOk
        ? 'Asking for JSON is not the same as declaring a shape - the task output schema above is what makes the answer parseable.'
        : reason('JSON mode')
    "
    @commit="emit('patch', { response_format: $event as LlmConfig['response_format'] }, 'Set response format')"
  />
  </template>

  <template v-if="region === 'expert'">

  <NumberRow
    label="Frequency penalty"
    :control-id="control('frequency_penalty')"
    :field="field('frequency_penalty')"
    :node-id="nodeId"
    :model-value="value.frequency_penalty"
    :min="-2"
    :max="2"
    :step="0.1"
    nullable
    slider
    placeholder="model default"
    @commit="emit('patch', { frequency_penalty: $event }, 'Set frequency penalty')"
  />

  <NumberRow
    label="Presence penalty"
    :control-id="control('presence_penalty')"
    :field="field('presence_penalty')"
    :node-id="nodeId"
    :model-value="value.presence_penalty"
    :min="-2"
    :max="2"
    :step="0.1"
    nullable
    slider
    placeholder="model default"
    @commit="emit('patch', { presence_penalty: $event }, 'Set presence penalty')"
  />

  <!--
    `pattern` is opened right up, and that is the point: every other chip list
    in this rail holds an IDENTIFIER, and a stop sequence is arbitrary text -
    `\n\n`, `Observation:`, a closing brace. The default pattern would refuse
    every useful one. `max` is 4 because `LlmConfig._validate_stop` refuses a
    fifth rather than truncating, which makes it a Tier-1 rule this widget is
    required to enforce at the keyboard rather than discover on save.
  -->
  <TokenListInput
    label="Stop sequences"
    :model-value="value.stop"
    :control-id="control('stop')"
    :field="field('stop')"
    :node-id="nodeId"
    subject="stop sequence"
    :pattern="/^.+$/"
    :max="4"
    max-message="Four stop sequences is the OpenAI-compatible ceiling; a fifth is refused rather than dropped."
    duplicate-message="This model already stops on that sequence."
    placeholder="Type a sequence and press Enter"
    help="Where a completion is cut off. Four at most, and the schema refuses a fifth rather than silently keeping the first four."
    @commit="emit('patch', { stop: $event }, 'Set stop sequences')"
  />

  <NumberRow
    label="Seed"
    :control-id="control('seed')"
    :field="field('seed')"
    :node-id="nodeId"
    :model-value="value.seed"
    :min="0"
    nullable
    placeholder="none"
    help="Best-effort reproducibility, and best-effort is the operative word: providers honour it when they can and never promise to."
    @commit="emit('patch', { seed: $event }, 'Set seed')"
  />

  <SegmentedRow
    label="Reasoning effort"
    :control-id="control('reasoning_effort')"
    :field="field('reasoning_effort')"
    :node-id="nodeId"
    :model-value="value.reasoning_effort"
    :options="[
      { value: null, word: 'none' },
      { value: 'low', word: 'low' },
      { value: 'medium', word: 'medium' },
      { value: 'high', word: 'high' },
    ]"
    :disabled="!reasoningOk"
    :reason="reason('reasoning')"
    :note="reasoningOk ? undefined : 'unsupported'"
    :note-warn="!reasoningOk"
    :help="
      reasoningOk
        ? 'CrewAI drops this for every OpenRouter model today (config.py notes it beside the constant), so it is stored and currently inert. It is kept because the drop is CrewAI behaviour rather than a property of the field, and a document that lost it on a save would lose it for good.'
        : reason('reasoning')
    "
    @commit="emit('patch', { reasoning_effort: $event as LlmConfig['reasoning_effort'] }, 'Set reasoning effort')"
  />
  </template>

  <p v-if="region === 'essentials' && model && inflation > 1" class="nitro-note">
    Routed for speed, so this bills up to {{ inflation.toFixed(1) }}× its headline on its dearest
    endpoint. The budget meter enforces the inflated figure.
  </p>
</template>

<style scoped>
.preset-chips { margin-bottom: 9px; }
.tier-dot { width: 6px; height: 6px; background: var(--warn-text); border-radius: var(--r-full); }

.node-cost { margin: 9px 0 0; color: var(--text-muted); font-size: var(--fs-11); line-height: 1.5; }
.node-cost strong { color: var(--text-title); font-family: var(--font-mono); }
.node-cost-calls { color: var(--text-40); }

.nitro-note { margin: 9px 0 0; color: var(--warn-text); font-size: var(--fs-11); line-height: 1.5; }
</style>
