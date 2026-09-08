<script setup lang="ts">
/**
 * Are we burning money faster than expected, is anyone here, and what must I
 * act on now.
 *
 * The first of the five docked panels (criterion 23). Four tiles, one series,
 * two lists - and the last list is the only part of this console that is not a
 * report: **each row of `Needs a decision` is a lever**, so it carries the
 * action beside the fact rather than sending the reader to find it.
 *
 * NOTHING HERE FETCHES. `AdminView` owns every request and hands the answers
 * down, so a panel can be mounted in a test with a fixture and no network at
 * all - and so the five panels cannot each invent their own window.
 */
import { computed } from 'vue'
import { Coins, TriangleAlert, Users, Activity } from 'lucide-vue-next'
import AdminBar from './AdminBar.vue'
import AdminColumns from './AdminColumns.vue'
import EstimateBand from './EstimateBand.vue'
import MoneyFigure from './MoneyFigure.vue'
import { count, dayLabel, humanise, money, personLabel } from './adminFormat'
import type { AdminAttentionRow, AdminSummary } from '../../services/adminApi'

const props = defineProps<{
  summary: AdminSummary | null
  loading: boolean
  problem: string
}>()

const emit = defineEmits<{
  openRun: [runId: string]
  openPerson: [userId: string]
}>()

const runs = computed(() => props.summary?.runs ?? null)

/** Every run in the window, whatever state it reached. */
const runTotal = computed(() => {
  const rows = runs.value
  if (!rows) return 0
  return (
    rows.completed +
    rows.failed +
    rows.cancelled +
    rows.cancelling +
    rows.waiting +
    rows.running +
    rows.queued
  )
})

const refusalTotal = computed(() => {
  const refusals = props.summary?.refusals
  return refusals ? refusals.account_cap + refusals.run_ceiling : 0
})

const days = computed(() =>
  (props.summary?.spend_by_day ?? []).map((day) => ({
    key: day.day,
    label: dayLabel(day.day),
    value: day.usd,
    display: money(day.usd),
  })),
)

/**
 * The accounts nearest their cap, drawn against the largest spend on the list
 * rather than against the cap.
 *
 * The cap is not one number - it is per account, and an exempt account has
 * none at all - so a bar over "the cap" would be a bar over a denominator that
 * changes row to row. The share is of the biggest row, which is what a reader
 * of a ranked list is actually comparing, and the cap is printed as words
 * beside it where it can say `exempt` truthfully.
 */
const accountPeak = computed(() =>
  (props.summary?.top_accounts ?? []).reduce((high, row) => Math.max(high, row.spent_usd), 0),
)

function capWords(row: { cap_usd: number | null; exempt: boolean }): string {
  if (row.exempt) return 'exempt'
  return row.cap_usd === null ? 'no cap' : `of ${money(row.cap_usd)}`
}

/**
 * One sentence for a row of `attention`, from the fields it happens to carry.
 *
 * An unrecognised `kind` still gets a sentence: its own words, spaced and
 * cased, plus whatever it named. Dropping it would be a silence on the one
 * tile whose entire job is to say what has not been dealt with.
 */
function attentionSentence(row: AdminAttentionRow): string {
  if (row.detail) return row.detail
  const who = row.email ?? (row.user_id ? personLabel(row.user_id, null) : '')
  const hours = row.hours === null || row.hours === undefined ? '' : `${Math.round(row.hours)}h`
  if (row.kind === 'gate_open_long') {
    return `a run${who ? ` for ${who}` : ''} has been waiting at a gate for ${hours || 'a while'}`
  }
  const parts = [humanise(row.kind)]
  if (who) parts.push(`· ${who}`)
  if (hours) parts.push(`· ${hours}`)
  return parts.join(' ')
}

function attentionTone(row: AdminAttentionRow): 'warn' | 'err' {
  return row.kind.includes('error') || row.kind.includes('fail') ? 'err' : 'warn'
}
</script>

<template>
  <section class="admin-panel" aria-labelledby="admin-overview-title">
    <h2 id="admin-overview-title" class="sr-only">Overview</h2>

    <p v-if="problem" class="admin-problem" role="alert">
      <TriangleAlert :size="14" aria-hidden="true" />{{ problem }}
    </p>
    <p v-else-if="loading" class="admin-loading" role="status">Reading the database…</p>

    <template v-if="summary">
      <ul class="admin-tiles">
        <li class="admin-tile">
          <span class="panel-kicker is-accent">
            <Coins :size="12" aria-hidden="true" /> SPEND · ESTIMATE
          </span>
          <MoneyFigure :value="summary.spend_usd_estimate" size="lead" :tag="false" />
          <span class="admin-tile-note">
            {{ count(runTotal) }} runs in this window
          </span>
        </li>
        <li class="admin-tile">
          <span class="panel-kicker">
            <Activity :size="12" aria-hidden="true" /> RUNS
          </span>
          <span class="admin-tile-figure">{{ count(runTotal) }}</span>
          <span class="admin-tile-note">
            {{ count(runs?.completed) }} finished ·
            {{ count(runs?.failed) }} failed ·
            {{ count(runs?.cancelled) }} cancelled
          </span>
        </li>
        <li class="admin-tile">
          <span class="panel-kicker">
            <Users :size="12" aria-hidden="true" /> PEOPLE ACTIVE
          </span>
          <span class="admin-tile-figure">
            {{ count(summary.people_active) }}
            <span class="admin-tile-of">of {{ count(summary.people_total) }}</span>
          </span>
          <span class="admin-tile-note">{{ count(summary.people_new) }} signed up in this window</span>
        </li>
        <li class="admin-tile" :class="{ 'is-warn': refusalTotal > 0 }">
          <span class="panel-kicker">
            <TriangleAlert :size="12" aria-hidden="true" /> REFUSALS
          </span>
          <span class="admin-tile-figure">{{ count(refusalTotal) }}</span>
          <span class="admin-tile-note">
            {{ count(summary.refusals.account_cap) }} account cap ·
            {{ count(summary.refusals.run_ceiling) }} run ceiling
          </span>
        </li>
      </ul>

      <!--
        The window may be truncated, and saying so is not optional: every
        aggregate is `.limit(ADMIN_MAX_SCAN_ROWS)` (§3), so a `truncated: true`
        total is a floor rather than a total, and a reader comparing it with
        last week would otherwise read a scan cap as a fall in spend.
      -->
      <p v-if="summary.truncated" class="admin-warning" role="status">
        This window hit the scan cap, so every total on this panel is a floor rather than a total.
      </p>

      <div class="admin-blocks">
        <section class="admin-block" aria-labelledby="admin-perday-title">
          <header class="admin-block-head">
            <h3 id="admin-perday-title">Spend per day</h3>
            <span class="panel-meta">estimate</span>
          </header>
          <AdminColumns :points="days" tone="money" unit="USD" />
          <EstimateBand :note="summary.error_note" />
        </section>

        <section class="admin-block" aria-labelledby="admin-accounts-title">
          <header class="admin-block-head">
            <h3 id="admin-accounts-title">Accounts nearest the cap</h3>
            <span class="panel-meta">lifetime · estimate</span>
          </header>
          <ul v-if="summary.top_accounts.length" class="admin-bars" data-testid="admin-top-accounts">
            <AdminBar
              v-for="row in summary.top_accounts"
              :key="row.user_id"
              :label="personLabel(row.user_id, row.email)"
              :value="row.spent_usd"
              :total="accountPeak"
              :display="money(row.spent_usd)"
              :hint="capWords(row)"
              tone="money"
            >
              <template #value>
                <button
                  class="admin-linkish"
                  type="button"
                  :data-testid="`admin-account-${row.user_id}`"
                  @click="emit('openPerson', row.user_id)"
                >
                  <MoneyFigure :value="row.spent_usd" :tag="false" />
                </button>
              </template>
            </AdminBar>
          </ul>
          <p v-else class="admin-empty">Nobody has spent anything in this window.</p>
        </section>
      </div>

      <section class="admin-block" aria-labelledby="admin-attention-title">
        <header class="admin-block-head">
          <h3 id="admin-attention-title">Needs a decision</h3>
          <span class="panel-meta">each row is a lever</span>
        </header>
        <ul v-if="summary.attention.length" class="admin-attention" data-testid="admin-attention">
          <li
            v-for="(row, index) in summary.attention"
            :key="`${row.kind}-${row.run_id ?? row.user_id ?? index}`"
            class="admin-attention-row"
            :class="`is-${attentionTone(row)}`"
          >
            <span class="admin-attention-kind">{{ humanise(row.kind) }}</span>
            <span class="admin-attention-said">{{ attentionSentence(row) }}</span>
            <button
              v-if="row.run_id"
              class="button button-quiet admin-attention-action"
              type="button"
              @click="emit('openRun', row.run_id)"
            >
              Open run
            </button>
            <button
              v-else-if="row.user_id"
              class="button button-quiet admin-attention-action"
              type="button"
              @click="emit('openPerson', row.user_id)"
            >
              Open person
            </button>
          </li>
        </ul>
        <p v-else class="admin-empty">Nothing is waiting on you.</p>
      </section>
    </template>
  </section>
</template>
