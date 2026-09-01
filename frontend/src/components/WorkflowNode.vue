<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { Bot, Check, Cog, FileText, Inbox, RotateCcw, ShieldCheck, Split, TriangleAlert } from 'lucide-vue-next'
import type { StudioNodeData } from '../composables/useValidatorRun'

const props = defineProps<{ data: StudioNodeData }>()

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
 * The crew boards the card it is working on.
 *
 * The progress strip already says which STAGE is running, but a stage is three
 * nodes at the fan-out and the operator still has to map a word at the top of
 * the screen back to a card on the canvas. ChatDev solves this by standing the
 * agent's character on the active node, which costs the viewer nothing; this is
 * the same idea in vector, sharing the strip's boat so the two read as one
 * system rather than two unrelated widgets.
 *
 * Only ever on a `running` node: a marker that is always present is furniture,
 * and furniture is what the 5px state chip already was.
 */
const isCrewed = computed(() => props.data.state === 'running' && !isQuarantine.value)

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

const ariaLabel = computed(() => {
  const pass = looped.value ? `, pass ${lap.value}` : ''
  if (isQuarantine.value) return `${props.data.label}, ${quarantineLabel.value}`
  if (isRouter.value) {
    return `${props.data.label}, deterministic router, no model call, ${stateLabel.value}${pass}`
  }
  return `${props.data.label}, ${stateLabel.value}${pass}`
})
</script>

<template>
  <article
    class="workflow-node"
    :class="[`is-${data.state}`, `is-${data.kind}`, { 'is-holding': isHolding, 'is-quiet': isQuarantine && !isHolding }]"
    role="group"
    :aria-label="ariaLabel"
  >
    <Handle v-if="!isQuarantine" class="node-handle" type="target" :position="Position.Top" />

    <!--
      The crew, moored to the card they are pulling. Aria-hidden because the
      node's own label already says "Running" - this is the same fact drawn at a
      size the default graph fit does not destroy.
    -->
    <div v-if="isCrewed" class="node-crew" data-testid="node-crew" aria-hidden="true">
      <svg viewBox="0 0 60 30" class="node-crew-svg">
        <!-- Hull, oars, rowers - same paint order as the strip's boat, and for
             the same reason: hull last buries the crew inside it. -->
        <path class="node-crew-hull" d="M2 17 C 8 15, 52 15, 58 17 L 55 23 C 49 27, 11 27, 5 23 Z" fill="currentColor" />
        <!-- Casing then oar, so the oar does not dissolve into the hull it
             crosses - both are `currentColor`. Same trick as the strip. -->
        <g class="node-crew-oars">
          <g v-for="i in 2" :key="i" class="node-crew-oar"
             :style="{ animationDelay: `${(i - 1) * 0.16}s` }">
            <line stroke="var(--bg-node)" stroke-width="4" stroke-linecap="round"
                  :x1="21 + (i - 1) * 17" y1="13" :x2="13 + (i - 1) * 17" y2="26" />
            <line stroke="currentColor" stroke-width="1.9" stroke-linecap="round"
                  :x1="21 + (i - 1) * 17" y1="13" :x2="13 + (i - 1) * 17" y2="26" />
          </g>
        </g>
        <g class="node-crew-rowers" fill="currentColor" stroke="var(--bg-node)" stroke-width="1.2">
          <g v-for="i in 2" :key="`r${i}`" class="node-crew-rower"
             :style="{ animationDelay: `${(i - 1) * 0.16}s` }">
            <circle :cx="23 + (i - 1) * 17" cy="6" r="3.1" />
            <path :d="`M${19.7 + (i - 1) * 17} 17 q0 -6.4 3.3 -6.4 q3.3 0 3.3 6.4 z`" />
          </g>
        </g>
      </svg>
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
.workflow-node {
  --node-gradient: linear-gradient(135deg, rgba(170, 255, 205, 0.5), rgba(153, 234, 249, 0.5), rgba(160, 196, 255, 0.5));
  position: relative;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 10px;
  width: 270px;
  min-height: 116px;
  padding: 13px;
  color: var(--text-body);
  background-image: linear-gradient(var(--bg-node), var(--bg-node)), var(--node-gradient);
  background-origin: border-box;
  background-clip: padding-box, border-box;
  border: 2px solid transparent;
  border-radius: var(--r-2xl);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.26);
  transition: filter var(--motion-fast) ease, box-shadow var(--motion-fast) ease;
}

.workflow-node.is-gate {
  --node-gradient: linear-gradient(135deg, rgba(255, 217, 122, 0.78), rgba(255, 184, 77, 0.68));
}

.workflow-node.is-output {
  --node-gradient: var(--gradient-brand);
}

/* Running is CYAN, completed is MINT. They used to share `--gradient-brand`
   verbatim, so the only thing separating "this agent is working" from "this
   agent is done" was a state chip that the graph's own default fit renders at
   under 5px. Two states that look identical are one state. */
.workflow-node.is-running {
  --node-gradient: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue));
  box-shadow: 0 0 0 1px rgba(153, 234, 249, 0.3), 0 14px 34px rgba(0, 0, 0, 0.35);
  animation: node-glowing 4s linear infinite, node-pulse 2s ease-in-out infinite;
}

.workflow-node.is-waiting {
  --node-gradient: linear-gradient(135deg, var(--accent-blue), var(--warn-text));
  box-shadow: 0 0 0 1px rgba(160, 196, 255, 0.26), 0 14px 34px rgba(0, 0, 0, 0.35);
}

.workflow-node.is-completed {
  --node-gradient: linear-gradient(135deg, var(--accent-mint), rgba(170, 255, 205, 0.55));
  background-image: linear-gradient(rgba(38, 48, 43, 0.98), rgba(40, 46, 44, 0.98)), var(--node-gradient);
}

.workflow-node.is-error {
  --node-gradient: linear-gradient(135deg, var(--err-border), #bd4a4a);
  background-image: linear-gradient(rgba(64, 35, 35, 0.96), rgba(42, 42, 42, 0.98)), var(--node-gradient);
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
  opacity: 0.6;
}

.is-quiet .node-icon { color: var(--text-40); background: transparent; border-color: var(--border-default); }
.is-quiet .node-copy strong { color: var(--text-muted); font-size: var(--fs-13); }
.is-quiet .node-copy p { color: var(--text-40); }

/* Quarantine: loud once the backend has actually parked frames on it. */
.workflow-node.is-holding {
  --node-gradient: linear-gradient(135deg, var(--warn-text), var(--warn-border));
  background-image: linear-gradient(rgba(46, 40, 26, 0.98), rgba(42, 42, 42, 0.98)), var(--node-gradient);
  box-shadow: 0 0 0 1px var(--warn-border), 0 12px 30px rgba(0, 0, 0, 0.3);
}

.is-holding .node-icon { color: var(--warn-text); background: var(--warn-bg); border-color: var(--warn-border); }
.is-holding .node-copy strong { color: var(--warn-text); }

.quarantine-count {
  gap: 4px;
  padding: 2px 7px;
  color: var(--text-40);
  font-variant-numeric: tabular-nums;
  border: 1px solid var(--border-default);
  border-radius: var(--r-pill);
}

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
.workflow-node.is-router.is-completed { border-style: solid; border-color: rgba(170, 255, 205, 0.3); }
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

.is-step .node-icon { color: var(--accent-blue); background: rgba(160, 196, 255, 0.08); border-color: rgba(160, 196, 255, 0.22); }

.node-icon {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  color: var(--accent-cyan);
  background: rgba(153, 234, 249, 0.08);
  border: 1px solid rgba(153, 234, 249, 0.22);
  border-radius: var(--r-md);
}

.is-gate .node-icon { color: var(--warn-text); background: var(--warn-bg); border-color: var(--warn-border); }
.is-output .node-icon { color: var(--accent-mint); }
.is-error .node-icon { color: var(--err-text); background: var(--err-bg); border-color: var(--err-border); }

.node-copy { min-width: 0; }
.node-eyebrow { display: block; color: var(--text-40); font: 700 var(--fs-11)/1 var(--font-mono); }
.node-copy strong { display: block; color: var(--text-title); font: 600 var(--fs-15)/1.2 var(--font-display); }
.node-copy p { margin: 6px 0 0; color: var(--text-muted); font-size: var(--fs-12); line-height: 1.42; }

.node-meta { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 9px; }
.node-meta span { padding: 3px 6px; color: var(--text-body); font: 500 10px/1.2 var(--font-mono); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-sm); }

/* The in-flight call. Reads as a live panel rather than another metadata chip,
   because it is the one thing on the card that answers "is this working?" */
.node-active {
  margin-top: 9px;
  padding: 6px 7px;
  background: color-mix(in srgb, var(--accent-running, #22d3ee) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent-running, #22d3ee) 35%, transparent);
  border-radius: var(--r-sm);
}
.node-active-head { display: flex; align-items: center; gap: 5px; }
.node-active-dot {
  width: 6px;
  height: 6px;
  flex: none;
  background: var(--accent-running, #22d3ee);
  border-radius: 50%;
  animation: node-active-pulse 1.4s ease-in-out infinite;
}
.node-active-label {
  overflow: hidden;
  color: var(--text-body);
  font: 600 9px/1.2 var(--font-mono);
  white-space: nowrap;
  text-overflow: ellipsis;
}
/* Tabular numerals so a ticking clock does not jitter its own width - a
   number that reflows every second reads as broken rather than as live. */
.node-active-elapsed {
  margin-left: auto;
  color: var(--accent-running, #22d3ee);
  font: 600 9px/1.2 var(--font-mono);
  font-variant-numeric: tabular-nums;
}
/* Two lines, then clamp. The full string is on `title`: a long query must not
   grow the card and shift the whole graph under the operator. */
.node-active-query {
  display: -webkit-box;
  margin: 4px 0 0;
  overflow: hidden;
  color: var(--text-40);
  font: 400 9px/1.35 var(--font-mono);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
}
.node-active-hint { margin: 4px 0 0; color: var(--text-40); font: 400 9px/1.35 var(--font-sans, inherit); }

@keyframes node-active-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.node-usage { display: flex; flex-wrap: wrap; gap: 4px 10px; margin: 8px 0 0; color: var(--text-40); font: 500 9px/1.2 var(--font-mono); }
.node-usage div { display: inline-flex; gap: 3px; }
.node-usage dt { text-transform: uppercase; }
.node-usage dd { margin: 0; color: var(--text-body); font-variant-numeric: tabular-nums; }

.node-state {
  position: absolute;
  top: 10px;
  right: 10px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-muted);
  font: 600 10px/1 var(--font-mono);
  text-transform: uppercase;
}

.is-running .node-state { color: var(--accent-cyan); }
.is-waiting .node-state { color: var(--warn-text); }
.is-completed .node-state { color: var(--accent-mint); }
.is-error .node-state { color: var(--err-text); }

.state-dot { width: 6px; height: 6px; background: currentColor; border-radius: 50%; }
.is-running .state-dot { animation: dot-pulse 1s ease-in-out infinite; }

.node-handle {
  width: 7px;
  height: 7px;
  background: var(--bg-node);
  border: 1px solid var(--accent-cyan);
  opacity: 0.72;
}

@keyframes node-glowing {
  0%, 100% { filter: saturate(1) drop-shadow(0 0 5px rgba(153, 234, 249, 0.3)); }
  50% { filter: saturate(1.35) drop-shadow(0 0 14px rgba(153, 234, 249, 0.56)); }
}

@keyframes node-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(153, 234, 249, 0), 0 12px 30px rgba(0, 0, 0, 0.26); }
  50% { box-shadow: 0 0 0 7px rgba(153, 234, 249, 0.08), 0 12px 30px rgba(0, 0, 0, 0.3); }
}

@keyframes dot-pulse { 50% { opacity: 0.35; } }

/*
 * The crew, moored to the running card.
 *
 * It sits ABOVE the card rather than inside it, for the same reason ChatDev
 * stands its character on the node: the card's own interior is already full of
 * label, description, model, tool and a three-column usage table, and anything
 * added inside competes with all of it. Above the top edge the marker is the
 * only thing at that height on the whole canvas, so "what is running" is
 * answered by the eye before any text is read - which matters most at the
 * default fit, where none of the text is legible anyway.
 */
.node-crew {
  position: absolute;
  top: -26px;
  left: 50%;
  width: 52px;
  height: 26px;
  color: var(--accent-cyan);
  transform: translateX(-50%);
  pointer-events: none;
}
.node-crew-svg { width: 100%; height: 100%; overflow: visible; filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.45)); }

/* Two rowers here, not the strip's three: the strip's three ARE the three
   research branches, and repeating that count on a single card would claim a
   fan-out that a single node does not have. */
.node-crew-oar { transform-box: fill-box; transform-origin: top right; animation: node-oar-stroke 1.05s ease-in-out infinite; }
.node-crew-rower { animation: node-rower-pull 1.05s ease-in-out infinite; }
.node-crew-hull { animation: node-hull-bob 2.1s ease-in-out infinite; }

@keyframes node-oar-stroke {
  0%, 100% { transform: rotate(0deg); }
  40% { transform: rotate(26deg); }
  70% { transform: rotate(-8deg); }
}
@keyframes node-rower-pull {
  0%, 100% { transform: translateX(0); }
  40% { transform: translateX(-2px); }
}
@keyframes node-hull-bob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(1.2px); }
}

/*
 * The eyebrow's margin moved here from `.node-eyebrow`, so the row's spacing is
 * byte-identical to the old single span whether or not a lap chip is present.
 *
 * `padding-right` reserves the lane the absolutely-positioned state chip
 * occupies. Without it the chip and a long eyebrow simply overlapped - which
 * they did not before only because nothing else shared the line.
 */
.node-eyebrow-row {
  display: flex;
  gap: 6px;
  align-items: center;
  min-width: 0;
  margin: 1px 0 3px;
  padding-right: 62px;
}
.node-eyebrow-row .node-eyebrow {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
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

@media (prefers-reduced-motion: reduce) {
  .workflow-node.is-running,
  .is-running .state-dot,
  .node-crew-oar,
  .node-crew-rower,
  .node-crew-hull,
  /* The dot stops pulsing; the elapsed COUNT keeps advancing, and that is the
     load-bearing signal anyway. Reduced motion must not cost a viewer the one
     piece of evidence that the run is alive. */
  .node-active-dot { animation: none; }
  /* The boat itself stays. Its PRESENCE is the signal - the stroke was only
     ever the flourish - so a reduced-motion viewer still sees which card the
     crew is on, and the lap chip is text and was never at risk. */
}
</style>