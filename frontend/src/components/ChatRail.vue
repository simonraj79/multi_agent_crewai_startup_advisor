<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Bot, ChevronLeft, ChevronRight, UserRound } from 'lucide-vue-next'
import AgentCharacter from './AgentCharacter.vue'
import type { PipState } from '../characters/pip'
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
  /**
   * Node id -> the identity the RUN resolved, and the pose it is in.
   *
   * Both from `useRunChoreography` by way of `StudioView`, and both optional
   * so this rail still renders in a spec that mounts it with entries alone.
   *
   * The identity is asked of the STORE rather than taken from `entry.identity`,
   * and the difference is the whole of T2.6. A row's own identity is resolved
   * per FRAME, so a node whose first frame carried no `agent_role` produces
   * early rows named after its label and later rows named after its role - two
   * seeds, two characters, one agent. The store answers with the first role it
   * ever saw and never changes it, so every row of a node draws one creature
   * and it is the creature standing on that node's card.
   */
  identityOf?: (nodeId: string) => string
  stateOf?: (nodeId: string) => PipState
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

/**
 * One row's rendered inputs, and the SAME object back while they are unchanged
 * (T2.8).
 *
 * A trace row is thirty-odd elements - a name, a time, a line, a `<details>`
 * with a six-row `<dl>`, a `<pre>`, and since the cast a fifteen-element SVG
 * character. A frame appends one row and Vue re-evaluated the template for
 * every row already there, so the cost of a frame grew with the length of the
 * run: measured in a mounted benchmark, 455 ms of render across 262 frames with
 * only 74 rows on screen, and the criterion's own replay is longer than that.
 *
 * `v-memo="[row]"` in the template is what skips them, and this is what makes
 * that key HONEST: everything the row renders which can change independently of
 * `entry` is folded into the object, so an unchanged object really does mean an
 * unchanged row. There are exactly two such things - the character's seed and
 * its pose, both of which come from the run store rather than from the entry -
 * and both are captured here. A memo key that named only `entry` would freeze
 * the newest row's character in whatever pose it was born in, which is the one
 * thing T2.6 measures.
 */
interface TraceRow {
  entry: ChatEntry
  seed: string
  pose: PipState
  /** True for a row about the OPERATOR: a gate opening, closing or lapsing. */
  you: boolean
}

/**
 * Whether this row is about a person rather than an agent.
 *
 * A gate is a human turn. The graph already refuses it a character - a gate
 * node keeps its lucide medallion and gets no Pip - and the trace has to make
 * the same distinction for the same reason: a cast member is something the
 * system runs, and the one thing in a run it does not run is you.
 *
 * Two signals, and both are needed. `tone === 'you'` is the interpreter's own
 * judgement and covers a line addressed to the operator whatever produced it;
 * the `gate_` kinds catch a gate frame the interpreter toned differently -
 * `gate_expired` is a warning, not a request.
 */
function isYou(entry: ChatEntry): boolean {
  return entry.tone === 'you' || entry.raw.kind.startsWith('gate')
}

const rowCache = new Map<string, TraceRow>()

const rows = computed<TraceRow[]>(() =>
  shown.value.map((entry) => {
    const seed = seedOf(entry)
    const pose = poseOf(entry)
    const cached = rowCache.get(entry.id)
    if (cached && cached.entry === entry && cached.seed === seed && cached.pose === pose) {
      return cached
    }
    const row: TraceRow = { entry, seed, pose, you: isYou(entry) }
    rowCache.set(entry.id, row)
    return row
  }),
)

// The window is 200 rows and a long run is longer, so the cache is trimmed to
// what is on screen rather than left to grow with the run. Cheap: it runs once
// per render of a list that is already being walked.
watch(rows, (current) => {
  if (rowCache.size <= WINDOW_ROWS * 2) return
  const live = new Set(current.map((row) => row.entry.id))
  for (const id of [...rowCache.keys()]) if (!live.has(id)) rowCache.delete(id)
})

/**
 * Follow the newest row, at most ONCE per animation frame, and only for a
 * reader who is already at the bottom (T2.8).
 *
 * Three separate costs were in the old one line, and each is the kind a unit
 * suite cannot see because jsdom implements no scrolling at all:
 *
 *  1. `behavior: 'smooth'` started a NEW animated scroll for every appended
 *     row. A burst of a dozen frames in one millisecond - which is exactly what
 *     the backend emits at a fan-out - started a dozen overlapping scroll
 *     animations, none of which ever caught up.
 *  2. Reading `scrollHeight` forces a synchronous layout. Doing it per frame,
 *     after `nextTick`, is a layout thrash in the middle of the burst.
 *  3. It fought the reader. Anybody who had scrolled up to read an earlier line
 *     was yanked back to the bottom by the next frame.
 *
 * Coalescing on `requestAnimationFrame` fixes all three at once: at most one
 * measurement and one scroll per painted frame, instant rather than animated,
 * and skipped entirely when the reader has scrolled away. `PIN_SLACK_PX` is
 * how far from the bottom still counts as "following" - a couple of rows, so a
 * one-pixel wheel nudge does not un-pin the log.
 */
const PIN_SLACK_PX = 120
let followHandle = 0

function follow(): void {
  if (props.collapsed || followHandle) return
  const raf = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : null
  const run = () => {
    followHandle = 0
    const element = list.value
    if (!element || typeof element.scrollTo !== 'function') return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    if (distance > PIN_SLACK_PX) return
    element.scrollTo({ top: element.scrollHeight, behavior: 'auto' })
  }
  if (!raf) {
    run()
    return
  }
  followHandle = raf(run)
}

onBeforeUnmount(() => {
  if (followHandle && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(followHandle)
})

watch(() => props.entries.length, () => follow())

/**
 * The seed this row's character is drawn from.
 *
 * The store first, the row's own identity second. The fallback matters for a
 * row the store has never heard of - a frame for a node outside the descriptor,
 * or a rail mounted in a spec with no run behind it - and it is the row's own
 * resolved identity rather than a placeholder, because a system whose strangers
 * look broken punishes the author of every flow it has not seen.
 */
function seedOf(entry: ChatEntry): string {
  const fromStore = entry.nodeId && props.identityOf ? props.identityOf(entry.nodeId) : ''
  return fromStore || entry.identity
}

function poseOf(entry: ChatEntry): PipState {
  return (entry.nodeId && props.stateOf ? props.stateOf(entry.nodeId) : undefined) ?? 'idle'
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
        v-for="row in rows"
        :key="row.entry.id"
        v-memo="[row]"
        class="trace-entry"
        data-testid="trace-entry"
        :class="[`is-${row.entry.variant}`, { 'is-system': !row.entry.identity }]"
        :data-node="row.entry.nodeId"
        :data-identity="row.entry.identity"
        :data-tone="row.entry.tone"
      >
        <!--
          The character's slot, and the character is in it.

          It held two initials before, which is what a rail does when it has no
          cast: `MA` and `MO` are two letters apart at 32px and told a reader
          nothing they could not get from the name printed beside them. The Pip
          is the same figure standing on that node's card - same store, same
          seed, same pose - so the trace and the graph are one view of one run
          rather than two lists that happen to be about it.

          `data-character-seed` and `data-character` stay on the WRAPPER because
          `traceInterpretation.spec.ts` pins them there; the seed the tie-in is
          checked against is the Pip's own `data-character`, one level in.
        -->
        <!--
          A person, not a cast member. Same decision as the graph's, in the same
          words: a gate is somebody being asked for something, and giving that
          turn a character would be the one place this console claimed an agent
          did work a human did. The mark is the amber the gate card and the
          waiting node already use, so the three read as one state.
        -->
        <span
          v-if="row.you"
          class="trace-avatar is-you"
          data-testid="trace-you"
          aria-hidden="true"
        >
          <UserRound :size="18" :stroke-width="2" />
        </span>
        <span
          v-else-if="row.entry.identity"
          class="trace-avatar"
          data-testid="trace-avatar"
          :data-character-seed="row.entry.identity"
          :data-character="characterIndexOf(row.entry)"
          :style="avatarStyle(row.entry)"
          aria-hidden="true"
        >
          <AgentCharacter :identity="row.seed" :state="row.pose" :size="32" :label="row.entry.actor" />
        </span>

        <div class="trace-content">
          <div class="trace-meta">
            <strong>{{ row.entry.actor }}</strong>
            <time class="panel-meta" :datetime="row.entry.timestamp">{{ row.entry.timestamp }}</time>
          </div>
          <div class="trace-bubble">
            <p class="trace-line" data-testid="trace-line">{{ row.entry.message }}</p>

            <!--
              Collapsed by default, and a native `<details>` rather than a
              toggled div: it is keyboard reachable, it is announced as an
              expandable region, and it costs no state in this component - which
              matters when 200 of them are in the DOM.
            -->
            <details class="trace-raw">
              <summary>Details</summary>
              <dl class="trace-raw-facts">
                <div><dt>Event</dt><dd>{{ row.entry.raw.kind }} · {{ row.entry.raw.eventType }}</dd></div>
                <div><dt>Sequence</dt><dd>{{ row.entry.raw.seq }}</dd></div>
                <div v-if="row.entry.raw.model"><dt>Model</dt><dd>{{ row.entry.raw.model }}</dd></div>
                <div v-if="row.entry.raw.tool"><dt>Tool</dt><dd>{{ row.entry.raw.tool }}</dd></div>
                <div v-if="row.entry.raw.durationMs !== undefined">
                  <dt>Took</dt><dd>{{ row.entry.raw.durationMs }}ms</dd>
                </div>
                <div v-if="tokenNote(row.entry)" data-testid="trace-tokens">
                  <dt>Tokens</dt><dd>{{ tokenNote(row.entry) }}</dd>
                </div>
                <!--
                  How many times this exact line came in a row. In the
                  disclosure and never in the sentence: the sentence is what
                  happened and the count is a fact about the log, and a reader
                  scanning for the failure should not have to read past a
                  multiplier to find it.
                -->
                <div v-if="(row.entry.repeats ?? 1) > 1" data-testid="trace-repeats">
                  <dt>Reported</dt><dd>{{ row.entry.repeats }}&times;</dd>
                </div>
              </dl>
              <p class="trace-raw-message">{{ row.entry.raw.message }}</p>
              <pre data-testid="trace-raw">{{ row.entry.raw.details }}</pre>
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
  /* NO `backdrop-filter` here, and its removal is a measurement rather than a
     taste (T2.8). `--surface-overlay` is 94% opaque in the dark theme and 95%
     in the light one, so a 12px blur of what is behind this rail contributes
     about a twentieth of each pixel - and it costs the compositor a blur of the
     whole rail's backdrop every time the rail's own content changes, which on
     this surface is every frame of a run. The two other rails keep theirs in
     `studio.css`; neither of them repaints per frame. */
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
/* `--on-accent-cyan`, not `--accent-cyan`: the raw accent measures 1.29:1 on
   the rail in the light theme (T3.3), because a colour chosen to glow on a
   dark ground is nearly white on paper. The `--on-*` pair is the same hue
   with a light-theme value that carries ink. */
.section-kicker { color: var(--on-accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); }
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
  /* The other half of the seam: the first trace row starts a clear gap below
     the dialogue block's border rather than a hairline under it, so the two
     regions read as two. `--space-6` rather than the 14px that was here,
     because the value is a token or it does not exist. */
  padding: var(--space-6) 14px 28px;
  scrollbar-color: color-mix(in srgb, var(--accent-cyan) 30%, transparent) transparent;
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
  margin-bottom: 10px;
  content-visibility: auto;
  contain-intrinsic-size: auto 58px;
}

/* A row about the operator wears the amber the gate card and the waiting node
   already use, on the same neutral ground every avatar stands on. `--warn-text`
   rather than a character colour, because the colour has to say "a person" and
   not "which agent". */
.trace-avatar.is-you {
  color: var(--warn-text);
  background: var(--warn-bg);
  box-shadow: inset 0 0 0 1px var(--warn-border);
}

.trace-entry.is-system { display: block; }

/* The GROUND a character stands on, not the mark itself.

   It was a filled disc in the node's own palette colour with two initials on
   top; the Pip carries that colour in its own body, so a filled disc behind it
   would be the same colour twice and the silhouette - the whole of the identity
   at 32px - would disappear into it. Same decision, same reason, as
   `.node-character.has-pip` in `motion.css` and `.crew-medallion` in the stage
   lane, and it is one decision in three places rather than three.

   `--character-color` is deliberately no longer read here. A palette entry
   measured 3.89-4.47:1 against the rail's ground in the light theme, which is
   under AA for anything carrying text - and now that nothing here is text, the
   colour belongs to the figure and not to the box around it.

   The inline `--character-color` binding is still WRITTEN, and that is not an
   oversight: it is pinned by an existing spec, and it is still the colour of
   the lucide medallion on the node kinds that keep an icon instead of a
   character (router, gate, output, step). One property, two readers, and this
   is no longer one of them. */
.trace-avatar {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  background: var(--bg-node);
  border-radius: var(--r-full);
}

.trace-content { min-width: 0; }
/*
 * THE COMPACT ROW, adopted from the dialogue rail 2026-09-05.
 *
 * avatar | name · time | one line | Details. What went is the BOX: every row
 * used to be a bubble - a raised background, a one-pixel border and a 12px
 * corner - and a hundred and thirty bubbles down a 320px rail is a column of
 * boxes rather than a transcript. A bubble is the right shape for a chat with
 * two sides to distinguish; this rail has one side and a name on every row, so
 * the border was drawing a distinction that does not exist.
 *
 * What replaces it is a hairline BETWEEN rows: one pixel per row instead of
 * four sides, so the eye gets the rhythm and the sentence gets the width. The
 * two rails now read as one surface, which is what they are - they sit in the
 * same column and divide the same frames between them.
 *
 * The tone tints stay, because they are the only thing that is not decoration:
 * a warning and an error have to be findable in a long scroll. They move from
 * a filled bubble to the TEXT plus a marker on the row's leading edge, which
 * survives at a glance and costs no box.
 */
.trace-meta { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin: 0 0 3px; }
.trace-meta strong { overflow: hidden; color: var(--text-muted); font-size: var(--fs-11); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
/* `.panel-meta` is W5's global for exactly this - a timestamp beside a name -
   and its token is `--text-meta`, which is the one that passes in both themes. */
.trace-meta time { flex: 0 0 auto; }

.trace-bubble { padding: 0; color: var(--text-body); font-size: var(--fs-12); line-height: 1.5; background: none; border: 0; border-radius: 0; }
.trace-bubble p { margin: 0; overflow-wrap: anywhere; }

/* The hairline is on the ROW rather than on the bubble, so the avatar column is
   inside it and the rhythm is the whole row's. `:last-child` keeps the list
   from ending on a rule that separates nothing. */
.trace-entry { padding-bottom: 10px; border-bottom: 1px solid var(--border-default); }
.trace-entry:last-child { border-bottom: 0; }

.is-system .trace-line { color: var(--text-muted); }
.is-warning .trace-line { color: var(--warn-text); }
.is-error .trace-line { color: var(--err-text); }
/* The leading edge, for the two tones a reader scrolls back to find. A 2px
   rule in the gap the grid already leaves, so nothing reflows. */
.trace-entry.is-warning { box-shadow: inset 2px 0 0 var(--warn-border); padding-left: 8px; }
.trace-entry.is-error { box-shadow: inset 2px 0 0 var(--err-border); padding-left: 8px; }

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
