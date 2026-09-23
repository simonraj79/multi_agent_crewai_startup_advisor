<script setup lang="ts">
/**
 * **Where do runs of this workflow go wrong?** - ranked lists and the outcomes.
 *
 * `.agent/plans/21-test-a-change.md`, R7's first section. Everything here is
 * arithmetic over frames the runs already wrote: no model call, no second
 * pipeline, and no number that is not a count of something that happened.
 *
 * EVERY ROW CARRIES THE COUNTS A SENTENCE WOULD HAVE TO CITE, and that is the
 * plan's phrasing rather than a layout preference. A rate on its own - "58%
 * empty" - is unfalsifiable by a reader; `7 of 12 calls` is not.
 *
 * ONE HUE PER LIST, and the hue is the list's SUBJECT rather than the row's
 * value (`AdminBar`'s rule): money is cyan, a refusal is warn, an error is
 * err. A bar that changed colour with its own size would be a fifth signal
 * nobody asked for.
 *
 * THE SMALL-SAMPLE LINE RIDES ON THE SERVER'S OWN FLOOR, and is simply absent
 * when the server names none. A floor written here would be a second answer to
 * a server constant, which is the one mistake this repository has made in the
 * same paragraph nine times.
 */
import { computed, ref } from 'vue'
import { Copy, TriangleAlert } from 'lucide-vue-next'
import AdminBar from './AdminBar.vue'
import MoneyFigure from './MoneyFigure.vue'
import { count, duration, durationMs, humanise } from './adminFormat'
import { describeCounts } from '../../services/adminApi'
import type { ImproveHotspots, ImproveRouteRow, ImproveTaskRow } from '../../services/adminApi'

const props = withDefaults(
  defineProps<{
    hotspots: ImproveHotspots | null
    loading?: boolean
    problem?: string
  }>(),
  { loading: false, problem: '' },
)

const runs = computed(() => props.hotspots?.runs ?? 0)
const minRuns = computed(() => props.hotspots?.min_runs ?? null)
const thin = computed(() => minRuns.value !== null && runs.value < minRuns.value)

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${Math.round(value * 100)}%`
}

const agents = computed(() => props.hotspots?.agents ?? [])
const tools = computed(() => props.hotspots?.tools ?? [])
const errors = computed(() => props.hotspots?.errors ?? [])
const gates = computed(() => props.hotspots?.gates ?? [])
const routes = computed(() => props.hotspots?.routes ?? [])
const outcomes = computed(() => props.hotspots?.outcomes ?? null)
const tasks = computed(() => props.hotspots?.tasks ?? [])
/**
 * Only the steps that finished over at least one tool failure.
 *
 * A row reading "0 of 2 completions recorded a tool failure" says nothing an
 * admin can act on, and a workflow with many steps drowned the one row that
 * did in two dozen that did not (production, 2026-09-23). The header count
 * still says how many completions were looked at, so the silence is honest.
 */
const failingTasks = computed(() => tasks.value.filter((row) => row.tool_failures > 0))
const taskCompletions = computed(() => props.hotspots?.task_completions ?? 0)
const taskToolFailures = computed(() => props.hotspots?.task_tool_failures ?? 0)
const sampleRunIds = computed(() => props.hotspots?.sample_run_ids ?? [])

/**
 * What people said about these runs, in one read-only sentence.
 *
 * It reads `runs.rating` through the same payload every count above it comes
 * from, and it writes nothing: the only place a rating is SET is the run
 * drawer's control (plan 20). A second control here would be a second door
 * onto one column, and the two would eventually disagree about what was
 * written.
 */
const ratingSentence = computed(() => {
  const mix = props.hotspots?.rating_mix
  if (!mix) return ''
  const said = (mix.good ?? 0) + (mix.bad ?? 0) + (mix.unsure ?? 0)
  if (said === 0) return ''
  const parts: string[] = []
  if (mix.good) parts.push(`${count(mix.good)} good`)
  if (mix.bad) parts.push(`${count(mix.bad)} bad`)
  if (mix.unsure) parts.push(`${count(mix.unsure)} not sure`)
  return `People said something about ${count(said)} of ${count(runs.value)} runs: ${parts.join(', ')}.`
})

/** The tallest bar in each list, so a chart is scaled by its own peak. */
function peak(values: number[]): number {
  return values.reduce((high, value) => Math.max(high, value), 0)
}

const errorPeak = computed(() => peak(errors.value.map((row) => row.count)))
const agentCost = computed(() => agents.value.reduce((total, row) => total + (row.cost_usd || 0), 0))

/**
 * Whether the cheap-tier figure is worth printing beside the real one.
 *
 * FOUND BY LOOKING, against a real backend: every node of the built-in
 * validator already runs on the cheap tier, and the server answers
 * `cheap_tier_cost_usd` equal to `cost_usd` rather than null - so six rows
 * read `$0.32 / about $0.32 on the cheap tier`, which is a suggestion to
 * change nothing, printed six times. A saving of less than a cent is not a
 * suggestion either; it is a rounding difference wearing one.
 */
function showsCheapTier(row: { cost_usd: number; cheap_tier_cost_usd?: number | null }): boolean {
  const cheap = row.cheap_tier_cost_usd
  if (cheap === null || cheap === undefined || !Number.isFinite(cheap)) return false
  return row.cost_usd - cheap >= 0.01
}

function agentName(row: { agent_role?: string | null; node_label?: string | null; node_id: string }): string {
  return row.agent_role || row.node_label || row.node_id
}

/**
 * A stored rating in the words the control itself uses.
 *
 * `unsure` is the column's value and `not sure` is what the button says, so
 * the screen says the second. An unknown value falls through to sentence case
 * rather than being dropped - the rule `verdictDisplay.ts` already follows.
 */
const RATING_WORDS: Readonly<Record<string, string>> = {
  good: 'good',
  bad: 'bad',
  unsure: 'not sure',
  unrated: 'nothing said',
}

function ratingWord(value: string): string {
  return RATING_WORDS[value] ?? humanise(value).toLowerCase()
}

/**
 * One router, as a sentence.
 *
 * Three cases and they are three different facts: a router that never decided
 * anything is not a router that always went the same way, and neither is a
 * router that branched. Saying "0 times out of 0" for the first would be a
 * finding about an empty window dressed as a finding about a graph.
 */
function routeSentence(row: ImproveRouteRow): string {
  const name = row.node_label || row.node_id
  if (row.decisions === 0) return `${name} made no decision in this window.`
  if (row.unique_routes <= 1) {
    return `${name} took the same branch ${count(row.decisions)} times out of ${count(row.decisions)}.`
  }
  return `${name} took ${count(row.unique_routes)} different branches over ${count(row.decisions)} decisions.`
}

/**
 * One step's tasks, named by the step and never by the task's rendered prompt.
 *
 * `completions` counts the task-completed frames that carry the new keys, not
 * every task that has ever finished - so the noun is `completions` rather than
 * `runs`, and the section's empty state carries the rest of that caveat.
 */
function taskSentence(row: ImproveTaskRow): string {
  // The STEP's own label, never the task's prompt: a builder task has no
  // declared name, and the server groups and names it by node. A declared
  // task name is added only when it says something the label does not - a
  // crew node running two named tasks.
  const where = row.node_label || row.node_id
  const named =
    row.task_name && row.task_name !== row.node_id && row.task_name !== where
      ? ` (${row.task_name})`
      : ''
  return (
    `${where}${named}: ${count(row.tool_failures)} of ` +
    `${count(row.completions)} completions recorded a tool failure and still finished.`
  )
}

/**
 * Copy a run id, and say so for a moment.
 *
 * NOT A LINK, and that is a measured fact rather than a preference: the hash
 * router has no `#/run/<run_id>` route - `workspaceRoute` answers `studio` for
 * every `run/…` hash - so an anchor here would land on whatever the console
 * last held and claim to have opened this run. An id you can copy into the
 * Runs tab is the honest affordance until that route exists.
 */
const copied = ref('')

async function copyRunId(runId: string): Promise<void> {
  try {
    await navigator.clipboard?.writeText(runId)
    copied.value = runId
    window.setTimeout(() => {
      if (copied.value === runId) copied.value = ''
    }, 2000)
  } catch {
    // A refused or absent clipboard is not an error worth a banner: the id is
    // on screen and selectable, which is what the affordance is for.
    copied.value = ''
  }
}
</script>

<template>
  <div class="improve-hotspots" data-testid="improve-hotspots">
    <p v-if="problem" class="admin-problem" role="alert">
      <TriangleAlert :size="14" aria-hidden="true" />{{ problem }}
    </p>
    <p v-else-if="loading" class="admin-loading" role="status">Reading frames…</p>

    <p v-if="thin" class="admin-warning" role="status" data-testid="improve-hotspots-thin">
      <TriangleAlert :size="13" aria-hidden="true" />
      {{ count(runs) }} run{{ runs === 1 ? '' : 's' }} in this window, under the
      {{ minRuns }} it takes to read a rate. Treat every share below as a hint about one or two
      events.
    </p>
    <p v-if="hotspots?.truncated" class="admin-warning" role="status">
      <TriangleAlert :size="13" aria-hidden="true" />
      The scan hit its row cap, so these counts are a floor and not a total.
    </p>

    <p v-if="ratingSentence" class="improve-lede" data-testid="improve-rating-line">
      {{ ratingSentence }}
    </p>

    <section class="admin-block" aria-labelledby="improve-agents-title">
      <header class="admin-block-head">
        <h3 id="improve-agents-title">Which agent costs the most, and which fails</h3>
        <span class="panel-meta">by estimated cost · {{ count(agents.length) }} node(s)</span>
      </header>
      <p class="improve-lede">
        One row per agent node. The bar is its share of this workflow's spend; the line under the
        name is how often it ran, how often it failed, and how many model calls it makes per run.
      </p>
      <ul v-if="agents.length" class="admin-bars" data-testid="improve-agent-rows">
        <AdminBar
          v-for="row in agents"
          :key="row.node_id"
          :label="agentName(row)"
          :value="row.cost_usd"
          :total="agentCost"
          tone="money"
          :hint="
            `${count(row.runs)} runs · ${count(row.executions)} executions · ` +
            `${count(row.failures)} failed · ${row.calls_per_execution.toFixed(1)} calls each` +
            (row.guardrail_retries ? ` · ${count(row.guardrail_retries)} guardrail retries` : '') +
            (row.truncated_outputs ? ` · ${count(row.truncated_outputs)} cut short` : '') +
            (describeCounts(row.error_classes) ? ` · ${describeCounts(row.error_classes)}` : '') +
            (row.mean_ms ? ` · ${durationMs(row.mean_ms)} each` : '')
          "
        >
          <template #value>
            <MoneyFigure :value="row.cost_usd" :tag="false" />
            <span v-if="showsCheapTier(row)" class="admin-sub">
              about <MoneyFigure :value="row.cheap_tier_cost_usd" :tag="false" /> on the cheap tier
            </span>
          </template>
        </AdminBar>
      </ul>
      <p v-else-if="!loading" class="admin-empty">No agent ran in this window.</p>
    </section>

    <section class="admin-block" aria-labelledby="improve-tools-title">
      <header class="admin-block-head">
        <h3 id="improve-tools-title">Which tool comes back empty, and which fails</h3>
        <span class="panel-meta">by share of calls that found nothing</span>
      </header>
      <p class="improve-lede">
        A tool that returns nothing is not an error - it is an answer the agent then writes around.
        The bar is the share of calls that came back empty; the failures are beside it.
      </p>
      <ul v-if="tools.length" class="admin-bars" data-testid="improve-tool-rows">
        <AdminBar
          v-for="row in tools"
          :key="`${row.tool}:${row.node_id ?? ''}`"
          :label="row.tool"
          :value="Math.round((row.empty_rate ?? 0) * 100)"
          :total="100"
          tone="warn"
          :display="`${count(row.empty)} of ${count(row.calls)} empty`"
          :hint="
            (row.node_id ? `on ${row.node_id} · ` : '') +
            `${count(row.calls)} calls · ${count(row.failed)} failed (${percent(row.failed_rate)})` +
            (row.from_cache ? ` · ${count(row.from_cache)} from cache` : '') +
            (row.queries_sample?.length ? ` · asked: ${row.queries_sample.slice(0, 2).join(' | ')}` : '')
          "
        />
      </ul>
      <p v-else-if="!loading" class="admin-empty">No tool was called in this window.</p>
    </section>

    <div class="admin-blocks">
      <section class="admin-block" aria-labelledby="improve-errors-title">
        <header class="admin-block-head">
          <h3 id="improve-errors-title">Errors raised, by exception class</h3>
          <span class="panel-meta">{{ count(errors.length) }} class(es)</span>
        </header>
        <p class="improve-lede">
          The exception classes these runs raised, and where. Fix the top one before changing a
          prompt anywhere downstream of it.
        </p>
        <ul v-if="errors.length" class="admin-bars" data-testid="improve-error-rows">
          <AdminBar
            v-for="row in errors"
            :key="row.error_class"
            :label="row.error_class"
            :value="row.count"
            :total="errorPeak"
            tone="err"
            :display="count(row.count)"
            :hint="
              [(row.nodes ?? []).slice(0, 3).join(', '), (row.agent_roles ?? []).slice(0, 2).join(', ')]
                .filter(Boolean)
                .join(' · ')
            "
          />
        </ul>
        <p v-else-if="!loading" class="admin-empty">Nothing raised in this window.</p>
      </section>

      <section class="admin-block" aria-labelledby="improve-gates-title">
        <header class="admin-block-head">
          <h3 id="improve-gates-title">Approvals, and how often they were sent back</h3>
          <span class="panel-meta">by share of answers that sent it back</span>
        </header>
        <p class="improve-lede">
          A step people send back often is the clearest signal on this screen: what the workflow
          proposes is not what they accept. The edited fields say which part.
        </p>
        <ul v-if="gates.length" class="admin-bars" data-testid="improve-gate-rows">
          <AdminBar
            v-for="row in gates"
            :key="row.gate_id"
            :label="row.gate_id"
            :value="Math.round((row.revise_rate ?? 0) * 100)"
            :total="100"
            tone="warn"
            :display="`${count(row.revise)} of ${count(row.answered)} sent back`"
            :hint="
              `${count(row.opened)} opened · ${count(row.expired)} expired` +
              (row.median_seconds ? ` · median ${duration(row.median_seconds)} to answer` : '') +
              (describeCounts(row.edited_fields) ? ` · edited: ${describeCounts(row.edited_fields)}` : '')
            "
          />
        </ul>
        <p v-else-if="!loading" class="admin-empty">Nobody was asked to approve anything here.</p>
      </section>
    </div>

    <!--
      ONE SENTENCE PER ROUTER, not a proportional bar.

      The finding here is a BINARY - did this router ever take a second branch -
      and the bar drew it as two channels at once: length encoded traffic while
      the finding was the colour, so a short warn-coloured bar asked the reader
      to decode two things to learn one.
    -->
    <section class="admin-block" aria-labelledby="improve-routes-title">
      <header class="admin-block-head">
        <h3 id="improve-routes-title">Branches taken</h3>
        <span class="panel-meta">{{ count(routes.length) }} decision point(s)</span>
      </header>
      <p class="improve-lede">
        A decision point that has taken the same branch every time is either a condition that never
        varies or a branch that is dead. Both are worth knowing; only you can say which.
      </p>
      <ul v-if="routes.length" class="improve-sentences" data-testid="improve-route-rows">
        <li
          v-for="row in routes"
          :key="row.node_id"
          class="improve-sentence"
          :class="{ 'is-warn': row.unique_routes <= 1 && row.decisions > 0 }"
          :data-node-id="row.node_id"
        >
          <span class="improve-sentence-line">{{ routeSentence(row) }}</span>
          <span v-if="describeCounts(row.routes, 4)" class="improve-sentence-sub">
            {{ describeCounts(row.routes, 4) }}
          </span>
        </li>
      </ul>
      <p v-else-if="!loading" class="admin-empty">Nothing branched in this window.</p>
    </section>

    <!--
      A run recorded before the serializer change carries none of these keys, so
      an empty list means "not recorded yet" and never "no tool failed" - which
      is the one confusion on this panel that would be completely invisible.
    -->
    <section class="admin-block" aria-labelledby="improve-tasks-title">
      <header class="admin-block-head">
        <h3 id="improve-tasks-title">Tasks, and the tool failures they finished over</h3>
        <span class="panel-meta">
          {{ count(taskToolFailures) }} of {{ count(taskCompletions) }} completions
        </span>
      </header>
      <p class="improve-lede">
        A tool can fail and the task can still finish: the agent narrates the failure and writes
        around it. That is the run nobody reports, and it is where a workflow quietly gets worse.
      </p>
      <ul v-if="failingTasks.length" class="improve-sentences" data-testid="improve-task-rows">
        <li
          v-for="row in failingTasks"
          :key="`${row.task_name}:${row.node_id}`"
          class="improve-sentence"
          :class="{ 'is-warn': row.tool_failures > 0 }"
          :data-node-id="row.node_id"
        >
          <span class="improve-sentence-line">{{ taskSentence(row) }}</span>
        </li>
      </ul>
      <p
        v-else-if="!loading && tasks.length"
        class="admin-empty"
        data-testid="improve-tasks-clean"
      >
        No task finished over a tool failure ({{ count(taskCompletions) }} completions).
      </p>
      <p v-else-if="!loading" class="admin-empty" data-testid="improve-tasks-empty">
        No run recorded after the update has finished a task yet.
      </p>
    </section>

    <section v-if="outcomes" class="admin-block" aria-labelledby="improve-outcomes-title">
      <header class="admin-block-head">
        <h3 id="improve-outcomes-title">How runs ended, and what each ending cost</h3>
        <span class="panel-meta">cost is an estimate</span>
      </header>
      <p class="improve-lede">
        The answers these runs reached, what people said about them, and how they finished. Cost per
        outcome is the number to compare a change against.
      </p>
      <div class="improve-outcome-grid" data-testid="improve-outcomes">
        <dl v-if="outcomes.by_verdict?.length" class="admin-facts">
          <div v-for="row in outcomes.by_verdict" :key="row.verdict" class="admin-fact">
            <dt>{{ humanise(row.verdict) }}</dt>
            <dd>
              {{ count(row.runs) }} run(s)
              <span class="admin-sub">
                <MoneyFigure :value="row.cost_per_run ?? null" :tag="false" /> each<template
                  v-if="row.mean_confidence !== null && row.mean_confidence !== undefined"
                >
                  · mean confidence {{ percent(row.mean_confidence) }}</template
                >
              </span>
            </dd>
          </div>
        </dl>
        <dl v-if="outcomes.by_rating?.length" class="admin-facts">
          <div v-for="row in outcomes.by_rating" :key="row.rating" class="admin-fact">
            <dt>Called {{ ratingWord(row.rating) }}</dt>
            <dd>
              {{ count(row.runs) }} run(s)
              <span class="admin-sub"><MoneyFigure :value="row.cost_usd ?? null" :tag="false" /></span>
            </dd>
          </div>
        </dl>
        <dl v-if="outcomes.by_status" class="admin-facts">
          <div v-for="(value, key) in outcomes.by_status" :key="key" class="admin-fact">
            <dt>{{ humanise(String(key)) }}</dt>
            <dd>{{ count(value) }}</dd>
          </div>
        </dl>
      </div>
    </section>

    <!--
      THE RUNS BEHIND THE COUNTS, so "read the bad ones" is a thing a person
      can actually do. The ids are the server's own sample and they are plain
      text with a copy button rather than links - see `copyRunId` for why.
    -->
    <section
      v-if="sampleRunIds.length"
      class="admin-block"
      aria-labelledby="improve-samples-title"
    >
      <header class="admin-block-head">
        <h3 id="improve-samples-title">Runs behind these counts</h3>
        <span class="panel-meta">{{ count(sampleRunIds.length) }} of {{ count(runs) }}</span>
      </header>
      <p class="improve-lede">
        A sample, not the whole window. Copy one and paste it into the Runs tab to read what
        actually happened in it.
      </p>
      <ul class="improve-samples" data-testid="improve-sample-runs">
        <li v-for="runId in sampleRunIds" :key="runId" class="improve-sample">
          <code class="improve-sample-id">{{ runId }}</code>
          <button
            type="button"
            class="improve-copy"
            :data-testid="`improve-copy-run-${runId}`"
            :aria-label="`Copy run id ${runId}`"
            @click="copyRunId(runId)"
          >
            <Copy :size="12" aria-hidden="true" />
            {{ copied === runId ? 'Copied' : 'Copy' }}
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.improve-hotspots { display: grid; gap: var(--space-4); }
.improve-lede { margin: 0; color: var(--text-meta); font: var(--type-meta); line-height: 1.55; }

/*
 * FOUND BY LOOKING, at 1440, and invisible to every test in this repository.
 *
 * `.admin-bar-label` is `nowrap` + `overflow: hidden` + `text-overflow:
 * ellipsis`, which is right for the Money panel's hints (`88 calls · 22 runs`)
 * and wrong for these. The hint under an agent carries six facts, and the
 * ellipsis never appears - `text-overflow` acts on the block's own text, not
 * on a nested grid item - so the line was simply CUT mid-word: `4 guardrail
 * retrie`, `asked: clinic`. A hint that stops mid-word does not read as
 * truncated, it reads as a value, which is worse than showing nothing.
 *
 * Scoped to this panel with `:deep` rather than fixed in `admin.css`, because
 * the shared rule is correct where it was written and four other panels are
 * drawn by it. The row simply grows a line instead of losing one.
 */
.improve-hotspots :deep(.admin-bar-label) {
  overflow: visible;
  white-space: normal;
}

.improve-hotspots :deep(.admin-bar-hint) { line-height: 1.5; }
.improve-outcome-grid {
  display: grid;
  gap: var(--space-4);
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
}

/* A LIST OF SENTENCES, where a bar chart used to be. One rule, two lists
   (branches and tasks), because both say the same kind of thing: a named node,
   a count, and a colour that agrees with the sentence instead of encoding a
   second quantity beside it. */
.improve-sentences { display: grid; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }

.improve-sentence {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-left: 3px solid var(--border-control);
  border-radius: var(--r-sm);
}

.improve-sentence.is-warn { border-left-color: var(--warn-border); }
.improve-sentence-line { color: var(--text-body); font: var(--type-meta); line-height: 1.5; }
.improve-sentence.is-warn .improve-sentence-line { color: var(--warn-text); }
.improve-sentence-sub { color: var(--text-40); font: var(--type-meta); }

.improve-samples { display: grid; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }

.improve-sample {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-3);
  align-items: center;
}

.improve-sample-id {
  color: var(--text-body);
  font: var(--type-meta);
  font-family: var(--font-mono);
  overflow-wrap: anywhere;
}

/* 44px, like every other pressable thing on this console: the copy button sits
   in a dense list and a 22px target in a list of ten is a list nobody can use
   on a touch screen. */
.improve-copy {
  display: inline-flex;
  gap: var(--space-1);
  align-items: center;
  min-height: 44px;
  padding: var(--space-1) var(--space-3);
  color: var(--text-meta);
  font: var(--type-meta);
  background: var(--surface-raised);
  border: 1px solid var(--border-control);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.improve-copy:hover { border-color: var(--border-hover-strong); }
.improve-copy:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
</style>
