<script lang="ts">
/**
 * MODULE SCOPE, and this block exists for exactly that.
 *
 * `<script setup>` is a component's setup function: every statement in it runs
 * again for every instance. A cache declared there is a cache per character,
 * which is no cache at all, and the shared observer below would have been one
 * observer per character - the thing it exists to avoid. A plain `<script>`
 * beside `<script setup>` runs ONCE per module, which is what these three need.
 *
 * Found by measurement rather than by reading: the first version of this file
 * put both caches in `<script setup>`, and a spec asserting that a second
 * character joins the first one's observer saw two observers constructed.
 */
import { pipPartsLabel, pipSvg, type PipState } from '../characters/pip'

/**
 * The generated markup, cached across every instance (T2.8).
 *
 * `pipSvg` is pure and total, so two calls with the same key return the same
 * string - which makes a module-level cache exactly as correct as calling it
 * again, and a great deal cheaper. It matters because of how MANY of these
 * there are: a long run puts one character on every graph node, one on every
 * trace row and one on every spoken line, and each one assembles about thirty
 * string fragments through the geometry table. The cache is keyed on the four
 * things the output depends on and nothing else.
 *
 * BOUNDED, because a cache that is not is a leak with a nice name. The key
 * space is small by construction - the identities of one run, times six states,
 * times the two or three sizes this product uses - so the ceiling is generous
 * enough never to evict during a run and small enough to matter if something
 * unexpected starts minting keys. Eviction is oldest-first, which for an
 * insertion-ordered `Map` is `keys().next()`.
 */
const MAX_CACHED_FIGURES = 512
const figures = new Map<string, string>()

function figureFor(seed: string, state: PipState, size: number): string {
  const key = `${seed}|${state}|${size}`
  const hit = figures.get(key)
  if (hit !== undefined) return hit
  const markup = pipSvg(seed, { size, state })
  if (figures.size >= MAX_CACHED_FIGURES) {
    const oldest = figures.keys().next()
    if (!oldest.done) figures.delete(oldest.value)
  }
  figures.set(key, markup)
  return markup
}

/** `pipPartsLabel` is the same shape of pure lookup, and is cached with it. */
const partLabels = new Map<string, string>()

function partsFor(seed: string): string {
  const hit = partLabels.get(seed)
  if (hit !== undefined) return hit
  const label = pipPartsLabel(seed)
  if (partLabels.size >= MAX_CACHED_FIGURES) {
    const oldest = partLabels.keys().next()
    if (!oldest.done) partLabels.delete(oldest.value)
  }
  partLabels.set(seed, label)
  return label
}

/**
 * ONE observer for every character on the page, not one each.
 *
 * A long run mounts a character per graph node, per trace row and per spoken
 * line - hundreds of them - and each was constructing its own
 * `IntersectionObserver` over a single element. Every scroll of the trace then
 * woke hundreds of observers with one entry apiece. A shared observer wakes
 * once with the entries that actually crossed, which is what the API is for.
 *
 * The callback map is keyed by the observed ELEMENT, so an unmounted character
 * is unobserved and forgotten without the observer having to be rebuilt.
 */
const watchers = new WeakMap<Element, (visible: boolean) => void>()
let sharedObserver: IntersectionObserver | null = null
/**
 * How many characters the shared observer is watching.
 *
 * Reference-counted rather than left alive for the life of the page, and it
 * earns the counter twice over: the observer is disconnected the moment the
 * last character unmounts, so a page that navigates away from the run console
 * leaves nothing behind; and a spec that stubs `IntersectionObserver` gets a
 * fresh one built against ITS stub rather than a singleton created under the
 * previous test's, which a module-level cache would otherwise hand it.
 */
let watched = 0

function observeVisibility(element: Element, onChange: (visible: boolean) => void): void {
  if (typeof IntersectionObserver === 'undefined') return
  if (!sharedObserver) {
    sharedObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) watchers.get(entry.target)?.(entry.isIntersecting)
    })
  }
  watchers.set(element, onChange)
  sharedObserver.observe(element)
  watched += 1
}

function unobserve(element: Element): void {
  if (!watchers.has(element)) return
  watchers.delete(element)
  sharedObserver?.unobserve(element)
  watched -= 1
  if (watched > 0) return
  sharedObserver?.disconnect()
  sharedObserver = null
  watched = 0
}
</script>

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

import { characterSeed, pipStateWord } from '../characters/pip'

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
const markup = computed(() => figureFor(seed.value, props.state, props.size))
const parts = computed(() => partsFor(seed.value))
const isSmall = computed(() => props.size < 48)

/* The accessible name is words, never a code: "the agent name, working". The
   figure inside is `aria-hidden`, so this is the only name a screen reader
   reads for it. */
const ariaLabel = computed(
  () => `${props.label || props.identity || seed.value}, ${pipStateWord(props.state)}`,
)

const root = ref<HTMLElement | null>(null)
const paused = ref(false)

onMounted(() => {
  /* jsdom has no IntersectionObserver, and neither does an SSR pass. Without
     the guard every mounted spec in the suite would throw here, so the pause is
     a progressive enhancement: absent the observer the character simply
     animates, which is what it did before this existed. `observeVisibility`
     carries that guard so the branch lives in one place. */
  if (root.value === null) return
  observeVisibility(root.value, (visible) => { paused.value = !visible })
})

onBeforeUnmount(() => {
  if (root.value) unobserve(root.value)
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
