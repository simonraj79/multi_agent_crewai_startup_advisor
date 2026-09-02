import { readErrorDetail, retryAfterSentence } from '../data/serverLimits'
import { getAccessToken } from './authClient'

/**
 * The one place a request leaves this client for the FastAPI service.
 *
 * Extracted from `studioApi.ts` unchanged, because `builderApi.ts` needs the
 * same three things and a second copy of them would be a second answer to the
 * questions this file already decides: where the API lives, what a 401 means,
 * and what an author is shown when the server refuses. Two copies of a 401
 * retry is how one of them quietly stops retrying.
 *
 * Nothing here knows about runs or documents. That is deliberate - the moment
 * this file learns what it is fetching, it acquires a reason to treat one
 * caller differently from another, and the divergence starts.
 */

/**
 * Where the API lives, with any trailing slash removed so `${base}${path}`
 * never produces a double slash.
 *
 * Empty when `VITE_API_URL` is unset, which resolves every path against the
 * page's own origin - correct behind the Vite dev proxy and WRONG in
 * production, where it lands on the SPA history fallback and answers 200
 * text/html for anything. `StudioApi.initialize` diagnoses exactly that case by
 * name; this constant is only the resolution, not the judgement.
 *
 * Read at module load rather than per instance. `import.meta.env` is
 * substituted at build time, so there is no moment at which the two differ.
 */
export const API_BASE_URL =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''

/**
 * `fetch` with the bearer token attached, and one retry on 401.
 *
 * The retry matters because the client's idea of freshness is only a guess.
 * `getAccessToken` decides from the token's own `exp`, but the API is the
 * authority: a session revoked server-side, or a key rotated on the auth
 * service, leaves a token here that still looks perfectly valid. Rather than
 * showing the operator "your session has expired" for a session that has not,
 * a 401 forces one fresh mint and one retry. Exactly one - a second 401 is
 * the real answer, and looping would turn an expired login into a hot loop
 * against the auth service.
 */
export async function authedFetch(
  path: string,
  init?: RequestInit,
  allowRetry = true,
  /*
   * Whether to bypass the token cache. SEPARATE from `allowRetry`, because
   * conflating them is a trap: the retry leg passed `allowRetry = false` and
   * the force flag was derived from it as `!allowRetry`, so ANY caller asking
   * merely "do not retry" also silently demanded a fresh network mint.
   *
   * `initialize` is exactly such a caller - and a forced mint there is a
   * second round trip to a sleeping free-plan auth service, inside the very
   * window the probe is timing. That is the defect the probe repair exists to
   * remove, so deriving it would have reintroduced it one line later.
   *
   * The retry leg still forces, which is the whole point of retrying: a
   * server-side revocation leaves a cached token that still looks valid.
   */
  forceToken = !allowRetry,
  /*
   * A token the caller already holds. `undefined` means "mint one";
   * anything else (a string OR null) is used as-is with no mint at all.
   *
   * `initialize` needs this because `getAccessToken` shares one in-flight
   * promise, so asking again after a timed-out race just awaits the same
   * pending mint - outside the AbortController's reach.
   */
  presetToken?: string | null,
): Promise<Response> {
  const token =
    presetToken === undefined ? await getAccessToken(forceToken) : presetToken
  const headers = new Headers(init?.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
  if (response.status === 401 && allowRetry && token) {
    return authedFetch(path, init, false)
  }
  return response
}

export async function fetchJson<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const response = await authedFetch(path, init)
  if (!response.ok) {
    /*
     * What the operator is shown when the server refuses.
     *
     * This used to be `new Error(await response.text())`, so a 2001-character
     * idea surfaced in the UI as the literal string
     *   {"detail":"inputs.idea is limited to 2000 characters; this one is 2001"}
     * - braces, quotes, key and all. The server's message was already good;
     * the client was showing the envelope around it.
     *
     * The 429 is the sharper case. The server computes `Retry-After`, and
     * `CORS_EXPOSE_HEADERS` names it precisely so a cross-origin client can
     * read it - a deliberate decision made for a reader that did not exist.
     * Now it does.
     */
    const body = await response.text().catch(() => '')
    let message = readErrorDetail(body, response.status)
    if (response.status === 429) {
      message += retryAfterSentence(response.headers.get('Retry-After'))
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}
