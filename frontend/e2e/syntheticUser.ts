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
 * When the cookie is absent the stub answers as `E2E Operator` and the proxies
 * forward `DEFAULT_SYNTHETIC_USER`, so the API sees the same signed-in person
 * the page does. The other 29 tests never set the cookie.
 */
export const SYNTHETIC_USER_COOKIE = 'e2e_synthetic_user'

/**
 * Who a context with NO cookie is, at the API.
 *
 * The stub auth origin answers every cookieless context as the E2E Operator,
 * signed in, and the SPA behaves accordingly: it mints a bearer and calls the
 * routes a signed-in author may call. Forwarding nobody for that context made
 * the API see an anonymous caller behind a signed-in page - a state production
 * cannot reach - and the first owned route the builder learned to call
 * (`GET /api/builder/credentials`, plan 01) answered 401, which Chrome logs as
 * a console error and the suite's zero-tolerance rule failed seven tests on.
 * Found at integration on 2026-09-03, by the merged suite and by nothing else.
 *
 * The id is the stub session's own `user.id`, so the header chip, the owner
 * column and the forwarded header name one person. `isolation.spec.ts` still
 * overrides it per context with the cookie.
 */
export const DEFAULT_SYNTHETIC_USER = 'e2e-user'

/** The server's own bound on the header: `^[a-z0-9_-]{1,64}$` (plan 01, C4). */
export const SYNTHETIC_USER_PATTERN = /^[a-z0-9_-]{1,64}$/

/**
 * Where the SPA keeps a signed-in user's draft, handoff record and run
 * pointer: under `u:<id>:<base>` (`src/data/identityStorage.ts`, D-01-5).
 *
 * Restated here rather than imported - the e2e directory is its own TypeScript
 * program - and `tests/identityStorage.spec.ts` pins the same literal on the
 * other side. A drift between the two fails loudly, as a missing handoff
 * banner or a null pointer, never silently.
 */
export function storageKeyFor(id: string, base: string): string {
  return `u:${encodeURIComponent(id)}:${base}`
}

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
