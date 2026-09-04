<script setup lang="ts">
import { computed } from 'vue'
import { ChevronRight, Sparkles } from 'lucide-vue-next'
import {
  expertMode,
  isAdvancedOpen,
  setAdvancedOpen,
  setExpertMode,
} from '../inspectors/expertMode'

/**
 * One disclosure region of the three-tier inspector - 04 D1.
 *
 * THREE TIERS, NOTHING HIDDEN. *Essentials* is not a region at all: it is the
 * top of the form, always rendered, and giving it a container would be giving
 * an author something to collapse that they should never want to. This
 * component is the other two.
 *
 * *Advanced* is a native `<details>`. Native because the keyboard behaviour -
 * Enter and Space on the summary, the disclosure triangle's focus ring, the
 * fact that browser find-in-page opens it - is a pile of work to reimplement
 * and a pile of ways to get wrong, and D9 asks for every widget to be a native
 * control or to carry role, tabindex and arrow handling. `aria-expanded` is set
 * explicitly on the summary rather than left to the implicit mapping, because
 * that mapping is still uneven across screen readers and the attribute costs
 * one line.
 *
 * *Expert* has no disclosure of its own. Its switch is the rail's, it is
 * global (decision 19), and when it is off the region is ABSENT FROM THE DOM
 * rather than hidden with CSS - which is the honest reading of "rendered only
 * while the switch is on", and the one a keyboard walk can tell apart from a
 * region it merely cannot see. In its place goes a single line saying how many
 * settings are behind the switch and offering to turn it on. **Nothing is ever
 * simply absent**: an author who cannot find a control has to be able to find
 * out that it exists, or they conclude the product cannot do it.
 *
 * `forceOpen` OUTRANKS BOTH. A field carrying a server problem opens its region
 * and, for Expert, turns the switch on. An error behind a closed disclosure is
 * the modal-stack failure R15 exists to prevent in miniature: the author is
 * told the document is invalid, is shown a form that looks clean, and has
 * nowhere to go. The switch is turned on rather than the region being smuggled
 * open past it, so the state on screen and the state in storage agree.
 */
const props = withDefaults(
  defineProps<{
    tier: 'advanced' | 'expert'
    /**
     * What the Advanced disclosure remembers its open state AGAINST. The node
     * kind, per D1 - `agent`, `crew`, `tool` - so an author tuning six agents
     * opens it once. Ignored for `expert`, whose switch is global.
     */
    kind: string
    /** How many controls are in here. The Expert placeholder states it. */
    count: number
    /**
     * A problem lands on a control inside this region. Opens it, and for Expert
     * turns the global switch on, so the anchor `focusField` is about to look
     * for is in the DOM by the time it looks.
     */
    forceOpen?: boolean
  }>(),
  { forceOpen: false },
)

const open = computed(() => props.forceOpen || isAdvancedOpen(props.kind))

/**
 * Expert is rendered when the switch is on, or when a problem forces it.
 *
 * The force case also FLIPS the switch (below) rather than rendering past it,
 * so the rail header and the region cannot disagree about whether Expert is on.
 */
const expertShown = computed(() => expertMode.value || props.forceOpen)

function toggleAdvanced(event: Event): void {
  // `toggle` fires after the browser has already changed `details.open`, so
  // this records what happened rather than deciding it - which is what keeps
  // the native control native.
  setAdvancedOpen(props.kind, (event.target as HTMLDetailsElement).open)
}
</script>

<template>
  <details
    v-if="tier === 'advanced'"
    class="tier-region is-advanced"
    data-tier="advanced"
    :open="open"
    @toggle="toggleAdvanced"
  >
    <summary class="tier-summary" :aria-expanded="open">
      <ChevronRight class="tier-chevron" :size="13" aria-hidden="true" />
      <span>Advanced</span>
      <span class="tier-count">{{ count }}</span>
    </summary>
    <div class="tier-body">
      <slot />
    </div>
  </details>

  <section v-else-if="expertShown" class="tier-region is-expert" data-tier="expert" aria-label="Expert settings">
    <p class="tier-summary is-static">
      <Sparkles :size="12" aria-hidden="true" />
      <span>Expert</span>
      <span class="tier-count">{{ count }}</span>
    </p>
    <div class="tier-body">
      <slot />
    </div>
  </section>

  <!--
    The off state. A LINK rather than nothing, because "this product cannot do
    that" and "you have that switched off" look identical when the answer is an
    empty space, and only one of them is true.
  -->
  <p v-else class="tier-hidden" data-tier="expert-hidden">
    <span>{{ count }} expert {{ count === 1 ? 'setting' : 'settings' }} hidden</span>
    <button type="button" class="tier-show" @click="setExpertMode(true)">show</button>
  </p>
</template>

<style scoped>
/* No colour, spacing or type scale that is not already a token: every value
   below is one of `tokens.css`'s, or a geometry the rail already uses. */
.tier-region { display: block; margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border-default); }

.tier-summary { display: flex; align-items: center; gap: 6px; margin: 0; padding: 4px 2px; color: var(--text-40); font: 700 var(--fs-11)/1 var(--font-mono); letter-spacing: 0.04em; text-transform: uppercase; cursor: pointer; list-style: none; }
.tier-summary.is-static { cursor: default; }
/* WebKit still paints its own marker through `list-style: none`. */
.tier-summary::-webkit-details-marker { display: none; }
.tier-summary:hover { color: var(--text-muted); }
.tier-summary:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 2px; border-radius: var(--r-sm); }
.tier-chevron { flex: 0 0 auto; transition: transform var(--motion-fast) ease; }
details[open] > .tier-summary .tier-chevron { transform: rotate(90deg); }
.tier-count { margin-left: auto; padding: 1px 5px; color: var(--text-40); font: 500 10px/1.5 var(--font-mono); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-full); }

.tier-body { padding-top: 13px; }

.tier-hidden { display: flex; align-items: baseline; gap: 6px; margin: 16px 0 0; padding-top: 14px; color: var(--text-40); font-size: var(--fs-11); line-height: 1.5; border-top: 1px solid var(--border-default); }
.tier-show { padding: 0; color: var(--accent-cyan); font: 600 var(--fs-11)/1.5 var(--font-body); background: transparent; border: 0; cursor: pointer; text-decoration: underline; }
.tier-show:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 2px; border-radius: var(--r-xs); }
</style>
