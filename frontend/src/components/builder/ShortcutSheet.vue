<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'
import {
  bindingLabels,
  HOTKEY_BINDINGS,
  HOTKEY_GROUPS,
  isMacPlatform,
} from '../../composables/useBuilderHotkeys'
import type { HotkeyBinding, HotkeyGroup } from '../../composables/useBuilderHotkeys'
import { useReturnFocus } from '../../composables/useReturnFocus'

/**
 * `?` — every keyboard shortcut, printed from the table the listener dispatches
 * from.
 *
 * THAT SHARING IS THE POINT, not a convenience. A hand-written sheet is a second
 * copy of the bindings, and the two copies fail in both directions: a shortcut
 * that is documented and unbound teaches an author a key that does nothing, and
 * one that is bound and undocumented is a feature nobody finds. Reading
 * `HOTKEY_BINDINGS` makes both states unrepresentable, and
 * `tests/builderShell.spec.ts` asserts set equality in both directions so a
 * filter added here later cannot quietly hide one.
 *
 * An overlay, not a dialog in the R15 sense - it is reference material, it
 * covers the canvas for as long as it is open and Escape closes it. The two
 * dialogs in this deliverable are `PublishDialog` and `ConflictDialog`; this is
 * the third overlay and the only one you can dismiss without deciding anything.
 */

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const sheet = ref<HTMLElement | null>(null)
const closeButton = ref<HTMLButtonElement | null>(null)

/**
 * Whether to print `⌘Z` or `Ctrl+Z`.
 *
 * Read ONCE when the sheet opens rather than per row: `isMacPlatform` reads
 * `navigator.userAgent`, and calling it for forty rows on every render is forty
 * reads of a value that cannot change while the tab is open.
 */
const mac = ref(false)

/**
 * The heading each group prints under - the only strings this file owns.
 *
 * `Record<HotkeyGroup, string>` rather than a partial map, so adding a sixth
 * group to `useBuilderHotkeys` is a compile error here instead of a section of
 * shortcuts that silently prints under `undefined`.
 */
const GROUP_TITLES: Record<HotkeyGroup, string> = {
  create: 'Creating',
  edit: 'Editing',
  select: 'Selecting',
  navigate: 'Navigating',
  document: 'The document',
}

/** The bindings grouped in the order `HOTKEY_GROUPS` declares. */
const sections = computed(() =>
  HOTKEY_GROUPS.map((group) => ({
    group,
    title: GROUP_TITLES[group],
    bindings: HOTKEY_BINDINGS.filter((binding) => binding.group === group),
  })).filter((section) => section.bindings.length > 0),
)

function keysOf(binding: HotkeyBinding): string[] {
  return bindingLabels(binding, mac.value)
}

const { capture, restore } = useReturnFocus()

watch(
  () => props.open,
  async (open) => {
    // Captured before the sheet takes focus and given back when it closes, so
    // `?` -> read -> Escape returns the keyboard to the button that opened it
    // rather than to `<body>`.
    if (!open) {
      restore()
      return
    }
    capture()
    mac.value = isMacPlatform()
    await nextTick()
    closeButton.value?.focus()
  },
)

/** Escape closes; Tab stays inside. The same nine lines as `PublishDialog`. */
function trap(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    emit('close')
    return
  }
  if (event.key !== 'Tab' || !sheet.value) return
  const focusable = sheet.value.querySelectorAll<HTMLElement>('button:not(:disabled), [href]')
  if (focusable.length === 0) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}
</script>

<template>
  <div v-if="open" class="shortcut-scrim" @keydown="trap">
    <div
      ref="sheet"
      class="shortcut-sheet"
      role="dialog"
      aria-modal="true"
      aria-labelledby="shortcut-title"
    >
      <header class="shortcut-header">
        <div>
          <span class="shortcut-kicker">KEYBOARD</span>
          <h2 id="shortcut-title">Every shortcut the builder listens for</h2>
        </div>
        <button
          ref="closeButton"
          class="icon-button"
          type="button"
          aria-label="Close the shortcut sheet"
          title="Close"
          @click="emit('close')"
        >
          <X :size="16" aria-hidden="true" />
        </button>
      </header>

      <div class="shortcut-columns">
        <!--
          The dispatched table. Every row below comes from `HOTKEY_BINDINGS`,
          which is what makes documented-and-unbound unrepresentable.
        -->
        <section v-for="section in sections" :key="section.group">
          <h3>{{ section.title }}</h3>
          <dl>
            <div v-for="binding in section.bindings" :key="binding.id" :data-testid="`shortcut-${binding.id}`">
              <dt>{{ binding.label }}</dt>
              <dd>
                <kbd v-for="keys in keysOf(binding)" :key="keys">{{ keys }}</kbd>
              </dd>
            </div>
          </dl>
        </section>
      </div>

      <!--
        POINTER modifiers, and deliberately NOT `HOTKEY_BINDINGS` rows.
        `useBuilderHotkeys` dispatches keystrokes; these three are held while the
        mouse does the work, and Vue Flow reads them directly off the pointer
        event (R2 - the library owns the pointer layer). Giving them binding ids
        would put four rows in the table the listener dispatches from that the
        listener cannot dispatch, which is the documented-and-unbound state this
        sheet exists to make impossible. So they are printed here, in their own
        section, with no `shortcut-<id>` testid - and `builderShell.spec.ts`'s
        set equality over the table still means what it says.

        They needed printing because §4.3's modifiers were reachable and
        completely unadvertised: nothing on screen said that a multi-selection
        was possible at all.
      -->
      <section class="shortcut-pointer">
        <h3>With the mouse</h3>
        <dl>
          <div>
            <dt>Marquee a group</dt>
            <dd><kbd>Drag</kbd> on empty canvas</dd>
          </div>
          <div>
            <dt>Add to the selection</dt>
            <dd><kbd>Shift</kbd> + click</dd>
          </div>
          <div>
            <dt>Toggle one node</dt>
            <dd><kbd>{{ mac ? '⌘' : 'Ctrl' }}</kbd> + click</dd>
          </div>
          <div>
            <dt>Pan</dt>
            <dd><kbd>Space</kbd> + drag, or middle-drag</dd>
          </div>
          <div>
            <dt>Drag off the grid</dt>
            <dd><kbd>Alt</kbd> + drag</dd>
          </div>
          <div>
            <dt>Duplicate as you drag</dt>
            <dd><kbd>Alt</kbd> + drag a node</dd>
          </div>
        </dl>
      </section>
    </div>
  </div>
</template>

<style scoped>
/* Shares every rule the dispatched columns use, so the two sections read as one
   sheet; only the separating rule above it says "these are held, not pressed". */
.shortcut-pointer {
  padding-top: 14px;
  margin-top: 4px;
  border-top: 1px solid var(--border-default);
}
.shortcut-pointer h3 { margin: 0 0 8px; color: var(--text-40); font: 700 var(--fs-11)/1 var(--font-mono); text-transform: uppercase; letter-spacing: 0.04em; }
.shortcut-pointer dl { display: grid; gap: 2px 18px; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); margin: 0; }
.shortcut-pointer dl > div { display: flex; gap: 12px; align-items: baseline; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid var(--border-default); }
.shortcut-pointer dt { min-width: 0; color: var(--text-body); font-size: var(--fs-12); }
.shortcut-pointer dd { display: flex; flex-shrink: 0; gap: 4px; margin: 0; color: var(--text-muted); font-size: var(--fs-11); }

.shortcut-scrim {
  position: fixed;
  z-index: var(--z-toast);
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(10, 10, 10, 0.62);
  -webkit-backdrop-filter: var(--blur-panel);
  backdrop-filter: var(--blur-panel);
}

.shortcut-sheet {
  display: grid;
  gap: 16px;
  align-content: start;
  width: min(760px, 100%);
  max-height: min(720px, calc(100dvh - 48px));
  overflow: auto;
  padding: 20px;
  background: var(--surface-overlay);
  border: 1px solid var(--border-default);
  border-radius: var(--r-2xl);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
}

.shortcut-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.shortcut-kicker { color: var(--accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); letter-spacing: 0.04em; }
.shortcut-header h2 { margin: 5px 0 0; font-size: var(--fs-18); }

.shortcut-columns { display: grid; gap: 18px; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
.shortcut-columns h3 { margin: 0 0 8px; color: var(--text-40); font: 700 var(--fs-11)/1 var(--font-mono); text-transform: uppercase; letter-spacing: 0.04em; }
.shortcut-columns dl { display: grid; gap: 2px; margin: 0; }
.shortcut-columns dl > div { display: flex; gap: 12px; align-items: baseline; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid var(--border-default); }
.shortcut-columns dt { min-width: 0; color: var(--text-body); font-size: var(--fs-12); }
.shortcut-columns dd { display: flex; flex-shrink: 0; gap: 4px; margin: 0; }

kbd {
  padding: 2px 6px;
  color: var(--text-title);
  font: 600 10px/1.5 var(--font-mono);
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-bottom-width: 2px;
  border-radius: var(--r-sm);
  white-space: nowrap;
}
</style>
