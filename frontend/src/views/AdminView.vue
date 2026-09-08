<script setup lang="ts">
/**
 * `#/admin` — one screen, live sources, nothing copied.
 *
 * `.agent/plans/17-admin-console.md`, criteria 23–29. Five docked panels behind
 * a tab rail, a docked right drawer, and **no modal anywhere** (R15): every
 * detail view is a column beside the thing it is about, never a sheet over it.
 *
 * THIS FILE OWNS EVERY REQUEST, and the panels own none. Two reasons, and both
 * are about the one thing a dashboard must not do:
 *
 * 1. **One window, one meaning.** `from`/`to` decides every aggregate on the
 *    screen. A panel that fetched its own would eventually be asked over a
 *    different fortnight from the panel beside it, and the two would disagree
 *    with nobody able to say why.
 * 2. **A panel is mountable with a fixture.** `adminPanels.spec.ts` and
 *    `adminCharts.spec.ts` hand a panel data and assert what it draws, with no
 *    network at all — which is only possible while drawing and fetching are in
 *    different files.
 *
 * WHAT IS FETCHED WHEN. `links`, `summary`, `health` and `providers` on mount,
 * because Overview is the landing tab and Health's ceilings are read by Money.
 * Everything else lands the first time its tab is opened. Nothing on this
 * screen fetches a billed cost: that is one press in the drawer (criterion 26),
 * because it is an outbound call to Langfuse on the server's own thread.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { Activity, Coins, Gauge, HeartPulse, Users } from 'lucide-vue-next'
import AccountChip from '../components/builder/AccountChip.vue'
import BrandLockup from '../components/BrandLockup.vue'
import AdminDrawer from '../components/admin/AdminDrawer.vue'
import AdminHealthPanel from '../components/admin/AdminHealth.vue'
import AdminMoney from '../components/admin/AdminMoney.vue'
import AdminOverview from '../components/admin/AdminOverview.vue'
import AdminPeople from '../components/admin/AdminPeople.vue'
import AdminRuns from '../components/admin/AdminRuns.vue'
import { PRODUCT_NAME } from '../data/brand'
import { adminApi } from '../services/adminApi'
import type {
  AdminDecisions,
  AdminGateStats,
  AdminHealth,
  AdminLinks,
  AdminProviders,
  AdminRunRow,
  AdminRunsPage,
  AdminSpend,
  AdminSpendAxis,
  AdminSummary,
  AdminUserDetail,
  AdminUsersPage,
  AdminVerdicts,
  AdminWindow,
} from '../services/adminApi'
import type { SignedInUser } from '../composables/useAuthGate'

const props = defineProps<{
  /** The signed-in admin. `App.vue` has already proved they are one. */
  user: SignedInUser | null
}>()

const emit = defineEmits<{ home: []; signOut: [] }>()

/* ── the window ───────────────────────────────────────────────────────────── */

/**
 * How far back the screen is looking.
 *
 * `null` sends NO `from`/`to` at all and takes the server's own
 * `ADMIN_DEFAULT_WINDOW_DAYS`. That is the default here on purpose: a client
 * that opened with its own idea of "recently" would be a second copy of a
 * server constant, which is the drift this repository has recorded nine times
 * in one paragraph of CLAUDE.md.
 */
const windowDays = ref<number | null>(null)
const WINDOWS: ReadonlyArray<{ days: number | null; label: string }> = [
  { days: 7, label: '7 days' },
  { days: null, label: 'default' },
  { days: 90, label: '90 days' },
]

const activeWindow = computed<AdminWindow | undefined>(() => {
  const days = windowDays.value
  if (days === null) return undefined
  const from = new Date(Date.now() - days * 24 * 60 * 60 * 1000)
  return { from: from.toISOString() }
})

/* ── the tabs ─────────────────────────────────────────────────────────────── */

type TabId = 'overview' | 'money' | 'people' | 'runs' | 'health'

const TABS: ReadonlyArray<{ id: TabId; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'money', label: 'Money' },
  { id: 'people', label: 'People' },
  { id: 'runs', label: 'Runs & decisions' },
  { id: 'health', label: 'Health' },
]

const tab = ref<TabId>('overview')

/* ── the answers ──────────────────────────────────────────────────────────── */

const links = ref<AdminLinks | null>(null)
const summary = ref<AdminSummary | null>(null)
const health = ref<AdminHealth | null>(null)
const providers = ref<AdminProviders | null>(null)
const spend = ref<AdminSpend | null>(null)
const users = ref<AdminUsersPage | null>(null)
const runs = ref<AdminRunsPage | null>(null)
const gates = ref<AdminGateStats | null>(null)
const verdicts = ref<AdminVerdicts | null>(null)

const spendAxis = ref<AdminSpendAxis>('model')
const userSort = ref<'spend' | 'recent' | 'joined'>('spend')

/** Per-panel, so a Money failure never blanks Overview's numbers. */
const busy = ref<Record<TabId, boolean>>({
  overview: false,
  money: false,
  people: false,
  runs: false,
  health: false,
})
const problems = ref<Record<TabId, string>>({
  overview: '',
  money: '',
  people: '',
  runs: '',
  health: '',
})

function sentence(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

/**
 * Run a panel's reads, recording its own busy flag and its own refusal.
 *
 * `Promise.allSettled` rather than `all`: one dead endpoint must not blank the
 * three beside it, and a panel that showed nothing because its least important
 * request failed would be a dashboard that goes dark exactly when something is
 * wrong.
 */
async function load(id: TabId, work: Array<() => Promise<void>>, fallback: string): Promise<void> {
  busy.value = { ...busy.value, [id]: true }
  problems.value = { ...problems.value, [id]: '' }
  const answers = await Promise.allSettled(work.map((run) => run()))
  const failed = answers.find((answer) => answer.status === 'rejected')
  busy.value = { ...busy.value, [id]: false }
  if (failed && failed.status === 'rejected') {
    problems.value = { ...problems.value, [id]: sentence(failed.reason, fallback) }
  }
}

async function loadOverview(): Promise<void> {
  await load(
    'overview',
    [
      async () => {
        summary.value = await adminApi.summary(activeWindow.value)
      },
    ],
    'the summary could not be read.',
  )
}

async function loadHealth(): Promise<void> {
  await load(
    'health',
    [
      async () => {
        health.value = await adminApi.health()
      },
      async () => {
        providers.value = await adminApi.providers()
      },
    ],
    'the health read could not be answered.',
  )
}

async function loadMoney(): Promise<void> {
  await load(
    'money',
    [
      async () => {
        spend.value = await adminApi.spend(spendAxis.value, activeWindow.value)
      },
    ],
    'the spend grouping could not be read.',
  )
}

async function loadPeople(): Promise<void> {
  await load(
    'people',
    [
      async () => {
        users.value = await adminApi.users(userSort.value)
      },
    ],
    'the account list could not be read.',
  )
}

async function loadRuns(): Promise<void> {
  await load(
    'runs',
    [
      async () => {
        runs.value = await adminApi.runs(activeWindow.value)
      },
      async () => {
        gates.value = await adminApi.gates(activeWindow.value)
      },
      async () => {
        verdicts.value = await adminApi.verdicts(activeWindow.value)
      },
    ],
    'the run list could not be read.',
  )
}

/** Which tabs have asked for their data, so opening one twice is free. */
const visited = ref(new Set<TabId>(['overview', 'health']))

function openTab(id: TabId): void {
  tab.value = id
  if (visited.value.has(id)) return
  visited.value = new Set([...visited.value, id])
  if (id === 'money') void loadMoney()
  if (id === 'people') void loadPeople()
  if (id === 'runs') void loadRuns()
}

/** A new window invalidates every answer on the screen, not only the visible
 *  one - two panels reading different fortnights is the failure this avoids. */
watch(activeWindow, () => {
  visited.value = new Set<TabId>(['overview', 'health'])
  void loadOverview()
  void loadHealth()
  if (tab.value === 'money') {
    visited.value = new Set([...visited.value, 'money'])
    void loadMoney()
  }
  if (tab.value === 'people') {
    visited.value = new Set([...visited.value, 'people'])
    void loadPeople()
  }
  if (tab.value === 'runs') {
    visited.value = new Set([...visited.value, 'runs'])
    void loadRuns()
  }
})

watch(spendAxis, () => void loadMoney())
watch(userSort, () => void loadPeople())

/* ── the drawer ───────────────────────────────────────────────────────────── */

const drawerRun = ref<AdminRunRow | null>(null)
const drawerDecisions = ref<AdminDecisions | null>(null)
const drawerPerson = ref<AdminUserDetail | null>(null)
const drawerBusy = ref(false)
const drawerProblem = ref('')

function closeDrawer(): void {
  drawerRun.value = null
  drawerDecisions.value = null
  drawerPerson.value = null
  drawerProblem.value = ''
}

/**
 * Open one run. The row may not be on the current page - `attention` names a
 * run id and nothing else - so the list is consulted first and the run is
 * fetched by id when it is not there.
 */
async function openRun(runId: string): Promise<void> {
  closeDrawer()
  drawerBusy.value = true
  const known = runs.value?.rows.find((row) => row.run_id === runId) ?? null
  drawerRun.value = known
  try {
    if (!known) {
      const page = await adminApi.runs({ ...activeWindow.value, limit: 1, user_id: undefined })
      drawerRun.value =
        page.rows.find((row) => row.run_id === runId) ??
        ({ run_id: runId, user_id: null, email: null, workflow_id: '', status: 'unknown',
            created_at: '', cost_usd: 0 } as AdminRunRow)
    }
    drawerDecisions.value = await adminApi.decisions(runId)
  } catch (error) {
    drawerProblem.value = sentence(error, 'this run could not be read.')
  } finally {
    drawerBusy.value = false
  }
}

async function openPerson(userId: string): Promise<void> {
  closeDrawer()
  drawerBusy.value = true
  try {
    drawerPerson.value = await adminApi.user(userId)
  } catch (error) {
    drawerProblem.value = sentence(error, 'this account could not be read.')
  } finally {
    drawerBusy.value = false
  }
}

/** A cancelled run changes the run list and the summary, so both are re-read
 *  rather than patched: the server is the truth, and a lever that only edited
 *  the screen would be a lever that lies when it fails. */
function afterCancel(): void {
  void loadOverview()
  if (visited.value.has('runs')) void loadRuns()
}

onMounted(() => {
  // The tab's name follows the route (U4). `Admin` rather than a workflow,
  // because this screen is about all of them.
  document.title = `Admin · ${PRODUCT_NAME}`
  void load(
    'overview',
    [
      async () => {
        links.value = await adminApi.links()
      },
    ],
    'the link configuration could not be read.',
  )
  void loadOverview()
  void loadHealth()
})
</script>

<template>
  <a class="skip-link" href="#admin-panels">Skip to the admin panels</a>
  <div class="studio-shell is-admin">
    <header class="app-header">
      <BrandLockup as="link">
        <template #default>
          <h1 class="sr-only">Admin</h1>
        </template>
      </BrandLockup>

      <div class="header-context">
        <nav class="breadcrumb" aria-label="Breadcrumb">
          <a class="breadcrumb-crumb" href="#/" @click.prevent="emit('home')">Workflows</a>
          <span class="breadcrumb-sep" aria-hidden="true">/</span>
          <span class="breadcrumb-crumb is-current" aria-current="page">
            <Gauge :size="13" aria-hidden="true" />
            <span class="breadcrumb-name">Admin</span>
          </span>
        </nav>
        <AccountChip v-if="props.user" :user="props.user" @sign-out="emit('signOut')" />
      </div>
    </header>

    <main class="admin-main">
      <div class="admin-rail">
        <div class="admin-tabs" role="tablist" aria-label="Admin panels">
          <button
            v-for="entry in TABS"
            :key="entry.id"
            class="admin-tab"
            type="button"
            role="tab"
            :id="`admin-tab-${entry.id}`"
            :aria-selected="tab === entry.id"
            :aria-controls="`admin-panel-${entry.id}`"
            :class="{ 'is-active': tab === entry.id }"
            :data-testid="`admin-tab-${entry.id}`"
            @click="openTab(entry.id)"
          >
            <Gauge v-if="entry.id === 'overview'" :size="13" aria-hidden="true" />
            <Coins v-else-if="entry.id === 'money'" :size="13" aria-hidden="true" />
            <Users v-else-if="entry.id === 'people'" :size="13" aria-hidden="true" />
            <Activity v-else-if="entry.id === 'runs'" :size="13" aria-hidden="true" />
            <HeartPulse v-else :size="13" aria-hidden="true" />
            {{ entry.label }}
          </button>
        </div>

        <div class="admin-window" role="group" aria-label="Window">
          <button
            v-for="option in WINDOWS"
            :key="String(option.days)"
            class="admin-axis-button"
            type="button"
            :class="{ 'is-active': windowDays === option.days }"
            :aria-pressed="windowDays === option.days"
            :data-testid="`admin-window-${option.days ?? 'default'}`"
            @click="windowDays = option.days"
          >
            {{ option.label }}
          </button>
        </div>
      </div>

      <!--
        THE BODY IS A GRID, and the drawer is its second column (criterion 23).
        A docked drawer narrows the panel; a modal would cover the table the
        reader is comparing against, which is the competitor's defining failure
        and the reason R15 cuts modals out of every editing path here.
      -->
      <div class="admin-body" :class="{ 'has-drawer': drawerRun || drawerPerson }">
        <div id="admin-panels" class="admin-panels" tabindex="-1">
          <div
            v-for="entry in TABS"
            :key="entry.id"
            :id="`admin-panel-${entry.id}`"
            role="tabpanel"
            :aria-labelledby="`admin-tab-${entry.id}`"
            :hidden="tab !== entry.id"
          >
            <AdminOverview
              v-if="entry.id === 'overview'"
              :summary="summary"
              :loading="busy.overview"
              :problem="problems.overview"
              @open-run="openRun"
              @open-person="openPerson"
            />
            <AdminMoney
              v-else-if="entry.id === 'money'"
              :axis="spendAxis"
              :spend="spend"
              :health="health"
              :loading="busy.money"
              :problem="problems.money"
              @select-axis="spendAxis = $event"
            />
            <AdminPeople
              v-else-if="entry.id === 'people'"
              :page="users"
              :sort="userSort"
              :selected-id="drawerPerson?.user_id ?? null"
              :loading="busy.people"
              :problem="problems.people"
              @open-person="openPerson"
              @select-sort="userSort = $event"
            />
            <AdminRuns
              v-else-if="entry.id === 'runs'"
              :runs="runs"
              :gates="gates"
              :verdicts="verdicts"
              :links="links"
              :selected-run-id="drawerRun?.run_id ?? null"
              :loading="busy.runs"
              :problem="problems.runs"
              @open-run="openRun"
            />
            <AdminHealthPanel
              v-else
              :health="health"
              :providers="providers"
              :links="links"
              :loading="busy.health"
              :problem="problems.health"
            />
          </div>
        </div>

        <AdminDrawer
          :run="drawerRun"
          :decisions="drawerDecisions"
          :person="drawerPerson"
          :links="links"
          :loading="drawerBusy"
          :problem="drawerProblem"
          @close="closeDrawer"
          @cancelled="afterCancel"
        />
      </div>
    </main>
  </div>
</template>

<style src="../components/admin/admin.css"></style>
