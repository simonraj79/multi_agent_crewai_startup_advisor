<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { AlertTriangle, ExternalLink } from 'lucide-vue-next'
import type {
  BuilderDocument,
  BuilderDocumentModel,
  BuilderEdge,
  BuilderNode,
} from '../../types/builder'
import type { SaveConflict } from '../../composables/useBuilderPersistence'
import { useReturnFocus } from '../../composables/useReturnFocus'

/**
 * Somebody else stored a version while this one was being edited.
 *
 * One of two dialogs in the whole builder (R15), and it earns the interruption:
 * a 409 has no default resolution. Every automatic answer loses somebody's
 * work, and which work is lost is a judgement about content that nothing on the
 * client can make.
 *
 * WHAT THIS NEVER DOES IS AUTO-RELOAD. The author's only copy of what they have
 * drawn is the one on screen, and a reload that replaced it with head would
 * destroy it with no undo and no warning - which is the single most expensive
 * thing a save loop can do. Both resolutions below go through `commit`, so
 * whichever version is displaced stays exactly one Ctrl+Z away.
 *
 * There is no Cancel, and that is deliberate rather than an omission. The
 * document cannot save until this is answered, so a dismissed dialog would
 * leave an author editing a graph that silently stopped being stored - which is
 * the failure the chip exists to make impossible. Escape does nothing here for
 * the same reason, and the dialog says so rather than swallowing the key.
 */

const props = defineProps<{
  conflict: SaveConflict
  /** The document the author has in hand, for the left column of the diff. */
  mine: BuilderDocument
  /** For the "open head" link; the hash route is a real deep link. */
  documentId: string
  /** Re-GET head. The dialog owns the fetch so it can render a diff rather than a warning. */
  loadHead: () => Promise<BuilderDocumentModel>
}>()

const emit = defineEmits<{
  /** Take the server's version. The author's stays one undo away. */
  discard: [head: BuilderDocumentModel]
  /** Keep the author's version and re-PUT against head's version. */
  keep: [head: BuilderDocumentModel]
}>()

/** One value that differs, already rendered. Both sides are shown; neither is "right". */
interface FieldChange {
  field: string
  mine: string
  theirs: string
}

interface NodeChange {
  id: string
  label: string
  changes: FieldChange[]
}

interface DocumentDiff {
  onlyMine: BuilderNode[]
  onlyTheirs: BuilderNode[]
  changed: NodeChange[]
  /** How many edges the two documents differ by, in either direction. */
  edgeDelta: number
  edgesOnlyMine: BuilderEdge[]
  edgesOnlyTheirs: BuilderEdge[]
  settings: FieldChange[]
}

/**
 * A value as one short line.
 *
 * Truncated because a `prompt_inputs` map or a 2000-character gate message is a
 * legitimate value and a diff row is not where it is read. The row's job is to
 * say WHICH field moved; the canvas behind the dialog is where the author looks
 * at what it moved to.
 */
function show(value: unknown): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value) ?? 'null'
  return text.length > 72 ? `${text.slice(0, 71)}…` : text
}

/**
 * Two documents, compared field by field.
 *
 * A TWO-way diff, and the naming is careful about that. There is no base
 * version to compare against - the client holds what the author drew and what
 * the server stored, and nothing that says which of the two changed a given
 * field. So the columns are labelled "yours" and "theirs" rather than "added"
 * and "removed", because a node present only in one of them may have been added
 * by that side or deleted by the other, and the dialog must not claim to know.
 *
 * Edges are counted rather than listed field by field. An edge has four fields
 * and no name, so a row reading `source_port: out -> approve` identifies
 * nothing an author can find; the count plus the node rows above it is what
 * actually tells them how far apart the two graphs are.
 */
function diffDocuments(mine: BuilderDocument, theirs: BuilderDocument): DocumentDiff {
  const mineNodes = new Map(mine.nodes.map((node) => [node.id as string, node]))
  const theirNodes = new Map(theirs.nodes.map((node) => [node.id as string, node]))

  const onlyMine = mine.nodes.filter((node) => !theirNodes.has(node.id))
  const onlyTheirs = theirs.nodes.filter((node) => !mineNodes.has(node.id))

  const changed: NodeChange[] = []
  for (const [id, node] of mineNodes) {
    const other = theirNodes.get(id)
    if (!other) continue
    const changes: FieldChange[] = []
    if (node.label !== other.label) {
      changes.push({ field: 'label', mine: show(node.label), theirs: show(other.label) })
    }
    if (node.kind !== other.kind) {
      changes.push({ field: 'kind', mine: node.kind, theirs: other.kind })
    }
    const fields = new Set([...Object.keys(node.config), ...Object.keys(other.config)])
    for (const field of fields) {
      const left = (node.config as unknown as Record<string, unknown>)[field]
      const right = (other.config as unknown as Record<string, unknown>)[field]
      if (JSON.stringify(left) === JSON.stringify(right)) continue
      changes.push({ field, mine: show(left), theirs: show(right) })
    }
    if (changes.length > 0) changed.push({ id, label: node.label, changes })
  }

  const mineEdges = new Set(mine.edges.map(edgeKey))
  const theirEdges = new Set(theirs.edges.map(edgeKey))
  const edgesOnlyMine = mine.edges.filter((edge) => !theirEdges.has(edgeKey(edge)))
  const edgesOnlyTheirs = theirs.edges.filter((edge) => !mineEdges.has(edgeKey(edge)))

  const settings: FieldChange[] = []
  if (mine.name !== theirs.name) {
    settings.push({ field: 'name', mine: show(mine.name), theirs: show(theirs.name) })
  }
  if (mine.input_field !== theirs.input_field) {
    settings.push({
      field: 'input_field',
      mine: show(mine.input_field),
      theirs: show(theirs.input_field),
    })
  }
  if (JSON.stringify(mine.joins) !== JSON.stringify(theirs.joins)) {
    settings.push({ field: 'joins', mine: show(mine.joins), theirs: show(theirs.joins) })
  }

  return {
    onlyMine,
    onlyTheirs,
    changed,
    edgeDelta: edgesOnlyMine.length + edgesOnlyTheirs.length,
    edgesOnlyMine,
    edgesOnlyTheirs,
    settings,
  }
}

/**
 * An edge's IDENTITY for the diff, which is its endpoints rather than its id.
 *
 * Edge ids are minted per document (`e1`, `e2`, …), so two authors drawing the
 * same connection produce the same edge under different ids and an id-keyed
 * diff would report it twice - once as added and once as removed - for a graph
 * where nothing moved.
 */
function edgeKey(edge: BuilderEdge): string {
  return `${edge.source}|${edge.source_port}|${edge.target}`
}

const head = shallowRef<BuilderDocumentModel | null>(null)
const loadFailure = ref('')
const busy = ref(false)
const panel = ref<HTMLElement | null>(null)

async function fetchHead(): Promise<void> {
  loadFailure.value = ''
  busy.value = true
  try {
    head.value = await props.loadHead()
  } catch (failure) {
    head.value = null
    loadFailure.value = failure instanceof Error ? failure.message : String(failure)
  } finally {
    busy.value = false
  }
}

const { capture, restore } = useReturnFocus()

onMounted(() => {
  // This dialog is `v-if`'d rather than `open`-propped, so its close IS its
  // unmount and the restore has to ride the teardown hook.
  capture()
  panel.value?.focus()
  void fetchHead()
})

onUnmounted(restore)

/**
 * Keep Tab inside the dialog.
 *
 * Hand-rolled rather than `inert` on the rest of the app: `inert` is the better
 * mechanism and it is one line, but it would have to be applied to a subtree
 * this component does not own, from a component that is mounted inside it.
 * Trapping the key is the version that is entirely local.
 */
function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Tab' || !panel.value) return
  const focusable = panel.value.querySelectorAll<HTMLElement>(
    'button:not(:disabled), a[href]',
  )
  if (focusable.length === 0) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement
  if (event.shiftKey && (active === first || active === panel.value)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}

/** `#/build/<id>` in a new tab, so head can be read side by side without losing this one. */
function openHead(): void {
  const { origin, pathname, search } = window.location
  window.open(`${origin}${pathname}${search}#/build/${props.documentId}`, '_blank', 'noopener')
}

const diff = computed(() => (head.value ? diffDocuments(props.mine, head.value.document) : null))
const empty = computed(
  () =>
    diff.value !== null &&
    diff.value.onlyMine.length === 0 &&
    diff.value.onlyTheirs.length === 0 &&
    diff.value.changed.length === 0 &&
    diff.value.edgeDelta === 0 &&
    diff.value.settings.length === 0,
)
</script>

<template>
  <div class="conflict-scrim">
    <section
      ref="panel"
      class="conflict-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="conflict-title"
      tabindex="-1"
      @keydown="onKeydown"
    >
      <header>
        <span class="conflict-icon" aria-hidden="true"><AlertTriangle :size="18" /></span>
        <div>
          <span class="conflict-kicker">SAVE CONFLICT</span>
          <h2 id="conflict-title">This graph changed while you were editing it</h2>
        </div>
      </header>

      <!-- The server's own sentence, verbatim. It names both versions, which is
           more than any wording invented here could. -->
      <p class="conflict-detail" data-testid="conflict-detail">{{ conflict.detail }}</p>

      <p class="conflict-rule">
        Nothing has been overwritten and nothing has been reloaded. Whichever version you do not
        keep is pushed onto the undo stack, so one Ctrl+Z brings it back.
      </p>

      <div v-if="busy" class="conflict-state" role="status">Reading the stored version…</div>
      <div v-else-if="loadFailure" class="conflict-state is-bad" role="alert">
        <span>{{ loadFailure }}</span>
        <button type="button" class="button button-secondary" @click="fetchHead()">Try again</button>
      </div>

      <div v-else-if="diff" class="conflict-diff" data-testid="conflict-diff">
        <p v-if="empty" class="conflict-state">
          The two versions have the same content. Keeping yours simply re-stores it.
        </p>

        <template v-else>
          <section v-if="diff.onlyMine.length" aria-labelledby="conflict-only-mine">
            <h3 id="conflict-only-mine">Only in yours</h3>
            <ul>
              <li v-for="node in diff.onlyMine" :key="node.id">
                <code>{{ node.id }}</code><span>{{ node.label }}</span>
              </li>
            </ul>
          </section>

          <section v-if="diff.onlyTheirs.length" aria-labelledby="conflict-only-theirs">
            <h3 id="conflict-only-theirs">Only in v{{ head?.version }}</h3>
            <ul>
              <li v-for="node in diff.onlyTheirs" :key="node.id">
                <code>{{ node.id }}</code><span>{{ node.label }}</span>
              </li>
            </ul>
          </section>

          <section v-if="diff.changed.length" aria-labelledby="conflict-changed">
            <h3 id="conflict-changed">Different in both</h3>
            <div v-for="node in diff.changed" :key="node.id" class="conflict-node">
              <p class="conflict-node-name"><code>{{ node.id }}</code><span>{{ node.label }}</span></p>
              <dl>
                <template v-for="change in node.changes" :key="change.field">
                  <dt>{{ change.field }}</dt>
                  <dd><span class="is-mine">{{ change.mine }}</span><span class="is-theirs">{{ change.theirs }}</span></dd>
                </template>
              </dl>
            </div>
          </section>

          <section v-if="diff.settings.length" aria-labelledby="conflict-settings">
            <h3 id="conflict-settings">Graph settings</h3>
            <dl>
              <template v-for="change in diff.settings" :key="change.field">
                <dt>{{ change.field }}</dt>
                <dd><span class="is-mine">{{ change.mine }}</span><span class="is-theirs">{{ change.theirs }}</span></dd>
              </template>
            </dl>
          </section>

          <p v-if="diff.edgeDelta" class="conflict-edges">
            {{ diff.edgeDelta }} connection<template v-if="diff.edgeDelta !== 1">s</template> differ:
            {{ diff.edgesOnlyMine.length }} only in yours, {{ diff.edgesOnlyTheirs.length }} only in
            v{{ head?.version }}.
          </p>
        </template>
      </div>

      <footer>
        <button
          type="button"
          class="button button-secondary"
          :disabled="!head"
          data-testid="conflict-discard"
          @click="head && emit('discard', head)"
        >
          Discard mine
        </button>
        <button
          type="button"
          class="button button-primary"
          :disabled="!head"
          data-testid="conflict-keep"
          @click="head && emit('keep', head)"
        >
          Keep mine
        </button>
        <button type="button" class="button button-quiet" @click="openHead()">
          <ExternalLink :size="14" aria-hidden="true" />
          Open v{{ head?.version ?? conflict.storedVersion }} in a new tab
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.conflict-scrim { position: fixed; z-index: var(--z-toast); inset: 0; display: grid; padding: 24px; place-items: center; background: rgba(0, 0, 0, 0.6); backdrop-filter: var(--blur-panel); }
.conflict-dialog { display: flex; width: min(640px, 100%); max-height: min(84vh, 720px); flex-direction: column; gap: 12px; padding: 20px; background: var(--surface-overlay); border: 1px solid var(--warn-border); border-radius: var(--r-2xl); box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5); outline: 0; }
.conflict-dialog:focus-visible { border-color: var(--accent-cyan); box-shadow: var(--glow-input); }
.conflict-dialog header { display: flex; align-items: center; gap: 10px; }
.conflict-icon { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; color: var(--warn-text); background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: var(--r-md); }
.conflict-kicker { color: var(--warn-text); font: 700 var(--fs-11)/1 var(--font-mono); }
.conflict-dialog h2 { margin: 3px 0 0; font-size: 16px; }
.conflict-detail { margin: 0; padding: 9px 10px; color: var(--warn-text); background: var(--surface-well); border-left: 2px solid var(--warn-text); font: 500 var(--fs-12)/1.5 var(--font-mono); }
.conflict-rule { margin: 0; color: var(--text-muted); font-size: var(--fs-12); line-height: 1.5; }
.conflict-state { display: flex; align-items: center; gap: 10px; margin: 0; color: var(--text-muted); font-size: var(--fs-12); }
.conflict-state.is-bad { color: var(--err-text); }

.conflict-diff { display: flex; min-height: 0; flex: 1; flex-direction: column; gap: 14px; overflow: auto; padding: 12px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.conflict-diff h3 { margin: 0 0 7px; color: var(--text-40); font: 700 var(--fs-11)/1 var(--font-mono); text-transform: uppercase; }
.conflict-diff ul { margin: 0; padding: 0; list-style: none; }
.conflict-diff li,
.conflict-node-name { display: flex; align-items: baseline; gap: 8px; margin: 0 0 4px; color: var(--text-body); font-size: var(--fs-12); }
.conflict-diff code { color: var(--accent-cyan); font: 500 var(--fs-11)/1.4 var(--font-mono); }
.conflict-node { margin-bottom: 10px; }
.conflict-diff dl { display: grid; grid-template-columns: minmax(0, 1fr); gap: 5px; margin: 0; }
.conflict-diff dt { color: var(--text-40); font: 700 var(--fs-11)/1.3 var(--font-mono); }
/* Two columns, so "yours" and "theirs" are read side by side rather than as a
   before/after that implies one of them is the correction. */
.conflict-diff dd { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; margin: 0; font-size: var(--fs-11); overflow-wrap: anywhere; }
.conflict-diff dd .is-mine { color: var(--accent-mint); }
.conflict-diff dd .is-theirs { color: var(--warn-text); }
.conflict-edges { margin: 0; color: var(--text-muted); font-size: var(--fs-11); }

.conflict-dialog footer { display: flex; gap: 8px; }
.conflict-dialog footer .button-quiet { margin-left: auto; }
.conflict-dialog footer .button:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
</style>
