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
import { Activity, Coins, Gauge, HeartPulse, Lightbulb, Sprout, Users } from 'lucide-vue-next'
import AccountChip from '../components/builder/AccountChip.vue'
import BrandLockup from '../components/BrandLockup.vue'
import AdminDrawer from '../components/admin/AdminDrawer.vue'
import AdminHealthPanel from '../components/admin/AdminHealth.vue'
import AdminImprove from '../components/admin/AdminImprove.vue'
import type { ImproveWorkflowOption } from '../components/admin/AdminImprove.vue'
import AdminInsights from '../components/admin/AdminInsights.vue'
import AdminMoney from '../components/admin/AdminMoney.vue'
import AdminOverview from '../components/admin/AdminOverview.vue'
import AdminPeople from '../components/admin/AdminPeople.vue'
import AdminRuns from '../components/admin/AdminRuns.vue'
import { PRODUCT_NAME } from '../data/brand'
import { adminApi, improveApi } from '../services/adminApi'
import type {
  AdminDecisions,
  AdminGateStats,
  AdminRatingFilter,
  AdminHealth,
  AdminInsights as AdminInsightsResponse,
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
  EvalsetRating,
  ImproveCompare,
  ImproveCompareAxis,
  ImproveDigestPage,
  ImproveHotspots,
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

type TabId = 'overview' | 'money' | 'people' | 'runs' | 'insights' | 'improve' | 'health'

const TABS: ReadonlyArray<{ id: TabId; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'money', label: 'Money' },
  { id: 'people', label: 'People' },
  { id: 'runs', label: 'Runs & decisions' },
  { id: 'insights', label: 'Insights' },
  // BESIDE Insights rather than at the end, because the two are one thought:
  // Insights says what went wrong on its own, and Improve is where somebody
  // does something about it and measures whether it worked. Health stays last;
  // it is the only tab that is about the service rather than about the work.
  { id: 'improve', label: 'Improve' },
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
const insights = ref<AdminInsightsResponse | null>(null)
const insightWorkflow = ref('')
const insightWorkflows = ref<Array<{ workflow_id: string; runs: number | null }>>([])
let insightGeneration = 0

const spendAxis = ref<AdminSpendAxis>('model')
const userSort = ref<'spend' | 'recent' | 'joined'>('spend')

/**
 * Which runs the table is showing, by what a person said about them.
 *
 * `''` sends no `rating` query at all rather than a word meaning "any", for
 * the reason the window above gives: the server decides what an absent filter
 * means, and a client spelling of it would be a second answer to one question.
 */
const runRating = ref<AdminRatingFilter>('')

/** Per-panel, so a Money failure never blanks Overview's numbers. */
const busy = ref<Record<TabId, boolean>>({
  overview: false,
  money: false,
  people: false,
  runs: false,
  insights: false,
  improve: false,
  health: false,
})
const problems = ref<Record<TabId, string>>({
  overview: '',
  money: '',
  people: '',
  runs: '',
  insights: '',
  improve: '',
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
        runs.value = await adminApi.runs({ ...activeWindow.value, rating: runRating.value })
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

async function loadInsights(): Promise<void> {
  const generation = ++insightGeneration
  busy.value = { ...busy.value, insights: true }
  problems.value = { ...problems.value, insights: '' }
  try {
    const answer = await adminApi.insights(activeWindow.value, insightWorkflow.value)
    if (generation !== insightGeneration || tab.value !== 'insights') return
    insights.value = answer
    const options = new Map(insightWorkflows.value.map((row) => [row.workflow_id, row]))
    for (const row of answer.workflows) options.set(row.workflow_id, row)
    insightWorkflows.value = [...options.values()]
  } catch (error) {
    if (generation !== insightGeneration || tab.value !== 'insights') return
    problems.value = { ...problems.value, insights: sentence(error, 'the governance insights could not be read.') }
  } finally {
    if (generation === insightGeneration) busy.value = { ...busy.value, insights: false }
  }
}

/* ── Improve - plan 21 ─────────────────────────────────────────────────────
 *
 * One read on the window (which workflows ran) and two on one workflow (where
 * it goes wrong, and the reviews already written). Compare and the review
 * itself happen on a press and never on a load.
 *
 * THE WORKFLOW LIST COMES FROM `spend(group_by=workflow)` RATHER THAN FROM A
 * NEW ENDPOINT. It is the one read that already answers "which workflows ran
 * in this window, and how much", it is behind the same `require_admin`, and it
 * is stored in its OWN ref so it can never fight the Money panel's `spendAxis`.
 *
 * THE MODEL AXIS'S PICKERS DO NOT COME FROM `spend` AT ALL, and that is worth
 * saying where the reader will look for the missing second call: they come from
 * `hotspots.node_models`. A `group_by=model` read answers "what billed anywhere
 * in this window", so it would have offered a model the chosen step never ran -
 * an arm that cannot exist, which is a question with no answer rather than a
 * comparison.
 *
 * NOTHING HERE WRITES A REVIEW. The stored list is a `GET`; the only thing
 * that spends money is a `POST`, and it is reachable from exactly one press.
 */
const improveWorkflows = ref<ImproveWorkflowOption[]>([])
const improveWorkflowId = ref('')
const improveHotspots = ref<ImproveHotspots | null>(null)
const improveDigests = ref<ImproveDigestPage | null>(null)
const improveCompareResult = ref<ImproveCompare | null>(null)

const compareAxis = ref<ImproveCompareAxis>('version')
const compareA = ref('')
const compareB = ref('')
const compareNodeId = ref('')
const evalsetRating = ref<EvalsetRating>('good')

const comparing = ref(false)
const digesting = ref(false)
const exporting = ref(false)
const compareProblem = ref('')
const digestProblem = ref('')
const exportProblem = ref('')

/**
 * Which runs the export will carry, in a sentence rather than in a button's
 * word.
 *
 * FOUND BY LOOKING: the rail's own labels are `7 days` / `default` / `90 days`,
 * and read into the export's sentence they came out as "over default", which
 * says nothing at all. The rail can be terse because three buttons beside each
 * other explain themselves; a sentence cannot.
 */
const windowLabel = computed(() => {
  const days = windowDays.value
  return days === null ? 'the default window' : `the last ${days} days`
})

/** The window-wide read: the two picker lists, and nothing per workflow. */
async function loadImprove(): Promise<void> {
  await load(
    'improve',
    [
      async () => {
        const byWorkflow = await adminApi.spend('workflow', activeWindow.value)
        improveWorkflows.value = byWorkflow.rows.map((row) => ({
          id: row.key,
          label: row.label || row.key,
          runs: row.runs ?? null,
        }))
      },
    ],
    'the workflow list could not be read.',
  )
  if (improveWorkflowId.value) await loadImproveWorkflow()
}

/** The two per-workflow reads. Both are free; neither calls a model. */
async function loadImproveWorkflow(): Promise<void> {
  const workflowId = improveWorkflowId.value
  if (!workflowId) {
    improveHotspots.value = null
    improveDigests.value = null
    return
  }
  await load(
    'improve',
    [
      async () => {
        improveHotspots.value = await improveApi.hotspots(workflowId, activeWindow.value)
      },
      async () => {
        improveDigests.value = await improveApi.digests(workflowId)
      },
    ],
    'this workflow could not be read.',
  )
}

function selectImproveWorkflow(id: string): void {
  improveWorkflowId.value = id
  // A comparison belongs to the workflow it was asked about, so switching
  // workflows drops it rather than leaving two sides of somebody else's graph
  // sitting under a new name. The chosen step goes with it, for the same
  // reason: a node id is only meaningful inside one workflow.
  improveCompareResult.value = null
  compareNodeId.value = ''
  compareProblem.value = ''
  digestProblem.value = ''
  exportProblem.value = ''
  void loadImproveWorkflow()
}

/**
 * Switch what is being compared, and drop the answer to the previous question.
 *
 * The two arms mean different things on the two axes - a version number is not
 * a model slug - so leaving `3` in the box while the label above it changed to
 * `Model A` would be a control that lies about what it will send.
 */
function selectCompareAxis(axis: ImproveCompareAxis): void {
  if (compareAxis.value === axis) return
  compareAxis.value = axis
  compareA.value = ''
  compareB.value = ''
  compareNodeId.value = ''
  improveCompareResult.value = null
  compareProblem.value = ''
}

/** On an explicit press only: two arms is a question, not a page load. */
async function runCompare(): Promise<void> {
  if (!improveWorkflowId.value || comparing.value) return
  // R4, from the client: the model axis has no meaning without a step, the
  // server answers 422 without one, and a refusal a panel could have avoided
  // is a refusal the reader has to interpret.
  if (compareAxis.value === 'model' && !compareNodeId.value) return
  comparing.value = true
  compareProblem.value = ''
  try {
    improveCompareResult.value = await improveApi.compare(
      improveWorkflowId.value,
      compareAxis.value,
      compareA.value.trim(),
      compareB.value.trim(),
      activeWindow.value,
      compareNodeId.value,
    )
  } catch (error) {
    improveCompareResult.value = null
    compareProblem.value = sentence(error, 'those two sides could not be compared.')
  } finally {
    comparing.value = false
  }
}

/**
 * THE ONE PLACE THIS PRODUCT SPENDS MONEY FROM THE ADMIN CONSOLE.
 *
 * One `POST` per press, guarded by `digesting` so a double click cannot make
 * two calls, and the new row is prepended to what is already on screen rather
 * than triggering a re-read - a second `GET` here would be a request nobody
 * asked for on the one path that has just cost something.
 */
async function runDigest(): Promise<void> {
  if (!improveWorkflowId.value || digesting.value) return
  digesting.value = true
  digestProblem.value = ''
  try {
    const row = await improveApi.runDigest(improveWorkflowId.value, activeWindow.value)
    improveDigests.value = improveDigests.value
      ? { ...improveDigests.value, rows: [row, ...improveDigests.value.rows] }
      : { rows: [row], enabled: true }
  } catch (error) {
    digestProblem.value = sentence(error, 'that review could not be written.')
  } finally {
    digesting.value = false
  }
}

async function exportEvalset(): Promise<void> {
  if (!improveWorkflowId.value || exporting.value) return
  exporting.value = true
  exportProblem.value = ''
  try {
    await improveApi.downloadEvalset(
      improveWorkflowId.value,
      evalsetRating.value,
      activeWindow.value,
    )
  } catch (error) {
    exportProblem.value = sentence(error, 'that download could not be streamed.')
  } finally {
    exporting.value = false
  }
}

/** Which tabs have asked for their data, so opening one twice is free. */
const visited = ref(new Set<TabId>(['overview', 'health']))

function openTab(id: TabId): void {
  if (tab.value === 'insights' && id !== 'insights') {
    const requestWasPending = busy.value.insights
    insightGeneration += 1
    busy.value = { ...busy.value, insights: false }
    if (requestWasPending) insights.value = null
  }
  tab.value = id
  if (visited.value.has(id)) {
    if (id === 'insights' && !insights.value && !busy.value.insights) void loadInsights()
    return
  }
  visited.value = new Set([...visited.value, id])
  if (id === 'money') void loadMoney()
  if (id === 'people') void loadPeople()
  if (id === 'runs') void loadRuns()
  if (id === 'insights') void loadInsights()
  if (id === 'improve') void loadImprove()
}

/** A new window invalidates every answer on the screen, not only the visible
 *  one - two panels reading different fortnights is the failure this avoids. */
watch(activeWindow, () => {
  insightWorkflows.value = insightWorkflow.value
    ? [{ workflow_id: insightWorkflow.value, runs: null }]
    : []
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
  if (tab.value === 'insights') {
    visited.value = new Set([...visited.value, 'insights'])
    void loadInsights()
  }
  if (tab.value === 'improve') {
    visited.value = new Set([...visited.value, 'improve'])
    // A comparison was measured over the old window, so it goes with it. The
    // two arms would otherwise sit under a fortnight they were never about.
    improveCompareResult.value = null
    void loadImprove()
  }
})

watch(spendAxis, () => void loadMoney())
watch(userSort, () => void loadPeople())
/** A new rating filter re-asks the server rather than filtering on screen: the
 *  table is a page of a keyset walk, so a client-side filter would silently
 *  narrow one page and call it the answer. */
watch(runRating, () => {
  if (visited.value.has('runs')) void loadRuns()
})
watch(insightWorkflow, () => {
  if (tab.value === 'insights') void loadInsights()
})

/* ── the drawer ───────────────────────────────────────────────────────────── */

const drawerRun = ref<AdminRunRow | null>(null)
const drawerDecisions = ref<AdminDecisions | null>(null)
const drawerPerson = ref<AdminUserDetail | null>(null)
const drawerBusy = ref(false)
const drawerProblem = ref('')
let drawerGeneration = 0

function closeDrawer(): void {
  drawerGeneration += 1
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
  const generation = drawerGeneration
  drawerBusy.value = true
  const known = runs.value?.rows.find((row) => row.run_id === runId) ?? null
  drawerRun.value = known
  try {
    if (!known) {
      const page = await adminApi.runs({ ...activeWindow.value, limit: 1, user_id: undefined })
      if (generation !== drawerGeneration) return
      drawerRun.value = page.rows.find((row) => row.run_id === runId) ??
        ({ run_id: runId, user_id: null, email: null, workflow_id: '', status: 'unknown',
          created_at: '', cost_usd: 0 } as AdminRunRow)
    }
    const answer = await adminApi.decisions(runId)
    if (generation !== drawerGeneration) return
    drawerDecisions.value = answer
  } catch (error) {
    if (generation !== drawerGeneration) return
    drawerProblem.value = sentence(error, 'this run could not be read.')
  } finally {
    if (generation === drawerGeneration) drawerBusy.value = false
  }
}

async function openInsightRun(run: AdminRunRow): Promise<void> {
  closeDrawer()
  const generation = drawerGeneration
  drawerRun.value = run
  drawerBusy.value = true
  try {
    const answer = await adminApi.decisions(run.run_id)
    if (generation !== drawerGeneration) return
    drawerDecisions.value = answer
  } catch (error) {
    if (generation !== drawerGeneration) return
    drawerProblem.value = sentence(error, 'this run could not be read.')
  } finally {
    if (generation === drawerGeneration) drawerBusy.value = false
  }
}

async function openPerson(userId: string): Promise<void> {
  closeDrawer()
  const generation = drawerGeneration
  drawerBusy.value = true
  try {
    const answer = await adminApi.user(userId)
    if (generation !== drawerGeneration) return
    drawerPerson.value = answer
  } catch (error) {
    if (generation !== drawerGeneration) return
    drawerProblem.value = sentence(error, 'this account could not be read.')
  } finally {
    if (generation === drawerGeneration) drawerBusy.value = false
  }
}

/** A cancelled run changes the run list and the summary, so both are re-read
 *  rather than patched: the server is the truth, and a lever that only edited
 *  the screen would be a lever that lies when it fails. */
function afterCancel(): void {
  void loadOverview()
  if (visited.value.has('runs')) void loadRuns()
}

/**
 * A rating written from the drawer changes the row behind it AND the drawer's
 * own block, so both are re-read from the server (plan 20 §2.4).
 *
 * The same judgement as `afterCancel`: the server is the truth on this screen.
 * A drawer that patched itself would show a rating the database might not hold
 * if the write half-succeeded, which is the one thing a record built to be
 * read as evidence must never do. The run list is re-read too, because a
 * `rating` filter can mean the row has just left the page it was on.
 */
async function afterRated(runId: string): Promise<void> {
  if (visited.value.has('runs')) void loadRuns()
  if (!runId || drawerRun.value?.run_id !== runId) return
  const generation = drawerGeneration
  try {
    const answer = await adminApi.decisions(runId)
    if (generation !== drawerGeneration) return
    drawerDecisions.value = answer
  } catch {
    // Quiet. The write itself already reported its own refusal in the control,
    // and a failed re-read must not put a second sentence over a save that
    // worked.
  }
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
            <Lightbulb v-else-if="entry.id === 'insights'" :size="13" aria-hidden="true" />
            <Sprout v-else-if="entry.id === 'improve'" :size="13" aria-hidden="true" />
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
              :rating="runRating"
              :loading="busy.runs"
              :problem="problems.runs"
              @open-run="openRun"
              @select-rating="runRating = $event"
            />
            <AdminInsights
              v-else-if="entry.id === 'insights'"
              :insights="insights"
              :workflows="insightWorkflows"
              :workflow-id="insightWorkflow"
              :loading="busy.insights"
              :problem="problems.insights"
              @refresh="loadInsights"
              @select-workflow="insightWorkflow = $event"
              @open-run="openInsightRun"
            />
            <AdminImprove
              v-else-if="entry.id === 'improve'"
              :workflows="improveWorkflows"
              :workflow-id="improveWorkflowId"
              :hotspots="improveHotspots"
              :compare="improveCompareResult"
              :digests="improveDigests"
              :compare-axis="compareAxis"
              :compare-a="compareA"
              :compare-b="compareB"
              :compare-node-id="compareNodeId"
              :evalset-rating="evalsetRating"
              :window-label="windowLabel"
              :loading="busy.improve"
              :comparing="comparing"
              :digesting="digesting"
              :exporting="exporting"
              :problem="problems.improve"
              :compare-problem="compareProblem"
              :digest-problem="digestProblem"
              :export-problem="exportProblem"
              @select-workflow="selectImproveWorkflow"
              @select-axis="selectCompareAxis"
              @update-compare-a="compareA = $event"
              @update-compare-b="compareB = $event"
              @select-compare-node="compareNodeId = $event"
              @run-compare="runCompare"
              @run-digest="runDigest"
              @select-evalset-rating="evalsetRating = $event"
              @export-evalset="exportEvalset"
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
          @rated="afterRated"
        />
      </div>
    </main>
  </div>
</template>

<style src="../components/admin/admin.css"></style>
