<script setup lang="ts">
import { computed } from 'vue'
import { NODE_KINDS } from '../../data/nodeKinds'
import type { BuilderDocument } from '../../types/builder'

/**
 * A document's topology as a static SVG spine, drawn from the document's own
 * `position` values.
 *
 * DERIVED, NOT DRAWN. The alternative every gallery reaches for is a captured
 * PNG per template, and it is wrong for one reason that costs nothing to avoid:
 * a picture can drift from the graph it advertises, silently, and the drift is
 * invisible until an author clicks a card expecting five nodes and gets nine.
 * Reading the document means the preview is a projection of the thing it
 * previews, so it cannot be stale and there is no asset to regenerate.
 *
 * It renders a document the server has never seen, so it must survive one:
 * a template with no nodes gets an empty frame, and a graph whose nodes all sit
 * at the same coordinate gets a single centred dot rather than a division by
 * zero.
 */
const props = withDefaults(
  defineProps<{
    document: BuilderDocument
    /**
     * What a screen reader is told instead of the picture. Defaulted rather
     * than required, because the card beside it already names the template -
     * an unlabelled decorative graphic there is `aria-hidden`, not silent.
     */
    label?: string
  }>(),
  { label: '' },
)

/** The viewBox. 240x90 is the card's spine slot, and the aspect it is drawn to. */
const W = 240
const H = 90
/** Half a node square, so a rect at the extreme edge is not clipped in half. */
const PAD = 5
const NODE = 6

interface Dot {
  readonly id: string
  readonly x: number
  readonly y: number
  readonly fill: string
}

/**
 * Every node placed inside the frame, and every edge between two placed nodes.
 *
 * One computed rather than two, because the edges are expressed in the SAME
 * normalised coordinates as the dots: computing them separately would mean
 * normalising twice and would let a rounding difference put an edge's endpoint
 * a pixel off the node it leaves.
 */
const spine = computed(() => {
  const nodes = props.document.nodes
  if (nodes.length === 0) return { dots: [] as Dot[], lines: [] as string[] }

  const xs = nodes.map((node) => node.position.x)
  const ys = nodes.map((node) => node.position.y)
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  // A graph one column wide has a zero span, and dividing by it yields NaN
  // coordinates - which SVG renders as nothing at all, so the thumbnail would
  // simply be blank with no error anywhere.
  //
  // Falling back to a span of 1 avoided the NaN and then got the picture wrong
  // a second way: `(x - minX) / 1` is 0 for every node, so a straight vertical
  // chain drew every dot at `x = PAD` and HUGGED THE LEFT EDGE of a 240-wide
  // box. Measured on the "Minimal gated agent" card: four rects, all at x=2,
  // 97.5% of the picture empty and not even centred. A degenerate axis is
  // pinned to the box CENTRE instead, which is what a single column actually
  // looks like - and it is worth keeping even after a template is transposed,
  // because an author's own hand-drawn column will reach this again.
  const rawSpanX = Math.max(...xs) - minX
  const rawSpanY = Math.max(...ys) - minY

  const place = (x: number, y: number) => ({
    x: rawSpanX === 0 ? W / 2 : PAD + ((x - minX) / rawSpanX) * (W - PAD * 2),
    y: rawSpanY === 0 ? H / 2 : PAD + ((y - minY) / rawSpanY) * (H - PAD * 2),
  })

  const dots: Dot[] = nodes.map((node) => {
    const point = place(node.position.x, node.position.y)
    return { id: node.id, x: point.x, y: point.y, fill: NODE_KINDS[node.kind].accent }
  })
  const byId = new Map(dots.map((dot) => [dot.id, dot]))

  const lines = props.document.edges.flatMap((edge) => {
    const from = byId.get(edge.source)
    const to = byId.get(edge.target)
    // An edge naming a node that is not there is a real document state - it is
    // `edge-unknown-endpoint`, an error the server reports - and a thumbnail
    // must draw what it can rather than throw over it.
    if (!from || !to) return []
    return [`M ${from.x} ${from.y} L ${to.x} ${to.y}`]
  })

  return { dots, lines }
})
</script>

<template>
  <svg
    class="graph-thumbnail"
    :viewBox="`0 0 ${W} ${H}`"
    preserveAspectRatio="xMidYMid meet"
    :role="label ? 'img' : 'presentation'"
    :aria-label="label || undefined"
    :aria-hidden="label ? undefined : 'true'"
  >
    <path v-for="(line, index) in spine.lines" :key="index" class="thumb-edge" :d="line" />
    <rect
      v-for="dot in spine.dots"
      :key="dot.id"
      class="thumb-node"
      :x="dot.x - NODE / 2"
      :y="dot.y - NODE / 2"
      :width="NODE"
      :height="NODE"
      rx="2"
      :fill="dot.fill"
    />
  </svg>
</template>

<style scoped>
.graph-thumbnail {
  display: block;
  width: 100%;
  height: 90px;
}

/* Edges under nodes, and dimmer than them. The topology reads as a shape at
   this size; the individual connections do not, and drawing them at full
   strength turns a nine-node graph into a grey smear. */
.thumb-edge {
  fill: none;
  stroke: var(--edge-inactive);
  stroke-width: 1;
  opacity: 0.5;
}

/* No stroke on the squares. A 1px border on a 6px square is a third of it. */
.thumb-node { opacity: 0.92; }
</style>
