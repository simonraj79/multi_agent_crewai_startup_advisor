<script setup lang="ts">
/**
 * The run's conclusion.
 *
 * Until this component existed the console showed nothing at the end of a run
 * - not the verdict, not the score, not the report. The body was on the wire
 * the whole time; it had nowhere to land. This is where it lands.
 *
 * It opens itself the first time a report arrives, because "the final output
 * is visible" cannot depend on the operator knowing to look for a button.
 *
 * The scorecard below the header arrived with the `verdict` frame. Before it,
 * the only number that ever reached this panel was a confidence percentage
 * rescued from the verdict gate as it closed - so an unattended (`gates=auto`)
 * run, which never opens that gate, finished under a bare fallback badge, and
 * the fatal floors were invisible in every mode. PRD 10.2 calls the
 * free-alternative floor "the most valuable output this system produces".
 *
 * The block that says so is keyed on `decision_reason`, NOT on `fatal_floors`,
 * and the difference is not cosmetic. The two are computed independently in
 * `Verdict.compute_mechanical_result`: the floors are collected first and
 * unconditionally, then a separate ladder picks the reason, and its FIRST
 * branch is the low-confidence override. A run at 34% confidence with
 * `market == 0` therefore carries `FLOOR_NO_MARKET` while that floor decided
 * nothing - and the block this replaces said, in its loudest element, that the
 * floor "not the arithmetic, is why this run reads NEEDS_WORK". It was false on
 * exactly the screen it was written for. Floors that did not decide are
 * demoted to also-rans here, in the conditional tense, because that is what
 * happened. `data/verdictDisplay.ts` carries the wording and the reasoning.
 */
import { computed, nextTick, ref, watch } from 'vue'
import { Check, Copy, FileText, Gauge, OctagonAlert, X } from 'lucide-vue-next'
import type { RunResult, VerdictSummary } from '../types/studio'
import {
  DIMENSION_MAX,
  confidenceChip,
  describeDecision,
  dimensionName,
  dimensionQuestion,
  thinDimensionKeys,
  thinEvidencePhrase,
  verdictLabel,
  verdictTone as verdictToneFor,
} from '../data/verdictDisplay'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps<{
  report: RunResult | null
  verdict: VerdictSummary | null
  open: boolean
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const panel = ref<HTMLElement | null>(null)
const copied = ref(false)
let copyTimer = 0

const body = computed(() => renderMarkdown(props.report?.markdown_body ?? ''))
const sources = computed(() => props.report?.sources ?? [])

/**
 * Either carrier may say so. The report's own flag predates the verdict frame
 * and a gate-sourced summary has no opinion, so the two are OR-ed rather than
 * one preferred: provisional is a warning, and losing a warning is the only
 * failure mode here that costs anything.
 */
const provisional = computed(
  () => props.report?.provisional === true || props.verdict?.provisional === true,
)

/** `VALIDATE` / `NEEDS_WORK` / `REJECT` drive the badge colour. */
const verdictTone = computed(() => `is-${verdictToneFor(props.verdict?.verdict)}`)
/** Words, never the enum. The badge shouts through CSS, not through the DOM. */
const verdictWord = computed(() => verdictLabel(props.verdict?.verdict))

/** 0-10, from `2 * (0.30D + 0.20M + 0.20C + 0.15F + 0.15X)`. */
const compositeScore = computed(() => {
  const value = props.verdict?.compositeScore
  return typeof value === 'number' ? value.toFixed(1) : null
})

/**
 * One chip, not two. `34% confidence` beside a shouted `LOW` was two elements
 * carrying one fact, and `LOW` alone answers "low what?" with nothing.
 */
const confidence = computed(() =>
  confidenceChip(props.verdict?.confidenceBand, props.verdict?.confidence),
)

/** Canonical dimension keys the report flagged as resting on too few sources. */
const thinKeys = computed(() => thinDimensionKeys(props.report))
const thinPhrase = computed(() => thinEvidencePhrase(thinKeys.value))

/**
 * The override block, keyed on `decision_reason` and NOT on `fatal_floors`.
 *
 * The two are computed independently in `Verdict.compute_mechanical_result`:
 * the floors are collected unconditionally, then a separate ladder picks the
 * reason and its first branch is the low-confidence override. So a run can
 * carry `FLOOR_NO_MARKET` while that floor decided nothing - which is exactly
 * what the block this replaces used to narrate as the cause. `null` here means
 * the arithmetic decided and there is nothing to override; the scores below
 * are then the whole answer and no red box is drawn.
 */
const decision = computed(() => describeDecision(props.verdict, props.report))

/** The scorecard, already in rubric order - the composable sorts it. */
const dimensionRows = computed(() =>
  Object.entries(props.verdict?.dimensions ?? {}).map(([key, score]) => {
    const value = score as number
    const blocked = decision.value?.blockedDimensions.includes(key) ?? false
    return {
      key,
      label: dimensionName(key),
      question: dimensionQuestion(key),
      thin: thinKeys.value.includes(key),
      // A zero is the score every fatal floor is written about, so it is the
      // one that earns the error tint whether or not a floor happened to fire.
      floored: value === 0 || blocked,
      score: value,
      // Every ladder is 0-5. Clamped so a score outside that range - a newer
      // server, a wider ladder - cannot draw a bar past the end of its track.
      percent: `${Math.min(100, Math.max(0, (value / DIMENSION_MAX) * 100))}%`,
    }
  }),
)

const hasVerdictDetail = computed(
  () => decision.value !== null || dimensionRows.value.length > 0,
)

// Move focus into the sheet when it opens so a keyboard user is not left
// behind on the canvas, and so Escape has somewhere to fire from.
watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return
    await nextTick()
    panel.value?.focus()
  },
)

async function copyReport(): Promise<void> {
  const text = props.report?.markdown_body
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    window.clearTimeout(copyTimer)
    copyTimer = window.setTimeout(() => { copied.value = false }, 2000)
  } catch {
    // Clipboard permission is not guaranteed; the body stays selectable, so
    // failing silently here still leaves the operator a way to take the text.
    copied.value = false
  }
}
</script>

<template>
  <section
    v-if="open && report"
    ref="panel"
    class="report-panel"
    role="dialog"
    aria-modal="false"
    aria-labelledby="report-title"
    tabindex="-1"
    @keydown.esc="emit('close')"
  >
    <header class="report-head">
      <div class="report-title-group">
        <span class="report-kicker"><FileText :size="13" aria-hidden="true" />VALIDATION REPORT</span>
        <h2 id="report-title">
          <span v-if="verdictWord" class="verdict-badge" :class="verdictTone" :data-code="verdict?.verdict">{{ verdictWord }}</span>
          <span v-else class="verdict-badge is-warn">Finished</span>
          <span v-if="compositeScore" class="verdict-score">{{ compositeScore }}<small>/10</small></span>
          <span
            v-if="confidence"
            class="verdict-confidence"
            :class="`is-${confidence.tone}`"
            title="How much evidence the five scores rest on: branch coverage, source freshness, and whether all three research branches came home."
          >{{ confidence.label }}</span>
        </h2>
      </div>
      <div class="report-actions">
        <button class="report-button" type="button" @click="copyReport">
          <component :is="copied ? Check : Copy" :size="14" aria-hidden="true" />
          {{ copied ? 'Copied' : 'Copy Markdown' }}
        </button>
        <button class="report-button is-icon" type="button" aria-label="Close report" @click="emit('close')">
          <X :size="16" aria-hidden="true" />
        </button>
      </div>
    </header>

    <div v-if="provisional || thinPhrase" class="report-flags">
      <!-- `Provisional` is kept as the head word, glossed rather than replaced:
           the markdown body below is REQUIRED by `validator_guardrails.py` to
           carry "Provisional" in its title and first summary line, and a chip
           reading something else over a report headed "(Provisional)" teaches
           the reader two names for one thing. -->
      <span
        v-if="provisional"
        class="report-flag is-provisional"
        title="The evidence is too thin to settle this. Re-run with better sources before acting on it."
      >Provisional · not a final answer</span>
      <span
        v-if="thinPhrase"
        class="report-flag"
        title="These scores rest on fewer sources than the rubric asks for."
      >Thin evidence · {{ thinPhrase }}</span>
    </div>

    <div v-if="hasVerdictDetail" class="verdict-summary">
      <!-- Above the scorecard on purpose: whatever decided this run overrode
           the arithmetic, so reading the composite first and the override
           afterwards gets the conclusion backwards. -->
      <section
        v-if="decision"
        class="verdict-decision"
        :class="`is-${decision.tone}`"
        :data-code="decision.code"
        aria-labelledby="verdict-decision-title"
      >
        <h3 id="verdict-decision-title">
          <OctagonAlert :size="13" aria-hidden="true" />
          <span>WHAT DECIDED THIS RUN</span>
        </h3>
        <p class="decision-headline">{{ decision.headline }}</p>
        <p v-if="decision.meaning" class="decision-meaning">{{ decision.meaning }}</p>
        <div v-if="decision.alsoBlocking.length" class="decision-also">
          <span class="decision-also-kicker">ALSO BLOCKING</span>
          <p
            v-for="entry in decision.alsoBlocking"
            :key="entry.code"
            class="decision-also-line"
            :data-code="entry.code"
          >{{ entry.text }}</p>
        </div>
      </section>

      <section v-if="dimensionRows.length" class="verdict-scores" aria-labelledby="verdict-scores-title">
        <h3 id="verdict-scores-title">
          <Gauge :size="13" aria-hidden="true" />
          <span>Scores</span>
        </h3>
        <div
          v-for="row in dimensionRows"
          :key="row.key"
          class="score-row"
          :class="{ 'is-floored': row.floored }"
          :data-dimension="row.key"
        >
          <span class="score-label">
            <span class="score-name">
              {{ row.label }}
              <span v-if="row.thin" class="score-thin" title="Fewer sources than the rubric asks for.">thin</span>
            </span>
            <span v-if="row.question" class="score-question">{{ row.question }}</span>
          </span>
          <span class="score-track" aria-hidden="true">
            <span class="score-fill" :style="{ width: row.percent }"></span>
          </span>
          <span class="score-value">{{ row.score }}<small>/5</small></span>
        </div>
      </section>
    </div>

    <!-- eslint-disable-next-line vue/no-v-html -->
    <article class="report-body markdown-body" v-html="body"></article>

    <footer v-if="sources.length" class="report-sources">
      <h3>{{ sources.length }} cited source{{ sources.length === 1 ? '' : 's' }}</h3>
      <ol>
        <li v-for="(source, i) in sources" :key="source.url ?? i">
          <a v-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer nofollow">
            {{ source.title || source.url }}
          </a>
          <span v-else>{{ source.title || 'Untitled source' }}</span>
        </li>
      </ol>
    </footer>
  </section>
</template>

<style scoped>
.report-panel {
  position: absolute;
  z-index: 12;
  top: 64px;
  right: 0;
  bottom: 0;
  left: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--surface-overlay);
  border-top: 1px solid var(--border-default);
  animation: report-rise var(--motion-medium) var(--ease-out);
}

/* NO `backdrop-filter` here, and its removal is a MEASUREMENT rather than a
   preference.

   W4's round-three bisect (`docs/run-shell/evidence/T2/perf-notes.md` §2) ran
   the 131-frame replay once per suppressed suspect. Every other arm moved the
   count of over-budget frames by at most 13; suppressing every
   `backdrop-filter` moved it from **77 to 13**, and p95 from 81.8 ms to
   28.3 ms. Headless Chromium rasterises in software here and a blur re-reads
   everything behind the element on every frame that touches it.

   And it was buying nothing. This surface is 94% opaque, so the blur was
   filtering a background that is already almost entirely covered - the
   coordinator's phrase for it is "a twentieth of a pixel". The alpha is
   deliberately NOT raised to compensate: there is nothing to compensate for at
   this opacity, and every token that could carry the rise is shared with the
   builder, whose sixteen baselines would move to correct a difference nobody
   can see.

   `--blur-panel` and `--blur-rail` still exist and the builder still uses both
   (its minimap, its two dialogs, its shortcut sheet) - see `docs/design.md`
   §3. A design canvas is still; a run console is not, and that is the whole
   difference. */


@keyframes report-rise {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

.report-head {
  display: flex;
  flex: 0 0 auto;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--border-default);
}

.report-kicker { display: inline-flex; gap: var(--space-2); align-items: center; color: var(--on-accent-cyan); font: var(--type-kicker); }
.report-title-group h2 { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 8px 0 0; font-size: var(--fs-18); }

.verdict-badge {
  padding: 4px 10px;
  color: var(--ink-on-brand);
  font: 800 var(--fs-13)/1.3 var(--font-mono);
  border-radius: var(--r-sm);
  letter-spacing: 0.04em;
  /* The DOM text is words ("Needs work"); the shout is typography. An
     unrecognised label from a newer server therefore cannot reach the screen
     looking like a variable name. */
  text-transform: uppercase;
}
/* Each variant is filled with its own status colour, and `is-fail` was the one
   literal in the set (`#ffb4b4`) until 2026-09-05.

   GAP RECORDED HERE, THEN CLOSED IN `tokens.css` THE SAME DAY, and both halves
   are worth keeping because the diagnosis is what made the fix a two-line one.
   `--warn-text` and `--err-text` are TEXT colours used here as FILLS. In the
   dark theme both are pale, so the near-black `--ink-on-brand` reads at 13.04:1
   and 11.85:1. In the light theme both flip DARK - a text colour on a pale tint
   has to - and the same ink measured 2.84:1 and 2.24:1, which made the badge
   saying REJECT the least readable thing on the page. `--accent-mint` is shared
   across themes, so `is-pass` was never affected and is 14.37:1 in both.

   It was not fixable from this file: `tokens.css` is explicit that nothing
   outside it knows a theme exists, so the answer had to be an ink per theme
   rather than a component-level media block. `--ink-on-warn` and `--ink-on-err`
   are that pair; they are near-black in dark and a 3-5% tint of their own
   family in light, and they measure 5.60:1 and 7.05:1 there. */
.verdict-badge.is-pass { background: var(--accent-mint); }
.verdict-badge.is-warn { color: var(--ink-on-warn); background: var(--warn-text); }
.verdict-badge.is-fail { color: var(--ink-on-err); background: var(--err-text); }

/* One chip carries the band word and the number, so a reader is never asked
   to join "34% confidence" to a shouted "LOW" themselves. */
.verdict-confidence {
  padding: 3px var(--space-3);
  color: var(--text-muted);
  font: 600 var(--fs-12)/1.2 var(--font-mono);
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
}
.verdict-confidence.is-high { color: var(--on-accent-mint); border-color: color-mix(in srgb, var(--accent-mint) 34%, transparent); }
.verdict-confidence.is-moderate { color: var(--on-accent-cyan); border-color: color-mix(in srgb, var(--accent-cyan) 32%, transparent); }
.verdict-confidence.is-low { color: var(--warn-text-strong); background: var(--warn-bg); border-color: var(--warn-border-strong); }

.verdict-score { color: var(--text-title); font: 700 var(--fs-18)/1 var(--font-display); }
.verdict-score small { color: var(--text-meta); font: 500 var(--fs-12)/1 var(--font-mono); }

.report-flags { display: flex; flex: 0 0 auto; flex-wrap: wrap; gap: var(--space-3); padding: var(--space-4) var(--space-7) 0; }
.report-flag {
  padding: var(--space-1) var(--space-3);
  color: var(--text-muted);
  font: 500 var(--fs-12)/1.4 var(--font-body);
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
}
.report-flag.is-provisional { color: var(--warn-text-strong); background: var(--warn-bg); border-color: var(--warn-border-strong); }

/* Bounded so a long decision block can never squeeze the report body to
   nothing on a short viewport; it scrolls on its own instead. */
.verdict-summary {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  gap: var(--space-5);
  max-height: 42vh;
  overflow: auto;
  padding: var(--space-5) var(--space-7) 0;
}

/* Tone tracks the KIND of decision, and the distinction is the point: red for
   "this idea is dead", amber for "we could not tell". A reader had to infer
   that before; the tint states it. Both are existing semantic tokens. */
.verdict-decision {
  padding: var(--space-5);
  border-radius: var(--r-md);
}
.verdict-decision.is-floor { background: var(--err-bg); border: 1px solid var(--err-border-strong); }
.verdict-decision.is-evidence { background: var(--warn-bg); border: 1px solid var(--warn-border-strong); }

.verdict-decision h3,
.verdict-scores h3 {
  display: inline-flex;
  gap: var(--space-2);
  align-items: center;
  margin: 0;
  font: var(--type-kicker);
  letter-spacing: var(--track-kicker);
  text-transform: uppercase;
}
.verdict-decision.is-floor h3 { color: var(--err-text); }
.verdict-decision.is-evidence h3 { color: var(--warn-text-strong); }

.decision-headline {
  margin: var(--space-3) 0 0;
  color: var(--text-title);
  font: 600 var(--fs-18)/1.3 var(--font-display);
}
.decision-meaning { margin: var(--space-2) 0 0; color: var(--text-body); font-size: var(--fs-13); line-height: 1.55; }

.decision-also {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-default);
}
.decision-also-kicker {
  display: block;
  margin-bottom: var(--space-1);
  color: var(--text-meta);
  font: var(--type-kicker);
  letter-spacing: var(--track-kicker);
}
.decision-also-line { margin: 0 0 var(--space-1); color: var(--text-muted); font-size: var(--fs-12); line-height: 1.5; }
.decision-also-line:last-child { margin-bottom: 0; }

.verdict-scores {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-5);
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
}
.verdict-scores h3 { margin-bottom: 2px; color: var(--on-accent-cyan); }
.score-row { display: grid; grid-template-columns: minmax(120px, 190px) minmax(48px, 1fr) auto; gap: var(--space-4); align-items: center; }
.score-label { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.score-name { display: flex; gap: var(--space-2); align-items: baseline; color: var(--text-body); font: 600 var(--fs-13)/1.3 var(--font-body); }
.score-question { color: var(--text-meta); font: 400 var(--fs-11)/1.35 var(--font-body); }
.score-thin {
  padding: 1px 5px;
  color: var(--warn-text-strong);
  font: 700 var(--fs-11)/1.3 var(--font-mono);
  background: var(--warn-bg);
  border: 1px solid var(--warn-border-strong);
  border-radius: var(--r-pill);
}
.score-track {
  height: 6px;
  overflow: hidden;
  background: var(--surface-well);
  box-shadow: inset 0 0 0 1px var(--border-control);
  border-radius: var(--r-pill);
}
/* The brand gradient's three stops, in their READABLE variants.

   `--gradient-brand` is one shared value in both themes, and measured against
   this track it is 16.26 / 14.08 / 10.75:1 in the dark and
   1.14 / 1.01 / 1.33:1 in the light - a pale mint bar on a pale grey groove,
   which is a progress bar whose proportion cannot be read at all. A cold
   reader found it; the numbers are `scripts/contrast-audit.mjs`'s formula over
   the stack this panel really paints (bg-app -> shell-bg -> surface-overlay ->
   well -> well).

   Every `--on-accent-*` token ALIASES its accent in the dark palette, so this
   gradient is byte-identical to `--gradient-brand` there - not one dark pixel
   moves - and resolves to the readable inks in the light one: 4.90 / 4.59 /
   4.72:1, against the 3:1 that WCAG 1.4.11 asks of a UI component. The bar is
   the only thing carrying the proportion, so it is a component and not
   decoration. */
.score-fill {
  display: block;
  height: 100%;
  background: linear-gradient(
    135deg,
    var(--on-accent-mint),
    var(--on-accent-cyan),
    var(--on-accent-blue)
  );
  border-radius: var(--r-pill);
  transition: width var(--motion-medium) var(--ease-out);
}
/* The one tie between the red block and the scorecard: a reader who has just
   read "Market scored 0 of 5" can find the row without hunting. */
/* A zero row draws NO fill, so the tint and its ring are the whole signal -
   and `--err-bg` alone measures 1.14:1 dark / 1.16:1 light against the card,
   which is a red that is not there. The ring carries it. `--err-border-strong`
   was the obvious token and lands at 3.16:1 dark but 2.91:1 light, 0.09 short
   of the bar; `--err-text` clears both at 11.32:1 and 5.46:1 and is already
   the colour of the `0/5` beside it, so the ring and the number read as one
   statement rather than two. */
.score-row.is-floored .score-track { background: var(--err-bg); box-shadow: inset 0 0 0 1px var(--err-text); }
.score-row.is-floored .score-value { color: var(--err-text); }
.score-value { color: var(--text-primary); font: 700 var(--fs-13)/1 var(--font-mono); }
.score-value small { color: var(--text-meta); font-weight: 500; }

.report-actions { display: flex; flex: 0 0 auto; gap: 8px; }
.report-button {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  padding: 7px 11px;
  color: var(--text-body);
  font: 600 var(--fs-12)/1 var(--font-body);
  background: var(--surface-raised);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  cursor: pointer;
  transition: border-color var(--motion-fast) ease, color var(--motion-fast) ease;
}
.report-button:hover { color: var(--text-title); border-color: var(--border-hover); }
.report-button.is-icon { padding: 7px; }

.report-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 18px 20px 28px;
  scrollbar-color: color-mix(in srgb, var(--accent-cyan) 30%, transparent) transparent;
}

.report-sources { flex: 0 0 auto; max-height: 26%; overflow: auto; padding: 12px 20px 18px; border-top: 1px solid var(--border-default); }
.report-sources h3 { margin: 0 0 var(--space-3); color: var(--on-accent-cyan); font: var(--type-kicker); text-transform: uppercase; }
.report-sources ol { margin: 0; padding-left: 20px; color: var(--text-muted); font-size: var(--fs-12); }
.report-sources li { margin-bottom: 4px; overflow-wrap: anywhere; }
.report-sources a { color: var(--link-strong); }

@media (prefers-reduced-motion: reduce) {
  .report-panel { animation: none; }
  .score-fill { transition: none; }
}
</style>
