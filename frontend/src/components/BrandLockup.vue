<script setup lang="ts">
/**
 * THE LOCKUP: the mark, the product's name, and on a canvas the way home.
 *
 * One component for four surfaces - the run console, the builder, the sign-in
 * wall and the session splash - because those four had four copies of the same
 * markup, and three of them said `M2` beside a heading that named a different
 * product on each. `PRODUCT_NAME` is spelled in `data/brand.ts` and nowhere
 * else (DEFINITION-OF-DONE D1); this file reads it, and `tests/brand.spec.ts`
 * asserts nothing in `frontend/src` spells it a second time.
 *
 * TWO FORMS, and the difference is what the product name IS on that surface.
 *
 * - `link` (the two canvases). The lockup is the way back to the workflow list
 *   - row U2's contract, and `e2e/shell.spec.ts` looks for exactly
 *   `a.brand-lockup[href="#/"]`. Here the product name is secondary: the page
 *   is a workflow, so the name rides in the kicker slot and the `<h1>` in the
 *   default slot is the workflow's, set by the view. The anchor carries an
 *   explicit accessible name, because without one it would be read out as its
 *   own text content - which is the workflow's name, not "home".
 *
 * - `static` (the wall and the splash). There is no workflow to be inside, so
 *   the product name IS the page's heading and takes the `<h1>`. That is why
 *   the wordmark is an element rather than a prop: on one surface it is a
 *   label beside a heading and on the other it is the heading.
 *
 * WHY THE CLASS NAMES ARE THE OLD ONES. `.brand-lockup` and `.brand-mark` are
 * styled from `studio.css`, globally, and are read by
 * `frontend/scripts/contrast-audit.mjs`'s two brand rows by name. Keeping them
 * means this component is a substitution rather than a new surface, and the
 * audit goes on measuring the pairing the page actually paints.
 */
import BrandMark from './BrandMark.vue'
import { PRODUCT_NAME } from '../data/brand'

withDefaults(
  defineProps<{
    /** `link` on a canvas, `static` where there is nowhere to go back to. */
    as?: 'link' | 'static'
    /** The glyph's size inside the 32px tile. 20 is the header's. */
    markSize?: number
  }>(),
  { as: 'link', markSize: 20 },
)
</script>

<template>
  <a
    v-if="as === 'link'"
    class="brand-lockup"
    href="#/"
    :aria-label="`${PRODUCT_NAME} — home`"
  >
    <span class="brand-mark" aria-hidden="true"><BrandMark :size="markSize" /></span>
    <!-- A div, not a span: the default slot holds the view's `<h1>`, and a
         heading inside phrasing content is invalid markup that the parser
         silently reshapes. `<a>` takes flow content, so the div is legal here. -->
    <div class="brand-words">
      <span class="brand-wordmark">{{ PRODUCT_NAME }}</span>
      <slot />
    </div>
  </a>

  <div v-else class="brand-lockup">
    <span class="brand-mark" aria-hidden="true"><BrandMark :size="markSize" /></span>
    <h1>{{ PRODUCT_NAME }}</h1>
  </div>
</template>
