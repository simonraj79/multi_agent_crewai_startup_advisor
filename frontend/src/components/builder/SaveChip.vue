<script setup lang="ts">
import { computed } from 'vue'
import { AlertTriangle, Archive, Check, CloudOff, PenLine, RefreshCw } from 'lucide-vue-next'
import type { SaveState } from '../../composables/useBuilderPersistence'

/**
 * What has happened to the author's work, in one line, always.
 *
 * The rule this component exists to keep is that SILENCE IS NEVER A STATE.
 * Every value of `saveState` renders a sentence, including the two that report
 * a failure - a builder whose chip goes blank when a save is refused is a
 * builder that has told the author their work is safe by omission.
 *
 * `role="status"` rather than `aria-live="assertive"`: this changes on a 2.5s
 * idle timer while the author is still typing, and an assertive region would
 * interrupt a screen reader mid-word every time it did. Polite is what a status
 * line is.
 */

const props = defineProps<{
  state: SaveState
  /** The stored version. 0 while nothing has ever been saved. */
  version: number
  /** The version the server holds, for the conflict wording. */
  headVersion: number
  /**
   * The server's own sentence when a save was REFUSED rather than lost.
   *
   * `saveState` has five values and none of them is "refused" - a 413 over
   * `max_document_bytes` and a 422 on a malformed document both land in
   * `offline`, which would be a lie without this. The state stays honest by
   * rendering the server's sentence instead of the offline wording, so the
   * author reads what actually happened rather than a category it does not fit.
   */
  error?: string
  /** True when the local draft was too big to keep. §5.6 forbids dropping it silently. */
  draftDropped?: boolean
}>()

/**
 * `⌘S` on a Mac, `Ctrl+S` everywhere else.
 *
 * Spec §4 writes every binding with `⌘` and says once that it means Ctrl on
 * Windows and Linux. Printing the glyph on Windows would be a shortcut hint
 * naming a key the keyboard does not have, which is worse than no hint.
 */
const saveKey = computed(() =>
  /mac|iphone|ipad/i.test(navigator.userAgent) ? '⌘S' : 'Ctrl+S',
)

const text = computed(() => {
  switch (props.state) {
    case 'saving':
      return 'saving…'
    case 'conflict':
      return `conflict — head is v${props.headVersion}`
    case 'offline':
      return props.error ? `not saved — ${props.error}` : 'offline — kept in this browser'
    case 'dirty':
      return `unsaved changes · ${saveKey.value}`
    case 'clean':
      return props.version > 0 ? `saved · v${props.version}` : 'saved'
  }
  return ''
})
</script>

<template>
  <div class="save-chip" :class="`is-${state}`">
    <span class="save-chip-line" role="status" data-testid="save-chip">
      <Check v-if="state === 'clean'" :size="13" aria-hidden="true" />
      <RefreshCw v-else-if="state === 'saving'" :size="13" class="is-spinning" aria-hidden="true" />
      <PenLine v-else-if="state === 'dirty'" :size="13" aria-hidden="true" />
      <AlertTriangle v-else-if="state === 'conflict'" :size="13" aria-hidden="true" />
      <CloudOff v-else :size="13" aria-hidden="true" />
      <span>{{ text }}</span>
    </span>

    <!-- A second line rather than a replacement: the draft being too large to
         keep locally is true ALONGSIDE whatever the save state is, and folding
         it into the same sentence would mean one of the two facts is dropped
         whenever they disagree. -->
    <span v-if="draftDropped" class="save-chip-line is-dropped" role="status">
      <Archive :size="13" aria-hidden="true" />
      <span>too large for a local backup — save to keep it</span>
    </span>
  </div>
</template>

<style scoped>
.save-chip { display: flex; flex-direction: column; gap: 3px; }
.save-chip-line { display: inline-flex; align-items: center; gap: 6px; color: var(--text-40); font: 600 var(--fs-11)/1 var(--font-mono); white-space: nowrap; }
.save-chip-line svg { flex: 0 0 auto; }
.is-clean .save-chip-line { color: var(--accent-mint); }
.is-dirty .save-chip-line { color: var(--text-muted); }
.is-saving .save-chip-line { color: var(--accent-cyan); }
.is-conflict .save-chip-line { color: var(--warn-text); }
.is-offline .save-chip-line { color: var(--err-text); }
/* Always amber, whatever the save state is doing above it. */
.save-chip-line.is-dropped { color: var(--warn-text); }

.is-spinning { animation: save-chip-spin 1.1s linear infinite; }
@keyframes save-chip-spin { to { transform: rotate(360deg); } }

/* The spinner is the one animation here and it encodes "a request is in
   flight", which the word `saving…` already says. Nothing is lost by stopping
   it, so it stops. */
@media (prefers-reduced-motion: reduce) {
  .is-spinning { animation: none; }
}
</style>
