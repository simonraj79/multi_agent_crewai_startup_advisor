<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  ArrowRight,
  Clock3,
  Copy,
  Download,
  FilePlus2,
  History,
  Loader,
  Trash2,
  TriangleAlert,
  Unplug,
  Upload,
} from 'lucide-vue-next'
import TemplateCard from './TemplateCard.vue'
import { ALL_BUILDER_TEMPLATES, documentFromTemplate } from '../../data/builderTemplates'
import { TEMPLATE_CATEGORIES } from '../../data/templateCategories'
import type { TemplateCategoryId } from '../../data/templateCategories'
import { loadModels } from '../../data/models'
import { BuilderConflictError, builderApi } from '../../services/builderApi'
import type { BuilderApiLike } from '../../services/builderApi'
import type { BuilderTemplate } from '../../data/builderTemplates'
import type { BuilderDocumentSummary } from '../../types/builder'
import { agoFrom, parseStamp } from '../../utils/storedTime'

/**
 * The builder's empty state, and the one screen a first-time author reads.
 *
 * Two jobs, and they are the same job: start something. Four templates on the
 * dot grid above the graphs this account already has, newest first. There is no
 * search, no folder and no tag (cut list item 13) - a flat list, because the
 * thing that makes a gallery hard to use at four items is chrome, not order.
 *
 * WHY IT ASKS THE SERVER WHAT ITS OWN TEMPLATES COST. Every card's price and
 * billable count come from `POST /api/builder/validate` over that template's
 * own document, fired once on mount. Writing the figures in would have been one
 * line each and they are already measured - and this repo has now recorded five
 * separate occasions where a number written into prose was wrong within two
 * commits. `bounds.py` and `budget.py` own those figures; the gallery renders
 * what they answer. The node and edge counts are the only numbers computed
 * here, and they are `document.nodes.length` and `document.edges.length`:
 * descriptions of the document rather than any of `bounds.py`'s counts (R6).
 *
 * WHY EACH CARD SAYS WHAT IT TEACHES. A gallery of graphs is a gallery of
 * pictures, and a picture of a flow does not say why anybody would draw it.
 * `teaches` and `modifyFirst` come off the template module verbatim; between
 * them they answer the two questions somebody landing here actually has, which
 * are what is this for and what do I touch first.
 *
 * THE MODEL ROSTER LOADS BEFORE THE PRICES. The four pattern templates name
 * their models by ROLE, and `documentFromTemplate` resolves those against the
 * served roster - so pricing a template before the roster has arrived would
 * price a document naming `{{workhorse}}`, which the server answers
 * `model-unknown` for. `loadModels()` is awaited first, and it is the same
 * single in-flight request every model picker shares.
 */

const props = withDefaults(
  defineProps<{
    /** Injected so a spec can drive the two requests without a server. */
    api?: BuilderApiLike
    /**
     * `POST .../unpublish`, the remedy a delete's 409 names (D-15-10). Its own
     * prop rather than a member of `api`, because `BuilderApiLike` is the Pick
     * three test doubles are compiler-forced to match and plan 15 criterion 11
     * says one of them passes unchanged.
     */
    unpublish?: (id: string) => Promise<unknown>
  }>(),
  { api: () => builderApi, unpublish: () => (id: string) => builderApi.unpublish(id) },
)

const emit = defineEmits<{
  /** Seed this template into the store as an ordinary unsaved draft. */
  start: [template: BuilderTemplate]
  /** Load a stored document by id. */
  open: [documentId: string]
  /**
   * The three actions the document bar's menu offers, from the row (D-15-15).
   *
   * Each carries a document id and `BuilderView` opens it on the way, so the
   * author acts on a graph they can see. Performed there rather than here
   * because that is where duplicate, export and the version rail already
   * live, and two implementations of "duplicate this graph" would be two
   * things to keep in step.
   */
  duplicate: [documentId: string]
  export: [documentId: string]
  versions: [documentId: string]
  /**
   * A `.builder.json` the author picked (plan 15 D2). The gallery only hands
   * the file up: reading it, posting it and opening the result is one code
   * path in `BuilderView`, shared with the document bar's Import item.
   */
  import: [file: File]
}>()

/**
 * The cards of one section, in gallery order.
 *
 * Derived from `category` on the template rather than from a list kept here, so
 * a card cannot be in two sections or in none, and adding a template is a data
 * change rather than a change to this file. `ALL_BUILDER_TEMPLATES` is already
 * in gallery order, so `filter` preserves it and no sort is needed.
 */
function cardsIn(id: TemplateCategoryId) {
  return ALL_BUILDER_TEMPLATES.filter((template) => template.category === id)
}

/**
 * Scroll a section into view inside the GALLERY'S OWN scroller.
 *
 * NOT an `href="#gallery-section-route"`. The fragment belongs to the hash
 * router: `workspaceRoute('#gallery-section-route')` matches neither `run` nor
 * `build` and falls to the HOME (`useWorkspaceRoute.ts`), so an anchor link
 * would leave the builder every time it was pressed - and a middle-click would
 * open a new tab on the wrong screen. Buttons in a `<nav>` cannot produce a
 * wrong URL, are in the tab order with no `tabindex` of their own, and do
 * exactly what they say.
 *
 * Focus moves to the section, so a keyboard reader lands where the scroll went
 * rather than continuing from the jump list. The section carries
 * `tabindex="-1"` for that and nothing else.
 */
function jumpTo(id: TemplateCategoryId): void {
  const section = document.getElementById(`gallery-section-${id}`)
  if (!section) return
  section.scrollIntoView({ block: 'start', behavior: 'smooth' })
  section.focus({ preventScroll: true })
}

/** What the server said one template costs, or why it did not say. */
interface Priced {
  readonly billable: number
  readonly floorUsd: number
  readonly staticUsd: number
}

const priced = reactive(new Map<string, Priced>())
const pricingProblem = ref('')
const pricing = ref(true)

const library = ref<BuilderDocumentSummary[]>([])
const libraryProblem = ref('')
const libraryLoading = ref(true)

/** Which row is mid-deletion, and what the author has typed to confirm it. */
const deleting = ref<string | null>(null)
const typedName = ref('')
const deleteProblem = ref('')
const deleteInFlight = ref(false)
/** The 409: a version is still registered, and only Unpublish lifts it. */
const deleteRefused = ref(false)
const unpublishing = ref(false)

const filePicker = ref<HTMLInputElement | null>(null)

/** Hand the file up and clear the input, so the same file can be picked twice. */
function onFilePicked(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) emit('import', file)
}

/**
 * One clock for the whole list, ticking, so "2 min ago" becomes "3 min ago"
 * without a reload. Thirty seconds is the resolution the relative form has
 * above a minute, so a faster tick would redraw for nothing.
 */
const now = ref(Date.now())
let ticker = 0

onMounted(() => {
  void priceTemplates()
  void loadLibrary()
  ticker = window.setInterval(() => {
    now.value = Date.now()
  }, 30_000)
})

onBeforeUnmount(() => window.clearInterval(ticker))

/**
 * Price every template at once, both rows.
 *
 * `allSettled`, not `all`: one template failing to validate must not blank the
 * prices of the others, and the failure that matters here is the network rather
 * than the document - every one of them is known to validate clean.
 *
 * `documentFromTemplate` rather than `template.document`, because that is what
 * resolves the model roles and it is also exactly what the author gets when
 * they click the card. Pricing the unresolved singleton would price a graph
 * nobody can run.
 */
async function priceTemplates(): Promise<void> {
  pricing.value = true
  await loadModels()
  const answers = await Promise.allSettled(
    ALL_BUILDER_TEMPLATES.map(async (template) => {
      const result = await props.api.validate(documentFromTemplate(template))
      return { id: template.id, budget: result.budget }
    }),
  )
  let failure = ''
  for (const answer of answers) {
    if (answer.status === 'rejected') {
      failure =
        answer.reason instanceof Error ? answer.reason.message : 'the server did not answer'
      continue
    }
    const budget = answer.value.budget
    if (!budget) {
      // A 200 with no `budget` block is a contract violation rather than a
      // refusal, and it is the shape a stale build or an interposed proxy
      // produces. Reading through it threw inside a `void`-ed promise, which
      // surfaces as an unhandled rejection and a gallery of blank cards with
      // nothing anywhere saying why. Reported as a missing price, which is what
      // it is.
      failure = 'the server answered without a budget'
      continue
    }
    priced.set(answer.value.id, {
      billable: budget.billable_nodes,
      floorUsd: budget.floor_cost_usd,
      staticUsd: budget.static_cost_usd,
    })
  }
  // Stated once for the gallery rather than four times on four cards. The
  // cards still open; a price nobody could fetch is missing information, not a
  // broken template.
  pricingProblem.value = failure
  pricing.value = false
}

async function loadLibrary(): Promise<void> {
  libraryLoading.value = true
  try {
    library.value = await props.api.list()
    libraryProblem.value = ''
  } catch (error) {
    libraryProblem.value =
      error instanceof Error ? error.message : 'your saved workflows could not be loaded.'
  } finally {
    libraryLoading.value = false
  }
}

/**
 * Ask to delete a row - or say why not, before the work (D-15-16).
 *
 * The row already carries the one fact that decides it: `status`. A published
 * row opens the confirm in its refused state, with the remedy rather than a
 * name box, so the author is not asked to type a name into a form whose
 * answer is known. The server is still the authority - `confirmDelete`
 * handles the 409 exactly as before, for the row this list saw as a draft
 * because somebody published it in another tab.
 */
function askToDelete(id: string): void {
  deleting.value = id
  typedName.value = ''
  const row = library.value.find((entry) => entry.id === id)
  if (row?.status === 'published') {
    deleteRefused.value = true
    deleteProblem.value =
      `“${row.name}” is live and cannot be deleted; unpublish it first, then delete it`
    return
  }
  deleteProblem.value = ''
  deleteRefused.value = false
}

function cancelDelete(): void {
  deleting.value = null
  typedName.value = ''
  deleteProblem.value = ''
  deleteRefused.value = false
}

/**
 * Lift the 409 the way its sentence says: unpublish, then the confirm returns
 * to its asking state with the typed name kept, and the row's pill follows.
 */
async function unpublishRefused(): Promise<void> {
  const id = deleting.value
  if (!id || unpublishing.value) return
  unpublishing.value = true
  try {
    await props.unpublish(id)
    deleteRefused.value = false
    deleteProblem.value = ''
    library.value = library.value.map((entry) =>
      entry.id === id ? { ...entry, status: 'draft' } : entry,
    )
  } catch (error) {
    deleteProblem.value =
      error instanceof Error ? error.message : 'the workflow could not be unpublished.'
  } finally {
    unpublishing.value = false
  }
}

/**
 * Whether the typed name matches the row being deleted.
 *
 * Trimmed and case-insensitive, because the confirmation exists to prove the
 * author read WHICH graph they are deleting - not to test their typing. An
 * exact-bytes match would fail on a trailing space pasted from the row above
 * and teach nothing.
 */
const confirmed = computed(() => {
  const row = library.value.find((entry) => entry.id === deleting.value)
  if (!row) return false
  return typedName.value.trim().toLowerCase() === row.name.trim().toLowerCase()
})

async function confirmDelete(): Promise<void> {
  const id = deleting.value
  if (!id || !confirmed.value || deleteInFlight.value) return
  deleteInFlight.value = true
  try {
    await props.api.remove(id)
    library.value = library.value.filter((entry) => entry.id !== id)
    cancelDelete()
  } catch (error) {
    deleteProblem.value =
      error instanceof Error ? error.message : 'the workflow could not be deleted.'
    deleteRefused.value = error instanceof BuilderConflictError
  } finally {
    deleteInFlight.value = false
  }
}

/** `2026-09-02T10:14:00Z` -> `2 Sep, 10:14`. Undated rows show the raw value. */
/**
 * A relative time, not a clipped clock (D-15-15).
 *
 * Three rows all read "3 Sept, 07:47" and could not be ordered by eye, which
 * is the same defect the version rows had (D-15-3) and is fixed the same way:
 * `agoFrom` keeps seconds under a minute, which is the resolution two rows
 * saved in one minute actually need, and falls back to the dated form once
 * relative stops being useful. It also reads a naive SQLite stamp as UTC,
 * which `Date.parse` here did not - every row was eight hours out on the
 * machine that found it.
 */
function when(iso: string): string {
  return agoFrom(iso, now.value)
}

/** The full stamp, seconds included, for the row's title. */
function exactly(iso: string): string {
  const at = parseStamp(iso)
  if (!Number.isFinite(at)) return iso
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(at)
}

/**
 * Newest first (D-15-15).
 *
 * The server returns the library in its own order; the author's question is
 * "where is the one I was just working on", and that is the top of this list.
 * An unreadable stamp sorts last rather than throwing the order away.
 */
const orderedLibrary = computed(() =>
  [...library.value].sort((left, right) => {
    const at = parseStamp(right.updated_at)
    const other = parseStamp(left.updated_at)
    return (Number.isFinite(at) ? at : -Infinity) - (Number.isFinite(other) ? other : -Infinity)
  }),
)
</script>

<template>
  <!--
    THE AUTHOR'S OWN GRAPHS FIRST (D-15-15). Four template cards occupied
    y147-595, so "Saved here" began at y659 and showed two and a half rows of
    the thing the author came back for. This is the first screen of the
    product and the templates are for the first visit only.

    A real DOM move rather than a CSS `order`, because `order` reorders the
    picture and leaves the reading order alone - a screen reader and a Tab
    press would still meet four templates before the author's own work.

    The empty case reads correctly in this order too: one line saying there is
    nothing saved yet, immediately above the shapes that fix that, which is
    why its copy now says "below".
  -->
  <div class="template-gallery">
    <section class="gallery-library" aria-labelledby="gallery-library-title">
      <header class="gallery-heading">
        <div>
          <span class="gallery-kicker">YOUR WORKFLOWS</span>
          <h2 id="gallery-library-title">Saved here</h2>
        </div>
      </header>

      <p v-if="libraryLoading" class="gallery-empty" role="status">
        <Loader :size="14" aria-hidden="true" /> Reading your saved workflows…
      </p>
      <p v-else-if="libraryProblem" class="gallery-empty is-problem" role="alert">
        <TriangleAlert :size="14" aria-hidden="true" /> {{ libraryProblem }}
      </p>
      <p v-else-if="library.length === 0" class="gallery-empty">
        <FilePlus2 :size="14" aria-hidden="true" />
        Nothing saved yet. Pick a template below and it is yours the moment you save it.
      </p>

      <ul v-else class="library-list">
        <li v-for="entry in orderedLibrary" :key="entry.id">
          <div class="library-row">
            <button class="library-open" type="button" @click="emit('open', entry.id)">
              <!-- Two lines before it clips, whole name in the title (D-15-4). -->
              <span class="library-name" :title="entry.name">{{ entry.name }}</span>
              <span class="library-meta">
                <span class="status-pill" :class="`is-${entry.status}`">{{ entry.status }}</span>
                <!--
                  The head's status is not the whole truth. `save` returns a
                  published head to `draft` while the service keeps serving the
                  older version whose budget was priced, so a row reading
                  `draft v2` can be answering launches from v1 - and until this
                  chip existed the gallery drew it identically to a graph that
                  had never been published. Only shown when the live version is
                  BEHIND head; when it is the head, the `published` pill beside
                  it has already said so.
                -->
                <span
                  v-if="entry.live_version !== null && entry.live_version !== entry.version"
                  class="live-pill"
                  :title="`v${entry.live_version} is answering launches while head is v${entry.version}`"
                >v{{ entry.live_version }} live</span>
                <span class="library-version">v{{ entry.version }}</span>
                <!--
                  Relative text, exact stamp on hover (D-15-15). The relative
                  form is what makes the list readable at a glance, and the
                  ORDER is what makes it unambiguous - but two rows four hours
                  old both read "4 h ago", so the precise stamp has to be
                  reachable. `VersionBrowser` makes the same pair.
                -->
                <span class="library-when" :title="exactly(entry.updated_at)">
                  <Clock3 :size="12" aria-hidden="true" />{{ when(entry.updated_at) }}
                </span>
              </span>
            </button>
            <!--
              WHAT THE DOCUMENT BAR'S MENU OFFERS (D-15-15). The row used to
              expose a trash icon and nothing else, so duplicate, export and
              versions each cost an open first - and the only thing reachable
              in one click from the list was the destructive one.

              These four are emitted rather than performed: `BuilderView`
              already owns duplicate, export and the version rail for the OPEN
              document, and a second implementation here would be a second
              thing to keep in step. Each one opens the document on its way,
              which is also what makes them safe - they act on a graph the
              author is then looking at.
            -->
            <div class="library-actions">
              <!--
                THE ROW'S ACTION, NAMED (X2 ruling 3, RV4's closing note).
                "Every card names its action" was met on the home (`Run ->`,
                `Open in Build ->`) and on every template card
                (`Use this template ->`), and missed here: this row offered
                FOUR icon-only buttons and no word at all, so the one thing it
                mostly does - open the workflow - was the only action a reader
                had to guess. The whole row already opens it; this says so.

                `Open`, not `Open in Build`: the home says where it is sending
                you because it is somewhere else, and this list IS Build.

                It emits the same `open` the row does - one handler, not a
                second - and the four icons stay, because D-15-15's reason for
                them holds unchanged.
              -->
              <button
                class="library-open-action"
                type="button"
                :aria-label="`Open ${entry.name}`"
                data-testid="library-open"
                @click="emit('open', entry.id)"
              >
                Open
                <ArrowRight :size="13" aria-hidden="true" />
              </button>
              <button
                class="icon-button"
                type="button"
                :aria-label="`Versions of ${entry.name}`"
                title="Versions"
                data-testid="library-versions"
                @click="emit('versions', entry.id)"
              >
                <History :size="15" aria-hidden="true" />
              </button>
              <button
                class="icon-button"
                type="button"
                :aria-label="`Duplicate ${entry.name}`"
                title="Duplicate"
                data-testid="library-duplicate"
                @click="emit('duplicate', entry.id)"
              >
                <Copy :size="15" aria-hidden="true" />
              </button>
              <button
                class="icon-button"
                type="button"
                :aria-label="`Export ${entry.name}`"
                title="Export"
                data-testid="library-export"
                @click="emit('export', entry.id)"
              >
                <Download :size="15" aria-hidden="true" />
              </button>
              <!--
                18px and a hairline between the three reversible actions and
                the one that is not (D-15-26). `aria-hidden`, because the
                separation is a visual grouping and a screen reader already
                hears "Delete <name>".
              -->
              <span class="library-actions-separator" aria-hidden="true"></span>
              <button
                class="icon-button library-delete"
                type="button"
                :aria-label="`Delete ${entry.name}`"
                title="Delete"
                data-testid="library-delete"
                @click="askToDelete(entry.id)"
              >
                <Trash2 :size="15" aria-hidden="true" />
              </button>
            </div>
          </div>

          <!--
            An in-app confirmation, never `window.confirm`. Two reasons and both
            are practical: the browser dialog blocks the whole tab so the graph
            you are about to delete is hidden at the exact moment you are asked
            about it, and it cannot say WHICH graph in a way that survives a
            misread - typing the name is what proves the right row was read.
          -->
          <form v-if="deleting === entry.id" class="delete-confirm" @submit.prevent="confirmDelete">
            <!-- The server's rule in the server's words (D-15-10); see the
                 docked confirm in `BuilderView` for why the clause is shared. -->
            <label :for="`confirm-${entry.id}`">
              <!-- Derived from the row's own status (D-15-16): a published row
                   never reaches this branch, so the warning about publishing
                   is not shown over a draft it cannot apply to. -->
              <template v-if="!deleteRefused">
                Delete <strong>{{ entry.name }}</strong> and every stored version of it? This
                cannot be undone. Type <strong>{{ entry.name }}</strong> to confirm.
              </template>
              <!--
                Nothing here when refused (D-15-18). This read "Not deleted —
                it is still published." directly above the server's own
                sentence, which since round 3 names the graph and says live
                once - so the pair said published twice in two vocabularies,
                and neither of them named which graph.
              -->
            </label>
            <!--
              ABOVE the buttons, which is where the docked confirm puts it.
              The same refusal was laid out two ways - text above the buttons
              when docked, below them here - so an author who met it in both
              places had to find it twice (D-15-18).
            -->
            <p v-if="deleteProblem" :id="`confirm-problem-${entry.id}`" class="delete-problem" role="alert">
              {{ deleteProblem }}
            </p>
            <div class="delete-actions" :class="{ 'is-refused': deleteRefused }">
              <input
                v-if="!deleteRefused"
                :id="`confirm-${entry.id}`"
                v-model="typedName"
                type="text"
                autocomplete="off"
                :aria-describedby="deleteProblem ? `confirm-problem-${entry.id}` : undefined"
              />
              <button
                v-if="deleteRefused"
                class="button button-primary"
                type="button"
                :disabled="unpublishing"
                data-testid="gallery-unpublish"
                @click="unpublishRefused"
              >
                <Unplug :size="14" aria-hidden="true" />
                {{ unpublishing ? 'Unpublishing…' : 'Unpublish' }}
              </button>
              <button class="button button-quiet" type="button" @click="cancelDelete">
                {{ deleteRefused ? 'Keep it published' : 'Keep it' }}
              </button>
              <button
                v-if="!deleteRefused"
                class="button button-danger"
                type="submit"
                :disabled="!confirmed || deleteInFlight"
              >
                {{ deleteInFlight ? 'Deleting…' : 'Delete' }}
              </button>
            </div>
          </form>
        </li>
      </ul>
    </section>

    <section aria-labelledby="gallery-templates-title">
      <header class="gallery-heading">
        <!--
          WHAT IT CONTAINS, AND WHAT A CLICK DOES (ROUND-2 §5 ruling 4).

          It read `START FROM / A shape that already works`, which the audit
          called a good sentence and a bad label: it names no category, and it
          is the heading the owner's question - "Gallery, what does it contain"
          - is literally about. Nothing anywhere said that a click COPIES the
          card onto the canvas as a new, unsaved workflow, which is what it
          does, so the one thing a reader needed to know before pressing was the
          one thing the screen never said.

          The good sentence survives as the heading; `TEMPLATES` is the label.
          The home's template section carries the same three strings verbatim -
          they are two views of one shelf, and the audit's C3 comparison named
          "two copies of the same section with different words" as the reason a
          reader cannot tell the two pages apart.
        -->
        <div>
          <span class="gallery-kicker">TEMPLATES</span>
          <h2 id="gallery-templates-title">Start from a working example</h2>
          <p class="gallery-lede">Click one to copy it onto the canvas as a new workflow.</p>
          <!--
            The one property of the whole shelf, said once (D1): human approval
            is not a category, because almost every card has it. Its own class
            rather than a second `.gallery-lede`, because ruling 4 binds that
            sentence by name and three suites assert there is exactly one of it.
          -->
          <p class="gallery-note">Most of these stop and ask a person before they spend anything.</p>
        </div>
        <div class="gallery-heading-aside">
          <p v-if="pricingProblem" class="gallery-notice" role="status">
            <TriangleAlert :size="13" aria-hidden="true" />
            Prices are unavailable — {{ pricingProblem }}
          </p>
          <!-- The file picker is the browser's own. `accept` is a hint;
               `readExportFile` in the shell is the check. -->
          <button
            class="button button-quiet gallery-import"
            type="button"
            data-testid="gallery-import"
            @click="filePicker?.click()"
          >
            <Upload :size="14" aria-hidden="true" />
            Import .builder.json
          </button>
          <input
            ref="filePicker"
            class="gallery-file-picker"
            type="file"
            accept=".json,application/json"
            tabindex="-1"
            aria-hidden="true"
            data-testid="gallery-import-file"
            @change="onFilePicked"
          />
        </div>
      </header>

      <!--
        THE JUMP LIST (D7). Navigation, not a filter, a tag, a folder or a
        search box - cut-list 13 and R15 both stand, and nothing here hides a
        card or narrows the list. Six buttons that move the scroller.

        Buttons rather than `href="#..."` anchors because the fragment is the
        hash router's (see `jumpTo`). The section title is the label and the
        category's promise is the tooltip, so the same six words do not have to
        carry both jobs.
      -->
      <nav class="gallery-jump" aria-label="Jump to a section of the gallery">
        <button
          v-for="category in TEMPLATE_CATEGORIES"
          :key="category.id"
          class="gallery-jump-link"
          type="button"
          :data-testid="`gallery-jump-${category.id}`"
          :title="category.promise"
          @click="jumpTo(category.id)"
        >{{ category.title }}</button>
      </nav>

      <!--
        ONE SECTION PER CATEGORY, in the order `templateCategories.ts` declares
        (D1). The order is the progression both sources recommend - one worker,
        a line, a fork, side by side, a check, a team - and it is read from the
        contract rather than restated here, so the gallery cannot disagree with
        the Python test that asserts it.

        The heading is a pair: what the shelf is, and the question a person is
        asking when it is the right shelf. The question is what makes this a
        gallery somebody can navigate without knowing the word for what they
        want.
      -->
      <section
        v-for="category in TEMPLATE_CATEGORIES"
        :key="category.id"
        :id="`gallery-section-${category.id}`"
        class="gallery-section"
        tabindex="-1"
        :aria-labelledby="`gallery-section-${category.id}-title`"
      >
        <header class="gallery-section-heading">
          <h3 :id="`gallery-section-${category.id}-title`">{{ category.title }}</h3>
          <p class="gallery-section-question">{{ category.question }}</p>
        </header>

        <ul class="template-grid">
          <li v-for="template in cardsIn(category.id)" :key="template.id">
            <TemplateCard
              :template="template"
              :price="priced.get(template.id) ?? null"
              :pricing="pricing"
              @start="emit('start', $event)"
            />
          </li>
        </ul>
      </section>

      <!--
        DECLINED IN WRITING, NOT OMITTED (D6).

        Four shapes both sources name that this runtime cannot honestly draw. A
        gallery that simply left them out would read as a gallery that had not
        heard of them, and the next person would draw one anyway and call a
        coordinator a swarm. Each sentence says what it is and why it is not
        here; none of them is a promise.
      -->
      <aside class="gallery-declined" aria-labelledby="gallery-declined-title">
        <h3 id="gallery-declined-title">Not in this gallery</h3>
        <ul>
          <li>
            A swarm, or a team that talks peer to peer. Those connections are
            decided while it runs, so a drawn one is a coordinator wearing the
            name.
          </li>
          <li>
            A publish and subscribe inbox. Waiting for the first of several
            branches cancels the others, so it is a race, not a queue.
          </li>
          <li>
            A lead that invents its own team while it runs. Every roster here is
            fixed when it is drawn.
          </li>
          <li>
            A workflow other agents can call as a tool server. Nothing here
            listens for that; agents in these templates consume tool servers,
            through the inspector.
          </li>
        </ul>
      </aside>
    </section>
  </div>
</template>

<style scoped>
/*
 * CONVERGED ON THE HOME SHELF'S SYSTEM (plan 16 criterion 12).
 *
 * This block used the raw size steps (`--fs-11/12/13/15`) and literal pixels
 * for almost every gap and pad, while `studio.css`'s `.home-*` block - the same
 * shelf, one route away - used the semantic type roles and the spacing scale.
 * `docs/design.md` calls a literal px in `padding`, `margin` or `gap` a bug,
 * and two shelves styled to two systems is how "improve the UI/UX as the
 * gallery grows" turns into a choice nobody made. The home is the reference
 * because it is the compliant one. No token was added; colours, radii, borders
 * and the card silhouette are untouched.
 *
 * Two `--fs-*` survive on purpose and neither has a role: the card action's
 * `600 var(--fs-12)/1.2` (byte-identical to `.home-card-action`, which is the
 * thing it must match) and the fact strip's 12px mono figure, which sits
 * between `--type-meta` at 11 and `--type-metric` at 15.
 */
.template-gallery {
  display: grid;
  gap: var(--space-8);
  align-content: start;
  width: min(1080px, 100%);
  max-height: 100%;
  overflow: auto;
  /* The head is shallower than the sides and the foot deeper than both: every
     pixel above the first card is a pixel the card's action needs to clear the
     fold, and a last row flush against the end of the scroller reads as a
     clipped page. */
  padding: var(--space-6) var(--space-8) calc(var(--space-8) + var(--space-6));
  margin: 0 auto;
}

.gallery-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-6);
  margin-bottom: var(--space-5);
}

.gallery-kicker { color: var(--on-accent-cyan); font: var(--type-kicker); letter-spacing: var(--track-kicker); }
.gallery-heading h2 { margin: var(--space-1) 0 0; font: var(--type-title); }

/* The sentence that says what a click does. Under the heading rather than on
   each card: it is true of every card, and thirteen copies of one sentence is
   thirteen places for it to go stale. */
.gallery-lede { margin: var(--space-1) 0 0; max-width: 56ch; color: var(--text-muted); font: var(--type-body); }
.gallery-note { margin: var(--space-1) 0 0; max-width: 56ch; color: var(--text-40); font: var(--type-label); }
.gallery-notice { display: inline-flex; gap: var(--space-2); align-items: center; margin: 0; color: var(--warn-text); font: var(--type-label); }
.gallery-heading-aside { display: flex; flex-wrap: wrap; gap: var(--space-5); align-items: center; justify-content: flex-end; }
.gallery-import { min-height: 32px; padding: 0 var(--space-5); font: var(--type-label); }
.gallery-file-picker { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); opacity: 0; pointer-events: none; }

/* 640, the width at which the shell already stops reserving a page (studio.css
   names the number and why). The heading and its aside share a row down to
   here; below it the row is too narrow for both, and the measured symptom was
   the note wrapping around an Import button that had itself wrapped to
   "Import / .builder.json". They stack, and the button keeps its label on one
   line. */
@media (max-width: 640px) {
  .gallery-heading { flex-direction: column; align-items: stretch; }
  .gallery-heading-aside { justify-content: flex-start; }
  .gallery-import { white-space: nowrap; }
}

/* THE JUMP LIST. A row of six, wrapping, quiet: it is a way to get down the
   page, not a control that changes what is on it, and styling it as a filter
   bar would promise a filter (cut-list 13). */
.gallery-jump {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  /* Pulled up under the shelf heading it belongs to, and pushed down off the
     first section heading it does not: the chips sat directly on "Start here"
     and read as that section's own controls. */
  margin-top: calc(-1 * var(--space-4));
  margin-bottom: var(--space-4);
}

.gallery-jump-link {
  padding: var(--space-2) var(--space-4);
  color: var(--text-muted);
  font: var(--type-label);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--r-pill);
  cursor: pointer;
  transition: color var(--motion-fast) ease, border-color var(--motion-fast) ease;
}

.gallery-jump-link:hover { color: var(--text-title); border-color: var(--border-hover); }
.gallery-jump-link:focus-visible { outline: 2px solid var(--on-accent-cyan); outline-offset: 2px; }

/* One shelf. `scroll-margin-top` keeps the heading clear of the scroller's own
   top edge when `jumpTo` lands on it - without it the title sits flush and
   reads as the top of the page rather than the top of a section.

   The step between shelves is bigger than the step inside one, or six sections
   read as one long list of cards with headings sprinkled through it. The
   gallery's own grid gap is the inside step; this is the outside one. */
.gallery-section {
  display: grid;
  gap: var(--space-5);
  scroll-margin-top: var(--space-5);
}

.gallery-section + .gallery-section { margin-top: var(--space-6); }

/* The section is focused by `jumpTo` so a keyboard reader lands here; the ring
   would be a box round the whole shelf, which says nothing a heading does not. */
.gallery-section:focus { outline: none; }

.gallery-section-heading { display: grid; gap: var(--space-1); }
.gallery-section-heading h3 { margin: 0; color: var(--text-title); font: var(--type-title); }

/* The question a person is asking when this is the right shelf. It is the
   index of this gallery: the headings are two words each and this is what
   tells you whether those two words mean your problem. */
.gallery-section-question { margin: 0; max-width: 56ch; color: var(--text-muted); font: var(--type-label); }

.template-grid {
  display: grid;
  /* The home's `.home-grid` track, to the pixel, so the two screens line their
     cards up at every width instead of each finding its own column count. */
  gap: var(--space-5);
  grid-template-columns: repeat(auto-fill, minmax(232px, 1fr));
  padding: 0;
  margin: 0;
  list-style: none;
}

/* What is NOT here, and why (D6). A quiet block at the foot rather than a card
   in the grid: these are not templates and a tile among tiles would read as
   four more things to click. */
.gallery-declined {
  padding: var(--space-5) var(--space-6);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--r-2xl);
}

.gallery-declined h3 { margin: 0; color: var(--text-title); font: var(--type-title); }

.gallery-declined ul {
  display: grid;
  gap: var(--space-2);
  max-width: 78ch;
  padding: 0 0 0 var(--space-6);
  margin: var(--space-3) 0 0;
  color: var(--text-40);
  font: var(--type-label);
}

.gallery-empty {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  margin: 0;
  padding: var(--space-5);
  color: var(--text-muted);
  font: var(--type-label);
  background: var(--surface-panel);
  border: 1px dashed var(--border-default);
  border-radius: var(--r-lg);
}

.gallery-empty.is-problem { color: var(--err-text); background: var(--err-bg); border-color: var(--err-border); border-style: solid; }

.library-list { display: grid; gap: var(--space-3); padding: 0; margin: 0; list-style: none; }

.library-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-3);
  align-items: center;
  padding: var(--space-1) var(--space-3) var(--space-1) var(--space-1);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--r-lg);
}

.library-open {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
  padding: var(--space-3) var(--space-4);
  text-align: left;
  color: var(--text-body);
  background: transparent;
  border: 0;
  border-radius: var(--r-md);
  cursor: pointer;
}

.library-open:hover { background: var(--surface-raised); }
.library-name {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  color: var(--text-title);
  font-size: var(--fs-13);
  font-weight: 600;
  line-height: 1.3;
  overflow-wrap: anywhere;
  white-space: normal;
}
.library-meta { display: flex; flex-wrap: wrap; gap: var(--space-4); align-items: center; color: var(--text-40); font: var(--type-meta); }
.library-when { display: inline-flex; gap: var(--space-1); align-items: center; }

/* The home's `.home-pill` shorthand, so one status pill does not read as two
   different components on two routes. */
.status-pill { padding: var(--space-1) var(--space-2); font: var(--type-kicker); letter-spacing: var(--track-kicker); text-transform: uppercase; border-radius: var(--r-pill); }
.status-pill.is-draft { color: var(--text-muted); background: var(--surface-raised); }
.status-pill.is-published { color: var(--on-accent-mint); background: color-mix(in srgb, var(--accent-mint) 14%, transparent); }
/* Same weight and shape as the status pill beside it - it is a status too,
   about a different version. Cyan rather than mint so "live, and it is not
   what you are editing" reads as distinct from "this head is published". */
.live-pill { padding: var(--space-1) var(--space-2); font: var(--type-kicker); letter-spacing: var(--track-kicker); text-transform: uppercase; border-radius: var(--r-pill); color: var(--on-accent-cyan); background: color-mix(in srgb, var(--accent-cyan) 14%, transparent); }

/* The row's four actions (D-15-15). `auto` in the row's own grid, so the name
   keeps every pixel the actions do not need.

   D-15-26: four 28px glyphs in a 2px row, with Delete 34px from Export and
   drawn in the same colour and weight as the three safe ones - so the
   irreversible action was two pixels of icon away from the reversible one it
   sits beside. The answer is `DocumentBar`'s own, from D-15-6, because this is
   the same defect on a second surface and a second answer to it would be a
   second thing to keep in step: a separator, a real gap, and the error colour
   AT REST rather than only on hover. */
.library-actions { display: inline-flex; gap: var(--space-1); align-items: center; }
/* The row's named action, in the same colour and weight `.template-action`
   uses on every template card, so the two lists' actions read as one kind of
   thing. `margin-right` puts a step between a word and the four icons rather
   than letting it read as a fifth icon with a label. */
.library-open-action {
  display: inline-flex;
  gap: var(--space-2);
  align-items: center;
  min-height: 30px;
  margin-right: var(--space-2);
  padding: 0 var(--space-2);
  color: var(--on-accent-cyan);
  font: 600 var(--fs-12)/1.2 var(--font-body);
  background: transparent;
  border: 0;
  border-radius: var(--r-md);
  cursor: pointer;
  white-space: nowrap;
}
.library-open-action:hover { background: var(--surface-raised); }
.library-actions-separator {
  width: 1px;
  align-self: stretch;
  margin: var(--space-1) var(--space-3);
  background: var(--border-default);
}
.library-delete { color: var(--err-text); }
.library-delete:hover { color: var(--err-text); background: var(--err-bg); border-color: var(--err-border); }

.delete-confirm {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-5);
  margin-top: var(--space-2);
  color: var(--text-body);
  font: var(--type-label);
  background: var(--surface-well);
  border: 1px solid var(--err-border);
  border-radius: var(--r-lg);
}

.delete-confirm label { color: var(--text-muted); }
.delete-confirm strong { color: var(--text-title); }
.delete-actions { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: var(--space-3); }
/* Refused: no text box, so the two buttons sit at the start rather than in a
   column reserved for an input that is not there. */
.delete-actions.is-refused { grid-template-columns: auto auto; justify-content: start; }
.delete-actions input {
  min-height: 38px;
  padding: 0 var(--space-4);
  color: var(--text-body);
  font: var(--type-body);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  outline: 0;
}
.delete-actions input:focus { border-color: var(--accent-cyan); box-shadow: var(--glow-input); }
.delete-actions .button { min-height: 38px; }
.button-danger { color: var(--err-text); background: var(--err-bg); border-color: var(--err-border); }
.delete-problem { margin: 0; color: var(--err-text); }
</style>
