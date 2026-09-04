<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
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
import GraphThumbnail from './GraphThumbnail.vue'
import {
  ALL_BUILDER_TEMPLATES,
  BUILDER_TEMPLATES,
  MORE_BUILDER_TEMPLATES,
  documentFromTemplate,
} from '../../data/builderTemplates'
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

const money = (value: number) => `$${value.toFixed(2)}`

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
      error instanceof Error ? error.message : 'your saved graphs could not be loaded.'
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
      error instanceof Error ? error.message : 'the graph could not be unpublished.'
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
      error instanceof Error ? error.message : 'the graph could not be deleted.'
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
          <span class="gallery-kicker">YOUR GRAPHS</span>
          <h2 id="gallery-library-title">Saved here</h2>
        </div>
      </header>

      <p v-if="libraryLoading" class="gallery-empty" role="status">
        <Loader :size="14" aria-hidden="true" /> Reading your saved graphs…
      </p>
      <p v-else-if="libraryProblem" class="gallery-empty is-problem" role="alert">
        <TriangleAlert :size="14" aria-hidden="true" /> {{ libraryProblem }}
      </p>
      <p v-else-if="library.length === 0" class="gallery-empty">
        <FilePlus2 :size="14" aria-hidden="true" />
        No saved graphs yet. Pick a shape below and it is yours the moment you save it.
      </p>

      <ul v-else class="library-list">
        <li v-for="entry in orderedLibrary" :key="entry.id">
          <div class="library-row">
            <button class="library-open" type="button" @click="emit('open', entry.id)">
              <!-- Two lines before it clips, whole name in the title (D-15-4). -->
              <span class="library-name" :title="entry.name">{{ entry.name }}</span>
              <span class="library-meta">
                <span class="status-pill" :class="`is-${entry.status}`">{{ entry.status }}</span>
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
        <div>
          <span class="gallery-kicker">START FROM</span>
          <h2 id="gallery-templates-title">A shape that already works</h2>
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

      <ul class="template-grid">
        <li v-for="template in BUILDER_TEMPLATES" :key="template.id">
          <button class="template-card" type="button" @click="emit('start', template)">
            <GraphThumbnail class="template-spine" :document="template.document" />
            <h3>{{ template.title }}</h3>
            <p class="template-blurb">{{ template.blurb }}</p>

            <!--
              The two sentences a picture cannot carry. `teaches` is why you
              would open this one; `modifyFirst` is what you do once you have.
              Both come off the module verbatim.
            -->
            <p class="template-teaches">
              <span class="template-lede">Teaches</span>{{ template.teaches }}
            </p>
            <p class="template-teaches">
              <span class="template-lede">Change first</span>{{ template.modifyFirst }}
            </p>

            <!--
              Rendered verbatim (R14). It is the difference between a template
              and a booby trap, and paraphrasing it on a card is how the
              difference gets lost.
            -->
            <p v-if="template.caveat" class="template-caveat">{{ template.caveat }}</p>

            <dl class="template-facts">
              <div>
                <dt>Nodes</dt>
                <dd>{{ template.document.nodes.length }}</dd>
              </div>
              <div>
                <dt>Edges</dt>
                <dd>{{ template.document.edges.length }}</dd>
              </div>
              <div>
                <dt>Billable</dt>
                <dd>
                  <template v-if="priced.get(template.id)">{{ priced.get(template.id)!.billable }}</template>
                  <template v-else-if="pricing">…</template>
                  <template v-else>—</template>
                </dd>
              </div>
              <div>
                <dt>Est. run</dt>
                <dd
                  :title="
                    priced.get(template.id)
                      ? `Published prices ${money(priced.get(template.id)!.floorUsd)}; enforced with the nitro margin ${money(priced.get(template.id)!.staticUsd)}.`
                      : undefined
                  "
                >
                  <!--
                    BOTH figures, never the enforced one alone. `static_cost_usd`
                    carries a 1.8x margin on every cheap node, so showing it by
                    itself reads as an error beside anyone's mental arithmetic -
                    the same reasoning BudgetMeter states at length.
                  -->
                  <template v-if="priced.get(template.id)">
                    {{ money(priced.get(template.id)!.floorUsd) }}–{{ money(priced.get(template.id)!.staticUsd) }}
                  </template>
                  <template v-else-if="pricing">…</template>
                  <template v-else>—</template>
                </dd>
              </div>
            </dl>
          </button>
        </li>
      </ul>

      <!--
        The second row, collapsed. These two are built from LIBRARY agents,
        whose prompts live in YAML rather than in the document - excellent
        proofs that the compiler works, and poor teachers, because a new author
        opening one sees six dropdown choices rather than a team they could have
        written. Kept rather than deleted because `e2e/builder.spec.ts` drives
        them (owner's decision 21), and demoted rather than removed because
        somebody looking for the smallest launchable graph should still find it.

        OPEN by default, and that is arithmetic rather than a preference. The
        grid is `repeat(auto-fill, minmax(232px, 1fr))` inside
        `width: min(1080px, 100%)`, which resolves to four columns - so six
        cards occupy two rows and eight cards occupy the same two rows.
        Shutting it saves no vertical space at all, and it would hide the card
        six E2E specs click, which is "a template change becomes a suite
        change": the thing owner's decision 21 was made to avoid. The author
        can still shut it. The demotion is the heading and the position, which
        is what a demotion is.
      -->
      <details class="template-more" open>
        <summary>
          More, built from this repository's own agents
          <span class="template-more-count">{{ MORE_BUILDER_TEMPLATES.length }}</span>
        </summary>
        <ul class="template-grid">
          <li v-for="template in MORE_BUILDER_TEMPLATES" :key="template.id">
            <button class="template-card" type="button" @click="emit('start', template)">
              <GraphThumbnail class="template-spine" :document="template.document" />
              <h3>{{ template.title }}</h3>
              <p class="template-blurb">{{ template.blurb }}</p>
              <p class="template-teaches">
                <span class="template-lede">Teaches</span>{{ template.teaches }}
              </p>
              <p class="template-teaches">
                <span class="template-lede">Change first</span>{{ template.modifyFirst }}
              </p>
              <dl class="template-facts">
                <div>
                  <dt>Nodes</dt>
                  <dd>{{ template.document.nodes.length }}</dd>
                </div>
                <div>
                  <dt>Edges</dt>
                  <dd>{{ template.document.edges.length }}</dd>
                </div>
                <div>
                  <dt>Billable</dt>
                  <dd>
                    <template v-if="priced.get(template.id)">{{ priced.get(template.id)!.billable }}</template>
                    <template v-else-if="pricing">…</template>
                    <template v-else>—</template>
                  </dd>
                </div>
                <div>
                  <dt>Est. run</dt>
                  <dd>
                    <template v-if="priced.get(template.id)">
                      {{ money(priced.get(template.id)!.floorUsd) }}–{{ money(priced.get(template.id)!.staticUsd) }}
                    </template>
                    <template v-else-if="pricing">…</template>
                    <template v-else>—</template>
                  </dd>
                </div>
              </dl>
            </button>
          </li>
        </ul>
      </details>
    </section>
  </div>
</template>

<style scoped>
.template-gallery {
  display: grid;
  gap: 26px;
  align-content: start;
  width: min(1080px, 100%);
  max-height: 100%;
  overflow: auto;
  padding: 30px 32px 40px;
  margin: 0 auto;
}

.gallery-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.gallery-kicker { color: var(--accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); letter-spacing: 0.04em; }
.gallery-heading h2 { margin: 4px 0 0; font-size: 17px; }
.gallery-notice { display: inline-flex; gap: 6px; align-items: center; margin: 0; color: var(--warn-text); font-size: var(--fs-11); }
.gallery-heading-aside { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: flex-end; }
.gallery-import { min-height: 32px; padding: 0 12px; font-size: var(--fs-12); }
.gallery-file-picker { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); opacity: 0; pointer-events: none; }

.template-grid {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(auto-fill, minmax(232px, 1fr));
  padding: 0;
  margin: 0;
  list-style: none;
}

/* A COLUMN, not a grid with `align-content: start`.
   The grid row is as tall as its tallest card, and the tallest card is the
   validator's - the only one carrying R14's caveat block. Packed to the start,
   the other three ended their content 206px above their own bottom edge (46% of
   the card) and read as three unfinished cards beside one finished one. As a
   flex column with the fact table pushed down, every card's stats sit on its
   bottom edge and the equal heights read as deliberate. */
.template-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  height: 100%;
  padding: 14px;
  text-align: left;
  color: var(--text-body);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--r-2xl);
  cursor: pointer;
  transition: background var(--motion-fast) ease, border-color var(--motion-fast) ease;
}

.template-card:hover { background: var(--surface-raised); border-color: var(--border-hover); }

.template-spine {
  padding: 6px 0;
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-lg);
}

.template-card h3 { margin: 2px 0 0; font-size: var(--fs-15); }
.template-blurb { margin: 0; color: var(--text-muted); font-size: var(--fs-12); line-height: 1.45; }

/* The two explanatory lines. Quieter than the blurb, because the blurb says
   what the graph IS and these say what it is for - and a card whose three
   paragraphs all shout is a card nobody finishes. */
.template-teaches {
  margin: 0;
  color: var(--text-40);
  font-size: var(--fs-11);
  line-height: 1.5;
}

/* INLINE, not a block. As a block it cost each card two lines, and six cards in
   two rows then overflowed the gallery's own `max-height: 100%` - which is
   `builder-layout.spec.ts`'s clipping guard, arriving from the other side. */
.template-lede {
  margin-right: 6px;
  color: var(--text-muted);
  font: 600 10px/1.6 var(--font-mono);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

/* The second row. `details` rather than a toggle of our own: it is a
   disclosure, the browser already has one, and the native element carries the
   expanded state to a screen reader without a line of script. */
.template-more { margin-top: 4px; }

.template-more > summary {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 8px 2px;
  color: var(--text-muted);
  font-size: var(--fs-12);
  cursor: pointer;
}

.template-more > summary:hover { color: var(--text-title); }

.template-more-count {
  padding: 1px 6px;
  color: var(--text-40);
  font: 600 10px/1.6 var(--font-mono);
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
}

.template-more .template-grid { margin-top: 10px; }

/* The thumbnail must not stretch to fill a flex column - it is a fixed-ratio
   spine and a stretched one is a different picture of the same graph. */
.template-spine { flex: none; }

/* Warn colours, not error. Nothing is wrong with the template; there is
   something about it the picture cannot say. */
.template-caveat {
  margin: 0;
  padding: 8px 10px;
  color: var(--warn-text);
  font-size: var(--fs-11);
  line-height: 1.5;
  background: var(--warn-bg);
  border: 1px solid var(--warn-border);
  border-radius: var(--r-md);
}

.template-facts {
  display: grid;
  /* Four now, not three - `Edges` joined the row. Two columns below the card's
     own breakpoint would be a second layout to keep in step, so the cell
     padding tightens instead. */
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  /* The one line that lands the stats on the card's bottom edge. */
  margin: auto 0 0;
  overflow: hidden;
  background: var(--border-default);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
}

.template-facts div { padding: 7px 6px; background: var(--surface-well); }
.template-facts dt { color: var(--text-40); font: 600 10px/1 var(--font-mono); text-transform: uppercase; }
.template-facts dd { margin: 5px 0 0; color: var(--text-title); font: 600 var(--fs-12)/1 var(--font-mono); font-variant-numeric: tabular-nums; }

.gallery-empty {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 0;
  padding: 14px;
  color: var(--text-muted);
  font-size: var(--fs-12);
  background: var(--surface-panel);
  border: 1px dashed var(--border-default);
  border-radius: var(--r-lg);
}

.gallery-empty.is-problem { color: var(--err-text); background: var(--err-bg); border-color: var(--err-border); border-style: solid; }

.library-list { display: grid; gap: 8px; padding: 0; margin: 0; list-style: none; }

.library-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 4px 8px 4px 4px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--r-lg);
}

.library-open {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 9px 10px;
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
.library-meta { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; color: var(--text-40); font: 500 10px/1 var(--font-mono); }
.library-when { display: inline-flex; gap: 4px; align-items: center; }

.status-pill { padding: 2px 6px; font: 700 10px/1.4 var(--font-mono); text-transform: uppercase; border-radius: var(--r-pill); }
.status-pill.is-draft { color: var(--text-muted); background: var(--surface-raised); }
.status-pill.is-published { color: var(--accent-mint); background: color-mix(in srgb, var(--accent-mint) 14%, transparent); }

/* The row's four actions (D-15-15). `auto` in the row's own grid, so the name
   keeps every pixel the actions do not need.

   D-15-26: four 28px glyphs in a 2px row, with Delete 34px from Export and
   drawn in the same colour and weight as the three safe ones - so the
   irreversible action was two pixels of icon away from the reversible one it
   sits beside. The answer is `DocumentBar`'s own, from D-15-6, because this is
   the same defect on a second surface and a second answer to it would be a
   second thing to keep in step: a separator, a real gap, and the error colour
   AT REST rather than only on hover. */
.library-actions { display: inline-flex; gap: 2px; align-items: center; }
.library-actions-separator {
  width: 1px;
  align-self: stretch;
  margin: 2px 9px;
  background: var(--border-default);
}
.library-delete { color: var(--err-text); }
.library-delete:hover { color: var(--err-text); background: var(--err-bg); border-color: var(--err-border); }

.delete-confirm {
  display: grid;
  gap: 9px;
  padding: 12px;
  margin-top: 6px;
  color: var(--text-body);
  font-size: var(--fs-12);
  line-height: 1.5;
  background: var(--surface-well);
  border: 1px solid var(--err-border);
  border-radius: var(--r-lg);
}

.delete-confirm label { color: var(--text-muted); }
.delete-confirm strong { color: var(--text-title); }
.delete-actions { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 8px; }
/* Refused: no text box, so the two buttons sit at the start rather than in a
   column reserved for an input that is not there. */
.delete-actions.is-refused { grid-template-columns: auto auto; justify-content: start; }
.delete-actions input {
  min-height: 38px;
  padding: 0 10px;
  color: var(--text-body);
  font-size: var(--fs-13);
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
