import { readonly, ref } from 'vue'

/**
 * Light or dark, as a `data-theme` attribute on the document element.
 *
 * 02-canvas.md D6, and it is one attribute and one localStorage key because
 * that is genuinely all it needs to be: `tokens.css` carries the whole light
 * palette as one `:root[data-theme='light']` block, so nothing outside this
 * file knows a theme exists. No component branches on it, no prop threads
 * through the shell, and a new surface is themed by using tokens - which is the
 * rule anyway.
 *
 * THREE PREFERENCES, TWO ATTRIBUTE VALUES, and the asymmetry is the one design
 * decision here. `system` is the default and it is not a synonym for dark: the
 * palette follows `prefers-color-scheme` while nobody has chosen. But the
 * ATTRIBUTE is always resolved to `light` or `dark`, never left off, so
 * `tokens.css` needs exactly one light block rather than the same thirty
 * declarations written twice - once under the attribute and once under a media
 * query. Two copies of a palette is two palettes, and the one that rots is
 * always the one nobody looks at.
 *
 * The cost of resolving in script is that `system` has to be WATCHED: a reader
 * who flips their OS to dark while the tab is open would otherwise keep the
 * light palette until they reloaded. `matchMedia`'s change event closes that,
 * and only while the preference is `system` - an explicit choice outranks the
 * operating system, because a preference expressed on this page should not be
 * overridden by one expressed somewhere else.
 *
 * NOT A DOCUMENT COMMIT (D6, D10). The theme is a property of the reader and
 * not of the graph: putting it in the undo ring would make Ctrl+Z change the
 * lights, and would ship one author's preference to everybody who opens their
 * published document.
 */

/** The three preferences. `system` is the one a fresh reader is in. */
export type StudioTheme = 'system' | 'light' | 'dark'
/** What actually gets written to `data-theme`, and what `tokens.css` reads. */
export type ResolvedTheme = 'light' | 'dark'

/**
 * The key, `studio-` prefixed like the rest of this app's browser storage.
 *
 * Read defensively everywhere below: a private window, cleared site data, or a
 * browser configured to block storage all make these calls THROW rather than
 * return null, and a theme toggle must never be what stops the builder booting.
 */
export const THEME_STORAGE_KEY = 'studio-theme'
/** The query `system` resolves against. Named once, used three times. */
export const LIGHT_QUERY = '(prefers-color-scheme: light)'

const THEMES: readonly StudioTheme[] = ['system', 'light', 'dark']

function isTheme(value: unknown): value is StudioTheme {
  return typeof value === 'string' && (THEMES as readonly string[]).includes(value)
}

/** What is stored, or `system` when nothing is stored and when the read throws. */
export function storedTheme(): StudioTheme {
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY)
    return isTheme(raw) ? raw : 'system'
  } catch {
    return 'system'
  }
}

/** What the operating system asks for, and `dark` where it cannot be asked. */
export function systemTheme(): ResolvedTheme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'dark'
  return window.matchMedia(LIGHT_QUERY).matches ? 'light' : 'dark'
}

/** A preference, resolved to the one of two things the stylesheet understands. */
export function resolveTheme(preference: StudioTheme): ResolvedTheme {
  return preference === 'system' ? systemTheme() : preference
}

/**
 * The module-level state, so every caller sees one answer.
 *
 * A module singleton rather than per-call state: `DocumentBar`'s button and the
 * `⇧L` binding are two callers of one preference, and two independent refs
 * would let the button and the key disagree about what the page is showing.
 */
const preference = ref<StudioTheme>('system')
const resolved = ref<ResolvedTheme>('dark')
let started = false
let media: MediaQueryList | null = null

function paint(): void {
  resolved.value = resolveTheme(preference.value)
  if (typeof window === 'undefined') return
  window.document.documentElement.setAttribute('data-theme', resolved.value)
}

export function useStudioTheme() {
  if (!started && typeof window !== 'undefined') {
    started = true
    preference.value = storedTheme()
    paint()
    if (typeof window.matchMedia === 'function') {
      media = window.matchMedia(LIGHT_QUERY)
      // `addEventListener` and not `addListener`: the deprecated form is absent
      // in every browser this ships to, and the listener is never removed
      // because the app owns the document for its whole lifetime.
      media.addEventListener?.('change', () => {
        if (preference.value === 'system') paint()
      })
    }
  }

  function setTheme(next: StudioTheme): void {
    preference.value = next
    paint()
    if (typeof window === 'undefined') return
    try {
      if (next === 'system') window.localStorage.removeItem(THEME_STORAGE_KEY)
      else window.localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // A private window, or storage the browser refuses. The theme still
      // applied; it simply will not survive a reload, which is the right
      // failure - the alternative is a toggle that throws.
    }
  }

  /**
   * What `⇧L` and the button both do: flip to the OPPOSITE of what is on screen.
   *
   * From `system` that means resolving the media query first, so the first press
   * always visibly changes something. A toggle that cycled
   * `system -> light -> dark` would look broken to a reader whose system is
   * already light, because the first press would do nothing at all.
   */
  function toggleTheme(): void {
    setTheme(resolved.value === 'dark' ? 'light' : 'dark')
  }

  return { theme: readonly(preference), resolved: readonly(resolved), setTheme, toggleTheme }
}

/** Test-only: forget the singleton so the next `useStudioTheme` re-reads storage. */
export function resetStudioTheme(): void {
  started = false
  media = null
  preference.value = 'system'
  resolved.value = 'dark'
  if (typeof window !== 'undefined') {
    window.document.documentElement.removeAttribute('data-theme')
  }
}
