<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Bot, ChevronLeft, ChevronRight } from 'lucide-vue-next'
import type { ChatEntry } from '../types/studio'

/**
 * The trace: one short line per thing that happened, and nothing else.
 *
 * It used to render `frame.message` verbatim, so the rail read as the
 * framework's own log - "persist started", "write_report to persist",
 * "ValidatorFlow completed", a guardrail's `{"valid":true,"feedback":null}`
 * shown as though somebody had said it, and `5168 in · 3994 out` on every row.
 * `trace/interpret.ts` now decides what a row says; this component decides how
 * it looks, and the two are separate so the vocabulary can be asserted over a
 * real frame log without mounting anything.
 *
 * NOTHING WAS DROPPED. Every row carries a `<details>` disclosure, collapsed by
 * default, holding the framework's own sentence, the whole `details` payload,
 * the model, the token counts and the duration. The raw is one click away
 * rather than in the way - which is the actual difference between a trace and
 * a dump.
 */

const props = defineProps<{
  entries: ChatEntry[]
  collapsed: boolean
  /**
   * Node id -> character index, so a trace avatar wears the same colour as the
   * node's own medallion. Optional: the rail renders a neutral placeholder
   * without it, and the cast work replaces the placeholder in place.
   */
  characterOf?: (nodeId: string) => number
}>()

const emit = defineEmits<{ toggle: [] }>()
const list = ref<HTMLElement | null>(null)

/**
 * How many rows are in the DOM at once.
 *
 * A run of 119+ frames is the criterion (T2.8, S3) and a long one goes well
 * past it, so the list is windowed rather than unbounded: the newest 200 rows
 * render, everything older folds behind one button that expands it when asked.
 * 200 and not 40, deliberately - the whole point of the trace is that a reader
 * can scroll back through what happened, and a fold that fires during an
 * ordinary run would hide the narrative rather than bound the DOM. Paired with
 * `content-visibility: auto` on the row, which lets the browser skip layout and
 * paint for the rows scrolled out of view; between them a 500-frame run costs
 * what a 200-row list costs.
 */
const WINDOW_ROWS = 200

const showAll = ref(false)
const hiddenCount = computed(() =>
  showAll.value ? 0 : Math.max(0, props.entries.length - WINDOW_ROWS),
)
const shown = computed(() =>
  hiddenCount.value > 0 ? props.entries.slice(-WINDOW_ROWS) : props.entries,
)

watch(
  () => props.entries.length,
  async () => {
    if (props.collapsed) return
    await nextTick()
    list.value?.scrollTo({ top: list.value.scrollHeight, behavior: 'smooth' })
  },
)

/** Two letters for the placeholder disc, from the identity the row resolved. */
function initials(identity: string): string {
  const words = identity.trim().split(/\s+/).filter(Boolean)
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase()
  return (identity.slice(0, 2) || '??').toUpperCase()
}

function avatarStyle(entry: ChatEntry): Record<string, string> {
  const index = entry.nodeId && props.characterOf ? props.characterOf(entry.nodeId) : null
  return index === null ? {} : { '--character-color': `var(--character-${index})` }
}

function characterIndexOf(entry: ChatEntry): string | undefined {
  if (!entry.nodeId || !props.characterOf) return undefined
  return String(props.characterOf(entry.nodeId))
}

/** The line's own numbers, for the disclosure. Never for the row. */
function tokenNote(entry: ChatEntry): string {
  const tokens = entry.raw.tokens
  if (!tokens) return ''
  return `${tokens.prompt.toLocaleString()} in · ${tokens.completion.toLocaleString()} out`
}
</script>

<template>
  <aside class="chat-rail" :class="{ 'is-collapsed': collapsed }" aria-label="Run activity">
    <div class="rail-header">
      <div>
        <span class="section-kicker">LIVE ACTIVITY</span>
        <h2>Agent trace</h2>
      </div>
      <span class="entry-count" aria-live="polite">{{ entries.length }}</span>
    </div>

    <button
      class="rail-toggle icon-button"
      type="button"
      :aria-label="collapsed ? 'Expand activity rail' : 'Collapse activity rail'"
      :aria-expanded="!collapsed"
      :title="collapsed ? 'Expand activity' : 'Collapse activity'"
      @click="emit('toggle')"
    >
      <ChevronRight v-if="collapsed" :size="17" aria-hidden="true" />
      <ChevronLeft v-else :size="17" aria-hidden="true" />
    </button>

    <!--
      The dialogue rail, mounted HERE rather than under the canvas.

      It was a fifth row of `.graph-workspace` first, and the measurement is why
      it is not: opening on the first utterance took the Vue Flow container from
      626px to 462px, mid-run, on the exact canvas the gauntlet's captures are
      taken of. A surface whose job is narrating a run must not shrink the run.
      In this column it costs the canvas nothing, it collapses with the rail it
      shares, and it is beside the trace it divides the frames with rather than
      across the page from it.
    -->
    <div v-show="!collapsed" class="rail-slot"><slot name="above" /></div>

    <div
      v-show="!collapsed"
      ref="list"
      class="rail-list"
      tabindex="0"
      role="log"
      aria-live="polite"
      aria-relevant="additions text"
      aria-label="Run activity log"
    >
      <div v-if="entries.length === 0" class="rail-empty">
        <Bot :size="20" aria-hidden="true" />
        <span>Run activity will appear here.</span>
      </div>

      <button
        v-if="hiddenCount > 0"
        class="trace-earlier"
        type="button"
        data-testid="trace-earlier"
        @click="showAll = true"
      >
        {{ hiddenCount }} earlier {{ hiddenCount === 1 ? 'line' : 'lines' }}
      </button>

      <article
        v-for="entry in shown"
        :key="entry.id"
        class="trace-entry"
        data-testid="trace-entry"
        :class="[`is-${entry.variant}`, { 'is-system': !entry.identity }]"
        :data-node="entry.nodeId"
        :data-identity="entry.identity"
        :data-tone="entry.tone"
      >
        <!--
          The character's slot. It is a 32px disc wearing the node's own colour
          today and the cast's character tomorrow: `data-character-seed` is the
          identity string the interpretation layer resolved, which is the same
          seed the node's medallion is drawn from, so the tie-in criterion is a
          string comparison rather than a screenshot.
        -->
        <span
          v-if="entry.identity"
          class="trace-avatar"
          data-testid="trace-avatar"
          :data-character-seed="entry.identity"
          :data-character="characterIndexOf(entry)"
          :style="avatarStyle(entry)"
          aria-hidden="true"
        >{{ initials(entry.identity) }}</span>

        <div class="trace-content">
          <div class="trace-meta">
            <strong>{{ entry.actor }}</strong>
            <time :datetime="entry.timestamp">{{ entry.timestamp }}</time>
          </div>
          <div class="trace-bubble">
            <p data-testid="trace-line">{{ entry.message }}</p>

            <!--
              Collapsed by default, and a native `<details>` rather than a
              toggled div: it is keyboard reachable, it is announced as an
              expandable region, and it costs no state in this component - which
              matters when 200 of them are in the DOM.
            -->
            <details class="trace-raw">
              <summary>Details</summary>
              <dl class="trace-raw-facts">
                <div><dt>Event</dt><dd>{{ entry.raw.kind }} · {{ entry.raw.eventType }}</dd></div>
                <div><dt>Sequence</dt><dd>{{ entry.raw.seq }}</dd></div>
                <div v-if="entry.raw.model"><dt>Model</dt><dd>{{ entry.raw.model }}</dd></div>
                <div v-if="entry.raw.tool"><dt>Tool</dt><dd>{{ entry.raw.tool }}</dd></div>
                <div v-if="entry.raw.durationMs !== undefined">
                  <dt>Took</dt><dd>{{ entry.raw.durationMs }}ms</dd>
                </div>
                <div v-if="tokenNote(entry)" data-testid="trace-tokens">
                  <dt>Tokens</dt><dd>{{ tokenNote(entry) }}</dd>
                </div>
              </dl>
              <p class="trace-raw-message">{{ entry.raw.message }}</p>
              <pre data-testid="trace-raw">{{ entry.raw.details }}</pre>
            </details>
          </div>
        </div>
      </article>
    </div>
  </aside>
</template>

<style scoped>
.chat-rail {
  position: relative;
  z-index: var(--z-rail);
  display: flex;
  min-width: 0;
  height: 100%;
  flex-direction: column;
  overflow: visible;
  background: var(--surface-overlay);
  border-right: 1px solid var(--border-default);
  backdrop-filter: var(--blur-rail);
  transition: width var(--motion-medium) var(--ease-out), min-width var(--motion-medium) var(--ease-out);
}

.chat-rail.is-collapsed { width: 0; min-width: 0; border-right: 0; }

.rail-header {
  display: flex;
  min-height: 64px;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  border-bottom: 1px solid var(--border-default);
}

.rail-header h2 { margin: 2px 0 0; font-size: 16px; }
.section-kicker { color: var(--accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); }
.entry-count { min-width: 24px; padding: 3px 6px; color: var(--text-muted); text-align: center; font: 600 var(--fs-11)/1 var(--font-mono); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-sm); }

.rail-toggle {
  position: absolute;
  top: 13px;
  right: -32px;
  width: 32px;
  height: 38px;
  border-left: 0;
  border-radius: 0 var(--r-lg) var(--r-lg) 0;
}

/* Sized to its content and never flexed, so the trace below keeps every pixel
   the dialogue does not need. */
.rail-slot { flex: 0 0 auto; }

.rail-list {
  min-height: 0;
  flex: 1;
  overflow: auto;
  padding: 14px 14px 28px;
  scrollbar-color: rgba(153, 234, 249, 0.3) transparent;
}

.rail-empty { display: flex; min-height: 180px; align-items: center; justify-content: center; gap: 8px; color: var(--text-muted); font-size: var(--fs-13); }

.trace-earlier {
  display: block;
  width: 100%;
  margin: 0 0 12px;
  padding: 6px 8px;
  color: var(--text-muted);
  font: 500 var(--fs-11)/1.3 var(--font-mono);
  background: var(--surface-well);
  border: 1px dashed var(--border-default);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.trace-earlier:hover { color: var(--text-title); }
.trace-earlier:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 2px; }

/*
 * `content-visibility` is what makes a long run cheap: the browser skips
 * layout and paint for a row scrolled out of view, and `contain-intrinsic-size`
 * gives it a height to reserve so the scrollbar does not jump as rows come back
 * into view. The window above bounds the node COUNT; this bounds the work per
 * node.
 */
.trace-entry {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  gap: 9px;
  margin-bottom: 13px;
  content-visibility: auto;
  contain-intrinsic-size: auto 58px;
}

.trace-entry.is-system { display: block; }

.trace-avatar {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  color: var(--bg-node);
  font: 800 10px/1 var(--font-mono);
  background: var(--character-color, var(--gradient-brand));
  border-radius: var(--r-full);
}

.trace-content { min-width: 0; }
.trace-meta { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin: 0 2px 5px; }
.trace-meta strong { overflow: hidden; color: var(--text-40); font-size: var(--fs-11); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.trace-meta time { flex: 0 0 auto; color: var(--text-40); font: 400 10px/1 var(--font-mono); }

.trace-bubble { padding: 10px 11px; color: var(--text-body); font-size: var(--fs-12); line-height: 1.5; background: var(--surface-raised); border: 1px solid var(--border-default); border-radius: 2px var(--r-2xl) var(--r-2xl) var(--r-2xl); }
.is-system .trace-bubble { border-radius: var(--r-lg); background: var(--surface-well); }
.is-warning .trace-bubble { color: var(--warn-text); background: var(--warn-bg); border-color: var(--warn-border); }
.is-error .trace-bubble { color: var(--err-text); background: var(--err-bg); border-color: var(--err-border); }
.trace-bubble p { margin: 0; overflow-wrap: anywhere; }

.trace-raw { margin-top: 7px; }
.trace-raw > summary {
  color: var(--text-40);
  font: 600 var(--fs-11)/1.3 var(--font-body);
  cursor: pointer;
  list-style: none;
}
.trace-raw > summary::-webkit-details-marker { display: none; }
.trace-raw > summary::before { content: '▸ '; }
.trace-raw[open] > summary::before { content: '▾ '; }
.trace-raw > summary:hover { color: var(--text-muted); }
.trace-raw > summary:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 2px; }

.trace-raw-facts { display: grid; gap: 2px; margin: 7px 0 0; }
.trace-raw-facts > div { display: flex; gap: 6px; }
.trace-raw-facts dt { flex: 0 0 62px; color: var(--text-40); font: 500 10px/1.4 var(--font-mono); }
.trace-raw-facts dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--text-muted); font: 400 10px/1.4 var(--font-mono); font-variant-numeric: tabular-nums; }

.trace-raw-message { margin: 7px 0 0 !important; color: var(--text-40); font: 400 10px/1.4 var(--font-mono); }

.trace-raw pre {
  max-height: 220px;
  margin: 6px 0 0;
  overflow: auto;
  padding: 7px 8px;
  color: var(--text-muted);
  font: 400 10px/1.45 var(--font-mono);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
}

@media (prefers-reduced-motion: reduce) {
  .chat-rail { transition: none; }
}
</style>
