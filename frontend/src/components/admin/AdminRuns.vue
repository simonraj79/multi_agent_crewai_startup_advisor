<script setup lang="ts">
/**
 * What the product decided, and whether the humans agreed with it.
 *
 * Three charts and a table. The charts are the aggregate - how gates were
 * answered, how long people took, what verdicts came out - and the table is the
 * way into one run, whose gate trail opens in the docked drawer beside it.
 *
 * THE VERDICT CHART IS LABELLED FRAGILE, and that label is a criterion rather
 * than modesty (§9 row 3): verdicts are read from `run_frames`, so a retention
 * purge deletes this history and a restart loses anything not written. The
 * durable fix is a `runs.verdict` column and it is Phase 2. Shipping the chart
 * unlabelled would be shipping a number that silently becomes wrong.
 */
import { computed } from 'vue'
import { TriangleAlert } from 'lucide-vue-next'
import AdminBar from './AdminBar.vue'
import LangfuseLink from './LangfuseLink.vue'
import MoneyFigure from './MoneyFigure.vue'
import { count, duration, durationMs, humanise, personLabel, shortId, when } from './adminFormat'
import type { AdminGateStats, AdminLinks, AdminRunsPage, AdminVerdicts } from '../../services/adminApi'

const props = defineProps<{
  runs: AdminRunsPage | null
  gates: AdminGateStats | null
  verdicts: AdminVerdicts | null
  links: AdminLinks | null
  selectedRunId: string | null
  loading: boolean
  problem: string
}>()

const emit = defineEmits<{ openRun: [runId: string] }>()

const langfuseOn = computed(() => props.links?.langfuse.configured === true)

/** approve / revise / expired, as three shares of the gates that were closed. */
const gateOutcomes = computed(() => {
  const stats = props.gates
  if (!stats) return []
  const total = stats.approve + stats.revise + stats.expired
  return [
    { key: 'approve', label: 'approve', value: stats.approve, tone: 'people' as const },
    { key: 'revise', label: 'revise', value: stats.revise, tone: 'warn' as const },
    { key: 'expired', label: 'expired', value: stats.expired, tone: 'err' as const },
  ].map((row) => ({ ...row, total }))
})

const verdictPeak = computed(() =>
  (props.verdicts?.rows ?? []).reduce((high, row) => Math.max(high, row.count), 0),
)

const slowestGate = computed(() => {
  const rows = props.gates?.by_gate ?? []
  let slowest: { gate_id: string; median_seconds: number | null } | null = null
  for (const row of rows) {
    if (row.median_seconds === null) continue
    if (slowest === null || (slowest.median_seconds ?? 0) < row.median_seconds) slowest = row
  }
  return slowest
})
</script>

<template>
  <section class="admin-panel" aria-labelledby="admin-runs-title">
    <h2 id="admin-runs-title" class="sr-only">Runs and decisions</h2>

    <p v-if="problem" class="admin-problem" role="alert">
      <TriangleAlert :size="14" aria-hidden="true" />{{ problem }}
    </p>
    <p v-else-if="loading" class="admin-loading" role="status">Reading runs, gates and verdicts…</p>

    <div class="admin-blocks">
      <section class="admin-block" aria-labelledby="admin-gates-title">
        <header class="admin-block-head">
          <h3 id="admin-gates-title">Gate behaviour</h3>
          <span class="panel-meta" v-if="gates">
            {{ count(gates.approve + gates.revise + gates.expired + gates.unanswered) }} gates
          </span>
        </header>
        <ul v-if="gates" class="admin-bars" data-testid="admin-gate-outcomes">
          <AdminBar
            v-for="row in gateOutcomes"
            :key="row.key"
            :label="row.label"
            :value="row.value"
            :total="row.total"
            :display="count(row.value)"
            :tone="row.tone"
          />
        </ul>
        <dl v-if="gates" class="admin-facts">
          <div class="admin-fact">
            <dt>Median time to answer</dt>
            <dd>{{ duration(gates.median_seconds) }}</dd>
          </div>
          <div class="admin-fact">
            <dt>Slowest gate</dt>
            <dd v-if="slowestGate">
              {{ slowestGate.gate_id }} · {{ duration(slowestGate.median_seconds) }}
            </dd>
            <dd v-else>—</dd>
          </div>
          <div class="admin-fact">
            <dt>Still unanswered</dt>
            <dd>{{ count(gates.unanswered) }}</dd>
          </div>
        </dl>
        <p v-else-if="!loading" class="admin-empty">No gate opened in this window.</p>
      </section>

      <section class="admin-block" aria-labelledby="admin-verdicts-title">
        <header class="admin-block-head">
          <h3 id="admin-verdicts-title">Verdict mix</h3>
          <span class="panel-meta">from frames · inside retention</span>
        </header>
        <ul v-if="verdicts?.rows.length" class="admin-bars" data-testid="admin-verdicts">
          <AdminBar
            v-for="row in verdicts.rows"
            :key="row.verdict"
            :label="humanise(row.verdict)"
            :value="row.count"
            :total="verdictPeak"
            :display="count(row.count)"
            tone="people"
          />
        </ul>
        <p v-else-if="!loading" class="admin-empty">No verdict frame survives in this window.</p>
        <p class="admin-warning" role="status" data-testid="admin-verdict-fragile">
          <TriangleAlert :size="13" aria-hidden="true" />
          <span v-if="verdicts && !verdicts.complete">
            Retention is on, so this chart is missing every purged run.
          </span>
          <span v-else>
            Rebuilt from run frames. A retention purge or a lost frame takes this history with it.
          </span>
          <span v-if="verdicts?.note" class="admin-sub">{{ verdicts.note }}</span>
        </p>
      </section>
    </div>

    <section class="admin-block" aria-labelledby="admin-runtable-title">
      <header class="admin-block-head">
        <h3 id="admin-runtable-title">Runs</h3>
        <span class="panel-meta">newest first · cost is an estimate</span>
      </header>
      <div v-if="runs?.rows.length" class="admin-table-wrap">
        <table class="admin-table" data-testid="admin-runs-table">
          <caption class="sr-only">Every run in this window, newest first.</caption>
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Run</th>
              <th scope="col">Person</th>
              <th scope="col">Workflow</th>
              <th scope="col">Status</th>
              <th scope="col" class="is-number">Took</th>
              <th scope="col" class="is-number">Est.</th>
              <th scope="col">Verdict</th>
              <th scope="col">Trace</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in runs.rows"
              :key="row.run_id"
              :class="{ 'is-selected': row.run_id === selectedRunId }"
            >
              <td>{{ when(row.created_at) }}</td>
              <th scope="row">
                <button
                  class="admin-linkish"
                  type="button"
                  :data-testid="`admin-run-${row.run_id}`"
                  @click="emit('openRun', row.run_id)"
                >
                  {{ shortId(row.run_id) }}
                </button>
              </th>
              <td>{{ personLabel(row.user_id, row.email) }}</td>
              <td>{{ row.workflow_id }}</td>
              <td>
                <span class="admin-pill" :class="`is-${row.status}`">{{ row.status }}</span>
                <span v-if="row.stop_reason" class="admin-sub">{{ humanise(row.stop_reason) }}</span>
              </td>
              <td class="is-number">{{ durationMs(row.duration_ms) }}</td>
              <td class="is-number"><MoneyFigure :value="row.cost_usd" :tag="false" /></td>
              <td>{{ row.verdict ?? '—' }}</td>
              <td>
                <LangfuseLink
                  :href="row.langfuse?.trace_url"
                  :configured="langfuseOn"
                  kind="trace"
                  compact
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else-if="!loading && !problem" class="admin-empty">No run in this window.</p>
      <p v-if="runs?.next" class="admin-warning" role="status">
        There are older runs than this page holds.
      </p>
    </section>
  </section>
</template>
