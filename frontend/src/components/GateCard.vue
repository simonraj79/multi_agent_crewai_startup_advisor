<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { AlertTriangle, Check, Clock3, RefreshCw, ShieldCheck } from 'lucide-vue-next'
import type { PendingGate } from '../types/studio'

const props = defineProps<{
  gate: PendingGate
  submitting: boolean
}>()

const emit = defineEmits<{
  submit: [outcome: string, fields?: Record<string, string>]
}>()

const fields = reactive<Record<string, string>>({})
const now = ref(Date.now())
let timer = 0

watch(
  () => props.gate,
  (gate) => {
    Object.keys(fields).forEach((key) => delete fields[key])
    Object.assign(fields, gate.fields ?? {})
  },
  { immediate: true },
)

const confidence = computed(() => props.gate.confidence == null ? '' : `${Math.round(props.gate.confidence * 100)}% confidence`)
const expiryTime = computed(() => props.gate.expiresAt ? Date.parse(props.gate.expiresAt) : 0)

// PRD F03. The server owns expiry: it resolves `expired` on every run-status
// read and pushes `gate_expired`/`gate_alert`. The ticking clock below is
// presentation only - it never decides, and it never gates the reply, because
// an expired gate still accepts one and still resumes the run.
const expired = computed(() => props.gate.expired === true)
const countdownEnded = computed(() => expiryTime.value > 0 && expiryTime.value <= now.value)
const pastDeadline = computed(() => expired.value || countdownEnded.value)
const alerting = computed(() => props.gate.alerting === true)

const countdown = computed(() => {
  if (!expiryTime.value) return ''
  const seconds = Math.max(0, Math.ceil((expiryTime.value - now.value) / 1000))
  if (seconds === 0) return 'Deadline passed'
  const minutes = Math.floor(seconds / 60)
  return `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')} remaining`
})

const overdue = computed(() => {
  const reported = props.gate.overdueSeconds
  const seconds = Number.isFinite(reported)
    ? Math.max(0, Math.round(reported as number))
    : expiryTime.value
      ? Math.max(0, Math.round((now.value - expiryTime.value) / 1000))
      : 0
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
})

const deadlineLabel = computed(() => {
  if (expired.value) return `Past deadline by ${overdue.value}`
  if (countdownEnded.value) return 'Deadline passed'
  return countdown.value
})

watch(
  () => props.gate.expiresAt,
  (expiresAt) => {
    window.clearInterval(timer)
    now.value = Date.now()
    if (expiresAt) timer = window.setInterval(() => { now.value = Date.now() }, 1000)
  },
  { immediate: true },
)
onBeforeUnmount(() => window.clearInterval(timer))

function submit(outcome: string): void {
  // Only an in-flight reply blocks a second one. Expiry never does: refusing
  // here is what locked an operator out of a run the server would finish.
  if (props.submitting) return
  emit('submit', outcome, props.gate.editable ? { ...fields } : undefined)
}
</script>

<template>
  <section class="gate-card" aria-labelledby="gate-title">
    <div class="gate-heading">
      <div class="gate-icon" aria-hidden="true"><ShieldCheck :size="18" /></div>
      <div>
        <span class="section-kicker">OPERATOR GATE</span>
        <h2 id="gate-title">{{ gate.title }}</h2>
      </div>
    </div>

    <p>{{ gate.summary }}</p>

    <div v-if="gate.verdict" class="verdict-row">
      <strong>{{ gate.verdict }}</strong>
      <span>{{ confidence }}</span>
    </div>

    <p v-if="expired" class="gate-late" role="status">
      <AlertTriangle :size="14" aria-hidden="true" />
      <span>
        This gate passed its deadline {{ overdue }} ago<template v-if="alerting"> and is now flagged for review</template>.
        The run has not failed — it is still waiting on you. Your answer will be sent and recorded as late.
      </span>
    </p>

    <form @submit.prevent>
      <label v-for="(_, key) in fields" :key="key" class="gate-field">
        <span>{{ String(key).replace('_', ' ') }}</span>
        <input v-model="fields[key]" :readonly="!gate.editable" autocomplete="off" />
      </label>

      <div class="gate-actions">
        <button
          v-for="option in gate.options"
          :key="option.id"
          type="button"
          class="button"
          :class="option.emphasis === 'primary' ? 'button-primary' : 'button-secondary'"
          :disabled="submitting"
          :title="expired ? `${option.label} — recorded as a late reply` : option.label"
          @click="submit(option.id)"
        >
          <!-- The live service sends `approve` with emphasis "primary" and
               `revise` with no emphasis at all, so keying the tick off the
               absence of "danger" put a tick on the revise button. -->
          <Check v-if="option.emphasis === 'primary'" :size="15" aria-hidden="true" />
          <RefreshCw v-else :size="15" aria-hidden="true" />
          {{ option.label }}<span v-if="expired" class="late-tag">late</span>
        </button>
      </div>
    </form>

    <div v-if="gate.expiresAt" class="gate-expiry" :class="{ 'is-expired': pastDeadline }">
      <Clock3 :size="13" aria-hidden="true" />
      <span>{{ deadlineLabel }}</span>
      <time :datetime="gate.expiresAt" :title="new Date(gate.expiresAt).toLocaleString()">
        {{ new Date(gate.expiresAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }}
      </time>
    </div>
  </section>
</template>

<style scoped>
.gate-card { padding: 16px; background: linear-gradient(145deg, rgba(255, 204, 0, 0.09), rgba(255, 255, 255, 0.025)); border-bottom: 1px solid var(--warn-border); }
.gate-heading { display: flex; align-items: center; gap: 10px; }
.gate-icon { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; color: var(--warn-text); background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: var(--r-md); }
.section-kicker { color: var(--warn-text); font: 700 var(--fs-11)/1 var(--font-mono); }
.gate-heading h2 { margin: 3px 0 0; font-size: 16px; }
.gate-card > p { margin: 12px 0; color: var(--text-muted); font-size: var(--fs-12); line-height: 1.5; }
.verdict-row { display: flex; align-items: center; justify-content: space-between; margin: 12px 0; padding: 9px 10px; background: var(--surface-well); border-left: 2px solid var(--warn-text); }
.verdict-row strong { color: var(--warn-text); font: 700 var(--fs-13)/1 var(--font-mono); }
.verdict-row span { color: var(--text-muted); font: 500 var(--fs-11)/1 var(--font-mono); }
.gate-late { display: flex; gap: 8px; margin: 12px 0 0; padding: 9px 10px; color: var(--warn-text); background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: var(--r-md); font-size: var(--fs-11); line-height: 1.5; }
.gate-late svg { flex: 0 0 auto; margin-top: 1px; }
.late-tag { margin-left: 6px; padding: 1px 5px; color: var(--warn-text); background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: 999px; font: 700 var(--fs-11)/1.4 var(--font-mono); text-transform: uppercase; }
.gate-field { display: block; margin-top: 9px; }
.gate-field span { display: block; margin-bottom: 5px; color: var(--text-40); font: 700 var(--fs-11)/1 var(--font-mono); text-transform: uppercase; }
.gate-field input { width: 100%; min-height: 40px; padding: 8px 9px; color: var(--text-body); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); outline: 0; }
.gate-field input:focus { border-color: var(--accent-cyan); box-shadow: var(--glow-input); }
.gate-field input[readonly] { color: var(--text-muted); }
/* The server decides how many options a gate has and in what order, so the row
   must not assume two with the primary second. */
.gate-actions { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 8px; margin-top: 13px; }
.gate-expiry { display: flex; align-items: center; gap: 6px; margin-top: 10px; color: var(--text-40); font-size: var(--fs-11); }
.gate-expiry time { margin-left: auto; font-family: var(--font-mono); }
/* Amber, not red: a passed deadline is a notice, not a failure. */
.gate-expiry.is-expired { color: var(--warn-text); }
</style>