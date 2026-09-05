<script setup lang="ts">
/**
 * One agent, drawn.
 *
 * This component renders a state; it does not derive one. `state` is a prop
 * and nothing in this file reads a clock, a run, a frame or a store - which is
 * the whole reason the cast can be screenshotted, snapshot-tested and replayed
 * deterministically. What decides that an agent is `working` rather than
 * `speaking` is the run choreography, one layer up.
 *
 * The SVG goes in with `v-html`, and that is safe by construction rather than
 * by sanitising: `pipSvg` consumes the identity string in a hash and returns
 * markup assembled entirely from literals in `characters/pip.ts` plus numbers
 * from its geometry table, so the identity never appears in the output at all.
 * `characterSystem.spec.ts` pins that with a `<script>` tag for an identity.
 *
 * The only thing this file adds beyond markup is the offscreen pause: an
 * `IntersectionObserver` sets `pip--paused`, so a character scrolled out of a
 * rail or panned off the canvas stops costing compositor work. Paused, not
 * removed - `animation: none` would snap the pose back to t = 0 and a Pip
 * halfway off screen would visibly jump.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  characterSeed,
  pipPartsLabel,
  pipStateWord,
  pipSvg,
  type PipState,
} from '../characters/pip'

const props = withDefaults(
  defineProps<{
    /** A role, or whatever `identityFor` resolved. Normalised here; never rendered. */
    identity: string
    state?: PipState
    /** Rendered edge in CSS px. Below 48 the detail tier is off. */
    size?: number
    /** What to call this agent out loud. Defaults to the identity as given. */
    label?: string
  }>(),
  { state: 'idle', size: 32, label: '' },
)

const seed = computed(() => characterSeed(props.identity))
const markup = computed(() => pipSvg(seed.value, { size: props.size, state: props.state }))
const parts = computed(() => pipPartsLabel(seed.value))
const isSmall = computed(() => props.size < 48)

/* The accessible name is words, never a code: "the agent name, working". The
   figure inside is `aria-hidden`, so this is the only name a screen reader
   reads for it. */
const ariaLabel = computed(
  () => `${props.label || props.identity || seed.value}, ${pipStateWord(props.state)}`,
)

const root = ref<HTMLElement | null>(null)
const paused = ref(false)
let observer: IntersectionObserver | null = null

onMounted(() => {
  /* jsdom has no IntersectionObserver, and neither does an SSR pass. Without
     the guard every mounted spec in the suite would throw here, so the pause is
     a progressive enhancement: absent the observer the character simply
     animates, which is what it did before this existed. */
  if (typeof IntersectionObserver === 'undefined' || root.value === null) return
  observer = new IntersectionObserver((entries) => {
    for (const entry of entries) paused.value = !entry.isIntersecting
  })
  observer.observe(root.value)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
})
</script>

<template>
  <span
    ref="root"
    class="pip"
    :class="[`pip--${state}`, { 'pip--sm': isSmall, 'pip--paused': paused }]"
    :data-character="seed"
    :data-state="state"
    :data-parts="parts"
    role="img"
    :aria-label="ariaLabel"
    v-html="markup"
  />
</template>
