<script setup lang="ts">
import { computed, inject, nextTick, ref, useTemplateRef, watch } from 'vue'
import type { Component } from 'vue'
import { AlertTriangle, ArrowRight } from 'lucide-vue-next'
import { nodeId as toNodeId } from '../../types/builder'
import type {
  AgentConfig,
  BuilderDocument,
  BuilderEdge,
  BuilderNode,
  BuilderVocabulary,
  CrewConfig,
  NodeId,
  NodeKind,
  Tier,
} from '../../types/builder'
import { NODE_KINDS, outPortsOf } from '../../data/nodeKinds'
import { renameCascade } from '../../utils/builderGraph'
import { BUILDER_PROBLEMS } from '../../composables/useBuilderProblems'
import FieldRow from './fields/FieldRow.vue'
import NodeIdField from './fields/NodeIdField.vue'
import InputForm from './inspectors/InputForm.vue'
import BillableForm from './inspectors/BillableForm.vue'
import GateForm from './inspectors/GateForm.vue'
import RouterForm from './inspectors/RouterForm.vue'
import TransformForm from './inspectors/TransformForm.vue'
import OutputForm from './inspectors/OutputForm.vue'
import GraphSettings from './inspectors/GraphSettings.vue'
import { coalesceKeyFor, inboundCount, patchConfig, replaceNode } from './commit'
import type { InspectorCommit } from './commit'

/**
 * The inspector: docked, never a modal.
 *
 * This is the direct answer to the thing that makes ChatDev's editor unusable at
 * size. Its `FormGenerator.vue` is 2,808 lines that render a STACK of overlays -
 * `modalStack`, with child modals opened from inside child modals - so reading
 * what a node is configured to do means covering up the graph you are
 * configuring it inside of, and comparing two nodes means closing one stack and
 * opening another. Everything here is in a rail beside the canvas, at the same
 * time as the canvas, and §5 R15 makes that a rule rather than a preference:
 * zero modals in the editing path.
 *
 * DISPATCH IS A TOTAL RECORD, NOT A SWITCH. `INSPECTORS` is typed
 * `Record<NodeKind, Component>`, so an eighth kind is a COMPILE error in this
 * file rather than a blank pane in front of an author. `agent` and `crew` map to
 * the same component on purpose: they extend one `_BillableConfig` in
 * `document.py`, so one form is the truthful modelling of what the schema says
 * and two would be two copies of the shared four fifths.
 *
 * NOTHING HERE WRITES THE DOCUMENT. Every form proposes a whole next document
 * through `commit`, and `BuilderView` is the only place that becomes a call to
 * `useBuilderDocument.commit()` (§1.1 invariant 1, §2 WP-F). The rail's own
 * three operations - the id rename, the label, and the multi-selection patch -
 * follow exactly the same route as the forms'.
 */

/**
 * One form per kind. The one place a kind becomes a component.
 *
 * `Record<NodeKind, Component>` is what the spec asks for and what the
 * exhaustiveness argument needs: a missing key fails to compile. It does not
 * check that each key got the RIGHT form - `<component :is>` erases props - so
 * `builderInspector.spec.ts` asserts the pairing by mounting all seven and
 * looking for a control only the right form renders.
 */
const INSPECTORS: Record<NodeKind, Component> = {
  input: InputForm,
  agent: BillableForm,
  crew: BillableForm,
  gate: GateForm,
  router: RouterForm,
  transform: TransformForm,
  output: OutputForm,
}

/**
 * Which controls each form actually renders.
 *
 * Handed to `unplacedForNode` so that a problem whose `FIELD_CODES` field is
 * absent from THIS form falls to the strip instead of vanishing. The case that
 * makes it necessary is real: `library-unknown-id` maps to `agent_id`, and
 * `compiler.py` raises it for a CREW's unregistered `crew_id` too, where no such
 * control exists.
 */
const INSPECTOR_FIELDS: Record<NodeKind, readonly string[]> = {
  input: ['field', 'label', 'max_chars', 'required'],
  agent: ['tier', 'agent_id', 'tools', 'max_iter', 'guardrail_max_retries', 'prompt_inputs'],
  crew: ['tier', 'crew_id', 'max_iter', 'guardrail_max_retries', 'prompt_inputs'],
  gate: ['message', 'editable_fields', 'max_turns'],
  router: ['branches'],
  transform: ['op', 'args'],
  output: ['body_key', 'source'],
}

const props = defineProps<{
  doc: BuilderDocument
  /** Null while `/vocabulary` has not loaded, or after it failed. */
  vocabulary: BuilderVocabulary | null
  /** Why the vocabulary is unusable, as a sentence, or '' when it is fine. */
  vocabularyProblem?: string
  selectedNodeIds: readonly string[]
  selectedEdgeIds: readonly string[]
  /**
   * A stored version that is not head is on screen (plan 15 D3): every control
   * in the rail is disabled, and the forms still RENDER, because "is v3 the one
   * I want back?" is answered by reading v3's configuration. The store's lock
   * would refuse the commits anyway; this is so a field cannot be typed into
   * and then watched revert.
   */
  readOnly?: boolean
}>()

const emit = defineEmits<{
  commit: [change: InspectorCommit]
  /** What a structural rewrite took with it, for a shell that wants to say so twice. */
  notice: [message: string]
}>()

/**
 * Required, and it throws when absent - the same contract `FieldProblem` states
 * for the same reason. A rail with no problem index would render every form
 * looking clean over a document the server has refused, and that is the one
 * outcome this package exists to prevent.
 */
const problems = inject(BUILDER_PROBLEMS)
if (!problems) {
  throw new Error('InspectorRail needs the BUILDER_PROBLEMS index; provide it from BuilderView')
}

/* --- what is selected --------------------------------------------------- */

const selectedNodes = computed(() =>
  props.doc.nodes.filter((node) => props.selectedNodeIds.includes(node.id)),
)
const selectedEdges = computed(() =>
  props.doc.edges.filter((edge) => props.selectedEdgeIds.includes(edge.id)),
)

const node = computed(() =>
  selectedNodes.value.length === 1 && selectedEdges.value.length === 0
    ? selectedNodes.value[0]
    : null,
)
const edge = computed(() =>
  selectedEdges.value.length === 1 && selectedNodes.value.length === 0
    ? selectedEdges.value[0]
    : null,
)
const many = computed(
  () => selectedNodes.value.length + selectedEdges.value.length > 1,
)

const meta = computed(() => (node.value ? NODE_KINDS[node.value.kind] : null))
/** 1-based, zero-padded, from document order - the same index the card draws. */
const nodeIndex = computed(() =>
  node.value
    ? String(props.doc.nodes.findIndex((entry) => entry.id === node.value?.id) + 1).padStart(2, '0')
    : '',
)

/** Problems that no control on the open form can carry, pinned at the top. */
const unplaced = computed(() =>
  node.value ? problems.unplacedForNode(node.value.id, INSPECTOR_FIELDS[node.value.kind]) : [],
)
const edgeProblems = computed(() => (edge.value ? problems.problemsForEdge(edge.value.id) : []))

/* --- node identity ------------------------------------------------------ */

const idDraft = ref('')
const labelDraft = ref('')
watch(
  node,
  (selected) => {
    idDraft.value = selected?.id ?? ''
    labelDraft.value = selected?.label ?? ''
  },
  { immediate: true },
)

const takenIds = computed(() =>
  props.doc.nodes.filter((entry) => entry.id !== node.value?.id).map((entry) => entry.id as string),
)

/**
 * How many places move with this rename, counted by running the rename.
 *
 * Not a re-implementation of `renameCascade`'s reach: it IS `renameCascade`,
 * against the draft, with the result compared to the input by identity. That
 * works because the function deliberately returns the SAME object for anything
 * it did not touch - `rewriteNode` and `rewriteJoins` both have early returns
 * saying so - which makes a `!==` an exact answer rather than an estimate. A
 * hand-rolled counter would be a second copy of the reach, and the reach is
 * precisely the thing that is easy to get subtly wrong.
 *
 * The renamed node itself is subtracted: it is the SUBJECT of the rename, not a
 * reference to it.
 */
const referencesMoved = computed(() => {
  const selected = node.value
  if (!selected) return null
  const draft = idDraft.value
  if (draft === selected.id) return null
  const next = renameCascade(props.doc, selected.id, draft as NodeId)
  let moved = -1
  next.nodes.forEach((entry, index) => {
    if (entry !== props.doc.nodes[index]) moved += 1
  })
  next.edges.forEach((entry, index) => {
    if (entry !== props.doc.edges[index]) moved += 1
  })
  if (next.joins !== props.doc.joins) moved += 1
  return Math.max(moved, 0)
})

function commitId(value: string): void {
  const selected = node.value
  if (!selected) return
  emit('commit', {
    label: `Rename ${selected.id} to ${value}`,
    next: renameCascade(props.doc, selected.id, toNodeId(value)),
  })
}

function commitLabel(): void {
  const selected = node.value
  if (!selected) return
  const label = labelDraft.value.trim()
  // `Label` is `min_length=1`: an empty label is a 422, so the stored one goes
  // back rather than a save failing on a box the author cleared.
  if (!label) {
    labelDraft.value = selected.label
    return
  }
  if (label === selected.label) return
  emit('commit', {
    label: 'Rename node',
    next: replaceNode(props.doc, { ...selected, label }),
    coalesceKey: coalesceKeyFor(selected.id, 'label'),
  })
}

/* --- the edge form ------------------------------------------------------ */

const sourceNode = computed(() =>
  edge.value ? (props.doc.nodes.find((entry) => entry.id === edge.value?.source) ?? null) : null,
)
const targetNode = computed(() =>
  edge.value ? (props.doc.nodes.find((entry) => entry.id === edge.value?.target) ?? null) : null,
)

/** Only kinds that HAVE an out-port can be a source; `output` has none at all. */
const sourceOptions = computed(() => props.doc.nodes.filter((entry) => outPortsOf(entry).length))
/** `accepts_incoming` is false only for `input`, which renders no target handle. */
const targetOptions = computed(() =>
  props.doc.nodes.filter((entry) => NODE_KINDS[entry.kind].acceptsIncoming),
)
const sourcePorts = computed(() => (sourceNode.value ? outPortsOf(sourceNode.value) : []))

function commitEdge(patch: Partial<BuilderEdge>, label: string): void {
  const selected = edge.value
  if (!selected) return
  emit('commit', {
    label,
    next: {
      ...props.doc,
      edges: props.doc.edges.map((entry) =>
        entry.id === selected.id ? { ...entry, ...patch } : entry,
      ),
    },
  })
}

/**
 * Moving an edge to a different source also moves its port, because a port name
 * belongs to the node that declares it.
 *
 * Left alone, `approve` on an edge re-pointed at a transform is
 * `edge-unknown-port` - an error produced by a control the author used
 * correctly. The new source's FIRST port is the only defensible answer, and
 * every kind that can be a source has one.
 */
function commitEdgeSource(event: Event): void {
  const source = toNodeId((event.target as HTMLSelectElement).value)
  const next = props.doc.nodes.find((entry) => entry.id === source)
  if (!next) return
  const ports = outPortsOf(next)
  const held = edge.value?.source_port ?? 'out'
  commitEdge(
    { source, source_port: ports.includes(held) ? held : (ports[0] ?? 'out') },
    'Move edge source',
  )
}

const targetInbound = computed(() =>
  targetNode.value ? inboundCount(props.doc, targetNode.value.id) : 0,
)
const targetJoins = computed(
  () => Boolean(targetNode.value && props.doc.joins[targetNode.value.id] === 'all'),
)

function commitTargetJoin(all: boolean): void {
  const target = targetNode.value
  if (!target) return
  const joins = { ...props.doc.joins }
  if (all) joins[target.id] = 'all'
  else delete joins[target.id]
  emit('commit', {
    label: all ? `Wait for every branch into ${target.id}` : `Fire ${target.id} on the first branch`,
    next: { ...props.doc, joins },
  })
}

/* --- multi-selection ---------------------------------------------------- */

/**
 * The billable nodes in a multi-selection, which is the only overlap worth
 * offering.
 *
 * `tier`, `max_iter` and `guardrail_max_retries` are the three fields `agent`
 * and `crew` genuinely share, and they are also the three that answer the
 * question a multi-selection is usually asked for: make all of these cheap. A
 * "common fields" pane that also offered `label` would be offering to give
 * six nodes the same name.
 */
const billable = computed(() =>
  selectedNodes.value.filter(
    (entry): entry is Extract<BuilderNode, { kind: 'agent' | 'crew' }> =>
      entry.kind === 'agent' || entry.kind === 'crew',
  ),
)

/** One value when they agree, `null` when they do not - which is what MIXED means. */
function shared<T>(read: (node: Extract<BuilderNode, { kind: 'agent' | 'crew' }>) => T): T | null {
  const values = billable.value.map(read)
  if (!values.length) return null
  return values.every((value) => value === values[0]) ? values[0] : null
}

const sharedTier = computed(() => shared((entry) => entry.config.tier))
const sharedIter = computed(() => shared((entry) => entry.config.max_iter))
const sharedRetries = computed(() => shared((entry) => entry.config.guardrail_max_retries))

/** ONE commit over every selected billable node, so it is ONE undo step. */
function commitToAll(patch: Partial<AgentConfig & CrewConfig>, label: string): void {
  let next = props.doc
  for (const entry of billable.value) next = patchConfig(next, entry, patch)
  emit('commit', { label, next })
}

function commitAllCount(field: 'max_iter' | 'guardrail_max_retries', event: Event): void {
  if (!props.vocabulary) return
  const low = field === 'max_iter' ? 1 : 0
  const high =
    field === 'max_iter'
      ? props.vocabulary.bounds.max_agent_iter
      : props.vocabulary.bounds.max_guardrail_retries
  const raw = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(raw)) return
  const clamped = Math.min(Math.max(Math.round(raw), low), high)
  commitToAll(
    { [field]: clamped } as Partial<AgentConfig & CrewConfig>,
    field === 'max_iter' ? 'Set iteration ceiling' : 'Set guardrail retries',
  )
}

/* --- landing on a control ----------------------------------------------- */

const root = useTemplateRef<HTMLElement>('root')

/**
 * Put the caret on the control a problem is about.
 *
 * Called by `ProblemsPanel`'s row click and by `F8`, and reached through the DOM
 * rather than through a chain of `defineExpose` down seven forms and four field
 * components - `data-field` is already on every row for exactly this, and a
 * ref chain would have to be threaded through `<component :is>`, which erases
 * it. The flash class is applied here; the keyframes are `builder.css`'s (§5.5),
 * where the reduced-motion block also names them.
 *
 * Returns whether it found anything, so a caller can tell "focused it" from
 * "that control is not on this form" instead of assuming.
 */
async function focusField(field: string): Promise<boolean> {
  await nextTick()
  const row = root.value?.querySelector<HTMLElement>(`[data-field="${CSS.escape(field)}"]`)
  if (!row) return false
  row.classList.remove('problem-anchor')
  // Reading `offsetWidth` restarts the animation; without it a second landing on
  // the same row adds a class the element already has and nothing plays.
  void row.offsetWidth
  row.classList.add('problem-anchor')
  const control = row.querySelector<HTMLElement>('input, select, textarea, button')
  control?.focus()
  return true
}

defineExpose({ focusField })
</script>

<template>
  <aside ref="root" class="inspector-rail" data-testid="inspector-rail" aria-label="Inspector">
    <!--
      `data-testid` because `e2e/builder.spec.ts` declared it a cross-package
      contract in its own docblock and then found only a class here: the WP-G
      suite anchors on testids so renaming a class cannot silently retire an
      assertion, and two of its ten tests failed with "element(s) not found"
      over exactly this attribute.
    -->
    <!-- No fallback list, ever (cut list 17). A palette and an inspector that
         invented `agent_ids` would draw graphs the compiler rejects, so the one
         honest thing is to say what failed. -->
    <div v-if="!vocabulary" class="rail-alert" role="alert">
      <AlertTriangle :size="14" aria-hidden="true" />
      <span>{{
        vocabularyProblem ||
        'The builder vocabulary has not loaded, so this rail cannot offer the agents, crews and result keys this build accepts.'
      }}</span>
    </div>

    <!--
      A `fieldset` rather than a flag threaded into seven forms: `disabled` on a
      fieldset disables every descendant control natively, keyboard included,
      and `display: contents` keeps it out of the rail's layout entirely.
    -->
    <fieldset v-else class="rail-lock" :disabled="readOnly">
      <!-- 1. One node. -->
      <template v-if="node && meta">
        <header class="rail-head">
          <!-- The card's own icon and the card's own accent, so the rail and the
               node an author just clicked read as one object rather than as a
               list that happens to be about it. `nodeKinds.ts` is the single
               source of both, which is why neither is restated here. -->
          <div class="rail-ident">
            <span class="rail-icon" :style="{ color: meta.accent }" aria-hidden="true">
              <component :is="meta.icon" :size="15" :stroke-width="1.8" />
            </span>
            <span class="rail-kicker" :style="{ color: meta.accent }">
              {{ nodeIndex }} · {{ node.kind }}
            </span>
          </div>
          <h2>{{ node.label }}</h2>
        </header>

        <!-- Pinned above the form, because these are the problems no control
             below can carry and they would otherwise be visible nowhere on this
             surface at all. -->
        <ul v-if="unplaced.length" class="rail-problems">
          <li
            v-for="problem in unplaced"
            :key="`${problem.code}:${problem.message}`"
            :class="problem.severity === 'warning' ? 'is-warn' : 'is-error'"
          >
            <code>{{ problem.code }}</code>
            <span>{{ problem.message }}</span>
          </li>
        </ul>

        <section class="rail-section" aria-label="Identity">
          <FieldRow
            label="Name"
            :control-id="`insp-${node.id}-node-label`"
            field="label"
            :node-id="node.id"
            :used="labelDraft.length"
            :max="vocabulary.bounds.max_label_chars"
            :warn-at="6"
            help="What the card is called on the canvas. Double-clicking the card renames it too."
            v-slot="row"
          >
            <input
              :id="`insp-${node.id}-node-label`"
              v-model="labelDraft"
              type="text"
              :maxlength="vocabulary.bounds.max_label_chars"
              :aria-describedby="row.describedBy"
              @keydown.enter.prevent="commitLabel"
              @blur="commitLabel"
            />
          </FieldRow>

          <NodeIdField
            v-model="idDraft"
            :committed="node.id"
            :taken="takenIds"
            label="Identifier"
            :control-id="`insp-${node.id}-node-id`"
            field="id"
            :references="referencesMoved"
            help="What every edge, join and state key in this graph calls this node."
            @commit="commitId"
          />
        </section>

        <section class="rail-section" :aria-label="`${node.kind} settings`">
          <component
            :is="INSPECTORS[node.kind]"
            :doc="doc"
            :node="node"
            :vocabulary="vocabulary"
            @commit="emit('commit', $event)"
            @notice="emit('notice', $event)"
          />
        </section>
      </template>

      <!-- 2. One edge. -->
      <template v-else-if="edge">
        <header class="rail-head">
          <span class="rail-kicker">EDGE</span>
          <h2 class="edge-title">
            <span>{{ edge.source }}</span>
            <ArrowRight :size="13" aria-hidden="true" />
            <span>{{ edge.target }}</span>
          </h2>
        </header>

        <ul v-if="edgeProblems.length" class="rail-problems">
          <li
            v-for="problem in edgeProblems"
            :key="`${problem.code}:${problem.message}`"
            :class="problem.severity === 'warning' ? 'is-warn' : 'is-error'"
          >
            <code>{{ problem.code }}</code>
            <span>{{ problem.message }}</span>
          </li>
        </ul>

        <section class="rail-section" aria-label="Edge endpoints">
          <FieldRow
            label="From"
            :control-id="`insp-${edge.id}-source`"
            field="source"
            mono
            v-slot="row"
          >
            <select
              :id="`insp-${edge.id}-source`"
              :value="edge.source"
              :aria-describedby="row.describedBy"
              @change="commitEdgeSource"
            >
              <option v-for="option in sourceOptions" :key="option.id" :value="option.id">
                {{ option.label }} ({{ option.id }})
              </option>
            </select>
          </FieldRow>

          <FieldRow
            label="Port"
            :control-id="`insp-${edge.id}-source-port`"
            field="source_port"
            mono
            help="Which way out of the source this edge leaves by. A gate's approve and revise may both land on the same node; the port is what tells them apart."
            v-slot="row"
          >
            <select
              :id="`insp-${edge.id}-source-port`"
              :value="edge.source_port"
              :aria-describedby="row.describedBy"
              :aria-invalid="row.invalid"
              @change="
                commitEdge(
                  { source_port: ($event.target as HTMLSelectElement).value },
                  'Change edge port',
                )
              "
            >
              <option v-for="port in sourcePorts" :key="port" :value="port">{{ port }}</option>
              <!-- A stored port the source does not declare stays visible rather
                   than being silently swapped for a legal one: `edge-unknown-port`
                   is already on this edge, and the author should see what it is
                   about. -->
              <option v-if="!sourcePorts.includes(edge.source_port)" :value="edge.source_port">
                {{ edge.source_port }} — not a port of {{ edge.source }}
              </option>
            </select>
          </FieldRow>

          <FieldRow
            label="To"
            :control-id="`insp-${edge.id}-target`"
            field="target"
            mono
            v-slot="row"
          >
            <select
              :id="`insp-${edge.id}-target`"
              :value="edge.target"
              :aria-describedby="row.describedBy"
              @change="
                commitEdge(
                  { target: toNodeId(($event.target as HTMLSelectElement).value) },
                  'Move edge target',
                )
              "
            >
              <option v-for="option in targetOptions" :key="option.id" :value="option.id">
                {{ option.label }} ({{ option.id }})
              </option>
            </select>
          </FieldRow>

          <!-- `in` is the ONLY legal target port, so this is a statement rather
               than a control. A second inbound port would be join semantics this
               document deliberately does not have: `joins` says how arrivals
               combine, and the answer is always "all". -->
          <FieldRow
            label="Arrives at"
            :control-id="`insp-${edge.id}-target-port`"
            field="target_port"
            mono
            group
            help="Every node has exactly one inbound port. How several arrivals combine is the fan-in setting below, not a second port."
          >
            <p class="readout">in</p>
          </FieldRow>
        </section>

        <section v-if="targetNode && targetInbound >= 2" class="rail-section" aria-label="Fan-in">
          <FieldRow
            label="Fan-in at the target"
            :control-id="`insp-${edge.id}-join`"
            field="joins"
            group
            :note="`${targetInbound} inbound`"
            help="AND waits for every branch into this node; OR runs it on the first that arrives."
          >
            <div class="segmented">
              <button type="button" :aria-pressed="targetJoins" @click="commitTargetJoin(true)">
                AND
              </button>
              <button type="button" :aria-pressed="!targetJoins" @click="commitTargetJoin(false)">
                OR
              </button>
            </div>
          </FieldRow>
        </section>
      </template>

      <!-- 3. More than one thing. -->
      <template v-else-if="many">
        <header class="rail-head">
          <span class="rail-kicker">SELECTION</span>
          <h2>
            {{ selectedNodes.length }} {{ selectedNodes.length === 1 ? 'node' : 'nodes' }}<template
              v-if="selectedEdges.length"
            >, {{ selectedEdges.length }} {{ selectedEdges.length === 1 ? 'edge' : 'edges' }}</template>
          </h2>
        </header>

        <section v-if="billable.length" class="rail-section" aria-label="Shared settings">
          <FieldRow
            label="Tier"
            control-id="insp-many-tier"
            field="tier"
            group
            :note="sharedTier === null ? 'MIXED' : `${billable.length} nodes`"
            :note-warn="sharedTier === null"
            help="Applied to every billable node in the selection, as one undo step."
          >
            <div class="segmented">
              <button
                v-for="tier in vocabulary.tiers"
                :key="tier"
                type="button"
                :aria-pressed="sharedTier === tier"
                @click="commitToAll({ tier: tier as Tier }, `Set ${billable.length} nodes to ${tier}`)"
              >
                <i v-if="tier === 'escalation'" class="tier-dot" aria-hidden="true" />
                {{ tier }}
              </button>
            </div>
          </FieldRow>

          <FieldRow
            label="Iterations"
            control-id="insp-many-iter"
            field="max_iter"
            :note="sharedIter === null ? 'MIXED' : undefined"
            :note-warn="sharedIter === null"
            v-slot="row"
          >
            <input
              id="insp-many-iter"
              type="number"
              min="1"
              :max="vocabulary.bounds.max_agent_iter"
              step="1"
              :value="sharedIter ?? ''"
              placeholder="Mixed"
              :aria-describedby="row.describedBy"
              @change="commitAllCount('max_iter', $event)"
            />
          </FieldRow>

          <FieldRow
            label="Guardrail retries"
            control-id="insp-many-retries"
            field="guardrail_max_retries"
            :note="sharedRetries === null ? 'MIXED' : undefined"
            :note-warn="sharedRetries === null"
            v-slot="row"
          >
            <input
              id="insp-many-retries"
              type="number"
              min="0"
              :max="vocabulary.bounds.max_guardrail_retries"
              step="1"
              :value="sharedRetries ?? ''"
              placeholder="Mixed"
              :aria-describedby="row.describedBy"
              @change="commitAllCount('guardrail_max_retries', $event)"
            />
          </FieldRow>
        </section>

        <!-- Never blank. A selection with nothing in common is a fact, and
             saying it is cheaper than an empty pane the author reads as broken. -->
        <p v-else class="rail-empty">
          Nothing in this selection shares a setting. Select one node to edit it.
        </p>
      </template>

      <!-- 4. Nothing selected. Graph settings, never blank space. -->
      <template v-else>
        <header class="rail-head">
          <span class="rail-kicker">GRAPH</span>
          <h2>{{ doc.name }}</h2>
        </header>
        <section class="rail-section" aria-label="Graph settings">
          <GraphSettings :doc="doc" :vocabulary="vocabulary" @commit="emit('commit', $event)" />
        </section>
      </template>
    </fieldset>
  </aside>
</template>

<style scoped>
.inspector-rail { display: flex; min-height: 0; flex-direction: column; overflow-y: auto; background: var(--surface-panel); border-left: 1px solid var(--border-default); }
/* Not a box. The fieldset exists for its `disabled` and for nothing else. */
.rail-lock { display: contents; min-inline-size: 0; margin: 0; padding: 0; border: 0; }
.rail-lock:disabled { opacity: 0.72; }
.rail-head { padding: 15px 16px 13px; border-bottom: 1px solid var(--border-default); }
.rail-ident { display: flex; align-items: center; gap: 7px; }
/* The wash is `color-mix` over the kind's own accent rather than a new custom
   property - the technique `WorkflowNode.vue` already uses, and the reason this
   package adds nothing to `tokens.css`. */
.rail-icon { display: grid; width: 24px; height: 24px; flex: 0 0 auto; place-items: center; background: color-mix(in srgb, currentColor 12%, transparent); border: 1px solid color-mix(in srgb, currentColor 30%, transparent); border-radius: var(--r-md); }
.rail-kicker { color: var(--accent-cyan); font: 700 var(--fs-11)/1 var(--font-mono); letter-spacing: 0.04em; text-transform: uppercase; }
.rail-head h2 { margin: 6px 0 0; overflow: hidden; color: var(--text-title); font: 600 var(--fs-15)/1.25 var(--font-display); text-overflow: ellipsis; }
.edge-title { display: flex; align-items: center; gap: 7px; font-family: var(--font-mono) !important; font-size: var(--fs-13) !important; }
.edge-title span { overflow: hidden; text-overflow: ellipsis; }
.edge-title svg { flex: 0 0 auto; color: var(--text-40); }

.rail-section { padding: 15px 16px; border-bottom: 1px solid var(--border-default); }
.rail-section:last-child { border-bottom: 0; }

/* The node's homeless problems. Pinned at the top rather than folded into the
   form, because by definition no control below is about them. */
.rail-problems { display: grid; gap: 7px; margin: 0; padding: 13px 16px; list-style: none; border-bottom: 1px solid var(--border-default); }
.rail-problems li { display: flex; gap: 6px; font-size: var(--fs-11); line-height: 1.5; }
.rail-problems code { flex: 0 0 auto; align-self: flex-start; padding: 1px 4px; font: 500 10px/1.5 var(--font-mono); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-xs); }
.rail-problems span { overflow-wrap: anywhere; }
.rail-problems li.is-error { color: var(--err-text); }
.rail-problems li.is-warn { color: var(--warn-text); }

.rail-alert { display: flex; align-items: flex-start; gap: 8px; margin: 16px; padding: 10px 11px; color: var(--warn-text); font-size: var(--fs-11); line-height: 1.5; background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: var(--r-md); }
.rail-alert svg { flex: 0 0 auto; margin-top: 1px; }
.rail-empty { margin: 0; padding: 16px; color: var(--text-40); font-size: var(--fs-11); line-height: 1.5; }

.readout { display: flex; min-height: 34px; align-items: center; margin: 0; padding: 7px 9px; color: var(--text-40); font: 500 var(--fs-12)/1.4 var(--font-mono); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.tier-dot { width: 6px; height: 6px; background: var(--warn-text); border-radius: var(--r-full); }
</style>
