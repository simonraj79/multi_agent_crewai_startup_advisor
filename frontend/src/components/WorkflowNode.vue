<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { Bot, Check, Cog, FileText, Inbox, ShieldCheck, Split, TriangleAlert } from 'lucide-vue-next'
import type { StudioNodeData } from '../composables/useValidatorRun'

const props = defineProps<{ data: StudioNodeData }>()

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

const ariaLabel = computed(() => {
  if (isQuarantine.value) return `${props.data.label}, ${quarantineLabel.value}`
  if (isRouter.value) return `${props.data.label}, deterministic router, no model call, ${stateLabel.value}`
  return `${props.data.label}, ${stateLabel.value}`
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

    <div class="node-icon" aria-hidden="true">
      <Inbox v-if="isQuarantine" :size="17" :stroke-width="1.8" />
      <Split v-else-if="isRouter" :size="15" :stroke-width="1.8" />
      <ShieldCheck v-else-if="data.kind === 'gate'" :size="17" :stroke-width="1.8" />
      <FileText v-else-if="data.kind === 'output'" :size="17" :stroke-width="1.8" />
      <Cog v-else-if="data.kind === 'step'" :size="17" :stroke-width="1.8" />
      <Bot v-else :size="17" :stroke-width="1.8" />
    </div>

    <div class="node-copy">
      <span class="node-eyebrow">{{ data.eyebrow }}</span>
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
.node-eyebrow { display: block; margin: 1px 0 3px; color: var(--text-40); font: 700 var(--fs-11)/1 var(--font-mono); }
.node-copy strong { display: block; color: var(--text-title); font: 600 var(--fs-15)/1.2 var(--font-display); }
.node-copy p { margin: 6px 0 0; color: var(--text-muted); font-size: var(--fs-12); line-height: 1.42; }

.node-meta { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 9px; }
.node-meta span { padding: 3px 6px; color: var(--text-body); font: 500 10px/1.2 var(--font-mono); background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-sm); }

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

@media (prefers-reduced-motion: reduce) {
  .workflow-node.is-running,
  .is-running .state-dot { animation: none; }
}
</style>