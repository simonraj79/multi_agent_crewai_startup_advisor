<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Bot, ChevronLeft, ChevronRight, Cpu, Wrench } from 'lucide-vue-next'
import type { ChatEntry } from '../types/studio'

const props = defineProps<{
  entries: ChatEntry[]
  collapsed: boolean
}>()

const emit = defineEmits<{ toggle: [] }>()
const list = ref<HTMLElement | null>(null)
const expanded = ref(new Set<string>())
const now = ref(Date.now())
let timer = 0

watch(
  () => props.entries.length,
  async () => {
    if (props.collapsed) return
    await nextTick()
    list.value?.scrollTo({ top: list.value.scrollHeight, behavior: 'smooth' })
  },
)

watch(
  () => props.entries.some((entry) => entry.calls.some((call) => call.active)),
  (hasActiveCall) => {
    window.clearInterval(timer)
    if (hasActiveCall) timer = window.setInterval(() => { now.value = Date.now() }, 100)
  },
  { immediate: true },
)

onBeforeUnmount(() => window.clearInterval(timer))

function toggleEntry(id: string): void {
  const next = new Set(expanded.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expanded.value = next
}

function callDuration(startedAt: number, durationMs?: number): string {
  const elapsedMs = durationMs ?? Math.max(0, now.value - startedAt)
  return `${(elapsedMs / 1000).toFixed(1)}s`
}
</script>

<template>
  <aside class="chat-rail" :class="{ 'is-collapsed': collapsed }" aria-label="Run activity">
    <div class="rail-header">
      <div>
        <span class="section-kicker">LIVE ACTIVITY</span>
        <h2>Agent trace</h2>
      </div>
      <span class="entry-count" aria-live="polite">{{ entries.length }}</span>
    </div>

    <button
      class="rail-toggle icon-button"
      type="button"
      :aria-label="collapsed ? 'Expand activity rail' : 'Collapse activity rail'"
      :aria-expanded="!collapsed"
      :title="collapsed ? 'Expand activity' : 'Collapse activity'"
      @click="emit('toggle')"
    >
      <ChevronRight v-if="collapsed" :size="17" aria-hidden="true" />
      <ChevronLeft v-else :size="17" aria-hidden="true" />
    </button>

    <div
      v-show="!collapsed"
      ref="list"
      class="rail-list"
      tabindex="0"
      role="log"
      aria-live="polite"
      aria-relevant="additions text"
      aria-label="Run activity log"
    >
      <div v-if="entries.length === 0" class="rail-empty">
        <Bot :size="20" aria-hidden="true" />
        <span>Run activity will appear here.</span>
      </div>

      <article
        v-for="entry in entries"
        :key="entry.id"
        class="trace-entry"
        :class="[`is-${entry.variant}`, { 'is-system': entry.variant !== 'agent' }]"
      >
        <div v-if="entry.variant === 'agent'" class="trace-avatar" aria-hidden="true">
          {{ entry.actor.slice(0, 2).toUpperCase() }}
        </div>
        <div class="trace-content">
          <div class="trace-meta">
            <strong>{{ entry.actor }}</strong>
            <time :datetime="entry.timestamp">{{ entry.timestamp }}</time>
          </div>
          <div class="trace-bubble">
            <p :class="{ 'is-clamped': entry.message.length > 180 && !expanded.has(entry.id) }">
              {{ entry.message }}
            </p>
            <button
              v-if="entry.message.length > 180"
              class="text-button"
              type="button"
              :aria-expanded="expanded.has(entry.id)"
              @click="toggleEntry(entry.id)"
            >
              {{ expanded.has(entry.id) ? 'Show less' : 'Show more' }}
            </button>
            <div v-if="entry.calls.length" class="call-list">
              <span v-for="call in entry.calls" :key="call.id" class="call-chip" :class="{ 'is-active': call.active }">
                <Wrench v-if="call.kind === 'tool'" :size="12" aria-hidden="true" />
                <Cpu v-else :size="12" aria-hidden="true" />
                {{ call.label }}
                <span>{{ callDuration(call.startedAt, call.durationMs) }}</span>
              </span>
            </div>
          </div>
        </div>
      </article>
    </div>
  </aside>
</template>

<style scoped>
.chat-rail {
  position: relative;
  z-index: var(--z-rail);
  display: flex;
  min-width: 0;
  height: 100%;
  flex-direction: column;
  overflow: visible;
  background: var(--surface-overlay);
  border-right: 1px solid var(--border-default);
  backdrop-filter: var(--blur-rail);
  transition: width var(--motion-medium) var(--ease-out), min-width var(--motion-medium) var(--ease-out);
}

.chat-rail.is-collapsed { width: 0; min-width: 0; border-right: 0; }

.rail-header {
  display: flex;
  min-height: 64px;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  border-bottom: 1px solid var(--border-default);
}

.rail-header h2 { margin: 2px 0 0; font-size: 16px; }
.section-kicker { color: var(--accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); }
.entry-count { min-width: 24px; padding: 3px 6px; color: var(--text-muted); text-align: center; font: 600 var(--fs-11)/1 var(--font-mono); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-sm); }

.rail-toggle {
  position: absolute;
  top: 13px;
  right: -32px;
  width: 32px;
  height: 38px;
  border-left: 0;
  border-radius: 0 var(--r-lg) var(--r-lg) 0;
}

.rail-list {
  min-height: 0;
  flex: 1;
  overflow: auto;
  padding: 14px 14px 28px;
  scrollbar-color: rgba(153, 234, 249, 0.3) transparent;
}

.rail-empty { display: flex; min-height: 180px; align-items: center; justify-content: center; gap: 8px; color: var(--text-muted); font-size: var(--fs-13); }

.trace-entry { display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 9px; margin-bottom: 13px; }
.trace-entry.is-system { display: block; }
.trace-avatar { display: grid; width: 34px; height: 34px; place-items: center; color: #101a18; font: 800 10px/1 var(--font-mono); background: var(--gradient-brand); border-radius: 50%; }
.trace-content { min-width: 0; }
.trace-meta { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin: 0 2px 5px; }
.trace-meta strong { overflow: hidden; color: var(--text-40); font-size: var(--fs-11); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.trace-meta time { flex: 0 0 auto; color: var(--text-40); font: 400 10px/1 var(--font-mono); }

.trace-bubble { padding: 10px 11px; color: var(--text-body); font-size: var(--fs-12); line-height: 1.5; background: var(--surface-raised); border: 1px solid var(--border-default); border-radius: 2px var(--r-2xl) var(--r-2xl) var(--r-2xl); }
.is-system .trace-bubble { border-radius: var(--r-lg); background: var(--surface-well); }
.is-warning .trace-bubble { color: var(--warn-text); background: var(--warn-bg); border-color: var(--warn-border); }
.is-error .trace-bubble { color: var(--err-text); background: var(--err-bg); border-color: var(--err-border); }
.trace-bubble p { margin: 0; overflow-wrap: anywhere; }
.trace-bubble p.is-clamped { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 4; mask-image: linear-gradient(to bottom, #000 calc(100% - 26px), transparent); }

.text-button { margin-top: 7px; padding: 0; color: var(--link-cyan); background: none; border: 0; font: 600 var(--fs-11)/1.3 var(--font-body); cursor: pointer; }
.call-list { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
.call-chip { display: inline-flex; align-items: center; gap: 4px; max-width: 100%; padding: 4px 6px; color: var(--text-muted); font: 500 10px/1.2 var(--font-mono); background: rgba(0, 0, 0, 0.2); border: 1px solid var(--border-default); border-radius: var(--r-sm); }
.call-chip.is-active { color: var(--accent-cyan); border-color: rgba(153, 234, 249, 0.35); animation: chip-pulse 1.4s ease-in-out infinite; }

@keyframes chip-pulse { 50% { opacity: 0.55; } }

@media (prefers-reduced-motion: reduce) {
  .chat-rail,
  .call-chip.is-active { transition: none; animation: none; }
}
</style>