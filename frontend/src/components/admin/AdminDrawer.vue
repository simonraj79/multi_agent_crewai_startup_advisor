<script setup lang="ts">
/**
 * The docked drawer: one run's decisions, or one person's account.
 *
 * **Docked, never modal** (R15, and criterion 23 restates it). It is a grid
 * column of `AdminView`'s body, so the panel beside it narrows rather than
 * being covered: a reader comparing a run against the table it came from can
 * see both, and nothing on this screen ever hides the thing it is about. There
 * is no `role="dialog"`, no `aria-modal`, no scrim and no focus trap anywhere
 * in this file, and `adminPanels.spec.ts` asserts their absence rather than
 * trusting this paragraph.
 *
 * THE GATE TRAIL IS WHY THIS DRAWER EXISTS. `run_gates.response` is the
 * operator's own words and their edited fields, verbatim - and it is **the one
 * view Langfuse cannot give**, because content policy hashes it there. Every
 * other block here is a convenience; this one is the only copy.
 *
 * `Fetch billed` IS A BUTTON, and that is criterion 26's other half: the billed
 * figure is an outbound call to Langfuse made on the server's thread, so it
 * happens when somebody asks and never on a page load.
 */
import { computed, ref, watch } from 'vue'
import { LoaderCircle, Square, TriangleAlert, X } from 'lucide-vue-next'
import LangfuseLink from './LangfuseLink.vue'
import MoneyFigure from './MoneyFigure.vue'
import RatingControl from '../RatingControl.vue'
import { count, duration, durationMs, humanise, money, personLabel, when } from './adminFormat'
import { adminApi } from '../../services/adminApi'
import { renderMarkdown } from '../../utils/markdown'
import { readRunRating, runRatingWord } from '../../data/runRating'
import { isTerminalRunStatus } from '../../data/runStatusDisplay'
import type {
  AdminBilled,
  AdminDecisions,
  AdminLinks,
  AdminRunRow,
  AdminUserDetail,
  ProbeUnavailable,
} from '../../services/adminApi'
import type { RunRating } from '../../types/studio'

const props = defineProps<{
  /** What the drawer is about. `null` on neither, and the drawer is not drawn. */
  run: AdminRunRow | null
  decisions: AdminDecisions | null
  person: AdminUserDetail | null
  links: AdminLinks | null
  loading: boolean
  problem: string
}>()

const emit = defineEmits<{ close: []; cancelled: [runId: string]; rated: [runId: string] }>()

const langfuseOn = computed(() => props.links?.langfuse.configured === true)

/* ── the billed figure, on a press ────────────────────────────────────────── */

const billed = ref<AdminBilled | ProbeUnavailable | null>(null)
const billedBusy = ref(false)
const billedProblem = ref('')

/** A new run clears the last one's answer: a figure that outlived its run
 *  would be the worst kind of wrong number on this screen. */
watch(
  () => props.run?.run_id,
  () => {
    billed.value = null
    billedProblem.value = ''
    cancelProblem.value = ''
    answerOpen.value = false
  },
)

async function fetchBilled(): Promise<void> {
  const id = props.run?.run_id
  if (!id || billedBusy.value) return
  billedBusy.value = true
  billedProblem.value = ''
  try {
    billed.value = await adminApi.billed(id)
  } catch (error) {
    billedProblem.value = error instanceof Error ? error.message : 'the billed figure could not be read.'
  } finally {
    billedBusy.value = false
  }
}

const billedFigure = computed(() => (billed.value?.available === true ? billed.value : null))
const billedRefusal = computed(() =>
  billed.value !== null && billed.value.available === false ? billed.value.reason : '',
)

/* ── the one lever this drawer offers ─────────────────────────────────────── */

const cancellable = computed(
  () => props.run !== null && !isTerminalRunStatus(props.run.status),
)
const cancelBusy = ref(false)
const cancelProblem = ref('')

async function cancelRun(): Promise<void> {
  const id = props.run?.run_id
  if (!id || cancelBusy.value) return
  cancelBusy.value = true
  cancelProblem.value = ''
  try {
    await adminApi.cancelRun(id)
    emit('cancelled', id)
  } catch (error) {
    cancelProblem.value = error instanceof Error ? error.message : 'the run could not be cancelled.'
  } finally {
    cancelBusy.value = false
  }
}

/* ── what it answered ────────────────────────────────────────────────────── */

/**
 * The run's own answer, so the person asked "was this run good?" has read the
 * thing they are judging. Every automatic check can be green on a reply that
 * is plainly wrong - a billing agent announcing a charge it never made - and
 * nothing but reading it catches that.
 *
 * The body is model output, untrusted by construction, so it reaches the page
 * only through `renderMarkdown`, which escapes every character before it
 * recognises any structure (the same path `ReportPanel.vue` uses).
 */
const answer = computed(() => props.decisions?.answer ?? null)
const answerHtml = computed(() => (answer.value ? renderMarkdown(answer.value) : ''))
const answerOpen = ref(false)

/** Past this many characters or lines the block starts collapsed and offers
 *  "Show all". A count rather than a measured height, because the drawer is
 *  judged in jsdom as well as in a browser and jsdom has no layout. */
const ANSWER_COLLAPSE_CHARS = 600
const ANSWER_COLLAPSE_LINES = 10
const answerLong = computed(() => {
  const text = answer.value ?? ''
  return text.length > ANSWER_COLLAPSE_CHARS || text.split('\n').length > ANSWER_COLLAPSE_LINES
})

/* ── was this run good? ───────────────────────────────────────────────────── */

/**
 * The human verdict on this run, as the decisions payload reported it.
 *
 * Read through `readRunRating` rather than taken as typed: the note has two
 * spellings in flight while plan 20's two builders land (see
 * `data/runRating.ts`), and a drawer that dropped a sentence somebody typed
 * would be the quietest possible loss.
 */
const rating = computed<RunRating | null>(() =>
  props.decisions?.rating ? readRunRating(props.decisions.rating, props.run?.run_id ?? '') : null,
)

/**
 * A save here changes a row on the table beside this drawer, so the PARENT is
 * told rather than the row patched locally: the admin console's rule is that
 * the server is the truth and a lever that only edited the screen would be a
 * lever that lies when it fails. The opposite call from `RunHistory`'s, and
 * for the opposite reason - there, the reply IS the whole row.
 */
function afterRating(answer: RunRating): void {
  emit('rated', answer.run_id || props.run?.run_id || '')
}

/** A gate's stored reply, printed as the operator left it. */
function responseLines(response: Record<string, unknown> | null | undefined): string[] {
  if (!response) return []
  return Object.entries(response).map(([key, value]) => {
    const text = typeof value === 'string' ? value : JSON.stringify(value)
    return `${key}: ${text}`
  })
}
</script>

<template>
  <aside
    v-if="run || person"
    class="admin-drawer"
    aria-labelledby="admin-drawer-title"
    data-testid="admin-drawer"
  >
    <header class="admin-drawer-head">
      <div>
        <span class="panel-kicker is-accent">{{ run ? 'RUN' : 'PERSON' }}</span>
        <h2 id="admin-drawer-title">
          {{ run ? `${run.workflow_id} · ${personLabel(run.user_id, run.email)}`
                 : personLabel(person?.user_id, person?.email) }}
        </h2>
        <p v-if="run" class="panel-meta">{{ run.run_id }}</p>
      </div>
      <button class="admin-drawer-close" type="button" aria-label="Close the drawer" @click="emit('close')">
        <X :size="15" aria-hidden="true" />
      </button>
    </header>

    <div class="admin-drawer-body">
      <p v-if="problem" class="admin-problem" role="alert">
        <TriangleAlert :size="14" aria-hidden="true" />{{ problem }}
      </p>
      <p v-else-if="loading" class="admin-loading" role="status">Reading…</p>

      <!-- ── one run ────────────────────────────────────────────────────── -->
      <template v-if="run">
        <!--
          THE RUN HEADER'S TWO LINKS (criterion 27). Both are the server's own
          URLs and both disappear entirely when Langfuse is not configured -
          never a broken href.
        -->
        <p class="admin-drawer-links">
          <LangfuseLink :href="run.langfuse?.session_url" :configured="langfuseOn" kind="session" />
          <LangfuseLink :href="run.langfuse?.trace_url" :configured="langfuseOn" kind="trace" />
        </p>

        <dl class="admin-facts">
          <div class="admin-fact">
            <dt>Status</dt>
            <dd>
              {{ run.status }}
              <span v-if="run.stop_reason" class="admin-sub">{{ humanise(run.stop_reason) }}</span>
            </dd>
          </div>
          <div class="admin-fact">
            <dt>Started · took</dt>
            <dd>{{ when(run.created_at) }} · {{ durationMs(run.duration_ms) }}</dd>
          </div>
          <div class="admin-fact">
            <dt>Spend</dt>
            <dd>
              <MoneyFigure :value="run.cost_usd" />
              <span class="admin-sub">
                admitted under {{ run.max_cost_usd === null || run.max_cost_usd === undefined
                  ? 'no per-run ceiling' : `a ${money(run.max_cost_usd)} ceiling` }}
                <template v-if="run.ceiling_kind"> ({{ humanise(run.ceiling_kind) }})</template>
              </span>
            </dd>
          </div>
          <div v-if="run.integrity" class="admin-fact" :class="{ 'is-warn': run.integrity.dropped > 0 || run.integrity.gaps > 0 }">
            <dt>Frames</dt>
            <dd>
              {{ count(run.integrity.captured) }} captured ·
              {{ count(run.integrity.dropped) }} dropped ·
              {{ count(run.integrity.gaps) }} gaps
            </dd>
          </div>
          <div v-if="run.error" class="admin-fact is-err">
            <dt>Error</dt>
            <dd>{{ run.error }}</dd>
          </div>
        </dl>

        <section class="admin-drawer-block" aria-labelledby="admin-billed-title">
          <header class="admin-block-head">
            <h3 id="admin-billed-title">Billed cost</h3>
            <span class="panel-meta">Langfuse · on request</span>
          </header>
          <button
            class="button button-secondary"
            type="button"
            :disabled="billedBusy"
            data-testid="admin-fetch-billed"
            @click="fetchBilled"
          >
            <LoaderCircle v-if="billedBusy" class="admin-spin" :size="13" aria-hidden="true" />
            Fetch billed
          </button>
          <dl v-if="billedFigure" class="admin-facts" data-testid="admin-billed">
            <div class="admin-fact">
              <dt>Billed</dt>
              <dd>{{ money(billedFigure.billed_usd) }} over {{ count(billedFigure.generations) }} generations</dd>
            </div>
            <div class="admin-fact">
              <dt>Against the estimate</dt>
              <dd>
                <MoneyFigure :value="billedFigure.estimate_usd" />
                <span v-if="billedFigure.delta_pct !== null" class="admin-sub">
                  {{ billedFigure.delta_pct > 0 ? '+' : '' }}{{ billedFigure.delta_pct }}% out
                </span>
              </dd>
            </div>
          </dl>
          <p v-else-if="billedRefusal" class="admin-warning" role="status">{{ billedRefusal }}</p>
          <p v-if="billedProblem" class="admin-problem" role="alert">{{ billedProblem }}</p>
        </section>

        <!--
          READ, THEN JUDGE. This block sits above "Was this run good?" on
          purpose: the rating is only worth having from somebody who has read
          the answer, and until this block existed nobody on this screen could.
        -->
        <section class="admin-drawer-block" aria-labelledby="admin-answer-title" data-testid="admin-answer">
          <header class="admin-block-head">
            <h3 id="admin-answer-title">What it answered</h3>
            <span class="panel-meta">the run's final reply</span>
          </header>
          <template v-if="answer">
            <!-- eslint-disable-next-line vue/no-v-html -->
            <article
              id="admin-answer-body"
              class="admin-answer markdown-body"
              :class="{ 'is-collapsed': answerLong && !answerOpen }"
              data-testid="admin-answer-body"
              v-html="answerHtml"
            ></article>
            <button
              v-if="answerLong"
              class="button button-secondary admin-answer-toggle"
              type="button"
              aria-controls="admin-answer-body"
              :aria-expanded="answerOpen"
              data-testid="admin-answer-toggle"
              @click="answerOpen = !answerOpen"
            >
              {{ answerOpen ? 'Show less' : 'Show all' }}
            </button>
            <p v-if="decisions?.answer_truncated" class="admin-sub" data-testid="admin-answer-truncated">
              This is the first part only; the stored answer is longer than the console shows.
            </p>
          </template>
          <p v-else-if="!loading && decisions" class="admin-empty" data-testid="admin-answer-empty">
            This run stored no answer.
          </p>
        </section>

        <!--
          THE ONE THING ON THIS SCREEN NOTHING COMPUTES. Every other block in
          this drawer is machine evidence - what it cost, which guardrail
          retried, which gate was revised - and none of it says whether the
          answer was worth having. This block is where that comes from, and an
          admin writing it is logged with their e-mail on the server.
        -->
        <section class="admin-drawer-block" aria-labelledby="admin-rating-title">
          <header class="admin-block-head">
            <h3 id="admin-rating-title">Was this run good?</h3>
            <span class="panel-meta">a judgement, not a measurement</span>
          </header>
          <p v-if="rating?.rating" class="admin-facts-line" data-testid="admin-rating-current">
            {{ runRatingWord(rating.rating) }}<template v-if="rating.rated_by"> · {{ personLabel(rating.rated_by, run && rating.rated_by === run.user_id ? run.email : null) }}</template><template v-if="rating.rated_at"> · {{ when(rating.rated_at) }}</template>
            <span v-if="rating.note" class="admin-sub">{{ rating.note }}</span>
          </p>
          <p v-else class="admin-empty" data-testid="admin-rating-current">Nobody has rated this run.</p>
          <RatingControl
            admin
            :run-id="run.run_id"
            :rating="rating?.rating ?? null"
            :note="rating?.note ?? ''"
            :status="run.status"
            @saved="afterRating"
          />
        </section>

        <section class="admin-drawer-block" aria-labelledby="admin-trail-title">
          <header class="admin-block-head">
            <h3 id="admin-trail-title">Gate trail</h3>
            <span class="panel-meta">the operator's own words</span>
          </header>
          <ol v-if="decisions?.gates.length" class="admin-trail" data-testid="admin-gate-trail">
            <li v-for="gate in decisions.gates" :key="`${gate.gate_id}-${gate.opened_at ?? ''}`">
              <span class="admin-trail-head">
                {{ gate.gate_id }} · {{ gate.outcome ?? gate.status }}
                <span v-if="gate.seconds !== null && gate.seconds !== undefined" class="admin-sub">
                  after {{ duration(gate.seconds) }}
                </span>
              </span>
              <ul v-if="responseLines(gate.response).length" class="admin-trail-said">
                <li v-for="line in responseLines(gate.response)" :key="line">{{ line }}</li>
              </ul>
            </li>
          </ol>
          <p v-else-if="!loading" class="admin-empty">No gate opened on this run.</p>
        </section>

        <section class="admin-drawer-block" aria-labelledby="admin-guardrails-title">
          <header class="admin-block-head">
            <h3 id="admin-guardrails-title">Guardrails and fallbacks</h3>
          </header>
          <ul v-if="decisions?.guardrails.length" class="admin-plain" data-testid="admin-guardrails">
            <li v-for="row in decisions.guardrails" :key="`${row.guardrail}-${row.node_id ?? ''}`">
              {{ row.guardrail }} retried {{ count(row.retry_count) }} time(s)
              <span v-if="row.node_id" class="admin-sub">on {{ row.node_id }}</span>
            </li>
          </ul>
          <p v-else-if="!loading" class="admin-empty">No guardrail retried.</p>
          <ul v-if="decisions?.fallback_models.length" class="admin-plain" data-testid="admin-fallbacks">
            <li v-for="row in decisions.fallback_models" :key="`${row.node_id}-${row.fallback_model}`">
              {{ row.node_id }} fell back to {{ row.fallback_model }}
            </li>
          </ul>
          <p v-else-if="!loading" class="admin-empty">No fallback model fired.</p>
        </section>

        <section v-if="cancellable" class="admin-drawer-block" aria-labelledby="admin-lever-title">
          <header class="admin-block-head">
            <h3 id="admin-lever-title">Lever</h3>
            <span class="panel-meta">logged with your email</span>
          </header>
          <button
            class="button button-secondary"
            type="button"
            :disabled="cancelBusy"
            data-testid="admin-cancel-run"
            @click="cancelRun"
          >
            <Square :size="13" aria-hidden="true" /> Cancel this run
          </button>
          <p v-if="cancelProblem" class="admin-problem" role="alert">{{ cancelProblem }}</p>
        </section>
      </template>

      <!-- ── one person ─────────────────────────────────────────────────── -->
      <template v-else-if="person">
        <p class="admin-drawer-links">
          <LangfuseLink :href="person.langfuse.user_url" :configured="langfuseOn" kind="user" />
        </p>
        <dl class="admin-facts">
          <div class="admin-fact">
            <dt>Lifetime spend</dt>
            <dd>
              <MoneyFigure :value="person.spent_usd" />
              <span class="admin-sub">
                + {{ money(person.committed_usd) }} committed
                <template v-if="person.committed_is_volatile">(memory only, lost on restart)</template>
                <template v-if="!person.exempt && person.cap_usd !== null">
                  of a {{ money(person.cap_usd) }} cap
                </template>
                <template v-else-if="person.exempt"> · exempt from the cap</template>
              </span>
            </dd>
          </div>
          <div class="admin-fact">
            <dt>Runs</dt>
            <dd>{{ count(person.runs) }}</dd>
          </div>
          <div class="admin-fact">
            <dt>Gates</dt>
            <dd>
              {{ count(person.gates.answered) }} answered · median
              {{ duration(person.gates.median_seconds) }} · {{ count(person.gates.expired) }} expired
            </dd>
          </div>
          <div class="admin-fact">
            <dt>Assets</dt>
            <dd>
              {{ count(person.documents ?? 0) }} graphs ({{ count(person.published ?? 0) }} live) ·
              {{ count(person.credentials ?? 0) }} credentials ·
              {{ count(person.mcp_servers ?? 0) }} MCP servers
            </dd>
          </div>
          <div class="admin-fact">
            <dt>Last sign-in</dt>
            <dd>
              {{ when(person.last_session_at) }}
              <span class="admin-sub">session refresh granularity, not a sign-in log</span>
            </dd>
          </div>
        </dl>

        <section class="admin-drawer-block" aria-labelledby="admin-person-runs-title">
          <header class="admin-block-head">
            <h3 id="admin-person-runs-title">Recent runs</h3>
          </header>
          <ul v-if="person.recent_runs.length" class="admin-plain" data-testid="admin-person-runs">
            <li v-for="row in person.recent_runs" :key="row.run_id">
              {{ when(row.created_at) }} · {{ row.workflow_id }} · {{ row.status }} ·
              <MoneyFigure :value="row.cost_usd" :tag="false" />
            </li>
          </ul>
          <p v-else class="admin-empty">No run on this account.</p>
        </section>
      </template>
    </div>
  </aside>
</template>
