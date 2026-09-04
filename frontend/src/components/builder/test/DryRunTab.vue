<script setup lang="ts">
import { computed } from 'vue'
import { Calculator } from 'lucide-vue-next'
import type { FlowTest } from '../../../composables/useFlowTest'

/**
 * The Dry-run tab: parse, bound, price and compile, spending nothing (D5).
 *
 * THE HEADLINE IS THE CALL COUNT AND THE PRICE, and the sentence *"no tokens
 * were spent"* is rendered beside them rather than left implied. The gauntlet's
 * fourth rubric-13 line is that nothing above the ceiling is reachable anywhere
 * in the product, and a preview that quietly cost something would be exactly
 * that - so the tab says what it did not do, in words, every time.
 *
 * BOTH figures, never one. `floor_cost_usd` is the graph at published prices
 * and is the number a real run's total is comparable with; `static_cost_usd` is
 * what admission ENFORCES, with the nitro margin applied. Showing the enforced
 * one alone reads as an error, and showing the floor alone hides the bound.
 */

const props = defineProps<{ test: FlowTest }>()

const result = computed(() => props.test.dryRunResult.value)
const errors = computed(() =>
  (result.value?.problems ?? []).filter((problem) => problem.severity === 'error'),
)
const warnings = computed(() =>
  (result.value?.problems ?? []).filter((problem) => problem.severity !== 'error'),
)

function money(value: number): string {
  return `$${Number(value ?? 0).toFixed(4)}`
}

/**
 * The stage plan, read off the compiled definition's own `methods` map.
 *
 * `definition.methods` is what `Flow.from_declaration` is handed, so this is
 * the plan the runtime will actually walk rather than a second opinion about
 * it - which is the same reason the dry run returns the registered definition
 * instead of recompiling the stored document. A method carrying `start: true`
 * is marked, because "where does this begin" is the first question a stage list
 * is asked.
 */
const planSteps = computed<string[]>(() => {
  const methods = result.value?.definition?.methods
  if (!methods || typeof methods !== 'object') return []
  return Object.entries(methods as Record<string, unknown>).map(([name, method]) => {
    const start = Boolean((method as { start?: unknown } | null)?.start)
    return start ? `${name}  ← start` : name
  })
})
</script>

<template>
  <div class="test-tab" data-testid="test-tab-dry">
    <div class="test-actions">
      <button
        type="button"
        class="test-run"
        data-testid="test-dry-run"
        :disabled="test.dryRunPending.value"
        @click="void test.runDryRun()"
      >
        <Calculator :size="13" aria-hidden="true" />
        {{ test.dryRunPending.value ? 'Compiling…' : 'Dry run' }}
      </button>
      <span class="test-free" data-testid="test-dry-free">no tokens were spent</span>
    </div>

    <template v-if="result">
      <dl class="test-figures" data-testid="test-dry-figures">
        <div class="test-figure">
          <dt>modelled calls</dt>
          <dd data-testid="test-dry-calls">{{ result.budget.modelled_calls }}</dd>
        </div>
        <div class="test-figure">
          <dt>at published prices</dt>
          <dd data-testid="test-dry-floor">{{ money(result.budget.floor_cost_usd) }}</dd>
        </div>
        <div class="test-figure">
          <dt>enforced</dt>
          <dd data-testid="test-dry-static">{{ money(result.budget.static_cost_usd) }}</dd>
        </div>
        <div class="test-figure">
          <dt>billable · escalation · cycles</dt>
          <dd data-testid="test-dry-shape">
            {{ result.budget.billable_nodes }} · {{ result.budget.escalation_nodes }} ·
            {{ result.budget.cycles }}
          </dd>
        </div>
      </dl>

      <p
        v-if="result.budget.unpriced_models.length"
        class="test-unpriced"
        role="alert"
        data-testid="test-dry-unpriced"
      >
        {{ result.budget.unpriced_models.join(', ') }} has no entry in PRICES, so every
        call it makes contributes nothing to these totals.
      </p>

      <!--
        The stage plan, in the one form the dry run actually carries: the
        compiled definition's own method list. `definition.methods` is what
        `Flow.from_declaration` is handed, so this is the order the runtime
        will walk rather than a second opinion about it.
      -->
      <section class="test-plan" data-testid="test-dry-plan">
        <h3 class="test-plan-title">Stage plan</h3>
        <ol class="test-plan-list">
          <li v-for="step in planSteps" :key="step">{{ step }}</li>
        </ol>
      </section>

      <p class="test-verdict" :class="result.valid ? 'is-ok' : 'is-bad'" data-testid="test-dry-verdict">
        {{ result.valid ? 'This graph compiles.' : `${errors.length} problem(s) block it.` }}
      </p>

      <ul v-if="errors.length || warnings.length" class="test-problems" data-testid="test-dry-problems">
        <li
          v-for="problem in [...errors, ...warnings]"
          :key="`${problem.code}-${problem.node_id ?? problem.edge_id ?? ''}`"
          :class="`is-${problem.severity}`"
        >
          <code>{{ problem.code }}</code>
          <span>{{ problem.message }}</span>
        </li>
      </ul>
    </template>

    <p v-else class="test-note">Nothing has been priced yet.</p>
  </div>
</template>

<style scoped>
.test-tab { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.test-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.test-run {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  padding: 5px 11px;
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
  background: var(--surface-raised);
  color: var(--text-title);
  font: 600 var(--fs-12)/1.4 var(--font-body);
  cursor: pointer;
}
.test-run:disabled { opacity: 0.45; cursor: default; }
.test-free { color: var(--accent-mint); font: 500 var(--fs-11)/1.4 var(--font-mono); }
.test-note { margin: 0; color: var(--text-40); font: 400 var(--fs-12)/1.5 var(--font-body); }

.test-figures { display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 0; }
.test-figure { display: flex; flex-direction: column; gap: 2px; }
.test-figure dt {
  color: var(--text-40);
  font: 600 var(--fs-11)/1.3 var(--font-mono);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.test-figure dd { margin: 0; color: var(--text-title); font: 600 var(--fs-14)/1.2 var(--font-display); }

.test-unpriced {
  margin: 0;
  padding: 6px 9px;
  border: 1px solid var(--err-border);
  border-radius: var(--r-sm);
  background: var(--err-bg);
  color: var(--text-title);
  font: 400 var(--fs-12)/1.5 var(--font-body);
}

.test-plan { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.test-plan-title {
  margin: 0;
  color: var(--text-40);
  font: 600 var(--fs-11)/1.3 var(--font-mono);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.test-plan-list {
  margin: 0;
  padding-left: 18px;
  color: var(--text-body);
  font: 400 var(--fs-12)/1.6 var(--font-mono);
}

.test-verdict { margin: 0; font: 500 var(--fs-12)/1.5 var(--font-body); }
.test-verdict.is-ok { color: var(--accent-mint); }
.test-verdict.is-bad { color: var(--err-text); }

.test-problems { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 5px; }
.test-problems li { display: flex; gap: 8px; min-width: 0; }
.test-problems code { flex: none; font: 500 var(--fs-11)/1.5 var(--font-mono); color: var(--text-40); }
.test-problems li span { min-width: 0; overflow-wrap: anywhere; font: 400 var(--fs-12)/1.5 var(--font-body); }
.test-problems li.is-error span { color: var(--err-text); }
.test-problems li.is-warning span { color: var(--warn-text); }
</style>
