<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AgentCharacter from './AgentCharacter.vue'
import type { PipState } from '../characters/pip'
import type { RunStatus } from '../types/studio'
import { ChevronDown, ChevronUp, MessagesSquare, Scissors } from 'lucide-vue-next'
import { TERMINAL, collapsedPreview, type DialogueEntry } from '../composables/useRunChoreography'
import { readSpeech, renderSpeech, type Speech } from '../trace/speech'
import { humaniseTask } from '../utils/humanise'
import { MAX_UTTERANCE_CHARS } from '../data/serverLimits'

/**
 * What the agents actually SAID.
 *
 * `ChatRail` keeps the trace - the kicker, the tool chips, the warnings, the
 * mechanics of a run - and it is good at that. What it never carried is the
 * one thing an operator watching a multi-agent run most wants: the model's
 * output. Its `message` is the backend's one-line frame text verbatim, a
 * `CallChip` carries a model name and a duration, and stream chunks were
 * dropped outright, so no prompt, no response and no tool argument was rendered
 * anywhere on the page.
 *
 * TWO DIFFERENCES FROM THE REFERENCE, and both are visible in a recording:
 *
 * 1. The reference reveals nothing. A bubble lands whole at `NODE_END`
 *    (`docs/chatdev-notes.md` §2). Here a streamed answer arrives as it
 *    streams, and an unstreamed one is revealed at 120 characters a second -
 *    so the rail reads as speech rather than as a log appending.
 * 2. Its chat avatars never match its graph, because the chat path omits the
 *    node id (`LaunchView.vue:960`). Here the avatar is
 *    `--character-<n>` for the same `n` the node's medallion and its handoff
 *    token wear, computed from the node id by a pure function.
 *
 * COLLAPSE IS KEYED ON RECENCY, not on length. The reference's
 * `CollapsibleMessage` collapses anything long, which hides exactly the entry
 * somebody is reading when a model is verbose. Everything but the last three
 * collapses here, so what is on screen is what just happened and the history
 * is one click away.
 */

const props = defineProps<{
  entries: DialogueEntry[]
  collapsed: boolean
  /** Node id -> character index, so the avatar's ground matches the card. */
  characterOf: (nodeId: string) => number
  /**
   * Node id -> the identity the RUN resolved, and the pose it is in.
   *
   * Optional, and asked of the STORE rather than taken from `entry.role`. A
   * dialogue entry's role is whatever the speakers map held when its utterance
   * landed, so an entry produced before the node's first `agent_role` carries
   * the label instead - two seeds for one agent. The store answers with the
   * first role it ever saw and never changes it, which is what makes the
   * character here provably the one on that node's card (T2.6).
   */
  identityOf?: (nodeId: string) => string
  stateOf?: (nodeId: string) => PipState
  /**
   * The run's status, so the rail can land at its end when the run stops.
   *
   * Optional: a rail mounted with entries alone still follows a reveal, it
   * simply never gets the terminal nudge. The comparison uses the choreography's
   * own `TERMINAL` rather than a fourth copy of the same three words.
   */
  status?: RunStatus
}>()

const emit = defineEmits<{ toggle: [] }>()

const list = ref<HTMLElement | null>(null)
/** Entries the reader has opened by hand, which recency must not re-close. */
const opened = ref(new Set<string>())

/**
 * Follow the newest entry, but only while it is the newest.
 *
 * Watched on the REVEALED length as well as the count, because an entry
 * revealing at 120 chars/second grows for seconds after it arrives and a rail
 * that scrolled only on arrival would leave the sentence being spoken below the
 * fold for the whole of it.
 */
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

/**
 * Whether the scroller is at its end, published on the root as a class and an
 * attribute.
 *
 * On the ROOT and not on the list, because the affordance it gates is a
 * `::after` and a pseudo-element on a scroll box scrolls away with the content
 * - the fade has to be painted by the element that CLIPS, not by the one that
 * moves. The attribute rides along so a spec can read the state without a
 * layout engine.
 */
const atEnd = ref(true)

function measureEnd(): void {
  const element = list.value
  if (!element) return
  atEnd.value = element.scrollHeight - element.scrollTop - element.clientHeight <= 1
}

/**
 * Land at the end, at most once per animation frame.
 *
 * `force` is the terminal case and it ignores the pin. That is a deliberate
 * asymmetry with the reveal, which must never yank a reader who has scrolled
 * up: a run STOPPING is one event, not a stream of them, and the newest entry
 * is the run's conclusion. Two cold readers met the alternative - a finished
 * run whose last entry was cut mid-sentence with a bare "Details" below it,
 * because the list had been left wherever the reveal's pin last allowed.
 */
function follow(force = false): void {
  if (props.collapsed || followHandle) return
  const raf = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : null
  const run = () => {
    followHandle = 0
    const element = list.value
    if (!element || typeof element.scrollTo !== 'function') return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    if (!force && distance > PIN_SLACK_PX) return
    element.scrollTo({ top: element.scrollHeight, behavior: 'auto' })
    // jsdom does not move `scrollTop` for a `scrollTo`, and a real browser does
    // not report the new position until the scroll lands, so the flag is set
    // from the intent rather than read back from the box.
    atEnd.value = true
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

// The first measurement, so a rail that opens already overflowing shows the
// affordance rather than waiting for the reader to scroll it once.
onMounted(measureEnd)

/*
 * Watched on the REVEALED length as well as the count, because an entry
 * revealing at 120 chars/second grows for seconds after it arrives and a rail
 * that scrolled only on arrival would leave the sentence being spoken below the
 * fold for the whole of it. That is also why the coalescing above matters more
 * here than in the trace: this watcher fires on every `requestAnimationFrame`
 * step of a reveal, and reading `scrollHeight` in each one is a forced layout
 * sixty times a second.
 */
watch(
  () => [props.entries.length, props.entries.at(-1)?.revealed ?? 0] as const,
  () => follow(),
)

/*
 * The run stopped: land at the end whatever the reveal left behind, so the
 * newest entry and its `Details` toggle are whole. Watched on the STATUS
 * crossing into terminal rather than on the last frame, because a run can stop
 * on a frame that adds no entry at all - a cancel, or an error after the last
 * thing anybody said.
 */
watch(
  () => props.status,
  (next, previous) => {
    if (!next || next === previous) return
    if (!TERMINAL.includes(next)) return
    follow(true)
  },
)

/**
 * What each entry IS, decided once per entry rather than in the template.
 *
 * `readSpeech` is where the three shapes an `utterance` frame can carry get
 * told apart - see `trace/speech.ts`. The one that matters here is the third:
 * a guardrail LLM's `{"valid":true,"feedback":null}` was being rendered as
 * something an agent said, in a rail whose entire subject is speech. It is a
 * machine answering a machine; it gets one line and its object behind the
 * disclosure.
 */
/**
 * `readSpeech` per entry, cached by the ENTRY OBJECT (T2.8).
 *
 * An entry's `text` is fixed once its utterance lands; what changes afterwards
 * is `revealed`, and `advanceReveal` only replaces the objects that moved. So
 * object identity is an exact key, and without it this parsed every entry's
 * whole text on every reveal tick - sixty times a second, for entries nobody
 * had touched in a minute.
 */
const speechCache = new Map<string, { entry: DialogueEntry; speech: Speech }>()

const read = computed(() =>
  props.entries.map((entry) => {
    const cached = speechCache.get(entry.callId)
    if (cached && cached.entry === entry) return cached.speech
    const speech = readSpeech(entry.text)
    speechCache.set(entry.callId, { entry, speech })
    return speech
  }),
)

/**
 * The newest thing anybody actually SAID, which a structured result may not
 * push out of view.
 *
 * `collapsed` is decided upstream over every entry, so three guardrail answers
 * in a row are enough to fold the last real utterance - the exact failure the
 * recency rule exists to prevent, arriving through a shape that is not speech.
 * One clause, and it can only ever open a row that speech is in.
 */
const newestProseId = computed(() => {
  for (let index = props.entries.length - 1; index >= 0; index -= 1) {
    if (read.value[index].kind === 'prose') return props.entries[index].callId
  }
  return ''
})

/**
 * One row, and the SAME object back while nothing about it has moved (T2.8).
 *
 * The expensive part is `renderSpeech`, which escapes and marks up the visible
 * slice. It ran for EVERY entry on every recompute, and a recompute happens on
 * every reveal tick - `advanceReveal` is driven by `requestAnimationFrame`, so
 * sixty times a second the rail re-rendered the markdown of every line anybody
 * had ever said. Only one entry is ever revealing; the rest are finished text
 * whose markup cannot have changed.
 *
 * The cache key is the entry OBJECT plus the two things outside it that the row
 * draws: whether it is open, and the character's seed and pose. `v-memo="[row]"`
 * in the template then skips an unchanged row entirely, and the key is honest
 * because everything rendered is either in the row or derived from it.
 */
interface SpokenRow {
  entry: DialogueEntry
  speech: Speech
  structured: boolean
  open: boolean
  preview: string
  visible: string
  html: string
  seed: string
  pose: PipState
  /** The task in words - `market_task` -> "Market". '' when none was named. */
  task: string
}

const rowCache = new Map<string, SpokenRow>()

const shown = computed<SpokenRow[]>(() =>
  props.entries.map((entry, index) => {
    const speech = read.value[index]
    const open =
      opened.value.has(entry.callId) ||
      !entry.collapsed ||
      entry.callId === newestProseId.value
    const seed = seedOf(entry)
    const pose = poseOf(entry)
    const cached = rowCache.get(entry.callId)
    if (
      cached
      && cached.entry === entry
      && cached.speech === speech
      && cached.open === open
      && cached.seed === seed
      && cached.pose === pose
    ) {
      return cached
    }
    // `task` is derived from `entry` and needs no key of its own: the entry
    // object is replaced whenever anything about it changes, and identity
    // above already covers that.

    // Reveal is a float so the reveal can advance by fractions of a character
    // between frames; the slice is where it becomes text.
    const visible = speech.text.slice(0, Math.floor(entry.revealed))
    const row: SpokenRow = {
      entry,
      speech,
      structured: speech.kind === 'structured',
      open,
      preview: collapsedPreview(speech.text),
      visible,
      // Escape-first: every character is escaped BEFORE any structure is
      // recognised, so model output cannot become markup. See CLAUDE.md's note
      // on why the renderer is not `marked` + `dompurify`.
      html: renderSpeech(visible),
      seed,
      pose,
      // `market_task` -> "Market", `scoping_task` -> "Scoping". The identifier
      // is CrewAI's, and the rail was showing it raw and then cutting it in
      // half at 330px - `scoping_ta…`, which is neither the name nor a word.
      task: humaniseTask(entry.task),
    }
    rowCache.set(entry.callId, row)
    return row
  }),
)

/** The trim note's number, from the constant that mirrors the server's. */
const trimmedAt = MAX_UTTERANCE_CHARS.toLocaleString()

function toggle(callId: string): void {
  const next = new Set(opened.value)
  next.has(callId) ? next.delete(callId) : next.add(callId)
  opened.value = next
}

function avatarStyle(nodeId: string): Record<string, string> {
  return { '--character-color': `var(--character-${props.characterOf(nodeId)})` }
}

/**
 * The seed this entry's character is drawn from.
 *
 * The store first, the entry's own role second - the fallback is for a rail
 * mounted with no run behind it, and it is the role rather than a placeholder
 * because a stranger should look like an ordinary agent, not like a defect.
 */
function seedOf(entry: DialogueEntry): string {
  const fromStore = entry.nodeId && props.identityOf ? props.identityOf(entry.nodeId) : ''
  return fromStore || entry.role
}

function poseOf(entry: DialogueEntry): PipState {
  return (entry.nodeId && props.stateOf ? props.stateOf(entry.nodeId) : undefined) ?? 'idle'
}

function clock(at: number): string {
  return new Date(at).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
</script>

<template>
  <section
    class="dialogue-rail"
    :class="{ 'is-collapsed': collapsed, 'is-at-end': atEnd }"
    :data-at-end="atEnd ? 'true' : 'false'"
    aria-label="Agent dialogue"
  >
    <button
      class="dialogue-head"
      type="button"
      data-testid="dialogue-toggle"
      :aria-expanded="!collapsed"
      @click="emit('toggle')"
    >
      <MessagesSquare :size="14" aria-hidden="true" />
      <span class="section-kicker">WHAT THE CREW SAID</span>
      <span class="dialogue-count" aria-live="polite">{{ entries.length }}</span>
      <ChevronDown v-if="collapsed" :size="15" aria-hidden="true" />
      <ChevronUp v-else :size="15" aria-hidden="true" />
    </button>

    <!--
      `role="log"` and `aria-relevant="additions text"`: a progressive reveal is
      a TEXT change to an element already in the tree, not an addition, so
      without `text` a screen reader would announce the empty bubble and then go
      silent for the whole sentence.
    -->
    <div
      v-show="!collapsed"
      ref="list"
      class="dialogue-list"
      data-testid="dialogue-list"
      @scroll.passive="measureEnd"
      tabindex="0"
      role="log"
      aria-live="polite"
      aria-relevant="additions text"
    >
      <p v-if="!entries.length" class="dialogue-empty">
        Nothing said yet. Model output appears here as it arrives.
      </p>

      <article
        v-for="row in shown"
        :key="row.entry.callId"
        v-memo="[row]"
        class="dialogue-entry"
        :class="{ 'is-folded': !row.open, 'is-structured': row.structured }"
        :data-node="row.entry.nodeId"
        :data-identity="row.entry.role"
      >
        <!--
          The character, where two initials used to be. Same store, same seed
          and same pose as the node's card and as the trace row for the same
          frame, so following one agent across three surfaces is following one
          figure. `data-character` and `data-character-seed` stay on the WRAPPER
          because existing specs pin them there; the seed the tie-in is checked
          against is the Pip's own `data-character`, one level in.
        -->
        <span
          class="dialogue-avatar"
          data-testid="dialogue-avatar"
          :data-character="characterOf(row.entry.nodeId)"
          :data-character-seed="row.entry.role"
          :style="avatarStyle(row.entry.nodeId)"
          aria-hidden="true"
        >
          <AgentCharacter :identity="row.seed" :state="row.pose" :size="32" :label="row.entry.role" />
        </span>

        <div class="dialogue-body">
          <!--
            TWO LINES, and the name owns the first one.

            It was one flex row - name, task chip, time - with the name
            ellipsised at whatever was left. Every real role this product has
            is three or four words ("Startup validation scoper", "Market
            evidence analyst"), so at a 330px rail the name was the thing being
            cut, which is exactly backwards: the name is who is speaking and
            the task is a detail about what they are speaking about. A name is
            also the one string here that must never be truncated - two agents
            can share a prefix, and "Startup validation…" names both.

            So the name takes the full width and may wrap to two lines, the
            time stays pinned right on the same baseline, and the task drops to
            a muted second line where it has room to be a whole word.
          -->
          <header class="dialogue-meta">
            <strong>{{ row.entry.role }}</strong>
            <time class="dialogue-time">{{ clock(row.entry.at) }}</time>
          </header>
          <p v-if="row.task" class="dialogue-task panel-meta">{{ row.task }}</p>

          <!--
            NOT speech. A guardrail LLM answering `{"valid":true,...}` is a
            machine talking to a machine, and rendering it in a bubble beside
            what the crew said is how a rail whose whole subject is speech ended
            up showing JSON. One line, and the object is one click away.
          -->
          <template v-if="row.structured">
            <p class="dialogue-structured" data-testid="dialogue-structured">
              {{ row.entry.role }} returned a structured result
            </p>
            <details class="dialogue-raw">
              <summary>Details</summary>
              <pre data-testid="dialogue-payload">{{ row.speech.payload }}</pre>
            </details>
          </template>

          <button
            v-else-if="!row.open"
            class="dialogue-fold"
            type="button"
            data-testid="dialogue-fold"
            :aria-expanded="false"
            @click="toggle(row.entry.callId)"
          >{{ row.preview }}</button>

          <template v-else>
            <!--
              `v-html` over `renderSpeech`, which escapes every character BEFORE
              it recognises any structure - so there is no path by which model
              output becomes markup. The models write Markdown; a rail showing
              `**the point**` with the asterisks is showing the wire format.
              `.markdown-body` is global rather than scoped for the reason
              CLAUDE.md gives: Vue's scoped attribute never reaches injected
              HTML, so a scoped selector would match nothing.
            -->
            <div
              class="dialogue-text markdown-body"
              data-testid="dialogue-text"
              v-html="row.html"
            />
            <button
              v-if="row.entry.collapsed"
              class="text-button"
              type="button"
              :aria-expanded="true"
              @click="toggle(row.entry.callId)"
            >Show less</button>
            <!--
              The server clipped this at `MAX_UTTERANCE_CHARS`. Saying so is the
              difference between an answer that ends mid-sentence for a reason
              and one that just ends - and the full text is already in the run's
              NDJSON export, so this names where it went.
            -->
            <p v-if="row.entry.truncated" class="dialogue-trimmed" data-testid="dialogue-trimmed">
              <Scissors :size="11" aria-hidden="true" />
              trimmed to {{ trimmedAt }} characters — the whole of it is in the run log
            </p>
            <!--
              The cost of the entry, and it is a detail rather than the entry.
              `5168 in · 3994 out` on every visible row is the same failure as
              the trace's raw payloads: true, unreadable, and in front of the
              thing somebody came to read.
            -->
            <details class="dialogue-raw">
              <summary>Details</summary>
              <p class="dialogue-tokens" data-testid="dialogue-tokens">
                {{ row.entry.tokens.prompt.toLocaleString() }} in ·
                {{ row.entry.tokens.completion.toLocaleString() }} out
              </p>
            </details>
          </template>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
/*
 * A row of `.graph-workspace`'s grid, like the stage lane above it, and NOT an
 * overlay. The console already learned this once: the crew strip shipped as
 * `position: absolute` and sat directly on top of the two nodes it exists to
 * narrate. A rail that covered the bottom of the canvas would do the same to
 * whatever is running last.
 */
.dialogue-rail {
  position: relative;
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  /* The band the scroll box's cut edge stops inside. See `.dialogue-list`.
     It is NOT the seam - a padding inside a scroll box scrolls away with the
     content, and `ChatRail.vue`'s `.rail-list` carries the border that is. */
  padding-bottom: var(--space-2);
  background: var(--surface-well);
  border-bottom: 1px solid var(--border-default);
}

/*
 * THE CUT EDGE, MARKED.
 *
 * The list is capped at `40vh`, so when the transcript is longer than that its
 * last visible entry is cut - and two cold readers read that cut as a defect
 * rather than as "there is more below", because nothing said which it was. A
 * 24px fade over the bottom of the scroller says it.
 *
 * On the ROOT's `::after` and not the list's, because a pseudo-element on a
 * scroll box scrolls with the content: it would sit at the bottom of the
 * TRANSCRIPT rather than at the bottom of the WINDOW onto it. `--fade-soft` is
 * the token the shell already fades with, and the affordance is gone the moment
 * the list is at its end, which is where a finished run now lands.
 */
.dialogue-rail::after {
  position: absolute;
  right: 0;
  bottom: var(--space-2);
  left: 0;
  height: 24px;
  content: '';
  background: linear-gradient(to bottom, transparent, var(--fade-soft));
  pointer-events: none;
  transition: opacity var(--motion-fast) var(--ease-out);
}

.dialogue-rail.is-at-end::after,
.dialogue-rail.is-collapsed::after { opacity: 0; }

.dialogue-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  color: var(--text-muted);
  background: transparent;
  border: 0;
  cursor: pointer;
}

.dialogue-head:hover { color: var(--text-title); }
.dialogue-head:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: -2px; }
/* `--on-accent-cyan`, not `--accent-cyan`: the raw accent measures 1.29:1 on
   the rail in the light theme (T3.3), because a colour chosen to glow on a
   dark ground is nearly white on paper. The `--on-*` pair is the same hue
   with a light-theme value that carries ink. */
.section-kicker { color: var(--on-accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); }
.dialogue-count {
  min-width: 22px;
  margin-left: auto;
  padding: 2px 6px;
  color: var(--text-muted);
  text-align: center;
  font: 600 var(--fs-11)/1 var(--font-mono);
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
}

/* Capped rather than free-growing: this shares a grid row with the canvas, and
   a rail that grew with the transcript would squeeze the graph out of the page
   over the course of a long run. */
/*
 * Capped, and the cap is a judgement about the column rather than about the
 * transcript. This shares a 330px rail with the trace, and a dialogue that grew
 * with the run would push the trace off the bottom - which is the same defect
 * one level down from the one that moved this rail out of the canvas.
 *
 * `40vh` and not a pixel value, because the two things sharing this column
 * scale with the window and a fixed cap that is generous at 1440 tall is most
 * of the rail at 800.
 */
.dialogue-list {
  max-height: 40vh;
  min-height: 0;
  flex: 0 1 auto;
  overflow: auto;
  /*
   * THE BOTTOM PADDING IS THE SEAM, and a cold reader found it: the last thing
   * in a dialogue entry is its `▸ Details` summary, and at the cap this box cut
   * it in half against the border - so the half-line read as the trace list
   * below overlapping the dialogue above. Nothing overlaps; a scroll container
   * was ending flush, one pixel from another region's first row, which is what
   * a rendering fault looks like.
   *
   * 12px was not enough because it is INSIDE the scroll box: it spaces the
   * content when the reader is at the end and does nothing at any other scroll
   * position, which is where a half-row is cut. The band below is outside the
   * scroller (`.dialogue-rail`'s own padding), so the cut edge is always inset
   * from the boundary and a partial row reads as "there is more here" rather
   * than as two regions colliding.
   */
  padding: 4px 14px 12px;
  scrollbar-color: color-mix(in srgb, var(--accent-cyan) 30%, transparent) transparent;
}

.dialogue-empty { margin: 8px 0; color: var(--text-40); font-size: var(--fs-12); }

/* 32px, matching the trace rail's column: the two rails sit in one stack and a
   character that changed size between them would read as a different mark. */
.dialogue-entry { display: grid; grid-template-columns: 32px minmax(0, 1fr); gap: 9px; margin-bottom: 10px; }
.dialogue-entry.is-folded { margin-bottom: 5px; }

/* The ground, not the mark. See `.trace-avatar` in `ChatRail.vue` for the
   reasoning; it is one decision applied in three places (here, the trace rail
   and `.node-character.has-pip`) rather than three. `--character-color` is no
   longer read: the Pip carries the palette colour in its own body, and a
   palette entry under text measured 3.89-4.47:1 in the light theme.

   The inline `--character-color` binding is still WRITTEN, and that is not an
   oversight: it is pinned by an existing spec, and it is still the colour of
   the lucide medallion on the node kinds that keep an icon instead of a
   character (router, gate, output, step). One property, two readers, and this
   is no longer one of them. */
.dialogue-avatar {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  background: var(--bg-node);
  border-radius: var(--r-full);
}

.dialogue-body { min-width: 0; }
.dialogue-meta { display: flex; align-items: baseline; gap: 8px; }
/* `min-width: 0` so the name may shrink inside the flex row, and NO
   `text-overflow`: it wraps instead. `overflow-wrap: anywhere` is the guard
   against the one string that cannot wrap on a space - a single unbroken
   sixty-character role - which would otherwise widen the rail rather than
   fold. */
.dialogue-meta strong {
  min-width: 0;
  flex: 1 1 auto;
  overflow-wrap: anywhere;
  color: var(--text-title);
  font: 600 var(--fs-12)/1.3 var(--font-body);
}
/* Second line, and `.panel-meta` in the markup carries the colour and the type
   role - W5's global for exactly this, so the two rails say a quiet fact the
   same way. What is left here is the spacing and the one rule that matters:
   a chip is never cut mid-word. */
.dialogue-task {
  margin: 2px 0 0;
  overflow-wrap: anywhere;
  text-overflow: clip;
  white-space: normal;
}
.dialogue-time { flex: 0 0 auto; margin-left: auto; color: var(--text-meta); font: 400 10px/1.3 var(--font-mono); }

/*
 * No `white-space: pre-wrap` any more, and its absence is the fix rather than a
 * simplification: the text is rendered as Markdown now, so paragraphs are
 * paragraphs and a `json.dumps`ed response's literal backslash-n is resolved
 * before it ever reaches the DOM. Preserving whitespace here would put the wire
 * format back on screen one layer down.
 */
.dialogue-text {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
  color: var(--text-body);
  font-size: var(--fs-12);
  line-height: 1.55;
}

/*
 * `.markdown-body` is sized for the REPORT - 14px body, 22/18/15px headings,
 * 0.9em paragraph gaps - and this is a 330px rail sharing a column with the
 * trace. `:deep()` and not a scoped selector, for the reason `studio.css`
 * already records: Vue's scoped data attribute is never applied to HTML
 * injected with `v-html`, so a plain scoped rule would match nothing at all.
 */
.dialogue-text :deep(h1),
.dialogue-text :deep(h2),
.dialogue-text :deep(h3),
.dialogue-text :deep(h4) { margin: 0.8em 0 0.3em; font-size: var(--fs-12); }
.dialogue-text :deep(p) { margin: 0 0 0.55em; }
.dialogue-text :deep(*:last-child) { margin-bottom: 0; }
.dialogue-text :deep(ul),
.dialogue-text :deep(ol) { margin: 0 0 0.55em; padding-left: 16px; }
.dialogue-text :deep(li) { margin-bottom: 0.2em; }
.dialogue-text :deep(pre) { margin: 0 0 0.55em; padding: 6px 8px; font-size: 10px; }
.dialogue-text :deep(table) { font-size: 10px; }
.dialogue-text :deep(hr) { margin: 0.7em 0; }

.dialogue-structured {
  margin: 4px 0 0;
  color: var(--text-40);
  font: 400 var(--fs-11)/1.5 var(--font-body);
  font-style: italic;
}

.dialogue-raw { margin-top: 5px; }
.dialogue-raw > summary {
  color: var(--text-40);
  font: 600 10px/1.3 var(--font-body);
  cursor: pointer;
  list-style: none;
}
.dialogue-raw > summary::-webkit-details-marker { display: none; }
.dialogue-raw > summary::before { content: '▸ '; }
.dialogue-raw[open] > summary::before { content: '▾ '; }
.dialogue-raw > summary:hover { color: var(--text-muted); }
.dialogue-raw > summary:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 2px; }
.dialogue-raw pre {
  max-height: 180px;
  margin: 5px 0 0;
  overflow: auto;
  padding: 6px 7px;
  color: var(--text-muted);
  font: 400 10px/1.45 var(--font-mono);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: var(--surface-raised);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
}

/* A folded entry is a BUTTON and not a clipped paragraph, so the whole line is
   the target and a keyboard reaches it. One line, ellipsised by the composable
   rather than by CSS, so the DOM says what is on screen. */
.dialogue-fold {
  display: block;
  width: 100%;
  margin: 3px 0 0;
  padding: 0;
  overflow: hidden;
  color: var(--text-40);
  text-align: left;
  font: 400 var(--fs-11)/1.4 var(--font-body);
  white-space: nowrap;
  background: none;
  border: 0;
  text-overflow: ellipsis;
  cursor: pointer;
}

.dialogue-fold:hover { color: var(--text-muted); }
.dialogue-fold:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 2px; }

/* `--link-strong`, not `--link-cyan`: the latter measures 4.41:1 on a well in
   the light theme and the bar for body-sized text is 4.5 (T3.3). `tokens.css`
   carries the pair and says so. */
.text-button { margin-top: 5px; padding: 0; color: var(--link-strong); background: none; border: 0; font: 600 var(--fs-11)/1.3 var(--font-body); cursor: pointer; }

.dialogue-trimmed { display: flex; align-items: center; gap: 4px; margin: 5px 0 0; color: var(--warn-text); font: 500 10px/1.3 var(--font-mono); }
.dialogue-tokens { margin: 5px 0 0; color: var(--text-muted); font: 500 10px/1.2 var(--font-mono); font-variant-numeric: tabular-nums; }

@media (max-width: 860px) {
  .dialogue-list { max-height: 30vh; }
}
</style>
