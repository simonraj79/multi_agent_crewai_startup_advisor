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
 */
import { computed, nextTick, ref, watch } from 'vue'
import { Copy, Check, FileText, X } from 'lucide-vue-next'
import type { RunResult } from '../types/studio'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps<{
  report: RunResult | null
  verdict: { verdict: string; confidence: number | null } | null
  open: boolean
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const panel = ref<HTMLElement | null>(null)
const copied = ref(false)
let copyTimer = 0

const body = computed(() => renderMarkdown(props.report?.markdown_body ?? ''))
const sources = computed(() => props.report?.sources ?? [])
const thin = computed(() => props.report?.thin_dimensions ?? [])
const provisional = computed(() => props.report?.provisional === true)

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
          <span v-if="confidencePercent" class="verdict-confidence">{{ confidencePercent }} confidence</span>
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
.report-title-group h2 { display: flex; align-items: center; gap: 10px; margin: 8px 0 0; font-size: var(--fs-18); }

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
}
</style>
