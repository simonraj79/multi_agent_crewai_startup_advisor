<script lang="ts">
/**
 * Two server constants this component has to restate, and the test that stops
 * them drifting.
 *
 * They are declared in a plain `<script>` block rather than in `<script setup>`
 * so `tests/budgetMeter.spec.ts` can import them and assert each against the
 * literal in `src/brief_crew/config.py`. That is the `data/serverLimits.ts`
 * idiom applied one component wide: a duplicated constant is allowed here only
 * because the drift is a failing test rather than a bar that fills to the wrong
 * place.
 *
 * Neither can be derived from the `/validate` response. The response carries
 * `static_cost_usd`, `ceiling_usd` and the boolean `over_ceiling`, but not the
 * margin between them - and the bar has to reach full EXACTLY where that
 * boolean flips, or the author is warned at the wrong moment in one direction
 * or the other.
 */

/** `config.py:GRAPH_STATIC_BUDGET_MARGIN`. `budget.py` refuses at `static * this > ceiling`. */
export const GRAPH_STATIC_BUDGET_MARGIN = 1.25

/** `config.py:NITRO_PRICE_FACTOR`. Applied to every cheap-tier node in `static_cost_usd`. */
export const NITRO_PRICE_FACTOR = 1.8
</script>

<script setup lang="ts">
/**
 * What this graph costs at its worst, and how much room is left before the
 * compiler stops accepting it.
 *
 * FOUR THINGS IT REFUSES TO DO, each of them a way a cost display lies.
 *
 * 1. It never shows one dollar figure. `static_cost_usd` is what admission
 *    ENFORCES, and it is `NITRO_PRICE_FACTOR` above the published rate on every
 *    cheap node - shown alone it reads as an error, because it is higher than
 *    any invoice will be. `floor_cost_usd` is the comparable number, the one a
 *    real run's `compute_cost_usd` total can be held against. Both, always,
 *    each labelled with what it is.
 * 2. It never renders a percentage of a disabled ceiling. `ceiling_usd <= 0` is
 *    how `MAX_RUN_COST_USD` is turned off, and a fraction with zero underneath
 *    is either 0 or infinity - both lies. The bar is removed entirely and the
 *    row reads `no ceiling configured`.
 * 3. It never prices a graph at $0.00 by rounding. Two decimal places on a
 *    four-cent graph is the shape of the defect this repo already shipped once:
 *    128,069 real tokens reported at $0.00, because "no price on file" and
 *    "this was free" had the same spelling. Below a cent, four places.
 * 4. It never hardcodes a bound. All four headroom rows read
 *    `vocabulary.bounds`, `Math.trunc`'d on ingest - the server has already
 *    moved `max_billable_nodes` from 8 to 13 and `max_escalation_nodes` from 5
 *    to 8 since the spec was written, and a pip row that had those numbers
 *    baked in would now be lying about a graph that is perfectly legal.
 *
 * The pips are advisory presentation, not enforcement (spec R6 and section
 * 6.1). Nothing here disables anything; `billable-count` is the server's
 * problem to raise, and it raises it. What the pips buy is that an author SEES
 * a row go full before they place the node that breaks it.
 */
import { computed } from 'vue'
import { AlertTriangle, DollarSign } from 'lucide-vue-next'
import { vocabulary, vocabularyProblem } from '../../data/builderVocabulary'
import type { BuilderBudget } from '../../types/builder'

const props = withDefaults(
  defineProps<{
    /** The `/validate` response's budget block, or null before the first answer. */
    budget: BuilderBudget | null
    /**
     * `doc.nodes.length`, for the fourth pip row.
     *
     * A prop rather than something read off `budget`, because the budget block
     * counts BILLABLE nodes and the graph bound counts all of them - a router,
     * a gate and three transforms cost nothing and still fill
     * `max_graph_nodes`.
     */
    nodeCount: number
    /** True while validation is pending; dims the figures rather than hiding them. */
    stale?: boolean
  }>(),
  { stale: false },
)

const bounds = computed(() => vocabulary.value?.bounds ?? null)

/** Whether a ceiling is being enforced at all. `<= 0` is the documented disable. */
const ceiling = computed(() => props.budget?.ceiling_usd ?? 0)
const ceilingEnabled = computed(() => ceiling.value > 0)

/**
 * How full the bar is: the figure admission actually compares, over the ceiling.
 *
 * `static * GRAPH_STATIC_BUDGET_MARGIN` is exactly what `budget_problems`
 * tests, so the bar hits 100% on the same graph that flips `over_ceiling`.
 * Clamped for the width only - `overCeiling` below reads the server's boolean,
 * never this number, so a rounding difference can never make the bar and the
 * problem list disagree about whether the graph is publishable.
 */
const fraction = computed(() => {
  if (!props.budget || !ceilingEnabled.value) return 0
  return (props.budget.static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN) / ceiling.value
})

const fillPercent = computed(() => Math.min(100, Math.max(0, fraction.value * 100)))

const overCeiling = computed(() => props.budget?.over_ceiling === true)

const barTone = computed(() => {
  if (overCeiling.value || fraction.value >= 1) return 'is-over'
  return fraction.value >= 0.8 ? 'is-near' : 'is-clear'
})

const unpriced = computed(() => props.budget?.unpriced_models ?? [])

interface PipRow {
  key: string
  label: string
  used: number
  bound: number | null
}

/**
 * The four headroom rows, in the order an author hits them.
 *
 * `bound` is null when the vocabulary has not loaded, and the row then renders
 * the count with no denominator and the reason beneath. A guessed denominator
 * would be worse than none: it is the cut list's fallback-vocabulary rule
 * (item 17) applied to a number instead of a list.
 */
const pipRows = computed<PipRow[]>(() => {
  const budget = props.budget
  const limits = bounds.value
  return [
    { key: 'billable', label: 'billable', used: budget?.billable_nodes ?? 0, bound: limits ? Math.trunc(limits.max_billable_nodes) : null },
    { key: 'escalation', label: 'escalation', used: budget?.escalation_nodes ?? 0, bound: limits ? Math.trunc(limits.max_escalation_nodes) : null },
    { key: 'cycles', label: 'cycles', used: budget?.cycles ?? 0, bound: limits ? Math.trunc(limits.max_cycles) : null },
    { key: 'nodes', label: 'nodes', used: props.nodeCount, bound: limits ? Math.trunc(limits.max_graph_nodes) : null },
  ]
})

/**
 * `[filled, filled, empty, ...]` for one row, capped so a bound the server
 * raises to something large cannot produce a thousand DOM nodes.
 *
 * Past the cap the row still renders its `n of m` label, which is the part
 * that carries the fact; the pips are the glanceable half.
 */
const MAX_PIPS = 32

function pipsFor(row: PipRow): boolean[] {
  if (row.bound === null || row.bound > MAX_PIPS) return []
  return Array.from({ length: row.bound }, (_, index) => index < row.used)
}

/** Amber AT the bound, not past it - the last legal node should already look full. */
function pipTone(row: PipRow): string {
  if (row.bound === null) return ''
  if (row.used > row.bound) return 'is-over'
  return row.used >= row.bound ? 'is-near' : ''
}

/**
 * A dollar figure that never rounds a real cost to nothing.
 *
 * Two places above a cent, four below it, and a bare `$0.00` only for an
 * honest zero. The alternative shipped once: `cost_usd` read 0.0 after 128,069
 * tokens, and nothing on screen distinguished "free" from "we could not price
 * this".
 */
function money(value: number | undefined): string {
  if (value === undefined || !Number.isFinite(value)) return '—'
  if (value === 0) return '$0.00'
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`
}
</script>

<template>
  <section class="budget-meter" :class="{ 'is-stale': stale }" aria-labelledby="budget-title">
    <div class="budget-head">
      <span id="budget-title" class="budget-kicker">
        <DollarSign :size="12" aria-hidden="true" />
        WORST-CASE COST
      </span>
      <span v-if="!budget" class="budget-pending" data-testid="budget-pending">not yet priced</span>
    </div>

    <template v-if="budget">
      <div class="budget-figures">
        <!-- The comparable figure is the large one. It is the number a real
             run's total can be held against; the enforced one deliberately
             cannot be, and saying so beside it is the whole point. -->
        <p class="budget-floor" data-testid="budget-floor">
          <span class="budget-amount">{{ money(budget.floor_cost_usd) }}</span>
          <span class="budget-label">at published prices</span>
        </p>
        <p class="budget-static" data-testid="budget-static">
          <span class="budget-amount">{{ money(budget.static_cost_usd) }}</span>
          <span class="budget-label">enforced · {{ NITRO_PRICE_FACTOR }}× nitro margin</span>
        </p>
        <p class="budget-ceiling" data-testid="budget-ceiling">
          <span class="budget-amount">{{ ceilingEnabled ? money(ceiling) : '—' }}</span>
          <span class="budget-label">{{ ceilingEnabled ? 'ceiling' : 'no ceiling configured' }}</span>
        </p>
      </div>

      <!-- Removed, not emptied and not zeroed. A track drawn against a disabled
           ceiling would be a percentage of zero. -->
      <div
        v-if="ceilingEnabled"
        class="budget-track"
        :class="barTone"
        data-testid="budget-track"
        role="progressbar"
        aria-labelledby="budget-title"
        :aria-valuemin="0"
        :aria-valuemax="100"
        :aria-valuenow="Math.round(fillPercent)"
        :aria-valuetext="`${money(budget.static_cost_usd)} of a ${money(ceiling)} ceiling, with the ${GRAPH_STATIC_BUDGET_MARGIN}× margin`"
      >
        <span class="budget-fill" :style="{ width: `${fillPercent}%` }" />
      </div>

      <p v-if="unpriced.length" class="budget-unpriced" role="alert" data-testid="budget-unpriced">
        <AlertTriangle :size="13" aria-hidden="true" />
        <span>
          {{ unpriced.join(', ') }} has no entry in PRICES, so every call it makes would
          contribute nothing to this total.
        </span>
      </p>

      <ul class="budget-pips" aria-label="Headroom against the graph bounds">
        <li v-for="row in pipRows" :key="row.key" class="budget-pip-row" :class="pipTone(row)">
          <span class="budget-pip-label">{{ row.label }}</span>
          <span v-if="pipsFor(row).length" class="budget-pip-track" aria-hidden="true">
            <span
              v-for="(filled, index) in pipsFor(row)"
              :key="index"
              class="budget-pip"
              :class="{ 'is-filled': filled }"
            />
          </span>
          <span class="budget-pip-count" :data-testid="`budget-pip-${row.key}`">
            {{ row.bound === null ? row.used : `${row.used} of ${row.bound}` }}
          </span>
        </li>
      </ul>

      <p v-if="!bounds" class="budget-bounds-missing" role="status">
        {{ vocabularyProblem || 'Bounds unavailable until the vocabulary loads.' }}
      </p>
    </template>
  </section>
</template>

<style scoped>
.budget-meter { display: grid; gap: 9px; padding: 11px 12px; background: var(--surface-panel); border-top: 1px solid var(--border-default); }
/* Dimmed, never hidden. A cost estimate from 400ms ago is still the best figure
   available; removing it would leave the author with nothing while they type. */
.budget-meter.is-stale { opacity: 0.55; }
.budget-head { display: flex; align-items: center; justify-content: space-between; }
.budget-kicker { display: inline-flex; align-items: center; gap: 5px; color: var(--text-40); font: 700 var(--fs-11)/1 var(--font-mono); letter-spacing: 0.04em; }
.budget-pending { color: var(--text-40); font: 500 var(--fs-11)/1 var(--font-mono); }

.budget-figures { display: flex; align-items: baseline; gap: 14px; }
.budget-figures p { display: grid; margin: 0; gap: 2px; }
.budget-amount { font: 600 var(--fs-15)/1 var(--font-mono); }
.budget-floor .budget-amount { color: var(--text-title); font-size: var(--fs-18); }
.budget-static .budget-amount,
.budget-ceiling .budget-amount { color: var(--text-muted); font-size: var(--fs-13); }
.budget-label { color: var(--text-40); font: 500 10px/1.2 var(--font-mono); }
.budget-ceiling { margin-left: auto !important; text-align: right; }

.budget-track { position: relative; height: 6px; overflow: hidden; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-pill); }
.budget-fill { display: block; height: 100%; border-radius: var(--r-pill); transition: width var(--motion-medium) var(--ease-out); }
.budget-track.is-clear .budget-fill { background: var(--gradient-brand); }
.budget-track.is-near .budget-fill { background: var(--warn-text); }
.budget-track.is-over .budget-fill { background: var(--err-text); }
.budget-track.is-over { border-color: var(--err-border); }

.budget-unpriced { display: flex; gap: 7px; margin: 0; padding: 7px 8px; color: var(--warn-text); background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: var(--r-sm); font-size: var(--fs-11); line-height: 1.5; }
.budget-unpriced svg { flex: 0 0 auto; margin-top: 1px; }

.budget-pips { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
.budget-pip-row { display: flex; align-items: center; gap: 8px; }
.budget-pip-label { width: 66px; flex: 0 0 auto; color: var(--text-40); font: 600 10px/1.4 var(--font-mono); }
.budget-pip-track { display: flex; flex: 1 1 auto; flex-wrap: wrap; gap: 3px; }
.budget-pip { width: 5px; height: 5px; border-radius: 1px; background: var(--surface-raised); }
.budget-pip.is-filled { background: var(--text-muted); }
.budget-pip-count { flex: 0 0 auto; color: var(--text-40); font: 500 10px/1.4 var(--font-mono); }
/* Amber AT the bound: the row is full, and the next node of that kind is the
   one the server refuses. Red only once it has actually been exceeded, which a
   hand-edited or newly-bounded document can be. */
.budget-pip-row.is-near .budget-pip.is-filled,
.budget-pip-row.is-near .budget-pip-count { background: initial; color: var(--warn-text); }
.budget-pip-row.is-near .budget-pip.is-filled { background: var(--warn-text); }
.budget-pip-row.is-over .budget-pip.is-filled { background: var(--err-text); }
.budget-pip-row.is-over .budget-pip-count { color: var(--err-text); }

.budget-bounds-missing { margin: 0; color: var(--warn-text); font-size: var(--fs-11); line-height: 1.45; }
</style>
