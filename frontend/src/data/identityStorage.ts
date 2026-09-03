/**
 * Browser storage keyed to the signed-in identity (plan 01 D9; D-01-5).
 *
 * Three things the console keeps in the browser belong to a PERSON, not to the
 * origin: the builder's local draft (`builder-draft:<id>` - the whole document,
 * `config.credential_id` included, written on every successful load and not
 * only for unsaved work), the publish dialog's run handoff
 * (`builder-run-handoff`), and the run console's refresh-recovery pointer
 * (`validator-active-run` with its session id). Until 2026-09-03 every one of
 * them was written under a key with no identity in it, and a sign-out ended the
 * token and nothing else - so the next person on the same browser profile
 * inherited the previous user's flow and run pointers in plaintext. That is
 * D-01-5, and the round-2 critic measured it by swapping the harness's
 * synthetic-user cookie under a live page.
 *
 * Two rules, and the first is the one that carries the weight:
 *
 * 1. **A key written while somebody is signed in carries that person's id**,
 *    as `u:<id>:<base>`. A different signed-in user on the same browser never
 *    reads it - even when the previous person closed the tab without signing
 *    out, which is the common case rather than the rare one. With no identity
 *    (the auth-off backend, the unit suite) `base` is used unchanged, so
 *    nothing about the anonymous harness moved.
 * 2. **A sign-out sweeps everything under that person's prefix** from both
 *    storages (`forgetIdentity`, called from `useAuthGate.endSession` and
 *    nowhere else). The user loses unsaved work when they sign out, and that is
 *    the intent: the draft holds a credential id.
 *
 * The id is URL-encoded inside the key so that no id can contain the
 * delimiter - `a:b` writing `k` and `a` writing `b:k` must not land under one
 * prefix - and a prefix match on `u:<id>:` cannot mistake `alice2` for `alice`,
 * because the trailing colon is part of the prefix.
 */

/** A signed-in user's id, or null for nobody. */
export type StorageIdentity = string | null

const IDENTITY_PREFIX = 'u:'

/** The key `base` is stored under for `userId`; `base` itself for nobody. */
export function scopedKey(base: string, userId: StorageIdentity | undefined): string {
  if (!userId) return base
  return `${identityPrefix(userId)}${base}`
}

function identityPrefix(userId: string): string {
  return `${IDENTITY_PREFIX}${encodeURIComponent(userId)}:`
}

/**
 * The bases that builds before 2026-09-03 wrote with no identity in them.
 *
 * A sign-out on a browser that used one of those builds is the first chance
 * anything has to remove them, so `forgetIdentity` takes them too. They are
 * restated here rather than imported from the owning modules - those modules
 * import THIS file - and `tests/identityStorage.spec.ts` pins each entry
 * against the constant its owner exports, which is the condition under which
 * spec R7 admits a mirror at all.
 */
export const UNSCOPED_LEGACY_KEYS: readonly string[] = [
  'validator-active-run',
  'validator-session-id',
  'builder-run-handoff',
]
export const UNSCOPED_LEGACY_PREFIXES: readonly string[] = ['builder-draft:']

/**
 * Remove everything `userId` wrote from both storages, plus the legacy
 * unscoped keys above, and name what went.
 *
 * Never throws. A browser that blocks site data must not be able to stop a
 * sign-out, and there is nothing to remove there anyway. Keys are collected
 * before anything is removed, because removing while walking `key(index)`
 * skips the entry that shifts into the vacated slot.
 */
export function forgetIdentity(userId: StorageIdentity | undefined): string[] {
  const prefix = userId ? identityPrefix(userId) : null
  const removed: string[] = []
  for (const storage of storages()) {
    for (const key of keysOf(storage)) {
      const theirs = prefix !== null && key.startsWith(prefix)
      const legacy =
        UNSCOPED_LEGACY_KEYS.includes(key)
        || UNSCOPED_LEGACY_PREFIXES.some((legacyPrefix) => key.startsWith(legacyPrefix))
      if (!theirs && !legacy) continue
      try {
        storage.removeItem(key)
        removed.push(key)
      } catch {
        /* Blocked site data: nothing was stored, so nothing is left behind. */
      }
    }
  }
  return removed
}

function storages(): Storage[] {
  const found: Storage[] = []
  try {
    if (globalThis.localStorage) found.push(globalThis.localStorage)
  } catch {
    /* The accessor itself throws when site data is blocked. */
  }
  try {
    if (globalThis.sessionStorage) found.push(globalThis.sessionStorage)
  } catch {
    /* Same. */
  }
  return found
}

function keysOf(storage: Storage): string[] {
  const keys: string[] = []
  try {
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index)
      if (key !== null) keys.push(key)
    }
  } catch {
    return []
  }
  return keys
}
