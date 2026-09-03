<script setup lang="ts">
/**
 * Every problem the server reported, all at once, with the one it is about
 * always one click away.
 *
 * Spec section 6.3, sink three of three, and the direct answer to the
 * competition's second weakness. ChatDev surfaces a `ConfigError` as a toast:
 * one problem at a time, in the order the checker happened to hit them, gone
 * before you have found the node, and computed at save time so the sentence on
 * screen may be about a graph you have since changed. Every one of those four
 * is a decision this panel makes the other way.
 *
 * - ALL AT ONCE. Errors then warnings, never paginated, never one-at-a-time.
 *   An author fixing a graph needs to know how many are left.
 * - VERBATIM. `bounds.py` writes full sentences for the author, with the
 *   offending count in them. Nothing here rewords one.
 * - ANCHORED. A row is a button: clicking it emits `focus`, and `BuilderView`
 *   turns that into select + `fitView` + focus the mapped inspector field +
 *   the `problem-anchor` flash. The panel deliberately does not do any of that
 *   itself - it owns no canvas and no inspector, and a second component
 *   reaching into either is how two packages come to disagree about what is
 *   selected.
 * - HONEST ABOUT AGE. `phase === 'stale'` dims the list and says `checking`.
 *   A stale list presented as current is the failure the whole loop exists to
 *   avoid, and a panel that hid it would be the last place it could hide.
 *
 * F8 / Shift+F8 walk the same path a click does, through `next()` and
 * `previous()` on the exposed instance. They are NOT a keydown listener here:
 * `useBuilderHotkeys` owns the single window listener and exports its binding
 * table so `ShortcutSheet` renders it, and a second listener in this file would
 * be a binding that is bound and undocumented.
 */
import { computed, ref } from 'vue'
// A severity DOT, not an icon per row. Section 5.2's row anatomy is dot + code
// chip + sentence + anchor, and an icon in front of every message competes with
// the sentence for the eye at exactly the moment the sentence is the point.
import { Check, ChevronDown, ChevronUp, Lock } from 'lucide-vue-next'
import type { BuilderProblem } from '../../types/builder'
import type { ValidationPhase } from '../../composables/useBuilderValidation'

const props = withDefaults(
  defineProps<{
    /** The live `/validate` list, in the server's order. */
    problems: readonly BuilderProblem[]
    phase: ValidationPhase
    /**
     * A publish 422's problem list. Merged in rather than shown in a dialog,
     * because they are the same `Problem` objects with the same anchors and the
     * author fixes them the same way - the only difference worth rendering is
     * where they came from, which is the `from publish` tag.
     */
    publishProblems?: readonly BuilderProblem[]
    /** Node and edge labels for the anchor column. Ids are the fallback, never blank. */
    labels?: Readonly<Record<string, string>>
    /** Why validation is unreachable, as a sentence. Rendered only in that phase. */
    reason?: string
    /**
     * The older version on screen, or null while head is being edited
     * (D-15-17).
     *
     * The dock read `✓ Ready to publish` while the document bar two rows up
     * read `viewing v1 of v2 · read-only` and Publish sat disabled beside it -
     * three surfaces, two answers. "Ready to publish" is a claim about what
     * the author can DO next, and on a stored version the answer is nothing:
     * publishing it is refused, and the list below is a verdict on a document
     * that is not the one a publish would take.
     *
     * A number rather than a boolean so this panel says the same words as the
     * bar rather than a paraphrase of them.
     */
    viewingVersion?: number | null
  }>(),
  {
    publishProblems: () => [],
    labels: () => ({}),
    reason: '',
    viewingVersion: null,
  },
)

const emit = defineEmits<{ focus: [problem: BuilderProblem] }>()

const open = ref(true)
/** Which row the walk is on. -1 until something is clicked or F8 is pressed. */
const current = ref(-1)

interface ProblemRow {
  key: string
  problem: BuilderProblem
  /** True when this row arrived from a publish refusal rather than the live loop. */
  fromPublish: boolean
  /** The node or edge it is about, by label; `''` for a document-level problem. */
  anchor: string
}

const isError = (problem: BuilderProblem): boolean => problem.severity !== 'warning'

/** Identity for de-duplication: a problem IS its code, sentence and anchors. */
const identity = (problem: BuilderProblem): string =>
  `${problem.code}\u0000${problem.message}\u0000${problem.node_id ?? ''}\u0000${problem.edge_id ?? ''}`

/**
 * The live list, then whatever publish said that the live list did not already.
 *
 * A publish refusal recomputes the same checks, so most of its problems are
 * already on screen. Appending them unconditionally would double every row and
 * double the header count - two identical sentences read as two problems, and
 * an author would go looking for a second router with five branches.
 */
const merged = computed<ProblemRow[]>(() => {
  const seen = new Set<string>()
  const rows: ProblemRow[] = []
  for (const problem of props.problems) {
    seen.add(identity(problem))
    rows.push(rowFor(problem, false))
  }
  for (const problem of props.publishProblems) {
    if (seen.has(identity(problem))) continue
    seen.add(identity(problem))
    rows.push(rowFor(problem, true))
  }
  return rows
})

function rowFor(problem: BuilderProblem, fromPublish: boolean): ProblemRow {
  const anchorId = problem.node_id ?? problem.edge_id ?? ''
  return {
    // The index is not part of the key: the same code can legitimately appear
    // on two nodes, and `identity` already carries both anchors.
    key: `${fromPublish ? 'publish' : 'live'}\u0000${identity(problem)}`,
    problem,
    fromPublish,
    anchor: anchorId ? props.labels[anchorId] ?? anchorId : '',
  }
}

/** Graph-wide facts. Both anchors null, so there is nothing to click through to. */
const documentRows = computed(() =>
  sorted(merged.value.filter((row) => !row.problem.node_id && !row.problem.edge_id)),
)
const anchoredRows = computed(() =>
  sorted(merged.value.filter((row) => row.problem.node_id || row.problem.edge_id)),
)

/** Errors first, then warnings; server order preserved inside each group. */
function sorted(rows: ProblemRow[]): ProblemRow[] {
  return [...rows.filter((row) => isError(row.problem)), ...rows.filter((row) => !isError(row.problem))]
}

/** The walk order, and the order on screen: document group first, then anchored. */
const walkable = computed(() => [...documentRows.value, ...anchoredRows.value])

const errorCount = computed(() => merged.value.filter((row) => isError(row.problem)).length)
const warningCount = computed(() => merged.value.length - errorCount.value)

const stale = computed(() => props.phase === 'stale')

/**
 * Nobody has answered yet.
 *
 * This is NOT the same fact as "the answer came back empty", and rendering the
 * two the same way is the exact failure section 6.2 names: a verdict that is
 * not current presented as current. It was reachable for real - a document
 * whose fingerprint equals the one the loop mounted with (a blank canvas is
 * literally the seed document) never moved the watcher, so the panel read
 * `Ready to publish` over a graph the server refuses with `no-input-node`.
 * `phase` was already a prop; it was simply not consulted here.
 */
const unchecked = computed(() => props.phase === 'idle')
const unreachable = computed(() => props.phase === 'unreachable')

/** An older version is on screen, so nothing here is publishable (D-15-17). */
const readOnly = computed(() => props.viewingVersion !== null)

/**
 * True only when an empty list MEANS an empty list - and means it about a
 * document the author could actually publish. A stored version is neither.
 */
const clean = computed(
  () => !merged.value.length && !unchecked.value && !unreachable.value && !readOnly.value,
)

const headline = computed(() => {
  // Before every other case: read-only outranks the verdict, because it is a
  // fact about what can be done rather than about what was found. The words
  // are the document bar's own, so the two surfaces read as one.
  if (readOnly.value) return `viewing v${props.viewingVersion} · read-only`
  if (!merged.value.length && unchecked.value) return 'Not checked yet'
  if (!merged.value.length && unreachable.value) return 'Validation unavailable'
  if (!merged.value.length) return 'Ready to publish'
  const parts: string[] = []
  if (errorCount.value) parts.push(`${errorCount.value} ${errorCount.value === 1 ? 'error' : 'errors'}`)
  if (warningCount.value) {
    parts.push(`${warningCount.value} ${warningCount.value === 1 ? 'warning' : 'warnings'}`)
  }
  return parts.join(' · ')
})

function select(index: number): void {
  const row = walkable.value[index]
  if (!row) return
  current.value = index
  emit('focus', row.problem)
}

/**
 * Walk to the next problem, wrapping.
 *
 * Wrapping rather than stopping at the end because the list is short and the
 * key is a survey instrument: an author presses F8 until they recognise
 * something, and a key that silently stops working reads as a broken key.
 * Opens the panel first - walking to a row nobody can see is the same as doing
 * nothing.
 */
function next(): void {
  if (!walkable.value.length) return
  open.value = true
  select((current.value + 1) % walkable.value.length)
}

function previous(): void {
  if (!walkable.value.length) return
  open.value = true
  const size = walkable.value.length
  select((current.value <= 0 ? size : current.value) - 1)
}

defineExpose({ next, previous })
</script>

<template>
  <section class="problems-panel" :class="{ 'is-collapsed': !open, 'is-stale': stale }">
    <div class="problems-head">
      <button
        type="button"
        class="problems-toggle"
        :aria-expanded="open"
        aria-controls="problems-list"
        @click="open = !open"
      >
        <ChevronDown v-if="open" :size="14" aria-hidden="true" />
        <ChevronUp v-else :size="14" aria-hidden="true" />
        <span class="problems-kicker">PROBLEMS</span>
      </button>

      <span
        class="problems-headline"
        :class="{
          'is-clean': clean,
          'is-unchecked': (unchecked && !merged.length) || readOnly,
          'is-blocking': errorCount > 0 && !readOnly,
        }"
        data-testid="problems-headline"
      >
        <Lock v-if="readOnly" :size="13" aria-hidden="true" />
        <Check v-else-if="clean" :size="13" aria-hidden="true" />
        {{ headline }}
      </span>

      <!-- Rendered, never concealed. The list below is dimmed at the same time,
           so "these are not about what you are looking at" is said twice. -->
      <span v-if="stale" class="problems-checking" data-testid="problems-checking">checking…</span>
    </div>

    <div
      v-show="open"
      id="problems-list"
      class="problems-body"
      role="log"
      aria-live="polite"
      aria-label="Validation problems"
    >
      <p v-if="readOnly" class="problems-empty" data-testid="problems-read-only">
        <span class="problems-dot is-unchecked" aria-hidden="true" />
        <span>
          Read-only. <em>This is v{{ viewingVersion }}; publishing and editing act on head.</em>
        </span>
      </p>

      <p v-else-if="!merged.length && unchecked" class="problems-empty" data-testid="problems-unchecked">
        <span class="problems-dot is-unchecked" aria-hidden="true" />
        <span>
          Not checked yet. Nothing has been asked of the compiler, so nothing here is a verdict.
        </span>
      </p>

      <p v-else-if="!merged.length && unreachable" class="problems-empty" data-testid="problems-unreachable">
        <span class="problems-dot is-error" aria-hidden="true" />
        <span>
          Validation unavailable.
          <em>{{ reason || 'the validator could not be reached' }}</em>
        </span>
      </p>

      <p v-else-if="!merged.length" class="problems-empty">
        <span class="problems-dot is-ready" aria-hidden="true" />
        <span>
          Ready to publish.
          <em>Warnings never block; errors always do.</em>
        </span>
      </p>

      <template v-else>
        <ul v-if="documentRows.length" class="problems-group" aria-label="Whole-graph problems">
          <li v-for="(row, index) in documentRows" :key="row.key">
            <button
              type="button"
              class="problem-row"
              :class="{ 'is-current': current === index }"
              :aria-current="current === index ? 'true' : undefined"
              :data-testid="`problem-${row.problem.code}`"
              @click="select(index)"
            >
              <span
                class="problems-dot"
                :class="isError(row.problem) ? 'is-error' : 'is-warning'"
                aria-hidden="true"
              />
              <span class="problem-code">{{ row.problem.code }}</span>
              <span class="problem-message">{{ row.problem.message }}</span>
              <span v-if="row.fromPublish" class="problem-tag">from publish</span>
              <span class="problem-anchor">whole graph</span>
            </button>
          </li>
        </ul>

        <ul v-if="anchoredRows.length" class="problems-group" aria-label="Node and edge problems">
          <li v-for="(row, index) in anchoredRows" :key="row.key">
            <button
              type="button"
              class="problem-row"
              :class="{ 'is-current': current === documentRows.length + index }"
              :aria-current="current === documentRows.length + index ? 'true' : undefined"
              :data-testid="`problem-${row.problem.code}`"
              @click="select(documentRows.length + index)"
            >
              <span
                class="problems-dot"
                :class="isError(row.problem) ? 'is-error' : 'is-warning'"
                aria-hidden="true"
              />
              <span class="problem-code">{{ row.problem.code }}</span>
              <span class="problem-message">{{ row.problem.message }}</span>
              <span v-if="row.fromPublish" class="problem-tag">from publish</span>
              <span class="problem-anchor">{{ row.anchor }}</span>
            </button>
          </li>
        </ul>
      </template>
    </div>
  </section>
</template>

<style scoped>
.problems-panel { display: flex; min-height: 0; flex-direction: column; background: var(--surface-panel); border-top: 1px solid var(--border-default); }
.problems-head { display: flex; align-items: center; gap: 10px; padding: 7px 12px; }
.problems-toggle { display: inline-flex; align-items: center; gap: 6px; padding: 3px 5px; color: var(--text-40); background: transparent; border: 0; border-radius: var(--r-sm); cursor: pointer; }
.problems-toggle:hover { color: var(--text-body); }
.problems-toggle:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.problems-kicker { font: 700 var(--fs-11)/1 var(--font-mono); letter-spacing: 0.04em; }
.problems-headline { display: inline-flex; align-items: center; gap: 6px; color: var(--text-muted); font: 600 var(--fs-12)/1 var(--font-mono); }
.problems-headline.is-clean { color: var(--accent-mint); }
.problems-headline.is-blocking { color: var(--err-text); }
.problems-checking { margin-left: auto; color: var(--text-40); font: 500 var(--fs-11)/1 var(--font-mono); }
.problems-body { min-height: 0; max-height: 190px; overflow: auto; padding: 0 12px 10px; }

/* The whole list dims while a check is pending, so the rows and the header say
   the same thing. Colour and opacity only - the rows stay clickable, because a
   problem that was true 400ms ago is still the best guess available and taking
   it away would leave the author with nothing. */
.problems-panel.is-stale .problems-body { opacity: 0.45; }

.problems-empty { display: flex; align-items: flex-start; gap: 8px; margin: 4px 0 0; color: var(--text-muted); font-size: var(--fs-12); line-height: 1.5; }
.problems-empty em { color: var(--text-40); font-style: normal; }
.problems-group { display: grid; gap: 3px; margin: 0 0 6px; padding: 0; list-style: none; }
.problems-dot { width: 7px; height: 7px; flex: 0 0 auto; margin-top: 4px; border-radius: var(--r-full); }
.problems-dot.is-error { background: var(--err-text); }
.problems-dot.is-warning { background: var(--warn-text); }
.problems-dot.is-ready { margin-top: 5px; background: var(--accent-mint); }
/* Not a verdict: an unlit dot, deliberately not mint. */
.problems-dot.is-unchecked { margin-top: 5px; background: var(--text-40); }

.problem-row { display: flex; width: 100%; align-items: flex-start; gap: 8px; padding: 6px 7px; color: var(--text-body); text-align: left; background: transparent; border: 1px solid transparent; border-radius: var(--r-sm); cursor: pointer; transition: color var(--motion-fast) ease, background var(--motion-fast) ease, border-color var(--motion-fast) ease; }
.problem-row:hover { background: var(--surface-raised); border-color: var(--border-default); }
.problem-row:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
/* The walked row keeps a border after focus moves to the inspector field, which
   is where a click sends it - without this the panel forgets which one you are
   working on the instant it becomes useful. */
.problem-row.is-current { background: color-mix(in srgb, var(--accent-cyan) 10%, transparent); border-color: color-mix(in srgb, var(--accent-cyan) 42%, transparent); }
.problem-code { flex: 0 0 auto; padding: 1px 5px; color: var(--text-40); font: 500 10px/1.5 var(--font-mono); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-xs); }
.problem-message { flex: 1 1 auto; font-size: var(--fs-12); line-height: 1.45; overflow-wrap: anywhere; }
.problem-tag { flex: 0 0 auto; padding: 1px 5px; color: var(--warn-text); background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: var(--r-pill); font: 700 10px/1.5 var(--font-mono); }
.problem-anchor { flex: 0 0 auto; max-width: 140px; overflow: hidden; color: var(--text-40); font: 600 10px/1.5 var(--font-mono); text-overflow: ellipsis; white-space: nowrap; }
</style>
