import { readFileSync } from 'node:fs'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  LIGHT_QUERY,
  THEME_STORAGE_KEY,
  resetStudioTheme,
  resolveTheme,
  useStudioTheme,
} from '../src/composables/useStudioTheme'

/**
 * The light theme is a palette and a preference, and nothing else.
 *
 * 02-canvas.md D6 and criterion 9. Two things are pinned here and the visual
 * specs pin the third:
 *
 *   1. `tokens.css` really carries a `[data-theme="light"]` block, and that
 *      block moves surfaces, text, borders, canvas, edges, glows and the two
 *      status tints - and NOT the kind accents. A kind that is one colour in
 *      the dark and another in the light is a kind an author learns twice.
 *   2. The preference is three-state and the attribute is two-state.
 *      `system` follows `prefers-color-scheme`, an explicit choice outranks it,
 *      and the choice survives a reload through one localStorage key.
 *
 * What is NOT here is whether it LOOKS right, because a jsdom mount never asks
 * how wide anything ended up (MISSION.md trap 13). That is
 * `e2e/visual/builder-canvas.spec.ts`, in a real browser, at two viewports.
 */

const TOKENS = readFileSync(path.resolve(process.cwd(), 'src/assets/styles/tokens.css'), 'utf8')

/** Every custom property the light block redefines. */
function lightBlockTokens(): string[] {
  const start = TOKENS.indexOf(":root[data-theme='light']")
  expect(start, 'tokens.css has no light block').toBeGreaterThan(-1)
  const body = TOKENS.slice(start, TOKENS.indexOf('}', start))
  return [...body.matchAll(/^\s*(--[a-z0-9-]+):/gm)].map((match) => match[1])
}

describe('tokens.css carries one light palette, under one attribute', () => {
  it('declares the block the criterion names', () => {
    expect(TOKENS).toContain("[data-theme='light']")
  })

  it('moves the surfaces, the text, the borders, the edges and the glows', () => {
    const moved = new Set(lightBlockTokens())
    for (const token of [
      '--bg-app',
      '--bg-node',
      '--surface-panel',
      '--surface-raised',
      '--surface-overlay',
      '--border-default',
      '--text-primary',
      '--text-body',
      '--text-title',
      '--text-muted',
      '--text-40',
      '--dot-color',
      '--edge-inactive',
      '--edge-label-bg',
      '--glow-input',
    ]) {
      expect(moved, token).toContain(token)
    }
  })

  it('leaves every kind accent exactly where the dark theme put it', () => {
    // D6: accents and kind gradients are SHARED. The squircle fill, the minimap
    // dot, the card's gradient rim and an edge's gradient stops are all one
    // value, and a kind whose colour changes with the lights is a kind an
    // author has to learn twice.
    const moved = new Set(lightBlockTokens())
    for (const token of [
      '--accent-mint',
      '--accent-cyan',
      '--accent-blue',
      '--accent-attach',
      '--kind-tool',
      '--kind-mcp',
      '--kind-skill',
      '--gradient-brand',
    ]) {
      expect(moved, token).not.toContain(token)
    }
  })

  it('DOES move the two status tints, because those are read rather than recognised', () => {
    // `--warn-text` and `--err-text` are pale by design against #1a1a1a. An
    // author has to be able to READ an error, so these are not identity and
    // they are not shared.
    const moved = new Set(lightBlockTokens())
    expect(moved).toContain('--warn-text')
    expect(moved).toContain('--err-text')
  })

  it('needs no second copy of the palette, because the attribute is always written', () => {
    // The alternative shape is an attribute block plus a
    // `@media (prefers-color-scheme: light)` block carrying the same thirty
    // declarations. Two copies of a palette is two palettes.
    //
    // Comments stripped first, because the block's own docblock explains the
    // media query it is deliberately not using - and a raw substring search
    // would report the explanation rather than the rule.
    expect(TOKENS.replace(/\/\*[\s\S]*?\*\//g, '')).not.toContain('@media')
  })
})

/* --- the preference -------------------------------------------------------- */

function stubMatchMedia(light: boolean): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === LIGHT_QUERY && light,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  )
}

describe('three preferences, two attribute values', () => {
  beforeEach(() => {
    window.localStorage.clear()
    resetStudioTheme()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    resetStudioTheme()
  })

  it('resolves `system` against prefers-color-scheme and writes the answer', () => {
    stubMatchMedia(true)
    const theme = useStudioTheme()
    expect(theme.theme.value).toBe('system')
    expect(theme.resolved.value).toBe('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })

  it('falls back to dark where the media query cannot be asked at all', () => {
    vi.stubGlobal('matchMedia', undefined)
    expect(resolveTheme('system')).toBe('dark')
  })

  it('lets an explicit choice outrank the operating system, and stores it', () => {
    stubMatchMedia(true)
    const theme = useStudioTheme()
    theme.setTheme('dark')

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  })

  it('reads the stored choice back on the next visit', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'light')
    stubMatchMedia(false)
    expect(useStudioTheme().resolved.value).toBe('light')
  })

  it('ignores a stored value that is not a theme', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'chartreuse')
    stubMatchMedia(false)
    expect(useStudioTheme().theme.value).toBe('system')
  })

  it('toggles to the OPPOSITE of what is on screen, so the first press does something', () => {
    // From `system` on a light machine, a cycle of system -> light -> dark would
    // spend its first press changing nothing at all.
    stubMatchMedia(true)
    const theme = useStudioTheme()
    expect(theme.resolved.value).toBe('light')

    theme.toggleTheme()
    expect(theme.resolved.value).toBe('dark')
    theme.toggleTheme()
    expect(theme.resolved.value).toBe('light')
  })

  it('drops the key when the preference goes back to `system`', () => {
    stubMatchMedia(false)
    const theme = useStudioTheme()
    theme.setTheme('light')
    theme.setTheme('system')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull()
  })

  it('still applies a theme when storage throws, rather than throwing itself', () => {
    // A private window, or a browser configured to block site data. A theme
    // toggle must never be the thing that stops the builder booting.
    stubMatchMedia(false)
    const theme = useStudioTheme()
    const setItem = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('denied')
      })

    expect(() => theme.setTheme('light')).not.toThrow()
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    setItem.mockRestore()
  })
})
