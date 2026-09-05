<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ChevronDown, ChevronUp, MessagesSquare, Scissors } from 'lucide-vue-next'
import { collapsedPreview, type DialogueEntry } from '../composables/useRunChoreography'
import { readSpeech, renderSpeech } from '../trace/speech'
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
  /** Node id -> character index, so the avatar matches the card. */
  characterOf: (nodeId: string) => number
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
watch(
  () => [props.entries.length, props.entries.at(-1)?.revealed ?? 0] as const,
  async () => {
    if (props.collapsed) return
    await nextTick()
    list.value?.scrollTo({ top: list.value.scrollHeight, behavior: 'auto' })
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
const read = computed(() => props.entries.map((entry) => readSpeech(entry.text)))

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

const shown = computed(() =>
  props.entries.map((entry, index) => {
    const speech = read.value[index]
    // Reveal is a float so the reveal can advance by fractions of a character
    // between frames; the slice is where it becomes text.
    const visible = speech.text.slice(0, Math.floor(entry.revealed))
    return {
      entry,
      speech,
      structured: speech.kind === 'structured',
      open:
        opened.value.has(entry.callId) ||
        !entry.collapsed ||
        entry.callId === newestProseId.value,
      preview: collapsedPreview(speech.text),
      visible,
      // Escape-first: every character is escaped BEFORE any structure is
      // recognised, so model output cannot become markup. See CLAUDE.md's note
      // on why the renderer is not `marked` + `dompurify`.
      html: renderSpeech(visible),
    }
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

function initials(role: string): string {
  const words = role.trim().split(/\s+/).filter(Boolean)
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase()
  return (role.slice(0, 2) || '??').toUpperCase()
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
  <section class="dialogue-rail" :class="{ 'is-collapsed': collapsed }" aria-label="Agent dialogue">
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
        class="dialogue-entry"
        :class="{ 'is-folded': !row.open, 'is-structured': row.structured }"
        :data-node="row.entry.nodeId"
        :data-identity="row.entry.role"
      >
        <span
          class="dialogue-avatar"
          data-testid="dialogue-avatar"
          :data-character="characterOf(row.entry.nodeId)"
          :data-character-seed="row.entry.role"
          :style="avatarStyle(row.entry.nodeId)"
          aria-hidden="true"
        >{{ initials(row.entry.role) }}</span>

        <div class="dialogue-body">
          <header class="dialogue-meta">
            <strong>{{ row.entry.role }}</strong>
            <span v-if="row.entry.task" class="dialogue-task">{{ row.entry.task }}</span>
            <time class="dialogue-time">{{ clock(row.entry.at) }}</time>
          </header>

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
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  background: var(--surface-well);
  border-bottom: 1px solid var(--border-default);
}

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
.section-kicker { color: var(--accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); }
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
  padding: 4px 14px 12px;
  scrollbar-color: rgba(153, 234, 249, 0.3) transparent;
}

.dialogue-empty { margin: 8px 0; color: var(--text-40); font-size: var(--fs-12); }

.dialogue-entry { display: grid; grid-template-columns: 28px minmax(0, 1fr); gap: 9px; margin-bottom: 10px; }
.dialogue-entry.is-folded { margin-bottom: 5px; }

.dialogue-avatar {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  color: var(--bg-node);
  font: 800 10px/1 var(--font-mono);
  background: var(--character-color, var(--accent-cyan));
  border-radius: var(--r-full);
}

.dialogue-body { min-width: 0; }
.dialogue-meta { display: flex; align-items: baseline; gap: 8px; }
.dialogue-meta strong { overflow: hidden; color: var(--text-title); font: 600 var(--fs-12)/1.3 var(--font-body); white-space: nowrap; text-overflow: ellipsis; }
.dialogue-task { flex: 0 1 auto; overflow: hidden; color: var(--text-40); font: 500 10px/1.3 var(--font-mono); white-space: nowrap; text-overflow: ellipsis; }
.dialogue-time { flex: 0 0 auto; margin-left: auto; color: var(--text-40); font: 400 10px/1.3 var(--font-mono); }

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

.text-button { margin-top: 5px; padding: 0; color: var(--link-cyan); background: none; border: 0; font: 600 var(--fs-11)/1.3 var(--font-body); cursor: pointer; }

.dialogue-trimmed { display: flex; align-items: center; gap: 4px; margin: 5px 0 0; color: var(--warn-text); font: 500 10px/1.3 var(--font-mono); }
.dialogue-tokens { margin: 5px 0 0; color: var(--text-muted); font: 500 10px/1.2 var(--font-mono); font-variant-numeric: tabular-nums; }

@media (max-width: 860px) {
  .dialogue-list { max-height: 30vh; }
}
</style>
