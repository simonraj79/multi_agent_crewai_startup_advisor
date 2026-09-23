<script setup lang="ts">
/**
 * **Test a change** - the fourth step of the loop, as one docked panel.
 *
 * `.agent/plans/21-test-a-change.md`, R7. Four sections in the order somebody
 * actually works in, and the order is the argument: you cannot compare before
 * you know where it hurts, keep runs before you have compared, or usefully ask
 * a model to read anything before all three.
 *
 * | # | Section | The question |
 * | 1 | Where runs go wrong | Which step fails, costs or comes back empty? |
 * | 2 | Compare two versions | Did the change help, on the same measures? |
 * | 3 | Export rated runs | Keep the runs worth checking a future change against |
 * | 4 | Ask a model to review | One written review, on one press, for a price |
 *
 * EVERY HEADING IS A PLAIN QUESTION OR A PLAIN INSTRUCTION. Nothing on this
 * screen is named after its implementation, because the reader is the person
 * who DREW the workflow and has never opened `improve_api.py`. A section headed
 * with an engineering noun and a table under it teaches nobody anything.
 *
 * DOCKED, NEVER MODAL (R15). Four sections stacked in the panel's own scroller,
 * every one of them readable beside the numbers above it.
 *
 * IT OWNS NO REQUEST. `AdminView` fetches, for the reason that file states at
 * length: one window decides every aggregate on the screen, and a panel that
 * fetched its own would eventually be asked over a different fortnight from the
 * panel beside it. It also makes this whole surface mountable from a fixture
 * with no network at all, which is what `adminImprove.spec.ts` does.
 */
import { computed } from 'vue'
import { Download, TriangleAlert } from 'lucide-vue-next'
import EstimateBand from './EstimateBand.vue'
import ImproveCompare from './ImproveCompare.vue'
import ImproveDigest from './ImproveDigest.vue'
import ImproveHotspots from './ImproveHotspots.vue'
import { count } from './adminFormat'
import type {
  EvalsetRating,
  ImproveCompare as ImproveCompareShape,
  ImproveCompareAxis,
  ImproveDigestPage,
  ImproveHotspots as ImproveHotspotsShape,
} from '../../services/adminApi'

export interface ImproveWorkflowOption {
  id: string
  label: string
  runs?: number | null
}

const props = withDefaults(
  defineProps<{
    workflows: ImproveWorkflowOption[]
    workflowId: string
    hotspots: ImproveHotspotsShape | null
    /**
     * The version "Where runs go wrong" is scoped to, as typed; blank is all.
     * A plain number box, like Compare's version fields, because no read this
     * page makes lists a workflow's versions.
     */
    hotspotsVersion?: string
    compare: ImproveCompareShape | null
    digests: ImproveDigestPage | null
    compareAxis: ImproveCompareAxis
    compareA: string
    compareB: string
    compareNodeId: string
    evalsetRating: EvalsetRating
    /** Which window the console is on, so the export says what it will carry. */
    windowLabel: string
    loading?: boolean
    comparing?: boolean
    digesting?: boolean
    exporting?: boolean
    problem?: string
    compareProblem?: string
    digestProblem?: string
    exportProblem?: string
  }>(),
  {
    hotspotsVersion: '',
    loading: false,
    comparing: false,
    digesting: false,
    exporting: false,
    problem: '',
    compareProblem: '',
    digestProblem: '',
    exportProblem: '',
  },
)

const emit = defineEmits<{
  selectWorkflow: [id: string]
  selectHotspotsVersion: [value: string]
  selectAxis: [axis: ImproveCompareAxis]
  updateCompareA: [value: string]
  updateCompareB: [value: string]
  selectCompareNode: [nodeId: string]
  runCompare: []
  runDigest: []
  selectEvalsetRating: [rating: EvalsetRating]
  exportEvalset: []
}>()

/**
 * Every step and the models it ran on, for the Model axis's three pickers.
 *
 * Read off the SAME payload the first section is drawn from rather than from a
 * second endpoint, and specifically off `node_models` rather than off
 * `spend(group_by=model)`: the spend read answers "what billed anywhere in
 * this window", so it would offer a model the chosen step never ran, and an
 * arm that cannot exist is a question with no answer.
 */
/** Blank, or a positive whole number - anything else is not sent. */
const versionInvalid = computed(() => {
  const text = props.hotspotsVersion.trim()
  return text !== '' && !/^[1-9][0-9]*$/.test(text)
})

const compareNodeModels = computed(() => props.hotspots?.node_models ?? [])

const EVALSET_RATINGS: ReadonlyArray<{ id: EvalsetRating; label: string; note: string }> = [
  { id: 'good', label: 'Good', note: 'only the runs somebody accepted' },
  { id: 'bad', label: 'Bad', note: 'only the runs somebody rejected' },
  { id: 'unsure', label: 'Not sure', note: 'only the runs somebody could not call' },
  { id: 'any', label: 'Any', note: 'every run in this window, whatever anybody said' },
]

const chosenRating = computed(
  () => EVALSET_RATINGS.find((entry) => entry.id === props.evalsetRating) ?? EVALSET_RATINGS[3],
)
</script>

<template>
  <section class="admin-panel" aria-labelledby="admin-improve-title">
    <h2 id="admin-improve-title" class="sr-only">Improve</h2>

    <p v-if="problem" class="admin-problem" role="alert">
      <TriangleAlert :size="14" aria-hidden="true" />{{ problem }}
    </p>
    <p v-else-if="loading" class="admin-loading" role="status">Reading runs and frames…</p>

    <!--
      ONE WORKFLOW AT A TIME, for all four sections. Every question here is
      about a graph somebody drew; answering them across every workflow at once
      would average a research pipeline with a social-post writer and call the
      result a finding.
    -->
    <div class="improve-picker" role="group" aria-labelledby="improve-picker-label">
      <label id="improve-picker-label" class="improve-picker-label" for="improve-workflow">
        Which workflow
      </label>
      <select
        id="improve-workflow"
        class="improve-select"
        :value="workflowId"
        data-testid="improve-workflow"
        @change="emit('selectWorkflow', ($event.target as HTMLSelectElement).value)"
      >
        <option value="">Choose one…</option>
        <option v-for="entry in workflows" :key="entry.id" :value="entry.id">
          {{ entry.label }}<template v-if="entry.runs"> · {{ count(entry.runs) }} run(s)</template>
        </option>
      </select>
      <span class="improve-note">
        Every section below is about one workflow, over the window chosen above.
      </span>
    </div>

    <!-- ── 1. Where runs go wrong ──────────────────────────────────────── -->
    <section
      class="admin-block"
      aria-labelledby="improve-wrong-title"
      data-testid="improve-wrong"
    >
      <header class="admin-block-head">
        <h3 id="improve-wrong-title">Where runs go wrong</h3>
        <span class="panel-meta">
          {{ workflowId || 'no workflow chosen' }}<template
            v-if="workflowId && hotspots?.document_version"
          > · version {{ hotspots.document_version }}</template>
        </span>
      </header>
      <p class="improve-lede">
        Which step fails most, which tool comes back empty, and what each step costs. Every row
        carries the counts behind it, so a share you do not believe can be checked.
      </p>
      <!--
        ONE VERSION, OR ALL OF THEM. Without this, runs of version 1 and
        version 2 are counted together, so a change cannot be seen in these
        lists at all. Applied on Enter or when the box loses focus, and it
        re-reads this section only.
      -->
      <div v-if="workflowId" class="improve-controls">
        <label class="improve-field">
          <span>Version (blank = all)</span>
          <input
            class="improve-input"
            type="text"
            inputmode="numeric"
            :value="hotspotsVersion"
            placeholder="All versions"
            :aria-invalid="versionInvalid"
            data-testid="improve-wrong-version"
            @change="emit('selectHotspotsVersion', ($event.target as HTMLInputElement).value)"
          />
        </label>
        <span v-if="versionInvalid" class="improve-note" data-testid="improve-wrong-version-invalid">
          A version is a whole number such as 2. Leave it blank for every version.
        </span>
      </div>
      <p v-if="!workflowId" class="admin-empty" data-testid="improve-wrong-none">
        Choose a workflow above and this fills in. Nothing is fetched until you do.
      </p>
      <template v-else>
        <EstimateBand
          v-if="hotspots?.estimate"
          :note="hotspots?.error_note"
          scope="cost share and cost per outcome are node metrics, blind to embeddings and Firecrawl"
        />
        <ImproveHotspots :hotspots="hotspots" :loading="loading" />
      </template>
    </section>

    <!-- ── 2. Compare two versions ─────────────────────────────────────── -->
    <section
      class="admin-block"
      aria-labelledby="improve-compare-title"
      data-testid="improve-compare-section"
    >
      <header class="admin-block-head">
        <h3 id="improve-compare-title">Compare two versions</h3>
        <span class="panel-meta">two sides, six measures</span>
      </header>
      <p v-if="!workflowId" class="admin-empty" data-testid="improve-compare-none">
        Choose a workflow above to compare two of its versions.
      </p>
      <ImproveCompare
        v-else
        :compare="compare"
        :axis="compareAxis"
        :a="compareA"
        :b="compareB"
        :node-id="compareNodeId"
        :node-models="compareNodeModels"
        :loading="comparing"
        :problem="compareProblem"
        @select-axis="emit('selectAxis', $event)"
        @update-a="emit('updateCompareA', $event)"
        @update-b="emit('updateCompareB', $event)"
        @select-node="emit('selectCompareNode', $event)"
        @run="emit('runCompare')"
      />
    </section>

    <!-- ── 3. Export rated runs ────────────────────────────────────────── -->
    <section
      class="admin-block"
      aria-labelledby="improve-export-title"
      data-testid="improve-export"
    >
      <header class="admin-block-head">
        <h3 id="improve-export-title">Export rated runs</h3>
        <span class="panel-meta">one line per run</span>
      </header>
      <p class="improve-lede">
        Keep the runs worth learning from, as a file you can check a future change against.
      </p>

      <div class="improve-controls">
        <div class="admin-window" role="group" aria-label="Which runs to export">
          <button
            v-for="entry in EVALSET_RATINGS"
            :key="entry.id"
            type="button"
            class="admin-axis-button improve-axis"
            :class="{ 'is-active': evalsetRating === entry.id }"
            :aria-pressed="evalsetRating === entry.id"
            :title="entry.note"
            :data-testid="`improve-export-${entry.id}`"
            @click="emit('selectEvalsetRating', entry.id)"
          >
            {{ entry.label }}
          </button>
        </div>
        <span class="improve-note" data-testid="improve-export-window">
          {{ chosenRating.note }}, over {{ windowLabel }}
        </span>
        <button
          type="button"
          class="improve-button"
          :disabled="!workflowId || exporting"
          data-testid="improve-export-run"
          @click="emit('exportEvalset')"
        >
          <Download :size="13" aria-hidden="true" />
          {{ exporting ? 'Downloading…' : 'Download' }}
        </button>
        <span v-if="!workflowId" class="improve-note" data-testid="improve-export-blocked">
          Pick a workflow first.
        </span>
      </div>

      <!--
        WHAT IS IN THE FILE, ON THE CONTROL AND NOT IN A README. This is the
        most privacy-sensitive artifact this repository produces: an idea, the
        workflow's answer and a person's correction in one file. Redaction is
        key-NAME based - it removes a field called `api_key` - so it does not
        and cannot find a key somebody pasted into the text of an idea. Saying
        that on the control is the difference between a caveat and a warning.
      -->
      <p class="admin-warning" role="status" data-testid="improve-export-warning">
        <TriangleAlert :size="13" aria-hidden="true" />
        Each line holds what a person typed, what the workflow answered, every approval and
        correction along the way, and what somebody said about the run afterwards. Fields NAMED like
        secrets are removed before the file is written; a key somebody pasted into the text of an
        idea is not. Read it before you share it.
      </p>
      <p v-if="exportProblem" class="admin-problem" role="alert" data-testid="improve-export-problem">
        <TriangleAlert :size="14" aria-hidden="true" />{{ exportProblem }}
      </p>
    </section>

    <!-- ── 4. Ask a model to review ────────────────────────────────────── -->
    <section
      class="admin-block"
      aria-labelledby="improve-review-title"
      data-testid="improve-review-section"
    >
      <header class="admin-block-head">
        <h3 id="improve-review-title">Ask a model to review</h3>
        <span class="panel-meta">one press, one call</span>
      </header>
      <!--
        FOUND BY LOOKING, and it is the reason this gate exists. Before a
        workflow is chosen there is no digest page, so the panel below rendered
        an amber "this spends real money and the server did not report a
        ceiling" over three more absent-value facts - four warnings on an
        untouched screen about a button nobody could press. The other three
        sections already said "choose a workflow above"; this one now does too,
        and every one of those sentences is again a real answer about a real
        workflow rather than a report on an unasked question.
      -->
      <p v-if="!workflowId" class="admin-empty" data-testid="improve-review-none">
        Choose a workflow above to read its reviews, or to ask for one.
      </p>
      <ImproveDigest
        v-else
        :page="digests"
        :workflow-id="workflowId"
        :loading="loading"
        :running="digesting"
        :problem="digestProblem"
        @run="emit('runDigest')"
      />
    </section>
  </section>
</template>

<style scoped>
.improve-lede { margin: 0; color: var(--text-meta); font: var(--type-meta); line-height: 1.55; }
.improve-note { color: var(--text-40); font: var(--type-meta); }

.improve-picker {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-3);
  align-items: center;
  padding: var(--space-3) var(--space-4);
  background: var(--surface-well);
  border: 1px solid var(--border-control);
  border-radius: var(--r-md);
}

.improve-picker-label {
  color: var(--text-meta);
  font: var(--type-kicker);
  letter-spacing: var(--track-kicker);
  text-transform: uppercase;
}

.improve-select {
  min-width: 240px;
  min-height: 44px;
  max-width: 100%;
  padding: var(--space-2) var(--space-3);
  color: var(--text-body);
  font: var(--type-meta);
  background: var(--surface-raised);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
}

.improve-select:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

.improve-controls { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: center; }

.improve-field { display: grid; gap: var(--space-1); }
.improve-field > span {
  color: var(--text-meta);
  font: var(--type-kicker);
  letter-spacing: var(--track-kicker);
  text-transform: uppercase;
}

.improve-input {
  min-width: 180px;
  min-height: 44px;
  padding: var(--space-2) var(--space-3);
  color: var(--text-body);
  font: var(--type-meta);
  font-family: var(--font-mono);
  background: var(--surface-raised);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
}

.improve-input:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.improve-axis { min-height: 44px; }

.improve-button {
  display: inline-flex;
  gap: var(--space-2);
  align-items: center;
  min-height: 44px;
  padding: var(--space-2) var(--space-4);
  color: var(--text-title);
  font: var(--type-label);
  background: var(--surface-raised);
  border: 1px solid var(--border-control);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.improve-button:hover:not(:disabled) { border-color: var(--border-hover-strong); }
.improve-button:disabled { opacity: 0.45; cursor: default; }
.improve-button:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
</style>
