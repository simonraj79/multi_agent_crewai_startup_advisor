<script setup lang="ts">
import { ControlButton, Controls } from '@vue-flow/controls'
import { useVueFlow } from '@vue-flow/core'
import { Hand, Maximize, Minus, MousePointer2, Plus } from 'lucide-vue-next'
import type { CanvasTool } from '../composables/useCanvasTool'

/**
 * The one control cluster, bottom-left, on BOTH canvases.
 *
 * `DEFINITION-OF-DONE.md` U3. Before this existed there were two clusters that
 * happened to look alike: `BuilderCanvas.vue` filled the `control-*` slots with
 * named `ControlButton`s and Lucide icons, and `StudioView.vue` rendered the
 * stock `<Controls>` and then reached into the DOM `onMounted` to write three
 * `aria-label`s onto buttons the library had already rendered. That hack is
 * deleted with this component; its own comment said the declarative fix was the
 * right one and named the reason it was not taken - the console is under a
 * committed screenshot baseline and swapping Vue Flow's icons for Lucide ones
 * moves pixels. **D4 lifts that reason for this build**: the baselines are
 * regenerated once, on the integrated branch, by RV1, because the header, the
 * brand and this cluster all move inside the same frames.
 *
 * IT IS A LABEL, NOT A REIMPLEMENTATION. `<Controls>` still positions the
 * panel, `ControlButton` still renders the `<button>`, and every one of the
 * library's own class names survives - `.vue-flow__controls`,
 * `.vue-flow__controls-button`, `.vue-flow__controls-zoomin` and its two
 * siblings, which `e2e/builder-layout.spec.ts` already clicks by class. The
 * `control-*` slots replace the whole button because that is the only place a
 * name can be attached at all.
 *
 * THE SEAM IS THREE PROPS, and it is three rather than one because the two
 * canvases genuinely differ in exactly one place: the fit. The builder's runs
 * through `useBuilderCanvas.fitView`, which carries the `MIN_LEGIBLE_ZOOM`
 * floor from plan 15 D-15-2; the console's is Vue Flow's own with the console's
 * padding. Everything else - zoom in, zoom out, the tool pair, the names, the
 * icons, the pressed state - is identical, which is the point of the row.
 */
const props = defineProps<{
  /**
   * The `useVueFlow` instance id of the canvas this cluster drives:
   * `studio-flow` or `builder-flow`. Zoom is the library's, keyed by id, so
   * this component never has to be handed a viewport.
   */
  flowId: string
  /** The mode the toggle shows. Owned by the view's `useCanvasTool`. */
  tool: CanvasTool
  /**
   * Fit view. A callback rather than options, because the builder's fit is a
   * function with a legibility floor in it and the console's is not.
   */
  fit: () => void
}>()

const emit = defineEmits<{ 'update:tool': [CanvasTool] }>()

const flow = useVueFlow(props.flowId)
</script>

<template>
  <Controls position="bottom-left" :show-interactive="false">
    <template #control-zoom-in>
      <ControlButton class="vue-flow__controls-zoomin" aria-label="Zoom in" @click="flow.zoomIn()">
        <Plus :size="12" :stroke-width="2.5" aria-hidden="true" />
      </ControlButton>
    </template>
    <template #control-zoom-out>
      <ControlButton class="vue-flow__controls-zoomout" aria-label="Zoom out" @click="flow.zoomOut()">
        <Minus :size="12" :stroke-width="2.5" aria-hidden="true" />
      </ControlButton>
    </template>
    <template #control-fit-view>
      <ControlButton
        class="vue-flow__controls-fitview"
        aria-label="Fit the graph to the view"
        @click="props.fit()"
      >
        <Maximize :size="12" :stroke-width="2.5" aria-hidden="true" />
      </ControlButton>
    </template>

    <!--
      The tool pair, in the default slot so it lands under Fit rather than over
      Zoom in - the three view controls are what a reader reaches for first and
      moving them would be a change nobody asked for.

      TWO BUTTONS WITH `aria-pressed`, not one button that toggles. A single
      button has to say what it will DO ("switch to hand") while showing what is
      true now, and screen-reader users get one of those two sentences depending
      on which the author chose. Two buttons say what each IS and which one is
      current, which is what a radio-shaped choice actually is; it is also the
      shape `StatusPanel`'s Review / Unattended pair and the header's Build /
      Run pair already use here.

      `aria-pressed` follows the MODE, deliberately - not `panning`. Holding
      space is a temporary hand and it moves the cursor and the pan, but it does
      not move the toggle, because a control that flickered while somebody held
      a key would be announcing a mode change that never happened.
    -->
    <ControlButton
      class="canvas-tool-button"
      aria-label="Select tool"
      title="Select (V)"
      :aria-pressed="props.tool === 'select'"
      @click="emit('update:tool', 'select')"
    >
      <MousePointer2 :size="12" :stroke-width="2.5" aria-hidden="true" />
    </ControlButton>
    <ControlButton
      class="canvas-tool-button"
      aria-label="Hand tool"
      title="Hand (H)"
      :aria-pressed="props.tool === 'hand'"
      @click="emit('update:tool', 'hand')"
    >
      <Hand :size="12" :stroke-width="2.5" aria-hidden="true" />
    </ControlButton>
  </Controls>
</template>
