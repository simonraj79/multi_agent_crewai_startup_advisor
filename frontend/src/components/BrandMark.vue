<script setup lang="ts">
/**
 * THE MARK. A fan-out: one agent, two wires, a crew.
 *
 * WHAT IT DEPICTS, and it is the product rather than a decoration. Everything
 * this repository builds is a graph of agents on a canvas: the Idea validator
 * fans one Scoper out to three research branches and joins them again, and a
 * document somebody draws in the builder does the same thing with their own
 * nodes. The mark is that move at its smallest honest size - a root node in
 * `--accent-cyan`, which is this design system's AGENT and RUNNING colour, two
 * edges leaving it, and two leaf nodes in `--accent-mint`, which is its INPUT
 * and SUCCESS colour (`docs/design.md` §1). Read left to right it is a crew;
 * read top to bottom it is a run. It is drawn in the same rounded-rectangle
 * grammar as a node card, at the card's own proportions.
 *
 * WHY IT SURVIVES 16 px, which is the size the favicon is actually seen at.
 * Three rules, each of which killed an earlier candidate when it was rendered
 * at 16 and LOOKED at (`frontend/test-results/w3/candidates*.png`):
 *
 * 1. **Nothing thinner than 3.4 units in a 24 unit box.** That is 2.3 px at
 *    16, which survives one round of rasterisation. A first attempt drew the
 *    wires as an org-chart bus at 1.9 units; at 16 px it was a grey smudge.
 * 2. **Three masses, not three outlines.** Every element is a filled shape or
 *    a round-capped stroke of the same weight, so the silhouette is what
 *    reads. An outlined version of the same graph disappeared entirely.
 * 3. **The two leaves are as large as the root.** Shrinking them to signal
 *    hierarchy (candidate `I_TALL`) cost them their colour at 16 px, and the
 *    mark stopped being three things and became a wire with a blob on it.
 *
 * WHY IT USES THE `--on-accent-*` PAIR RATHER THAN THE ACCENTS THEMSELVES.
 * `--on-accent-cyan` and `--on-accent-mint` ARE `--accent-cyan` and
 * `--accent-mint` in the dark theme - the declarations are literally
 * `var(--accent-cyan)` - so no dark pixel differs. In the light theme they are
 * the same hue with enough ink to be read on paper, and the light theme is
 * where the pale pastels measure 1.02:1 against the header. `studio.css`
 * already made exactly this swap for the old lucide placeholder, and
 * `frontend/scripts/contrast-audit.mjs`'s "brand mark on the header" row
 * measures `on-accent-cyan`, so painting the accent here would have left the
 * gate measuring a pairing the page no longer paints.
 *
 * THE GEOMETRY IS DUPLICATED IN `public/favicon.svg`, which cannot read a
 * custom property and so carries the token VALUES as literals. The four
 * geometry strings below are byte-identical there and
 * `frontend/tests/brand.spec.ts` asserts both halves - the shapes and the
 * colours - so a change here that is not made there fails a test rather than
 * drifting into two marks that only used to be one.
 */
withDefaults(defineProps<{ size?: number }>(), { size: 20 })
</script>

<template>
  <svg
    class="brand-glyph"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
    focusable="false"
  >
    <path
      class="brand-glyph-wire"
      d="M12 7.6 L4.6 16.4 M12 7.6 L19.4 16.4"
      stroke-width="3.4"
      stroke-linecap="round"
    />
    <rect class="brand-glyph-root" x="7.6" y="0.6" width="8.8" height="8.8" rx="3" />
    <rect class="brand-glyph-leaf" x="0.4" y="14.6" width="8.8" height="8.8" rx="3" />
    <rect class="brand-glyph-leaf" x="14.8" y="14.6" width="8.8" height="8.8" rx="3" />
  </svg>
</template>

<style scoped>
/* `display: block` so the glyph does not sit on a text baseline inside the
   32 px tile: as an inline element it inherits the line box's descender and
   lands two pixels low, which at 20 px is a tenth of the mark. */
.brand-glyph { display: block; }
.brand-glyph-wire { stroke: var(--on-accent-cyan); }
.brand-glyph-root { fill: var(--on-accent-cyan); }
.brand-glyph-leaf { fill: var(--on-accent-mint); }
</style>
