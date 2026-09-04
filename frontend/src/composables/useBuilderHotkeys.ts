import { onBeforeUnmount, onMounted } from 'vue'
import { NODE_KINDS, NODE_KIND_ORDER } from '../data/nodeKinds'
import type { NodeKind } from '../types/builder'

/**
 * Every keyboard binding in the builder, declared once, as data.
 *
 * `ShortcutSheet` renders this table and dispatch reads the same table, which
 * closes both halves of a failure the repo has hit in prose five times: a
 * binding cannot be documented-and-unbound, and it cannot be bound-and-
 * undocumented. The sheet's own spec asserts set equality in both directions,
 * so the only way to add a shortcut is to add it here, and adding it here
 * publishes it.
 *
 * MATCHING AND LABELLING COME FROM THE SAME FIELD. A binding declares chords -
 * `{ mod: true, shift: true, key: 'p' }` - and `matchesChord` and `chordLabel`
 * are both derived from that one declaration. A hand-written `matches` beside a
 * hand-written label is two copies of one fact, and the copy that rots is
 * always the one nobody executes.
 *
 * THE TEXT-ENTRY GATE. While focus is in an input, a textarea or anything
 * `contenteditable`, every binding is ignored except `Escape` and `⌘S`. The
 * exceptions are not symmetric with the rest and should not be: `Escape` is how
 * an author gets OUT of a field they are trapped in, and `⌘S` is muscle memory
 * that must work from wherever the hand happens to be - refusing it mid-word is
 * how unsaved work is lost by a control that was technically behaving.
 */

/** `Ctrl` on Windows and Linux, `Cmd` on macOS. One flag, resolved at the edges. */
export interface HotkeyChord {
  /** `KeyboardEvent.key`, compared case-insensitively. Ignored when `code` is set. */
  key?: string
  /**
   * `KeyboardEvent.code`, for the chords whose `key` depends on the layout.
   * `Shift+1` reports `!` on a US keyboard and something else elsewhere, while
   * the physical key is `Digit1` everywhere.
   */
  code?: string
  mod?: boolean
  shift?: boolean
  alt?: boolean
}

export type HotkeyGroup = 'create' | 'edit' | 'select' | 'navigate' | 'document'

export interface HotkeyBinding {
  /** Stable, and the `data-testid` the sheet and the specs both address. */
  readonly id: string
  readonly group: HotkeyGroup
  readonly label: string
  readonly chords: readonly HotkeyChord[]
  /** Only `Escape` and `⌘S` are true. See the file docblock. */
  readonly allowInTextEntry: boolean
  /**
   * Fires only while focus is inside the canvas. True for `Tab`, `⇧Tab` and the
   * two nudges, and for nothing else.
   *
   * Repurposing `Tab` is legitimate inside `role="application"`, which is
   * exactly what `BuilderCanvas` declares itself to be - and is a WCAG 2.1.1
   * failure anywhere else, because a `preventDefault` on `Tab` at the window
   * would make the palette, the inspector and the document bar unreachable by
   * keyboard for as long as the builder is mounted. The arrows are the same
   * argument one step milder: they would stop every scrollable rail scrolling.
   *
   * The gate is a required constructor argument rather than an option with a
   * permissive default, so the hazardous state is not one a caller can reach by
   * forgetting something.
   */
  readonly requiresCanvasFocus?: boolean
  readonly run: (actions: HotkeyActions, event: KeyboardEvent) => void
}

/** What dispatch needs to know about the world outside the keyboard. */
export interface HotkeyContext {
  /** True while the focused element is the canvas or lives inside it. */
  canvasHasFocus(): boolean
}

/**
 * What the builder can be asked to do from the keyboard.
 *
 * Plain functions rather than the composables themselves, and that is the whole
 * decoupling: this file knows that `⌘Z` means undo and nothing whatever about
 * where undo lives. `BuilderView` is the one place that knows both, which is
 * also the one place that can see whether a binding is wired to the right thing.
 */
export interface HotkeyActions {
  undo(): void
  redo(): void
  save(): void
  publish(): void
  validateNow(): void
  deleteSelection(): void
  selectAll(): void
  escape(): void
  /**
   * Move focus off the canvas, so `Tab` becomes the browser's again.
   *
   * WCAG 2.1.2 (No Keyboard Trap), which is a DIFFERENT criterion from the
   * 2.1.1 argument `requiresCanvasFocus` makes above and was not covered by it.
   * `role="application"` legitimises repurposing `Tab`; it does not exempt the
   * page from providing a documented way out, and there was none - 60 presses
   * of `Tab` from the canvas landed on the canvas 60 times, and every control
   * after it in the DOM (the whole inspector, the problems dock, the zoom
   * buttons, both rail toggles - 57 of them) was unreachable by keyboard for
   * the rest of the session.
   */
  leaveCanvas(): void
  copy(): void
  cut(): void
  paste(): void
  duplicate(): void
  insertKind(kind: NodeKind): void
  renameFocused(): void
  linkFromFocused(): void
  /** Enter, while a keyboard link is live: connect to the numbered candidate. */
  confirmLink(): void
  /** Flow units, already the grid step or one pixel. Never a key code. */
  nudge(dx: number, dy: number): void
  traverse(step: 1 | -1): void
  cycleSibling(step: 1 | -1): void
  fitView(): void
  zoomToActual(): void
  zoomToSelection(): void
  focusFilter(): void
  walkProblems(step: 1 | -1): void
  toggleShortcuts(): void
}

/** The grid step a bare arrow moves, matching `snapGrid` so a nudge lands on a dot. */
const NUDGE_STEP = 20
/** What `Shift` buys: the one-pixel adjustment the grid cannot express. */
const NUDGE_FINE = 1

const ARROWS: Record<string, { dx: number; dy: number }> = {
  ArrowUp: { dx: 0, dy: -1 },
  ArrowDown: { dx: 0, dy: 1 },
  ArrowLeft: { dx: -1, dy: 0 },
  ArrowRight: { dx: 1, dy: 0 },
}

function arrowChords(shift: boolean): HotkeyChord[] {
  return Object.keys(ARROWS).map((key) => ({ key, shift }))
}

/**
 * One binding per kind rather than one binding matching ten keys.
 *
 * The sheet has to be able to say `3 — Insert crew`; a single row reading
 * "1-7 inserts a kind" would leave an author counting tiles to find the one
 * they want, which is the thing a shortcut sheet exists to stop. The key is
 * `NODE_KINDS[kind].hotkey` and is not written down twice - `nodeKinds.ts` owns
 * it, the palette prints it, and this binds it.
 *
 * The three ATTACHMENT kinds answer to `T`, `M` and `K` rather than to `8`,
 * `9` and `0` (owner's decision 18, 2026-09-04): the digits `1`-`7` already
 * select a kind on the same surface, and a second digit row is a collision an
 * author discovers by pressing one.
 *
 * `key` is matched case-insensitively by `matches()` below, so the letters are
 * declared in the case the SHEET should print them in.
 */
const INSERT_BINDINGS: readonly HotkeyBinding[] = NODE_KIND_ORDER.map((kind) => ({
  id: `insert-${kind}`,
  group: 'create' as const,
  label: `Insert ${kind}`,
  chords: [{ key: NODE_KINDS[kind].hotkey }],
  allowInTextEntry: false,
  run: (actions: HotkeyActions) => actions.insertKind(kind),
}))

export const HOTKEY_BINDINGS: readonly HotkeyBinding[] = [
  ...INSERT_BINDINGS,
  {
    id: 'link-from-node',
    group: 'create',
    label: 'Connect from the focused node',
    chords: [{ key: 'e' }],
    allowInTextEntry: false,
    run: (actions) => actions.linkFromFocused(),
  },
  {
    id: 'link-confirm',
    group: 'create',
    label: 'Connect to the highlighted candidate',
    chords: [{ key: 'Enter' }],
    allowInTextEntry: false,
    /*
     * Canvas-gated for the same reason `Tab` is, and here it is not merely
     * polite: an ungated `Enter` with `preventDefault` at the window would stop
     * every button in the palette, the inspector, the problems dock and both
     * dialogs from being activated by keyboard for as long as the builder is
     * mounted. `confirmLink` is a no-op unless a link is live, so the key keeps
     * its ordinary meaning everywhere else on the canvas too.
     */
    requiresCanvasFocus: true,
    run: (actions) => actions.confirmLink(),
  },
  {
    id: 'rename',
    group: 'edit',
    label: 'Rename the focused node',
    chords: [{ key: 'r' }],
    allowInTextEntry: false,
    run: (actions) => actions.renameFocused(),
  },
  {
    id: 'delete',
    group: 'edit',
    label: 'Delete the selection',
    chords: [{ key: 'Delete' }, { key: 'Backspace' }],
    allowInTextEntry: false,
    run: (actions) => actions.deleteSelection(),
  },
  {
    id: 'undo',
    group: 'edit',
    label: 'Undo',
    chords: [{ key: 'z', mod: true }],
    allowInTextEntry: false,
    run: (actions) => actions.undo(),
  },
  {
    id: 'redo',
    group: 'edit',
    label: 'Redo',
    chords: [
      { key: 'z', mod: true, shift: true },
      { key: 'y', mod: true },
    ],
    allowInTextEntry: false,
    run: (actions) => actions.redo(),
  },
  {
    id: 'copy',
    group: 'edit',
    label: 'Copy',
    chords: [{ key: 'c', mod: true }],
    allowInTextEntry: false,
    run: (actions) => actions.copy(),
  },
  {
    id: 'cut',
    group: 'edit',
    label: 'Cut',
    chords: [{ key: 'x', mod: true }],
    allowInTextEntry: false,
    run: (actions) => actions.cut(),
  },
  {
    id: 'paste',
    group: 'edit',
    label: 'Paste',
    chords: [{ key: 'v', mod: true }],
    allowInTextEntry: false,
    run: (actions) => actions.paste(),
  },
  {
    id: 'duplicate',
    group: 'edit',
    label: 'Duplicate',
    chords: [{ key: 'd', mod: true }],
    allowInTextEntry: false,
    run: (actions) => actions.duplicate(),
  },
  {
    id: 'nudge',
    group: 'edit',
    label: 'Nudge the selection one grid step',
    chords: arrowChords(false),
    allowInTextEntry: false,
    // Gated for the same reason `Tab` is, one step milder. A `preventDefault`
    // on the arrow keys at the window would stop the problems panel and the
    // library list from scrolling for as long as the builder is mounted, and
    // nudging is a canvas gesture on a canvas selection anyway. `BuilderCanvas`
    // takes focus after a palette drop, so the common "drop it, then move it"
    // sequence never has to be told about this.
    requiresCanvasFocus: true,
    run: (actions, event) => {
      const arrow = ARROWS[event.key]
      if (arrow) actions.nudge(arrow.dx * NUDGE_STEP, arrow.dy * NUDGE_STEP)
    },
  },
  {
    id: 'nudge-fine',
    group: 'edit',
    label: 'Nudge the selection one pixel',
    chords: arrowChords(true),
    allowInTextEntry: false,
    requiresCanvasFocus: true,
    run: (actions, event) => {
      const arrow = ARROWS[event.key]
      if (arrow) actions.nudge(arrow.dx * NUDGE_FINE, arrow.dy * NUDGE_FINE)
    },
  },
  {
    id: 'select-all',
    group: 'select',
    label: 'Select everything',
    chords: [{ key: 'a', mod: true }],
    allowInTextEntry: false,
    run: (actions) => actions.selectAll(),
  },
  {
    id: 'leave-canvas',
    group: 'navigate',
    label: 'Leave the canvas (Tab returns to the page)',
    chords: [{ key: 'Escape', shift: true }],
    allowInTextEntry: false,
    // Canvas-gated, because off the canvas there is nothing to leave. Declared
    // BEFORE `escape` so the shifted chord is matched by the binding that names
    // it; `escape` itself declares no `shift`, and `matchesChord` compares the
    // flag rather than ignoring it, so the two can never both fire.
    requiresCanvasFocus: true,
    run: (actions) => actions.leaveCanvas(),
  },
  {
    id: 'escape',
    group: 'select',
    label: 'Abort the gesture, then clear the selection, then close the sheet',
    chords: [{ key: 'Escape' }],
    allowInTextEntry: true,
    run: (actions) => actions.escape(),
  },
  {
    id: 'traverse-forward',
    group: 'navigate',
    label: 'Focus the next node downstream',
    chords: [{ key: 'Tab' }],
    allowInTextEntry: false,
    requiresCanvasFocus: true,
    run: (actions) => actions.traverse(1),
  },
  {
    id: 'traverse-back',
    group: 'navigate',
    label: 'Focus the previous node upstream',
    chords: [{ key: 'Tab', shift: true }],
    allowInTextEntry: false,
    requiresCanvasFocus: true,
    run: (actions) => actions.traverse(-1),
  },
  {
    id: 'sibling-previous',
    group: 'navigate',
    label: 'Focus the previous sibling branch',
    chords: [{ key: '[' }],
    allowInTextEntry: false,
    run: (actions) => actions.cycleSibling(-1),
  },
  {
    id: 'sibling-next',
    group: 'navigate',
    label: 'Focus the next sibling branch',
    chords: [{ key: ']' }],
    allowInTextEntry: false,
    run: (actions) => actions.cycleSibling(1),
  },
  {
    id: 'fit-view',
    group: 'navigate',
    label: 'Fit the whole graph',
    chords: [{ key: 'f' }],
    allowInTextEntry: false,
    run: (actions) => actions.fitView(),
  },
  {
    id: 'zoom-actual',
    group: 'navigate',
    label: 'Zoom to 100%',
    chords: [{ code: 'Digit1', shift: true }],
    allowInTextEntry: false,
    run: (actions) => actions.zoomToActual(),
  },
  {
    id: 'zoom-selection',
    group: 'navigate',
    label: 'Zoom to the selection',
    chords: [{ key: 'z' }],
    allowInTextEntry: false,
    run: (actions) => actions.zoomToSelection(),
  },
  {
    id: 'filter',
    group: 'navigate',
    label: 'Filter nodes by name',
    chords: [{ key: '/' }],
    allowInTextEntry: false,
    run: (actions) => actions.focusFilter(),
  },
  {
    id: 'problem-next',
    group: 'navigate',
    label: 'Go to the next problem',
    chords: [{ key: 'F8' }],
    allowInTextEntry: false,
    run: (actions) => actions.walkProblems(1),
  },
  {
    id: 'problem-previous',
    group: 'navigate',
    label: 'Go to the previous problem',
    chords: [{ key: 'F8', shift: true }],
    allowInTextEntry: false,
    run: (actions) => actions.walkProblems(-1),
  },
  {
    id: 'shortcuts',
    group: 'navigate',
    label: 'Show this sheet',
    // Two chords for one glyph: `?` is Shift+/ on a US layout and an unshifted
    // key on several others, and a sheet that cannot be opened on a German
    // keyboard is a sheet nobody there reads.
    chords: [{ key: '?', shift: true }, { key: '?' }],
    allowInTextEntry: false,
    run: (actions) => actions.toggleShortcuts(),
  },
  {
    id: 'save',
    group: 'document',
    label: 'Save',
    chords: [{ key: 's', mod: true }],
    allowInTextEntry: true,
    run: (actions) => actions.save(),
  },
  {
    id: 'validate-now',
    group: 'document',
    label: 'Validate now',
    chords: [{ key: 'Enter', mod: true }],
    allowInTextEntry: false,
    run: (actions) => actions.validateNow(),
  },
  {
    id: 'publish',
    group: 'document',
    label: 'Publish',
    chords: [{ key: 'p', mod: true, shift: true }],
    allowInTextEntry: false,
    run: (actions) => actions.publish(),
  },
]

/** The groups in the order the sheet prints them. */
export const HOTKEY_GROUPS: readonly HotkeyGroup[] = [
  'create',
  'edit',
  'select',
  'navigate',
  'document',
]

/**
 * True when the key event came from somewhere an author is typing prose.
 *
 * `isContentEditable` covers the inline label rename on the card, which is a
 * `contenteditable` span rather than an input - miss it and pressing `d` while
 * renaming a node duplicates the selection instead of typing a letter.
 */
export function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

export function matchesChord(chord: HotkeyChord, event: KeyboardEvent): boolean {
  const mod = event.metaKey || event.ctrlKey
  if (mod !== Boolean(chord.mod)) return false
  if (event.shiftKey !== Boolean(chord.shift)) return false
  // `alt` is compared only when the chord names it. Alt is the builder's free-
  // drag and subtractive-marquee modifier (R12, §4.3), and an author holding it
  // over the canvas must not silently lose every other binding.
  if (chord.alt !== undefined && event.altKey !== chord.alt) return false
  if (chord.code !== undefined) return event.code === chord.code
  if (chord.key === undefined) return false
  return event.key.toLowerCase() === chord.key.toLowerCase()
}

/** The binding an event fires, or null. Pure, and the whole of dispatch. */
export function matchBinding(event: KeyboardEvent): HotkeyBinding | null {
  for (const binding of HOTKEY_BINDINGS) {
    for (const chord of binding.chords) {
      if (matchesChord(chord, event)) return binding
    }
  }
  return null
}

/**
 * Run whatever `event` binds to, honouring the text-entry gate.
 *
 * Returns the binding it ran, so a caller - and a test - can tell "nothing is
 * bound to this" from "this was deliberately ignored because you are typing".
 */
export function dispatchHotkey(
  event: KeyboardEvent,
  actions: HotkeyActions,
  context: HotkeyContext,
): HotkeyBinding | null {
  const binding = matchBinding(event)
  if (!binding) return null
  if (!binding.allowInTextEntry && isTextEntry(event.target)) return null
  if (binding.requiresCanvasFocus && !context.canvasHasFocus()) return null
  event.preventDefault()
  binding.run(actions, event)
  return binding
}

/* --- labels --------------------------------------------------------------- */

const KEY_GLYPHS: Record<string, string> = {
  ArrowUp: '↑',
  ArrowDown: '↓',
  ArrowLeft: '←',
  ArrowRight: '→',
  Enter: '↵',
  Escape: 'Esc',
  Backspace: '⌫',
  Delete: 'Del',
  Tab: 'Tab',
}

/** True on macOS, where the modifier is Cmd and the glyphs are different. */
export function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false
  return /mac|iphone|ipad|ipod/i.test(navigator.userAgent)
}

/** The printable name of one chord. The sheet's only source of key text. */
export function chordLabel(chord: HotkeyChord, mac = isMacPlatform()): string {
  const parts: string[] = []
  if (chord.mod) parts.push(mac ? '⌘' : 'Ctrl')
  if (chord.shift) parts.push(mac ? '⇧' : 'Shift')
  if (chord.alt) parts.push(mac ? '⌥' : 'Alt')
  const bare = chord.code
    ? chord.code.replace(/^(Digit|Key)/, '')
    : (chord.key ?? '')
  parts.push(KEY_GLYPHS[bare] ?? (bare.length === 1 ? bare.toUpperCase() : bare))
  return parts.join(mac ? '' : '+')
}

/** Every chord of a binding, as the sheet prints them: `⌘Z` or `Ctrl+Z`. */
export function bindingLabels(binding: HotkeyBinding, mac = isMacPlatform()): string[] {
  return binding.chords.map((chord) => chordLabel(chord, mac))
}

/**
 * The one `window` keydown listener, installed for the life of `BuilderView`.
 *
 * One listener rather than a `@keydown` on the canvas, because half of these
 * bindings have to work while focus is on the inspector, the problems panel or
 * the document bar - and a canvas-scoped listener would make `⌘Z` depend on
 * where the author last clicked. `window` is also what makes the removal
 * unambiguous: the composable installs and removes exactly one thing.
 */
export function useBuilderHotkeys(actions: HotkeyActions, context: HotkeyContext) {
  const onKeyDown = (event: KeyboardEvent) => {
    // A key the browser or another handler has already claimed is not ours to
    // re-run. Without this, a native `⌘S` intercepted upstream would still
    // reach `save()` here and fire it twice.
    if (event.defaultPrevented) return
    dispatchHotkey(event, actions, context)
  }

  onMounted(() => window.addEventListener('keydown', onKeyDown))
  onBeforeUnmount(() => window.removeEventListener('keydown', onKeyDown))

  return { bindings: HOTKEY_BINDINGS, groups: HOTKEY_GROUPS }
}
