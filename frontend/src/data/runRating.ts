/**
 * The three words a person may say about a finished run, in one place.
 *
 * Plan 20 §2.2 and §2.4. Four surfaces read this - the control itself, the
 * admin Runs chip, the admin drawer and the admin filter - and a second copy
 * of "what does `unsure` say on screen" is exactly the drift
 * `data/serverLimits.ts` exists to turn into a failing test rather than a
 * wrong word.
 *
 * `unsure` IS AN ANSWER, not a missing one, and that is why it is here while
 * `null` is not: `null` clears a rating and is the absence of a value rather
 * than a fourth one. Nothing anywhere turns it into a number between good and
 * bad, because "I do not know" is evidence and a midpoint would be invented.
 */
import type { RunRating, RunRatingValue } from '../types/studio'

/** The wire vocabulary. The server answers 422 to anything else (§2.2). */
export const RUN_RATING_VALUES: readonly RunRatingValue[] = ['good', 'bad', 'unsure']

/**
 * What each one says on screen, and what its tooltip explains.
 *
 * The words are the plan's: **Good**, **Bad**, **Not sure**. `unsure` on the
 * wire and `Not sure` on the screen is deliberate - the stored vocabulary is a
 * thing aggregates are counted over and must never move, while the words a
 * person reads are allowed to be the ones a person would use.
 */
export const RUN_RATING_CHOICES: ReadonlyArray<{
  value: RunRatingValue
  label: string
  hint: string
}> = [
  { value: 'good', label: 'Good', hint: 'The answer was worth having.' },
  { value: 'bad', label: 'Bad', hint: 'The answer was wrong, thin, or unusable.' },
  { value: 'unsure', label: 'Not sure', hint: 'Recorded as its own answer, never as a middle value.' },
]

/** The word for a stored value, or '' when nobody has said anything. */
export function runRatingWord(value: string | null | undefined): string {
  return RUN_RATING_CHOICES.find((choice) => choice.value === value)?.label ?? ''
}

/**
 * Read whatever the server answered into the shape §2.2 declares.
 *
 * TWO SPELLINGS ARE ACCEPTED FOR THE NOTE, and the reason is recorded rather
 * than hidden: plan 20 §2.2 names the field `note`, while the branch this work
 * is ported from answers `rating_note` (`improve_api.py`'s `RunRatingModel`).
 * The two builders are working in parallel, and a client that read only one of
 * them would silently drop a sentence somebody typed - a rating still saved,
 * its reason gone, with nothing on screen to say so. Reading both costs one
 * `??` and cannot be wrong either way; the canonical spelling everything
 * downstream uses is §2.2's.
 */
export function readRunRating(body: unknown, fallbackRunId = ''): RunRating {
  const row = (body ?? {}) as Record<string, unknown>
  const rating = row.rating
  return {
    run_id: typeof row.run_id === 'string' ? row.run_id : fallbackRunId,
    rating: RUN_RATING_VALUES.includes(rating as RunRatingValue)
      ? (rating as RunRatingValue)
      : null,
    note:
      typeof row.note === 'string'
        ? row.note
        : typeof row.rating_note === 'string'
          ? row.rating_note
          : null,
    rated_by: typeof row.rated_by === 'string' ? row.rated_by : null,
    rated_at: typeof row.rated_at === 'string' ? row.rated_at : null,
  }
}
