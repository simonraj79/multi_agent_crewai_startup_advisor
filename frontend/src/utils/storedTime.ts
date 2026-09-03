/**
 * Reading a stored timestamp, in the one place that knows how.
 *
 * Extracted from `VersionBrowser.vue` in round 3 (D-15-15), where the version
 * rows had already had to solve this twice - once for the naive stamp SQLite
 * returns (D-15-3) and once for the resolution two rows from one minute need.
 * The saved-graphs library needed the same answers, and a second copy of
 * `parseStamp` is a second thing to get wrong on the next backend that returns
 * a stamp in a new shape.
 */

/**
 * A stored stamp as milliseconds, with a naive one read as UTC.
 *
 * `created_at` and `updated_at` are written with `utcnow()` into a
 * `DateTime(timezone=True)` column. PostgreSQL hands the offset back and the
 * string ends in `Z`; SQLite - every local and synthetic backend - drops the
 * tzinfo, and the string arrives as `2026-09-03T04:38:12` with no zone.
 * `Date.parse` reads that form as LOCAL time, which put every row eight hours
 * out on the machine this was found on and made a version saved seconds ago
 * read "8 h ago". The server's time is UTC either way, so a stamp with no zone
 * is given one.
 */
export function parseStamp(iso: string): number {
  const zoned = /(?:[zZ]|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`
  return Date.parse(zoned)
}

/** `2026-09-02T10:14:00Z` -> `2 Sep, 10:14`. Undated values pass through. */
export function formatStamp(iso: string): string {
  const at = parseStamp(iso)
  if (!Number.isFinite(at)) return iso
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(at)
}

/**
 * `12 s ago`, `3 min ago`, `2 h ago`, `yesterday`, else the dated form.
 *
 * Seconds are kept under a minute because that is the resolution two rows
 * from the same minute need - which is the whole reason this exists rather
 * than a `DateTimeFormat` call: three library rows all reading "3 Sept, 07:47"
 * cannot be ordered by eye (D-15-15), and the same was true of two version
 * rows (D-15-3). A row from the future (a clock skewed against the server's)
 * reads `just now` rather than a negative number.
 *
 * `now` is passed in rather than read here, so a caller ticking a ref keeps
 * one clock for a whole list and a test can hand it a fixed instant.
 */
export function agoFrom(iso: string, now: number): string {
  const at = parseStamp(iso)
  if (!Number.isFinite(at)) return iso
  const seconds = Math.round((now - at) / 1000)
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds} s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 22) return `${hours} h ago`
  if (hours < 36) return 'yesterday'
  return formatStamp(iso)
}
