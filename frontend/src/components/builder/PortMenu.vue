<script lang="ts">
import type { BuilderNode, NodeId, NodePosition, TransformOp } from '../../types/builder'

/**
 * The fixed end of the drag that opened this menu.
 *
 * Both directions exist because both gestures do (§4.2): dragging a PORT into
 * empty canvas creates the node downstream of it, and dragging the SOURCE end
 * of an existing edge into empty canvas creates the node upstream of a target
 * that is staying put. One component, because the only thing that changes is
 * which end of the new edge is the new node.
 */
export interface PortMenuOrigin {
  /**
   * `'source'` - the fixed end is an out-port and the new node becomes the
   * target. `'target'` - the fixed end is a node's `in` port and the new node
   * becomes the source.
   */
  direction: 'source' | 'target'
  node: NodeId
  /** The out-port the drag left by. Only meaningful when `direction === 'source'`. */
  port: string
}

/**
 * Everything the consumer needs to make ONE commit.
 *
 * The node and the edge travel together on purpose. §4.1 requires that a single
 * undo removes both, and the only construction that guarantees it is a single
 * command - two commits taken in quick succession are two undo steps forever,
 * and the second Ctrl+Z would leave a node dangling where a node had never
 * been asked for.
 */
export interface PortMenuCreation {
  node: BuilderNode
  source: NodeId
  sourcePort: string
  target: NodeId
  /** The undo label, e.g. `Add market analyst`. */
  label: string
}

/** Which vocabulary list a row came from, and what it therefore configures. */
export type PortMenuSlot =
  | { type: 'kind' }
  | { type: 'agent'; agentId: string }
  | { type: 'crew'; crewId: string }
  | { type: 'transform'; op: TransformOp }

export interface PortMenuEntry {
  key: string
  kind: BuilderNode['kind']
  /** The row's own words, and the node's label when it is created. */
  title: string
  /** The muted right-hand word: which list this came from. */
  hint: string
  slot: PortMenuSlot
}

/**
 * `market_analyst` -> `Market analyst`.
 *
 * Sentence case rather than Title Case, because these are ids from a server
 * list and "Market Analyst" quietly asserts a proper noun where there is only a
 * key. Clipped to 40, which is `BuilderNodeBase.label`'s ceiling and a hard 422
 * past it.
 */
export function titleiseId(id: string): string {
  const words = id.replace(/_/g, ' ').trim()
  return (words.charAt(0).toUpperCase() + words.slice(1)).slice(0, 40)
}
</script>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { NODE_KINDS, NODE_KIND_ORDER } from '../../data/nodeKinds'
import { mintNodeId, newNode } from '../../data/builderDefaults'
import { vocabulary, vocabularyProblem, vocabularyUnavailable } from '../../data/builderVocabulary'
import { nodeId, type NodeKind } from '../../types/builder'
import { useReturnFocus } from '../../composables/useReturnFocus'

const props = defineProps<{
  open: boolean
  /** The fixed end of the drag. `null` closes the menu regardless of `open`. */
  origin: PortMenuOrigin | null
  /** Where to anchor, in pixels inside the canvas host's own box. */
  at: { x: number; y: number }
  /** Where the new node lands, in FLOW coordinates, already rounded to the 20 grid. */
  position: NodePosition
  /** Every id already in the document, so the new one is free by construction. */
  takenIds: ReadonlySet<string>
}>()

const emit = defineEmits<{
  /** Create the node and the edge as ONE commit. */
  (event: 'create', payload: PortMenuCreation): void
  /** Dismissed. ZERO commits - this is the Escape contract of §4.5. */
  (event: 'close'): void
}>()

const query = ref('')
const active = ref(0)
const inputEl = ref<HTMLInputElement | null>(null)

/* ─── what can legally be created here ───────────────────────────────────── */

/**
 * The new node is the target when the drag came out of a port, so it must
 * accept an inbound edge - which rules out `input`, the one kind whose
 * `accepts_incoming` is false. Dragging the other way round, the new node is
 * the source and must have somewhere for the edge to leave by, which rules out
 * `output`.
 *
 * These are the §6.1 Tier-1 refusals restated as an absence rather than as a
 * validation: a row that cannot produce a legal edge is not offered, so Enter
 * on any visible row always works. No count and no bound is consulted here -
 * `max_fanout_width` is explicitly NOT the client's business (R6), and a fifth
 * outgoing edge is created from this menu exactly as readily as a first.
 */
const entries = computed<PortMenuEntry[]>(() => {
  const served = vocabulary.value
  if (!served) return []
  const direction = props.origin?.direction ?? 'source'

  const isLegal = (kind: NodeKind): boolean => {
    if (direction === 'source') return NODE_KINDS[kind].acceptsIncoming
    // The new node would be the SOURCE, so it needs somewhere for the edge to
    // leave by. Asked of `outPorts` over a default node of that kind rather
    // than written out as "not output": `output` drops out because
    // `_OUT_PORTS_BY_KIND` gives it an empty tuple, not because this file
    // remembers that it does. Seven cheap constructions, recomputed only when
    // the vocabulary or the drag origin changes - never per keystroke, which
    // `matches` handles separately.
    return NODE_KINDS[kind].outPorts(newNode(kind, { x: 0, y: 0 }, [])).length > 0
  }

  const legalKinds = NODE_KIND_ORDER.filter(isLegal)
  const kinds = new Set(legalKinds)
  const rows: PortMenuEntry[] = []

  for (const kind of legalKinds) {
    rows.push({
      key: `kind:${kind}`,
      kind,
      title: NODE_KINDS[kind].defaultLabel,
      hint: 'kind',
      slot: { type: 'kind' },
    })
  }
  // The named rows come after the seven generic ones because they are longer
  // lists and a typeahead that opens on 30 agent ids buries the seven kinds
  // that are the common answer.
  if (kinds.has('agent')) {
    for (const agentId of served.agent_ids) {
      rows.push({
        key: `agent:${agentId}`,
        kind: 'agent',
        title: titleiseId(agentId),
        hint: 'agent',
        slot: { type: 'agent', agentId },
      })
    }
  }
  if (kinds.has('crew')) {
    for (const crewId of served.crew_ids) {
      rows.push({
        key: `crew:${crewId}`,
        kind: 'crew',
        title: titleiseId(crewId),
        hint: 'crew',
        slot: { type: 'crew', crewId },
      })
    }
  }
  if (kinds.has('transform')) {
    for (const op of served.transform_ops) {
      rows.push({
        key: `transform:${op}`,
        kind: 'transform',
        title: titleiseId(op),
        hint: 'transform',
        slot: { type: 'transform', op },
      })
    }
  }
  return rows
})

const matches = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (needle === '') return entries.value
  return entries.value.filter(
    (entry) =>
      entry.title.toLowerCase().includes(needle) || entry.hint.toLowerCase().includes(needle),
  )
})

watch([() => props.open, matches], () => {
  // The highlight resets to the top on every keystroke. Keeping it pinned to an
  // index across a filter change is how a typeahead ends up creating the row
  // that used to be third.
  active.value = 0
})

const { capture, restore } = useReturnFocus()

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) {
      // The opener here is usually the canvas itself, which is exactly where an
      // author wants to be after an abort: the arrow keys and `1`-`7` are gated
      // on the canvas holding focus.
      restore()
      return
    }
    capture()
    query.value = ''
    active.value = 0
    await nextTick()
    inputEl.value?.focus()
  },
)

/* ─── creation ───────────────────────────────────────────────────────────── */

function build(entry: PortMenuEntry): PortMenuCreation | null {
  const origin = props.origin
  if (!origin) return null

  const base = newNode(entry.kind, props.position, props.takenIds)
  let node = base
  let label = `Add ${entry.title.toLowerCase()}`

  if (entry.slot.type !== 'kind') {
    // A named row names the node too: its id is the slug of what was picked, so
    // `${state.out__market_analyst}` downstream reads as the thing it refers to
    // rather than as `agent_3`.
    const id = mintNodeId(entry.title, props.takenIds)
    node = { ...base, id, label: entry.title }
  } else {
    // A generic kind row keeps `newNode`'s `Agent 1` / `agent_1`, and the undo
    // label says what was actually added rather than the row's word.
    label = `Add ${base.label.toLowerCase()}`
  }

  if (entry.slot.type === 'agent' && node.kind === 'agent') {
    node = { ...node, config: { ...node.config, agent_id: nodeId(entry.slot.agentId) } }
  } else if (entry.slot.type === 'crew' && node.kind === 'crew') {
    node = { ...node, config: { ...node.config, crew_id: nodeId(entry.slot.crewId) } }
  } else if (entry.slot.type === 'transform' && node.kind === 'transform') {
    node = { ...node, config: { ...node.config, op: entry.slot.op } }
  }

  if (origin.direction === 'source') {
    return { node, source: origin.node, sourcePort: origin.port, target: node.id, label }
  }
  // Dragging a target end into empty space: the new node feeds the fixed one,
  // and it leaves by its FIRST declared out-port - `out` for most kinds,
  // `approve` for a gate, the first branch for a router. `nodeKinds` answers
  // that, so the port drawn on the new card is the port the edge uses.
  const outPort = NODE_KINDS[node.kind].outPorts(node)[0]
  return { node, source: node.id, sourcePort: outPort, target: origin.node, label }
}

function choose(entry: PortMenuEntry | undefined): void {
  if (!entry) return
  const creation = build(entry)
  if (!creation) return
  emit('create', creation)
  emit('close')
}

function move(delta: number): void {
  const count = matches.value.length
  if (count === 0) return
  active.value = (active.value + delta + count) % count
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    move(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    move(-1)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    choose(matches.value[active.value])
  } else if (event.key === 'Escape') {
    // Zero commits. The whole gesture unwinds, which is what makes trying one
    // of these free.
    event.preventDefault()
    event.stopPropagation()
    emit('close')
  }
}

const heading = computed(() => {
  const origin = props.origin
  if (!origin) return ''
  return origin.direction === 'source'
    ? `Connect ${origin.node} · ${origin.port} to a new node`
    : `Feed a new node into ${origin.node}`
})

const activeId = computed(() => {
  const entry = matches.value[active.value]
  return entry ? `portmenu-${entry.key}` : undefined
})
</script>

<template>
  <div
    v-if="open && origin"
    class="builder-portmenu nodrag nopan nowheel"
    :style="{ left: `${at.x}px`, top: `${at.y}px` }"
    @keydown="onKeydown"
    @pointerdown.stop
  >
    <p class="builder-portmenu-head">{{ heading }}</p>

    <p v-if="vocabularyUnavailable" class="builder-portmenu-alert" role="alert">
      {{ vocabularyProblem }}
    </p>

    <template v-else>
      <input
        ref="inputEl"
        v-model="query"
        class="builder-portmenu-input"
        type="text"
        role="combobox"
        aria-expanded="true"
        aria-controls="builder-portmenu-list"
        :aria-activedescendant="activeId"
        aria-label="Search node kinds, agents, crews and transforms"
        placeholder="Type to filter…"
        autocomplete="off"
      />

      <ul id="builder-portmenu-list" class="builder-portmenu-list" role="listbox">
        <li
          v-for="(entry, index) in matches"
          :id="`portmenu-${entry.key}`"
          :key="entry.key"
          class="builder-portmenu-row"
          :class="{ 'is-active': index === active }"
          role="option"
          :aria-selected="index === active"
          @mousemove="active = index"
          @click="choose(entry)"
        >
          <component
            :is="NODE_KINDS[entry.kind].icon"
            class="builder-portmenu-icon"
            :class="NODE_KINDS[entry.kind].className"
            :size="13"
            :stroke-width="1.9"
            aria-hidden="true"
          />
          <span class="builder-portmenu-title">{{ entry.title }}</span>
          <span class="builder-portmenu-hint">{{ entry.hint }}</span>
        </li>
        <li v-if="matches.length === 0" class="builder-portmenu-none" role="option" aria-selected="false">
          nothing matches “{{ query }}”
        </li>
      </ul>
    </template>
  </div>
</template>
