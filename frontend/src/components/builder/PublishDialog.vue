<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Check, CircleAlert, Play, Rocket, X } from 'lucide-vue-next'
import { builderApi, BuilderPublishRefusedError } from '../../services/builderApi'
import type { BuilderApiLike } from '../../services/builderApi'
import { useReturnFocus } from '../../composables/useReturnFocus'
import type {
  BuilderBudget,
  BuilderDocument,
  BuilderProblem,
  BuilderPublish,
} from '../../types/builder'

/**
 * The one dialog in the publish path, and the only place the builder covers the
 * graph it is editing.
 *
 * R15 puts zero modals in the EDITING path, because a stack of overlays hiding
 * the canvas is the defining failure of the product this one is measured
 * against. Publishing is not editing. It registers a runnable workflow in five
 * server-side maps, changes what `POST /api/sessions/{id}/runs` accepts, and
 * hands the author a contract they now own - `input_field`, the keys a run
 * request will be REFUSED for carrying, the price, and whether a stranger can
 * launch it. A step with those consequences deserves a moment where nothing
 * else is happening, and it is the one step where the graph underneath is not
 * what you are reading.
 *
 * IT PUBLISHES WHAT IS STORED. There is no document in the publish request at
 * all - it names an id and a version - which is why "save first" is a
 * precondition rather than a courtesy, and why the checklist below leads with
 * it. An author who published while dirty would register the version BEFORE
 * their last edit and have nothing on screen say so.
 */

const props = withDefaults(
  defineProps<{
    open: boolean
    /** The document as it stands, for the ungated-path jump. */
    document: BuilderDocument
    /** Null until the draft has been saved once - itself a blocker. */
    documentId: string | null
    /** How many `severity: 'error'` problems the SERVER reported. */
    errorCount: number
    saveState: 'clean' | 'dirty' | 'saving' | 'conflict' | 'offline'
    /** The version on the canvas, and the newest the server holds. */
    version: number
    headVersion: number
    /** `useBuilderValidation.phase`. `stale` and `unreachable` both block. */
    phase: 'idle' | 'checking' | 'stale' | 'fresh' | 'unreachable'
    budget: BuilderBudget | null
    /** Already published at this version, so the button reads Republish. */
    publishedVersion: number | null
    api?: BuilderApiLike
  }>(),
  { api: () => builderApi },
)

const emit = defineEmits<{
  close: []
  /** A 422 compile refusal's problems, to merge into `ProblemsPanel`. */
  refused: [problems: BuilderProblem[]]
  /** Select and centre this node - the jump from the ungated-path warning. */
  focusNode: [nodeId: string]
  /** Published. The bar re-reads the document; the author gets the contract. */
  published: [result: BuilderPublish]
  /** Take me to the run console for this workflow, with this input key. */
  run: [workflowId: string, inputField: string]
}>()

const publishing = ref(false)
const result = ref<BuilderPublish | null>(null)
const failure = ref('')
const dialog = ref<HTMLElement | null>(null)
const firstControl = ref<HTMLButtonElement | null>(null)

/** One precondition: whether it is met, and the sentence when it is not. */
interface Precondition {
  readonly id: string
  readonly label: string
  readonly met: boolean
  /** §6.5's blocking message, rendered when `met` is false. */
  readonly blocker: string
}

/**
 * The five refusals of §6.5, plus the one that precedes all of them.
 *
 * "Saved at least once" is not in that table because the table assumes a stored
 * document; a draft that has never been saved has no id to publish and no
 * version to compare, so it fails every other row for a reason that is not the
 * real one. Naming it first is the difference between "3 errors must be fixed"
 * and "save it first".
 */
const preconditions = computed<Precondition[]>(() => {
  const budget = props.budget
  return [
    {
      id: 'saved',
      label: 'Saved at least once',
      met: props.documentId !== null,
      blocker: 'this draft has never been saved, so there is no stored version to publish',
    },
    {
      id: 'clean',
      label: 'No unsaved changes',
      met: props.saveState === 'clean',
      blocker: 'save first — publish registers the stored version',
    },
    {
      id: 'head',
      label: 'Viewing the newest version',
      met: props.version === props.headVersion,
      blocker: `you are viewing v${props.version}; publish works on head (v${props.headVersion})`,
    },
    {
      id: 'fresh',
      /*
       * `idle` fails this row, and leaving it out was a real hole rather than a
       * tidy-up. A document whose fingerprint never moved from the one the
       * validation loop mounted with - a blank canvas is literally that
       * document - was never checked at all, and this checklist ticked
       * "Validation is current" over an answer nobody had asked for. The row is
       * about whether the verdict is CURRENT, and "there is no verdict" fails
       * that as surely as an out-of-date one does.
       */
      label: 'Validation is current',
      met: props.phase !== 'idle' && props.phase !== 'stale' && props.phase !== 'unreachable',
      blocker:
        props.phase === 'unreachable'
          ? 'validation is not current — the server did not answer the last check'
          : props.phase === 'idle'
            ? 'validation has not run yet'
            : 'validation is not current',
    },
    {
      id: 'errors',
      label: 'No errors',
      met: props.errorCount === 0,
      blocker:
        props.errorCount === 1 ? '1 error must be fixed' : `${props.errorCount} errors must be fixed`,
    },
    {
      id: 'ceiling',
      label: 'Inside the run cost ceiling',
      met: !budget?.over_ceiling,
      blocker: budget
        ? `estimated at $${budget.static_cost_usd.toFixed(2)} with margin, over the $${budget.ceiling_usd.toFixed(2)} run ceiling`
        : 'the run cost ceiling has not been checked',
    },
  ]
})

const blockers = computed(() => preconditions.value.filter((row) => !row.met))
const ready = computed(() => blockers.value.length === 0)
const actionLabel = computed(() => (props.publishedVersion === null ? 'Publish' : 'Republish'))

/**
 * The first billable node reachable from an input WITHOUT passing a gate.
 *
 * A line-for-line mirror of `descriptor.gate_before_first_billable`
 * (`builder/descriptor.py:282-321`) - walk forward from the inputs, do NOT
 * expand through a gate, stop at the first billable node - except that it
 * returns the node instead of a boolean, because a warning an author cannot
 * act on is half a warning.
 *
 * The BOOLEAN is still the server's: `gated_before_spend` comes off the publish
 * response and is what this component renders. This mirror only answers WHERE
 * to look, which is presentation (§6.1). If the two ever disagreed, the server's
 * answer is the one shown and this jump simply would not offer itself.
 */
const firstUngatedBillable = computed(() => {
  const byId = new Map(props.document.nodes.map((node) => [node.id as string, node]))
  const successors = new Map<string, string[]>()
  for (const edge of props.document.edges) {
    const list = successors.get(edge.source) ?? []
    list.push(edge.target)
    successors.set(edge.source, list)
  }
  const seen = new Set<string>()
  const frontier = props.document.nodes.filter((node) => node.kind === 'input').map((node) => node.id as string)
  while (frontier.length > 0) {
    const id = frontier.pop() as string
    if (seen.has(id)) continue
    seen.add(id)
    const node = byId.get(id)
    if (!node) continue
    if (node.kind === 'agent' || node.kind === 'crew') return node
    // A gate is reached, and what is behind it is only reached by answering it.
    if (node.kind === 'gate') continue
    frontier.push(...(successors.get(id) ?? []))
  }
  return null
})

/**
 * The service's own 403, spelled the way the service spells it.
 *
 * Quoted rather than paraphrased because the author will meet this exact string
 * if they hand the link to somebody who is not signed in, and a dialog that
 * described the refusal in different words would leave them matching two
 * sentences that mean the same thing.
 * (`service/app.py`, the `gated_before_spend` branch of `create_run`.)
 */
const gatelessSentence = computed(() =>
  result.value
    ? `workflow ${result.value.workflow_id} reaches a billable node before any human gate; `
      + 'sign in, or add a gate above the first agent'
    : '',
)

const { capture, restore } = useReturnFocus()

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      // Back to whatever opened it - Publish, or `⌘⇧P` from the canvas.
      restore()
      return
    }
    capture()
    // A re-open starts clean. Leaving the previous contract on screen would
    // present the LAST publish's `graph_version` above a button about to make a
    // new one.
    result.value = null
    failure.value = ''
    await nextTick()
    firstControl.value?.focus()
  },
)

async function publish(): Promise<void> {
  const id = props.documentId
  if (!id || !ready.value || publishing.value) return
  publishing.value = true
  failure.value = ''
  try {
    const published = await props.api.publish(id)
    result.value = published
    emit('published', published)
  } catch (error) {
    if (error instanceof BuilderPublishRefusedError) {
      // The one 422 on this router whose detail is an OBJECT. Its problems are
      // the compiler's, not the linter's, so they belong in the same panel as
      // every other problem rather than in a paragraph inside a dialog that is
      // about to close - tagged `from publish` by the panel that receives them.
      failure.value = error.message
      emit('refused', error.problems)
    } else {
      failure.value = error instanceof Error ? error.message : 'the graph could not be published.'
    }
  } finally {
    publishing.value = false
  }
}

function jumpToBillable(): void {
  const node = firstUngatedBillable.value
  if (!node) return
  emit('focusNode', node.id)
  emit('close')
}

function launch(): void {
  if (!result.value) return
  emit('run', result.value.workflow_id, result.value.input_field)
}

/**
 * Keep Tab inside the dialog while it is open.
 *
 * Hand-rolled rather than a library, and it is nine lines: the cut list forbids
 * the dependency and this is the only focus trap in the deliverable. Tabbing out
 * of a modal to controls that are visually behind it is the failure - the author
 * cannot see what is focused and Enter does something they did not read.
 */
function trap(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    emit('close')
    return
  }
  if (event.key !== 'Tab' || !dialog.value) return
  const focusable = dialog.value.querySelectorAll<HTMLElement>(
    'button:not(:disabled), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
  )
  if (focusable.length === 0) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement
  if (event.shiftKey && active === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}
</script>

<template>
  <div v-if="open" class="publish-scrim" @keydown="trap">
    <div
      ref="dialog"
      class="publish-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="publish-title"
    >
      <header class="publish-header">
        <div>
          <span class="publish-kicker">{{ result ? 'PUBLISHED' : 'PUBLISH' }}</span>
          <h2 id="publish-title">
            {{ result ? 'This graph is live' : 'Register this graph as a runnable workflow' }}
          </h2>
        </div>
        <button
          ref="firstControl"
          class="icon-button"
          type="button"
          aria-label="Close"
          title="Close"
          @click="emit('close')"
        >
          <X :size="16" aria-hidden="true" />
        </button>
      </header>

      <!-- Before: the checklist. Every row states its own blocker, so nothing
           is refused by a greyed button with no sentence beside it. -->
      <template v-if="!result">
        <ul class="precondition-list">
          <li
            v-for="row in preconditions"
            :key="row.id"
            :class="row.met ? 'is-met' : 'is-blocked'"
          >
            <Check v-if="row.met" :size="14" aria-hidden="true" />
            <CircleAlert v-else :size="14" aria-hidden="true" />
            <span>
              <span class="precondition-label">{{ row.label }}</span>
              <span v-if="!row.met" class="precondition-blocker">{{ row.blocker }}</span>
            </span>
          </li>
        </ul>

        <p v-if="failure" class="publish-failure" role="alert">{{ failure }}</p>

        <footer class="publish-actions">
          <button class="button button-quiet" type="button" @click="emit('close')">Not yet</button>
          <button
            class="button button-primary"
            type="button"
            :disabled="!ready || publishing"
            :title="ready ? undefined : blockers[0].blocker"
            @click="publish"
          >
            <Rocket :size="15" aria-hidden="true" />
            {{ publishing ? 'Publishing…' : actionLabel }}
          </button>
        </footer>
      </template>

      <!-- After: the contract. These five facts are what the author now owns,
           and four of them are only knowable from this response. -->
      <template v-else>
        <dl class="publish-contract">
          <div>
            <dt>Run input key</dt>
            <dd>
              <code>{{ result.input_field }}</code>
              <span class="contract-note">
                A run request carries the text under <code>inputs.{{ result.input_field }}</code>.
              </span>
            </dd>
          </div>
          <div>
            <dt>Graph version</dt>
            <dd>
              <code>{{ result.graph_version }}</code>
              <span class="contract-note">Document v{{ result.version }}. The graph's ETag body.</span>
            </dd>
          </div>
          <div>
            <dt>Estimated cost</dt>
            <dd>
              <code>${{ result.static_cost_usd.toFixed(4) }}</code>
              <span class="contract-note">Per run, enforced with the nitro margin.</span>
            </dd>
          </div>
          <div>
            <dt>Refused input keys</dt>
            <dd>
              <span class="contract-note">
                A run request carrying any of these is answered 422 — they are this graph's own
                control keys.
              </span>
              <ul class="reserved-keys">
                <li v-for="key in result.reserved_input_keys" :key="key"><code>{{ key }}</code></li>
              </ul>
            </dd>
          </div>
        </dl>

        <!-- The consequence, in full, with somewhere to go about it. -->
        <div v-if="!result.gated_before_spend" class="gateless-warning" role="alert">
          <p class="gateless-lead">Anyone signed out is refused. The service answers <strong>403</strong>:</p>
          <p class="gateless-quote">{{ gatelessSentence }}</p>
          <p class="gateless-why">
            A billable node runs before any human gate, so an unanswered gate is no longer the
            spend cap. Signed-in authors can still launch it.
          </p>
          <button
            v-if="firstUngatedBillable"
            class="button button-secondary"
            type="button"
            @click="jumpToBillable"
          >
            Go to {{ firstUngatedBillable.label }}
          </button>
        </div>
        <p v-else class="gated-note">
          A human gate stops this graph before it spends anything, so anyone with the link can
          launch it.
        </p>

        <footer class="publish-actions">
          <button class="button button-quiet" type="button" @click="emit('close')">Back to the canvas</button>
          <button class="button button-primary" type="button" @click="launch">
            <Play :size="15" aria-hidden="true" />
            Run it
          </button>
        </footer>
      </template>
    </div>
  </div>
</template>

<style scoped>
.publish-scrim {
  position: fixed;
  z-index: var(--z-toast);
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(10, 10, 10, 0.62);
  -webkit-backdrop-filter: var(--blur-panel);
  backdrop-filter: var(--blur-panel);
}

.publish-dialog {
  display: grid;
  gap: 16px;
  width: min(560px, 100%);
  max-height: min(680px, calc(100dvh - 48px));
  overflow: auto;
  padding: 20px;
  background: var(--surface-overlay);
  border: 1px solid var(--border-default);
  border-radius: var(--r-2xl);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
}

.publish-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.publish-kicker { color: var(--accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); letter-spacing: 0.04em; }
.publish-header h2 { margin: 5px 0 0; font-size: var(--fs-18); }

.precondition-list { display: grid; gap: 7px; padding: 0; margin: 0; list-style: none; }
.precondition-list li { display: grid; grid-template-columns: 16px minmax(0, 1fr); gap: 9px; align-items: start; font-size: var(--fs-13); }
.precondition-list svg { margin-top: 2px; }
.precondition-list li.is-met { color: var(--text-muted); }
.precondition-list li.is-met svg { color: var(--accent-mint); }
.precondition-list li.is-blocked { color: var(--text-body); }
.precondition-list li.is-blocked svg { color: var(--err-text); }
.precondition-label { display: block; }
.precondition-blocker { display: block; margin-top: 3px; color: var(--err-text); font-size: var(--fs-12); line-height: 1.45; }

.publish-contract { display: grid; gap: 12px; margin: 0; }
.publish-contract > div { display: grid; gap: 5px; padding: 11px 12px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-lg); }
.publish-contract dt { color: var(--text-40); font: 700 10px/1 var(--font-mono); text-transform: uppercase; letter-spacing: 0.04em; }
.publish-contract dd { display: grid; gap: 5px; margin: 0; }
.publish-contract code { padding: 2px 5px; color: var(--accent-mint); font: 500 var(--fs-12)/1.5 var(--font-mono); background: var(--surface-panel); border: 1px solid var(--border-default); border-radius: var(--r-xs); overflow-wrap: anywhere; }
.publish-contract dd > code { justify-self: start; }
.contract-note { color: var(--text-muted); font-size: var(--fs-11); line-height: 1.5; }
.reserved-keys { display: flex; flex-wrap: wrap; gap: 5px; padding: 0; margin: 2px 0 0; list-style: none; }

.gateless-warning { display: grid; gap: 8px; justify-items: start; padding: 12px; color: var(--warn-text); background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: var(--r-lg); }
.gateless-lead { margin: 0; font-size: var(--fs-12); }
.gateless-quote { margin: 0; padding: 8px 10px; color: var(--text-body); font: 500 var(--fs-12)/1.55 var(--font-mono); background: var(--surface-well); border-radius: var(--r-md); }
.gateless-why { margin: 0; color: var(--text-muted); font-size: var(--fs-11); line-height: 1.5; }
.gated-note { margin: 0; padding: 11px 12px; color: var(--accent-mint); font-size: var(--fs-12); line-height: 1.5; background: color-mix(in srgb, var(--accent-mint) 10%, transparent); border: 1px solid color-mix(in srgb, var(--accent-mint) 30%, transparent); border-radius: var(--r-lg); }

.publish-failure { margin: 0; padding: 10px 12px; color: var(--err-text); font-size: var(--fs-12); line-height: 1.5; background: var(--err-bg); border: 1px solid var(--err-border); border-radius: var(--r-lg); }

.publish-actions { display: flex; justify-content: flex-end; gap: 8px; }

@media (prefers-reduced-motion: reduce) {
  /* Nothing here animates. The block exists so the next person to add a
     transition to this dialog finds the place it has to be named. */
  .publish-dialog { transition: none; }
}
</style>
