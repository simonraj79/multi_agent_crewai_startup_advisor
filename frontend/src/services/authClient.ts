/**
 * The browser half of authentication.
 *
 * Two credentials live here and they are deliberately different things:
 *
 *  - The **session** is an httpOnly cookie on this origin. This file cannot
 *    read it and neither can any other script on the page; it is sent
 *    automatically to `/api/auth/*`, which the Node server in `server/`
 *    handles.
 *  - The **access token** is a short-lived JWT fetched from that same origin
 *    and sent to the FastAPI service, which is a different origin and cannot
 *    receive the cookie (see `server/auth.ts` on the Public Suffix List).
 *
 * The token is held in a module variable and never written to `localStorage` or
 * `sessionStorage`. That is the whole point of the split: a stored token
 * survives the tab and is readable by any injected script, while this one dies
 * with the page and is reissued from the cookie on the next load.
 */
import { createAuthClient } from 'better-auth/vue'
import { jwtClient } from 'better-auth/client/plugins'

export const authClient = createAuthClient({
  // No baseURL: auth is served from this very origin, by the Node server that
  // also served this page. Naming an origin here would be the one way to get it
  // wrong, and it is exactly the mistake `VITE_API_URL` invites for the API.
  plugins: [jwtClient()],
})

export const { useSession, signIn, signOut } = authClient

/**
 * Treat a token as expired this many milliseconds early.
 *
 * A token that is valid for another two seconds is worthless: it can expire
 * between the check here and the moment the API verifies it, and the user sees
 * an unexplained 401 on an action they just took. Sixty seconds also covers the
 * clock skew the API allows for (`AUTH_JWT_LEEWAY_SECONDS`).
 */
const EXPIRY_SKEW_MS = 60_000

interface CachedToken {
  token: string
  /** Epoch milliseconds, already reduced by EXPIRY_SKEW_MS. */
  usableUntil: number
}

let cached: CachedToken | null = null

/**
 * The in-flight fetch, so concurrent callers share one request.
 *
 * This is not an optimisation. A single page load fires the graph fetch, the
 * run snapshot and the frame replay at once; without this each would mint its
 * own token, and Better Auth's `/token` endpoint has no caching of its own -
 * its handler calls `getJwtToken` on every request. Three tokens where one
 * would do, on every load, for every user.
 */
let inflight: Promise<string | null> | null = null

/**
 * Whether a signed-in session is known to exist.
 *
 * Defaults to FALSE, and the default is the important part. Without it,
 * `getAccessToken` would call `/api/auth/token` on every page load - including
 * for a signed-out visitor, where the answer is always 401, and including in
 * the unit suite, where a mocked `fetch` would hand the token request the
 * response the test had queued for the API call and every assertion downstream
 * would be off by one. That is exactly how this was found.
 *
 * `useAuthGate` flips it as the session resolves, and the studio does not probe
 * the API until that has happened - so the ordering is not a race.
 */
let sessionKnownActive = false

/**
 * Declare whether a session exists. Called by `useAuthGate` only.
 *
 * Going false also drops the cached token: a signed-out client holding a
 * still-unexpired JWT would keep sending it, and the API would keep honouring
 * it until it aged out.
 */
export function setSessionActive(active: boolean): void {
  sessionKnownActive = active
  if (!active) clearAccessToken()
}

/**
 * Read `exp` out of a JWT without verifying it.
 *
 * Verification is the API's job and cannot be done here anyway - the client has
 * no private key and no business trusting its own answer. This reads the claim
 * only to decide when to ask for a new token, which is a scheduling decision:
 * the worst a forged `exp` could do is make this client refresh too often.
 */
function expiryOf(token: string): number | null {
  const segments = token.split('.')
  if (segments.length !== 3) return null
  try {
    // base64url -> base64, then pad. atob rejects the URL-safe alphabet.
    const padded = segments[1].replace(/-/g, '+').replace(/_/g, '/')
    const json = atob(padded + '='.repeat((4 - (padded.length % 4)) % 4))
    const exp = JSON.parse(json)?.exp
    return typeof exp === 'number' ? exp * 1000 : null
  } catch {
    return null
  }
}

async function requestToken(): Promise<string | null> {
  try {
    // Same-origin, so the httpOnly session cookie authenticates this call.
    const response = await fetch('/api/auth/token', {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    })
    if (!response.ok) return null
    const token = (await response.json())?.token
    if (typeof token !== 'string' || !token) return null

    // Fall back to a conservative lifetime if `exp` is unreadable, rather than
    // caching forever. `frontend/server/auth.ts` issues 15 minutes.
    const expiry = expiryOf(token) ?? Date.now() + 10 * 60_000
    cached = { token, usableUntil: expiry - EXPIRY_SKEW_MS }
    return token
  } catch {
    return null
  }
}

/**
 * The bearer token for a call to the FastAPI service, or null when signed out.
 *
 * @param force Skip the cache. Used once after a 401, because the API is the
 *   authority on whether a token is still good - a session revoked server-side
 *   leaves a token here that still *looks* valid by its own `exp`.
 */
export async function getAccessToken(force = false): Promise<string | null> {
  // No session, no token, no request. See `setSessionActive`.
  if (!sessionKnownActive) return null
  if (!force && cached && Date.now() < cached.usableUntil) return cached.token
  if (inflight) return inflight
  if (force) cached = null
  inflight = requestToken().finally(() => {
    inflight = null
  })
  return inflight
}

/** Drop the cached token. Call on sign-out, before the session cookie goes. */
export function clearAccessToken(): void {
  cached = null
  inflight = null
}

/** Whether a token is currently held. Exported for tests, not for gating UI. */
export function hasCachedToken(): boolean {
  return cached !== null && Date.now() < cached.usableUntil
}
