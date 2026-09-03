import { beforeEach, describe, expect, it } from 'vitest'
import { clearRunHandoff, readRunHandoff, writeRunHandoff } from '../src/data/builderRunHandoff'

/*
 * D-01-5. The handoff names a published graph and its input key, and the run
 * console launches whatever it finds. Written by one person and read by the
 * next on the same browser, it pointed a stranger's console at the previous
 * user's graph under "Running your published graph". It is theirs now.
 */

const HANDOFF = { workflowId: 'ug_e9afa950', inputField: 'idea', name: 'Idea validator' }

describe('the run handoff belongs to the signed-in user (D-01-5)', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it("is written under the user's own key and read back only by them", () => {
    writeRunHandoff(HANDOFF, 'alice')
    expect(window.sessionStorage.getItem('u:alice:builder-run-handoff')).not.toBeNull()
    expect(window.sessionStorage.getItem('builder-run-handoff')).toBeNull()
    expect(readRunHandoff('alice')).toEqual(HANDOFF)
    expect(readRunHandoff('bob')).toBeNull()
    expect(readRunHandoff(null)).toBeNull()
  })

  it('is cleared for the user who holds it and for nobody else', () => {
    writeRunHandoff(HANDOFF, 'alice')
    writeRunHandoff({ ...HANDOFF, name: "Bob's graph" }, 'bob')
    clearRunHandoff('alice')
    expect(readRunHandoff('alice')).toBeNull()
    expect(readRunHandoff('bob')?.name).toBe("Bob's graph")
  })

  it('keeps the anonymous shape when nobody is signed in', () => {
    writeRunHandoff(HANDOFF, null)
    expect(window.sessionStorage.getItem('builder-run-handoff')).not.toBeNull()
    expect(readRunHandoff(null)).toEqual(HANDOFF)
    expect(readRunHandoff('alice')).toBeNull()
  })
})
