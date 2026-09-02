import { onBeforeUnmount } from 'vue'

/**
 * Give the keyboard back where it came from when an overlay closes.
 *
 * WCAG 2.4.3 (Focus Order) in the one place a dialog always breaks it: all four
 * of this deliverable's overlays - `ShortcutSheet`, `PublishDialog`,
 * `ConflictDialog` and `PortMenu` - moved focus IN on open and none of them
 * moved it back on close, so dismissing any of them dropped a keyboard author
 * on `<body>`. Measured: open the sheet from its header button, press Escape,
 * `document.activeElement` is `BODY`, and getting back to Publish is twelve
 * more Tabs. A sighted mouse user never sees this; a keyboard user pays it
 * every single time.
 *
 * ONE composable rather than four identical five-line additions, because four
 * copies is four chances for the next overlay to be the one that forgets - and
 * the "capture the opener" half is the half that is easy to leave out, since
 * omitting it produces no symptom until somebody actually closes the thing.
 *
 * `capture()` must be called BEFORE the overlay moves focus, which in practice
 * means at the top of the same `watch` that focuses the first control.
 */
export function useReturnFocus() {
  let opener: HTMLElement | null = null

  /** Remember whatever had the keyboard, unless it was already the overlay's. */
  function capture(): void {
    const active = typeof document === 'undefined' ? null : document.activeElement
    opener = active instanceof HTMLElement ? active : null
  }

  /**
   * Hand it back, if it is still there to hand back to.
   *
   * `isConnected` is the guard that matters and it is not theoretical: the
   * `PortMenu` is opened from a port on a node, and the node can be deleted
   * while the menu is open. Focusing a detached element silently moves focus to
   * `<body>` - the exact failure this exists to fix - so a lost opener is
   * treated as "no opener" and focus is left where the browser put it rather
   * than being thrown somewhere worse.
   */
  function restore(): void {
    const target = opener
    opener = null
    if (!target || !target.isConnected) return
    // A hidden or removed-from-layout opener refuses focus without throwing;
    // there is nothing to do about that here and nothing to report.
    target.focus()
  }

  /** An overlay unmounted while open has no `close` to run. Drop the reference. */
  onBeforeUnmount(() => {
    opener = null
  })

  return { capture, restore }
}
