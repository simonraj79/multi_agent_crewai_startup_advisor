<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Activity,
  Download,
  FastForward,
  GitBranch,
  Play,
  UserCheck,
  RotateCcw,
  Square,
  LoaderCircle,
  TriangleAlert,
  X,
} from 'lucide-vue-next'
import type { ConnectionStatus, GatesMode, LogFormat, TransportMode } from '../services/studioApi'
import type { RunStatus, UsageMetrics } from '../types/studio'
import { IDEA_CHARS_WARN_AT, MAX_IDEA_CHARS, MIN_IDEA_CHARS } from '../data/serverLimits'
import { runStatusDisplay } from '../data/runStatusDisplay'

const props = withDefaults(defineProps<{
  status: RunStatus
  transportMode: TransportMode
  connection: ConnectionStatus
  runId: string
  idea: string
  usage: UsageMetrics
  lastSequence: number
  droppedFrames: number
  canLaunch: boolean
  isActive: boolean
  primaryLabel: string
  /**
   * The run has been asked for and its first frame has not arrived (plan 11
   * D6.1).
   *
   * The gap it covers is real and was previously blank: a POST to Singapore, a
   * queue slot and a socket handshake, during which the button read `Launching…`
   * and nothing else on the page acknowledged the press. The glow is the
   * reference's own `gradientShift` + `glowPulse` pair, because there is one
   * motion vocabulary here and a second glow meaning the same thing is how a
   * design stops reading as one system.
   */
  armed?: boolean
  activeView: 'graph' | 'activity'
  gatesMode: GatesMode
  error: string
  /**
   * Why the console is not talking to a real backend. Rendered ABOVE `error`
   * and not dismissible: while this is set, nothing on screen is a real run,
   * and a banner the operator can wave away is how they end up reading a
   * scripted verdict as their own.
   */
  transportProblem: string
  /**
   * The server's sentence when it refused the graph this console is pointed
   * at (D-01-2). Rendered like `transportProblem` - above `error`, not
   * dismissible - because while it is set the Launch button below is disabled
   * for a reason the operator has to be able to read, and the only other
   * carrier is a banner they can wave away.
   */
  graphProblem?: string
  downloadStatus: 'idle' | 'pending' | 'success' | 'error'
  downloadMessage: string
  /**
   * The graph this console is pointed at, and what its request input is called.
   *
   * Both defaulted to the built-in validator's, so every existing caller is
   * unchanged - and both are props rather than literals because the console now
   * also runs a PUBLISHED BUILDER GRAPH. The well used to read "Idea Validator"
   * unconditionally, which on a graph an author drew and named themselves is
   * not a small cosmetic slip: it is the panel that says which workflow the
   * Launch button is about to spend money on.
   */
  workflowName?: string
  inputLabel?: string
}>(), {
  workflowName: 'Idea Validator',
  inputLabel: 'IDEA TO VALIDATE',
  graphProblem: '',
})

const emit = defineEmits<{
  'update:idea': [value: string]
  launch: []
  cancel: []
  download: [format: LogFormat]
  dismissError: []
  selectView: [value: 'graph' | 'activity']
  'update:gatesMode': [value: GatesMode]
}>()

/**
 * What the character counter says.
 *
 * Three states, in the order the operator meets them: too short to launch,
 * comfortably inside the bound, and close enough to the ceiling that the
 * `maxlength` attribute is about to start silently discarding keystrokes -
 * which is the one thing a hard cap does that needs warning about.
 */
const ideaLength = computed(() => props.idea.length)
const ideaRemaining = computed(() => MAX_IDEA_CHARS - ideaLength.value)
const ideaNearLimit = computed(() => ideaRemaining.value <= IDEA_CHARS_WARN_AT)
const ideaHint = computed(() => {
  const trimmed = props.idea.trim().length
  if (trimmed > 0 && trimmed < MIN_IDEA_CHARS) {
    return `${MIN_IDEA_CHARS - trimmed} more characters to launch`
  }
  if (ideaNearLimit.value) {
    return ideaRemaining.value === 0
      ? `${MAX_IDEA_CHARS} character limit reached`
      : `${ideaRemaining.value} characters left of ${MAX_IDEA_CHARS}`
  }
  return `${ideaLength.value} / ${MAX_IDEA_CHARS} characters`
})

/**
 * The run's state, in the one vocabulary every surface shares.
 *
 * `data/runStatusDisplay.ts` is the table, and the reason it exists is that
 * this panel used to render `status.replace('_', ' ')` over a CSS `capitalize`
 * while `RunHistory` one panel over rendered the un-normalised backend
 * spelling - so a run this rail called `error` was called `failed` in the list
 * beneath it. The tone is a semantic role, never a colour; the class below
 * binds it to a token.
 */
const statusWords = computed(() => runStatusDisplay(props.status))

/**
 * What the primary button SAYS it will do.
 *
 * `primaryLabel` is `useValidatorRun`'s and answers `Send` while a run is
 * running or waiting - on a button `canLaunch` has already disabled, so it
 * names an action nobody can take and that nothing on this panel would do if
 * they could. Mid-run the honest word is the run's own state; `Launch`,
 * `Relaunch` and `Launching…` pass straight through, because those three are
 * the cases where the button really is the verb.
 *
 * Derived here rather than in the composable because the composable is another
 * worker's file this week; the vocabulary is the shared table either way.
 */
const MID_RUN_VERBS: Readonly<Record<string, string>> = {
  queued: 'Queued…',
  running: 'Running…',
  waiting: 'Waiting for you',
  stopping: 'Stopping…',
}
const primaryWord = computed(() => MID_RUN_VERBS[props.status] ?? props.primaryLabel)

const connectionLabel = computed(() => props.transportMode === 'mock' ? 'Mock stream' : props.connection)
const elapsed = computed(() => {
  const totalSeconds = Math.floor(props.usage.elapsedMs / 1000)
  return `${String(Math.floor(totalSeconds / 60)).padStart(2, '0')}:${String(totalSeconds % 60).padStart(2, '0')}`
})
const tokens = computed(() => new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(props.usage.totalTokens))

// The service serves the same run log as NDJSON or as a ZIP; a long run is a
// much smaller download as the archive, so the operator picks.
const logFormat = ref<LogFormat>('ndjson')
</script>

<template>
  <section class="status-panel" aria-label="Run controls">
    <!--
      Not dismissible, and deliberately first. While this is set the console is
      playing a scripted demonstration, so every number on screen is fiction -
      including the verdict and the cost. The previous behaviour was a small
      "Mock mode" chip rendered in the SUCCESS colour, which a real operator
      read straight past on 2026-09-01.
    -->
    <div v-if="transportProblem" class="panel-banner is-warn transport-banner" role="alert">
      <TriangleAlert :size="15" aria-hidden="true" />
      <span>
        <strong>Demonstration mode - no agent is running.</strong>
        {{ transportProblem }}
      </span>
    </div>

    <!--
      A real server refused this graph (D-01-2). Until 2026-09-03 the console
      answered that by drawing the demonstration graph under the refused
      workflow's name with a green Launch; now the canvas is empty, Launch is
      disabled, and this says why in the server's own words.
    -->
    <div v-if="graphProblem" class="panel-banner is-error graph-banner" role="alert">
      <TriangleAlert :size="15" aria-hidden="true" />
      <span>
        <strong>This graph cannot be launched from here.</strong>
        The server answered: {{ graphProblem }}
      </span>
    </div>

    <div v-if="error" class="panel-banner is-error error-banner" role="alert">
      <span>{{ error }}</span>
      <button class="icon-button" type="button" aria-label="Dismiss error" title="Dismiss" @click="emit('dismissError')">
        <X :size="15" aria-hidden="true" />
      </button>
    </div>

    <div class="panel-section control-section">
      <label for="idea" class="control-label panel-kicker">{{ inputLabel }}</label>
      <textarea
        id="idea"
        class="panel-well"
        :value="idea"
        rows="4"
        :maxlength="MAX_IDEA_CHARS"
        :disabled="isActive"
        aria-describedby="idea-hint"
        @input="emit('update:idea', ($event.target as HTMLTextAreaElement).value)"
        @keydown.ctrl.enter.prevent="emit('launch')"
      />
      <!--
        The counter now states the bound rather than only the position. It used
        to read "2401 characters" in a calm grey right up to a Launch that
        answered 422, because nothing on the client knew a limit existed.

        It also explains the disabled button below the minimum. An operator who
        has typed six characters and sees a dead Launch has no way to learn why.
      -->
      <span id="idea-hint" class="field-meta" :class="{ 'is-warn': ideaNearLimit }">
        {{ ideaHint }}
      </span>
    </div>

    <div class="panel-section control-section compact-section">
      <span class="control-label panel-kicker">WORKFLOW</span>
      <!--
        The `M2` chip that used to sit here was the PRODUCT's build mark, and
        it is still in the header two inches above. Inside a well labelled
        WORKFLOW, beside a workflow's name, it read as that workflow's version -
        so a published graph called "News to social post" was labelled M2, which
        is a version it does not have and a claim nothing on the page could
        check. A graph an author drew has a real version (`v1`, `v2`), and this
        panel is not passed one; asserting the wrong number is worse than
        asserting none, so the chip goes and the build mark stays where it is
        true.
      -->
      <div class="read-only-well panel-well">
        <GitBranch :size="15" aria-hidden="true" />
        <span class="workflow-title">{{ workflowName }}</span>
      </div>
    </div>

    <div class="panel-section control-section compact-section">
      <span class="control-label panel-kicker">GATES</span>
      <div class="segmented" role="group" aria-label="Who answers the gates">
        <button
          type="button"
          :aria-pressed="gatesMode === 'human'"
          :disabled="isActive"
          @click="emit('update:gatesMode', 'human')"
        >
          <UserCheck :size="14" aria-hidden="true" /> Review
        </button>
        <button
          type="button"
          :aria-pressed="gatesMode === 'auto'"
          :disabled="isActive"
          @click="emit('update:gatesMode', 'auto')"
        >
          <FastForward :size="14" aria-hidden="true" /> Unattended
        </button>
      </div>
      <p class="control-hint">
        <!--
          "at every human gate", not "at the scope and verdict gates". Those two
          are the Idea Validator's gates and nothing else's - this panel also
          drives a graph somebody drew, whose gates are named whatever they
          named them, and there may be one or five. A sentence that lists
          another workflow's checkpoints is wrong on every workflow but one.
        -->
        <template v-if="gatesMode === 'human'">
          Pauses for you at every human gate.
        </template>
        <template v-else>
          Runs the whole pipeline without stopping. Costs more, and the
          deployment must allow it.
        </template>
      </p>
    </div>

    <div class="panel-section control-section compact-section">
      <span class="control-label panel-kicker">VIEW</span>
      <div class="segmented" role="group" aria-label="Workspace view">
        <button type="button" :aria-pressed="activeView === 'graph'" @click="emit('selectView', 'graph')">
          <GitBranch :size="14" aria-hidden="true" /> Graph
        </button>
        <button type="button" :aria-pressed="activeView === 'activity'" @click="emit('selectView', 'activity')">
          <Activity :size="14" aria-hidden="true" /> Activity
        </button>
      </div>
    </div>

    <div class="panel-section control-section metrics-section">
      <div class="status-line">
        <span class="control-label panel-kicker">STATUS</span>
        <!--
          The word and the tone both come from `data/runStatusDisplay.ts`, so
          this rail and the history list beneath it can no longer call one run
          two things. `title` carries the clause that explains the word, which
          is the whole gloss an operator needs and none of the noise a second
          line of copy would be.
        -->
        <!--
          `data-status` carries the RAW status beside the human word, and it is
          not redundant: `e2e/cast.spec.ts` and `e2e/cast-perf.spec.ts` already
          read this attribute and call it the contract, falling back to the
          visible text only because the chip had carried its status as prose
          since before that was written. Now that the prose is a sentence
          ("Waiting for you", "Finished") rather than the enum, the attribute is
          the only thing a test should be reading - and a machine-readable state
          beside a human-readable one is the right shape anyway.
        -->
        <span
          class="status-badge"
          :class="`is-tone-${statusWords.tone}`"
          :data-status="status"
          :title="statusWords.hint || undefined"
        ><i aria-hidden="true" />{{ statusWords.label }}</span>
      </div>
      <dl class="metrics-grid">
        <div><dt>Elapsed</dt><dd>{{ elapsed }}</dd></div>
        <div><dt>Calls</dt><dd>{{ usage.callCount }}</dd></div>
        <div><dt>Tokens</dt><dd>{{ tokens }}</dd></div>
        <div><dt>Cost</dt><dd>${{ usage.costUsd.toFixed(4) }}</dd></div>
      </dl>
      <div class="stream-line">
        <span><i :class="`is-${connection}`" aria-hidden="true" />{{ connectionLabel }}</span>
        <span>seq {{ lastSequence }}</span>
        <span :class="{ 'has-drops': droppedFrames > 0 }">{{ droppedFrames }} dropped</span>
      </div>
      <code v-if="runId" class="run-id" :title="runId">{{ runId.slice(0, 8) }}</code>
    </div>

    <div class="control-actions">
      <button
        class="button button-primary"
        :class="{ 'is-armed': armed }"
        data-testid="launch-button"
        type="button"
        :disabled="!canLaunch"
        @click="emit('launch')"
      >
        <RotateCcw v-if="primaryLabel === 'Relaunch'" :size="16" aria-hidden="true" />
        <Play v-else :size="16" aria-hidden="true" />
        {{ primaryWord }}
      </button>
      <button class="button button-secondary" type="button" :disabled="!isActive || status === 'stopping'" @click="emit('cancel')">
        <Square :size="14" aria-hidden="true" />
        {{ status === 'stopping' ? 'Stopping…' : 'Cancel' }}
      </button>
      <div class="download-row">
        <button
          class="button button-quiet"
          type="button"
          :disabled="!runId || downloadStatus === 'pending'"
          @click="emit('download', logFormat)"
        >
          <LoaderCircle v-if="downloadStatus === 'pending'" class="download-spinner" :size="16" aria-hidden="true" />
          <Download v-else :size="16" aria-hidden="true" />
          {{ downloadStatus === 'pending' ? 'Preparing…' : 'Download logs' }}
        </button>
        <div class="segmented format-picker" role="group" aria-label="Log format">
          <button
            v-for="option in (['ndjson', 'zip'] as LogFormat[])"
            :key="option"
            type="button"
            :aria-pressed="logFormat === option"
            :title="option === 'zip' ? 'Download the run log as a ZIP archive' : 'Download the run log as newline-delimited JSON'"
            @click="logFormat = option"
          >
            {{ option.toUpperCase() }}
          </button>
        </div>
      </div>
      <p
        v-if="downloadMessage"
        class="download-feedback"
        :class="`is-${downloadStatus}`"
        :role="downloadStatus === 'error' ? 'alert' : 'status'"
      >
        {{ downloadMessage }}
      </p>
    </div>
  </section>
</template>

<style scoped>
/*
 * WHAT THIS BLOCK NO LONGER DECLARES, and where it went.
 *
 * `.segmented`, `.metrics-grid` and the panel-section / kicker / well / banner
 * treatments are now global classes in `studio.css` (SHELL-SCOPE.md §4). Two
 * of them had to move rather than merely wanting to: the segmented base was
 * declared HERE and only here, so Vue scoped it to `.segmented[data-v-...]`
 * and the application header - which spells the same class in both workspaces
 * - inherited no display, no background and no border, and rendered its
 * Build/Run pair as two NATIVE buttons. A base rule that reaches one component
 * is not a base rule.
 *
 * What stays is what is genuinely this panel's: sizes and states that no other
 * panel has an opinion about.
 */
.control-hint {
  margin: var(--space-3) 0 0;
  color: var(--text-muted);
  font-size: var(--fs-11);
  line-height: 1.45;
}

.status-panel { min-width: 0; }
/* `.panel-section` supplies the 16px inset and the hairline; this is the one
   thing that differs - a section holding a single control does not need a
   panel's full block padding. 12px, where it was 13. */
.compact-section { padding-block: var(--space-5); }
.control-label { display: block; margin-bottom: var(--space-3); }
textarea { display: block; width: 100%; min-height: 104px; resize: vertical; padding: var(--space-4); color: var(--text-body); font: var(--type-body); border-radius: var(--r-lg); outline: 0; }
textarea:focus { border-color: var(--on-accent-cyan); box-shadow: var(--glow-input); }
textarea:disabled { cursor: not-allowed; opacity: 0.64; }
.field-meta { display: block; margin-top: var(--space-2); color: var(--text-meta); font: var(--type-meta); text-align: right; }
/* The counter only raises its voice near the ceiling, because `maxlength` is a
   hard stop: past it the browser discards keystrokes with no feedback at all,
   and a counter that looked identical at 1,900 and at 2,000 would be the only
   warning the operator ever got. */
.field-meta.is-warn { color: var(--warn-text-strong); }
.read-only-well { display: flex; min-height: 40px; align-items: center; gap: var(--space-3); padding: 0 var(--space-4); color: var(--text-body); font-size: var(--fs-13); }
/* A drawn graph's name can be 80 characters; the well is 310px wide minus a
   rail. Ellipsis rather than wrap, so the panel's height does not change with
   the length of somebody's title. */
.read-only-well .workflow-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* `.read-only-well .version` was here and is gone with the element it styled -
   see the comment in the template. A rule for a class nothing renders is the
   thing that makes the next person believe the element still exists. */
.status-line { display: flex; align-items: center; justify-content: space-between; }
.status-line .control-label { margin: 0; }
.status-badge { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--text-muted); font: var(--type-meta); }
.status-badge i, .stream-line i { width: 7px; height: 7px; background: currentColor; border-radius: 50%; }
/*
 * A TONE, never a colour. `runStatusDisplay` names six semantic roles and
 * this is the only place in the shell that knows which token each one is
 * painted with - so a seventh status, or a re-hue, is one edit here rather
 * than a hunt through three panels for the word `cancelled`.
 */
.status-badge.is-tone-active { color: var(--on-accent-cyan); }
.status-badge.is-tone-attention { color: var(--warn-text-strong); }
.status-badge.is-tone-done { color: var(--on-accent-mint); }
.status-badge.is-tone-failed, .status-badge.is-tone-stopped { color: var(--err-text); }
.stream-line { display: flex; flex-wrap: wrap; gap: var(--space-3) var(--space-5); margin-top: var(--space-4); color: var(--text-meta); font: var(--type-meta); }
.stream-line span { display: inline-flex; align-items: center; gap: var(--space-2); }
.stream-line i.is-connected { color: var(--on-accent-mint); }
.stream-line i.is-connecting, .stream-line i.is-reconnecting { color: var(--warn-text-strong); }
.stream-line .has-drops { color: var(--err-text); }
.run-id { display: inline-block; margin-top: var(--space-3); padding: var(--space-1) var(--space-2); color: var(--text-muted); font: var(--type-meta); background: var(--surface-well); border-radius: var(--r-sm); }
.control-actions { display: grid; gap: var(--space-3); padding: var(--space-6); }
/* `.panel-banner` supplies the layout and the colour family; these three keep
   only what differs. The error banner is the one with a control in it, so it
   centres its row and pushes the dismiss to the end. */
.error-banner { align-items: center; justify-content: space-between; }
.error-banner .icon-button { flex: 0 0 auto; }
.transport-banner, .graph-banner { line-height: 1.45; }
.download-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--space-3); }
.format-picker { grid-template-columns: 1fr 1fr; }
.format-picker button { min-height: 34px; padding: 0 var(--space-4); font: var(--type-meta); }
.download-feedback { margin: 0; color: var(--text-muted); font-size: var(--fs-11); text-align: center; }
.download-feedback.is-success { color: var(--on-accent-mint); }
.download-feedback.is-error { color: var(--err-text); }
.download-spinner { animation: download-spin 0.8s linear infinite; }

@keyframes download-spin { to { transform: rotate(360deg); } }

/*
 * THE ONE ANIMATION IN THE SHELL WITH NO NAMED RULE, until now.
 *
 * The global blanket in `studio.css` sets `animation-duration: .01ms` and
 * `animation-iteration-count: 1`, which does not STOP a spinner - it freezes
 * it at whatever rotation .01ms of a 0.8s cycle reaches, so a reduced-motion
 * reader got a permanently crooked loader for as long as a log export takes to
 * prepare. `animation: none` leaves the icon upright, which is the same answer
 * `RunHistory.vue` and `SignInPanel.vue` already give for the identical icon.
 */
@media (prefers-reduced-motion: reduce) {
  .download-spinner { animation: none; }
}
</style>