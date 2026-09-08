<script setup lang="ts">
/**
 * What the money went on, on whichever of five axes the reader asks for.
 *
 * `GET /spend?group_by=user|day|workflow|model|node` is one endpoint and five
 * questions, so the axis is a control rather than five blocks: a reader wants
 * "which tier costs most" and "which graph is expensive" one after the other,
 * over the same window, and five stacked charts would make them scroll between
 * two answers to the same question.
 *
 * THE CEILINGS BLOCK IS NOT A CHART and is deliberately last: it is what the
 * numbers above are measured against, and it is the only part of this panel a
 * reader can act on without leaving the screen. It reads `/health`'s
 * `ceilings`, because those four figures are `config.py` constants and this
 * console must never restate one (the drift CLAUDE.md has recorded nine times).
 */
import { computed } from 'vue'
import { TriangleAlert } from 'lucide-vue-next'
import AdminBar from './AdminBar.vue'
import EstimateBand from './EstimateBand.vue'
import MoneyFigure from './MoneyFigure.vue'
import { count, humanise, money } from './adminFormat'
import type { AdminHealth, AdminSpend, AdminSpendAxis, AdminSpendRow } from '../../services/adminApi'

const props = defineProps<{
  axis: AdminSpendAxis
  spend: AdminSpend | null
  health: AdminHealth | null
  loading: boolean
  problem: string
}>()

const emit = defineEmits<{ selectAxis: [axis: AdminSpendAxis] }>()

/** The five axes, in the order a reader asks them. */
const AXES: ReadonlyArray<{ id: AdminSpendAxis; label: string; question: string }> = [
  { id: 'model', label: 'By model', question: 'Which tier costs most?' },
  { id: 'workflow', label: 'By workflow', question: 'Which graph is expensive?' },
  { id: 'user', label: 'By person', question: 'Who is spending?' },
  { id: 'node', label: 'By node', question: 'Which step in the graph?' },
  { id: 'day', label: 'By day', question: 'Is it going up?' },
]

const rows = computed(() => props.spend?.rows ?? [])
const peak = computed(() => rows.value.reduce((high, row) => Math.max(high, row.cost_usd), 0))

function rowLabel(row: AdminSpendRow): string {
  return row.label || row.key || '—'
}

/**
 * The second line of a bar: calls and runs where the axis has them.
 *
 * Not decoration. A model at $1.02 over 88 calls and a model at $1.02 over 4
 * calls are two completely different findings, and the second one is the price
 * table being wrong rather than the tier being expensive.
 */
function rowHint(row: AdminSpendRow): string {
  const parts: string[] = []
  if (row.call_count !== undefined) parts.push(`${count(row.call_count)} calls`)
  if (row.runs !== undefined) parts.push(`${count(row.runs)} runs`)
  if (row.total_tokens !== undefined) parts.push(`${count(row.total_tokens)} tokens`)
  return parts.join(' · ')
}

/**
 * Rows that cost nothing while making calls: a price-table gap, not free usage.
 *
 * The exact defect this repository shipped once - 128,069 real tokens priced at
 * `$0.00`, because "no price on file" and "this was free" had one spelling. It
 * is called out rather than left as a zero in a list.
 */
const unpriced = computed(() =>
  rows.value.filter((row) => row.cost_usd === 0 && (row.call_count ?? 0) > 0),
)

const ceilings = computed(() => props.health?.ceilings ?? null)
</script>

<template>
  <section class="admin-panel" aria-labelledby="admin-money-title">
    <h2 id="admin-money-title" class="sr-only">Money</h2>

    <EstimateBand
      :note="spend?.error_note"
      scope="Embedding, rerank and Firecrawl dollars are in no figure here."
    />

    <div class="admin-axis" role="group" aria-label="Group spend by">
      <button
        v-for="option in AXES"
        :key="option.id"
        class="admin-axis-button"
        type="button"
        :class="{ 'is-active': option.id === axis }"
        :aria-pressed="option.id === axis"
        :title="option.question"
        :data-testid="`admin-axis-${option.id}`"
        @click="emit('selectAxis', option.id)"
      >
        {{ option.label }}
      </button>
    </div>

    <p v-if="problem" class="admin-problem" role="alert">
      <TriangleAlert :size="14" aria-hidden="true" />{{ problem }}
    </p>
    <p v-else-if="loading" class="admin-loading" role="status">Grouping the window…</p>

    <template v-if="spend">
      <header class="admin-block-head">
        <h3>{{ AXES.find((option) => option.id === axis)?.label }}</h3>
        <span class="panel-meta">
          total <MoneyFigure :value="spend.total_usd" :tag="false" /> · estimate
        </span>
      </header>

      <ul v-if="rows.length" class="admin-bars" data-testid="admin-spend-rows">
        <AdminBar
          v-for="row in rows"
          :key="row.key"
          :label="rowLabel(row)"
          :value="row.cost_usd"
          :total="peak"
          :display="money(row.cost_usd)"
          :hint="rowHint(row) || null"
          tone="money"
        >
          <template #value>
            <MoneyFigure :value="row.cost_usd" :tag="false" />
          </template>
        </AdminBar>
      </ul>
      <p v-else class="admin-empty">Nothing was billed on this axis in this window.</p>

      <p v-if="unpriced.length" class="admin-warning" role="status" data-testid="admin-unpriced">
        <TriangleAlert :size="13" aria-hidden="true" />
        {{ unpriced.map(rowLabel).join(', ') }} made calls and contributed nothing to the total.
        That is a gap in the price table, not free usage.
      </p>

      <p v-if="spend.truncated" class="admin-warning" role="status">
        This grouping hit the scan cap; the total is a floor.
      </p>
    </template>

    <section class="admin-block" aria-labelledby="admin-ceilings-title">
      <header class="admin-block-head">
        <h3 id="admin-ceilings-title">Ceilings and meters in force</h3>
        <span class="panel-meta">live constants</span>
      </header>
      <dl v-if="ceilings" class="admin-facts" data-testid="admin-ceilings">
        <div class="admin-fact">
          <dt>Per-run ceiling</dt>
          <dd>{{ ceilings.run_usd === null ? 'none' : money(ceilings.run_usd) }}</dd>
        </div>
        <div class="admin-fact">
          <dt>Per-account lifetime cap</dt>
          <dd>{{ ceilings.account_usd === null ? 'none' : money(ceilings.account_usd) }}</dd>
        </div>
        <div class="admin-fact">
          <dt>Static budget margin</dt>
          <dd>{{ ceilings.margin === null ? '—' : `${ceilings.margin}×` }}</dd>
        </div>
        <div class="admin-fact">
          <dt>Platform Firecrawl per day</dt>
          <dd>{{ ceilings.firecrawl_daily === null ? '—' : `${count(ceilings.firecrawl_daily)} · resets 00:00 UTC` }}</dd>
        </div>
      </dl>
      <p v-else class="admin-empty">{{ humanise('health_not_read') }} — the health read has not answered.</p>
    </section>

    <!--
      §9 row 14, and it is in words rather than in a blank tile on purpose: a
      tile with no number in it reads as zero, and every one of these is
      unknown. `docs/admin-console/README.md` carries the same list.
    -->
    <p class="admin-absent" data-testid="admin-money-absent">
      <strong>Declared absent.</strong> Embedding, rerank and Firecrawl dollars are in no figure on
      this screen. Command-line runs are never traced. Retries inside the HTTP client are invisible.
      A blank here means unknown, not zero.
    </p>
  </section>
</template>
