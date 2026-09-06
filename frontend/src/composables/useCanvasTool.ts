import { computed, onBeforeUnmount, onMounted, ref, type ComputedRef, type Ref } from 'vue'

/**
 * The one pointer tool both canvases share, and the keyboard that switches it.
 *
 * `DEFINITION-OF-DONE.md` U3 asks for a Select / Hand toggle on the run console
 * AND the builder, with the same keys, the same cursor and the same accessible
 * names. It also carries D3, which keeps R2 standing: **Hand is Vue Flow's own
 * `panOnDrag`, not a pointer layer of ours.** So everything below resolves to
 * one boolean-or-array that is handed straight to `<VueFlow>`; nothing here
 * listens for a pointer, computes a delta, or writes a transform.
 *
 * WHY ONE LEVER IS ENOUGH, and it is worth writing down because the obvious
 * second one is a trap. Vue Flow 1.48.2 computes, in `Viewport`:
 *
 * ```js
 * shouldPanOnDrag  = (!selectionKeyPressed || selectionKeyCode === true) && (panKeyPressed || panOnDrag)
 * shouldSelectOnDrag = selectionKeyCode === true && shouldPanOnDrag !== true
 * ```
 *
 * So on the builder - which passes `selection-key-code="true"` to get a
 * left-drag marquee - setting `panOnDrag` to the literal `true` makes
 * `shouldPanOnDrag` exactly `true`, which makes `shouldSelectOnDrag` false and
 * turns the marquee off by itself. Flipping `selectionKeyCode` as well would be
 * a second lever for a state the library already derives, and a second lever is
 * a second thing to get out of step. The E2E proves the derivation rather than
 * trusting this comment: in Hand mode on the builder no `.vue-flow__selection`
 * appears and the viewport transform moves.
 *
 * THE ARRAY IS NOT DECORATION EITHER. `[1, 2]` is middle and right; left is
 * deliberately absent, because that is what leaves the left button to the
 * marquee on the builder and to nothing at all on the console. Vue Flow's d3
 * filter rejects a `mousedown` whose button is not in the array *before* it
 * looks at anything else, which is why Space cannot be implemented by the
 * library's `panActivationKeyCode` alone - see `spaceHeld` below.
 */

/** Which tool the pointer is. */
export type CanvasTool = 'select' | 'hand'

/** Which canvas is asking. The only thing it decides is the resting tool. */
export type CanvasSurface = 'console' | 'builder'

/**
 * The resting tool per canvas, chosen to be TODAY'S BEHAVIOUR on first load.
 *
 * The console has never had a `pan-on-drag` prop, so it inherits the library
 * default of `true` and a left-drag pans it - that is Hand, and it has been
 * Hand since the console existed. The builder passes `[1, 2]` and
 * `selection-key-code="true"` so a left-drag marquees - that is Select
 * (`BuilderCanvas.vue`'s own note: "a corner-to-corner unmodified drag selected
 * nothing and moved the viewport instead", which is the defect these defaults
 * must not reintroduce).
 *
 * Measured before the change, at `63bd2b2`, on the synthetic backend: a
 * left-drag on the console moved the transform from `translate(57.96px,
 * 25.19px)` to `translate(177.96px, 105.19px)`, and the same drag on the
 * builder left `translate(124px, 26.23px)` untouched while
 * `.vue-flow__selection` appeared. So no existing E2E sees a different canvas
 * on its first frame than it saw yesterday.
 *
 * NOT PERSISTED. `sessionStorage` was offered and declined: a remembered tool
 * makes the first frame of every test depend on what the previous test did,
 * which is the one property this table exists to guarantee.
 */
const RESTING_TOOL: Readonly<Record<CanvasSurface, CanvasTool>> = {
  console: 'hand',
  builder: 'select',
}

/**
 * Middle and right. Left belongs to the marquee (builder) or to nothing
 * (console), which is what "Select" means on each.
 */
const PAN_BUTTONS_WITHOUT_LEFT: readonly number[] = [1, 2]

/** What a canvas binds. */
export interface CanvasToolApi {
  /** The mode the toggle shows. Written through `setTool`, never assigned. */
  readonly tool: Ref<CanvasTool>
  /** True while Hand is the mode - what `aria-pressed` on the Hand button reads. */
  readonly isHand: ComputedRef<boolean>
  /** True while the space bar is down, wherever the mode is. */
  readonly spaceHeld: Ref<boolean>
  /**
   * Hand OR space: the tool the pointer actually has this instant. The cursor
   * and `panOnDrag` follow this; `aria-pressed` deliberately does not, because
   * holding a key is not changing a mode.
   */
  readonly panning: ComputedRef<boolean>
  /** Straight onto `<VueFlow :pan-on-drag>`. */
  readonly panOnDrag: ComputedRef<boolean | number[]>
  /** `is-hand-tool` / `is-select-tool`, for the cursor rules in `studio.css`. */
  readonly canvasClass: ComputedRef<string>
  /** The only way `tool` moves. */
  setTool: (next: CanvasTool) => void
}

/**
 * True when a keystroke belongs to whatever the user is typing into.
 *
 * Lifted verbatim from `BuilderCanvas.vue`, where it guarded the space bar
 * alone. It matters far more now: `h` and `v` are letters somebody types into
 * a node's prompt every few seconds, and a shortcut that fires from inside a
 * textarea is a shortcut that eats the document.
 */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.isContentEditable ||
    target.tagName === 'INPUT' ||
    target.tagName === 'TEXTAREA' ||
    target.tagName === 'SELECT'
  )
}

export function useCanvasTool(surface: CanvasSurface): CanvasToolApi {
  const tool = ref<CanvasTool>(RESTING_TOOL[surface])

  /**
   * True while the space bar is held, and the reason `panOnDrag` is a computed
   * rather than a constant per mode.
   *
   * Moved here from `BuilderCanvas.vue` unchanged in behaviour - the same three
   * listeners on `window`, the same repeat guard, the same typing guard, the
   * same `blur` release - because the console needs the identical thing and two
   * copies of a keyboard latch is exactly how the two canvases drifted apart in
   * the first place. Its original note is still the reason it cannot be the
   * library's own `panActivationKeyCode`: measured, holding space correctly
   * drops `.selection` off the pane so a drag no longer marquees, and then the
   * drag does nothing at all, because the d3 filter still refuses button 0
   * while `panOnDrag` is an array that excludes it. Widening `panOnDrag` to
   * `true` for exactly as long as the key is down is the remaining half, and it
   * is still Vue Flow doing the panning (R2) - one boolean, not a pointer
   * layer.
   *
   * Scoped to `keyup`/`blur` as well as `keydown`, because a key released while
   * the window is not focused never sends a `keyup` and the canvas would be
   * stuck unable to marquee for the rest of the session.
   */
  const spaceHeld = ref(false)

  function setTool(next: CanvasTool): void {
    tool.value = next
  }

  /**
   * One `keydown` listener for both jobs, and the ORDER of its guards is the
   * whole of its correctness.
   *
   * Space is answered FIRST, behind the same two guards it had before this
   * composable existed and no others - so `Shift`+space, which used to pan,
   * still pans. `h` and `v` are answered after the modifier guard, so
   * `Ctrl`/`Cmd`+`V` stays paste (`useBuilderHotkeys` owns it) and nothing here
   * competes with a browser or OS chord. `event.key` rather than `event.code`,
   * because these are named after the letters printed on the toggle.
   */
  function onKeyDown(event: KeyboardEvent): void {
    if (isTypingTarget(event.target)) return

    if (event.code === 'Space') {
      if (!event.repeat) spaceHeld.value = true
      return
    }

    if (event.repeat) return
    if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return

    const key = event.key.toLowerCase()
    if (key === 'h') setTool('hand')
    else if (key === 'v') setTool('select')
  }

  function onKeyUp(event: KeyboardEvent): void {
    if (event.code === 'Space') spaceHeld.value = false
  }

  function releaseSpace(): void {
    spaceHeld.value = false
  }

  onMounted(() => {
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('blur', releaseSpace)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onKeyDown)
    window.removeEventListener('keyup', onKeyUp)
    window.removeEventListener('blur', releaseSpace)
  })

  const isHand = computed(() => tool.value === 'hand')
  const panning = computed(() => isHand.value || spaceHeld.value)
  const panOnDrag = computed<boolean | number[]>(() =>
    panning.value ? true : [...PAN_BUTTONS_WITHOUT_LEFT],
  )
  const canvasClass = computed(() => (panning.value ? 'is-hand-tool' : 'is-select-tool'))

  return { tool, isHand, spaceHeld, panning, panOnDrag, canvasClass, setTool }
}
