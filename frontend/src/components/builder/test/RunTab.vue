<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Play, Square } from 'lucide-vue-next'
import RunLog from './RunLog.vue'
import TestInputPicker from './TestInputPicker.vue'
import { renderMarkdown } from '../../../utils/markdown'
import { PANEL_DEFAULT_PX, PANEL_MIN_PX, type FlowTest } from '../../../composables/useFlowTest'

/**
 * The Try it tab: pick an input, press Try it, watch it on the canvas, read
 * the body.
 *
 * The node STATES are not drawn here. They are drawn on the builder canvas,
 * through `[data-mode='run']` (13 D2, `builder.css`) - which is the whole reason
 * the panel is docked rather than modal: the graph the author is testing stays
 * on screen while it runs, and this tab carries only what the graph cannot show.
 */

const props = defineProps<{ test: FlowTest; labels: Record<string, string> }>()

const run = props.test.run
const body = computed(() => run.report.value?.markdown_body ?? '')
const rendered = computed(() => (body.value ? renderMarkdown(body.value) : ''))

/**
 * The gate outcome that means "carry on", read off the gate rather than typed.
 *
 * The SERVER decides how many options a gate has and in what order, and the
 * first is the forward one by construction - `GateCard` already renders the
 * list in the order it arrives for that reason. Hard-coding `approve` would be
 * this panel's own opinion about an author's gate, and a builder gate's
 * outcomes are the author's to name.
 */
const forwardOption = computed(() => run.pendingGate.value?.options[0]?.id ?? 'approve')

/* ── the result, which the author pressed the button FOR (item 6, X2) ──────
 *
 * AUDIT-R2 H4, measured: at the panel's default height the reader saw the
 * input, the saved-input row and the button, and the result was BELOW THE
 * FOLD - the one thing the run was for was the one thing not on screen, and
 * finding it meant knowing the 6px drag handle existed. This is the same
 * "open on the first body" behaviour `ReportPanel.vue` already implements on
 * the console, in the panel's own terms.
 *
 * THREE THINGS, AND EACH ONE IS BOUNDED:
 *
 *   grow  ONCE, and only from the FLOOR. `PANEL_MIN_PX` -> `PANEL_DEFAULT_PX`,
 *         so a reader who dragged the panel anywhere above the minimum keeps
 *         the height they chose - a panel that resized itself under somebody
 *         who had just sized it is worse than one that never moved. Read off
 *         `height`, not `panelHeight`: the latter answers the COLLAPSED strip
 *         while the panel is shut, which would look like the floor and is not.
 *   scroll `block: 'nearest'`, which moves the panel's own scroller and
 *         nothing else on the page - the canvas the author is watching must
 *         not jump. Guarded, because jsdom does not implement
 *         `scrollIntoView` and a unit mount would throw on a real behaviour.
 *   once  keyed on the run id, so a second Try it re-arms it and a re-render
 *         mid-run does not scroll the reader away from the log.
 */
const resultEl = ref<HTMLElement | null>(null)
const revealedFor = ref<string | null>(null)
const TERMINAL = ['completed', 'cancelled', 'error'] as const

watch(
  () => [run.runId.value, run.status.value, body.value] as const,
  async ([id, status, text]) => {
    if (!id || !text) return
    if (!(TERMINAL as readonly string[]).includes(status)) return
    if (revealedFor.value === id) return
    revealedFor.value = id
    if (props.test.height.value <= PANEL_MIN_PX) props.test.setHeight(PANEL_DEFAULT_PX)
    await nextTick()
    const el = resultEl.value
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' })
  },
)

/**
 * The exact bytes, behind a disclosure - the pattern the trace rows already use.
 *
 * The renderer is escape-first (`utils/markdown.ts`) and degrades anything it
 * does not recognise to an escaped paragraph, which is the right default: a
 * real agent's last output is prose. It is also why the raw view has to exist -
 * a compiled flow whose last node returns JSON renders as one long paragraph,
 * and the author who needs the keys needs the string.
 */
const showRaw = ref(false)
</script>

<template>
  <div class="test-tab" data-testid="test-body-run">
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

    <div class="test-actions">
      <button
        type="button"
        class="test-run"
        data-testid="test-run"
        :disabled="!test.canRun.value"
        @click="void test.startRun()"
      >
        <Play :size="13" aria-hidden="true" />
        {{ run.launching.value ? 'Starting…' : 'Try it' }}
      </button>
      <button
        v-if="run.isActive.value"
        type="button"
        class="test-cancel"
        data-testid="test-cancel"
        @click="void run.cancel()"
      >
        <Square :size="13" aria-hidden="true" />
        Cancel
      </button>
      <span class="test-status" data-testid="test-run-status">{{ run.status.value }}</span>
      <span v-if="run.usage.costUsd > 0" class="test-cost" data-testid="test-run-cost">
        ${{ run.usage.costUsd.toFixed(4) }}
      </span>
    </div>

    <p v-if="test.runBlockedReason.value" class="test-note" data-testid="test-run-blocked">
      {{ test.runBlockedReason.value }}
    </p>

    <!--
      A gate parks the run, and the panel offers the FORWARD answer only.

      The console owns the gate card, with the editable fields and the revise
      route; duplicating that here would be a second surface over a
      compare-and-set that accepts exactly one reply, and a second place to get
      the fields/derived split wrong. What a test run needs is different and
      smaller: an author checking that their graph moves needs to say "carry
      on", and anything they want to CHANGE is a change to the document they are
      looking at, not to one run's inputs. The other options are named in the
      sentence, so nobody has to guess where they went.
    -->
    <div v-if="run.pendingGate.value" class="test-gate" data-testid="test-run-gate">
      <p class="test-gate-copy">
        <strong>{{ run.pendingGate.value.title }}</strong>
        — {{ run.pendingGate.value.summary }}
      </p>
      <button
        type="button"
        class="test-run"
        data-testid="test-gate-approve"
        :disabled="run.gateSubmitting.value"
        @click="void run.submitGate(forwardOption)"
      >
        Approve and continue
      </button>
      <span class="test-note">Editing a reply, or sending it back, is the run console.</span>
    </div>

    <RunLog
      :entries="run.chatEntries.value"
      :usage="run.nodeUsage"
      :states="run.nodeStates"
      :labels="labels"
    />

    <section v-if="rendered" ref="resultEl" class="test-result" data-testid="test-run-result">
      <header class="test-result-head">
        <h3 class="test-result-title">Result</h3>
        <button
          type="button"
          class="test-result-raw-toggle"
          data-testid="test-result-raw-toggle"
          :aria-expanded="showRaw"
          aria-controls="test-result-raw"
          @click="showRaw = !showRaw"
        >{{ showRaw ? 'Hide raw' : 'Show raw' }}</button>
      </header>
      <!-- eslint-disable-next-line vue/no-v-html -- `renderMarkdown` escapes first; see utils/markdown.ts -->
      <div v-show="!showRaw" class="markdown-body" v-html="rendered" />
      <pre
        v-show="showRaw"
        id="test-result-raw"
        class="test-result-raw"
        data-testid="test-run-result-raw"
      >{{ body }}</pre>
    </section>
  </div>
</template>

<style scoped>
.test-tab { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.test-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.test-run,
.test-cancel {
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
.test-run:hover:not(:disabled) { border-color: var(--accent-cyan); }
.test-run:disabled { opacity: 0.45; cursor: default; }
.test-cancel:hover { border-color: var(--err-border); }
.test-status { color: var(--text-muted); font: 500 var(--fs-11)/1.4 var(--font-mono); }
.test-cost { color: var(--accent-mint); font: 500 var(--fs-11)/1.4 var(--font-mono); }
.test-note { margin: 0; color: var(--text-muted); font: 400 var(--fs-12)/1.5 var(--font-body); }

.test-gate {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid var(--warn-border);
  border-radius: var(--r-sm);
  background: var(--warn-bg);
}
.test-gate-copy { flex: 1 1 200px; margin: 0; min-width: 0; color: var(--text-title); font: 400 var(--fs-12)/1.5 var(--font-body); }

.test-result { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.test-result-head { display: flex; gap: 8px; align-items: baseline; justify-content: space-between; }
.test-result-raw-toggle {
  flex: none;
  padding: 2px 7px;
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--text-muted);
  font: 500 var(--fs-11)/1.4 var(--font-body);
  cursor: pointer;
}
.test-result-raw-toggle:hover { border-color: var(--border-hover); color: var(--text-body); }
.test-result-raw-toggle:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
/* `pre-wrap`, not `pre`: the raw body is one line of JSON often enough that a
   horizontal scrollbar inside a 260px dock would be the whole reading
   experience. `anywhere` because a URL in it has no break opportunity. */
.test-result-raw {
  margin: 0;
  padding: 8px 10px;
  min-width: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  color: var(--text-body);
  font: 400 var(--fs-11)/1.5 var(--font-mono);
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
}
.test-result-title {
  margin: 0;
  color: var(--text-40);
  font: 600 var(--fs-11)/1.3 var(--font-mono);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
</style>
