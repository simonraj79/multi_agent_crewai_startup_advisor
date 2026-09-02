<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Plus } from 'lucide-vue-next'
import { nodeId } from '../../../types/builder'
import type {
  BuilderDocument,
  BuilderEdge,
  BuilderNode,
  BuilderVocabulary,
  RouterBranch,
} from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import RouterBranchEditor from './RouterBranchEditor.vue'
import { replaceNode } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * The `router` node: a deterministic fork, and the one config where editing a
 * field changes the SHAPE of the card.
 *
 * A router's out-ports ARE its branch labels (`_OUT_PORTS_BY_KIND` computes them
 * per node), so every edit here has a consequence on the canvas within the same
 * tick: adding a branch grows a port, renaming one moves it, deleting one takes
 * it away. That is why two of the four operations below rewrite EDGES in the
 * same commit, and why doing so is not overreach:
 *
 *   - DELETING a branch with an edge on it deletes that edge too. Left behind,
 *     it is an `edge-unknown-port` error the author did not make, on an edge
 *     they can no longer see a port for. One commit, so one undo brings back
 *     both.
 *   - RENAMING a branch moves `source_port` on every edge that left by the old
 *     name. Left behind, every one of them is `edge-unknown-port` - a rename
 *     that silently breaks the whole fan-out is the same failure `renameCascade`
 *     exists to prevent one level up.
 *
 * Neither rewrite can turn a valid document into an invalid one, which is the
 * test this package applies before rewriting anything on an author's behalf.
 *
 * THE COUNT IS ADVISORY. `router-branch-count` is Tier 2 (§6.1) - the server
 * says 2..4 and the client renders the sentence. What the header does is state
 * the position against the served bound so an author sees they are at four
 * before they press Add, not after.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'router' }>
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{
  commit: [change: InspectorCommit]
  /** What a rewrite took with it, so a shell with a toast can say so too. */
  notice: [message: string]
}>()

const branches = computed(() => props.node.config.branches)
const otherwiseOp = computed(() => props.vocabulary.router_otherwise)
const bounds = computed(() => props.vocabulary.bounds)

const control = (name: string) => `insp-${props.node.id}-${name}`

/**
 * What the last structural rewrite took with it.
 *
 * Rendered inline, beside the list it is about, rather than as a floating toast
 * - which is the same argument the whole rail makes: the answer to "what just
 * happened to my graph" belongs next to the graph, not on top of it.
 *
 * Every handler below clears it first and only `say()` sets it, so the notice
 * describes the LAST edit or nothing at all. A timer was the obvious
 * alternative and is worse twice over: it makes the message disappear while the
 * author is still reading it, and it makes a test wait on a clock.
 */
const notice = ref('')
watch(
  () => props.node.id,
  () => {
    notice.value = ''
  },
)

function say(message: string): void {
  notice.value = message
  emit('notice', message)
}

function writeBranches(next: RouterBranch[], label: string, edges?: BuilderEdge[]): void {
  const withBranches = replaceNode(props.doc, { ...props.node, config: { branches: next } })
  emit('commit', {
    label,
    next: edges ? { ...withBranches, edges } : withBranches,
  })
}

/* --- edit, reorder ------------------------------------------------------ */

function updateBranch(index: number, branch: RouterBranch): void {
  notice.value = ''
  const next = branches.value.slice()
  next[index] = branch
  writeBranches(next, `Set branch ${branch.label}`)
}

function moveBranch(index: number, delta: number): void {
  notice.value = ''
  const target = index + delta
  if (target < 0 || target >= branches.value.length) return
  const next = branches.value.slice()
  const [moved] = next.splice(index, 1)
  next.splice(target, 0, moved)
  writeBranches(next, `Reorder branch ${moved.label}`)
}

/* --- rename, which the edges follow ------------------------------------- */

function renameBranch(index: number, label: string): void {
  notice.value = ''
  const from = branches.value[index].label
  const to = nodeId(label)
  const next = branches.value.slice()
  next[index] = { ...next[index], label: to }

  const moving = props.doc.edges.filter(
    (edge) => edge.source === props.node.id && edge.source_port === from,
  )
  const edges = moving.length
    ? props.doc.edges.map((edge) =>
        edge.source === props.node.id && edge.source_port === from
          ? { ...edge, source_port: to as string }
          : edge,
      )
    : undefined

  if (moving.length) {
    say(
      moving.length === 1
        ? `1 edge moved from ${from} to ${to}.`
        : `${moving.length} edges moved from ${from} to ${to}.`,
    )
  }
  writeBranches(next, `Rename branch to ${to}`, edges)
}

/* --- add, remove -------------------------------------------------------- */

/**
 * A new branch is born legal, the way `newNode` makes a whole router legal.
 *
 * The key is copied from the first comparison branch rather than left null,
 * because `RouterBranch._validate_shape` refuses a comparison with no key - an
 * author who pressed Add would otherwise be handed a 422 about a field they had
 * not typed in. A router is almost always forking on ONE key, so the copy is
 * usually also the right answer.
 */
function addBranch(): void {
  notice.value = ''
  const held = new Set(branches.value.map((branch) => branch.label as string))
  let index = 1
  while (held.has(`branch_${index}`)) index += 1
  const label = nodeId(`branch_${index}`)
  const sibling = branches.value.find((branch) => branch.op !== otherwiseOp.value)
  const created: RouterBranch = {
    label,
    op: (props.vocabulary.router_comparisons[0] ?? 'eq') as RouterBranch['op'],
    key: sibling?.key ?? nodeId('decision'),
    value: null,
  }

  // Placed before `otherwise`, which is the branch that fires when nothing else
  // did and therefore reads last wherever it is drawn.
  const next = branches.value.slice()
  const fallbackAt = next.findIndex((branch) => branch.op === otherwiseOp.value)
  if (fallbackAt === -1) next.push(created)
  else next.splice(fallbackAt, 0, created)
  writeBranches(next, `Add branch ${label}`)
}

function removeBranch(index: number): void {
  notice.value = ''
  const gone = branches.value[index]
  const next = branches.value.filter((_, position) => position !== index)
  const orphaned = props.doc.edges.filter(
    (edge) => edge.source === props.node.id && edge.source_port === gone.label,
  )
  const edges = orphaned.length
    ? props.doc.edges.filter(
        (edge) => !(edge.source === props.node.id && edge.source_port === gone.label),
      )
    : undefined

  if (orphaned.length) {
    const targets = orphaned.map((edge) => edge.target).join(', ')
    say(
      orphaned.length === 1
        ? `Deleting ${gone.label} also removed its edge to ${targets}. One undo restores both.`
        : `Deleting ${gone.label} also removed ${orphaned.length} edges, to ${targets}. One undo restores them all.`,
    )
  }
  writeBranches(next, `Delete branch ${gone.label}`, edges)
}

const otherwiseTakenBy = computed(() =>
  branches.value.findIndex((branch) => branch.op === otherwiseOp.value),
)
const countNote = computed(
  () =>
    `${branches.value.length} of ${bounds.value.min_router_branches}–${bounds.value.max_fanout_width}`,
)
const countWarn = computed(
  () =>
    branches.value.length < bounds.value.min_router_branches ||
    branches.value.length >= bounds.value.max_fanout_width,
)
</script>

<template>
  <div class="inspector-form">
    <FieldRow
      label="Branches"
      :control-id="control('branches')"
      field="branches"
      :node-id="node.id"
      group
      :note="countNote"
      :note-warn="countWarn"
      help="Each branch is one comparison over one state key, and its name is the port an edge leaves by. There is no expression here; a node that needs arithmetic is a transform."
    >
      <ul class="branch-list">
        <RouterBranchEditor
          v-for="(branch, index) in branches"
          :key="`${index}:${branch.label}`"
          :doc="doc"
          :node="node"
          :vocabulary="vocabulary"
          :branch="branch"
          :index="index"
          :otherwise-taken="otherwiseTakenBy !== -1 && otherwiseTakenBy !== index"
          :can-remove="branches.length > 1"
          :can-move-up="index > 0"
          :can-move-down="index < branches.length - 1"
          @update="updateBranch"
          @rename="renameBranch"
          @remove="removeBranch"
          @move="moveBranch"
        />
      </ul>

      <button type="button" class="row-add" @click="addBranch">
        <Plus :size="12" aria-hidden="true" />
        Add branch
      </button>

      <p v-if="notice" class="branch-notice" role="status">{{ notice }}</p>
    </FieldRow>
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
.branch-list { display: grid; gap: 9px; margin: 0 0 9px; padding: 0; list-style: none; }
.row-add { display: inline-flex; width: 100%; min-height: 32px; align-items: center; justify-content: center; gap: 6px; color: var(--text-muted); font: 600 var(--fs-11)/1 var(--font-body); background: transparent; border: 1px dashed var(--border-default); border-radius: var(--r-md); cursor: pointer; transition: color var(--motion-fast) ease, border-color var(--motion-fast) ease; }
.row-add:hover { color: var(--text-title); border-color: var(--border-hover); }
.row-add:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
/* Cyan rather than amber: nothing went wrong, the graph simply moved further
   than the control the author touched. */
.branch-notice { margin: 9px 0 0; padding: 8px 9px; color: var(--accent-cyan); font-size: var(--fs-11); line-height: 1.5; background: color-mix(in srgb, var(--accent-cyan) 10%, transparent); border: 1px solid color-mix(in srgb, var(--accent-cyan) 30%, transparent); border-radius: var(--r-sm); }
</style>
