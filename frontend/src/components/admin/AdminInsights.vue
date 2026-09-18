<script setup lang="ts">
import { ExternalLink, Lightbulb, RefreshCw, TriangleAlert } from 'lucide-vue-next'
import type { AdminInsights, AdminInsightSample, AdminRunRow } from '../../services/adminApi'
import { count, money, when } from './adminFormat'

defineProps<{
  insights: AdminInsights | null
  workflows: { workflow_id: string; runs: number | null }[]
  workflowId: string
  loading: boolean
  problem: string
}>()

const emit = defineEmits<{
  refresh: []
  selectWorkflow: [workflowId: string]
  openRun: [run: AdminRunRow]
}>()

function runRow(sample: AdminInsightSample, workflowId: string): AdminRunRow {
  return {
    run_id: sample.run_id,
    user_id: sample.user_id,
    email: null,
    workflow_id: workflowId,
    status: sample.status,
    created_at: sample.created_at,
    cost_usd: sample.cost_usd,
    langfuse: sample.langfuse,
  }
}

function percent(rate: number): string {
  return `${Math.round(rate * 100)}%`
}
</script>

<template>
  <section class="admin-panel admin-insights" aria-labelledby="admin-insights-title">
    <header class="admin-panel-head">
      <div>
        <span class="panel-kicker is-accent">GOVERNANCE</span>
        <h2 id="admin-insights-title">Governance insights</h2>
        <p class="panel-meta">Deterministic signals from sampled terminal workflow runs.</p>
      </div>
      <div class="admin-insights-controls">
        <label class="admin-insights-filter">
          <span>Workflow</span>
          <select
            :value="workflowId"
            data-testid="admin-insights-workflow"
            @change="emit('selectWorkflow', ($event.target as HTMLSelectElement).value)"
          >
            <option value="">All workflows</option>
            <option
              v-for="workflow in workflows"
              :key="workflow.workflow_id"
              :value="workflow.workflow_id"
            >
              {{ workflow.workflow_id }}<template v-if="workflow.runs !== null"> ({{ count(workflow.runs) }})</template>
            </option>
          </select>
        </label>
        <button
          class="button button-secondary"
          type="button"
          :disabled="loading"
          data-testid="admin-insights-refresh"
          @click="emit('refresh')"
        >
          <RefreshCw :size="13" aria-hidden="true" /> Refresh
        </button>
      </div>
    </header>

    <p v-if="problem" class="admin-problem" role="alert">
      <TriangleAlert :size="14" aria-hidden="true" />{{ problem }}
    </p>
    <p v-else-if="loading" class="admin-loading" role="status">Reading governance signals…</p>

    <template v-else-if="insights">
      <div
        v-if="insights.coverage.incomplete || insights.coverage.truncated || insights.coverage.warnings.length"
        class="admin-warning"
        data-testid="admin-insights-partial"
      >
        <strong>Partial evidence.</strong>
        {{ count(insights.coverage.runs_scanned) }} terminal runs scanned;
        {{ count(insights.coverage.runs_missing_frames) }} missing frames and
        {{ count(insights.coverage.runs_with_integrity_loss) }} with integrity loss.
        <ul v-if="insights.coverage.warnings.length" class="admin-plain">
          <li v-for="warning in insights.coverage.warnings" :key="warning">{{ warning }}</li>
        </ul>
      </div>

      <p v-if="insights.suppressed_count" class="admin-insights-note" data-testid="admin-insights-suppressed">
        {{ count(insights.suppressed_count) }} signal(s) hidden below the required evidence floors.
      </p>

      <!--
        WHAT PEOPLE SAID, beside what the rules found (plan 20 §2.2). It is one
        sentence rather than a chart on purpose: four counts over the same
        sample every finding below is counted against, in the order a person
        would read them, and "N not rated yet" last because it is the number
        that says how much of this is still unanswered.
      -->
      <p v-if="insights.labels" class="admin-insights-note" data-testid="admin-insights-labels">
        People rated {{ count(insights.labels.good) }} runs good,
        {{ count(insights.labels.bad) }} bad,
        {{ count(insights.labels.unsure) }} not sure.
        {{ count(insights.labels.unrated) }} not rated yet.
      </p>

      <div class="admin-insights-coverage" data-testid="admin-insights-coverage">
        <span>{{ count(insights.coverage.runs_scanned) }} terminal runs</span>
        <span>{{ count(insights.coverage.frames_scanned) }} frames</span>
        <span>{{ count(insights.coverage.gates_scanned) }} gates</span>
        <span>Minimum {{ count(insights.thresholds.min_runs) }} workflow runs and {{ count(insights.thresholds.min_affected_runs) }} affected runs</span>
      </div>
      <p class="admin-insights-note">
        These repeated patterns support investigation; they do not prove cause or measure output quality.
        Rates use all sampled terminal workflow runs, not node visits.
      </p>

      <div v-if="insights.findings.length" class="admin-insight-grid" data-testid="admin-insight-findings">
        <article v-for="finding in insights.findings" :key="`${finding.rule_id}-${finding.workflow_id}-${finding.node_id}-${finding.gate_id ?? ''}`" class="admin-insight-card">
          <header class="admin-insight-card-head">
            <div>
              <span class="panel-kicker">{{ finding.severity }} · {{ finding.workflow_id }}</span>
              <h3>{{ finding.title }}</h3>
            </div>
            <span class="admin-insight-rate">
              <template v-if="insights.coverage.truncated || insights.coverage.incomplete">at least </template>{{ count(finding.affected_runs) }} / {{ count(finding.total_runs) }}
              <small>{{ percent(finding.rate) }}<template v-if="insights.coverage.truncated || insights.coverage.incomplete"> of scanned runs</template></small>
            </span>
          </header>
          <p>{{ finding.explanation }}</p>
          <p class="admin-insight-suggestion"><Lightbulb :size="14" aria-hidden="true" />{{ finding.suggestion }}</p>
          <p class="panel-meta">
            Denominator: all sampled terminal {{ finding.workflow_id }} runs.
            <!-- `rated_bad` joins `failed_run` here because its `node_id` is
                 the literal `(run)` (§2.2): a rating is about the whole run,
                 so "Node (run)" would be a node name that is not one. -->
            <template v-if="finding.rule_id === 'failed_run' || finding.rule_id === 'rated_bad'">Scope: whole workflow</template>
            <template v-else>Node {{ finding.node_id }}</template><template v-if="finding.gate_id"> · gate {{ finding.gate_id }}</template>
          </p>
          <ul v-if="finding.samples.length" class="admin-insight-samples" aria-label="Sample runs">
            <li v-for="sample in finding.samples" :key="sample.run_id">
              <button type="button" class="admin-insight-run" :data-testid="`admin-insight-run-${sample.run_id}`" @click="emit('openRun', runRow(sample, finding.workflow_id))">
                <span>{{ when(sample.created_at) }} · {{ sample.status }} · estimate {{ money(sample.cost_usd) }}</span>
                <span class="panel-meta">
                  {{ sample.run_id }}<template v-if="sample.seq !== null"> · frame {{ sample.seq }}</template><template v-if="sample.gate_id"> · gate {{ sample.gate_id }}</template>
                </span>
              </button>
              <a v-if="sample.langfuse.trace_url" :href="sample.langfuse.trace_url" target="_blank" rel="noreferrer noopener" class="admin-langfuse-link" aria-label="Open sample trace in Langfuse">
                <ExternalLink :size="12" aria-hidden="true" /> Trace
              </a>
            </li>
          </ul>
        </article>
      </div>

      <div v-if="insights.insufficient.length" class="admin-empty" data-testid="admin-insights-small-sample">
        <p>More completed evidence is needed before a governance signal can be shown.</p>
        <ul class="admin-plain">
          <li v-for="row in insights.insufficient" :key="row.workflow_id">
            {{ row.workflow_id }}: {{ count(row.total_runs) }} of {{ count(row.required_runs) }} required terminal runs
          </li>
        </ul>
      </div>
      <p v-if="!insights.findings.length && !insights.insufficient.length" class="admin-empty" data-testid="admin-insights-empty">
        No repeated governance signals were found in the scanned evidence.
        <template v-if="insights.coverage.incomplete || insights.coverage.truncated">Coverage is incomplete; unscanned or missing evidence may contain other signals.</template>
      </p>
    </template>
  </section>
</template>
