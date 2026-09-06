import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ShortcutSheet from '../src/components/builder/ShortcutSheet.vue'
import {
  HOTKEY_BINDINGS,
  bindingLabels,
  matchBinding,
} from '../src/composables/useBuilderHotkeys'

/**
 * The sheet and the dispatcher read ONE table, and this is what makes that
 * provable in both directions.
 *
 * 02-canvas.md criterion 12, and its wording is the test: "adding the theme
 * toggle key fails `shortcutSheet.spec.ts` unless declared". Two failure modes
 * are being closed and they are opposites - a shortcut that is documented and
 * unbound teaches an author a key that does nothing, and one that is bound and
 * undocumented is a feature nobody finds. Set equality in both directions makes
 * both unrepresentable, so the only way to add a shortcut is to add it to
 * `HOTKEY_BINDINGS`, and adding it there publishes it.
 *
 * `builderShell.spec.ts` already asserts the equality; this file is the
 * criterion's own, and it goes one step further by proving the round trip for
 * the binding the criterion names: `⇧L` is declared, printed, and dispatched to
 * `toggleTheme` by a real `KeyboardEvent`.
 */

function open() {
  return mount(ShortcutSheet, { props: { open: true } })
}

/** Every binding id the sheet actually printed, from its own testids. */
function printedIds(wrapper: ReturnType<typeof open>): string[] {
  return wrapper
    .findAll('[data-testid^="shortcut-"]')
    .map((row) => row.attributes('data-testid')!.replace('shortcut-', ''))
}

describe('the sheet prints the table the listener dispatches from', () => {
  it('prints every declared binding, and nothing that is not declared', () => {
    const printed = printedIds(open()).sort()
    const declared = HOTKEY_BINDINGS.map((binding) => binding.id).sort()
    expect(printed).toEqual(declared)
  })

  it('prints each binding under its own declared label and chords', () => {
    const wrapper = open()
    for (const binding of HOTKEY_BINDINGS) {
      const row = wrapper.find(`[data-testid="shortcut-${binding.id}"]`)
      expect(row.exists(), binding.id).toBe(true)
      expect(row.find('dt').text(), binding.id).toBe(binding.label)
      const keys = row.findAll('kbd').map((key) => key.text())
      // `bindingLabels` derives the printed glyph from the SAME chord
      // `matchesChord` compares, so a hand-written label beside a hand-written
      // matcher - two copies of one fact, one of which rots - is impossible.
      expect(keys.length, binding.id).toBeGreaterThan(0)
      expect(bindingLabels(binding), binding.id).toEqual(expect.arrayContaining(keys))
    }
  })

  it('gives every binding a unique id, so no row can shadow another', () => {
    const ids = HOTKEY_BINDINGS.map((binding) => binding.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})

/* --- the criterion's own binding ------------------------------------------ */

describe('the theme toggle is declared, printed and dispatched as one fact', () => {
  it('is in the binding table at all', () => {
    const theme = HOTKEY_BINDINGS.find((binding) => binding.id === 'theme')
    expect(theme).toBeDefined()
    expect(theme?.label).toBe('Switch between light and dark')
  })

  it('appears in the sheet, which is what "unless declared" means', () => {
    // Delete the binding and this row is gone AND the set equality above fails.
    // Declare it without the sheet reading the table and the first test fails
    // instead. There is no state in which one is true and the other is not.
    expect(printedIds(open())).toContain('theme')
  })

  it('is `Shift+L`, and the bare `l` it deliberately does not claim stays free', () => {
    const shifted = new KeyboardEvent('keydown', { key: 'L', shiftKey: true })
    expect(matchBinding(shifted)?.id).toBe('theme')

    // `matchesChord` compares the shift flag rather than ignoring it. A bare
    // letter would be wrong here in a way it is not wrong for `f` or `r`: those
    // act on the graph and are undone by the same key, while this repaints the
    // whole application.
    expect(matchBinding(new KeyboardEvent('keydown', { key: 'l' }))).toBeNull()
  })

  it('does not collide with the canvas tools, which now sit in the same table', () => {
    // `Shift+L` and the bare `v`/`h` are different keys, and this is the
    // assertion that says so after C4 put three bare letters in one table.
    expect(matchBinding(new KeyboardEvent('keydown', { key: 'v' }))).toBeNull()
    expect(matchBinding(new KeyboardEvent('keydown', { key: 'h' }))).toBeNull()
  })

  it('does not collide with any other declared chord', () => {
    // The three attachment kinds took `T`, `M` and `K` (decision 18) and the
    // digits `1`-`7` select a kind on the same surface, so a new binding's real
    // risk is a chord another row already answers to.
    const event = new KeyboardEvent('keydown', { key: 'l', shiftKey: true })
    const matches = HOTKEY_BINDINGS.filter((binding) => matchBinding(event)?.id === binding.id)
    expect(matches.map((binding) => binding.id)).toEqual(['theme'])
  })

  it('runs `toggleTheme` and nothing else', () => {
    const theme = HOTKEY_BINDINGS.find((binding) => binding.id === 'theme')!
    const called: string[] = []
    const actions = new Proxy(
      {},
      {
        get:
          (_target, name: string) =>
          () => {
            called.push(name)
          },
      },
    ) as never
    theme.run(actions, new KeyboardEvent('keydown'))
    expect(called).toEqual(['toggleTheme'])
  })

  it('is refused while focus is in a text field, like every binding but two', () => {
    // `Escape` is how an author gets OUT of a field and `⌘S` is muscle memory
    // that must work from anywhere. Repainting the application mid-word is
    // neither.
    expect(theme().allowInTextEntry).toBe(false)
  })
})

function theme() {
  return HOTKEY_BINDINGS.find((binding) => binding.id === 'theme')!
}

/* ── C4: the canvas tools are in the sheet, and still bound only once ────────
 *
 * `V` and `H` have been real keys since the canvas tool landed
 * (`useCanvasTool.ts`), and until now they were advertised in a `title`
 * tooltip and nowhere else - so the sheet that exists to make a bound key a
 * discoverable one could not show the two keys every design tool this product
 * is measured against puts on the same letters. That is exactly the failure
 * this file's docstring names ("bound and undocumented is a feature nobody
 * finds"), and it was invisible to the set-equality assertion above because
 * the table it compares against did not contain them either.
 *
 * The other half is what a careless fix breaks. A binding declared here with a
 * `run` would be bound TWICE - two window listeners for one keystroke, and
 * `dispatchHotkey` calling `preventDefault` on a key it does not handle - so
 * the row is marked `documentedElsewhere` and `matchBinding` skips it. Both
 * halves are asserted, because either alone is the wrong thing.
 */
describe('Select and Hand are printed here and dispatched by useCanvasTool', () => {
  const tools = () => HOTKEY_BINDINGS.filter((binding) => binding.group === 'canvas')

  it('declares both, on the letters the canvas controls already print', () => {
    expect(tools().map((binding) => binding.id)).toEqual(['tool-select', 'tool-hand'])
    expect(bindingLabels(tools()[0])).toEqual(['V'])
    expect(bindingLabels(tools()[1])).toEqual(['H'])
  })

  it('prints them in the sheet, under a group of their own', () => {
    const wrapper = open()
    expect(printedIds(wrapper)).toEqual(expect.arrayContaining(['tool-select', 'tool-hand']))
    expect(wrapper.text()).toContain('The canvas')
    expect(wrapper.get('[data-testid="shortcut-tool-select"]').text()).toContain('Select tool')
    expect(wrapper.get('[data-testid="shortcut-tool-hand"]').text()).toContain('Hand tool')
  })

  it('binds neither a second time: this table dispatches nothing for V or H', () => {
    // The whole point. `useCanvasTool` owns these keys on its own listener,
    // together with the space-bar temporary pan whose guard ORDER is the whole
    // of its correctness; a second dispatcher would answer the same keystroke
    // and `preventDefault` it on the way.
    expect(matchBinding(new KeyboardEvent('keydown', { key: 'v' }))).toBeNull()
    expect(matchBinding(new KeyboardEvent('keydown', { key: 'V' }))).toBeNull()
    expect(matchBinding(new KeyboardEvent('keydown', { key: 'h' }))).toBeNull()
    for (const binding of tools()) expect(binding.documentedElsewhere).toBe(true)
  })

  it('leaves Ctrl+V paste alone, which shares a letter with Select', () => {
    const paste = matchBinding(new KeyboardEvent('keydown', { key: 'v', ctrlKey: true }))
    expect(paste?.id).toBe('paste')
  })
})
