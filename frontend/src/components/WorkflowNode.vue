<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { Bot, Check, Cog, FileText, Inbox, RedoDot, RotateCcw, ShieldCheck, Split, TriangleAlert } from 'lucide-vue-next'
import type { StudioNodeData } from '../composables/useValidatorRun'
import { MAX_NODE_CARD_ERROR_CHARS } from '../data/serverLimits'

const props = defineProps<{ data: StudioNodeData }>()

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
  >
    <Handle v-if="!isQuarantine" class="node-handle" type="target" :position="Position.Top" />

    <!--
      The character. One colour per node, the same colour in the dialogue rail
      and on the token that walks the edge, so an operator tracking one agent
      tracks one mark rather than re-reading a 7px label at every stop.

      Not on the quarantine node: that is instrumentation, not a cast member,
      and giving it a face would put it in the story.
    -->
    <div
      v-if="!isQuarantine"
      class="node-character"
      :class="{ 'is-receiving': data.receiving }"
      data-testid="node-character"
      :data-character="data.character"
      :style="characterStyle"
      aria-hidden="true"
    >
      <Split v-if="isRouter" :size="16" :stroke-width="2.2" />
      <ShieldCheck v-else-if="data.kind === 'gate'" :size="17" :stroke-width="2.2" />
      <FileText v-else-if="data.kind === 'output'" :size="17" :stroke-width="2.2" />
      <Cog v-else-if="data.kind === 'step'" :size="17" :stroke-width="2.2" />
      <Bot v-else :size="17" :stroke-width="2.2" />
    </div>

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
   competed with it would be the loudest thing on a canvas full of failures. */
.node-rerun {
  display: inline-flex;
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