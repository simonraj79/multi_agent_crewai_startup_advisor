/**
 * How the admin console writes a number down.
 *
 * One module rather than a helper per panel, because five panels printing
 * money five ways is how `$0.00` came to mean both "free" and "we could not
 * price this" the first time (CLAUDE.md section 8, the `cost_usd` defect). The
 * rules here are `BudgetMeter.vue`'s, restated for a screen that shows dollars
 * in twelve places instead of three.
 */

/**
 * A dollar figure that never rounds a real cost to nothing.
 *
 * Two places above a cent, FOUR below it, and a bare `$0.00` only for an
 * honest zero. `—` for a value that is not a number at all, which on this
 * screen means "the server did not answer" and must not read as free.
 */
export function money(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (value === 0) return '$0.00'
  const magnitude = Math.abs(value)
  return magnitude < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`
}

/** A count, grouped, or `—` when there is no number rather than a zero. */
export function count(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat().format(value)
}

/**
 * A whole-number percentage of a total, or null when the total is zero.
 *
 * Null rather than 0, and the callers render nothing rather than `0%`: a
 * percentage of nothing is not zero, it is undefined, and a bar drawn at 0%
 * over an empty window says "nobody spent anything" where the truth is "there
 * is nothing here to compare against".
 */
export function shareOf(value: number, total: number): number | null {
  if (!Number.isFinite(value) || !Number.isFinite(total) || total <= 0) return null
  return Math.min(100, Math.max(0, (value / total) * 100))
}

/** `3m 12s`, `2h 11m`, `—`. Seconds in, the coarsest honest unit out. */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—'
  const whole = Math.max(0, Math.round(seconds))
  if (whole < 60) return `${whole}s`
  if (whole < 3600) return `${Math.floor(whole / 60)}m ${whole % 60}s`
  const hours = Math.floor(whole / 3600)
  return `${hours}h ${Math.floor((whole % 3600) / 60)}m`
}

/** Milliseconds, for a run's own duration column. */
export function durationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '—'
  return duration(ms / 1000)
}

/**
 * A timestamp in the VIEWER's locale and zone, never the server's.
 *
 * `RunHistory.vue`'s rule: the API sends UTC ISO-8601, and a run launched at
 * 22:00 in Singapore must not read as the previous day because the string was
 * printed verbatim.
 */
const stamp = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

export function when(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '—' : stamp.format(parsed)
}

/** A bare day bucket (`2026-09-01`) as `Mon 1 Sep`, without inventing a zone. */
export function dayLabel(day: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day)
  if (!match) return day
  // Constructed as UTC and read as UTC. The bucket IS a UTC day (§3), so
  // rendering it in the viewer's zone would move a Monday to a Sunday for
  // anyone west of Greenwich - the exact mistake `when` exists to avoid, made
  // in the other direction.
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
  return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', timeZone: 'UTC' })
    .format(date)
}

/** The reserved key for `runs.user_id IS NULL`. Mirrors `adminApi`'s constant. */
const UNOWNED = '__unowned__'

/**
 * What to call a person on screen.
 *
 * The email when there is one, the id shortened when there is not, and
 * `unowned runs` for the reserved key - which is a real bucket of real spend
 * and must never render as an empty cell or as somebody's account.
 */
export function personLabel(userId: string | null | undefined, email?: string | null): string {
  if (userId === UNOWNED) return 'unowned runs'
  if (email) return email
  if (!userId) return 'unowned runs'
  return userId.length > 12 ? `${userId.slice(0, 10)}…` : userId
}

/** A run id, short enough for a table cell and long enough to search for. */
export function shortId(value: string | null | undefined): string {
  if (!value) return '—'
  return value.length > 10 ? `${value.slice(0, 8)}…` : value
}

/**
 * An unknown code as sentence-case English.
 *
 * `verdictDisplay.ts`'s rule, applied to `attention[].kind` and to a stop
 * reason: never SNAKE_CASE on screen, and never an invented meaning either -
 * the words are the code's own, only spaced and cased.
 */
export function humanise(code: string | null | undefined): string {
  if (!code) return ''
  const words = code.replace(/[_-]+/g, ' ').trim().toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}
