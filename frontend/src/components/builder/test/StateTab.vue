<script setup lang="ts">
import { computed } from 'vue'
import type { FlowTest } from '../../../composables/useFlowTest'

/**
 * The State tab: the flow state at one moment, grouped (D2).
 *
 * `step` IS A FRAME `seq`, not a state row id, and that is the server's
 * decision rather than this tab's: a frame seq is the only cursor a client
 * already has - it is what `/frames` pages on and what the socket replays from
 * - and the answer is the last `flow_states` row written at or before that
 * frame's timestamp.
 *
 * The reserved namespaces are GROUPED AND KEPT, never hidden. `__builder__` and
 * the `turns__` counters are the interesting half of "why did this run take the
 * branch it took", which is the whole question a step slider is for; the
 * server does not strip them either, and a client that did would be answering a
 * different question than the one it was handed.
 */

const props = defineProps<{ test: FlowTest }>()

const runId = computed(() => props.test.run.runId.value)
const max = computed(() => props.test.maxStep.value)

function preview(value: unknown): string {
  if (value === null || value === undefined) return String(value)
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}
</script>

<template>
  <div class="test-tab" data-testid="test-tab-state">
    <p v-if="!runId" class="test-note" data-testid="test-state-empty">
      Run this graph once, and every step of it can be inspected here.
    </p>

    <template v-else>
      <div class="test-step">
        <label class="test-step-label" :for="'test-state-step'">Step</label>
        <input
          id="test-state-step"
          class="test-step-slider"
          data-testid="test-state-step"
          type="range"
          min="1"
          :max="Math.max(1, max)"
          :value="test.stateStep.value || Math.max(1, max)"
          :disabled="max < 1"
          @change="void test.loadState(Number(($event.target as HTMLInputElement).value))"
        >
        <span class="test-step-count" data-testid="test-state-count">
          {{ test.stateStep.value || 0 }} / {{ max }}
        </span>
      </div>

      <p v-if="test.statePending.value" class="test-note">Reading…</p>

      <section
        v-for="group in test.stateGroups.value"
        :key="group.prefix || 'own'"
        class="test-state-group"
        :data-prefix="group.prefix"
        data-testid="test-state-group"
      >
        <h3 class="test-state-title">{{ group.label }}</h3>
        <dl class="test-state-list">
          <template v-for="entry in group.entries" :key="entry.key">
            <dt>{{ entry.label }}</dt>
            <dd>{{ preview(entry.value) }}</dd>
          </template>
        </dl>
      </section>

      <p
        v-if="test.stateResult.value && !test.stateGroups.value.length"
        class="test-note"
        data-testid="test-state-blank"
      >
        Nothing had been written to the state at that step.
      </p>
    </template>
  </div>
</template>

<style scoped>
.test-tab { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.test-note { margin: 0; color: var(--text-40); font: 400 var(--fs-12)/1.5 var(--font-body); }

.test-step { display: flex; gap: 8px; align-items: center; min-width: 0; }
.test-step-label {
  color: var(--text-40);
  font: 600 var(--fs-11)/1.3 var(--font-mono);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.test-step-slider { flex: 1 1 auto; min-width: 0; }
.test-step-count { color: var(--text-muted); font: 500 var(--fs-11)/1.4 var(--font-mono); flex: none; }

.test-state-group { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.test-state-title {
  margin: 0;
  color: var(--text-40);
  font: 600 var(--fs-11)/1.3 var(--font-mono);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.test-state-list {
  display: grid;
  grid-template-columns: minmax(80px, max-content) minmax(0, 1fr);
  gap: 2px 10px;
  margin: 0;
}
.test-state-list dt { color: var(--text-muted); font: 500 var(--fs-11)/1.5 var(--font-mono); }
.test-state-list dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--text-body);
  font: 400 var(--fs-12)/1.5 var(--font-body);
}
</style>
