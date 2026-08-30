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
 * run, which never opens that gate, finished under a bare `COMPLETE` badge, and
 * the fatal floors were invisible in every mode. PRD 10.2 calls the
 * free-alternative floor "the most valuable output this system produces"; a
 * REJECT that a floor forced now says which floor, in the loudest block here.
 */
import { computed, nextTick, ref, watch } from 'vue'
import { Check, Copy, FileText, Gauge, OctagonAlert, X } from 'lucide-vue-next'
import type { RunResult, VerdictSummary } from '../types/studio'
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
const thin = computed(() => props.report?.thin_dimensions ?? [])
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
const verdictTone = computed(() => {
  const label = props.verdict?.verdict?.toUpperCase() ?? ''
  if (label.includes('VALIDATE')) return 'is-pass'
  if (label.includes('REJECT')) return 'is-fail'
  return 'is-warn'
})

const confidencePercent = computed(() => {
  const value = props.verdict?.confidence
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : null
})

/** 0-10, from `2 * (0.30D + 0.20M + 0.20C + 0.15F + 0.15X)`. */
const compositeScore = computed(() => {
  const value = props.verdict?.compositeScore
  return typeof value === 'number' ? value.toFixed(1) : null
})

const confidenceBand = computed(() => props.verdict?.confidenceBand ?? null)
const bandTone = computed(() => `is-${(confidenceBand.value ?? '').toLowerCase()}`)

const fatalFloors = computed(() => props.verdict?.fatalFloors ?? [])
const decisionReason = computed(() => props.verdict?.decisionReason ?? null)

function sentenceCase(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/**
 * `FLOOR_ALREADY_FREE` -> `Already free`. Deliberately a transform rather than
 * a lookup table: the floors live in `config.py`, and a table here would render
 * a newly added one as nothing at all. The raw token is shown beside it so the
 * rubric stays greppable from what is on screen.
 */
function floorLabel(floor: string): string {
  return sentenceCase(floor.replace(/^FLOOR_/, '').replaceAll('_', ' ').toLowerCase())
}

/** The scorecard, already in rubric order - the composable sorts it. */
const dimensionRows = computed(() =>
  Object.entries(props.verdict?.dimensions ?? {}).map(([key, score]) => ({
    key,
    label: sentenceCase(key.replaceAll('_', ' ')),
    score: score as number,
    // Every ladder is 0-5. Clamped so a score outside that range - a newer
    // server, a wider ladder - cannot draw a bar past the end of its track.
    percent: `${Math.min(100, Math.max(0, ((score as number) / 5) * 100))}%`,
  })),
)

const hasVerdictDetail = computed(
  () => fatalFloors.value.length > 0 || decisionReason.value !== null || dimensionRows.value.length > 0,
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
          <span v-if="verdict" class="verdict-badge" :class="verdictTone">{{ verdict.verdict }}</span>
          <span v-else class="verdict-badge is-warn">COMPLETE</span>
          <span v-if="compositeScore" class="verdict-score">{{ compositeScore }}<small>/10</small></span>
          <span v-if="confidencePercent" class="verdict-confidence">{{ confidencePercent }} confidence</span>
          <span v-if="confidenceBand" class="verdict-band" :class="bandTone">{{ confidenceBand }}</span>
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

    <div v-if="provisional || thin.length" class="report-flags">
      <span v-if="provisional" class="report-flag is-provisional">PROVISIONAL</span>
      <span v-if="thin.length" class="report-flag">
        Thin evidence: {{ thin.join(', ') }}
      </span>
    </div>

    <div v-if="hasVerdictDetail" class="verdict-summary">
      <!-- Above the scorecard on purpose: a floor overrides the arithmetic, so
           reading the composite first and the floor afterwards gets the
           conclusion backwards. -->
      <section v-if="fatalFloors.length" class="verdict-floors" aria-labelledby="verdict-floors-title">
        <h3 id="verdict-floors-title">
          <OctagonAlert :size="13" aria-hidden="true" />
          <span>{{ fatalFloors.length === 1 ? 'Fatal floor' : 'Fatal floors' }}</span>
        </h3>
        <p>
          A floor overrides the composite score outright. It, not the arithmetic, is why this run
          reads {{ verdict?.verdict ?? 'the way it does' }}.
        </p>
        <ul>
          <li v-for="floor in fatalFloors" :key="floor">
            <span class="floor-name">{{ floorLabel(floor) }}</span>
            <code>{{ floor }}</code>
          </li>
        </ul>
      </section>

      <p v-if="decisionReason" class="verdict-reason">{{ decisionReason }}</p>

      <section v-if="dimensionRows.length" class="verdict-scorecard" aria-labelledby="verdict-scorecard-title">
        <h3 id="verdict-scorecard-title">
          <Gauge :size="13" aria-hidden="true" />
          <span>Rubric dimensions</span>
        </h3>
        <div v-for="row in dimensionRows" :key="row.key" class="score-row">
          <span class="score-label">{{ row.label }}</span>
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
  -webkit-backdrop-filter: var(--blur-rail);
  backdrop-filter: var(--blur-rail);
  animation: report-rise var(--motion-medium) var(--ease-out);
}

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

.report-kicker { display: inline-flex; gap: 6px; align-items: center; color: var(--accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); }
.report-title-group h2 { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 8px 0 0; font-size: var(--fs-18); }

.verdict-badge {
  padding: 4px 10px;
  color: #101a18;
  font: 800 var(--fs-13)/1.3 var(--font-mono);
  border-radius: var(--r-sm);
  letter-spacing: 0.04em;
}
.verdict-badge.is-pass { background: var(--accent-mint); }
.verdict-badge.is-warn { background: var(--warn-text); }
.verdict-badge.is-fail { background: #ffb4b4; }
.verdict-confidence { color: var(--text-muted); font: 500 var(--fs-13)/1 var(--font-mono); }

.verdict-score { color: var(--text-title); font: 700 var(--fs-18)/1 var(--font-display); }
.verdict-score small { color: var(--text-40); font: 500 var(--fs-12)/1 var(--font-mono); }

.verdict-band {
  padding: 3px 7px;
  color: var(--text-muted);
  font: 700 var(--fs-11)/1.2 var(--font-mono);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
  letter-spacing: 0.05em;
}
/* `ConfidenceBand` is exactly HIGH / MODERATE / LOW (`schemas/validator.py:33`).
   Anything else keeps the neutral base style rather than vanishing. */
.verdict-band.is-high { color: var(--accent-mint); background: rgba(170, 255, 205, 0.1); border-color: rgba(170, 255, 205, 0.34); }
.verdict-band.is-moderate { color: var(--accent-cyan); background: rgba(153, 234, 249, 0.1); border-color: rgba(153, 234, 249, 0.32); }
.verdict-band.is-low { color: var(--warn-text); background: var(--warn-bg); border-color: var(--warn-border); }

.report-flags { display: flex; flex: 0 0 auto; flex-wrap: wrap; gap: 8px; padding: 10px 20px 0; }
.report-flag {
  padding: 4px 8px;
  color: var(--text-muted);
  font: 600 var(--fs-11)/1.4 var(--font-mono);
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-sm);
}
.report-flag.is-provisional { color: var(--warn-text); background: var(--warn-bg); border-color: var(--warn-border); }

/* Bounded so a long floor list can never squeeze the report body to nothing on
   a short viewport; it scrolls on its own instead. */
.verdict-summary {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  gap: 12px;
  max-height: 42vh;
  overflow: auto;
  padding: 12px 20px 0;
}

.verdict-floors {
  padding: 11px 13px;
  background: var(--err-bg);
  border: 1px solid var(--err-border);
  border-radius: var(--r-md);
}
.verdict-floors h3,
.verdict-scorecard h3 {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  margin: 0;
  font: 700 var(--fs-11)/1 var(--font-mono);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.verdict-floors h3 { color: var(--err-text); }
.verdict-floors p { margin: 7px 0 10px; color: var(--text-muted); font-size: var(--fs-12); line-height: 1.5; }
.verdict-floors ul { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; padding: 0; list-style: none; }
.verdict-floors li {
  display: inline-flex;
  gap: 8px;
  align-items: baseline;
  padding: 5px 9px;
  background: var(--surface-well);
  border: 1px solid var(--err-border);
  border-radius: var(--r-sm);
}
.floor-name { color: var(--text-title); font: 600 var(--fs-13)/1.2 var(--font-body); }
.verdict-floors code { color: var(--err-text); font: 500 var(--fs-11)/1.2 var(--font-mono); }

.verdict-reason { margin: 0; color: var(--text-muted); font-size: var(--fs-13); line-height: 1.55; }

.verdict-scorecard {
  display: grid;
  gap: 7px;
  padding: 11px 13px;
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
}
.verdict-scorecard h3 { margin-bottom: 3px; color: var(--accent-cyan); }
.score-row { display: grid; grid-template-columns: minmax(90px, 132px) minmax(48px, 1fr) auto; gap: 10px; align-items: center; }
.score-label { color: var(--text-muted); font: 500 var(--fs-12)/1.3 var(--font-mono); }
.score-track { height: 6px; overflow: hidden; background: rgba(255, 255, 255, 0.08); border-radius: var(--r-pill); }
.score-fill {
  display: block;
  height: 100%;
  background: var(--gradient-brand);
  border-radius: var(--r-pill);
  transition: width var(--motion-medium) var(--ease-out);
}
.score-value { color: var(--text-primary); font: 700 var(--fs-13)/1 var(--font-mono); }
.score-value small { color: var(--text-40); font-weight: 500; }

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
  scrollbar-color: rgba(153, 234, 249, 0.3) transparent;
}

.report-sources { flex: 0 0 auto; max-height: 26%; overflow: auto; padding: 12px 20px 18px; border-top: 1px solid var(--border-default); }
.report-sources h3 { margin: 0 0 8px; color: var(--accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); text-transform: uppercase; }
.report-sources ol { margin: 0; padding-left: 20px; color: var(--text-muted); font-size: var(--fs-12); }
.report-sources li { margin-bottom: 4px; overflow-wrap: anywhere; }
.report-sources a { color: var(--link-cyan); }

@media (prefers-reduced-motion: reduce) {
  .report-panel { animation: none; }
  .score-fill { transition: none; }
}
</style>
