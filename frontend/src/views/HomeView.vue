<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CircleDot, Clock3, FilePlus2, GitBranch, Loader, Play, TriangleAlert } from 'lucide-vue-next'
import AccountChip from '../components/builder/AccountChip.vue'
import GraphThumbnail from '../components/builder/GraphThumbnail.vue'
import { PRODUCT_NAME } from '../data/brand'
import { ALL_BUILDER_TEMPLATES } from '../data/builderTemplates'
import { readRunHandoff } from '../data/builderRunHandoff'
import { scopedKey } from '../data/identityStorage'
import { MOCK_GRAPH } from '../data/mockGraph'
import { runStatusDisplay } from '../data/runStatusDisplay'
import { ACTIVE_RUN_STORAGE_KEY } from '../composables/useValidatorRun'
import { homeResumesConsole } from '../composables/useWorkspaceRoute'
import { builderApi } from '../services/builderApi'
import { studioApi } from '../services/studioApi'
import { agoFrom, parseStamp } from '../utils/storedTime'
import type { SignedInUser } from '../composables/useAuthGate'
import type { RunPointerState } from '../composables/useWorkspaceRoute'
import type { BuilderDocument, BuilderDocumentSummary, DocumentId } from '../types/builder'
import type { RunStatus } from '../types/studio'

/**
 * The home: every workflow this account can open, on one page.
 *
 * `docs/ux-shell/DEFINITION-OF-DONE.md` U1, and the reason it exists is that
 * `#/` used to be the run console - one fixed workflow, drawn as a graph, with
 * no way from it to the eight other things this product can run except a
 * segmented button labelled Build. A person who had saved four graphs had no
 * screen that listed four graphs. This is that screen, and the console moved to
 * `#/run` to make room for it (D2, amending `docs/flow-builder-spec.md` §1.3).
 *
 * THREE SECTIONS, IN THE ORDER SOMEBODY READS THEM. What is ready to run, then
 * what you saved, then what you could start. It is a flat list in each - no
 * search, no folders, no tags, no favourites - because cut list item 13 stands
 * and because the thing that makes a list of nine hard to use is chrome rather
 * than order.
 *
 * IT ADDS NO ENDPOINT. Everything on the page is a request the builder gallery
 * or the run console already makes: `GET /api/workflows/{id}/graph` for the
 * fixed validator, `GET /api/builder/workflows` for the library, and the
 * templates are a module. The one place that costs more than the gallery does
 * is the thumbnails - see `loadLibrary`.
 */

const props = defineProps<{
  /**
   * The signed-in account, or null when authentication is not configured.
   *
   * There is no `authenticated` prop beside it, unlike `StudioView`'s pair, and
   * the asymmetry is deliberate: that view guards its own first request on the
   * phase because it can be reached while the gate is still deciding. This one
   * cannot - `App.vue` renders the splash and then the wall before it routes at
   * all - so a second prop here would guard a state that does not exist, and
   * the next reader would maintain it.
   */
  user: SignedInUser | null
  /**
   * Whether this mount is the page's own arrival at `#/`, rather than a later
   * visit from the breadcrumb.
   *
   * The hand-over below is about RECOVERY - reopening a run that is still going
   * after a reload - and a person who has just pressed `Workflows` from a live
   * console is not recovering, they are leaving. Asked on every mount, the same
   * predicate would bounce them straight back and the breadcrumb would look
   * broken. `App.vue` owns the flag and closes the window on the first
   * navigation of the session.
   */
  resumeOnLoad: boolean
}>()

const emit = defineEmits<{
  /** Hand over to the console: a run is still going, or the builder sent one. */
  resume: []
  /** Open the run console. */
  run: []
  /** Open the builder's gallery. */
  build: []
  /**
   * Open one stored document on the builder canvas.
   *
   * `DocumentId` rather than `string`, the same cast `BuilderView.openFromGallery`
   * makes on the same value: the id came from `GET /api/builder/workflows`, so
   * it is server-assigned and already matches `DOCUMENT_ID_PATTERN` - the brand
   * records that, and the route type demands it.
   */
  openDocument: [documentId: DocumentId]
  /** Seed one template into the builder as an unsaved draft. */
  openTemplate: [templateId: string]
  signOut: []
}>()

const identity = computed(() => props.user?.id ?? null)

/* ── the hand-over to the console (D2) ─────────────────────────────────────
 *
 * Moving the console off `#/` must not put refresh recovery one click further
 * away than it was: a run waiting at a gate, and a graph the builder has just
 * handed over, are exactly the two states in which somebody reloads. The
 * DECISION is `homeResumesConsole` in `useWorkspaceRoute.ts`, which is pure and
 * tested; everything here is the reading it needs.
 *
 * The handoff is synchronous, so a builder hand-over never draws this page at
 * all. The run pointer is not: it carries no status - `StoredRunContext` is a
 * run id, a session id and a workflow id - so the only way to know whether that
 * run is still going is to ask the server, and `restoreRun` asks the same
 * question with the same request one route later. While that is in flight the
 * page renders, with a line saying what it is doing, rather than holding a
 * blank screen on a request that may time out.
 */

/** The stored run id, or null. Guarded: site data can be blocked outright. */
function storedRunId(): string | null {
  try {
    const raw = globalThis.localStorage?.getItem(scopedKey(ACTIVE_RUN_STORAGE_KEY, identity.value))
    if (!raw) return null
    const parsed = JSON.parse(raw) as { version?: number; runId?: string }
    return parsed.version === 1 && parsed.runId ? parsed.runId : null
  } catch {
    return null
  }
}

const TERMINAL_RUN_STATUSES: readonly RunStatus[] = ['completed', 'error', 'cancelled']

/** The run the console left behind, once the server has been asked about it. */
const lastRun = ref<{ id: string; status: RunStatus } | null>(null)
const checkingPointer = ref(false)

async function resolvePointer(): Promise<RunPointerState> {
  const id = storedRunId()
  if (!id) return 'none'
  checkingPointer.value = true
  try {
    await studioApi.initialize()
    const snapshot = await studioApi.getRun(id)
    lastRun.value = { id, status: snapshot.status }
    return TERMINAL_RUN_STATUSES.includes(snapshot.status) ? 'terminal' : 'live'
  } catch {
    // Recovery wins. A pointer whose status could not be read is treated as a
    // run still going: being wrong that way costs one click back to here, and
    // being wrong the other way strands an operator away from a gate that is
    // waiting for them.
    return 'live'
  } finally {
    checkingPointer.value = false
  }
}

/** The card the home shows for a finished run: history, not a hand-over. */
const lastRunCard = computed(() => {
  const run = lastRun.value
  if (!run || !TERMINAL_RUN_STATUSES.includes(run.status)) return null
  return { id: run.id, display: runStatusDisplay(run.status) }
})

/* ── the fixed workflow ───────────────────────────────────────────────────── */

/**
 * The built-in validator's own name and size, read from the server.
 *
 * `MOCK_GRAPH` is the seed rather than a fabricated topology to draw: the card
 * renders a NAME and two counts and navigates to `#/run`, where the console
 * does its own read and reports its own refusal (D-01-2). Seeding from the same
 * constant `useValidatorRun` seeds from is what keeps the two screens calling
 * one workflow one thing before either has heard from the API.
 */
const validatorGraph = ref(MOCK_GRAPH)
const validatorProblem = ref('')

/* ── the library ──────────────────────────────────────────────────────────── */

const library = ref<BuilderDocumentSummary[]>([])
const libraryProblem = ref('')
const libraryLoading = ref(true)
/** `id` -> the stored document, for its `GraphThumbnail`. Absent while loading. */
const thumbnails = ref(new Map<string, BuilderDocument>())

/**
 * The saved graphs, then a picture of each.
 *
 * TWO PASSES, AND THE SECOND IS N REQUESTS. `GET /api/builder/workflows` is a
 * SUMMARY - id, name, version, status, timestamps - and carries no document, so
 * a thumbnail needs `GET /api/builder/workflows/{id}` per row. The alternative
 * is a new endpoint returning documents in bulk, which is a server change this
 * work is not allowed to make and would be the wrong trade anyway for a
 * personal library: the list itself renders from the first request and is
 * usable immediately, and the pictures arrive after. A row whose document could
 * not be read keeps its name, its pill and its date and shows no picture, which
 * is a row missing an illustration rather than a broken list.
 */
async function loadLibrary(): Promise<void> {
  libraryLoading.value = true
  try {
    library.value = await builderApi.list()
    libraryProblem.value = ''
  } catch (error) {
    libraryProblem.value =
      error instanceof Error ? error.message : 'your saved workflows could not be loaded.'
    libraryLoading.value = false
    return
  }
  libraryLoading.value = false
  const answers = await Promise.allSettled(
    library.value.map(async (row) => ({ id: row.id, model: await builderApi.get(row.id) })),
  )
  const drawn = new Map(thumbnails.value)
  for (const answer of answers) {
    if (answer.status === 'fulfilled') drawn.set(answer.value.id, answer.value.model.document)
  }
  thumbnails.value = drawn
}

/**
 * Newest first, the same rule and the same helper the builder gallery uses.
 *
 * The question a returning author has is "where is the one I was just working
 * on", and the answer is the top of this list. An unreadable stamp sorts last
 * rather than throwing the order away.
 */
const orderedLibrary = computed(() =>
  [...library.value].sort((left, right) => {
    const at = parseStamp(right.updated_at)
    const other = parseStamp(left.updated_at)
    return (Number.isFinite(at) ? at : -Infinity) - (Number.isFinite(other) ? other : -Infinity)
  }),
)

/** One clock for the whole page, so "2 min ago" is not frozen at load. */
const now = ref(Date.now())
let ticker = 0

function when(iso: string): string {
  return agoFrom(iso, now.value)
}

/* ── the templates ────────────────────────────────────────────────────────── */

/**
 * All nine, in the gallery's own order, both of its rows flattened into one.
 *
 * The gallery demotes two of them into a collapsed `<details>` because what
 * they teach is that the compiler works rather than anything an author needs
 * first. That is a judgement about a screen whose whole job is teaching; this
 * page's job is listing what can be opened, and a list that hides two of nine
 * is not one.
 */
const templates = ALL_BUILDER_TEMPLATES

async function loadValidator(): Promise<void> {
  try {
    await studioApi.initialize()
    validatorGraph.value = await studioApi.getGraph()
    validatorProblem.value = ''
  } catch (error) {
    validatorProblem.value =
      error instanceof Error ? error.message : 'this workflow could not be read.'
  }
}

/**
 * The one question this page asks before it settles: should it be here at all?
 *
 * The handoff is read first and synchronously, so a graph the builder has just
 * published never draws a home the reader did not ask for. The pointer costs a
 * request, and the page renders while it is in flight - a blank screen behind a
 * request that can time out is worse than a list with one line saying what is
 * being checked.
 */
async function askWhetherToResume(): Promise<void> {
  if (!props.resumeOnLoad) return
  if (homeResumesConsole({ handoff: readRunHandoff(identity.value) !== null, pointer: 'none' })) {
    emit('resume')
    return
  }
  const pointer = await resolvePointer()
  if (homeResumesConsole({ handoff: false, pointer })) emit('resume')
}

onMounted(() => {
  /*
   * The tab's name follows the route (U4), and on the home it is the bare
   * product: this page is a LIST of workflows, so there is no one workflow to
   * name it after. Set on mount rather than declared in `index.html` alone,
   * because arriving here from a canvas has to take the workflow's name back
   * OFF the tab - a title that only ever grew would leave a home tab reading
   * the name of the last graph its reader closed.
   */
  document.title = PRODUCT_NAME
  ticker = window.setInterval(() => {
    now.value = Date.now()
  }, 30_000)
  void askWhetherToResume()
  void loadLibrary()
  void loadValidator()
})

onBeforeUnmount(() => window.clearInterval(ticker))
</script>

<template>
  <a class="skip-link" href="#home-workflows">Skip to the workflow list</a>
  <div class="studio-shell is-home">
    <header class="app-header">
      <!--
        The same three elements the two canvas headers carry, in the same class
        names, so W3's `BrandLockup.vue` is a one-for-one substitution here as
        well. On the home the lockup is not a link: it would point at the page
        it is on.
      -->
      <div class="brand-lockup">
        <div class="brand-mark" aria-hidden="true"><CircleDot :size="20" :stroke-width="1.8" /></div>
        <div>
          <span>M2</span>
          <h1>{{ PRODUCT_NAME }}</h1>
        </div>
      </div>

      <div class="header-context">
        <AccountChip v-if="user" :user="user" @sign-out="emit('signOut')" />
      </div>
    </header>

    <main class="home-main">
      <div class="home-page">
        <p v-if="checkingPointer" class="home-resuming" role="status">
          <Loader :size="14" aria-hidden="true" />
          Checking a run you left open…
        </p>

        <!--
          The finished run, as history rather than as a hand-over (D2). A
          non-terminal pointer never reaches this page; a terminal one is
          something you might want to read again, and `restoreRun` on `#/run`
          still restores it exactly as it did when `#/` was the console.
        -->
        <section v-if="lastRunCard" class="home-last-run" aria-labelledby="home-last-run-title">
          <div>
            <span class="home-kicker">LAST RUN</span>
            <h2 id="home-last-run-title">{{ lastRunCard.display.label }}</h2>
          </div>
          <button class="button button-secondary" type="button" @click="emit('run')">
            <Play :size="14" aria-hidden="true" /> Open it
          </button>
        </section>

        <section
          id="home-workflows"
          class="home-section"
          aria-labelledby="home-ready-title"
          tabindex="-1"
        >
          <header class="home-heading">
            <div>
              <span class="home-kicker">READY TO RUN</span>
              <h2 id="home-ready-title">Built in</h2>
            </div>
          </header>

          <ul class="home-grid">
            <li>
              <button class="home-card" type="button" data-testid="home-validator" @click="emit('run')">
                <span class="home-card-name">{{ validatorGraph.name }}</span>
                <span class="home-card-blurb">
                  Scores an idea against real evidence — market, discussion and buildability —
                  and stops twice to ask you.
                </span>
                <span v-if="validatorProblem" class="home-card-problem">
                  <TriangleAlert :size="12" aria-hidden="true" />{{ validatorProblem }}
                </span>
                <span class="home-card-meta">
                  <span class="home-pill is-run-only">run only</span>
                  <span class="home-card-count">{{ validatorGraph.nodes.length }} nodes</span>
                  <span class="home-card-count">{{ validatorGraph.edges.length }} edges</span>
                </span>
              </button>
            </li>
          </ul>
        </section>

        <section class="home-section" aria-labelledby="home-saved-title">
          <header class="home-heading">
            <div>
              <span class="home-kicker">YOUR WORKFLOWS</span>
              <h2 id="home-saved-title">Saved here</h2>
            </div>
            <button class="button button-quiet" type="button" data-testid="home-build" @click="emit('build')">
              <FilePlus2 :size="14" aria-hidden="true" /> Build a new one
            </button>
          </header>

          <p v-if="libraryLoading" class="home-empty" role="status">
            <Loader :size="14" aria-hidden="true" /> Reading your saved workflows…
          </p>
          <p v-else-if="libraryProblem" class="home-empty is-problem" role="alert">
            <TriangleAlert :size="14" aria-hidden="true" /> {{ libraryProblem }}
          </p>
          <p v-else-if="library.length === 0" class="home-empty">
            <FilePlus2 :size="14" aria-hidden="true" />
            Nothing saved yet. Pick a shape below and it is yours the moment you save it.
          </p>

          <ul v-else class="home-grid" data-testid="home-library">
            <li v-for="entry in orderedLibrary" :key="entry.id">
              <button
                class="home-card"
                type="button"
                :data-testid="`home-document-${entry.id}`"
                @click="emit('openDocument', entry.id as DocumentId)"
              >
                <GraphThumbnail
                  v-if="thumbnails.get(entry.id)"
                  class="home-card-spine"
                  :document="thumbnails.get(entry.id)!"
                />
                <!-- No picture yet, and the slot is held so nothing reflows
                     under the reader's pointer when one arrives. -->
                <span v-else class="home-card-spine is-empty" aria-hidden="true" />
                <span class="home-card-name" :title="entry.name">{{ entry.name }}</span>
                <span class="home-card-meta">
                  <span class="home-pill" :class="`is-${entry.status}`">{{ entry.status }}</span>
                  <span class="home-card-count">v{{ entry.version }}</span>
                  <span class="home-card-count">
                    <Clock3 :size="12" aria-hidden="true" />{{ when(entry.updated_at) }}
                  </span>
                </span>
              </button>
            </li>
          </ul>
        </section>

        <section class="home-section" aria-labelledby="home-templates-title">
          <header class="home-heading">
            <div>
              <span class="home-kicker">START FROM</span>
              <h2 id="home-templates-title">A shape that already works</h2>
            </div>
          </header>

          <ul class="home-grid" data-testid="home-templates">
            <li v-for="template in templates" :key="template.id">
              <button
                class="home-card"
                type="button"
                :data-testid="`home-template-${template.id}`"
                @click="emit('openTemplate', template.id)"
              >
                <GraphThumbnail class="home-card-spine" :document="template.document" />
                <span class="home-card-name">{{ template.title }}</span>
                <span class="home-card-blurb">{{ template.blurb }}</span>
                <span class="home-card-meta">
                  <span class="home-pill is-template">template</span>
                  <span class="home-card-count">
                    <GitBranch :size="12" aria-hidden="true" />{{ template.document.nodes.length }} nodes
                  </span>
                </span>
              </button>
            </li>
          </ul>
        </section>
      </div>
    </main>
  </div>
</template>
