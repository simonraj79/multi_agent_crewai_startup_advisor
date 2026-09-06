import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { App } from 'vue'
import { useCanvasTool, type CanvasSurface } from '../src/composables/useCanvasTool'
import { withSetup } from './helpers'

/**
 * The pointer tool both canvases share (`DEFINITION-OF-DONE.md` U3).
 *
 * What this file can answer and what it cannot is worth stating, because the
 * split is the same one section 14's defects 3 and 4 are about: jsdom has no
 * layout and no d3, so **nothing here proves a drag pans**. What it proves is
 * the state machine that feeds Vue Flow - the resting tool per canvas, the two
 * keys, the guards that stop those keys firing from inside a textarea, the
 * space latch and its release, and the exact `panOnDrag` value each state
 * resolves to. Whether Vue Flow then moves the viewport is
 * `e2e/canvas-controls.spec.ts`'s question, in a real browser, which is the
 * only place it has an answer.
 */

/** A keydown that reaches `window` from wherever it was aimed. */
function keyDown(target: EventTarget, init: KeyboardEventInit): void {
  target.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, ...init }))
}

function keyUp(target: EventTarget, init: KeyboardEventInit): void {
  target.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, ...init }))
}

const SPACE: KeyboardEventInit = { key: ' ', code: 'Space' }
const H: KeyboardEventInit = { key: 'h', code: 'KeyH' }
const V: KeyboardEventInit = { key: 'v', code: 'KeyV' }

describe('the canvas pointer tool', () => {
  let app: App
  let tool: ReturnType<typeof useCanvasTool>

  function mount(surface: CanvasSurface): void {
    ;[tool, app] = withSetup(() => useCanvasTool(surface))
  }

  afterEach(() => {
    app?.unmount()
    document.body.innerHTML = ''
  })

  /**
   * The two resting values, and why they are not the same value.
   *
   * They are today's behaviour written down, not a preference: the console has
   * never passed `pan-on-drag`, so it inherited the library's `true` and a
   * left-drag panned it; the builder passes `[1, 2]` so a left-drag marquees
   * (§4.3). A shared default would have silently changed one of the two
   * canvases on its first frame, which is exactly what D4's baseline
   * regeneration must not be asked to absorb.
   */
  describe('rests where each canvas already was', () => {
    it('opens the console in Hand, panning with every button', () => {
      mount('console')
      expect(tool.tool.value).toBe('hand')
      expect(tool.isHand.value).toBe(true)
      expect(tool.panOnDrag.value).toBe(true)
      expect(tool.canvasClass.value).toBe('is-hand-tool')
    })

    it('opens the builder in Select, leaving the left button to the marquee', () => {
      mount('builder')
      expect(tool.tool.value).toBe('select')
      expect(tool.isHand.value).toBe(false)
      expect(tool.panOnDrag.value).toEqual([1, 2])
      expect(tool.canvasClass.value).toBe('is-select-tool')
    })

    it('hands out a fresh array, so a consumer cannot edit the next canvas', () => {
      mount('builder')
      const first = tool.panOnDrag.value as number[]
      first.push(0)
      app.unmount()
      mount('builder')
      expect(tool.panOnDrag.value).toEqual([1, 2])
    })
  })

  describe('the toggle', () => {
    it('switches both ways and takes the pan value with it', () => {
      mount('builder')
      tool.setTool('hand')
      expect(tool.panOnDrag.value).toBe(true)
      expect(tool.canvasClass.value).toBe('is-hand-tool')
      tool.setTool('select')
      expect(tool.panOnDrag.value).toEqual([1, 2])
      expect(tool.canvasClass.value).toBe('is-select-tool')
    })
  })

  describe('H and V', () => {
    it('switches to Hand on H and back to Select on V, on the builder', () => {
      mount('builder')
      keyDown(window, H)
      expect(tool.tool.value).toBe('hand')
      keyDown(window, V)
      expect(tool.tool.value).toBe('select')
    })

    it('switches on the console too - one keyboard, both canvases', () => {
      mount('console')
      keyDown(window, V)
      expect(tool.tool.value).toBe('select')
      keyDown(window, H)
      expect(tool.tool.value).toBe('hand')
    })

    it('reads the letter, not the case, so caps lock is not a broken shortcut', () => {
      mount('builder')
      keyDown(window, { key: 'H', code: 'KeyH' })
      expect(tool.tool.value).toBe('hand')
    })

    /**
     * The guard that matters most, because `h` and `v` are letters somebody
     * types into a node's prompt every few seconds. A shortcut that fires from
     * inside a textarea is a shortcut that eats the document.
     */
    it.each([
      ['input', () => document.createElement('input')],
      ['textarea', () => document.createElement('textarea')],
      ['select', () => document.createElement('select')],
    ])('ignores a keystroke aimed at a %s', (_name, make) => {
      mount('builder')
      const field = make()
      document.body.append(field)
      keyDown(field, H)
      expect(tool.tool.value).toBe('select')
    })

    it('ignores a keystroke aimed at a contenteditable', () => {
      mount('builder')
      const editable = document.createElement('div')
      editable.setAttribute('contenteditable', 'true')
      Object.defineProperty(editable, 'isContentEditable', { value: true })
      document.body.append(editable)
      keyDown(editable, H)
      expect(tool.tool.value).toBe('select')
    })

    /**
     * `Ctrl`/`Cmd`+`V` is paste and `useBuilderHotkeys` owns it; the other
     * three are browser and OS chords. None of them may move the tool.
     */
    it.each([
      ['ctrl', { ctrlKey: true }],
      ['meta', { metaKey: true }],
      ['alt', { altKey: true }],
      ['shift', { shiftKey: true }],
    ])('ignores %s + H', (_name, modifier) => {
      mount('builder')
      keyDown(window, { ...H, ...modifier })
      expect(tool.tool.value).toBe('select')
    })

    it('ignores an auto-repeat, so holding H is one switch and not a stream', () => {
      mount('builder')
      keyDown(window, { ...H, repeat: true })
      expect(tool.tool.value).toBe('select')
    })
  })

  describe('the space bar', () => {
    it('pans temporarily from Select without moving the toggle', () => {
      mount('builder')
      keyDown(window, SPACE)
      expect(tool.spaceHeld.value).toBe(true)
      expect(tool.panOnDrag.value).toBe(true)
      expect(tool.canvasClass.value).toBe('is-hand-tool')
      // The MODE is untouched: `aria-pressed` reads this, and a toggle that
      // flickered while a key was held would announce a change that never was.
      expect(tool.tool.value).toBe('select')
      expect(tool.isHand.value).toBe(false)
    })

    it('gives the left button back on keyup', () => {
      mount('builder')
      keyDown(window, SPACE)
      keyUp(window, SPACE)
      expect(tool.spaceHeld.value).toBe(false)
      expect(tool.panOnDrag.value).toEqual([1, 2])
    })

    /**
     * A key released while the window is not focused never sends a `keyup`,
     * and the canvas would be stuck unable to marquee for the rest of the
     * session. `BuilderCanvas` learnt this before the composable existed.
     */
    it('releases on blur, not only on keyup', () => {
      mount('builder')
      keyDown(window, SPACE)
      window.dispatchEvent(new Event('blur'))
      expect(tool.spaceHeld.value).toBe(false)
    })

    it('is ignored inside a textarea, where space is a space', () => {
      mount('builder')
      const field = document.createElement('textarea')
      document.body.append(field)
      keyDown(field, SPACE)
      expect(tool.spaceHeld.value).toBe(false)
    })

    /**
     * Space keeps the guards it had in `BuilderCanvas` and NO others. It is
     * answered before the modifier check on purpose: `Shift`+space panned
     * before U3, and a refactor that quietly took that away would be a
     * behaviour change hiding inside a move.
     */
    it('still pans with a modifier held, as it did before the toggle existed', () => {
      mount('builder')
      keyDown(window, { ...SPACE, shiftKey: true })
      expect(tool.spaceHeld.value).toBe(true)
    })

    it('changes nothing while the canvas is already in Hand', () => {
      mount('console')
      keyDown(window, SPACE)
      expect(tool.panOnDrag.value).toBe(true)
      keyUp(window, SPACE)
      expect(tool.panOnDrag.value).toBe(true)
      expect(tool.tool.value).toBe('hand')
    })
  })

  it('stops listening when the canvas goes away', () => {
    mount('builder')
    app.unmount()
    keyDown(window, H)
    keyDown(window, SPACE)
    expect(tool.tool.value).toBe('select')
    expect(tool.spaceHeld.value).toBe(false)
  })
})
