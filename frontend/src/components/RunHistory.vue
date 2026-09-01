<script setup lang="ts">
/**
 * "Your runs" - the caller's own history, newest first.
 *
 * The API applies the ownership filter in SQL, so nothing here decides who may
 * see what; this component only renders what it was given. That separation is
 * the point: a bug in this file can make the list wrong, but it cannot make it
 * somebody else's.
 */
import { computed, ref, watch } from 'vue'
import { Download, History, LoaderCircle, RefreshCw } from 'lucide-vue-next'
import type { RunHistoryEntry } from '../types/studio'
import { studioApi } from '../services/studioApi'

const props = defineProps<{
  /**
   * Changes whenever the live run's identity or status does, which is the
   * signal to refetch. A string rather than a watcher on the run itself so
   * this component needs to know nothing about how a run progresses - only
   * that something worth re-reading has happened.
   */
  reloadKey: string
  /** False on a deployment with no auth server, where there is no "yours". */
  enabled: boolean
}>()

/*
 * The row action is DOWNLOAD, not "open this run again", and the choice is
 * forced by two existing decisions rather than by taste.
 *
 * `restoreRun` in useValidatorRun is refresh recovery for a run still in
 * flight: it explicitly drops a run in a terminal status so the next load does
 * not re-open a stale result forever. And re-subscribing would need the
 * `session_id`, which this endpoint deliberately does not return because run id
 * plus session id is what opens a run's live socket.
 *
 * `GET /api/runs/{id}/logs` needs neither: the bearer token and the run id are
 * enough, and it hands back every frame the run produced. So the row offers the
 * thing that actually works completely.
 */
const downloading = ref<string | null>(null)

async function download(runId: string): Promise<void> {
  downloading.value = runId
  try {
    await studioApi.downloadLogs(runId, 'ndjson')
  } catch {
    // Deliberately quiet. A failed download of a historical log must not
    // occupy the error banner the live run needs.
  } finally {
    downloading.value = null
  }
}

const runs = ref<RunHistoryEntry[]>([])
const loading = ref(false)
const loaded = ref(false)

/**
 * Why the list could not be loaded, or '' when it was. Separate from `runs`
 * because an empty array is a legitimate answer and a failure is not - saying
 * "Nothing yet" over a request that 401'd is how a completed run disappeared
 * from this panel in production.
 */
const loadError = ref('')

async function refresh(): Promise<void> {
  if (!props.enabled) return
  loading.value = true
  loadError.value = ''
  try {
    runs.value = await studioApi.listRuns()
  } catch (error) {
    // Keep whatever was already on screen: a refresh that fails should not
    // erase a list the operator could read a moment ago.
    loadError.value = error instanceof Error ? error.message : 'Your runs could not be loaded.'
  } finally {
    loading.value = false
    loaded.value = true
  }
}

watch(() => [props.reloadKey, props.enabled] as const, () => void refresh(), {
  immediate: true,
})

/**
 * Dates are formatted in the VIEWER's locale and timezone, not the server's.
 * The API sends UTC ISO-8601; a run launched at 22:00 in Singapore must not
 * read as the previous day because the string was rendered verbatim.
 */
const formatter = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

function when(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '' : formatter.format(parsed)
}

function money(value: number): string {
  if (!value) return ''
  // Below a tenth of a cent "$0.00" is a lie of rounding; say "<$0.01".
  return value < 0.01 ? '<$0.01' : `$${value.toFixed(2)}`
}

const isEmpty = computed(() => loaded.value && !loading.value && runs.value.length === 0)
</script>

<template>
  <section v-if="enabled" class="run-history" aria-labelledby="run-history-heading">
    <header class="run-history-head">
      <h2 id="run-history-heading">
        <History :size="14" aria-hidden="true" />
        Your runs
      </h2>
      <button
        class="run-history-refresh"
        type="button"
        :disabled="loading"
        title="Refresh"
        @click="refresh"
      >
        <LoaderCircle v-if="loading" class="spin" :size="13" aria-hidden="true" />
        <RefreshCw v-else :size="13" aria-hidden="true" />
        <span class="sr-only">Refresh your runs</span>
      </button>
    </header>

    <p v-if="loadError" class="run-history-empty run-history-error" role="alert">
      Your runs could not be loaded - this is not the same as having none.
      <button class="run-history-retry" type="button" @click="refresh">Try again</button>
    </p>

    <p v-else-if="isEmpty" class="run-history-empty">
      Nothing yet. Launch a validation and it will appear here.
    </p>

    <ul v-else class="run-history-list">
      <li v-for="run in runs" :key="run.run_id" class="run-history-item">
        <div class="run-history-body">
          <span class="run-history-label">{{ run.label || run.run_id.slice(0, 8) }}</span>
          <span class="run-history-meta">
            <span class="run-history-status" :class="`is-${run.status}`">{{ run.status }}</span>
            <span>{{ when(run.created_at) }}</span>
            <span v-if="money(run.cost_usd)">{{ money(run.cost_usd) }}</span>
          </span>
        </div>
        <button
          class="run-history-download"
          type="button"
          :disabled="downloading === run.run_id"
          :title="`Download the log for this run`"
          @click="download(run.run_id)"
        >
          <LoaderCircle v-if="downloading === run.run_id" class="spin" :size="13" aria-hidden="true" />
          <Download v-else :size="13" aria-hidden="true" />
          <span class="sr-only">Download the log for the run from {{ when(run.created_at) }}</span>
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.run-history {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--r-2xl);
}

.run-history-head { display: flex; align-items: center; justify-content: space-between; }

.run-history-head h2 {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  color: var(--accent-cyan);
  font: 700 var(--fs-11)/1 var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.run-history-refresh {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  color: var(--text-40);
  background: transparent;
  border: 0;
  border-radius: var(--r-sm);
  cursor: pointer;
}

.run-history-refresh:hover:not(:disabled) { color: var(--text-body); background: var(--surface-raised); }
.run-history-refresh:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

.run-history-empty { margin: 0; color: var(--text-40); font: 400 var(--fs-12)/1.5 var(--font-body); }
/* Warn, not muted: a failed load must not read like an ordinary empty list. */
.run-history-error { color: var(--warn-text); }
.run-history-retry { margin-left: 6px; padding: 0; color: inherit; font: inherit; text-decoration: underline; background: none; border: 0; cursor: pointer; }

.run-history-list { display: flex; flex-direction: column; gap: 4px; margin: 0; padding: 0; list-style: none; }

.run-history-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-md);
}

.run-history-item:hover { background: var(--surface-raised); border-color: var(--border-default); }

.run-history-body { display: flex; flex: 1; flex-direction: column; gap: 4px; min-width: 0; }

.run-history-download {
  display: grid;
  flex: none;
  width: 24px;
  height: 24px;
  place-items: center;
  color: var(--text-40);
  background: transparent;
  border: 0;
  border-radius: var(--r-sm);
  cursor: pointer;
}

.run-history-download:hover:not(:disabled) { color: var(--accent-cyan); background: var(--surface-well); }
.run-history-download:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

.run-history-label {
  display: -webkit-box;
  overflow: hidden;
  color: var(--text-body);
  font: 500 var(--fs-12)/1.4 var(--font-body);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.run-history-meta {
  display: flex;
  gap: 8px;
  color: var(--text-40);
  font: 500 10px/1 var(--font-mono);
  text-transform: uppercase;
}

.run-history-status.is-completed { color: var(--accent-mint); }
.run-history-status.is-failed { color: var(--err-text); }
.run-history-status.is-waiting { color: var(--warn-text); }
.run-history-status.is-running { color: var(--accent-cyan); }

.spin { animation: history-spin 900ms linear infinite; }

@media (prefers-reduced-motion: reduce) {
  .spin { animation: none; }
}

@keyframes history-spin {
  to { transform: rotate(360deg); }
}
</style>
