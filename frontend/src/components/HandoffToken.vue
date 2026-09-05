<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { characterSeed, pipSvg } from '../characters/pip'
import { characterIndex, handoffDurationMs, type Handoff } from '../composables/useRunChoreography'

/**
 * A message, walking the edge it was sent along.
 *
 * This is the reference's own mechanism verbatim (`LaunchView.vue:2044-2075`):
 * `path.getPointAtLength(t x length)` over `clamp(pathLength x 0.02, 2000,
 * 4000)` ms, linear, driven by `requestAnimationFrame`. What it is NOT is the
 * reference's trigger. ChatDev starts this walk by regex-matching one of its
 * own human-readable log lines - the one announcing that an edge's condition
 * was satisfied - which PRD §8.5 already named the most fragile thing in that
 * product; ours starts on a structured `edge_traversal` frame, and if none
 * arrives the edge simply falls back to today's dashed march and nothing
 * regresses. Criterion 5 is a grep for that log line's wording over
 * `frontend/src`, so it is deliberately not written out anywhere here.
 *
 * The token is the SOURCE agent's own character at 24px, with a short trailing
 * dash in its colour. Facing is dropped: "which way is it walking" is answered
 * by the trail rather than by a mirrored image, and the trail keeps working at
 * 50% zoom where a turned figure would not.
 *
 * The figure is drawn IDLE and not in the sender's live state, deliberately.
 * What is walking the edge is a message, not the agent - the agent is still
 * standing on the card it left - and a token whose pose changed halfway across
 * would be a second animated cast member on a canvas that already counts this
 * walk as one of its twelve. `pipSvg` is called directly rather than mounting
 * `AgentCharacter`, because that component's root is a `<span>` and this is
 * inside an `<svg>`; the markup it returns is a nested `<svg>`, which is not.
 *
 * MEASURING THE PATH is why this component exists at all rather than a CSS
 * `offset-path`. Only the DOM knows how long a bezier turned out to be after
 * layout, and the duration is a function of that length. The measurement is
 * guarded end to end: `getTotalLength` and `getPointAtLength` are unimplemented
 * in jsdom, so a mount in the unit suite must render the token at its
 * destination and finish rather than throw.
 */

const props = defineProps<{
  /** The edge's own path data, so this measures the line it is walking. */
  path: string
  handoff: Handoff
  /**
   * The SOURCE node's character index, as the edge knew it.
   *
   * Kept as the fallback for a handoff carrying no identity - a frame log
   * written before `fromIdentity` existed, or a replay of one. When an
   * identity IS present its own hash decides the colour, because that is the
   * hash the figure is drawn from and two colours on one token would be worse
   * than either.
   */
  character: number
}>()

const emit = defineEmits<{
  /** The walk finished. The parent drops the token from the DOM. */
  done: [string]
}>()

const measurer = ref<SVGPathElement | null>(null)
const at = ref<{ x: number; y: number } | null>(null)
const trail = ref<{ x: number; y: number } | null>(null)
let frame = 0

/** The sender's identity, normalised - the same seed its card is drawn from. */
const seed = computed(() => characterSeed(props.handoff.fromIdentity || props.handoff.from))

/* The colour is `characterIndex` of the SEED and not of the node id, because
   `pipSvg` colours the figure from the raw FNV of that same seed and the two
   must be one colour. `characterIndex` is byte-for-byte that hash - its own
   docstring says so and `pip.ts` says so from the other side. */
const colour = computed(() =>
  props.handoff.fromIdentity
    ? `var(--character-${characterIndex(seed.value)})`
    : `var(--character-${props.character})`,
)

/** 24px, detail off: cheeks and sparkles are mud at this size (`pip.ts`). */
const FIGURE_SIZE = 24
const figure = computed(() => pipSvg(seed.value, { size: FIGURE_SIZE, state: 'idle', detail: false }))

/** How far behind the token the trailing dash sits, in path units. */
const TRAIL_LENGTH = 26

function reduceMotion(): boolean {
  return globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true
}

function pointAt(element: SVGPathElement, length: number): { x: number; y: number } | null {
  try {
    const point = element.getPointAtLength(Math.max(0, length))
    return { x: point.x, y: point.y }
  } catch {
    // jsdom, and any browser that failed to lay the path out. The caller
    // finishes the walk rather than looping on a measurement that will not come.
    return null
  }
}

function finish(): void {
  if (frame) cancelAnimationFrame(frame)
  frame = 0
  emit('done', props.handoff.edgeId)
}

onMounted(() => {
  const element = measurer.value
  let total = 0
  try {
    total = element?.getTotalLength?.() ?? 0
  } catch {
    total = 0
  }
  // Reduced motion places the token at its destination within one frame and
  // finishes (D8). The arrival still happens and the receipt pulse still fires;
  // what is dropped is the two to four seconds of travel.
  if (!element || !total || reduceMotion()) {
    at.value = total ? pointAt(element!, total) : null
    finish()
    return
  }

  const duration = handoffDurationMs(total)
  const startedAt = performance.now()
  const step = (now: number) => {
    // LINEAR, and that is the reference's choice rather than an omission: an
    // eased token reads as accelerating and decelerating for reasons the run
    // does not have. A message in flight has no opinion about its own middle.
    const t = Math.min(1, (now - startedAt) / duration)
    at.value = pointAt(element, total * t)
    trail.value = pointAt(element, total * t - TRAIL_LENGTH)
    if (t >= 1 || at.value === null) {
      finish()
      return
    }
    frame = requestAnimationFrame(step)
  }
  frame = requestAnimationFrame(step)
})

onBeforeUnmount(() => {
  if (frame) cancelAnimationFrame(frame)
})
</script>

<template>
  <g class="handoff-token" data-testid="handoff-token" :data-edge="handoff.edgeId" aria-hidden="true">
    <!--
      The ruler. Never painted - it exists so `getTotalLength` and
      `getPointAtLength` have something to answer about - and it carries the
      SAME `d` the visible edge does, so the token walks the line an operator
      can see rather than a straight approximation of it.
    -->
    <path ref="measurer" :d="path" fill="none" stroke="none" />
    <line
      v-if="at && trail"
      class="handoff-token-trail"
      :x1="trail.x"
      :y1="trail.y"
      :x2="at.x"
      :y2="at.y"
      :stroke="colour"
    />
    <!--
      The disc stays UNDER the figure rather than being replaced by it: an
      edge is a thin line on a dark canvas and a Pip alone at 24px loses its
      silhouette against it. The disc is the ground the character stands on,
      which is what the node card's medallion already is.
    -->
    <circle
      v-if="at"
      class="handoff-token-disc"
      :cx="at.x"
      :cy="at.y"
      r="14"
      :fill="colour"
    />
    <g
      v-if="at"
      class="handoff-token-figure"
      data-testid="handoff-token-figure"
      :data-character="seed"
      :transform="`translate(${at.x - FIGURE_SIZE / 2} ${at.y - FIGURE_SIZE / 2})`"
      v-html="figure"
    />
  </g>
</template>
