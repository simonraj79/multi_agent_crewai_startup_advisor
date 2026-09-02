<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Clock3, FilePlus2, Loader, Trash2, TriangleAlert } from 'lucide-vue-next'
import GraphThumbnail from './GraphThumbnail.vue'
import { BUILDER_TEMPLATES } from '../../data/builderTemplates'
import { builderApi } from '../../services/builderApi'
import type { BuilderApiLike } from '../../services/builderApi'
import type { BuilderTemplate } from '../../data/builderTemplates'
import type { BuilderDocumentSummary } from '../../types/builder'

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
 * what they answer. The node count is the only number computed here, and it is
 * `document.nodes.length`: a description of the document rather than one of
 * `bounds.py`'s counts (R6).
 */

const props = withDefaults(
  defineProps<{
    /** Injected so a spec can drive the two requests without a server. */
    api?: BuilderApiLike
  }>(),
  { api: () => builderApi },
)

const emit = defineEmits<{
  /** Seed this template into the store as an ordinary unsaved draft. */
  start: [template: BuilderTemplate]
  /** Load a stored document by id. */
  open: [documentId: string]
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

const money = (value: number) => `$${value.toFixed(2)}`

onMounted(() => {
  void priceTemplates()
  void loadLibrary()
})

/**
 * Price all four templates at once.
 *
 * `allSettled`, not `all`: one template failing to validate must not blank the
 * prices of the other three, and the failure that matters here is the network
 * rather than the document - all four are known to validate clean.
 */
async function priceTemplates(): Promise<void> {
  pricing.value = true
  const answers = await Promise.allSettled(
    BUILDER_TEMPLATES.map(async (template) => {
      const result = await props.api.validate(template.document)
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

function askToDelete(id: string): void {
  deleting.value = id
  typedName.value = ''
  deleteProblem.value = ''
}

function cancelDelete(): void {
  deleting.value = null
  typedName.value = ''
  deleteProblem.value = ''
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
  } finally {
    deleteInFlight.value = false
  }
}

/** `2026-09-02T10:14:00Z` -> `2 Sep, 10:14`. Undated rows show the raw value. */
function when(iso: string): string {
  const at = Date.parse(iso)
  if (!Number.isFinite(at)) return iso
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(at)
}
</script>

<template>
  <div class="template-gallery">
    <section aria-labelledby="gallery-templates-title">
      <header class="gallery-heading">
        <div>
          <span class="gallery-kicker">START FROM</span>
          <h2 id="gallery-templates-title">A shape that already works</h2>
        </div>
        <p v-if="pricingProblem" class="gallery-notice" role="status">
          <TriangleAlert :size="13" aria-hidden="true" />
          Prices are unavailable — {{ pricingProblem }}
        </p>
      </header>

      <ul class="template-grid">
        <li v-for="template in BUILDER_TEMPLATES" :key="template.id">
          <button class="template-card" type="button" @click="emit('start', template)">
            <GraphThumbnail class="template-spine" :document="template.document" />
            <h3>{{ template.title }}</h3>
            <p class="template-blurb">{{ template.blurb }}</p>

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
    </section>

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
        No saved graphs yet. Pick a shape above and it is yours the moment you save it.
      </p>

      <ul v-else class="library-list">
        <li v-for="entry in library" :key="entry.id">
          <div class="library-row">
            <button class="library-open" type="button" @click="emit('open', entry.id)">
              <span class="library-name">{{ entry.name }}</span>
              <span class="library-meta">
                <span class="status-pill" :class="`is-${entry.status}`">{{ entry.status }}</span>
                <span class="library-version">v{{ entry.version }}</span>
                <span class="library-when"><Clock3 :size="12" aria-hidden="true" />{{ when(entry.updated_at) }}</span>
              </span>
            </button>
            <button
              class="icon-button library-delete"
              type="button"
              :aria-label="`Delete ${entry.name}`"
              title="Delete"
              @click="askToDelete(entry.id)"
            >
              <Trash2 :size="15" aria-hidden="true" />
            </button>
          </div>

          <!--
            An in-app confirmation, never `window.confirm`. Two reasons and both
            are practical: the browser dialog blocks the whole tab so the graph
            you are about to delete is hidden at the exact moment you are asked
            about it, and it cannot say WHICH graph in a way that survives a
            misread - typing the name is what proves the right row was read.
          -->
          <form v-if="deleting === entry.id" class="delete-confirm" @submit.prevent="confirmDelete">
            <label :for="`confirm-${entry.id}`">
              Deleting a published graph unregisters it, and running graphs are not affected.
              Type <strong>{{ entry.name }}</strong> to confirm.
            </label>
            <div class="delete-actions">
              <input
                :id="`confirm-${entry.id}`"
                v-model="typedName"
                type="text"
                autocomplete="off"
                :aria-describedby="deleteProblem ? `confirm-problem-${entry.id}` : undefined"
              />
              <button class="button button-quiet" type="button" @click="cancelDelete">Keep it</button>
              <button class="button button-danger" type="submit" :disabled="!confirmed || deleteInFlight">
                {{ deleteInFlight ? 'Deleting…' : 'Delete' }}
              </button>
            </div>
            <p v-if="deleteProblem" :id="`confirm-problem-${entry.id}`" class="delete-problem" role="alert">
              {{ deleteProblem }}
            </p>
          </form>
        </li>
      </ul>
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
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  /* The one line that lands the stats on the card's bottom edge. */
  margin: auto 0 0;
  overflow: hidden;
  background: var(--border-default);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
}

.template-facts div { padding: 7px 8px; background: var(--surface-well); }
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
.library-name { overflow: hidden; color: var(--text-title); font-size: var(--fs-13); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.library-meta { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; color: var(--text-40); font: 500 10px/1 var(--font-mono); }
.library-when { display: inline-flex; gap: 4px; align-items: center; }

.status-pill { padding: 2px 6px; font: 700 10px/1.4 var(--font-mono); text-transform: uppercase; border-radius: var(--r-pill); }
.status-pill.is-draft { color: var(--text-muted); background: var(--surface-raised); }
.status-pill.is-published { color: var(--accent-mint); background: color-mix(in srgb, var(--accent-mint) 14%, transparent); }

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
