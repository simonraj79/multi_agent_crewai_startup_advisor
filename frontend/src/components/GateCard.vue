<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { AlertTriangle, Check, Clock3, Lock, RefreshCw, ShieldCheck } from 'lucide-vue-next'
import type { GateDerivedField, PendingGate } from '../types/studio'
import { describeValue, verdictLabel } from '../data/verdictDisplay'
import { humaniseCode } from '../utils/humanise'

const props = defineProps<{
  gate: PendingGate
  submitting: boolean
}>()

const emit = defineEmits<{
  submit: [outcome: string, fields?: Record<string, string>]
}>()

/**
 * Mirrors `GATE_NOTE_FIELD` in `src/brief_crew/service/registry.py`. It is the
 * free-text lever a gate carries whatever flow declared it: on a send-back
 * reply the server lifts it to the payload's top level, where the paired
 * router reads it and hands it to whatever reruns the step. Prose, not a
 * value - so it gets a box, not a line.
 */
const NOTE_FIELD = 'feedback'

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

/**
 * Values the operator reads but cannot change.
 *
 * The server splits a gate's payload in two and this is the half an edit does
 * not reach: anything the flow recomputes from its own work on every pass, and
 * anything bound to what a tool actually returned. Offering one of those as an
 * input invites an edit that cannot land - the operator types a value, submits,
 * and watches the server's own answer come back instead.
 *
 * They are shown in full because they are the reason to approve or send back;
 * the lever for disagreeing with them is a send-back reply plus a note, which
 * returns the step to whatever produced it. The measured case that shaped all
 * of this was the idea validator's scoring gate, whose entire payload is
 * recomputed and discarded on every pass - but the rule is about gates, not
 * about that flow.
 */
const derived = computed(() => props.gate.derived ?? [])

/** `startup_idea` -> `Startup idea`; `evidence_counts` -> `Evidence counts`. */
function label(key: string): string {
  return humaniseCode(key) || key
}

/** The gate's own headline outcome, if it carries one, in words. */
const verdictWord = computed(() => verdictLabel(props.gate.verdict))

/**
 * One row of the read-only payload, decoded far enough to be read.
 *
 * This used to be dumped into a `<pre>` whole: an operator was asked to
 * approve or send back a decision presented to them as `FATAL FLOORS / []`,
 * `DECISION REASON / null` and `NEEDS_WORK`. Every one of those has an English
 * answer, and none of them needed a new concept to produce it - `describeValue`
 * in `data/verdictDisplay.ts` humanises whatever it is handed and falls through
 * to the general humaniser for a code it has never seen, so a gate from a flow
 * written next week decodes without an edit here.
 *
 * The decoding stops at one level, deliberately. The worked example was a
 * scoring gate's `{score, anchor_matched, evidence_urls, evidence_thin}`, which
 * flattens into four readable pairs; anything nested deeper than that is a
 * structure, not a sentence, and structures go behind a collapsed `<details>`
 * where a developer can still read them and an operator is not made to.
 */
interface DerivedPair {
  label: string
  value: string
}

interface DerivedRow {
  key: string
  label: string
  /** A single value, a list of values, or a one-level key/value list. */
  shape: 'value' | 'list' | 'pairs'
  value: string
  items: string[]
  pairs: DerivedPair[]
  /** Pretty JSON for the disclosure, or `null` when nothing is hidden. */
  raw: string | null
}

/** A value this card can render inline: not an object, not a nested array. */
function isFlat(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (Array.isArray(value)) return value.every((entry) => entry === null || typeof entry !== 'object')
  return typeof value !== 'object'
}

function decodeRow(item: GateDerivedField): DerivedRow {
  const row: DerivedRow = {
    key: item.key,
    label: label(item.key),
    shape: 'value',
    value: '—',
    items: [],
    pairs: [],
    raw: null,
  }
  if (item.kind !== 'json') {
    row.value = describeValue(item.value)
    return row
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(item.value)
  } catch {
    // A `json` value the server could not have produced. Show it as it came
    // rather than swallowing it: a multi-line blob goes behind the
    // disclosure, a single line is just a value.
    if (item.value.includes('\n')) {
      row.value = 'see below'
      row.raw = item.value
    } else {
      row.value = describeValue(item.value)
    }
    return row
  }

  if (parsed === null || parsed === undefined) return row

  if (Array.isArray(parsed)) {
    if (parsed.length === 0) {
      row.value = 'none'
      return row
    }
    if (parsed.every((entry) => entry === null || typeof entry !== 'object')) {
      row.shape = 'list'
      row.items = parsed.map((entry) => describeValue(entry))
      return row
    }
    row.value = `${parsed.length} ${parsed.length === 1 ? 'entry' : 'entries'}`
    row.raw = item.value
    return row
  }

  if (typeof parsed === 'object') {
    const entries = Object.entries(parsed as Record<string, unknown>)
    if (entries.length === 0) {
      row.value = 'none'
      return row
    }
    row.shape = 'pairs'
    row.pairs = entries
      .filter(([, value]) => isFlat(value))
      .map(([key, value]) => ({ label: label(key), value: describeValue(value) }))
    // Anything this card refused to flatten is still available, collapsed.
    if (entries.some(([, value]) => !isFlat(value))) row.raw = item.value
    if (row.pairs.length === 0) {
      row.shape = 'value'
      row.value = 'see below'
    }
    return row
  }

  row.value = describeValue(parsed)
  return row
}

const derivedRows = computed<DerivedRow[]>(() => derived.value.map(decodeRow))
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

    <div v-if="verdictWord" class="verdict-row">
      <strong :data-code="gate.verdict">{{ verdictWord }}</strong>
      <span>{{ confidence }}</span>
    </div>

    <p v-if="expired" class="gate-late" role="status">
      <AlertTriangle :size="14" aria-hidden="true" />
      <span>
        This gate passed its deadline {{ overdue }} ago<template v-if="alerting"> and is now flagged for review</template>.
        The run has not failed — it is still waiting on you. Your answer will be sent and recorded as late.
      </span>
    </p>

    <!-- Read-only, and never rendered as an input. Placed above the form so the
         operator reads what the run computed before deciding, and so no control
         here can be mistaken for something their edit would reach. -->
    <section v-if="derived.length" class="gate-derived" aria-labelledby="gate-derived-title">
      <h3 id="gate-derived-title">
        <Lock :size="12" aria-hidden="true" />
        <span>Computed by the run</span>
      </h3>
      <p class="gate-derived-note">
        Recomputed by the server from what produced it; edit the inputs above and it is recomputed.
      </p>
      <dl>
        <template v-for="row in derivedRows" :key="row.key">
          <dt :data-key="row.key">{{ row.label }}</dt>
          <dd>
            <ul v-if="row.shape === 'list'" class="derived-list">
              <li v-for="(entry, index) in row.items" :key="index">{{ entry }}</li>
            </ul>
            <ul v-else-if="row.shape === 'pairs'" class="derived-pairs">
              <li v-for="pair in row.pairs" :key="pair.label">
                <span class="derived-pair-key">{{ pair.label }}</span>
                <span class="derived-pair-value">{{ pair.value }}</span>
              </li>
            </ul>
            <span v-else>{{ row.value }}</span>
            <!-- Anything the card refused to flatten. Collapsed, so the
                 operator is not made to read a structure, and present, so a
                 developer never loses one. -->
            <details v-if="row.raw" class="derived-raw">
              <summary>Show the raw value</summary>
              <pre>{{ row.raw }}</pre>
            </details>
          </dd>
        </template>
      </dl>
    </section>

    <form @submit.prevent>
      <label v-for="(_, key) in fields" :key="key" class="gate-field">
        <span>{{ label(String(key)) }}</span>
        <textarea
          v-if="key === NOTE_FIELD"
          v-model="fields[key]"
          rows="3"
          :readonly="!gate.editable"
          placeholder="What should be reconsidered? Sent with your reply."
        />
        <input v-else v-model="fields[key]" :readonly="!gate.editable" autocomplete="off" />
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
.gate-card { padding: var(--space-6); background: var(--warn-bg); border-bottom: 1px solid var(--warn-border-strong); }
.gate-heading { display: flex; align-items: center; gap: 10px; }
.gate-icon { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; color: var(--warn-text-strong); background: var(--warn-bg); border: 1px solid var(--warn-border-strong); border-radius: var(--r-md); }
.section-kicker { color: var(--warn-text-strong); font: 700 var(--fs-11)/1 var(--font-mono); }
.gate-heading h2 { margin: 3px 0 0; font-size: 16px; }
.gate-card > p { margin: 12px 0; color: var(--text-muted); font-size: var(--fs-12); line-height: 1.5; }
.verdict-row { display: flex; align-items: center; justify-content: space-between; margin: 12px 0; padding: 9px 10px; background: var(--surface-well); border-left: 2px solid var(--warn-text); }
.verdict-row strong { color: var(--warn-text-strong); font: 700 var(--fs-13)/1 var(--font-mono); }
.verdict-row span { color: var(--text-muted); font: 500 var(--fs-11)/1 var(--font-mono); }
.gate-late { display: flex; gap: 8px; margin: 12px 0 0; padding: 9px 10px; color: var(--warn-text-strong); background: var(--warn-bg); border: 1px solid var(--warn-border-strong); border-radius: var(--r-md); font-size: var(--fs-11); line-height: 1.5; }
.gate-late svg { flex: 0 0 auto; margin-top: 1px; }
.late-tag { margin-left: 6px; padding: 1px 5px; color: var(--warn-text-strong); background: var(--warn-bg); border: 1px solid var(--warn-border-strong); border-radius: 999px; font: 700 var(--fs-11)/1.4 var(--font-mono); text-transform: uppercase; }
.gate-field { display: block; margin-top: 9px; }
.gate-field span { display: block; margin-bottom: 5px; color: var(--text-meta); font: 700 var(--fs-11)/1 var(--font-mono); text-transform: uppercase; }
.gate-field input,
.gate-field textarea { width: 100%; min-height: 40px; padding: 8px 9px; color: var(--text-body); font: inherit; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); outline: 0; }
.gate-field textarea { min-height: 62px; resize: vertical; line-height: 1.45; }
.gate-field input:focus,
.gate-field textarea:focus { border-color: var(--on-accent-cyan); box-shadow: var(--glow-input); }
.gate-field input[readonly],
.gate-field textarea[readonly] { color: var(--text-muted); }

/* Deliberately not a form. Nothing here is an input, nothing here is focusable,
   and the lock in the heading says why before the operator reaches for it. */
.gate-derived { margin-top: 13px; padding: 10px 11px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.gate-derived h3 { display: flex; align-items: center; gap: 5px; margin: 0; color: var(--text-meta); font: 700 var(--fs-11)/1 var(--font-mono); text-transform: uppercase; }
.gate-derived-note { margin: 7px 0 10px; color: var(--text-muted); font-size: var(--fs-11); line-height: 1.5; }
.gate-derived dl { display: grid; grid-template-columns: minmax(0, 1fr); gap: 8px; margin: 0; }
/* Sentence case, not shouted: `text-transform: uppercase` over a humanised key
   produced MEDIAN MARKET SOURCE AGE MONTHS, which reads as a constant name
   even though it no longer is one. */
.gate-derived dt { color: var(--text-meta); font: 700 var(--fs-11)/1.3 var(--font-body); }
.gate-derived dd { margin: 3px 0 0; color: var(--text-body); font-size: var(--fs-12); line-height: 1.45; overflow-wrap: anywhere; }
.derived-list { margin: 0; padding-left: var(--space-6); }
.derived-list li { margin-bottom: 2px; }
.derived-pairs { display: grid; gap: 2px; margin: 0; padding: 0; list-style: none; }
.derived-pairs li { display: flex; gap: var(--space-3); align-items: baseline; justify-content: space-between; }
.derived-pair-key { color: var(--text-meta); font-size: var(--fs-11); }
.derived-pair-value { color: var(--text-body); text-align: right; }
.derived-raw { margin-top: var(--space-1); }
.derived-raw summary { color: var(--text-meta); font-size: var(--fs-11); cursor: pointer; }
.gate-derived pre { max-height: 140px; margin: var(--space-1) 0 0; padding: 7px 8px; overflow: auto; color: var(--text-muted); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-xs); font: 500 var(--fs-11)/1.5 var(--font-mono); }
/* The server decides how many options a gate has and in what order, so the row
   must not assume two with the primary second. */
.gate-actions { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 8px; margin-top: 13px; }
.gate-expiry { display: flex; align-items: center; gap: 6px; margin-top: 10px; color: var(--text-meta); font-size: var(--fs-11); }
.gate-expiry time { margin-left: auto; font-family: var(--font-mono); }
/* Amber, not red: a passed deadline is a notice, not a failure. */
.gate-expiry.is-expired { color: var(--warn-text-strong); }
</style>