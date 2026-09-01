<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Activity,
  Download,
  FastForward,
  GitBranch,
  Play,
  UserCheck,
  RotateCcw,
  Square,
  LoaderCircle,
  X,
} from 'lucide-vue-next'
import type { ConnectionStatus, GatesMode, LogFormat, TransportMode } from '../services/studioApi'
import type { RunStatus, UsageMetrics } from '../types/studio'
import { IDEA_CHARS_WARN_AT, MAX_IDEA_CHARS, MIN_IDEA_CHARS } from '../data/serverLimits'

const props = defineProps<{
  status: RunStatus
  transportMode: TransportMode
  connection: ConnectionStatus
  runId: string
  idea: string
  usage: UsageMetrics
  lastSequence: number
  droppedFrames: number
  canLaunch: boolean
  isActive: boolean
  primaryLabel: string
  activeView: 'graph' | 'activity'
  gatesMode: GatesMode
  error: string
  downloadStatus: 'idle' | 'pending' | 'success' | 'error'
  downloadMessage: string
}>()

const emit = defineEmits<{
  'update:idea': [value: string]
  launch: []
  cancel: []
  download: [format: LogFormat]
  dismissError: []
  selectView: [value: 'graph' | 'activity']
  'update:gatesMode': [value: GatesMode]
}>()

/**
 * What the character counter says.
 *
 * Three states, in the order the operator meets them: too short to launch,
 * comfortably inside the bound, and close enough to the ceiling that the
 * `maxlength` attribute is about to start silently discarding keystrokes -
 * which is the one thing a hard cap does that needs warning about.
 */
const ideaLength = computed(() => props.idea.length)
const ideaRemaining = computed(() => MAX_IDEA_CHARS - ideaLength.value)
const ideaNearLimit = computed(() => ideaRemaining.value <= IDEA_CHARS_WARN_AT)
const ideaHint = computed(() => {
  const trimmed = props.idea.trim().length
  if (trimmed > 0 && trimmed < MIN_IDEA_CHARS) {
    return `${MIN_IDEA_CHARS - trimmed} more characters to launch`
  }
  if (ideaNearLimit.value) {
    return ideaRemaining.value === 0
      ? `${MAX_IDEA_CHARS} character limit reached`
      : `${ideaRemaining.value} characters left of ${MAX_IDEA_CHARS}`
  }
  return `${ideaLength.value} / ${MAX_IDEA_CHARS} characters`
})

const statusLabel = computed(() => props.status === 'stopping' ? 'Stopping…' : props.status.replace('_', ' '))
const connectionLabel = computed(() => props.transportMode === 'mock' ? 'Mock stream' : props.connection)
const elapsed = computed(() => {
  const totalSeconds = Math.floor(props.usage.elapsedMs / 1000)
  return `${String(Math.floor(totalSeconds / 60)).padStart(2, '0')}:${String(totalSeconds % 60).padStart(2, '0')}`
})
const tokens = computed(() => new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(props.usage.totalTokens))

// The service serves the same run log as NDJSON or as a ZIP; a long run is a
// much smaller download as the archive, so the operator picks.
const logFormat = ref<LogFormat>('ndjson')
</script>

<template>
  <section class="status-panel" aria-label="Run controls">
    <div v-if="error" class="error-banner" role="alert">
      <span>{{ error }}</span>
      <button class="icon-button" type="button" aria-label="Dismiss error" title="Dismiss" @click="emit('dismissError')">
        <X :size="15" aria-hidden="true" />
      </button>
    </div>

    <div class="control-section">
      <label for="idea" class="control-label">IDEA TO VALIDATE</label>
      <textarea
        id="idea"
        :value="idea"
        rows="4"
        :maxlength="MAX_IDEA_CHARS"
        :disabled="isActive"
        aria-describedby="idea-hint"
        @input="emit('update:idea', ($event.target as HTMLTextAreaElement).value)"
        @keydown.ctrl.enter.prevent="emit('launch')"
      />
      <!--
        The counter now states the bound rather than only the position. It used
        to read "2401 characters" in a calm grey right up to a Launch that
        answered 422, because nothing on the client knew a limit existed.

        It also explains the disabled button below the minimum. An operator who
        has typed six characters and sees a dead Launch has no way to learn why.
      -->
      <span id="idea-hint" class="field-meta" :class="{ 'is-warn': ideaNearLimit }">
        {{ ideaHint }}
      </span>
    </div>

    <div class="control-section compact-section">
      <span class="control-label">WORKFLOW</span>
      <div class="read-only-well">
        <GitBranch :size="15" aria-hidden="true" />
        <span>Idea Validator</span>
        <span class="version">M2</span>
      </div>
    </div>

    <div class="control-section compact-section">
      <span class="control-label">GATES</span>
      <div class="segmented" role="group" aria-label="Who answers the gates">
        <button
          type="button"
          :aria-pressed="gatesMode === 'human'"
          :disabled="isActive"
          @click="emit('update:gatesMode', 'human')"
        >
          <UserCheck :size="14" aria-hidden="true" /> Review
        </button>
        <button
          type="button"
          :aria-pressed="gatesMode === 'auto'"
          :disabled="isActive"
          @click="emit('update:gatesMode', 'auto')"
        >
          <FastForward :size="14" aria-hidden="true" /> Unattended
        </button>
      </div>
      <p class="control-hint">
        <template v-if="gatesMode === 'human'">
          Pauses for you at the scope and verdict gates.
        </template>
        <template v-else>
          Runs the whole pipeline without stopping. Costs more, and the
          deployment must allow it.
        </template>
      </p>
    </div>

    <div class="control-section compact-section">
      <span class="control-label">VIEW</span>
      <div class="segmented" role="group" aria-label="Workspace view">
        <button type="button" :aria-pressed="activeView === 'graph'" @click="emit('selectView', 'graph')">
          <GitBranch :size="14" aria-hidden="true" /> Graph
        </button>
        <button type="button" :aria-pressed="activeView === 'activity'" @click="emit('selectView', 'activity')">
          <Activity :size="14" aria-hidden="true" /> Activity
        </button>
      </div>
    </div>

    <div class="control-section metrics-section">
      <div class="status-line">
        <span class="control-label">STATUS</span>
        <span class="status-badge" :class="`is-${status}`"><i aria-hidden="true" />{{ statusLabel }}</span>
      </div>
      <dl class="metrics-grid">
        <div><dt>Elapsed</dt><dd>{{ elapsed }}</dd></div>
        <div><dt>Calls</dt><dd>{{ usage.callCount }}</dd></div>
        <div><dt>Tokens</dt><dd>{{ tokens }}</dd></div>
        <div><dt>Cost</dt><dd>${{ usage.costUsd.toFixed(4) }}</dd></div>
      </dl>
      <div class="stream-line">
        <span><i :class="`is-${connection}`" aria-hidden="true" />{{ connectionLabel }}</span>
        <span>seq {{ lastSequence }}</span>
        <span :class="{ 'has-drops': droppedFrames > 0 }">{{ droppedFrames }} dropped</span>
      </div>
      <code v-if="runId" class="run-id" :title="runId">{{ runId.slice(0, 8) }}</code>
    </div>

    <div class="control-actions">
      <button class="button button-primary" type="button" :disabled="!canLaunch" @click="emit('launch')">
        <RotateCcw v-if="primaryLabel === 'Relaunch'" :size="16" aria-hidden="true" />
        <Play v-else :size="16" aria-hidden="true" />
        {{ primaryLabel }}
      </button>
      <button class="button button-secondary" type="button" :disabled="!isActive || status === 'stopping'" @click="emit('cancel')">
        <Square :size="14" aria-hidden="true" />
        {{ status === 'stopping' ? 'Stopping…' : 'Cancel' }}
      </button>
      <div class="download-row">
        <button
          class="button button-quiet"
          type="button"
          :disabled="!runId || downloadStatus === 'pending'"
          @click="emit('download', logFormat)"
        >
          <LoaderCircle v-if="downloadStatus === 'pending'" class="download-spinner" :size="16" aria-hidden="true" />
          <Download v-else :size="16" aria-hidden="true" />
          {{ downloadStatus === 'pending' ? 'Preparing…' : 'Download logs' }}
        </button>
        <div class="segmented format-picker" role="group" aria-label="Log format">
          <button
            v-for="option in (['ndjson', 'zip'] as LogFormat[])"
            :key="option"
            type="button"
            :aria-pressed="logFormat === option"
            :title="option === 'zip' ? 'Download the run log as a ZIP archive' : 'Download the run log as newline-delimited JSON'"
            @click="logFormat = option"
          >
            {{ option.toUpperCase() }}
          </button>
        </div>
      </div>
      <p
        v-if="downloadMessage"
        class="download-feedback"
        :class="`is-${downloadStatus}`"
        :role="downloadStatus === 'error' ? 'alert' : 'status'"
      >
        {{ downloadMessage }}
      </p>
    </div>
  </section>
</template>

<style scoped>
.control-hint {
  margin: 7px 0 0;
  color: var(--text-muted);
  font-size: var(--fs-11);
  line-height: 1.45;
}
.segmented button:disabled { cursor: not-allowed; opacity: 0.5; }

.status-panel { min-width: 0; }
.control-section { padding: 16px; border-bottom: 1px solid var(--border-default); }
.compact-section { padding-block: 13px; }
.control-label { display: block; margin-bottom: 8px; color: var(--text-40); font: 700 var(--fs-11)/1 var(--font-mono); letter-spacing: 0.04em; }
textarea { display: block; width: 100%; min-height: 104px; resize: vertical; padding: 10px; color: var(--text-body); font: 400 var(--fs-13)/1.5 var(--font-body); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-lg); outline: 0; }
textarea:focus { border-color: var(--accent-cyan); box-shadow: var(--glow-input); }
textarea:disabled { cursor: not-allowed; opacity: 0.64; }
.field-meta { display: block; margin-top: 6px; color: var(--text-40); font: 500 10px/1 var(--font-mono); text-align: right; }
/* The counter only raises its voice near the ceiling, because `maxlength` is a
   hard stop: past it the browser discards keystrokes with no feedback at all,
   and a counter that looked identical at 1,900 and at 2,000 would be the only
   warning the operator ever got. */
.field-meta.is-warn { color: var(--warn-text); }
.read-only-well { display: flex; min-height: 40px; align-items: center; gap: 8px; padding: 0 10px; color: var(--text-body); font-size: var(--fs-13); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.read-only-well .version { margin-left: auto; color: var(--accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); }
.segmented { display: grid; grid-template-columns: 1fr 1fr; padding: 3px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-lg); }
.segmented button { display: inline-flex; min-height: 34px; align-items: center; justify-content: center; gap: 6px; color: var(--text-muted); background: transparent; border: 0; border-radius: var(--r-md); cursor: pointer; }
.segmented button[aria-pressed='true'] { color: var(--text-title); background: var(--surface-raised); box-shadow: inset 0 0 0 1px rgba(153, 234, 249, 0.2); }
.status-line { display: flex; align-items: center; justify-content: space-between; }
.status-line .control-label { margin: 0; }
.status-badge { display: inline-flex; align-items: center; gap: 6px; color: var(--text-muted); font: 600 var(--fs-11)/1 var(--font-mono); text-transform: capitalize; }
.status-badge i, .stream-line i { width: 7px; height: 7px; background: currentColor; border-radius: 50%; }
.status-badge.is-running, .status-badge.is-queued { color: var(--accent-cyan); }
.status-badge.is-waiting, .status-badge.is-stopping { color: var(--warn-text); }
.status-badge.is-completed { color: var(--accent-mint); }
.status-badge.is-error, .status-badge.is-cancelled { color: var(--err-text); }
.metrics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; margin: 13px 0 0; background: var(--border-default); border: 1px solid var(--border-default); border-radius: var(--r-md); overflow: hidden; }
.metrics-grid div { padding: 9px 10px; background: var(--surface-well); }
.metrics-grid dt { color: var(--text-40); font: 600 10px/1 var(--font-mono); text-transform: uppercase; }
.metrics-grid dd { margin: 5px 0 0; color: var(--text-title); font: 600 var(--fs-13)/1 var(--font-mono); font-variant-numeric: tabular-nums; }
.stream-line { display: flex; flex-wrap: wrap; gap: 8px 12px; margin-top: 10px; color: var(--text-40); font: 500 10px/1 var(--font-mono); }
.stream-line span { display: inline-flex; align-items: center; gap: 5px; }
.stream-line i.is-connected { color: var(--accent-mint); }
.stream-line i.is-connecting, .stream-line i.is-reconnecting { color: var(--warn-text); }
.stream-line .has-drops { color: var(--err-text); }
.run-id { display: inline-block; margin-top: 9px; padding: 3px 5px; color: var(--text-muted); background: var(--surface-well); border-radius: var(--r-sm); }
.control-actions { display: grid; gap: 8px; padding: 16px; }
.error-banner { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 12px; color: var(--err-text); font-size: var(--fs-12); background: var(--err-bg); border-bottom: 1px solid var(--err-border); }
.error-banner .icon-button { flex: 0 0 auto; }
.download-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
.format-picker { grid-template-columns: 1fr 1fr; }
.format-picker button { min-height: 34px; padding: 0 10px; font: 600 10px/1 var(--font-mono); }
.download-feedback { margin: 0; color: var(--text-muted); font-size: var(--fs-11); text-align: center; }
.download-feedback.is-success { color: var(--accent-mint); }
.download-feedback.is-error { color: var(--err-text); }
.download-spinner { animation: download-spin 0.8s linear infinite; }

@keyframes download-spin { to { transform: rotate(360deg); } }
</style>