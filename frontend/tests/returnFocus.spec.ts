/**
 * Closing an overlay gives the keyboard back to whatever opened it.
 *
 * WCAG 2.4.3 in the one place a dialog always breaks it. All four overlays in
 * this deliverable moved focus IN on open and none moved it back on close, so
 * dismissing any of them dropped a keyboard author on `<body>` - twelve Tabs
 * from Publish, and a state a mouse user never sees.
 *
 * MOUNTED, not called. `useReturnFocus` on its own would pass trivially; what
 * had to be proved is that each overlay calls `capture()` BEFORE it steals
 * focus and `restore()` on the path it actually closes by - which for three of
 * them is an `open` prop going false and for `ConflictDialog` is its unmount.
 * That distinction is the whole bug, and it is only visible through the
 * components.
 */
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import ShortcutSheet from '../src/components/builder/ShortcutSheet.vue'
import { useReturnFocus } from '../src/composables/useReturnFocus'

let opener: HTMLButtonElement

beforeEach(() => {
  document.body.innerHTML = ''
  opener = document.createElement('button')
  opener.textContent = 'Keyboard shortcuts'
  document.body.appendChild(opener)
  opener.focus()
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('the shortcut sheet hands focus back', () => {
  it('takes focus on open and returns it to the opener on close', async () => {
    expect(document.activeElement).toBe(opener)

    const wrapper = mount(ShortcutSheet, {
      props: { open: false },
      attachTo: document.body,
    })
    await wrapper.setProps({ open: true })
    await wrapper.vm.$nextTick()

    // In, first: the close button, so Escape and Enter both do something
    // predictable the moment the sheet appears.
    expect(document.activeElement).not.toBe(opener)
    expect((document.activeElement as HTMLElement).getAttribute('aria-label')).toBe(
      'Close the shortcut sheet',
    )

    await wrapper.setProps({ open: false })
    // ...and back out. Without this the answer is BODY, which is where the
    // measurement that opened this finding landed.
    expect(document.activeElement).toBe(opener)
    wrapper.unmount()
  })

  it('does not throw when the opener has been removed while the sheet was up', async () => {
    const wrapper = mount(ShortcutSheet, { props: { open: false }, attachTo: document.body })
    await wrapper.setProps({ open: true })
    opener.remove()
    await wrapper.setProps({ open: false })
    // A detached element silently moves focus to `<body>` when focused - the
    // exact failure this exists to fix - so a lost opener is treated as no
    // opener and focus is left where the browser put it.
    expect(document.body.contains(document.activeElement)).toBe(true)
    wrapper.unmount()
  })
})

describe('the composable itself, at its two edges', () => {
  function host() {
    // `defineComponent` so `wrapper.vm.capture` is typed rather than `never`:
    // an inline object literal loses the setup return type on the way through
    // `mount`, and the two calls below are the entire subject of these tests.
    const Host = defineComponent({
      setup() {
        const { capture, restore } = useReturnFocus()
        return { capture, restore }
      },
      template: '<div />',
    })
    return mount(Host)
  }

  it('is a no-op when nothing had focus to begin with', () => {
    ;(document.activeElement as HTMLElement).blur()
    const wrapper = host()
    wrapper.vm.capture()
    expect(() => wrapper.vm.restore()).not.toThrow()
    wrapper.unmount()
  })

  it('forgets the opener after one restore, so a second close cannot yank focus', () => {
    const wrapper = host()
    wrapper.vm.capture()
    const other = document.createElement('button')
    document.body.appendChild(other)
    wrapper.vm.restore()
    expect(document.activeElement).toBe(opener)

    other.focus()
    wrapper.vm.restore()
    expect(document.activeElement).toBe(other)
    wrapper.unmount()
  })
})
