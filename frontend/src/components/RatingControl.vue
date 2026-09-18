<script setup lang="ts">
/**
 * **Was this run good?** - the one verdict nothing else in this product can
 * supply.
 *
 * Plan 20 §2.4, criterion L9. Everything else this repository records about a
 * run is machine evidence: a tool came back empty, a guardrail retried, a gate
 * was revised. None of it says whether the ANSWER was worth having, and a pile
 * of runs with no human verdict on any of them is only useful to itself. This
 * control is where that verdict comes from, and it is deliberately three words
 * and a note rather than a five-point scale: a person can tell good from bad
 * about their own run, and anything finer would be a number nobody could
 * defend.
 *
 * `unsure` IS AN ANSWER. §2.3 sends it to Langfuse as a categorical companion
 * rather than as a made-up 0.5, because "I do not know" is evidence and a
 * midpoint is a fabrication. Clearing is a fourth STATE, not a fourth value.
 *
 * TWO DOORS, ONE CONTROL. `admin` switches the PUT to
 * `PUT /api/admin/runs/{run_id}/rating` (§2.2), which is the same write behind
 * `require_admin` instead of `require_own_run` and is logged with the actor's
 * e-mail on the server. Everything else about the control is identical, because
 * an admin rating a run and an owner rating it are the same act.
 *
 * ONLY FOR A RUN THE CALLER OWNS - and the parent decides that, not this file.
 * The console renders it for the run it launched, `RunHistory` for rows the API
 * already filtered by owner in SQL, the admin drawer behind `require_admin`.
 * This component makes no ownership judgement of its own and does not have to:
 * the server answers **404, not 403** for somebody else's run
 * (`require_own_run`'s rule - a 403 confirms the run exists), and that sentence
 * lands in the status line below like any other.
 *
 * OPTIMISTIC, THEN RECONCILED. The press paints immediately and the server's
 * answer replaces it; a refusal restores the value that was there before and
 * says why in one sentence. A control that showed a rating the database does
 * not hold would be poisoning the very record it exists to build.
 */
import { computed, ref, watch } from 'vue'
import { CircleHelp, Eraser, LoaderCircle, MessageSquare, ThumbsDown, ThumbsUp } from 'lucide-vue-next'
import { MAX_RATING_NOTE_CHARS, RATING_NOTE_WARN_AT } from '../data/serverLimits'
import { RUN_RATING_CHOICES } from '../data/runRating'
import { studioApi } from '../services/studioApi'
import { adminApi } from '../services/adminApi'
import type { RunRating, RunRatingValue } from '../types/studio'

/** The one call this control makes, so a spec's double is exactly that. */
export interface RatingApiLike {
  rateRun(runId: string, rating: RunRatingValue | null, note?: string): Promise<RunRating>
}

const props = withDefaults(
  defineProps<{
    runId: string
    /** What the server last said, when the caller already knows. */
    rating?: RunRatingValue | null
    note?: string | null
    /** A history row: the three buttons, with the note behind a toggle. */
    compact?: boolean
    /** Write through the admin door instead of the owner's one (§2.2). */
    admin?: boolean
    api?: RatingApiLike
  }>(),
  { rating: null, note: '', compact: false, admin: false, api: undefined },
)

const emit = defineEmits<{ saved: [RunRating] }>()

/**
 * Which door. Chosen per press rather than captured at setup, so a parent that
 * flips `admin` cannot leave a stale transport behind - and an explicit `api`
 * still wins, because that is what a spec hands in.
 */
const transport = computed<RatingApiLike>(
  () => props.api ?? (props.admin ? adminApi : studioApi),
)

const current = ref<RunRatingValue | null>(props.rating ?? null)
const draftNote = ref(props.note ?? '')
const savedNote = ref(props.note ?? '')
const busy = ref(false)
const problem = ref('')
const saved = ref(false)
const noteOpen = ref(false)

/** A parent that re-reads the run replaces what is on screen, not the draft a
 *  person is halfway through typing - unless they have typed nothing. */
watch(
  () => [props.rating, props.note] as const,
  ([rating, note]) => {
    current.value = rating ?? null
    if (draftNote.value === savedNote.value) draftNote.value = note ?? ''
    savedNote.value = note ?? ''
  },
)

const remaining = computed(() => MAX_RATING_NOTE_CHARS - draftNote.value.length)
const noteDirty = computed(() => draftNote.value !== savedNote.value)
const noteId = computed(() => `rating-note-${props.runId || 'none'}`)

/**
 * Save, optimistically, and put it back if the server disagrees.
 *
 * The previous value is captured BEFORE anything paints, so the restore is the
 * value that was really there rather than a re-read that could race a second
 * press. `saved` is a quiet acknowledgement rather than a toast: this is a
 * control somebody uses once and walks away from.
 */
async function apply(next: RunRatingValue | null, note = draftNote.value): Promise<void> {
  if (!props.runId || busy.value) return
  const previousRating = current.value
  const previousNote = savedNote.value
  current.value = next
  busy.value = true
  problem.value = ''
  saved.value = false
  try {
    const answer = await transport.value.rateRun(props.runId, next, note)
    current.value = answer.rating ?? null
    savedNote.value = answer.note ?? ''
    // Only overwrite the box when the person is not mid-edit, for the reason
    // the watcher above gives.
    if (!noteDirty.value || note === draftNote.value) draftNote.value = savedNote.value
    saved.value = true
    emit('saved', answer)
  } catch (error) {
    current.value = previousRating
    savedNote.value = previousNote
    problem.value =
      error instanceof Error && error.message
        ? error.message
        : 'That could not be saved. Nothing was recorded.'
  } finally {
    busy.value = false
  }
}

/** Pressing the chosen value again clears it - one control, both directions. */
function choose(value: RunRatingValue): void {
  void apply(current.value === value ? null : value)
}
</script>

<template>
  <div
    class="rating-control"
    :class="{ 'is-compact': compact }"
    data-testid="rating-control"
    :data-run-id="runId"
  >
    <!--
      FOUND BY LOOKING. The lede is suppressed on the admin door because the
      only surface that opens that door - the drawer - already carries "Was
      this run good?" as the heading of the block this sits in, and the two
      together read as the question asked twice. The group's `aria-label` still
      carries it, so a screen reader is told once rather than not at all.
    -->
    <p v-if="!compact && !admin" class="rating-lede" data-testid="rating-lede">
      Was this run good? Nothing the software records can answer that for you.
    </p>

    <div class="rating-row">
      <div class="rating-choices" role="group" aria-label="Was this run good?">
        <button
          v-for="choice in RUN_RATING_CHOICES"
          :key="choice.value"
          type="button"
          class="rating-choice"
          :class="[`is-${choice.value}`, { 'is-chosen': current === choice.value }]"
          :aria-pressed="current === choice.value"
          :disabled="busy || !runId"
          :title="choice.hint"
          :data-testid="`rating-${choice.value}`"
          @click="choose(choice.value)"
        >
          <ThumbsUp v-if="choice.value === 'good'" :size="13" aria-hidden="true" />
          <ThumbsDown v-else-if="choice.value === 'bad'" :size="13" aria-hidden="true" />
          <CircleHelp v-else :size="13" aria-hidden="true" />
          {{ choice.label }}
        </button>
      </div>

      <button
        v-if="compact"
        type="button"
        class="rating-note-toggle"
        :aria-expanded="noteOpen"
        :aria-controls="noteId"
        data-testid="rating-note-toggle"
        @click="noteOpen = !noteOpen"
      >
        <MessageSquare :size="12" aria-hidden="true" />
        Note
      </button>

      <button
        v-if="current"
        type="button"
        class="rating-clear"
        :disabled="busy"
        data-testid="rating-clear"
        @click="apply(null)"
      >
        <Eraser :size="12" aria-hidden="true" />
        Clear
      </button>

      <LoaderCircle v-if="busy" class="rating-spin" :size="13" aria-hidden="true" />
    </div>

    <div v-if="!compact || noteOpen" class="rating-note-block">
      <label class="rating-note-label" :for="noteId">Add a note (optional)</label>
      <textarea
        :id="noteId"
        v-model="draftNote"
        class="rating-note"
        rows="2"
        :maxlength="MAX_RATING_NOTE_CHARS"
        :disabled="busy || !runId"
        data-testid="rating-note"
        placeholder="What was right or wrong about this answer?"
      />
      <div class="rating-note-foot">
        <!--
          The ceiling is STATED, not merely enforced: past it `maxlength` starts
          discarding keystrokes with no feedback at all, which is the defect
          item 11 records about the idea box, met a second time.
        -->
        <span
          class="rating-count"
          :class="{ 'is-warn': remaining <= RATING_NOTE_WARN_AT }"
          data-testid="rating-note-count"
        >
          {{ draftNote.length }} / {{ MAX_RATING_NOTE_CHARS }} characters
        </span>
        <button
          type="button"
          class="rating-save"
          :disabled="busy || !noteDirty || !runId"
          data-testid="rating-note-save"
          @click="apply(current)"
        >
          Save note
        </button>
      </div>
    </div>

    <p v-if="problem" class="rating-problem" role="alert" data-testid="rating-problem">
      {{ problem }}
    </p>
    <p v-else-if="saved" class="rating-saved" role="status" data-testid="rating-saved">
      Saved.
    </p>
    <p v-else-if="!compact && !current" class="rating-hint" data-testid="rating-hint">
      Not rated yet.
    </p>
  </div>
</template>

<style scoped>
.rating-control {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--surface-well);
  border: 1px solid var(--border-control);
  border-radius: var(--r-md);
}

.rating-control.is-compact {
  padding: var(--space-2) 0 0;
  background: transparent;
  border: 0;
}

.rating-lede { margin: 0; color: var(--text-meta); font: var(--type-meta); line-height: 1.5; }

.rating-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}

.rating-choices { display: inline-flex; flex-wrap: wrap; gap: var(--space-2); }

/* 44px, the same floor `admin.css` already holds its own controls to. A
   rating is pressed once on a phone by somebody who has just read a report,
   and a 28px target is the one that gets missed. */
.rating-choice,
.rating-note-toggle,
.rating-clear,
.rating-save {
  display: inline-flex;
  gap: var(--space-2);
  align-items: center;
  min-height: 44px;
  padding: var(--space-2) var(--space-3);
  color: var(--text-muted);
  font: var(--type-meta);
  background: var(--surface-raised);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.rating-note-toggle,
.rating-clear,
.rating-save { background: transparent; }

.rating-choice:hover:not(:disabled),
.rating-note-toggle:hover:not(:disabled),
.rating-clear:hover:not(:disabled),
.rating-save:hover:not(:disabled) { color: var(--text-body); border-color: var(--border-hover); }

.rating-choice:disabled,
.rating-clear:disabled,
.rating-save:disabled { opacity: 0.45; cursor: default; }

.rating-choice:focus-visible,
.rating-note-toggle:focus-visible,
.rating-clear:focus-visible,
.rating-save:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

/* ONE HUE PER MEANING, and none of the three is a judgement painted on a
   button nobody has pressed: an unchosen `Bad` is not red. The tint arrives
   with the press, so the colour reports what was said rather than suggesting
   what to say. */
.rating-choice.is-chosen { color: var(--text-title); border-color: var(--border-control); background: var(--surface-panel); }
.rating-choice.is-good.is-chosen { color: var(--on-accent-mint); }
.rating-choice.is-bad.is-chosen { color: var(--err-text); }
.rating-choice.is-unsure.is-chosen { color: var(--warn-text); }

.rating-note-block { display: grid; gap: var(--space-2); }
.rating-note-label { color: var(--text-meta); font: var(--type-meta); }

.rating-note {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  color: var(--text-body);
  font: var(--type-meta);
  font-family: var(--font-body);
  background: var(--surface-raised);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
  resize: vertical;
}

.rating-note:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

.rating-note-foot { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: center; justify-content: space-between; }
.rating-count { color: var(--text-40); font: var(--type-meta); }
.rating-count.is-warn { color: var(--warn-text); }

.rating-problem { margin: 0; color: var(--err-text); font: var(--type-meta); }
.rating-saved,
.rating-hint { margin: 0; color: var(--text-40); font: var(--type-meta); }

.rating-spin { color: var(--text-40); animation: rating-spin 900ms linear infinite; }

@media (prefers-reduced-motion: reduce) {
  .rating-spin { animation: none; }
}

@keyframes rating-spin {
  to { transform: rotate(360deg); }
}
</style>
