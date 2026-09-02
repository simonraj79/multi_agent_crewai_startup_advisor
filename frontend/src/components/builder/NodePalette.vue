<script lang="ts">
import type { BuilderNode, NodeKind, Tier } from '../../types/builder'

/**
 * The drag payload's MIME type.
 *
 * A private type rather than `text/plain` so the canvas can tell a palette tile
 * from a URL, a file or a selection of text dropped in from another window, and
 * refuse the three it cannot make a node out of. `text/plain` is set as well,
 * carrying the same word, so dragging a tile into a text field somewhere else
 * pastes something meaningful instead of nothing.
 */
export const BUILDER_KIND_MIME = 'application/x-builder-kind'

/**
 * The kinds that cost money, derived rather than listed.
 *
 * `Extract` picks out exactly the members of the `BuilderNode` union whose
 * config carries a `tier`, which is the client-side shadow of Python's
 * `_BillableConfig` - the base class `AgentConfig` and `CrewConfig` extend and
 * nothing else does. The `Record` below is then EXHAUSTIVE over that union, so
 * a third billable kind appearing in `types/builder.ts` breaks this file at
 * compile time rather than quietly dropping out of the palette's counter.
 */
export type BillableKind = Extract<BuilderNode, { config: { tier: Tier } }>['kind']
export const BILLABLE_KINDS: Record<BillableKind, true> = { agent: true, crew: true }

export function isBillableKind(kind: NodeKind): kind is BillableKind {
  return kind in BILLABLE_KINDS
}
</script>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { FileStack, Search } from 'lucide-vue-next'
import { NODE_KINDS } from '../../data/nodeKinds'
import {
  loadVocabulary,
  vocabulary,
  vocabularyProblem,
  vocabularyUnavailable,
} from '../../data/builderVocabulary'
import type { BuilderBudget, BuilderDocumentSummary } from '../../types/builder'

const props = withDefaults(
  defineProps<{
    /**
     * The last validate response's budget, or `null` before one has landed.
     *
     * The counters read the SERVER's counts. The palette never counts nodes
     * itself: that is a `bounds.py` figure and R6 is unambiguous about who owns
     * one. What the palette is allowed to do with it is the single advisory
     * §6.1 sanctions by name - disable at the ceiling - and even that still
     * permits the author to reach the same state by pasting.
     */
    budget?: BuilderBudget | null
    /**
     * The caller's saved graphs, from `GET /api/builder/workflows`, newest
     * first (the endpoint orders it; this list is rendered as received).
     *
     * Passed in rather than fetched here so the palette owns no request, no
     * loading state and no error state for something the shell already has.
     */
    library?: readonly BuilderDocumentSummary[]
    /** The document currently open, so its row reads as current rather than as a link. */
    openDocumentId?: string | null
    /**
     * Section 4.5's node filter, owned by the canvas and typed here.
     *
     * The palette owns the text box and nothing else: what a query DOES -
     * highlight matching cards, drop the rest to .35 - is a fact about the
     * graph projection, and the two would drift the moment either moved.
     * `/` focuses this input, which is the whole reason it exists as a real
     * control rather than as a binding pointing at a selector that matched
     * nothing.
     */
    filter?: string
    /** How many graph nodes the current query matches, for the live count. */
    filterMatches?: number
  }>(),
  { budget: null, library: () => [], openDocumentId: null, filter: '', filterMatches: 0 },
)

const emit = defineEmits<{
  /** Click-to-place: drop this kind at the viewport centre as one commit. */
  (event: 'place', kind: NodeKind): void
  /** Open a saved graph. */
  (event: 'open', id: string): void
  /** The filter query changed. */
  (event: 'update:filter', value: string): void
}>()

onMounted(() => {
  void loadVocabulary()
})

/**
 * The server's order, not ours.
 *
 * `_vocabulary()` lists the seven literals in a deliberate order and the
 * hotkeys `1`-`7` follow it; sorting here would silently renumber every key
 * against the tile above it. `tests/nodeKinds.spec.ts` reads the Python list
 * and asserts the two agree, which is why this can render the served array
 * directly and still be sure `NODE_KINDS[kind]` exists for each entry.
 */
const kinds = computed<NodeKind[]>(() => vocabulary.value?.node_kinds ?? [])
const bounds = computed(() => vocabulary.value?.bounds ?? null)

const billableUsed = computed(() => props.budget?.billable_nodes ?? 0)
const escalationUsed = computed(() => props.budget?.escalation_nodes ?? 0)
const billableMax = computed(() => bounds.value?.max_billable_nodes ?? null)
const escalationMax = computed(() => bounds.value?.max_escalation_nodes ?? null)

/**
 * At the billable ceiling, and only there.
 *
 * The escalation count is DISPLAYED on the same tiles and deliberately does not
 * gate anything: a new node is born `cheap` (see `nodeKinds.ts`), so placing
 * one can never raise `escalation_nodes`. Disabling a tile on a count the
 * gesture cannot change would be a control refusing an action for a reason that
 * is not true of it.
 */
const atBillableCeiling = computed(
  () => billableMax.value !== null && billableUsed.value >= billableMax.value,
)

function disabledFor(kind: NodeKind): boolean {
  if (vocabularyUnavailable.value) return true
  return isBillableKind(kind) && atBillableCeiling.value
}

function tooltipFor(kind: NodeKind): string {
  if (!isBillableKind(kind)) return NODE_KINDS[kind].blurb
  if (!atBillableCeiling.value) return NODE_KINDS[kind].blurb
  // The bound is named, because "you cannot add another" without the name of
  // the rule is an editor asserting authority it will not explain.
  return `max_billable_nodes is ${billableMax.value}; this graph already has ${billableUsed.value}.`
}

/** `paletteOrder + 1` is the `1`-`7` key, and the tile prints the key it answers to. */
function hotkeyFor(kind: NodeKind): number {
  return NODE_KINDS[kind].paletteOrder + 1
}

function onDragStart(event: DragEvent, kind: NodeKind): void {
  if (disabledFor(kind)) {
    event.preventDefault()
    return
  }
  const transfer = event.dataTransfer
  if (!transfer) return
  transfer.effectAllowed = 'copy'
  transfer.setData(BUILDER_KIND_MIME, kind)
  transfer.setData('text/plain', kind)
}

function place(kind: NodeKind): void {
  if (disabledFor(kind)) return
  emit('place', kind)
}
</script>

<template>
  <aside class="builder-palette" aria-label="Node palette and saved graphs">
    <header class="builder-palette-head">
      <span class="builder-palette-kicker">PALETTE</span>
      <h2>Kinds</h2>
    </header>

    <!--
      No hardcoded fallback list, ever (cut list item 17). A palette that keeps
      drawing kinds after `/vocabulary` failed is a palette drawing graphs the
      compiler will refuse, and the author finds out at publish.
    -->
    <p v-if="vocabularyUnavailable" class="builder-palette-alert" role="alert">
      {{ vocabularyProblem }}
    </p>

    <!--
      The control `/` focuses. It filters the GRAPH, not this list, which is why
      it reads "Filter nodes" and sits above the tiles rather than inside them:
      seven kinds do not need filtering and a sixteen-node graph does.
    -->
    <div class="builder-filter">
      <Search class="builder-filter-icon" :size="13" :stroke-width="1.9" aria-hidden="true" />
      <input
        type="search"
        class="builder-filter-input"
        placeholder="Filter nodes by name"
        aria-label="Filter nodes by name"
        aria-keyshortcuts="/"
        :value="filter"
        @input="emit('update:filter', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="filter.trim()" class="builder-filter-count">
        {{ filterMatches }} {{ filterMatches === 1 ? 'match' : 'matches' }}
      </span>
    </div>

    <div class="builder-tiles" role="list">
      <button
        v-for="kind in kinds"
        :key="kind"
        type="button"
        role="listitem"
        class="builder-tile"
        :class="[NODE_KINDS[kind].className, { 'is-billable': isBillableKind(kind) }]"
        :draggable="!disabledFor(kind)"
        :disabled="disabledFor(kind)"
        :title="tooltipFor(kind)"
        :aria-keyshortcuts="String(hotkeyFor(kind))"
        @dragstart="onDragStart($event, kind)"
        @click="place(kind)"
      >
        <!--
          A miniature of the card it produces, not a generic icon in a generic
          box: the same gradient-bordered well, tinted by the same
          `--node-gradient` the dropped card will carry. Dragging a tile should
          be a promise about what lands.
        -->
        <span class="builder-tile-well" aria-hidden="true">
          <component :is="NODE_KINDS[kind].icon" :size="15" :stroke-width="1.9" />
        </span>
        <span class="builder-tile-copy">
          <span class="builder-tile-name">
            {{ NODE_KINDS[kind].defaultLabel }}
            <kbd class="builder-tile-key">{{ hotkeyFor(kind) }}</kbd>
          </span>
          <span class="builder-tile-blurb">{{ NODE_KINDS[kind].blurb }}</span>
          <!--
            Both counts on the two tiles they are about, so the author sees the
            row fill BEFORE placing the node that breaks it. Amber lands AT the
            bound, not past it - past it is a problem the server has already
            reported and this is the warning that precedes one.
          -->
          <span v-if="isBillableKind(kind) && bounds" class="builder-tile-counts">
            <span class="builder-tile-count" :class="{ 'is-at-bound': atBillableCeiling }">
              billable {{ billableUsed }}/{{ billableMax }}
            </span>
            <span
              class="builder-tile-count is-escalation"
              :class="{ 'is-at-bound': escalationMax !== null && escalationUsed >= escalationMax }"
            >
              escalation {{ escalationUsed }}/{{ escalationMax }}
            </span>
          </span>
        </span>
      </button>
    </div>

    <header class="builder-palette-head builder-palette-head-library">
      <span class="builder-palette-kicker">LIBRARY</span>
      <h2>Saved graphs</h2>
    </header>

    <p v-if="library.length === 0" class="builder-palette-empty">No saved graphs yet</p>

    <ul v-else class="builder-library">
      <li v-for="entry in library" :key="entry.id">
        <button
          type="button"
          class="builder-library-row"
          :class="{ 'is-open': entry.id === openDocumentId }"
          :aria-current="entry.id === openDocumentId ? 'true' : undefined"
          @click="emit('open', entry.id)"
        >
          <FileStack class="builder-library-icon" :size="13" :stroke-width="1.9" aria-hidden="true" />
          <span class="builder-library-name">{{ entry.name }}</span>
          <span class="builder-library-version">v{{ entry.version }}</span>
          <span class="builder-library-status" :class="`is-${entry.status}`">{{ entry.status }}</span>
        </button>
      </li>
    </ul>
  </aside>
</template>
