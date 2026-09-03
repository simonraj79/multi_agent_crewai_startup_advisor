<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { VueFlow } from '@vue-flow/core'
import { Activity, ChevronLeft, ChevronRight, CircleDot, FileText, GitBranch, LogOut, PenTool, Play, Radio, X } from 'lucide-vue-next'
import ChatRail from '../components/ChatRail.vue'
import CrewProgress from '../components/CrewProgress.vue'
import GateCard from '../components/GateCard.vue'
import ReportPanel from '../components/ReportPanel.vue'
import RunHistory from '../components/RunHistory.vue'
import StatusPanel from '../components/StatusPanel.vue'
import WorkflowEdge from '../components/WorkflowEdge.vue'
import WorkflowNode from '../components/WorkflowNode.vue'
import { useValidatorRun } from '../composables/useValidatorRun'
import { clearRunHandoff, readRunHandoff } from '../data/builderRunHandoff'
import type { SignedInUser } from '../composables/useAuthGate'

/**
 * The run console, moved out of `App.vue` unchanged.
 *
 * Everything below the header's new segmented pair is the same code that ran
 * here before the builder existed, in the same order, with the same comments -
 * the move is a move, not a rewrite, which is what let the ten specs that
 * exercise `useValidatorRun` stay untouched through it. `App.vue` keeps the
 * three-phase auth gate and switches between this and `BuilderView`; the sign-in
 * wall and the session chip therefore arrive as props rather than being read
 * twice.
 */

const props = defineProps<{
  /** The signed-in account, or null when authentication is not configured. */
  user: SignedInUser | null
  /** True once the session request has resolved to a signed-in account. */
  authenticated: boolean
}>()

const emit = defineEmits<{
  build: []
  signOut: []
}>()

/**
 * Which published graph this console is pointed at, if the author sent one over
 * from the builder.
 *
 * Read ONCE at setup rather than watched: `useValidatorRun` takes the workflow
 * as a construction option, so changing it mid-session would mean rebuilding
 * the composable underneath a live run. Clearing it navigates, which remounts.
 */
const handoff = ref(readRunHandoff(props.user?.id ?? null))

/**
 * Names for `<Controls>`'s three unnamed buttons.
 *
 * `onMounted` and a query, because the labels have to land on elements the
 * library renders and there is no prop for them. Keyed off the library's own
 * class names, which are its public API - they are what every Vue Flow theme
 * targets - and each write is guarded, so a version that renames one leaves the
 * other two named rather than throwing on the render.
 */
const CONTROL_NAMES: ReadonlyArray<[string, string]> = [
  ['.vue-flow__controls-zoomin', 'Zoom in'],
  ['.vue-flow__controls-zoomout', 'Zoom out'],
  ['.vue-flow__controls-fitview', 'Fit the graph to the view'],
]

onMounted(() => {
  for (const [selector, name] of CONTROL_NAMES) {
    document.querySelector(selector)?.setAttribute('aria-label', name)
  }
})

/**
 * What the canvas heading says, when it is not the validator.
 *
 * `descriptor.name` is the graph the console is ACTUALLY drawing, and after a
 * builder handoff that is the author's own workflow. The kicker's "FIXED"
 * likewise stops being true the moment the graph is one somebody just drew.
 * Both fall back to the validator's own wording verbatim, which is the only
 * thing this console could draw before the builder existed.
 */
const canvasKicker = computed(() => (handoff.value ? 'PUBLISHED GRAPH' : 'FIXED VALIDATOR GRAPH'))
const canvasTitle = computed(() =>
  handoff.value ? handoff.value.name || descriptor.value.name : 'Evidence pipeline',
)

const {
  descriptor,
  idea,
  gatesMode,
  status,
  transportMode,
  connection,
  runId,
  pendingGate,
  gateSubmitting,
  downloadStatus,
  downloadMessage,
  lastError,
  transportProblem,
  graphProblem,
  report,
  verdictSummary,
  lastSequence,
  droppedFrames,
  chatEntries,
  usage,
  nodeStates,
  nodeVisits,
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
} = useValidatorRun(undefined, {
  workflowId: handoff.value?.workflowId,
  inputField: handoff.value?.inputField,
  // The run pointer is this person's (D-01-5): keyed to the signed-in user so
  // the next person on the same browser never restores it, and swept on
  // sign-out. The handoff above is read the same way.
  userId: () => props.user?.id ?? null,
})

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

/**
 * The report sheet opens itself the first time a body arrives and stays
 * dismissible after that. Auto-opening is the point: the previous behaviour
 * was that a finished run showed no conclusion at all, and a reveal the
 * operator has to discover is barely better than none.
 *
 * Keyed on the run id as well as the body so a relaunch re-arms it.
 */
const reportOpen = ref(false)
let announcedReport = ''
watch(
  () => [runId.value, report.value?.markdown_body] as const,
  ([id, body]) => {
    if (!body) return
    const key = `${id}:${body.length}`
    if (key === announcedReport) return
    announcedReport = key
    reportOpen.value = true
  },
)

const chatCollapsed = ref(window.matchMedia('(max-width: 860px)').matches)
const controlsCollapsed = ref(false)
const activeView = ref<'graph' | 'activity'>('graph')

watch(activeView, (view) => {
  if (view === 'activity') chatCollapsed.value = false
})

/*
 * What tells the history list to refetch.
 *
 * A string rather than a watcher on the run itself, so RunHistory needs to know
 * nothing about how a run progresses - only that something worth re-reading has
 * happened. It changes when a run starts (new id) and on every status
 * transition, which is exactly when the row for that run would be stale.
 */
const historyReloadKey = computed(() => `${runId.value ?? ''}:${status.value}`)

/*
 * The studio probes the API only once it is allowed to.
 *
 * `initialize()` used to run unconditionally on mount. With authentication in
 * front of it that would fire a guaranteed 401 before the visitor has had a
 * chance to sign in - wasted, and it would leave `transportMode` decided by a
 * request made on behalf of nobody. `{ immediate: true }` keeps the
 * already-signed-in and the auth-disabled cases behaving exactly as before,
 * because this view is only mounted once the gate has resolved.
 */
let studioStarted = false
watch(
  () => props.authenticated || props.user === null,
  (allowed) => {
    if (!allowed || studioStarted) return
    studioStarted = true
    void initialize()
  },
  { immediate: true },
)

/**
 * Stop running the published graph and go back to the built-in validator.
 *
 * A reload rather than a ref reset, and deliberately: the workflow is a
 * construction option of `useValidatorRun`, so the honest way to change it is
 * to build the composable again. Reaching in to reassign `workflowId` would
 * leave the descriptor, the node map and any restored run belonging to the
 * previous graph, which is how a console comes to draw one workflow's topology
 * over another's frames.
 */
function backToValidator(): void {
  clearRunHandoff(props.user?.id ?? null)
  handoff.value = null
  window.location.reload()
}
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
        <!--
          The one control this view gained in the move. `Run` is pressed because
          you are looking at the run console; `Build` leaves for `#/build`. The
          builder never offers the mirror image of this pair inside itself
          (cut list item 1) - it navigates back here through the same route.
        -->
        <div class="segmented workspace-switch" role="group" aria-label="Workspace">
          <button type="button" :aria-pressed="false" @click="emit('build')">
            <PenTool :size="14" aria-hidden="true" /> Build
          </button>
          <button type="button" :aria-pressed="true">
            <Play :size="14" aria-hidden="true" /> Run
          </button>
        </div>

        <span class="workflow-name"><GitBranch :size="14" aria-hidden="true" />{{ descriptor.name }}</span>
        <span class="live-status" :class="`is-${connection}`" aria-live="polite">
          <Radio :size="13" aria-hidden="true" />
          {{ connectionLabel }}
        </span>

        <div v-if="user" class="account-chip">
          <!--
            `referrerpolicy` is not decoration. Google's avatar host receives a
            Referer naming this app on every load otherwise, and `no-referrer`
            costs nothing here because the image is public.
            @error hides a broken avatar rather than showing the browser's
            placeholder - Google's URLs do expire.
          -->
          <img
            v-if="user.image"
            class="account-avatar"
            :src="user.image"
            alt=""
            referrerpolicy="no-referrer"
            @error="($event.target as HTMLImageElement).style.display = 'none'"
          />
          <span class="account-name">{{ user.name || user.email }}</span>
          <button class="account-signout" type="button" title="Sign out" @click="emit('signOut')">
            <LogOut :size="14" aria-hidden="true" />
            <span class="sr-only">Sign out</span>
          </button>
        </div>
      </div>
    </header>

    <main class="studio-main">
      <ChatRail :entries="chatEntries" :collapsed="chatCollapsed" @toggle="chatCollapsed = !chatCollapsed" />

      <section id="workflow-canvas" class="graph-workspace" aria-labelledby="graph-title" tabindex="-1">
        <div class="canvas-heading">
          <div>
            <!--
              Sourced, not hardcoded. The two literals were written when this
              console could only ever draw one graph; since the builder can hand
              it a published one, `Minimal gated agent` was rendering under
              `FIXED VALIDATOR GRAPH / Evidence pipeline` - a heading that
              describes a different workflow than the nodes below it. The
              validator's own wording is preserved exactly when no handoff is in
              effect, which is still the common case.
            -->
            <span class="canvas-kicker">{{ canvasKicker }}</span>
            <h2 id="graph-title">{{ canvasTitle }}</h2>
          </div>
          <div class="canvas-meta">
            <span><Activity :size="13" aria-hidden="true" />{{ status }}</span>
            <code>{{ descriptor.version }}</code>
          </div>
        </div>

        <CrewProgress
          :node-states="nodeStates"
          :node-visits="nodeVisits"
          :descriptor="descriptor"
          :active="isActive"
        />

        <VueFlow
          id="studio-flow"
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
          :aria-label="`${canvasTitle} workflow graph`"
        >
          <template #node-workflow="nodeProps">
            <WorkflowNode v-bind="nodeProps" />
          </template>
          <template #edge-workflow="edgeProps">
            <WorkflowEdge v-bind="edgeProps" />
          </template>
          <Background :gap="20" :size="1" color="#777777" pattern-color="#777777" />
          <!--
            Stock markup, named after the fact - and the DOM pass is the point
            rather than a shortcut. `<Controls>` renders three `<button>`s
            around bare `<svg>`s with no title and no text, which a screen
            reader announces as "button, button, button"; they were the only
            unnamed interactive elements on this page. Replacing them through
            the `control-*` slots is the declarative fix and is what
            `BuilderCanvas` does - but this canvas is under WP-A's committed
            screenshot baseline, and swapping Vue Flow's icons for Lucide ones
            moves pixels inside `.validator-flow`. An `aria-label` moves none.
            The gate exists to prove the card extraction changed nothing; it
            must not be spent on an accessibility label.
          -->
          <Controls position="bottom-left" :show-interactive="false" />
        </VueFlow>

        <ReportPanel
          :report="report"
          :verdict="verdictSummary"
          :open="reportOpen"
          @close="reportOpen = false"
        />

        <button
          v-if="report && !reportOpen"
          class="report-reopen"
          type="button"
          @click="reportOpen = true"
        >
          <FileText :size="14" aria-hidden="true" />
          View validation report
        </button>
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
          <!--
            Stated where the Launch button is, because that is the button whose
            meaning it changes. Not dismissible without acting: "dismiss" here
            would leave the console pointed at a graph with nothing on screen
            saying so, and the whole reason this strip exists is that a silent
            repoint is indistinguishable from the mock-mode failure.
          -->
          <div v-if="handoff" class="handoff-banner" role="status">
            <span>
              Running your published graph <strong>{{ handoff.name }}</strong>. It asks for
              <code>{{ handoff.inputField }}</code>.
            </span>
            <button
              class="icon-button"
              type="button"
              aria-label="Go back to the built-in validator"
              :title="isActive ? 'Finish or cancel this run first' : 'Back to the validator'"
              :disabled="isActive"
              @click="backToValidator"
            >
              <X :size="15" aria-hidden="true" />
            </button>
          </div>

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
            v-model:gates-mode="gatesMode"
            :error="lastError"
            :transport-problem="transportProblem"
            :graph-problem="graphProblem"
            :download-status="downloadStatus"
            :download-message="downloadMessage"
            :workflow-name="handoff ? handoff.name : undefined"
            :input-label="handoff ? `${handoff.inputField.replaceAll('_', ' ').toUpperCase()} TO RUN` : undefined"
            @launch="launch"
            @cancel="cancel"
            @download="downloadLogs"
            @dismiss-error="dismissError"
            @select-view="activeView = $event"
          />
          <RunHistory
            :reload-key="historyReloadKey"
            :enabled="authenticated"
          />
        </div>
      </aside>
    </main>
  </div>
</template>

<style scoped>
/* Narrower than the two segmented pairs in the control rail, which are full
   width in a 310px column. This one sits between the brand lockup and the
   workflow name in a 52px header, so it is sized to its content. */
.workspace-switch {
  grid-template-columns: auto auto;
  padding: 2px;
}

.workspace-switch button {
  min-height: 28px;
  padding: 0 10px;
  font-size: var(--fs-12);
}

.handoff-banner {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  color: var(--accent-cyan);
  font-size: var(--fs-12);
  line-height: 1.5;
  background: color-mix(in srgb, var(--accent-cyan) 10%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--accent-cyan) 30%, transparent);
}

.handoff-banner strong { color: var(--text-title); }
.handoff-banner code { padding: 1px 5px; color: var(--accent-mint); font: 500 var(--fs-11)/1.5 var(--font-mono); background: var(--surface-well); border-radius: var(--r-xs); }
.handoff-banner .icon-button { flex: 0 0 auto; }
/* Disabled only while a run is in flight, because leaving would reload the
   page out from under it. The title says so rather than leaving a dead
   control. */
.handoff-banner .icon-button:disabled { cursor: not-allowed; opacity: 0.42; }

@media (max-width: 860px) {
  /* First thing to go when the header runs out of room; `#/build` is still a
     URL and the builder is still reachable. */
  .workspace-switch { display: none; }
}
</style>
