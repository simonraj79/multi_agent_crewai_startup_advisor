<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArchiveRestore, Clock3, CornerUpLeft, Eye, Loader, Lock, TriangleAlert, X } from 'lucide-vue-next'
import type { BuilderVersionRow } from '../../types/builder'
import { agoFrom, parseStamp } from '../../utils/storedTime'

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
    /** The clock the relative times read. Injected so a spec can hold it still. */
    clock?: () => number
  }>(),
  // A Function-typed prop's default IS the value, not a factory - Vue calls a
  // default as a factory only for Object and Array props. The first cut wrote
  // `() => () => Date.now()`, so `props.clock()` answered a FUNCTION, every
  // subtraction was NaN, and every row fell through to the dated form; the
  // specs passed because each handed in a stilled clock. Round 2's capture
  // caught it.
  { blocked: '', clock: () => Date.now() },
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

/*
 * WHAT A ROW SAYS, and why it says three things (round 2, D-15-3).
 *
 * Round 1 put two rows on screen that read "v2 HEAD DRAFT 3 Sept, 00:19" and
 * "v1 DRAFT 3 Sept, 00:19", differing by 0.2 KB in ten-pixel text at the far
 * right; choosing which to restore was guesswork. A row now carries a LABEL
 * (the name at that version and its node count, read off the stored row by
 * the server), its SOURCE (`created`, `saved`, `autosaved`, `restored from
 * v1`, `imported`, `duplicated`), and a RELATIVE time that keeps seconds under
 * a minute - "12 s ago" against "48 s ago" - with the full timestamp, seconds
 * included, in the title. Two autosaves from the same minute now differ in at
 * least one of the three.
 */

/** Ticks so "12 s ago" does not read "12 s ago" all afternoon. */
const now = ref(props.clock())
let ticker = 0
onMounted(() => {
  ticker = window.setInterval(() => {
    now.value = props.clock()
  }, 30_000)
})
onBeforeUnmount(() => window.clearInterval(ticker))

/*
 * `parseStamp`, `when` and the body of `ago` moved to `utils/storedTime.ts` in
 * round 3 (D-15-15), because the saved-graphs library needs the same answers
 * and a second copy of the naive-UTC rule is a second thing to get wrong. The
 * reasoning behind each lives there now; `agoFrom` falls back to
 * `formatStamp`, which is what `when` used to be.
 */

/** The full stamp, seconds included, for the title: `2 Sep 2026, 10:14:32`. */
function stamp(iso: string): string {
  const at = parseStamp(iso)
  if (!Number.isFinite(at)) return iso
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(at)
}

/** The shared rule, against this panel's own ticking clock. */
function ago(iso: string): string {
  return agoFrom(iso, now.value)
}

/** `Minimal gated agent · 5 nodes`; a nameless row still shows its count. */
function label(row: BuilderVersionRow): string {
  const parts: string[] = []
  if (row.name) parts.push(row.name)
  if (row.node_count !== null) parts.push(`${row.node_count} ${row.node_count === 1 ? 'node' : 'nodes'}`)
  return parts.join(' · ') || 'unreadable version'
}

/**
 * What changed between this row and the one below it - D-15-24.
 *
 * The rows differed only by `5 nodes`/`4 nodes` and `1.4 KB`/`1.3 KB` in the
 * far-right columns, so telling two candidates apart cost two clicks each and
 * did not scale. A delta answers the question the list is FOR - "what did this
 * version change?" - without opening anything.
 *
 * Computed here rather than served, because it is a property of the list's
 * ORDER and not of a row: the server answers newest first and nothing re-sorts
 * (see the class note), so row `i`'s predecessor is `i + 1`. A server field
 * would have to be recomputed on every insert.
 *
 * `null` for the oldest row, which has nothing to be a delta from, and for any
 * row whose counts could not be read - a version stored under a schema this
 * service no longer parses lists with whatever it can say, and "no change" is
 * not something it can say.
 */
function delta(index: number): string {
  const row = props.versions[index]
  const older = props.versions[index + 1]
  if (!row || !older) return ''
  const parts: string[] = []
  const moved = (now: number | null, before: number | null, noun: string): void => {
    if (now === null || before === null) return
    const change = now - before
    if (change === 0) return
    // A true minus sign, not a hyphen: these sit in tabular monospace beside
    // `+`, and the hyphen is visibly shorter at 11px.
    parts.push(`${change > 0 ? '+' : '\u2212'}${Math.abs(change)} ${noun}${Math.abs(change) === 1 ? '' : 's'}`)
  }
  moved(row.node_count, older.node_count, 'node')
  moved(row.edge_count, older.edge_count, 'edge')
  if (parts.length) return parts.join(', ')
  // Both counts readable and both equal: the graph's SHAPE is unchanged, which
  // is a real answer and a different one from "we cannot tell".
  if (row.node_count !== null && older.node_count !== null) return 'same shape'
  return ''
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
      <li v-for="(row, index) in versions" :key="row.version">
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
          <span class="version-label" :title="label(row)" data-testid="version-label">{{ label(row) }}</span>
          <span class="version-source" data-testid="version-source">{{ row.source }}</span>
          <!--
            The delta against the version below (D-15-24). Rendered even when
            empty so the column keeps its width and the rows stay aligned; a
            column that appears and disappears per row is a list that jitters
            as you read down it.
          -->
          <span
            class="version-delta"
            :class="{ 'is-same': delta(index) === 'same shape' }"
            :title="delta(index) ? `Against v${versions[index + 1]?.version}` : undefined"
            :data-testid="`version-delta-${row.version}`"
            >{{ delta(index) }}</span
          >
          <span class="version-when" :title="stamp(row.created_at)" data-testid="version-when">
            <Clock3 :size="11" aria-hidden="true" />
            <time :datetime="row.created_at">{{ ago(row.created_at) }}</time>
          </span>
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
  grid-template-columns: 44px auto minmax(0, 1fr) auto auto auto auto;
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
/* The label is the row's identity and takes the flexible column; the source
   and the time are facts beside it, in the type scale's smallest step rather
   than the 10px the critic measured - and the same tokens the chip uses. */
.version-label { min-width: 0; overflow: hidden; color: var(--text-body); font-size: var(--fs-12); text-overflow: ellipsis; white-space: nowrap; }
.version-source { color: var(--text-muted); font: 500 var(--fs-11)/1 var(--font-mono); white-space: nowrap; }
.version-when { display: inline-flex; gap: 4px; align-items: center; color: var(--text-40); font: 500 var(--fs-11)/1 var(--font-mono); white-space: nowrap; }
.version-bytes { color: var(--text-40); font: 500 var(--fs-11)/1 var(--font-mono); font-variant-numeric: tabular-nums; }
/* The delta reads as a fact about the graph rather than as a warning, so it
   takes the same quiet monospace as its neighbours - and `same shape` is
   quieter still, because "nothing moved" is the least interesting row in the
   list and should not compete with the ones that did. */
.version-delta {
  color: var(--text-muted);
  font: 500 var(--fs-11)/1 var(--font-mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.version-delta.is-same { color: var(--text-40); }
</style>
