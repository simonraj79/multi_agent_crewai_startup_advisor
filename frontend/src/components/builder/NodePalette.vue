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
 * The second MIME entry a SPECIFIC tool's drag carries: the catalogue id.
 *
 * A drag from the tool sub-list sets BOTH - `BUILDER_KIND_MIME` says "make a
 * `tool` node" and this says "make it that one" - so a canvas that has never
 * heard of the sub-list still makes the right KIND of node from the same drop,
 * and one that has reads the id off the second entry.
 *
 * MOVED to `useBuilderCanvas` on 2026-09-04, when the canvas finally grew a
 * reader for it, and re-exported here so every existing importer keeps
 * resolving. One binding rather than two equal strings: this constant is now a
 * contract with two ends, and the copy that would have lived here is the drift
 * `BUILDER_KIND_MIME` above is still an example of.
 */
import { BUILDER_TOOL_ID_MIME } from '../../composables/useBuilderCanvas'

export { BUILDER_TOOL_ID_MIME }

/**
 * How long the tool sub-list's filter trails the box.
 *
 * Flowise debounces its own node search at 500ms behind a fuzzy scorer
 * (`views/canvas/AddNodes.jsx`); this is 250 because the catalogue is at most
 * about thirty entries and an exact substring match over thirty labels is not
 * work worth waiting half a second to avoid. Exported so the spec asserts the
 * number the component uses rather than a copy of it.
 */
export const TOOL_FILTER_DEBOUNCE_MS = 250

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
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ChevronDown, FileStack, Search } from 'lucide-vue-next'
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
    /**
     * A stored version that is not head is on the canvas (round 2, D-15-1).
     * Every tile is disabled and says why: the store would refuse the commit
     * anyway, and a palette that still invited a drop over a read-only canvas
     * was the loudest of the cues the bar failed to give.
     */
    readOnly?: boolean
  }>(),
  { budget: null, library: () => [], openDocumentId: null, filter: '', filterMatches: 0, readOnly: false },
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

/** Why nothing can be placed, while a stored version is on screen. */
const READ_ONLY = 'Read-only — a stored version is on the canvas. Restore it, or go back to head, to edit.'

function disabledFor(kind: NodeKind): boolean {
  if (props.readOnly) return true
  if (vocabularyUnavailable.value) return true
  return isBillableKind(kind) && atBillableCeiling.value
}

function tooltipFor(kind: NodeKind): string {
  if (props.readOnly) return READ_ONLY
  if (!isBillableKind(kind)) return NODE_KINDS[kind].blurb
  if (!atBillableCeiling.value) return NODE_KINDS[kind].blurb
  // The bound is named, because "you cannot add another" without the name of
  // the rule is an editor asserting authority it will not explain.
  return `max_billable_nodes is ${billableMax.value}; this graph already has ${billableUsed.value}.`
}

/**
 * The key this tile answers to, printed on the tile.
 *
 * `1`-`7` for the seven flow kinds and `T`, `M`, `K` for the three attachments
 * (owner's decision 18). Read from `nodeKinds.ts` rather than derived from
 * `paletteOrder + 1`, which is what it used to be: with ten kinds that formula
 * prints `8`, `9` and `10` on tiles the shortcut layer binds to letters, and a
 * palette that prints a key nothing is listening for is worse than one that
 * prints none. `useBuilderHotkeys` reads the same field.
 */
function hotkeyFor(kind: NodeKind): string {
  return NODE_KINDS[kind].hotkey
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

/**
 * Dragging one NAMED tool out of the sub-list.
 *
 * Both MIME entries, and the order matters only in that both are present: the
 * kind entry is what every existing drop handler already reads, so a specific
 * tool lands as a `tool` node even on a canvas that ignores the second key.
 * `text/plain` carries the tool id rather than the word `tool`, because that is
 * the useful thing to paste into a text field somewhere else.
 */
function onToolDragStart(event: DragEvent, toolId: string): void {
  if (disabledFor('tool')) {
    event.preventDefault()
    return
  }
  const transfer = event.dataTransfer
  if (!transfer) return
  transfer.effectAllowed = 'copy'
  transfer.setData(BUILDER_KIND_MIME, 'tool')
  transfer.setData(BUILDER_TOOL_ID_MIME, toolId)
  transfer.setData('text/plain', toolId)
}

/* --- the tool sub-list (D7) ---------------------------------------------
 *
 * A catalogue drawer under the `tool` tile, so an author reaches a NAMED tool
 * in one gesture instead of dropping a blank tool node and then hunting for it
 * in the inspector. Rendered only when the server has served `vocabulary.tools`
 * - a client-side catalogue is cut-list item 17, and it would offer tools the
 * compiler has never heard of.
 */
const toolsOpen = ref(false)
const toolQuery = ref('')
/**
 * The query the LIST is filtered by, which trails the box by 250ms.
 *
 * Flowise debounces its own node search at 500ms behind a fuzzy scorer; 250ms
 * here because the catalogue is <= 30 entries and an exact substring match over
 * thirty labels is not work worth waiting half a second to avoid. Debounced at
 * all rather than not, because every keystroke otherwise re-renders the drawer
 * mid-drag-target.
 */
const debouncedQuery = ref('')
let filterTimer: ReturnType<typeof setTimeout> | null = null

function onToolQuery(value: string): void {
  toolQuery.value = value
  if (filterTimer !== null) clearTimeout(filterTimer)
  filterTimer = setTimeout(() => {
    debouncedQuery.value = value
    filterTimer = null
  }, TOOL_FILTER_DEBOUNCE_MS)
}

onBeforeUnmount(() => {
  // A timer that outlives the component writes a ref nothing is watching, and
  // in a suite that reuses one worker it is reported against whichever file
  // happens to be running when it fires.
  if (filterTimer !== null) clearTimeout(filterTimer)
})

/** The served catalogue, or null while this build's `/vocabulary` is still v1. */
const toolCatalogue = computed(() => vocabulary.value?.tools ?? null)

const filteredTools = computed(() => {
  const rows = toolCatalogue.value ?? []
  const query = debouncedQuery.value.trim().toLowerCase()
  if (!query) return rows
  // LABEL only, which is what D7 names. An author searching the drawer is
  // looking for the words they read on the row; matching the id as well would
  // return rows whose visible text does not contain what they typed.
  return rows.filter((row) => row.label.toLowerCase().includes(query))
})

function place(kind: NodeKind): void {
  if (disabledFor(kind)) return
  emit('place', kind)
}
</script>

<template>
  <aside class="builder-palette" :class="{ 'is-read-only': readOnly }" aria-label="Node palette and saved graphs">
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

    <p v-if="readOnly" class="builder-palette-readonly" role="status" data-testid="palette-read-only">
      {{ READ_ONLY }}
    </p>

    <div class="builder-tiles" role="list">
      <template v-for="kind in kinds" :key="kind">
      <button
        type="button"
        role="listitem"
        class="builder-tile"
        :class="[
          NODE_KINDS[kind].className,
          `is-family-${NODE_KINDS[kind].family}`,
          { 'is-billable': isBillableKind(kind) },
        ]"
        :draggable="!disabledFor(kind)"
        :disabled="disabledFor(kind)"
        :title="tooltipFor(kind)"
        :aria-keyshortcuts="hotkeyFor(kind)"
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

      <!--
        The catalogue drawer, under the tool tile and nowhere else.

        Under it rather than beside it because the sub-list is ABOUT that tile -
        the generic tile drops a blank tool node, and every row below it drops a
        named one - and a drawer that opened somewhere else would be a second
        palette. It is absent entirely, not empty, when the server has served no
        catalogue: cut-list item 17 again, and an empty search box over nothing
        is a feature that looks broken.
      -->
      <template v-if="kind === 'tool' && toolCatalogue">
        <button
          type="button"
          class="builder-subtoggle"
          :aria-expanded="toolsOpen"
          aria-controls="builder-tool-sublist"
          @click="toolsOpen = !toolsOpen"
        >
          <ChevronDown
            class="builder-subtoggle-caret"
            :class="{ 'is-open': toolsOpen }"
            :size="12"
            :stroke-width="2"
            aria-hidden="true"
          />
          {{ toolCatalogue.length }} named {{ toolCatalogue.length === 1 ? 'tool' : 'tools' }}
        </button>

        <div v-if="toolsOpen" id="builder-tool-sublist" class="builder-sublist">
          <input
            type="search"
            class="builder-subfilter"
            placeholder="Search tools"
            aria-label="Search tools by name"
            data-testid="tool-search"
            :value="toolQuery"
            @input="onToolQuery(($event.target as HTMLInputElement).value)"
          />
          <p v-if="filteredTools.length === 0" class="builder-subempty">
            No tool matches “{{ toolQuery }}”.
          </p>
          <ul v-else class="builder-subrows">
            <li v-for="tool in filteredTools" :key="tool.tool_id">
              <button
                type="button"
                class="builder-subrow"
                data-testid="tool-row"
                :data-tool-id="tool.tool_id"
                :draggable="!disabledFor('tool')"
                :disabled="disabledFor('tool')"
                :title="tool.description"
                @dragstart="onToolDragStart($event, tool.tool_id)"
              >
                <span class="builder-subrow-name">{{ tool.label }}</span>
                <span class="builder-subrow-cat">{{ tool.category }}</span>
              </button>
            </li>
          </ul>
        </div>
      </template>
      </template>
    </div>

    <header class="builder-palette-head builder-palette-head-library">
      <span class="builder-palette-kicker">LIBRARY</span>
      <div class="builder-library-headline">
        <h2>Saved graphs</h2>
        <!--
        HOW MANY THERE ARE (D-15-4, round 2). The list scrolls, and 87px of
        it are on screen at 1440x900 - so the second row's card was cut at
        the viewport edge in five captures with nothing visible to say a
        third existed. Every row was REACHABLE, which the layout spec already
        proved by scrolling to the last one; what was missing was any way to
        know to scroll. What is scored is what is visible.

        A count rather than a styled scrollbar alone: it is legible at a
        glance, it survives a platform that draws overlay scrollbars only
        while scrolling (which is what made this invisible on the capture
        machine), and it answers "how much more" rather than "there is more".
          The list also keeps a permanent gutter, below.
        -->
        <span v-if="library.length" class="builder-library-count" data-testid="library-count">
          {{ library.length }}
        </span>
      </div>
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
          <!-- Two lines before it clips, and the whole name in the title
               (D-15-4): "Minimal gated age…" lost the one word - copy - that
               told the row from its source. -->
          <span class="builder-library-name" :title="entry.name">{{ entry.name }}</span>
          <span class="builder-library-meta">
            <span class="builder-library-version">v{{ entry.version }}</span>
            <span class="builder-library-status" :class="`is-${entry.status}`">{{ entry.status }}</span>
          </span>
        </button>
      </li>
    </ul>
  </aside>
</template>
