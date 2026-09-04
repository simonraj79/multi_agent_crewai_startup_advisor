<script lang="ts">
import type { BuilderNodeData as CanvasNodeData } from '../../composables/useBuilderCanvas'
import type { BuilderNode as BuilderDocumentNode, NodeKind } from '../../types/builder'
import type { NodeRunState } from '../../types/studio'

/**
 * The design-time card. It is deliberately the SAME card as the run console's:
 * `builder.css`
 * restates none of `node-card.css`'s geometry, double-clip border, radius, fill
 * or shadow, it only re-lays the interior and re-tenants `--node-gradient`
 * (§5.1). Two cards that merely agree today are two cards; one stylesheet is
 * the only construction that makes them one product.
 *
 * ChatDev's card, for the comparison this package exists to win, is a gradient
 * border with a type line and an id line, and its active state is
 * `hue-rotate(0deg -> 360deg)` - an animation that walks the node through every
 * hue on the wheel, so a running node is briefly the colour of every other
 * node's kind. A palette that destroys its own identity to say "busy" is worse
 * than no palette; here the channel says KIND at design time and would say
 * STATE at run time, and neither reading ever borrows the other's colours.
 *
 * NOTHING HERE COMPUTES. Every judgement on this card - which ports exist,
 * whether an inbound edge is legal right now, whether a drop would close a
 * loop, the worst severity anchored here - is projected by `useBuilderCanvas`
 * and read from `data`. That is not tidiness: the canvas's `isValidConnection`
 * is what the MOUSE obeys, and a card that recomputed the same predicate would
 * be a second opinion that draws a port as valid which the pointer then
 * refuses. `nodeKinds.ts` is consulted here for exactly two things the
 * projection does not carry, the icon and the kind class, neither of which any
 * other surface can disagree with.
 */

/**
 * What the card renders, plus one RESERVED seam.
 *
 * `inbound` is supplied by the canvas projection and is real. `runState` is
 * not: nothing in `src/` writes it, the canvas is `data-mode="design"` and
 * `StudioView` mounts `WorkflowNode`, never this card, so the run tenancy of
 * `--node-gradient` (§5.1) is reserved CSS and this field is the hook it will
 * hang on. Said in the same words `BuilderEdge` uses for `active`, because a
 * seam described as a feature is the stub the brief forbids: the card's answer
 * without it - `idle` - is exactly right for a graph being drawn rather than
 * watched, and that is the only state this deliverable can produce.
 */
export interface BuilderNodeData extends CanvasNodeData {
  /** RESERVED. Written by nothing today; the run tenancy's hook when it lands. */
  runState?: NodeRunState
}

/* ─── the one mono line under the title (§5.2) ───────────────────────────── */

/**
 * The card's config summary, per kind, exactly as §5.2 enumerates it.
 *
 * It exists so the canvas answers "what is this node set to" without a click.
 * ChatDev's equivalent is `InlineConfigRenderer` inside a `SettingsModal` - the
 * settings are real, but reading one means covering the graph you are reading
 * it against, which is the failure R15 bans outright.
 */
export function summariseConfig(node: BuilderDocumentNode): string {
  switch (node.kind) {
    case 'input': {
      const { field, max_chars, required } = node.config
      return `${field} · ${max_chars} chars · ${required ? 'required' : 'optional'}`
    }
    case 'agent': {
      const { tier, agent_id, max_iter, tools } = node.config
      const bound = tools.length === 0 ? 'no tools' : `${tools.length} tool${tools.length === 1 ? '' : 's'}`
      return `${tier} · ${agent_id} · ${max_iter} iter · ${bound}`
    }
    case 'crew':
      return `${node.config.tier} · ${node.config.crew_id}`
    case 'gate': {
      const { max_turns, editable_fields } = node.config
      return `${max_turns} turn${max_turns === 1 ? '' : 's'} · ${editable_fields.length} editable`
    }
    case 'router': {
      const count = node.config.branches.length
      return `${count} branch${count === 1 ? '' : 'es'}`
    }
    case 'transform': {
      const names = Object.keys(node.config.args)
      return names.length === 0 ? node.config.op : `${node.config.op} · ${names.join(', ')}`
    }
    case 'output':
      return node.config.body_key
    /*
     * The three attachments (03 D6). Each answers "which one is this", which is
     * the only question a pill can be asked without opening it: an author looks
     * at a canvas of eight tools and needs to tell them apart, not to read their
     * parameters.
     *
     * A key glyph is NOT in this string. `credential_id` is rendered as its own
     * chip in the template, because a sentence saying "key" would be one more
     * token competing for a 160px pill, and because whether a tool has a key is
     * a yes/no an author scans for rather than reads.
     */
    case 'tool': {
      const names = Object.keys(node.config.params)
      return names.length === 0 ? node.config.tool_id : `${node.config.tool_id} · ${names.join(', ')}`
    }
    case 'mcp': {
      const count = node.config.tool_names.length
      // Nought is worth saying out loud: an MCP node with no tools selected
      // exposes nothing, and `bounds.py` reports it. The card should not read
      // like a node that is finished.
      return `${node.config.server_id} · ${count} tool${count === 1 ? '' : 's'}`
    }
    case 'skill':
      return node.config.skill_id
  }
}

/**
 * The summary, split into the lines the card actually draws.
 *
 * §5.2 asks for "one mono line, ellipsised", and at `NODE_W` 240 that line
 * ellipsises on the kind that carries the most: an agent measured
 * `escalation · scoper · 2 iter · no too…` and `cheap · market_analyst · 2 iter · 1 t…`
 * on the shipped validator template - five of ten visible cards losing their
 * last token. A truncated fact is worse than a shorter one, because it invites
 * the click into a modal that R15 bans; the summary exists to answer "what is
 * this set to" WITHOUT one.
 *
 * So the CONTENT is unchanged - `summariseConfig` is still the whole sentence,
 * still what `title` carries, still what the specs assert - and only the agent,
 * the one kind with four facts, wraps: identity on line one, budget on line
 * two. Two deterministic lines rather than a free wrap, because a wrap decided
 * by measurement makes a card's height depend on its label and reflows the
 * canvas under an author who is typing.
 */
export function summaryLines(node: BuilderDocumentNode): string[] {
  const whole = summariseConfig(node)
  if (node.kind !== 'agent') return [whole]
  const { tier, agent_id, max_iter, tools } = node.config
  const bound = tools.length === 0 ? 'no tools' : `${tools.length} tool${tools.length === 1 ? '' : 's'}`
  return [`${tier} · ${agent_id}`, `${max_iter} iter · ${bound}`]
}

/** The card's own name for a kind, uppercased into the eyebrow. */
export const KIND_EYEBROW: Record<NodeKind, string> = {
  input: 'INPUT',
  agent: 'AGENT',
  crew: 'CREW',
  gate: 'GATE',
  router: 'ROUTER',
  transform: 'TRANSFORM',
  output: 'OUTPUT',
  tool: 'TOOL',
  mcp: 'MCP',
  skill: 'SKILL',
}
</script>

<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { KeyRound, Lock } from 'lucide-vue-next'
import { BUILDER_HOVERED_NODE, BUILDER_READ_ONLY } from '../../composables/useBuilderCanvas'
import { NODE_KINDS } from '../../data/nodeKinds'
import { vocabulary } from '../../data/builderVocabulary'
import type { BuilderProblem } from '../../types/builder'

const props = defineProps<{
  id: string
  data: BuilderNodeData
  /** Vue Flow's own selection flag. */
  selected?: boolean
}>()

const emit = defineEmits<{
  /** A committed inline rename. The consumer turns it into ONE `setLabel` commit. */
  (event: 'rename', payload: { id: string; label: string }): void
  /** The problem badge was activated - walk to it, the way a ProblemsPanel row does. */
  (event: 'inspect-problem', payload: { id: string; problem: BuilderProblem }): void
  /** The join glyph was activated - toggle `joins[id]` between `'all'` and absent. */
  (event: 'toggle-join', payload: { id: string; joined: boolean }): void
  /** The caret is in the label; the `R` latch that put it there may be cleared. */
  (event: 'rename-started'): void
}>()

/** The two things the projection does not carry: the icon and the kind class. */
const meta = computed(() => NODE_KINDS[props.data.node.kind])
const node = computed(() => props.data.node)
const problems = computed(() => props.data.problems)

/* ─── the escalation ring ────────────────────────────────────────────────── */

/**
 * Only spend shouts. `tier` exists on `agent` and `crew` alone - it is the
 * field `MAX_ESCALATION_NODES` counts and the budget prices - and the cheap
 * tier gets no marker at all, so the ring means one thing and is never
 * furniture (§5.1).
 */
const isEscalation = computed(
  () =>
    (node.value.kind === 'agent' || node.value.kind === 'crew') &&
    node.value.config.tier === 'escalation',
)

/* ─── hover, written here and read by the edges (§5.4) ───────────────────── */

/**
 * The CARD writes the hovered id and the EDGE reads it, through the ref
 * `BuilderCanvas` provides. A prop would rebuild the whole nodes-and-edges
 * projection on every `mousemove`, which is the one interaction that has to
 * stay smooth. Injected with a `null` default so a card mounted outside a
 * canvas - in a spec, in a thumbnail - renders instead of throwing.
 */
const hovered = inject(BUILDER_HOVERED_NODE, null)
/**
 * The canvas's read-only flag, for the lock in the eyebrow (D-15-1). Null
 * outside a canvas. A top-level ref, so the template reads it unwrapped -
 * `readOnly`, never `readOnly.value`, which on an unwrapped boolean is
 * `undefined` and hides the lock everywhere.
 */
const readOnly = inject(BUILDER_READ_ONLY, null)
function setHover(value: string | null): void {
  if (hovered) hovered.value = value
}
onBeforeUnmount(() => {
  // A card unmounted mid-hover (deleted, filtered out, paged away) would
  // otherwise leave the whole edge field dimmed against a node that is gone.
  if (hovered && hovered.value === props.id) hovered.value = null
})

/* ─── ports (§5.3) ───────────────────────────────────────────────────────── */

/**
 * Where each source port sits along the bottom edge, as a percentage.
 *
 * The general rule is `((i + 0.5) / n) * 100`, which for one port is dead
 * centre. A gate is the one hardcoded exception: §5.3 puts `approve` at 30% and
 * `revise` at 70% rather than the formula's 25/75, because the two carry
 * permanent labels and the wider pair reads as a fork rather than as two ports
 * that happen to be adjacent.
 */
const portOffsets = computed<number[]>(() => {
  const ports = props.data.ports
  if (node.value.kind === 'gate' && ports.length === 2) return [30, 70]
  // `out` then `error`, on a node whose `on_error` is `route`. D1 puts the
  // error exit bottom-RIGHT rather than at the formula's 25/75, because the two
  // are not siblings: one is where the run goes and the other is where it goes
  // when it did not. Symmetry would say they were alternatives of equal weight.
  if (ports.length === 2 && ports[1] === 'error') return [40, 82]
  return ports.map((_port, index) => ((index + 0.5) / ports.length) * 100)
})

/**
 * The target ports drawn on the LEFT edge - `attach`, then `member`.
 *
 * `in` is excluded because it is drawn on the top edge, where the flow arrives.
 * D1 puts these two on the left so attachment wires run horizontally against
 * the flow's vertical, which is the thing that keeps a wired agent readable
 * once it has three tools and a skill hanging off it.
 */
const sideTargetPorts = computed(() => props.data.targetPorts.filter((port) => port !== 'in'))

const sideTargetOffsets = computed<number[]>(() =>
  sideTargetPorts.value.map((_port, index) => ((index + 0.5) / sideTargetPorts.value.length) * 100),
)

/**
 * Which class a source port and its label take.
 *
 * One function for both, because the port and its label must never disagree
 * about what they are - a mint disc under an amber word is a port that reads as
 * two different things depending on which half you looked at.
 */
function portTone(port: string): string {
  if (port === 'error') return 'is-port-error'
  // An attachment's one port is a SOURCE and it is the square, not a disc: the
  // shape is what survives 50% zoom and deuteranopia, where the violet does not.
  if (port === 'attach') return 'is-port-attach'
  if (node.value.kind === 'gate') return port === 'approve' ? 'is-approve' : 'is-revise'
  if (node.value.kind !== 'router') return ''
  const branch = node.value.config.branches.find((candidate) => candidate.label === port)
  return branch?.op === 'otherwise' ? 'is-otherwise' : 'is-branch'
}

/** The class a left-edge target port takes. Two ports, two shapes, no overlap. */
function targetTone(port: string): string {
  return port === 'member' ? 'is-port-member' : 'is-port-attach'
}

/**
 * Whether a source port carries a permanently visible label.
 *
 * Gate and router ports always do - which of a gate's two exits an edge leaves
 * by is the single fact the canvas exists to show. `error` does too, and for a
 * sharper reason: an unlabelled red disc beside an unlabelled grey one is a
 * decoration, and the whole point of an error exit is that a reader can tell it
 * from the ordinary one without opening anything.
 */
function portLabelled(port: string): boolean {
  if (port === 'error') return true
  if (port === 'attach') return false
  return node.value.kind === 'gate' || node.value.kind === 'router'
}

/** True when ANY source port on this card is labelled, so the footer lane is reserved. */
const labelledPorts = computed(() => props.data.ports.some((port) => portLabelled(port)))

/** An attachment's one port sits on the right edge, not along the bottom. */
const portsOnRight = computed(() => NODE_KINDS[node.value.kind].family === 'attachment')

/* ─── inline rename (§4.4) ───────────────────────────────────────────────── */

const editing = ref(false)
const titleEl = ref<HTMLElement | null>(null)

/** `BuilderNodeBase.label` is `1..40`, and a 41st character is a hard 422. */
const MAX_LABEL_CHARS = 40

async function startRename(): Promise<void> {
  editing.value = true
  await nextTick()
  const element = titleEl.value
  if (!element) return
  element.focus()
  const range = document.createRange()
  range.selectNodeContents(element)
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(range)
}

function commitRename(): void {
  if (!editing.value) return
  editing.value = false
  const next = (titleEl.value?.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, MAX_LABEL_CHARS)
  // An empty label is a 422 and a card with no name is unreadable, so an
  // emptied box REVERTS rather than committing. Undo is the confirmation
  // everywhere else in this editor; here there is nothing to undo yet.
  if (next === '' || next === node.value.label) return
  emit('rename', { id: props.id, label: next })
}

function cancelRename(): void {
  editing.value = false
}

/*
 * Both key handlers below do NOTHING - and consume NOTHING - unless the label
 * is actually being edited, and that guard is the repair for a defect that
 * reached far outside this card.
 *
 * They used to be `@keydown.enter.prevent` and `@keydown.esc.stop.prevent`,
 * modifiers that fire unconditionally. The title also carried `tabindex="-1"`,
 * which in Chromium makes an element MOUSE-focusable - so clicking any node
 * card put focus on its `<strong>`, and from that moment:
 *
 *   - `Escape` was `stopPropagation`d here and never reached the window
 *     listener, so the whole Escape ladder (abort the gesture, clear the
 *     selection, close the sheet) was dead for the rest of the session;
 *   - `Enter` was `preventDefault`ed here, and `useBuilderHotkeys` skips any
 *     event whose default is already prevented, so no Enter binding could fire.
 *
 * Measured: a `keydown` probe on `window` saw the capture phase and never the
 * bubble phase. The tabindex is gone when not editing, and the handlers now
 * declare their own stop/prevent only in the state that owns the key.
 */
function onTitleEnter(event: KeyboardEvent): void {
  if (!editing.value) return
  event.preventDefault()
  commitRename()
}

function onTitleEscape(event: KeyboardEvent): void {
  if (!editing.value) return
  event.stopPropagation()
  event.preventDefault()
  cancelRename()
}

/**
 * `R` on the focused node (section 4.4), driven through the projection.
 *
 * The card owns rename - the contenteditable, the caret placement, the
 * select-all, Enter-commits and Escape-reverts - so the shortcut's whole job is
 * to ask, and this is where the asking arrives. The previous route was a
 * `document.querySelector` in `BuilderView` against `[data-node-id]`, an
 * attribute nothing in the app ever wrote, whose miss was swallowed by `?.`.
 */
watch(
  () => props.data.renaming,
  (wanted) => {
    if (!wanted || editing.value) return
    void startRename()
    emit('rename-started')
  },
  { immediate: true },
)

// The DOM keeps whatever was typed after a cancel, because `contenteditable`
// text is not bound. Re-seeding it from the document is what makes Escape
// actually revert rather than merely stop editing.
watch(editing, (isEditing) => {
  if (!isEditing && titleEl.value) titleEl.value.textContent = node.value.label
})

/* ─── the reserved run tenancy (§5.1) ────────────────────────────────────── */

/**
 * `idle` unless something one day supplies otherwise. See `BuilderNodeData`:
 * nothing writes `runState` in this deliverable, so `is-idle` is the only class
 * this card can carry and the `[data-mode='run']` rules in `builder.css` are
 * reserved rather than reachable. Kept as a computed anyway, because the
 * alternative - hardcoding `is-idle` in the template - is the version that
 * silently stops working when the runner does arrive.
 */
const runState = computed<NodeRunState>(() => props.data.runState ?? 'idle')

/* ─── presentation ───────────────────────────────────────────────────────── */

const eyebrow = computed(
  () => `${String(props.data.index).padStart(2, '0')} · ${KIND_EYEBROW[node.value.kind]}`,
)
const summary = computed(() => summariseConfig(node.value))
const lines = computed(() => summaryLines(node.value))
/**
 * Offerable on a fan-in (§4.2), and always where AND is already on so it can be
 * turned back off. `inbound` is the canvas's count now rather than an absent
 * optional, so the glyph appears on every node that qualifies instead of only
 * on the ones where somebody had already switched it on from the inspector.
 */
const showsJoin = computed(() => props.data.inbound >= 2 || props.data.joined)

/* ─── the two silhouettes (§5.1, 03 D5) ─────────────────────────────── */

/**
 * A flow node is a CARD; an attachment is a PILL. One class, read off
 * `nodeKinds.ts`'s `family`, and the third identity channel D5 asks for.
 *
 * Colour and icon both stop working before the shape does. At the 0.5 zoom
 * criterion 7 captures at, an 11px eyebrow is 5.5px and two violet accents
 * eight points of lightness apart are one colour - but a 160px pill beside a
 * 240px card is still unmistakably a different sort of object. That is the
 * whole argument for spending a channel on silhouette rather than on a fourth
 * shade.
 */
const isAttachment = computed(() => meta.value.family === 'attachment')

/**
 * The three chips an attachment shows instead of a summary line (D6).
 *
 * The catalogue LABEL rather than the id where the server has served one: an
 * author picked "Firecrawl scrape" from a list and should see that, not
 * `firecrawl_scrape`. The fallback is the id, never a guess - this build's
 * `/vocabulary` does not serve `tools` yet (C2 v2 is criterion 5's, on the
 * Python side), so today every pill reads its id and that is honest.
 */
const attachmentChips = computed<{ text: string; key: boolean }[]>(() => {
  const current = node.value
  if (current.kind === 'tool') {
    const entry = vocabulary.value?.tools?.find((row) => row.tool_id === current.config.tool_id)
    return [
      { text: entry?.label ?? current.config.tool_id, key: false },
      // A KEY, not the credential's label or id: which key a tool uses is an
      // inspector question, and whether it needs one at all is the thing an
      // author scans a canvas for.
      ...(current.config.credential_id ? [{ text: 'key', key: true }] : []),
    ]
  }
  if (current.kind === 'mcp') {
    const count = current.config.tool_names.length
    return [
      { text: current.config.server_id, key: false },
      { text: `${count} tool${count === 1 ? '' : 's'}`, key: false },
      ...(current.config.credential_id ? [{ text: 'key', key: true }] : []),
    ]
  }
  if (current.kind === 'skill') return [{ text: current.config.skill_id, key: false }]
  return []
})
const showsBadges = computed(
  () => props.data.severity !== null || showsJoin.value || isEscalation.value,
)

const problemLabel = computed(() => {
  const count = problems.value.length
  if (count === 0) return ''
  const noun = props.data.severity === 'error' ? 'error' : 'warning'
  return `${count} ${noun}${count === 1 ? '' : 's'}`
})

const ariaLabel = computed(() => {
  const parts = [node.value.label, KIND_EYEBROW[node.value.kind].toLowerCase(), summary.value]
  if (problemLabel.value) parts.push(problemLabel.value)
  if (props.data.joined) parts.push('waits for every inbound branch')
  if (runState.value !== 'idle') parts.push(runState.value)
  return parts.join(', ')
})
</script>

<template>
  <article
    class="workflow-node builder-node"
    :class="[
      meta.className,
      `is-${runState}`,
      // D5's silhouette channel. `is-card` is written out rather than left as
      // the absence of `is-pill`, so a test and a stylesheet can both name it.
      isAttachment ? 'is-pill' : 'is-card',
      {
        'has-error': data.severity === 'error',
        'has-warning': data.severity === 'warning',
        'is-selected': selected,
        'is-anchor': data.anchor,
        'is-tier-escalation': isEscalation,
        'is-loop-target': data.loopTarget,
        'is-loop-illegal': data.loopIllegal,
        'is-anchored': data.flashing,
        // §4.1: the card plays `node-land` ONCE on arrival. Set from the
        // canvas's own arrival diff, so paste and `⌘D` acknowledge themselves
        // as visibly as a palette drop does.
        'is-landing': data.landing,
        'is-editing': editing,
        // Reserves the footer lane rather than letting a gate's two port labels
        // hang off the bottom of the card. On the CARD and not on the footer,
        // because the labels are positioned against the card's own box - a
        // positioned footer would anchor the handles to itself and lift every
        // port off the bottom edge.
        'has-port-labels': labelledPorts,
        // Section 4.1's keyboard link. A candidate is numbered; the current one
        // is what Enter takes. Both are gesture-lifetime only.
        'is-link-candidate': data.linkIndex != null,
        'is-link-current': data.linkCurrent,
        // Section 4.5. Dimmed, never hidden: removing a card would change the
        // shape of the graph an author is searching inside.
        'is-filter-match': data.filterMatch,
        'is-filter-dimmed': data.filterDimmed,
        // D2: a connect drag was released over this card and refused. One shot,
        // cleared by the canvas on a `--motion-medium` timer.
        'is-refused': data.refused,
      },
    ]"
    role="group"
    :aria-label="ariaLabel"
    @pointerenter="setHover(props.id)"
    @pointerleave="setHover(null)"
  >
    <!--
      §5.7's seam, and nothing more. The run console's rowing crew and `×N` lap
      chip are driven by `data.state` / `data.visits` in `WorkflowNode.vue`;
      this card renders an empty, correctly-sized 34px box so that when the
      runner lands the crew mounts into a slot that already exists and nothing
      reflows.

      It held twelve ChatDev character sprites until 2026-09-02, and three
      things were wrong with that at once. The spec reserved this slot and said
      "do not build a design-time animation into it; an idle canvas that rows is
      the ChatDev disco" - and only R4 was lifted above the spec, not §5.7. The
      walk cycle could never run: `runState` is written by nothing, so 132 of
      the 144 PNGs were unreachable and opening the validator template fetched
      195,832 bytes of frames 2 and 3 for a first stride that cannot occur. And
      the art was ChatDev's own, downscaled - the competitor's characters
      imported into the product whose whole argument is that it is not that
      competitor. The per-kind lucide icon in the eyebrow is this card's
      identity, and it is ours.
    -->
    <div class="node-crew-slot" aria-hidden="true" />

    <!--
      No target handle at all on an `input`, rather than an inert one:
      `accepts_incoming` is false only there, and an edge that arrives is
      `edge-target-refuses-incoming`. A port drawn and then refused is the
      silent disagreement §6.1 exists to prevent.

      `is-port-ready` is the canvas's OWN answer, projected - not a second
      opinion computed here - so a port that pulses is a port
      `isValidConnection` will accept.
    -->
    <Handle
      v-if="data.targetPorts.includes('in')"
      id="in"
      class="builder-port is-port-in"
      :class="{ 'is-port-ready': data.connectable }"
      type="target"
      :position="Position.Top"
    />

    <!--
      The STRUCTURAL target ports, on the left edge (D1): `attach` on an agent
      or a crew, `member` on a crew. Drawn from `data.targetPorts`, which the
      canvas projects from the same table `isValidConnection` refuses against -
      so a port that exists here is a port the pointer will accept, and there is
      no second opinion to drift.

      They carry no `is-port-ready`: that pulse is the answer to "could the edge
      you are currently dragging land here", and the canvas computes it for the
      flow port. An attach drag is a different question and gets Vue Flow's own
      red/green under the pointer instead, which is the more direct answer.
    -->
    <Handle
      v-for="(port, index) in sideTargetPorts"
      :id="port"
      :key="`target-${port}`"
      class="builder-port"
      :class="targetTone(port)"
      type="target"
      :position="Position.Left"
      :style="{ top: `${sideTargetOffsets[index]}%` }"
    />

    <span class="node-eyebrow-row builder-eyebrow-row">
      <!--
        D5: a 28px colour-FILLED squircle, not a bare 13px glyph on the panel.
        Flowise v2 draws its node icon this way and it is the reason its cards
        read at a glance; a stroke-only icon in the accent colour is a thin line
        that disappears at the zoom an author actually works at.

        The fill is `meta.accent` - the same value the minimap dot and the
        inspector's kicker use - passed as a custom property rather than as a
        `background` so the stylesheet keeps the radius, the size and the
        contrast rule in one place. The glyph is `--bg-app` on top, because
        every accent is a light tint and a light glyph on it would vanish.
      -->
      <span
        class="builder-kind-squircle"
        :style="{ '--kind-accent': meta.accent }"
        aria-hidden="true"
      >
        <component :is="meta.icon" :size="15" :stroke-width="2" />
      </span>
      <span class="node-eyebrow builder-eyebrow">{{ eyebrow }}</span>
      <!--
        Round 2, D-15-1: a stored version on the canvas is read-only, and the
        card says so where the eye lands rather than leaving it to a banner in
        the dock. The store refuses every commit either way; this is the cue.
      -->
      <span
        v-if="readOnly"
        class="builder-node-lock"
        title="Read-only — a stored version is on the canvas"
        data-testid="node-lock"
      >
        <Lock :size="11" :stroke-width="2" aria-hidden="true" />
      </span>
    </span>

    <!--
      Section 4.1: while `E` is live every legal target wears its number, and
      the one Enter would take wears it lit. Rendered only for the length of
      that gesture - the design canvas is still, and a badge nobody is currently
      choosing between is decoration.
    -->
    <span
      v-if="data.linkIndex != null"
      class="builder-link-index"
      :class="{ 'is-current': data.linkCurrent }"
      data-link-index
      >{{ data.linkIndex }}</span
    >

    <strong
      ref="titleEl"
      class="builder-title nodrag"
      :contenteditable="editing"
      :tabindex="editing ? 0 : undefined"
      spellcheck="false"
      :title="node.label"
      @dblclick.stop="startRename"
      @keydown.enter="onTitleEnter"
      @keydown.esc="onTitleEscape"
      @blur="commitRename"
      >{{ node.label }}</strong
    >

    <!--
      D6: an attachment's config is CHIPS, a flow node's is the mono summary
      line. Not a style choice - a pill is 160px and a comma-separated sentence
      in it ellipsises to nothing, while three chips wrap and each one still
      reads. The `title` carries the whole sentence either way, so nothing is
      lost to the shorter form.
    -->
    <span v-if="isAttachment" class="builder-chips" :title="summary">
      <span
        v-for="chip in attachmentChips"
        :key="chip.text"
        class="builder-chip"
        :class="{ 'is-key': chip.key }"
      >
        <KeyRound v-if="chip.key" :size="10" :stroke-width="2.2" aria-hidden="true" />
        {{ chip.text }}
      </span>
    </span>
    <span v-else class="builder-summary" :title="summary">
      <span v-for="line in lines" :key="line" class="builder-summary-line">{{ line }}</span>
    </span>

    <div v-if="showsBadges" class="builder-badges">
      <!--
        The count, and the server's sentence on hover or focus - verbatim, never
        a client paraphrase. Activating it walks to the problem through the same
        path a ProblemsPanel row uses, so "the red thing on the card" and "the
        row in the list" are one behaviour rather than two.
      -->
      <button
        v-if="data.severity"
        type="button"
        class="builder-badge builder-badge-problem nodrag"
        :class="data.severity === 'error' ? 'is-error' : 'is-warning'"
        :aria-label="`${problemLabel}. ${problems[0].message}`"
        @click.stop="emit('inspect-problem', { id: props.id, problem: problems[0] })"
      >
        {{ problems.length }}
        <span class="builder-problem-pop" role="tooltip">
          <span v-for="problem in problems" :key="problem.code + (problem.edge_id ?? '')">
            {{ problem.message }}
          </span>
        </span>
      </button>

      <!--
        AND / OR fan-in, on the card. AND waits for every inbound branch; OR
        fires on the first. It is one click here because the alternative - the
        inspector - means selecting the node to answer a question the topology
        has already asked out loud.
      -->
      <button
        v-if="showsJoin"
        type="button"
        class="builder-badge builder-badge-join nodrag"
        :class="{ 'is-on': data.joined }"
        :aria-pressed="data.joined"
        :title="
          data.joined
            ? 'Waits for every inbound branch. Click for first-to-arrive.'
            : 'Fires on the first inbound branch. Click to wait for all.'
        "
        @click.stop="emit('toggle-join', { id: props.id, joined: !data.joined })"
      >
        &#931;
      </button>

      <span
        v-if="isEscalation"
        class="builder-badge-escalation"
        role="img"
        aria-label="Escalation tier"
        title="Escalation tier"
      />
    </div>

    <!--
      The gate's two ports carry permanent labels. This is the interaction
      ChatDev buries behind a node click, a settings modal and a form field:
      here the fork is drawn, named and connectable without opening anything.
    -->
    <footer v-if="data.ports.length > 0" class="builder-ports" :class="{ 'is-labelled': labelledPorts }">
      <template v-for="(port, index) in data.ports" :key="port">
        <!--
          An attachment's one port goes on the RIGHT edge and every flow port
          along the bottom. Same element, same classes, one different side -
          because that one difference is what makes attachment wires horizontal
          and flow wires vertical, which is the whole of D1's argument about a
          wired agent staying readable.
        -->
        <Handle
          :id="port"
          class="builder-port is-port-out"
          :class="portTone(port)"
          type="source"
          :position="portsOnRight ? Position.Right : Position.Bottom"
          :style="portsOnRight ? { top: '50%' } : { left: `${portOffsets[index]}%` }"
        />
        <span
          v-if="portLabelled(port)"
          class="builder-port-label"
          :class="portTone(port)"
          :style="{ left: `${portOffsets[index]}%` }"
          >{{ port }}</span
        >
      </template>
    </footer>

    <p v-if="data.loopIllegal" class="builder-loop-note">only a gate or router may close a loop</p>
  </article>
</template>
