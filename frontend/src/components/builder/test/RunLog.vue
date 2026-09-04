<script setup lang="ts">
import { computed } from 'vue'
import type { ChatEntry, NodeRunState, UsageMetrics } from '../../../types/studio'

/**
 * The run log, grouped by node, with each node's calls and its cost.
 *
 * 13 D2's Run tab: "the log grouped by node with inputs/outputs/cost (12 D5)".
 * Plan 12 owns the run-phase group in `ProblemsPanel` and the shared log
 * SURFACE; this is the Run tab's own copy of it, in this plan's files, which is
 * what the brief for this wave asked for. The two are expected to converge; the
 * thing that must not happen is one of them being edited into the other's file
 * while both waves are open.
 *
 * WHY GROUPED BY NODE AND NOT BY TIME. A flat transcript is the right shape for
 * a conversation and the wrong one for a graph: three research branches run at
 * once, so time order interleaves them into something no reader can attribute.
 * Grouping answers the question an author has - what did THIS node do, and what
 * did it cost - and keeps the entries inside each group in the order they
 * arrived, which is the only place time order is informative.
 *
 * Entries with no `nodeId` are not dropped. They go in a final group, because a
 * frame the server could not attribute is exactly the frame worth reading - it
 * is the same judgement the `unattributed` quarantine node makes on the run
 * canvas.
 */

const props = defineProps<{
  entries: ChatEntry[]
  /** Per-node usage, keyed by the author's own node id. */
  usage: Record<string, UsageMetrics>
  /** Per-node state, for the dot beside each group's name. */
  states: Record<string, NodeRunState>
  /** Node labels by id, so a group reads as the card it is. */
  labels?: Record<string, string>
  /** Show only this node's entries - the Node tab's whole difference. */
  onlyNode?: string | null
}>()

interface LogGroup {
  nodeId: string
  label: string
  state: NodeRunState
  entries: ChatEntry[]
  usage: UsageMetrics | null
}

const UNATTRIBUTED = '__unattributed__'

const groups = computed<LogGroup[]>(() => {
  const order: string[] = []
  const byNode = new Map<string, ChatEntry[]>()
  for (const entry of props.entries) {
    const id = entry.nodeId ?? UNATTRIBUTED
    if (props.onlyNode && id !== props.onlyNode) continue
    if (!byNode.has(id)) {
      byNode.set(id, [])
      order.push(id)
    }
    byNode.get(id)?.push(entry)
  }
  return order.map((nodeId) => ({
    nodeId,
    label:
      nodeId === UNATTRIBUTED
        ? 'Unattributed'
        : props.labels?.[nodeId] ?? nodeId,
    state: props.states[nodeId] ?? 'idle',
    entries: byNode.get(nodeId) ?? [],
    usage: props.usage[nodeId] ?? null,
  }))
})

function money(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '$0.0000'
  return `$${value.toFixed(4)}`
}
</script>

<template>
  <div class="run-log" data-testid="run-log">
    <p v-if="!groups.length" class="run-log-empty" data-testid="run-log-empty">
      Nothing has been said yet.
    </p>

    <section
      v-for="group in groups"
      :key="group.nodeId"
      class="run-log-group"
      :data-node="group.nodeId"
      :data-state="group.state"
      data-testid="run-log-group"
    >
      <header class="run-log-head">
        <span class="run-log-dot" :class="`is-${group.state}`" aria-hidden="true" />
        <span class="run-log-name">{{ group.label }}</span>
        <span
          v-if="group.usage"
          class="run-log-cost"
          :data-testid="`run-log-cost-${group.nodeId}`"
        >
          {{ money(group.usage.costUsd) }} · {{ group.usage.totalTokens }} tokens
        </span>
      </header>

      <ol class="run-log-entries">
        <li
          v-for="entry in group.entries"
          :key="entry.id"
          class="run-log-entry"
          :class="`is-${entry.variant}`"
        >
          <span class="run-log-actor">{{ entry.actor }}</span>
          <span class="run-log-message">{{ entry.message }}</span>
          <span v-if="entry.calls.length" class="run-log-calls">
            <span
              v-for="call in entry.calls"
              :key="call.id"
              class="run-log-call"
              :class="{ 'is-active': call.active }"
            >
              {{ call.label }}
            </span>
          </span>
        </li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.run-log { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.run-log-empty { margin: 0; color: var(--text-40); font: 400 var(--fs-12)/1.5 var(--font-body); }

.run-log-group {
  min-width: 0;
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  background: var(--surface-well);
}
.run-log-head {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border-default);
}
.run-log-dot { width: 7px; height: 7px; border-radius: var(--r-full); background: var(--text-40); flex: none; }
.run-log-dot.is-running { background: var(--accent-cyan); }
.run-log-dot.is-waiting { background: var(--warn-text); }
.run-log-dot.is-completed { background: var(--accent-mint); }
.run-log-dot.is-error { background: var(--err-border); }
.run-log-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-title);
  font: 600 var(--fs-12)/1.3 var(--font-display);
}
.run-log-cost { color: var(--text-muted); font: 400 var(--fs-11)/1.3 var(--font-mono); }

.run-log-entries { margin: 0; padding: 6px 10px; list-style: none; display: flex; flex-direction: column; gap: 6px; }
.run-log-entry { display: flex; flex-wrap: wrap; gap: 4px 8px; min-width: 0; }
.run-log-actor { color: var(--text-40); font: 500 var(--fs-11)/1.5 var(--font-mono); flex: none; }
.run-log-message {
  flex: 1 1 220px;
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--text-body);
  font: 400 var(--fs-12)/1.5 var(--font-body);
}
.run-log-entry.is-warning .run-log-message { color: var(--warn-text); }
.run-log-entry.is-error .run-log-message { color: var(--err-text); }
.run-log-entry.is-system .run-log-message { color: var(--text-muted); }

.run-log-calls { display: flex; flex-wrap: wrap; gap: 4px; }
.run-log-call {
  padding: 1px 6px;
  border: 1px solid var(--border-default);
  border-radius: var(--r-pill);
  color: var(--text-muted);
  font: 500 var(--fs-11)/1.5 var(--font-mono);
}
.run-log-call.is-active { border-color: var(--accent-cyan); color: var(--accent-cyan); }
</style>
