<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { VueFlow } from '@vue-flow/core'
import { Activity, ChevronLeft, ChevronRight, CircleDot, GitBranch, Radio } from 'lucide-vue-next'
import ChatRail from './components/ChatRail.vue'
import GateCard from './components/GateCard.vue'
import StatusPanel from './components/StatusPanel.vue'
import WorkflowEdge from './components/WorkflowEdge.vue'
import WorkflowNode from './components/WorkflowNode.vue'
import { useValidatorRun } from './composables/useValidatorRun'

const {
  descriptor,
  idea,
  status,
  transportMode,
  connection,
  runId,
  pendingGate,
  gateSubmitting,
  downloadStatus,
  downloadMessage,
  lastError,
  lastSequence,
  droppedFrames,
  chatEntries,
  usage,
  graphNodes,
  graphEdges,
  isActive,
  canLaunch,
  primaryLabel,
  initialize,
  launch,
  submitGate,
  cancel,
  downloadLogs,
  dismissError,
} = useValidatorRun()

/**
 * What the header badge says about the backend.
 *
 * `connection` tracks the WebSocket alone, and no socket is opened until a run
 * is launched - so a freshly loaded console read "Offline" while the API was
 * answering perfectly, and it is the first thing a visitor sees. "The backend
 * is down" and "no run yet" were the same word.
 *
 * When nothing is streaming, report the transport we actually probed instead:
 * `live` means the graph on screen came from the API, which is the honest
 * claim to make at that moment. Once a run is in flight the socket is the
 * truth again and its own state wins.
 */
const connectionLabel = computed(() => {
  if (transportMode.value === 'mock') return 'Mock mode'
  if (transportMode.value === 'probing') return 'connecting'
  if (!isActive.value && connection.value === 'offline') return 'ready'
  return connection.value
})

const chatCollapsed = ref(window.matchMedia('(max-width: 860px)').matches)
const controlsCollapsed = ref(false)
const activeView = ref<'graph' | 'activity'>('graph')

watch(activeView, (view) => {
  if (view === 'activity') chatCollapsed.value = false
})

onMounted(initialize)
</script>

<template>
  <a class="skip-link" href="#workflow-canvas">Skip to workflow canvas</a>
  <div
    class="studio-shell"
    :class="{
      'chat-is-collapsed': chatCollapsed,
      'controls-are-collapsed': controlsCollapsed,
      'activity-is-active': activeView === 'activity',
    }"
  >
    <header class="app-header">
      <div class="brand-lockup">
        <div class="brand-mark" aria-hidden="true"><CircleDot :size="20" :stroke-width="1.8" /></div>
        <div>
          <span>M2</span>
          <h1>Validator Studio</h1>
        </div>
      </div>

      <div class="header-context">
        <span class="workflow-name"><GitBranch :size="14" aria-hidden="true" />{{ descriptor.name }}</span>
        <span class="live-status" :class="`is-${connection}`" aria-live="polite">
          <Radio :size="13" aria-hidden="true" />
          {{ connectionLabel }}
        </span>
      </div>
    </header>

    <main class="studio-main">
      <ChatRail :entries="chatEntries" :collapsed="chatCollapsed" @toggle="chatCollapsed = !chatCollapsed" />

      <section id="workflow-canvas" class="graph-workspace" aria-labelledby="graph-title" tabindex="-1">
        <div class="canvas-heading">
          <div>
            <span class="canvas-kicker">FIXED VALIDATOR GRAPH</span>
            <h2 id="graph-title">Evidence pipeline</h2>
          </div>
          <div class="canvas-meta">
            <span><Activity :size="13" aria-hidden="true" />{{ status }}</span>
            <code>{{ descriptor.version }}</code>
          </div>
        </div>

        <VueFlow
          class="validator-flow"
          :nodes="graphNodes"
          :edges="graphEdges"
          :min-zoom="0.28"
          :max-zoom="1.45"
          :default-viewport="{ x: 0, y: 0, zoom: 0.72 }"
          :nodes-draggable="false"
          :nodes-connectable="false"
          :elements-selectable="false"
          :zoom-on-double-click="false"
          :fit-view-on-init="true"
          :fit-view-options="{ padding: 0.12, maxZoom: 0.9 }"
          aria-label="Idea validator workflow graph"
        >
          <template #node-workflow="nodeProps">
            <WorkflowNode v-bind="nodeProps" />
          </template>
          <template #edge-workflow="edgeProps">
            <WorkflowEdge v-bind="edgeProps" />
          </template>
          <Background :gap="20" :size="1" color="#777777" pattern-color="#777777" />
          <Controls position="bottom-left" :show-interactive="false" />
        </VueFlow>
      </section>

      <aside class="control-rail" aria-label="Validation controls">
        <button
          class="control-toggle icon-button"
          type="button"
          :aria-expanded="!controlsCollapsed"
          :aria-label="controlsCollapsed ? 'Expand control panel' : 'Collapse control panel'"
          :title="controlsCollapsed ? 'Expand controls' : 'Collapse controls'"
          @click="controlsCollapsed = !controlsCollapsed"
        >
          <ChevronLeft v-if="controlsCollapsed" :size="17" aria-hidden="true" />
          <ChevronRight v-else :size="17" aria-hidden="true" />
        </button>

        <div v-show="!controlsCollapsed" class="control-scroll">
          <GateCard
            v-if="pendingGate"
            :gate="pendingGate"
            :submitting="gateSubmitting"
            @submit="submitGate"
          />
          <StatusPanel
            v-model:idea="idea"
            :status="status"
            :transport-mode="transportMode"
            :connection="connection"
            :run-id="runId"
            :usage="usage"
            :last-sequence="lastSequence"
            :dropped-frames="droppedFrames"
            :can-launch="canLaunch"
            :is-active="isActive"
            :primary-label="primaryLabel"
            :active-view="activeView"
            :error="lastError"
            :download-status="downloadStatus"
            :download-message="downloadMessage"
            @launch="launch"
            @cancel="cancel"
            @download="downloadLogs"
            @dismiss-error="dismissError"
            @select-view="activeView = $event"
          />
        </div>
      </aside>
    </main>
  </div>
</template>
