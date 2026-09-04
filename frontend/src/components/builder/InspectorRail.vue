<script setup lang="ts">
import { computed, inject, nextTick, ref, useTemplateRef, watch } from 'vue'
import type { Component } from 'vue'
import { AlertTriangle, ArrowRight } from 'lucide-vue-next'
import { isAuthoredAgent, isAuthoredCrew, nodeId as toNodeId } from '../../types/builder'
import type {
  AgentConfig,
  AuthoredAgentConfig,
  AuthoredCrewConfig,
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
import ToolForm from './inspectors/ToolForm.vue'
import McpForm from './inspectors/McpForm.vue'
import SkillForm from './inspectors/SkillForm.vue'
import GraphSettings from './inspectors/GraphSettings.vue'
import ModelPicker from './inspectors/ModelPicker.vue'
import { AUTHORED_AGENT_FIELDS, AUTHORED_CREW_FIELDS, EXPERT_FIELDS } from './inspectors/authoredFields'
import { expertMode, setExpertMode } from './inspectors/expertMode'
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
 * `Record<NodeKind, Component>`, so an eleventh kind is a COMPILE error in this
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
 * `builderInspector.spec.ts` asserts the pairing by mounting all TEN and
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
  /*
   * The three ATTACHMENT kinds get one form each, and they are deliberately NOT
   * folded into one the way `agent` and `crew` are. That pair shares a form
   * because they extend one `_BillableConfig` in `document.py` - two thirds of
   * their controls are literally the same field. `ToolConfig`, `McpConfig` and
   * `SkillConfig` share nothing: three ids into three different catalogues,
   * owned by three different plans (06, 07, 08). One form over them would be a
   * switch wearing a component's name.
   */
  tool: ToolForm,
  mcp: McpForm,
  skill: SkillForm,
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
  /*
   * BOTH ARMS' UNION, not one arm's list. `agent` and `crew` each have a
   * library arm and an authored one (`document.py`'s two-member unions), and
   * `BillableForm` picks between them at render time - so a per-arm list here
   * would need this map to know which arm is selected, which it cannot: it is
   * keyed by KIND.
   *
   * The union is the right answer rather than a compromise. Over-listing costs
   * one thing - a problem anchored to a field the OPEN arm does not render
   * falls through to nothing instead of to the strip - and that state is
   * unreachable, because a problem naming `role` can only come from a document
   * that HAS a `role`, which is the authored arm. Under-listing costs the
   * opposite and it is reachable: `library-unknown-id` maps to `agent_id`, and
   * `compiler.py` raises it for a crew's `crew_id` too, which is exactly the
   * case this parameter was added for.
   */
  agent: [
    'tier', 'agent_id', 'credential_id', 'tools', 'convert',
    'max_iter', 'guardrail_max_retries', 'prompt_inputs',
    ...AUTHORED_AGENT_FIELDS,
  ],
  crew: [
    'tier', 'crew_id', 'max_iter', 'guardrail_max_retries', 'prompt_inputs',
    ...AUTHORED_CREW_FIELDS,
  ],
  gate: ['message', 'editable_fields', 'max_turns'],
  router: ['branches'],
  transform: ['op', 'args'],
  output: ['body_key', 'source'],
  tool: ['tool_id'],
  mcp: ['server_id'],
  skill: ['skill_id'],
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
  /**
   * Show a node on the canvas - the authored forms' "jump to node".
   *
   * The same channel `ProblemsPanel` already uses, and forwarded rather than
   * handled here, because selecting and centring is `useBuilderCanvas`'s job
   * and this rail holds no viewport.
   */
  focusNode: [id: string]
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

/*
 * D8's authored additions.
 *
 * The three above are what `agent` and `crew` share in the SCHEMA. These four
 * are what they share in the AUTHORED arm, and they are here for the same
 * reason the first three are: they answer the question a multi-selection is
 * usually asked for, one level up. "Make all of these cheap" is the first
 * three; "make all of these retry twice, on the same model, and route their
 * failures" is these.
 *
 * `authoredOnly` is the gate. A selection mixing a library agent with an
 * authored one has no `llm` in common - the library arm does not have one - so
 * offering the control would be offering to write a field into a config whose
 * schema forbids it, and `extra="forbid"` makes that a 422 rather than a
 * dropped key. The pane says so rather than showing controls that would fail.
 *
 * D8 lists `tool_failure_policy`, `memory` and `cache` as well. They are not
 * here, and the reason is the same gate read the other way: an authored CREW
 * has `memory` and `cache` but no `tool_failure_policy`, so the three do not
 * share one predicate and a control offered over "authored nodes" would be
 * wrong for one of the two kinds. They are one selection-kind check away and
 * that check is a decision about what a mixed selection should DO, which is not
 * this plan's to make quietly.
 */
const authoredOnly = computed(
  () =>
    billable.value.length > 0 &&
    billable.value.every((entry) =>
      entry.kind === 'agent' ? isAuthoredAgent(entry.config) : isAuthoredCrew(entry.config),
    ),
)

/** One value across the selection, or null - which is what MIXED means. */
function sharedAuthored<T>(read: (config: AuthoredAgentConfig | AuthoredCrewConfig) => T): T | null {
  if (!authoredOnly.value) return null
  const values = billable.value.map((entry) =>
    read(entry.config as AuthoredAgentConfig | AuthoredCrewConfig),
  )
  if (!values.length) return null
  return values.every((value) => value === values[0]) ? values[0] : null
}

const sharedModel = computed(() =>
  sharedAuthored((config) => ('llm' in config ? config.llm.model : config.manager_llm?.model ?? null)),
)
const sharedNodeRetries = computed(() => sharedAuthored((config) => config.retry.max_retries))
const sharedBackoff = computed(() => sharedAuthored((config) => config.retry.backoff_seconds))
const sharedOnError = computed(() => sharedAuthored((config) => config.on_error ?? 'fail'))

/**
 * ONE COMMIT over every selected authored node, so it is ONE undo step.
 *
 * `patch` is built per node rather than shared, because `llm` and `retry` are
 * composites: spreading a partial `llm` over a node would drop the other ten
 * leaves, and each node's ten are different.
 */
function commitAuthored(
  build: (config: AuthoredAgentConfig | AuthoredCrewConfig) => Partial<AgentConfig & CrewConfig>,
  label: string,
): void {
  let next = props.doc
  for (const entry of billable.value) {
    next = patchConfig(next, entry, build(entry.config as AuthoredAgentConfig | AuthoredCrewConfig))
  }
  emit('commit', { label, next })
}

function commitSharedModel(model: string): void {
  commitAuthored(
    (config) =>
      'llm' in config
        ? ({ llm: { ...config.llm, model } } as Partial<AgentConfig & CrewConfig>)
        : config.manager_llm
          ? ({ manager_llm: { ...config.manager_llm, model } } as Partial<AgentConfig & CrewConfig>)
          : ({} as Partial<AgentConfig & CrewConfig>),
    `Set ${billable.value.length} nodes to ${model}`,
  )
}

function commitSharedRetry(field: 'max_retries' | 'backoff_seconds', value: number | null): void {
  if (value === null) return
  commitAuthored(
    (config) => ({ retry: { ...config.retry, [field]: value } }) as Partial<AgentConfig & CrewConfig>,
    field === 'max_retries' ? 'Set node retries' : 'Set retry backoff',
  )
}

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

/* --- the expert switch, and landing on a control ------------------------- */

/**
 * Whether this control lives behind the global Expert switch.
 *
 * Read off `authoredFields.ts` rather than restated, so the switch, the "N
 * hidden" count, the region and this lookup are all the same list. A second
 * copy here is exactly how a control ends up unreachable from a problem row.
 */
function isExpertField(field: string): boolean {
  return (EXPERT_FIELDS as readonly string[]).includes(field)
}

/**
 * How many Expert controls the OPEN form has, for the header switch's label.
 *
 * Null when nothing with an Expert tier is selected - a gate, a transform, an
 * edge - and the switch is then absent rather than offering to reveal nothing.
 * The switch itself stays global; what varies is whether this rail has anything
 * to say about it.
 */
const expertOnForm = computed(() => {
  if (!node.value) return 0
  if (node.value.kind !== 'agent') return 0
  return isAuthoredAgent(node.value.config) ? EXPERT_FIELDS.length : 0
})

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
  /*
   * OPEN THE REGION BEFORE LOOKING IN IT.
   *
   * D1: a field carrying a problem forces its tier open. Two of the three tiers
   * can be shut, and they are shut in different ways - Advanced is a `<details>`
   * whose own form opens it from `forceOpen`, and Expert is ABSENT FROM THE DOM
   * behind a global switch. The first needs nothing here; the second does,
   * because a query for a control that has not been rendered finds nothing and
   * the caller is told "that control is not on this form" about a control that
   * is.
   *
   * Turning the switch on rather than smuggling one region open is deliberate:
   * the switch is global (decision 19), so an author who was sent to an expert
   * field once should find the rest of them where they left them. The `await`
   * below is what lets the newly rendered region exist before the query runs.
   */
  if (isExpertField(field)) setExpertMode(true)
  await nextTick()
  const row = root.value?.querySelector<HTMLElement>(`[data-field="${CSS.escape(field)}"]`)
  if (!row) return false
  row.classList.remove('problem-anchor')
  // Reading `offsetWidth` restarts the animation; without it a second landing on
  // the same row adds a class the element already has and nothing plays.
  void row.offsetWidth
  row.classList.add('problem-anchor')
  /*
   * The first ENABLED control, and the row itself when there is none.
   *
   * A disabled control silently refuses `focus()`, so the unqualified query
   * left the author teleported to a region they cannot type in with the caret
   * still down in the problems dock - the exact half-arrival R15's docked
   * inspector exists to avoid. It is not a hypothetical: `model-lacks-capability`
   * anchors to `llm.reasoning_effort`, and that control is disabled precisely
   * BECAUSE the model cannot honour it, so the one problem that most needs
   * walking to is the one that could not be walked to.
   *
   * Focusing the row rather than giving up: the sentence's repair is elsewhere
   * (`llm.model`, which it names), so the honest landing is the row that
   * carries the sentence. `tabIndex = -1` makes it programmatically focusable
   * without adding it to the tab order, so a keyboard walk is unchanged.
   */
  const control = row.querySelector<HTMLElement>(
    'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])',
  )
  if (control) control.focus()
  else {
    row.tabIndex = -1
    row.focus()
  }
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

          <!--
            THE EXPERT SWITCH LIVES HERE, IN THE HEADER, AND IT IS GLOBAL.
            Owner's decision 19: per node kind means an author learns the same
            control four times and it remembers a different answer each time.
            It is rendered only where the open form HAS an expert tier, because
            a switch offering to reveal nothing is worse than no switch.
          -->
          <label v-if="expertOnForm" class="expert-switch">
            <input
              type="checkbox"
              :checked="expertMode"
              @change="setExpertMode(($event.target as HTMLInputElement).checked)"
            />
            <span>Expert settings</span>
          </label>
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
            @focus-node="emit('focusNode', $event)"
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

          <!--
            D8's authored additions, offered only when EVERY selected node has
            them. A mixed selection sees the three above and this sentence,
            because a control that would 422 on half the selection is worse than
            a control that is not there.
          -->
          <template v-if="authoredOnly">
            <FieldRow
              label="Model"
              control-id="insp-many-model"
              field="llm.model"
              group
              :note="sharedModel === null ? 'MIXED' : undefined"
              :note-warn="sharedModel === null"
              help="Applied to every selected node in one undo step."
            >
              <ModelPicker
                mode="pick"
                :model-value="sharedModel"
                control-id="insp-many-model"
                @update:model-value="commitSharedModel"
              />
            </FieldRow>

            <FieldRow
              label="Node retries"
              control-id="insp-many-node-retries"
              field="retry.max_retries"
              :note="sharedNodeRetries === null ? 'MIXED' : undefined"
              :note-warn="sharedNodeRetries === null"
              v-slot="row"
            >
              <input
                id="insp-many-node-retries"
                type="number"
                min="0"
                :max="vocabulary.bounds.max_retries"
                step="1"
                :value="sharedNodeRetries ?? ''"
                placeholder="Mixed"
                :aria-describedby="row.describedBy"
                @change="commitSharedRetry('max_retries', Number(($event.target as HTMLInputElement).value))"
              />
            </FieldRow>

            <FieldRow
              label="Retry backoff"
              control-id="insp-many-backoff"
              field="retry.backoff_seconds"
              note-warn
              :note="sharedBackoff === null ? 'MIXED' : 'seconds'"
              v-slot="row"
            >
              <input
                id="insp-many-backoff"
                type="number"
                min="0"
                max="60"
                step="1"
                :value="sharedBackoff ?? ''"
                placeholder="Mixed"
                :aria-describedby="row.describedBy"
                @change="commitSharedRetry('backoff_seconds', Number(($event.target as HTMLInputElement).value))"
              />
            </FieldRow>

            <FieldRow
              label="On error"
              control-id="insp-many-on-error"
              field="on_error"
              group
              :note="sharedOnError === null ? 'MIXED' : undefined"
              :note-warn="sharedOnError === null"
              help="Routing grows a second source port named error on every selected card."
            >
              <div class="segmented">
                <button
                  type="button"
                  :aria-pressed="sharedOnError === 'fail'"
                  @click="commitToAll({ on_error: 'fail' }, 'Fail the run on error')"
                >
                  fail the run
                </button>
                <button
                  type="button"
                  :aria-pressed="sharedOnError === 'route'"
                  @click="commitToAll({ on_error: 'route' }, 'Route errors')"
                >
                  route it
                </button>
              </div>
            </FieldRow>
          </template>
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
.expert-switch { display: flex; align-items: center; gap: 6px; margin-top: 9px; color: var(--text-40); font: 600 var(--fs-11)/1 var(--font-body); cursor: pointer; }
.expert-switch input { accent-color: var(--accent-cyan); }
.expert-switch input:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 2px; }
.expert-switch:hover { color: var(--text-muted); }

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
