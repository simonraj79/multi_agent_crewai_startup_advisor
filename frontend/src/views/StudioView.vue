<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch, watchEffect } from 'vue'
import { Background } from '@vue-flow/background'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Activity, ChevronLeft, ChevronRight, FileText, GitBranch, LogOut, PenTool, Play, Radio, X } from 'lucide-vue-next'
import BrandLockup from '../components/BrandLockup.vue'
import CanvasControls from '../components/CanvasControls.vue'
import ChatRail from '../components/ChatRail.vue'
import CrewProgress from '../components/CrewProgress.vue'
import DialogueRail from '../components/DialogueRail.vue'
import GateCard from '../components/GateCard.vue'
import ReportPanel from '../components/ReportPanel.vue'
import RunHistory, { takeRevealHistory } from '../components/RunHistory.vue'
import StatusPanel from '../components/StatusPanel.vue'
import WorkflowEdge from '../components/WorkflowEdge.vue'
import WorkflowNode from '../components/WorkflowNode.vue'
import { useCanvasTool } from '../composables/useCanvasTool'
import { useValidatorRun, workflowIdentity } from '../composables/useValidatorRun'
import { characterIndex } from '../composables/useRunChoreography'
import { pageTitle } from '../data/brand'
import { clearRunHandoff, readRunHandoff } from '../data/builderRunHandoff'
import { connectionLabel as transportWord, runStatusDisplay } from '../data/runStatusDisplay'
import type { SignedInUser } from '../composables/useAuthGate'
import type { RunStatus } from '../types/studio'
import type { DocumentId } from '../types/builder'

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
  /** The breadcrumb's first crumb: back to the list of every workflow. */
  home: []
  /**
   * Draw this workflow: the mode switch's other half.
   *
   * It CARRIES THE DOCUMENT now (item 57, ROUND-2 R3). It used to be a bare
   * `build: []` and `App.vue` answered it with `documentId: null`, so pressing
   * Build while running a graph somebody drew landed on the gallery rather
   * than on that graph - the switch is the mode pair of one workflow, and one
   * of its two halves forgot which workflow. `null` is still the honest answer
   * for the built-in validator, which has no builder document behind it.
   */
  build: [documentId: DocumentId | null]
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
 * Select / Hand, `H` / `V`, and the space bar - the same composable the builder
 * canvas uses, on the same terms (`DEFINITION-OF-DONE.md` U3).
 *
 * It replaces a DOM hack that lived here: three `aria-label`s written onto the
 * library's own buttons in `onMounted`, because `<Controls>` renders three
 * `<button>`s around bare `<svg>`s with no title and no text and there is no
 * prop for a name. `CanvasControls` fills the `control-*` slots instead, which
 * is the declarative fix that hack's own comment said it wanted; D4 is what
 * makes it affordable, by regenerating the screenshot baselines once on the
 * integrated branch rather than treating them as a reason not to name a button.
 *
 * `console` rests on Hand, which is what this canvas has always done - it never
 * passed `pan-on-drag`, so it inherited the library's `true` and a left-drag
 * panned. Nothing about the first frame of a run changes.
 */
const { tool, setTool, panOnDrag, canvasClass } = useCanvasTool('console')

/** The instance `<VueFlow id>` registers, so Fit and zoom reach this canvas. */
const flow = useVueFlow('studio-flow')

/**
 * The console's fit, stated once.
 *
 * Bound to `<VueFlow :fit-view-options>` AND handed to the Fit button, because
 * a button that framed the graph differently from the automatic fit is a button
 * that undoes what the page did on arrival. It was an inline literal on the
 * prop alone until the Fit button needed the same numbers.
 */
const FIT_VIEW_OPTIONS = { padding: 0.12, maxZoom: 0.9 }


const {
  descriptor,
  // The workflow this console is pointed at, and the `inputs` key its launch
  // must carry. Both are the composable's own state - seeded from the handoff
  // or from the stored run context - and both feed `workflowIdentity` above.
  workflowId,
  inputField,
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
  dialogue,
  stages,
  framesApplied,
  armed,
  endHandoff,
  identities,
  identityFor,
  castStates,
  castState,
  // The cast, for one card. Cached by the store, so an unchanged card is handed
  // the SAME object and Vue skips it - a literal built here would re-render all
  // fourteen on every frame (T2.8).
  castFor,
  initialize,
  launch,
  // The run pointer survives a run ending now (item 58, R4), so leaving this
  // workflow has to put it down deliberately - see `backToValidator`.
  forgetRun,
  submitGate,
  cancel,
  resumeFrom,
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
 * WHO THIS CONSOLE IS ABOUT — one computed, off the run's own descriptor
 * (item 55, ROUND-2 R1).
 *
 * There were three computeds here and all three keyed on `handoff`, which only
 * the publish dialog's "Run it" writes. The kicker, the canvas heading, the
 * breadcrumb, the tab title, the WORKFLOW well, the input label and the
 * report's kicker therefore all reverted to the validator's wording for a
 * builder run reached by the test panel, by the Run switch or by a restored
 * pointer — RV2 measured exactly that on 2026-09-06, and this pass reproduced
 * it before changing anything (`evidence/R1/before-*.png`).
 *
 * `workflowIdentity` is pure and lives beside the composable that owns the
 * descriptor; its docstring carries the measured JSON both rules rest on. The
 * handoff's `name` is passed as the PROVISIONAL name and nothing else, which is
 * the one thing it is genuinely for: it is right before the graph read
 * resolves, and it is never allowed to override what the server served.
 *
 * BELOW the destructure, like the `watchEffect` under it and for the same
 * reason — `descriptor`, `workflowId` and `inputField` are bound there.
 */
const identity = computed(() =>
  workflowIdentity(descriptor.value, workflowId.value, inputField.value, handoff.value?.name ?? ''),
)
const workflowName = computed(() => identity.value.name)
/**
 * Which document the Build half of the switch opens.
 *
 * The workflow id and the document id are ONE string for a builder graph:
 * `builder/descriptor.py::builder_workflow_id` returns `document.id`, and the
 * descriptor served for a published graph carries it as its own `id` (measured
 * 2026-09-06: `GET /api/workflows/ug_a96d869d/graph` -> `"id": "ug_a96d869d"`).
 * So nothing has to be looked up, and nothing has to be carried in the handoff.
 */
const buildTarget = computed<DocumentId | null>(() =>
  identity.value.authored ? (workflowId.value as DocumentId) : null,
)
const canvasKicker = computed(() => identity.value.kicker)
const canvasTitle = computed(() => identity.value.title)

/**
 * The tab's name follows the route (U4). One workflow per tab, so the workflow
 * is what names it; `pageTitle` owns the separator and the product half, and
 * `PRODUCT_NAME` is spelled in `data/brand.ts` and nowhere else.
 *
 * BELOW the destructure, because a `watchEffect` runs its body immediately:
 * reading `descriptor` from above the `const` that binds it is a temporal
 * dead zone, which is a blank page at runtime rather than a type error. The
 * computeds above are lazy and so may sit here.
 */
watchEffect(() => {
  // `|| null` rather than the empty string: `pageTitle` reads a blank name as
  // "no workflow" and gives the product name alone, which is the right tab for
  // the one frame before a restored builder run has its descriptor.
  document.title = pageTitle(workflowName.value || null)
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
const connectionLabel = computed(() =>
  transportWord(transportMode.value, connection.value, isActive.value),
)

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

/**
 * The reconnecting strip. Plan 12 D7.
 *
 * The header badge already turns amber, and it is 12px of text in a corner
 * nobody is looking at while a run is in flight - so a socket that dropped read
 * as a run that had gone quiet. This says the two things somebody in that
 * moment actually needs: that the connection is being re-made, and that
 * nothing already on screen has been lost.
 *
 * N is the frame count APPLIED, which is the honest number. `lastSequence` is
 * the highest sequence the server issued and would over-report on a run that
 * dropped frames; the count of frames this console has actually put on the page
 * is what "kept" means.
 */
const reconnecting = computed(() => connection.value === 'reconnecting')
const reconnectingLabel = computed(
  () => `reconnecting — ${framesApplied.value} steps kept`,
)

/**
 * The dialogue rail opens itself the first time an agent says anything, the way
 * `ReportPanel` opens itself for the first body. Keyed on the run id so a
 * relaunch re-arms it, and only ONCE per run - an operator who collapsed it has
 * said what they want, and a rail that reopened on every utterance would be
 * fighting them for the rest of the run.
 */
const dialogueCollapsed = ref(true)
let dialogueOpenedFor = ''
watch(
  () => [runId.value, dialogue.value.length] as const,
  ([id, count]) => {
    if (!count || dialogueOpenedFor === id) return
    dialogueOpenedFor = id
    dialogueCollapsed.value = false
  },
)

const chatCollapsed = ref(window.matchMedia('(max-width: 860px)').matches)
const controlsCollapsed = ref(false)

/**
 * The scrim behind an open rail, and the one gesture it carries.
 *
 * Below 640px both rails are OVERLAYS - they cover the console rather than
 * shrinking it - and a cold reader at 390px found the consequence: the rail sat
 * on the console with nothing between them, so a sliver of half-cut console
 * text showed down the edge and nothing on screen said which layer was live.
 * A scrim is the answer to that question, and dismissing it is the gesture
 * every overlay on a phone has.
 *
 * Rendered whenever a rail is open at ANY width and hidden above 640px by CSS,
 * so the breakpoint stays a fact about the stylesheet and this file never
 * learns that a phone exists. Closing BOTH is deliberate: a scrim means "put
 * the layer over the content away", and at this width opening one rail does not
 * close the other, so a scrim that closed only one would leave the reader
 * looking at the same defect with one fewer control.
 */
const aRailIsOpen = computed(() => !chatCollapsed.value || !controlsCollapsed.value)
function closeRails(): void {
  chatCollapsed.value = true
  controlsCollapsed.value = true
}
const activeView = ref<'graph' | 'activity'>('graph')

watch(activeView, (view) => {
  if (view === 'activity') chatCollapsed.value = false
})

/**
 * The home's `Run history` link, arriving (item 3, ROUND-2 ruling 3).
 *
 * The list is always rendered - it is the last block of the control rail - so
 * "reveal" is two facts and not a new panel: the rail must be OPEN, and the
 * list must be where the reader is looking. Below 640px the rail is an overlay
 * and starts collapsed, which is exactly the width at which a person who
 * pressed `Run history` would otherwise land on a console with no list on it.
 *
 * ONE SHOT. `takeRevealHistory` removes the note as it reads it, so a reload of
 * `#/run` does not scroll the reader away from a run they are watching. The
 * scroll is guarded on the method existing, because jsdom implements no layout
 * and does not define it.
 */
onMounted(async () => {
  if (!takeRevealHistory()) return
  controlsCollapsed.value = false
  await nextTick()
  const heading = document.getElementById('run-history')
  if (heading && typeof heading.scrollIntoView === 'function') {
    heading.scrollIntoView({ block: 'nearest' })
  }
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
/**
 * The handoff banner is about LAUNCHING, so it goes when there is nothing left
 * to launch.
 *
 * A cold reader found it stacked above "Run failed" in the right rail
 * (`evidence/S/failure.png`): two banners, two dismiss buttons, and the upper
 * one saying "Running your published graph …" about a run that had already
 * stopped. Present tense about a finished thing.
 *
 * Driven by the run's own status rather than by a timer, so it is exact: the
 * banner is up while a launch is a live prospect and down the moment the run
 * reaches an end state, whichever end that is. `handoff` itself is NOT
 * cleared - the console is still pointed at that graph, Relaunch still runs
 * it, and the WORKFLOW well still names it. Only the sentence goes.
 */
const TERMINAL_RUN_STATUSES: readonly RunStatus[] = ['completed', 'error', 'cancelled']
const handoffBannerShown = computed(
  () => handoff.value !== null && !TERMINAL_RUN_STATUSES.includes(status.value),
)

function backToValidator(): void {
  clearRunHandoff(props.user?.id ?? null)
  // AND THE RUN POINTER, which is new and is not tidiness (item 58, R4). This
  // function reloads the page, and a pointer that now survives a finished run
  // would have `initialize` restore that run and repoint the console straight
  // back at the workflow the operator just asked to leave - the control would
  // look broken, and the cause would be two files away.
  forgetRun()
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
      <!--
        The lockup is a LINK to the workflow list (row U2), and the `<h1>`
        inside it is the view's own heading, handed to the default slot. The
        `<template #default>` wrapper looks redundant and is not: it keeps the
        heading's line at the indentation it has always had, so the worker who
        owns that line's TEXT and the worker who owned this block could change
        their own halves without landing on each other.
      -->
      <!--
        THE HEADING IS THE WORKFLOW (U4), AND IT IS `sr-only` (U2's ruling,
        2026-09-06). This slot held the product's OLD name, standing where the
        page's own heading belongs; `BrandLockup` carries `PRODUCT_NAME` in the
        kicker beside it, so a product name here would have named the product
        twice and the thing on screen never.

        The workflow's name then appeared TWICE - here and as the breadcrumb's
        current crumb, which U2 fixes as `Workflows / <workflow name>`. The
        crumb is the visible one, because it is the one that also says where
        the name sits; the heading stays in the DOM because a page about one
        workflow should have that workflow as its `<h1>`, and taking it out
        would leave this document with no heading at all for anyone reading it
        by structure.

        The old product name is not quoted anywhere in this file on purpose -
        `tests/brand.spec.ts` greps `src/` for it line by line, comments
        included, which is the only form of that check nobody can talk their
        way past.
      -->
      <BrandLockup as="link">
        <template #default>
          <h1 class="sr-only">{{ workflowName }}</h1>
        </template>
      </BrandLockup>

      <div class="header-context">
        <!--
          WHERE YOU ARE, IN TWO CRUMBS (U2). It replaces the bare
          `.workflow-name` span that sat where the second crumb now does: the
          name was already here, and what was missing was the fact that it is
          one of a list and the way back to that list. `Workflows` is a real
          `<a href="#/">`, not a button, so the browser's own affordances - a
          status-bar target, middle-click, copy link - all work; the click is
          intercepted so the SPA routes rather than reloading.
        -->
        <nav class="breadcrumb" aria-label="Breadcrumb">
          <a class="breadcrumb-crumb" href="#/" @click.prevent="emit('home')">Workflows</a>
          <span class="breadcrumb-sep" aria-hidden="true">/</span>
          <span class="breadcrumb-crumb is-current" aria-current="page">
            <GitBranch :size="13" aria-hidden="true" />
            <span class="breadcrumb-name">{{ workflowName }}</span>
          </span>
        </nav>

        <!--
          The mode switch for the workflow the breadcrumb names: Build draws it,
          Run runs it. Both canvases carry the same pair now, so it is the one
          control that means the same thing in both places.

          THE COMMENT HERE USED TO CITE CUT LIST ITEM 1 - "the builder offers no
          mirror image of this pair" - and that ruling was already overturned by
          `.agent/plans/00-architecture.md` D2 before this file was written;
          `BuilderView.vue` has carried the same segmented pair since. It is
          recorded rather than deleted because a stale citation is worse than
          none: the next reader would have taken the cut list at its word.
        -->
        <div class="segmented workspace-switch" role="group" aria-label="Workspace">
          <!--
            Build goes to THIS workflow's canvas when there is one (item 57).
            `identity.authored` is the descriptor's own answer to "somebody drew
            this", and a builder graph registers under its DOCUMENT id, so the
            workflow id IS the `#/build/<id>` this lands on. The built-in
            validator has no document, so it keeps the gallery.
          -->
          <!--
            `aria-label` ALWAYS, not only when the word is hidden. Below 860px
            this pair collapses to this half alone and the word goes with it
            (R10, below), so the accessible name has to come from somewhere the
            media query cannot reach - and a label that appears at one width and
            not another is a control that is announced differently on a phone.
            It says the same thing the visible word does, so nothing changes
            above the breakpoint.
          -->
          <button
            type="button"
            :aria-pressed="false"
            aria-label="Build"
            title="Open this workflow in Build"
            data-testid="build-switch"
            @click="emit('build', buildTarget)"
          >
            <PenTool :size="14" aria-hidden="true" />
            <span class="switch-word">Build</span>
          </button>
          <button type="button" :aria-pressed="true">
            <Play :size="14" aria-hidden="true" />
            <span class="switch-word">Run</span>
          </button>
        </div>

        <!--
          The word is in a span so the 390 block below can take it out of the
          LAYOUT without taking it out of the page: `.sr-only` there, not
          `display: none`, because this element is `aria-live` and a live region
          that renders nothing announces nothing. `title` puts it back within
          reach of a pointer, and the dot keeps its colour either way.
        -->
        <span
          class="live-status"
          :class="`is-${connection}`"
          aria-live="polite"
          :title="connectionLabel"
        >
          <Radio :size="13" aria-hidden="true" />
          <span class="live-word">{{ connectionLabel }}</span>
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
      <!--
        The scrim. `studio.css` hides it above 640px, where the rails are docked
        columns and there is nothing to dismiss; below it, a rail covers the
        console and this is both the answer to "which layer is live" and the way
        back out.

        A `<button>` because it is a control and should carry a control's
        semantics, but OUT of the tab order and hidden from the accessibility
        tree - and that pair is deliberate rather than lazy. Both rails already
        have real toggle buttons that are focusable, labelled, and do exactly
        this; a third control here would be a duplicate announced twice and
        tabbed through once, buying nobody a capability they did not have. It is
        a pointer affordance for a gesture the keyboard already has.
      -->
      <button
        v-if="aRailIsOpen"
        class="rail-scrim"
        type="button"
        tabindex="-1"
        aria-hidden="true"
        @click="closeRails"
      />
      <!--
        `identityFor` and `castState` are handed to all three surfaces from ONE
        store (`useRunChoreography`, by way of the run composable), which is the
        whole of DoD T2.6: the node card, the trace row and the spoken line can
        disagree about an agent only if they ask three different questions, and
        here they ask one. `characterIndex` stays beside them because it is what
        still colours the lucide medallion on the node kinds that get no
        character - a router, a gate, an output, a step.
      -->
      <ChatRail
        :entries="chatEntries"
        :collapsed="chatCollapsed"
        :character-of="characterIndex"
        :identity-of="identityFor"
        :state-of="castState"
        @toggle="chatCollapsed = !chatCollapsed"
      >
        <template #above>
          <DialogueRail
            :entries="dialogue"
            :collapsed="dialogueCollapsed"
            :status="status"
            :character-of="characterIndex"
            :identity-of="identityFor"
            :state-of="castState"
            @toggle="dialogueCollapsed = !dialogueCollapsed"
          />
        </template>
      </ChatRail>

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
            <!--
              THE GRAPH VERSION IS IN A `title` NOW, not on the line (AUDIT-R2
              N6, item 9's ruling extended). It rendered as a bare
              `9c6ca8a6fefbfffd` beside the run's status, on the surface a
              first-time visitor reads first, and it is a sixteen-character
              ETag body with no reader on this screen. It is still READABLE in
              two places: hovering the workflow's name, and the rail's own
              `Details` disclosure, which is where the rest of the
              instrumentation went. `title` on the heading rather than on the
              whole heading block, because the version is a fact about THIS
              workflow and the name is the thing it is about.
            -->
            <h2 id="graph-title" :title="`Version ${descriptor.version}`">{{ canvasTitle }}</h2>
          </div>
          <div class="canvas-meta">
            <!--
              The same word the status rail uses. The heading said "Completed"
              beside a rail saying "Finished" - one state, two words, eighteen
              inches apart - which is the defect `runStatusDisplay` was written
              for and this surface had never been routed through it.
            -->
            <span><Activity :size="13" aria-hidden="true" />{{ runStatusDisplay(status).label }}</span>
          </div>
        </div>

        <!--
          Said where the run is, not in the corner. The header badge is 12px in
          a place nobody looks at while a graph is moving, so a dropped socket
          read as a run that had gone quiet.
        -->
        <p
          v-if="reconnecting"
          class="stream-reconnecting"
          data-testid="stream-reconnecting"
          role="status"
          aria-live="polite"
        >{{ reconnectingLabel }}</p>

        <CrewProgress
          :node-states="nodeStates"
          :node-visits="nodeVisits"
          :descriptor="descriptor"
          :active="isActive"
          :run-stages="stages"
          :identities="identities"
          :cast-states="castStates"
        />

        <!--
          `canvasClass` is `is-hand-tool` / `is-select-tool`, and it is on the
          flow root rather than on a wrapper because `.vue-flow__pane` is a
          descendant of it and the cursor rules in `studio.css` are the only
          thing that reads it. `pan-on-drag` was ABSENT here until U3 - the
          library's default is `true`, which is Hand, which is what the console
          has always done; the composable's resting value for this surface is
          that same `true`, so the first frame is unchanged.
        -->
        <VueFlow
          id="studio-flow"
          class="validator-flow"
          :class="canvasClass"
          :nodes="graphNodes"
          :edges="graphEdges"
          :min-zoom="0.28"
          :max-zoom="1.45"
          :default-viewport="{ x: 0, y: 0, zoom: 0.72 }"
          :nodes-draggable="false"
          :nodes-connectable="false"
          :elements-selectable="false"
          :zoom-on-double-click="false"
          :pan-on-drag="panOnDrag"
          :fit-view-on-init="true"
          :fit-view-options="FIT_VIEW_OPTIONS"
          :aria-label="`${canvasTitle} workflow canvas`"
        >
          <template #node-workflow="nodeProps">
            <!--
              `cast` is a declared prop rather than another field on `data`,
              because `data` is rebuilt by `graphNodes` on every frame and the
              cast is answered by a different store. Declared, so it does NOT
              fall through onto the `<article>` the way `id` deliberately does.
            -->
            <WorkflowNode v-bind="nodeProps" :cast="castFor(nodeProps.id)" @rerun="resumeFrom" />
          </template>
          <template #edge-workflow="edgeProps">
            <WorkflowEdge v-bind="edgeProps" @handoff-done="endHandoff" />
          </template>
          <Background :gap="20" :size="1" color="#777777" pattern-color="#777777" />
          <!--
            The declarative fix the stock markup here was waiting for, and the
            same component the builder canvas renders (U3).

            The comment this replaces named the reason the buttons were left
            stock and labelled in `onMounted` instead: this canvas is under a
            committed screenshot baseline, and swapping Vue Flow's icons for
            Lucide ones moves pixels inside `.validator-flow` where an
            `aria-label` moves none. **D4 lifts that reason for this build** -
            `run-canvas.spec.ts`'s three PNGs and `builder-canvas.spec.ts`'s
            sixteen are regenerated once, on the integrated branch, by RV1,
            because the header, the brand and this cluster all move inside the
            same frames. The gate is being spent deliberately, by the document
            that owns it, rather than raided.
          -->
          <CanvasControls
            flow-id="studio-flow"
            :tool="tool"
            :fit="() => flow.fitView(FIT_VIEW_OPTIONS)"
            @update:tool="setTool"
          />
        </VueFlow>

        <!--
          The report's kicker read `VALIDATION REPORT` over every run, including
          one from a graph that validates nothing (item 55's fourth surface).
          It takes the workflow's own name now; the built-in keeps its wording
          because `ReportPanel`'s default is the one it always had.
        -->
        <ReportPanel
          :report="report"
          :verdict="verdictSummary"
          :open="reportOpen"
          :workflow-name="identity.authored ? workflowName : undefined"
          @close="reportOpen = false"
        />

        <button
          v-if="report && !reportOpen"
          class="report-reopen"
          type="button"
          @click="reportOpen = true"
        >
          <FileText :size="14" aria-hidden="true" />
          {{ identity.authored ? 'View run report' : 'View validation report' }}
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
          <!-- `&& handoff` is for the type narrowing, not for the logic:
               `handoffBannerShown` already implies it, but a computed does not
               narrow a ref inside the template the way a direct `v-if` does. -->
          <div v-if="handoffBannerShown && handoff" class="handoff-banner" role="status">
            <span>
              Running your published workflow <strong>{{ handoff.name }}</strong>. It asks for
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
          <!--
            `can-return-home` is the way back, and it lives in the panel because
            the banner that used to carry it retires at a terminal status. The
            condition is the same one the banner used: a published graph is
            loaded.
          -->
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
            :armed="armed"
            :is-active="isActive"
            :primary-label="primaryLabel"
            :active-view="activeView"
            v-model:gates-mode="gatesMode"
            :error="lastError"
            :transport-problem="transportProblem"
            :graph-problem="graphProblem"
            :download-status="downloadStatus"
            :download-message="downloadMessage"
            :workflow-name="workflowName || undefined"
            :input-label="identity.inputLabel"
            :graph-version="descriptor.version"
            :can-return-home="identity.authored"
            @launch="launch"
            @cancel="cancel"
            @download="downloadLogs"
            @dismiss-error="dismissError"
            @return-home="backToValidator"
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
  padding: 0 var(--space-4);
  font-size: var(--fs-12);
}

/* The same shape as `studio.css`'s `.panel-banner`, in a third colour family:
   this one is neither a warning nor a fault, it is a fact about which graph
   the Launch button is pointed at. It keeps its own rule rather than taking a
   fourth modifier onto the shared class, because the shared class has exactly
   two families and both are semantic states. */
.handoff-banner {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  color: var(--on-accent-cyan);
  font: var(--type-label);
  line-height: 1.5;
  background: color-mix(in srgb, var(--accent-cyan) 10%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--accent-cyan) 30%, transparent);
}

.handoff-banner strong { color: var(--text-title); }
.handoff-banner code { padding: 1px var(--space-2); color: var(--on-accent-mint); font: var(--type-meta); background: var(--surface-well); border-radius: var(--r-xs); }
.handoff-banner .icon-button { flex: 0 0 auto; }
/* Disabled only while a run is in flight, because leaving would reload the
   page out from under it. The title says so rather than leaving a dead
   control. */
.handoff-banner .icon-button:disabled { cursor: not-allowed; opacity: 0.42; }

/*
 * R10, THE CONSOLE'S HALF (ROUND-2 row R10, AUDIT-R2 C1).
 *
 * This block used to read `.workspace-switch { display: none }`, with the
 * comment "first thing to go when the header runs out of room; `#/build` is
 * still a URL and the builder is still reachable." Measured at 390x844: a
 * console had NO route to Build at all - `#/build` is a URL only to somebody
 * who knows to type one, and the audit's C1 counted that as one of the two
 * halves of a mode switch that does not exist on a phone.
 *
 * THE PAIR COLLAPSES TO ITS ONE USEFUL HALF rather than growing a menu. `Run`
 * is the mode you are already in - a segmented control whose second half is
 * the current page is redundant at any width and unaffordable at this one -
 * and `Build` is the route that was missing. Icon-only, because the header had
 * SEVEN pixels of slack: measured on this tree before the change at 390, the
 * brand runs 16-58, the breadcrumb 58-261, the transport chip 275-329 and the
 * account chip 343-383 of 390. A worded button is ~78px and would have taken
 * that out of the workflow's own name, which U2 spent a ruling keeping.
 *
 * The word is `display: none` rather than `visibility: hidden` - the opposite
 * of the choice `BuilderView`'s Run half makes two files over, and for the
 * opposite reason: there the two labels must reserve the wider one's width so
 * the control cannot move under a pointer, and here the whole point is to give
 * the width back. The accessible name is on `aria-label` above, so it survives
 * either way.
 */
/*
 * WHERE THE 36px COMES FROM, measured rather than hoped.
 *
 * At 390 before this change the header ran brand 16-58, breadcrumb 58-261,
 * transport chip 275-329, account chip 343-383 of 390 - seven pixels of slack.
 * Putting the switch back at its icon width alone pushed `.header-context` to
 * 433 and the account chip clean off the right edge, measured. So two things
 * give the width back at 390 and only at 390, and neither is the workflow's
 * own name, which U2 spent a ruling keeping:
 *
 *   the gap    14px -> 8px across four items, 18px
 *   the word   the transport chip keeps its dot and gives up its word to
 *              `.sr-only` - roughly 34px, and it is the one thing in this
 *              header that says nothing about which workflow you are looking at
 *
 * Measured after: the account chip's right edge is back inside the viewport.
 * These rules are SCOPED to this component, so the builder's header - which has
 * its own switch, its own rule and no transport chip - is untouched.
 */
@media (max-width: 640px) {
  .header-context { gap: var(--space-3); }
  .live-status .live-word {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
}

@media (max-width: 860px) {
  .workspace-switch { grid-template-columns: auto; }
  /* The current mode. `aria-pressed` is the state, so the selector is the fact
     rather than a position that a later edit could reorder. */
  .workspace-switch button[aria-pressed='true'] { display: none; }
  .workspace-switch button { padding: 0 var(--space-3); }
  .workspace-switch .switch-word { display: none; }
}
</style>
