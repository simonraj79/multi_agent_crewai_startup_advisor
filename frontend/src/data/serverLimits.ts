/**
 * The server's admission bounds, restated on the client.
 *
 * The server enforces these and answers 422 or 429; nothing here is a security
 * control and none of it can be trusted by the backend. The point is narrower
 * and entirely about the operator: until these existed, a visitor could type
 * 2,400 characters into a box that counted them helpfully all the way up, press
 * Launch, and be shown a raw JSON envelope. The bound was right; the client
 * simply did not know it existed.
 *
 * These are duplicated constants and duplicated constants drift, so each one
 * names its source. `tests/serverLimits.spec.ts` asserts the numbers against
 * the same literals the Python side uses, which turns a silent drift into a
 * failing test rather than into a surprising 422 in front of a user.
 */

/** `MAX_RUN_INPUT_CHARS` - `src/brief_crew/config.py`. */
export const MAX_IDEA_CHARS = 2000

/**
 * The launch guard in `useValidatorRun.canLaunch`. This one is the CLIENT's
 * own rule, not the server's - the API accepts a shorter idea - but it is a
 * bound the operator runs into, and an unexplained disabled button is the worst
 * kind of bound.
 */
export const MIN_IDEA_CHARS = 12

/** Below this many characters remaining, the counter starts warning. */
export const IDEA_CHARS_WARN_AT = 100

/**
 * `MAX_UTTERANCE_CHARS` - `src/brief_crew/config.py:1534`.
 *
 * How much of a model's completed response the serializer puts on the wire
 * (`events/serializer.py`, `stage: "utterance"`), and therefore the number the
 * dialogue rail quotes when it says an answer was trimmed. It was written into
 * that sentence as the literal "4,096" and would have gone on saying 4,096
 * after the server moved - a rail that names the wrong bound is worse than one
 * that names none, because it reads as authoritative.
 *
 * The count is rendered with a thousands separator, which is a rendering
 * decision and not part of the constant.
 */
export const MAX_UTTERANCE_CHARS = 4096

/**
 * How much of a node's failure the CARD shows before the ellipsis (12 D2).
 *
 * A client bound and not a server one, and the distinction matters: the frame
 * carries up to `MAX_NODE_ERROR_CHARS` = 1024 (`config.py:1542`), so nothing is
 * lost on the wire. This is how much of it fits on a 270px card without pushing
 * every node under it off the canvas. The remainder is one hover away in the
 * `title` and is spoken in full by the aria label, so the bound costs a reader
 * nothing.
 */
export const MAX_NODE_CARD_ERROR_CHARS = 120

/**
 * Pull a human sentence out of whatever the API returned.
 *
 * FastAPI answers `{"detail": "..."}` for a refusal the operator can act on -
 * "inputs.idea is limited to 2000 characters; this one is 2001" is a genuinely
 * good message - and the client used to render the raw envelope, braces,
 * quotes, key and all. `detail` can also be pydantic's list-of-errors shape, in
 * which case the useful part is each entry's `msg`.
 *
 * Anything unrecognised falls back to the original text, because an ugly
 * message beats a swallowed one.
 */
export function readErrorDetail(body: string, status?: number): string {
  const fallback = body || (status ? `Request failed (${status})` : 'Request failed')
  if (!body.trim().startsWith('{') && !body.trim().startsWith('[')) return fallback
  try {
    const parsed = JSON.parse(body) as unknown
    const detail = (parsed as { detail?: unknown })?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map((entry) => (entry as { msg?: unknown })?.msg)
        .filter((msg): msg is string => typeof msg === 'string' && msg.trim().length > 0)
      if (messages.length) return messages.join('; ')
    }
    return fallback
  } catch {
    return fallback
  }
}

/**
 * Turn a 429's `Retry-After` into a sentence.
 *
 * The server computes the header and `CORS_EXPOSE_HEADERS` lists it precisely
 * so a cross-origin client can read it - the static site is a separate origin,
 * and without that entry this would always be null. Nothing read it until now,
 * which made the one header that answers "when can I try again?" pure
 * decoration on the far side of a deliberate CORS decision.
 */
export function retryAfterSentence(header: string | null): string {
  if (!header) return ''
  const seconds = Number(header)
  if (!Number.isFinite(seconds) || seconds <= 0) return ''
  if (seconds < 60) return ` Try again in ${Math.ceil(seconds)}s.`
  return ` Try again in about ${Math.ceil(seconds / 60)} min.`
}
