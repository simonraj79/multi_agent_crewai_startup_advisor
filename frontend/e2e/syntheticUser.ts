/**
 * Being somebody in the end-to-end suite, at no cost.
 *
 * The free backend runs `SYNTHETIC=1` with no `AUTH_BASE_URL`, and in exactly
 * that configuration - and no other - `current_user` honours an
 * `X-Synthetic-User: <id>` header and answers `User(id, email=f"{id}@synthetic")`
 * (plan 01 D8). A browser cannot set that header on a navigation, so a test
 * sets THIS COOKIE on its context instead, and `vite.e2e.config.ts` does two
 * things with it: the stub auth origin returns a session for that id, and the
 * `/api` and `/ws` proxies forward it as the header. One cookie, one identity,
 * on both legs of every request the page makes.
 *
 * Shared by the config and `isolation.spec.ts` rather than restated in each,
 * because a cookie name that drifts between the setter and the reader fails as
 * "Bob can see Alice's graph" - the one false negative this file must not be
 * able to produce.
 *
 * When the cookie is absent the harness behaves exactly as it did before it
 * existed: the stub answers as `E2E Operator` and no header is forwarded. The
 * other 28 tests never set it.
 */
export const SYNTHETIC_USER_COOKIE = 'e2e_synthetic_user'

/** The server's own bound on the header: `^[a-z0-9_-]{1,64}$` (plan 01, C4). */
export const SYNTHETIC_USER_PATTERN = /^[a-z0-9_-]{1,64}$/

/**
 * The synthetic user named by a request's `Cookie` header, or null.
 *
 * A value that does not match the server's pattern is treated as absent rather
 * than forwarded, so a malformed cookie degrades to the anonymous harness and
 * not to a 422 from a header the test never wrote.
 */
export function syntheticUserOf(cookieHeader: string | undefined): string | null {
  if (!cookieHeader) return null
  for (const pair of cookieHeader.split(';')) {
    const at = pair.indexOf('=')
    if (at < 0) continue
    if (pair.slice(0, at).trim() !== SYNTHETIC_USER_COOKIE) continue
    const value = decodeURIComponent(pair.slice(at + 1).trim())
    return SYNTHETIC_USER_PATTERN.test(value) ? value : null
  }
  return null
}
