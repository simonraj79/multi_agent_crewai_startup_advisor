import { API_BASE_URL, authedFetch, fetchJson } from './httpCore'
import { readErrorDetail } from '../data/serverLimits'

/**
 * Personal API keys - `/api/account/api-keys` (`.agent/plans/22-api-keys.md` §3).
 *
 * A fourth client beside `studioApi`, `builderApi` and `adminApi`, sharing
 * `httpCore` and nothing else. Like `adminApi` there is deliberately NO mock
 * transport: a fabricated key list is a page that would hand somebody a secret
 * that authenticates against nothing.
 *
 * These three routes are SESSION ONLY on the server. A key presented here is
 * 403, by design (D4): a leaked key must not be able to mint more keys or
 * revoke its owner's. This client only ever sends the console's own JWT.
 */

export const ACCOUNT_API_PREFIX = '/api/account'

/**
 * `API_KEY_NAME_MAX_CHARS` in `src/brief_crew/config.py` (plan 22 D7). The
 * server is the authority and answers 422 past it; this only stops the box
 * accepting a name the server would refuse.
 */
export const API_KEY_NAME_MAX_CHARS = 64

/** `ApiKey`, exactly as §3 declares it. The secret is never part of it. */
export interface ApiKey {
  id: string
  name: string
  /** The first characters of the secret, for recognising it - never enough to use. */
  prefix: string
  created_at: string
  last_used_at: string | null
}

export interface ApiKeyList {
  keys: ApiKey[]
  /** `MAX_API_KEYS_PER_USER` - active keys one account may hold. */
  limit: number
}

/** The one response that carries the secret, and it carries it once. */
export interface CreatedApiKey {
  key: ApiKey
  secret: string
}

export function listApiKeys(): Promise<ApiKeyList> {
  return fetchJson<ApiKeyList>(`${ACCOUNT_API_PREFIX}/api-keys`)
}

export function createApiKey(name: string): Promise<CreatedApiKey> {
  return fetchJson<CreatedApiKey>(`${ACCOUNT_API_PREFIX}/api-keys`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

/**
 * 204 on success, so this cannot go through `fetchJson` (there is no body to
 * parse). A refusal still surfaces the server's own sentence.
 */
export async function revokeApiKey(id: string): Promise<void> {
  const response = await authedFetch(
    `${ACCOUNT_API_PREFIX}/api-keys/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
  )
  if (!response.ok) {
    const body = await response.text().catch(() => '')
    throw new Error(readErrorDetail(body, response.status))
  }
}

/**
 * The API origin a script should call, for the curl example.
 *
 * `API_BASE_URL` is what this SPA itself calls; empty means "the page's own
 * origin" (the dev proxy, or a same-origin deployment), so that is the answer
 * then too.
 */
export function apiOrigin(): string {
  return API_BASE_URL || window.location.origin
}
