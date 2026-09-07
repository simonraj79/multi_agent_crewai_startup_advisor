<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight } from 'lucide-vue-next'
import GraphThumbnail from './GraphThumbnail.vue'
import type { BuilderTemplate, PatternSource } from '../../data/builderTemplates'

/**
 * One template card, used for every card the gallery draws.
 *
 * WHY IT IS A COMPONENT AT ALL. There were two copies of this markup in
 * `TemplateGallery.vue` - the first row's card and the demoted row's - and the
 * second had silently lost the caveat block (AUDIT-REPO §2.2, rec 13). Nothing
 * failed, because neither demoted template carried a caveat; the divergence was
 * simply waiting for one to. A gallery growing from nine cards to thirteen
 * across six sections cannot carry two card bodies, so there is one.
 *
 * WHY THE CARD IS NOT A `<button>` ANY MORE, WHICH IT WAS UNTIL THIS CHANGE.
 * The card now holds a native `<details>` (`.agent/plans/16-pattern-templates.md`
 * criterion 11), and `<details>` is interactive content: inside a `<button>` it
 * is invalid HTML and no browser toggles it - the button swallows the press.
 * The same sentence is already written in `TemplateGallery.vue`'s caveat
 * comment, where it ruled OUT a disclosure for the caveat for exactly this
 * reason. So the card is an `<article>`, and the one control inside it is the
 * `Use this template` action, whose `::after` is stretched over the whole card:
 * one focusable thing with the right accessible name, the whole card clickable,
 * and a disclosure that actually opens.
 *
 * The click handler sits on the `<article>` rather than on the action, so a
 * press anywhere - including a keyboard Enter on the action, which dispatches a
 * click that bubbles - reaches one handler. A handler on both would fire twice.
 *
 * WHY THE FIELDS ARE IN THIS ORDER. A person browsing has a job, not a
 * vocabulary. Pattern name first because it is the word the literature uses and
 * the one they may have arrived carrying; then what this is; then the JOB, which
 * is the field the owner asked for by name; then the two decision lines that let
 * them rule it in or out without opening it. `teaches` and `modifyFirst` are the
 * syntax notes - true, useful, and not what the first question is - so they are
 * behind a closed disclosure. That is also what keeps thirteen cards inside
 * `e2e/builder-layout.spec.ts`'s tallest-to-shortest content ratio.
 */

/** What the server said this template costs. `null` while it is still asking. */
export interface TemplatePrice {
  readonly billable: number
  readonly floorUsd: number
  readonly staticUsd: number
}

const props = defineProps<{
  template: BuilderTemplate
  /** The server's answer, or `null` if it has not arrived or did not come. */
  price?: TemplatePrice | null
  /** Whether the gallery is still asking, which is the difference between `…` and `—`. */
  pricing: boolean
}>()

const emit = defineEmits<{ start: [template: BuilderTemplate] }>()

const money = (value: number) => `$${value.toFixed(2)}`

/**
 * Who calls this shape by this name (D5).
 *
 * Named in the pattern line and nowhere else, so the card never turns into a
 * bibliography. `none` is the two scaffolds, which are not patterns and get no
 * attribution rather than a fabricated one.
 */
const PROVENANCE: Readonly<Record<PatternSource, string>> = {
  anthropic: 'Anthropic',
  google: 'Google',
  both: 'Anthropic and Google',
  none: '',
}

const provenance = computed(() => PROVENANCE[props.template.pattern.source])
</script>

<template>
  <article class="template-card" @click="emit('start', template)">
    <!-- Derived from the document, never a captured picture, so it cannot
         advertise a shape the template no longer has (spec R39). -->
    <GraphThumbnail class="template-spine" :document="template.document" />

    <p class="template-pattern">
      <span class="template-pattern-name">{{ template.pattern.name }}</span>
      <span v-if="provenance" class="template-pattern-source">{{ provenance }}</span>
    </p>

    <!-- h4: the gallery section above it owns the h3, so the outline reads
         TEMPLATES > Start here > Blank canvas rather than two h3s in a row. -->
    <h4>{{ template.title }}</h4>

    <!--
      THE JOB LEADS, AND THE BLURB IS GONE FROM THIS CARD.
      Found by looking at the 1440 capture: the two paragraphs said the same
      thing twice - `single-agent` read "One agent with one search tool answers
      a question..." and then "A help desk gets a product question. One agent
      decides what to search for...". Two openings is one too many, and they
      pushed the two lines a person actually decides on below the fold. The job
      is the specific one, so it stays; the blurb keeps its place on the HOME,
      where there is no job line and one sentence has to do the whole work.
    -->
    <p class="template-use-case">{{ template.useCase }}</p>

    <!--
      THE TWO DECISION LINES, AS ONE BLOCK THAT SCANS.
      They are the most useful thing on the card and they were the least
      visible: two more grey paragraphs in a column of grey paragraphs. Given
      the fact strip's shape - a well, a hairline, uppercase mono labels - so
      the eye finds them without reading them, which is what a person choosing
      between thirteen cards is doing.
    -->
    <dl class="template-rules">
      <div>
        <dt>Use it when</dt>
        <dd>{{ template.useWhen }}</dd>
      </div>
      <div>
        <dt>Not when</dt>
        <dd>{{ template.notWhen }}</dd>
      </div>
    </dl>

    <!--
      Rendered verbatim (R14). It is the difference between a template and a
      booby trap, and paraphrasing it on a card is how the difference gets lost.
      Lifted above the action's stretched overlay so its own scroller still
      answers a wheel - see the style block.
    -->
    <p v-if="template.caveat" class="template-caveat">{{ template.caveat }}</p>

    <dl class="template-facts">
      <div>
        <dt>Nodes</dt>
        <dd>{{ template.document.nodes.length }}</dd>
      </div>
      <div>
        <dt>Edges</dt>
        <dd>{{ template.document.edges.length }}</dd>
      </div>
      <div>
        <dt>Billable</dt>
        <dd>
          <template v-if="price">{{ price.billable }}</template>
          <template v-else-if="pricing">…</template>
          <template v-else>—</template>
        </dd>
      </div>
      <div>
        <dt>Est. run</dt>
        <dd
          :title="
            price
              ? `Published prices ${money(price.floorUsd)}; enforced with the nitro margin ${money(price.staticUsd)}.`
              : undefined
          "
        >
          <!--
            BOTH figures, never the enforced one alone. `static_cost_usd`
            carries a 1.8x margin on every cheap node, so showing it by itself
            reads as an error beside anyone's mental arithmetic - the same
            reasoning BudgetMeter states at length.
          -->
          <template v-if="price">
            {{ money(price.floorUsd) }}–{{ money(price.staticUsd) }}
          </template>
          <template v-else-if="pricing">…</template>
          <template v-else>—</template>
        </dd>
      </div>
    </dl>

    <!--
      The syntax notes, closed. Native `<details>`: the browser already has a
      disclosure, it carries the expanded state to a screen reader without a
      line of script, and it is the reason the card can hold five more fields
      than it used to without doubling in height.
    -->
    <!--
      `@click.stop` is load-bearing and was found by LOOKING: the summary
      toggles natively AND the click bubbles to the card, so opening the
      disclosure also seeded the template onto the canvas and the reader never
      saw what they had asked to see. Stopped here rather than by moving the
      handler, because the handler on the card is what makes the whole tile one
      press.
    -->
    <details class="template-drawn" @click.stop>
      <summary>How it is drawn</summary>
      <!--
        `aka` was a line under the kicker and read as a subtitle - "SINGLE AGENT
        Anthropic and Google" over "Single-agent system" looked like a second
        name for the card rather than the other source's name for the pattern.
        It is provenance, so it belongs with the rest of the explanation.
      -->
      <p v-if="template.pattern.aka" class="template-teaches">
        <span class="template-lede">Also called</span>{{ template.pattern.aka }}
      </p>
      <p class="template-teaches">
        <span class="template-lede">Teaches</span>{{ template.teaches }}
      </p>
      <p class="template-teaches">
        <span class="template-lede">Change first</span>{{ template.modifyFirst }}
      </p>
    </details>

    <!--
      WHAT THE CLICK DOES, on the card itself (ROUND-2 X2's rule that every card
      names its action), and the card's one focusable control.

      Its `::after` covers the card, so the whole tile is the affordance while
      exactly one thing is in the tab order and it is named `Use this template`.
      The card's handler takes the press; this carries no handler of its own, or
      every click would count twice.
    -->
    <button class="template-action" type="button">
      Use this template
      <ArrowRight :size="13" aria-hidden="true" />
    </button>
  </article>
</template>

<style scoped>
/*
 * A COLUMN, not a grid with `align-content: start`.
 *
 * The grid row is as tall as its tallest card, and cards packed to the start
 * ended their content 206px above their own bottom edge (46% of the card) and
 * read as unfinished beside a full one. As a flex column with the fact table
 * pushed down, every card's stats sit near its bottom edge and the equal
 * heights read as deliberate (D-15-27).
 *
 * `position: relative` is the action's positioning context; see `.template-action`.
 */
.template-card {
  position: relative;
  display: flex;
  flex-direction: column;
  /* Six text blocks now rather than three, so the rhythm is one step tighter:
     at `--space-3` the gaps alone were 80px of a 600px card. */
  gap: var(--space-2);
  width: 100%;
  height: 100%;
  padding: var(--space-5);
  text-align: left;
  color: var(--text-body);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--r-2xl);
  cursor: pointer;
  transition: background var(--motion-fast) ease, border-color var(--motion-fast) ease;
}

.template-card:hover { background: var(--surface-raised); border-color: var(--border-hover); }

/* The focus ring belongs to the CARD even though the button owns the focus:
   the button is a strip at the bottom and the thing being chosen is the tile. */
.template-card:focus-within { border-color: var(--border-hover-strong); box-shadow: var(--glow-input); }

/*
 * The thumbnail must not stretch to fill a flex column - it is a fixed-ratio
 * spine and a stretched one is a different picture of the same workflow.
 *
 * The height is CAPPED rather than left to the 240x90 viewBox, which resolved
 * to 83px at this column width - a big field with two dots on it for half the
 * templates, and 30px of the height the `Use this template` action needed to
 * clear the fold. The class lands on the `<svg>` itself, so this is the svg's
 * own box; `preserveAspectRatio` scales the whole drawing down and nothing is
 * cropped.
 */
.template-spine {
  flex: none;
  height: 56px;
  padding: var(--space-2) 0;
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-lg);
}

/* The pattern this card is an instance of, and who calls it that (D5). One
   line, wrapping, so a long provenance drops under the name instead of
   clipping. */
.template-pattern {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-2);
  align-items: baseline;
  margin: 0;
}

.template-pattern-name {
  color: var(--on-accent-cyan);
  font: var(--type-kicker);
  letter-spacing: var(--track-kicker);
  text-transform: uppercase;
}

/* Not uppercase: two proper nouns in mono caps read as shouting, and the line
   is already long enough to wrap at the card's 232px floor. */
.template-pattern-source { color: var(--text-40); font: var(--type-meta); }

.template-card h4 { margin: 0; color: var(--text-title); font: var(--type-title); }

/* The job: who, what arrives, what goes out. The card's lead paragraph, and
   the only prose on it above the rules. */
.template-use-case { margin: 0; color: var(--text-muted); font: var(--type-label); }

/* The drawing notes, inside the disclosure. `--fs-11` rather than a role, and
   that is the criterion's own exception: both roles at 11px
   (`--type-kicker`, `--type-meta`) are the uppercase mono ones, and these are
   prose. */
.template-teaches {
  margin: 0;
  color: var(--text-40);
  font-size: var(--fs-11);
  line-height: 1.5;
}

/*
 * THE DECISION BLOCK. The fact strip's family - a well, a hairline between the
 * rows, uppercase mono labels - because it answers the same kind of question:
 * something to check rather than something to read. Two rows and never more,
 * so it stays a block and does not become a table.
 */
.template-rules {
  display: grid;
  margin: 0;
  overflow: hidden;
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
}

.template-rules > div { padding: var(--space-2) var(--space-3); }
.template-rules > div + div { border-top: 1px solid var(--border-default); }

.template-rules dt {
  margin-bottom: var(--space-1);
  color: var(--text-muted);
  font: var(--type-kicker);
  letter-spacing: var(--track-kicker);
  text-transform: uppercase;
}

.template-rules dd { margin: 0; color: var(--text-40); font: var(--type-label); }

/* INLINE, not a block. As a block each label cost the card a line, and the
   cards then overflowed the gallery's own `max-height: 100%` - which is
   `builder-layout.spec.ts`'s clipping guard, arriving from the other side. */
.template-lede {
  margin-right: var(--space-2);
  color: var(--text-muted);
  font: var(--type-kicker);
  letter-spacing: var(--track-kicker);
  text-transform: uppercase;
}

/*
 * Warn colours, not error. Nothing is wrong with the template; there is
 * something about it the picture cannot say.
 *
 * D-15-27: one card carries this block and its neighbours do not, so the grid
 * row - as tall as its tallest card - made the block 177px of a 232px column
 * and the siblings read as unfinished. The answer is "equalise heights and
 * scroll inside the block", which keeps R14 intact where clamping would not:
 * the caveat is in the DOM verbatim and in full, and read in full by a screen
 * reader. What changes is how much of the card's height it spends.
 */
.template-caveat {
  /* Above the action's stretched overlay, or a wheel over the block would
     scroll the gallery behind it and the rest of the sentence would be
     unreachable. The cost is that a click here does not open the template,
     which is the right trade for a warning you are meant to read. */
  position: relative;
  z-index: 1;
  margin: 0;
  padding: var(--space-3) var(--space-4);
  /* Three lines plus the padding. The block was nine. */
  max-height: calc(3 * 1.5 * var(--fs-11) + 18px);
  overflow-y: auto;
  /* Or a wheel over the caveat scrolls the gallery once the block reaches its
     end, which reads as the page jumping. */
  overscroll-behavior: contain;
  color: var(--warn-text);
  font-size: var(--fs-11);
  line-height: 1.5;
  background: var(--warn-bg);
  border: 1px solid var(--warn-border);
  border-radius: var(--r-md);
}

/*
 * The four counts, on the card's bottom edge.
 *
 * Hairlines are cell borders rather than a 1px grid gap over a background: a
 * literal px in `gap` is a bug (`docs/design.md`), and this one was never
 * spacing - it was a rule being drawn. Same pixels, one fewer literal.
 */
.template-facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  /* The one line that lands the stats near the card's bottom edge. */
  margin: auto 0 0;
  overflow: hidden;
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
}

.template-facts div {
  padding: var(--space-2) var(--space-1);
  background: var(--surface-well);
  border-left: 1px solid var(--border-default);
}
.template-facts div:first-child { border-left: 0; }
.template-facts dt {
  color: var(--text-40);
  font: var(--type-meta);
  font-weight: 600;
  text-transform: uppercase;
}
.template-facts dd {
  margin: var(--space-1) 0 0;
  color: var(--text-title);
  font: 600 var(--fs-12)/1 var(--font-mono);
  font-variant-numeric: tabular-nums;
}

/* The disclosure, above the overlay so the browser's own toggle still works. */
.template-drawn {
  position: relative;
  z-index: 1;
  display: grid;
  gap: var(--space-2);
}

.template-drawn > summary {
  color: var(--text-muted);
  font: var(--type-label);
  cursor: pointer;
}
.template-drawn > summary:hover { color: var(--text-title); }
.template-drawn[open] > summary { margin-bottom: var(--space-1); }

/*
 * The card's own action, and its only focusable control.
 *
 * `margin-top: auto` pins it to the bottom of the column so the row lines up
 * across cards of different heights - a floating action reads as several
 * different controls. The stretched `::after` is what makes the whole tile
 * clickable while exactly one thing sits in the tab order carrying the name
 * `Use this template`.
 */
.template-action {
  display: inline-flex;
  gap: var(--space-2);
  align-items: center;
  margin-top: auto;
  padding: var(--space-1) 0 0;
  color: var(--on-accent-cyan);
  font: 600 var(--fs-12)/1.2 var(--font-body);
  text-align: left;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.template-action::after { content: ''; position: absolute; inset: 0; }
.template-card:hover .template-action { color: var(--text-title); }
/* The ring is drawn on the card by `:focus-within`; a second one on a strip
   inside it would read as two things being focused. */
.template-action:focus-visible { outline: none; }
</style>
