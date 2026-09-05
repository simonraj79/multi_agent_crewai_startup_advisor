/**
 * One vocabulary for a run's status, shared by every surface that shows one.
 *
 * Before this file there were three, and they disagreed about the same run:
 * `StatusPanel.vue` rendered `status.replace('_', ' ')` over a CSS
 * `capitalize` (so `error`, `waiting`), `RunHistory.vue` rendered the
 * UN-normalised `BackendRunStatus` verbatim (so `failed`, `cancelling`), and
 * `StudioView.vue` rendered the status with no mapping at all. A run that the
 * status rail called `error` was called `failed` one panel over, because
 * `studioApi.ts` normalises the live run's status and not the history rows'.
 * That is not a wording defect, it is two panels contradicting each other
 * about the same fact.
 *
 * So this module is a table over BOTH unions in `types/studio.ts` -
 * `RunStatus` (what the client keeps) and `BackendRunStatus` (what the API
 * returns for a history row) - and every key of both is present. The two
 * spellings that differ (`error`/`failed`, `stopping`/`cancelling`) map to the
 * same word and the same tone, which is the whole point: whichever carrier a
 * surface happens to hold, the operator reads one word.
 *
 * `humaniseCode` is the floor. A status this table has never seen still
 * renders as words rather than as an identifier, which is criterion T1.4 of
 * `docs/run-shell/DEFINITION-OF-DONE.md`.
 */

import { humaniseCode } from '../utils/humanise'

/**
 * The semantic colour role, never a colour.
 *
 * Consumers spell it into their own class (`is-tone-active`) and bind that to
 * a token; nothing here knows a hex. The six roles are the distinctions the
 * shell already draws in `studio.css`: idle grey, in-flight cyan, needs-you
 * amber, finished mint, failed red, and stopped-by-a-human red-but-not-a-fault.
 */
export type RunStatusTone =
  | 'idle'
  | 'active'
  | 'attention'
  | 'done'
  | 'failed'
  | 'stopped'

export interface RunStatusDisplay {
  /**
   * Sentence case. A surface that wants to shout applies `text-transform` in
   * CSS, so an unrecognised status can never reach the screen looking like a
   * variable name.
   */
  label: string
  tone: RunStatusTone
  /**
   * One clause explaining the word, for a `title`. Empty where the word needs
   * no gloss - a `title` that restates its own label is noise.
   */
  hint: string
}

/**
 * Keyed by every member of `RunStatus` and `BackendRunStatus`.
 *
 * `error` and `failed` are the same event seen from two sides, as are
 * `stopping` and `cancelling`; both pairs deliberately share a label.
 */
export const RUN_STATUS_DISPLAY: Readonly<Record<string, RunStatusDisplay>> = {
  // `RunStatus` only: nothing has been launched in this session yet.
  idle: {
    label: 'Ready',
    tone: 'idle',
    hint: 'Nothing is running. Describe an idea and press Launch.',
  },
  queued: {
    label: 'Queued',
    tone: 'active',
    hint: 'Accepted and waiting for a free worker.',
  },
  running: {
    label: 'Running',
    tone: 'active',
    hint: 'The crew is working.',
  },
  waiting: {
    label: 'Waiting for you',
    tone: 'attention',
    hint: 'Paused at a checkpoint until you answer it.',
  },
  // `RunStatus` spelling.
  stopping: {
    label: 'Stopping',
    tone: 'attention',
    hint: 'Cancel was pressed; the run stops at the next checkpoint.',
  },
  // `BackendRunStatus` spelling of the same state.
  cancelling: {
    label: 'Stopping',
    tone: 'attention',
    hint: 'Cancel was pressed; the run stops at the next checkpoint.',
  },
  cancelled: {
    label: 'Stopped',
    tone: 'stopped',
    hint: 'Someone cancelled this run before it finished.',
  },
  completed: {
    label: 'Finished',
    tone: 'done',
    hint: 'The run reached the end and produced a result.',
  },
  // `RunStatus` spelling.
  error: {
    label: 'Failed',
    tone: 'failed',
    hint: 'The run stopped on an error and produced no result.',
  },
  // `BackendRunStatus` spelling of the same state.
  failed: {
    label: 'Failed',
    tone: 'failed',
    hint: 'The run stopped on an error and produced no result.',
  },
}

/**
 * Words for a status, whichever union it came from and whether or not this
 * file has heard of it.
 *
 * The fallback tone is `idle` rather than `failed`: an unknown status is an
 * unknown status, and painting it red would assert a fault nobody measured.
 */
export function runStatusDisplay(status: string | null | undefined): RunStatusDisplay {
  const key = typeof status === 'string' ? status.trim().toLowerCase() : ''
  const known = RUN_STATUS_DISPLAY[key]
  if (known) return known
  const label = humaniseCode(key)
  return {
    label: label || 'Unknown',
    tone: 'idle',
    hint: '',
  }
}
