<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowRight, Clock3, FilePlus2, GitBranch, History, Loader, Play, TriangleAlert } from 'lucide-vue-next'
import AccountChip from '../components/builder/AccountChip.vue'
import BrandLockup from '../components/BrandLockup.vue'
import GraphThumbnail from '../components/builder/GraphThumbnail.vue'
import { PRODUCT_NAME, PRODUCT_SENTENCE } from '../data/brand'
import { ALL_BUILDER_TEMPLATES } from '../data/builderTemplates'
import { readRunHandoff, writeRunHandoff } from '../data/builderRunHandoff'
import { askToRevealHistory } from '../components/RunHistory.vue'
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

/**
 * The stored run pointer, or null. Guarded: site data can be blocked outright.
 *
 * `workflowId` comes back beside the run id because the LAST RUN card has to
 * name the workflow (item 3, and WA's own follow-up on R4): the card read
 * `LAST RUN / Finished / Open it`, which says a run happened and not what it
 * was. `GET /api/runs/{id}` answers a `RunSnapshot`, which carries a status and
 * no workflow at all - so the name is a lookup, and this is the only carrier of
 * the key to look it up by.
 */
function storedRunPointer(): { runId: string; workflowId: string } | null {
  try {
    const raw = globalThis.localStorage?.getItem(scopedKey(ACTIVE_RUN_STORAGE_KEY, identity.value))
    if (!raw) return null
    const parsed = JSON.parse(raw) as { version?: number; runId?: string; workflowId?: string }
    if (parsed.version !== 1 || !parsed.runId) return null
    return { runId: parsed.runId, workflowId: parsed.workflowId ?? '' }
  } catch {
    return null
  }
}

const TERMINAL_RUN_STATUSES: readonly RunStatus[] = ['completed', 'error', 'cancelled']

/** The run the console left behind, once the server has been asked about it. */
const lastRun = ref<{ id: string; status: RunStatus; workflowId: string } | null>(null)
const checkingPointer = ref(false)

async function resolvePointer(): Promise<RunPointerState> {
  const pointer = storedRunPointer()
  if (!pointer) return 'none'
  const id = pointer.runId
  checkingPointer.value = true
  try {
    await studioApi.initialize()
    const snapshot = await studioApi.getRun(id)
    lastRun.value = { id, status: snapshot.status, workflowId: pointer.workflowId }
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

/**
 * The card the home shows for a finished run: history, not a hand-over.
 *
 * It NAMES THE WORKFLOW now. This page already holds both lists the name can
 * come from - the library it fetched and the built-in it read - so the lookup
 * costs no request; a workflow that has since been deleted, or a pointer
 * written before this field existed, falls back to a heading that is at least
 * true. The status keeps its own line either way, because "Finished" is the
 * other half of what the card says and losing it would trade one gap for
 * another.
 */
const lastRunCard = computed(() => {
  const run = lastRun.value
  if (!run || !TERMINAL_RUN_STATUSES.includes(run.status)) return null
  const named =
    run.workflowId === validatorGraph.value.id
      ? validatorGraph.value.name
      : library.value.find((row) => row.id === run.workflowId)?.name ?? ''
  return { id: run.id, name: named || 'Your last run', display: runStatusDisplay(run.status) }
})

/**
 * `Run history`, which opens the console with the list revealed.
 *
 * The list lives at the bottom of the console's control rail and always has;
 * what the home lacked was any mention of runs at all (AUDIT-R2 H2, and half of
 * the Q5 FAIL). The hint is a one-shot `sessionStorage` note that `RunHistory`
 * itself declares and `StudioView` consumes on its next mount - see
 * `RunHistory.vue`'s own block for why it is not a route field.
 */
function openRunHistory(): void {
  askToRevealHistory()
  emit('run')
}

/**
 * A saved workflow can be RUN from this page, not only opened for editing.
 *
 * Two conditions, and the second is not caution. `status === 'published'`
 * because a run resolves a REGISTERED version; and the document must have
 * arrived, because the handoff has to carry `input_field` - the key `inputs`
 * must use - and the LIST endpoint is a summary that does not carry it. The
 * document is already being fetched for the thumbnail, so this costs no extra
 * request; a row whose picture has not landed yet simply does not offer Run
 * until it has, which is honest rather than a button that would 422.
 */
function runnableDocument(entry: BuilderDocumentSummary): BuilderDocument | null {
  if (entry.status !== 'published') return null
  return thumbnails.value.get(entry.id) ?? null
}

/**
 * Hand the console this workflow and leave - the same handoff, and the same
 * three fields, that `BuilderView.runPublished` and the publish dialog write.
 */
function runDocument(entry: BuilderDocumentSummary, document: BuilderDocument): void {
  writeRunHandoff(
    { workflowId: entry.id, inputField: String(document.input_field), name: entry.name },
    identity.value,
  )
  emit('run')
}

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
        The STATIC lockup, the same one the sign-in wall and the splash use, and
        for the same reason: there is nowhere to go back to from here, and the
        product name IS this page's heading. A `link` lockup would be an anchor
        to the page it is already on, and its `<h1>` slot would have nothing to
        hold - the home is a list of workflows rather than one of them.
      -->
      <BrandLockup as="static" />

      <div class="header-context">
        <AccountChip v-if="user" :user="user" @sign-out="emit('signOut')" />
      </div>
    </header>

    <main class="home-main">
      <div class="home-page">
        <!--
          WHAT THIS IS, before what is in it (ROUND-2 X2, §5 ruling 2).

          The sentence is not new and it is not written here: `PRODUCT_SENTENCE`
          is the sign-in wall's own lede, and until now the wall was the only
          place it appeared - so a person who had an account never read the one
          line that says what the product does. AUDIT-R2 H1 measured that as the
          highest-value change in the document and the cheapest: it is a move,
          not a write.

          It sits under the header's brand rather than inside it. The header is
          the shell's, shared with every other surface; this line is about this
          page, and a lockup that grew a subtitle on one route only would be a
          second lockup.
        -->
        <p class="home-lede" data-testid="product-sentence">{{ PRODUCT_SENTENCE }}</p>

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
            <!--
              THE WORKFLOW, not the status (item 3). The heading was
              `{{ display.label }}`, so the card read `LAST RUN / Finished /
              Open it` - three lines that say a run happened and never what it
              was about. The state keeps its own line below, because "Finished"
              is the other half of what this card says.
            -->
            <h2 id="home-last-run-title">{{ lastRunCard.name }}</h2>
            <p class="home-last-run-state">{{ lastRunCard.display.label }}</p>
          </div>
          <!--
            `Open it` stays FIRST. `console-identity.spec.ts` asks for it by
            name and `home.spec.ts` takes the strip's first button, and it is
            the primary action here either way.
          -->
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
            <!--
              The way back to a run from yesterday (item 3, ROUND-2 ruling 3,
              AUDIT-R2 H2). It sits in THIS section rather than beside the LAST
              RUN card because the card only exists while a pointer does - and
              the pointer is this browser's, cleared by a sign-out and by a
              second person - while the list on the console is the account's and
              is always there. A route that appears and disappears is not a
              route a reader can rely on.
            -->
            <button
              class="button button-quiet"
              type="button"
              data-testid="home-run-history"
              @click="openRunHistory()"
            >
              <History :size="14" aria-hidden="true" /> Run history
            </button>
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
                <!-- X2: every card names its action. A span rather than a
                     button, because the card IS the button - the same shape the
                     template cards use. -->
                <span class="home-card-action">
                  Run
                  <ArrowRight :size="13" aria-hidden="true" />
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

          <!--
            TWO ACTIONS ON ONE CARD, which is why this cell is shaped the way it
            is (item 3). A saved workflow can be edited and, once it is
            published, run - and two actions cannot both be a span inside one
            button the way the single-action cards do it. So the card keeps the
            whole cell as its own click target and its own action name, and the
            second action is a REAL button beside it, layered over the card's
            bottom-right corner. Nested buttons are invalid HTML; siblings are
            not, and this is the one card that needs two.
          -->
          <ul v-else class="home-grid" data-testid="home-library">
            <li v-for="entry in orderedLibrary" :key="entry.id" class="home-cell">
              <button
                class="home-card"
                type="button"
                :class="{ 'is-runnable': runnableDocument(entry) }"
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
                <span class="home-card-action">
                  Open in Build
                  <ArrowRight :size="13" aria-hidden="true" />
                </span>
              </button>
              <button
                v-if="runnableDocument(entry)"
                class="home-card-run"
                type="button"
                :data-testid="`home-run-${entry.id}`"
                :aria-label="`Run ${entry.name}`"
                :title="`Run ${entry.name}`"
                @click="runDocument(entry, runnableDocument(entry)!)"
              >
                <Play :size="13" aria-hidden="true" />
                Run
              </button>
            </li>
          </ul>
        </section>

        <section class="home-section" aria-labelledby="home-templates-title">
          <header class="home-heading">
            <!--
              The gallery's three strings, verbatim (ROUND-2 §5 ruling 4). The
              home's template shelf and the builder's ARE the same shelf, and
              the audit's C3 table named "two copies of the same section with
              different words" as the reason a reader cannot tell the two pages
              apart.
            -->
            <div>
              <span class="home-kicker">TEMPLATES</span>
              <h2 id="home-templates-title">Start from a working example</h2>
              <p class="home-section-lede">Click one to copy it onto the canvas as a new workflow.</p>
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
                <!-- X2: every card names its action. A span, because the card
                     is the button - see TemplateGallery for the whole reason. -->
                <span class="home-card-action">
                  Use this template
                  <ArrowRight :size="13" aria-hidden="true" />
                </span>
              </button>
            </li>
          </ul>
        </section>
      </div>
    </main>
  </div>
</template>
