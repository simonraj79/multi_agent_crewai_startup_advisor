import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  UNSCOPED_LEGACY_KEYS,
  UNSCOPED_LEGACY_PREFIXES,
  forgetIdentity,
  scopedKey,
} from '../src/data/identityStorage'
import { DRAFT_PREFIX } from '../src/composables/useBuilderPersistence'
import { ACTIVE_RUN_STORAGE_KEY, SESSION_STORAGE_KEY } from '../src/composables/useValidatorRun'
import { HANDOFF_KEY } from '../src/data/builderRunHandoff'

/*
 * D-01-5. The three things the browser keeps for a person - a draft, a handoff
 * record and a run pointer - are keyed to that person, and a sign-out sweeps
 * them. This file pins the key SHAPE as a literal, because the E2E suite and
 * the critic's probe both spell it by hand.
 */

function keysOf(storage: Storage): string[] {
  const found: string[] = []
  for (let index = 0; index < storage.length; index += 1) found.push(storage.key(index) as string)
  return found.sort()
}

describe('scopedKey', () => {
  it('leaves the anonymous shape alone, for the auth-off backend and the tests', () => {
    expect(scopedKey('builder-draft:ug_0a1b2c3d', null)).toBe('builder-draft:ug_0a1b2c3d')
    expect(scopedKey('validator-active-run', '')).toBe('validator-active-run')
  })

  it("puts the signed-in user's id in front", () => {
    expect(scopedKey('builder-draft:ug_0a1b2c3d', 'alice')).toBe('u:alice:builder-draft:ug_0a1b2c3d')
    expect(scopedKey('builder-run-handoff', 'e2e-user')).toBe('u:e2e-user:builder-run-handoff')
  })

  it('encodes the id, so no id can spell the delimiter and land in another prefix', () => {
    // `a:b` writing `k` must not collide with `a` writing `b:k`.
    expect(scopedKey('k', 'a:b')).toBe('u:a%3Ab:k')
    expect(scopedKey('k', 'a:b')).not.toBe(scopedKey('b:k', 'a'))
  })
})

describe('forgetIdentity', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.sessionStorage.clear()
  })

  it("removes the identity's keys from both storages and reports them", () => {
    window.localStorage.setItem('u:alice:builder-draft:ug_0a1b2c3d', '{"v":1}')
    window.localStorage.setItem('u:alice:validator-active-run', '{"version":1}')
    window.localStorage.setItem('u:alice:validator-session-id', 'session-1')
    window.sessionStorage.setItem('u:alice:builder-run-handoff', '{"workflowId":"ug_0a1b2c3d"}')

    const removed = forgetIdentity('alice')

    expect(removed.sort()).toEqual([
      'u:alice:builder-draft:ug_0a1b2c3d',
      'u:alice:builder-run-handoff',
      'u:alice:validator-active-run',
      'u:alice:validator-session-id',
    ])
    expect(keysOf(window.localStorage)).toEqual([])
    expect(keysOf(window.sessionStorage)).toEqual([])
  })

  it('leaves every other identity alone, including one whose id starts with this one', () => {
    window.localStorage.setItem('u:alice:builder-draft:ug_0a1b2c3d', '{"v":1}')
    window.localStorage.setItem('u:bob:builder-draft:ug_0a1b2c3d', '{"v":1}')
    window.localStorage.setItem('u:alice2:validator-active-run', '{"version":1}')
    window.sessionStorage.setItem('u:bob:builder-run-handoff', '{}')
    // Preferences and the server's own vocabulary cache are not anybody's.
    window.localStorage.setItem('builder-minimap-collapsed', '1')
    window.sessionStorage.setItem('builder-vocabulary', '{}')

    forgetIdentity('alice')

    expect(keysOf(window.localStorage)).toEqual([
      'builder-minimap-collapsed',
      'u:alice2:validator-active-run',
      'u:bob:builder-draft:ug_0a1b2c3d',
    ])
    expect(keysOf(window.sessionStorage)).toEqual(['builder-vocabulary', 'u:bob:builder-run-handoff'])
  })

  it('also takes the keys a build before 2026-09-03 wrote with no identity in them', () => {
    window.localStorage.setItem('builder-draft:ug_0a1b2c3d', '{"v":1}')
    window.localStorage.setItem('builder-draft:ug_9f8e7d6c', '{"v":1}')
    window.localStorage.setItem('validator-active-run', '{"version":1}')
    window.localStorage.setItem('validator-session-id', 'session-1')
    window.sessionStorage.setItem('builder-run-handoff', '{}')
    window.localStorage.setItem('builder-minimap-collapsed', '1')

    forgetIdentity('alice')

    expect(keysOf(window.localStorage)).toEqual(['builder-minimap-collapsed'])
    expect(keysOf(window.sessionStorage)).toEqual([])
  })

  it('never throws when site data is blocked', () => {
    const denied = (): never => {
      throw new DOMException('The operation is insecure.', 'SecurityError')
    }
    vi.spyOn(Storage.prototype, 'key').mockImplementation(denied)
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(denied)
    expect(() => forgetIdentity('alice')).not.toThrow()
    expect(forgetIdentity('alice')).toEqual([])
  })
})

/**
 * The legacy list is a mirror of the bases the owning modules write, and a
 * mirror is admitted only when a test regenerates it from the source of truth
 * (spec R7). Each module exports its base for exactly this assertion.
 */
describe('the legacy list mirrors the owning modules', () => {
  it('names exactly the bases those modules write', () => {
    expect([...UNSCOPED_LEGACY_KEYS].sort()).toEqual(
      [ACTIVE_RUN_STORAGE_KEY, HANDOFF_KEY, SESSION_STORAGE_KEY].sort(),
    )
    expect([...UNSCOPED_LEGACY_PREFIXES]).toEqual([DRAFT_PREFIX])
  })
})
