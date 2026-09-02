<script setup lang="ts">
import { computed } from 'vue'
import { ArchiveRestore, Clock3, CornerUpLeft, Eye, Loader, Lock, TriangleAlert, X } from 'lucide-vue-next'
import type { BuilderVersionRow } from '../../types/builder'

/**
 * Every stored version of the open graph, and the two things an author can do
 * with one that is not head: look at it, and make it head again.
 *
 * DOCKED, in a grid row under `DocumentBar`, never a popover over the canvas
 * (R15). The list is short and the decision it supports - "is v3 the one I
 * want back?" - is made while looking at v3 ON the canvas, so the browser has
 * to sit beside the graph rather than on top of it.
 *
 * PRESENTATIONAL, like the bar above it. The rows arrive as a prop in the
 * server's own order - newest first, which is what `GET .../versions` answers -
 * and nothing here re-sorts them: a client that sorted would hide a server
 * that stopped, and `e2e/builder.spec.ts` asserts the first row IS the newest
 * precisely so that contract is checked end to end. `view`, `head` and
 * `restore` leave as events; `BuilderView` owns the persistence calls, because
 * a restore is a compare-and-set save and the save loop lives in one place.
 *
 * WHAT "READ-ONLY" MEANS HERE. Viewing v3 of v7 loads v3's document into the
 * ordinary store with the history cleared, and `BuilderView` refuses every
 * write path while `version !== headVersion`. There is no second document
 * model and no diff view: the version on screen is the version, drawn by the
 * same canvas, which is the only way "what would I get back?" is answered
 * honestly. Restore then commits it as the next head through the normal save -
 * one undo step, one new version, never a rewrite of history (plan 15 D3).
 */

const props = withDefaults(
  defineProps<{
    versions: readonly BuilderVersionRow[]
    /** The version on the canvas. 0 until the first save. */
    version: number
    headVersion: number
    loading: boolean
    /** Why the list could not be read, as a sentence. `''` when it could. */
    problem: string
    /** True while Restore's save is in flight, so it cannot be pressed twice. */
    restoring: boolean
    /** Null for an unsaved draft, which has no versions to list. */
    documentId: string | null
    /**
     * Why no version may be opened right now, as a sentence, or `''`.
     *
     * Opening a stored version LOADS it - history cleared, canvas replaced -
     * so while the canvas is ahead of the store (dirty, saving, or under a
     * conflict) the rows are disabled and this sentence says why, rather than
     * a click quietly discarding the last 2.5 seconds of work.
     */
    blocked?: string
  }>(),
  { blocked: '' },
)

const emit = defineEmits<{
  /** Open this stored version on the canvas, read-only. Head opens normally. */
  view: [version: number]
  /** Back to head. */
  head: []
  /** Commit the version on screen as the next head. */
  restore: []
  close: []
}>()

const viewing = computed(() => props.headVersion > 0 && props.version !== props.headVersion)

/** `2026-09-02T10:14:00Z` -> `2 Sep, 10:14`. Undated rows show the raw value. */
function when(iso: string): string {
  const at = Date.parse(iso)
  if (!Number.isFinite(at)) return iso
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(at)
}

/** `1234` -> `1.2 KB`. Bytes below a kilobyte stay as bytes. */
function weight(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return ''
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}
</script>

<template>
  <section
    id="version-browser"
    class="version-browser"
    aria-labelledby="version-browser-title"
    data-testid="version-browser"
  >
    <header class="version-head">
      <div>
        <span class="version-kicker">VERSIONS</span>
        <h2 id="version-browser-title">
          {{ documentId ? `${versions.length} stored` : 'Nothing stored yet' }}
        </h2>
      </div>
      <button
        class="icon-button"
        type="button"
        aria-label="Close the version browser"
        title="Close"
        @click="emit('close')"
      >
        <X :size="14" aria-hidden="true" />
      </button>
    </header>

    <!--
      The banner is the whole read-only state, said once, with both ways out
      beside it. `role="status"` so a screen reader hears the mode change
      without the canvas having to announce anything itself.
    -->
    <div v-if="viewing" class="version-viewing" role="status" data-testid="version-viewing">
      <Eye :size="14" aria-hidden="true" />
      <span class="version-viewing-copy">
        Viewing <strong>v{{ version }}</strong> of v{{ headVersion }} — read-only. Restore it to make
        it the next version, or go back to v{{ headVersion }}.
      </span>
      <button
        class="button button-quiet"
        type="button"
        :disabled="restoring"
        data-testid="version-back"
        @click="emit('head')"
      >
        <CornerUpLeft :size="14" aria-hidden="true" />
        Back to v{{ headVersion }}
      </button>
      <button
        class="button button-primary"
        type="button"
        :disabled="restoring || blocked !== ''"
        data-testid="version-restore"
        @click="emit('restore')"
      >
        <ArchiveRestore :size="14" aria-hidden="true" />
        {{ restoring ? 'Restoring…' : `Restore v${version}` }}
      </button>
    </div>

    <p v-if="blocked" class="version-empty is-blocked" role="status" data-testid="version-blocked">
      <Lock :size="14" aria-hidden="true" /> {{ blocked }}
    </p>

    <p v-if="!documentId" class="version-empty">
      Save this graph and every version it is stored at will be listed here.
    </p>
    <p v-else-if="loading" class="version-empty" role="status">
      <Loader :size="14" aria-hidden="true" /> Reading the stored versions…
    </p>
    <p v-else-if="problem" class="version-empty is-problem" role="alert">
      <TriangleAlert :size="14" aria-hidden="true" /> {{ problem }}
    </p>
    <p v-else-if="versions.length === 0" class="version-empty">No versions have been stored.</p>

    <ol v-else class="version-list" aria-label="Stored versions">
      <li v-for="row in versions" :key="row.version">
        <button
          class="version-row"
          :class="{ 'is-current': row.version === version, 'is-head': row.version === headVersion }"
          type="button"
          :disabled="blocked !== ''"
          :aria-current="row.version === version ? 'true' : undefined"
          :title="row.version === headVersion ? 'Head — the newest stored version' : `Open v${row.version} read-only`"
          :data-testid="`version-row-${row.version}`"
          @click="emit('view', row.version)"
        >
          <span class="version-number">v{{ row.version }}</span>
          <span class="version-tags">
            <span v-if="row.version === headVersion" class="version-pill is-headpill">head</span>
            <span class="version-pill" :class="`is-${row.status}`">{{ row.status }}</span>
          </span>
          <span class="version-when"><Clock3 :size="11" aria-hidden="true" />{{ when(row.created_at) }}</span>
          <span class="version-bytes">{{ weight(row.bytes) }}</span>
        </button>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.version-browser {
  display: grid;
  gap: 8px;
  padding: 8px 40px 10px;
  background: var(--surface-panel);
  border-bottom: 1px solid var(--border-default);
}

.version-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.version-kicker { color: var(--accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); letter-spacing: 0.04em; }
.version-head h2 { margin: 3px 0 0; font-size: var(--fs-13); }

.version-viewing {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  color: var(--warn-text);
  font-size: var(--fs-12);
  line-height: 1.45;
  background: var(--warn-bg);
  border: 1px solid var(--warn-border);
  border-radius: var(--r-lg);
}
.version-viewing-copy { flex: 1 1 260px; min-width: 0; color: var(--text-body); }
.version-viewing strong { color: var(--text-title); }
.version-viewing .button { min-height: 30px; padding: 0 10px; font-size: var(--fs-12); }

.version-empty {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 0;
  color: var(--text-muted);
  font-size: var(--fs-12);
}
.version-empty.is-problem { color: var(--err-text); }
.version-empty.is-blocked { color: var(--warn-text); }
.version-row:disabled { cursor: not-allowed; opacity: 0.55; }

/* A bounded list rather than a growing one: a graph saved every 2.5s for an
   afternoon has hundreds of versions, and a dock that took the whole canvas
   to list them would be the overlay R15 forbids by another route. */
.version-list {
  display: grid;
  gap: 3px;
  max-height: 168px;
  overflow: auto;
  padding: 0;
  margin: 0;
  list-style: none;
}

.version-row {
  display: grid;
  grid-template-columns: 44px auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 5px 8px;
  color: var(--text-body);
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: background var(--motion-fast) ease, border-color var(--motion-fast) ease;
}
.version-row:hover { background: var(--surface-raised); border-color: var(--border-default); }
.version-row:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.version-row.is-current { background: color-mix(in srgb, var(--accent-cyan) 10%, transparent); border-color: color-mix(in srgb, var(--accent-cyan) 42%, transparent); }

.version-number { color: var(--text-title); font: 600 var(--fs-12)/1 var(--font-mono); font-variant-numeric: tabular-nums; }
.version-tags { display: inline-flex; gap: 4px; }
.version-pill { padding: 2px 6px; font: 700 10px/1.4 var(--font-mono); text-transform: uppercase; border-radius: var(--r-pill); }
.version-pill.is-draft { color: var(--text-muted); background: var(--surface-raised); }
.version-pill.is-published { color: var(--accent-mint); background: color-mix(in srgb, var(--accent-mint) 14%, transparent); }
.version-pill.is-headpill { color: var(--accent-cyan); background: color-mix(in srgb, var(--accent-cyan) 14%, transparent); }
.version-when { display: inline-flex; gap: 4px; align-items: center; color: var(--text-40); font: 500 10px/1 var(--font-mono); }
.version-bytes { color: var(--text-40); font: 500 10px/1 var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
