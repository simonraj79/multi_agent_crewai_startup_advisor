import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SignedInUser } from '../src/composables/useAuthGate'

/*
 * `endSession` is the one place a session ends (App.vue), and D-01-5 is what it
 * left behind: the token was dropped and the cookie revoked while every draft,
 * handoff record and run pointer the identity had written stayed in browser
 * storage for the next person on the profile.
 */

const auth = vi.hoisted(() => ({
  user: null as (SignedInUser & { emailVerified?: boolean }) | null,
  calls: [] as string[],
}))

vi.mock('../src/services/authClient', async () => {
  const { computed } = await import('vue')
  return {
    authClient: {},
    useSession: () =>
      computed(() => ({
        data: auth.user ? { user: auth.user } : null,
        isPending: false,
        error: null,
      })),
    signIn: { social: async () => ({ error: null }) },
    signOut: async () => {
      auth.calls.push('signOut')
      return { data: { success: true }, error: null }
    },
    clearAccessToken: () => {
      auth.calls.push('clearAccessToken')
    },
    setSessionActive: () => {},
  }
})

import { useAuthGate } from '../src/composables/useAuthGate'

const ALICE: SignedInUser = { id: 'alice', name: 'Alice', email: 'alice@synthetic', image: null }

function keysOf(storage: Storage): string[] {
  const found: string[] = []
  for (let index = 0; index < storage.length; index += 1) found.push(storage.key(index) as string)
  return found.sort()
}

describe('endSession clears what the identity wrote (D-01-5)', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.sessionStorage.clear()
    auth.calls.length = 0
    auth.user = ALICE
  })

  it("removes every key the signed-in user wrote, in both storages, and nobody else's", async () => {
    window.localStorage.setItem('u:alice:builder-draft:ug_dbc5c011', '{"v":1}')
    window.localStorage.setItem('u:alice:validator-active-run', '{"version":1}')
    window.localStorage.setItem('u:alice:validator-session-id', 'session-1')
    window.sessionStorage.setItem('u:alice:builder-run-handoff', '{"workflowId":"ug_dbc5c011"}')
    window.localStorage.setItem('u:bob:builder-draft:ug_dbc5c011', '{"v":1}')
    window.localStorage.setItem('u:alice2:validator-active-run', '{"version":1}')
    window.localStorage.setItem('builder-minimap-collapsed', '1')
    window.sessionStorage.setItem('builder-vocabulary', '{}')

    const gate = useAuthGate()
    expect(gate.user.value?.id).toBe('alice')
    await gate.endSession()

    expect(keysOf(window.localStorage)).toEqual([
      'builder-minimap-collapsed',
      'u:alice2:validator-active-run',
      'u:bob:builder-draft:ug_dbc5c011',
    ])
    expect(keysOf(window.sessionStorage)).toEqual(['builder-vocabulary'])
  })

  it('also takes the keys a build before 2026-09-03 wrote with no identity in them', async () => {
    window.localStorage.setItem('builder-draft:ug_dbc5c011', '{"v":1}')
    window.localStorage.setItem('validator-active-run', '{"version":1}')
    window.localStorage.setItem('validator-session-id', 'session-1')
    window.sessionStorage.setItem('builder-run-handoff', '{}')

    await useAuthGate().endSession()

    expect(keysOf(window.localStorage)).toEqual([])
    expect(keysOf(window.sessionStorage)).toEqual([])
  })

  it('still drops the token before the cookie goes', async () => {
    await useAuthGate().endSession()
    expect(auth.calls).toEqual(['clearAccessToken', 'signOut'])
  })

  it('signs out even when site data is blocked', async () => {
    const denied = (): never => {
      throw new DOMException('The operation is insecure.', 'SecurityError')
    }
    vi.spyOn(Storage.prototype, 'key').mockImplementation(denied)
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(denied)

    await expect(useAuthGate().endSession()).resolves.toBeUndefined()
    expect(auth.calls).toEqual(['clearAccessToken', 'signOut'])
  })
})
