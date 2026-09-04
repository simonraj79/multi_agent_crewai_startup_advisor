<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ChevronDown, ChevronUp, FlaskConical } from 'lucide-vue-next'
import CodePreview from './CodePreview.vue'
import DryRunTab from './test/DryRunTab.vue'
import NodeTab from './test/NodeTab.vue'
import RunTab from './test/RunTab.vue'
import StateTab from './test/StateTab.vue'
import { PANEL_MIN_PX, TEST_TABS, type FlowTest, type TestTab } from '../../composables/useFlowTest'

/**
 * The docked test panel - .agent/plans/13-flow-testing.md D1.
 *
 * A GRID ROW, NOT AN OVERLAY, and that is R15 rather than a preference: a stack
 * of panes hiding the graph you are editing is the competitor's defining
 * failure, and this repository has already measured what a pane that steals
 * height without re-fitting does (section 14 defects 3 and 4, and the crew strip
 * that used to sit on top of the two nodes it narrated). The shell gives this a
 * real track; `BuilderCanvas`'s settling observer re-fits the graph when the
 * dock GROWS, which is exactly what opening this does.
 *
 * COLLAPSED BY DEFAULT to a 36px tab strip. An author lands on a canvas to
 * draw, not to test, and a panel that opens itself takes 260px from the first
 * thing they came to do. Pressing a tab opens it - one gesture, and the gesture
 * says which tab.
 *
 * THE DRAG HANDLE IS A `separator`, with arrow keys. A pointer-only resize is
 * unreachable from a keyboard, and this panel's whole job is to be reachable
 * while the graph stays visible; `aria-valuenow` carries the height so a screen
 * reader hears the same number the pointer moves.
 */

const props = defineProps<{
  test: FlowTest
  /** Node labels by id, so the log reads as the cards the author drew. */
  labels: Record<string, string>
}>()

const TAB_LABELS: Record<TestTab, string> = {
  run: 'Run',
  node: 'Node',
  dry: 'Dry run',
  code: 'Code',
  state: 'State',
}

const dragging = ref(false)
let startY = 0
let startHeight = 0

const style = computed(() => ({ height: `${props.test.panelHeight.value}px` }))

/**
 * Resize by pointer.
 *
 * Listeners on `window` rather than on the handle, and released on `pointerup`
 * anywhere: a drag that leaves the handle - which every drag does, because the
 * handle is 6px tall and the pointer is moving vertically through it - would
 * otherwise stop tracking the moment it left, and the panel would stick.
 * `setPointerCapture` is the other answer and needs the element; this one needs
 * nothing and works when the pointer ends over an iframe or outside the window.
 */
function beginDrag(event: PointerEvent): void {
  dragging.value = true
  startY = event.clientY
  startHeight = props.test.panelHeight.value
  window.addEventListener('pointermove', onDrag)
  window.addEventListener('pointerup', endDrag, { once: true })
}

function onDrag(event: PointerEvent): void {
  // Upward is TALLER: the panel is docked at the bottom, so the handle moving
  // toward the top of the screen adds height. Getting this backwards is the
  // classic bottom-dock bug and it reads as the panel fighting the pointer.
  props.test.setHeight(startHeight + (startY - event.clientY))
}

function endDrag(): void {
  dragging.value = false
  window.removeEventListener('pointermove', onDrag)
}

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onDrag)
  window.removeEventListener('pointerup', endDrag)
})

/** Keyboard resize, in the same steps a pointer would reach by accident. */
function onHandleKey(event: KeyboardEvent): void {
  const step = event.shiftKey ? 48 : 16
  if (event.key === 'ArrowUp') props.test.setHeight(props.test.panelHeight.value + step)
  else if (event.key === 'ArrowDown') props.test.setHeight(props.test.panelHeight.value - step)
  else return
  event.preventDefault()
}
</script>

<template>
  <section
    class="test-panel"
    :class="{ 'is-open': test.open.value, 'is-dragging': dragging }"
    :style="style"
    aria-label="Test this flow"
    data-testid="test-panel"
    :data-open="test.open.value ? 'true' : 'false'"
  >
    <div
      v-if="test.open.value"
      class="test-handle"
      role="separator"
      tabindex="0"
      aria-orientation="horizontal"
      aria-label="Resize the test panel"
      :aria-valuenow="test.panelHeight.value"
      :aria-valuemin="PANEL_MIN_PX"
      :aria-valuemax="test.maxHeight.value"
      data-testid="test-panel-handle"
      @pointerdown.prevent="beginDrag"
      @keydown="onHandleKey"
    />

    <div class="test-tabs" role="tablist" aria-label="Test this flow">
      <FlaskConical class="test-tabs-icon" :size="13" aria-hidden="true" />
      <button
        v-for="name in TEST_TABS"
        :key="name"
        type="button"
        class="test-tab-button"
        role="tab"
        :class="{ 'is-current': test.open.value && test.tab.value === name }"
        :aria-selected="test.open.value && test.tab.value === name"
        :data-testid="`test-tab-${name}`"
        @click="test.selectTab(name)"
      >
        {{ TAB_LABELS[name] }}
      </button>

      <span class="test-tabs-spacer" />

      <button
        type="button"
        class="test-toggle"
        data-testid="test-panel-toggle"
        :aria-expanded="test.open.value"
        aria-controls="test-panel-body"
        @click="test.toggle()"
      >
        <component :is="test.open.value ? ChevronDown : ChevronUp" :size="14" aria-hidden="true" />
        <span class="test-toggle-label">{{ test.open.value ? 'Hide' : 'Test' }}</span>
      </button>
    </div>

    <div v-show="test.open.value" id="test-panel-body" class="test-body" data-testid="test-panel-body">
      <p v-if="test.problem.value" class="test-problem" role="alert" data-testid="test-panel-problem">
        {{ test.problem.value }}
      </p>

      <RunTab v-if="test.tab.value === 'run'" :test="test" :labels="labels" />
      <NodeTab v-else-if="test.tab.value === 'node'" :test="test" :labels="labels" />
      <DryRunTab v-else-if="test.tab.value === 'dry'" :test="test" />
      <CodePreview v-else-if="test.tab.value === 'code'" :test="test" />
      <StateTab v-else :test="test" />
    </div>
  </section>
</template>

<style scoped>
/* `min-height: 0` on the body and `overflow: auto` there rather than here: an
   auto grid row grows to its tallest child, which is the defect §12 records
   about `.studio-main` - three panes overflowing an 848px container to 1894px
   because the inner `flex: 1; overflow: auto` resolved against an over-tall
   parent and never had anything to clip. */
.test-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  border-top: 1px solid var(--border-default);
  background: var(--surface-panel);
}
.test-panel.is-dragging { user-select: none; }

.test-handle {
  position: absolute;
  top: -3px;
  left: 0;
  right: 0;
  height: 6px;
  cursor: ns-resize;
  background: transparent;
}
.test-handle:hover,
.test-handle:focus-visible { background: var(--accent-cyan); outline: none; }

.test-tabs {
  display: flex;
  flex: none;
  gap: 2px;
  align-items: center;
  height: 36px;
  padding: 0 10px;
  min-width: 0;
  overflow-x: auto;
}
.test-tabs-icon { flex: none; color: var(--text-40); margin-right: 4px; }
.test-tabs-spacer { flex: 1 1 auto; }

.test-tab-button {
  flex: none;
  padding: 4px 9px;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--text-muted);
  font: 500 var(--fs-12)/1.4 var(--font-body);
  cursor: pointer;
}
.test-tab-button:hover { color: var(--text-body); }
.test-tab-button.is-current {
  border-color: var(--border-default);
  background: var(--surface-raised);
  color: var(--text-title);
}
.test-tab-button:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

.test-toggle {
  display: inline-flex;
  flex: none;
  gap: 4px;
  align-items: center;
  padding: 4px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--text-muted);
  font: 500 var(--fs-11)/1.4 var(--font-body);
  cursor: pointer;
}
.test-toggle:hover { border-color: var(--border-hover); color: var(--text-body); }

.test-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 8px 12px 12px;
}
.test-problem {
  margin: 0 0 8px;
  padding: 6px 9px;
  border: 1px solid var(--err-border);
  border-radius: var(--r-sm);
  background: var(--err-bg);
  color: var(--text-title);
  font: 400 var(--fs-12)/1.5 var(--font-body);
}
</style>
