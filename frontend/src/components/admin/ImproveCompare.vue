<script setup lang="ts">
/**
 * **Did the change help?** - two arms, six measures, on the same workflow.
 *
 * `.agent/plans/21-test-a-change.md` R4 and criterion T6. Two axes and no more,
 * because these are the only two the data supports: `version` (the workflow you
 * drew, before and after an edit) and `model` scoped to ONE node - the
 * counterfactual the whole exercise is for, *"what if a cheaper model ran this
 * step"*.
 *
 * THE NODE IS REQUIRED ON THE MODEL AXIS, and this panel enforces it rather
 * than discovering it: the server answers 422 without one, the arms are only
 * disjoint once a node is named, and the cost per run then means that node's
 * cost rather than the whole run's. Nothing is fetched until a node is chosen,
 * so the refusal never has to happen.
 *
 * `n` IS PRINTED ON EVERY ARM, AND `underpowered` IS LOUD - twice. An arm under
 * the server's floor is flagged in the arm's own header, because everything in
 * that column is read through it, AND once above the table, because a caveat
 * only under the numbers is a caveat somebody has already acted on.
 *
 * NOTHING IS SUBTRACTED FOR YOU. There is no "+12% better" anywhere here: the
 * two arms are printed side by side and the reader does the arithmetic. A delta
 * implies a significance nobody has established, and this data cannot establish
 * it.
 *
 * `unknown` IS ITS OWN ARM. A run whose workflow has no saved versions - every
 * built-in one - is grouped `unknown` and never merged into an arm it might not
 * belong to. The panel says so in a sentence and points at the other axis.
 */
import { computed } from 'vue'
import { TriangleAlert } from 'lucide-vue-next'
import MoneyFigure from './MoneyFigure.vue'
import { count, durationMs, humanise } from './adminFormat'
import type {
  ImproveCompare,
  ImproveCompareAxis,
  ImproveNodeModels,
} from '../../services/adminApi'

const props = withDefaults(
  defineProps<{
    compare: ImproveCompare | null
    axis: ImproveCompareAxis
    a: string
    b: string
    /** Which step the model axis is about. `''` until one is chosen. */
    nodeId: string
    /** Every step, with the models it has run on. The model axis's one source. */
    nodeModels: ImproveNodeModels[]
    loading?: boolean
    problem?: string
  }>(),
  { loading: false, problem: '' },
)

const emit = defineEmits<{
  selectAxis: [axis: ImproveCompareAxis]
  updateA: [value: string]
  updateB: [value: string]
  selectNode: [nodeId: string]
  run: []
}>()

const AXES: ReadonlyArray<{
  id: ImproveCompareAxis
  label: string
  question: string
  /** The limit, in body copy under the control - never in the label itself. */
  note?: string
}> = [
  {
    id: 'version',
    label: 'Version',
    question: 'Two saved versions of the workflow you drew, on the same measures.',
  },
  {
    id: 'model',
    label: 'Model',
    question: 'Two models on one step, on the same measures.',
    note: 'A model is chosen step by step, so one step at a time is as far as these runs go.',
  },
]

const arms = computed(() => props.compare?.arms ?? [])

/** The six measures, in one table so the arms line up by row. */
const MEASURES: ReadonlyArray<{ key: string; label: string; note?: string }> = [
  { key: 'status_mix', label: 'How they ended' },
  { key: 'verdict_mix', label: 'What they answered' },
  { key: 'rating_mix', label: 'What people said' },
  { key: 'gate_revise_rate', label: 'Approvals sent back' },
  { key: 'median_duration_ms', label: 'Median time' },
  { key: 'cost_per_run_usd', label: 'Cost per run', note: 'estimate' },
]

function mixOf(bag: Record<string, number> | undefined): string {
  const entries = Object.entries(bag ?? {}).filter(([, value]) => Number(value) > 0)
  if (entries.length === 0) return '—'
  return entries.map(([key, value]) => `${humanise(key)} ${count(value)}`).join(' · ')
}

function rate(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${Math.round(value * 100)}%`
}

/**
 * The axis's own sentence, joined HERE rather than in the template.
 *
 * FOUND BY LOOKING: two interpolations with a space between them inside a
 * `<template v-if>` render as `…same measures.A model is chosen…`, because
 * Vue's default whitespace handling condenses the text node that held the
 * space away. Joining the two strings in script is the fix that cannot come
 * undone the next time somebody reformats the template.
 */
const axisSentence = computed(() => {
  const entry = AXES.find((option) => option.id === props.axis)
  if (!entry) return ''
  return entry.note ? `${entry.question} ${entry.note}` : entry.question
})

/**
 * The steps that can be compared at all: those that ran on two models or more.
 *
 * A step with one model has no second arm, so offering it would be offering a
 * question whose answer is always "these are the same runs twice".
 */
const comparableNodes = computed(() =>
  (props.nodeModels ?? []).filter((node) => (node.models ?? []).length >= 2),
)

/** The chosen step's models, which is the only list either box may offer. */
const modelsForNode = computed(
  () => comparableNodes.value.find((node) => node.node_id === props.nodeId)?.models ?? [],
)

/** The model axis needs a step; the version axis does not. R4, on the client. */
const needsNode = computed(() => props.axis === 'model')
const hasNode = computed(() => props.nodeId.trim() !== '')

/**
 * The two arm keys that are not a version and not a model.
 *
 * `mixed` is a run whose chosen step used more than one model, so it belongs to
 * neither arm; `unknown` is a run whose version could not be worked out. Both
 * are their OWN arm rather than being folded into a neighbour they might not
 * belong to, and both get a sentence: a column headed `mixed` with five
 * measures under it is a number nobody can read.
 */
const ARM_SENTENCES: Readonly<Record<string, string>> = {
  mixed: 'Runs where this step used more than one model',
  unknown: 'Runs whose version could not be worked out',
}

/**
 * One arm's sentence: why this column is not simply a number.
 *
 * `missing` wins over the two keys above, and reads differently per axis
 * because the two axes are asking different questions. A missing arm is SHOWN
 * with `n = 0` rather than dropped: a two-column table that quietly becomes
 * one column invites the reader to conclude the other side lost, and "nobody
 * ran this" is a different answer from "this did worse".
 */
function armSentence(arm: { key: string; missing?: boolean }): string {
  if (arm.missing) {
    return props.axis === 'model'
      ? 'No runs on this model at this step in the window'
      : 'No runs of this version in the window'
  }
  return ARM_SENTENCES[arm.key] ?? ''
}

const ready = computed(() => {
  if (props.a.trim() === '' || props.b.trim() === '') return false
  return !needsNode.value || hasNode.value
})

/**
 * Why the button is off, in the order a person hits the reasons.
 *
 * FOUND BY LOOKING, against a real backend whose every step runs one model:
 * the "nothing to compare" case has its OWN line below, with the remedy on it,
 * and this computed said the same thing one line above it. Two sentences
 * saying one thing is a screen arguing with itself, so this one stays silent
 * where the other speaks.
 */
const blockedBecause = computed(() => {
  if (needsNode.value && comparableNodes.value.length === 0) return ''
  if (needsNode.value && !hasNode.value) return 'Choose a step first. Two models are only comparable on one step.'
  if (!ready.value) return 'Choose both sides to compare.'
  return ''
})

const underpowered = computed(() => arms.value.filter((arm) => arm.underpowered))

/**
 * A workflow with no saved versions, asked about on the version axis.
 *
 * One arm, keyed `unknown`, is the server saying "every run here belongs to a
 * workflow that has no version history" - which is true of every built-in
 * workflow. Printing that arm alone with no sentence would read as a comparison
 * that came back half empty.
 */
const noVersions = computed(
  () => props.axis === 'version' && arms.value.length === 1 && arms.value[0]?.key === 'unknown',
)
</script>

<template>
  <div class="improve-compare" data-testid="improve-compare">
    <p class="improve-lede">
      Did the change help? Pick what to compare, choose both sides, and read the six measures side
      by side. Nothing is worked out for you: the two columns are printed as they are.
    </p>

    <div class="improve-controls">
      <div class="admin-window" role="group" aria-label="What to compare">
        <button
          v-for="entry in AXES"
          :key="entry.id"
          type="button"
          class="admin-axis-button improve-axis"
          :class="{ 'is-active': axis === entry.id }"
          :aria-pressed="axis === entry.id"
          :data-testid="`improve-axis-${entry.id}`"
          @click="emit('selectAxis', entry.id)"
        >
          {{ entry.label }}
        </button>
      </div>

      <!--
        THE STEP COMES FIRST, and it is first in the DOM as well as in the
        sentence: on the model axis nothing else on this row means anything
        until it is answered.
      -->
      <label v-if="needsNode" class="improve-field">
        <span>Step</span>
        <select
          class="improve-select"
          :value="nodeId"
          :disabled="comparableNodes.length === 0"
          data-testid="improve-compare-node"
          @change="emit('selectNode', ($event.target as HTMLSelectElement).value)"
        >
          <option value="">Choose a step…</option>
          <option v-for="node in comparableNodes" :key="node.node_id" :value="node.node_id">
            {{ node.label || node.node_id }} · {{ node.models.length }} models
          </option>
        </select>
      </label>

      <label class="improve-field">
        <span>{{ needsNode ? 'Model A' : 'Version A' }}</span>
        <select
          v-if="needsNode"
          class="improve-select"
          :value="a"
          :disabled="!hasNode"
          data-testid="improve-compare-a"
          @change="emit('updateA', ($event.target as HTMLSelectElement).value)"
        >
          <option value="">Choose a model…</option>
          <!-- ONLY THE CHOSEN STEP'S MODELS. A box offering a model that step
               never ran would be offering an arm that cannot exist. -->
          <option v-for="model in modelsForNode" :key="model" :value="model">{{ model }}</option>
        </select>
        <input
          v-else
          class="improve-input"
          type="text"
          inputmode="numeric"
          :value="a"
          placeholder="e.g. 1"
          data-testid="improve-compare-a"
          @input="emit('updateA', ($event.target as HTMLInputElement).value)"
        />
      </label>

      <label class="improve-field">
        <span>{{ needsNode ? 'Model B' : 'Version B' }}</span>
        <select
          v-if="needsNode"
          class="improve-select"
          :value="b"
          :disabled="!hasNode"
          data-testid="improve-compare-b"
          @change="emit('updateB', ($event.target as HTMLSelectElement).value)"
        >
          <option value="">Choose a model…</option>
          <option v-for="model in modelsForNode" :key="model" :value="model">{{ model }}</option>
        </select>
        <input
          v-else
          class="improve-input"
          type="text"
          inputmode="numeric"
          :value="b"
          placeholder="e.g. 2"
          data-testid="improve-compare-b"
          @input="emit('updateB', ($event.target as HTMLInputElement).value)"
        />
      </label>

      <button
        type="button"
        class="improve-button"
        :disabled="!ready || loading"
        data-testid="improve-compare-run"
        @click="emit('run')"
      >
        {{ loading ? 'Comparing…' : 'Compare' }}
      </button>
    </div>

    <p class="improve-note">{{ axisSentence }}</p>
    <p v-if="blockedBecause" class="improve-note" data-testid="improve-compare-blocked">
      {{ blockedBecause }}
    </p>
    <p
      v-if="needsNode && comparableNodes.length === 0"
      class="improve-note"
      data-testid="improve-compare-no-nodes"
    >
      No step of this workflow has run on more than one model in this window, so there is nothing to
      pick from yet. Run the same step on a second model and this fills in.
    </p>

    <p v-if="problem" class="admin-problem" role="alert" data-testid="improve-compare-problem">
      <TriangleAlert :size="14" aria-hidden="true" />{{ problem }}
    </p>

    <!--
      THE FLAG, ABOVE THE TABLE. It is a `role="status"` sentence rather than a
      styled box alone, because a reader who never scrolls past the numbers has
      to have been told before they read them.
    -->
    <p
      v-if="underpowered.length"
      class="admin-warning"
      role="status"
      data-testid="improve-compare-thin"
    >
      <TriangleAlert :size="13" aria-hidden="true" />
      {{ underpowered.length === 1 ? 'One side has' : `${underpowered.length} sides have` }} too few
      runs to tell<template v-if="compare?.min_runs"> (needs {{ compare.min_runs }})</template>. A
      difference over a handful of runs is noise wearing a number. Run both sides more times before
      acting on this.
    </p>

    <p v-if="noVersions" class="admin-warning" role="status" data-testid="improve-compare-no-versions">
      <TriangleAlert :size="13" aria-hidden="true" />
      This workflow is built in, so it has no saved versions to compare. Switch to Model and compare
      two models on one step instead.
    </p>

    <div v-if="arms.length" class="admin-table-wrap">
      <table class="admin-table" data-testid="improve-compare-table">
        <caption class="sr-only">Two sides of one workflow on six measures.</caption>
        <thead>
          <tr>
            <th scope="col">Measure</th>
            <th v-for="arm in arms" :key="arm.key" scope="col">
              {{ arm.key }}
              <!-- `mixed` and `unknown` are not a version and not a model, and
                   a column headed with one of them over five measures is a
                   number nobody can read. Each gets its own sentence. -->
              <span
                v-if="armSentence(arm)"
                class="admin-sub"
                :data-testid="`improve-arm-note-${arm.key}`"
              >{{ armSentence(arm) }}</span>
              <span class="admin-sub">
                n = {{ count(arm.n) }}
                <template v-if="arm.underpowered">
                  · too few runs to tell<template v-if="compare?.min_runs">
                    (needs {{ compare.min_runs }})</template
                  >
                </template>
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="measure in MEASURES" :key="measure.key">
            <th scope="row">
              {{ measure.label }}
              <span v-if="measure.note" class="admin-sub">{{ measure.note }}</span>
            </th>
            <td v-for="arm in arms" :key="`${arm.key}:${measure.key}`">
              <template v-if="measure.key === 'status_mix'">{{ mixOf(arm.status_mix) }}</template>
              <template v-else-if="measure.key === 'verdict_mix'">
                {{ mixOf(arm.verdict_mix) }}
                <span
                  v-if="arm.mean_confidence !== null && arm.mean_confidence !== undefined"
                  class="admin-sub"
                >mean confidence {{ rate(arm.mean_confidence) }}</span>
              </template>
              <template v-else-if="measure.key === 'rating_mix'">{{ mixOf(arm.rating_mix) }}</template>
              <template v-else-if="measure.key === 'gate_revise_rate'">
                {{ rate(arm.gate_revise_rate) }}
              </template>
              <template v-else-if="measure.key === 'median_duration_ms'">
                {{ durationMs(arm.median_duration_ms) }}
              </template>
              <template v-else>
                <MoneyFigure :value="arm.cost_per_run_usd ?? null" :tag="false" />
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-else-if="!loading && !problem" class="admin-empty" data-testid="improve-compare-empty">
      Choose both sides and press Compare. Nothing is fetched until you do.
    </p>
  </div>
</template>

<style scoped>
.improve-compare { display: grid; gap: var(--space-3); }
.improve-lede,
.improve-note { margin: 0; color: var(--text-meta); font: var(--type-meta); line-height: 1.55; }
.improve-note { color: var(--text-40); }

.improve-controls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: flex-end;
}

.improve-field { display: grid; gap: var(--space-1); }
.improve-field > span {
  color: var(--text-meta);
  font: var(--type-kicker);
  letter-spacing: var(--track-kicker);
  text-transform: uppercase;
}

/* 44px on every control in this row, so the axis buttons, the two pickers and
   the press are one band rather than four heights. */
.improve-axis { min-height: 44px; }

.improve-input,
.improve-select {
  min-width: 180px;
  min-height: 44px;
  padding: var(--space-2) var(--space-3);
  color: var(--text-body);
  font: var(--type-meta);
  background: var(--surface-raised);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
}

.improve-input { font-family: var(--font-mono); }
.improve-select { max-width: 320px; }

.improve-input:focus-visible,
.improve-select:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

.improve-button {
  min-height: 44px;
  padding: var(--space-2) var(--space-4);
  color: var(--text-title);
  font: var(--type-label);
  background: var(--surface-well);
  border: 1px solid var(--border-control);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.improve-button:hover:not(:disabled) { border-color: var(--border-hover-strong); }
.improve-button:disabled { opacity: 0.45; cursor: default; }
.improve-button:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
</style>
