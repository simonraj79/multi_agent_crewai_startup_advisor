<script setup lang="ts">
import { computed, ref } from 'vue'
import { Copy, RefreshCw } from 'lucide-vue-next'
import type { FlowTest } from '../../composables/useFlowTest'

/**
 * The Code tab: what this canvas compiled to, as something a person reads.
 *
 * TWO RENDERINGS SIDE BY SIDE (09 D8, C7): the YAML is what runs -
 * `Flow.from_declaration` is handed exactly that - and the Python is what it
 * means, naming the constructors the entrypoints will build. Neither is
 * generated here: both come off `GET /workflows/{id}/compiled`, because a
 * second renderer in TypeScript would be wrong the first time the compiler
 * changed, and being wrong about what runs is the one thing this tab cannot be.
 *
 * NO SECRET REACHES EITHER, and the mechanism is on the server: the route hands
 * `render_preview` a LABELLING function rather than the vault, so
 * `<credential: My OpenRouter key>` is a label the renderer could not have
 * turned into a key even by accident. This component renders text it is given
 * and holds no opinion about it.
 *
 * IT IS THE ONE TAB A DRAFT CAN USE. The other three resolve a run mode against
 * `BUILDER_WORKFLOWS`, which only a publish writes; this reads the document
 * store, so it answers for any saved version.
 */

const props = defineProps<{ test: FlowTest }>()

const copied = ref<'yaml' | 'python' | null>(null)
const preview = computed(() => props.test.compiled.value)

async function copy(which: 'yaml' | 'python'): Promise<void> {
  const text = which === 'yaml' ? preview.value?.yaml : preview.value?.python
  if (!text) return
  try {
    await navigator.clipboard?.writeText(text)
    copied.value = which
  } catch {
    // A clipboard a browser refuses is not an error worth a banner: the text is
    // on screen and selectable, which is the fallback every user already knows.
    copied.value = null
  }
}
</script>

<template>
  <div class="test-tab" data-testid="test-tab-code">
    <div class="test-actions">
      <button
        type="button"
        class="test-run"
        data-testid="code-refresh"
        :disabled="test.compiledPending.value"
        @click="void test.loadCompiled()"
      >
        <RefreshCw :size="13" aria-hidden="true" />
        {{ test.compiledPending.value ? 'Compiling…' : 'Recompile' }}
      </button>
      <span v-if="preview" class="test-status" data-testid="code-version">
        v{{ preview.version }}
      </span>
    </div>

    <ul
      v-if="test.compiledProblems.value.length"
      class="code-problems"
      role="alert"
      data-testid="code-problems"
    >
      <li v-for="problem in test.compiledProblems.value" :key="`${problem.code}-${problem.node_id ?? ''}`">
        <code>{{ problem.code }}</code>
        <span>{{ problem.message }}</span>
      </li>
    </ul>

    <div v-if="preview" class="code-panes">
      <section class="code-pane">
        <header class="code-head">
          <h3 class="code-title">YAML — what runs</h3>
          <button type="button" class="code-copy" data-testid="code-copy-yaml" @click="void copy('yaml')">
            <Copy :size="12" aria-hidden="true" />
            {{ copied === 'yaml' ? 'Copied' : 'Copy' }}
          </button>
        </header>
        <pre class="code-body" data-testid="code-yaml">{{ preview.yaml }}</pre>
      </section>

      <section class="code-pane">
        <header class="code-head">
          <h3 class="code-title">Python — what it means</h3>
          <button type="button" class="code-copy" data-testid="code-copy-python" @click="void copy('python')">
            <Copy :size="12" aria-hidden="true" />
            {{ copied === 'python' ? 'Copied' : 'Copy' }}
          </button>
        </header>
        <pre class="code-body" data-testid="code-python">{{ preview.python }}</pre>
      </section>
    </div>

    <p v-else-if="!test.compiledPending.value" class="test-note" data-testid="code-empty">
      Save this graph, and what it compiles to appears here.
    </p>
  </div>
</template>

<style scoped>
.test-tab { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.test-actions { display: flex; gap: 8px; align-items: center; }
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
.test-note { margin: 0; color: var(--text-40); font: 400 var(--fs-12)/1.5 var(--font-body); }

/* Two panes on a wide dock, one column when the dock is narrow. `minmax(0,1fr)`
   rather than `1fr`, because a grid item's automatic minimum size is its
   content and a long compiled line would otherwise widen the whole panel
   instead of scrolling inside its own pane. */
.code-panes {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr));
  gap: 10px;
  min-width: 0;
}
.code-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  background: var(--surface-well);
}
.code-head {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  padding: 5px 9px;
  border-bottom: 1px solid var(--border-default);
}
.code-title {
  margin: 0;
  color: var(--text-40);
  font: 600 var(--fs-11)/1.3 var(--font-mono);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.code-copy {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  padding: 2px 7px;
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--text-muted);
  font: 500 var(--fs-11)/1.4 var(--font-body);
  cursor: pointer;
}
.code-copy:hover { border-color: var(--border-hover); color: var(--text-body); }
.code-body {
  margin: 0;
  padding: 8px 9px;
  max-height: 340px;
  overflow: auto;
  color: var(--text-body);
  font: 400 var(--fs-11)/1.6 var(--font-mono);
  white-space: pre;
}

.code-problems { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 5px; }
.code-problems li { display: flex; gap: 8px; min-width: 0; }
.code-problems code { flex: none; color: var(--text-40); font: 500 var(--fs-11)/1.5 var(--font-mono); }
.code-problems li span { min-width: 0; overflow-wrap: anywhere; color: var(--err-text); font: 400 var(--fs-12)/1.5 var(--font-body); }
</style>
