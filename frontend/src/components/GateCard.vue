<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { Check, Clock3, RefreshCw, ShieldCheck } from 'lucide-vue-next'
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
const expired = computed(() => expiryTime.value > 0 && expiryTime.value <= now.value)
const countdown = computed(() => {
  if (!expiryTime.value) return ''
  const seconds = Math.max(0, Math.ceil((expiryTime.value - now.value) / 1000))
  if (seconds === 0) return 'Expired'
  const minutes = Math.floor(seconds / 60)
  return `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')} remaining`
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
  if (expired.value || props.submitting) return
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

    <form @submit.prevent>
      <label v-for="(_, key) in fields" :key="key" class="gate-field">
        <span>{{ String(key).replace('_', ' ') }}</span>
        <input v-model="fields[key]" :readonly="!gate.editable" :disabled="expired" autocomplete="off" />
      </label>

      <div class="gate-actions">
        <button
          v-for="option in gate.options"
          :key="option.id"
          type="button"
          class="button"
          :class="option.emphasis === 'primary' ? 'button-primary' : 'button-secondary'"
          :disabled="submitting || expired"
          @click="submit(option.id)"
        >
          <RefreshCw v-if="option.emphasis === 'danger'" :size="15" aria-hidden="true" />
          <Check v-else :size="15" aria-hidden="true" />
          {{ option.label }}
        </button>
      </div>
    </form>

    <div v-if="gate.expiresAt" class="gate-expiry" :class="{ 'is-expired': expired }">
      <Clock3 :size="13" aria-hidden="true" />
      <span v-if="expired" role="alert">Gate expired</span>
      <span v-else>{{ countdown }}</span>
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
.gate-field { display: block; margin-top: 9px; }
.gate-field span { display: block; margin-bottom: 5px; color: var(--text-40); font: 700 var(--fs-11)/1 var(--font-mono); text-transform: uppercase; }
.gate-field input { width: 100%; min-height: 40px; padding: 8px 9px; color: var(--text-body); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); outline: 0; }
.gate-field input:focus { border-color: var(--accent-cyan); box-shadow: var(--glow-input); }
.gate-field input[readonly] { color: var(--text-muted); }
.gate-actions { display: grid; grid-template-columns: 1fr 1.2fr; gap: 8px; margin-top: 13px; }
.gate-expiry { display: flex; align-items: center; gap: 6px; margin-top: 10px; color: var(--text-40); font-size: var(--fs-11); }
.gate-expiry time { margin-left: auto; font-family: var(--font-mono); }
.gate-expiry.is-expired { color: var(--err-text); }
</style>