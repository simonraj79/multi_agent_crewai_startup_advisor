<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { Bot, Check, Cog, FileText, Inbox, RedoDot, RotateCcw, ShieldCheck, Split, TriangleAlert } from 'lucide-vue-next'
import AgentCharacter from './AgentCharacter.vue'
import type { PipState } from '../characters/pip'
import type { CastMark } from '../composables/useRunChoreography'
import type { StudioNodeData } from '../composables/useValidatorRun'
import { MAX_NODE_CARD_ERROR_CHARS } from '../data/serverLimits'

/**
 * Who stands on this card, and what they are doing (T2.5, T2.6).
 *
 * ONE prop rather than three, and passed rather than derived, for the reason
 * `character` and `receded` are already computed in the composable: the answer
 * depends on the RUN - the first `agent_role` any frame carried, whether a gate
 * downstream is holding this agent up - and a card has no way to know any of
 * that. `useRunChoreography` owns the store; this component owns the drawing.
 *
 * Optional, so a card mounted with no run behind it (the design-time gallery,
 * a spec, a mock transport) still draws a character rather than nothing.
 *
 * The type is the composable's `CastMark`, re-exported under the name the card
 * and its specs already use. It is the composable's because the OBJECT has to
 * come from there: `castFor` hands out a cached one so an unchanged card is
 * handed the same object and Vue can skip it, and a type living here would
 * invite a call site to build its own (T2.8).
 */
export type NodeCast = CastMark

/**
 * NO FALLTHROUGH ATTRIBUTES, and the reason is a defect a spec found (S4).
 *
 * Vue Flow's node slot passes `id`, `position`, `dimensions`, `selected`,
 * `dragging`, `zIndex` and half a dozen more as props of the slot scope, and
 * `v-bind="nodeProps"` in `StudioView` forwards every one this component does
 * not declare. They landed on the `<article>` as DOM attributes - most of them
 * as the literal string `[object Object]`, and `id` as the node's own id.
 *
 * `id="idea"` on a card is not merely untidy: an authored graph whose input
 * node is called `idea` produced a SECOND element with the id the launch
 * textarea already has, and `document.querySelector('#idea')` then resolved to
 * whichever came first in the document. A duplicate id is invalid HTML, it
 * breaks `label[for]`, and it breaks every tool that addresses an element by
 * id, a screen reader included.
 *
 * The node's id is still published, as `data-node-id` - an attribute that
 * cannot collide with anything, on a card that is already found by
 * `.vue-flow__node[data-id="…"] .workflow-node` in every spec that looks for
 * one. Vue Flow's own wrapper keeps its `data-id`; nothing on this element was
 * ever read.
 */
defineOptions({ inheritAttrs: false })

const props = defineProps<{ data: StudioNodeData; cast?: NodeCast }>()

const emit = defineEmits<{
  /** "Re-run from here" was pressed on this node. Carries its id (12 D6). */
  rerun: [string]
}>()

/**
 * The live elapsed clock for a call in flight.
 *
 * This is the whole fix for "it looks stuck". Every other animation on a
 * running node is an infinite CSS loop, which is identical at second 5 and at
 * minute 6 - it proves an animation is playing, never that work is happening.
 * A digit that changes once a second is the only honest progress an agent can
 * offer, because there is no denominator to put in a bar: the agent does not
 * know how far through it is either.
 *
 * The interval exists ONLY while a call is in flight, so a finished graph is
 * completely idle.
 */
const nowMs = ref(Date.now())
let ticker: ReturnType<typeof setInterval> | null = null

function stopTicker(): void {
  if (ticker !== null) {
    clearInterval(ticker)
    ticker = null
  }
}

watch(
  () => props.data.activeCall?.startedAt ?? null,
  (startedAt) => {
    stopTicker()
    if (startedAt === null) return
    nowMs.value = Date.now()
    ticker = setInterval(() => (nowMs.value = Date.now()), 1000)
  },
  { immediate: true },
)

onBeforeUnmount(stopTicker)

const activeElapsed = computed(() => {
  const call = props.data.activeCall
  if (!call) return ''
  const seconds = Math.max(0, Math.floor((nowMs.value - call.startedAt) / 1000))
  const minutes = Math.floor(seconds / 60)
  return minutes > 0 ? `${minutes}m ${seconds % 60}s` : `${seconds}s`
})

/**
 * The normalcy prior. A first-time operator has no way to know whether 40
 * seconds is fine, and that gap is exactly where "its stuck" was manufactured -
 * a real run was abandoned as hung while it was working correctly.
 *
 * Deliberately held back until 15s: saying "this can take a while" about
 * something that finishes in four seconds is noise, and noise is how a hint
 * stops being read.
 */
const showDurationHint = computed(
  () => props.data.activeCall !== null && (nowMs.value - props.data.activeCall.startedAt) >= 15_000,
)

/** The literal query a branch is running. On the wire all along; never shown. */
const activeQuery = computed(() => props.data.activeCall?.query ?? '')

const stateLabel = computed(() => ({
  idle: 'Idle',
  running: 'Running',
  waiting: 'Waiting',
  completed: 'Completed',
  error: 'Error',
}[props.data.state]))
const hasUsage = computed(() => props.data.usage.callCount > 0 || props.data.usage.totalTokens > 0 || props.data.usage.costUsd > 0)
const tokenCount = computed(() => new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(props.data.usage.totalTokens))

// The quarantine node is a diagnostic, not a stage. It stays faint while it is
// empty and only asserts itself once the backend has actually parked frames on
// it, so unattributed events are impossible to miss but never shout at an
// operator watching a clean run.
const isQuarantine = computed(() => props.data.kind === 'quarantine')
const quarantineCount = computed(() => props.data.frameCount)
const isHolding = computed(() => isQuarantine.value && quarantineCount.value > 0)
const quarantineLabel = computed(() =>
  quarantineCount.value === 0
    ? 'No unattributed frames'
    : `${quarantineCount.value} unattributed frame${quarantineCount.value === 1 ? '' : 's'}`,
)

// A router decides where the run goes next by reading a structured reply. It
// makes no model call at all (PRD §7.0), so it is drawn as plumbing between the
// stages rather than as another stage: compact, flat, dashed, no usage block.
// Costing and latency belong to the agent cards, and the graph should say so.
const isRouter = computed(() => props.data.kind === 'router')
// `step` and `start` nodes are deterministic too - cache reads, index writes,
// file persistence - so they carry the same "nothing is spent here" marker
// while keeping a full card, because they do real work.
const isDeterministic = computed(() => isRouter.value || props.data.kind === 'step')

/**
 * The agent, standing on the card it is working (T2.9).
 *
 * WHAT THIS REPLACES: a 34px disc holding a per-kind lucide icon, plus a
 * two-rower boat that appeared above the card while it was running. Both are
 * gone rather than kept alongside - the criterion's words are "replaced, not
 * duplicated" - and the reasons are worth recording, because the boat was a
 * deliberate design and this is not a tidy-up. The boat could say a node was
 * running and nothing else: it was the same two rowers on every card, so it
 * answered "is this one working" at a glance and "which agent is this" never;
 * and it appeared only while running, so fifteen sixteenths of the run it said
 * nothing at all. A character that is present in every state and different for
 * every agent answers both questions with one mark in the same 34px slot.
 *
 * WHO GETS ONE. Agents and crews, plus any node a frame actually named an
 * agent role for - the escape hatch for a published graph whose author drew
 * something the descriptor calls a `step`. Routers, gates, inputs, outputs and
 * the quarantine node do NOT: a router makes no model call (its card already
 * says `0 LLM CALLS`), and a gate is a person being asked for something. Giving
 * a human's turn a cartoon face would be the one place in this console where
 * the cast lied about who was doing the work.
 */
/*
 * `StudioNodeKind` has exactly six members and `agent` is the only one that
 * runs an agent, so this list is the other five written out rather than
 * inferred - and written out is the point: if a seventh kind is added, the
 * question "does this one have somebody in it" has to be answered rather than
 * defaulted. There is deliberately NO "promote on a frame role" escape hatch:
 * a builder `transform` compiles to `step` and an `input` to `start`, and T2
 * names both as characterless, so a hatch keyed on a role turning up in a
 * frame would put a face on the two nodes the criterion says must not have one.
 */
const CHARACTERLESS_KINDS: ReadonlySet<string> = new Set([
  'gate',
  'output',
  'quarantine',
  'router',
  'step',
])

const hasCharacter = computed(() => !CHARACTERLESS_KINDS.has(props.data.kind))

/**
 * The seed, and the pose. Both degrade rather than disappear when no run is
 * wired up: the label is rung three of the same ladder the composable walks,
 * and the node's own state maps onto four of the six poses. What a card can
 * never work out for itself is `speaking` (an `llm` frame bounds it) or the
 * `blocked` a gate imposes on the agent that fed it - which is exactly why the
 * store is one layer up.
 */
const castIdentity = computed(
  () => props.cast?.identity || props.data.label || props.data.nodeId,
)

const STATE_POSE: Record<string, PipState> = {
  idle: 'idle',
  running: 'working',
  waiting: 'blocked',
  completed: 'done',
  error: 'blocked-error',
}

const castPose = computed<PipState>(
  () => props.cast?.state ?? STATE_POSE[props.data.state] ?? 'idle',
)

/**
 * How many passes this node has had. Shown from 2, because "×1" on every card
 * of every run is noise that trains the eye past the one number that matters.
 *
 * This is the loop made visible ON the topology: the revise nodes are the only
 * ones that can climb on a normal run, and a research branch reading ×2 is the
 * single clearest sign that a scope revision sent the whole fan-out back.
 */
const lap = computed(() => props.data.visits ?? 0)
const looped = computed(() => lap.value > 1 && !isQuarantine.value)

/**
 * The character medallion's colour (plan 11 D1).
 *
 * A custom property rather than a `background` literal, so one declaration in
 * `motion.css` styles the disc and this only chooses which of the twelve it
 * fills with. `data.character` is a pure function of the node id, computed once
 * in the composable, which is what makes this medallion, the dialogue avatar
 * and the walking token provably the same colour rather than three call sites
 * that agree today.
 */
const characterStyle = computed(() => ({
  '--character-color': `var(--character-${props.data.character})`,
}))

/**
 * The failure, ON the card. Plan 12 D2.
 *
 * The rail already carried it, and the rail is not where somebody looking at a
 * red node is looking - they are looking at the red node, and it said "Error"
 * and nothing else. 120 characters is the bound the criterion sets and it is
 * the right one: a card is 270px wide and an untruncated stack trace would push
 * every node below it off the canvas. The FULL text is never lost - it is the
 * `title` and it is in the aria label, so a hover and a screen reader both get
 * all of it, and the NDJSON export has it whole.
 */
const errorMessage = computed(() => props.data.errorMessage ?? '')
const shortError = computed(() =>
  errorMessage.value.length > MAX_NODE_CARD_ERROR_CHARS
    ? `${errorMessage.value.slice(0, MAX_NODE_CARD_ERROR_CHARS - 1).trimEnd()}…`
    : errorMessage.value,
)
const hasError = computed(() => props.data.state === 'error' && Boolean(errorMessage.value))

/**
 * A node whose output was REPLAYED rather than run (10 D5).
 *
 * Drawn dimmed, because it is the one thing on a resumed canvas that did not
 * happen: the value came out of the source run's saved state and no model was
 * called for it. A replayed node drawn like a run node claims work nobody did.
 */
const isReplayed = computed(() => props.data.replayed === true)

const ariaLabel = computed(() => {
  const pass = looped.value ? `, pass ${lap.value}` : ''
  if (isQuarantine.value) return `${props.data.label}, ${quarantineLabel.value}`
  if (isRouter.value) {
    return `${props.data.label}, deterministic router, no model call, ${stateLabel.value}${pass}`
  }
  // The failure is in the label UNTRUNCATED. A screen reader has no hover, so
  // the `title` that carries the full sentence for a sighted reader reaches
  // nobody here - this is the only place the whole message is spoken.
  const failure = hasError.value ? `. ${errorMessage.value}` : ''
  const replay = isReplayed.value ? ', replayed from a saved run' : ''
  return `${props.data.label}, ${stateLabel.value}${pass}${replay}${failure}`
})
</script>

<template>
  <article
    class="workflow-node"
    :class="[
      `is-${data.state}`,
      `is-${data.kind}`,
      {
        'is-holding': isHolding,
        'is-quiet': isQuarantine && !isHolding,
        'is-receded': data.receded,
        'is-replayed': isReplayed,
      },
    ]"
    role="group"
    :aria-label="ariaLabel"
    :data-node-id="data.nodeId"
  >
    <Handle v-if="!isQuarantine" class="node-handle" type="target" :position="Position.Top" />

    <!--
      The cast, in the slot the icon medallion and the crew both used to hold.

      One mark per node, in the same 34px box, in every state - so an operator
      tracking one agent tracks one figure across the canvas, the rail and the
      token that walks the edge, rather than re-reading a 7px label at every
      stop. `AgentCharacter` publishes the seed and the pose as `data-character`
      and `data-state`, which is how the graph and the trace are checked against
      each other (T2.6) rather than asserted to agree.

      Aria-hidden, because the card's own `aria-label` already carries the label
      and the state in words. Two accessible names for one fact is a screen
      reader saying everything twice.
    -->
    <div
      v-if="!isQuarantine"
      class="node-character"
      :class="{ 'is-receiving': data.receiving, 'has-pip': hasCharacter }"
      data-testid="node-character"
      :data-character-index="data.character"
      :style="characterStyle"
      aria-hidden="true"
    >
      <AgentCharacter
        v-if="hasCharacter"
        data-testid="node-agent-character"
        :identity="castIdentity"
        :state="castPose"
        :size="32"
        :label="data.label"
      />
      <template v-else>
        <Split v-if="isRouter" :size="16" :stroke-width="2.2" />
        <ShieldCheck v-else-if="data.kind === 'gate'" :size="17" :stroke-width="2.2" />
        <FileText v-else-if="data.kind === 'output'" :size="17" :stroke-width="2.2" />
        <Cog v-else-if="data.kind === 'step'" :size="17" :stroke-width="2.2" />
        <Bot v-else :size="17" :stroke-width="2.2" />
      </template>
    </div>

    <div class="node-icon" aria-hidden="true">
      <Inbox v-if="isQuarantine" :size="17" :stroke-width="1.8" />
      <Split v-else-if="isRouter" :size="15" :stroke-width="1.8" />
      <ShieldCheck v-else-if="data.kind === 'gate'" :size="17" :stroke-width="1.8" />
      <FileText v-else-if="data.kind === 'output'" :size="17" :stroke-width="1.8" />
      <Cog v-else-if="data.kind === 'step'" :size="17" :stroke-width="1.8" />
      <Bot v-else :size="17" :stroke-width="1.8" />
    </div>

    <div class="node-copy">
      <span class="node-eyebrow-row">
        <span class="node-eyebrow">{{ data.eyebrow }}</span>
        <!--
          The lap, on the node. Text, so it survives reduced motion, a
          screenshot and the graph's own aggressive default zoom - none of which
          an animation does. This is the only place the topology itself admits
          it has cycles.

          In the eyebrow row rather than the corners: bottom-right collides with
          the three-column usage table on a node that has spent anything, and
          top-right is the state chip's. The eyebrow is the one line on the card
          with room to spare, and "01 - DEFINE (x2)" reads as one fact.
        -->
        <span
          v-if="looped"
          class="node-lap"
          data-testid="node-lap"
          :title="`This node has run ${lap} times`"
          aria-hidden="true"
        >
          <RotateCcw :size="10" :stroke-width="2.4" />
          <span>&times;{{ lap }}</span>
        </span>
      </span>
      <strong :title="isRouter ? data.description : undefined">{{ data.label }}</strong>
      <p v-if="!isRouter">{{ data.description }}</p>
      <span
        v-if="isDeterministic"
        class="node-deterministic"
        data-testid="deterministic-tag"
        title="Deterministic: this node makes no model call."
      >0 LLM CALLS</span>
      <div v-if="data.model || data.tool" class="node-meta">
        <span v-if="data.model">{{ data.model }}</span>
        <span v-if="data.tool">{{ data.tool }}</span>
      </div>
      <!--
        What this node is doing RIGHT NOW, and for how long. Present only while
        a call is in flight, so its presence is itself information: an operator
        can tell "working" from "between steps" without reading a word.
      -->
      <div v-if="data.activeCall" class="node-active" data-testid="node-active-call">
        <div class="node-active-head">
          <span class="node-active-dot" aria-hidden="true"></span>
          <span class="node-active-label">{{ data.activeCall.label }}</span>
          <span class="node-active-elapsed" data-testid="node-active-elapsed">{{ activeElapsed }}</span>
        </div>
        <p v-if="activeQuery" class="node-active-query" :title="activeQuery">"{{ activeQuery }}"</p>
        <p v-if="showDurationHint" class="node-active-hint" data-testid="node-active-hint">
          Reading pages it found — this normally takes under a minute.
        </p>
      </div>
      <!--
        The failure, where the failure is. It was in the rail and nowhere else,
        which is not where somebody looking at a red card is looking.
      -->
      <p
        v-if="hasError"
        class="node-error"
        data-testid="node-error-message"
        :title="errorMessage"
      >{{ shortError }}</p>
      <!--
        Offered on the failed node of a FINISHED run, and nowhere else. The
        server refuses a resume of a run still being written (422: a state still
        in flight is not a state to replay), so a control that appeared mid-run
        would be a button whose only outcome is an error message.
      -->
      <button
        v-if="data.rerunnable"
        class="node-rerun"
        type="button"
        data-testid="rerun-from-here"
        :title="`Replay this run up to ${data.label} and run again from there`"
        @click.stop="emit('rerun', data.nodeId)"
      >
        <RedoDot :size="12" aria-hidden="true" />
        Re-run from here
      </button>
      <span
        v-if="isReplayed"
        class="node-replayed"
        data-testid="node-replayed"
        title="This node's output came from the run being resumed. No model was called."
      >REPLAYED</span>
      <dl v-if="hasUsage && !isQuarantine && !isRouter" class="node-usage" aria-label="Node usage">
        <div><dt>Calls</dt><dd>{{ data.usage.callCount }}</dd></div>
        <div><dt>Tokens</dt><dd>{{ tokenCount }}</dd></div>
        <div><dt>Cost</dt><dd>${{ data.usage.costUsd.toFixed(4) }}</dd></div>
      </dl>
    </div>

    <div v-if="isQuarantine" class="node-state quarantine-count" data-testid="quarantine-count" :title="quarantineLabel">
      <TriangleAlert v-if="isHolding" :size="13" aria-hidden="true" />
      <span>{{ quarantineCount }}</span>
    </div>
    <div v-else class="node-state" :title="stateLabel">
      <Check v-if="data.state === 'completed'" :size="13" aria-hidden="true" />
      <TriangleAlert v-else-if="data.state === 'error'" :size="13" aria-hidden="true" />
      <span v-else class="state-dot" aria-hidden="true" />
      <span>{{ stateLabel }}</span>
    </div>

    <Handle v-if="!isQuarantine" class="node-handle" type="source" :position="Position.Bottom" />
  </article>
</template>

<style scoped>
/*
 * What is NOT here any more: the card's visual shell - geometry, the
 * double-clip gradient border, `.node-icon`, `.node-copy`, `.node-eyebrow-row`,
 * `.node-meta`, `.node-state`, `.node-usage`, the in-flight call panel, the
 * crew SVG, every `@keyframes` and the reduced-motion block - lives in
 * `src/assets/styles/node-card.css`, global, so the builder's design-time card
 * is guaranteed to be the same card rather than a copy that agrees today.
 *
 * What stayed is the RUN tenancy of `--node-gradient`: the per-state and
 * per-kind rules that say what this card means while a flow is executing. That
 * file's header records the three rules that had to travel with the shell for
 * cascade reasons, and `e2e/visual/run-canvas.spec.ts` is the gate that proved
 * the move changed nothing.
 */

.workflow-node.is-waiting {
  --node-gradient: linear-gradient(135deg, var(--accent-blue), var(--warn-text));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-blue) 26%, transparent), var(--shadow-raised);
}

.workflow-node.is-completed {
  --node-gradient: linear-gradient(135deg, var(--accent-mint), color-mix(in srgb, var(--accent-mint) 55%, transparent));
  background-image: var(--node-wash-completed), var(--node-gradient);
}

.workflow-node.is-error {
  --node-gradient: linear-gradient(135deg, var(--err-border), var(--node-danger-deep));
  background-image: var(--node-wash-error), var(--node-gradient);
}

/* Quarantine: recessive while empty. */
.workflow-node.is-quarantine {
  width: 230px;
  min-height: 0;
  box-shadow: none;
}

.workflow-node.is-quiet {
  color: var(--text-muted);
  background-image: none;
  background-color: var(--surface-well);
  border: 1px dashed var(--border-default);
  /* `--recede-opacity`, not a third number. Plan 11 criterion 3 names exactly
     two levels on a card - receded 0.55 and present 1.0 - and a run measured
     THREE, because this rule carried its own 0.6 (critic P-09). An empty
     quarantine node is a card that is stepped back, which is what
     `--recede-opacity` already means, so the vocabulary is one value rather
     than two that happen to look similar. */
  opacity: var(--recede-opacity);
}

.is-quiet .node-icon { color: var(--text-40); background: transparent; border-color: var(--border-default); }
.is-quiet .node-copy strong { color: var(--text-muted); font-size: var(--fs-13); }
.is-quiet .node-copy p { color: var(--text-40); }

/* Quarantine: loud once the backend has actually parked frames on it. */
.workflow-node.is-holding {
  --node-gradient: linear-gradient(135deg, var(--warn-text), var(--warn-border));
  background-image: var(--node-wash-holding), var(--node-gradient);
  box-shadow: 0 0 0 1px var(--warn-border), var(--shadow-controls);
}

.is-holding .node-icon { color: var(--warn-text); background: var(--warn-bg); border-color: var(--warn-border); }
.is-holding .node-copy strong { color: var(--warn-text); }

.is-holding .quarantine-count { color: var(--warn-text); background: var(--warn-bg); border-color: var(--warn-border); }

/*
 * Routers: plumbing, not a stage. A deterministic branch with zero model calls
 * behind it must not read like one of the six agents, so it keeps the column
 * width (the graph stays a clean spine) and gives up everything else - the
 * gradient border, the card height, the description, the usage block and the
 * running glow. These rules sit after the state rules on purpose: a router that
 * is running or completed must still look like a router.
 */
.workflow-node.is-router {
  min-height: 0;
  padding: 9px 12px;
  grid-template-columns: 26px minmax(0, 1fr);
  align-items: center;
  color: var(--text-muted);
  background-image: none;
  background-color: var(--surface-well);
  border: 1px dashed var(--border-default);
  box-shadow: none;
  animation: none;
}

.is-router .node-icon { width: 26px; height: 26px; color: var(--text-muted); background: transparent; border-color: var(--border-default); }
.is-router .node-copy strong { color: var(--text-body); font: 600 var(--fs-13)/1.15 var(--font-mono); }
.is-router .node-state { top: 9px; right: 11px; }

.workflow-node.is-router.is-running { border-style: solid; border-color: var(--accent-cyan); }
.workflow-node.is-router.is-running .node-icon { color: var(--accent-cyan); }
.workflow-node.is-router.is-completed { border-style: solid; border-color: color-mix(in srgb, var(--accent-mint) 30%, transparent); }
.workflow-node.is-router.is-error { border-style: solid; border-color: var(--err-border); }

/* Deterministic marker. Shared with `step`/`start` nodes, which keep a full
   card because they do real I/O, but spend nothing on a model either. */
.node-deterministic {
  display: inline-block;
  margin-top: 5px;
  padding: 2px 6px;
  color: var(--text-40);
  font: 700 9px/1.3 var(--font-mono);
  letter-spacing: 0.04em;
  background: transparent;
  border: 1px solid var(--border-default);
  border-radius: var(--r-pill);
}

.is-step .node-icon { color: var(--accent-blue); background: color-mix(in srgb, var(--accent-blue) 8%, transparent); border-color: color-mix(in srgb, var(--accent-blue) 22%, transparent); }

.is-gate .node-icon { color: var(--warn-text); background: var(--warn-bg); border-color: var(--warn-border); }
.is-output .node-icon { color: var(--accent-mint); }
.is-error .node-icon { color: var(--err-text); background: var(--err-bg); border-color: var(--err-border); }

.is-running .node-state { color: var(--accent-cyan); }
.is-waiting .node-state { color: var(--warn-text); }
.is-completed .node-state { color: var(--accent-mint); }
.is-error .node-state { color: var(--err-text); }

/* The failure sentence, on the card. Red on the card's own error tint rather
   than in a box: it is part of what the card SAYS, not an annotation on it. */
.node-error {
  margin: 7px 0 0;
  overflow-wrap: anywhere;
  color: var(--err-text);
  font: 500 var(--fs-11)/1.4 var(--font-mono);
}

/* Small, and deliberately not a `.button`: this is a per-node control on a
   270px card, and the primary action on this screen is Launch. A control that
   competed with it would be the loudest thing on a canvas full of failures.

   `pointer-events: auto` IS THE WHOLE REASON THIS BUTTON WORKS, and it is not
   defensive. Vue Flow writes `pointer-events: none` INLINE on every
   `.vue-flow__node` whose node is not draggable, selectable or connectable and
   carries no handlers - which on this canvas is all fourteen of them
   (`StudioView.vue` passes `:nodes-draggable="false"`,
   `:nodes-connectable="false"`, `:elements-selectable="false"`). Measured: the
   card resolves to `pointer-events: none`, and `elementFromPoint` over the
   middle of a card answers `.vue-flow__pane`. So a click on this button was
   intercepted by the pane every time - the control rendered, reported itself
   visible and enabled, and did nothing.

   Scoped to the BUTTON and not lifted off the card, deliberately. The card
   being transparent to the pointer is Vue Flow behaving correctly for a node
   nobody can select: it is what lets an operator pan the canvas by dragging
   ACROSS a card, and on a fourteen-node graph the cards are most of the
   surface. Restoring pointer events to the whole card would trade a working
   button for a canvas that stops panning wherever there is a node. A
   descendant may re-enable itself under a `none` ancestor - that is what the
   property is for. */
.node-rerun {
  display: inline-flex;
  pointer-events: auto;
  gap: 5px;
  align-items: center;
  margin-top: 8px;
  padding: 4px 8px;
  color: var(--err-text);
  font: 600 10px/1.2 var(--font-mono);
  background: var(--err-bg);
  border: 1px solid var(--err-border);
  border-radius: var(--r-pill);
  cursor: pointer;
}

.node-rerun:hover { color: var(--text-title); border-color: var(--border-hover); }
.node-rerun:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 2px; }

/* A node whose value came out of a saved run. Dimmed, because it is the one
   thing on a resumed canvas that did not happen. */
.workflow-node.is-replayed { opacity: 0.62; }
.node-replayed {
  display: inline-block;
  margin-top: 6px;
  padding: 2px 6px;
  color: var(--text-40);
  font: 700 9px/1.3 var(--font-mono);
  letter-spacing: 0.04em;
  border: 1px dashed var(--border-default);
  border-radius: var(--r-pill);
}

.node-handle {
  width: 7px;
  height: 7px;
  background: var(--bg-node);
  border: 1px solid var(--accent-cyan);
  opacity: 0.72;
}

/* The lap chip, sized to sit on the eyebrow's own baseline without pushing the
   row taller - the card's min-height is tuned and a taller first line would
   reflow every node on the canvas, looped or not. */
.node-lap {
  display: inline-flex;
  flex: 0 0 auto;
  gap: 2px;
  align-items: center;
  padding: 0 4px 0 3px;
  color: var(--warn-text);
  font: 700 10px/1.5 var(--font-mono);
  font-variant-numeric: tabular-nums;
  background: var(--warn-bg);
  border: 1px solid var(--warn-border);
  border-radius: var(--r-pill);
}

</style>