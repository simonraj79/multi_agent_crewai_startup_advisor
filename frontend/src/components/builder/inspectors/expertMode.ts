import { ref } from 'vue'

/**
 * The inspector's three-tier disclosure state - 04 D1, and decision 19.
 *
 * TWO SETTINGS, DELIBERATELY DIFFERENT IN SCOPE AND IN STORAGE, because they
 * answer two different questions.
 *
 * `expertMode` is **global** and lives in `localStorage`. Owner's decision 19:
 * per node kind means an author learns the same control four times and it
 * remembers a different answer each time - you turn Expert on for an agent,
 * open a crew, and the settings you just went looking for are gone with nothing
 * on screen saying why. It is a statement about the PERSON ("I want to see
 * everything"), so it outlives the tab.
 *
 * `advancedOpen` is **per node kind** and lives in `sessionStorage`. That one is
 * a statement about the WORK in front of you - an author tuning retries across
 * six agents wants Advanced open on every agent and does not thereby want it
 * open on every gate - and it is cheap enough to be wrong that it dies with the
 * tab rather than following somebody into next week.
 *
 * NEITHER EVER HIDES A PROBLEM. A field carrying a server problem forces its
 * region open regardless of both settings (`TierRegion`'s `forceOpen`), because
 * an error behind a closed disclosure is precisely the modal-stack failure R15
 * exists to prevent, wearing a smaller hat.
 *
 * Storage is best-effort on both sides. A browser in private mode, or one
 * configured to refuse site data, throws on the accessor itself - so every read
 * and every write is wrapped, and the fallback is the default rather than a
 * broken rail.
 */

/** 04 D1 names this key. `localStorage`, because the switch is about the person. */
export const EXPERT_STORAGE_KEY = 'builder-inspector-expert'

/** `sessionStorage`, keyed by node kind, because the disclosure is about the task. */
export const ADVANCED_STORAGE_KEY = 'builder-inspector-advanced'

function readExpert(): boolean {
  try {
    return window.localStorage.getItem(EXPERT_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

function readAdvanced(): Record<string, boolean> {
  try {
    const stored = window.sessionStorage.getItem(ADVANCED_STORAGE_KEY)
    if (!stored) return {}
    const parsed: unknown = JSON.parse(stored)
    if (!parsed || typeof parsed !== 'object') return {}
    const out: Record<string, boolean> = {}
    for (const [kind, open] of Object.entries(parsed as Record<string, unknown>)) {
      out[kind] = open === true
    }
    return out
  } catch {
    // A half-written or older-shaped entry is discarded rather than repaired.
    return {}
  }
}

/**
 * Whether Expert controls are rendered at all. One value, read by every form.
 *
 * A module singleton rather than a provide, for the same reason `models.ts` is
 * one: N inspector forms mount over the life of a session and all of them mean
 * the same switch. A provide would make the answer depend on which subtree a
 * form happens to be in, which is how "global" quietly becomes "per rail".
 */
export const expertMode = ref(readExpert())

/** Per-kind Advanced disclosure. Absent means closed, which is D1's default. */
const advanced = ref<Record<string, boolean>>(readAdvanced())

export function setExpertMode(on: boolean): void {
  expertMode.value = on
  try {
    window.localStorage.setItem(EXPERT_STORAGE_KEY, on ? '1' : '0')
  } catch {
    /* Losing the preference costs one click next session and nothing else. */
  }
}

export function isAdvancedOpen(kind: string): boolean {
  return advanced.value[kind] === true
}

export function setAdvancedOpen(kind: string, open: boolean): void {
  advanced.value = { ...advanced.value, [kind]: open }
  try {
    window.sessionStorage.setItem(ADVANCED_STORAGE_KEY, JSON.stringify(advanced.value))
  } catch {
    /* As above. */
  }
}

/**
 * Drop both settings and re-read them. Exported for tests, and honest about it:
 * a module singleton outlives one spec file's expectations, and a store that
 * cannot be reset makes the second test in a file depend on the first.
 */
export function resetInspectorTiers(): void {
  expertMode.value = readExpert()
  advanced.value = readAdvanced()
}
