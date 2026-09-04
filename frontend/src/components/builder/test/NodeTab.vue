<script setup lang="ts">
import { Play } from 'lucide-vue-next'
import RunLog from './RunLog.vue'
import TestInputPicker from './TestInputPicker.vue'
import type { FlowTest } from '../../../composables/useFlowTest'

/**
 * The Node tab: one node for real, everything above it replayed (D4).
 *
 * `node_test` is a DERIVED PLAN and not a special runner - every ancestor
 * compiles to `runtime:replay_output` seeded from the saved input's mocks, and
 * every descendant is absent. Two consequences show on this tab:
 *
 * * only FLOW-kind nodes are offered. An attachment has no output, so there is
 *   nothing for a replay to seed and nothing for the tab to render.
 * * a node whose mocks are incomplete is refused HERE, before a run row exists,
 *   naming the missing keys. The server's 422 says the same thing and is the
 *   refusal that binds; this one is the one an author can act on without
 *   spending a request.
 */

const props = defineProps<{ test: FlowTest; labels: Record<string, string> }>()
const run = props.test.run
</script>

<template>
  <div class="test-tab" data-testid="test-body-node">
    <label class="test-node-pick">
      <span class="test-input-legend">Node</span>
      <select
        class="test-node-select"
        data-testid="test-node-select"
        :value="test.nodeUnderTest.value ?? ''"
        aria-label="The node to test on its own"
        @change="test.nodeUnderTest.value = ($event.target as HTMLSelectElement).value || null"
      >
        <option value="">—</option>
        <option v-for="node in test.testableNodes.value" :key="node.id" :value="node.id">
          {{ node.label }} · {{ node.kind }}
        </option>
      </select>
    </label>

    <TestInputPicker
      :inputs="test.testInputs.value"
      :selected-id="test.selectedInputId.value"
      :value="test.inputValue.value"
      :field="test.inputField.value"
      :last-run-id="run.runId.value"
      :saving="test.savingInput.value"
      :disabled="run.isActive.value"
      @update:value="test.inputValue.value = $event"
      @select="test.select($event)"
      @save="(label, fromLastRun) => void test.saveTestInput(label, { fromLastRun })"
      @delete="(id) => void test.removeTestInput(id)"
    />

    <p
      v-if="test.nodeUnderTest.value && test.missingMocks.value.length"
      class="test-missing"
      role="alert"
      data-testid="test-node-missing"
    >
      No mock for
      <template v-for="(id, index) in test.missingMocks.value" :key="id">
        <code>out__{{ id }}</code><span v-if="index < test.missingMocks.value.length - 1">, </span>
      </template>
      — save a test input carrying them, or take them from a finished run.
    </p>

    <div class="test-actions">
      <button
        type="button"
        class="test-run"
        data-testid="test-node-run"
        :disabled="!test.canRunNode.value || run.isActive.value"
        @click="void test.startNodeTest()"
      >
        <Play :size="13" aria-hidden="true" />
        Run this node
      </button>
      <span class="test-status" data-testid="test-node-status">{{ run.status.value }}</span>
    </div>

    <RunLog
      :entries="run.chatEntries.value"
      :usage="run.nodeUsage"
      :states="run.nodeStates"
      :labels="labels"
      :only-node="test.nodeUnderTest.value"
    />
  </div>
</template>

<style scoped>
.test-tab { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.test-node-pick { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.test-input-legend {
  color: var(--text-40);
  font: 600 var(--fs-11)/1.3 var(--font-mono);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.test-node-select {
  width: 100%;
  min-width: 0;
  padding: 5px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
  background: var(--surface-well);
  color: var(--text-body);
  font: 400 var(--fs-12)/1.4 var(--font-body);
}
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
.test-status { color: var(--text-muted); font: 500 var(--fs-11)/1.4 var(--font-mono); }
.test-missing {
  margin: 0;
  padding: 6px 9px;
  border: 1px solid var(--warn-border);
  border-radius: var(--r-sm);
  background: var(--warn-bg);
  color: var(--text-title);
  font: 400 var(--fs-12)/1.5 var(--font-body);
}
.test-missing code { font: 500 var(--fs-11)/1.5 var(--font-mono); }
</style>
