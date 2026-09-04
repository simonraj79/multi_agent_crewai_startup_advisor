<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { Brain, Braces, Eye, Gauge, Wrench } from 'lucide-vue-next'
import {
  loadModels,
  modelById,
  modelForTier,
  nitroMultiplier,
  roster,
  rosterProblem,
} from '../../../data/models'
import type { RegistryModel } from '../../../types/builder'

/**
 * Which model a billable node runs on, and what that costs - plan 05 D7 and D8.
 *
 * TWO MODES, and the second is the one that exists today.
 *
 * `mode="pick"` is the picker proper: an author chooses a roster model for an
 * AUTHORED agent's `llm.model`, and every unsupported parameter is shown
 * disabled with a tooltip naming the model rather than dropped. That is D7, and
 * it is enforced twice - `builder/registry.py` reports
 * `model-lacks-capability` for a document that carries the value anyway, so a
 * stale client cannot smuggle a parameter past the compiler. A parameter
 * rendered, accepted, sent and silently dropped is what the gauntlet names as
 * the single most infuriating competitor behaviour, and a client-side-only gate
 * is precisely how you ship one.
 *
 * `mode="preset"` is what a LIBRARY node gets, and it is read-only because
 * there is nothing to write: a library agent names one of `config.py`'s YAML
 * agents, whose LLMs are built inside the crew from the tier constants. The
 * document's `tier` word is the whole of what it says. So the row answers the
 * question an author actually has at that point - "what does `escalation`
 * mean, and what does it cost" - which until now had no answer anywhere in the
 * console.
 *
 * WHY BOTH PRICE COLUMNS ARE RENDERED. `cost_in` is the headline and what a run
 * is priced at. `cost_in_max_endpoint` is the dearest endpoint serving the same
 * slug, and for the cheap preset it is the difference between $0.30 and $0.54:
 * `:nitro` routes on SPEED, not price, so the published rate is a floor. A row
 * that showed only the headline would leave an author unable to explain why the
 * budget meter reads higher than the arithmetic they just did.
 *
 * IT COMPUTES NO BUDGET. The meter renders the SERVER's figure; a second
 * estimator here would be a number that quietly disagrees with the one
 * enforcing the ceiling (§1.1 invariant 3).
 */
const props = withDefaults(
  defineProps<{
    /** `pick` for an authored node's own model; `preset` for a library node's tier. */
    mode?: 'pick' | 'preset'
    /** The selected model id, in any spelling. Ignored in `preset` mode. */
    modelValue?: string | null
    /** The tier whose preset to describe. Ignored in `pick` mode. */
    tier?: string
    /** The `<select>`'s id, so a `<label for>` resolves to a real element. */
    controlId?: string
    describedBy?: string
    invalid?: boolean
  }>(),
  { mode: 'preset', modelValue: null, tier: 'cheap', controlId: 'model-picker' },
)

const emit = defineEmits<{ 'update:modelValue': [id: string] }>()

// Fired on mount rather than by a parent, so a picker works wherever it is
// dropped and N of them mounting at once still make one request.
onMounted(() => {
  void loadModels()
})

const models = computed<RegistryModel[]>(() => roster.value?.models ?? [])

/**
 * The row this control describes: the selected model, or the tier's preset.
 *
 * `null` covers three states that look the same to the template and are not the
 * same to the author - the roster has not loaded, the roster failed to load,
 * and the document names a model no roster row carries. The third is the
 * interesting one and the template says so, because that document is exactly
 * what the server answers `model-unknown` for.
 */
const selected = computed<RegistryModel | null>(() =>
  props.mode === 'pick' ? modelById(props.modelValue ?? '') : modelForTier(props.tier),
)

/** The preset's spelling WITH its variant, which is where `:nitro` shows up. */
const presetSpelling = computed(() =>
  props.mode === 'preset' ? (roster.value?.presets[props.tier] ?? '') : (props.modelValue ?? ''),
)

/**
 * What this model may bill above its headline, or 1 when nothing routes it.
 *
 * Rendered only when it is not 1, because "x1.0" is noise on eight of the ten
 * roster rows and the whole point of the line is that it is surprising on the
 * two it applies to.
 */
const inflation = computed(() => nitroMultiplier(presetSpelling.value))

const enforcedIn = computed(() =>
  selected.value ? selected.value.cost_in * inflation.value : 0,
)

/** A model id names something no roster row carries - the `model-unknown` shape. */
const unknown = computed(
  () => props.mode === 'pick' && !!props.modelValue && models.value.length > 0 && !selected.value,
)

/**
 * D7's table, as data. `title` becomes the tooltip on a disabled control.
 *
 * `supports_vision` is here and gates NOTHING, deliberately: `multimodal` is CUT
 * from `AuthoredAgentConfig` (deprecated at CrewAI 1.15.18, removed at 2.0), so
 * there is no field for a document to carry. It is still shown, because an
 * author choosing between two models wants to know which one can read an image
 * even when nothing here can ask it to yet.
 */
const CAPABILITIES = [
  { key: 'supports_tools', icon: Wrench, label: 'Tools', gates: 'attached tools' },
  { key: 'supports_json_mode', icon: Braces, label: 'JSON mode', gates: 'response_format' },
  { key: 'supports_reasoning', icon: Brain, label: 'Reasoning', gates: 'reasoning_effort' },
  { key: 'supports_vision', icon: Eye, label: 'Vision', gates: '' },
] as const

const capabilities = computed(() =>
  CAPABILITIES.map((entry) => {
    const supported = selected.value ? selected.value[entry.key] === true : false
    return {
      ...entry,
      supported,
      title: selected.value
        ? supported
          ? `${selected.value.id} supports ${entry.label.toLowerCase()}.`
          : entry.gates
            ? `${selected.value.id} does not support ${entry.label.toLowerCase()}, so ${entry.gates} is disabled.`
            : `${selected.value.id} does not support ${entry.label.toLowerCase()}.`
        : entry.label,
    }
  }),
)

/**
 * Whether a named parameter may be offered at all on the selected model.
 *
 * Exported so the surrounding form can disable ITS controls from one answer
 * rather than each of them re-deriving the rule - which is how two controls end
 * up disagreeing about one model.
 */
function supports(parameter: 'response_format' | 'reasoning_effort' | 'tools'): boolean {
  const model = selected.value
  if (!model) return true
  if (parameter === 'response_format') return model.supports_json_mode
  if (parameter === 'reasoning_effort') return model.supports_reasoning
  return model.supports_tools
}

defineExpose({ supports })

/** `1,048,576` reads as a number; `1.0M` reads as a context window. */
function context(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`
  if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K`
  return String(tokens)
}

/** Four decimals, because `deepseek-v4-flash` is $0.088606 and two would read $0.09. */
function usd(value: number): string {
  return value < 0.1 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`
}

function onSelect(event: Event): void {
  emit('update:modelValue', (event.target as HTMLSelectElement).value)
}
</script>

<template>
  <div class="model-picker" :data-mode="mode">
    <p v-if="rosterProblem" class="picker-problem" role="alert">{{ rosterProblem }}</p>

    <select
      v-else-if="mode === 'pick'"
      :id="controlId"
      class="model-select"
      :value="modelValue ?? ''"
      :aria-describedby="describedBy"
      :aria-invalid="invalid || unknown"
      @change="onSelect"
    >
      <!-- A model the document names and the roster does not is SHOWN, marked.
           Dropping it would silently rewrite the author's document to the first
           legal option the moment they touched anything else; showing it leaves
           the document alone and lets the server's own `model-unknown` say
           why. -->
      <option v-if="unknown" :value="modelValue">{{ modelValue }} — not in this build</option>
      <option v-for="model in models" :key="model.id" :value="model.id">
        {{ model.name }} — {{ usd(model.cost_in) }}/{{ usd(model.cost_out) }} per M
      </option>
    </select>

    <p v-else-if="selected" class="preset-name">
      <span class="preset-slug">{{ presetSpelling }}</span>
      <span class="preset-human">{{ selected.name }}</span>
    </p>

    <dl v-if="selected" class="model-facts">
      <div>
        <dt>Input</dt>
        <dd>{{ usd(selected.cost_in) }}<span class="unit">/M</span></dd>
      </div>
      <div>
        <dt>Output</dt>
        <!-- The larger half of every estimate: the budget model prices 4,253
             completion tokens per call, so hiding this would make the meter
             look arbitrary. -->
        <dd>{{ usd(selected.cost_out) }}<span class="unit">/M</span></dd>
      </div>
      <div>
        <dt>Context</dt>
        <dd>{{ context(selected.context_window) }}</dd>
      </div>
      <div>
        <dt>Speed</dt>
        <dd class="speed"><Gauge :size="11" aria-hidden="true" />{{ selected.speed_tier }}</dd>
      </div>
    </dl>

    <p v-if="selected && inflation > 1" class="dearest">
      Routed for speed, so this bills up to
      <strong>{{ usd(selected.cost_in_max_endpoint) }}/M</strong> on its dearest endpoint —
      {{ inflation.toFixed(1) }}× the headline. The budget meter enforces
      {{ usd(enforcedIn) }}/M.
    </p>
    <p v-else-if="selected && selected.cost_in_max_endpoint > selected.cost_in" class="dearest">
      Dearest endpoint {{ usd(selected.cost_in_max_endpoint) }}/M, filtered out before routing
      by the ${{ roster?.ceiling_usd_per_m_input.toFixed(2) }}/M ceiling.
    </p>

    <ul v-if="selected" class="capabilities">
      <li
        v-for="entry in capabilities"
        :key="entry.key"
        :class="{ off: !entry.supported }"
        :aria-disabled="!entry.supported"
        :title="entry.title"
      >
        <component :is="entry.icon" :size="11" aria-hidden="true" />
        <span>{{ entry.label }}</span>
      </li>
    </ul>

    <p v-if="selected && selected.recommended_for.length" class="roles">
      <span v-for="role in selected.recommended_for" :key="role">{{ role }}</span>
    </p>
  </div>
</template>

<style scoped>
.model-picker { display: grid; gap: 8px; }
.picker-problem { margin: 0; color: var(--err-text); font-size: var(--fs-11); line-height: 1.5; }

.model-select { width: 100%; }

.preset-name { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; margin: 0; }
.preset-slug { color: var(--accent-cyan); font: 600 var(--fs-12)/1.3 var(--font-mono); }
.preset-human { color: var(--text-muted); font-size: var(--fs-11); }

.model-facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; margin: 0; padding: 7px 8px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.model-facts div { min-width: 0; }
.model-facts dt { color: var(--text-40); font: 600 var(--fs-10)/1 var(--font-body); letter-spacing: 0.04em; text-transform: uppercase; }
.model-facts dd { margin: 3px 0 0; color: var(--text-title); font: 600 var(--fs-12)/1.2 var(--font-mono); white-space: nowrap; }
.model-facts .unit { color: var(--text-40); font-weight: 500; }
.speed { display: inline-flex; align-items: center; gap: 3px; }

.dearest { margin: 0; color: var(--warn-text); font-size: var(--fs-11); line-height: 1.5; }
.dearest strong { font-family: var(--font-mono); }

.capabilities { display: flex; flex-wrap: wrap; gap: 4px; margin: 0; padding: 0; list-style: none; }
.capabilities li { display: inline-flex; align-items: center; gap: 4px; padding: 2px 6px; color: var(--text-body); font: 600 var(--fs-10)/1.4 var(--font-body); background: var(--surface-raised); border: 1px solid var(--border-default); border-radius: var(--r-full); }
/* Struck through as well as dimmed: colour alone is not a signal, and this row
   is the difference between a parameter that works and one that is ignored. */
.capabilities li.off { color: var(--text-40); text-decoration: line-through; background: transparent; }

.roles { display: flex; flex-wrap: wrap; gap: 4px; margin: 0; }
.roles span { padding: 1px 5px; color: var(--text-muted); font: 500 var(--fs-10)/1.5 var(--font-mono); background: var(--surface-raised); border-radius: var(--r-sm); }
</style>
